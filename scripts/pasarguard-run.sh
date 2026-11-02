#!/bin/bash
# Build and (re)create the PasarGuard panel container on Exit.
# Live DB is on the host bind mount, so recreating the container never loses data.
#
# Usage: pasarguard-run.sh [VERSION]     e.g. pasarguard-run.sh v5.4.1
#
# Before swapping: online DB backup to /var/lib/pasarguard/pre-upgrade/.
# Old container is kept stopped as pasarguard-old-<stamp> for rollback.
set -euo pipefail

VERSION="${1:-v5.4.1}"
NAME=pasarguard
DATA=/var/lib/pasarguard
DB=$DATA/db.sqlite3
CERTS=/root/.pg_nodes/certs
IMAGE="pasarguard-local:$VERSION"
DOCKERFILE_DIR=/root/vpn-infra/configs/pasarguard
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
PRE=$DATA/pre-upgrade

log() { echo "[pasarguard] $*" >&2; }

sqlite_copy() {
	python3 - "$1" "$2" <<'PY'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1], timeout=30)
res = src.execute("pragma integrity_check").fetchone()[0]
if res != "ok":
    raise SystemExit("integrity_check failed: " + res)
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close()
src.close()
PY
}

wait_healthy() {
	local i code
	for i in $(seq 1 90); do
		code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/ || true)
		if [[ "$code" =~ ^[234] ]]; then
			python3 /root/vpn-infra/scripts/vpn-path-core.py status >/dev/null 2>&1 && return 0
		fi
		sleep 2
	done
	return 1
}

log "pull pasarguard/panel:$VERSION"
docker pull -q "pasarguard/panel:$VERSION" >/dev/null
log "build $IMAGE"
docker build -q --build-arg "PG_VERSION=$VERSION" -t "$IMAGE" "$DOCKERFILE_DIR" >/dev/null

install -d -m 700 "$PRE"
OLD=""
LEGACY=0
BACKUP=""
if docker inspect "$NAME" >/dev/null 2>&1; then
	url=$(docker inspect "$NAME" --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^SQLALCHEMY_DATABASE_URL=//p')
	old_ver=$(docker exec "$NAME" sh -c 'grep -m1 -E "^version" /code/pyproject.toml' 2>/dev/null | cut -d'"' -f2 || true)
	log "current container version=${old_ver:-unknown}"
	log "stop $NAME"
	docker stop -t 30 "$NAME" >/dev/null
	if [[ -z "$url" ]]; then
		# Legacy layout: DB inside the container layer at /code/db.sqlite3.
		LEGACY=1
		tmp=$PRE/legacy-$STAMP
		mkdir -p "$tmp"
		docker cp "$NAME:/code/db.sqlite3" "$tmp/db.sqlite3"
		docker cp "$NAME:/code/db.sqlite3-wal" "$tmp/db.sqlite3-wal" 2>/dev/null || true
		docker cp "$NAME:/code/db.sqlite3-shm" "$tmp/db.sqlite3-shm" 2>/dev/null || true
		sqlite_copy "$tmp/db.sqlite3" "$DB.new"
		[[ -f "$DB" ]] && mv "$DB" "$PRE/stale-host-db-$STAMP.sqlite3"
		rm -f "$DB-wal" "$DB-shm"
		mv "$DB.new" "$DB"
		log "migrated legacy /code DB → $DB (raw copy in $tmp)"
	else
		BACKUP=$PRE/db-${old_ver:-old}-$STAMP.sqlite3
		sqlite_copy "$DB" "$BACKUP"
		log "backup $BACKUP"
	fi
	OLD="$NAME-old-$STAMP"
	docker rename "$NAME" "$OLD"
fi

log "run $IMAGE"
docker run -d --name "$NAME" \
	--network host \
	--restart unless-stopped \
	-v "$DATA:$DATA" \
	-v "$CERTS:$CERTS:ro" \
	-e UVICORN_HOST=127.0.0.1 \
	-e UVICORN_PORT=8000 \
	-e "SQLALCHEMY_DATABASE_URL=sqlite+aiosqlite:///$DB" \
	"$IMAGE" >/dev/null

if wait_healthy; then
	log "OK $NAME $VERSION healthy (panel HTTP + API key)"
	[[ -n "$OLD" ]] && log "old container kept stopped: $OLD (docker rm $OLD when satisfied)"
	exit 0
fi

log "ERROR: new container not healthy; last logs:"
docker logs --tail 40 "$NAME" >&2 || true
if [[ -n "$OLD" ]]; then
	log "rollback → $OLD"
	docker rm -f "$NAME" >/dev/null
	if [[ "$LEGACY" -eq 0 && -n "$BACKUP" ]]; then
		rm -f "$DB-wal" "$DB-shm"
		cp -a "$BACKUP" "$DB"
	fi
	docker rename "$OLD" "$NAME"
	docker start "$NAME" >/dev/null
fi
exit 1
