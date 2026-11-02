# Split mode (EXIT_SPLIT=1): Exit host separate from the Pasarguard master

Use when the master is panel-only (e.g. panel on 127.0.0.1 behind cloudflared, no inbound ports) and the
backhaul Exit is another server — possibly one already running a Pasarguard node.

## Topology
```
users -> Iran (pg-node fk1 core) ==tunnel paths==> EXIT (kit xray, own unit) -> Internet
panel (master) --grpc/TLS--> EXIT:CTL_LOCAL_PORT (nft: MASTER_IP only) -> reverse portal -> tunnel -> Iran 127.0.0.1:PG_NODE_PORT
failover controller (EXIT) -> panel API via public PASARGUARD_URL (PUT only the kit core, restart_nodes=false)
```
- Iran never sees the master IP. The master only dials the Exit (it already dials existing nodes there).
- Nothing is installed on the master; it only gets add-only panel objects (core/node/hosts prefixed KIT_PREFIX).
- On the Exit: own xray binary in /opt/vpn-infra-kit/exit/bin, unit `${KIT_PREFIX}-exit-xray`, own nft table
  `inet ${KIT_PREFIX}_exit` that only matches kit ports. Existing node container/xray/ports are never touched.
- Ports (defaults): REALITY 8444 + DIRECT 9443 (Iran IP only), XHTTP origin 10443 (TLS by xray, CDN-facing),
  control 62051 (master IP only), socks test 10808 (localhost). 443 is NOT shared with the existing node.
- CF orange: add an Origin Rule (hostname -> destination port XHTTP_ORIGIN_PORT). Gcore/Bunny origin: https://EXIT_IP:XHTTP_ORIGIN_PORT, Host header = the CDN hostname.
- Certs: acme.sh DNS-01 via Cloudflare (CF_DNS_TOKEN, DNS:Edit only), auto-renew restarts only the kit unit.
- Keep CTL_DIRECT_FALLBACK=0 in split mode: a direct fallback would make the master dial Iran directly (exposes master IP).

## Run
From a workstation: `ENV_FILE=/path/.env installer/ship_to_exit.sh --plan`, then `--phase <name>` per phase.
