#!/bin/bash
# Run on Iran relay after files are copied to /root/.pg_nodes and /root/vpn-infra
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
timedatectl set-timezone Asia/Tehran || true
mkdir -p /var/log/xray /etc/hysteria /root/.pg_nodes/iran
touch /var/log/xray/access.log /var/log/xray/error.log

if ! command -v xray >/dev/null; then
  if [ -x /root/.pg_nodes/bin/xray ]; then
    install -m 755 /root/.pg_nodes/bin/xray /usr/local/bin/xray
    mkdir -p /usr/local/share/xray
    cp -a /root/.pg_nodes/bin/geoip.dat /root/.pg_nodes/bin/geosite.dat /usr/local/share/xray/ || true
  else
    bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install
  fi
fi
if ! command -v hysteria >/dev/null; then
  if [ -x /root/.pg_nodes/bin/hysteria ]; then
    install -m 755 /root/.pg_nodes/bin/hysteria /usr/local/bin/hysteria
  else
    curl -fsSL https://get.hy2.sh | bash
  fi
fi
if [ -x /root/.pg_nodes/bin/tuic-client ]; then
  install -m 755 /root/.pg_nodes/bin/tuic-client /usr/local/bin/tuic-client
fi

install -m 644 /root/.pg_nodes/iran/hysteria-inbound.yaml /etc/hysteria/inbound.yaml
install -m 644 /root/.pg_nodes/iran/hysteria-backhaul.yaml /etc/hysteria/backhaul.yaml
install -m 755 /root/vpn-infra/scripts/vpn-path /usr/local/sbin/vpn-path
install -m 644 /root/vpn-infra/configs/hysteria-backhaul.service /etc/systemd/system/hysteria-backhaul.service
install -m 644 /root/vpn-infra/configs/tuic-client.service /etc/systemd/system/tuic-client.service
cp /root/vpn-infra/configs/nftables-iran.conf /etc/nftables.conf

# xray unit if missing
if [ ! -f /etc/systemd/system/xray.service ]; then
  cat > /etc/systemd/system/xray.service << 'EOF'
[Unit]
Description=Xray Service
After=network.target nss-lookup.target
[Service]
User=root
ExecStart=/usr/local/bin/xray run -config /root/.pg_nodes/iran/xray.json
Restart=on-failure
RestartPreventExitStatus=23
LimitNPROC=10000
LimitNOFILE=1000000
[Install]
WantedBy=multi-user.target
EOF
fi
mkdir -p /etc/systemd/system/xray.service.d
cat > /etc/systemd/system/xray.service.d/override.conf << 'EOF'
[Service]
User=root
ExecStart=
ExecStart=/usr/local/bin/xray run -config /root/.pg_nodes/iran/xray.json
EOF

# hysteria inbound via template if present, else dedicated unit
if [ -f /etc/systemd/system/hysteria-server@.service ]; then
  systemctl enable hysteria-server@inbound.service
else
  cat > /etc/systemd/system/hysteria-inbound.service << 'EOF'
[Unit]
Description=Hysteria2 client inbound
After=network-online.target
[Service]
User=root
ExecStart=/usr/local/bin/hysteria server --config /etc/hysteria/inbound.yaml
Restart=always
RestartSec=3
LimitNOFILE=1048576
[Install]
WantedBy=multi-user.target
EOF
  systemctl enable hysteria-inbound.service
fi

xray run -test -config /root/.pg_nodes/iran/xray.json
systemctl daemon-reload
systemctl enable --now xray.service
systemctl enable --now hysteria-backhaul.service
systemctl enable --now tuic-client.service
if systemctl enable --now hysteria-server@inbound.service 2>/dev/null; then
  true
else
  systemctl enable --now hysteria-inbound.service
fi
systemctl enable nftables
nft -f /etc/nftables.conf
sleep 2
systemctl is-active xray hysteria-backhaul tuic-client || true
ss -lntup | grep -E 'xray|hysteria|tuic' || true
echo IRAN_BOOTSTRAP_DONE
