"""Firma de órdenes y lectura del registro de juzgados.

Las claves de demostración viven solo en datos/juzgados.json; esta plataforma nunca
las expone por HTTP ni las loguea. En producción esto sería una firma digital real
del juez, no un HMAC compartido.
"""
import hashlib
import hmac
import json
from pathlib import Path
from typing import Dict, List, Tuple

from .evidencia import pedir


def firmar(clave: str, mensaje: str) -> str:
    """HMAC-SHA256 en hexadecimal, según el esquema de firmas del README oficial."""
    return hmac.new(clave.encode("utf-8"), mensaje.encode("utf-8"), hashlib.sha256).hexdigest()


def mensaje_orden(orden_id: str, tipo: str, objetivo: str, vence_min: int, juez_id: str) -> str:
    """Mensaje canónico que se firma para una orden de bloqueo."""
    return f"{orden_id}|{tipo}|{objetivo}|{vence_min}|{juez_id}"


def mensaje_levantar(orden_id: str, juez_id: str) -> str:
    """Mensaje canónico que se firma para levantar una orden."""
    return f"LEVANTAR|{orden_id}|{juez_id}"


class FueraDeTurno(RuntimeError):
    """El juez que aprobó no está de turno (o no existe): no se firma en su nombre."""


class RegistroJueces:
    """Carga datos/juzgados.json y firma en nombre del juez que aprobó, si está de turno."""

    def __init__(self, base: str, juzgados_path: Path):
        self.base = base
        registro = json.loads(juzgados_path.read_text(encoding="utf-8"))
        self.jueces: Dict[str, dict] = {}       # juez_id -> {id, nombre, clave_firma_demo}
        self.juzgado_de: Dict[str, dict] = {}   # juez_id -> {id, nombre, jurisdiccion}
        for juzgado in registro["juzgados"]:
            for juez in juzgado["jueces"]:
                self.jueces[juez["id"]] = juez
                self.juzgado_de[juez["id"]] = juzgado

    def jueces_de_turno(self) -> List[str]:
        """Jueces de turno en este instante según el simulador. Nunca se cachea: el turno cambia a mitad de partido."""
        return list(pedir(self.base, "/estado").get("jueces_de_turno", []))

    def _firmante(self, juez_id: str) -> Tuple[dict, dict]:
        """Clave y juzgado del juez que aprobó, solo si sigue de turno en el instante de firmar.

        La plataforma firma únicamente en nombre del juez que inició sesión y aprobó; si ese juez
        ya no está de turno, nadie firma por él (el expediente vuelve a la Mesa del juez entrante).
        """
        if juez_id not in self.jueces:
            raise FueraDeTurno(f"Juez desconocido: {juez_id}")
        if juez_id not in self.jueces_de_turno():
            raise FueraDeTurno(f"{juez_id} no está de turno: no se firma en su nombre")
        return self.jueces[juez_id], self.juzgado_de[juez_id]

    def firmar_orden(self, orden_id: str, tipo: str, objetivo: str, vence_min: int, juez_id: str) -> dict:
        """Arma el cuerpo de la orden firmado por el juez que la aprobó (que debe estar de turno)."""
        juez, juzgado = self._firmante(juez_id)
        msg = mensaje_orden(orden_id, tipo, objetivo, vence_min, juez_id)
        return {
            "orden_id": orden_id, "tipo": tipo, "objetivo": objetivo, "vence_min": vence_min,
            "juzgado_id": juzgado["id"], "juez_id": juez_id, "firma": firmar(juez["clave_firma_demo"], msg),
        }

    def firmar_levantamiento(self, orden_id: str, motivo: str, juez_id: str) -> dict:
        """Arma el cuerpo de levantamiento firmado por el juez que lo aprobó (que debe estar de turno)."""
        juez, _ = self._firmante(juez_id)
        msg = mensaje_levantar(orden_id, juez_id)
        return {"juez_id": juez_id, "firma": firmar(juez["clave_firma_demo"], msg), "motivo": motivo}
