# Monitoring

Shared code: `/usr/local/lib/vpn-monitor/` (from `scripts/monitor/`).
Alerts always append `/var/log/monitoring/alerts.log`. Telegram is optional.

## Telegram

BotFather cannot be completed from this server (needs your Telegram account):

1. Open `@BotFather` → `/newbot` → copy the token.
2. On Exit put `TELEGRAM_BOT_TOKEN=...` in `/root/.vpn-secrets/.env` (mode 600).
3. Copy the same token to Iran `/etc/vpn-monitor/secrets.env`.
4. Send any message to the bot, then:
   `python3 /usr/local/lib/vpn-monitor/telegram_setup.py`
   that writes `TELEGRAM_CHAT_ID`.
5. `vpn-mon-test` — five test messages (capacity, hardware, quota, google, boot).

## Units (both hosts)

| Timer / service | Interval |
|---|---|
| `vpn-mon-capacity.timer` | 1 min |
| `vpn-mon-hardware.timer` | 1 min |
| `vpn-mon-quota.timer` | 30 min |
| `vpn-mon-google.timer` | 6 h |
| `vpn-mon-boot.service` | at boot |

Thresholds in `/etc/vpn-monitor/config.env`.

NIC: `rx_errors` / CRC / frame / fifo / missed alert on **any** increase
(driver/hardware). `rx_dropped` on virtio is usually software noise — alert
only if `Δdrop >= NIC_DROP_DELTA` in one 1-minute interval (default 100).

Capacity `CONN_THRESHOLD` is **unique active client IPs** on inbound
TCP `:443`/`:2053` on Iran. It does **not** count TIME_WAIT, outbound
HTTPS to Cloudflare/XHTTP (remote `:443`), loopback `path_health` probes,
or handshake-only scanners. `CONN_THRESHOLD=0` disables that alert.
Exit sets it to 0: `:443` there is Cloudflare XHTTP, not end-users.

Breach alerts re-fire after `COOLDOWN_SEC` (30 min) while still bad.
Recovery/`[OK]` fires **once** on the transition back to healthy. Monitor
state is merged under a lock so the 1-minute capacity/hardware jobs cannot
clobber each other and duplicate that OK.

Iran quota Telegram alerts are **disabled**. The Iranian DC already notifies the
operator by SMS; local vnstat estimates were noisy and often disagreed with
billing. On Iran, `vpn-mon-quota.timer` is disabled. Exit still runs the
German rolling 24h fair-use check.

Germany has **no monthly cap**. Fair-use is **2 TB in any trailing 24 hours**,
then ~200 Mbit/s throttle. The monitor calls
`GET /servers/{id}/metrics/network?hours=24` (10-minute byte/sec buckets;
IN+OUT × interval). Alerts at 60/80/95% of 2 TB in that window, plus throttle
engage/recovery. If SCP REST fails, it falls back to local `vnstat` (last 24h)
and sends at most one Telegram INFO every 6 hours with a Persian explanation —
not a raw `HTTPError`.

OAuth refresh token: `/root/.vpn-secrets/netcup-scp-oauth.json` and
`NETCUP_SCP_REFRESH_TOKEN` in `.env` (mode 600). Use at least every 30 days.
If refresh is rejected: `vpn-mon-netcup-login` (browser device-code).

`NETCUP_VSERVER_NAME` is the SCP **Name** field (`v2202608400527502404`).

## Post-reboot Xray on Iran

`iran-sync-apply` no-ops when `applied.sha256` matches, even if docker `node`
came up without a core. After reboot that left TCP `:443`/`:2053` down.
Apply now POSTs `/start` again if those ports are down.
