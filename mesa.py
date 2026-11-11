"""Estado compartido entre el hilo de ingesta, el hilo de reclamos y el servidor del juez.

Todo pasa por acá para que un solo lock proteja la consistencia. El juez nunca firma nada
directamente: pide una decisión acá, y el hilo despachador recién firma y envía cuando ve
el estado "aprobado".
"""
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from evidencia import Expediente


@dataclass
class DecisionExpediente:
    expediente: Expediente
    estado: str = "pendiente"        # pendiente | aprobado | rechazado | despachado
    decidido_por: Optional[str] = None
    decidido_min: Optional[float] = None
    motivo_rechazo: Optional[str] = None


@dataclass
class DecisionReclamo:
    reclamo: dict
    propuesta: str                   # "levantar_y_precisar" | "levantar" | "mantener"
    razon: str
    orden_afectada: dict = field(default_factory=dict)
    estado: str = "pendiente"        # pendiente | aprobado | rechazado | resuelto
    decidido_por: Optional[str] = None


class Mesa:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.expedientes: Dict[str, DecisionExpediente] = {}
        self.reclamos: Dict[str, DecisionReclamo] = {}
        self.ordenes_enviadas: List[dict] = []   # vista de solo lectura para la pantalla de transparencia

    # --- expedientes -----------------------------------------------------------------

    def nuevo_expediente(self, exp: Expediente) -> None:
        with self.lock:
            self.expedientes[exp.id] = DecisionExpediente(expediente=exp)

    def decidir_expediente(self, exp_id: str, aprobar: bool, juez_id: str, motivo: str = "") -> bool:
        with self.lock:
            d = self.expedientes.get(exp_id)
            if d is None or d.estado != "pendiente":
                return False
            d.estado = "aprobado" if aprobar else "rechazado"
            d.decidido_por = juez_id
            d.decidido_min = time.time()
            d.motivo_rechazo = motivo if not aprobar else None
            return True

    def pendientes_expedientes(self) -> List[DecisionExpediente]:
        with self.lock:
            return [d for d in self.expedientes.values() if d.estado == "pendiente"]

    def aprobados_sin_despachar(self) -> List[DecisionExpediente]:
        with self.lock:
            return [d for d in self.expedientes.values() if d.estado == "aprobado"]

    def marcar_despachado(self, exp_id: str) -> None:
        with self.lock:
            self.expedientes[exp_id].estado = "despachado"

    # --- reclamos ----------------------------------------------------------------------

    def nuevo_reclamo(self, dr: DecisionReclamo) -> None:
        with self.lock:
            self.reclamos[dr.reclamo["id"]] = dr

    def decidir_reclamo(self, reclamo_id: str, aprobar: bool, juez_id: str) -> bool:
        with self.lock:
            d = self.reclamos.get(reclamo_id)
            if d is None or d.estado != "pendiente":
                return False
            d.estado = "aprobado" if aprobar else "rechazado"
            d.decidido_por = juez_id
            return True

    def pendientes_reclamos(self) -> List[DecisionReclamo]:
        with self.lock:
            return [d for d in self.reclamos.values() if d.estado == "pendiente"]

    def aprobados_sin_resolver_reclamo(self) -> List[DecisionReclamo]:
        with self.lock:
            return [d for d in self.reclamos.values() if d.estado == "aprobado"]

    def marcar_reclamo_resuelto(self, reclamo_id: str) -> None:
        with self.lock:
            self.reclamos[reclamo_id].estado = "resuelto"

    # --- transparencia -------------------------------------------------------------------

    def registrar_orden_enviada(self, orden: dict, proveedor_id: str, respuesta: dict) -> None:
        with self.lock:
            self.ordenes_enviadas.append({
                "proveedor": proveedor_id, "orden_id": orden["orden_id"], "expediente_id": orden["expediente_id"],
                "tipo": orden["tipo"], "objetivo": orden["objetivo"], "vence_min": orden["vence_min"],
                "juez_id": orden["juez_id"], "resultado": respuesta,
            })

    def vista_transparencia(self) -> List[dict]:
        with self.lock:
            # Vista pública: sin expediente completo ni evidencia, solo qué se bloqueó, por orden de
            # quién y hasta cuándo (lo que pide el README para el registro público de transparencia).
            return [{"tipo": o["tipo"], "objetivo": o["objetivo"], "vence_min": o["vence_min"],
                     "juez_id": o["juez_id"], "proveedor": o["proveedor"],
                     "estado": o["resultado"].get("estado", "enviada")} for o in self.ordenes_enviadas]
