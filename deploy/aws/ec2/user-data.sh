#!/usr/bin/env bash
# EC2 bootstrap. Runs once at first boot, as root.
#
# AWS-specific provisioning only: it prepares the host and then invokes the
# generic installer. It does not duplicate systemd units or nginx configuration
# — those live in deploy/server/ and stay reusable on any Linux host (ADR-0013).
set -euo pipefail

REPO_URL=${REPO_URL:-https://github.com/crismag/KAE-Memory.git}
CHECKOUT=/opt/kae-memory

apt-get update -y
apt-get install -y --no-install-recommends git python3-venv python3-pip nginx curl ca-certificates

git clone "$REPO_URL" "$CHECKOUT" 2>/dev/null || git -C "$CHECKOUT" pull --ff-only
bash "$CHECKOUT/deploy/server/install.sh"

install -m 644 "$CHECKOUT/deploy/server/reverse-proxy/kae.conf.example" \
  /etc/nginx/sites-available/kae.conf
ln -sf /etc/nginx/sites-available/kae.conf /etc/nginx/sites-enabled/kae.conf
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

cat <<'EOF' > /etc/motd

KAE-Memory host. Before the services start:

  1. set KAE_DATABASE_URL in /etc/kae-memory/{api,worker}.env
  2. run migrations
  3. systemctl enable --now kae-api kae-worker

The API has no authentication. Keep port 8000 closed to the internet; nginx on
80/443 is the only intended ingress.
EOF
