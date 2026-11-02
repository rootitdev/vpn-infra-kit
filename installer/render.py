#!/usr/bin/env python3
"""Copy the kit to a staging dir, substituting ${VAR} ONLY for variables declared in .env.example.
Shell/python variables that are not kit variables are left untouched. Missing kit vars render as ''."""
import os, re, shutil, sys
root, out = sys.argv[1], sys.argv[2]
keys = {l.split('=',1)[0] for l in open(os.path.join(root,'.env.example')) if re.match(r'^[A-Z_][A-Z0-9_]*=', l)}
keys |= {'SECRET'}
pat = re.compile(r'\$\{(' + '|'.join(sorted(keys, key=len, reverse=True)) + r')\}')
if os.path.exists(out): shutil.rmtree(out)
for d in ('scripts','panels','iran','configs','systemd','templates','patches','master'):
    src=os.path.join(root,d)
    if not os.path.isdir(src): continue
    for dp,_,fs in os.walk(src):
        for f in fs:
            s=os.path.join(dp,f); t=os.path.join(out,os.path.relpath(s,root)); os.makedirs(os.path.dirname(t),exist_ok=True)
            b=open(s,'rb').read()
            try: txt=b.decode()
            except UnicodeDecodeError: shutil.copy2(s,t); continue
            open(t,'w').write(pat.sub(lambda m: os.environ.get(m.group(1),''), txt)); shutil.copymode(s,t)
print('rendered to', out)
