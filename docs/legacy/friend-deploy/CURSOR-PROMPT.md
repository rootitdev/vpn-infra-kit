# Cursor prompt — replicate this 2-hop VPN stack

**Give your friend two things:**

1. This entire prompt (**after you fill the OPERATOR VALUES block below**).
2. The archive `vpn-infra-portable-scripts.tar.gz` — extract at `/root/vpn-infra`.  
   Without the tarball, Cursor will rewrite vpn-path / sync from scratch and you will debug for days.

Also give `IMPLEMENTATION-GUIDE.md` + `NODE-DISABLED.md` + `SCRIPTS-INSTALL.md` if available (or they are already under `docs/` in the tarball).

**Out of scope for this handoff (do not install):** Instagram/porn traffic multiplier, sni-watch (`/watch/`), and capacity/hardware monitor. Those are operator-private tools. Core stack only: Iran relay + Exit panel + backhaul + sync/stats + vpn-path + transparent panel proxy.

Never paste Cloudflare tokens, panel passwords, Reality keys, or API keys into chat. Put secrets only in `/root/.vpn-secrets/.env` (mode 600) on the servers.

---

You are an infrastructure engineer. Implement **this exact 2-hop architecture** on two empty Ubuntu 22.04 servers. Do **not** build a single-server VPN. Do **not** rewrite the portable scripts — adapt IPs, domains, and systemd paths only.

---

## OPERATOR VALUES — fill this block before pasting to Cursor

**This is the only place you put server IPs and hostnames.** Replace every `REPLACE_…` below with real values. Cursor must use these everywhere (scripts, nginx, nft, DNS, cores).

```text
# --- servers ---
IRAN_IP=REPLACE_IRAN_IPV4
EXIT_IP=REPLACE_EXIT_IPV4

# --- hostnames (DNS you control) ---
IR_HOST=ir.EXAMPLE.com          # client Reality/Vision entry → grey A → IRAN_IP
PANEL_IR=panel.EXAMPLE.ir       # saved client URLs :2096 → grey A → IRAN_IP
PANEL_EXIT=panel.EXAMPLE.com    # panel on 443 via CF / SNI mux → orange A → EXIT_IP
CDN_HOST=cdn.EXAMPLE.com        # backhaul CF XHTTP → orange A → EXIT_IP
XHTTP_HOST=xhttp.EXAMPLE.com    # backhaul direct XHTTP → orange or grey → EXIT_IP

# --- Cloudflare ---
# Do NOT put the API token in this prompt.
# On Exit after bootstrap, create:
#   /root/.vpn-secrets/.env   mode 600
# with at least:
#   CF_API_TOKEN=...          (Zone.DNS Edit + Zone.Zone Read for the zone)
#   CF_ZONE_ID=...            (optional if scripts need it)
#   PG_API_KEY=...            (PasarGuard X-API-Key — AFTER owner exists; see below)
# DNS records themselves are created via dashboard or cf_dns.py using that .env.
```

Also replace every leftover example IP/domain from the portable pack (`${IRAN_IP}`, `${EXIT_IP}`, `${MAIN_ZONE}`, `${ALT_ZONE}`, `${EXTRA_ZONE}`) with the values above.

### PasarGuard install + owner account (hard rule)

- Cursor **does** install PasarGuard (Docker on Exit, `127.0.0.1:8000`) as part of the stack.
- Cursor must **not** invent or auto-create the panel **owner/admin** username/password.
- On first boot PasarGuard shows a **one-time setup / create-admin token** (UI or logs). Cursor must surface that token to the human operator and **stop**.
- The **human operator** opens the panel UI, enters that token, and creates the **owner** account themselves.
- After owner login, the operator creates a panel **API key** (header `X-API-Key`) in the UI and puts it in `/root/.vpn-secrets/.env` as `PG_API_KEY`. Then tell Cursor to continue.
- Cursor then uses `PG_API_KEY` (local `.env` only — never paste into chat) to create Core / Node (disabled) / Hosts / Groups / a test user via API. The human does **not** need to pre-build those entities by hand before handing off; they only need to create **owner + API key**.

