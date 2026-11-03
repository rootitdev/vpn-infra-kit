#!/bin/bash
# TO-AMS-SSH backhaul: 4 SSH SOCKS tunnels (Iran -> Exit:22) behind haproxy 127.0.0.1:18300.
# Run ON IRAN with root SSH to Exit. Adds a locked non-root user rootit-tun on Exit
# (key restricted: port-forwarding only, from IRAN_IP only). No sshd_config change.
# Then adds outbound {"tag":"TO-AMS-SSH","protocol":"socks","settings":{"servers":[{"address":"127.0.0.1","port":18300}]}}
# to the panel core (run add_ssh_outbound on Exit) and publish.
set -euo pipefail
: "${EXIT_IP:?}" "${IRAN_IP:?}"
D=$(cd "$(dirname "$0")" && pwd)
B=/root/backups/ssh-path-$(date +%Y%m%d-%H%M%S); mkdir -p -m700 "$B"
[[ -f /etc/haproxy/haproxy.cfg ]] && cp -a /etc/haproxy/haproxy.cfg "$B/"
test -f /root/.ssh/rootit_tunnel || ssh-keygen -q -t ed25519 -N '' -C rootit-ssh-tunnel -f /root/.ssh/rootit_tunnel
PUB=$(cat /root/.ssh/rootit_tunnel.pub)
ssh -o BatchMode=yes "root@$EXIT_IP" "id rootit-tun >/dev/null 2>&1 || useradd -m -s /usr/sbin/nologin rootit-tun; passwd -l rootit-tun >/dev/null;
 install -d -m700 -o rootit-tun -g rootit-tun /home/rootit-tun/.ssh;
 echo 'restrict,port-forwarding,from=\"$IRAN_IP\",command=\"/bin/false\" $PUB' > /home/rootit-tun/.ssh/authorized_keys;
 chown rootit-tun: /home/rootit-tun/.ssh/authorized_keys; chmod 600 /home/rootit-tun/.ssh/authorized_keys"
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq haproxy >/dev/null
grep -q rootit_ssh_socks /etc/haproxy/haproxy.cfg || cat "$D/haproxy-rootit-ssh.cfg" >> /etc/haproxy/haproxy.cfg
haproxy -c -f /etc/haproxy/haproxy.cfg -q
sed "s/\${EXIT_IP}/$EXIT_IP/" "$D/rootit-ssh-tunnel@.service" > /etc/systemd/system/rootit-ssh-tunnel@.service
systemctl daemon-reload
for p in 18301 18302 18303 18304; do systemctl enable --now -q "rootit-ssh-tunnel@$p"; done
systemctl enable -q haproxy && systemctl restart haproxy
sleep 4
curl -s -o /dev/null -w "probe %{http_code}\n" --socks5-hostname 127.0.0.1:18300 https://www.gstatic.com/generate_204
