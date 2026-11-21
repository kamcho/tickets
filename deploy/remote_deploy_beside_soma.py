#!/usr/bin/env python3
"""Upload Metrolinks to the shared Soma Smart VPS and run beside-somasmart.sh.

Reads DEPLOY_SSH_PASSWORD from the environment (never commit passwords).
"""
from __future__ import annotations

import os
import sys
import tempfile
import zipfile
from pathlib import Path

import paramiko

HOST = os.environ.get("DEPLOY_HOST", "185.170.196.219")
USER = os.environ.get("DEPLOY_USER", "root")
PASSWORD = os.environ.get("DEPLOY_SSH_PASSWORD", "")
REMOTE_DIR = "/srv/metrolinks"
REPO_ROOT = Path(__file__).resolve().parent.parent

SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules",
    "staticfiles", "media", ".cursor", "tmp",
}
SKIP_FILES = {".env", "db.sqlite3", ".DS_Store"}


def should_skip(rel: Path) -> bool:
    if set(rel.parts) & SKIP_DIRS:
        return True
    if rel.name in SKIP_FILES:
        return True
    if rel.suffix == ".pyc":
        return True
    return False


def make_zip() -> Path:
    fd, path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    zpath = Path(path)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in REPO_ROOT.rglob("*"):
            if not item.is_file():
                continue
            rel = item.relative_to(REPO_ROOT)
            if should_skip(rel):
                continue
            # Normalize text scripts to LF so bash on Linux is happy
            data = item.read_bytes()
            if rel.suffix in {".sh", ".py", ".service", ".conf", ".md", ".txt", ".example"} or rel.name in {
                "deploy.sh", "requirements.txt", "manage.py",
            }:
                try:
                    text = data.decode("utf-8")
                    data = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
                except UnicodeDecodeError:
                    pass
            zf.writestr(rel.as_posix(), data)
    return zpath


def run_ssh(client: paramiko.SSHClient, cmd: str, timeout: int = 1800) -> int:
    print(f"\n$ {cmd}\n")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout, get_pty=True)
    for line in iter(stdout.readline, ""):
        if not line:
            break
        print(line, end="")
    err = stderr.read().decode(errors="replace")
    if err.strip():
        print(err, file=sys.stderr)
    return stdout.channel.recv_exit_status()


def main() -> int:
    if not PASSWORD:
        print("Set DEPLOY_SSH_PASSWORD in the environment.", file=sys.stderr)
        return 1

    print(f"Packaging {REPO_ROOT} ...")
    archive = make_zip()
    print(f"Archive size: {archive.stat().st_size / 1024 / 1024:.1f} MB")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {USER}@{HOST} ...")
    client.connect(HOST, username=USER, password=PASSWORD, timeout=60)

    # Preflight: Soma Smart still there
    print("Preflight: checking elearning ...")
    run_ssh(client, "systemctl is-active elearning nginx postgresql; ls -la /srv/elearning/manage.py 2>/dev/null | head -1")

    remote_zip = "/tmp/metrolinks-deploy.zip"
    print("Uploading ...")
    sftp = client.open_sftp()
    sftp.put(str(archive), remote_zip)
    sftp.close()
    archive.unlink(missing_ok=True)

    script = f"""
set -euo pipefail
apt-get install -y -qq unzip rsync >/dev/null
mkdir -p {REMOTE_DIR}
# Replace app code but keep existing .env / media / staticfiles / venv if present
TMP=/tmp/metrolinks-src
rm -rf "$TMP"
mkdir -p "$TMP"
unzip -o -q {remote_zip} -d "$TMP"
rm -f {remote_zip}

# Preserve secrets and runtime data
if [ -f {REMOTE_DIR}/.env ]; then cp -a {REMOTE_DIR}/.env /tmp/metrolinks.env.bak; fi
rsync -a --delete \\
  --exclude '.env' --exclude '.venv' --exclude 'media' --exclude 'staticfiles' --exclude 'tmp' --exclude 'db.sqlite3' \\
  "$TMP"/ {REMOTE_DIR}/
if [ -f /tmp/metrolinks.env.bak ]; then mv /tmp/metrolinks.env.bak {REMOTE_DIR}/.env; fi
rm -rf "$TMP"

chmod +x {REMOTE_DIR}/deploy.sh {REMOTE_DIR}/deploy/*.sh
sed -i 's/\\r$//' {REMOTE_DIR}/deploy.sh {REMOTE_DIR}/deploy/*.sh || true

bash {REMOTE_DIR}/deploy/beside-somasmart.sh

echo "==== POSTCHECK ===="
systemctl is-active elearning metrolinks-gunicorn metrolinks-celery || true
curl -sI -o /dev/null -w "elearning HTTP %{{http_code}}\\n" http://127.0.0.1/ -H "Host: somasmartassesments.com" || true
ss -ltnp | grep -E 'elearning|metrolinks|nginx' || true
ls -la /run/metrolinks/ 2>/dev/null || true
"""
    code = run_ssh(client, script, timeout=2400)
    client.close()
    if code != 0:
        print(f"Remote deploy failed with exit {code}", file=sys.stderr)
        return code
    print("\nDeploy finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
