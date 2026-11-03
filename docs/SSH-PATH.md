# TO-AMS-SSH backhaul path

Why: some Iranian DCs let short flows (health 204) through but stall every proxied
TCP flow after ~15 KB (REALITY/DIRECT/CDN all affected). Plain SSH on :22 was not
throttled (measured 2026-11-03: SSH 14–27 Mbit/s single, 29 Mbit/s with 8 streams; REALITY/DIRECT ~0).

Layout (Iran): `rootit-ssh-tunnel@18301..18304` (ssh -D, keepalive 10s) → haproxy
`127.0.0.1:18300` (leastconn) ← xray outbound `TO-AMS-SSH` (socks).
Exit: locked user `rootit-tun`, key `restrict,port-forwarding,from=IRAN_IP`. No sshd change.

Install: `EXIT_IP=.. IRAN_IP=.. iran/ssh-path/setup-ssh-path.sh` on Iran, then
`python3 scripts/add_ssh_outbound.py` on Exit. Priority (standalone):
REALITY, SSH, GCORE, BUNNY, XHTTP, CF, DIRECT.

Health: `path_health.py` now also needs a 1 MB download ≥ 1 Mbit/s per path
(`THRU_URLS`), so 15 KB-stall paths fail and failover moves to SSH.

Caveats: TCP-over-TCP (head-of-line under loss), no UDP, depends on :22 staying unthrottled.
Disable: `systemctl disable --now rootit-ssh-tunnel@1830{1..4}` and pick another path.
