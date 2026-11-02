#!/bin/bash
# Full stack backup (Exit + Iran) → GPG → optional Telegram.
# Secrets stay inside the encrypted archive only.
set -euo pipefail

# shellcheck disable=SC1091
set -a
# shellcheck source=/dev/null
. /root/.vpn-secrets/.env
set +a

: "${BACKUP_PASSPHRASE:?BACKUP_PASSPHRASE missing in .env}"

IRAN_HOST="${BACKUP_IRAN_HOST:-root@${IRAN_IP}}"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DEST=/root/.pg_nodes/backups
mkdir -p "$DEST"
chmod 700 "$DEST"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
STAGE="$TMP/stack"
mkdir -p "$STAGE/exit" "$STAGE/iran" "$STAGE/meta"

log() { echo "[backup] $*" >&2; }

copy_tree() {
  local src=$1 dst=$2
  if [ -e "$src" ]; then
    mkdir -p "$(dirname "$dst")"
    cp -a "$src" "$dst"
  fi
}

# --- Exit ---
log "collect Exit…"
mkdir -p "$STAGE/exit/root" "$STAGE/exit/etc" "$STAGE/exit/opt" "$STAGE/exit/systemd" "$STAGE/exit/usr-local-sbin"

copy_tree /root/vpn-infra "$STAGE/exit/root/vpn-infra"
find "$STAGE/exit/root/vpn-infra" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true

copy_tree /root/.vpn-secrets "$STAGE/exit/root/.vpn-secrets"

# SSH keys (needed to reach Iran after Exit wipe) — stay inside GPG only
if [ -d /root/.ssh ]; then
  mkdir -p "$STAGE/exit/root/.ssh"
  # private/public keys + config; skip sockets / agent
  find /root/.ssh -maxdepth 1 -type f ! -name 'authorized_keys' \
    -exec cp -a {} "$STAGE/exit/root/.ssh/" \; 2>/dev/null || true
  chmod 700 "$STAGE/exit/root/.ssh"
  chmod 600 "$STAGE/exit/root/.ssh/"* 2>/dev/null || true
fi

# pg_nodes without heavy binaries and without nested backup history
mkdir -p "$STAGE/exit/root/.pg_nodes"
for d in exit iran certs test-subs; do
  copy_tree "/root/.pg_nodes/$d" "$STAGE/exit/root/.pg_nodes/$d"
done
# keep a MANIFEST note; do not embed old .gpg backups (circular / large)

copy_tree /etc/vpn-monitor "$STAGE/exit/etc/vpn-monitor"
copy_tree /etc/settle-web "$STAGE/exit/etc/settle-web"
copy_tree /etc/ig-mult-web "$STAGE/exit/etc/ig-mult-web"
copy_tree /var/lib/settle-web "$STAGE/exit/var/lib/settle-web"
copy_tree /etc/nginx "$STAGE/exit/etc/nginx"
copy_tree /etc/nftables.conf "$STAGE/exit/etc/nftables.conf"
[ -d /etc/nftables ] && copy_tree /etc/nftables "$STAGE/exit/etc/nftables"
[ -d /etc/nftables.d ] && copy_tree /etc/nftables.d "$STAGE/exit/etc/nftables.d"
# TLS certs used by nginx / panel (if present)
[ -d /etc/letsencrypt ] && copy_tree /etc/letsencrypt "$STAGE/exit/etc/letsencrypt"
[ -d /etc/ssl/vpn ] && copy_tree /etc/ssl/vpn "$STAGE/exit/etc/ssl/vpn"

if [ -d /opt/pasarguard ]; then
  mkdir -p "$STAGE/exit/opt/pasarguard"
  # compose + env + custom entrypoint; skip bulky image layers (docker handles images)
  for f in docker-compose.yml compose.yml .env; do
    copy_tree "/opt/pasarguard/$f" "$STAGE/exit/opt/pasarguard/$f"
  done
  copy_tree /opt/pasarguard/bin "$STAGE/exit/opt/pasarguard/bin"
fi

# SQLite online backup (includes pages still in the -wal file; plain cp does not).
# Runs inside the container so it works whatever SQLALCHEMY_DATABASE_URL points at.
PG_SNAP=/var/lib/pasarguard/.backup-snapshot.sqlite3
rm -f "$PG_SNAP"
if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx pasarguard; then
  docker exec -i pasarguard python - <<'PY' || log "WARN: panel DB online backup failed"
