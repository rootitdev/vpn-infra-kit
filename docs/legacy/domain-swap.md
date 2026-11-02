# Domain / path reassignment

Primary after Phase 0: **${MAIN_ZONE}** (`${EXTRA_ZONE}` is DNS-hijacked to `${IRAN_PRIVATE_IP}` from Iran).
Live XHTTP domain: **${XHTTP_DOMAIN_ALT}**.
Cold: `${EXTRA_ZONE}` records exist for later.

## What must change together

1. Cloudflare DNS A/CNAME (script: `python3 /root/vpn-infra/scripts/cf_dns.py upsert NAME IP proxied ZONE_ID`)
2. Let's Encrypt SAN list (`certbot certonly --cert-name vpn-stack --dns-cloudflare ...`)
3. Iran Xray outbound `address` / `serverName` / `xhttpSettings.host` in `/root/.pg_nodes/iran/xray.json`
4. Exit TLS cert already covers current names; add SAN before switching
5. Client-facing `ir.<domain>` in `/root/.pg_nodes/test-subs/` and HY2/Vision SNI
6. `systemctl restart xray` on both hosts; `vpn-path auto`

## One-command sketch (after editing the four hostname variables)

```bash
# example: move XHTTP from ${XHTTP_DOMAIN_ALT} to ${XHTTP_DOMAIN}
python3 - << 'PY'
import json
from pathlib import Path
p=Path("/root/.pg_nodes/iran/xray.json")
c=json.loads(p.read_text())
for ob in c["outbounds"]:
    if ob.get("tag")=="TO-AMS-XHTTP":
        ob["settings"]["vnext"][0]["address"]="${XHTTP_DOMAIN}"
        ob["streamSettings"]["tlsSettings"]["serverName"]="${XHTTP_DOMAIN}"
        ob["streamSettings"]["xhttpSettings"]["host"]="${XHTTP_DOMAIN}"
p.write_text(json.dumps(c, indent=2))
PY
scp /root/.pg_nodes/iran/xray.json root@${IRAN_IP}:/root/.pg_nodes/iran/
ssh root@${IRAN_IP} 'xray run -test -config /root/.pg_nodes/iran/xray.json && systemctl restart xray'
```

Secrets stay in `/root/.vpn-secrets/.env` only.
