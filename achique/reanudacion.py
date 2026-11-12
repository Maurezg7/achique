"""Reanudación tras un reinicio: reconstruye el estado desde la auditoría y los expedientes exportados.

Si la plataforma se cae a mitad del partido, al volver a arrancar con el mismo `--log` no empieza
de cero: no vuelve a abrir expedientes por detecciones ya procesadas, muestra otra vez los pendientes
al juez de turno, recuerda qué órdenes ya se enviaron (para no duplicarlas) y sigue su confirmación y
vencimiento. La cadena de auditoría continúa donde quedó. Las sesiones no se guardan: los jueces
vuelven a ingresar.

Si el archivo exportado de un expediente falta, quedó a medio escribir o no verifica su sello, el
expediente se reconstruye con su mismo número desde la detección original del simulador. Queda
auditado y, si estaba aprobado pero sin despachar del todo, vuelve a la Mesa para una nueva decisión.
"""
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .despacho import EstadoOrden
from .evidencia import Expediente, pedir, verificar_expediente

FINALES_SIN_ORDEN_VIVA = ("fallida", "reemplazada")


def leer_eventos(ruta: Path) -> List[Tuple[str, dict]]:
    if not ruta.exists():
        return []
    eventos = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        if linea.strip():
            entrada = json.loads(linea)
            eventos.append((entrada["evento"], entrada.get("datos", {})))
    return eventos


