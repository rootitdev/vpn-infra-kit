#!/usr/bin/env python3
"""Build node /start protobuf from panel sqlite. Writes /tmp/pg-start-users.bin. No secrets printed."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

from PasarGuardNodeBridge import create_proxy, create_user
from PasarGuardNodeBridge.common import service_pb2 as service

sys.path.insert(0, "/tmp")
try:
    from instagram_multiplier import inject_into_core, load_settings
except ImportError:
    inject_into_core = None  # type: ignore
    load_settings = None  # type: ignore

c = sqlite3.connect("/var/lib/pasarguard/db.sqlite3")
c.execute(
    "update nodes set status='disabled', keep_alive=0, connection_type='rest' where id=1"
)
# Keep the row present (client entry is this node) but never let the panel
# issue Germany→Iran /start. Desired state is applied by iran-sync-apply.
c.commit()
cfg, exclude = c.execute("select config,exclude_inbound_tags from core_configs where id=2").fetchone()
excl = [x.strip() for x in (exclude or "").split(",") if x.strip()]
if inject_into_core is not None:
    cfg_obj = json.loads(cfg) if isinstance(cfg, str) else cfg
    inject_into_core(cfg_obj, load_settings("/tmp/ig-mult"))
    cfg = json.dumps(cfg_obj, separators=(",", ":"))
rows = c.execute(
    """
select u.id, u.proxy_settings, group_concat(distinct pi.tag)
from users u
left join users_groups_association uga on u.id=uga.user_id
left join groups g on uga.groups_id=g.id and g.is_disabled=0
left join inbounds_groups_association iga on g.id=iga.group_id
left join inbounds pi on iga.inbound_id=pi.id
where u.status in ('active','on_hold')
group by u.id
"""
).fetchall()
users = []
for uid, settings, tags in rows:
    settings = json.loads(settings) if isinstance(settings, str) else (settings or {})
    inbounds = [t for t in (tags.split(",") if tags else []) if t]
    if not inbounds:
        continue
    vless = (settings.get("vless") or {}).get("id")
    users.append(create_user(str(uid), create_proxy(vless_id=vless), inbounds))
req = service.Backend(
    type=service.BackendType.XRAY,
    config=cfg,
    users=users,
    keep_alive=0,
    exclude_inbounds=excl,
)
raw = req.SerializeToString()
Path("/tmp/pg-start-users.bin").write_bytes(raw)
print(len(users), hashlib.sha256(raw).hexdigest(), len(raw))
