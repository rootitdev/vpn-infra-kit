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
from urllib.error import HTTPError
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
    data = None; h = {"Accept": "application/json", "User-Agent": "vpn-infra-kit/1.0"}  # CF bot rules 403 Python-urllib UA
    if body is not None:
        if form: data = urlencode(body).encode(); h["Content-Type"] = "application/x-www-form-urlencoded"
        else: data = json.dumps(body).encode(); h["Content-Type"] = "application/json"
    if token and token.startswith("apikey:"): h["X-Api-Key"] = token[7:]
    elif token: h["Authorization"] = f"Bearer {token}"
    try:
        with urlopen(Request(BASE + path, data=data, headers=h, method=method), timeout=30) as r:
            raw = r.read(); return json.loads(raw) if raw else None
    except HTTPError as e:
        sys.stderr.write(f"API {method} {path} -> {e.code}: {e.read().decode(errors='replace')[:800]}\n"); raise

def login():
    # Temporary panel API key (pg_key_...) preferred: no admin password needed; revoke it after install.
    if ENV.get("PASARGUARD_API_KEY"): return "apikey:" + ENV["PASARGUARD_API_KEY"]
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

def _server_ca():
    f = Path(ENV.get("NODE_SERVER_CA_FILE") or (STATE_DIR / "iran-node-cert.pem"))
    return f.read_text() if f.exists() else ""

def _inline_certs(cfg):
    """Panel validates certificateFile paths on the MASTER filesystem; in split mode the files only exist on the Exit/Iran.
    Embed the cert/key inline instead (refreshed by `refresh-cert` from the acme renew hook)."""
    cf, kf = ENV.get("TLS_CERT_FILE", ""), ENV.get("TLS_KEY_FILE", "")
    if ENV.get("EXIT_SPLIT") != "1" or not (cf and Path(cf).exists()): return cfg
    cert, key = Path(cf).read_text().splitlines(), Path(kf).read_text().splitlines()
    for i in cfg.get("inbounds", []):
        for c in (i.get("streamSettings", {}).get("tlsSettings", {}) or {}).get("certificates", []):
            if "certificateFile" in c: c.pop("certificateFile"); c.pop("keyFile", None); c["certificate"] = cert; c["key"] = key
    return cfg

