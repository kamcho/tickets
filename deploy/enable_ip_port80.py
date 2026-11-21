#!/usr/bin/env python3
"""Serve Metrolinks on http://VPS_IP/ (port 80) without breaking Soma Smart domains."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

HOST = os.environ.get("DEPLOY_HOST", "185.170.196.219")
PASSWORD = os.environ.get("DEPLOY_SSH_PASSWORD", "")
CONF = Path(__file__).resolve().parent / "nginx" / "metrolinks-ip.conf"


def main() -> int:
    if not PASSWORD:
        print("Set DEPLOY_SSH_PASSWORD", file=sys.stderr)
        return 1
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username="root", password=PASSWORD, timeout=30, allow_agent=False, look_for_keys=False)
    sftp = client.open_sftp()
    data = CONF.read_text(encoding="utf-8").replace("\r\n", "\n").encode()
    with sftp.file("/srv/metrolinks/deploy/nginx/metrolinks-ip.conf", "wb") as f:
        f.write(data)
    sftp.close()

    remote = """
set -e
cp /srv/metrolinks/deploy/nginx/metrolinks-ip.conf /etc/nginx/sites-available/metrolinks-ip
ln -sf /etc/nginx/sites-available/metrolinks-ip /etc/nginx/sites-enabled/metrolinks-ip
for f in /etc/nginx/sites-available/elearning /etc/nginx/sites-enabled/elearning; do
  if [ -f "$f" ]; then
    sed -i 's/ 185.170.196.219//g; s/ 159.223.143.29//g' "$f"
    sed -i 's/server_name  /server_name /g' "$f"
  fi
done
nginx -t
systemctl reload nginx
echo === CHECK ===
curl -sI http://127.0.0.1/login/ -H 'Host: 185.170.196.219' | head -6
curl -sI http://127.0.0.1/ -H 'Host: somasmartassesments.com' | head -3
"""
    _, out, err = client.exec_command(remote, timeout=60)
    print(out.read().decode())
    e = err.read().decode()
    if e.strip():
        print(e, file=sys.stderr)
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())