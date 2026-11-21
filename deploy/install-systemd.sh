#!/bin/bash
# Copy systemd units for Metrolinks (paths default to /srv/metrolinks).
# Prefer first-time: sudo bash deploy/beside-somasmart.sh
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

if [ "$APP_DIR" != "/srv/metrolinks" ]; then
  for f in metrolinks-gunicorn metrolinks-celery metrolinks-celerybeat; do
    sed -i "s|/srv/metrolinks|$APP_DIR|g" "/etc/systemd/system/${f}.service"
  done
fi

systemctl daemon-reload
systemctl enable --now metrolinks-gunicorn metrolinks-celery metrolinks-celerybeat
systemctl status metrolinks-gunicorn --no-pager
echo "Installed. Logs: journalctl -u metrolinks-gunicorn -f"
