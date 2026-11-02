#!/usr/bin/env python3
"""Render VPN configs from /root/.vpn-secrets/.env. Never prints secret values."""
from __future__ import annotations

import json
import os
from pathlib import Path

ENV = Path("/root/.vpn-secrets/.env")
EXIT_DIR = Path("/root/.pg_nodes/exit")
CERT = "/etc/letsencrypt/live/vpn-stack/fullchain.pem"
KEY = "/etc/letsencrypt/live/vpn-stack/privkey.pem"
IRAN_IP = "${IRAN_IP}"
EXIT_IP = "${EXIT_IP}"
XHTTP_PATH = os.environ.get("XHTTP_PATH", "${XHTTP_PATH}")


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for ln in ENV.read_text().splitlines():
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        env[k] = v
    return env


def warp_block(env: dict[str, str]) -> dict:
    addrs = [a.strip() for a in env.get("WARP_ADDRESSES", "").split(",") if a.strip()]
    if not addrs:
        addrs = ["172.16.0.2/32"]
    settings = {
        "secretKey": env["WARP_PRIVATE_KEY"],
        "address": addrs,
        "peers": [
            {
                "publicKey": env["WARP_PEER_PUBLIC_KEY"],
                "allowedIPs": ["0.0.0.0/0", "::/0"],
                "endpoint": env.get("WARP_ENDPOINT") or "engage.cloudflareclient.com:2408",
            }
        ],
        "domainStrategy": "ForceIPv4",
        "mtu": 1280,
    }
    reserved = env.get("WARP_RESERVED", "").strip()
    if reserved and reserved.startswith("["):
        try:
            settings["reserved"] = json.loads(reserved)
        except json.JSONDecodeError:
            pass
    return {
        "tag": "WARP",
        "protocol": "wireguard",
        "settings": settings,
    }


def write(path: Path, text: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.chmod(path, mode)


def main() -> None:
    env = load_env()
    uuid = env["XRAY_BRIDGE_UUID"]
    hy2_auth = env["HY2_AUTH"]
    hy2_obfs = env["HY2_OBFS"]
    tuic_uuid = env["TUIC_UUID"]
    tuic_pass = env["TUIC_PASSWORD"]
    rpriv = env["REALITY_PRIVATE_KEY"]
    rshort = env["REALITY_SHORT_ID"]
    rdest = env.get("REALITY_DEST") or "www.microsoft.com:443"
    rsni = env.get("REALITY_SERVER_NAME") or "www.microsoft.com"

    xray = {
        "log": {
            "loglevel": "warning",
            "access": "/var/log/xray/access.log",
            "error": "/var/log/xray/error.log",
        },
        "inbounds": [
            {
                "tag": "socks-in",
                "listen": "127.0.0.1",
                "port": 10808,
                "protocol": "socks",
                "settings": {"udp": True, "auth": "noauth"},
                "sniffing": {
                    "enabled": True,
                    "destOverride": ["http", "tls", "quic"],
                    "routeOnly": True,
                },
            },
            {
                # Public TCP 443 is nginx stream (ssl_preread). XHTTP stays on loopback.
                "tag": "xhttp-bridge",
                "listen": "127.0.0.1",
                "port": 10443,
                "protocol": "vless",
                "settings": {
                    "clients": [{"id": uuid, "email": "backhaul-xhttp"}],
                    "decryption": "none",
                },
                "streamSettings": {
                    "network": "xhttp",
                    "security": "tls",
                    "tlsSettings": {
                        "certificates": [
                            {"certificateFile": CERT, "keyFile": KEY}
                        ],
                        "alpn": ["h2", "http/1.1"],
                    },
                    "xhttpSettings": {"path": XHTTP_PATH, "mode": "auto"},
                },
                "sniffing": {
                    "enabled": True,
                    "destOverride": ["http", "tls", "quic"],
                    "routeOnly": True,
                },
            },
            {
                "tag": "direct-tls",
                "listen": "0.0.0.0",
                "port": 9443,
                "protocol": "vless",
                "settings": {
                    "clients": [
                        {
                            "id": uuid,
                            "email": "backhaul-direct",
                            "flow": "xtls-rprx-vision",
                        }
                    ],
                    "decryption": "none",
                },
                "streamSettings": {
                    "network": "tcp",
                    "security": "tls",
                    "tlsSettings": {
                        "certificates": [
                            {"certificateFile": CERT, "keyFile": KEY}
                        ],
                        "alpn": ["h2", "http/1.1"],
                    },
                },
                "sniffing": {
                    "enabled": True,
                    "destOverride": ["http", "tls", "quic"],
                    "routeOnly": True,
                },
            },
        ],
        "outbounds": [
            {"tag": "DIRECT", "protocol": "freedom", "settings": {"domainStrategy": "UseIP"}},
            {
                "tag": "PANEL-LOCAL",
                "protocol": "freedom",
                "settings": {"redirect": "127.0.0.1:2096"},
            },
            warp_block(env),
            {"tag": "BLOCK", "protocol": "blackhole"},
        ],
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "rules": [
                {
                    "type": "field",
                    "outboundTag": "PANEL-LOCAL",
                    "network": "tcp",
                    "port": "2096",
                },
                {
                    "type": "field",
                    "outboundTag": "PANEL-LOCAL",
                    "domain": [
                        "full:${PANEL_DOMAIN}",
                        "full:${PANEL_DOMAIN_ALT}",
                        "full:${PANEL_DOMAIN_EXTRA}",
                    ],
                },
                {"type": "field", "outboundTag": "BLOCK", "ip": ["geoip:private"]},
            ],
        },
    }
    write(EXIT_DIR / "xray.json", json.dumps(xray, indent=2))

    hy2 = f"""listen: :4443

tls:
  cert: {CERT}
  key: {KEY}

auth:
  type: password
  password: {hy2_auth}

obfs:
  type: salamander
  salamander:
    password: {hy2_obfs}

masquerade:
  type: proxy
  proxy:
    url: https://www.microsoft.com
    rewriteHost: true

bandwidth:
  up: 1 gbps
  down: 1 gbps

outbounds:
  - name: xray
    type: socks5
    socks5:
      addr: 127.0.0.1:10808
"""
    write(Path("/etc/hysteria/config.yaml"), hy2, 0o640)
    write(EXIT_DIR / "hysteria.yaml", hy2, 0o600)

    tuic = f"""log_level = "warn"
server = "0.0.0.0:8443"
udp_relay_ipv6 = false
zero_rtt_handshake = false
dual_stack = false
auth_timeout = "3s"
max_external_packet_size = 1500

[users]
{tuic_uuid} = "{tuic_pass}"

[tls]
self_sign = false
certificate = "{CERT}"
private_key = "{KEY}"
alpn = ["h3"]
hostname = "${CF_GRAY_DOMAIN}"
auto_ssl = false

[backend]
mode = "quinn"

[backend.quinn]
initial_mtu = 1280
min_mtu = 1200
gso = true
pmtu = true

[backend.quinn.congestion_control]
controller = "bbr"

[outbound.default]
type = "socks5"
addr = "127.0.0.1:10808"
allow_udp = true

[experimental]
drop_loopback = true
drop_private = true
"""
    write(Path("/etc/tuic/config.toml"), tuic, 0o640)
    write(EXIT_DIR / "tuic.toml", tuic, 0o600)

    print("RENDERED_EXIT_CONFIGS")


if __name__ == "__main__":
    main()
