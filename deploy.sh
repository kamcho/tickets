#!/bin/bash
# Redeploy Metrolinks on the shared Soma Smart VPS (after git pull).
# Usage: bash deploy.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

VENV_DIR="${VENV_DIR:-$APP_DIR/.venv}"
PYTHON="${PYTHON:-$VENV_DIR/bin/python}"
PIP="${PIP:-$VENV_DIR/bin/pip}"
APP_USER="${APP_USER:-metrolinks}"

echo "==> Deploying Metrolinks in $APP_DIR (shared VPS — Soma Smart untouched)"

if [ ! -x "$PYTHON" ]; then
  echo "ERROR: Python not found at $PYTHON"
  echo "First-time install: sudo bash deploy/beside-somasmart.sh"
  exit 1
fi

if [ ! -f "$APP_DIR/.env" ]; then
  echo "ERROR: Missing $APP_DIR/.env — copy .env.hostinger.example or run beside-somasmart.sh"
  exit 1
fi

echo "==> Installing dependencies"
"$PIP" install -r requirements.txt --quiet

run_manage() {
  if id "$APP_USER" >/dev/null 2>&1 && [ "$(id -u)" -eq 0 ]; then
    sudo -u "$APP_USER" "$PYTHON" manage.py "$@"
  else
    "$PYTHON" manage.py "$@"
  fi
}

echo "==> Running migrations"
run_manage migrate --noinput

echo "==> Collecting static files"
run_manage collectstatic --noinput

# nginx (www-data) must traverse staticfiles/ when serving /static/
if [ -d "$APP_DIR/staticfiles" ]; then
  find "$APP_DIR/staticfiles" -type d -exec chmod 755 {} +
  find "$APP_DIR/staticfiles" -type f -exec chmod 644 {} +
fi

mkdir -p "$APP_DIR/tmp" "$APP_DIR/media"

reload_unit() {
  local unit="$1"
  if systemctl cat "$unit" &>/dev/null; then
    echo "==> Restarting $unit"
    sudo systemctl restart "$unit"
  else
    echo "==> Skipping $unit (not installed)"
  fi
}

reload_unit metrolinks-gunicorn.service
reload_unit metrolinks-celery.service
reload_unit metrolinks-celerybeat.service

# Sanity: Soma Smart still up if present
if systemctl cat elearning.service &>/dev/null; then
  if systemctl is-active --quiet elearning; then
    echo "==> Soma Smart (elearning) still active"
  else
    echo "WARN: elearning service is not active — check: systemctl status elearning"
  fi
fi

echo "==> Deploy finished OK"
echo "    Logs: sudo journalctl -u metrolinks-gunicorn -f"
