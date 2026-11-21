#!/usr/bin/env python3
import os, sys
from pathlib import Path
import paramiko

PASSWORD = os.environ.get("DEPLOY_SSH_PASSWORD", "")
REPO = Path(__file__).resolve().parent.parent
FILES = [
    "core/views.py",
    "core/context_processors.py",
]


def main():
    if not PASSWORD:
        print("Set DEPLOY_SSH_PASSWORD", file=sys.stderr)
        return 1
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect("185.170.196.219", username="root", password=PASSWORD, timeout=30, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    for rel in FILES:
        data = (REPO / rel).read_text(encoding="utf-8").replace("\r\n", "\n").encode()
        with sftp.file(f"/srv/metrolinks/{rel}", "wb") as f:
            f.write(data)
        print("uploaded", rel)
    sftp.close()
    _, out, _ = c.exec_command("systemctl restart metrolinks-gunicorn && sleep 1 && systemctl is-active metrolinks-gunicorn", timeout=30)
    print(out.read().decode())
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())