#!/bin/bash
# One-shot: copy systemd units and enable services (run on the VPS with sudo).
# Usage: sudo bash deploy/install-systemd.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="$APP_DIR/deploy/systemd"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo bash deploy/install-systemd.sh"
  exit 1
fi

cp "$UNIT_DIR"/metrolinks-gunicorn.service /etc/systemd/system/
cp "$UNIT_DIR"/metrolinks-celery.service /etc/systemd/system/
cp "$UNIT_DIR"/metrolinks-celerybeat.service /etc/systemd/system/

# If app is not at /var/www/metrolinks, rewrite paths in the installed units
if [ "$APP_DIR" != "/var/www/metrolinks" ]; then
  for f in metrolinks-gunicorn metrolinks-celery metrolinks-celerybeat; do
    sed -i "s|/var/www/metrolinks|$APP_DIR|g" "/etc/systemd/system/${f}.service"
  done
fi

systemctl daemon-reload
systemctl enable --now metrolinks-gunicorn metrolinks-celery metrolinks-celerybeat
systemctl status metrolinks-gunicorn --no-pager
echo "Installed. Logs: journalctl -u metrolinks-gunicorn -f"
