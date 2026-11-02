"""Shared panel-core helpers for vpn-path and failover. No secrets printed."""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from urllib.request import Request, urlopen

from vpn_paths import ALL_LIVE, FALLBACK, PANEL_DOMAINS, PANEL_RULE_MARK, PRIORITY, WATCH_ONLY

ENV = Path("/root/.vpn-secrets/.env")
EXPORT = Path("/root/vpn-infra/scripts/iran_sync_export.py")
MODE_FILE = Path("/var/lib/pasarguard/vpn-path-mode.json")
HISTORY_FILE = Path("/var/lib/pasarguard/path-health-history.jsonl")
HISTORY_KEEP = 2000


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for ln in ENV.read_text().splitlines():
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


_TOKEN: dict[str, str] = {}


def _auth_headers(env: dict) -> dict:
    """X-Api-Key if PANEL_API_KEY is set, else admin login (Bearer) — master/split mode creates no API key on the master."""
    key = env.get("PANEL_API_KEY") or env.get("PASARGUARD_API_KEY") or ""
    if key:
        return {"X-Api-Key": key}
    if not _TOKEN.get("t"):
        from urllib.parse import urlencode
        base = (env.get("PASARGUARD_URL") or "http://127.0.0.1:8000").rstrip("/")
        user, pw = env.get("PASARGUARD_ADMIN_USER"), env.get("PASARGUARD_ADMIN_PASS")
        if not (user and pw):
            raise SystemExit("missing PANEL_API_KEY or PASARGUARD_ADMIN_USER/PASS")
        r = Request(base + "/api/admin/token", data=urlencode({"username": user, "password": pw}).encode(),
                    headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "vpn-infra-kit/1.0"})
        with urlopen(r, timeout=30) as resp:
            _TOKEN["t"] = json.loads(resp.read())["access_token"]
    return {"Authorization": "Bearer " + _TOKEN["t"]}


