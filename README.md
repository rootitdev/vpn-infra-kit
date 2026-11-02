# vpn-infra-kit

Iran ⇄ Exit (Germany) tunnel stack built on **Pasarguard** with multi-path backhaul, real-traffic health checks,
automatic failover, admin/sales panels, and encrypted daily backups. Everything is templated; no secrets are stored here.

## Modes — pick one with `INSTALL_MODE=standalone|master` (required)
| | `standalone` (no master — like the original two-server setup) | `master` (attach to a friend's existing Pasarguard master) |
|---|---|---|
| Exit server | fresh; kit installs Pasarguard panel, exit xray, nginx | existing master serving other nodes; kit only ADDS |
| Panel | own Pasarguard + path-web, settle-web (/settle, /pay), ig-mult-web, sni-watch | master's existing panel; kit panels skipped (optional path-web via `INSTALL_PANELS=1`) |
| Objects created | everything | `${KIT_PREFIX}-exit-xray` unit, core `${KIT_PREFIX}-iran-core`, node `${KIT_PREFIX}-iran`, inbounds/hosts `${KIT_PREFIX}-*`, nft rules commented `vpn-infra-kit:${KIT_PREFIX}`, `conf.d/${KIT_PREFIX}-xhttp.conf` |
| Restarts on Exit | as needed (fresh box) | none of the master's services; only our own unit; nginx `reload` |
| Default `PATH_PRIORITY` | reality,xhttp,gcore,bunny,cf,direct | xhttp,gcore,cf,reality,direct (CDN-first to hide the master IP) |
| Control link (panel→node) | tunnel (default) | tunnel (default) |
| Rollback | `rollback.sh --restore/--exit/--ctl` | same + `--master-objects` (deletes only kit-recorded IDs) |

Both modes share the same scripts, templates, health/failover and backup; only the Exit-side phases differ.
`install.sh` refuses to run if `INSTALL_MODE` is not set. CFORANGE is watch-only in both modes.

### Panel ⇄ node control link (`CTL_MODE`)
- `tunnel` (default): the Iran node API binds to 127.0.0.1 only. A dedicated Iran xray `${KIT_PREFIX}-ctl-bridge` dials out
  through the tunnel (`CTL_PATHS`, default XHTTP + REALITY, leastPing) to a reverse **portal** in the kit's own Exit xray.
  The panel connects to `CTL_NODE_ADDRESS:CTL_LOCAL_PORT` (local-only on the Exit/master). Nothing listens publicly for the node API.
- `direct`: classic panel → `IRAN_IP:PG_NODE_PORT`. Iran nft table `${KIT_PREFIX}_ctl` accepts that port only from `EXIT_IP`.
- `CTL_DIRECT_FALLBACK=1`: tunnel + the direct path kept open (EXIT_IP only) for emergencies.
On master, existing nodes keep their own addresses/ports; only the new node uses the control link.

### Target guard
Put the IPs of servers this kit must NEVER touch (e.g. your own existing production servers) in
`/root/.vpn-secrets/target-deny.txt` or `.target-deny` in the repo root (gitignored), one IP/CIDR per line.
`install.sh`/`rollback.sh` abort if `EXIT_IP` or `IRAN_IP` matches.

## Backhaul paths (Iran → Exit)
Priority (auto failover) = `PATH_PRIORITY` or the mode default (see table above). `CFORANGE` = watch-only canary.
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
for p in exit iran ctl paths hosts failover backup verify; do ./install.sh --phase $p; done
```
Rollback: `./rollback.sh --list | --exit --yes | --master-objects --yes | --restore <TS> --yes`.
Secret scan before every push: `installer/secret-scan.sh` (add your own real domains/IPs to the gitignored `.scan-deny`).

## Layout
```
install.sh  rollback.sh  .env.example  PROMPT.md
installer/  lib.sh render.py secret-scan.sh
ctl/        gen_ctl.py  (panel<->node control link: reverse portal/bridge configs)
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

### Hosts & groups (`--phase hosts`)
`master/pg_master.py hosts` (dry-run) / `hosts --yes`: creates one subscription host per kit inbound, named by
`HOST_REMARK_TEMPLATE` (e.g. `fk1-VLESS-REALITY`), and APPENDS the kit inbound tags to the groups in `PG_GROUPS`
(optionally creates them with `PG_GROUP_CREATE=1`). Existing hosts/groups/users are never edited beyond the appended tags;
everything is recorded for `rollback.sh --master-objects --yes` (which removes only the appended tags, never a group).
Auth: `PASARGUARD_API_KEY` (pg_key_…, sent as `X-Api-Key`) or admin login.
