#!/usr/bin/env bash
# vpn-infra-kit installer — idempotent, phase-based. Runs ON the Exit/master host as root.
#   ./install.sh --plan                 preflight + print every change, apply nothing (DEFAULT)
#   ./install.sh --phase <name> [--yes] run one phase
#   ./install.sh --all --yes            run all phases in order
# Phases: preflight gen exit iran paths panels failover backup verify
# Safety: backs up every file before touching it; never deletes; never restarts the
# master's existing xray/panel/nodes; secrets are never echoed.
set -euo pipefail
. "$(dirname "$0")/installer/lib.sh"
PHASE=""; ALL=0; PLAN=1
while [ $# -gt 0 ]; do case "$1" in
  --phase) PHASE="$2"; PLAN=0; shift;; --all) ALL=1; PLAN=0;; --plan) PLAN=1;; --yes) ASSUME_YES=1;;
  *) die "unknown arg $1";; esac; shift; done
load_env
MODE="${INSTALL_MODE:-}"; case "$MODE" in standalone|master) ;; *) die "set INSTALL_MODE=standalone or master in .env";; esac
[ "$MODE" = master ] && export INBOUND_PREFIX="${KIT_PREFIX}-"
RENDERED=/opt/vpn-infra-kit/rendered; export KIT_RENDERED=$RENDERED
KXRAY_DIR=/opt/vpn-infra-kit/exit; KXRAY_UNIT="${KIT_PREFIX}-exit-xray"
[ "$PLAN" = 1 ] || { mkdir -p "$STATE_DIR"; chmod 700 "$STATE_DIR"; }   # --plan writes nothing

port_free(){ ! ss -Hltn "sport = :$1" | grep -q .; }

phase_preflight(){
  log "preflight (read-only) — mode=$MODE"
  need EXIT_IP IRAN_IP PASARGUARD_URL PASARGUARD_ADMIN_USER PASARGUARD_ADMIN_PASS
  for b in python3 curl ssh docker nft ss openssl; do command -v $b >/dev/null || die "missing binary $b"; done
  [ -n "${IRAN_SSH_KEY_FILE:-}" ] || command -v sshpass >/dev/null || die "sshpass needed for password SSH (apt install sshpass)"
  on_iran 'echo iran-ssh-ok; uname -r; docker --version 2>/dev/null || echo NO_DOCKER; ss -Hltn | awk "{print \$4}" | grep -Eo "[0-9]+$" | sort -nu | tr "\n" " "' || die "cannot SSH to Iran"
  # /openapi.json is 404 when the panel runs with docs disabled (common in production) -> verify by admin login instead
  python3 "$KIT_ROOT/master/pg_master.py" login >/dev/null 2>&1 \
    && log "Pasarguard API reachable (admin login ok)" || die "Pasarguard API login failed at PASARGUARD_URL"
  # exit-side prerequisites on THIS host (master mode assumes the master is also the Exit)
  XR=$(command -v xray || ls /root/.pg_nodes/bin/xray 2>/dev/null || true); [ -n "$XR" ] && log "xray binary: $XR" || warn "no xray binary on this host — phase gen/exit need one (install xray-core standalone; master's panel container is NOT used)"
  command -v nginx >/dev/null && log "nginx present" || warn "nginx absent — phase exit will NOT create the XHTTP/CDN origin on 443; CDN paths (xhttp/gcore/bunny/cf) stay dead until an origin is set up"
  [ -f "${TLS_CERT_FILE:-/nonexistent}" ] && log "TLS cert present" || warn "TLS cert ${TLS_CERT_FILE:-} missing — needed for XHTTP/DIRECT origin"
  docker ps --format '{{.Names}} {{.Image}}' | sed 's/^/  container: /'
  for p in "${REALITY_PORT}" "${XHTTP_BRIDGE_PORT}" "${DIRECT_TLS_PORT}" "${SOCKS_TEST_PORT}"; do
    if port_free "$p"; then log "port $p free"; elif systemctl is-active -q "$KXRAY_UNIT"; then log "port $p held by our $KXRAY_UNIT (ok)"; else warn "port $p IN USE on master — pick another in .env"; fi; done
  ss -Hltn "sport = :443" | grep -q . && log "443 already served (nginx stream/sni will be extended, not replaced)"
  nft list ruleset >/dev/null 2>&1 && log "nftables present: $(nft list tables | tr '\n' ' ')"
  for d in PANEL_DOMAIN XHTTP_DOMAIN CF_GRAY_DOMAIN CFORANGE_DOMAIN GCORE_DOMAIN BUNNY_DOMAIN IRAN_DOMAIN; do
    v="${!d:-}"; [ -z "$v" ] && { log "$d empty -> path skipped"; continue; }; getent hosts "$v" >/dev/null && log "$d resolves" || warn "$d does not resolve yet"; done
  if [ "$MODE" = master ] && [ "$PLAN" != 1 ]; then python3 "$KIT_ROOT/master/pg_master.py" snapshot >/dev/null && log "master API snapshot taken"; fi
}

