#!/usr/bin/env python3
"""Cloudflare DNS helper. Secrets from /root/.vpn-secrets/.env only. Never prints secret values."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ENV_PATH = Path("/root/.vpn-secrets/.env")


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for ln in ENV_PATH.read_text().splitlines():
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        env[k] = v
    return env


def cf_request(method: str, url: str, token: str, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")[:800]
        raise SystemExit(f"CF_HTTP {e.code} {url} {raw}") from e


def main() -> None:
    env = load_env()
    token = env["CF_API_TOKEN"]
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "zones":
        data = cf_request("GET", "https://api.cloudflare.com/client/v4/zones?per_page=50", token)
        for z in data.get("result") or []:
            print(z["name"], z["id"], z["status"])
        return
    if cmd == "list":
        zone_id = sys.argv[2]
        data = cf_request(
            "GET",
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records?per_page=100",
            token,
        )
        for rec in data.get("result") or []:
            print(rec["type"], rec["name"], rec["content"], "proxied=" + str(rec["proxied"]), rec["id"])
        return
    if cmd == "upsert":
        # upsert A name content proxied zone_id
        name, content, proxied, zone_id = sys.argv[2:6]
        proxied_b = proxied.lower() in ("1", "true", "yes", "orange")
        existing = cf_request(
            "GET",
            "https://api.cloudflare.com/client/v4/zones/"
            + zone_id
            + "/dns_records?type=A&name="
            + urllib.parse.quote(name),
            token,
        )
        payload = {
            "type": "A",
            "name": name,
            "content": content,
            "ttl": 1 if proxied_b else 120,
            "proxied": proxied_b,
        }
        recs = existing.get("result") or []
        if recs:
            rid = recs[0]["id"]
            data = cf_request(
                "PUT",
                f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{rid}",
                token,
                payload,
            )
            print("UPDATED", name, data.get("success"), "proxied", proxied_b)
        else:
            data = cf_request(
                "POST",
                f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records",
                token,
                payload,
            )
            print("CREATED", name, data.get("success"), "proxied", proxied_b)
        return
    if cmd == "setting":
        zone_id, key, value = sys.argv[2], sys.argv[3], sys.argv[4]
        data = cf_request(
            "PATCH",
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/settings/{key}",
            token,
            {"value": value},
        )
        print("SETTING", key, data.get("success"), data.get("errors"))
        return
    print("usage: zones|list|upsert|setting")


if __name__ == "__main__":
    main()
