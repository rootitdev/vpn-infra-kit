# Cursor prompt — 2-hop VPN stack (core + path/backhaul UI)

**به دوست بده:**

1. همین پرامپت (بعد از پر کردن بلوک **OPERATOR VALUES**).
2. ریپوی گیت‌هاب (ترجیح) **یا** آرشیو portable:

```text
https://github.com/${GITHUB_OWNER}/vpn-infra.git
```

روی هر دو سرور (یا حداقل Exit):

```bash
git clone https://github.com/${GITHUB_OWNER}/vpn-infra.git /root/vpn-infra
# جایگزین tarball: tar را در /root/vpn-infra باز کنید اگر کلون ممکن نیست
```

پنل مسیریابی بک‌هال (**path-web** / همان vpn-path UI) داخل همین ریپو است:

```bash
cd /root/vpn-infra/scripts/path-web
sudo bash install.sh
```

3. در صورت وجود کنار پرامپت: `IMPLEMENTATION-GUIDE.md` + `NODE-DISABLED.md` + `SCRIPTS-INSTALL.md`.

**منبع حقیقت کد:** ریپوی بالا — از نو ننویس. اگر کلون در دسترس نبود از `vpn-infra-portable-scripts.tar.gz` استفاده کن؛ بدون یکی از این دو، Cursor اسکریپت‌ها را از صفر می‌سازد و روزها دیباگ می‌کنید.

---

## Out of scope — نصب نکن / نساز

این‌ها عمداً در این استقرار **نیستند** (حتی اگر داخل tarball باشند، نادیده بگیر):

| مسیر وب / ابزار | دلیل |
|---|---|
| `https://…:2096/watch/` — `sni-watch` | ابزار شخصی اپراتور |
| `https://…:2096/ig/` — `ig-mult-web` + `instagram-multiplier` | ضریب ترافیک اینستا/پورن — شخصی |
| `https://…:2096/settle/` — `settle-web` | تسویه نمایندگی — شخصی |
| `scripts/monitor/` / vpn-mon-* | مانیتور ظرفیت — شخصی |

**حتماً نصب کن:** هسته دوهاب + کنترل‌پلین سینک + **vpn-path** + **path-web** (`/path/`) برای انتخاب مسیر بک‌هال.

Never paste Cloudflare tokens, panel passwords, Reality keys, or API keys into chat. Secrets only in `/root/.vpn-secrets/.env` (mode 600).

---

You are an infrastructure engineer. Implement **this exact 2-hop architecture** on two empty **Ubuntu 22.04** servers. Do **not** build a single-server VPN. Do **not** rewrite the portable scripts — adapt IPs, domains, and systemd paths only.

---

## OPERATOR VALUES — fill before pasting to Cursor

```text
# --- servers ---
IRAN_IP=REPLACE_IRAN_IPV4
EXIT_IP=REPLACE_EXIT_IPV4

# --- hostnames (DNS you control) ---
IR_HOST=ir.EXAMPLE.com          # client Reality/Vision → grey A → IRAN_IP
PANEL_IR=panel.EXAMPLE.ir       # client panel URLs :2096 → grey A → IRAN_IP
PANEL_EXIT=panel.EXAMPLE.com    # panel on 443 via CF / SNI mux → orange A → EXIT_IP
CDN_HOST=cdn.EXAMPLE.com        # backhaul CF XHTTP → orange A → EXIT_IP
XHTTP_HOST=xhttp.EXAMPLE.com    # backhaul direct XHTTP → orange/grey → EXIT_IP

# --- path-web login (separate from PasarGuard) ---
PATH_WEB_USER=path
PATH_WEB_PASS=REPLACE_STRONG_PASSWORD   # or leave empty for install.sh to generate

# --- Cloudflare ---
# Do NOT put the API token in this prompt.
# On Exit after bootstrap, create /root/.vpn-secrets/.env mode 600 with at least:
#   CF_API_TOKEN=...     (Zone.DNS Edit + Zone.Zone Read)
#   CF_ZONE_ID=...       (optional)
#   PG_API_KEY=...       (AFTER owner exists — see below)
#   PG_CORE_ID=...       (after Core created; vpn-path / path-web need it)
```

Replace every leftover example from the portable pack (`${IRAN_IP}`, `${EXIT_IP}`, `${MAIN_ZONE}`, `${ALT_ZONE}`, `${EXTRA_ZONE}`) with the values above.

### PasarGuard install + owner (hard rule)

- Cursor **does** install PasarGuard (Docker on Exit, `127.0.0.1:8000`).
- Cursor must **not** invent the panel owner username/password.
- First boot shows a one-time setup token → Cursor surfaces it and **stops**.
- Human creates owner in UI, then creates API key (`X-API-Key`) → puts `PG_API_KEY` in `.env` → tells Cursor to continue.
- Cursor then creates Core / Iran Node (**disabled**) / Hosts / Groups / test user via API.

