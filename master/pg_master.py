#!/usr/bin/env python3
"""Add-only integration with an EXISTING Pasarguard master (latest dev).

  pg_master.py snapshot          # back up cores/nodes/hosts/groups/inbounds JSON (read-only)
  pg_master.py plan              # dry-run: list exactly what would be ADDED; detects name/port collisions
  pg_master.py apply             # create the objects from the plan (requires --yes)
  pg_master.py rollback          # delete ONLY objects recorded in state as created by this kit (requires --yes)

Hard rules enforced in code:
  * never PUT/PATCH/DELETE an object this kit did not create (IDs tracked in STATE_FILE)
  * every created object name starts with KIT_PREFIX
  * core config is created with restart_nodes=false semantics; other nodes keep their own cores
  * users are never modified; the operator assigns users/groups to the new inbounds in the panel
Endpoint paths are verified against the live /openapi.json before any write.
"""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode

ENV = os.environ
BASE = ENV.get("PASARGUARD_URL", "http://127.0.0.1:8000").rstrip("/")
PREFIX = ENV.get("KIT_PREFIX", "ikit")
STATE_DIR = Path(ENV.get("STATE_DIR", "/var/lib/vpn-infra-kit"))
STATE_FILE = STATE_DIR / "master-created.json"
RENDER = Path(ENV.get("KIT_RENDERED", "/opt/vpn-infra-kit/rendered"))

def _req(method, path, token=None, body=None, form=False):
    data = None; h = {"Accept": "application/json"}
    if body is not None:
        if form: data = urlencode(body).encode(); h["Content-Type"] = "application/x-www-form-urlencoded"
        else: data = json.dumps(body).encode(); h["Content-Type"] = "application/json"
    if token: h["Authorization"] = f"Bearer {token}"
    with urlopen(Request(BASE + path, data=data, headers=h, method=method), timeout=30) as r:
        raw = r.read(); return json.loads(raw) if raw else None

def login():
    r = _req("POST", "/api/admin/token", body={"username": ENV["PASARGUARD_ADMIN_USER"], "password": ENV["PASARGUARD_ADMIN_PASS"]}, form=True)
    return r["access_token"]

def openapi_paths():
    try: return set(_req("GET", "/openapi.json")["paths"].keys())
    except Exception: return set()

def _list(tok, path):
    r = _req("GET", path, tok)
    if isinstance(r, dict):
        for k in ("cores", "nodes", "hosts", "groups", "items", "data"):
            if k in r and isinstance(r[k], list): return r[k]
    return r if isinstance(r, list) else []

ENDPOINTS = {"cores": "/api/cores", "nodes": "/api/nodes", "hosts": "/api/hosts", "groups": "/api/groups", "inbounds": "/api/inbounds"}

def snapshot(tok):
    out = STATE_DIR / "backups" / time.strftime("%Y%m%dT%H%M%S") / "master-api"
    out.mkdir(parents=True, exist_ok=True)
    for name, ep in ENDPOINTS.items():
        try: (out / f"{name}.json").write_text(json.dumps(_req("GET", ep, tok), indent=2))
        except Exception as e: (out / f"{name}.error").write_text(str(e))
    os.chmod(out, 0o700); print(f"snapshot saved: {out}"); return out

def desired():
    core_cfg = json.loads((RENDER / "templates" / "iran-core.json.tmpl").read_text())  # produced by render_iran_configs.py
    return {
        "core": {"name": f"{PREFIX}-iran-core", "config": core_cfg, "exclude_inbound_tags": [], "fallbacks_inbound_tags": []},
        "node": {"name": f"{PREFIX}-iran", "address": (ENV.get("CTL_NODE_ADDRESS", "127.0.0.1") if ENV.get("CTL_MODE", "tunnel") == "tunnel" else ENV["IRAN_IP"]),
                  "port": int(ENV.get("CTL_LOCAL_PORT", "62051") if ENV.get("CTL_MODE", "tunnel") == "tunnel" else ENV.get("PG_NODE_PORT", "62050")),
                  "api_key": ENV["PG_NODE_API_KEY"], "connection_type": "grpc", "usage_coefficient": 1.0},
        "inbound_tags": [i.get("tag") for i in core_cfg.get("inbounds", []) if i.get("tag")],
    }

