"""Envía las órdenes aprobadas a cada proveedor que corresponda, con reintento y seguimiento."""
import threading
import time
from dataclasses import dataclass
from typing import Dict, List

from auditoria import RegistroAuditoria
from evidencia import Expediente, pedir
from firmas import RegistroJueces
from mesa import Mesa


@dataclass
class EstadoOrden:
    proveedor_id: str
    orden_id: str
    expediente_id: str
    tipo: str
    objetivo: str
    vence_min: int
    estado: str = "recibida"
    intentos: int = 0


class Despachador:
    def __init__(self, base: str, mesa: Mesa, jueces: RegistroJueces, auditoria: RegistroAuditoria):
        self.base = base
        self.mesa = mesa
        self.jueces = jueces
        self.auditoria = auditoria
        self.proveedores = pedir(base, "/proveedores")
        self.ordenes: Dict[str, EstadoOrden] = {}  # key = f"{proveedor_id}:{orden_id}"
        self._seq = 0
        self._lock = threading.Lock()

    def _nuevo_orden_id(self, exp_id: str) -> str:
        with self._lock:
            self._seq += 1
            return f"ord-{exp_id}-{self._seq}"

    def despachar_expediente(self, exp: Expediente) -> None:
        self.auditoria.registrar("expediente_aprobado", expediente_id=exp.id, **exp.to_dict())
        for prov in self.proveedores:
            if exp.tipo_recomendado not in prov["capacidades"]:
                self.auditoria.registrar("proveedor_sin_capacidad", expediente_id=exp.id,
                                         proveedor=prov["id"], tipo=exp.tipo_recomendado)
                continue
            self._enviar(prov["id"], exp.id, exp.tipo_recomendado, exp.objetivo_recomendado, exp.vencimiento_propuesto)
        self.mesa.marcar_despachado(exp.id)

    def _enviar(self, proveedor_id: str, exp_id: str, tipo: str, objetivo: str, vence_min: int) -> None:
        orden_id = self._nuevo_orden_id(exp_id)
        orden_firmada = self.jueces.firmar_orden(orden_id, tipo, objetivo, vence_min)
        orden_firmada["expediente_id"] = exp_id
        resp = pedir(self.base, f"/proveedores/{proveedor_id}/ordenes", orden_firmada, "POST")
        clave = f"{proveedor_id}:{orden_id}"
        self.ordenes[clave] = EstadoOrden(proveedor_id, orden_id, exp_id, tipo, objetivo, vence_min,
                                          estado=resp.get("estado", "error"))
        self.mesa.registrar_orden_enviada(orden_firmada, proveedor_id, resp)
        self.auditoria.registrar("orden_enviada", expediente_id=exp_id, proveedor=proveedor_id,
                                 orden_id=orden_id, tipo=tipo, objetivo=objetivo,
                                 juez_id=orden_firmada["juez_id"], respuesta=resp)

    def reintentar_fallidas(self) -> None:
        for clave, eo in list(self.ordenes.items()):
            if eo.estado in ("aplicada", "vencida", "levantada"):
                continue
            resp = pedir(self.base, f"/proveedores/{eo.proveedor_id}/ordenes/{eo.orden_id}")
            nuevo_estado = resp.get("estado") if isinstance(resp, dict) else None
            if nuevo_estado:
                eo.estado = nuevo_estado
            if eo.estado == "fallida" and eo.intentos < 3:
                eo.intentos += 1
                self.auditoria.registrar("reintento_orden", proveedor=eo.proveedor_id,
                                         expediente_id=eo.expediente_id, intento=eo.intentos)
                self._enviar(eo.proveedor_id, eo.expediente_id, eo.tipo, eo.objetivo, eo.vence_min)

    def levantar_orden(self, proveedor_id: str, orden_id: str, motivo: str) -> dict:
        firma = self.jueces.firmar_levantamiento(orden_id, motivo)
        resp = pedir(self.base, f"/proveedores/{proveedor_id}/ordenes/{orden_id}/levantar", firma, "POST")
        self.auditoria.registrar("orden_levantada", proveedor=proveedor_id, orden_id=orden_id,
                                 juez_id=firma["juez_id"], motivo=motivo, respuesta=resp)
        return resp


def hilo_despacho(despachador: Despachador, mesa: Mesa, detener: threading.Event) -> None:
    while not detener.is_set():
        for d in mesa.aprobados_sin_despachar():
            despachador.despachar_expediente(d.expediente)
        despachador.reintentar_fallidas()
        time.sleep(1)
