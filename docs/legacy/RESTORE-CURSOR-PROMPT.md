# Cursor prompt — disaster restore از بکاپ GPG (سرور خام → استک کامل)

این فایل را **کامل** در یک چت جدید Cursor بده (روی سرور Exit خام، یا از ماشینی که SSH root به Exit و ایران دارد).

همراه این پرامپت این‌ها را هم بده / آماده کن:

1. فایل بکاپ `vpn-stack-YYYYMMDD….tar.gz.gpg` (از تلگرام یا کپی آفلاین)
2. مقدار `BACKUP_PASSPHRASE` (آفلاین — **داخل پیام تلگرام نیست**)
3. بلوک **OPERATOR VALUES** پایین را قبل از پیست پر کن

---

## BACKUP_PASSPHRASE کجاست؟

| محل | دارد؟ |
|---|---|
| کپشن تلگرام ربات (`Keep BACKUP_PASSPHRASE offline`) | **خیر** — عمداً فقط یادآوری است |
| داخل فایل `.gpg` (بعد از decrypt با همان passphrase) | بله، داخل `exit/root/.vpn-secrets/.env` |
| روی Exit زنده: `/root/.vpn-secrets/.env` کلید `BACKUP_PASSPHRASE=` | بله |

اگر سرور Exit پاک شده و passphrase را جای دیگر ذخیره نکرده‌ای، آرشیو تلگرام **باز نمی‌شود**. همین الان در password manager نگه دار؛ هرگز در چت/گیت/تلگرام نفرست.

رمزگشایی مثال (روی ماشین معتمد؛ passphrase را از env یا prompt وارد کن، در لاگ چاپ نکن):

```bash
gpg --batch --yes --passphrase-file <(printf '%s' "$BACKUP_PASSPHRASE") \
  -d vpn-stack-….tar.gz.gpg > stack.tgz
tar -xzf stack.tgz
# باید ببینی: exit/  iran/  meta/
```

---

You are an infrastructure engineer. Restore **this exact production 2-hop VPN stack** from an encrypted backup onto **bare Ubuntu 22.04+** servers. Do **not** redesign the architecture. Do **not** invent new domains/IPs — use OPERATOR VALUES. Do **not** print secrets, tokens, private keys, or `BACKUP_PASSPHRASE` into chat or commit logs. Put secrets only under `/root/.vpn-secrets/` mode `700` / files `600`.

Speak Persian briefly to the operator for status; keep commands and file paths exact.

---

## OPERATOR VALUES — قبل از پیست پر کن

```text
# --- backup ---
BACKUP_GPG_PATH=REPLACE_PATH_TO/vpn-stack-….tar.gz.gpg
# Do NOT paste BACKUP_PASSPHRASE into this prompt.
# On the restore machine, export it once in the shell only:
#   export BACKUP_PASSPHRASE='…'   # from password manager
# Or place temporarily in /root/.vpn-secrets/.env after creating that file.

# --- which hosts are wiped? ---
RESTORE_EXIT=yes          # yes|no
RESTORE_IRAN=yes          # yes|no

# --- target servers (new or same IPs) ---
IRAN_IP=REPLACE_IRAN_IPV4
EXIT_IP=REPLACE_EXIT_IPV4
IRAN_SSH=root@REPLACE_IRAN_IPV4
EXIT_SSH=root@REPLACE_EXIT_IPV4   # if agent runs elsewhere

# --- DNS hostnames (must match certs / Reality / nginx in backup, OR you will edit after restore) ---
IR_HOST=REPLACE          # client entry → grey → IRAN_IP
PANEL_IR=REPLACE         # panel URLs from Iran → grey → IRAN_IP :2096
PANEL_EXIT=REPLACE       # Exit panel SNI / CF
CDN_HOST=REPLACE         # CF XHTTP backhaul
XHTTP_HOST=REPLACE

# --- IP change? ---
OLD_EXIT_IP=${EXIT_IP}     # from meta/README.txt inside archive if present
OLD_IRAN_IP=${IRAN_IP}
IPS_CHANGED=no                 # yes if new VPS has different IPs → must rewrite configs + DNS
```

**Hard rules**

- Iran **Node** row in PasarGuard stays **disabled** (`keep_alive=0`). Do not Enable. Do not delete the row.
- Clients connect only to Iran; Exit is egress + panel.
- Never put Cloudflare / panel / Reality secrets in chat.
- Prefer restoring files from the archive over rewriting scripts from scratch.
- After restore, run one real client test and `vpn-path status`.

