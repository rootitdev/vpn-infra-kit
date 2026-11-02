#!/usr/bin/env bash
# Roll back what vpn-infra-kit added. Never touches objects it did not create.
#   ./rollback.sh --list                 show backups + recorded additions
#   ./rollback.sh --master-objects --yes remove ONLY the Pasarguard core/node this kit created (IDs in state)
#   ./rollback.sh --exit --yes           stop/disable our backhaul xray unit, remove our nft rules (by comment), disable our nginx conf (renamed, not deleted)
#   ./rollback.sh --restore <TS> --yes   copy files from backups/<TS> back into place
set -euo pipefail
. "$(dirname "$0")/installer/lib.sh"; load_env
case "${1:-}" in
  --list) ls -1 "$STATE_DIR/backups" 2>/dev/null; cat "$STATE_DIR/master-created.json" 2>/dev/null || true; cat "$STATE_DIR/nft-added.txt" 2>/dev/null || true;;
  --master-objects) [ "${2:-}" = --yes ] || die "needs --yes"; python3 "$KIT_ROOT/master/pg_master.py" rollback --yes;;
  --exit) [ "${2:-}" = --yes ] || die "needs --yes"
    systemctl disable --now "${KIT_PREFIX}-exit-xray" 2>/dev/null || true
    nft -a list ruleset | awk -v tag="vpn-infra-kit:${KIT_PREFIX}" '/^table/{t=$2" "$3} /chain /{c=$2} index($0,tag){print t, c, $NF}' | while read -r fam tab ch h; do nft delete rule $fam $tab $ch handle $h; done
    f=/etc/nginx/conf.d/${KIT_PREFIX}-xhttp.conf; [ -f "$f" ] && mv "$f" "$f.disabled" && nginx -t && systemctl reload nginx; log "exit side rolled back";;
  --restore) [ "${3:-}" = --yes ] || die "needs --yes"; src="$STATE_DIR/backups/$2"; [ -d "$src" ] || die "no backup $2"; cp -a "$src"/. /; log "restored files from $2 (services not restarted; reload the affected one manually)";;
  *) sed -n '2,8p' "$0";;
esac
