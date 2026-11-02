#!/bin/bash
# Run ON IRAN. Recreate the PasarGuard node container with the live flags
# (the old /opt/pg-node/docker-compose.yml does NOT match production — do not use it).
#
# Usage: pg-node-run.sh vX.Y.Z
#
# Downtime: Xray restarts (~10-20 s). Old container kept stopped as node-old-<stamp>.
set -euo pipefail

VERSION="${1:?usage: pg-node-run.sh vX.Y.Z}"
NAME=node
ENVF=/opt/pg-node/node.env
IMAGE="pasarguard/node:$VERSION"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)

log() { echo "[pg-node] $*" >&2; }

wait_port() {
	local port=$1 secs=$2 i
	for i in $(seq 1 "$secs"); do
		ss -lnt "sport = :$port" | grep -q LISTEN && return 0
		sleep 1
	done
	return 1
}

log "pull $IMAGE"
docker pull -q "$IMAGE" >/dev/null

install -d -m 700 /opt/pg-node
if docker inspect "$NAME" >/dev/null 2>&1; then
	umask 077
	docker inspect "$NAME" --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -v -E '^(PATH=|$)' >"$ENVF.new"
	mv "$ENVF.new" "$ENVF"
	chmod 600 "$ENVF"
fi
if [[ ! -s "$ENVF" ]]; then
	log "ERROR: $ENVF missing and no running container to copy env from"
	exit 2
fi

systemctl stop iran-sync-apply.timer
trap 'systemctl start iran-sync-apply.timer' EXIT

OLD=""
if docker inspect "$NAME" >/dev/null 2>&1; then
	OLD="$NAME-old-$STAMP"
	log "stop $NAME → $OLD"
	docker stop -t 10 "$NAME" >/dev/null
	docker rename "$NAME" "$OLD"
fi

log "run $IMAGE"
docker run -d --name "$NAME" \
	--network host \
	--restart unless-stopped \
	--cap-add NET_ADMIN \
	--env-file "$ENVF" \
	-v /root/.pg_nodes/certs:/root/.pg_nodes/certs:ro \
	-v /var/lib/pg-node:/var/lib/pg-node \
	-v /var/log/xray:/var/log/xray \
	"$IMAGE" >/dev/null

ok=0
if wait_port 62050 60; then
	# Wraps xray for sni-watch, then iran_sync_apply POSTs /start (ports are down).
	/bin/sh /usr/local/sbin/ensure_xray_wrap.sh || true
	if wait_port 443 60 && wait_port 2053 30; then
		ok=1
	fi
fi

if [[ "$ok" -eq 1 ]]; then
	log "OK $NAME $VERSION — :443 :2053 listening; $(docker exec "$NAME" /usr/local/bin/xray.real version 2>/dev/null | head -1)"
	[[ -n "$OLD" ]] && log "old container kept stopped: $OLD (docker rm $OLD when satisfied)"
	exit 0
fi

log "ERROR: new node not serving; last logs:"
docker logs --tail 30 "$NAME" >&2 || true
if [[ -n "$OLD" ]]; then
	log "rollback → $OLD"
	docker rm -f "$NAME" >/dev/null
	docker rename "$OLD" "$NAME"
	docker start "$NAME" >/dev/null
	wait_port 62050 60 || true
	python3 /usr/local/sbin/iran_sync_apply.py || true
fi
exit 1
