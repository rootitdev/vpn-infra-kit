#!/usr/bin/env python3
"""Write test subscription links and QR codes. Does not print secrets."""
from __future__ import annotations

import os
import subprocess
import urllib.parse
from pathlib import Path

ENV = Path("/root/.vpn-secrets/.env")
OUT = Path("/root/.pg_nodes/test-subs")


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for ln in ENV.read_text().splitlines():
        if ln and not ln.startswith("#") and "=" in ln:
            k, v = ln.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def main() -> None:
    env = load_env()
    OUT.mkdir(parents=True, exist_ok=True)
    os.chmod(OUT, 0o700)
    host = "${IRAN_DOMAIN}"
    ip = "${IRAN_IP}"
    pbk = env["REALITY_CLIENT_PUBLIC_KEY"]
    sid = env["REALITY_CLIENT_SHORT_ID"]
    sni = env.get("REALITY_SERVER_NAME") or "dl.google.com"
    hy_user = "testuser"
    hy_pass = env["HY2_CLIENT_AUTH"]
    hy_obfs = env["HY2_CLIENT_OBFS"]

    def vless_reality(uid: str, name: str) -> str:
        q = urllib.parse.urlencode(
            {
                "encryption": "none",
                "flow": "",
                "security": "reality",
                "sni": sni,
                "fp": "chrome",
                "pbk": pbk,
                "sid": sid,
                "type": "tcp",
                "headerType": "none",
            }
        )
        return f"vless://{uid}@{host}:443?{q}#{urllib.parse.quote(name)}"

    def vless_vision(uid: str, name: str) -> str:
        q = urllib.parse.urlencode(
            {
                "encryption": "none",
                "flow": "xtls-rprx-vision",
                "security": "tls",
                "sni": host,
                "fp": "chrome",
                "alpn": "h2,http/1.1",
                "type": "tcp",
            }
        )
        return f"vless://{uid}@{host}:2053?{q}#{urllib.parse.quote(name)}"

    def hy2(user: str, name: str) -> str:
        auth = urllib.parse.quote(f"{user}:{hy_pass}", safe="")
        q = urllib.parse.urlencode(
            {
                "obfs": "salamander",
                "obfs-password": hy_obfs,
                "sni": host,
                "insecure": "0",
            }
        )
        return f"hysteria2://{auth}@{host}:443/?{q}#{urllib.parse.quote(name)}"

    users = [("testuser", env["TESTUSER_UUID"]), ("testuser2", env["TESTUSER2_UUID"])]
    all_links: list[str] = []
    for uname, uid in users:
        links = [
            vless_reality(uid, f"{uname}-REALITY"),
            vless_vision(uid, f"{uname}-VISION"),
            hy2(uname, f"{uname}-HY2"),
        ]
        (OUT / f"{uname}.txt").write_text("\n".join(links) + "\n")
        os.chmod(OUT / f"{uname}.txt", 0o600)
        all_links.extend(links)
        for i, link in enumerate(links):
            png = OUT / f"{uname}-{i}.png"
            subprocess.run(["qrencode", "-o", str(png), link], check=True)
            os.chmod(png, 0o600)
    (OUT / "all.txt").write_text("\n".join(all_links) + "\n")
    os.chmod(OUT / "all.txt", 0o600)
    # v2rayN-style subscription (base64 of links)
    import base64

    b64 = base64.b64encode("\n".join(all_links).encode()).decode()
    (OUT / "subscription.base64").write_text(b64 + "\n")
    os.chmod(OUT / "subscription.base64", 0o600)
    print("SUBS_WRITTEN", str(OUT), "files", len(list(OUT.iterdir())))


if __name__ == "__main__":
    main()