import os, re, sqlite3
url = os.environ.get("SQLALCHEMY_DATABASE_URL") or "sqlite+aiosqlite:///db.sqlite3"
m = re.match(r"sqlite(?:\+\w+)?:///(.+)$", url)
src_path = m.group(1) if m else "db.sqlite3"
src = sqlite3.connect(src_path if src_path.startswith("/") else "/code/" + src_path, timeout=30)
dst = sqlite3.connect("/var/lib/pasarguard/.backup-snapshot.sqlite3")
src.backup(dst)
dst.close()
src.close()
PY
fi
if [ -s "$PG_SNAP" ]; then
  mv "$PG_SNAP" "$STAGE/exit/pasarguard.sqlite3"
  log "panel DB users=$(python3 -c "import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute('select count(*) from users').fetchone()[0])" "$STAGE/exit/pasarguard.sqlite3")"
else
  log "ERROR: panel DB snapshot missing — archive has NO panel DB"
  echo "panel_db=missing" >"$STAGE/exit/PANEL_DB_MISSING.txt"
fi

# small panel-side state (api key, sync hash, path mode); DB handled above
mkdir -p "$STAGE/exit/var/lib/pasarguard"
for f in panel-api-key bootstrap-ids.json vpn-path-mode.json failover-state.json; do
  copy_tree "/var/lib/pasarguard/$f" "$STAGE/exit/var/lib/pasarguard/$f"
done
copy_tree /var/lib/pasarguard/iran-sync "$STAGE/exit/var/lib/pasarguard/iran-sync"

# systemd units we care about
shopt -s nullglob
for u in /etc/systemd/system/vpn-* \
         /etc/systemd/system/iran-* \
         /etc/systemd/system/settle-web.service \
         /etc/systemd/system/ig-mult-web.service \
         /etc/systemd/system/path-web.service \
         /etc/systemd/system/pasarguard.service \
         /etc/systemd/system/sni-watch-*.service \
         /etc/systemd/system/sni-watch-*.timer; do
  [ -e "$u" ] || continue
  cp -a "$u" "$STAGE/exit/systemd/"
done
shopt -u nullglob

# installed CLIs
for b in vpn-path instagram-multiplier sni-watch; do
  [ -e "/usr/local/sbin/$b" ] && cp -a "/usr/local/sbin/$b" "$STAGE/exit/usr-local-sbin/"
done
copy_tree /usr/local/lib/settle-web "$STAGE/exit/usr-local-lib/settle-web"
copy_tree /usr/local/lib/ig-mult-web "$STAGE/exit/usr-local-lib/ig-mult-web"
copy_tree /usr/local/lib/path-web "$STAGE/exit/usr-local-lib/path-web"
copy_tree /etc/path-web "$STAGE/exit/etc/path-web"

# --- Iran (via SSH) ---
log "collect Iran from $IRAN_HOST…"
IRAN_LIST=$(mktemp)
cat >"$IRAN_LIST" <<'EOF'
etc/sni-watch
var/lib/sni-watch
usr/local/lib/sni-watch
usr/local/sbin/sni-watch
etc/nginx
etc/nftables.conf
var/lib/pg-node
root/.pg_nodes/certs
root/.pg_nodes/iran
EOF

# Build a remote tar of existing paths only (skip missing / skip bin)
set +e
ssh -o BatchMode=yes -o ConnectTimeout=20 "$IRAN_HOST" bash -s <<'REMOTE' >"$STAGE/iran/iran-fs.tgz"
set -euo pipefail
paths=()
add() { [ -e "$1" ] && paths+=("$1"); }
add /etc/sni-watch
add /opt/pg-node
add /usr/local/sbin/pg-node-run.sh
add /usr/local/sbin/ensure_xray_wrap.sh
add /usr/local/sbin/iran_sync_apply.py
add /var/lib/sni-watch
add /usr/local/lib/sni-watch
add /usr/local/sbin/sni-watch
add /etc/nginx
add /etc/nftables.conf
add /var/lib/pg-node
add /root/.pg_nodes/certs
add /root/.pg_nodes/iran
# systemd units
tmpdir=$(mktemp -d)
mkdir -p "$tmpdir/systemd"
cp -a /etc/systemd/system/sni-watch.service "$tmpdir/systemd/" 2>/dev/null || true
cp -a /etc/systemd/system/sni-xray-wrap.* "$tmpdir/systemd/" 2>/dev/null || true
cp -a /etc/systemd/system/iran-sync-apply.* "$tmpdir/systemd/" 2>/dev/null || true
cp -a /etc/systemd/system/xray-subproxy.service "$tmpdir/systemd/" 2>/dev/null || true
paths+=("$tmpdir/systemd")
if [ "${#paths[@]}" -eq 0 ]; then
  echo "NO_IRAN_PATHS" >&2
  exit 1
