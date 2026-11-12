"""Tests sin dependencias: python3 -m unittest discover -s tests -v"""
import base64
import hashlib
import hmac
import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from achique import despacho, evidencia, firmas, plataforma, reanudacion, reclamos, servidor_juez, sesiones  # noqa: E402
from achique.auditoria import RegistroAuditoria, verificar_cadena  # noqa: E402
from achique.mesa import Mesa  # noqa: E402

JUZGADOS = {"juzgados": [
    {"id": "jg-a", "nombre": "Juzgado A", "jurisdiccion": "X",
     "jueces": [{"id": "jueza-a", "nombre": "Dra. A", "clave_firma_demo": "clave-a"}]},
    {"id": "jg-b", "nombre": "Juzgado B", "jurisdiccion": "X",
     "jueces": [{"id": "juez-b", "nombre": "Dr. B", "clave_firma_demo": "clave-b"}]}],
    "turnos": []}


class SimuladorFalso:
    """Imita la API del simulador oficial lo justo para probar la plataforma sin red."""

    def __init__(self):
        self.minuto = 10.0
        self.de_turno = ["jueza-a"]
        self.dns = {
            "203.0.113.10": {"dominios": ["s1.pirata.test", "s1-respaldo.pirata.test"], "organizacion": "Hosting Dedicado"},
            "198.51.100.20": {"dominios": ["live.otro.test", "panaderia.test"], "organizacion": "NubeRápida CDN"},
            "203.0.113.50": {"dominios": ["solo.pirata.test"], "organizacion": "Hosting Compartido"},
        }
        self.proveedores = [{"id": "grande", "capacidades": ["ip", "dominio"], "clientes": 100},
                            {"id": "chico", "capacidades": ["dominio"], "clientes": 10}]
        self.ordenes = {}         # (proveedor, orden_id) -> dict
        self.estado_inicial = {}  # proveedor -> estado al consultar (p. ej. "fallida")
        self.recibidas = []

    def pedir(self, base, ruta, cuerpo=None, metodo="GET"):
        if ruta == "/estado":
            return {"minuto_actual": self.minuto, "jueces_de_turno": list(self.de_turno), "fin_min": 105}
        if ruta == "/partido":
            return {"id": "p1", "fin_min": 105,
                    "marcas_de_agua_validas": [{"prefijo": "LP-OFI", "origen": "Señal oficial"},
                                               {"prefijo": "LP-LIC", "origen": "Licenciatario"}],
                    "licenciatarios": [{"prefijo_marca": "LP-LIC", "dominios_autorizados": ["envivo.lic.test"]}]}
        if ruta.startswith("/dns-pasivo?ip="):
            ip = ruta.split("=", 1)[1]
            return dict(self.dns[ip], ip=ip, asn=64600) if ip in self.dns else {"error": "sin datos"}
        if ruta == "/proveedores":
            return self.proveedores
        partes = ruta.strip("/").split("/")
        if metodo == "POST" and partes[-1] == "ordenes":
            self.recibidas.append((partes[1], cuerpo))
            self.ordenes[(partes[1], cuerpo["orden_id"])] = dict(cuerpo, estado="recibida")
            return {"orden_id": cuerpo["orden_id"], "estado": "recibida"}
        if metodo == "GET" and len(partes) == 4:
            orden = self.ordenes.get((partes[1], partes[3]))
            if orden is None:
                return {"error": "Orden inexistente"}
            orden["estado"] = self.estado_inicial.get(partes[1], "aplicada") if orden["estado"] == "recibida" else orden["estado"]
            return dict(orden, aplicada_min=self.minuto)
        raise AssertionError(f"ruta no simulada: {metodo} {ruta}")


def deteccion(id_="D-1", host="s1.pirata.test", ip="203.0.113.10", marca="LP-OFI-123"):
    return {"id": id_, "minuto": 2.0, "pagina": "https://pirata.test/", "stream_url": f"https://{host}/x.m3u8",
            "host_stream": host, "ip_servidor": ip, "asn": 64600, "marca_de_agua_extraida": marca,
            "captura": {"capturada_min": 2.0, "formato": "mpegts", "duracion_seg": 6,
                        "contenido_b64": base64.b64encode(b"video").decode()}}


