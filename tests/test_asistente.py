"""Tests del asistente del juez: python3 -m unittest discover -s tests -v"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_plataforma import ConSimulador, deteccion  # noqa: E402
from tarjeta_roja.asistente import Asistente  # noqa: E402
from tarjeta_roja.auditoria import verificar_cadena  # noqa: E402
from tarjeta_roja.mesa import DecisionReclamo  # noqa: E402


def est(minuto=10.0, turno=("jueza-a",), finalizado=False, fin=105.0):
    return {"minuto": minuto, "fin": fin, "turno": list(turno), "finalizado": finalizado}


def grupo(exp_id, proveedores, aplicada_min=None, vence_min=105):
    return {"expediente_id": exp_id, "juez_id": "jueza-a", "vence_min": vence_min, "objetivos": [],
            "proveedores": proveedores, "aplicada_min": aplicada_min}


class TestAsistente(ConSimulador):
    def setUp(self):
        super().setUp()
        self.asis = Asistente({"grande": 100, "chico": 10}, {"juez-b": "Dr. B"},
                              [{"juez_id": "juez-b", "desde_min": 50}], self.auditoria)

    def _pendiente(self, **kw):
        exp = self.builder.construir(deteccion(**kw))
        self.mesa.nuevo_expediente(exp)
        return exp

    def _claves(self, estado):
        return {a["clave"]: a["nivel"] for a in estado["alertas"]}

    def test_todo_en_orden(self):
        estado = self.asis.evaluar(est(), [], [], [])
        self.assertEqual(estado["alertas"][0]["nivel"], "ok")
        self.assertIn("Mesa al día", estado["siguiente"]["texto"])

    def test_espera_de_firma_escala_y_guia_al_boton(self):
        exp = self._pendiente()  # detectado en el min 2
        exps = list(self.mesa.expedientes.values())
        self.assertNotIn(f"espera-atencion-{exp.id}", self._claves(self.asis.evaluar(est(minuto=2.5), exps, [], [])))
        self.assertEqual(self._claves(self.asis.evaluar(est(minuto=3.5), exps, [], []))[f"espera-atencion-{exp.id}"],
                         "atencion")
        estado = self.asis.evaluar(est(minuto=5.0), exps, [], [])
        self.assertEqual(self._claves(estado)[f"espera-critico-{exp.id}"], "critico")
        self.assertEqual(estado["siguiente"]["foco"], f'[data-k="{exp.id}"] .btn.aprobar')

    def test_sin_turno_y_cadena_alterada_son_criticas(self):
        claves = self._claves(self.asis.evaluar(est(turno=()), [], [], [], cadena_ok=False))
        self.assertEqual((claves["sin-turno"], claves["cadena"]), ("critico", "critico"))

    def test_reclamo_de_dano_colateral_va_primero(self):
        self._pendiente()
        dr = DecisionReclamo(reclamo={"id": "R-1", "dominio": "panaderia.test", "proveedor": "grande", "minuto": 3.0,
                                      "mensaje": "nos bloquearon"},
                             propuesta="levantar_y_precisar", razon="Daño colateral",
                             orden_afectada={"tipo": "ip", "objetivo": "198.51.100.20"})
        estado = self.asis.evaluar(est(minuto=2.2), list(self.mesa.expedientes.values()), [dr], [])
        self.assertEqual(estado["alertas"][0]["clave"], "reclamo-R-1")
        self.assertIn("R-1", estado["siguiente"]["texto"])
        exp = Asistente.explicar_reclamo(dr)
        self.assertIn("si el DNS pasivo identifica", " ".join(exp["puntos"]))
        self.assertIn("queda sin bloquear", " ".join(exp["revisar"]))

    def test_ordenes_rechazadas_fallidas_y_sin_confirmar(self):
        g = grupo("EXP-1", {"grande": ("rechazada", "ip"), "chico": ("fallida", "dominio")})
        g2 = grupo("EXP-2", {"grande": ("aplicada", "ip"), "chico": ("recibida", "dominio")}, aplicada_min=10)
        claves = self._claves(self.asis.evaluar(est(minuto=12), [], [], [g, g2]))
        self.assertNotIn("sin-confirmar-EXP-2-chico", claves)
        claves = self._claves(self.asis.evaluar(est(minuto=17.5), [], [], [g, g2]))
        self.assertEqual(claves["rechazada-EXP-1-grande"], "critico")
        self.assertEqual(claves["fallida-EXP-1-chico"], "atencion")
        self.assertEqual(claves["sin-confirmar-EXP-2-chico"], "atencion")

    def test_bloqueos_por_ip_al_final_del_partido(self):
        g = grupo("EXP-1", {"grande": ("aplicada", "ip")}, aplicada_min=10)
        self.assertEqual(self._claves(self.asis.evaluar(est(minuto=98), [], [], [g]))["ip-fin"], "info")
        recien = self._claves(self.asis.evaluar(est(minuto=105.01, finalizado=True), [], [], [g]))
        self.assertNotIn("ip-post-partido", recien)
        self.assertEqual(recien["ip-fin"], "info")
        self.assertEqual(self._claves(self.asis.evaluar(est(minuto=107.5, finalizado=True), [], [], [g]))["ip-post-partido"],
                         "critico")
        vencida = grupo("EXP-1", {"grande": ("vencida", "ip")})
        self.assertNotIn("ip-post-partido", self._claves(self.asis.evaluar(est(minuto=106, finalizado=True), [], [], [vencida])))

    def test_avisa_cambio_de_turno(self):
        alerta = next(a for a in self.asis.evaluar(est(minuto=47), [], [], [])["alertas"] if a["clave"].startswith("turno"))
        self.assertIn("Dr. B", alerta["titulo"])

    def test_explica_ip_y_dominio(self):
        ip = Asistente.explicar_expediente(self.builder.construir(deteccion()))
        self.assertIn("Bloquear la IP", ip["resumen"])
        self.assertIn("s1-respaldo.pirata.test", " ".join(ip["puntos"]))
        dom = Asistente.explicar_expediente(self.builder.construir(deteccion(host="live.otro.test", ip="198.51.100.20")))
        self.assertIn("dominio", dom["resumen"])
        self.assertIn("panaderia.test", " ".join(dom["puntos"]))
        self.assertIn("afectaría a terceros", dom["resumen"])
        sin_dns = Asistente.explicar_expediente(self.builder.construir(deteccion(host="live.nuevo.test", ip="10.9.9.9")))
        self.assertIn("no se puede descartar", sin_dns["resumen"])
        self.assertIn("Sin datos de DNS pasivo", " ".join(sin_dns["puntos"]))

    def test_audita_cada_alerta_una_sola_vez_y_no_decide(self):
        self._pendiente()
        exps = list(self.mesa.expedientes.values())
        for _ in range(3):
            self.asis.evaluar(est(minuto=5.0), exps, [], [])
        lineas = Path(self.auditoria.ruta).read_text(encoding="utf-8").splitlines()
        self.assertEqual(sum('"asistente_alerta"' in linea for linea in lineas), 1)
        self.assertTrue(verificar_cadena(self.auditoria.ruta))
        self.assertTrue(all(d.estado == "pendiente" for d in exps))


if __name__ == "__main__":
    unittest.main()
