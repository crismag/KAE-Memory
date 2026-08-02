#!/usr/bin/env bash
# Run the whole system locally: database, API, worker, and workspace.
#
# Everything is local and nothing is deployed. The API binds to loopback, the
# database runs in Docker with a persistent volume, and the workspace is served
# by Vite with a proxy so the browser sees one origin — the same shape ADR-0017
# recommends for a real deployment, which means no CORS to configure here.
#
# Ctrl-C stops all three processes. The database keeps running, on purpose: it
# holds your projects, and restarting it every time would make "persistent
# memory" a claim rather than something you can see.
set -euo pipefail

cd "$(dirname "$0")/../.."

DEV_DB_CONTAINER=${DEV_DB_CONTAINER:-kae-crdb-dev}
DEV_DB_PORT=${DEV_DB_PORT:-26259}
DEV_DB_VERSION=${DEV_DB_VERSION:-v26.2.1}
DEV_DB_VOLUME=${DEV_DB_VOLUME:-kae-crdb-dev-data}
API_PORT=${KAE_API_PORT:-8000}
UI_PORT=${UI_PORT:-5173}

export KAE_DATABASE_URL=${KAE_DATABASE_URL:-"cockroachdb+psycopg://root@localhost:${DEV_DB_PORT}/kae_dev?sslmode=disable"}
export KAE_API_PORT=$API_PORT
export KAE_LOG_LEVEL=${KAE_LOG_LEVEL:-INFO}

say() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

for tool in docker uv npm; do
  have "$tool" || { echo "$tool is required but not installed" >&2; exit 1; }
done

# Fail before starting anything rather than after. A port already in use used to
# leave the API dead while the script printed a summary claiming it was up.
port_busy() { (ss -ltn 2>/dev/null || netstat -ltn 2>/dev/null) | grep -q ":$1 "; }
for port in "$API_PORT" "$UI_PORT"; do
  if port_busy "$port"; then
    echo "port $port is already in use — stop whatever holds it, or set" >&2
    echo "KAE_API_PORT / UI_PORT to something else" >&2
    exit 1
  fi
done

say "database on port $DEV_DB_PORT"
if [[ "$(docker inspect -f '{{.State.Running}}' "$DEV_DB_CONTAINER" 2>/dev/null)" != "true" ]]; then
  docker rm -f "$DEV_DB_CONTAINER" >/dev/null 2>&1 || true
  # A named volume, not type=mem: the test database is disposable, this one is
  # not. Losing your projects on every restart would hide the product's point.
  docker volume create "$DEV_DB_VOLUME" >/dev/null
  docker run -d --name "$DEV_DB_CONTAINER" \
    -p "${DEV_DB_PORT}:26257" -p 8081:8080 \
    -v "${DEV_DB_VOLUME}:/cockroach/cockroach-data" \
    "cockroachdb/cockroach:${DEV_DB_VERSION}" \
    start-single-node --insecure >/dev/null
  printf 'waiting'
  until docker exec "$DEV_DB_CONTAINER" ./cockroach sql --insecure -e 'SELECT 1' >/dev/null 2>&1; do
    printf '.'; sleep 1
  done
  echo
fi
docker exec "$DEV_DB_CONTAINER" ./cockroach sql --insecure \
  -e 'CREATE DATABASE IF NOT EXISTS kae_dev' >/dev/null
echo "ready — DB console at http://localhost:8081"

say "migrations"
uv run alembic upgrade head 2>&1 | grep -E 'Running upgrade|already at' || echo "schema current"

say "frontend dependencies"
[[ -d frontend/node_modules ]] || npm --prefix frontend ci

PIDS=()
cleanup() {
  echo
  say "stopping"
  # SIGTERM, not SIGKILL: the worker's graceful path releases its lease so a run
  # in flight is immediately claimable rather than waiting out its expiry.
  #
  # Descendants first. `npm run dev` spawns Vite as a child, and signalling only
  # the npm wrapper leaves Vite holding the port — which then blocks the next
  # start with a confusing "address already in use".
  for pid in "${PIDS[@]:-}"; do
    pkill -TERM -P "$pid" 2>/dev/null || true
    kill -TERM "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  echo "the database is still running — 'make dev-db-down' to stop it"
}
trap cleanup EXIT INT TERM

say "api on http://127.0.0.1:$API_PORT"
uv run python -m kae_memory.api & PIDS+=($!)

say "worker (offline extractor unless KAE_EXTRACTION=bedrock)"
uv run python -m kae_memory.worker & PIDS+=($!)

say "waiting for the api"
for attempt in $(seq 1 30); do
  if body=$(curl -fsS "http://127.0.0.1:${API_PORT}/health" 2>/dev/null); then
    echo "$body"
    break
  fi
  # A dead API must not be reported as a healthy stack.
  kill -0 "${PIDS[0]}" 2>/dev/null || { echo "the api exited during startup" >&2; exit 1; }
  sleep 1
  [[ $attempt -eq 30 ]] && { echo "the api did not become healthy" >&2; exit 1; }
done

say "workspace on http://localhost:$UI_PORT"
npm --prefix frontend run dev -- --port "$UI_PORT" --strictPort & PIDS+=($!)

cat <<EOF

  Workspace   http://localhost:$UI_PORT
  API docs    http://127.0.0.1:$API_PORT/docs
  Health      http://127.0.0.1:$API_PORT/health
  DB console  http://localhost:8081

  Ctrl-C stops the three processes and leaves the database running.

EOF

wait
