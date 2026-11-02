#!/usr/bin/env python3
"""Render Iran relay configs from secrets. Never prints secret values."""
from __future__ import annotations

import json
import os
from pathlib import Path

ENV = Path("/root/.vpn-secrets/.env")
OUT = Path("/root/.pg_nodes/iran")
CERT = "/root/.pg_nodes/certs/fullchain.pem"
KEY = "/root/.pg_nodes/certs/privkey.pem"
EXIT_IP = "${EXIT_IP}"
XHTTP_PATH = "${XHTTP_PATH}"


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for ln in ENV.read_text().splitlines():
        if ln and not ln.startswith("#") and "=" in ln:
            k, v = ln.split("=", 1)
            env[k] = v
    return env


def write(path: Path, text: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.chmod(path, mode)


def vless_user(uid: str, email: str, flow: str | None = None) -> dict:
    u = {"id": uid, "email": email}
    if flow:
        u["flow"] = flow
    return u


def main() -> None:
    env = load_env()
    bridge = env["XRAY_BRIDGE_UUID"]
    u1, u2 = env["TESTUSER_UUID"], env["TESTUSER2_UUID"]
    rpriv = env["REALITY_CLIENT_PRIVATE_KEY"]
    rshort = env["REALITY_CLIENT_SHORT_ID"]
    bpub = env["REALITY_PUBLIC_KEY"]
    bshort = env["REALITY_SHORT_ID"]
    rsni = env.get("REALITY_SERVER_NAME") or "www.microsoft.com"
    rdest = env.get("REALITY_DEST") or "www.microsoft.com:443"

    fragment = {
        "tag": "fragment",
        "protocol": "freedom",
        "settings": {
            "domainStrategy": "UseIPv4",
            "fragment": {"packets": "tlshello", "length": "100-200", "interval": "10-20"},
        },
    }

    def xhttp_out(tag: str, host: str) -> dict:
        return {
            "tag": tag,
            "protocol": "vless",
            "settings": {
                "vnext": [
                    {
                        "address": host,
                        "port": 443,
                        "users": [{"id": bridge, "encryption": "none"}],
                    }
                ]
            },
            "streamSettings": {
                "network": "xhttp",
                "security": "tls",
                "tlsSettings": {
                    "serverName": host,
                    "fingerprint": "chrome",
                    "alpn": ["h2", "http/1.1"],
                },
                "xhttpSettings": {"path": XHTTP_PATH, "mode": "auto", "host": host},
                "sockopt": {"dialerProxy": "fragment", "tcpKeepAliveInterval": 30},
            },
        }

    xray = {
        "log": {
            "loglevel": "warning",
            "access": "/var/log/xray/access.log",
            "error": "/var/log/xray/error.log",
        },
        "api": {
            "tag": "api",
            "services": ["HandlerService", "LoggerService", "StatsService", "RoutingService"],
        },
        "inbounds": [
            {
                "tag": "api",
                "listen": "127.0.0.1",
                "port": 10085,
                "protocol": "dokodemo-door",
                "settings": {"address": "127.0.0.1"},
            },
            {
                "tag": "VLESS-REALITY",
                "listen": "0.0.0.0",
                "port": 443,
                "protocol": "vless",
                "settings": {
                    "clients": [
                        vless_user(u1, "testuser"),
                        vless_user(u2, "testuser2"),
                    ],
                    "decryption": "none",
                },
                "streamSettings": {
                    "network": "tcp",
                    "security": "reality",
                    "realitySettings": {
                        "show": False,
                        "dest": rdest,
                        "xver": 0,
                        "serverNames": [rsni],
                        "privateKey": rpriv,
                        "shortIds": [rshort],
                        "fingerprint": "chrome",
                    },
                },
                "sniffing": {
                    "enabled": True,
                    "destOverride": ["http", "tls", "quic"],
                    "routeOnly": False,
                },
            },
            {
                "tag": "VLESS-VISION",
                "listen": "0.0.0.0",
                "port": 2053,
                "protocol": "vless",
                "settings": {
                    "clients": [
                        vless_user(u1, "testuser-vision", "xtls-rprx-vision"),
                        vless_user(u2, "testuser2-vision", "xtls-rprx-vision"),
                    ],
                    "decryption": "none",
                },
                "streamSettings": {
                    "network": "tcp",
                    "security": "tls",
                    "tlsSettings": {
                        "certificates": [{"certificateFile": CERT, "keyFile": KEY}],
                        "alpn": ["h2", "http/1.1"],
                    },
                },
                "sniffing": {
                    "enabled": True,
                    "destOverride": ["http", "tls", "quic"],
                    "routeOnly": False,
                },
            },
            {
                "tag": "PANEL-ADMIN",
                "listen": "127.0.0.1",
                "port": 11080,
                "protocol": "socks",
                "settings": {"udp": True, "auth": "noauth"},
                "sniffing": {
                    "enabled": True,
                    "destOverride": ["http", "tls", "quic"],
                    "routeOnly": False,
                },
            },
        ],
        "outbounds": [
            xhttp_out("TO-AMS-CF", "${CF_GRAY_DOMAIN}"),
            xhttp_out("TO-AMS-XHTTP", "${XHTTP_DOMAIN_ALT}"),
            xhttp_out("TO-AMS-GCORE", "standby.${EXTRA_ZONE}"),
            xhttp_out("TO-AMS-BUNNY", "${BUNNY_DOMAIN}"),
            {
                "tag": "TO-AMS-DIRECT",
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {
                            "address": EXIT_IP,
                            "port": 9443,
                            "users": [
                                {
                                    "id": bridge,
                                    "encryption": "none",
                                    "flow": "xtls-rprx-vision",
                                }
                            ],
                        }
                    ]
                },
                "streamSettings": {
                    "network": "tcp",
                    "security": "tls",
                    "tlsSettings": {
                        "serverName": "${CF_GRAY_DOMAIN}",
                        "fingerprint": "chrome",
                        "alpn": ["h2", "http/1.1"],
                    },
                    "sockopt": {"dialerProxy": "fragment", "tcpKeepAliveInterval": 30},
                },
            },
            fragment,
            {"tag": "DIRECT", "protocol": "freedom", "settings": {"domainStrategy": "UseIP"}},
            {"tag": "BLOCK", "protocol": "blackhole"},
            {"tag": "api", "protocol": "freedom"},
        ],
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "balancers": [
                {
                    "tag": "backhaul",
                    "selector": [
                        "TO-AMS-DIRECT",
                        "TO-AMS-XHTTP",
                        "TO-AMS-GCORE",
                        "TO-AMS-BUNNY",
                        "TO-AMS-CF",
                    ],
                    "fallbackTag": "TO-AMS-DIRECT",
                    "strategy": {"type": "leastPing"},
                }
            ],
            "rules": [
                {"type": "field", "inboundTag": ["api"], "outboundTag": "api"},
                {"type": "field", "ip": ["geoip:private"], "outboundTag": "BLOCK"},
                {
                    "type": "field",
                    "domain": ["full:${PANEL_DOMAIN}", "full:${PANEL_DOMAIN_ALT}", "full:${PANEL_DOMAIN_EXTRA}"],
                    "outboundTag": "TO-AMS-DIRECT",
                },
                {
                    "type": "field",
                    "domain": ["geosite:category-ir", "regexp:.*\\.ir$"],
                    "outboundTag": "DIRECT",
                },
                {"type": "field", "ip": ["geoip:ir"], "outboundTag": "DIRECT"},
                {
                    "type": "field",
                    "inboundTag": ["VLESS-REALITY", "VLESS-VISION", "PANEL-ADMIN"],
                    "balancerTag": "backhaul",
                },
            ],
        },
        "observatory": {
            "subjectSelector": ["TO-AMS-"],
            "probeURL": "https://www.msftconnecttest.com/connecttest.txt",
            "probeInterval": "30s",
            "enableConcurrency": True,
        },
    }
    write(OUT / "xray.json", json.dumps(xray, indent=2))

    hy2_client = f"""server: {EXIT_IP}:4443
auth: {env['HY2_AUTH']}
tls:
  sni: ${CF_GRAY_DOMAIN}
  insecure: false
obfs:
  type: salamander
  salamander:
    password: {env['HY2_OBFS']}
bandwidth:
  up: 100 mbps
  down: 300 mbps
socks5:
  listen: 127.0.0.1:11081
quic:
  maxIdleTimeout: 30s
  keepAlivePeriod: 10s
"""
    write(OUT / "hysteria-backhaul.yaml", hy2_client)

    hy2_in = f"""listen: :443
tls:
  cert: {CERT}
  key: {KEY}
auth:
  type: userpass
  userpass:
    testuser: {env['HY2_CLIENT_AUTH']}
    testuser2: {env['HY2_CLIENT_AUTH']}
obfs:
  type: salamander
  salamander:
    password: {env['HY2_CLIENT_OBFS']}
masquerade:
  type: proxy
  proxy:
    url: https://www.microsoft.com
    rewriteHost: true
bandwidth:
  up: 300 mbps
  down: 300 mbps
outbounds:
  - name: backhaul
    type: socks5
    socks5:
      addr: 127.0.0.1:11080
"""
    write(OUT / "hysteria-inbound.yaml", hy2_in)
    # TUIC removed: UDP backhaul from Iranian DCs is not usable.
    print("RENDERED_IRAN_CONFIGS")


if __name__ == "__main__":
    main()
