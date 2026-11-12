"""Interfaz web del juez y registro público de transparencia, sin frameworks.

- `/login`        Ingreso del juez con usuario y contraseña (ver sesiones.py). La Mesa, `/fragmento` y
                  `/asistente.json` exigen sesión; las decisiones, además, que el juez esté de turno.
- `/`             Mesa del juez: una sola página en vivo (pide `/fragmento` cada 1,5 s y lo reemplaza
                  en su lugar). Muestra el expediente completo (evidencia, riesgo colateral, hashes) para
                  que el juez de turno apruebe o rechace, y los reclamos con la propuesta de la plataforma.
- `/transparencia` Registro público de solo lectura: qué se bloqueó, cuándo, por orden de quién y hasta
                  cuándo. Sin evidencia interna. También en JSON: `/transparencia.json`.
- `/asistente.json` Estado del asistente del juez (alertas y siguiente paso), ver `asistente.py`.
- `/static/…`     Página base, estilos, script y logos de `web/`.

Las decisiones se cargan en la Mesa; el hilo de despacho (despacho.py) recién firma y envía cuando ve
una decisión "aprobada". El juez nunca ve ni toca la clave de firma.
"""
import json
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from .asistente import Asistente
from .auditoria import verificar_cadena
from .evidencia import pedir
from . import LEMA, NOMBRE
from .mesa import Mesa
from .sesiones import COOKIE, Sesiones, Usuarios

ICONO_RED = {"x": "𝕏", "telegram": "✈", "discord": "◆"}
# Qué estado mostrar por proveedor cuando tiene varias órdenes del mismo bloqueo (reintentos, reemplazos).
RANGO_ESTADO = {"aplicada": 6, "recibida": 5, "enviada": 5, "vencida": 4, "levantada": 3, "fallida": 2,
                "rechazada": 1, "reemplazada": 0}


LIGA = "Liga de Fútbol Argentino"   # liga ficticia de la demo (alusión, no es la AFA)
# Página, estilos, script y logos viven en web/ (servidos en /static/). Los logos también se incrustan
# en el fragmento en vivo: logo.svg (la "A" de Achique dentro del arco) y liga.svg (escudo ficticio).
WEB = Path(__file__).resolve().parent / "web"
ESTATICOS = {"estilos.css": "text/css; charset=utf-8", "app.js": "application/javascript; charset=utf-8",
             "logo.svg": "image/svg+xml", "liga.svg": "image/svg+xml"}
PAGINA_BASE = (WEB / "index.html").read_text(encoding="utf-8")
LOGO_APP = (WEB / "logo.svg").read_text(encoding="utf-8")
ESCUDO_LIGA = (WEB / "liga.svg").read_text(encoding="utf-8")

# Marcador ilustrativo para la demo (minutos de simulación). No interviene en ninguna decisión ni orden.
GOLES_ILUSTRATIVOS = ((23, "local"), (71, "visitante"), (92, "local"))
FIN_PRIMER_TIEMPO, FIN_ENTRETIEMPO = 45.0, 60.0


def minuto_tv(m: float) -> str:
    """Minuto como en la transmisión: 1T 0-45', entretiempo, 2T 46-90' (el simulador cuenta 105 con el ET)."""
    if m < FIN_PRIMER_TIEMPO:
        return f"{int(m) + 1}′"
    if m < FIN_ENTRETIEMPO:
        return "ET"
    return f"{min(90, int(m - (FIN_ENTRETIEMPO - FIN_PRIMER_TIEMPO)) + 1)}′"


def etapa(m: float, finalizado: bool) -> str:
    if finalizado:
        return "FINAL"
    return "1T" if m < FIN_PRIMER_TIEMPO else ("ENTRETIEMPO" if m < FIN_ENTRETIEMPO else "2T")


