# Tarjeta Roja — bloqueo judicial de señal pirata en vivo

**Tarjeta Roja** es una plataforma federal de órdenes de bloqueo en vivo, el MVP para el **Desafío Fútbol** (Hackathon Argentina Space 2026): durante un partido, cada stream
pirata detectado llega como **expediente con evidencia verificable** a un **juez de turno humano**, que
aprueba con un clic; la plataforma **firma con el juez de turno en ese instante**, envía la orden a
**cada proveedor en el tipo de bloqueo que acepta**, sigue su confirmación, reintenta las fallidas y
deja que los bloqueos por IP **venzan solos** al terminar el partido. Todo queda en una **auditoría
encadenada por hashes** y en un **registro público de transparencia**.

Python 3.9+ y **solo biblioteca estándar**. Corre contra el simulador oficial; no bloquea nada real.

## Para los jueces (5 minutos)

Equipo y marca del pitch: **Achique** (logo en [`entrega/achique_logo.svg`](entrega/achique_logo.svg)).

1. **Correr** (Python 3.9+, sin instalar nada): simulador oficial + plataforma, ver [Cómo correrla](#cómo-correrla).
2. **Abrir la Mesa del juez** (`http://localhost:8090`). La primera vez se abre una **guía de 13 pasos** (botón 🧭
   para volver a verla) que recorre marcador, expedientes, riesgo colateral, firma, reclamos, órdenes y registro público.
3. **Aprobar los expedientes** con *Aprobar y firmar*. El **Asistente del juez** (panel derecho) marca el siguiente
   paso, avisa demoras, órdenes fallidas o rechazadas y bloqueos por IP cerca del final, y explica cada expediente
   en lenguaje claro. Es local y por reglas: **recomienda, nunca aprueba ni firma**.
4. **Verificar** al terminar: `evaluacion/verificar.py` (métricas oficiales) y la cadena de auditoría.

| Criterio | Dónde mirarlo |
|---|---|
| Circuito completo | detección → expediente → juez de turno → proveedores → confirmación → vencimiento ([Arquitectura](#arquitectura)) |
| Daño colateral | IP compartida o CDN ⇒ se pide el **dominio**; tarjeta "Riesgo de daño colateral" y explicación del asistente |
| Evidencia verificable | `entrega/expediente_ejemplo*.json`, `python3 -m tarjeta_roja.evidencia` |
| Firma humana y de turno | `firmas.py` resuelve el juez de turno al firmar; sin auto-aprobación |
| Auditoría | `python3 -m tarjeta_roja.auditoria entrega/auditoria_ejemplo.jsonl` → *Cadena íntegra: SÍ* |
| Transparencia | `/transparencia` y `/transparencia.json` |
| Pitch | `entrega/presentacion.pptx`, `entrega/guion_pitch.md`, `entrega/guion_video.md` |

## Resultado en el partido de práctica

`evaluacion/verificar.py` sobre una corrida completa (`--acelerar 30`, juez aprobando a mano). Salida
completa en [`entrega/evaluacion_practica.txt`](entrega/evaluacion_practica.txt).

| Métrica | Resultado |
|---|---|
| Fases piratas bloqueadas | **7 de 7**, todas con **100 % de clientes cubiertos** |
| Primer bloqueo confirmado | 1,6 – 2,1 min desde la detección (incluye la decisión del juez) |
| Visibilidad residual promedio | 6,6 % |
| Daño colateral / falsos positivos | **0 / 0** (ni el licenciatario ni el VOD de otro partido) |
| Bloqueos por IP activos después del partido | **0** |
| Órdenes rechazadas / firmadas fuera de turno | **0 / 0** (hubo cambio de turno en el minuto 50) |
| Cadena de auditoría | íntegra (`python3 -m tarjeta_roja.auditoria entrega/auditoria_ejemplo.jsonl`) |

La recomendación IP/dominio coincidió en los 7 expedientes con la `bloqueo_recomendado` de la verdad del escenario.

## Cómo correrla

El repo oficial `desafio-futbol` (simulador + datos) va al lado de este:

```
Documentos/
├── desafio-futbol/        # simulador, datos/, evaluacion/verificar.py
└── mi_solucion-futbol/    # este repo
```

```bash
cd desafio-futbol
# Terminal 1: simulador oficial
python3 simulador/servidor.py --escenario datos/escenario_practica.json --acelerar 30 --puerto 8000

# Terminal 2: Tarjeta Roja
python3 ../mi_solucion-futbol/plataforma.py --simulador http://localhost:8000 --puerto-juez 8090 \
    --juzgados datos/juzgados.json --log salida/auditoria.jsonl
```

- **Mesa del juez:** <http://localhost:8090> — aprobar o rechazar cada expediente (nadie aprueba solo).
- **Registro público:** <http://localhost:8090/transparencia> (y `/transparencia.json`).
- Cada expediente se exporta a `salida/expedientes/EXP-….json`.
- El marcador muestra por defecto **Azul Juniors vs Rojo Plate** por la ficticia **LFA · Liga de Fútbol Argentino**
  (alusiones de demo, sin logos reales); los equipos se cambian con `--local` y `--visitante`. Los goles del
  marcador son ilustrativos y no intervienen en ninguna decisión.

Al terminar el partido (y los 5 min de gracia):

```bash
python3 evaluacion/verificar.py --log salida/registro.jsonl     # métricas oficiales
cd ../mi_solucion-futbol
python3 -m tarjeta_roja.auditoria ../desafio-futbol/salida/auditoria.jsonl                     # Cadena íntegra: SÍ
python3 -m tarjeta_roja.evidencia ../desafio-futbol/salida/expedientes/EXP-2026-000001.json    # Expediente íntegro: SÍ
```

`python3 plataforma.py` es un atajo; también se puede correr con `python3 -m tarjeta_roja` desde la raíz del repo.

Tests (sin dependencias, sin red):

```bash
cd mi_solucion-futbol && python3 -m unittest discover -s tests -v
```

## Estructura

```
mi_solucion-futbol/
├── plataforma.py              # atajo: python3 plataforma.py … (= python3 -m tarjeta_roja)
├── tarjeta_roja/              # el paquete de la plataforma (solo biblioteca estándar)
│   ├── __init__.py            # nombre y lema
│   ├── __main__.py            # python3 -m tarjeta_roja
│   ├── plataforma.py          # main(): hilos de ingesta, despacho, reclamos y servidor HTTP
│   ├── evidencia.py           # expediente + verificación de sello (CLI)
│   ├── mesa.py                # estado compartido y decisiones del juez
│   ├── firmas.py              # HMAC con el juez de turno al firmar
│   ├── despacho.py            # único que firma; envío, seguimiento y reintentos
│   ├── reclamos.py            # verificación y resolución de reclamos
│   ├── auditoria.py           # cadena de hashes (CLI de verificación)
│   ├── asistente.py           # asistente del juez: vigila, explica y guía (por reglas, offline)
│   ├── servidor_juez.py       # Mesa del juez y registro público
│   └── web/                   # index.html, estilos.css, app.js, logo.svg, liga.svg
├── tests/                     # unittest con simulador falso en memoria
└── entrega/                   # entregables del desafío (expediente, auditoría, propuesta, pitch)
```

## Arquitectura

```
detecciones ─► evidencia.py ─► mesa.py ◄── servidor_juez.py (juez humano: aprobar / rechazar)
                (expediente)      │
                                  ▼ solo lo "aprobado"
                            despacho.py ── firmas.py (juez de turno AHORA) ──► proveedores
                                  │            ▲                                  │
                            reclamos.py ───────┘ levantar + precisar          confirmación
                                  │                                               │
                            auditoria.py (cadena de hashes) ◄─────── cada paso ───┘
```

| Módulo (`tarjeta_roja/`) | Responsabilidad |
|---|---|
| `evidencia.py` | Verifica la marca de agua contra `/partido`, descarta licenciatarios en su dominio y señales de otro partido, identifica servidor (host, IP, ASN, organización), evalúa riesgo colateral con DNS pasivo, calcula hashes y **sella** el expediente. |
| `mesa.py` | Estado compartido con un único lock: expedientes (con re-detecciones), reclamos, decisiones del juez (auditadas) y estado de cada orden. |
| `firmas.py` | HMAC-SHA256 según el README oficial con el juez de turno resuelto **en el instante de firmar** (nunca cacheado). |
| `despacho.py` | Único que firma. Envía a cada proveedor en el tipo que acepta, sigue la orden hasta `aplicada` y `vencida`, reintenta fallidas (sin multiplicarlas) y firma levantamientos. |
| `reclamos.py` | Verifica cada reclamo, propone mantener / levantar / levantar y precisar, y ejecuta lo que el juez aprobó en **todos** los proveedores afectados. |
| `auditoria.py` | JSONL append-only encadenado por SHA-256; `verificar_cadena()` detecta cualquier edición o borrado. |
| `asistente.py` | Asistente del juez local y por reglas (sin API ni red): vigila demoras de firma, órdenes rechazadas / fallidas / sin confirmar, bloqueos por IP cerca del final, turno y cadena de auditoría; explica cada expediente y reclamo en lenguaje claro y marca el siguiente paso. Sus alertas quedan en la auditoría (`asistente_alerta`). **Recomienda, nunca aprueba ni firma.** También en `/asistente.json`. |
| `servidor_juez.py` | Mesa del juez en vivo (escritorio y celular, avisos sonoros y notificaciones) y registro público. Incluye una guía interactiva de 13 pasos (botón 🧭) y "Mostrame dónde", que resalta el elemento a revisar. La página, estilos, script y logos están en `web/`. |
| `plataforma.py` | Punto de entrada: hilos de ingesta, despacho, reclamos y servidor HTTP. |

## Decisiones clave

- **El juez siempre decide.** `servidor_juez.py` solo escribe una decisión en `Mesa`; `despacho.py` firma
  únicamente lo aprobado. Sin juez de turno no se puede decidir ni firmar. La clave nunca pasa por HTTP.
- **IP o dominio, con criterio.** Se bloquea la IP cuando solo sirve al sitio pirata (incluidos sus
  espejos: `s1` y `s1-respaldo.pelotaya.test` comparten dominio base, y bloquear la IP corta a ambos). Si
  la IP sirve **otro** sitio, si el ASN es CDN / hosting compartido, o si no hay datos de DNS pasivo, se
  pide el **dominio**. Nunca se convierte un bloqueo de dominio en uno de IP.
- **Cobertura total según capacidad.** Un proveedor que solo bloquea por dominio recibe el dominio del
  stream cuando el expediente pide IP: es el host del pirata, así que no agrega daño colateral y sus
  clientes no quedan afuera (en la práctica, FibraValle pasa de 0 % a 100 % de cobertura).
- **Una re-detección no es otra orden.** Si el mismo servidor (host + IP) vuelve a aparecer, se suma como
  evidencia al expediente existente; si el pirata cambia de servidor, se abre un expediente nuevo.
- **Evidencia que se puede auditar.** SHA-256 de los bytes de la captura, de la detección original y un
  sello de todo el expediente; sellos de tiempo de partido y UTC. Cada paso (detección descartada, expediente
  creado, decisión, orden enviada, confirmada, fallida, reintentada, vencida, reclamo) queda en la cadena.
- **Reclamos con verificación.** Un licenciatario o un dominio nunca detectado se propone levantar (y
  precisar si era un bloqueo por IP); un dominio detectado como pirata se propone mantener. Siempre decide el juez.

## Supuestos

- El dominio base se aproxima con las dos últimas etiquetas del host (válido para `.test` / `.example`;
  en producción se usaría la Public Suffix List).
- El vencimiento propuesto es el fin del partido (`fin_min`) para IP y dominio; el proveedor lo aplica solo.
- Quien hace clic en la Mesa del juez es el juez de turno que informa `/estado` (la demo no tiene login).
- La firma HMAC con claves de demostración reemplaza a la firma digital real del juez.

## Qué existía antes del evento

Todo el código de este repositorio se escribió durante el hackathon, a partir del 11 de noviembre de 2026
(ver el historial de git). No se reutilizó código propio previo ni se usaron librerías externas: solo la
biblioteca estándar de Python 3.9+. El simulador, los datos y `evaluacion/verificar.py` son del repositorio
oficial `desafio-futbol` y no están copiados acá.

## Entregables (`entrega/`)

- `expediente_ejemplo.json` (dominio, IP compartida en CDN) y `expediente_ejemplo_ip.json` (IP dedicada).
- `auditoria_ejemplo.jsonl` — auditoría completa de la corrida. **El día 3 se reemplazan por los del partido final.**
- `evaluacion_practica.txt` — salida de `verificar.py`.
- `propuesta_normativa.md` — propuesta normativa de 1 página.
- `presentacion.pptx` y `guion_pitch.md` — pitch. El video demo (`demo.mp4`) no se versiona: se sube a Hacki.
- `guion_video.md` — guion del video publicitario (escenas, textos en pantalla y locución); `achique_logo.svg` / `achique_logo.png` — logo de Achique. El video tampoco se versiona.
