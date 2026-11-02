# Architecture & operations

## Data flow
User → Iran node (`pg-node` container, inbounds VLESS-REALITY:443, VLESS-VISION:2053, VLESS-WS:2083) → one backhaul outbound
`TO-AMS-*` (selected by catch-all rule) → Exit backhaul xray (inbounds reality-bridge, xhttp-bridge via nginx/CDN, direct-tls) → Internet (freedom / optional WARP).
Admin panel traffic from Iran is pinned to TO-AMS-DIRECT through the `PANEL-ADMIN` socks inbound (127.0.0.1:11080, also used for tests).

## Control loop (on Exit/master)
- `vpn-health.timer` → `healthcheck-exit.sh` → runs `path_health.py` on Iran → `/var/lib/pg-node/sync/health.json`
- `vpn-failover.timer` (15 s) → `vpn_failover.py` → reads health + `/var/lib/pasarguard/vpn-path-mode.json` → `vpn_path_lib.put_selector()` → `PUT /api/core/{PG_CORE_ID}?restart_nodes=false`
- `vpn-path` CLI / path-web panel: manual lock (`write_mode`) or `auto`.

## Master mode guarantees
1. `pg_master.py snapshot` saves cores/nodes/hosts/groups/inbounds JSON before any write.
2. `plan` lists additions and **blocks** on name/tag/address collisions.
3. Only objects named `${KIT_PREFIX}-*` are created; their IDs are recorded in `/var/lib/vpn-infra-kit/master-created.json`; rollback deletes only those.
4. The kit core config is bound only to the new node; `put_selector` touches only `PG_CORE_ID` with `restart_nodes=false`.
5. Exit side runs its **own** xray unit (`${KIT_PREFIX}-exit-xray`) — the master's panel/xray/containers are never restarted. nginx is `-t` tested and **reloaded**.
6. nft rules are inserted with comment `vpn-infra-kit:${KIT_PREFIX}` and removed by handle on rollback.
7. Users are not modified; the operator assigns groups/users to the new inbounds in the panel UI.

## Known manual steps (not automatable / not generalized)
- **DNS & CDN dashboards**: Gcore resource + CNAME, Bunny pull zone (account must be funded) + custom hostname + free cert, Cloudflare records (gray for CF/XHTTP, proxied for CFORANGE). `cf_dns.py` can manage CF records with a scoped token.
- **Cloudflare zone settings for CFORANGE**: SSL Full(strict), WebSockets on, HTTP/2 to origin on, Bot Fight off, Email Obfuscation off, Cache Rule bypass for `${XHTTP_PATH}*`, min TLS 1.2.
- **TLS certificates** for Exit (`TLS_CERT_FILE/TLS_KEY_FILE`) and Iran node certs — issue with certbot/acme.sh or copy existing ones.
- **SNI stream map on master :443**: if the master already multiplexes 443 with `ssl_preread`, the new hostnames must be added to its map (reference: `templates/reference/nginx-exit-stream-sni-443.conf`). Shown in plan, applied only after confirmation.
- **nft persistence**: runtime rules are added; persisting into `/etc/nftables.conf` is left to operator review.
- `render_exit_configs.py` / `render_iran_configs.py` are legacy renderers (pre-REALITY, include HY2/TUIC). The source of truth is `templates/iran-core.json.tmpl` and `templates/reference/exit-xray.json.tmpl`, captured from the live system.
- Panels (settle-web, ig-mult-web, sni-watch) are business-specific; installed only in standalone mode.
- Bunny path currently needs a funded account; Gcore was observed unstable from some Iranian DCs — health check handles it.
