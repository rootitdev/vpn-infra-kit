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

## Control link (panel ⇄ node) — `ctl/gen_ctl.py`
```
Pasarguard panel ──► CTL_NODE_ADDRESS:CTL_LOCAL_PORT  (dokodemo "${KIT_PREFIX}-ctl-in", local-only, kit Exit xray)
                     └► reverse portal "${KIT_PREFIX}-ctl-portal" (domain ctl.${KIT_PREFIX}.internal)
                         ◄══ tunnel (XHTTP via CDN / REALITY) ══ Iran "${KIT_PREFIX}-ctl-bridge" (dials OUT)
                                                                   └► freedom redirect 127.0.0.1:PG_NODE_PORT (pg-node API)
```
- Plan: `./install.sh --plan` prints the ctl line (ports, units, nft table, which paths carry it).
- Apply: `--phase exit` (adds portal + entry into the kit's own xray config), `--phase iran` (binds node API to 127.0.0.1, runs `ctl`),
  or `--phase ctl` alone. `paths` registers the node on the panel with the ctl address/port.
- Verify: `--phase verify` checks the Exit entry port listens, `${KIT_PREFIX}-ctl-bridge` is active on Iran, the node API is bound to 127.0.0.1,
  and that `IRAN_IP:PG_NODE_PORT` is NOT reachable from outside (unless fallback). Then the panel must show node `${KIT_PREFIX}-iran` connected.
- Rollback: `./rollback.sh --ctl --yes` (stops the bridge, removes the nft table). To go back to direct quickly: set `CTL_MODE=direct`,
  rerun `--phase iran` (node API rebinds to 0.0.0.0, nft allows only EXIT_IP) and update the node address in the panel.
- The control link uses a balancer of its own (leastPing over `CTL_PATHS`) and is independent of the user-traffic failover selector.
- Docker note: if the panel container is not on host networking, `127.0.0.1` inside it is the container itself. Set
  `CTL_LISTEN` and `CTL_NODE_ADDRESS` to the docker bridge gateway (e.g. 172.17.0.1); that address is not routable from outside.

## Mode compatibility
Standalone and master use identical Iran-side components, health, failover, backup and control link.
Master-only: `master/pg_master.py` (add-only API), prefixed inbound tags (`INBOUND_PREFIX`), panels skipped by default,
CDN-first default priority. Standalone-only: Pasarguard bootstrap (`pg_bootstrap_panel.py`) and the business panels.
