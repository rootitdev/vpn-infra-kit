# Backhaul failover

Live selector lives in **panel core `iran-xray`**, then Iran docker Xray via the
desired-state sync (`docs/control-plane.md`). `vpn-path` on Iran is a stub.

On Exit:

```
vpn-path status|auto|cf|xhttp|direct|tuic|publish|test
```

## Priority

1. `TO-AMS-CF` — `${CF_GRAY_DOMAIN}:443` XHTTP
2. `TO-AMS-XHTTP` — `${XHTTP_DOMAIN_ALT}:443` XHTTP
3. `TO-AMS-DIRECT` — `${EXIT_IP}:9443` VLESS+TLS
4. `TO-AMS-TUIC` — listed but **not usable today** (QUIC/UDP DPI from ${IRAN_PROVIDER})

HY2 is removed. TUIC stays last in the list so a future non-QUIC fix can plug in without a redesign. If CF+XHTTP+DIRECT are all down, the daemon logs `ALERT NO_FALLBACK` and **keeps the last selector**; Iran inbounds `:443`/`:2053` stay up (clients are not kicked), but internet via backhaul is dead until a path recovers.

## Daemon

`vpn-failover.timer` on Exit (`OnUnitInactiveSec=15s`):

- SSH `path_health.py` (TLS/HTTP, not ping) on Iran
- 3 consecutive failures of the pinned path → next healthy tag
- Fail back to a higher-priority path after **5** consecutive successes

Logs: `/var/log/vpn-path/failover.log`

No Telegram bot exists in this repo.
