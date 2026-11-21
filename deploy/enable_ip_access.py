#!/usr/bin/env python3
"""Enable temporary Metrolinks access via http://VPS_IP:8080 on the shared VPS."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

HOST = os.environ.get("DEPLOY_HOST", "185.170.196.219")
USER = os.environ.get("DEPLOY_USER", "root")
PASSWORD = os.environ.get("DEPLOY_SSH_PASSWORD", "")
REPO = Path(__file__).resolve().parent.parent
IP = HOST


def upload(sftp, local: Path, remote: str) -> None:
    data = local.read_bytes()
    if local.suffix in {".py", ".conf", ".sh", ".service"} or local.name.endswith(".py"):
        try:
            data = data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").encode()
        except UnicodeDecodeError:
            pass
    with sftp.file(remote, "wb") as f:
        f.write(data)


def main() -> int:
    if not PASSWORD:
        print("Set DEPLOY_SSH_PASSWORD", file=sys.stderr)
        return 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=60, allow_agent=False, look_for_keys=False)
    sftp = client.open_sftp()

    upload(sftp, REPO / "ticket" / "hosts.py", "/srv/metrolinks/ticket/hosts.py")
    upload(sftp, REPO / "ticket" / "settings.py", "/srv/metrolinks/ticket/settings.py")
    upload(sftp, REPO / "deploy" / "nginx" / "metrolinks-ip.conf", "/srv/metrolinks/deploy/nginx/metrolinks-ip.conf")
    sftp.close()

    script = f"""
set -euo pipefail
ENV=/srv/metrolinks/.env

# Patch .env for IP HTTP access (idempotent)
grep -q '^SERVE_COMBINED_ON_DEFAULT_HOST=' "$ENV" && sed -i 's/^SERVE_COMBINED_ON_DEFAULT_HOST=.*/SERVE_COMBINED_ON_DEFAULT_HOST=True/' "$ENV" || echo 'SERVE_COMBINED_ON_DEFAULT_HOST=True' >> "$ENV"
grep -q '^SECURE_SSL_REDIRECT=' "$ENV" && sed -i 's/^SECURE_SSL_REDIRECT=.*/SECURE_SSL_REDIRECT=False/' "$ENV" || echo 'SECURE_SSL_REDIRECT=False' >> "$ENV"
grep -q '^SESSION_COOKIE_SECURE=' "$ENV" && sed -i 's/^SESSION_COOKIE_SECURE=.*/SESSION_COOKIE_SECURE=False/' "$ENV" || echo 'SESSION_COOKIE_SECURE=False' >> "$ENV"
grep -q '^CSRF_COOKIE_SECURE=' "$ENV" && sed -i 's/^CSRF_COOKIE_SECURE=.*/CSRF_COOKIE_SECURE=False/' "$ENV" || echo 'CSRF_COOKIE_SECURE=False' >> "$ENV"

# ALLOWED_HOSTS: ensure IP present
if grep -q '^ALLOWED_HOSTS=' "$ENV"; then
  if ! grep -q '^ALLOWED_HOSTS=.*{IP}' "$ENV"; then
    sed -i 's/^ALLOWED_HOSTS=/ALLOWED_HOSTS={IP},/' "$ENV"
  fi
fi

# CSRF for http://IP:8080
ORIGIN="http://{IP}:8080"
if grep -q '^CSRF_TRUSTED_ORIGINS=' "$ENV"; then
  if ! grep -q "CSRF_TRUSTED_ORIGINS=.*{IP}:8080" "$ENV"; then
    sed -i "s|^CSRF_TRUSTED_ORIGINS=|CSRF_TRUSTED_ORIGINS=$ORIGIN,|" "$ENV"
  fi
else
  echo "CSRF_TRUSTED_ORIGINS=$ORIGIN" >> "$ENV"
fi

cp /srv/metrolinks/deploy/nginx/metrolinks-ip.conf /etc/nginx/sites-available/metrolinks-ip
ln -sf /etc/nginx/sites-available/metrolinks-ip /etc/nginx/sites-enabled/metrolinks-ip
ufw allow 8080/tcp || true
nginx -t
systemctl reload nginx
systemctl restart metrolinks-gunicorn

echo "==== CHECK ===="
systemctl is-active metrolinks-gunicorn elearning
curl -sI -o /dev/null -w "ip8080 %{{http_code}}\\n" "http://127.0.0.1:8080/" -H "Host: {IP}"
curl -sI -o /dev/null -w "login %{{http_code}}\\n" "http://127.0.0.1:8080/login/" -H "Host: {IP}"
curl -sI -o /dev/null -w "soma80 %{{http_code}}\\n" "http://127.0.0.1/" -H "Host: somasmartassesments.com"
"""
    _, stdout, stderr = client.exec_command(script, get_pty=True, timeout=120)
    print(stdout.read().decode())
    err = stderr.read().decode()
    if err.strip():
        print(err, file=sys.stderr)
    code = stdout.channel.recv_exit_status()
    client.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