fi
tar -czf - --warning=no-file-changed -C / "${paths[@]#/}" 2>/dev/null || tar -czf - -C / "${paths[@]#/}"
REMOTE
iran_rc=$?
set -e
rm -f "$IRAN_LIST"
if [ "$iran_rc" -ne 0 ] || [ ! -s "$STAGE/iran/iran-fs.tgz" ]; then
  log "WARN: Iran collect failed (rc=$iran_rc) — Exit-only archive will still be built"
  echo "iran_collect=failed rc=$iran_rc" >"$STAGE/iran/FAILED.txt"
  rm -f "$STAGE/iran/iran-fs.tgz"
else
  log "Iran archive $(du -h "$STAGE/iran/iran-fs.tgz" | awk '{print $1}')"
fi

# --- meta ---
{
  echo "stamp=$STAMP"
  echo "exit_host=$(hostname -f 2>/dev/null || hostname)"
  echo "exit_ip=$(curl -4 -s --max-time 5 ifconfig.me 2>/dev/null || true)"
  echo "iran_host=$IRAN_HOST"
  echo "created_utc=$(date -u -Iseconds)"
  echo "contents=exit_scripts_secrets_panel_db_nginx_nft_systemd + iran_sni_pgnode_nginx"
} >"$STAGE/meta/README.txt"

cat >"$STAGE/meta/RESTORE.txt" <<'EOF'
RESTORE (high level)
====================
Full Cursor prompt: docs/RESTORE-CURSOR-PROMPT.md inside vpn-infra (also in this
archive under exit/root/vpn-infra/docs/ after decrypt).

BACKUP_PASSPHRASE is NEVER inside Telegram captions. It lives only in
  /root/.vpn-secrets/.env
Keep a copy in a password manager offline.

1) Decrypt on a trusted machine:
     gpg -d vpn-stack-YYYYMMDD….tar.gz.gpg > stack.tgz
     tar -xzf stack.tgz

2) Exit (new VPS) — see RESTORE-CURSOR-PROMPT.md
3) Iran (new VPS) — extract iran/iran-fs.tgz
4) DNS + vpn-path status + real client test

NOT a disk image. Install docker/nginx/nftables on bare OS first.
EOF

# --- pack + encrypt ---
log "tar + gpg…"
set +e
tar -C "$STAGE" --warning=no-file-changed -czf "$TMP/stack.tgz" .
tar_rc=$?
set -e
if [ "$tar_rc" -gt 1 ] || [ ! -s "$TMP/stack.tgz" ]; then
  echo "TAR_FAIL $tar_rc" >&2
  exit 1
fi

OUT="$DEST/vpn-stack-${STAMP}.tar.gz.gpg"
gpg --batch --yes --passphrase "$BACKUP_PASSPHRASE" --symmetric --cipher-algo AES256 \
  -o "$OUT" "$TMP/stack.tgz"
chmod 600 "$OUT"
SIZE_B=$(stat -c%s "$OUT")
SIZE_H=$(du -h "$OUT" | awk '{print $1}')
log "wrote $OUT ($SIZE_H)"

# retain local copies 14 days
find "$DEST" -name 'vpn-stack-*.tar.gz.gpg' -mtime +14 -delete
find "$DEST" -name 'vpn-*.tar.gz.gpg' ! -name 'vpn-stack-*.tar.gz.gpg' -mtime +7 -delete

# --- Telegram ---
send_telegram() {
  local file=$1
  local caption=$2
  if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
    log "Telegram skipped (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set)"
    return 0
  fi
  # Bot API limit ~50 MiB
  if [ "$SIZE_B" -gt $((49 * 1024 * 1024)) ]; then
    log "ERROR: archive larger than Telegram bot limit ($SIZE_H)"
    curl -sS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
      --data-urlencode "text=VPN backup TOO LARGE for Telegram ($SIZE_H). File left on Exit: $file" \
      >/dev/null || true
    return 1
  fi
  log "upload Telegram…"
  local resp
  resp=$(curl -sS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendDocument" \
    -F "chat_id=${TELEGRAM_CHAT_ID}" \
    -F "document=@${file}" \
    -F "caption=${caption}")
  if echo "$resp" | grep -q '"ok":true'; then
    log "Telegram OK"
    return 0
  fi
  log "Telegram FAIL: $(echo "$resp" | head -c 400)"
  return 1
}

CAPTION="VPN stack backup ${STAMP}
Exit+Iran encrypted (GPG)
size ${SIZE_H}
Keep BACKUP_PASSPHRASE offline."

TG_RC=0
send_telegram "$OUT" "$CAPTION" || TG_RC=$?

echo "BACKUP_OK stamp=$STAMP file=$OUT size=$SIZE_H telegram=$TG_RC"
exit 0
