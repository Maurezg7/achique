"""Tests sin dependencias: python3 -m unittest discover -s tests -v"""
import base64
import hashlib
import hmac
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import despacho  # noqa: E402
import evidencia  # noqa: E402
import firmas  # noqa: E402
from auditoria import RegistroAuditoria, verificar_cadena  # noqa: E402
from mesa import Mesa  # noqa: E402

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

    def test_firma_con_el_juez_de_turno_en_el_instante(self):
        orden = self.jueces.firmar_orden("o1", "dominio", "x.test", 105)
        esperada = hmac.new(b"clave-a", b"o1|dominio|x.test|105|jueza-a", hashlib.sha256).hexdigest()
        self.assertEqual((orden["juez_id"], orden["juzgado_id"], orden["firma"]), ("jueza-a", "jg-a", esperada))
        self.sim.de_turno = ["juez-b"]  # cambio de turno: no se cachea
        self.assertEqual(self.jueces.firmar_orden("o2", "ip", "1.1.1.1", 105)["juez_id"], "juez-b")

    def test_sin_juez_de_turno_no_se_firma(self):
        self.sim.de_turno = []
        with self.assertRaises(RuntimeError):
            self.jueces.firmar_orden("o1", "ip", "1.1.1.1", 105)


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
