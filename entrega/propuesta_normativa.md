# Propuesta normativa — Bloqueo judicial de transmisión ilegal de eventos deportivos

**Qué debería establecer una norma o resolución para que este tipo de bloqueo funcione en la práctica, sin pisar derechos de terceros.**

## 1. Marco normativo mínimo

La orden de bloqueo debe nacer de una resolución judicial (o de un organismo con competencia
delegada por ley), firmada digitalmente, con **vigencia acotada al evento** — nunca un bloqueo
permanente por una resolución pensada para un partido puntual. Vencido el evento, el bloqueo
cae solo, sin necesidad de un segundo trámite para levantarlo.

## 2. Registro público de proveedores obligados

Un registro único (mantenido por el regulador de telecomunicaciones) con los proveedores de
internet alcanzados, su capacidad técnica declarada (bloqueo por IP, por dominio, o ambos) y
un canal de recepción de órdenes estandarizado (misma API para todos, no un trámite distinto
por proveedor). Sin esto, cada juzgado termina reinventando el circuito con cada proveedor.
La orden se emite **en el tipo que cada proveedor declaró**: un proveedor chico que solo bloquea
por dominio recibe el dominio, no una IP que no puede aplicar. Los costos de implementación de
los proveedores chicos (bajo cierto número de clientes) deberían cubrirse con un fondo a cargo
de los titulares de derechos que piden los bloqueos.

## 3. Plazos máximos y duración

- **Duración:** el bloqueo por IP vence al terminar el evento (más una gracia corta); el bloqueo
  por dominio puede extenderse solo con una nueva resolución fundada, nunca de forma indefinida.
- **Decisión judicial:** un juez de turno 24/7 durante los eventos, con plazo de minutos para
  aprobar o rechazar cada expediente, y sus fundamentos registrados.

- **Aplicación de la orden:** el proveedor tiene un máximo (p. ej. 5 minutos) desde la
  recepción para aplicarla o reportar por qué no puede.
- **Resolución de reclamos:** un reclamo por bloqueo indebido debe resolverse en un plazo
  corto (p. ej. 30 minutos durante el evento), porque cada minuto de un sitio legítimo caído
  es un daño que no se revierte solo.

## 4. Control de daño colateral como requisito, no como opción

La norma debe **exigir** que el solicitante identifique si la IP a bloquear es compartida por
otros dominios (vía DNS pasivo u otro mecanismo equivalente) y, si lo es, debe **preferir el
bloqueo más específico posible** (por dominio) sobre el bloqueo de IP completa. Bloquear una IP
compartida sin verificar esto debería ser, en sí mismo, motivo de responsabilidad para quien
lo pidió — no alcanza con "atender el reclamo después".

## 5. Reclamos: quién puede reclamar y qué pasa mientras se resuelve

Cualquier titular de un dominio bloqueado puede reclamar, sin necesidad de probar nada de
entrada (la carga de revisar es de la plataforma/juzgado, no del afectado). Mientras se
resuelve el reclamo, el bloqueo **sigue vigente** salvo que la plataforma ya tenga evidencia
clara de que es daño colateral — no se desbloquea por defecto, para no abrir una vía de
apelación que el propio pirata use para reflotar su transmisión.

## 6. Transparencia

Un registro público, actualizado en vivo, de qué se bloqueó, bajo qué orden, por cuánto
tiempo y de qué juzgado — **sin** exponer la evidencia interna del expediente (capturas,
metadatos de la detección). El objetivo es que cualquiera pueda verificar que un bloqueo
existe y por qué categoría general, sin que el registro se convierta en un mapa para evadir
el próximo bloqueo.

## 7. Trazabilidad y auditoría

Toda orden firmada, todo levantamiento y toda resolución de reclamo debe quedar en un registro
inalterable (p. ej. con verificación criptográfica de integridad) accesible para una auditoría
posterior — judicial, de un organismo de control, o de las partes afectadas por una orden
indebida.
