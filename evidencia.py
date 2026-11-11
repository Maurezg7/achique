"""Expediente: arma y verifica la evidencia de cada detección antes de recomendar un bloqueo."""
import hashlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def pedir(base: str, ruta: str, cuerpo: Optional[dict] = None, metodo: str = "GET") -> Any:
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    req = urllib.request.Request(base + ruta, data=datos, method=metodo,
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return json.loads(err.read())


@dataclass
class Expediente:
    id: str
    deteccion_id: str
    minuto_deteccion: float
    host_stream: str
    pagina: str
    ip_servidor: str
    asn: int
    marca_de_agua: str
    prefijo_coincidente: str
    dominios_en_la_ip: List[str]
    riesgo_colateral: bool
    tipo_recomendado: str          # "ip" | "dominio"
    objetivo_recomendado: str
    hash_captura: str
    sellos_tiempo: List[float]
    vencimiento_propuesto: int
    promocion: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


class ExpedienteBuilder:
    """Verifica cada detección contra /partido y /dns-pasivo antes de recomendar un bloqueo.

    Reglas (ver README del desafío):
    - La marca de agua tiene que coincidir con un prefijo válido del partido (oficial o de
      un licenciatario). Si no coincide con ninguno, no es la señal del partido: se descarta.
    - Si coincide con el prefijo de un licenciatario Y el host es uno de sus dominios
      autorizados, es retransmisión legítima: se descarta (evita el falso positivo).
    - Cualquier otro caso con marca válida es señal pirata (incluida una marca de
      licenciatario usada fuera de su propio dominio: retransmisión no autorizada).
    - Riesgo colateral: si la IP del servidor aparece con más de un dominio en el DNS
      pasivo, es una IP compartida (CDN/hosting); se recomienda bloqueo por dominio en
      vez de por IP, aunque eso implique no cortar de inmediato un posible espejo en la
      misma IP (se prioriza no afectar servicios legítimos).
    """

    def __init__(self, base: str):
        self.base = base
        partido = pedir(base, "/partido")
        self.marcas_validas: List[dict] = partido["marcas_de_agua_validas"]
        self.dominio_a_prefijo: Dict[str, str] = {
            dom: lic["prefijo_marca"]
            for lic in partido.get("licenciatarios", [])
            for dom in lic["dominios_autorizados"]
        }
        self.fin_min = int(partido["fin_min"])
        self._contador = 0

    def _prefijo_de(self, marca: str) -> Optional[str]:
        for m in self.marcas_validas:
            if marca.startswith(m["prefijo"]):
                return m["prefijo"]
        return None

    def construir(self, deteccion: dict) -> Optional[Expediente]:
        marca = deteccion.get("marca_de_agua_extraida", "")
        host = deteccion["host_stream"]
        prefijo = self._prefijo_de(marca)
        if prefijo is None:
            return None  # Ninguna marca válida del partido: no corresponde evidencia de piratería.
        if self.dominio_a_prefijo.get(host) == prefijo:
            return None  # Licenciatario retransmitiendo legalmente en su propio dominio.

        ip = deteccion["ip_servidor"]
        dns = pedir(self.base, f"/dns-pasivo?ip={ip}")
        dominios_en_ip = dns.get("dominios", []) if dns.get("ip") else [host]
        riesgo = len(set(dominios_en_ip) - {host}) > 0
        tipo, objetivo = ("dominio", host) if riesgo else ("ip", ip)

        self._contador += 1
        captura = deteccion.get("captura", {})
        hash_captura = hashlib.sha256(captura.get("contenido_b64", "").encode("utf-8")).hexdigest()

        return Expediente(
            id=f"EXP-2026-{self._contador:06d}",
            deteccion_id=deteccion["id"],
            minuto_deteccion=deteccion["minuto"],
            host_stream=host,
            pagina=deteccion.get("pagina", ""),
            ip_servidor=ip,
            asn=deteccion.get("asn", 0),
            marca_de_agua=marca,
            prefijo_coincidente=prefijo,
            dominios_en_la_ip=dominios_en_ip,
            riesgo_colateral=riesgo,
            tipo_recomendado=tipo,
            objetivo_recomendado=objetivo,
            hash_captura=hash_captura,
            sellos_tiempo=[captura.get("capturada_min", deteccion["minuto"])],
            vencimiento_propuesto=self.fin_min,
            promocion=deteccion.get("promocion", []),
        )
