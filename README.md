# vpn-infra-kit

Iran ⇄ Exit (Germany) tunnel stack built on **Pasarguard** with multi-path backhaul, real-traffic health checks,
automatic failover, admin/sales panels, and encrypted daily backups. Everything is templated; no secrets are stored here.

## Modes
| Mode | Use when | What gets created |
|---|---|---|
| `standalone` | fresh Exit server, own panel | Pasarguard + exit xray + nginx + panels + Iran node + failover + backup |
| `master` | an **existing** Pasarguard (latest dev) master already serving other nodes | ADD-ONLY: dedicated `${KIT_PREFIX}-exit-xray` unit, a new core config + node + hosts (all `${KIT_PREFIX}-*`), scoped nft rules, one nginx `conf.d` file (reload, never restart). Existing nodes/inbounds/hosts/users are never modified. |

## Backhaul paths (Iran → Exit)
Priority (auto failover): **REALITY → XHTTP → GCORE → BUNNY → CF gray → DIRECT**. `CFORANGE` = watch-only canary.
| Tag | Transport | Notes |
|---|---|---|
| TO-AMS-REALITY | VLESS+REALITY tcp → `EXIT_IP:REALITY_PORT` | nft allows only `IRAN_IP`; SNI `REALITY_SERVER_NAME` |
| TO-AMS-XHTTP | VLESS+XHTTP via `XHTTP_DOMAIN` | hides Exit IP if proxied by a CDN |
| TO-AMS-GCORE | XHTTP via Gcore CDN (`GCORE_DOMAIN`) | optional |
| TO-AMS-BUNNY | XHTTP via Bunny pull zone (`BUNNY_DOMAIN`) | optional; needs funded Bunny account + custom-host cert |
| TO-AMS-CF | XHTTP via `CF_GRAY_DOMAIN` (DNS-only) | effectively direct to Exit IP |
| TO-AMS-DIRECT | VLESS+TLS tcp → `EXIT_IP:DIRECT_TLS_PORT` | last resort |
| TO-AMS-CFORANGE | XHTTP via CF proxied `CFORANGE_DOMAIN` | watch-only; promote after ≥2 days stable |

Health (`scripts/path_health.py`, runs on Iran) pushes **real traffic** through each outbound (generate_204) — an edge
answering 400 is NOT healthy. Failover (`vpn_failover.py`, every 15 s): switch away after 3 failures, fail back after 5 successes.
The active path is pinned by a catch-all routing rule in the node's core config (`vpn_path_lib.put_selector`), pushed with `restart_nodes=false`.

## Quick start
```bash
git clone https://github.com/<owner>/vpn-infra-kit /opt/vpn-infra-kit && cd /opt/vpn-infra-kit
install -d -m 700 /root/.vpn-secrets && cp .env.example /root/.vpn-secrets/.env && chmod 600 /root/.vpn-secrets/.env
# fill values (never paste them into chat)
./install.sh --plan                      # preflight + full change list, applies nothing
./install.sh --phase gen --yes
for p in exit iran paths failover backup verify; do ./install.sh --phase $p; done
```
Rollback: `./rollback.sh --list | --exit --yes | --master-objects --yes | --restore <TS> --yes`.
Secret scan before every push: `installer/secret-scan.sh` (add your own real domains/IPs to the gitignored `.scan-deny`).

## Layout
```
install.sh  rollback.sh  .env.example  PROMPT.md
installer/  lib.sh render.py secret-scan.sh
master/     pg_master.py  (snapshot / plan / apply / rollback against Pasarguard API, add-only)
scripts/    path/failover/health/backup/sync/provisioning scripts (control host)
iran/sbin/  Iran-side helpers (pg-node runner, vpn-path stub, xray wrap)
panels/     path-web (path switcher), settle-web (sales/settlement + /pay portal), ig-mult-web (usage multiplier), sni-watch
templates/  iran-core.json.tmpl (node core config), reference/ (exit xray, nginx, nftables as deployed)
systemd/    exit/ and iran/ units + timers
configs/    nginx/nft/service snippets (legacy, used by panel installers)
patches/    Pasarguard node-bridge patch (REST)
docs/       ARCHITECTURE.md, legacy/ (original runbooks)
```
## Not generalized / manual
See docs/ARCHITECTURE.md → "Known manual steps".
