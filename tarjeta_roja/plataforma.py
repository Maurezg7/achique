"""Tarjeta Roja — punto de entrada: arma la plataforma completa y la corre contra el simulador.

Hilos:
  - ingesta:   detecciones -> verifica y arma expedientes -> Mesa (NO auto-aprueba)
  - despacho:  firma y envía las órdenes que el juez aprobó, sigue confirmaciones, reintenta fallidas
  - reclamos:  revisa reclamos nuevos, propone resolución, ejecuta las que el juez aprobó
  - juez HTTP: dashboard donde un humano aprueba/rechaza y registro público (servidor_juez.py)

Uso (desde la raíz del repo o con el repo en el PYTHONPATH):
  python3 plataforma.py --simulador http://localhost:8000 --puerto-juez 8090
  python3 -m tarjeta_roja --simulador http://localhost:8000 --puerto-juez 8090
"""
import argparse
import json
import threading
import time
from pathlib import Path

from .auditoria import RegistroAuditoria, verificar_cadena
from .despacho import INTERVALO_SEG, Despachador, hilo_despacho
from .evidencia import ExpedienteBuilder, pedir, sha256_json
from .firmas import RegistroJueces
from .mesa import Mesa
from .reclamos import GestorReclamos, hilo_reclamos
from .servidor_juez import iniciar_servidor_juez


class Ingesta:
    """Lee detecciones nuevas, arma su expediente y lo deja pendiente en la Mesa para el juez."""

    def __init__(self, base: str, mesa: Mesa, builder: ExpedienteBuilder, gestor: GestorReclamos,
                 auditoria: RegistroAuditoria, carpeta_expedientes: Path):
        self.base, self.mesa, self.builder, self.gestor = base, mesa, builder, gestor
        self.auditoria = auditoria
        self.carpeta = carpeta_expedientes
        self.carpeta.mkdir(parents=True, exist_ok=True)
        self._vistos = set()
        self._desde = -1.0

    def procesar(self, deteccion: dict) -> None:
        if deteccion["id"] in self._vistos:
            return
        self._vistos.add(deteccion["id"])
        datos = dict(deteccion_id=deteccion["id"], minuto=deteccion["minuto"], host=deteccion["host_stream"],
                     ip=deteccion["ip_servidor"], hash_deteccion=sha256_json(deteccion))
        motivo = self.builder.motivo_descarte(deteccion)
        if motivo:
            self.auditoria.registrar("deteccion_descartada", motivo=motivo,
                                     marca=deteccion.get("marca_de_agua_extraida"), **datos)
            return
        existente = self.mesa.expediente_por_servidor(deteccion["host_stream"], deteccion["ip_servidor"])
        if existente is not None:
            # Mismo servidor ya en un expediente: se suma como evidencia, sin otra orden ni otra firma.
            self.mesa.agregar_deteccion(existente.expediente.id, deteccion, datos["hash_deteccion"])
            self.auditoria.registrar("deteccion_reiterada", expediente_id=existente.expediente.id, **datos)
            return
        exp = self.builder.construir(deteccion)
        self.mesa.nuevo_expediente(exp)
        self.gestor.registrar_host_pirata(exp.host_stream)
        (self.carpeta / f"{exp.id}.json").write_text(json.dumps(exp.to_dict(), ensure_ascii=False, indent=2),
                                                     encoding="utf-8")
        self.auditoria.registrar("expediente_creado", expediente_id=exp.id, hash_expediente=exp.hash_expediente,
                                 hash_captura=exp.hash_captura, tipo_recomendado=exp.tipo_recomendado,
                                 objetivo_recomendado=exp.objetivo_recomendado, riesgo_colateral=exp.riesgo_colateral,
                                 motivo_riesgo=exp.motivo_riesgo, **datos)

    def ciclo(self, detener: threading.Event) -> None:
        while not detener.is_set():
            try:
                lote = pedir(self.base, f"/detecciones?desde={self._desde}")
                for deteccion in lote["detecciones"]:
                    self.procesar(deteccion)
                self._desde = lote["minuto_actual"]
            except Exception as e:
                print(f"[ingesta] error: {e}")
            time.sleep(INTERVALO_SEG)


def main() -> None:
    ap = argparse.ArgumentParser(description="Tarjeta Roja: plataforma federal de órdenes de bloqueo en vivo")
    ap.add_argument("--simulador", default="http://localhost:8000")
    ap.add_argument("--puerto-juez", type=int, default=8090)
    ap.add_argument("--log", default="salida/registro_plataforma.jsonl")
    ap.add_argument("--juzgados", default="datos/juzgados.json")
    ap.add_argument("--local", default="Azul Juniors", help="nombre del equipo local en el marcador (solo visual)")
    ap.add_argument("--visitante", default="Rojo Plate", help="nombre del equipo visitante en el marcador (solo visual)")
    args = ap.parse_args()

    base = args.simulador
    auditoria = RegistroAuditoria(Path(args.log))
    mesa = Mesa(auditoria)
    jueces = RegistroJueces(base, Path(args.juzgados))
    builder = ExpedienteBuilder(base)
    despachador = Despachador(base, mesa, jueces, auditoria)
    licenciatarios = {d for p in pedir(base, "/partido").get("licenciatarios", []) for d in p["dominios_autorizados"]}
    gestor_reclamos = GestorReclamos(base, mesa, despachador, licenciatarios)
    ingesta = Ingesta(base, mesa, builder, gestor_reclamos, auditoria, Path(args.log).parent / "expedientes")
    auditoria.registrar("plataforma_iniciada", simulador=base, partido=builder.partido_id,
                        proveedores=[p["id"] for p in despachador.proveedores])

    detener = threading.Event()
    hilos = [
        threading.Thread(target=ingesta.ciclo, args=(detener,), daemon=True),
        threading.Thread(target=hilo_despacho, args=(despachador, mesa, detener), daemon=True),
        threading.Thread(target=hilo_reclamos, args=(gestor_reclamos, detener), daemon=True),
    ]
    for hilo in hilos:
        hilo.start()
    servidor_juez = iniciar_servidor_juez(mesa, base, args.puerto_juez, despachador, (args.local, args.visitante))

    print(f"Tarjeta Roja en marcha. Mesa del juez: http://localhost:{args.puerto_juez}/")
    print(f"Registro público de transparencia: http://localhost:{args.puerto_juez}/transparencia")
    print(f"Auditoría: {args.log}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nDeteniendo...")
        detener.set()
        servidor_juez.shutdown()
        print("Cadena de auditoría íntegra:", "SÍ" if verificar_cadena(Path(args.log)) else "NO")


if __name__ == "__main__":
    main()