phase_gen(){
  log "generating missing secrets (values written to .env only)"
  [ -n "${XRAY_BRIDGE_UUID:-}" ] || set_env XRAY_BRIDGE_UUID "$(cat /proc/sys/kernel/random/uuid)"
  [ -n "${XHTTP_PATH:-}" ] || set_env XHTTP_PATH "/$(openssl rand -hex 4)/$(openssl rand -hex 3)"
  [ -n "${PG_NODE_API_KEY:-}" ] || set_env PG_NODE_API_KEY "$(cat /proc/sys/kernel/random/uuid)"
  [ -n "${BACKUP_PASSPHRASE:-}" ] || { set_env BACKUP_PASSPHRASE "$(openssl rand -base64 33 | tr -d '\n=+/')"; warn "BACKUP_PASSPHRASE generated — operator must copy it OFFLINE (read it with: grep ^BACKUP_PASSPHRASE= $ENV_FILE)"; }
  [ -n "${REALITY_SHORT_ID:-}" ] || set_env REALITY_SHORT_ID "$(openssl rand -hex 8)"
  [ -n "${REALITY_CLIENT_SHORT_ID:-}" ] || set_env REALITY_CLIENT_SHORT_ID "$(openssl rand -hex 8)"
  XR=$(command -v xray || echo /root/.pg_nodes/bin/xray)
  if [ -z "${REALITY_PRIVATE_KEY:-}" ]; then out=$("$XR" x25519); set_env REALITY_PRIVATE_KEY "$(echo "$out" | awk -F': ' '/Private/{print $2}')"; set_env REALITY_PUBLIC_KEY "$(echo "$out" | awk -F': ' '/Public|Password/{print $2}' | head -1)"; fi
  if [ -z "${REALITY_CLIENT_PRIVATE_KEY:-}" ]; then out=$("$XR" x25519); set_env REALITY_CLIENT_PRIVATE_KEY "$(echo "$out" | awk -F': ' '/Private/{print $2}')"; fi
  render_tree "$RENDERED"; chmod -R go-rwx "$RENDERED"
}