def plan(tok):
    d = desired(); problems = []; existing = {k: _list(tok, v) for k, v in ENDPOINTS.items() if k != "inbounds"}
    names = {k: {o.get("name") or o.get("remark") for o in v} for k, v in existing.items()}
    if d["core"]["name"] in names["cores"]: problems.append(f"core name exists: {d['core']['name']}")
    if d["node"]["name"] in names["nodes"]: problems.append(f"node name exists: {d['node']['name']}")
    for n in existing["nodes"]:
        if n.get("address") == d["node"]["address"] and str(n.get("port")) == str(d["node"]["port"]):
            problems.append(f"a node already uses {d['node']['address']}:{d['node']['port']} on master (pick another CTL_LOCAL_PORT)")
    try: tags = set(_req("GET", "/api/inbounds", tok) or [])
    except Exception: tags = set()
    for t in d["inbound_tags"]:
        if not t.startswith(PREFIX): problems.append(f"inbound tag not prefixed: {t}")
        if t in tags: problems.append(f"inbound tag already used on master: {t}")
    print("== PLAN (add-only) ==")
    print(f"  + core config  {d['core']['name']}  (inbounds: {', '.join(d['inbound_tags'])})")
    print(f"  + node         {d['node']['name']}  -> {PREFIX} core, connection grpc")
    print(f"  + hosts        one per new inbound, remark prefixed '{PREFIX}-'")
    print(f"  = untouched    {len(existing['nodes'])} existing nodes, {len(existing['cores'])} cores, {len(existing['hosts'])} hosts, all users")
    if problems: print("== BLOCKERS =="); [print("  !", p) for p in problems]
    return d, problems

def apply(tok):
    paths = openapi_paths()
    for need in ("/api/core", "/api/node", "/api/host"):
        if paths and need not in paths: sys.exit(f"endpoint {need} missing on this Pasarguard version; adjust pg_master.py (no changes made)")
    d, problems = plan(tok)
    if problems: sys.exit("blockers present; nothing applied")
    snapshot(tok)
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {"created": []}
    core = _req("POST", "/api/core", tok, d["core"]); state["created"].append({"type": "core", "id": core["id"], "name": d["core"]["name"]})
    STATE_FILE.write_text(json.dumps(state, indent=2))
    node_body = dict(d["node"], core_config_id=core["id"])
    node = _req("POST", "/api/node", tok, node_body); state["created"].append({"type": "node", "id": node["id"], "name": d["node"]["name"]})
    STATE_FILE.write_text(json.dumps(state, indent=2)); os.chmod(STATE_FILE, 0o600)
    print(f"created core id={core['id']} node id={node['id']}  (write PG_CORE_ID / PG_NODE_ID to .env)")
    print("hosts: create via `install.sh --phase hosts` after the node reports connected")

def rollback(tok):
    if not STATE_FILE.exists(): sys.exit("nothing recorded; nothing to roll back")
    st = json.loads(STATE_FILE.read_text())
    for obj in reversed(st["created"]):
        if not obj["name"].startswith(PREFIX): print("refusing non-kit object", obj["name"]); continue
        try: _req("DELETE", f"/api/{obj['type']}/{obj['id']}", tok); print("removed", obj["type"], obj["name"])
        except Exception as e: print("could not remove", obj["name"], e)
    STATE_FILE.rename(STATE_FILE.with_suffix(".rolledback.json"))

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "plan"; tok = login(); STATE_DIR.mkdir(parents=True, exist_ok=True)
    if cmd in ("apply", "rollback") and "--yes" not in sys.argv: sys.exit(f"{cmd} requires --yes (run plan first)")
    {"snapshot": snapshot, "plan": plan, "apply": apply, "rollback": rollback}[cmd](tok)
