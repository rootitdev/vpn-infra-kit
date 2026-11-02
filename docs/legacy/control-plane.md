# Control plane: panel (Exit) → desired-state files → Iran agent

Live Iran Xray is the docker `pasarguard/node` process. It spawns
`xray -c stdin:` from `/var/lib/pg-node/generated/xray.json` **only when**
the node handles `POST /start`. Editing systemd
`/root/.pg_nodes/iran/xray.json` has no effect.

Germany `POST https://<iran>:62050/start` is **not used**. The node returns
200 but the panel HTTP client times out on the body, retries, and takes
`LockControl`. The panel node row stays `disabled` / `keep_alive=0`.

## Queue

| Where | Path |
|---|---|
| Exit copy | `/var/lib/pasarguard/iran-sync/state.bin` + `state.sha256` |
| Iran queue | `/var/lib/pg-node/sync/state.bin` + `state.sha256` |
| Applied | `/var/lib/pg-node/sync/applied.sha256` |

The blob is a full PasarGuard `Backend` protobuf (core JSON + all active users).
Applying the same sha256 twice is a no-op.

## Tick

1. Exit `iran-sync-export.timer` every **10s** rebuilds proto from panel sqlite and SCPs if hash changed.
2. Iran `iran-sync-apply.timer` every **10s** POSTs `https://127.0.0.1:62050/start` if `state.sha256 != applied.sha256`.
3. Iran **must not** poll `panel:2096` on the public IP. Direct HTTPS to the Exit IP
   (any port, including 2096 and 4444) completes TLS then DPI drops HTTP.
   The queue stays SSH-push + local apply. This panel-via-backhaul path is
   **only for humans/API from Iran**, not for node sync.

## Add/remove a user

Use the panel UI as usual (from a VPN client, or via the SOCKS below).
Within ~10–20s the export hash changes and Iran `/start`s.
Do not Enable the node in the UI.

Logs: `/var/log/vpn-path/sync.log` on Iran.

## Traffic stats while the node is `disabled`

The panel job `record_usages` only queries nodes that are connected. With the
row `disabled` / `keep_alive=0`, UI usage and `online_at` stay at zero even
though Xray is serving clients. We do **not** Enable the node (that reopens
Germany `POST /start`).

Instead Exit `iran-stats.timer` (30s) SSHs to Iran and runs `xray api
statsquery` on the local API inbound, then writes deltas into panel sqlite
(`users.used_traffic` / `online_at`, `nodes.uplink` / `downlink`). No `/start`.

Per-user counters appear after the next VLESS session (emails are panel user
ids). SOCKS admin traffic is not a panel user so it only shows on the node
totals. `online_at` is updated when that user has a positive traffic delta
in the interval (PasarGuard’s usual “recently online” signal).

Writes use `PRAGMA journal_mode=WAL`, `busy_timeout=30s`, `BEGIN IMMEDIATE`,
and retry on `database is locked`. Panel API reads stay unblocked during those
writes.

Logs: `/var/log/vpn-path/stats.log` on Exit.

## Panel access from Iran (via backhaul)

Direct `https://${PANEL_DOMAIN}:2096/` from an Iran IP is not reliable.
The hostname used to match the `.ir → DIRECT` rule, so Xray sent panel HTTP
straight to Germany and DPI ate it. That rule is now bypassed.

Iran core routing (before the `.ir` DIRECT catch-all):

`full:${PANEL_DOMAIN}` / `${PANEL_DOMAIN_ALT}` / `${PANEL_DOMAIN_EXTRA}`
→ outbound `TO-AMS-DIRECT` (always). User VLESS still uses balancer `backhaul`.

Pinning the VPN path to CF/XHTTP must **not** move panel admin HTTP onto that
same pin — otherwise Iran nginx → subproxy → panel returns **502** while VPN
clients still work. Panel stays on the direct backhaul tunnel.

On Exit, those same hostnames go to outbound `PANEL-LOCAL`
(`freedom` redirect `127.0.0.1:2096` nginx). The HTTP never crosses the
Iran–DE path in the clear.

### From a laptop in Iran (normal admin)

1. Connect the usual client to Reality `:443` or Vision `:2053`.
2. Open `https://${PANEL_DOMAIN}:2096/dashboard/`
3. Do not use the raw Exit IP in the browser; use the `panel.*` hostname.

### From the Iran server itself

Local SOCKS already exists: `127.0.0.1:11080` (xray inbound tag `PANEL-ADMIN`,
localhost-only, excluded from user assignment). It is not the Hysteria2 protocol.

```
curl -k --socks5-hostname 127.0.0.1:11080 \
  https://${PANEL_DOMAIN}:2096/dashboard/
```

Firefox on the VPS: Settings → Network → Manual proxy → SOCKS5
`127.0.0.1:11080`, proxy DNS.

Proof (22 Aug 2026): socks dashboard HTTP 200 in 0.49s; direct same URL
timeout 0 bytes. Xray: `${PANEL_DOMAIN}:2096 [PANEL-ADMIN -> TO-AMS-CF]`.
API list/add/delete user through that SOCKS returned 200/201/204. Sync
timers stayed active; node row still `disabled`.
