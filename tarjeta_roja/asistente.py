"""Asistente del juez: un agente local por reglas que vigila la plataforma y guía al juez en la Mesa.

Hace tres cosas, sin red, sin dependencias y sin modelos externos:
- **Vigila** la operación en vivo y levanta alertas: expedientes que esperan firma, órdenes rechazadas o
  fallidas, proveedores que no confirman, reclamos con daño colateral, bloqueos por IP cerca del final,
  cambio de turno próximo, falta de juez de turno o auditoría alterada.
- **Explica** cada expediente y cada reclamo en lenguaje claro: por qué IP o dominio, qué revisar.
- **Guía** al juez: indica el siguiente paso y qué elemento de la pantalla mirar.

El asistente recomienda; nunca decide ni firma. No escribe en la Mesa: solo lee su estado. Cada alerta de
atención o crítica que levanta queda en la auditoría (`asistente_alerta`), una sola vez por alerta.
"""
import threading
from typing import Dict, List, Optional

from .evidencia import dominio_base

# Minutos de partido que un expediente puede esperar firma antes de avisar (la velocidad se evalúa).
ESPERA_ATENCION_MIN = 1.0
ESPERA_CRITICA_MIN = 2.5
# Minutos desde que un proveedor aplicó el bloqueo para que los demás también confirmen.
CONFIRMACION_ATENCION_MIN = 1.5
AVISO_FIN_MIN = 10.0
AVISO_TURNO_MIN = 5.0
NIVELES = ("critico", "atencion", "info", "ok")


def _alerta(nivel: str, clave: str, titulo: str, detalle: str, foco: str = "") -> dict:
    return {"nivel": nivel, "clave": clave, "titulo": titulo, "detalle": detalle, "foco": foco}


def foco_tarjeta(item_id: str, dentro: str = "") -> str:
    """Selector CSS de la tarjeta (expediente o reclamo) en la Mesa, opcionalmente de un elemento dentro."""
    return f'[data-k="{item_id}"]' + (f" {dentro}" if dentro else "")