def _escape(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def _corto(h: str, n: int = 12) -> str:
    return f"{h[:n]}…{h[-6:]}" if h and len(h) > n + 6 else (h or "")


class JuezHandler(BaseHTTPRequestHandler):
    mesa: Mesa
    base_simulador: str
    proveedores: List[dict] = []
    nombres_jueces: Dict[str, str] = {}
    local, visitante = "Azul Juniors", "Rojo Plate"
    turnos: List[dict] = []
    asistente: Asistente = Asistente()
    usuarios: Optional[Usuarios] = None
    sesiones: Sesiones = Sesiones()

    def log_message(self, formato, *args):
        pass

    # --- respuestas ----------------------------------------------------------------------

    def _responder(self, cuerpo: str, estado: int = 200, tipo: str = "text/html; charset=utf-8") -> None:
        b = cuerpo.encode("utf-8")
        self.send_response(estado)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _redirigir(self, destino: str = "/") -> None:
        if self.headers.get("X-Requested-With") == "fetch":
            self.send_response(204)  # decisión desde la página en vivo: no hay que navegar a ningún lado
            return self.end_headers()
        self.send_response(303)
        self.send_header("Location", destino)
        self.end_headers()

    # --- sesión del juez ---------------------------------------------------------------------

    def _token(self) -> Optional[str]:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            return None
        m = cookie.get(COOKIE)
        return m.value if m else None

    def _juez_sesion(self) -> Optional[str]:
        return self.sesiones.juez(self._token())

    def _auditar(self, evento: str, **datos) -> None:
        auditoria = getattr(self.mesa, "auditoria", None)
        if auditoria is not None:
            auditoria.registrar(evento, **datos)

    def _ir(self, destino: str, cookie: Optional[str] = None) -> None:
        self.send_response(303)
        self.send_header("Location", destino)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _login(self, cuerpo: dict) -> None:
        origen = self.client_address[0]
        usuario = cuerpo.get("usuario", [""])[0].strip()
        clave = cuerpo.get("clave", [""])[0]
        conocido = usuario if self.usuarios and usuario in self.usuarios.por_usuario else "(desconocido)"
        if self.sesiones.bloqueado(origen):
            self._auditar("ingreso_bloqueado", usuario=conocido, origen=origen)
            return self._ir("/login?error=bloqueado")
        juez = self.usuarios.verificar(usuario, clave) if self.usuarios else None
        if juez is None:
            self.sesiones.registrar_fallo(origen)
            self._auditar("ingreso_fallido", usuario=conocido, origen=origen)
            return self._ir("/login?error=1")
        self.sesiones.limpiar_fallos(origen)
        token = self.sesiones.crear(juez)
        self._auditar("ingreso_juez", usuario=usuario, juez_id=juez, origen=origen)
        return self._ir("/", f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; "
                             f"Max-Age={int(self.sesiones.duracion_seg)}")

    def _pagina_login(self, query: dict) -> str:
        error = query.get("error", [""])[0]
        aviso = {"1": "Usuario o contraseña incorrectos.",
                 "bloqueado": "Demasiados intentos fallidos: esperá un minuto y probá de nuevo."}.get(error, "")
        if query.get("salio"):
            aviso = "Sesión cerrada."
        aviso_html = f"<p class='login-aviso{' error' if error else ''}'>{_escape(aviso)}</p>" if aviso else ""
        return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{NOMBRE} · Ingreso del juez</title>
<link rel="icon" href="/static/logo.svg" type="image/svg+xml"><link rel="stylesheet" href="/static/estilos.css">
</head><body class="login-body"><form class="login" method="post" action="/login">
<div class="login-logo">{LOGO_APP}</div><h1>{NOMBRE}</h1><p class="login-sub">Mesa del juez · ingreso</p>{aviso_html}
<label>Usuario<input name="usuario" autocomplete="username" autocapitalize="none" spellcheck="false" required autofocus></label>
<label>Contraseña<input name="clave" type="password" autocomplete="current-password" required></label>
<button class="btn aprobar" type="submit">Ingresar</button>
<small>Cada juez ve y firma solo lo que le toca mientras está de turno.<br>
<a href="/transparencia">Registro público de bloqueos ↗</a></small></form></body></html>"""

    # --- rutas -------------------------------------------------------------------------------

    def do_GET(self) -> None:
        url = urlparse(self.path)
        partes = [p for p in url.path.split("/") if p]
        if partes == ["login"]:
            return self._responder(self._pagina_login(parse_qs(url.query)))
        if len(partes) == 2 and partes[0] == "static" and partes[1] in ESTATICOS:  # lista blanca: sin rutas arbitrarias
            return self._responder((WEB / partes[1]).read_text(encoding="utf-8"), tipo=ESTATICOS[partes[1]])
        if partes == ["transparencia"]:
            return self._responder(PAGINA_BASE.replace("__TITULO__", "Registro público de bloqueos")
                                   .replace("__FRAG__", "/transparencia/fragmento"))
        if partes == ["transparencia", "fragmento"]:
            return self._responder(self._fragmento_transparencia())
        if partes == ["transparencia.json"]:
            return self._responder(json.dumps(self.mesa.vista_transparencia(), ensure_ascii=False, indent=2),
                                   tipo="application/json; charset=utf-8")
        # Desde acá, solo con sesión de juez (la Mesa muestra evidencia interna).
        juez = self._juez_sesion()
        if not partes:
            if juez is None:
                return self._ir("/login")
            return self._responder(PAGINA_BASE.replace("__TITULO__", "Mesa del juez").replace("__FRAG__", "/fragmento"))
        if partes in (["fragmento"], ["asistente.json"]) and juez is None:
            return self._responder("Iniciá sesión", 401, "text/plain; charset=utf-8")
        if partes == ["fragmento"]:
            return self._responder(self._fragmento(juez))
        if partes == ["asistente.json"]:
            return self._responder(json.dumps(self._evaluar_asistente(), ensure_ascii=False, indent=2),
                                   tipo="application/json; charset=utf-8")
        self._responder("No encontrado", 404)

    def do_POST(self) -> None:
        largo = int(self.headers.get("Content-Length", "0"))
        cuerpo = parse_qs(self.rfile.read(largo).decode("utf-8"))
        partes = [p for p in urlparse(self.path).path.split("/") if p]
        if partes == ["login"]:
            return self._login(cuerpo)
        if partes == ["logout"]:
            juez = self.sesiones.cerrar(self._token())
            if juez:
                self._auditar("salida_juez", juez_id=juez)
            return self._ir("/login?salio=1", f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict")
        if len(partes) == 3 and partes[0] in ("expedientes", "reclamos") and partes[2] == "decidir":
            juez_id = self._juez_sesion()
            if juez_id is None:
                return self._responder("Iniciá sesión", 401, "text/plain; charset=utf-8")
            de_turno, minuto = self._turno()
            if juez_id not in de_turno:
                # El saliente (o cualquiera fuera de turno) ya no puede decidir ni firmar.
                self._auditar("decision_denegada", juez_id=juez_id, objeto=f"{partes[0]}/{partes[1]}",
                              motivo="fuera de turno", minuto=minuto)
                return self._responder("No estás de turno: no podés decidir ni firmar.", 403,
                                       "text/plain; charset=utf-8")
            aprobar = cuerpo.get("decision", [""])[0] == "aprobar"
            if aprobar and cuerpo.get("confirmado", [""])[0] != "si":
                # Aprobar exige la confirmación explícita del juez ("¿Seguro que querés bloquear?").
                return self._responder("Falta tu confirmación: no se aprobó ni se firmó nada.", 400,
                                       "text/plain; charset=utf-8")
            if partes[0] == "expedientes":
                self.mesa.decidir_expediente(partes[1], aprobar, juez_id, cuerpo.get("motivo", [""])[0], minuto)
            else:
                self.mesa.decidir_reclamo(partes[1], aprobar, juez_id)
            return self._redirigir()
        self._responder("No encontrado", 404)

    def _turno(self) -> tuple:
        try:
            estado = pedir(self.base_simulador, "/estado")
            return list(estado.get("jueces_de_turno", [])), estado.get("minuto_actual")
        except Exception:
            return [], None

    @classmethod
    def _estado_simulador(cls) -> dict:
        try:
            estado = pedir(cls.base_simulador, "/estado")
            return {"minuto": float(estado["minuto_actual"]), "fin": float(estado.get("fin_min", 105)),
                    "turno": estado["jueces_de_turno"], "finalizado": bool(estado.get("finalizado"))}
        except Exception:
            return {"minuto": 0.0, "fin": 105.0, "turno": [], "finalizado": False}

    @classmethod
    def _nombre_juez(cls, juez_id: Optional[str]) -> str:
        return cls.nombres_jueces.get(juez_id or "", juez_id or "—")

    # --- datos derivados -------------------------------------------------------------------

    @staticmethod
    def _agrupar_ordenes(ordenes: list) -> list:
        """Agrupa las órdenes por bloqueo (expediente), más reciente primero.

        Un mismo bloqueo se envía a cada proveedor en el tipo que acepta (y se reintenta si falla):
        se muestra una sola línea con el estado más relevante por proveedor, en vez de una por orden.
        """
        grupos: dict = {}
        for o in ordenes:
            g = grupos.setdefault(o["expediente_id"], {"expediente_id": o["expediente_id"], "juez_id": o["juez_id"],
                                                       "juzgado_id": o.get("juzgado_id", ""), "vence_min": o["vence_min"],
                                                       "objetivos": [], "proveedores": {}, "aplicada_min": None})
            if (o["tipo"], o["objetivo"]) not in g["objetivos"]:
                g["objetivos"].append((o["tipo"], o["objetivo"]))
            res = o.get("resultado", {})
            estado = res.get("estado") or ("rechazada" if "error" in res else "enviada")
            anterior = g["proveedores"].get(o["proveedor"], ("", ""))[0]
            if RANGO_ESTADO.get(estado, 0) >= RANGO_ESTADO.get(anterior, -1):
                g["proveedores"][o["proveedor"]] = (estado, o["tipo"])
            if res.get("aplicada_min") is not None:
                g["aplicada_min"] = min(x for x in (g["aplicada_min"], res["aplicada_min"]) if x is not None)
        return list(reversed(list(grupos.values())))

    @staticmethod
    def _chips(g: dict) -> str:
        mixto = len({t for t, _ in g["objetivos"]}) > 1
        return "".join(f"<span class='chip c-{_escape(est)}' title='{_escape(prov)}: {_escape(est)} ({_escape(tipo)})'>"
                       f"{_escape(prov)}{(' · ' + _escape(tipo)) if mixto else ''}<i>{_escape(est)}</i></span>"
                       for prov, (est, tipo) in g["proveedores"].items())

    @staticmethod
    def _objetivos(g: dict) -> str:
        return " ".join(f"<span class='tipo t-{_escape(t)}'>{_escape(t)}</span> <code>{_escape(obj)}</code>"
                        for t, obj in g["objetivos"])

    @classmethod
    def _clientes(cls) -> Dict[str, int]:
        return {p["id"]: p.get("clientes", 0) for p in cls.proveedores}

    @classmethod
    def _cobertura(cls, grupo: dict) -> float:
        clientes = cls._clientes()
        total = sum(clientes.values()) or 1
        return 100.0 * sum(clientes.get(p, 0) for p, (e, _) in grupo["proveedores"].items() if e == "aplicada") / total

    # --- partido: marcador, línea de tiempo y relato ------------------------------------------

    def _marcador(self, est: dict, titulo: str, subtitulo: str, derecha: str) -> str:
        m, fin = est["minuto"], est["fin"]
        goles = [g for g in GOLES_ILUSTRATIVOS if g[0] <= m]
        gl, gv = sum(1 for g in goles if g[1] == "local"), sum(1 for g in goles if g[1] == "visitante")
        festejo = next((g[1] for g in goles if m - g[0] < 2.5), None)
        festejo_html = (f"<div class='festejo f-{festejo}' data-k='gol-{festejo}-{len(goles)}'>¡GOL de {_escape(self.local if festejo == 'local' else self.visitante)}!</div>"
                        if festejo and not est["finalizado"] else "")
        vivo = "off" if est["finalizado"] else ""
        return f"""
<header class="top">
 <div class="brand"><div class="logo">{LOGO_APP}</div><div><b>{NOMBRE}</b>
   <span class="seccion">{_escape(titulo)}</span><small>{_escape(subtitulo)}</small></div></div>
 <div class="centro">
 <div class="torneo"><span class="liga">{ESCUDO_LIGA}</span><b>{_escape(LIGA.upper())}</b><i>Torneo 2026 · Fecha 12 · ficticio</i></div>
 <div class="marcador{' gol' if festejo else ''}">
  <div class="equipo local"><div class="escudo azul"><span>AJ</span></div><b>{_escape(self.local)}</b></div>
  <div class="tanteador"><span>{gl}</span><i>-</i><span>{gv}</span></div>
  <div class="equipo visit"><b>{_escape(self.visitante)}</b><div class="escudo rojo"><span>RP</span></div></div>
  <div class="reloj"><span class="live {vivo}"><i></i>{etapa(m, est['finalizado'])}</span>
   <b>{minuto_tv(min(m, fin)) if not est['finalizado'] else '90′'}</b><small>sim {min(m, fin):.0f}/{fin:.0f}</small></div>
  {festejo_html}
 </div></div>
 <div class="duty">{derecha}</div>
</header>"""

    def _linea_de_tiempo(self, est: dict, todos: list) -> str:
        m, fin = est["minuto"], est["fin"] or 105.0
        pct = lambda x: max(0.0, min(100.0, x / fin * 100))  # noqa: E731
        marcas = "".join(f"<span class='mk det{' riesgo' if d.expediente.riesgo_colateral else ''}' style='left:{pct(d.expediente.minuto_deteccion):.2f}%'"
                         f" title='{_escape(minuto_tv(d.expediente.minuto_deteccion))} {_escape(d.expediente.host_stream)}'></span>"
                         for d in todos)
        marcas += "".join(f"<span class='mk gol' style='left:{pct(g[0]):.2f}%'>⚽</span>" for g in GOLES_ILUSTRATIVOS if g[0] <= m)
        marcas += "".join(f"<span class='mk turno' style='left:{pct(t['desde_min']):.2f}%' title='Turno: "
                          f"{_escape(self._nombre_juez(t['juez_id']))}'>⚖</span>"
                          for t in self.turnos if 0 < t["desde_min"] <= min(m, fin))
        return f"""
<div class="timeline"><div class="tl-track">
 <div class="tl-seg et" style="left:{pct(FIN_PRIMER_TIEMPO):.2f}%;width:{pct(FIN_ENTRETIEMPO) - pct(FIN_PRIMER_TIEMPO):.2f}%"></div>
 <div class="tl-prog" style="width:{pct(m):.2f}%"></div>{marcas}
 <span class="tl-now" style="left:{pct(m):.2f}%"></span></div>
 <div class="tl-labels"><span style="left:0">0′</span><span style="left:{pct(FIN_PRIMER_TIEMPO / 2):.1f}%">1er tiempo</span>
 <span style="left:{pct((FIN_PRIMER_TIEMPO + FIN_ENTRETIEMPO) / 2):.1f}%">ET</span>
 <span style="left:{pct((FIN_ENTRETIEMPO + fin) / 2):.1f}%">2do tiempo</span><span style="left:100%">90′</span></div>
 <div class="tl-ley"><i class="l-det"></i>stream pirata <i class="l-riesgo"></i>con riesgo colateral <b>⚽</b> gol (ilustrativo) <b>⚖</b> cambio de turno</div>
</div>"""

    def _relato(self, est: dict, todos: list, grupos: list) -> str:
        m = est["minuto"]
        eventos = [(g[0], "gol", f"¡Gol de {self.local if g[1] == 'local' else self.visitante}!")
                   for g in GOLES_ILUSTRATIVOS if g[0] <= m]
        eventos += [(d.expediente.minuto_deteccion, "det", f"Stream pirata detectado: {d.expediente.host_stream}") for d in todos]
        exp_min = {d.expediente.id: d.expediente.minuto_deteccion for d in todos}
        eventos += [(g["aplicada_min"], "blq", f"Bloqueo aplicado: {g['objetivos'][0][1]} · {self._cobertura(g):.0f}% clientes")
                    for g in grupos if g["aplicada_min"] is not None and g["expediente_id"] in exp_min]
        eventos += [(t["desde_min"], "turno", f"Cambio de turno: {self._nombre_juez(t['juez_id'])}")
                    for t in self.turnos if 0 < t["desde_min"] <= m]
        eventos += [(x, "fase", txt) for x, txt in ((FIN_PRIMER_TIEMPO, "Entretiempo"), (FIN_ENTRETIEMPO, "Arranca el segundo tiempo"),
                                                    (est["fin"], "Final del partido: los bloqueos por IP vencen solos")) if x <= m]
        icono = {"gol": "⚽", "det": "🚨", "blq": "🛡", "turno": "⚖", "fase": "⏱"}
        chips = "".join(f"<div class='ev ev-{t}' data-k='{_escape(f'{x}-{t}-{txt}')}'><b>{_escape(minuto_tv(x))}</b><span>{icono[t]}</span>{_escape(txt)}</div>"
                        for x, t, txt in sorted(eventos, key=lambda e: e[0], reverse=True)[:6])
        return f"<div class='relato'><div class='relato-tit'>MINUTO A MINUTO</div><div class='evs'>{chips or '<div class=ev>Arranca el partido…</div>'}</div></div>"

    # --- mesa del juez ---------------------------------------------------------------------

    @classmethod
    def _instantanea(cls) -> tuple:
        """Copia consistente (bajo el lock de la Mesa) de expedientes, reclamos y órdenes agrupadas."""
        with cls.mesa.lock:
            todos = list(cls.mesa.expedientes.values())
            reclamos = list(cls.mesa.reclamos.values())
            ordenes = [dict(o, resultado=dict(o["resultado"])) for o in cls.mesa.ordenes_enviadas]
        return todos, reclamos, cls._agrupar_ordenes(ordenes)

    @classmethod
    def _evaluar_asistente(cls) -> dict:
        todos, reclamos, grupos = cls._instantanea()
        return cls.asistente.evaluar(cls._estado_simulador(), todos, reclamos, grupos, cls._cadena_ok())

    def _fragmento(self, juez: Optional[str] = None) -> str:
        est = self._estado_simulador()
        todos, reclamos, grupos = self._instantanea()
        # Primero los de riesgo colateral: son los que más exigen la mirada del juez.
        pendientes = sorted((d for d in todos if d.estado == "pendiente"),
                            key=lambda d: (not d.expediente.riesgo_colateral, d.expediente.minuto_deteccion))
        decididos = sorted((d for d in todos if d.estado != "pendiente"),
                           key=lambda d: d.decidido_min or 0, reverse=True)[:8]
        reclamos_pend = [d for d in reclamos if d.estado == "pendiente"]
        reclamos_ok = sum(1 for d in reclamos if d.estado != "pendiente")
        activos = [g for g in grupos if any(e == "aplicada" for e, _ in g["proveedores"].values())]
        minuto_det = {d.expediente.id: d.expediente.minuto_deteccion for d in todos}
        demoras = [g["aplicada_min"] - minuto_det[g["expediente_id"]] for g in grupos
                   if g["aplicada_min"] is not None and g["expediente_id"] in minuto_det]
        demora_media = f"{sum(demoras) / len(demoras):.1f}′" if demoras else "—"
        cobertura = (sum(self._cobertura(g) for g in activos) / len(activos)) if activos else 0.0
        cadena_ok = self._cadena_ok()
        estado_asis = self.asistente.evaluar(est, todos, reclamos, grupos, cadena_ok)
        turno = est["turno"][0] if est["turno"] else None
        en_turno = juez is not None and juez in est["turno"]
        if not en_turno:
            # Cada juez ve y firma solo lo suyo mientras está de turno: fuera de turno no hay nada que decidir.
            quien = self._nombre_juez(turno) if turno else "el próximo juez de turno"
            estado_asis = dict(estado_asis, siguiente={"texto": f"No estás de turno: los pendientes los decide {quien}.",
                                                       "foco": ".sesion"})
        panel_asistente = self._panel_asistente(estado_asis)

        derecha = (f"<small>Juez de turno</small><b>{_escape(self._nombre_juez(turno)) if turno else 'Sin turno'}</b>"
                   f"<span class='sesion'>👤 {_escape(self._nombre_juez(juez))} · "
                   f"<b class='{'en-turno' if en_turno else 'fuera-turno'}'>{'De turno' if en_turno else 'Fuera de turno'}</b>"
                   "<form method='post' action='/logout'><button type='submit' class='salir'>Salir</button></form></span>"
                   f"<span class='chain {'ok' if cadena_ok else 'bad'}'>{'🔒 Auditoría íntegra' if cadena_ok else '⚠ Auditoría alterada'}</span>"
                   "<a class='pub' href='/transparencia' target='_blank'>Registro público ↗</a>"
                   "<button type='button' class='guia-btn' data-guia>🧭 Guía de la mesa</button>")
        seccion_reclamos = ""
        if reclamos_pend:
            seccion_reclamos = (f'<section><h2><span class="dot ambar"></span>Reclamos de terceros '
                                f'<em>{len(reclamos_pend)}</em></h2><div class="grid">'
                                + "".join(self._card_reclamo(d) for d in reclamos_pend) + "</div></section>")
        cards = "".join(self._card_expediente(d) for d in pendientes[:8]) or (
            "<div class='vacio grande'><div class='vacio-ico'>⚖</div><b>Mesa al día</b>"
            "<span>No hay expedientes esperando decisión. Las detecciones nuevas aparecen acá solas.</span></div>")
        mas = (f"<p class='nota'>+ {len(pendientes) - 8} más en cola · primero los de riesgo colateral</p>"
               if len(pendientes) > 8 else "")
        feed = "".join(self._item_bloqueo(g) for g in grupos[:8]) or \
            "<div class='vacio'>Todavía no se firmó ninguna orden.</div>"
        hist = "".join(self._fila_decidida(d) for d in decididos) or \
            "<div class='vacio'>Todavía no se decidió ningún expediente.</div>"
        sin_turno = "" if turno else ("<div class='banner'>⚠ No hay juez de turno en este momento: "
                                      "nadie puede decidir ni firmar.</div>")
        if turno and not en_turno:
            sin_turno = (f"<div class='banner'>⚠ Estás fuera de turno: el juez de turno es "
                         f"{_escape(self._nombre_juez(turno))}. Podés ver el estado, pero no decidir ni firmar.</div>")
            seccion_reclamos, mas = "", ""
            cards = ("<div class='vacio grande'><div class='vacio-ico'>⏸</div><b>No estás de turno</b>"
                     f"<span>{len(pendientes)} expediente(s) y {len(reclamos_pend)} reclamo(s) pendientes los decide "
                     f"{_escape(self._nombre_juez(turno))}.</span></div>")
            pendientes, reclamos_pend = [], []

        return f"""
<div id="meta" data-pendientes="{_escape(','.join(d.expediente.id for d in pendientes))}"
     data-reclamos="{_escape(','.join(d.reclamo['id'] for d in reclamos_pend))}"></div>
{self._marcador(est, "Mesa del juez", LEMA, derecha)}
{self._linea_de_tiempo(est, todos)}
{sin_turno}
{self._relato(est, todos, grupos)}
<div class="kpis">
 <div class="kpi"><b>{len(pendientes)}</b><span>para decidir</span></div>
 <div class="kpi rojo"><b>{sum(1 for d in pendientes if d.expediente.riesgo_colateral)}</b><span>con riesgo colateral</span></div>
 <div class="kpi verde"><b>{len(activos)}</b><span>bloqueos activos</span></div>
 <div class="kpi azul"><b>{cobertura:.0f}<small>%</small></b><span>clientes cubiertos</span></div>
 <div class="kpi violeta"><b>{demora_media}</b><span>detección → bloqueo</span></div>
 <div class="kpi ambar"><b>{reclamos_ok}</b><span>reclamos resueltos</span></div>
</div>
<div class="cols">
 <main>
  {seccion_reclamos}
  <section><h2><span class="dot rojo"></span>Para revisar y firmar <em>{len(pendientes)}</em></h2>
  <div class="grid">{cards}</div>{mas}</section>
 </main>
 <aside>
  {panel_asistente}
  <section><h2><span class="dot verde"></span>Órdenes en proveedores</h2><div class="lista">{feed}</div></section>
  <section><h2><span class="dot"></span>Últimas decisiones</h2><div class="lista">{hist}</div></section>
 </aside>
</div>"""

    @classmethod
    def _cadena_ok(cls) -> bool:
        auditoria = getattr(cls.mesa, "auditoria", None)
        try:
            return auditoria is None or verificar_cadena(auditoria.ruta)
        except Exception:
            return False

    @staticmethod
    def _panel_asistente(estado: dict) -> str:
        sig = estado["siguiente"]
        alertas = "".join(
            f"<div class='alerta-asis n-{_escape(a['nivel'])}' data-k='asis-{_escape(a['clave'])}'>"
            f"<b>{_escape(a['titulo'])}</b><span>{_escape(a['detalle'])}</span>"
            + (f"<button type='button' class='ver' data-foco='{_escape(a['foco'])}'>ver</button>" if a["foco"] else "")
            + "</div>" for a in estado["alertas"][:6])
        return f"""<section id="asistente" class="asistente"><h2><span class="dot violeta"></span>Asistente del juez</h2>
  <div class="siguiente"><small>Siguiente paso</small><p>{_escape(sig['texto'])}</p>
   <button type="button" class="mostrar" data-foco="{_escape(sig['foco'])}">Mostrame dónde</button></div>
  <div class="lista">{alertas}</div>
  <p class="nota">Recomienda y vigila; nunca aprueba ni firma.</p></section>"""

    @staticmethod
    def _explicacion(item_id: str, exp: dict) -> str:
        puntos = "".join(f"<li>{_escape(p)}</li>" for p in exp["puntos"])
        revisar = ("<small>Antes de decidir, revisá:</small><ul class='checks'>"
                   + "".join(f"<li>{_escape(r)}</li>" for r in exp["revisar"]) + "</ul>") if exp["revisar"] else ""
        return (f"<details class='asis' id='asis-{_escape(item_id)}'><summary>🤖 Asistente: {_escape(exp['resumen'])}</summary>"
                f"<ul>{puntos}</ul>{revisar}<p class='sugerencia'>{_escape(exp['sugerencia'])}</p></details>")

    def _card_expediente(self, d) -> str:
        e = d.expediente
        if e.riesgo_colateral:
            otros = e.otros_sitios_en_la_ip
            lista = "".join(f"<span>{_escape(s)}</span>" for s in otros[:6])
            extra = f"<span>+{len(otros) - 6}</span>" if len(otros) > 6 else ""
            alerta = (f'<div class="alerta"><b>Riesgo de daño colateral</b>{_escape(e.motivo_riesgo)}'
                      f'<div class="sitios">{lista}{extra}</div></div>')
        else:
            alerta = f'<div class="limpio"><b>Sin riesgo colateral</b>{_escape(e.motivo_riesgo)}</div>'
        checks = "".join(f"<li>{_escape(v)}</li>" for v in e.verificaciones)
        promo = "".join(f"<a class='promo' href='{_escape(p.get('url', ''))}' target='_blank' rel='noopener'>"
                        f"{ICONO_RED.get(p.get('red', ''), '•')} {_escape(p.get('red', ''))} · min {p.get('minuto', '?')}</a>"
                        for p in e.promocion) or "<span class='nota'>sin datos</span>"
        reiteradas = len(e.detecciones_adicionales)
        return f"""<article class="card{' riesgo' if e.riesgo_colateral else ''}" data-k="{_escape(e.id)}">
 <div class="meta"><span class="pill">{_escape(e.id)}</span> detectado {_escape(minuto_tv(e.minuto_deteccion))} · sim {e.minuto_deteccion:g}
   {f"<span class='pill gris'>+{reiteradas} re-detección(es)</span>" if reiteradas else ""}</div>
 <h3>{_escape(e.host_stream)}</h3>
 <div class="srv"><code>{_escape(e.ip_servidor)}</code> · ASN {e.asn} · {_escape(e.organizacion or '—')}</div>
 <div class="marca">✓ Señal oficial <code>{_escape(e.marca_de_agua)}</code></div>
 {alerta}
 <div class="pedido"><small>Orden propuesta</small>
   <div><span class="tipo t-{_escape(e.tipo_recomendado)}">{_escape(e.tipo_recomendado)}</span>
   <code>{_escape(e.objetivo_recomendado)}</code><span class="vence">vence min {e.vencimiento_propuesto}</span></div></div>
 {self._explicacion(e.id, self.asistente.explicar_expediente(e))}
 <details id="det-{_escape(e.id)}"><summary>Ver evidencia completa</summary>
  <ul class="checks">{checks}</ul>
  <dl>
   <dt>Página</dt><dd>{_escape(e.pagina)}</dd>
   <dt>Stream</dt><dd>{_escape(e.stream_url)}</dd>
   <dt>Hash captura</dt><dd><code title="{_escape(e.hash_captura)}">{_escape(_corto(e.hash_captura))}</code></dd>
   <dt>Hash detección</dt><dd><code title="{_escape(e.hash_deteccion)}">{_escape(_corto(e.hash_deteccion))}</code></dd>
   <dt>Sello expediente</dt><dd><code title="{_escape(e.hash_expediente)}">{_escape(_corto(e.hash_expediente))}</code></dd>
   <dt>Sellado</dt><dd>{_escape(e.sello_utc)} · min {', '.join(f'{s:g}' for s in e.sellos_tiempo)}</dd>
   <dt>Promoción</dt><dd class="promos">{promo}</dd>
  </dl>
 </details>
 <form method="post" action="/expedientes/{_escape(e.id)}/decidir" data-confirmar="bloqueo" data-id="{_escape(e.id)}"
       data-host="{_escape(e.host_stream)}" data-tipo="{_escape(e.tipo_recomendado)}" data-objetivo="{_escape(e.objetivo_recomendado)}"
       data-vence="{e.vencimiento_propuesto}" data-riesgo="{'1' if e.riesgo_colateral else ''}">
  <button class="btn aprobar" name="decision" value="aprobar">✓ Aprobar y firmar</button>
  <button class="btn rechazar" name="decision" value="rechazar">Rechazar</button>
 </form>
</article>"""

    def _card_reclamo(self, d) -> str:
        r = d.reclamo
        orden = d.orden_afectada
        afecta = (f"<div class='srv'>Orden afectada: <span class='tipo t-{_escape(orden.get('tipo', ''))}'>"
                  f"{_escape(orden.get('tipo', ''))}</span> <code>{_escape(orden.get('objetivo', ''))}</code></div>"
                  if orden else "")
        return f"""<article class="card reclamo" data-k="{_escape(r['id'])}">
 <div class="meta"><span class="pill ambar">{_escape(r['id'])}</span> min {r['minuto']:.1f} · vía {_escape(r['proveedor'])}</div>
 <h3>{_escape(r['dominio'])}</h3>
 <blockquote>“{_escape(r['mensaje'])}”</blockquote>
 {afecta}
 <div class="pedido"><small>Propuesta de la plataforma</small><div><span class="tipo">{_escape(d.propuesta.replace('_', ' '))}</span></div>
 <p class="razon">{_escape(d.razon)}</p></div>
 {self._explicacion(r['id'], self.asistente.explicar_reclamo(d))}
 <form method="post" action="/reclamos/{_escape(r['id'])}/decidir" data-confirmar="reclamo" data-id="{_escape(r['id'])}"
       data-dominio="{_escape(r['dominio'])}" data-propuesta="{_escape(d.propuesta.replace('_', ' '))}">
  <button class="btn aprobar" name="decision" value="aprobar">✓ Aprobar propuesta</button>
  <button class="btn rechazar" name="decision" value="rechazar">Rechazar</button>
 </form>
</article>"""

    def _item_bloqueo(self, g: dict) -> str:
        cob = self._cobertura(g)
        return (f"<div class='item'><div class='item-top'>{self._objetivos(g)}</div>"
                f"<div class='cob'><div style='width:{cob:.0f}%'></div></div>"
                f"<small>{_escape(g['expediente_id'])} · {cob:.0f}% de clientes · firmó "
                f"{_escape(self._nombre_juez(g['juez_id']))} · vence min {g['vence_min']}</small>"
                f"<div class='chips'>{self._chips(g)}</div></div>")

    def _fila_decidida(self, d) -> str:
        e = d.expediente
        cuando = f" · min {d.minuto_decision:.0f}" if d.minuto_decision is not None else ""
        return (f"<div class='item fila'><span class='badge b-{d.estado}'>{_escape(d.estado)}</span>"
                f"<div><b>{_escape(e.host_stream)}</b><small>{_escape(e.id)} · {_escape(self._nombre_juez(d.decidido_por))}"
                f"{cuando}</small></div></div>")

    # --- registro público ------------------------------------------------------------------

    def _fragmento_transparencia(self) -> str:
        est = self._estado_simulador()
        # La vista pública sale de Mesa.vista_transparencia (sin evidencia interna) y se agrupa por expediente.
        filas = [{"expediente_id": f["expediente_id"], "juez_id": f["juez_id"], "juzgado_id": f["juzgado_id"],
                  "vence_min": f["vence_min"], "tipo": f["tipo"], "objetivo": f["objetivo"], "proveedor": f["proveedor"],
                  "resultado": {"estado": f["estado"], "aplicada_min": f["desde_min"]}}
                 for f in self.mesa.vista_transparencia()]
        cuerpo = "".join(
            f"<tr><td>{self._objetivos(g)}</td><td>{_escape(g['expediente_id'])}</td>"
            f"<td>{_escape(self._nombre_juez(g['juez_id']))}<small>{_escape(g['juzgado_id'])}</small></td>"
            f"<td>{'min ' + format(g['aplicada_min'], '.1f') if g['aplicada_min'] is not None else '—'}</td>"
            f"<td>min {g['vence_min']}</td><td><div class='chips'>{self._chips(g)}</div></td></tr>"
            for g in self._agrupar_ordenes(filas))
        cuerpo = cuerpo or "<tr><td colspan='6' class='vacio'>Todavía no hay bloqueos ordenados.</td></tr>"
        return f"""
{self._marcador(est, "Registro público", "Qué se bloqueó, cuándo, por orden de quién y hasta cuándo",
                "<small>Datos abiertos</small><a class='pub' href='/transparencia.json'>transparencia.json ↗</a>")}
<p class="aviso">Este registro no publica la evidencia interna de los expedientes (capturas, metadatos de detección)
para no ofrecer un mapa para evadir el próximo bloqueo. Los bloqueos por IP vencen solos al terminar el partido.</p>
<div class="tabla"><table><thead><tr><th>Bloqueo</th><th>Expediente</th><th>Ordenado por</th>
<th>Desde</th><th>Hasta</th><th>Estado por proveedor</th></tr></thead><tbody>{cuerpo}</tbody></table></div>"""


def iniciar_servidor_juez(mesa: Mesa, base_simulador: str, puerto: int, despachador=None,
                          equipos: tuple = ("Azul Juniors", "Rojo Plate"),
                          usuarios: Optional[Usuarios] = None) -> ThreadingHTTPServer:
    JuezHandler.mesa = mesa
    JuezHandler.usuarios = usuarios or Usuarios()
    JuezHandler.sesiones = Sesiones()
    JuezHandler.base_simulador = base_simulador
    JuezHandler.local, JuezHandler.visitante = equipos
    try:
        JuezHandler.turnos = pedir(base_simulador, "/juzgados").get("turnos", [])
    except Exception:
        JuezHandler.turnos = []
    if despachador is not None:
        JuezHandler.proveedores = despachador.proveedores
        JuezHandler.nombres_jueces = {jid: j.get("nombre", jid) for jid, j in despachador.jueces.jueces.items()}
    JuezHandler.asistente = Asistente(JuezHandler._clientes(), JuezHandler.nombres_jueces, JuezHandler.turnos,
                                      getattr(mesa, "auditoria", None))
    servidor = ThreadingHTTPServer(("0.0.0.0", puerto), JuezHandler)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    threading.Thread(target=vigilar_con_asistente, daemon=True).start()
    return servidor


def vigilar_con_asistente(intervalo_seg: float = 1.0) -> None:
    """El asistente vigila aunque nadie tenga la Mesa abierta: audita alertas y avisa las críticas en consola."""
    avisadas: set = set()
    while True:
        try:
            for a in JuezHandler._evaluar_asistente()["alertas"]:
                if a["nivel"] == "critico" and a["clave"] not in avisadas:
                    avisadas.add(a["clave"])
                    print(f"[asistente] ⚠ {a['titulo']} — {a['detalle']}")
        except Exception as e:
            print(f"[asistente] error: {e}")
        time.sleep(intervalo_seg)
