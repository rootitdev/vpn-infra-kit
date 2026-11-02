# Gcore / Bunny CDN standby (XHTTP)

## Live hostnames
- **Bunny (working from Iran):** `${BUNNY_DOMAIN}` → pullzone `vpn-bunny-backhaul` → origin `${EXIT_IP}` with Host/SNI `${GCORE_CNAME_DOMAIN}`
- **Gcore:** `${GCORE_DOMAIN}` → account CNAME `${GCORE_CDN_HOSTNAME}` → same origin. Edge may return `503 Default Vhost` until SSL/vhost fully activates; `.ir` CNAMEs are rejected by Gcore as reserved. `*.${EXTRA_ZONE}` is DNS-hijacked inside Iran (`${IRAN_PRIVATE_IP}`).

## Iran Xray tags
- `TO-AMS-BUNNY` → `${BUNNY_DOMAIN}`
- `TO-AMS-GCORE` → `${GCORE_DOMAIN}`
- Secrets: `GCORE_API_TOKEN`, `BUNNY_API_KEY` in `/root/.vpn-secrets/.env`
- Meta: `/root/.vpn-secrets/cdn-standby.json`

## Notes
TUIC UDP backhaul removed. Keep balancer on DIRECT until Gcore probe returns HTTP 400 + `x-padding` from Iran and a socks tunnel test succeeds.

## CF orange canary
- Hostname: `${CFORANGE_DOMAIN}` (Cloudflare **proxied**/orange)
- Xray tag: `TO-AMS-CFORANGE` (WATCH_ONLY — not in auto failover)
- UI: کارت «CF orange (canary)» در `/path/`
- Manual test: `vpn-path cforange` (only for deliberate test; keep clients on DIRECT otherwise)
- Bring back to circuit only after multi-day healthy tunnel probes from Iran.
