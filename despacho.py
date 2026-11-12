"""Envía las órdenes aprobadas a cada proveedor que corresponda, con reintento y seguimiento."""
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from auditoria import RegistroAuditoria
from evidencia import Expediente, pedir
from firmas import RegistroJueces
from mesa import Mesa

# Estados en los que una orden ya no necesita seguimiento.
# "reemplazada": orden fallida que ya se reenvió con otro id; seguirla reintentando multiplicaría órdenes.
# "rechazada": el proveedor no la aceptó al enviarla (no existe en su registro).
ESTADOS_FINALES = ("vencida", "levantada", "reemplazada", "rechazada")
MAX_REINTENTOS = 5
INTERVALO_SEG = 0.25


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
    minuto_deteccion: Optional[float] = None


def tipo_para_proveedor(exp: Expediente, capacidades: List[str]) -> Optional[tuple]:
    """(tipo, objetivo) que se le pide a un proveedor según lo que acepta, o None si no puede.

    Si se recomienda IP y el proveedor solo bloquea por dominio, se le pide el dominio del
    stream: es el host del propio pirata, así que no agrega daño colateral y no deja a sus
    clientes sin cobertura. Nunca se hace al revés (dominio -> IP), porque eso sí lo agregaría.
    """
    if exp.tipo_recomendado in capacidades:
        return exp.tipo_recomendado, exp.objetivo_recomendado
    if exp.tipo_recomendado == "ip" and "dominio" in capacidades:
        return "dominio", exp.host_stream
    return None