Iran **Node** row stays **disabled** forever in day-one deploy (see hard rule below). That is part of this architecture, not optional.

---

## Mandatory architecture

```
Client in Iran
  → Iran relay: VLESS Reality TCP 443 + VLESS Vision TCP 2053
       (+ optional Hysteria2 UDP 443 inbound)
  → backhaul to Exit, priority:
       1) TO-AMS-CF     XHTTP via Cloudflare orange (CDN_HOST)
       2) TO-AMS-XHTTP  XHTTP (XHTTP_HOST)
       3) TO-AMS-DIRECT VLESS+TLS TCP 9443 on Exit, nft allow IRAN_IP only
       4) TO-AMS-TUIC   listed last; UDP often dies on Iranian DC DPI
  → Exit: internet egress (optional WARP for Google)
```

Clients never connect to the Exit for VPN. Reality owns Iran `:443` — **do not put nginx on Iran 443**.

**PasarGuard panel** runs only on Exit, bound to `127.0.0.1:8000`. Exit nginx terminates TLS on `:2096`. Public Exit TCP `443` is **nginx stream `ssl_preread`** (no TLS terminate): SNI `PANEL_*` → `127.0.0.1:2096`; default → XHTTP on `127.0.0.1:10443`. Exit Xray must **not** listen on public 443.

Panel core JSON (`iran-xray`) is **not** the Exit backhaul Xray JSON. Do not point PasarGuard at the Exit Xray config or it will overwrite the tunnel.

### Panel Node row — hard rule

Create an Iran **Node** row (API typically `:62050`) but leave it **disabled**, `keep_alive=0`. **Do not Enable it** on day one. **Do not delete the row** (user inbound tags attach to it).

Why: PasarGuard’s native path is Exit `POST https://IRAN:62050/start` with a huge body (full core + all users). The node can return HTTP 200 while the panel HTTP client **times out reading the body**, retries, and enters **LockControl**. Live Iran Xray is docker `pasarguard/node` (`xray -c stdin:`). Disk `/root/.pg_nodes/iran/xray.json` is unused until `/start`.

Required control plane instead:

- Exit every ~10s: `iran_sync_export.py` builds Backend protobuf from panel sqlite; SCP to Iran `/var/lib/pg-node/sync/` if hash changed.
- Iran every ~10s: `iran_sync_apply.py` `POST https://127.0.0.1:62050/start` if hash changed **or** `:443`/`:2053` are down.
- Exit every ~30s: `iran_stats_ingest.py` SSH + `xray api statsquery` on Iran, write `used_traffic` / `online_at` into sqlite (disabled nodes are not polled by the panel).

Iran must **never** poll `https://panel:2096` on the Exit **public IP** for node sync (TLS completes, then DPI drops HTTP). Humans reach the panel from Iran via backhaul or the local SOCKS, not via raw Exit IP.

After the stack works, you **may** experiment with native Enable **only if** Exit can complete POST `/start` to Iran `:62050` repeatedly under the panel’s timeout. Until that test passes, keep SCP + local apply.

## Cloudflare and DNS

Zone: SSL **Full (Strict)**, **HTTP/3 off**.

| Record | Cloud | Points at | Role |
|---|---|---|---|
| `IR_HOST` | grey | `IRAN_IP` | Reality/Vision inbound. Never orange. |
| `PANEL_IR` (:2096 URLs) | grey | `IRAN_IP` | Transparent panel proxy. Orange does not proxy 2096. |
| `PANEL_EXIT` (443) | orange OK | `EXIT_IP` | Panel via CF + SNI mux |
| `CDN_HOST` / `XHTTP_HOST` | orange | `EXIT_IP` | Backhaul only, not client VPN |

One Let’s Encrypt cert (DNS-01 Cloudflare, using `CF_API_TOKEN` from `.env`) with SANs for all hostnames above. Copy fullchain+key to Iran. Test Iranian DNS hijack: `dig @8.8.8.8` from the relay.

