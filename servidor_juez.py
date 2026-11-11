"""Interfaz web del juez: una página HTML simple, sin frameworks, con autorefresh.

Muestra el expediente completo (evidencia, riesgo colateral, hashes) para que el juez de
turno apruebe o rechace, y los reclamos pendientes con la propuesta de la plataforma.
Las decisiones se cargan en la Mesa; el hilo de despacho (despacho.py) recién firma y
envía cuando ve una decisión "aprobada". El juez nunca ve ni toca la clave de firma.
"""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

from evidencia import pedir
from mesa import Mesa


def _escape(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


class JuezHandler(BaseHTTPRequestHandler):
    mesa: Mesa
    base_simulador: str

    def log_message(self, formato, *args):
        pass

    def _responder_html(self, cuerpo: str, estado: int = 200) -> None:
        b = cuerpo.encode("utf-8")
        self.send_response(estado)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _redirigir(self, destino: str = "/") -> None:
        self.send_response(303)
        self.send_header("Location", destino)
        self.end_headers()

    def do_GET(self) -> None:
        partes = [p for p in urlparse(self.path).path.split("/") if p]
        if not partes:
            return self._responder_html(self._pagina())
        self._responder_html("No encontrado", 404)

    def do_POST(self) -> None:
        largo = int(self.headers.get("Content-Length", "0"))
        cuerpo = parse_qs(self.rfile.read(largo).decode("utf-8"))
        partes = [p for p in urlparse(self.path).path.split("/") if p]

        if len(partes) == 3 and partes[0] == "expedientes" and partes[2] == "decidir":
            aprobar = cuerpo.get("decision", [""])[0] == "aprobar"
            juez_id = self._juez_de_turno()
            self.mesa.decidir_expediente(partes[1], aprobar, juez_id, cuerpo.get("motivo", [""])[0])
            return self._redirigir()

        if len(partes) == 3 and partes[0] == "reclamos" and partes[2] == "decidir":
            aprobar = cuerpo.get("decision", [""])[0] == "aprobar"
            juez_id = self._juez_de_turno()
            self.mesa.decidir_reclamo(partes[1], aprobar, juez_id)
            return self._redirigir()

        self._responder_html("No encontrado", 404)

    def _juez_de_turno(self) -> str:
        try:
            de_turno = pedir(self.base_simulador, "/estado")["jueces_de_turno"]
            return de_turno[0] if de_turno else "sin-turno"
        except Exception:
            return "desconocido"

    def _pagina(self) -> str:
        try:
            estado = pedir(self.base_simulador, "/estado")
            minuto, juez_turno = estado["minuto_actual"], ", ".join(estado["jueces_de_turno"]) or "ninguno"
        except Exception:
            minuto, juez_turno = "?", "?"

        pendientes = self.mesa.pendientes_expedientes()
        decididos = sorted(
            [d for d in self.mesa.expedientes.values() if d.estado != "pendiente"],
            key=lambda d: d.decidido_min or 0, reverse=True,
        )[:15]
        reclamos_pend = self.mesa.pendientes_reclamos()

        filas_pendientes = "".join(self._fila_expediente(d) for d in pendientes) or \
            "<tr><td colspan=7 class='vacio'>Sin expedientes pendientes.</td></tr>"
        filas_decididos = "".join(self._fila_decidida(d) for d in decididos) or \
            "<tr><td colspan=4 class='vacio'>Todavía no se decidió ninguno.</td></tr>"
        filas_reclamos = "".join(self._fila_reclamo(d) for d in reclamos_pend) or \
            "<tr><td colspan=5 class='vacio'>Sin reclamos pendientes.</td></tr>"

        return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="4">
<title>Juez de turno — Desafío Fútbol</title>
<style>
 body{{font-family:system-ui,sans-serif;background:#111;color:#eee;margin:0;padding:24px}}
 h1{{margin:0 0 4px}} .sub{{color:#9a9;margin:0 0 20px}}
 table{{width:100%;border-collapse:collapse;margin-bottom:28px;font-size:14px}}
 th,td{{border:1px solid #333;padding:8px;text-align:left;vertical-align:top}}
 th{{background:#1b1b1b}} tr:nth-child(even){{background:#161616}}
 .vacio{{text-align:center;color:#777}}
 .riesgo{{color:#f55;font-weight:bold}} .ok{{color:#5f5}}
 .btn{{padding:5px 12px;border:none;border-radius:4px;cursor:pointer;font-weight:bold}}
 .aprobar{{background:#2a7}} .rechazar{{background:#a33;color:#fff}}
 form{{display:inline}}
 code{{color:#9cf}}
 .badge{{padding:2px 7px;border-radius:3px;font-size:12px}}
 .b-aprobado{{background:#163}} .b-rechazado{{background:#622}} .b-despachado{{background:#036}}
 .b-resuelto{{background:#036}}
</style></head><body>
<h1>⚖️ Interfaz del juez de turno</h1>
<p class="sub">Partido en el minuto {minuto} · Juez de turno ahora: <b>{_escape(juez_turno)}</b> ·
 se actualiza solo cada 4 s</p>

<h2>Expedientes pendientes de aprobación ({len(pendientes)})</h2>
<table>
<tr><th>Expediente</th><th>Stream</th><th>Evidencia</th><th>Riesgo colateral</th>
    <th>Bloqueo propuesto</th><th>Hash captura</th><th>Decisión</th></tr>
{filas_pendientes}
</table>

<h2>Reclamos pendientes ({len(reclamos_pend)})</h2>
<table>
<tr><th>Reclamo</th><th>Dominio</th><th>Mensaje</th><th>Propuesta de la plataforma</th><th>Decisión</th></tr>
{filas_reclamos}
</table>

<h2>Últimas decisiones</h2>
<table>
<tr><th>Expediente</th><th>Stream</th><th>Estado</th><th>Firmado por</th></tr>
{filas_decididos}
</table>
</body></html>"""

    def _fila_expediente(self, d) -> str:
        e = d.expediente
        riesgo = ('<span class="riesgo">SÍ — IP compartida con '
                 f'{len(e.dominios_en_la_ip) - 1} sitio(s) más</span>' if e.riesgo_colateral
                 else '<span class="ok">No</span>')
        return f"""<tr>
 <td><b>{_escape(e.id)}</b><br><small>min {e.minuto_deteccion:g}</small></td>
 <td>{_escape(e.host_stream)}<br><small>{_escape(e.ip_servidor)} · ASN {e.asn}</small></td>
 <td>marca <code>{_escape(e.marca_de_agua)}</code><br>coincide con <code>{_escape(e.prefijo_coincidente)}</code></td>
 <td>{riesgo}</td>
 <td><b>{e.tipo_recomendado}</b> → <code>{_escape(e.objetivo_recomendado)}</code><br>
     <small>vence min {e.vencimiento_propuesto}</small></td>
 <td><small>{_escape(e.hash_captura[:16])}…</small></td>
 <td>
  <form method="post" action="/expedientes/{e.id}/decidir">
   <button class="btn aprobar" name="decision" value="aprobar">Aprobar y firmar</button>
   <button class="btn rechazar" name="decision" value="rechazar">Rechazar</button>
  </form>
 </td>
</tr>"""

    def _fila_reclamo(self, d) -> str:
        r = d.reclamo
        return f"""<tr>
 <td>{_escape(r['id'])}<br><small>min {r['minuto']:.1f}</small></td>
 <td>{_escape(r['dominio'])}<br><small>vía {_escape(r['proveedor'])}</small></td>
 <td>{_escape(r['mensaje'])}</td>
 <td><b>{_escape(d.propuesta)}</b><br><small>{_escape(d.razon)}</small></td>
 <td>
  <form method="post" action="/reclamos/{r['id']}/decidir">
   <button class="btn aprobar" name="decision" value="aprobar">Aprobar propuesta</button>
   <button class="btn rechazar" name="decision" value="rechazar">Rechazar</button>
  </form>
 </td>
</tr>"""

    def _fila_decidida(self, d) -> str:
        e = d.expediente
        return (f"<tr><td>{_escape(e.id)}</td><td>{_escape(e.host_stream)}</td>"
                f"<td><span class='badge b-{d.estado}'>{_escape(d.estado)}</span></td>"
                f"<td>{_escape(d.decidido_por or '')}</td></tr>")


def iniciar_servidor_juez(mesa: Mesa, base_simulador: str, puerto: int) -> ThreadingHTTPServer:
    JuezHandler.mesa = mesa
    JuezHandler.base_simulador = base_simulador
    servidor = ThreadingHTTPServer(("0.0.0.0", puerto), JuezHandler)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return servidor
