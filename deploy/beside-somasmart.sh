#!/usr/bin/env bash
# Install Metrolinks NEXT TO Soma Smart (Elearning) on the shared VPS.
# Safe: does not edit /srv/elearning, elearning.service, or the elearning nginx site.
#
# Prerequisites: code already at /srv/metrolinks (git clone or upload).
# Usage (as root): sudo bash /srv/metrolinks/deploy/beside-somasmart.sh
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  exec sudo bash "$0" "$@"
fi

APP=/srv/metrolinks
ELEARNING_NGINX=/etc/nginx/sites-available/elearning
ELEARNING_BEFORE=""
if [[ -f "$ELEARNING_NGINX" ]]; then
  ELEARNING_BEFORE="$(sha256sum "$ELEARNING_NGINX")"
fi

if [[ ! -f "$APP/manage.py" ]]; then
  echo "ERROR: $APP/manage.py missing. Clone/upload the app first:"
  echo "  git clone YOUR_REPO $APP"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

# --- OS packages (idempotent; won't remove Soma Smart stack) ---
apt-get update -y
apt-get install -y python3 python3-venv python3-pip nginx redis-server \
  certbot python3-certbot-nginx git curl ufw

# Postgres should already exist for Soma Smart; ensure client libs present
apt-get install -y libpq-dev postgresql postgresql-contrib || true
systemctl enable --now redis-server postgresql nginx || true

# --- Isolated app user (same pattern as elearning / crowdsource) ---
if ! id metrolinks >/dev/null 2>&1; then
  useradd --system --gid www-data --home-dir "$APP" --shell /usr/sbin/nologin metrolinks
fi

# --- Python venv ---
python3 -m venv "$APP/.venv"
"$APP/.venv/bin/pip" install --upgrade pip
"$APP/.venv/bin/pip" install --no-cache-dir -r "$APP/requirements.txt"

# --- Dedicated Postgres DB (separate from elearning) ---
DB_PASSWORD=""
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='metrolinks'" | grep -q 1; then
  DB_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  sudo -u postgres psql -v ON_ERROR_STOP=1 -c "CREATE USER metrolinks WITH PASSWORD '${DB_PASSWORD}'"
fi
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='metrolinks'" | grep -q 1; then
  sudo -u postgres psql -v ON_ERROR_STOP=1 -c "CREATE DATABASE metrolinks OWNER metrolinks"
fi
sudo -u postgres psql -v ON_ERROR_STOP=1 -d metrolinks -c "GRANT ALL ON SCHEMA public TO metrolinks"

# --- .env (create once; never overwrite secrets) ---
if [[ ! -f "$APP/.env" ]]; then
  if [[ -z "${DB_PASSWORD}" ]]; then
    DB_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
    sudo -u postgres psql -v ON_ERROR_STOP=1 -c "ALTER USER metrolinks WITH PASSWORD '${DB_PASSWORD}'"
  fi
  SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')"
  umask 077
  cat > "$APP/.env" << EOF
DEBUG=False
SECRET_KEY=${SECRET_KEY}
TIME_ZONE=Africa/Nairobi
LOG_LEVEL=INFO

ALLOWED_HOSTS=metrolinkssolutionltd.co.ke,www.metrolinkssolutionltd.co.ke,tickets.metrolinkssolutionltd.co.ke,127.0.0.1,localhost
CSRF_TRUSTED_ORIGINS=https://metrolinkssolutionltd.co.ke,https://www.metrolinkssolutionltd.co.ke,https://tickets.metrolinkssolutionltd.co.ke
SITE_BASE_URL=https://tickets.metrolinkssolutionltd.co.ke
TICKETS_PORTAL_LOGIN_URL=https://tickets.metrolinkssolutionltd.co.ke/portal/login/
PARENT_HOST=metrolinkssolutionltd.co.ke

SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True

DB_ENGINE=postgres
DB_NAME=metrolinks
DB_USER=metrolinks
DB_PASSWORD=${DB_PASSWORD}
DB_HOST=127.0.0.1
DB_PORT=5432

# Redis DB 1 — leave DB 0 free for other apps on this VPS
CELERY_BROKER_URL=redis://127.0.0.1:6379/1
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/1
CELERY_TASK_ALWAYS_EAGER=False

GUNICORN_WORKERS=2
GUNICORN_BIND=unix:/run/metrolinks/metrolinks.sock

SMS_DEBUG_PRINT=False
EOF
  echo "==> Created $APP/.env — add Ujumbe / M-Pesa keys before go-live"
fi

mkdir -p "$APP/tmp" "$APP/media" "$APP/staticfiles"
chown -R metrolinks:www-data "$APP"
chmod 640 "$APP/.env"
chmod 755 /srv "$APP"

# --- Migrate + static ---
sudo -u metrolinks "$APP/.venv/bin/python" "$APP/manage.py" migrate --noinput
sudo -u metrolinks "$APP/.venv/bin/python" "$APP/manage.py" collectstatic --noinput
find "$APP/staticfiles" -type d -exec chmod 755 {} +
find "$APP/staticfiles" -type f -exec chmod 644 {} +

# --- systemd (gunicorn + celery) ---
cp "$APP/deploy/systemd/metrolinks-gunicorn.service" /etc/systemd/system/
cp "$APP/deploy/systemd/metrolinks-celery.service" /etc/systemd/system/
cp "$APP/deploy/systemd/metrolinks-celerybeat.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now metrolinks-gunicorn metrolinks-celery metrolinks-celerybeat
systemctl is-active --quiet metrolinks-gunicorn

# --- nginx site (additive only) ---
cp "$APP/deploy/nginx/metrolinks.conf" /etc/nginx/sites-available/metrolinks
ln -sf /etc/nginx/sites-available/metrolinks /etc/nginx/sites-enabled/metrolinks
nginx -t
systemctl reload nginx

# --- Prove we did not touch Soma Smart nginx ---
if [[ -n "$ELEARNING_BEFORE" ]]; then
  ELEARNING_AFTER="$(sha256sum "$ELEARNING_NGINX")"
  if [[ "$ELEARNING_BEFORE" != "$ELEARNING_AFTER" ]]; then
    echo "ERROR: elearning nginx site changed — aborting integrity check failed."
    exit 1
  fi
  echo "==> Verified: elearning nginx site unchanged"
fi

echo ""
echo "==> Metrolinks installed beside Soma Smart"
echo "    App:     $APP"
echo "    Service: metrolinks-gunicorn (socket /run/metrolinks/metrolinks.sock)"
echo "    DB:      postgres / metrolinks (separate from elearning)"
echo "    Redis:   db 1"
echo ""
echo "Next:"
echo "  1. Point www + tickets DNS A records at this VPS IP"
echo "  2. sudo certbot --nginx -d metrolinkssolutionltd.co.ke -d www.metrolinkssolutionltd.co.ke -d tickets.metrolinkssolutionltd.co.ke"
echo "  3. Edit $APP/.env for SMS / M-Pesa, then: sudo systemctl restart metrolinks-gunicorn metrolinks-celery metrolinks-celerybeat"
echo "  4. sudo -u metrolinks $APP/.venv/bin/python $APP/manage.py createsuperuser"
