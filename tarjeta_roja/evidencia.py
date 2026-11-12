"""Expediente: arma y verifica la evidencia de cada detección antes de recomendar un bloqueo."""
import base64
import binascii
import hashlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# Pistas en el nombre de la organización del ASN de que la IP es infraestructura compartida.
PISTAS_INFRA_COMPARTIDA = ("cdn", "compartido", "shared")
# Campos que no entran en el sello: el propio sello y lo que se agrega después de crear el expediente.
CAMPOS_FUERA_DEL_SELLO = ("hash_expediente", "detecciones_adicionales")


def pedir(base: str, ruta: str, cuerpo: Optional[dict] = None, metodo: str = "GET") -> Any:
    """Hace un pedido JSON al simulador y devuelve la respuesta ya decodificada.

    Ante un error HTTP (4xx/5xx) no lanza excepción: devuelve el cuerpo JSON del error, para
    que quien llama pueda leer el estado o el motivo que informa el simulador.
    """
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    req = urllib.request.Request(base + ruta, data=datos, method=metodo,
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return json.loads(err.read())


def sha256_json(obj: Any) -> str:
    """Hash SHA-256 de la forma canónica (claves ordenadas) de un objeto JSON."""
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def dominio_base(host: str) -> str:
    """Dominio registrable aproximado (las dos últimas etiquetas): s1.pelotaya.test -> pelotaya.test."""
    return ".".join(host.lower().rstrip(".").split(".")[-2:])


def hash_captura(captura: dict) -> str:
    """SHA-256 de los bytes reales de la captura (base64 decodificado); si no decodifica, del texto."""
    contenido = captura.get("contenido_b64", "")
    try:
        crudo = base64.b64decode(contenido, validate=True)
    except (binascii.Error, ValueError):
        crudo = contenido.encode("utf-8")
    return hashlib.sha256(crudo).hexdigest()


def sellar_expediente(datos: dict) -> str:
    """Sello de integridad del expediente: hash de toda la evidencia original."""
    return sha256_json({k: v for k, v in datos.items() if k not in CAMPOS_FUERA_DEL_SELLO})


def verificar_expediente(datos: dict) -> bool:
    """True si el expediente exportado no fue alterado desde que se selló."""
    return datos.get("hash_expediente") == sellar_expediente(datos)


@dataclass
class Expediente:
    """Toda la evidencia de una detección pirata, lista para que el juez decida."""
    id: str
    deteccion_id: str
    minuto_deteccion: float
    host_stream: str
    stream_url: str
    pagina: str
    ip_servidor: str
    asn: int
    organizacion: str
    marca_de_agua: str
    prefijo_coincidente: str
    origen_marca: str
    dominios_en_la_ip: List[str]
    otros_sitios_en_la_ip: List[str]
    riesgo_colateral: bool
    motivo_riesgo: str
    tipo_recomendado: str          # "ip" | "dominio"
    objetivo_recomendado: str
    hash_captura: str
    captura_formato: str
    captura_duracion_seg: float
    hash_deteccion: str
    sellos_tiempo: List[float]
    sello_utc: str
    vencimiento_propuesto: int
    verificaciones: List[str]
    promocion: List[dict] = field(default_factory=list)
    detecciones_adicionales: List[dict] = field(default_factory=list)
    hash_expediente: str = ""

    def to_dict(self) -> dict:
        return json.loads(json.dumps(self.__dict__))

    def sellar(self) -> None:
        self.hash_expediente = sellar_expediente(self.to_dict())


class ExpedienteBuilder:
    """Verifica cada detección contra /partido y /dns-pasivo antes de recomendar un bloqueo.

    Reglas (ver README del desafío):
    - La marca de agua tiene que coincidir con un prefijo válido del partido (oficial o de
      un licenciatario). Si no coincide con ninguno, no es la señal del partido: se descarta.
    - Si coincide con el prefijo de un licenciatario Y el host es uno de sus dominios
      autorizados, es retransmisión legítima: se descarta (evita el falso positivo).
    - Cualquier otro caso con marca válida es señal pirata (incluida una marca de
      licenciatario usada fuera de su propio dominio: retransmisión no autorizada).
    - Riesgo colateral: si en la IP aparecen dominios de OTRO sitio (otro dominio base), o el
      ASN es una CDN / hosting compartido, o no hay datos de DNS pasivo, se recomienda bloqueo
      por dominio. Los espejos del mismo sitio pirata (s1 y s1-respaldo.pelotaya.test) no son
      daño colateral: ahí conviene bloquear la IP, que corta también al espejo.
    """

    def __init__(self, base: str):
        self.base = base
        partido = pedir(base, "/partido")
        self.partido_id = partido.get("id", "")
        self.marcas_validas: List[dict] = partido["marcas_de_agua_validas"]
        self.dominio_a_prefijo: Dict[str, str] = {
            dominio: licenciatario["prefijo_marca"]
            for licenciatario in partido.get("licenciatarios", [])
            for dominio in licenciatario["dominios_autorizados"]
        }
        self.fin_min = int(partido["fin_min"])
        self._contador = 0

    def _marca_valida(self, marca: str) -> Optional[dict]:
        """Devuelve la marca válida del partido con cuyo prefijo empieza la marca, o None."""
        for marca_valida in self.marcas_validas:
            if marca and marca.startswith(marca_valida["prefijo"]):
                return marca_valida
        return None

    def motivo_descarte(self, deteccion: dict) -> Optional[str]:
        """Por qué una detección NO es señal pirata del partido, o None si sí lo es."""
        marca = deteccion.get("marca_de_agua_extraida") or ""
        valida = self._marca_valida(marca)
        if valida is None:
            return f"La marca de agua '{marca or 'ninguna'}' no corresponde a este partido"
        if self.dominio_a_prefijo.get(deteccion["host_stream"]) == valida["prefijo"]:
            return "Licenciatario autorizado retransmitiendo en su propio dominio"
        return None

    def _evaluar_riesgo_colateral(self, ip: str, host: str) -> Tuple[dict, List[str], bool, str]:
        """Consulta el DNS pasivo de la IP. Devuelve (dns, otros_sitios, riesgo, motivo)."""
        dns = pedir(self.base, f"/dns-pasivo?ip={ip}")
        if not dns.get("ip"):
            return dns, [], True, "Sin datos de DNS pasivo para la IP: por prudencia se bloquea el dominio"
        base = dominio_base(host)
        otros = sorted(d for d in dns.get("dominios", []) if dominio_base(d) != base)
        organizacion = (dns.get("organizacion") or "").lower()
        if otros:
            return dns, otros, True, f"La IP también sirve {len(otros)} sitio(s) de otros dominios"
        if any(pista in organizacion for pista in PISTAS_INFRA_COMPARTIDA):
            return dns, otros, True, f"El ASN es infraestructura compartida ({dns.get('organizacion')})"
        return dns, otros, False, "La IP solo sirve dominios del mismo sitio pirata"

    def construir(self, deteccion: dict) -> Optional[Expediente]:
        """Arma el expediente de una detección, o devuelve None si no es señal pirata."""
        if self.motivo_descarte(deteccion):
            return None
        marca = deteccion["marca_de_agua_extraida"]
        valida = self._marca_valida(marca)
        host, ip = deteccion["host_stream"], deteccion["ip_servidor"]
        dns, otros, riesgo, motivo = self._evaluar_riesgo_colateral(ip, host)
        tipo, objetivo = ("dominio", host) if riesgo else ("ip", ip)
        captura = deteccion.get("captura", {})
        asn = deteccion.get("asn", 0)

        verificaciones = [
            f"Marca de agua {marca} coincide con '{valida['origen']}' ({valida['prefijo']})",
            f"{host} no es dominio autorizado de un licenciatario",
            f"Servidor del video: {host} → {ip} (ASN {asn}, {dns.get('organizacion') or 'organización desconocida'})",
            motivo,
            f"Captura {captura.get('formato', '?')} de {captura.get('duracion_seg', '?')} s, SHA-256 calculado",
        ]
        if dns.get("asn") is not None and dns.get("asn") != asn:
            verificaciones.append(f"ATENCIÓN: el ASN del DNS pasivo ({dns.get('asn')}) difiere del detectado ({asn})")

        self._contador += 1
        exp = Expediente(
            id=f"EXP-2026-{self._contador:06d}",
            deteccion_id=deteccion["id"],
            minuto_deteccion=deteccion["minuto"],
            host_stream=host,
            stream_url=deteccion.get("stream_url", ""),
            pagina=deteccion.get("pagina", ""),
            ip_servidor=ip,
            asn=asn,
            organizacion=dns.get("organizacion") or "",
            marca_de_agua=marca,
            prefijo_coincidente=valida["prefijo"],
            origen_marca=valida["origen"],
            dominios_en_la_ip=dns.get("dominios", [host]),
            otros_sitios_en_la_ip=otros,
            riesgo_colateral=riesgo,
            motivo_riesgo=motivo,
            tipo_recomendado=tipo,
            objetivo_recomendado=objetivo,
            hash_captura=hash_captura(captura),
            captura_formato=captura.get("formato", ""),
            captura_duracion_seg=captura.get("duracion_seg", 0),
            hash_deteccion=sha256_json(deteccion),
            sellos_tiempo=[captura.get("capturada_min", deteccion["minuto"])],
            sello_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            vencimiento_propuesto=self.fin_min,
            verificaciones=verificaciones,
            promocion=deteccion.get("promocion", []),
        )
        exp.sellar()
        return exp


if __name__ == "__main__":
    import argparse
    from pathlib import Path
    ap = argparse.ArgumentParser(description="Verifica el sello de integridad de un expediente exportado")
    ap.add_argument("ruta", type=Path)
    args = ap.parse_args()
    ok = verificar_expediente(json.loads(args.ruta.read_text(encoding="utf-8")))
    print("Expediente íntegro: SÍ" if ok else "Expediente íntegro: NO — fue alterado")
