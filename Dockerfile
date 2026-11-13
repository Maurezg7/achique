# Demo pública de Achique: simulador oficial (partido de práctica en loop) + Mesa del juez en $PORT.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl git && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 https://github.com/qualydata-org/desafio-futbol.git /desafio-futbol
WORKDIR /app
COPY . /app
ENV SIM=/desafio-futbol PORT=8090 ACELERAR=6
EXPOSE 8090
CMD ["./demo/demo_publico.sh"]
