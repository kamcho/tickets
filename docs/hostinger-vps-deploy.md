# Hostinger VPS deployment (Metrolinks)

Stack: **nginx → Gunicorn → Django**, plus **Redis + Celery** for billing jobs. MySQL/MariaDB for data.

App path used below: `/var/www/metrolinks`. Change it consistently in systemd units and nginx if you use another path.

---

## 1. VPS prep (Ubuntu 22.04 / 24.04)

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip nginx redis-server \
  mariadb-server certbot python3-certbot-nginx git ufw
sudo systemctl enable --now redis-server mariadb nginx
```

Firewall (Hostinger panel + UFW):

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

Point DNS A records at the VPS IP:

| Host | Type | Value |
|------|------|--------|
| `@` | A | VPS IP |
| `www` | A | VPS IP |
| `tickets` | A | VPS IP |

---

## 2. Database

```bash
sudo mysql -e "CREATE DATABASE metrolinks CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
sudo mysql -e "CREATE USER 'metrolinks'@'localhost' IDENTIFIED BY 'STRONG_PASSWORD';"
sudo mysql -e "GRANT ALL ON metrolinks.* TO 'metrolinks'@'localhost'; FLUSH PRIVILEGES;"
```

---

## 3. App user & code

```bash
sudo mkdir -p /var/www/metrolinks
sudo chown "$USER":www-data /var/www/metrolinks
cd /var/www
git clone YOUR_REPO_URL metrolinks
cd metrolinks

python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt

cp .env.hostinger.example .env
nano .env   # SECRET_KEY, DB_*, domains, SMS, M-Pesa, etc.

# Generate SECRET_KEY:
python -c "import secrets; print(secrets.token_urlsafe(50))"

mkdir -p tmp media
sudo chown -R www-data:www-data media tmp
```

First migrate + static:

```bash
bash deploy.sh
# or:
python manage.py migrate --noinput
python manage.py ensure_utf8mb4
python manage.py collectstatic --noinput
python manage.py createsuperuser
```

---

## 4. Systemd

```bash
sudo cp deploy/systemd/metrolinks-*.service /etc/systemd/system/
# Edit WorkingDirectory / paths if not /var/www/metrolinks
sudo systemctl daemon-reload
sudo systemctl enable --now metrolinks-gunicorn metrolinks-celery metrolinks-celerybeat
sudo systemctl status metrolinks-gunicorn --no-pager
```

App must listen on `127.0.0.1:8000` (see `deploy/gunicorn.conf.py`).

---

## 5. Nginx + TLS

```bash
sudo cp deploy/nginx/metrolinks.conf /etc/nginx/sites-available/metrolinks
sudo ln -sf /etc/nginx/sites-available/metrolinks /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

# After DNS propagates:
sudo certbot --nginx \
  -d metrolinkssolutionltd.co.ke \
  -d www.metrolinkssolutionltd.co.ke \
  -d tickets.metrolinkssolutionltd.co.ke
```

Confirm in `.env`:

- `DEBUG=False`
- `ALLOWED_HOSTS` includes all three hostnames
- `CSRF_TRUSTED_ORIGINS` uses `https://...` for each
- `SITE_BASE_URL=https://tickets.metrolinkssolutionltd.co.ke`
- `CELERY_TASK_ALWAYS_EAGER=False`
- `PARENT_HOST=metrolinkssolutionltd.co.ke` (optional; default when DEBUG=False)

Restart after env changes:

```bash
sudo systemctl restart metrolinks-gunicorn metrolinks-celery metrolinks-celerybeat
```

---

## 6. Host routing (django-hosts)

| Hostname | Site |
|----------|------|
| `www.metrolinkssolutionltd.co.ke` | Marketing (`core.urls_main`) |
| `tickets.metrolinkssolutionltd.co.ke` | Portal / billing / tickets |
| apex (optional redirect) | → www via nginx |

---

## 7. Updates (redeploy)

```bash
cd /var/www/metrolinks
git pull
bash deploy.sh
```

`deploy.sh` installs deps, migrates, collectstatic, and restarts systemd units.

---

## 8. Smoke checks

```bash
curl -I https://www.metrolinkssolutionltd.co.ke/
curl -I https://tickets.metrolinkssolutionltd.co.ke/portal/login/
sudo journalctl -u metrolinks-gunicorn -n 50 --no-pager
sudo journalctl -u metrolinks-celery -n 50 --no-pager
redis-cli ping
```

M-Pesa: set production Daraja credentials and ensure callback URL is public HTTPS on the tickets host.

MikroTik: add each tower under Django Admin → Network routers (do not rely only on `.env` fallback).

---

## 9. Permissions note

Gunicorn/Celery run as `www-data`. After clone/pull as your SSH user:

```bash
sudo chown -R www-data:www-data /var/www/metrolinks/media /var/www/metrolinks/tmp /var/www/metrolinks/staticfiles
# Keep code readable by www-data:
sudo chmod -R g+rX /var/www/metrolinks
```

Or run git as a deploy user in group `www-data`.

---

## Files added for this setup

| Path | Role |
|------|------|
| `.env.hostinger.example` | Production env template |
| `deploy/gunicorn.conf.py` | Gunicorn workers/bind |
| `deploy/nginx/metrolinks.conf` | HTTP→HTTPS + proxy |
| `deploy/systemd/metrolinks-*.service` | App + Celery |
| `deploy.sh` | Pull-time migrate / static / restart |
| `requirements.txt` | Includes `gunicorn`, `PyMySQL` |