def req(method: str, path: str, env: dict, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    r = Request(
        f"{(env.get('PASARGUARD_URL') or 'http://127.0.0.1:8000').rstrip('/')}{path}",
        data=data,
        method=method,
        headers={**_auth_headers(env), "Content-Type": "application/json", "User-Agent": "vpn-infra-kit/1.0"},
    )
    with urlopen(r, timeout=30) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else {}


def get_core(env: dict) -> dict:
    core_id = env.get("PG_CORE_ID")
    if not core_id:
        raise SystemExit("missing PG_CORE_ID")
    return req("GET", f"/api/core/{core_id}", env)


def put_core(env: dict, core: dict) -> None:
    payload = {
        "name": core["name"],
        "config": core["config"],
        "type": core.get("type") or "xray",
        "exclude_inbound_tags": list(core.get("exclude_inbound_tags") or []),
        "fallbacks_inbound_tags": list(core.get("fallbacks_inbound_tags") or []),
    }
    core_id = env.get("PG_CORE_ID")
    # master mode: the kit core is used ONLY by the kit node, so restarting its nodes is safe and required to apply
    restart = "true" if env.get("INSTALL_MODE") == "master" else "false"
    req("PUT", f"/api/core/{core_id}?restart_nodes={restart}", env, payload)


def current_selector(cfg: dict) -> tuple[list[str], str | None]:
    """Read live backhaul path from balancers OR catch-all outboundTag rule."""
    routing = (cfg or {}).get("routing") or {}
    bals = routing.get("balancers") or []
    if bals:
        b = bals[0] or {}
        return list(b.get("selector") or []), b.get("fallbackTag")
    for rule in reversed(list(routing.get("rules") or [])):
        if not isinstance(rule, dict):
            continue
        tag = rule.get("outboundTag")
        if not tag or tag in ("DIRECT", "BLOCK"):
            continue
        if rule.get("network") or (
            not rule.get("domain") and not rule.get("ip") and not rule.get("inboundTag")
        ):
            return [tag], tag
    return [], None


def put_selector(env: dict, core: dict, selector: list[str]) -> None:
    """Pin Iran backhaul via outboundTag (no balancers).

    From many Iranian DCs, Exit IP (DIRECT) is blocked and CF/XHTTP VLESS tunnels
    hang after edge TLS, while Bunny CDN still works. Balancers+leastPing then
    falsely prefer CF and blackhole clients — so we pin a single outboundTag.
    """
    cfg = core["config"]
    routing = cfg.setdefault("routing", {})
    have = {o.get("tag") for o in (cfg.get("outbounds") or []) if o.get("tag")}
    sel = [t for t in (selector or []) if t in have]
    if not sel:
        sel = [FALLBACK] if FALLBACK in have else ["DIRECT"]
    live = sel[0]
    routing.pop("balancers", None)
    cfg.pop("observatory", None)
    cfg.pop("burstObservatory", None)
    routing["domainStrategy"] = routing.get("domainStrategy") or "AsIs"
    keep = []
    for rule in list(routing.get("rules") or []):
        if not isinstance(rule, dict):
            continue
        dom = rule.get("domain") or []
        ip = rule.get("ip") or []
        if rule.get("outboundTag") == "DIRECT" and (
            any("category-ir" in str(d) or ".ir" in str(d) for d in dom)
            or any("geoip:ir" in str(x) or "geoip:private" in str(x) for x in ip)
        ):
            keep.append(rule)
    if not keep:
        keep = [
            {
                "type": "field",
                "domain": ["regexp:.*\\.ir$", "geosite:category-ir"],
                "outboundTag": "DIRECT",
            },
            {"type": "field", "ip": ["geoip:ir", "geoip:private"], "outboundTag": "DIRECT"},
        ]
    # Panel admin hosts always via FALLBACK (DIRECT tunnel), independent of user path pin.
    keep.append({
        "type": "field",
        "domain": list(PANEL_DOMAINS),
        "outboundTag": FALLBACK if FALLBACK in have else live,
    })
    keep.append({"type": "field", "network": "tcp,udp", "outboundTag": live})
    routing["rules"] = keep
    put_core(env, core)


def ensure_panel_via_backhaul(cfg: dict) -> bool:
    """Pin panel.* hostnames to TO-AMS-DIRECT (tunneled), independent of backhaul selector.

    Admin panels on Iran (nginx → subproxy → SOCKS) resolve panel.* and must keep working
    when the operator locks users onto CF/XHTTP/CDN. Cleartext Iran→Exit:2096 is still avoided.
    """
    rules = cfg.setdefault("routing", {}).setdefault("rules", [])
    desired = {
        "type": "field",
        "domain": list(PANEL_DOMAINS),
        "outboundTag": FALLBACK,  # TO-AMS-DIRECT
    }
    for i, r in enumerate(rules):
        if not isinstance(r, dict):
            continue
        if PANEL_RULE_MARK not in (r.get("domain") or []):
            continue
        if (
            r.get("outboundTag") == FALLBACK
            and not r.get("balancerTag")
            and list(r.get("domain") or []) == list(PANEL_DOMAINS)
        ):
            return False
        rules[i] = desired
        return True
    insert_at = 0
    for i, r in enumerate(rules):
        dom = (r.get("domain") or []) if isinstance(r, dict) else []
        if any("category-ir" in str(d) or ".ir$" in str(d) for d in dom):
            insert_at = i
            break
    rules.insert(insert_at, desired)
    return True


def publish() -> None:
    """Push panel core to Iran. Export injects CAT-instagram clones of the live selector."""
    if not EXPORT.exists():  # master/split mode: panel pushes the core to the node itself
        return
    subprocess.run(["python3", str(EXPORT)], check=True)


def read_mode() -> dict:
    """auto: failover picks the path. manual: operator pinned `path`.

    `failover` (manual only): still leave a dead pinned path after FAIL_STREAK.
    """
    try:
        d = json.loads(MODE_FILE.read_text())
    except (OSError, ValueError):
        d = {}
    mode = d.get("mode") if d.get("mode") in ("auto", "manual") else "auto"
    allowed = set(PRIORITY) | set(WATCH_ONLY)
    path = d.get("path") if d.get("path") in allowed else ""
    if mode == "manual" and not path:
        mode = "auto"
    return {
        "mode": mode,
        "path": path,
        "failover": bool(d.get("failover", True)),
        "by": str(d.get("by") or ""),
        "ts": int(d.get("ts") or 0),
        "note": str(d.get("note") or ""),
    }


def write_mode(mode: str, path: str = "", failover: bool = True, by: str = "", note: str = "") -> dict:
    d = {
        "mode": mode,
        "path": path if mode == "manual" else "",
        "failover": bool(failover),
        "by": by,
        "ts": int(time.time()),
        "note": note,
    }
    MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = MODE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d) + "\n")
    tmp.chmod(0o600)
    tmp.replace(MODE_FILE)
    return d


def append_history(health: dict) -> None:
    """One compact line per failover run; trimmed to HISTORY_KEEP lines."""
    paths = health.get("paths") or {}
    row = {
        "ts": int(health.get("ts") or time.time()),
        "in": bool(health.get("inbound_ok")),
        "p": {
            t: [1 if (paths.get(t) or {}).get("ok") else 0, int((paths.get(t) or {}).get("ms") or 0)]
            for t in list(PRIORITY) + list(WATCH_ONLY)
        },
    }
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_FILE.open("a") as f:
        f.write(json.dumps(row, separators=(",", ":")) + "\n")
    try:
        lines = HISTORY_FILE.read_text().splitlines()
    except OSError:
        return
    if len(lines) > HISTORY_KEEP + 200:
        tmp = HISTORY_FILE.with_suffix(".tmp")
        tmp.write_text("\n".join(lines[-HISTORY_KEEP:]) + "\n")
        tmp.replace(HISTORY_FILE)


def read_history(limit: int = 240) -> list[dict]:
    try:
        lines = HISTORY_FILE.read_text().splitlines()[-limit:]
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out
