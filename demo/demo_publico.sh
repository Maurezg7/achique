#!/bin/bash
# Demo pública de Achique: corre el simulador oficial (partido de práctica) y la plataforma, y cuando el
# partido termina vuelve a empezar. Pensado para una URL de prueba del jurado; no es el partido final.
#   SIM=/ruta/a/desafio-futbol PORT=8090 ACELERAR=6 ./demo/demo_publico.sh
set -u
cd "$(dirname "$0")/.."
SIM=${SIM:-../desafio-futbol}; PORT=${PORT:-8090}; ACELERAR=${ACELERAR:-6}; PUERTO_SIM=${PUERTO_SIM:-8000}
export ACHIQUE_DEMO=1
while true; do
  rm -rf salida; mkdir -p salida
  python3 "$SIM/simulador/servidor.py" --escenario "$SIM/datos/escenario_practica.json" --datos "$SIM/datos" \
      --acelerar "$ACELERAR" --puerto "$PUERTO_SIM" --log salida/registro.jsonl & S=$!
  sleep 2
  python3 plataforma.py --simulador "http://localhost:$PUERTO_SIM" --puerto-juez "$PORT" \
      --juzgados "$SIM/datos/juzgados.json" --log salida/auditoria.jsonl & P=$!
  while kill -0 $S 2>/dev/null; do
    fin=$(curl -s "http://localhost:$PUERTO_SIM/estado" | python3 -c 'import sys,json
d=json.load(sys.stdin); print(d["minuto_actual"] >= d["fin_min"] + 6)' 2>/dev/null)
    [ "$fin" = "True" ] && break
    sleep 5
  done
  echo "demo: partido terminado, arranca otro" >&2
  kill $P $S 2>/dev/null; wait $P $S 2>/dev/null; sleep 1
done