---

## Architecture (must preserve)

```
Client → Iran (Reality :443, Vision :2053, optional HY2 UDP :443)
      → backhaul (CF XHTTP / XHTTP / DIRECT :9443 / TUIC)
      → Exit → Internet

Panel PasarGuard: Exit only, typically 127.0.0.1:8000
Exit nginx TLS :2096 for panel UI; public :443 often nginx stream ssl_preread
Iran control: iran-sync-export (Exit) + iran-sync-apply (Iran) — not native panel Enable
Extras in THIS stack (restore them): settle-web /settle/, ig-mult-web /ig/, path-web /path/ (vpn-path UI), instagram-multiplier, sni-watch /watch/, vpn-backup timer
```

---

## Phase 0 — decrypt & inventory

On a trusted machine (preferably the new Exit once SSH works):

1. Install `gpg tar curl`.
2. Decrypt with `BACKUP_PASSPHRASE` (env only — never `echo` into logs).
3. `tar -tzf stack.tgz | head -100` and confirm:
   - `exit/root/vpn-infra/`
   - `exit/root/.vpn-secrets/`
   - `exit/root/.ssh/` (keys; if missing in older backups, operator must supply Iran SSH key separately)
   - `exit/root/.pg_nodes/{exit,iran,certs}/`
   - `exit/pasarguard.sqlite3`
   - `exit/etc/nginx`, `exit/systemd/`, `exit/var/lib/settle-web/` (newer backups)
   - `iran/iran-fs.tgz` or `iran/FAILED.txt`
4. Read `meta/README.txt` and `meta/RESTORE.txt`.
5. If `IPS_CHANGED=yes`, plan a global replace of `OLD_*_IP` → new IPs after file copy (nft, xray JSON, nginx, `.env`, systemd, scripts).

Do not proceed until archive lists cleanly.

---

## Phase 1 — bare OS packages

### Exit

Install at least:

- `docker.io` or Docker CE + compose plugin
- `nginx`, `nftables`, `curl`, `jq`, `python3`, `sqlite3`, `gpg`, `rsync`, `openssh-client`
- whatever the live Exit Xray backhaul needs (binary often under `/root/.pg_nodes/` or system path — restore from archive / reinstall xray-core if binary missing; archive may omit heavy `bin/`)

Enable IP forwarding if previously used. Do not start conflicting services on `:443` before nft/nginx/xray layout is restored.

### Iran

Install:

- Docker (`pasarguard/node` image will be pulled)
- `nginx`, `nftables`, `curl`, `python3`, `gpg`
- Do **not** bind nginx to `:443` (Reality owns it)

---

## Phase 2 — restore Exit filesystem

From extracted `exit/`:

```bash
# paths (adjust if extract dir differs)
E=./exit

install -d -m 700 /root/.vpn-secrets /root/.ssh /root/.pg_nodes
cp -a "$E/root/vpn-infra" /root/
cp -a "$E/root/.vpn-secrets/." /root/.vpn-secrets/
chmod 700 /root/.vpn-secrets
chmod 600 /root/.vpn-secrets/* 2>/dev/null || true

# SSH keys to Iran
if [ -d "$E/root/.ssh" ]; then
  cp -a "$E/root/.ssh/." /root/.ssh/
  chmod 700 /root/.ssh
  chmod 600 /root/.ssh/id_* 2>/dev/null || true
  chmod 644 /root/.ssh/*.pub /root/.ssh/known_hosts 2>/dev/null || true
fi

cp -a "$E/root/.pg_nodes/." /root/.pg_nodes/
# optional: restore settle DB, monitor, webs
[ -d "$E/etc/vpn-monitor" ] && cp -a "$E/etc/vpn-monitor" /etc/
[ -d "$E/etc/settle-web" ] && cp -a "$E/etc/settle-web" /etc/
[ -d "$E/etc/ig-mult-web" ] && cp -a "$E/etc/ig-mult-web" /etc/
[ -d "$E/var/lib/settle-web" ] && cp -a "$E/var/lib/settle-web" /var/lib/
[ -d "$E/etc/nginx" ] && cp -a "$E/etc/nginx/." /etc/nginx/
[ -f "$E/etc/nftables.conf" ] && cp -a "$E/etc/nftables.conf" /etc/nftables.conf
[ -d "$E/etc/nftables" ] && cp -a "$E/etc/nftables" /etc/
[ -d "$E/etc/letsencrypt" ] && cp -a "$E/etc/letsencrypt" /etc/
[ -d "$E/opt/pasarguard" ] && mkdir -p /opt/pasarguard && cp -a "$E/opt/pasarguard/." /opt/pasarguard/

cp -a "$E/systemd/"*.service "$E/systemd/"*.timer /etc/systemd/system/ 2>/dev/null || true
cp -a "$E/usr-local-sbin/." /usr/local/sbin/ 2>/dev/null || true
[ -d "$E/usr-local-lib" ] && cp -a "$E/usr-local-lib/." /usr/local/lib/

systemctl daemon-reload
```

