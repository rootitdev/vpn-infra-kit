# SSH backhaul paths (second + third)

## Why

Some Iranian DCs let short flows (health 204) through but stall every proxied TCP
flow after ~15 KB (REALITY/DIRECT/CDN all affected). Plain SSH on :22 is often
still open (measured 2026-11-03 on Netcup: SSH 14–27 Mbit/s).

When **WaterWall** and **direct VLESS to NL** are both blocked, operators still
need a working exit. This kit keeps **two** SSH SOCKS backhauls:

| Tag | From (Iran) | To | Local haproxy | Role |
|-----|-------------|-----|---------------|------|
| `TO-AMS-SSH` | Shetaban | Netcup / AMS Exit `:22` | `127.0.0.1:18300` | Primary SSH path (already in production) |
| `TO-NL-SSH` | Shetaban | MobinHost NL `:22` | `127.0.0.1:18400` | **Third path** — VPN over SSH when WW + direct NL die |

Failover order (standalone default): REALITY → **SSH-Netcup** → **SSH-NL** → GCORE → Bunny → XHTTP → CF → DIRECT.

## Layout (Iran)

### TO-AMS-SSH (Netcup)

`rootit-ssh-tunnel@18301..18304` (`ssh -D`) → haproxy `127.0.0.1:18300` ← xray outbound `TO-AMS-SSH`.

Install: `EXIT_IP=.. IRAN_IP=.. iran/ssh-path/setup-ssh-path.sh` on Iran, then
`python3 scripts/add_ssh_outbound.py` on the panel host.

### TO-NL-SSH (MobinHost NL)

`rootit-ssh-tunnel-nl@18401..18404` → haproxy `127.0.0.1:18400` ← xray outbound `TO-NL-SSH`.

```bash
# On Iran (Shetaban)
NL_EXIT_IP=185.19.33.221 IRAN_IP=193.228.90.107 \
  ./iran/ssh-path/setup-ssh-path-nl.sh

# On panel (NL)
python3 scripts/add_nl_ssh_outbound.py
```

Exit side: locked user `rootit-tun`, key
`restrict,port-forwarding,from=IRAN_IP`. No sshd_config change.

## Health / path-web

`path_health.py` probes include both SSH tags. In `/path/` UI:

- **SSH → Netcup** = `TO-AMS-SSH`
- **SSH → هلند** = `TO-NL-SSH` (manual lock: mode `ssh-nl`)

## Caveats

- TCP-over-TCP (head-of-line under loss), no UDP, depends on `:22` staying unthrottled.
- Disable NL path: `systemctl disable --now rootit-ssh-tunnel-nl@1840{1..4}` and pick another path in `/path/`.
- Shahrah emergency port-forward (`deploy/install-ssh-fallback.sh`) is a thinner L-forward for ops smoke tests; production client traffic should use these SOCKS outbounds.

## Related

- Panel reverse tunnels (watch/path UI): separate from client backhaul — see stabilize notes.
- WaterWall durability: `shahrah` durability/WW commits; SSH is the fallback when WW dies.
