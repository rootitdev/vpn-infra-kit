#!/usr/bin/env bash
# Shared helpers. Never echo secret values.
set -euo pipefail
KIT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-/root/.vpn-secrets/.env}"
STATE_DIR="${STATE_DIR:-/var/lib/vpn-infra-kit}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="$STATE_DIR/backups/$TS"
log(){ printf '\033[1;34m[kit]\033[0m %s\n' "$*"; }
warn(){ printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
die(){ printf '\033[1;31m[fail]\033[0m %s\n' "$*" >&2; exit 1; }
load_env(){ [ -f "$ENV_FILE" ] || die "missing $ENV_FILE (copy .env.example)"; [ "$(stat -c %a "$ENV_FILE")" = 600 ] || chmod 600 "$ENV_FILE"; set -a; . "$ENV_FILE"; set +a; }
need(){ for v in "$@"; do [ -n "${!v:-}" ] || die "required variable $v is empty in .env"; done; }
set_env(){ # set_env KEY VALUE  (writes without printing)
  local k="$1" v="$2"; if grep -q "^$k=" "$ENV_FILE"; then python3 - "$ENV_FILE" "$k" "$v" <<'P'
import sys;p,k,v=sys.argv[1:];L=open(p).read().splitlines();open(p,'w').write('\n'.join((f"{k}={v}" if l.startswith(k+'=') else l) for l in L)+'\n')
P
  else echo "$k=$v" >> "$ENV_FILE"; fi; export "$k=$v"; }
_ssh_opts(){ echo "-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -o ServerAliveInterval=10"; }
on_iran(){ # run a command on Iran
  if [ -n "${IRAN_SSH_KEY_FILE:-}" ]; then ssh $(_ssh_opts) -i "$IRAN_SSH_KEY_FILE" -p "$IRAN_SSH_PORT" "$IRAN_SSH_USER@$IRAN_IP" "$@";
  else SSHPASS="$IRAN_SSH_PASSWORD" sshpass -e ssh $(_ssh_opts) -p "$IRAN_SSH_PORT" "$IRAN_SSH_USER@$IRAN_IP" "$@"; fi; }
to_iran(){ # to_iran localpath remotepath
  if [ -n "${IRAN_SSH_KEY_FILE:-}" ]; then scp $(_ssh_opts) -i "$IRAN_SSH_KEY_FILE" -P "$IRAN_SSH_PORT" -r "$1" "$IRAN_SSH_USER@$IRAN_IP:$2";
  else SSHPASS="$IRAN_SSH_PASSWORD" sshpass -e scp $(_ssh_opts) -P "$IRAN_SSH_PORT" -r "$1" "$IRAN_SSH_USER@$IRAN_IP:$2"; fi; }
backup_path(){ # backup_path /abs/path  (local) — copies, never moves
  mkdir -p "$BACKUP_DIR"; [ -e "$1" ] && cp -a --parents "$1" "$BACKUP_DIR/" && log "backed up $1"; true; }
iran_backup(){ on_iran "mkdir -p $STATE_DIR/backups/$TS && for p in $*; do [ -e \$p ] && cp -a --parents \$p $STATE_DIR/backups/$TS/; done; true"; }
# Render ${PLACEHOLDER}s (only known kit variables) into a staging tree
render_tree(){ python3 "$KIT_ROOT/installer/render.py" "$KIT_ROOT" "$1"; }
confirm(){ [ "${ASSUME_YES:-0}" = 1 ] && return 0; read -r -p "$1 [type YES] " a; [ "$a" = YES ] || die "aborted by operator"; }
