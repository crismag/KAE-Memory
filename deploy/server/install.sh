#!/usr/bin/env bash
# Prepare a Linux host to run KAE-Memory. Idempotent: safe to re-run.
#
# Installs no Docker, assumes no hosting provider, creates no AWS resources, and
# embeds no credentials. Environment files are created empty and root-owned for
# an operator to fill in (FR-018).
set -euo pipefail

APP_DIR=${APP_DIR:-/opt/kae-memory}
ENV_DIR=${ENV_DIR:-/etc/kae-memory}
LOG_DIR=${LOG_DIR:-/var/log/kae-memory}
WEB_DIR=${WEB_DIR:-/var/www/kae-memory}
SERVICE_USER=${SERVICE_USER:-kae}
REPO_URL=${REPO_URL:-https://github.com/crismag/KAE-Memory.git}

say() { printf '\n== %s\n' "$1"; }

[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }

say "Python 3.12 or newer"
python3 --version
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' \
  || { echo "Python 3.12+ is required" >&2; exit 1; }

say "service user"
id -u "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --shell /usr/sbin/nologin "$SERVICE_USER"

say "directories"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" "$APP_DIR" "$LOG_DIR"
install -d -o root -g root -m 750 "$ENV_DIR"
install -d "$WEB_DIR"

say "application source"
if [[ -d $APP_DIR/.git ]]; then
  sudo -u "$SERVICE_USER" git -C "$APP_DIR" fetch --quiet origin
else
  sudo -u "$SERVICE_USER" git clone --quiet "$REPO_URL" "$APP_DIR"
fi

say "virtual environment"
sudo -u "$SERVICE_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/pip" install --quiet -e "$APP_DIR[api]"

say "environment files"
# Created empty rather than templated with placeholders: a file containing
# KAE_DATABASE_URL= with a fake password is one careless commit from looking real.
for unit in api worker; do
  if [[ ! -f $ENV_DIR/$unit.env ]]; then
    touch "$ENV_DIR/$unit.env"
    chmod 640 "$ENV_DIR/$unit.env"
    echo "created empty $ENV_DIR/$unit.env — set KAE_DATABASE_URL before starting"
  fi
done

say "systemd units"
install -m 644 "$(dirname "$0")/services/kae-api.service" /etc/systemd/system/
install -m 644 "$(dirname "$0")/services/kae-worker.service" /etc/systemd/system/
systemctl daemon-reload

cat <<EOF

Installed. Before starting:

  1. set KAE_DATABASE_URL in $ENV_DIR/api.env and $ENV_DIR/worker.env
  2. run migrations:  sudo -u $SERVICE_USER $APP_DIR/.venv/bin/alembic -c $APP_DIR/alembic.ini upgrade head
  3. deploy the frontend build to $WEB_DIR (see deploy/static-site/README.md)
  4. systemctl enable --now kae-api kae-worker

The API has no authentication (ADR-0014). Do not expose port 8000 publicly.
EOF
