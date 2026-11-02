#!/usr/bin/env python3
"""Install PasarGuard node on Iran and populate panel core/group/hosts.

Never prints secret values.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from pathlib import Path

ENV = Path("/root/.vpn-secrets/.env")
IRAN = "root@${IRAN_IP}"
SCRIPTS = Path("/root/vpn-infra/scripts")
ZIP = Path("/tmp/pg-node-dist/pasarguard-node-linux-amd64.zip")
IDS = Path("/var/lib/pasarguard/bootstrap-ids.json")
KEYFILE = Path("/var/lib/pasarguard/panel-api-key")


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for ln in ENV.read_text().splitlines():
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def upsert_env(key: str, val: str) -> None:
    lines = ENV.read_text().splitlines()
    out: list[str] = []
    found = False
    prefix = f"{key}="
    for ln in lines:
        if ln.startswith(prefix) or ln.startswith(f"{key} ="):
            out.append(f'{key}="{val}"')
            found = True
        else:
            out.append(ln)
    if not found:
        out.append(f'{key}="{val}"')
    ENV.write_text("\n".join(out) + "\n")
    os.chmod(ENV, 0o600)


def sh(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, text=True, **kw)


def ssh(remote: str) -> str:
    r = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", IRAN, remote],
        check=True,
        text=True,
        capture_output=True,
    )
    return r.stdout


def scp(local: str, remote: str) -> None:
    sh(["scp", "-o", "BatchMode=yes", local, f"{IRAN}:{remote}"])


def main() -> None:
    env = load_env()
    node_key = env.get("PG_NODE_API_KEY") or str(uuid.uuid4())
    upsert_env("PG_NODE_API_KEY", node_key)
    env = load_env()

    if not ZIP.exists():
        raise SystemExit("missing node zip")

    print("installing pg-node on iran")
    scp(str(ZIP), "/tmp/pasarguard-node-linux-amd64.zip")
    scp("/root/vpn-infra/configs/nftables-iran.conf", "/tmp/nftables-iran.conf")
    scp("/root/vpn-infra/scripts/vpn-path", "/tmp/vpn-path")

    node_env = f"""SERVICE_PORT=62050
NODE_HOST=0.0.0.0
SERVICE_PROTOCOL=grpc
API_KEY={node_key}
SSL_CERT_FILE=/var/lib/pg-node/certs/ssl_cert.pem
SSL_KEY_FILE=/var/lib/pg-node/certs/ssl_key.pem
XRAY_EXECUTABLE_PATH=/usr/local/bin/xray
XRAY_ASSETS_PATH=/usr/local/share/xray
GENERATED_CONFIG_PATH=/var/lib/pg-node/generated
"""
    subprocess.run(
        ["ssh", "-o", "BatchMode=yes", IRAN, "cat > /tmp/pg-node.env && chmod 600 /tmp/pg-node.env"],
        check=True,
        input=node_env,
        text=True,
    )

    ssh(
        """
set -euo pipefail
apt-get install -y -qq unzip openssl >/dev/null
mkdir -p /var/lib/pg-node/certs /var/lib/pg-node/generated
unzip -o /tmp/pasarguard-node-linux-amd64.zip -d /tmp/pg-node-bin >/dev/null
install -m 755 /tmp/pg-node-bin/pasarguard-node-linux-amd64 /usr/local/bin/pasarguard-node
install -m 600 /tmp/pg-node.env /var/lib/pg-node/.env
if [ ! -s /var/lib/pg-node/certs/ssl_cert.pem ]; then
  openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -days 3650 -nodes \
    -keyout /var/lib/pg-node/certs/ssl_key.pem -out /var/lib/pg-node/certs/ssl_cert.pem \
    -subj "/CN=pg-node-iran" >/dev/null 2>&1
  chmod 600 /var/lib/pg-node/certs/ssl_key.pem /var/lib/pg-node/certs/ssl_cert.pem
