"""Estado compartido entre el hilo de ingesta, el hilo de reclamos y el servidor del juez.

Todo pasa por acá para que un solo lock proteja la consistencia. El juez nunca firma nada
directamente: pide una decisión acá, y el hilo despachador recién firma y envía cuando ve
el estado "aprobado".
"""
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .evidencia import Expediente


@dataclass
class DecisionExpediente:
    expediente: Expediente
    estado: str = "pendiente"        # pendiente | aprobado | rechazado | despachado
    decidido_por: Optional[str] = None
    decidido_min: Optional[float] = None   # timestamp de reloj (time.time()), usado para ordenar
    motivo_rechazo: Optional[str] = None
    creado_ts: float = field(default_factory=time.time)
    minuto_decision: Optional[float] = None  # minuto de partido en que decidió el juez


@dataclass
class DecisionReclamo:
    reclamo: dict
    propuesta: str                   # "levantar_y_precisar" | "levantar" | "mantener"
    razon: str
    orden_afectada: dict = field(default_factory=dict)
    estado: str = "pendiente"        # pendiente | aprobado | rechazado | resuelto
    decidido_por: Optional[str] = None


class Mesa:
    """Expedientes y reclamos con su estado de decisión, protegidos por un único lock."""

    def __init__(self, auditoria=None) -> None:
        self.lock = threading.RLock()
        self.auditoria = auditoria
        self.expedientes: Dict[str, DecisionExpediente] = {}
        self.reclamos: Dict[str, DecisionReclamo] = {}
        self.ordenes_enviadas: List[dict] = []   # vista de solo lectura para la pantalla de transparencia

    def _auditar(self, evento: str, **datos) -> None:
        if self.auditoria is not None:
            self.auditoria.registrar(evento, **datos)

    # --- expedientes -----------------------------------------------------------------

    def nuevo_expediente(self, exp: Expediente) -> None:
        with self.lock:
            self.expedientes[exp.id] = DecisionExpediente(expediente=exp)

    def expediente_por_servidor(self, host: str, ip: str) -> Optional[DecisionExpediente]:
        """Expediente ya abierto para el mismo servidor (host + IP): una re-detección no abre otro."""
        with self.lock:
            for decision in self.expedientes.values():
                if decision.expediente.host_stream == host and decision.expediente.ip_servidor == ip:
                    return decision
            return None

    def agregar_deteccion(self, exp_id: str, deteccion: dict, hash_deteccion: str) -> None:
        """Suma una re-detección como evidencia adicional (no altera el sello original)."""
        with self.lock:
            exp = self.expedientes[exp_id].expediente
            exp.detecciones_adicionales.append({"deteccion_id": deteccion["id"], "minuto": deteccion["minuto"],
                                                "hash_deteccion": hash_deteccion})

    def decidir_expediente(self, exp_id: str, aprobar: bool, juez_id: str, motivo: str = "",
                           minuto: Optional[float] = None) -> bool:
        with self.lock:
            decision = self.expedientes.get(exp_id)
            if decision is None or decision.estado != "pendiente":
                return False
            decision.estado = "aprobado" if aprobar else "rechazado"
            decision.decidido_por = juez_id
            decision.decidido_min = time.time()
            decision.minuto_decision = minuto
            decision.motivo_rechazo = motivo if not aprobar else None
            self._auditar("decision_juez", expediente_id=exp_id, decision=decision.estado, juez_id=juez_id,
                          minuto=minuto, motivo=motivo or None,
                          hash_expediente=decision.expediente.hash_expediente,
                          segundos_en_mesa=round(decision.decidido_min - decision.creado_ts, 2))
            return True

    def pendientes_expedientes(self) -> List[DecisionExpediente]:
        with self.lock:
            return [decision for decision in self.expedientes.values() if decision.estado == "pendiente"]

    def aprobados_sin_despachar(self) -> List[DecisionExpediente]:
        with self.lock:
            return [decision for decision in self.expedientes.values() if decision.estado == "aprobado"]

    def marcar_despachado(self, exp_id: str) -> None:
        with self.lock:
            self.expedientes[exp_id].estado = "despachado"

    # --- reclamos ----------------------------------------------------------------------

    def nuevo_reclamo(self, dr: DecisionReclamo) -> None:
        with self.lock:
            self.reclamos[dr.reclamo["id"]] = dr

    def decidir_reclamo(self, reclamo_id: str, aprobar: bool, juez_id: str) -> bool:
        with self.lock:
            decision = self.reclamos.get(reclamo_id)
            if decision is None or decision.estado != "pendiente":
                return False
            decision.estado = "aprobado" if aprobar else "rechazado"
            decision.decidido_por = juez_id
            self._auditar("decision_juez_reclamo", reclamo_id=reclamo_id, propuesta=decision.propuesta,
                          decision=decision.estado, juez_id=juez_id)
            return True

    def pendientes_reclamos(self) -> List[DecisionReclamo]:
        with self.lock:
            return [decision for decision in self.reclamos.values() if decision.estado == "pendiente"]

    def aprobados_sin_resolver_reclamo(self) -> List[DecisionReclamo]:
        with self.lock:
            return [decision for decision in self.reclamos.values() if decision.estado == "aprobado"]

    def marcar_reclamo_resuelto(self, reclamo_id: str) -> None:
        with self.lock:
            self.reclamos[reclamo_id].estado = "resuelto"

    # --- órdenes y transparencia -----------------------------------------------------------

    def registrar_orden_enviada(self, orden: dict, proveedor_id: str, respuesta: dict) -> None:
        with self.lock:
            self.ordenes_enviadas.append({
                "proveedor": proveedor_id, "orden_id": orden["orden_id"], "expediente_id": orden["expediente_id"],
                "tipo": orden["tipo"], "objetivo": orden["objetivo"], "vence_min": orden["vence_min"],
                "juzgado_id": orden.get("juzgado_id", ""), "juez_id": orden["juez_id"], "resultado": respuesta,
            })

    def actualizar_orden(self, proveedor_id: str, orden_id: str, vista: dict) -> None:
        """Guarda el último estado informado por el proveedor (aplicada, fallida, vencida...)."""
        with self.lock:
            for orden in self.ordenes_enviadas:
                if orden["proveedor"] == proveedor_id and orden["orden_id"] == orden_id:
                    orden["resultado"] = dict(orden["resultado"], **vista)

    def vista_transparencia(self) -> List[dict]:
        with self.lock:
            # Vista pública: sin expediente completo ni evidencia, solo qué se bloqueó, por orden de
            # quién y hasta cuándo (lo que pide el README para el registro público de transparencia).
            return [{"tipo": orden["tipo"], "objetivo": orden["objetivo"], "vence_min": orden["vence_min"],
                     "juzgado_id": orden["juzgado_id"], "juez_id": orden["juez_id"], "proveedor": orden["proveedor"],
                     "expediente_id": orden["expediente_id"],
                     "estado": orden["resultado"].get("estado", "rechazada" if "error" in orden["resultado"]
                                                      else "enviada"),
                     "desde_min": orden["resultado"].get("aplicada_min") or orden["resultado"].get("recibida_min"),
                     "hasta_min": orden["resultado"].get("finalizada_min")}
                    for orden in self.ordenes_enviadas]
