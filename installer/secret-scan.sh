#!/usr/bin/env bash
# Pre-push secret scan. Exit 1 on findings. Prints file:line + rule only, never the matched value.
# Put operator-specific strings (real domains/IPs/handles), one regex per line, in .scan-deny (gitignored).
cd "$(dirname "$0")/.." && exec python3 - <<'P'
import os,re,sys,ipaddress
rules={
 'private-key':r'BEGIN [A-Z ]*PRIVATE KEY',
 'telegram-token':r'\b[0-9]{8,10}:[A-Za-z0-9_-]{35}\b',
 'github-token':r'\bgh[pousr]_[A-Za-z0-9]{30,}',
 'cloudflare-token':r'\b[A-Za-z0-9_-]{40}\b(?=.*(?:token|bearer|authorization))',
 'assigned-secret':r'(?i)(token|passw(or)?d|pass|secret|private_?key|api_?key|passphrase)\s*[=:]\s*["\']?(?!\$\{|REPLACE|<|change|xxx|your|os\.environ|env)[A-Za-z0-9_+/=-]{12,}(?![A-Za-z0-9_(.])',
 'uuid':r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b',
 'x25519-json':r'"(privateKey|secretKey)"\s*:\s*"(?!\$\{)[A-Za-z0-9_+/-]{40,}"',
}
deny=[l.strip() for l in open('.scan-deny')] if os.path.exists('.scan-deny') else []
deny=[d for d in deny if d and not d.startswith('#')]
skip={'.git'}; bad=0
ipre=re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')
for dp,dn,fs in os.walk('.'):
  dn[:]=[d for d in dn if d not in skip]
  for f in fs:
    p=os.path.join(dp,f)
    if f in('secret-scan.sh','.scan-deny','.target-deny'): continue
    try: L=open(p,encoding='utf-8').read().splitlines()
    except Exception: continue
    for i,l in enumerate(L,1):
      for n,r in rules.items():
        if re.search(r,l): print(f'FOUND {n}: {p}:{i}'); bad+=1
      for d in deny:
        if re.search(d,l): print(f'FOUND denylist: {p}:{i}'); bad+=1
      for m in ipre.findall(l):
        try: a=ipaddress.ip_address(m)
        except ValueError: continue
        if a.is_global and m not in ('1.1.1.1','8.8.8.8','8.8.4.4','1.0.0.1') and not m.endswith('.0'):
          print(f'FOUND public-ip: {p}:{i}'); bad+=1
print('secret-scan: CLEAN' if not bad else f'secret-scan: FAILED ({bad})'); sys.exit(1 if bad else 0)
P
