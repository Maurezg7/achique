# Guion del video de presentación — Achique

Video publicitario de ~2:10 (1080p) para el pitch. Locución en español rioplatense; imágenes de la Mesa del juez corriendo contra el simulador oficial (`escenario_practica.json`). El video no se versiona en el repo (ver `AGENTS.md`).

Logo: [`achique_logo.svg`](achique_logo.svg) / [`achique_logo.png`](achique_logo.png) — la "A" es el ángulo que achica el arquero dentro del arco; la barra roja es el bloqueo y el triángulo, la señal pirata frenada.

| # | Escena | Seg. | En pantalla | Locución |
|---|---|---|---|---|
| 0 | Apertura | 0:00 | Placa: HACKATHON ARGENTINA SPACE 2026 · DESAFÍO FÚTBOL · EQUIPO ACHIQUE PRESENTA | — |
| 1 | El partido | 0:04 | PARTIDO EN VIVO. / Y UN SITIO PIRATA LO TRANSMITE GRATIS. | Partido en vivo. Y mientras la pelota rueda, un sitio pirata lo está transmitiendo gratis. |
| 2 | El problema | 0:11 | CADA MINUTO PIRATA = AUDIENCIA ROBADA / OJO: IP COMPARTIDA — BLOQUEARLA APAGA TAMBIÉN A UN CLUB O UNA ESCUELA | Cada minuto que sigue en el aire es audiencia robada. Pero ojo: si el pirata comparte servidor con otros sitios, bloquear esa IP también deja sin servicio a sitios legítimos, como el de un club o una escuela. |
| 3 | Por qué se cae el club | 0:24 | Animación: servidor compartido (IP 192.0.2.50) con el pirata, un club, una escuela y una panadería. BLOQUEO POR IP = SE APAGAN TODOS / BLOQUEO POR DOMINIO = SOLO EL PIRATA | ¿Por qué pasa esto? Porque muchos sitios viven en el mismo servidor, y comparten la misma dirección IP. Si se bloquea esa IP, se apagan todos: el pirata... pero también el club y la escuela. En cambio, bloqueando solo el dominio del pirata, los demás siguen en línea. |
| 4 | Expediente | 0:42 | EXPEDIENTE CON EVIDENCIA SELLADA — Marca de agua · servidor · hashes · juez de turno | Para eso está Achique: recibe cada detección, verifica la marca de agua del partido, identifica el servidor y arma un expediente con evidencia sellada para el juez de turno. |
| 5 | Daño colateral | 0:53 | IP COMPARTIDA → SOLO EL DOMINIO — Sin daño colateral a sitios legítimos | Si esa IP la comparten sitios legítimos, Achique lo detecta y propone bloquear solo el dominio del pirata. |
| 6 | Asistente del juez | 1:00 | NUEVO: ASISTENTE DEL JUEZ — Vigila · avisa · señala dónde actuar | Y ahora suma el Asistente del juez: vigila la plataforma, avisa lo que se demora y señala exactamente dónde actuar. |
| 7 | Explicaciones | 1:08 | CADA CASO, EN LENGUAJE CLARO — Por qué IP o dominio, y qué revisar | Además, explica cada caso en lenguaje claro, antes de decidir. |
| 8 | Guía | 1:14 | GUÍA INTERACTIVA — La mesa del juez, paso a paso | ¿Primera vez en la mesa? Una guía interactiva la recorre paso a paso. |
| 9 | Firma humana | 1:20 | LA DECISIÓN ES HUMANA — El asistente recomienda; nunca firma | La decisión siempre es humana: el juez aprueba con un clic y la plataforma firma con el juez de turno. El asistente recomienda; nunca firma. |
| 10 | Proveedores | 1:29 | A CADA PROVEEDOR DE INTERNET — En el tipo de bloqueo que acepta | La orden llega a cada proveedor de internet, en el tipo de bloqueo que acepta, y Achique sigue su confirmación. |
| 11 | En vivo | 1:37 | TODO EN VIVO — Cobertura · tiempos · alertas | Cobertura de clientes, tiempos y alertas: todo en vivo. |
| 12 | Transparencia | 1:41 | TRANSPARENCIA Y AUDITORÍA — Registro público · la IP vence sola al final | Todo queda en un registro público y en una auditoría encadenada: si alguien la altera, se nota. Y los bloqueos por IP vencen solos al terminar el partido. |
| 13 | Resultados | 1:52 | PROBADO CONTRA EL SIMULADOR OFICIAL: 7/7 streams bloqueados · 100% clientes cubiertos · 0 daño colateral | Probado contra el simulador oficial del desafío: siete de siete streams bloqueados, cien por ciento de clientes cubiertos y cero daño colateral. |
| 14 | Cierre | 2:01 | Logo + ACHIQUE — Bloqueo judicial de señal pirata en vivo — LE CERRAMOS EL ARCO AL PIRATA. Sin tocar al barrio. | Achique. Le cerramos el arco al pirata... sin tocar al barrio. |

Datos citados: resultado de `evaluacion/verificar.py` en el partido de práctica (7/7 fases, 100 % de clientes cubiertos, 0 daño colateral, 0 bloqueos por IP después del partido). Todos los sitios, IPs, jueces y clubes son ficticios del simulador oficial.
