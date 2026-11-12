# Guion de pitch — Plataforma de bloqueo judicial (Desafío Fútbol)
Duración total: ~6 min. Marcado en segundos para que no te quedes sin tiempo.

---

## 1. Problema (0:00 – 0:40)

> "Cuando se piratea un partido en vivo, cada minuto que el sitio sigue arriba es un
> minuto de audiencia robada. Hoy, cortar eso depende de una orden judicial que llega
> tarde, y cuando llega, muchas veces se bloquea de más: se corta una IP compartida y
> de paso se cae una panadería, un club de barrio, una municipalidad. Nuestro problema
> no es solo bloquear rápido — es bloquear **preciso**, sin romper nada que no sea el
> pirata."

---

## 2. Qué construimos (0:40 – 1:20)

> "Armamos la plataforma que conecta la detección de streams piratas con la firma
> judicial y el despacho a los proveedores de internet. Tres reglas no negociables:
> primero, **nunca se firma nada sin que un juez humano lo apruebe** — la plataforma
> propone, nunca decide. Segundo, si una IP está compartida con sitios legítimos,
> preferimos bloquear por dominio exacto, aunque sea más lento, para no generar daño
> colateral. Tercero, todo queda en un registro de auditoría que no se puede alterar
> sin que se note."

*(Mostrar en pantalla: diagrama simple de 4 cajas — Detección → Expediente → Juez → Despacho)*

---

## 3. Demo en vivo (1:20 – 4:00)

**Guion de clics, en orden:**

1. Mostrar el simulador corriendo en la terminal (`/estado`) — "esto es el partido real,
   con detecciones de streams piratas llegando en tiempo acelerado."
2. Abrir el dashboard del juez (`localhost:8090`) — "esto es lo que ve un juez real:
   cada expediente con la marca de agua detectada, la IP, y si hay riesgo de daño
   colateral."
3. Señalar un expediente con riesgo colateral marcado en rojo — "esta IP está
   compartida con otro dominio. Por eso el sistema recomienda bloquear por dominio,
   no por IP entera."
4. Clic en **Aprobar y firmar** — "con un clic, el juez firma. La clave de firma nunca
   sale de este proceso — ni siquiera yo la veo desde el dashboard."
5. Mostrar en otra terminal que la orden llegó a los proveedores (`curl .../ordenes`).
6. **El momento fuerte — reclamo con daño colateral:** mostrar el reclamo automático de
   un sitio inocente, la propuesta de la plataforma ("levantar y precisar"), aprobarlo,
   y mostrar que la orden de IP se levantó y se reemplazó por un bloqueo exacto del
   dominio pirata real — sin tocar al inocente.
   > "Esto es lo que nos diferencia: no solo reaccionamos al reclamo, lo resolvemos sin
   > perder la cobertura sobre el pirata real."
7. Mostrar el log de auditoría y correr `verificar.py` en vivo si da tiempo, o mostrar
   el resultado ya corrido: "7 de 7 streams piratas bloqueados, cero daño colateral,
   cero falsos positivos, verificado contra el simulador oficial del desafío."

---

## 4. Cierre (4:00 – 4:40)

> "No construimos un bloqueador más rápido. Construimos uno que un juez puede confiar
> en aprobar sin mirar dos veces, porque la plataforma ya hizo el trabajo de no
> equivocarse con terceros. Eso es lo que separa una solución que funciona en la demo
> de una que un juzgado real podría usar."

---

## 5. Preguntas esperables de los jueces (preparar respuesta corta)

- **"¿Por qué HMAC y no firma digital asimétrica real?"**
  → "Para la demo alcanza y es lo que define el simulador oficial. En producción,
  cada juez tendría un par de claves propio (ECDSA o similar) y la plataforma solo
  verificaría la firma, nunca la generaría ni la guardaría — hoy tampoco la guarda,
  solo la usa en el momento de firmar."

- **"¿Por qué hilos y no async/await?"**
  → "El cuello de botella es la latencia de red contra el simulador y los proveedores,
  no CPU. Con 4 hilos (ingesta, despacho, reclamos, servidor del juez) alcanza y el
  código queda mucho más simple de auditar que con una máquina de estados async."

- **"¿Qué pasa si hay 10x más detecciones?"**
  → "El lock único en `Mesa` sería el primer cuello de botella. La solución real
  sería particionar por proveedor o por expediente, pero para el volumen de un
  partido es innecesario — preferimos simplicidad verificable sobre escalar algo
  que no hace falta escalar todavía."

- **"¿Qué pasa si el juez de turno cambia mientras una orden está en vuelo?"**
  → "Resolvemos el juez de turno en el instante exacto de firmar, nunca lo cacheamos
  — por eso `verificar.py` da cero órdenes firmadas fuera de turno."