fi
install -m 755 /tmp/vpn-path /usr/local/sbin/vpn-path
install -m 644 /tmp/nftables-iran.conf /etc/nftables.conf
nft -f /etc/nftables.conf
cat > /etc/systemd/system/pg-node.service << 'EOF'
[Unit]
Description=PasarGuard Node
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
WorkingDirectory=/var/lib/pg-node
EnvironmentFile=/var/lib/pg-node/.env
ExecStart=/usr/local/bin/pasarguard-node
Restart=on-failure
RestartSec=2
LimitNOFILE=1048576
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now pg-node
sleep 1
systemctl is-active pg-node
ss -lntp | grep 62050 || true
"""
    )

    cert_len = int(ssh("wc -c < /var/lib/pg-node/certs/ssl_cert.pem").strip())
    print("node_cert_bytes", cert_len)
    if cert_len > 2000:
        raise SystemExit("node cert too large for panel server_ca limit")
    sh(["scp", "-o", "BatchMode=yes", f"{IRAN}:/var/lib/pg-node/certs/ssl_cert.pem", "/tmp/pg-node.crt"])

    inp = {
        "testuser_uuid": env["TESTUSER_UUID"],
        "testuser2_uuid": env["TESTUSER2_UUID"],
        "node_api_key": node_key,
    }
    Path("/tmp/pg-bootstrap-input.json").write_text(json.dumps(inp))
    os.chmod("/tmp/pg-bootstrap-input.json", 0o600)

    print("bootstrap core/group/hosts (no node yet)")
    sh(["docker", "exec", "pasarguard", "mkdir", "-p", "/root/.pg_nodes/certs"])
    sh(["docker", "cp", "/root/.pg_nodes/certs/fullchain.pem", "pasarguard:/root/.pg_nodes/certs/fullchain.pem"])
    sh(["docker", "cp", "/root/.pg_nodes/certs/privkey.pem", "pasarguard:/root/.pg_nodes/certs/privkey.pem"])
    sh(["docker", "cp", str(SCRIPTS / "pg_bootstrap_panel.py"), "pasarguard:/tmp/pg_bootstrap_panel.py"])
    sh(["docker", "cp", "/root/.pg_nodes/iran/xray.json", "pasarguard:/tmp/iran-xray.json"])
    sh(["docker", "cp", "/tmp/pg-bootstrap-input.json", "pasarguard:/tmp/pg-bootstrap-input.json"])
    r = subprocess.run(
        [
            "docker",
            "exec",
            "-w",
            "/code",
            "-e",
            "PYTHONPATH=/code",
            "pasarguard",
            "/code/.venv/bin/python",
            "/tmp/pg_bootstrap_panel.py",
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    print("bootstrap1_rc", r.returncode)
    if r.stdout:
        print(r.stdout[-2000:])
    if r.returncode != 0:
        err = r.stderr[-2500:] if r.stderr else ""
        print("bootstrap1_err", err)
        raise SystemExit("bootstrap1 failed")

    print("cutover: stop systemd xray, register node")
    ssh("systemctl disable --now xray || true")
    sh(["docker", "cp", "/tmp/pg-node.crt", "pasarguard:/tmp/pg-node.crt"])
    r2 = subprocess.run(
        [
            "docker",
            "exec",
            "-w",
            "/code",
            "-e",
            "PYTHONPATH=/code",
            "pasarguard",
            "/code/.venv/bin/python",
            "/tmp/pg_bootstrap_panel.py",
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    print("bootstrap2_rc", r2.returncode)
    if r2.stdout:
        print(r2.stdout[-2000:])
    if r2.returncode != 0:
        print("bootstrap2_err", (r2.stderr or "")[-2500:])
        print("rollback xray")
        ssh("systemctl enable --now xray")
        raise SystemExit("bootstrap2 failed")

    ids = json.loads(IDS.read_text()) if IDS.exists() else {}
    if KEYFILE.exists():
        upsert_env("PANEL_API_KEY", KEYFILE.read_text().strip())
    if ids.get("core_id"):
        upsert_env("PG_CORE_ID", str(ids["core_id"]))
    if ids.get("group_id"):
        upsert_env("PG_GROUP_ID", str(ids["group_id"]))
    if ids.get("node_id"):
        upsert_env("PG_NODE_ID", str(ids["node_id"]))
    print("ids", {k: ids.get(k) for k in ("core_id", "group_id", "node_id", "node_status", "users_created", "users_skipped", "hosts_created")})

    sh(["install", "-m", "755", str(SCRIPTS / "vpn-path-remote.sh"), "/usr/local/sbin/vpn-path"])
    sh(["install", "-m", "755", str(SCRIPTS / "vpn-path-core.py"), "/usr/local/sbin/vpn-path-core.py"])

    for _ in range(12):
        st = ssh("systemctl is-active pg-node; ss -lntp | grep -E ':443|:2053|:62050' || true")
        print("iran_listen", " ".join(st.split()))
        time.sleep(2)
        if ":443" in st and ":62050" in st:
            break

    print("DONE")


if __name__ == "__main__":
    main()
