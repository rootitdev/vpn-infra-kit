# Install prompt — paste everything below the line into a NEW chat with the bot

---

You are setting up my VPN tunnel stack from the PRIVATE GitHub repo `rootitdev/vpn-infra-kit` (branch `main`).
Read `README.md`, `docs/ARCHITECTURE.md`, `.env.example`, `install.sh`, `rollback.sh` and `master/pg_master.py` in full before doing anything.

## Step 0 — ask me which mode FIRST (do nothing else before I answer)
Ask: "Which mode? **standalone** or **master**?" and explain briefly:
- **standalone** (`INSTALL_MODE=standalone`): no shared master. A fresh Germany/Exit server gets its own Pasarguard panel,
  exit xray, nginx, panels (path-web, settle-web /settle + /pay, ig-mult-web, sni-watch), plus the Iran node.
  Default path priority: REALITY → XHTTP → GCORE → BUNNY → CF → DIRECT.
- **master** (`INSTALL_MODE=master`): the Germany server is an EXISTING Pasarguard (latest dev) master serving OTHER nodes.
  Only new `KIT_PREFIX`-named objects are ADDED (own backhaul xray unit, core config, node, hosts, commented nft rules,
  one nginx conf.d file + reload). Panels skipped. Default priority (CDN-first, hides the master IP): XHTTP → GCORE → CF → REALITY → DIRECT.
In both modes CF-orange is watch-only, and I may override the order with `PATH_PRIORITY`.

## Goal
Build an Iran ⇄ Germany (Exit) tunnel for Pasarguard with backhaul paths REALITY, XHTTP, GCORE, BUNNY, CF-gray, DIRECT
(+ CF-orange watch-only), real-traffic health checks, 15-second automatic failover in `PATH_PRIORITY` order, and daily
GPG-encrypted backups to Telegram, in the mode I chose.