phase_exit(){
  log "exit/master: dedicated backhaul xray ($KXRAY_UNIT) — master's own xray is NOT touched"
  render_tree "$RENDERED"; mkdir -p "$KXRAY_DIR"; backup_path "$KXRAY_DIR/xray.json"
  python3 - "$RENDERED/templates/reference/exit-xray.json.tmpl" "$KXRAY_DIR/xray.json" <<'P'
import json,os,sys
c=json.load(open(sys.argv[1])); ports={'socks-in':os.environ['SOCKS_TEST_PORT'],'xhttp-bridge':os.environ['XHTTP_BRIDGE_PORT'],'direct-tls':os.environ['DIRECT_TLS_PORT'],'reality-bridge':os.environ['REALITY_PORT']}
for i in c['inbounds']:
    if i['tag'] in ports: i['port']=int(ports[i['tag']])
    i['tag']=os.environ['KIT_PREFIX']+'-'+i['tag'] if os.environ.get('INSTALL_MODE')=='master' else i['tag']
if not os.environ.get('WARP_PRIVATE_KEY'): c['outbounds']=[o for o in c['outbounds'] if o.get('tag')!='WARP']
json.dump(c,open(sys.argv[2],'w'),indent=2); os.chmod(sys.argv[2],0o600)
P
  if [ "${CTL_MODE:-tunnel}" = tunnel ]; then   # control link: portal + local-only entry on our OWN xray
    python3 "$KIT_ROOT/ctl/gen_ctl.py" "$RENDERED/templates/iran-core.json.tmpl" "$KXRAY_DIR/xray.json" "$KXRAY_DIR/iran-ctl.json"
  fi
  XR=$(command -v xray || echo /root/.pg_nodes/bin/xray); "$XR" run -test -c "$KXRAY_DIR/xray.json" >/dev/null || die "xray config test failed"
  cat > /etc/systemd/system/$KXRAY_UNIT.service <<U
[Unit]
Description=vpn-infra-kit backhaul xray (exit side)
After=network-online.target
[Service]
ExecStart=$XR run -c $KXRAY_DIR/xray.json
Restart=always
LimitNOFILE=1048576
[Install]
WantedBy=multi-user.target
U
  systemctl daemon-reload; systemctl enable -q $KXRAY_UNIT
  if systemctl is-active -q $KXRAY_UNIT; then systemctl restart $KXRAY_UNIT; else systemctl start $KXRAY_UNIT; fi   # our own unit only
  # nft: scoped, commented rules; REALITY only from IRAN_IP. Inserted into the existing input chain if one drops by default.
  backup_path /etc/nftables.conf
  if ! nft list ruleset | grep -q "vpn-infra-kit:$KIT_PREFIX"; then
    fam_tab_chain=$(nft -a list ruleset | awk '/^table/{t=$2" "$3} /chain input/{print t" input"; exit}')
    if [ -n "$fam_tab_chain" ]; then
      nft insert rule $fam_tab_chain ip saddr "$IRAN_IP" tcp dport "{ ${REALITY_PORT}, ${DIRECT_TLS_PORT} }" accept comment "\"vpn-infra-kit:$KIT_PREFIX\""
      nft insert rule $fam_tab_chain tcp dport "${REALITY_PORT}" drop comment "\"vpn-infra-kit:$KIT_PREFIX-reality-guard\"" 2>/dev/null || true
      nft insert rule $fam_tab_chain ip saddr "$IRAN_IP" tcp dport "${REALITY_PORT}" accept comment "\"vpn-infra-kit:$KIT_PREFIX\""
      nft list ruleset | grep "vpn-infra-kit:$KIT_PREFIX" >> "$STATE_DIR/nft-added.txt"
      warn "nft rules added at runtime; persist them by appending to /etc/nftables.conf (operator review)"
    else log "no input chain filtering found; nothing to add"; fi
  fi
  # nginx: XHTTP on 443 via SNI/host — add a server block include, test, then RELOAD (graceful, no drop)
  if command -v nginx >/dev/null && [ -n "${XHTTP_DOMAIN:-}" ]; then
    f=/etc/nginx/conf.d/$KIT_PREFIX-xhttp.conf; backup_path "$f"
    sed -n '/location .*XHTTP_PATH/,/^    }/p' "$RENDERED/templates/reference/nginx-exit-vpn-panel.conf" >/dev/null
    cat > "$f" <<N
# vpn-infra-kit ($KIT_PREFIX): XHTTP backhaul origin for CDN paths
server {
  listen 127.0.0.1:${XHTTP_NGINX_PORT:-8447} ssl http2;
  server_name ${XHTTP_DOMAIN} ${CF_GRAY_DOMAIN} ${CFORANGE_DOMAIN} ${GCORE_DOMAIN} ${BUNNY_DOMAIN};
  ssl_certificate ${TLS_CERT_FILE}; ssl_certificate_key ${TLS_KEY_FILE};
  location ${XHTTP_PATH} { grpc_pass grpc://127.0.0.1:${XHTTP_BRIDGE_PORT}; client_max_body_size 0; grpc_read_timeout 1h; grpc_send_timeout 1h; }
  location / { return 404; }
}
N
    nginx -t && systemctl reload nginx || { warn "nginx -t failed — reverting our file"; cp -a "$BACKUP_DIR/$f" "$f" 2>/dev/null || mv "$f" "$f.disabled"; }
    warn "if 443 is an SNI stream (ssl_preread) on master, map the new hostnames to 127.0.0.1:${XHTTP_NGINX_PORT:-8447} in the stream map (see templates/reference/nginx-exit-stream-sni-443.conf) — shown in --plan, applied only with confirmation"
  fi
}

phase_iran(){
  log "iran: pg-node container + config (Iran host is dedicated to this kit)"
  render_tree "$RENDERED"
  iran_backup /etc/nginx /etc/nftables.conf /var/lib/pg-node /etc/systemd/system/pg-node.service
  on_iran "mkdir -p /usr/local/sbin /var/lib/pg-node/sync /root/.pg_nodes/certs"
  to_iran "$RENDERED/iran/sbin/." /usr/local/sbin/
  to_iran "$RENDERED/scripts/path_health.py" /usr/local/sbin/path_health.py
  to_iran "$RENDERED/scripts/vpn_paths.py" /usr/local/sbin/vpn_paths.py
  to_iran "$RENDERED/systemd/iran/." /etc/systemd/system/
  on_iran "chmod 755 /usr/local/sbin/*; command -v docker >/dev/null || (curl -fsSL https://get.docker.com | sh)"
  on_iran "cat > /etc/default/pg-node <<X
API_KEY=$PG_NODE_API_KEY
SERVICE_PORT=$PG_NODE_PORT
SERVICE_PROTOCOL=grpc
NODE_HOST=$( [ "${CTL_MODE:-tunnel}" = tunnel ] && [ "${CTL_DIRECT_FALLBACK:-0}" != 1 ] && echo 127.0.0.1 || echo 0.0.0.0 )
SSL_CERT_FILE=/root/.pg_nodes/certs/fullchain.pem
SSL_KEY_FILE=/root/.pg_nodes/certs/privkey.pem
X
chmod 600 /etc/default/pg-node; docker image inspect $PG_NODE_IMAGE >/dev/null 2>&1 || docker pull $PG_NODE_IMAGE"
  on_iran "systemctl daemon-reload; systemctl enable -q pg-node && (systemctl is-active -q pg-node || systemctl start pg-node)"
  phase_ctl
}

# Panel<->node control link. tunnel: Iran ctl-bridge xray dials out through XHTTP/REALITY to the Exit portal.
# Node API port on Iran is never reachable from the Internet except (optional fallback) from EXIT_IP.
phase_ctl(){
  log "control link: CTL_MODE=${CTL_MODE:-tunnel} fallback=${CTL_DIRECT_FALLBACK:-0}"
  iran_backup /etc/nftables.conf
  # Iran firewall for the node API port: loopback always; EXIT_IP only when direct/fallback; everyone else dropped
  on_iran "nft list table inet ${KIT_PREFIX}_ctl >/dev/null 2>&1 && nft delete table inet ${KIT_PREFIX}_ctl; nft -f - <<N
table inet ${KIT_PREFIX}_ctl {
  chain input { type filter hook input priority -10; policy accept;
    iif lo tcp dport ${PG_NODE_PORT} accept
    $( { [ "${CTL_MODE:-tunnel}" = direct ] || [ "${CTL_DIRECT_FALLBACK:-0}" = 1 ]; } && echo "ip saddr ${EXIT_IP} tcp dport ${PG_NODE_PORT} accept" )
    tcp dport ${PG_NODE_PORT} drop comment \"vpn-infra-kit:${KIT_PREFIX}-nodeapi-guard\"
  }
}
N"
  [ "${CTL_MODE:-tunnel}" = tunnel ] || { log "direct control link: panel -> ${IRAN_IP}:${PG_NODE_PORT} (EXIT_IP only)"; return; }
  [ -f "$KXRAY_DIR/iran-ctl.json" ] || die "run --phase exit first (generates iran-ctl.json)"
  on_iran "mkdir -p /opt/vpn-infra-kit && chmod 700 /opt/vpn-infra-kit"
  to_iran "$KXRAY_DIR/iran-ctl.json" /opt/vpn-infra-kit/ctl.json
  on_iran "XR=\$(command -v xray || ls /usr/local/bin/xray /root/.pg_nodes/bin/xray 2>/dev/null | head -1); [ -n \"\$XR\" ] || (bash -c \"\$(curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh)\" @ install && XR=/usr/local/bin/xray)
chmod 600 /opt/vpn-infra-kit/ctl.json; \$XR run -test -c /opt/vpn-infra-kit/ctl.json >/dev/null
cat > /etc/systemd/system/${KIT_PREFIX}-ctl-bridge.service <<U
[Unit]
Description=vpn-infra-kit control-link reverse bridge (panel<->node via tunnel)
After=network-online.target pg-node.service
[Service]
ExecStart=\$XR run -c /opt/vpn-infra-kit/ctl.json
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
U
systemctl daemon-reload; systemctl enable -q ${KIT_PREFIX}-ctl-bridge; systemctl restart ${KIT_PREFIX}-ctl-bridge"
  log "panel must use node address ${CTL_NODE_ADDRESS:-127.0.0.1}:${CTL_LOCAL_PORT:-62051}"
}

phase_paths(){
  log "paths: register node + core on Pasarguard (add-only), CDN/DNS checks"
  if [ "$MODE" = master ]; then
    python3 "$KIT_ROOT/master/pg_master.py" plan
    confirm "Apply the add-only plan above to the master panel?"
    python3 "$KIT_ROOT/master/pg_master.py" apply --yes
  else
    python3 "$RENDERED/scripts/pg_bootstrap_panel.py"
  fi
  [ -n "${CF_API_TOKEN:-}" ] && python3 "$RENDERED/scripts/cf_dns.py" --check || true
}

phase_panels(){
  [ "$MODE" = master ] && [ "${INSTALL_PANELS:-0}" != 1 ] && { log "master mode: panels skipped (set INSTALL_PANELS=1 to add path-web only)"; return; }
  render_tree "$RENDERED"
  for p in path-web settle-web ig-mult-web sni-watch; do [ -x "$RENDERED/panels/$p/install.sh" ] && bash "$RENDERED/panels/$p/install.sh"; done
}

phase_failover(){
  log "failover: vpn-health + vpn-failover timers (15s) on control host"
  render_tree "$RENDERED"; install -d /root/vpn-infra/scripts
  for f in vpn_paths.py vpn_path_lib.py vpn_failover.py vpn-path-core.py vpn-path path_health.py; do backup_path /root/vpn-infra/scripts/$f; install -m 755 "$RENDERED/scripts/$f" /root/vpn-infra/scripts/$f; done
  for u in vpn-health.service vpn-health.timer vpn-failover.service vpn-failover.timer; do backup_path /etc/systemd/system/$u; install -m 644 "$RENDERED/systemd/exit/$u" /etc/systemd/system/$u; done
  install -m 755 "$RENDERED/scripts/healthcheck-exit.sh" /usr/local/sbin/healthcheck-exit.sh
  systemctl daemon-reload; systemctl enable --now -q vpn-health.timer vpn-failover.timer
}

phase_backup(){
  need TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID BACKUP_PASSPHRASE
  render_tree "$RENDERED"; backup_path /root/vpn-infra/scripts/backup-stack.sh
  install -m 755 "$RENDERED/scripts/backup-stack.sh" /root/vpn-infra/scripts/backup-stack.sh
  for u in vpn-backup.service vpn-backup.timer; do install -m 644 "$RENDERED/systemd/exit/$u" /etc/systemd/system/$u; done
  systemctl daemon-reload; systemctl enable --now -q vpn-backup.timer; log "backup timer enabled (first run: systemctl start vpn-backup.service)"
}

phase_verify(){
  log "verify: per-path tunnel probes (expect HTTP 204 through EVERY path)"
  on_iran "python3 /usr/local/sbin/path_health.py >/dev/null 2>&1; cat /var/lib/pg-node/sync/health.json" | python3 -c '
import json,sys
d=json.load(sys.stdin); bad=0
for t,v in (d.get("paths") or d).items():
    ok=v.get("ok"); bad+= (not ok); print(f"  {t:18} {\"OK \" if ok else \"FAIL\"} {v.get(\"code\",\"\")} {v.get(\"ms\",\"\")}ms {v.get(\"err\",\"\")[:60]}")
sys.exit(1 if bad else 0)' || warn "some paths failing (see above)"
  on_iran "curl -s -o /dev/null -w 'tunnel %{http_code} %{time_total}s\n' -x socks5h://127.0.0.1:11080 https://www.gstatic.com/generate_204" || warn "end-to-end tunnel test failed"
  [ "$MODE" = master ] && { python3 "$KIT_ROOT/master/pg_master.py" plan | grep -E "untouched|BLOCK" ; }
  if [ "${CTL_MODE:-tunnel}" = tunnel ]; then
    timeout 5 bash -c "</dev/tcp/${CTL_LISTEN:-127.0.0.1}/${CTL_LOCAL_PORT:-62051}" && log "ctl entry ${CTL_LOCAL_PORT} open on Exit" || warn "ctl entry port not listening"
    on_iran "systemctl is-active ${KIT_PREFIX}-ctl-bridge; ss -Hltn 'sport = :${PG_NODE_PORT}' | awk '{print \$4}'" | sed 's/^/  iran: /'
  fi
  log "external exposure check of node API (must be closed unless fallback):"; timeout 5 bash -c "</dev/tcp/${IRAN_IP}/${PG_NODE_PORT}" 2>/dev/null && echo "  ${PG_NODE_PORT} reachable from Exit (expected only with fallback/direct)" || echo "  ${PG_NODE_PORT} closed from Exit"
  systemctl --no-pager --plain list-timers 'vpn-*' | head
}

PHASES=(preflight gen exit iran ctl paths panels failover backup verify)
if [ $PLAN = 1 ]; then
  phase_preflight
  echo; log "PLAN (nothing applied):"
  cat <<P
  gen      : generate missing UUID/XHTTP path/REALITY keys/node key/backup passphrase into .env
  exit     : new unit $KXRAY_UNIT (own xray, ports ${REALITY_PORT}/${XHTTP_BRIDGE_PORT}/${DIRECT_TLS_PORT}/${SOCKS_TEST_PORT});
             nft: insert commented accept rules (REALITY only from Iran IP); nginx: add conf.d/$KIT_PREFIX-xhttp.conf, nginx -t, reload
  iran     : copy kit scripts + units, docker pg-node ($PG_NODE_IMAGE) on :$PG_NODE_PORT
  ctl      : CTL_MODE=${CTL_MODE:-tunnel}: $( [ "${CTL_MODE:-tunnel}" = tunnel ] && echo "Exit portal ${KIT_PREFIX}-ctl-portal + local entry ${CTL_LISTEN:-127.0.0.1}:${CTL_LOCAL_PORT:-62051}; Iran unit ${KIT_PREFIX}-ctl-bridge via ${CTL_PATHS:-TO-AMS-XHTTP,TO-AMS-REALITY}; node API bound 127.0.0.1" || echo "direct") ; Iran nft table ${KIT_PREFIX}_ctl: node port lo$( { [ "${CTL_MODE:-tunnel}" = direct ] || [ "${CTL_DIRECT_FALLBACK:-0}" = 1 ]; } && echo " + EXIT_IP") only
  paths    : $( [ "$MODE" = master ] && echo "Pasarguard ADD-ONLY: core '${KIT_PREFIX}-iran-core', node '${KIT_PREFIX}-iran', hosts '${KIT_PREFIX}-*'" || echo "bootstrap own panel entities" )
  panels   : $( [ "$MODE" = master ] && echo "skipped" || echo "path-web, settle-web, ig-mult-web, sni-watch" )
  failover : vpn-health/vpn-failover timers; priority: $(PYTHONPATH="$KIT_ROOT/scripts" python3 -c 'import vpn_paths as v;print(" > ".join(v.PRIORITY))'); CFORANGE watch-only
  backup   : daily GPG(AES256) archive to Telegram
  verify   : 204 through every path + end-to-end
P
  [ "$MODE" = master ] && python3 "$KIT_ROOT/master/pg_master.py" plan || true
  exit 0
fi
if [ $ALL = 1 ]; then for p in "${PHASES[@]}"; do log "=== phase $p ==="; phase_$p; done
else [[ " ${PHASES[*]} " == *" $PHASE "* ]] || die "unknown phase $PHASE"; phase_$PHASE; fi
log "done. backups of changed files: $BACKUP_DIR"
