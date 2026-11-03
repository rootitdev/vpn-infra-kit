# Extra Iran nodes (same panel, same users)

Model: every Iran node runs the SAME desired state (core + users) that Exit already builds for
the primary Iran node. Nothing changes on the primary node, the core, or users. Add-only:

1. On the new Iran box: Docker + haproxy + nftables (copy primary's), `/opt/pg-node/{node.env,.env}`,
   `/var/lib/pg-node/certs`, `/root/.pg_nodes/certs`, `iran_sync_apply.py` + `iran-sync-apply.timer`,
   `path_health.py`, `vpn_paths.py`, `pg-node-run.sh` (preload image via `docker save|ssh docker load`
   when Docker Hub returns 403), SSH path (`iran/ssh-path/setup-ssh-path.sh`, user rootit-tun key
   restricted with `from=NEW_IP`), RoOtIt-backup timer (BACKUP_TG_PROXY=socks5h://127.0.0.1:18300).
2. Exit: add Exit root key to the new box; `/etc/nftables.conf` line for NEW_IP on 8444/9443;
   `/root/.vpn-secrets/extra-iran-iran2.env` with `EXTRA_IRAN_IP=` and `EXTRA_IRAN_NAME=iran2`;
   enable `extra-iran-sync-export@iran2.timer` and `extra-iran-stats@iran2.timer`.
3. Panel: add hosts that copy the primary REALITY / VISION hosts with `address=[NEW_IP]`
   (same inbound tags, so every user's subscription gets the extra node).

Limits: the backhaul selector is shared (failover is driven by the primary node's health), so all
nodes use the same path; per-node selection would need per-node cores. Node uplink/downlink in the
panel is summed into node 1; user usage is correct.