## Portable pack — core only (do not rewrite)

Extract `vpn-infra-portable-scripts.tar.gz`. Treat these as source of truth; only substitute IP/domain/repo path (`/root/vpn-infra`):

- `vpn-path`, `vpn-path-core.py`, `vpn_path_lib.py`, `vpn_paths.py`, `path_health.py`, `vpn_failover.py`
- `iran_sync_export.py`, `iran_sync_apply.py`, `build_iran_start_proto.py`, `iran_stats_ingest.py`
- `cf_dns.py`, nginx iran-subproxy + `xray-subproxy.*`, nftables
- systemd units: `iran-sync-*`, `iran-stats-*`, `vpn-failover-*`

**Skip / ignore if present in the tarball:** `instagram-multiplier*`, `scripts/sni-watch/`, `configs/sni-watch/`, `scripts/monitor/`, `configs/monitor/` (except nothing required for core).

Do **not** blindly run `bootstrap-iran.sh` (it assumes systemd Xray; live Iran Xray is docker node).

Install per `docs/friend-deploy/SCRIPTS-INSTALL.md` **sections for vpn-path + sync/stats only**:

1. **vpn-path** on Exit → `/usr/local/sbin/vpn-path` + `vpn-failover.timer`
2. **iran-sync-export / iran-sync-apply / iran-stats** timers (Exit + Iran as documented)
3. **Do not** install instagram-multiplier, sni-watch, or vpn-mon-*

## Routing: panel from Iran

On Iran, **before** DIRECT `geosite:category-ir` / `*.ir`, send `PANEL_IR` / `PANEL_EXIT` to balancer `backhaul`. On Exit, those hostnames go outbound `PANEL-LOCAL` → `127.0.0.1:2096`.

Iran admin SOCKS: `127.0.0.1:11080`, inbound tag `PANEL-ADMIN`, localhost-only, not assigned to panel users.

Transparent panel proxy on Iran: nginx `:2096` and `:8443`, `proxy_pass https://127.0.0.1:10444` (xray-subproxy → SOCKS → backhaul). Dokodemo destination must be a hostname whose DNS still points at **Exit** (otherwise hairpin after you move `PANEL_IR` A to Iran). Proxy `location /` (not only `/dashboard/`) so `/statics/`, `/api/`, `/sub/` load. `proxy_ssl_verify off` on loopback. nft TCP 2096 open.

## Firewall minimum

Iran: TCP 22, 443, 2053, 8443, 2096; UDP 443; 62050/62051 **only from EXIT_IP**.

Exit: TCP 22, 80, 443, 2096 from world; TCP 9443 and backhaul UDP **only from IRAN_IP**; panel `:8000` not reachable from WAN.

## Eight steps (finish and test each)

1. Fill OPERATOR VALUES; create DNS; put `CF_API_TOKEN` in Exit `/root/.vpn-secrets/.env`; issue SAN cert  
2. Exit: nft, backhaul Xray, nginx stream 443 + http 2096  
3. Docker PasarGuard → show setup token → **wait for human owner + `PG_API_KEY` in `.env`** → then Core + Iran Node **disabled** + Hosts/Groups/test user via API  
4. Iran: docker node, Reality 443, Vision 2053  
5. SSH keys; iran-sync-export/apply; iran-stats; **do not Enable node**  
6. Test CF then XHTTP then DIRECT; install vpn-path  
7. Iran nginx/xray-subproxy 2096; grey `PANEL_IR` A to Iran if clients keep `:2096` URLs  
8. Real-client test (Reality **fragment tlshello** in the app), backups, lock down SSH  

Never print secrets. Do not invent panel owner password. Do not git commit unless asked. Do not Enable the Iran node. Do not install operator-private tools (multiplier / sni-watch / monitor).

## Done when

Report (no secrets): final IPs/hostnames; node still disabled; `vpn-path status`; sub URL and dashboard HTTP 200 via Iran `:2096`; Reality still `xray` on Iran 443 not nginx; which backhaul tag is live; which portable files were installed unchanged vs which paths you substituted.
