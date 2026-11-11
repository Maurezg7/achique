# Solución — Desafío Fútbol (bloqueo de streaming pirata)

Plataforma en Python 3.9+ sin dependencias externas. Arquitectura con **juez humano real**
(dashboard web), no un auto-aprobador: la firma de cada orden sale del juez de turno, nunca
de la plataforma.

## Módulos

| Archivo | Responsabilidad |
|---|---|
| `evidencia.py` | Verifica cada detección contra `/partido` y `/dns-pasivo`: descarta retransmisiones legítimas de licenciatarios, detecta riesgo de daño colateral por IP compartida y recomienda bloqueo por dominio o por IP. |
| `firmas.py` | Resuelve el juez de turno en el instante exacto de firmar (nunca cacheado, porque el turno rota) y firma con HMAC-SHA256 según el esquema del README oficial. La clave de firma nunca sale de este módulo. |
| `mesa.py` | Estado compartido con un único lock: expedientes y reclamos pendientes/decididos. El juez decide acá; nadie firma desde esta clase. |
| `despacho.py` | Firma y envía la orden aprobada a cada proveedor con la capacidad necesaria, reintenta automáticamente las fallidas (hasta 3 veces) y firma los levantamientos. |
| `reclamos.py` | Ante un reclamo, decide si el dominio reclamante es el pirata real (mantener bloqueo) o es daño colateral (levantar, y si fue por IP, reemplazar por un bloqueo de dominio preciso contra el verdadero pirata). |
| `auditoria.py` | Registro de auditoría con cadena de hashes (tipo blockchain de logs): cualquier alteración posterior se detecta con `verificar_cadena()`. |
| `servidor_juez.py` | Dashboard HTTP del juez: ve cada expediente con su evidencia completa y cada reclamo con la propuesta de la plataforma, y aprueba o rechaza con un clic. Se autorefresca cada 4 s. |
| `plataforma.py` | Punto de entrada: levanta los 4 hilos (ingesta, despacho, reclamos, servidor del juez) y los conecta. |

## Cómo correrla

> El simulador usa el puerto 8080 por defecto, que choca con el panel del juez; por eso se lo levanta en el 8000.

Esta plataforma usa el simulador y los datos del repo oficial del desafío. Cloná ambos repos lado a lado y corré los dos comandos desde la carpeta `desafio-futbol`:

```
Documentos/
├── desafio-futbol/        # repo oficial (simulador + datos)
└── mi_solucion-futbol/    # este repo
```

```bash
cd desafio-futbol

# Terminal 1: el simulador oficial
python3 simulador/servidor.py --escenario datos/escenario_practica.json --acelerar 20 --puerto 8000

# Terminal 2: esta plataforma
python3 ../mi_solucion-futbol/plataforma.py --simulador http://localhost:8000 --puerto-juez 8080 \
    --juzgados datos/juzgados.json --log salida/auditoria.jsonl
```

Abrir `http://localhost:8080/` — ahí aparecen los expedientes y reclamos a medida que llegan,
con un botón de aprobar/rechazar para cada uno. Nada se firma ni se envía sin ese clic.

## Decisiones de diseño clave

- **Domino > IP cuando hay riesgo de daño colateral.** Si la IP del stream pirata aparece
  con más de un dominio en el DNS pasivo, se recomienda bloquear por dominio aunque eso
  implique no cortar un espejo en la misma IP: se prioriza no afectar sitios legítimos.
- **El juez nunca firma directo.** `servidor_juez.py` solo escribe una decisión en `Mesa`;
  el hilo de despacho es el único que llama a `firmas.py` y solo cuando ve `estado="aprobado"`.
  Así la clave de firma jamás pasa por el proceso HTTP que mira un humano.
- **Reclamos con verificación, no con confianza ciega.** Un reclamo nunca se resuelve solo
  porque alguien se queja: se cruza el dominio reclamante contra los streams piratas
  detectados por la propia plataforma. Si coincide, se propone *mantener* el bloqueo (puede
  ser el pirata disfrazándose de víctima) — y aun así pasa por el juez.
- **Auditoría a prueba de alteración.** Cada entrada incluye el hash de la anterior; probado
  en vivo con `python auditoria.py <archivo>`.

Probado de punta a punta contra el simulador real: detección → expediente → aprobación del
juez → despacho a los proveedores con capacidad → reintento de fallidas → reclamo automático
→ propuesta → aprobación → levantamiento + reemplazo preciso. Cadena de auditoría verificada
íntegra en cada corrida.
