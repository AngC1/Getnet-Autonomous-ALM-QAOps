#!/usr/bin/env bash
# Levanta y para la web del verificador de marca (API Node + cliente React + Redis).
# Uso: web/run.sh start | stop | restart | status
# Variables opcionales: PORT (3001), REDIS_URL, MEDIA_BUCKET, MEDIA_DIR.
# Redis: usa REDIS_URL si ya está definida; si no, Docker (docker-compose.yml) o redis-server/valkey-server
# locales; si no hay ninguno, la API usa el almacén en memoria.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$ROOT/.run"
PID_FILE="$RUN_DIR/server.pid"
REDIS_PID_FILE="$RUN_DIR/redis.pid"
REDIS_MODE_FILE="$RUN_DIR/redis.mode"
LOG_FILE="$RUN_DIR/server.log"
PORT="${PORT:-3001}"
# Modelo de visión de Bedrock (us-east-1) que usa el verificador; el dashboard lo comprueba en vivo.
export BRAND_MODEL_ID="${BRAND_MODEL_ID:-us.anthropic.claude-sonnet-4-5-20250929-v1:0}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
REDIS_PORT="${REDIS_PORT:-6379}"
mkdir -p "$RUN_DIR"

log() { printf '[web] %s\n' "$*"; }
is_running() { [[ -f "$1" ]] && kill -0 "$(cat "$1")" 2>/dev/null; }

install_deps() {
  for d in server client; do
    if [[ ! -d "$ROOT/$d/node_modules" ]]; then
      log "Instalando dependencias de $d..."
      (cd "$ROOT/$d" && npm install --no-audit --no-fund --silent)
    fi
  done
  if [[ ! -d "$ROOT/client/dist" ]]; then
    log "Compilando el cliente..."
    (cd "$ROOT/client" && npm run build --silent)
  fi
}

start_redis() {
  if [[ -n "${REDIS_URL:-}" ]]; then log "Usando REDIS_URL externa."; echo external >"$REDIS_MODE_FILE"; return; fi
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    log "Levantando Redis con Docker..."
    docker compose -f "$ROOT/docker-compose.yml" up -d >/dev/null
    echo docker >"$REDIS_MODE_FILE"; export REDIS_URL="redis://localhost:$REDIS_PORT"; return
  fi
  for bin in redis-server valkey-server; do
    if command -v "$bin" >/dev/null 2>&1; then
      log "Levantando $bin local en el puerto $REDIS_PORT..."
      "$bin" --port "$REDIS_PORT" --save "" --appendonly no --daemonize no >"$RUN_DIR/redis.log" 2>&1 &
      echo $! >"$REDIS_PID_FILE"; echo local >"$REDIS_MODE_FILE"
      export REDIS_URL="redis://localhost:$REDIS_PORT"; sleep 1; return
    fi
  done
  log "Redis no disponible (ni Docker ni redis-server): la API usará el almacén en memoria."
  echo none >"$REDIS_MODE_FILE"
}

start() {
  if is_running "$PID_FILE"; then log "Ya está en marcha (pid $(cat "$PID_FILE")) en http://localhost:$PORT"; return; fi
  command -v node >/dev/null 2>&1 || { log "Falta Node.js."; exit 1; }
  if curl -fsS "http://localhost:$PORT/api/health" >/dev/null 2>&1; then
    log "El puerto $PORT ya está ocupado por otro proceso. Páralo o usa PORT=<otro>."; exit 1
  fi
  install_deps
  start_redis
  log "Arrancando la API en el puerto $PORT..."
  # exec: el PID guardado es el de node, no el de un subshell intermedio.
  (cd "$ROOT/server" && exec env PORT="$PORT" nohup node index.js >"$LOG_FILE" 2>&1) &
  echo $! >"$PID_FILE"
  for _ in $(seq 1 20); do
    if curl -fsS "http://localhost:$PORT/api/health" >/dev/null 2>&1; then
      log "Listo: http://localhost:$PORT  ($(curl -fsS "http://localhost:$PORT/api/health"))"; return
    fi
    is_running "$PID_FILE" || { log "La API se detuvo. Últimas líneas del log:"; tail -n 15 "$LOG_FILE"; exit 1; }
    sleep 0.5
  done
  log "La API no respondió a tiempo. Revisa $LOG_FILE"; exit 1
}

stop() {
  if is_running "$PID_FILE"; then
    log "Parando la API (pid $(cat "$PID_FILE"))..."
    kill "$(cat "$PID_FILE")" 2>/dev/null || true
    for _ in $(seq 1 10); do is_running "$PID_FILE" || break; sleep 0.3; done
    is_running "$PID_FILE" && kill -9 "$(cat "$PID_FILE")" 2>/dev/null || true
  else
    log "La API no estaba en marcha."
  fi
  rm -f "$PID_FILE"
  mode="$(cat "$REDIS_MODE_FILE" 2>/dev/null || echo none)"
  case "$mode" in
    docker) log "Parando Redis (Docker)..."; docker compose -f "$ROOT/docker-compose.yml" down >/dev/null 2>&1 || true ;;
    local)  if is_running "$REDIS_PID_FILE"; then log "Parando Redis local..."; kill "$(cat "$REDIS_PID_FILE")" 2>/dev/null || true; fi ;;
  esac
  rm -f "$REDIS_PID_FILE" "$REDIS_MODE_FILE"
  log "Parado."
}

status() {
  if is_running "$PID_FILE"; then
    log "API en marcha (pid $(cat "$PID_FILE")): $(curl -fsS "http://localhost:$PORT/api/health" 2>/dev/null || echo 'sin respuesta')"
  else
    log "API parada."
  fi
  log "Redis: $(cat "$REDIS_MODE_FILE" 2>/dev/null || echo parado)"
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  restart) stop; start ;;
  status) status ;;
  *) echo "Uso: $0 start|stop|restart|status"; exit 2 ;;
esac