class ConSimulador(unittest.TestCase):
    def setUp(self):
        self.sim = SimuladorFalso()
        self.parches = [mock.patch.object(m, "pedir", self.sim.pedir) for m in (evidencia, despacho, firmas)]
        for p in self.parches:
            p.start()
        self.tmp = tempfile.TemporaryDirectory()
        ruta_jz = Path(self.tmp.name) / "juzgados.json"
        ruta_jz.write_text(json.dumps(JUZGADOS), encoding="utf-8")
        self.jueces = firmas.RegistroJueces("http://sim", ruta_jz)
        self.auditoria = RegistroAuditoria(Path(self.tmp.name) / "auditoria.jsonl")
        self.mesa = Mesa(self.auditoria)
        self.builder = evidencia.ExpedienteBuilder("http://sim")

    def tearDown(self):
        for p in self.parches:
            p.stop()
        self.auditoria._archivo.close()
        self.tmp.cleanup()


class TestAuditoria(unittest.TestCase):
    def test_cadena_integra_y_detecta_alteracion(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "a.jsonl"
            reg = RegistroAuditoria(ruta)
            for i in range(5):
                reg.registrar("evento", n=i)
            reg._archivo.close()
            self.assertTrue(verificar_cadena(ruta))
            lineas = ruta.read_text(encoding="utf-8").splitlines()
            alterada = json.loads(lineas[2])
            alterada["datos"]["n"] = 99
            lineas[2] = json.dumps(alterada, ensure_ascii=False)
            ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
            self.assertFalse(verificar_cadena(ruta))

    def test_detecta_linea_borrada(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "a.jsonl"
            reg = RegistroAuditoria(ruta)
            for i in range(4):
                reg.registrar("evento", n=i)
            reg._archivo.close()
            lineas = ruta.read_text(encoding="utf-8").splitlines()
            ruta.write_text("\n".join(lineas[:1] + lineas[2:]) + "\n", encoding="utf-8")
            self.assertFalse(verificar_cadena(ruta))

    def test_continua_la_cadena_al_reabrir(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "a.jsonl"
            reg = RegistroAuditoria(ruta)
            reg.registrar("uno")
            reg._archivo.close()
            reg = RegistroAuditoria(ruta)
            self.assertEqual(reg.registrar("dos")["seq"], 2)
            reg._archivo.close()
            self.assertTrue(verificar_cadena(ruta))


class TestFirmas(ConSimulador):
    def test_mensajes_canonicos(self):
        self.assertEqual(firmas.mensaje_orden("o1", "ip", "1.2.3.4", 105, "j"), "o1|ip|1.2.3.4|105|j")
        self.assertEqual(firmas.mensaje_levantar("o1", "j"), "LEVANTAR|o1|j")

    def test_firma_el_juez_que_aprobo_si_esta_de_turno(self):
        orden = self.jueces.firmar_orden("o1", "dominio", "x.test", 105, "jueza-a")
        esperada = hmac.new(b"clave-a", b"o1|dominio|x.test|105|jueza-a", hashlib.sha256).hexdigest()
        self.assertEqual((orden["juez_id"], orden["juzgado_id"], orden["firma"]), ("jueza-a", "jg-a", esperada))

    def test_nadie_firma_en_nombre_de_un_juez_fuera_de_turno(self):
        self.sim.de_turno = ["juez-b"]  # cambio de turno: no se cachea
        with self.assertRaises(firmas.FueraDeTurno):
            self.jueces.firmar_orden("o2", "ip", "1.1.1.1", 105, "jueza-a")
        with self.assertRaises(firmas.FueraDeTurno):
            self.jueces.firmar_levantamiento("o2", "reclamo", "jueza-a")
        self.assertEqual(self.jueces.firmar_orden("o3", "ip", "1.1.1.1", 105, "juez-b")["juez_id"], "juez-b")

    def test_sin_juez_de_turno_no_se_firma(self):
        self.sim.de_turno = []
        with self.assertRaises(RuntimeError):
            self.jueces.firmar_orden("o1", "ip", "1.1.1.1", 105, "jueza-a")


class TestEvidencia(ConSimulador):
    def test_espejos_del_mismo_sitio_no_son_colateral(self):
        exp = self.builder.construir(deteccion())
        self.assertFalse(exp.riesgo_colateral)
        self.assertEqual((exp.tipo_recomendado, exp.objetivo_recomendado), ("ip", "203.0.113.10"))

    def test_ip_compartida_con_otros_sitios_bloquea_dominio(self):
        exp = self.builder.construir(deteccion(host="live.otro.test", ip="198.51.100.20"))
        self.assertTrue(exp.riesgo_colateral)
        self.assertEqual((exp.tipo_recomendado, exp.objetivo_recomendado), ("dominio", "live.otro.test"))
        self.assertEqual(exp.otros_sitios_en_la_ip, ["panaderia.test"])

    def test_hosting_compartido_o_sin_dns_bloquea_dominio(self):
        self.assertEqual(self.builder.construir(deteccion(host="solo.pirata.test", ip="203.0.113.50")).tipo_recomendado,
                         "dominio")
        self.assertEqual(self.builder.construir(deteccion(ip="10.9.9.9")).tipo_recomendado, "dominio")

    def test_descarta_licenciatario_y_marca_ajena(self):
        lic = deteccion(host="envivo.lic.test", marca="LP-LIC-1")
        self.assertIsNotNone(self.builder.motivo_descarte(lic))
        self.assertIsNone(self.builder.construir(lic))
        self.assertIsNone(self.builder.construir(deteccion(marca="OTRO-PARTIDO-1")))
        self.assertIsNone(self.builder.construir(deteccion(marca="")))
        # Marca de licenciatario fuera de su dominio: retransmisión no autorizada.
        self.assertIsNotNone(self.builder.construir(deteccion(marca="LP-LIC-1")))

    def test_hash_de_captura_y_sello_detectan_alteracion(self):
        exp = self.builder.construir(deteccion())
        self.assertEqual(exp.hash_captura, hashlib.sha256(b"video").hexdigest())
        datos = exp.to_dict()
        self.assertTrue(evidencia.verificar_expediente(datos))
        datos["objetivo_recomendado"] = "otra.test"
        self.assertFalse(evidencia.verificar_expediente(datos))


class TestDespacho(ConSimulador):
    def _aprobado(self, det):
        exp = self.builder.construir(det)
        self.mesa.nuevo_expediente(exp)
        self.assertTrue(self.mesa.decidir_expediente(exp.id, True, "jueza-a"))
        return exp

    def test_ip_con_fallback_a_dominio_para_proveedor_sin_capacidad(self):
        d = despacho.Despachador("http://sim", self.mesa, self.jueces, self.auditoria)
        d.despachar_expediente(self._aprobado(deteccion()))
        pedidos = {p: (c["tipo"], c["objetivo"]) for p, c in self.sim.recibidas}
        self.assertEqual(pedidos, {"grande": ("ip", "203.0.113.10"), "chico": ("dominio", "s1.pirata.test")})

    def test_dominio_nunca_se_convierte_en_ip(self):
        exp = self.builder.construir(deteccion(host="live.otro.test", ip="198.51.100.20"))
        self.assertEqual(despacho.tipo_para_proveedor(exp, ["ip"]), None)

    def test_reintentos_no_se_multiplican_y_respetan_el_maximo(self):
        self.sim.estado_inicial["grande"] = "fallida"
        d = despacho.Despachador("http://sim", self.mesa, self.jueces, self.auditoria)
        d.despachar_expediente(self._aprobado(deteccion()))
        for _ in range(despacho.MAX_REINTENTOS + 4):
            d.seguir_ordenes()
            vivas = [o for o in d.lista_ordenes() if o.proveedor_id == "grande" and o.estado not in despacho.ESTADOS_FINALES]
            self.assertLessEqual(len(vivas), 1)
        enviadas_grande = [c for p, c in self.sim.recibidas if p == "grande"]
        self.assertEqual(len(enviadas_grande), 1 + despacho.MAX_REINTENTOS)

    def test_no_reintenta_ordenes_vencidas(self):
        self.sim.estado_inicial["grande"] = "fallida"
        d = despacho.Despachador("http://sim", self.mesa, self.jueces, self.auditoria)
        d.despachar_expediente(self._aprobado(deteccion()))
        self.sim.minuto = 106
        d.seguir_ordenes()
        d.seguir_ordenes()
        self.assertEqual(len([c for p, c in self.sim.recibidas if p == "grande"]), 1)

    def test_sin_aprobacion_no_se_despacha_nada(self):
        exp = self.builder.construir(deteccion())
        self.mesa.nuevo_expediente(exp)
        self.assertEqual(self.mesa.aprobados_sin_despachar(), [])
        self.mesa.decidir_expediente(exp.id, False, "jueza-a", "dudoso")
        self.assertEqual(self.mesa.aprobados_sin_despachar(), [])

    def test_auditoria_queda_integra(self):
        d = despacho.Despachador("http://sim", self.mesa, self.jueces, self.auditoria)
        d.despachar_expediente(self._aprobado(deteccion()))
        d.seguir_ordenes()
        eventos = [json.loads(l)["evento"] for l in self.auditoria.ruta.read_text(encoding="utf-8").splitlines()]
        self.assertIn("decision_juez", eventos)
        self.assertIn("orden_confirmada", eventos)
        self.assertTrue(verificar_cadena(self.auditoria.ruta))


class TestCambioDeTurno(ConSimulador):
    def _aprobado(self, det):
        exp = self.builder.construir(det)
        self.mesa.nuevo_expediente(exp)
        self.mesa.decidir_expediente(exp.id, True, "jueza-a")
        return exp

    def test_aprobado_por_el_saliente_sin_firmar_pasa_al_entrante(self):
        d = despacho.Despachador("http://sim", self.mesa, self.jueces, self.auditoria)
        exp = self._aprobado(deteccion())
        self.sim.de_turno = ["juez-b"]
        d.despachar_expediente(exp)
        self.assertEqual(self.sim.recibidas, [])
        self.assertEqual(self.mesa.expedientes[exp.id].estado, "pendiente")
        self.assertTrue(self.mesa.decidir_expediente(exp.id, True, "juez-b"))
        d.despachar_expediente(exp)
        self.assertEqual({c["juez_id"] for _, c in self.sim.recibidas}, {"juez-b"})

    def test_reintento_tras_cambio_de_turno_vuelve_a_la_mesa(self):
        self.sim.estado_inicial["grande"] = "fallida"
        d = despacho.Despachador("http://sim", self.mesa, self.jueces, self.auditoria)
        exp = self._aprobado(deteccion())
        d.despachar_expediente(exp)
        self.sim.de_turno = ["juez-b"]
        d.seguir_ordenes()
        self.assertEqual([c["juez_id"] for p, c in self.sim.recibidas if p == "grande"], ["jueza-a"])
        self.assertEqual(self.mesa.expedientes[exp.id].estado, "pendiente")
        self.sim.estado_inicial.pop("grande")
        self.mesa.decidir_expediente(exp.id, True, "juez-b")
        d.despachar_expediente(exp)
        enviadas = [(p, c["juez_id"]) for p, c in self.sim.recibidas]
        self.assertEqual(enviadas, [("grande", "jueza-a"), ("chico", "jueza-a"), ("grande", "juez-b")])
        self.assertTrue(verificar_cadena(self.auditoria.ruta))


class TestMesaConcurrente(ConSimulador):
    def test_una_sola_decision_gana(self):
        exp = self.builder.construir(deteccion())
        self.mesa.nuevo_expediente(exp)
        resultados = []
        hilos = [threading.Thread(target=lambda: resultados.append(self.mesa.decidir_expediente(exp.id, True, "jueza-a")))
                 for _ in range(20)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        self.assertEqual(resultados.count(True), 1)
        self.assertEqual(len(self.mesa.aprobados_sin_despachar()), 1)

    def test_altas_concurrentes(self):
        def alta(i):
            exp = self.builder.construir(deteccion(id_=f"D-{i}"))
            exp.id = f"EXP-{i}"
            self.mesa.nuevo_expediente(exp)
        hilos = [threading.Thread(target=alta, args=(i,)) for i in range(50)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        self.assertEqual(len(self.mesa.pendientes_expedientes()), 50)
        self.assertTrue(verificar_cadena(self.auditoria.ruta))


if __name__ == "__main__":
    unittest.main()


class TestSesiones(unittest.TestCase):
    def test_usuarios_demo_atados_a_los_jueces_oficiales(self):
        u = sesiones.Usuarios()
        self.assertEqual(u.verificar("laura", "laura-demo-2026"), "jueza-laura-ficticia")
        self.assertEqual(u.verificar("martin", "martin-demo-2026"), "juez-martin-ejemplo")
        self.assertIsNone(u.verificar("laura", "martin-demo-2026"))
        self.assertIsNone(u.verificar("nadie", "laura-demo-2026"))
        self.assertNotIn("laura-demo-2026", sesiones.USUARIOS_DEMO.read_text(encoding="utf-8"))

    def test_sesion_vence_y_se_cierra(self):
        s = sesiones.Sesiones()
        t = s.crear("jueza-a")
        self.assertEqual(s.juez(t), "jueza-a")
        self.assertIsNone(s.juez("otro-token"))
        self.assertEqual(s.cerrar(t), "jueza-a")
        self.assertIsNone(s.juez(t))
        self.assertIsNone(sesiones.Sesiones(duracion_seg=0).juez(sesiones.Sesiones(duracion_seg=0).crear("x")))

    def test_bloqueo_por_intentos_fallidos(self):
        s = sesiones.Sesiones()
        for _ in range(sesiones.MAX_FALLOS):
            self.assertFalse(s.bloqueado("1.2.3.4"))
            s.registrar_fallo("1.2.3.4")
        self.assertTrue(s.bloqueado("1.2.3.4"))
        self.assertFalse(s.bloqueado("5.6.7.8"))
        s.limpiar_fallos("1.2.3.4")
        self.assertFalse(s.bloqueado("1.2.3.4"))


class TestMesaConIngreso(ConSimulador):
    """La Mesa por HTTP: sin sesión no se ve nada; fuera de turno no se decide ni se firma."""

    def setUp(self):
        super().setUp()
        ruta = Path(self.tmp.name) / "usuarios.json"
        ruta.write_text(json.dumps({"usuarios": [sesiones.crear_usuario("a", "jueza-a", "clave-a-demo"),
                                                 sesiones.crear_usuario("b", "juez-b", "clave-b-demo")]}),
                        encoding="utf-8")
        for p in (mock.patch.object(servidor_juez, "pedir", self.sim.pedir),
                  mock.patch.object(servidor_juez, "vigilar_con_asistente", lambda *a: None)):
            p.start()
            self.parches.append(p)
        self.servidor = servidor_juez.iniciar_servidor_juez(self.mesa, "http://sim", 0, usuarios=sesiones.Usuarios(ruta))
        self.puerto = self.servidor.server_address[1]
        self.exp = self.builder.construir(deteccion())
        self.mesa.nuevo_expediente(self.exp)

    def tearDown(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        super().tearDown()

    def _pedir(self, metodo, ruta, datos=None, cookie=None, fetch=False):
        c = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=5)
        cab = {"Content-Type": "application/x-www-form-urlencoded"}
        if cookie:
            cab["Cookie"] = cookie
        if fetch:
            cab["X-Requested-With"] = "fetch"
        c.request(metodo, ruta, urlencode(datos or {}), cab)
        r = c.getresponse()
        cuerpo = r.read().decode("utf-8")
        c.close()
        return r.status, dict(r.getheaders()), cuerpo

    def _ingresar(self, usuario, clave):
        estado, cab, _ = self._pedir("POST", "/login", {"usuario": usuario, "clave": clave})
        self.assertEqual((estado, cab["Location"]), (303, "/"))
        self.assertIn("HttpOnly", cab["Set-Cookie"])
        return cab["Set-Cookie"].split(";")[0]

    def test_sin_sesion_no_se_ve_la_mesa(self):
        estado, cab, _ = self._pedir("GET", "/")
        self.assertEqual((estado, cab["Location"]), (303, "/login"))
        self.assertEqual(self._pedir("GET", "/fragmento")[0], 401)
        self.assertEqual(self._pedir("GET", "/asistente.json")[0], 401)
        self.assertEqual(self._pedir("POST", f"/expedientes/{self.exp.id}/decidir", {"decision": "aprobar"})[0], 401)
        self.assertEqual(self._pedir("GET", "/transparencia.json")[0], 200)  # el registro público sigue público
        self.assertEqual(self.mesa.expedientes[self.exp.id].estado, "pendiente")

    def test_clave_incorrecta(self):
        estado, cab, _ = self._pedir("POST", "/login", {"usuario": "a", "clave": "mal"})
        self.assertEqual((estado, cab["Location"]), (303, "/login?error=1"))
        self.assertNotIn("Set-Cookie", cab)
        self.assertNotIn("mal", self.auditoria.ruta.read_text(encoding="utf-8"))

    def test_fuera_de_turno_no_decide_y_el_de_turno_si(self):
        cookie_b = self._ingresar("b", "clave-b-demo")
        _, _, frag = self._pedir("GET", "/fragmento", cookie=cookie_b)
        self.assertIn("No estás de turno", frag)
        estado, _, _ = self._pedir("POST", f"/expedientes/{self.exp.id}/decidir", {"decision": "aprobar"},
                                   cookie=cookie_b, fetch=True)
        self.assertEqual(estado, 403)
        self.assertEqual(self.mesa.expedientes[self.exp.id].estado, "pendiente")
        self.assertIn("decision_denegada", self.auditoria.ruta.read_text(encoding="utf-8"))

        cookie_a = self._ingresar("a", "clave-a-demo")
        self.assertIn(self.exp.id, self._pedir("GET", "/fragmento", cookie=cookie_a)[2])
        estado, _, _ = self._pedir("POST", f"/expedientes/{self.exp.id}/decidir", {"decision": "aprobar"},
                                   cookie=cookie_a, fetch=True)
        self.assertEqual(estado, 204)
        d = self.mesa.expedientes[self.exp.id]
        self.assertEqual((d.estado, d.decidido_por), ("aprobado", "jueza-a"))
        self.assertTrue(verificar_cadena(self.auditoria.ruta))

    def test_al_cambio_de_turno_el_saliente_ya_no_firma(self):
        cookie_a = self._ingresar("a", "clave-a-demo")
        self.sim.de_turno = ["juez-b"]
        estado, _, _ = self._pedir("POST", f"/expedientes/{self.exp.id}/decidir", {"decision": "aprobar"},
                                   cookie=cookie_a, fetch=True)
        self.assertEqual(estado, 403)
        cookie_b = self._ingresar("b", "clave-b-demo")
        self.assertIn(self.exp.id, self._pedir("GET", "/fragmento", cookie=cookie_b)[2])

    def test_salir_cierra_la_sesion(self):
        cookie_a = self._ingresar("a", "clave-a-demo")
        estado, cab, _ = self._pedir("POST", "/logout", cookie=cookie_a)
        self.assertEqual((estado, cab["Location"]), (303, "/login?salio=1"))
        self.assertEqual(self._pedir("GET", "/fragmento", cookie=cookie_a)[0], 401)


class TestReanudacion(ConSimulador):
    """Tras un reinicio con el mismo log, la plataforma retoma sin duplicar expedientes ni órdenes."""

    def _plataforma(self):
        auditoria = RegistroAuditoria(Path(self.tmp.name) / "auditoria.jsonl")
        mesa = Mesa(auditoria)
        builder = evidencia.ExpedienteBuilder("http://sim")
        d = despacho.Despachador("http://sim", mesa, self.jueces, auditoria)
        gestor = reclamos.GestorReclamos("http://sim", mesa, d)
        ingesta = plataforma.Ingesta("http://sim", mesa, builder, gestor, auditoria, Path(self.tmp.name) / "exp")
        return auditoria, mesa, builder, d, gestor, ingesta

    def _reanudar(self, partes):
        auditoria, mesa, builder, d, gestor, ingesta = partes
        return reanudacion.reanudar(auditoria.ruta, ingesta.carpeta, mesa, builder, ingesta, d, gestor, auditoria)

    def test_retoma_despachados_y_pendientes_sin_duplicar(self):
        self.auditoria._archivo.close()
        p1 = self._plataforma()
        auditoria, mesa, builder, d, gestor, ingesta = p1
        ingesta.procesar(deteccion("D-1"))
        ingesta.procesar(deteccion("D-1b"))                                   # re-detección del mismo servidor
        ingesta.procesar(deteccion("D-2", host="live.otro.test", ip="198.51.100.20"))
        exp1 = mesa.expedientes["EXP-2026-000001"].expediente
        mesa.decidir_expediente(exp1.id, True, "jueza-a")
        d.despachar_expediente(exp1)
        self.assertEqual(len(self.sim.recibidas), 2)
        auditoria._archivo.close()

        p2 = self._plataforma()
        resumen = self._reanudar(p2)
        auditoria2, mesa2, builder2, d2, gestor2, ingesta2 = p2
        self.assertEqual((resumen["expedientes"], resumen["pendientes"], resumen["ordenes"]), (2, 1, 2))
        self.assertEqual(mesa2.expedientes[exp1.id].estado, "despachado")
        self.assertEqual(len(mesa2.expedientes[exp1.id].expediente.detecciones_adicionales), 1)
        self.assertEqual(mesa2.expedientes["EXP-2026-000002"].estado, "pendiente")
        self.assertEqual(builder2._contador, 2)
        # Las mismas detecciones no abren nada nuevo; una nueva sigue la numeración.
        for det in (deteccion("D-1"), deteccion("D-1b"), deteccion("D-2", host="live.otro.test", ip="198.51.100.20")):
            ingesta2.procesar(det)
        self.assertEqual(len(mesa2.expedientes), 2)
        ingesta2.procesar(deteccion("D-3", host="solo.pirata.test", ip="203.0.113.50"))
        self.assertIn("EXP-2026-000003", mesa2.expedientes)
        # Las órdenes ya enviadas se siguen (no se reenvían) y los ids nuevos no chocan.
        d2.despachar_expediente(exp1)
        self.assertEqual(len(self.sim.recibidas), 2)
        d2.seguir_ordenes()
        self.assertEqual({o.estado for o in d2.lista_ordenes()}, {"aplicada"})
        self.assertTrue(all(o.juez_id == "jueza-a" for o in d2.lista_ordenes()))
        self.assertEqual(d2._nuevo_orden_id("x"), "ord-x-3")
        self.assertEqual(len(mesa2.vista_transparencia()), 2)
        self.assertTrue(verificar_cadena(auditoria2.ruta))
        auditoria2._archivo.close()

    def test_aprobado_a_medio_despachar_completa_lo_que_falta(self):
        self.auditoria._archivo.close()
        p1 = self._plataforma()
        auditoria, mesa, builder, d, gestor, ingesta = p1
        ingesta.procesar(deteccion("D-1"))
        exp = mesa.expedientes["EXP-2026-000001"].expediente
        mesa.decidir_expediente(exp.id, True, "jueza-a")
        d.enviar_orden("grande", exp.id, "ip", "203.0.113.10", 105, "jueza-a")  # se cayó antes del segundo proveedor
        auditoria._archivo.close()

        p2 = self._plataforma()
        self._reanudar(p2)
        auditoria2, mesa2, _, d2, _, _ = p2
        self.assertEqual(mesa2.expedientes[exp.id].estado, "aprobado")
        d2.despachar_expediente(mesa2.expedientes[exp.id].expediente)
        self.assertEqual([p for p, _ in self.sim.recibidas], ["grande", "chico"])
        self.assertEqual(mesa2.expedientes[exp.id].estado, "despachado")
        auditoria2._archivo.close()

    def test_log_vacio_es_arranque_normal(self):
        self.auditoria._archivo.close()
        p = self._plataforma()
        self.assertIsNone(self._reanudar(p))
        p[0]._archivo.close()
