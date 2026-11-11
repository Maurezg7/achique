"""Punto de entrada: arma la plataforma completa y la corre contra el simulador.

Hilos:
  - principal: ingesta de detecciones -> construye expedientes -> Mesa (NO auto-aprueba)
  - despacho:  firma y envía las órdenes que el juez aprobó, reintenta fallidas
  - reclamos:  revisa reclamos nuevos, propone resolución, ejecuta las que el juez aprobó
  - juez HTTP: dashboard donde un humano aprueba/rechaza (servidor_juez.py)

Uso:
  python plataforma.py --simulador http://localhost:8000 --puerto-juez 8080
"""
import argparse
import threading
import time
from pathlib import Path

from auditoria import RegistroAuditoria
from despacho import Despachador, hilo_despacho
from evidencia import ExpedienteBuilder, pedir
from firmas import RegistroJueces
from mesa import Mesa
from reclamos import GestorReclamos, hilo_reclamos
from servidor_juez import iniciar_servidor_juez


def hilo_ingesta(base: str, mesa: Mesa, builder: ExpedienteBuilder, gestor: GestorReclamos,
                  detener: threading.Event) -> None:
    vistos = set()
    while not detener.is_set():
        try:
            detecciones = pedir(base, "/detecciones")["detecciones"]
            for d in detecciones:
                if d["id"] in vistos:
                    continue
                vistos.add(d["id"])
                exp = builder.construir(d)
                if exp is None:
                    continue  # no es señal pirata (transmisión legítima del licenciatario)
                mesa.nuevo_expediente(exp)
                gestor.registrar_host_pirata(exp.host_stream)
        except Exception as e:
            print(f"[ingesta] error: {e}")
        time.sleep(1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--simulador", default="http://localhost:8000")
    ap.add_argument("--puerto-juez", type=int, default=8080)
    ap.add_argument("--log", default="salida/registro_plataforma.jsonl")
    ap.add_argument("--juzgados", default="datos/juzgados.json")
    args = ap.parse_args()

    base = args.simulador
    mesa = Mesa()
    jueces = RegistroJueces(base, Path(args.juzgados))
    auditoria = RegistroAuditoria(Path(args.log))
    builder = ExpedienteBuilder(base)
    despachador = Despachador(base, mesa, jueces, auditoria)
    gestor_reclamos = GestorReclamos(base, mesa, despachador)

    detener = threading.Event()
    hilos = [
        threading.Thread(target=hilo_ingesta, args=(base, mesa, builder, gestor_reclamos, detener), daemon=True),
        threading.Thread(target=hilo_despacho, args=(despachador, mesa, detener), daemon=True),
        threading.Thread(target=hilo_reclamos, args=(gestor_reclamos, detener), daemon=True),
    ]
    for h in hilos:
        h.start()
    servidor_juez = iniciar_servidor_juez(mesa, base, args.puerto_juez)

    print(f"Plataforma en marcha. Dashboard del juez: http://localhost:{args.puerto_juez}/")
    print(f"Auditoría: {args.log}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nDeteniendo...")
        detener.set()
        servidor_juez.shutdown()


if __name__ == "__main__":
    main()
