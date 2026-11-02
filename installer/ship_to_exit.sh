#!/usr/bin/env bash
# Split mode: copy the kit + filled .env to the EXIT host and run install.sh there.
#   ENV_FILE=/path/.env installer/ship_to_exit.sh [install.sh args...]   (default: --plan)
# Honors the target-IP deny file. Password auth via EXIT_SSH_PASSWORD (sshpass -e) or EXIT_SSH_KEY_FILE.
set -euo pipefail
. "$(dirname "$0")/lib.sh"; load_env; need EXIT_IP
[ "${EXIT_SPLIT:-0}" = 1 ] || die "EXIT_SPLIT=1 required"
o="-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15"
if [ -n "${EXIT_SSH_KEY_FILE:-}" ]; then S=(ssh $o -i "$EXIT_SSH_KEY_FILE" -p "$EXIT_SSH_PORT"); else export SSHPASS="$EXIT_SSH_PASSWORD"; S=(sshpass -e ssh $o -p "$EXIT_SSH_PORT"); fi
R="$EXIT_SSH_USER@$EXIT_IP"; DST=/opt/vpn-infra-kit/src
tar -C "$KIT_ROOT" --exclude=.git --exclude=.target-deny --exclude=.scan-deny -czf - . | "${S[@]}" "$R" "umask 077; mkdir -p $DST /root/.vpn-secrets && tar -xzf - -C $DST"
"${S[@]}" "$R" "umask 077; cat > /root/.vpn-secrets/.env" < "$ENV_FILE"
[ -n "${TARGET_DENY_FILE:-}" ] && "${S[@]}" "$R" "cat > /root/.vpn-secrets/target-deny.txt" < "$TARGET_DENY_FILE"
"${S[@]}" -t "$R" "cd $DST && ENV_FILE=/root/.vpn-secrets/.env ./install.sh ${*:---plan}"