class Asistente:
    def __init__(self, clientes: Optional[Dict[str, int]] = None, nombres_jueces: Optional[Dict[str, str]] = None,
                 turnos: Optional[List[dict]] = None, auditoria=None) -> None:
        self.clientes = dict(clientes or {})
        self.nombres_jueces = dict(nombres_jueces or {})
        self.turnos = list(turnos or [])
        self.auditoria = auditoria
        self._lock = threading.Lock()
        self._auditadas: set = set()

    def _nombre(self, juez_id: Optional[str]) -> str:
        return self.nombres_jueces.get(juez_id or "", juez_id or "—")

    # --- vigilancia ----------------------------------------------------------------------

    def evaluar(self, est: dict, expedientes: list, reclamos: list, grupos: list, cadena_ok: bool = True) -> dict:
        """Estado del asistente: alertas ordenadas por gravedad y el siguiente paso sugerido.

        `est`: {minuto, fin, turno, finalizado} del simulador; `expedientes` y `reclamos`: decisiones de la
        Mesa; `grupos`: órdenes agrupadas por bloqueo (ver `JuezHandler._agrupar_ordenes`).
        """
        m, fin, finalizado = est["minuto"], est["fin"], est["finalizado"]
        pendientes = sorted((d for d in expedientes if d.estado == "pendiente"),
                            key=lambda d: (not d.expediente.riesgo_colateral, d.expediente.minuto_deteccion))
        reclamos_pend = [d for d in reclamos if d.estado == "pendiente"]
        alertas: List[dict] = []

        if not est["turno"]:
            alertas.append(_alerta("critico", "sin-turno", "No hay juez de turno",
                                   "Nadie puede decidir ni firmar hasta que entre el próximo juez.", ".banner"))
        if not cadena_ok:
            alertas.append(_alerta("critico", "cadena", "La auditoría no verifica",
                                   "Alguien editó o borró una línea del registro: revisá el archivo de auditoría.", ".chain"))

        for d in reclamos_pend:
            r = d.reclamo
            if d.propuesta.startswith("levantar"):
                alertas.append(_alerta("critico", f"reclamo-{r['id']}", f"Sitio legítimo bloqueado: {r['dominio']}",
                                       "Mientras no se resuelva el reclamo, ese sitio sigue sin servicio.",
                                       foco_tarjeta(r["id"])))
            else:
                alertas.append(_alerta("atencion", f"reclamo-{r['id']}", f"Reclamo de {r['dominio']} sin resolver",
                                       "La plataforma propone mantener el bloqueo: confirmalo o rechazalo.",
                                       foco_tarjeta(r["id"])))

        if not finalizado:
            for d in pendientes:
                e = d.expediente
                espera = m - e.minuto_deteccion
                if espera >= ESPERA_CRITICA_MIN:
                    nivel = "critico"
                elif espera >= ESPERA_ATENCION_MIN:
                    nivel = "atencion"
                else:
                    continue
                alertas.append(_alerta(nivel, f"espera-{nivel}-{e.id}", f"{e.host_stream} espera firma hace {espera:.1f}′",
                                       "Cada minuto sin bloqueo suma audiencia pirata. Revisalo y decidí.",
                                       foco_tarjeta(e.id)))

        for g in grupos:
            exp_id = g["expediente_id"]
            for prov, (estado, _tipo) in g["proveedores"].items():
                if estado == "rechazada":
                    alertas.append(_alerta("critico", f"rechazada-{exp_id}-{prov}", f"{prov} rechazó la orden de {exp_id}",
                                           "El proveedor no la aceptó: sus clientes siguen viendo el stream.", "aside"))
                elif estado == "fallida":
                    alertas.append(_alerta("atencion", f"fallida-{exp_id}-{prov}", f"{prov} no pudo aplicar {exp_id}",
                                           "El despacho la reintenta solo (sin duplicar órdenes).", "aside"))
                elif (estado in ("recibida", "enviada") and g["aplicada_min"] is not None
                      and m - g["aplicada_min"] >= CONFIRMACION_ATENCION_MIN):
                    faltan = f"{self.clientes.get(prov, 0):,}".replace(",", ".")
                    alertas.append(_alerta("atencion", f"sin-confirmar-{exp_id}-{prov}",
                                           f"{prov} todavía no confirmó {exp_id}",
                                           f"Los demás proveedores ya lo aplicaron; faltan {faltan} clientes.", "aside"))

        ip_activas = [g for g in grupos if any(t == "ip" and e == "aplicada" for e, t in g["proveedores"].values())]
        if ip_activas:
            vencidas = [g for g in ip_activas if m >= g["vence_min"]]
            if finalizado or vencidas:
                alertas.append(_alerta("critico", "ip-post-partido", "Bloqueos por IP activos después del vencimiento",
                                       f"{len(vencidas or ip_activas)} bloqueo(s) por IP siguen aplicados: deberían haber vencido.",
                                       "aside"))
            elif fin - m <= AVISO_FIN_MIN:
                alertas.append(_alerta("info", "ip-fin", f"{len(ip_activas)} bloqueo(s) por IP vencen solos en el min {fin:.0f}",
                                       "No hace falta levantarlos a mano: el proveedor los libera al terminar el partido.",
                                       "aside"))

        proximo = next((t for t in sorted(self.turnos, key=lambda t: t["desde_min"])
                        if 0 < t["desde_min"] - m <= AVISO_TURNO_MIN), None)
        if proximo and not finalizado:
            alertas.append(_alerta("info", f"turno-{proximo['juez_id']}",
                                   f"Cambio de turno en el min {proximo['desde_min']:g}: entra {self._nombre(proximo['juez_id'])}",
                                   "Lo pendiente pasa al juez entrante y el saliente ya no puede firmar.", ".duty"))

        alertas.sort(key=lambda a: NIVELES.index(a["nivel"]))
        if not any(a["nivel"] in ("critico", "atencion") for a in alertas):
            alertas.insert(0, _alerta("ok", "ok", "Todo en orden",
                                      "Sin demoras, sin órdenes rechazadas y la auditoría verifica.", ".kpis"))
        self._auditar(alertas, m)
        return {"minuto": m, "alertas": alertas, "siguiente": self.siguiente_paso(est, pendientes, reclamos_pend, grupos)}

    def _auditar(self, alertas: List[dict], minuto: float) -> None:
        if self.auditoria is None:
            return
        with self._lock:
            nuevas = [a for a in alertas if a["nivel"] in ("critico", "atencion") and a["clave"] not in self._auditadas]
            self._auditadas.update(a["clave"] for a in nuevas)
        for a in nuevas:
            self.auditoria.registrar("asistente_alerta", nivel=a["nivel"], clave=a["clave"], titulo=a["titulo"],
                                     minuto=minuto)

    # --- guía ----------------------------------------------------------------------------

    def siguiente_paso(self, est: dict, pendientes: list, reclamos_pend: list, grupos: list) -> dict:
        """Qué conviene hacer ahora y qué elemento de la pantalla mirar (selector CSS en `foco`)."""
        if not est["turno"]:
            return {"texto": "Esperá al juez de turno: sin turno nadie puede firmar.", "foco": ".duty"}
        urgentes = [d for d in reclamos_pend if d.propuesta.startswith("levantar")]
        if urgentes:
            r = urgentes[0].reclamo
            return {"texto": f"Resolvé el reclamo {r['id']}: {r['dominio']} es un sitio legítimo que quedó bloqueado.",
                    "foco": foco_tarjeta(r["id"], ".btn.aprobar")}
        if pendientes:
            e = pendientes[0].expediente
            extra = " Tiene riesgo colateral: confirmá que la orden sea por dominio." if e.riesgo_colateral else ""
            return {"texto": f"Revisá {e.id} ({e.host_stream}) y decidí.{extra}",
                    "foco": foco_tarjeta(e.id, ".btn.aprobar")}
        if reclamos_pend:
            r = reclamos_pend[0].reclamo
            return {"texto": f"Confirmá o rechazá el reclamo {r['id']} de {r['dominio']}.", "foco": foco_tarjeta(r["id"])}
        if any(e in ("fallida", "rechazada") for g in grupos for e, _ in g["proveedores"].values()):
            return {"texto": "Mirá las órdenes en proveedores: hay alguna fallida o rechazada.", "foco": "aside"}
        if est["finalizado"]:
            return {"texto": "Partido terminado. Verificá que los bloqueos por IP hayan vencido y revisá el registro público.",
                    "foco": ".pub"}
        return {"texto": "Mesa al día. Los expedientes nuevos aparecen solos y te aviso apenas llegue uno.", "foco": ".kpis"}

    # --- explicaciones -------------------------------------------------------------------

    @staticmethod
    def explicar_expediente(e) -> dict:
        base = dominio_base(e.host_stream)
        espejos = [d for d in e.dominios_en_la_ip if d != e.host_stream and dominio_base(d) == base]
        puntos = [f"La marca de agua <{e.marca_de_agua}> coincide con el prefijo {e.prefijo_coincidente} "
                  f"({e.origen_marca}): es la señal de este partido.",
                  f"El stream sale de {e.host_stream} en la IP {e.ip_servidor} (ASN {e.asn}, {e.organizacion or 'organización desconocida'})."]
        revisar = ["Que la marca de agua sea de este partido y no de un licenciatario en su propio dominio."]
        if e.tipo_recomendado == "dominio":
            if e.otros_sitios_en_la_ip:
                otros = ", ".join(e.otros_sitios_en_la_ip[:3]) + ("…" if len(e.otros_sitios_en_la_ip) > 3 else "")
                puntos.append(f"La IP también sirve a {len(e.otros_sitios_en_la_ip)} sitio(s) ajeno(s) ({otros}): "
                              "bloquearla los dejaría sin servicio.")
            else:
                puntos.append(f"No conviene bloquear la IP: {e.motivo_riesgo}")
            puntos.append(f"Por eso se propone bloquear solo el dominio {e.objetivo_recomendado}.")
            revisar.append("Que la orden sea por dominio y no por IP (evita el daño colateral).")
            resumen = "Bloquear por dominio: la IP es compartida y cortarla afectaría a terceros."
        else:
            puntos.append("La IP solo sirve a este sitio pirata" + (f" y a sus espejos ({', '.join(espejos)})" if espejos else "")
                          + ": bloquear la IP lo corta entero sin afectar a nadie más.")
            revisar.append("Que en la IP no aparezca ningún sitio de otro dueño.")
            resumen = "Bloquear la IP: solo sirve al sitio pirata" + (" y sus espejos." if espejos else ".")
        if e.detecciones_adicionales:
            puntos.append(f"Siguió transmitiendo: {len(e.detecciones_adicionales)} re-detección(es) del mismo servidor.")
        if e.promocion:
            puntos.append(f"Se promociona en {len(e.promocion)} publicación(es) en redes.")
        puntos.append(f"El bloqueo vence solo en el min {e.vencimiento_propuesto} (fin del partido).")
        revisar.append("Que el sello del expediente esté presente (la evidencia no se alteró).")
        return {"resumen": resumen, "puntos": puntos, "revisar": revisar,
                "sugerencia": "La evidencia es consistente con un stream pirata. La decisión es tuya."}

    @staticmethod
    def explicar_reclamo(d) -> dict:
        r, orden = d.reclamo, d.orden_afectada or {}
        objetivo = f"{orden.get('tipo', '')} {orden.get('objetivo', '')}".strip()
        if d.propuesta == "levantar_y_precisar":
            si_aprobas = (f"Se levanta el bloqueo {objetivo} en todos los proveedores y se reemplaza por un bloqueo del "
                          "dominio pirata real: el pirata sigue bloqueado y el reclamante vuelve a funcionar.")
        elif d.propuesta == "levantar":
            si_aprobas = f"Se levanta el bloqueo {objetivo} en todos los proveedores."
        else:
            si_aprobas = "El bloqueo se mantiene tal como está."
        return {"resumen": d.razon, "puntos": [f"Reclama {r['dominio']} vía {r['proveedor']}.", si_aprobas],
                "revisar": [], "sugerencia": "La plataforma propone; vos decidís."}
