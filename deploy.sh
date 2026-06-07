#!/bin/bash
# Run on the server after git pull (cPanel deployment hook or manual SSH).
# Usage: bash deploy.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

# --- Configure for your cPanel account (or set in cPanel Git "Deploy" env) ---
# Example: /home/metroli4/virtualenv/tickets.metrolinkssolutionltd.co.ke/3.11/bin/python
PYTHON="${PYTHON:-python3}"
PIP="${PIP:-pip}"

echo "==> Deploying in $APP_DIR"

if [ -f requirements.txt ]; then
  echo "==> Installing dependencies"
  "$PIP" install -r requirements.txt --quiet
fi

if [ -f manage.py ]; then
  echo "==> Running migrations"
  "$PYTHON" manage.py migrate --noinput

  echo "==> Collecting static files"
  "$PYTHON" manage.py collectstatic --noinput
fi

mkdir -p tmp
touch tmp/restart.txt
echo "==> Passenger restart triggered (tmp/restart.txt)"

echo "==> Deploy finished OK"
