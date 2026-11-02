#!/bin/bash
# Per-host encrypted backup -> Telegram (kit component, works on Iran / Exit / Master).
# Config (root-only, mode 600): /root/.vpn-secrets/.env
#   TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, BACKUP_GPG_PASS   (required)
#   BACKUP_LABEL        host label in file name / caption (default: hostname)
#   BACKUP_PATHS        space-separated files/dirs to include
#   BACKUP_EXCLUDES     space-separated tar --exclude patterns
#   BACKUP_PG_CONTAINER optional: postgres container for a read-only pg_dump (uses DB_USER/DB_NAME
#                       from BACKUP_PG_ENVFILE, default /opt/pasarguard/.env)
#   BACKUP_TG_PROXY     optional proxy for Telegram (e.g. socks5h://127.0.0.1:11080 on an Iran node where
#                       api.telegram.org is filtered); direct is tried first, then this proxy
#   BACKUP_RETENTION_DAYS  delete local RoOtIt-*.tar.gz.gpg* archives in /root/RoOtIt-backups older than N days (default 14; 0 = keep all)
#   BACKUP_KEEP_LOCAL   optional: prune local archives beyond N newest (unset = keep all, nothing deleted)
# Nothing is restarted. Secrets only ever exist inside the GPG archive.
set -euo pipefail
umask 077
ENVF=/root/.vpn-secrets/.env
set -a; . "$ENVF"; set +a
: "${TELEGRAM_BOT_TOKEN:?}"; : "${TELEGRAM_CHAT_ID:?}"; : "${BACKUP_GPG_PASS:?}"
LABEL="${BACKUP_LABEL:-$(hostname -s)}"
STAMP=$(date +%Y%m%d-%H%M)
DEST=/root/RoOtIt-backups; mkdir -p "$DEST"; chmod 700 "$DEST"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
STAGE="$TMP/$LABEL"; mkdir -p "$STAGE"
log(){ echo "[RoOtIt-backup] $*" >&2; }

if [ -n "${BACKUP_PG_CONTAINER:-}" ]; then
  PGENV="${BACKUP_PG_ENVFILE:-/opt/pasarguard/.env}"
  DBU=$(grep -E '^DB_USER=' "$PGENV" | cut -d= -f2- | tr -d '"'"'")
  DBN=$(grep -E '^DB_NAME=' "$PGENV" | cut -d= -f2- | tr -d '"'"'")
  log "pg_dump (read-only) $BACKUP_PG_CONTAINER/$DBN"
  docker exec "$BACKUP_PG_CONTAINER" pg_dump -U "$DBU" -d "$DBN" -Fc > "$STAGE/pasarguard-db.dump" 2>"$TMP/pgdump.err" \
    || { log "pg_dump failed: $(tail -2 "$TMP/pgdump.err")"; rm -f "$STAGE/pasarguard-db.dump"; echo "pg_dump FAILED" > "$STAGE/PG_DUMP_FAILED"; }
fi

EXCL=(--exclude='__pycache__' --exclude='*.log')
for e in ${BACKUP_EXCLUDES:-}; do EXCL+=(--exclude="$e"); done
INC=()
for p in ${BACKUP_PATHS:-}; do [ -e "$p" ] && INC+=("$p"); done
{ echo "label=$LABEL"; echo "date=$(date -Is)"; echo "host=$(hostname)"; printf 'path=%s\n' "${INC[@]}"; } > "$STAGE/MANIFEST.txt"
systemctl list-units --no-pager --plain --type=service --state=running > "$STAGE/running-services.txt" 2>/dev/null || true
crontab -l > "$STAGE/crontab.txt" 2>/dev/null || true

OUT="$DEST/RoOtIt-$LABEL-$STAMP.tar.gz.gpg"
tar -czf - "${EXCL[@]}" -C / "${INC[@]/#\//}" -C "$TMP" "$LABEL" 2>"$TMP/tar.err" \
 | gpg --batch --yes --pinentry-mode loopback --passphrase-fd 3 --symmetric --cipher-algo AES256 -o "$OUT" 3<<<"$BACKUP_GPG_PASS"
chmod 600 "$OUT"
SIZE=$(stat -c %s "$OUT"); SHA=$(sha256sum "$OUT" | cut -c1-16)
log "archive $(basename "$OUT") $SIZE bytes"

# Telegram bot upload limit is 50 MB -> split at 45 MB
PARTS=("$OUT")
if [ "$SIZE" -gt $((45*1024*1024)) ]; then
  split -b 45M -d -a 2 "$OUT" "$TMP/$(basename "$OUT").part"
  PARTS=("$TMP/$(basename "$OUT").part"*)
fi
n=0; FAIL=0
for f in "${PARTS[@]}"; do
  n=$((n+1))
  CAP="🗄 RoOtIt backup | $LABEL | $(date '+%Y-%m-%d %H:%M %Z') | part $n/${#PARTS[@]} | $((SIZE/1024)) KB | sha256:$SHA"
  R=""
  for px in "" ${BACKUP_TG_PROXY:-}; do
    R=$(curl -sS --max-time 300 ${px:+-x "$px"} -F chat_id="$TELEGRAM_CHAT_ID" -F caption="$CAP" -F document=@"$f" \
        "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendDocument" 2>/dev/null || true)
    echo "$R" | grep -q '"ok":true' && break
  done
  if echo "$R" | grep -q '"ok":true'; then log "sent part $n ok:true"; else log "send part $n FAILED: $(echo "$R" | head -c 200)"; FAIL=1; fi
done
if [ -n "${BACKUP_KEEP_LOCAL:-}" ]; then KEEP=$BACKUP_KEEP_LOCAL
ls -1t "$DEST"/RoOtIt-"$LABEL"-*.gpg 2>/dev/null | tail -n +$((KEEP+1)) | xargs -r rm -f
fi
RD="${BACKUP_RETENTION_DAYS:-14}"
if [ "$RD" -gt 0 ] 2>/dev/null; then
  find "$DEST" -maxdepth 1 -type f -name 'RoOtIt-*.tar.gz.gpg*' -mtime +"$RD" -print -delete | sed 's/^/[RoOtIt-backup] retention removed: /' >&2 || true
fi
exit $FAIL
