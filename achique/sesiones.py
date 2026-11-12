"""Ingreso de los jueces: usuarios con contraseña (PBKDF2-SHA256) y sesiones por cookie.

Cada usuario está atado a un juez de datos/juzgados.json. La contraseña nunca se guarda ni se
audita en claro: solo sal + hash. Los usuarios de demostración viven en usuarios_demo.json (las
bases del desafío permiten usuarios y contraseñas de demostración); para crear otro:

  python3 -m achique.sesiones <usuario> <juez_id>     # pide la contraseña e imprime la entrada JSON
"""
import getpass
import hashlib
import hmac
import json
import secrets
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

ITERACIONES = 200_000
DURACION_SESION_SEG = 8 * 3600
MAX_FALLOS, BLOQUEO_SEG = 5, 60.0
COOKIE = "achique_sesion"
USUARIOS_DEMO = Path(__file__).resolve().parent / "usuarios_demo.json"


def hash_clave(clave: str, sal: str, iteraciones: int = ITERACIONES) -> str:
    return hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), bytes.fromhex(sal), iteraciones).hex()


def crear_usuario(usuario: str, juez_id: str, clave: str) -> dict:
    sal = secrets.token_hex(16)
    return {"usuario": usuario, "juez_id": juez_id, "sal": sal, "iteraciones": ITERACIONES,
            "hash": hash_clave(clave, sal)}


class Usuarios:
    """Usuarios de la Mesa (usuario -> juez_id) y verificación de contraseña en tiempo constante."""

    def __init__(self, ruta: Path = USUARIOS_DEMO):
        datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
        self.por_usuario: Dict[str, dict] = {u["usuario"]: u for u in datos["usuarios"]}
        self._ficticio = crear_usuario("-", "-", secrets.token_hex(8))

    def verificar(self, usuario: str, clave: str) -> Optional[str]:
        """juez_id si usuario y contraseña coinciden; None si no (sin revelar cuál de los dos falló)."""
        u = self.por_usuario.get(usuario)
        ref = u or self._ficticio  # mismo costo exista o no el usuario
        ok = hmac.compare_digest(hash_clave(clave, ref["sal"], ref["iteraciones"]), ref["hash"])
        return u["juez_id"] if (u is not None and ok) else None


class Sesiones:
    """Sesiones en memoria (token aleatorio -> juez) y freno a los intentos fallidos por origen."""

    def __init__(self, duracion_seg: float = DURACION_SESION_SEG):
        self.duracion_seg = duracion_seg
        self._lock = threading.Lock()
        self._sesiones: Dict[str, Tuple[str, float]] = {}
        self._fallos: Dict[str, Tuple[int, float]] = {}

    def crear(self, juez_id: str) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._sesiones[token] = (juez_id, time.time() + self.duracion_seg)
        return token

    def juez(self, token: Optional[str]) -> Optional[str]:
        if not token:
            return None
        with self._lock:
            sesion = self._sesiones.get(token)
            if sesion is None:
                return None
            if time.time() >= sesion[1]:
                del self._sesiones[token]
                return None
            return sesion[0]

    def cerrar(self, token: Optional[str]) -> Optional[str]:
        with self._lock:
            sesion = self._sesiones.pop(token or "", None)
        return sesion[0] if sesion else None

    def bloqueado(self, origen: str) -> bool:
        with self._lock:
            n, hasta = self._fallos.get(origen, (0, 0.0))
            return n >= MAX_FALLOS and time.time() < hasta

    def registrar_fallo(self, origen: str) -> None:
        with self._lock:
            n, hasta = self._fallos.get(origen, (0, 0.0))
            if n >= MAX_FALLOS and time.time() >= hasta:
                n = 0
            self._fallos[origen] = (n + 1, time.time() + BLOQUEO_SEG)

    def limpiar_fallos(self, origen: str) -> None:
        with self._lock:
            self._fallos.pop(origen, None)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("uso: python3 -m achique.sesiones <usuario> <juez_id>")
    print(json.dumps(crear_usuario(sys.argv[1], sys.argv[2], getpass.getpass("Contraseña: ")), ensure_ascii=False))
