# Cutover checklist (future production users)

Do **not** import old users yet.

1. Confirm Phase 0 from a real Iran mobile (MCI) at evening peak — this session only used the ${IRAN_PROVIDER} relay once.
2. Rotate secrets that appeared in chat: Cloudflare API token, root passwords, then `ssh` keys if needed.
3. Issue `$GCORE_API_TOKEN` and follow `docs/gcore-standby.md` if you want a second CDN.
4. Panel: `https://${PANEL_DOMAIN}:2096/dashboard/`. Exit TCP 443 is XHTTP only (not the panel). Do not point PG at the same Xray JSON we manage, or it will overwrite backhaul.
5. Create production users in one place only (panel **or** `/root/.pg_nodes/iran/xray.json` + HY2 userpass).
6. Replace test UUIDs; regenerate `/root/.pg_nodes/test-subs/` with `python3 /root/vpn-infra/scripts/gen_subs.py`.
7. Import on Windows (v2rayN), Android (v2rayNG), iOS (Streisand/Shadowrocket) using files in `/root/.pg_nodes/test-subs/` (QR PNGs included).
8. Enable client-side Reality **fragment** in the app (tlshello) — server inbound cannot fragment the client's ClientHello.
9. Tighten Exit SSH (now key-only but still world-open on 22) to your admin IPs.
10. Restore drill: decrypt a backup from `/root/.pg_nodes/backups/` with `$BACKUP_PASSPHRASE`.
