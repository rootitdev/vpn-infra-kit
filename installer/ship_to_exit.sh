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
# pull back values generated ON the Exit (phase gen / installer IDs) into the local .env for keys that are empty locally
"${S[@]}" "$R" "cat /root/.vpn-secrets/.env 2>/dev/null" | python3 -c '
import sys,re
loc=sys.argv[1]; rem={}
GEN={"XRAY_BRIDGE_UUID","XHTTP_PATH","PG_NODE_API_KEY","BACKUP_PASSPHRASE","REALITY_SHORT_ID","REALITY_CLIENT_SHORT_ID","REALITY_PRIVATE_KEY","REALITY_PUBLIC_KEY","REALITY_CLIENT_PRIVATE_KEY","PG_CORE_ID","PG_NODE_ID","PG_GROUP_ID"}  # only installer-generated keys
for l in sys.stdin.read().splitlines():
    m=re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$",l)
    if m and m.group(1) in GEN and m.group(2) not in ("","\x27\x27"): rem[m.group(1)]=m.group(2)
L=open(loc).read().splitlines(); seen=set(); out=[]
for l in L:
    m=re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$",l)
    if m: seen.add(m.group(1))
    if m and m.group(2)=="" and m.group(1) in rem: l=m.group(1)+"="+rem[m.group(1)]
    out.append(l)
out+= [k+"="+v for k,v in rem.items() if k not in seen]
open(loc,"w").write("\n".join(out)+"\n")' "$ENV_FILE"
# the Exit only needs Iran creds + API tokens: strip master/exit SSH secrets and local-only keys
grep -vE '^(EXIT_SSH_PASSWORD|MASTER_SSH_PASSWORD|MASTER_SSH_KEY_FILE|EXIT_SSH_KEY_FILE|F_[A-Z_]+|STATE_DIR|KIT_RENDERED|TARGET_DENY_FILE)=' "$ENV_FILE" \
  | "${S[@]}" "$R" "umask 077; cat > /root/.vpn-secrets/.env"
[ -n "${TARGET_DENY_FILE:-}" ] && "${S[@]}" "$R" "cat > /root/.vpn-secrets/target-deny.txt" < "$TARGET_DENY_FILE"
"${S[@]}" -t "$R" "cd $DST && ENV_FILE=/root/.vpn-secrets/.env ./install.sh ${*:---plan}"
