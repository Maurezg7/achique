# AGENTS.md — guía para agentes de código (Devin y otros)

Plataforma de bloqueo de streaming pirata para el **Desafío Fútbol** (hackathon). Corre contra un
**simulador** oficial; no bloquea nada real. Lo que se evalúa es lo que esté en el repo al cierre.

## Reglas duras (no negociables)
- **Python 3.9+ y solo librería estándar.** No agregues dependencias.
- **Nunca se firma sin aprobación de un juez humano.** Solo `tarjeta_roja/despacho.py` llama a `firmas.py`, y solo
  sobre decisiones "aprobadas" en `mesa.py`. No agregues auto-aprobación, ni siquiera "para probar".
- **El juez de turno se resuelve en el instante de firmar** (`RegistroJueces.de_turno_ahora`), nunca se cachea.
- **La auditoría es una cadena de hashes** (`auditoria.py`). No la edites a mano ni cambies el formato de
  `_hash_entrada` sin actualizar `verificar_cadena`. `verificar_cadena()` debe seguir dando `True`.
- **Sin datos personales ni claves reales.** Solo las claves de demo de `datos/juzgados.json`.
- **Nada ofensivo:** solo se habla con el simulador (`--simulador`). Sin escaneos ni tráfico a terceros.
- No subas videos, logs ni la carpeta `entrega/grabacion_demo/` (están en `.gitignore`).
- Hacé commits chicos y descriptivos. No reescribas historia ni hagas force-push.

## Cómo correr
El repo oficial `desafio-futbol` (simulador + datos) debe estar al lado de este:
```
Documentos/
├── desafio-futbol/        # simulador, datos/, evaluacion/verificar.py
└── mi_solucion-futbol/    # este repo
```
```bash
cd desafio-futbol
# Terminal 1
python3 simulador/servidor.py --escenario datos/escenario_practica.json --acelerar 30 --puerto 8000
# Terminal 2
python3 ../mi_solucion-futbol/plataforma.py --simulador http://localhost:8000 --puerto-juez 8090 \
    --juzgados datos/juzgados.json --log salida/auditoria.jsonl
# Dashboard del juez: http://localhost:8090  (aprobar a mano; nadie aprueba solo)
```
Al terminar: `python3 evaluacion/verificar.py` (ver `--help` por los argumentos) sobre el log del simulador.
Usá puertos distintos por corrida y matá los procesos al terminar (si queda un simulador viejo en el puerto,
la prueba "pasa" contra un partido ya terminado y no prueba nada).

Tests: `python3 -m unittest discover -s tests -v` (simulador falso en memoria, sin red).
Para matar procesos de prueba usá el PID del puerto (`ss -ltnp`), no `pkill -f "<args>"`: el patrón
coincide con la propia línea de comandos del shell y la mata.

## Arquitectura (paquete `tarjeta_roja/`, un módulo por responsabilidad)
El código vive en `tarjeta_roja/` con imports relativos; `plataforma.py` en la raíz es solo un atajo a
`tarjeta_roja.plataforma.main` (también `python3 -m tarjeta_roja`). La UI (HTML, CSS, JS y logos SVG) está
en `tarjeta_roja/web/` y se sirve en `/static/` con lista blanca. Verificaciones por CLI:
`python3 -m tarjeta_roja.auditoria <log>` y `python3 -m tarjeta_roja.evidencia <expediente.json>`.

| Archivo | Rol |
|---|---|
| `evidencia.py` | Arma el `Expediente` (marca de agua, host/IP/ASN, hash de captura, riesgo colateral por DNS pasivo). |
| `mesa.py` | Estado compartido con un único lock (RLock): expedientes y reclamos, y su decisión. |
| `firmas.py` | HMAC-SHA256 con el juez de turno en el momento de firmar. |
| `despacho.py` | Firma y envía a cada proveedor con capacidad, reintenta fallidas, firma levantamientos. |
| `reclamos.py` | Propone mantener / levantar / levantar_y_precisar; ejecuta lo que el juez aprobó. |
| `auditoria.py` | JSONL encadenado por hash. |
| `asistente.py` | Asistente del juez por reglas (sin red): alertas, explicaciones y siguiente paso. Solo lee snapshots; nunca decide. |
| `servidor_juez.py` | UI del juez, una sola página en vivo (`/` + `/fragmento` cada 1,5 s, POST por fetch). |
| `plataforma.py` | Punto de entrada: hilos de ingesta, despacho, reclamos y servidor del juez. |

## Lecciones ya aprendidas (no las repitas)
- Un reintento **no** debe dejar viva la orden vieja: se marca `reemplazada` y la nueva hereda `intentos`.
  Si no, las órdenes se multiplican (bug ya corregido en `despacho.py`).
- Los hilos deben capturar excepciones y seguir: un error puntual no debe matar el despacho.
- En el panel hay 4 proveedores: agrupá por bloqueo, no muestres una línea por proveedor.
- Sin juez de turno nadie puede decidir ni firmar.
- Una orden con `vence_min` ya pasado no se reintenta (el proveedor la rechaza).

## Criterios de evaluación (rúbrica del desafío)
Circuito completo 25 · Validez e integridad de la evidencia 25 · Control de daño colateral 20 ·
Velocidad 15 · Claridad y propuesta normativa 15. El núcleo debe correr de punta a punta antes que los extras.

## Tareas sugeridas, por prioridad
Verificá cada una contra el código antes de tocarla; algunas pueden ya estar resueltas.
1. **Vencimiento automático de bloqueos por IP al terminar el partido.** Confirmar que existe y que
   `verificar.py` no reporta "bloqueos por IP activos después del partido".
2. **Tests** (`unittest`, sin dependencias) para: cadena de auditoría (detecta alteración), firmas
   (mensaje canónico), reintentos (no se multiplican, respetan `MAX_REINTENTOS` y vencimiento),
   decisión de IP vs dominio, `Mesa` bajo concurrencia.
3. **Velocidad:** medir minutos de detección → bloqueo confirmado; reducir esperas innecesarias
   (hoy los hilos duermen 1 s) sin romper la regla del juez humano.
4. **Registro público de transparencia** (extra): exponer en el servidor del juez una vista de solo
   lectura (`Mesa.vista_transparencia` ya arma los datos, sin evidencia interna).
5. **Promoción del enlace** (extra): llenar `Expediente.promocion` si el simulador provee los datos.
6. **README:** cómo correr, supuestos, y qué código preexistía al evento (requisito excluyente).
7. **Entregables en `entrega/`:** ejemplo de expediente y de auditoría del partido final, y la propuesta
   normativa de 1 página (revisar `propuesta_normativa.md`).

## Definición de terminado
- `python3 -m compileall -q tarjeta_roja plataforma.py tests` limpio y tests en verde.
- Corrida completa contra el simulador sin excepciones en consola; `verificar_cadena()` en `True`.
- `evaluacion/verificar.py`: sin falsos positivos, sin daño colateral, sin órdenes fuera de turno.
- Documentá en el PR qué cambiaste y cómo lo probaste; no toques firmas ni auditoría sin avisar.
