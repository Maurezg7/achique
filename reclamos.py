"""Atiende los reclamos de sitios que quedaron bloqueados por error.

Verificación automática (lo que puede decidir la plataforma sola, sin inventar datos que
no tiene): si el dominio reclamante nunca fue el host_stream de ningún expediente nuestro,
es casi seguro daño colateral de un bloqueo por IP — se propone levantar esa orden y, si
el proveedor lo permite, reemplazarla por un bloqueo más preciso (por dominio, apuntando
al host pirata real). Si el dominio reclamante SÍ fue detectado como stream pirata, se
propone mantener el bloqueo, pero igual pasa por el juez: la plataforma nunca resuelve
un reclamo sin firma.
"""
import threading
import time
from typing import Dict, List, Set

from despacho import Despachador
from evidencia import pedir
from mesa import DecisionReclamo, Mesa


class GestorReclamos:
    def __init__(self, base: str, mesa: Mesa, despachador: Despachador):
        self.base = base
        self.mesa = mesa
        self.despachador = despachador
        self.hosts_piratas_detectados: Set[str] = set()
        self._vistos: Set[str] = set()
        self._desde = -1.0

    def registrar_host_pirata(self, host: str) -> None:
        self.hosts_piratas_detectados.add(host)

    def _proponer(self, reclamo: dict) -> DecisionReclamo:
        dominio = reclamo["dominio"]
        orden_afectada = self._orden_que_bloquea(reclamo["proveedor"], dominio)
        if dominio in self.hosts_piratas_detectados:
            propuesta, razon = "mantener", "El dominio reclamante coincide con un stream pirata detectado por esta plataforma."
        else:
            propuesta = "levantar_y_precisar" if orden_afectada and orden_afectada.get("tipo") == "ip" else "levantar"
            razon = ("Daño colateral: el dominio nunca fue detectado como señal pirata; "
                     "quedó bloqueado por compartir IP con el sitio real.")
        return DecisionReclamo(reclamo=reclamo, propuesta=propuesta, razon=razon,
                               orden_afectada=orden_afectada or {})

    def _orden_que_bloquea(self, proveedor_id: str, dominio: str) -> dict:
        ordenes = pedir(self.base, f"/proveedores/{proveedor_id}/ordenes")
        activas = [o for o in ordenes if o["estado"] in ("recibida", "aplicada")]
        # El reclamo trae el dominio afectado; si el bloqueo activo es por IP, hay que
        # confirmar que esa IP sirve ese dominio (vía DNS pasivo) para no levantar la orden que no es.
        for o in activas:
            if o["tipo"] == "dominio" and o["objetivo"] == dominio:
                return o
            if o["tipo"] == "ip":
                dns = pedir(self.base, f"/dns-pasivo?ip={o['objetivo']}")
                if dominio in dns.get("dominios", []):
                    return o
        return {}

    def revisar_nuevos(self) -> None:
        lote = pedir(self.base, f"/reclamos?desde={self._desde}")
        self._desde = lote["minuto_actual"]
        for reclamo in lote["reclamos"]:
            if reclamo["id"] in self._vistos:
                continue
            self._vistos.add(reclamo["id"])
            self.mesa.nuevo_reclamo(self._proponer(reclamo))

    def resolver_aprobados(self) -> None:
        for d in self.mesa.aprobados_sin_resolver_reclamo():
            orden = d.orden_afectada
            if orden and d.propuesta in ("levantar", "levantar_y_precisar"):
                # /proveedores/<id>/ordenes no incluye el id del proveedor en cada orden (es
                # implícito en la ruta): lo tomamos del reclamo, que es el mismo proveedor que consultamos.
                self.despachador.levantar_orden(d.reclamo["proveedor"], orden["orden_id"],
                                                motivo=f"Reclamo {d.reclamo['id']}: {d.razon}")
                if d.propuesta == "levantar_y_precisar":
                    # Reemplazo más preciso: de todos los dominios que compartían esa IP, solo
                    # bloqueamos por dominio los que SÍ fueron detectados como señal pirata.
                    dns = pedir(self.base, f"/dns-pasivo?ip={orden['objetivo']}")
                    piratas_en_ip = set(dns.get("dominios", [])) & self.hosts_piratas_detectados
                    if not piratas_en_ip:
                        self.despachador.auditoria.registrar(
                            "reclamo_sin_reemplazo", reclamo_id=d.reclamo["id"],
                            motivo="No se identificó el dominio pirata real que compartía la IP")
                    for host_real in piratas_en_ip:
                        self.despachador._enviar(d.reclamo["proveedor"], orden.get("expediente_id", "reclamo"),
                                                 "dominio", host_real, orden.get("vence_min", 105))
            self.mesa.marcar_reclamo_resuelto(d.reclamo["id"])


def hilo_reclamos(gestor: GestorReclamos, detener: threading.Event) -> None:
    while not detener.is_set():
        gestor.revisar_nuevos()
        gestor.resolver_aprobados()
        time.sleep(1)
