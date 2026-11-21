#!/usr/bin/env python3
"""Push STATIC_URL + CSS hotfix and collectstatic on VPS."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

HOST = os.environ.get("DEPLOY_HOST", "185.170.196.219")
USER = os.environ.get("DEPLOY_USER", "root")
PASSWORD = os.environ.get("DEPLOY_SSH_PASSWORD", "")
REPO = Path(__file__).resolve().parent.parent

FILES = [
    REPO / "ticket" / "settings.py",
    REPO / "core" / "static" / "core" / "css" / "style.css",
    REPO / "core" / "static" / "core" / "css" / "landing.css",
    REPO / "core" / "templates" / "core" / "landing.html",
]


def upload(sftp, local: Path, remote: str) -> None:
    data = local.read_bytes()
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
    for local in FILES:
        rel = local.relative_to(REPO).as_posix()
        upload(sftp, local, f"/srv/metrolinks/{rel}")
        print("uploaded", rel)
    sftp.close()

    cmd = r"""
set -e
cd /srv/metrolinks
sudo -u metrolinks .venv/bin/python manage.py collectstatic --noinput
find staticfiles -type d -exec chmod 755 {} +
find staticfiles -type f -exec chmod 644 {} +
systemctl restart metrolinks-gunicorn
curl -sI -o /dev/null -w 'css %{http_code}\n' http://127.0.0.1:8080/static/core/css/style.css
curl -sI -o /dev/null -w 'login-css %{http_code}\n' 'http://127.0.0.1:8080/static/core/css/style.css' -H 'Host: 185.170.196.219' --path-as-is
"""
    _, out, _ = client.exec_command(cmd, get_pty=True, timeout=300)
    print(out.read().decode())
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())