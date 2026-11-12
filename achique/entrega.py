"""Arma los entregables del partido final en entrega/ en un solo paso.

  python3 -m achique.entrega --registro ../desafio-futbol/salida/registro.jsonl \
      --auditoria ../desafio-futbol/salida/auditoria.jsonl \
      --expedientes ../desafio-futbol/salida/expedientes \
      --verificar ../desafio-futbol/evaluacion/verificar.py

Copia la auditoría completa, elige un expediente por dominio (con riesgo colateral) y uno por IP,
verifica la cadena y los sellos, y guarda la salida de evaluacion/verificar.py. Todo con nombres
`*_final*` para no pisar los ejemplos de la práctica.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from .auditoria import verificar_cadena
from .evidencia import verificar_expediente


def elegir_expedientes(carpeta: Path) -> dict:
    """Un expediente por dominio (riesgo colateral) y uno por IP, si los hay."""
    elegidos = {}
    for archivo in sorted(carpeta.glob("EXP-*.json")):
        exp = json.loads(archivo.read_text(encoding="utf-8"))
        clave = "dominio" if exp.get("riesgo_colateral") else "ip"
        elegidos.setdefault(clave, archivo)
    return elegidos


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Entregables del partido final en entrega/")
    ap.add_argument("--registro", required=True, help="log del simulador (para verificar.py)")
    ap.add_argument("--auditoria", required=True, help="log de auditoría de la plataforma")
    ap.add_argument("--expedientes", required=True, help="carpeta salida/expedientes")
    ap.add_argument("--verificar", required=True, help="ruta a evaluacion/verificar.py del repo oficial")
    ap.add_argument("--destino", default=str(Path(__file__).resolve().parent.parent / "entrega"))
    args = ap.parse_args(argv)
    destino = Path(args.destino)
    destino.mkdir(parents=True, exist_ok=True)
    problemas = []

    auditoria = Path(args.auditoria)
    shutil.copyfile(auditoria, destino / "auditoria_final.jsonl")
    cadena = verificar_cadena(auditoria)
    print(f"auditoria_final.jsonl ← {auditoria} · cadena íntegra: {'SÍ' if cadena else 'NO'}")
    if not cadena:
        problemas.append("la cadena de auditoría no verifica")

    for clave, archivo in elegir_expedientes(Path(args.expedientes)).items():
        datos = json.loads(archivo.read_text(encoding="utf-8"))
        ok = verificar_expediente(datos)
        nombre = "expediente_final.json" if clave == "dominio" else "expediente_final_ip.json"
        shutil.copyfile(archivo, destino / nombre)
        print(f"{nombre} ← {archivo.name} ({datos['tipo_recomendado']} {datos['objetivo_recomendado']}) · "
              f"sello íntegro: {'SÍ' if ok else 'NO'}")
        if not ok:
            problemas.append(f"{archivo.name} no verifica")

    salida = subprocess.run([sys.executable, args.verificar, "--log", args.registro],
                            capture_output=True, text=True)
    texto = salida.stdout + salida.stderr
    (destino / "evaluacion_final.txt").write_text(texto, encoding="utf-8")
    resumen = [l.strip() for l in texto.splitlines() if l.startswith("  ") and ":" in l][:14]
    print("evaluacion_final.txt ← verificar.py\n  " + "\n  ".join(resumen))
    if salida.returncode != 0:
        problemas.append(f"verificar.py terminó con código {salida.returncode}")

    print("Listo: revisá, commiteá y pusheá entrega/ antes del cierre." if not problemas
          else "ATENCIÓN: " + "; ".join(problemas))
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