Ensure `/root/.vpn-secrets/.env` contains at least (values already in restored file — do not reprint):

- `BACKUP_PASSPHRASE`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- `PG_API_KEY`, Cloudflare vars if used
- `BACKUP_IRAN_HOST=root@$IRAN_IP` if IP changed

If `IPS_CHANGED=yes`, rewrite old IPs in:

- `/root/.vpn-secrets/.env`
- `/root/.pg_nodes/exit/**`, `/root/.pg_nodes/iran/**`
- `/etc/nftables.conf`, nginx confs
- systemd units and `/root/vpn-infra` scripts that hardcode IPs
- `BACKUP_IRAN_HOST`

Test: `ssh -o BatchMode=yes -o ConnectTimeout=10 root@$IRAN_IP true`

---

## Phase 3 — PasarGuard panel + DB

The panel is a plain `docker run` container (no compose), created only by
`/root/vpn-infra/scripts/pasarguard-run.sh`. It builds `pasarguard-local:<version>` from
`configs/pasarguard/Dockerfile` (upstream image + node-bridge HTTP/1.1 patch), and runs it with
`--network host`, `-v /var/lib/pasarguard:/var/lib/pasarguard`, `-v /root/.pg_nodes/certs:...:ro`,
`SQLALCHEMY_DATABASE_URL=sqlite+aiosqlite:////var/lib/pasarguard/db.sqlite3`.
All Exit scripts read the DB at `/var/lib/pasarguard/db.sqlite3` (via `docker exec pasarguard`).

1. Restore the DB onto the host path **before** first start (no container exists yet):

```bash
install -d /var/lib/pasarguard
rm -f /var/lib/pasarguard/db.sqlite3-wal /var/lib/pasarguard/db.sqlite3-shm
cp -a "$E/pasarguard.sqlite3" /var/lib/pasarguard/db.sqlite3
# also restore other state files from the archive if present (panel-api-key, iran-sync/, bootstrap-ids.json)
```

2. Start the panel (pulls + builds + runs; alembic migrates the DB to the image version):

```bash
/root/vpn-infra/scripts/pasarguard-run.sh v5.4.1   # or the newest tag you trust
```

   The script's health check needs `/root/.vpn-secrets/.env` (`PANEL_API_KEY`, `PG_CORE_ID`) already restored.

3. Confirm UI on Exit `https://127.0.0.1:2096` (via nginx) or local `:8000` after nginx is up.
4. **Do not** Enable the Iran node row.
5. `vpn-path status` must print the selector (proves API key + core id).

If `exit/PANEL_DB_MISSING.txt` exists in the archive, stop and ask the operator for an older backup — do not start with an empty panel.

Future upgrades: `pasarguard-run.sh vX.Y.Z` (keeps `pasarguard-old-<stamp>` stopped for rollback; DB backup in `/var/lib/pasarguard/pre-upgrade/`). Stop `iran-sync-export.timer iran-stats.timer vpn-failover.timer sni-watch-resolve.timer` during the swap, then start them and compare `/var/lib/pasarguard/iran-sync/state.sha256` before/after.

---

## Phase 4 — Exit data plane + timers

1. Restore/start Exit Xray backhaul (config under `.pg_nodes/exit/` — not the panel iran-xray core).
2. `nft -f /etc/nftables.conf` or `systemctl enable --now nftables`.
3. `nginx -t && systemctl enable --now nginx`.
4. Enable timers/services that exist:

```bash
systemctl enable --now iran-sync-export.timer iran-stats.timer
systemctl enable --now vpn-backup.timer vpn-health.timer vpn-failover.timer
systemctl enable --now settle-web.service ig-mult-web.service path-web.service
systemctl enable --now sni-watch-tunnel.service sni-watch-resolve.timer
# monitor timers if present
systemctl enable --now vpn-mon-boot.service 2>/dev/null || true
```

