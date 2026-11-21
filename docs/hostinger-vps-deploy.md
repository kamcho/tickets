# Metrolinks on the Soma Smart VPS (shared)

Metrolinks runs **beside** Soma Smart (Elearning), not instead of it.

| | Soma Smart | Metrolinks |
|--|------------|------------|
| Path | `/srv/elearning` | `/srv/metrolinks` |
| systemd | `elearning` | `metrolinks-gunicorn` (+ celery) |
| Socket | `/run/elearning/elearning.sock` | `/run/metrolinks/metrolinks.sock` |
| DB | Postgres `elearning` | Postgres `metrolinks` |
| Redis | (own use) | **DB index 1** |
| nginx site | `elearning` | `metrolinks` |
| Domains | `somasmartassesments.com` | `www` + `tickets.metrolinkssolutionltd.co.ke` |

Same public IP / nginx / Redis / Postgres **server** — separate users, DBs, sockets, and site files. The install script refuses to change the elearning nginx config.

---

## First-time install (on the VPS)

```bash
# Use the same SSH host you use for Soma Smart
ssh root@YOUR_VPS_IP

git clone YOUR_METROLINKS_REPO /srv/metrolinks
sudo bash /srv/metrolinks/deploy/beside-somasmart.sh
```

That script:

1. Creates user `metrolinks` (group `www-data`)
2. Creates Postgres user/DB `metrolinks` (does not touch `elearning`)
3. Writes `.env` once (Redis DB **1**, unix socket bind)
4. Migrates + collectstatic
5. Enables gunicorn + celery units
6. Adds nginx site `metrolinks` only
7. Verifies the elearning nginx file hash is unchanged

Then:

```bash
# DNS: A records for apex, www, tickets → this VPS IP
sudo certbot --nginx \
  -d metrolinkssolutionltd.co.ke \
  -d www.metrolinkssolutionltd.co.ke \
  -d tickets.metrolinkssolutionltd.co.ke

nano /srv/metrolinks/.env   # Ujumbe, M-Pesa, etc.
sudo systemctl restart metrolinks-gunicorn metrolinks-celery metrolinks-celerybeat
sudo -u metrolinks /srv/metrolinks/.venv/bin/python /srv/metrolinks/manage.py createsuperuser
```

---

## Updates

```bash
cd /srv/metrolinks
git pull
bash deploy.sh
```

---

## Temporary access by VPS IP

| URL | App |
|-----|-----|
| `http://185.170.196.219/login/` | Metrolinks (port 80, Host = IP) |
| `http://185.170.196.219:8080/` | Metrolinks (alternate) |
| `https://somasmartassesments.com/` | Soma Smart (domain only; IP removed from elearning nginx) |

Apply after deploy: `python deploy/enable_ip_port80.py`

---

## Smoke checks (both apps)

```bash
systemctl is-active elearning metrolinks-gunicorn
curl -I https://somasmartassesments.com/
curl -I https://www.metrolinkssolutionltd.co.ke/
curl -I https://tickets.metrolinkssolutionltd.co.ke/portal/login/
sudo journalctl -u metrolinks-gunicorn -n 40 --no-pager
```

---

## Resource notes

- Gunicorn defaults to **2 workers** (`GUNICORN_WORKERS`) so Soma Smart keeps headroom.
- Celery concurrency is **1**.
- Do **not** point Metrolinks at the `elearning` Postgres database.

---

## Files

| Path | Role |
|------|------|
| `deploy/beside-somasmart.sh` | Safe first-time install beside Soma Smart |
| `deploy/nginx/metrolinks.conf` | Own nginx server_name blocks |
| `deploy/systemd/metrolinks-*.service` | App + Celery |
| `deploy/gunicorn.conf.py` | Unix socket bind |
| `.env.hostinger.example` | Env template (Postgres + Redis /1) |
| `deploy.sh` | Pull-time migrate / static / restart |
