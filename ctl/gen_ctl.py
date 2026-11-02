#!/usr/bin/env python3
"""Generate the panel<->node CONTROL LINK configs (xray reverse proxy over the backhaul tunnel).

Pasarguard's panel dials the node API. Instead of exposing the node port on the Iran public IP, we:
  Iran : pg-node API listens on 127.0.0.1:PG_NODE_PORT only.
         A dedicated xray "ctl-bridge" (unit ${KIT_PREFIX}-ctl-bridge) dials OUT to the Exit/master through the
         tunnel (CTL_PATHS order, default XHTTP then REALITY) and registers a reverse bridge.
  Exit : the kit's own backhaul xray (${KIT_PREFIX}-exit-xray) runs a reverse PORTAL and a local-only
         dokodemo inbound 127.0.0.1:CTL_LOCAL_PORT. The panel's node address = 127.0.0.1 (or the docker host gateway),
         port CTL_LOCAL_PORT. Traffic: panel -> 127.0.0.1:CTL_LOCAL_PORT -> portal -> tunnel -> Iran bridge -> 127.0.0.1:PG_NODE_PORT.
No existing inbound/outbound/node on the master is touched; everything is new and prefixed.

usage: gen_ctl.py <rendered_iran_core.json> <exit_xray.json (modified in place)> <out_iran_ctl.json>
"""
import json, os, sys

E_ = os.environ
PFX = E_.get("KIT_PREFIX", "ikit")
DOMAIN = f"ctl.{PFX}.internal"          # reverse-proxy rendezvous name (never resolved in DNS)
LOCAL = int(E_.get("CTL_LOCAL_PORT", "62051"))
NODE = int(E_.get("PG_NODE_PORT", "62050"))
PATHS = [p.strip() for p in E_.get("CTL_PATHS", "TO-AMS-XHTTP,TO-AMS-REALITY").split(",") if p.strip()]

core = json.load(open(sys.argv[1])); exit_cfg = json.load(open(sys.argv[2]))
outs = {o["tag"]: o for o in core["outbounds"]}
tunnel = []
for t in PATHS:
    if t in outs:
        o = json.loads(json.dumps(outs[t])); o["tag"] = f"{PFX}-ctl-{t.split('-')[-1].lower()}"; tunnel.append(o)
if not tunnel: sys.exit("no CTL_PATHS outbound found in core config")

# ---- Iran side: bridge -----------------------------------------------------
iran = {
  "log": {"loglevel": "warning"},
  "reverse": {"bridges": [{"tag": f"{PFX}-ctl-bridge", "domain": DOMAIN}]},
  "outbounds": tunnel + [
    {"tag": f"{PFX}-ctl-nodeapi", "protocol": "freedom", "settings": {"redirect": f"127.0.0.1:{NODE}"}}],
  "observatory": {"subjectSelector": [o["tag"] for o in tunnel], "probeURL": "https://www.gstatic.com/generate_204", "probeInterval": "30s"},
  "routing": {
    "balancers": [{"tag": f"{PFX}-ctl-tunnel", "selector": [o["tag"] for o in tunnel], "strategy": {"type": "leastPing"},
                    "fallbackTag": tunnel[0]["tag"]}],
    "rules": [
      {"type": "field", "inboundTag": [f"{PFX}-ctl-bridge"], "domain": [f"full:{DOMAIN}"], "balancerTag": f"{PFX}-ctl-tunnel"},
      {"type": "field", "inboundTag": [f"{PFX}-ctl-bridge"], "outboundTag": f"{PFX}-ctl-nodeapi"}]},
}
json.dump(iran, open(sys.argv[3], "w"), indent=2); os.chmod(sys.argv[3], 0o600)

# ---- Exit side: portal + local-only entry (idempotent) ---------------------
portal = f"{PFX}-ctl-portal"; entry = f"{PFX}-ctl-in"
exit_cfg.setdefault("reverse", {}).setdefault("portals", [])
exit_cfg["reverse"]["portals"] = [p for p in exit_cfg["reverse"]["portals"] if p.get("tag") != portal] + [{"tag": portal, "domain": DOMAIN}]
exit_cfg["inbounds"] = [i for i in exit_cfg["inbounds"] if i.get("tag") != entry] + [{
  "tag": entry, "listen": E_.get("CTL_LISTEN", "127.0.0.1"), "port": LOCAL, "protocol": "dokodemo-door",
  "settings": {"address": "127.0.0.1", "port": NODE, "network": "tcp"}}]
bridge_inbounds = [i["tag"] for i in exit_cfg["inbounds"] if any(k in i["tag"] for k in ("reality-bridge", "xhttp-bridge", "direct-tls"))]
rules = exit_cfg.setdefault("routing", {}).setdefault("rules", [])
rules[:] = [r for r in rules if r.get("outboundTag") != portal]
rules[0:0] = [
  {"type": "field", "inboundTag": [entry], "outboundTag": portal},
  {"type": "field", "inboundTag": bridge_inbounds, "domain": [f"full:{DOMAIN}"], "outboundTag": portal}]
json.dump(exit_cfg, open(sys.argv[2], "w"), indent=2)
print(f"ctl: panel -> 127.0.0.1:{LOCAL} -> portal -> tunnel({', '.join(o['tag'] for o in tunnel)}) -> Iran 127.0.0.1:{NODE}")