5. CLIs: `/usr/local/sbin/vpn-path`, `instagram-multiplier`, `sni-watch` must be executable.
6. DNS: point `PANEL_*`, `CDN_HOST`, `XHTTP_HOST` A/AAAA (and CF orange/grey as before) to `EXIT_IP` / `IRAN_IP`.

---

## Phase 5 — restore Iran

If `RESTORE_IRAN=yes` and `iran/iran-fs.tgz` exists:

```bash
# from machine that can SSH as root to Iran, or on Iran itself:
scp iran/iran-fs.tgz root@$IRAN_IP:/tmp/
ssh root@$IRAN_IP 'tar -xzf /tmp/iran-fs.tgz -C /'
```

Archive layout is paths relative to `/` (e.g. `etc/nginx`, `var/lib/pg-node`, `usr/local/lib/sni-watch`, plus a temp `…/systemd` tree). After extract:

1. Find restored unit files (often under a `tmp/.../systemd` path inside the tarball — copy any `*.service`/`*.timer` found into `/etc/systemd/system/`).
2. `systemctl daemon-reload`
3. Start the node with `/usr/local/sbin/pg-node-run.sh v0.5.4` (copy from `/root/vpn-infra/scripts/pg-node-run.sh`). Do **not** use `/opt/pg-node/docker-compose.yml` — it lacks the certs and `/var/log/xray` mounts. On a bare host the script needs `/opt/pg-node/node.env` (mode 600; keys `SERVICE_PORT NODE_HOST SERVICE_PROTOCOL API_KEY SSL_CERT_FILE SSL_KEY_FILE GENERATED_CONFIG_PATH DEBUG`), restored from the archive or rebuilt from `/opt/pg-node/.env`. The script re-applies the sni-watch Xray wrap and triggers `iran_sync_apply`.
4. Apply nftables; open TCP `22,443,2053,8443,2096` and UDP `443`; API `62050/62051` **only from EXIT_IP**.
5. Enable: `sni-watch`, `iran-sync-apply` (timer/service), `sni-xray-wrap` if present, nginx for panel proxy /watch if used.
6. If IP changed: Reality/shortIds stay; update any Exit allow-lists and DNS grey records for `IR_HOST` / `PANEL_IR`.

If `iran/FAILED.txt` only: rebuild Iran from `docs/friend-deploy/` using restored Exit `.pg_nodes/iran/*` as source of truth, then re-enable sync.

---

## Phase 6 — verify (must all pass)

```bash
# Exit
vpn-path status
systemctl is-active nginx iran-sync-export.timer vpn-backup.timer settle-web ig-mult-web
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/ || true
ssh -o BatchMode=yes root@$IRAN_IP 'ss -lntp | grep -E ":443|:2053|:62050" || true'

# sync hash moving?
ls -la /var/lib/pasarguard/iran-sync/ 2>/dev/null | tail
ssh root@$IRAN_IP 'ls -la /var/lib/pg-node/sync/ 2>/dev/null | tail'

# backup still works
/root/vpn-infra/scripts/backup-stack.sh   # should Telegram OK; do not print passphrase
```

Human: one real VLESS client through Iran → internet. Panel users/traffic should match pre-wipe DB.

Optional: `/settle/`, `/ig/`, `/watch/` via panel nginx paths.

---

## Phase 7 — operator checklist after Cursor finishes

- [ ] `BACKUP_PASSPHRASE` still only in password manager + `/root/.vpn-secrets/.env`
- [ ] Fresh `vpn-stack-*.tar.gz.gpg` arrived in Telegram
- [ ] Iran node still **disabled** in panel
- [ ] DNS TTL settled; CF orange hosts healthy
- [ ] Old VPS destroyed only after client test OK

---

## Out of scope / do not do

- Do not Enable Iran node “to simplify”
- Do not rebuild Instagram multiplier / sni-watch from scratch if files exist in archive
- Do not force-push or commit secrets
- Do not use the friend-deploy prompt alone — that is greenfield; **this** prompt is restore-from-backup

If something in the archive is missing (old backup before settle/ssh inclusion), say what failed, restore what exists, and ask the operator for the missing piece (SSH key or settle.db) instead of inventing state.