**Panel ⇄ node control link (both modes, `CTL_MODE=tunnel` default):** the Iran node API must listen on 127.0.0.1 only and be
reached by the panel THROUGH the tunnel (Iran `KIT_PREFIX-ctl-bridge` reverse bridge over XHTTP/REALITY → reverse portal in the
kit's Exit xray → local-only `CTL_LOCAL_PORT` on the Exit). The node API port must never be publicly open; with
`CTL_DIRECT_FALLBACK=1` (or `CTL_MODE=direct`) it is open ONLY to the Exit IP. Ask me whether I want the fallback.
If the panel runs in docker without host networking, set `CTL_LISTEN`/`CTL_NODE_ADDRESS` to the docker bridge gateway.

## Hard safety rules (never break these)
1. Never print, echo, log or paste any secret (passwords, tokens, keys, UUIDs, passphrases). Refer to them by variable name only.
2. Collect every `.env` value from me through a secure secret form — never ask me to type secrets in chat. Store the file at
   `/root/.vpn-secrets/.env` on the master with mode 600. Prefer SSH keys over passwords.
3. On the master: do NOT restart, modify or delete any existing node, inbound, host, core config, user, group, container,
   xray process or nginx config. Only ADD uniquely named objects with prefix `KIT_PREFIX`. Use the Pasarguard API, not DB edits.
   nginx changes: `nginx -t` then `reload` only. Never `systemctl restart` the panel, docker, xray or nginx on master.
   If any step truly requires a restart of a shared service, STOP, explain why and the expected impact, and wait for my explicit OK.
4. Back up before every change (install.sh does this into `/var/lib/vpn-infra-kit/backups/<timestamp>`; also run
   `master/pg_master.py snapshot`). Never delete files — rename to `.disabled` if something must be turned off.
5. Do not change SSH config, passwords, or firewall default policies. nft additions must be scoped and commented.
6. **Target guard:** before anything, create `/root/.vpn-secrets/target-deny.txt` on the control host listing any server IPs I
   say must never be touched (e.g. my own existing servers). The installer refuses to run against them. Never bypass it.
7. Before every `git push` run `installer/secret-scan.sh` and only push if it says CLEAN.
8. Every time you report a time, use Asia/Tehran.

## Steps
1. **Setup questionnaire.** Ask in this exact order, ONE question group at a time. Non-secret answers go in chat.
   Every SECRET (marked 🔒) is requested through a secure secret form, one field per form, never in chat, never echoed back.
   After each group, repeat the non-secret answers as a short table and ask me to confirm.
   - **A. Mode:** `standalone` or `master` (see Step 0). If master: is the Exit (e.g. Germany) a separate server from the
     master panel? → `EXIT_SPLIT=1` (3 servers) or `0` (Exit = master).
   - **B. Servers — ask separately for each of the THREE roles** (Iran node, Exit, Master panel; in a 2-server layout say
     "same as Exit" for master):
     IP · SSH port · SSH user · auth method (`password` or `key`) → 🔒 password, or 🔒 private key (saved as a file on the box,
     path goes in `*_SSH_KEY_FILE`) · provider · location/city. For the master you may choose `MASTER_AUTH=none`
     (panel API only, no SSH). Then SSH in read-only and **check the OS** (`/etc/os-release`, kernel, free RAM/disk, open ports);
     report it and stop if it's not Ubuntu 22.04/24.04 or Debian 12 unless I agree.
   - **C. Pasarguard master panel:** panel URL · version (from the dashboard) · auth: 🔒 temporary API key (`pg_key_...`,
     preferred) OR admin username + 🔒 admin password. Warn me: failover needs long-lived auth; a temporary key must be
     replaced by a long-lived key/admin login before I revoke it. Verify by a read-only API call (list nodes/groups) and show
     me the existing nodes, groups and inbounds count.
   - **D. Naming:** node name (`PG_NODE_NAME`) · core config name (`PG_CORE_NAME`) · `KIT_PREFIX` (short, e.g. `fk1`) ·
     group(s) the new inbounds are attached to (`PG_GROUPS`, pick from the list you showed; create new? `PG_GROUP_CREATE`) ·
     subscription host remark template (`HOST_REMARK_TEMPLATE`, e.g. `{prefix}-{proto}` → `fk1-VLESS-REALITY`) and host address
     (`HOST_ADDRESS`, default Iran domain/IP). Check every name is unused on the master.
   - **E. Domains per path:** XHTTP, CF gray, CF orange (watch-only), Gcore, Bunny, Iran (subscription address), panel.
     Empty = path skipped.
   - **F. Cloudflare:** 🔒 API token (scopes: Zone Read, DNS Edit, Zone Settings Edit, Cache Rules Edit, Firewall Services Edit),
     zone name(s) (`CF_ZONES`), 🔒 optional DNS-only token for certs (`CF_DNS_TOKEN`).
   - **G. Gcore:** 🔒 API token + the Gcore hostname. ⚠ It must be a **non-.ir** domain — Gcore rejects `.ir`.
   - **H. Bunny:** 🔒 API key + hostname. ⚠ The Bunny account must have a **funded balance**; at $0 / trial end the zone stops
     serving (403 / certificate mismatch). Ask me to confirm the balance, else skip Bunny.
   - **I. Let's Encrypt:** email (`ACME_EMAIL`).
   - **J. Backup:** 🔒 Telegram bot token + chat ID (`TELEGRAM_CHAT_ID`, non-secret). If I say "later", skip the backup phase
     and remind me at the end.
   - **K. Path priority:** show the mode default and ask whether to keep it or give `PATH_PRIORITY`; ask about
     `CTL_DIRECT_FALLBACK`.
   - **L. Web panels — ask each as a separate yes/no question; build/install the web version of every "yes":**
     1. "Install the Instagram multiplier web panel?" → `INSTALL_PANEL_IG=1`
     2. "Install the Failover web panel?" → `INSTALL_PANEL_FAILOVER=1`; then ask its hostname (`PATH_WEB_DOMAIN`, e.g. path.<zone>)
        and login user (`PATH_WEB_USER`, default admin). Password is generated (`PATH_WEB_PASS`) — never show it in chat;
        tell me where it is stored. In split mode it runs on the Exit over HTTPS on `PATH_WEB_PORT` (default 8790) behind a
        CF-proxied hostname + Origin Rule to that port; nft allows only Cloudflare edge IPs to that port.
     3. "Install the Sales web panel?" → `INSTALL_PANEL_SALES=1` (master mode: warn it sells on the shared master panel).
   Auto-generated (never ask): REALITY keys, UUIDs, XHTTP path, node API key, backup passphrase, panel passwords.
   Write everything to `/root/.vpn-secrets/.env` (600) following `.env.example`; never display the file.
2. Copy the repo to the Exit/master at `/opt/vpn-infra-kit`, write the `.env` there (600) with `INSTALL_MODE` set to my answer,
   create the target-deny file, and run `./install.sh --plan`.
   This is read-only preflight: SSH reachability, Pasarguard API, port collisions (8444/10443/9443/10808 and the node port —
   pick free ones if taken), current nftables tables, how 443 is served, DNS resolution, and an API snapshot of the master.
3. In master mode also run `python3 master/pg_master.py plan`. Show me ONE consolidated plan: every object/file/rule that will be added,
   on which host, plus what stays untouched (count of existing nodes/hosts/users). List blockers. **Wait for my "yes".**
4. After my OK, run phases one at a time and report after each:
   `gen` → `exit` → `iran` (includes `ctl`) → `paths` (in master mode asks again before writing to the master API) →
   `hosts` (creates the subscription hosts and appends the new inbounds to `PG_GROUPS` — show its dry-run first) → `cert` (split) → `panels` (any mode; installs only the panels answered "yes" in L) → `failover` → `backup` → `verify`.
5. Manual items you must guide me through (with exact clicks/values) and then re-check: DNS records, Gcore resource,
   Bunny pull zone + custom hostname cert, Cloudflare settings for CF-orange (see docs/ARCHITECTURE.md), TLS certs,
   and — if master multiplexes :443 with an SNI stream map — the map entries for the new hostnames (show me the exact diff first).
6. **Verify end to end** from Iran: for EVERY enabled path, force that outbound and request `https://www.gstatic.com/generate_204`
   through the tunnel — expect HTTP 204 for each; report latency and a speed sample. Then confirm failover: show health.json
   status for all paths, the active path and the priority in use. Control link: the panel shows the new node connected via
   `CTL_NODE_ADDRESS:CTL_LOCAL_PORT`, `KIT_PREFIX-ctl-bridge` is active, the node API is bound to 127.0.0.1 on Iran, and the node
   port is NOT reachable from the Internet (only from the Exit IP if fallback is on). In master mode confirm the master's OTHER nodes are still
   "connected" (compare with the snapshot).
7. Final report: active path, per-path result table, what was added on each host, backup locations, where the backup
   passphrase is (variable name and file only — tell me to copy it offline), how to roll back
   (`./rollback.sh --exit --yes`, `--ctl --yes`, `--master-objects --yes` in master mode, `--restore <TS> --yes`), and anything left manual.

## If something fails
Stop at the failing phase, show the error (with secrets redacted), propose the fix, and wait for me. Never "clean up" by deleting
anything on the master. Use `rollback.sh` only with my explicit approval.
