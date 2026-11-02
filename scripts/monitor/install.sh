#!/bin/bash
# Install vpn-monitor on this host. Usage: install.sh exit|iran
set -euo pipefail
ROLE="${1:-}"
if [[ "$ROLE" != "exit" && "$ROLE" != "iran" ]]; then
  echo "usage: $0 exit|iran" >&2
  exit 2
fi
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LIB=/usr/local/lib/vpn-monitor
install -d -m 755 "$LIB" /etc/vpn-monitor /var/lib/vpn-monitor /var/log/monitoring
install -m 644 "$ROOT/scripts/monitor/"*.py "$LIB/"
install -m 644 "$ROOT/configs/monitor/vpn-mon-"*.service "$ROOT/configs/monitor/vpn-mon-"*.timer /etc/systemd/system/ 2>/dev/null || true
install -m 644 "$ROOT/configs/monitor/vpn-mon-boot.service" /etc/systemd/system/
if [[ "$ROLE" == "exit" ]]; then
  install -m 644 "$ROOT/configs/monitor/config.exit.env" /etc/vpn-monitor/config.env
else
  install -m 644 "$ROOT/configs/monitor/config.iran.env" /etc/vpn-monitor/config.env
  # detect default iface
  IFACE=$(ip -o route show default 2>/dev/null | awk '{print $5; exit}')
  if [[ -n "${IFACE:-}" ]]; then
    sed -i "s/^IFACE=.*/IFACE=${IFACE}/" /etc/vpn-monitor/config.env
  fi
fi
install -m 644 "$ROOT/configs/monitor/logrotate.conf" /etc/logrotate.d/vpn-monitoring
if ! command -v vnstat >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq vnstat >/dev/null
fi
systemctl enable --now vnstat.service 2>/dev/null || systemctl enable --now vnstat 2>/dev/null || true
systemctl daemon-reload
systemctl enable --now vpn-mon-capacity.timer vpn-mon-hardware.timer vpn-mon-quota.timer vpn-mon-google.timer
systemctl enable vpn-mon-boot.service
# wrappers
install -m 755 /dev/null /usr/local/sbin/vpn-mon-test
cat > /usr/local/sbin/vpn-mon-test << 'EOF'
#!/bin/sh
exec /usr/bin/python3 /usr/local/lib/vpn-monitor/test_alerts.py
EOF
chmod 755 /usr/local/sbin/vpn-mon-test
install -m 755 /dev/null /usr/local/sbin/vpn-mon-netcup-login
cat > /usr/local/sbin/vpn-mon-netcup-login << 'EOF'
#!/bin/sh
exec /usr/bin/python3 /usr/local/lib/vpn-monitor/netcup_oauth.py
EOF
chmod 755 /usr/local/sbin/vpn-mon-netcup-login
echo "installed role=$ROLE"