Iran **Node** row stays **disabled** forever on day one (`keep_alive=0`). Do not Enable. Do not delete the row.

---

## Mandatory architecture

```
Client in Iran
  → Iran relay: VLESS Reality TCP 443 + VLESS Vision TCP 2053
       (+ optional Hysteria2 UDP 443 inbound)
  → backhaul to Exit, priority (vpn-path / path-web switches these):
       1) TO-AMS-CF     XHTTP via Cloudflare orange (CDN_HOST)
       2) TO-AMS-XHTTP  XHTTP (XHTTP_HOST)
       3) TO-AMS-DIRECT VLESS+TLS TCP 9443 on Exit, nft allow IRAN_IP only
       4) TO-AMS-TUIC   listed last; UDP often dies on Iranian DC DPI
  → Exit: internet egress (optional WARP for Google)
```

Clients never connect to Exit for VPN. Reality owns Iran `:443` — **no nginx on Iran 443**.

**PasarGuard** only on Exit → `127.0.0.1:8000`. Exit nginx TLS on `:2096`. Public Exit TCP `443` is **nginx stream `ssl_preread`** (no TLS terminate): SNI `PANEL_*` → `127.0.0.1:2096`; default → XHTTP `127.0.0.1:10443`. Exit Xray must **not** listen on public 443.

Panel core JSON (`iran-xray`) is **not** the Exit backhaul Xray JSON. Never point PasarGuard at Exit Xray config.

### Panel Node — hard rule

Create Iran Node (API typically `:62050`) but leave **disabled**. Why: native Enable does Exit `POST https://IRAN:62050/start` with a huge body; panel client often times out → LockControl. Live Iran Xray is docker `pasarguard/node` (`xray -c stdin:`).

Required control plane:

- Exit ~10s: `iran_sync_export.py` → Backend protobuf from panel sqlite → SCP to Iran `/var/lib/pg-node/sync/` if hash changed.
- Iran ~10s: `iran_sync_apply.py` → `POST https://127.0.0.1:62050/start` if hash changed **or** `:443`/`:2053` down.
- Exit ~30s: `iran_stats_ingest.py` → SSH + `xray api statsquery` on Iran → `used_traffic` / `online_at` in sqlite.

Iran must **never** poll `https://panel:2096` on Exit **public IP** for node sync (TLS OK, then DPI drops HTTP). Humans open panel from Iran via backhaul/subproxy or local SOCKS.

## Cloudflare and DNS

Zone: SSL **Full (Strict)**, **HTTP/3 off**.

| Record | Cloud | Points at | Role |
|---|---|---|---|
| `IR_HOST` | grey | `IRAN_IP` | Reality/Vision. Never orange. |
| `PANEL_IR` (:2096) | grey | `IRAN_IP` | Transparent panel proxy. CF does not proxy 2096. |
| `PANEL_EXIT` (443) | orange OK | `EXIT_IP` | Panel via CF + SNI mux |
| `CDN_HOST` / `XHTTP_HOST` | orange | `EXIT_IP` | Backhaul only |

One Let’s Encrypt cert (DNS-01 Cloudflare) with SANs for all hostnames. Copy fullchain+key to Iran.

## Portable pack — install these (do not rewrite)

Extract tarball to `/root/vpn-infra`. Source of truth; only substitute IP/domain/path:

### A) Control plane + backhaul routing CLI

```
scripts/vpn-path                 → /usr/local/sbin/vpn-path   (Exit)
scripts/vpn-path-core.py
scripts/vpn_path_lib.py
scripts/vpn_paths.py
scripts/path_health.py
scripts/vpn_failover.py
configs/vpn-failover.service
configs/vpn-failover.timer
scripts/vpn-path-iran-stub.sh    → Iran /usr/local/sbin/vpn-path (optional stub)

scripts/iran_sync_export.py      (Exit)
scripts/iran_sync_apply.py       (Iran)
scripts/build_iran_start_proto.py
scripts/iran_stats_ingest.py     (Exit)
configs/iran-sync-*.service/timer
configs/iran-stats-*.service/timer

scripts/cf_dns.py
scripts/panel-via-backhaul
nginx iran-subproxy + xray-subproxy.*
nftables samples
```

### B) path-web — UI for backhaul path selection (REQUIRED)

Same GitHub repo: `https://github.com/${GITHUB_OWNER}/vpn-infra` → folder `scripts/path-web/`  
(CLI is `vpn-path`; web UI is `path-web` at `/path/` — do not invent a third tool named vpn-patch.)

```
scripts/path-web/app.py
scripts/path-web/install.sh
scripts/path-web/path-web.service
scripts/lib/panel_install_lib.sh   # required by install.sh
```

**Install on Exit only** (after `vpn-path` works and `PG_API_KEY` + `PG_CORE_ID` exist in secrets):