class Despachador:
    """Único componente que llama a firmas.py: firma y envía solo lo que el juez aprobó."""

    def __init__(self, base: str, mesa: Mesa, jueces: RegistroJueces, auditoria: RegistroAuditoria):
        self.base = base
        self.mesa = mesa
        self.jueces = jueces
        self.auditoria = auditoria
        self.proveedores = pedir(base, "/proveedores")
        self.ordenes: Dict[str, EstadoOrden] = {}  # clave = f"{proveedor_id}:{orden_id}"
        self._seq = 0
        self._lock = threading.RLock()

    def _nuevo_orden_id(self, exp_id: str) -> str:
        with self._lock:
            self._seq += 1
            return f"ord-{exp_id}-{self._seq}"

    def lista_ordenes(self) -> List[EstadoOrden]:
        with self._lock:
            return list(self.ordenes.values())

    def despachar_expediente(self, exp: Expediente) -> None:
        """Envía la orden del expediente a cada proveedor con la capacidad necesaria."""
        self.auditoria.registrar("expediente_aprobado", expediente_id=exp.id, hash_expediente=exp.hash_expediente,
                                 tipo=exp.tipo_recomendado, objetivo=exp.objetivo_recomendado)
        for proveedor in self.proveedores:
            if any(o.expediente_id == exp.id and o.proveedor_id == proveedor["id"] for o in self.lista_ordenes()):
                continue  # ya enviada en un intento anterior que se cortó a mitad: no duplicar
            pedido = tipo_para_proveedor(exp, proveedor["capacidades"])
            if pedido is None:
                self.auditoria.registrar("proveedor_sin_capacidad", expediente_id=exp.id,
                                         proveedor=proveedor["id"], tipo=exp.tipo_recomendado)
                continue
            if pedido[0] != exp.tipo_recomendado:
                self.auditoria.registrar("bloqueo_adaptado_a_capacidad", expediente_id=exp.id,
                                         proveedor=proveedor["id"], tipo=pedido[0], objetivo=pedido[1],
                                         motivo="El proveedor no bloquea por IP: se pide el dominio del stream")
            self.enviar_orden(proveedor["id"], exp.id, pedido[0], pedido[1], exp.vencimiento_propuesto,
                              minuto_deteccion=exp.minuto_deteccion)
        self.mesa.marcar_despachado(exp.id)

    def enviar_orden(self, proveedor_id: str, exp_id: str, tipo: str, objetivo: str, vence_min: int,
                     intentos: int = 0, minuto_deteccion: Optional[float] = None) -> None:
        """Firma (con el juez de turno en este instante) y envía una orden a un proveedor."""
        orden_id = self._nuevo_orden_id(exp_id)
        orden_firmada = self.jueces.firmar_orden(orden_id, tipo, objetivo, vence_min)
        orden_firmada["expediente_id"] = exp_id
        resp = pedir(self.base, f"/proveedores/{proveedor_id}/ordenes", orden_firmada, "POST")
        estado = resp.get("estado") or "rechazada"
        with self._lock:
            self.ordenes[f"{proveedor_id}:{orden_id}"] = EstadoOrden(
                proveedor_id, orden_id, exp_id, tipo, objetivo, vence_min,
                estado=estado, intentos=intentos, minuto_deteccion=minuto_deteccion)
        self.mesa.registrar_orden_enviada(orden_firmada, proveedor_id, resp)
        self.auditoria.registrar("orden_enviada" if estado != "rechazada" else "orden_rechazada",
                                 expediente_id=exp_id, proveedor=proveedor_id, orden_id=orden_id, tipo=tipo,
                                 objetivo=objetivo, vence_min=vence_min, juzgado_id=orden_firmada["juzgado_id"],
                                 juez_id=orden_firmada["juez_id"], firma=orden_firmada["firma"], respuesta=resp)

    def _actualizar_estado(self, orden: EstadoOrden) -> None:
        """Consulta al proveedor el estado actual de la orden y audita cada cambio."""
        resp = pedir(self.base, f"/proveedores/{orden.proveedor_id}/ordenes/{orden.orden_id}")
        nuevo_estado = resp.get("estado") if isinstance(resp, dict) else None
        if not nuevo_estado or nuevo_estado == orden.estado:
            return
        orden.estado = nuevo_estado
        self.mesa.actualizar_orden(orden.proveedor_id, orden.orden_id, resp)
        datos = dict(proveedor=orden.proveedor_id, orden_id=orden.orden_id, expediente_id=orden.expediente_id,
                     tipo=orden.tipo, objetivo=orden.objetivo)
        if nuevo_estado == "aplicada":
            aplicada = resp.get("aplicada_min")
            demora = (round(aplicada - orden.minuto_deteccion, 2)
                      if aplicada is not None and orden.minuto_deteccion is not None else None)
            self.auditoria.registrar("orden_confirmada", aplicada_min=aplicada,
                                     minutos_desde_deteccion=demora, **datos)
        else:
            self.auditoria.registrar(f"orden_{nuevo_estado}", minuto=resp.get("finalizada_min"),
                                     motivo=resp.get("motivo"), **datos)

    def seguir_ordenes(self) -> None:
        """Sigue cada orden hasta su estado final y reenvía las fallidas.

        Las aplicadas solo se vuelven a consultar al llegar su vence_min, para confirmar el
        vencimiento automático. Una orden fallida cuyo vence_min ya pasó no se reintenta: el
        proveedor la rechazaría ("vence_min debe ser posterior al minuto actual").
        """
        minuto_actual = pedir(self.base, "/estado").get("minuto_actual", 0)
        for orden in self.lista_ordenes():
            if orden.estado in ESTADOS_FINALES or (orden.estado == "aplicada" and minuto_actual < orden.vence_min):
                continue
            self._actualizar_estado(orden)
            if orden.estado != "fallida" or orden.intentos >= MAX_REINTENTOS:
                continue
            if minuto_actual >= orden.vence_min:
                self.auditoria.registrar("reintento_descartado_por_vencimiento", proveedor=orden.proveedor_id,
                                         expediente_id=orden.expediente_id, vence_min=orden.vence_min,
                                         minuto_actual=minuto_actual)
                orden.estado = "reemplazada"
                continue
            self.auditoria.registrar("reintento_orden", proveedor=orden.proveedor_id, orden_id=orden.orden_id,
                                     expediente_id=orden.expediente_id, intento=orden.intentos + 1)
            self.enviar_orden(orden.proveedor_id, orden.expediente_id, orden.tipo, orden.objetivo,
                              orden.vence_min, intentos=orden.intentos + 1, minuto_deteccion=orden.minuto_deteccion)
            orden.estado = "reemplazada"  # la nueva hereda el conteo: una sola cadena de reintentos

    # Nombre histórico: se mantiene para no romper a quien lo llame.
    reintentar_fallidas = seguir_ordenes

    def levantar_orden(self, proveedor_id: str, orden_id: str, motivo: str) -> dict:
        """Firma el levantamiento con el juez de turno y lo envía al proveedor."""
        firma = self.jueces.firmar_levantamiento(orden_id, motivo)
        resp = pedir(self.base, f"/proveedores/{proveedor_id}/ordenes/{orden_id}/levantar", firma, "POST")
        with self._lock:
            local = self.ordenes.get(f"{proveedor_id}:{orden_id}")
        if local is not None and resp.get("estado") == "levantada":
            local.estado = "levantada"
            self.mesa.actualizar_orden(proveedor_id, orden_id, resp)
        self.auditoria.registrar("orden_levantada", proveedor=proveedor_id, orden_id=orden_id,
                                 juez_id=firma["juez_id"], firma=firma["firma"], motivo=motivo, respuesta=resp)
        return resp


def hilo_despacho(despachador: Despachador, mesa: Mesa, detener: threading.Event) -> None:
    while not detener.is_set():
        try:
            for decision in mesa.aprobados_sin_despachar():
                despachador.despachar_expediente(decision.expediente)
            despachador.seguir_ordenes()
        except Exception as error:  # un fallo puntual (p. ej. sin juez de turno) no debe matar el hilo
            print(f"[despacho] error, se reintenta: {error}")
        time.sleep(INTERVALO_SEG)
