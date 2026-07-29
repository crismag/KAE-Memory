#!/usr/bin/env bash
# Update a release: fetch, install, migrate, restart, health-check.
#
# Deliberately simple. Automated rollback and release version management are
# deferred; `git checkout` of a previous ref plus a re-run is the rollback.
set -euo pipefail

APP_DIR=${APP_DIR:-/opt/kae-memory}
SERVICE_USER=${SERVICE_USER:-kae}
REF=${1:-main}
HEALTH_URL=${HEALTH_URL:-http://127.0.0.1:8000/health}

say() { printf '\n== %s\n' "$1"; }

[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }

say "fetching $REF"
sudo -u "$SERVICE_USER" git -C "$APP_DIR" fetch --quiet origin
sudo -u "$SERVICE_USER" git -C "$APP_DIR" checkout --quiet "$REF"
sudo -u "$SERVICE_USER" git -C "$APP_DIR" pull --quiet --ff-only origin "$REF" || true

say "dependencies"
sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/pip" install --quiet -e "$APP_DIR[api]"

say "migrations"
# Before the restart: the new code must not meet an old schema. Additive
# migrations make the reverse order safe too, but not every future one will be.
sudo -u "$SERVICE_USER" --preserve-env=KAE_DATABASE_URL \
  env "$(grep -E '^KAE_DATABASE_URL=' /etc/kae-memory/api.env | head -1)" \
  "$APP_DIR/.venv/bin/alembic" -c "$APP_DIR/alembic.ini" upgrade head

say "restarting"
# The worker first: it drains gracefully, and the API restarting under it would
# not have helped it finish.
systemctl restart kae-worker
systemctl restart kae-api

say "health"
for attempt in $(seq 1 30); do
  if body=$(curl -fsS "$HEALTH_URL" 2>/dev/null); then
    echo "$body"
    python3 -c 'import json,sys; sys.exit(0 if json.loads(sys.argv[1])["status"] == "ok" else 1)' "$body" \
      && { echo "healthy after ${attempt}s"; exit 0; }
  fi
  sleep 1
done

echo "the API did not report healthy" >&2
systemctl --no-pager --lines=20 status kae-api || true
exit 1
