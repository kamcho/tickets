#!/bin/bash
# Hostinger VPS deploy — run after git pull (or from CI).
# Usage (on server):
#   bash deploy.sh
# Optional:
#   APP_DIR=/var/www/metrolinks PYTHON=/var/www/metrolinks/.venv/bin/python bash deploy.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

VENV_DIR="${VENV_DIR:-$APP_DIR/.venv}"
PYTHON="${PYTHON:-$VENV_DIR/bin/python}"
PIP="${PIP:-$VENV_DIR/bin/pip}"

echo "==> Deploying Metrolinks in $APP_DIR"

if [ ! -x "$PYTHON" ]; then
  echo "ERROR: Python not found at $PYTHON"
  echo "Create the venv first: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

if [ ! -f "$APP_DIR/.env" ]; then
  echo "ERROR: Missing $APP_DIR/.env — copy .env.hostinger.example and fill secrets."
  exit 1
fi

echo "==> Installing dependencies"
"$PIP" install -r requirements.txt --quiet

echo "==> Running migrations"
"$PYTHON" manage.py migrate --noinput

if grep -qE '^DB_ENGINE=mysql' "$APP_DIR/.env" 2>/dev/null; then
  echo "==> Ensuring MySQL utf8mb4 (emoji / chat safe)"
  "$PYTHON" manage.py ensure_utf8mb4 2>/dev/null || true
fi

echo "==> Collecting static files"
"$PYTHON" manage.py collectstatic --noinput

mkdir -p "$APP_DIR/tmp" "$APP_DIR/media"
chmod 755 "$APP_DIR/tmp" "$APP_DIR/media" || true

# Restart app processes when systemd units are installed
reload_unit() {
  local unit="$1"
  if systemctl list-unit-files "$unit" &>/dev/null && systemctl cat "$unit" &>/dev/null; then
    echo "==> Restarting $unit"
    sudo systemctl restart "$unit"
  else
    echo "==> Skipping $unit (not installed)"
  fi
}

reload_unit metrolinks-gunicorn.service
reload_unit metrolinks-celery.service
reload_unit metrolinks-celerybeat.service

echo "==> Deploy finished OK"
echo "    Check: sudo systemctl status metrolinks-gunicorn --no-pager"
echo "    Logs:  sudo journalctl -u metrolinks-gunicorn -f"