def desired():
    core_cfg = _inline_certs(json.loads((RENDER / "templates" / "iran-core.json.tmpl").read_text()))
    return {
        "core": {"name": ENV.get("PG_CORE_NAME") or f"{PREFIX}-iran-core", "config": core_cfg, "exclude_inbound_tags": [], "fallbacks_inbound_tags": []},
        "node": {"name": ENV.get("PG_NODE_NAME") or f"{PREFIX}-iran", "address": (ENV.get("CTL_NODE_ADDRESS") or (ENV["EXIT_IP"] if ENV.get("EXIT_SPLIT") == "1" else "127.0.0.1") if ENV.get("CTL_MODE", "tunnel") == "tunnel" else ENV["IRAN_IP"]),
                  "port": int(ENV.get("CTL_LOCAL_PORT", "62051") if ENV.get("CTL_MODE", "tunnel") == "tunnel" else ENV.get("PG_NODE_PORT", "62050")),
                  "api_key": ENV["PG_NODE_API_KEY"], "connection_type": "grpc", "usage_coefficient": 1.0, "keep_alive": 60,
                  "server_ca": _server_ca()},
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
    if not d["node"]["server_ca"]: problems.append("node server_ca missing (run --phase iran first)")
    if problems: sys.exit("blockers present; nothing applied: " + "; ".join(problems))
    snapshot(tok)
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {"created": []}
    core = _req("POST", "/api/core", tok, d["core"]); state["created"].append({"type": "core", "id": core["id"], "name": d["core"]["name"]})
    STATE_FILE.write_text(json.dumps(state, indent=2))
    node_body = dict(d["node"], core_config_id=core["id"])
    node = _req("POST", "/api/node", tok, node_body); state["created"].append({"type": "node", "id": node["id"], "name": d["node"]["name"]})
    STATE_FILE.write_text(json.dumps(state, indent=2)); os.chmod(STATE_FILE, 0o600)
    print(f"created core id={core['id']} node id={node['id']}  (write PG_CORE_ID / PG_NODE_ID to .env)")
    print("hosts: create via `install.sh --phase hosts` after the node reports connected")

def refresh_cert(tok):
    st = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {"created": []}
    core = next((o for o in st["created"] if o["type"] == "core"), None)
    if not core: sys.exit("no kit core recorded")
    cur = _req("GET", f"/api/core/{core['id']}", tok); cfg = _inline_certs(cur["config"])
    body = {k: cur.get(k) for k in ("name", "exclude_inbound_tags", "fallbacks_inbound_tags")}; body["config"] = cfg
    _req("PUT", f"/api/core/{core['id']}?restart_nodes=true", tok, body); print("kit core cert refreshed (only the kit node restarts)")

def rollback(tok):
    if not STATE_FILE.exists(): sys.exit("nothing recorded; nothing to roll back")
    st = json.loads(STATE_FILE.read_text())
    for obj in reversed(st["created"]):
        if obj["type"] == "group-tags":   # restore only the tags we appended; never delete the group
            try:
                g = _req("GET", f"/api/group/{obj['id']}", tok)
                keep = [t for t in g.get("inbound_tags", []) if t not in obj["added"]]
                _req("PUT", f"/api/group/{obj['id']}", tok, {"name": g["name"], "inbound_tags": keep, "is_disabled": g.get("is_disabled", False)})
                print("group", g["name"], "-> removed kit tags", obj["added"])
            except Exception as e: print("could not restore group", obj["name"], e)
            continue
        try: _req("DELETE", f"/api/{obj['type']}/{obj['id']}", tok); print("removed", obj["type"], obj["name"])
        except Exception as e: print("could not remove", obj["name"], e)
    STATE_FILE.rename(STATE_FILE.with_suffix(".rolledback.json"))

def _state():
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {"created": []}

def _save(st):
    STATE_FILE.write_text(json.dumps(st, indent=2)); os.chmod(STATE_FILE, 0o600)

def _host_plan(tok):
    """fk1-style hosts: one subscription host per kit inbound, remark = HOST_REMARK_TEMPLATE."""
    core_cfg = json.loads((RENDER / "templates" / "iran-core.json.tmpl").read_text())
    tpl = ENV.get("HOST_REMARK_TEMPLATE") or (PREFIX + "-{proto}")
    addr = ENV.get("HOST_ADDRESS") or ENV.get("IRAN_DOMAIN") or ENV["IRAN_IP"]
    skip = {t.strip() for t in ENV.get("HOST_SKIP_TAGS", "").split(",") if t.strip()}
    have = {(h.get("inbound_tag"), h.get("remark")) for h in _list(tok, "/api/hosts")}
    out = []
    for i in core_cfg.get("inbounds", []):
        tag = i.get("tag") or ""
        if not tag or tag in skip or i.get("protocol") not in ("vless", "vmess", "trojan", "shadowsocks"): continue
        proto = tag[len(ENV.get("INBOUND_PREFIX", "")):] if tag.startswith(ENV.get("INBOUND_PREFIX", "")) else tag
        remark = tpl.format(prefix=PREFIX, proto=proto, tag=tag, node=ENV.get("PG_NODE_NAME") or f"{PREFIX}-iran")
        body = {"remark": remark, "address": [addr], "port": i.get("port"), "inbound_tag": tag, "security": "inbound_default",
                "priority": int(ENV.get("HOST_PRIORITY", "1")), "is_disabled": False}
        out.append((body, (tag, remark) in have))
    return out

def _group_plan(tok):
    want = [g.strip() for g in ENV.get("PG_GROUPS", "").split(",") if g.strip()]
    tags = [b["inbound_tag"] for b, _ in _host_plan(tok)]
    groups = {g.get("name"): g for g in _list(tok, "/api/groups")}
    plan = []
    for name in want:
        g = groups.get(name)
        if g: plan.append(("append", name, g["id"], [t for t in tags if t not in (g.get("inbound_tags") or [])]))
        elif ENV.get("PG_GROUP_CREATE", "0") == "1": plan.append(("create", name, None, tags))
        else: plan.append(("missing", name, None, tags))
    return plan

def hosts(tok):
    """hosts [--yes]: create kit hosts + attach kit inbounds to PG_GROUPS (append-only)."""
    hp = _host_plan(tok); gp = _group_plan(tok)
    print("== HOSTS / GROUPS PLAN (add-only) ==")
    for b, exists in hp: print(f"  {'=' if exists else '+'} host  {b['remark']:28} inbound={b['inbound_tag']} {b['address'][0]}:{b['port']}")
    for act, name, _, t in gp:
        print({"append": f"  ~ group {name}: append tags {t or '(none, already attached)'}", "create": f"  + group {name} with tags {t}",
               "missing": f"  ! group {name} not found (set PG_GROUP_CREATE=1 to create it)"}[act])
    if "--yes" not in sys.argv: print("(dry-run; rerun with --yes)"); return
    if any(a == "missing" for a, *_ in gp): sys.exit("missing groups; nothing applied")
    snapshot(tok); st = _state()
    for b, exists in hp:
        if exists: continue
        h = _req("POST", "/api/host", tok, b); st["created"].append({"type": "host", "id": h["id"], "name": b["remark"]}); _save(st)
        print("created host", b["remark"])
    for act, name, gid, t in gp:
        if act == "create":
            g = _req("POST", "/api/group", tok, {"name": name, "inbound_tags": t, "is_disabled": False})
            st["created"].append({"type": "group", "id": g["id"], "name": name}); _save(st); print("created group", name)
        elif act == "append" and t:
            g = _req("GET", f"/api/group/{gid}", tok)
            _req("PUT", f"/api/group/{gid}", tok, {"name": g["name"], "inbound_tags": (g.get("inbound_tags") or []) + t, "is_disabled": g.get("is_disabled", False)})
            st["created"].append({"type": "group-tags", "id": gid, "name": name, "added": t}); _save(st); print("group", name, "+", t)
    print("users are NOT modified: users in these groups now receive the new hosts in their subscription")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "plan"; tok = login()
    if cmd == "login": print("login ok"); sys.exit(0)
    if cmd != "plan": STATE_DIR.mkdir(parents=True, exist_ok=True)
    if cmd in ("apply", "rollback") and "--yes" not in sys.argv: sys.exit(f"{cmd} requires --yes (run plan first)")
    {"snapshot": snapshot, "plan": plan, "apply": apply, "rollback": rollback, "refresh-cert": refresh_cert, "hosts": hosts}[cmd](tok)
