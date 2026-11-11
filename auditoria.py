"""Registro de auditoría inalterable: una cadena de hashes, como un mini blockchain de logs.

Cada línea incluye el hash de la línea anterior. Si alguien edita o borra una línea del
archivo, todos los hashes posteriores dejan de coincidir y `verificar_cadena` lo detecta.
Es append-only: no hay método para editar ni borrar una entrada ya escrita.
"""
import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


GENESIS = "0" * 64


def _hash_entrada(seq: int, ts: float, evento: str, datos: dict, hash_anterior: str) -> str:
    canonico = json.dumps({"seq": seq, "ts": ts, "evento": evento, "datos": datos,
                           "hash_anterior": hash_anterior}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


class RegistroAuditoria:
    def __init__(self, ruta: Path):
        self.ruta = ruta
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._seq = 0
        self._ultimo_hash = GENESIS
        if self.ruta.exists():
            with open(self.ruta, encoding="utf-8") as f:
                for linea in f:
                    if linea.strip():
                        entrada = json.loads(linea)
                        self._seq = entrada["seq"]
                        self._ultimo_hash = entrada["hash"]
        self._archivo = open(self.ruta, "a", encoding="utf-8")

    def registrar(self, evento: str, **datos: Any) -> dict:
        with self._lock:
            self._seq += 1
            ts = time.time()
            h = _hash_entrada(self._seq, ts, evento, datos, self._ultimo_hash)
            entrada = {"seq": self._seq, "ts": ts, "evento": evento, "datos": datos,
                      "hash_anterior": self._ultimo_hash, "hash": h}
            self._archivo.write(json.dumps(entrada, ensure_ascii=False) + "\n")
            self._archivo.flush()
            self._ultimo_hash = h
            return entrada


def verificar_cadena(ruta: Path) -> bool:
    """Recalcula la cadena de principio a fin. Lo puede correr cualquiera (juez, proveedor,
    auditor externo) para confirmar que el registro no fue alterado."""
    anterior = GENESIS
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            if not linea.strip():
                continue
            e = json.loads(linea)
            esperado = _hash_entrada(e["seq"], e["ts"], e["evento"], e["datos"], anterior)
            if esperado != e["hash"] or e["hash_anterior"] != anterior:
                return False
            anterior = e["hash"]
    return True


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Verifica la integridad del registro de auditoría")
    ap.add_argument("ruta", type=Path)
    args = ap.parse_args()
    ok = verificar_cadena(args.ruta)
    print("Cadena íntegra: SÍ" if ok else "Cadena íntegra: NO — el archivo fue alterado")
