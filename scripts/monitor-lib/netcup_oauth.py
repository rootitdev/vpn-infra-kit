#!/usr/bin/env python3
"""netcup SCP REST OAuth2 device-code (offline refresh). Never SOAP. Never prints tokens."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEVICE = "https://www.servercontrolpanel.de/realms/scp/protocol/openid-connect/auth/device"
TOKEN = "https://www.servercontrolpanel.de/realms/scp/protocol/openid-connect/token"
API = "https://www.servercontrolpanel.de/scp-core/api/v1"
CLIENT = "scp"
SCOPE = "offline_access openid"
TOKEN_FILE = Path("/root/.vpn-secrets/netcup-scp-oauth.json")
SECRETS = Path("/root/.vpn-secrets/.env")


def _form(url: str, data: dict, timeout: int = 25) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(
        url, data=body, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _json_get(url: str, access: str, timeout: int = 25) -> object:
    req = urllib.request.Request(url, method="GET", headers={"Authorization": f"Bearer {access}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        # Never include body (may leak). Surface only HTTP status for operators.
        raise SystemExit(f"scp_http_{e.code}") from None
    except urllib.error.URLError as e:
        raise SystemExit(f"scp_network:{type(e.reason).__name__ if e.reason else 'URLError'}") from None


def upsert_env(key: str, value: str) -> None:
    SECRETS.parent.mkdir(parents=True, exist_ok=True)
    lines = SECRETS.read_text().splitlines() if SECRETS.exists() else []
    out, found = [], False
    for ln in lines:
        if ln.startswith(key + "="):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(ln)
    if not found:
        out.append(f"{key}={value}")
    SECRETS.write_text("\n".join(out) + "\n")
    SECRETS.chmod(0o600)


def save_oauth(doc: dict) -> None:
    keep = {
        "refresh_token": doc.get("refresh_token") or "",
        "access_token": doc.get("access_token") or "",
        "expires_at": int(time.time()) + int(doc.get("expires_in") or 250) - 30,
    }
    TOKEN_FILE.write_text(json.dumps(keep) + "\n")
    TOKEN_FILE.chmod(0o600)
    if keep["refresh_token"]:
        upsert_env("NETCUP_SCP_REFRESH_TOKEN", keep["refresh_token"])


def load_oauth() -> dict:
    if TOKEN_FILE.exists():
        try:
            return json.loads(TOKEN_FILE.read_text())
        except Exception:
            return {}
    return {}


def start_device() -> dict:
    return _form(DEVICE, {"client_id": CLIENT, "scope": SCOPE})


def poll_device(device_code: str, interval: int = 5, expires: int = 600) -> dict:
    deadline = time.time() + min(int(expires or 600), 600)
    wait = max(5, int(interval or 5))
    while time.time() < deadline:
        try:
            doc = _form(
                TOKEN,
                {
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": device_code,
                    "client_id": CLIENT,
                },
            )
        except urllib.error.HTTPError as e:
            raw = e.read().decode(errors="replace")
            try:
                err = json.loads(raw)
            except Exception:
                err = {"error": "http"}
            if err.get("error") in ("authorization_pending", "slow_down"):
                if err.get("error") == "slow_down":
                    wait += 5
                time.sleep(wait)
                continue
            raise SystemExit(f"device_poll_{err.get('error') or e.code}")
        save_oauth(doc)
        return doc
        time.sleep(wait)
    raise SystemExit("device_expired")


def access_token(refresh: str | None = None) -> str:
    o = load_oauth()
    now = time.time()
    if o.get("access_token") and float(o.get("expires_at") or 0) > now:
        return str(o["access_token"])
    rt = refresh or o.get("refresh_token") or ""
    if not rt:
        # env fallback
        if SECRETS.exists():
            for ln in SECRETS.read_text().splitlines():
                if ln.startswith("NETCUP_SCP_REFRESH_TOKEN="):
                    rt = ln.split("=", 1)[1].strip()
                    break
    if not rt:
        raise SystemExit("missing_refresh_token")
    try:
        doc = _form(TOKEN, {"client_id": CLIENT, "grant_type": "refresh_token", "refresh_token": rt})
    except urllib.error.HTTPError as e:
        # 400/401 usually means refresh revoked — need vpn-mon-netcup-login again
        raise SystemExit(f"scp_refresh_http_{e.code}") from None
    except urllib.error.URLError:
        raise SystemExit("scp_refresh_network") from None
    if not doc.get("refresh_token"):
        doc["refresh_token"] = rt
    save_oauth(doc)
    return str(doc.get("access_token") or "")


def list_servers(access: str) -> list:
    raw = _json_get(f"{API}/servers?limit=50", access)
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for k in ("items", "servers", "content", "data"):
            if isinstance(raw.get(k), list):
                return raw[k]
    return []


def pick_server(servers: list, name: str, ip: str = "${EXIT_IP}") -> dict | None:
    want = (name or "").strip().lower()
    for s in servers:
        if not isinstance(s, dict):
            continue
        nm = str(s.get("name") or s.get("serverName") or "").lower()
        nick = str(s.get("nickname") or "").lower()
        if want and (nm == want or nm.startswith(want) or want in nm):
            return s
        blob = json.dumps(s)
        if ip and ip in blob:
            return s
        if nick and want and want in nick:
            return s
    if len(servers) == 1 and isinstance(servers[0], dict):
        return servers[0]
    return None


def _sum_rx(obj, depth: int = 0) -> int:
    if depth > 8:
        return 0
    n = 0
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = str(k).lower()
            if lk in ("rx", "rxbytes", "bytesin", "in", "download", "incoming") and isinstance(v, (int, float)):
                n += int(v)
            else:
                n += _sum_rx(v, depth + 1)
    elif isinstance(obj, list):
        for it in obj:
            n += _sum_rx(it, depth + 1)
    return n


def integrate_network_metrics(doc: dict) -> tuple[int, int, float, int]:
    """Return (in_bytes, out_bytes, last_total_mbps, n_buckets).

    SCP /metrics/network?hours=N is 10-minute buckets of bytes/sec per NIC IN/OUT.
    No rolling-total field and no throttle flag on GET /servers/{id}.
    """
    if not isinstance(doc, dict) or not doc:
        return 0, 0, 0.0, 0
    times = sorted(doc.keys())
    interval = 600.0
    if len(times) >= 2:
        from datetime import datetime

        t0 = datetime.fromisoformat(times[0].replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(times[1].replace("Z", "+00:00"))
        interval = max(1.0, (t1 - t0).total_seconds())
    in_b = out_b = 0.0
    last_mbps = 0.0
    for i, ts in enumerate(times):
        series = doc.get(ts) or {}
        inn = outt = 0.0
        for k, v in series.items():
            ks = str(k)
            val = float(v or 0)
            if ks.endswith(" IN"):
                inn += val
            elif ks.endswith(" OUT"):
                outt += val
        in_b += inn * interval
        out_b += outt * interval
        if i >= len(times) - 3:
            last_mbps = max(last_mbps, (inn + outt) * 8 / 1_000_000)
    return int(in_b), int(out_b), last_mbps, len(times)


def rolling_24h(vname: str) -> dict:
    access = access_token()
    servers = list_servers(access)
    srv = pick_server(servers, vname)
    if not srv:
        names = [str((s or {}).get("name")) for s in servers if isinstance(s, dict)]
        raise SystemExit("no_server_match:" + ",".join(names)[:80])
    sid = srv.get("id") or srv.get("serverId")
    if sid is None:
        raise SystemExit("no_server_id")
    doc = _json_get(f"{API}/servers/{sid}/metrics/network?hours=24", access)
    inn, out, mbps, n = integrate_network_metrics(doc if isinstance(doc, dict) else {})
    full = {}
    try:
        full = _json_get(f"{API}/servers/{sid}", access)
    except Exception:
        full = {}
    live = (full or {}).get("serverLiveInfo") or {}
    return {
        "server_id": sid,
        "name": srv.get("name"),
        "in_bytes": inn,
        "out_bytes": out,
        "total_bytes": inn + out,
        "recent_mbps": mbps,
        "buckets": n,
        "source": "scp_rest_metrics_network_24h",
        "api_throttle_field": None,
        "server_state": live.get("state"),
        "template": (srv.get("template") or {}).get("name") if isinstance(srv.get("template"), dict) else srv.get("template"),
    }


def monthly_rx_bytes(vname: str, hours: int) -> tuple[int | None, str]:
    access = access_token()
    servers = list_servers(access)
    srv = pick_server(servers, vname)
    if not srv:
        names = [str((s or {}).get("name")) for s in servers if isinstance(s, dict)]
        return None, "no_server_match:" + ",".join(names)[:80]
    sid = srv.get("id") or srv.get("serverId")
    if sid is None:
        return None, "no_server_id"
    hours = max(1, min(int(hours), 1440))
    url = f"{API}/servers/{sid}/metrics/network?hours={hours}"
    try:
        doc = _json_get(url, access)
    except Exception as e:
        return None, f"metrics_fail:{type(e).__name__}"
    used = _sum_rx(doc)
    if used <= 0:
        # maybe values are bytes/sec samples; still return what we got
        return None, "metrics_empty"
    return int(used), "scp_rest_network"


def login_interactive() -> None:
    d = start_device()
    uri = d.get("verification_uri_complete") or d.get("verification_uri")
    print("Open this URL in a browser and approve SCP offline_access:")
    print(uri)
    print("user_code", d.get("user_code"))
    poll_device(str(d.get("device_code") or ""), int(d.get("interval") or 5), int(d.get("expires_in") or 600))
    print("refresh_token_saved")


if __name__ == "__main__":
    login_interactive()
