# Achique — bloqueo judicial de señal pirata en vivo

**Achique** es una plataforma federal de órdenes de bloqueo en vivo, el MVP para el **Desafío Fútbol** (Hackathon Argentina Space 2026): durante un partido, cada stream
pirata detectado llega como **expediente con evidencia verificable** a un **juez de turno humano**, que
aprueba con un clic; la plataforma **firma con el juez de turno en ese instante**, envía la orden a
**cada proveedor en el tipo de bloqueo que acepta**, sigue su confirmación, reintenta las fallidas y
deja que los bloqueos por IP **venzan solos** al terminar el partido. Todo queda en una **auditoría
encadenada por hashes** y en un **registro público de transparencia**.

Python 3.9+ y **solo biblioteca estándar**. Corre contra el simulador oficial; no bloquea nada real.

## Para los jueces (5 minutos)

Equipo y marca del pitch: **Achique** (logo en [`entrega/achique_logo.svg`](entrega/achique_logo.svg)).

1. **Correr** (Python 3.9+, sin instalar nada): simulador oficial + plataforma, ver [Cómo correrla](#cómo-correrla).
2. **Ingresar a la Mesa del juez** (`http://localhost:8090`) con un usuario de demostración (ver
   [Ingreso de los jueces](#ingreso-de-los-jueces)). La primera vez se abre una **guía de 13 pasos** (botón 🧭
   para volver a verla) que recorre marcador, expedientes, riesgo colateral, firma, reclamos, órdenes y registro público.
3. **Aprobar los expedientes** con *Aprobar y firmar*. El **Asistente del juez** (panel derecho) marca el siguiente
   paso, avisa demoras, órdenes fallidas o rechazadas y bloqueos por IP cerca del final, y explica cada expediente
   en lenguaje claro. Es local y por reglas: **recomienda, nunca aprueba ni firma**.
4. **Verificar** al terminar: `evaluacion/verificar.py` (métricas oficiales) y la cadena de auditoría.

| Criterio | Dónde mirarlo |
|---|---|
| Circuito completo | detección → expediente → juez de turno → proveedores → confirmación → vencimiento ([Arquitectura](#arquitectura)) |
| Daño colateral | IP compartida o CDN ⇒ se pide el **dominio**; tarjeta "Riesgo de daño colateral" y explicación del asistente |
| Evidencia verificable | `entrega/expediente_ejemplo*.json`, `python3 -m achique.evidencia` |
| Ingreso y firma de turno | Login con usuario y contraseña (`sesiones.py`); firma solo el juez que inició sesión, aprobó y sigue de turno; al cambio de turno lo pendiente pasa al entrante |
| Auditoría | `python3 -m achique.auditoria entrega/auditoria_ejemplo.jsonl` → *Cadena íntegra: SÍ* |
| Transparencia | `/transparencia` y `/transparencia.json` |
| Pitch | `entrega/presentacion.pptx`, `entrega/guion_pitch.md`, `entrega/guion_video.md` |

## Qué agrega frente a otros países

El desafío compara modelos de Italia, Francia, Reino Unido, Grecia, Perú y México: ninguno hace que cada pedido llegue en
el momento a un juez de turno. Achique lo hace sin perder velocidad (primer bloqueo en 1 o 2 minutos) y evita el problema
de Piracy Shield (Italia), que bloqueó sitios legítimos: si la IP es compartida, se pide el dominio. Detalle en
[`entrega/propuesta_normativa.md`](entrega/propuesta_normativa.md).

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
| Cadena de auditoría | íntegra (`python3 -m achique.auditoria entrega/auditoria_ejemplo.jsonl`) |

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

# Terminal 2: Achique
python3 ../mi_solucion-futbol/plataforma.py --simulador http://localhost:8000 --puerto-juez 8090 \
    --juzgados datos/juzgados.json --log salida/auditoria.jsonl
```

- **Mesa del juez:** <http://localhost:8090> — ingresar con usuario y contraseña y aprobar o rechazar cada
  expediente (nadie aprueba solo).
- **Registro público:** <http://localhost:8090/transparencia> (y `/transparencia.json`).
- Cada expediente se exporta a `salida/expedientes/EXP-….json`.
- El marcador muestra por defecto **Azul Juniors vs Rojo Plate** por la ficticia **LFA · Liga de Fútbol Argentino**
  (alusiones de demo, sin logos reales); los equipos se cambian con `--local` y `--visitante`. Los goles del
  marcador son ilustrativos y no intervienen en ninguna decisión.

Al terminar el partido (y los 5 min de gracia):

```bash
python3 evaluacion/verificar.py --log salida/registro.jsonl     # métricas oficiales
cd ../mi_solucion-futbol
python3 -m achique.auditoria ../desafio-futbol/salida/auditoria.jsonl                     # Cadena íntegra: SÍ
python3 -m achique.evidencia ../desafio-futbol/salida/expedientes/EXP-2026-000001.json    # Expediente íntegro: SÍ
```

`python3 plataforma.py` es un atajo; también se puede correr con `python3 -m achique` desde la raíz del repo.

**Si la plataforma se reinicia a mitad del partido**, volvé a correr el mismo comando con el mismo `--log`: retoma
desde la auditoría y los expedientes exportados (sin duplicar expedientes ni órdenes, con los pendientes otra vez en
la Mesa y siguiendo las órdenes ya enviadas). Los jueces vuelven a ingresar. Queda registrado como `plataforma_reanudada`.

**Entregables del partido final** (expediente, auditoría y evaluación) en un paso, desde `mi_solucion-futbol/`:

```bash
python3 -m achique.entrega --registro ../desafio-futbol/salida/registro.jsonl \
    --auditoria ../desafio-futbol/salida/auditoria.jsonl --expedientes ../desafio-futbol/salida/expedientes \
    --verificar ../desafio-futbol/evaluacion/verificar.py
```

Deja `entrega/auditoria_final.jsonl`, `entrega/expediente_final.json` (por dominio), `entrega/expediente_final_ip.json`
y `entrega/evaluacion_final.txt`; después, commit y push antes del cierre.

Tests (sin dependencias, sin red):

```bash
cd mi_solucion-futbol && python3 -m unittest discover -s tests -v
```

## Ingreso de los jueces

Cada juez entra con su propio usuario y contraseña. Los usuarios de demostración están atados a los jueces ficticios
de `datos/juzgados.json` (los mismos del partido final) y sirven también ese día:

| Usuario | Contraseña (demo) | Juez | Turno en el escenario |
|---|---|---|---|
| `laura` | `laura-demo-2026` | Dra. Laura Ficticia (`jueza-laura-ficticia`) | hasta el minuto 50 |
| `martin` | `martin-demo-2026` | Dr. Martín Ejemplo (`juez-martin-ejemplo`) | desde el minuto 50 |

- **Solo firma el que aprobó y está de turno.** La plataforma firma con la clave de un juez solo después de que ese
  juez inició sesión y aprobó; nadie firma en su nombre. La decisión exige estar de turno (si no, HTTP 403 y
  `decision_denegada` en la auditoría) y la firma lo vuelve a comprobar en el instante de firmar.
- **Cada juez ve lo suyo.** Fuera de turno, la Mesa no muestra expedientes ni reclamos para decidir: indica quién
  está de turno y cuántos pendientes tiene.
- **Cambio de turno.** Lo pendiente pasa al juez entrante y el saliente ya no puede firmar. Si el saliente aprobó y
  cambió el turno antes de que se firmara, o una orden suya falló y hay que reintentarla, el expediente vuelve a la
  Mesa del entrante (`expediente_reasignado` / `reintento_requiere_juez_de_turno`); lo ya enviado no se duplica.
- **Seguridad.** Contraseñas con PBKDF2-SHA256 (200 000 iteraciones, sal por usuario); en el repo solo hay sal y
  hash. Sesión con token aleatorio en cookie `HttpOnly` y `SameSite=Strict`, vence a las 8 h, y 5 intentos fallidos
  frenan el ingreso 1 minuto. La auditoría registra ingresos, salidas e intentos fallidos, nunca la contraseña.
- Otro usuario: `python3 -m achique.sesiones <usuario> <juez_id>` pide la contraseña e imprime la entrada para
  `achique/usuarios_demo.json` (o un archivo propio con `--usuarios`).

## Estructura

```
mi_solucion-futbol/
├── plataforma.py              # atajo: python3 plataforma.py … (= python3 -m achique)
├── achique/              # el paquete de la plataforma (solo biblioteca estándar)
│   ├── __init__.py            # nombre y lema
│   ├── __main__.py            # python3 -m achique
│   ├── plataforma.py          # main(): hilos de ingesta, despacho, reclamos y servidor HTTP
│   ├── evidencia.py           # expediente + verificación de sello (CLI)
│   ├── mesa.py                # estado compartido y decisiones del juez
│   ├── firmas.py              # HMAC en nombre del juez que aprobó, solo si está de turno
│   ├── sesiones.py            # ingreso de los jueces (PBKDF2) y sesiones por cookie
│   ├── usuarios_demo.json     # usuarios de demostración (sal + hash, sin contraseñas)
│   ├── despacho.py            # único que firma; envío, seguimiento y reintentos
│   ├── reclamos.py            # verificación y resolución de reclamos
│   ├── auditoria.py           # cadena de hashes (CLI de verificación)
│   ├── asistente.py           # asistente del juez: vigila, explica y guía (por reglas, offline)
│   ├── reanudacion.py         # tras un reinicio, retoma desde la auditoría y los expedientes exportados
│   ├── entrega.py             # arma los entregables del partido final en entrega/
│   ├── servidor_juez.py       # Mesa del juez y registro público
│   └── web/                   # index.html, estilos.css, app.js, logo.svg, liga.svg
├── tests/                     # unittest con simulador falso en memoria
└── entrega/                   # entregables del desafío (expediente, auditoría, propuesta, pitch)
```

## Arquitectura

```
detecciones ─► evidencia.py ─► mesa.py ◄── servidor_juez.py (juez con sesión y de turno: aprobar / rechazar)
                (expediente)      │
                                  ▼ solo lo "aprobado"
                            despacho.py ── firmas.py (el que aprobó, si sigue de turno) ──► proveedores
                                  │            ▲                                  │
                            reclamos.py ───────┘ levantar + precisar          confirmación
                                  │                                               │
                            auditoria.py (cadena de hashes) ◄─────── cada paso ───┘
```

| Módulo (`achique/`) | Responsabilidad |
|---|---|
| `evidencia.py` | Verifica la marca de agua contra `/partido`, descarta licenciatarios en su dominio y señales de otro partido, identifica servidor (host, IP, ASN, organización), evalúa riesgo colateral con DNS pasivo, calcula hashes y **sella** el expediente. |
| `mesa.py` | Estado compartido con un único lock: expedientes (con re-detecciones), reclamos, decisiones del juez (auditadas) y estado de cada orden. |
| `firmas.py` | HMAC-SHA256 según el README oficial, **en nombre del juez que aprobó** y solo si sigue de turno en el instante de firmar (turno nunca cacheado). Si no, `FueraDeTurno`: nadie firma por él. |
| `sesiones.py` | Usuarios de los jueces con contraseña PBKDF2-SHA256 (sal por usuario, comparación en tiempo constante), sesiones con token aleatorio en cookie `HttpOnly` + `SameSite=Strict` y freno tras 5 intentos fallidos. |
| `despacho.py` | Único que firma. Envía a cada proveedor en el tipo que acepta, sigue la orden hasta `aplicada` y `vencida`, reintenta fallidas (sin multiplicarlas) y firma levantamientos. |
| `reclamos.py` | Verifica cada reclamo, propone mantener / levantar / levantar y precisar, y ejecuta lo que el juez aprobó en **todos** los proveedores afectados. |
| `auditoria.py` | JSONL append-only encadenado por SHA-256; `verificar_cadena()` detecta cualquier edición o borrado. |
| `asistente.py` | Asistente del juez local y por reglas (sin API ni red): vigila demoras de firma, órdenes rechazadas / fallidas / sin confirmar, bloqueos por IP cerca del final, turno y cadena de auditoría; explica cada expediente y reclamo en lenguaje claro y marca el siguiente paso. Sus alertas quedan en la auditoría (`asistente_alerta`). **Recomienda, nunca aprueba ni firma.** También en `/asistente.json`. |
| `servidor_juez.py` | Mesa del juez en vivo (escritorio y celular, avisos sonoros y notificaciones) y registro público. Incluye una guía interactiva de 13 pasos (botón 🧭) y "Mostrame dónde", que resalta el elemento a revisar. La página, estilos, script y logos están en `web/`. |
| `reanudacion.py` | Si se arranca con un `--log` que ya tiene eventos, reconstruye el estado: detecciones ya procesadas, expedientes (desde `salida/expedientes/`), decisiones, órdenes enviadas y su último estado. No duplica expedientes ni órdenes; completa lo que quedó a medio despachar. |
| `entrega.py` | `python3 -m achique.entrega …`: copia a `entrega/` la auditoría, un expediente por dominio y uno por IP (verificando sellos y cadena) y la salida de `verificar.py`. |
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
- El turno lo informa `/estado` del simulador; la plataforma lo consulta en cada decisión y en cada firma.
- Las sesiones viven en memoria: si se reinicia la plataforma, los jueces vuelven a ingresar (el resto del estado se
  recupera de la auditoría, ver `reanudacion.py`).
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
