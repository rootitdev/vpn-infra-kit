#!/usr/bin/env python3
"""Add TO-NL-SSH (socks → Iran haproxy 127.0.0.1:18400) to the Iran core, then publish.

Prefers the core that already has TO-AMS-SSH (usually shetaban-iran-core).
Uses unverified TLS when PASARGUARD_URL is https://127.0.0.1.
"""
from __future__ import annotations

import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

TAG = "TO-NL-SSH"
SOCKS_PORT = 18400
ENV = Path("/root/.vpn-secrets/.env")


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if ENV.exists():
        for ln in ENV.read_text().splitlines():
            if not ln or ln.startswith("#") or "=" not in ln:
                continue
            k, v = ln.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def api(env: dict, method: str, path: str, body=None):
    base = (env.get("PASARGUARD_URL") or "https://127.0.0.1:8000").rstrip("/")
    key = env.get("PANEL_API_KEY") or env.get("PASARGUARD_API_KEY") or ""
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={
            "X-Api-Key": key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    ctx = ssl._create_unverified_context() if base.startswith("https://127.0.0.1") else None
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=90) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def main() -> int:
    env = load_env()
    if not (env.get("PANEL_API_KEY") or env.get("PASARGUARD_API_KEY")):
        print("missing PANEL_API_KEY", file=sys.stderr)
        return 1
    st, cores = api(env, "GET", "/api/cores")
    if st != 200 or not isinstance(cores, dict):
        print("cores fail", st, cores)
        return 2
    items = cores.get("cores") or []
    target = None
    for csum in items:
        st, core = api(env, "GET", f"/api/core/{csum['id']}")
        tags = [o.get("tag") for o in (core.get("config") or {}).get("outbounds") or []]
        if "TO-AMS-SSH" in tags or "shetaban" in (core.get("name") or "").lower():
            target = core
            if "TO-AMS-SSH" in tags:
                break
    if not target:
        print("no iran core with TO-AMS-SSH")
        return 3
    cid = target["id"]
    obs = target["config"]["outbounds"]
    if any(o.get("tag") == TAG for o in obs):
        print("already present", TAG, "on", target.get("name"))
        return 0
    tags = [o.get("tag") for o in obs]
    at = tags.index("TO-AMS-SSH") + 1 if "TO-AMS-SSH" in tags else len(obs)
    obs.insert(
        at,
        {
            "tag": TAG,
            "protocol": "socks",
            "settings": {"servers": [{"address": "127.0.0.1", "port": SOCKS_PORT}]},
        },
    )
    payload = {
        "name": target["name"],
        "config": target["config"],
        "type": target.get("type") or "xray",
        "exclude_inbound_tags": list(target.get("exclude_inbound_tags") or []),
        "fallbacks_inbound_tags": list(target.get("fallbacks_inbound_tags") or []),
    }
    st, res = api(env, "PUT", f"/api/core/{cid}?restart_nodes=false", payload)
    print("PUT", st, target.get("name"), TAG)
    if st not in (200, 201):
        print(res)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