def exportar_expediente(carpeta: Path, exp: Expediente) -> None:
    """Escribe el expediente de forma atómica: un corte a mitad de la escritura no deja un JSON truncado."""
    destino = carpeta / f"{exp.id}.json"
    temporal = destino.with_suffix(".json.tmp")
    temporal.write_text(json.dumps(exp.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporal, destino)


def _leer_expediente(archivo: Path) -> Optional[Expediente]:
    try:
        datos = json.loads(archivo.read_text(encoding="utf-8"))
        return Expediente(**datos) if verificar_expediente(datos) else None
    except (OSError, ValueError, TypeError):
        return None


def _reconstruir(exp_id: str, deteccion_id: str, ingesta, builder) -> Optional[Expediente]:
    try:
        detecciones = pedir(ingesta.base, "/detecciones?desde=-1")["detecciones"]
        original = next((d for d in detecciones if d["id"] == deteccion_id), None)
        return builder.construir(original, exp_id) if original else None
    except Exception:
        return None


def reanudar(ruta_log: Path, carpeta_expedientes: Path, mesa, builder, ingesta, despachador, gestor,
             auditoria) -> Optional[dict]:
    """Devuelve un resumen de lo recuperado, o None si el log estaba vacío (arranque normal)."""
    eventos = leer_eventos(ruta_log)
    if not any(ev != "plataforma_iniciada" for ev, _ in eventos):
        return None

    # 1. Detecciones ya procesadas: no se vuelven a evaluar.
    for ev, d in eventos:
        if ev in ("expediente_creado", "deteccion_descartada", "deteccion_reiterada") and d.get("deteccion_id"):
            ingesta._vistos.add(d["deteccion_id"])

    # 2. Expedientes exportados, en el orden en que se crearon.
    expedientes: Dict[str, Expediente] = {}
    reconstruidos = set()
    for ev, d in eventos:
        if ev != "expediente_creado" or d["expediente_id"] in expedientes:
            continue
        exp_id = d["expediente_id"]
        # El número se reserva aunque el expediente no se recupere: un id nunca se reutiliza.
        numero = re.search(r"(\d+)$", exp_id)
        if numero:
            builder._contador = max(builder._contador, int(numero.group(1)))
        exp = _leer_expediente(carpeta_expedientes / f"{exp_id}.json")
        if exp is None or exp.id != exp_id:
            exp = _reconstruir(exp_id, d.get("deteccion_id", ""), ingesta, builder)
            if exp is None:
                auditoria.registrar("expediente_no_recuperado", expediente_id=exp_id,
                                    deteccion_id=d.get("deteccion_id"), hash_original=d.get("hash_expediente"))
                continue
            exportar_expediente(carpeta_expedientes, exp)
            reconstruidos.add(exp_id)
            auditoria.registrar("expediente_reconstruido", expediente_id=exp_id, deteccion_id=exp.deteccion_id,
                                hash_original=d.get("hash_expediente"), hash_expediente=exp.hash_expediente,
                                motivo="el archivo exportado faltaba o no verificaba su sello")
        expedientes[exp.id] = exp
        mesa.nuevo_expediente(exp)
        gestor.registrar_host_pirata(exp.host_stream)
    for ev, d in eventos:
        if ev == "deteccion_reiterada" and d.get("expediente_id") in expedientes:
            mesa.agregar_deteccion(d["expediente_id"], {"id": d["deteccion_id"], "minuto": d["minuto"]},
                                   d.get("hash_deteccion", ""))

    # 3. Decisiones del juez y reasignaciones por cambio de turno, en orden.
    with mesa.lock:
        for ev, d in eventos:
            decision = mesa.expedientes.get(d.get("expediente_id", ""))
            if decision is None:
                continue
            if ev == "decision_juez":
                decision.estado = d["decision"]
                decision.decidido_por = d.get("juez_id")
                decision.minuto_decision = d.get("minuto")
                decision.motivo_rechazo = d.get("motivo")
                decision.decidido_min = decision.creado_ts
            elif ev == "expediente_reasignado":
                decision.estado, decision.decidido_por, decision.minuto_decision = "pendiente", None, None

    # 4. Órdenes enviadas y su último estado conocido; el seguimiento las vuelve a consultar.
    ordenes: Dict[Tuple[str, str], EstadoOrden] = {}
    reintentos: Dict[Tuple[str, str], int] = {}
    seq = 0
    for ev, d in eventos:
        clave = (d.get("proveedor", ""), d.get("orden_id", ""))
        if ev in ("orden_enviada", "orden_rechazada"):
            exp = expedientes.get(d["expediente_id"])
            n = reintentos.get((d["proveedor"], d["expediente_id"]), 0)
            orden = EstadoOrden(d["proveedor"], d["orden_id"], d["expediente_id"], d["tipo"], d["objetivo"],
                                d["vence_min"], estado="recibida" if ev == "orden_enviada" else "rechazada",
                                intentos=n, minuto_deteccion=exp.minuto_deteccion if exp else None,
                                juez_id=d.get("juez_id", ""))
            ordenes[clave] = orden
            mesa.registrar_orden_enviada(dict(orden_id=orden.orden_id, expediente_id=orden.expediente_id,
                                              tipo=orden.tipo, objetivo=orden.objetivo, vence_min=orden.vence_min,
                                              juzgado_id=d.get("juzgado_id", ""), juez_id=orden.juez_id),
                                         orden.proveedor_id, d.get("respuesta") or {"estado": orden.estado})
            numero = re.search(r"-(\d+)$", d["orden_id"])
            if numero:
                seq = max(seq, int(numero.group(1)))
        elif ev == "reintento_orden":
            reintentos[(d["proveedor"], d["expediente_id"])] = d.get("intento", 1)
            if clave in ordenes:
                ordenes[clave].estado = "reemplazada"
        elif ev == "reintento_requiere_juez_de_turno" and clave in ordenes:
            ordenes[clave].estado = "reemplazada"
        elif ev == "reintento_descartado_por_vencimiento":
            for o in ordenes.values():
                if o.proveedor_id == d.get("proveedor") and o.expediente_id == d.get("expediente_id") \
                        and o.estado == "fallida":
                    o.estado = "reemplazada"
        elif ev == "orden_confirmada" and clave in ordenes:
            ordenes[clave].estado = "aplicada"
            mesa.actualizar_orden(clave[0], clave[1], {"estado": "aplicada", "aplicada_min": d.get("aplicada_min")})
        elif ev.startswith("orden_") and ev[6:] in ("fallida", "vencida", "levantada") and clave in ordenes:
            ordenes[clave].estado = ev[6:]
            mesa.actualizar_orden(clave[0], clave[1], {"estado": ev[6:], "finalizada_min": d.get("minuto")})
    with despachador._lock:
        for (pid, oid), orden in ordenes.items():
            despachador.ordenes[f"{pid}:{oid}"] = orden
        despachador._seq = max(despachador._seq, seq)

    # 5. Un expediente aprobado cuenta como despachado solo si todos los proveedores ya tienen su orden;
    #    si no, el hilo de despacho completa lo que falta (sin duplicar lo ya enviado).
    proveedores = {p["id"] for p in despachador.proveedores}
    with mesa.lock:
        for exp_id, decision in mesa.expedientes.items():
            if decision.estado != "aprobado":
                continue
            con_orden = {o.proveedor_id for o in ordenes.values()
                         if o.expediente_id == exp_id and o.estado not in FINALES_SIN_ORDEN_VIVA}
            sin_capacidad = {d["proveedor"] for ev, d in eventos
                             if ev == "proveedor_sin_capacidad" and d.get("expediente_id") == exp_id}
            if proveedores <= con_orden | sin_capacidad:
                decision.estado = "despachado"
    # Lo aprobado sobre un expediente que hubo que reconstruir no se firma sin que el juez lo vuelva a ver.
    for exp_id in sorted(reconstruidos):
        if mesa.expedientes[exp_id].estado == "aprobado":
            mesa.devolver_a_pendiente(exp_id, "expediente reconstruido tras el reinicio: requiere nueva decisión")

    # 6. Reclamos ya resueltos no se vuelven a proponer; los demás se releen del simulador.
    for ev, d in eventos:
        if ev == "reclamo_resuelto":
            gestor._vistos.add(d["reclamo_id"])

    resumen = {"expedientes": len(expedientes), "pendientes": len(mesa.pendientes_expedientes()),
               "ordenes": len(ordenes), "detecciones_vistas": len(ingesta._vistos),
               "reconstruidos": len(reconstruidos)}
    auditoria.registrar("plataforma_reanudada", **resumen)
    return resumen
