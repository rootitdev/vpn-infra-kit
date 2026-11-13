#!/bin/bash
# TO-NL-SSH backhaul: Iran (Shetaban) → MobinHost NL :22 SOCKS (4 tunnels + haproxy :18400).
# Third path when WaterWall and direct VLESS-to-NL are blocked — same pattern as TO-AMS-SSH (Netcup).
#
# Run ON IRAN:
#   NL_EXIT_IP=185.19.33.221 IRAN_IP=193.228.90.107 ./setup-ssh-path-nl.sh
# Then on PANEL (NL): python3 scripts/add_nl_ssh_outbound.py
set -euo pipefail
: "${NL_EXIT_IP:?}" "${IRAN_IP:?}"
D=$(cd "$(dirname "$0")" && pwd)
B=/root/backups/ssh-path-nl-$(date +%Y%m%d-%H%M%S); mkdir -p -m700 "$B"
[[ -f /etc/haproxy/haproxy.cfg ]] && cp -a /etc/haproxy/haproxy.cfg "$B/"

KEY=/root/.ssh/rootit_tunnel_nl
test -f "$KEY" || ssh-keygen -q -t ed25519 -N '' -C rootit-ssh-tunnel-nl -f "$KEY"
PUB=$(cat "${KEY}.pub")

ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new "root@$NL_EXIT_IP" "id rootit-tun >/dev/null 2>&1 || useradd -m -s /usr/sbin/nologin rootit-tun; passwd -l rootit-tun >/dev/null;
 install -d -m700 -o rootit-tun -g rootit-tun /home/rootit-tun/.ssh;
 touch /home/rootit-tun/.ssh/authorized_keys;
 grep -qF '$PUB' /home/rootit-tun/.ssh/authorized_keys || echo 'restrict,port-forwarding,from=\"$IRAN_IP\",command=\"/bin/false\" $PUB' >> /home/rootit-tun/.ssh/authorized_keys;
 chown rootit-tun: /home/rootit-tun/.ssh/authorized_keys; chmod 600 /home/rootit-tun/.ssh/authorized_keys"

DEBIAN_FRONTEND=noninteractive apt-get install -y -qq haproxy >/dev/null
grep -q rootit_ssh_socks_nl /etc/haproxy/haproxy.cfg || cat "$D/haproxy-rootit-ssh-nl.cfg" >> /etc/haproxy/haproxy.cfg
haproxy -c -f /etc/haproxy/haproxy.cfg -q

sed "s/\${NL_EXIT_IP}/$NL_EXIT_IP/" "$D/rootit-ssh-tunnel-nl@.service" > /etc/systemd/system/rootit-ssh-tunnel-nl@.service
systemctl daemon-reload
for p in 18401 18402 18403 18404; do systemctl enable --now -q "rootit-ssh-tunnel-nl@$p"; done
systemctl enable -q haproxy && systemctl restart haproxy
sleep 4
curl -s -o /dev/null -w "nl-ssh-probe %{http_code}\n" --socks5-hostname 127.0.0.1:18400 https://www.gstatic.com/generate_204 || true
echo "TO-NL-SSH ready — haproxy 127.0.0.1:18400 → $NL_EXIT_IP"
