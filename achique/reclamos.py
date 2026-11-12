"""Atiende los reclamos de sitios que quedaron bloqueados por error.

Verificación automática (lo que puede decidir la plataforma sola, sin inventar datos que
no tiene): si el dominio reclamante nunca fue el host_stream de ningún expediente nuestro,
es casi seguro daño colateral de un bloqueo por IP — se propone levantar esa orden y, si
el proveedor lo permite, reemplazarla por un bloqueo más preciso (por dominio, apuntando
al host pirata real). Si el dominio reclamante SÍ fue detectado como stream pirata, se
propone mantener el bloqueo, pero igual pasa por el juez: la plataforma nunca resuelve
un reclamo sin firma.

El mismo bloqueo está en varios proveedores: si el juez aprueba levantarlo, se levanta en
todos (el daño colateral no es solo de los clientes del proveedor que reclamó).
"""
import threading
import time
from typing import Set

from .despacho import INTERVALO_SEG, Despachador
from .evidencia import pedir
from .mesa import DecisionReclamo, Mesa


class GestorReclamos:
    """Lee reclamos nuevos, propone una resolución y ejecuta las que el juez aprobó."""

    def __init__(self, base: str, mesa: Mesa, despachador: Despachador, dominios_licenciatarios: Set[str] = frozenset()):
        self.base = base
        self.mesa = mesa
        self.despachador = despachador
        self.dominios_licenciatarios = set(dominios_licenciatarios)
        self.hosts_piratas_detectados: Set[str] = set()
        self._vistos: Set[str] = set()
        self._desde = -1.0

    def registrar_host_pirata(self, host: str) -> None:
        self.hosts_piratas_detectados.add(host)

    def _proponer(self, reclamo: dict) -> DecisionReclamo:
        dominio = reclamo["dominio"]
        orden_afectada = self._orden_que_bloquea(reclamo["proveedor"], dominio)
        es_bloqueo_por_ip = bool(orden_afectada) and orden_afectada.get("tipo") == "ip"
        if dominio in self.dominios_licenciatarios:
            propuesta = "levantar_y_precisar" if es_bloqueo_por_ip else "levantar"
            razon = "El reclamante es un licenciatario autorizado del partido: su retransmisión es legal."
        elif dominio in self.hosts_piratas_detectados:
            propuesta = "mantener"
            razon = "El dominio reclamante coincide con un stream pirata detectado por esta plataforma."
        elif not orden_afectada:
            propuesta = "mantener"
            razon = "No se encontró ninguna orden activa nuestra que afecte a ese dominio."
        else:
            propuesta = "levantar_y_precisar" if es_bloqueo_por_ip else "levantar"
            razon = ("Daño colateral: el dominio nunca fue detectado como señal pirata; "
                     "quedó bloqueado por compartir IP con el sitio real.")
        return DecisionReclamo(reclamo=reclamo, propuesta=propuesta, razon=razon,
                               orden_afectada=orden_afectada or {})

    def _orden_que_bloquea(self, proveedor_id: str, dominio: str) -> dict:
        ordenes = pedir(self.base, f"/proveedores/{proveedor_id}/ordenes")
        activas = [orden for orden in ordenes if orden["estado"] in ("recibida", "aplicada")]
        # El reclamo trae el dominio afectado; si el bloqueo activo es por IP, hay que
        # confirmar que esa IP sirve ese dominio (vía DNS pasivo) para no levantar la orden que no es.
        for orden in activas:
            if orden["tipo"] == "dominio" and orden["objetivo"] == dominio:
                return orden
            if orden["tipo"] == "ip":
                dns = pedir(self.base, f"/dns-pasivo?ip={orden['objetivo']}")
                if dominio in dns.get("dominios", []):
                    return orden
        return {}

    def revisar_nuevos(self) -> None:
        lote = pedir(self.base, f"/reclamos?desde={self._desde}")
        self._desde = lote["minuto_actual"]
        for reclamo in lote["reclamos"]:
            if reclamo["id"] in self._vistos:
                continue
            self._vistos.add(reclamo["id"])
            decision = self._proponer(reclamo)
            self.despachador.auditoria.registrar("reclamo_recibido", reclamo_id=reclamo["id"], dominio=reclamo["dominio"],
                                                 proveedor=reclamo["proveedor"], minuto=reclamo["minuto"],
                                                 propuesta=decision.propuesta, razon=decision.razon,
                                                 orden_afectada=decision.orden_afectada.get("orden_id"))
            self.mesa.nuevo_reclamo(decision)

    def _reemplazar_por_dominio(self, decision: DecisionReclamo, orden: dict, proveedor_id: str) -> None:
        # Reemplazo más preciso: de todos los dominios que compartían esa IP, solo
        # bloqueamos por dominio los que SÍ fueron detectados como señal pirata.
        dns = pedir(self.base, f"/dns-pasivo?ip={orden['objetivo']}")
        piratas_en_ip = set(dns.get("dominios", [])) & self.hosts_piratas_detectados
        if not piratas_en_ip:
            self.despachador.auditoria.registrar(
                "reclamo_sin_reemplazo", reclamo_id=decision.reclamo["id"], proveedor=proveedor_id,
                motivo="No se identificó el dominio pirata real que compartía la IP")
        for host_real in sorted(piratas_en_ip):
            self.despachador.enviar_orden(proveedor_id, orden.get("expediente_id", "reclamo"),
                                          "dominio", host_real, orden.get("vence_min", 105))

    def resolver_aprobados(self) -> None:
        for decision in self.mesa.aprobados_sin_resolver_reclamo():
            orden = decision.orden_afectada
            if orden and decision.propuesta in ("levantar", "levantar_y_precisar"):
                motivo = f"Reclamo {decision.reclamo['id']}: {decision.razon}"
                # El mismo bloqueo (tipo + objetivo) en todos los proveedores donde siga activo.
                # /proveedores/<id>/ordenes no incluye el id del proveedor (es implícito en la ruta):
                # el del reclamante sale del reclamo; los demás, de nuestro registro de órdenes.
                objetivos = {(decision.reclamo["proveedor"], orden["orden_id"])}
                objetivos |= {(o.proveedor_id, o.orden_id) for o in self.despachador.lista_ordenes()
                              if o.tipo == orden["tipo"] and o.objetivo == orden["objetivo"]
                              and o.estado in ("recibida", "aplicada")}
                for proveedor_id, orden_id in sorted(objetivos):
                    resp = self.despachador.levantar_orden(proveedor_id, orden_id, motivo=motivo)
                    if decision.propuesta == "levantar_y_precisar" and resp.get("estado") == "levantada":
                        self._reemplazar_por_dominio(decision, orden, proveedor_id)
            self.mesa.marcar_reclamo_resuelto(decision.reclamo["id"])
            self.despachador.auditoria.registrar("reclamo_resuelto", reclamo_id=decision.reclamo["id"],
                                                 propuesta=decision.propuesta, juez_id=decision.decidido_por)


def hilo_reclamos(gestor: GestorReclamos, detener: threading.Event) -> None:
    while not detener.is_set():
        try:
            gestor.revisar_nuevos()
            gestor.resolver_aprobados()
        except Exception as error:  # no matar el hilo por un fallo puntual
            print(f"[reclamos] error, se reintenta: {error}")
        time.sleep(INTERVALO_SEG * 2)