```bash
# if repo missing:
# git clone https://github.com/${GITHUB_OWNER}/vpn-infra.git /root/vpn-infra
cd /root/vpn-infra/scripts/path-web
sudo PANEL_BASE="https://${PANEL_EXIT}:2096" \
     AUTH_USER="${PATH_WEB_USER}" \
     AUTH_PASS="${PATH_WEB_PASS}" \
     PANEL_NGINX_APPLY=y \
     bash install.sh
```

Expected result:

| Item | Value |
|---|---|
| systemd | `path-web.service` listen `127.0.0.1:8790` (or as set) |
| password file | `/etc/path-web/admin.pass` mode 600 |
| nginx on Exit `:2096` | `location /path/` → `http://127.0.0.1:8790/` |
| UI URL | `https://PANEL_EXIT:2096/path/` (and via Iran subproxy same path) |
| auth | **Separate** from PasarGuard login |

CLI equivalents (must still work):

```bash
vpn-path status|auto|cf|xhttp|direct|tuic|publish|test
systemctl status vpn-failover.timer
```

`path-web` must set `Environment=VPN_SCRIPTS=/root/vpn-infra/scripts` so it imports the same libs as `vpn-path`. Do not invent a second routing engine.

### Skip / ignore if present in tarball

```
scripts/instagram-multiplier*
scripts/ig-mult-web/
scripts/sni-watch/
scripts/settle-web/
scripts/monitor/          # capacity monitor — skip
configs/sni-watch/
configs/monitor/instagram-multiplier*
```

Do **not** add nginx `location /watch/`, `/ig/`, or `/settle/`.

Do **not** blindly run `bootstrap-iran.sh` (assumes systemd Xray; live Iran Xray is docker node).

## Routing: panel from Iran

On Iran, **before** DIRECT `geosite:category-ir` / `*.ir`, send `PANEL_IR` / `PANEL_EXIT` to balancer `backhaul`. On Exit, those hostnames → outbound `PANEL-LOCAL` → `127.0.0.1:2096`.

Iran admin SOCKS: `127.0.0.1:11080`, tag `PANEL-ADMIN`, localhost-only.

Transparent panel proxy on Iran: nginx `:2096` and `:8443`, `proxy_pass https://127.0.0.1:10444` (xray-subproxy → SOCKS → backhaul). Dokodemo destination = hostname whose DNS still points at **Exit** (avoid hairpin after moving `PANEL_IR` A to Iran). Proxy `location /` (not only `/dashboard/`) so `/statics/`, `/api/`, `/sub/`, and **`/path/`** load. `proxy_ssl_verify off` on loopback. nft TCP 2096 open.

## Firewall minimum

**Iran:** TCP 22, 443, 2053, 8443, 2096; UDP 443; 62050/62051 **only from EXIT_IP**.

**Exit:** TCP 22, 80, 443, 2096 from world; TCP 9443 and backhaul UDP **only from IRAN_IP**; panel `:8000` and path-web `:8790` not on WAN.

## Eight steps (finish and test each)

1. Fill OPERATOR VALUES; DNS; `CF_API_TOKEN` in Exit `.env`; issue SAN cert  
2. Exit: nft, backhaul Xray, nginx stream 443 + http 2096  
3. Docker PasarGuard → setup token → **wait for human owner + `PG_API_KEY`** → Core + Iran Node **disabled** + Hosts/Groups/test user; record `PG_CORE_ID` in `.env`  
4. Iran: docker node, Reality 443, Vision 2053  
5. SSH keys; iran-sync-export/apply; iran-stats; **do not Enable node**  
6. Test CF → XHTTP → DIRECT; install `vpn-path` + `vpn-failover.timer`; verify `vpn-path status`  
7. Install **path-web** + nginx `/path/`; Iran nginx/xray-subproxy 2096 (include `/path/`); grey `PANEL_IR` A to Iran if clients keep `:2096` URLs  
8. Real-client test (Reality **fragment tlshello** in app), backups, SSH key-only  

Never print secrets. Do not invent panel owner password. Do not git commit unless asked. Do not Enable the Iran node. Do not install watch / ig / settle / multiplier / capacity monitor.

## Done when

Report (no secrets):

- Final IPs/hostnames  
- Node still **disabled**  
- `vpn-path status` and which backhaul tag is live  
- `systemctl is-active path-web vpn-failover.timer iran-sync-export.timer` (names as installed)  
- Dashboard HTTP 200 via Iran `:2096`  
- `https://…:2096/path/` reachable (login with path-web user, **not** PasarGuard)  
- Confirm `/watch/`, `/ig/`, `/settle/` are **absent** (404 or not configured)  
- Reality still `xray` on Iran 443 (not nginx)  
- Which portable files installed unchanged vs path substitutions only  
