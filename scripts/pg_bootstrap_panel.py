#!/usr/bin/env python3
"""Create PasarGuard core/group/hosts/users inside the panel container.

Reads /tmp/iran-xray.json and /tmp/pg-bootstrap-input.json (no stdout secrets).
Writes ids to /var/lib/pasarguard/bootstrap-ids.json and API key to
/var/lib/pasarguard/panel-api-key (mode 600).
"""
from __future__ import annotations

import asyncio
import json
import os
from copy import deepcopy
from pathlib import Path
from uuid import UUID

CORE_JSON = Path("/tmp/iran-xray.json")
INPUT = Path("/tmp/pg-bootstrap-input.json")
IDS_OUT = Path("/var/lib/pasarguard/bootstrap-ids.json")
KEY_OUT = Path("/var/lib/pasarguard/panel-api-key")
CERT = Path("/tmp/pg-node.crt")


def empty_clients(cfg: dict) -> dict:
    out = deepcopy(cfg)
    for inbound in out.get("inbounds", []):
        tag = inbound.get("tag")
        if tag in ("VLESS-REALITY", "VLESS-VISION"):
            settings = inbound.setdefault("settings", {})
            settings["clients"] = []
            settings["decryption"] = "none"
    return out


async def owner_details(db):
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.db.models import Admin
    from app.models.admin import AdminDetails, AdminRoleData

    q = await db.execute(select(Admin).options(selectinload(Admin.role)))
    admins = list(q.scalars().all())
    if not admins:
        raise RuntimeError("no admin in database")
    picked = admins[0]
    for admin in admins:
        if admin.role is not None and bool(getattr(admin.role, "is_owner", False)):
            picked = admin
            break
    role = AdminRoleData.model_validate(picked.role) if picked.role is not None else None
    return AdminDetails.model_validate(
        {
            "id": picked.id,
            "username": picked.username,
            "telegram_id": picked.telegram_id,
            "discord_webhook": picked.discord_webhook,
            "sub_domain": picked.sub_domain,
            "profile_title": picked.profile_title,
            "support_url": picked.support_url,
            "custom_variables": picked.custom_variables,
            "notification_enable": picked.notification_enable,
            "total_users": 0,
            "used_traffic": picked.used_traffic or 0,
            "data_limit": picked.data_limit,
            "status": picked.status,
            "sub_template": picked.sub_template,
            "lifetime_used_traffic": 0,
            "note": picked.note,
            "role": role,
            "permission_overrides": picked.permission_overrides,
        }
    )


async def main() -> None:
    inp = json.loads(INPUT.read_text())
    cfg = empty_clients(json.loads(CORE_JSON.read_text()))

    from app.db import GetDB
    from app.models.core import CoreCreate, CoreType
    from app.models.group import GroupCreate
    from app.models.host import CreateHost
    from app.models.node import NodeCreate
    from app.models.user import UserCreate
    from app.models.proxy import ProxyTable, VlessSettings
    from app.models.api_key import APIKeyCreate
    from app.operation import OperatorType
    from app.operation.core import CoreOperation
    from app.operation.group import GroupOperation
    from app.operation.host import HostOperation
    from app.operation.node import NodeOperation
    from app.operation.user import UserOperation
    from app.operation.api_key import APIKeyOperation
    from app.db.models import UserStatus, NodeConnectionType, DataLimitResetStrategy, ProxyHostSecurity, ProxyHostFingerprint, ProxyHostALPN

    core_op = CoreOperation(operator_type=OperatorType.API)
    group_op = GroupOperation(operator_type=OperatorType.API)
    host_op = HostOperation(operator_type=OperatorType.API)
    node_op = NodeOperation(operator_type=OperatorType.API)
    user_op = UserOperation(operator_type=OperatorType.API)
    key_op = APIKeyOperation(operator_type=OperatorType.API)

    ids: dict = {}

    async with GetDB() as db:
        admin = await owner_details(db)

        existing = await core_op.get_all_cores(db, __import__("app.models.core", fromlist=["CoreListQuery"]).CoreListQuery())
        core = None
        for c in existing.cores:
            if c.name == "iran-xray":
                core = c
                break
        payload = CoreCreate(
            name="iran-xray",
            config=cfg,
            type=CoreType.xray,
            exclude_inbound_tags={"api", "PANEL-ADMIN"},
            fallbacks_inbound_tags=set(),
        )
        if core is None:
            core = await core_op.create_core(db, payload, admin)
        else:
            core = await core_op.modify_core(db, core.id, payload, admin)
        ids["core_id"] = core.id

        from app.models.group import GroupListQuery, GroupModify

        groups = await group_op.get_all_groups(db, GroupListQuery(), admin)
        group = None
        for g in groups.groups:
            if g.name == "iran":
                group = g
                break
        if group is None:
            group = await group_op.create_group(
                db,
                GroupCreate(name="iran", inbound_tags=["VLESS-REALITY", "VLESS-VISION"], is_disabled=False),
                admin,
            )
        else:
            group = await group_op.modify_group(
                db,
                group.id,
                GroupModify(name="iran", inbound_tags=["VLESS-REALITY", "VLESS-VISION"], is_disabled=False),
                admin,
            )
        ids["group_id"] = group.id

        hosts = await host_op.get_hosts(db=db, query=__import__("app.models.host", fromlist=["HostListQuery"]).HostListQuery())
        wanted = [
            {
                "remark": "Reality",
                "address": {"${IRAN_DOMAIN}"},
                "inbound_tag": "VLESS-REALITY",
                "port": 443,
                "sni": {"dl.google.com"},
                "host": set(),
                "security": ProxyHostSecurity.inbound_default,
                "fingerprint": ProxyHostFingerprint.chrome,
                "allowinsecure": False,
                "is_disabled": False,
                "priority": 1,
            },
            {
                "remark": "Reality-IP",
                "address": {"${IRAN_IP}"},
                "inbound_tag": "VLESS-REALITY",
                "port": 443,
                "sni": {"dl.google.com"},
                "host": set(),
                "security": ProxyHostSecurity.inbound_default,
                "fingerprint": ProxyHostFingerprint.chrome,
                "allowinsecure": False,
                "is_disabled": False,
                "priority": 2,
            },
            {
                "remark": "Vision",
                "address": {"${IRAN_DOMAIN}"},
                "inbound_tag": "VLESS-VISION",
                "port": 2053,
                "sni": {"${IRAN_DOMAIN}"},
                "host": set(),
                "security": ProxyHostSecurity.inbound_default,
                "alpn": [ProxyHostALPN.h2, ProxyHostALPN.h1],
                "fingerprint": ProxyHostFingerprint.chrome,
                "allowinsecure": False,
                "is_disabled": False,
                "priority": 3,
            },
            {
                "remark": "Vision-IP",
                "address": {"${IRAN_IP}"},
                "inbound_tag": "VLESS-VISION",
                "port": 2053,
                "sni": {"${IRAN_DOMAIN}"},
                "host": set(),
                "security": ProxyHostSecurity.inbound_default,
                "alpn": [ProxyHostALPN.h2, ProxyHostALPN.h1],
                "fingerprint": ProxyHostFingerprint.chrome,
                "allowinsecure": False,
                "is_disabled": False,
                "priority": 4,
            },
        ]
        have = {h.remark for h in hosts}
        created_hosts = []
        for spec in wanted:
            if spec["remark"] in have:
                continue
            h = await host_op.create_host(db, CreateHost(**spec), admin)
            created_hosts.append(h.remark)
        ids["hosts_created"] = created_hosts

        for uname, uuid_key in (("testuser", "testuser_uuid"), ("testuser2", "testuser2_uuid")):
            uid = UUID(inp[uuid_key])
            try:
                await user_op.create_user(
                    db,
                    UserCreate(
                        username=uname,
                        status=UserStatus.active,
                        group_ids=[group.id],
                        data_limit=0,
                        proxy_settings=ProxyTable(vless=VlessSettings(id=uid)),
                    ),
                    admin,
                    skip_role_limits=True,
                )
                ids.setdefault("users_created", []).append(uname)
            except Exception as e:
                ids.setdefault("users_skipped", []).append(f"{uname}:{type(e).__name__}")

        if not KEY_OUT.exists():
            created = await key_op.create_api_key(
                db, admin=admin, model=APIKeyCreate(name="vpn-infra", inherit_permissions=True)
            )
            KEY_OUT.write_text(created.api_key)
            os.chmod(KEY_OUT, 0o600)
            ids["api_key_created"] = True
        else:
            ids["api_key_created"] = False

        if CERT.exists() and inp.get("node_api_key"):
            ca = CERT.read_text().strip()
            nodes = await node_op.get_db_nodes(
                db=db, query=__import__("app.models.node", fromlist=["NodeListQuery"]).NodeListQuery()
            )
            node = None
            for n in nodes.nodes:
                if n.name == "iran":
                    node = n
                    break
            n_payload = NodeCreate(
                name="iran",
                address="${IRAN_IP}",
                port=62050,
                api_port=62051,
                usage_coefficient=1.0,
                connection_type=NodeConnectionType.grpc,
                server_ca=ca,
                keep_alive=60,
                core_config_id=core.id,
                api_key=inp["node_api_key"],
                data_limit=0,
                data_limit_reset_strategy=DataLimitResetStrategy.no_reset,
                reset_time=-1,
            )
            if node is None:
                node = await node_op.create_node(db, n_payload, admin)
                ids["node_created"] = True
            else:
                ids["node_created"] = False
            ids["node_id"] = node.id
            ids["node_status"] = str(node.status)

        await db.commit()

    IDS_OUT.parent.mkdir(parents=True, exist_ok=True)
    IDS_OUT.write_text(json.dumps(ids, indent=2))
    print("BOOTSTRAP_OK", json.dumps({k: v for k, v in ids.items() if "key" not in k.lower()}))


if __name__ == "__main__":
    asyncio.run(main())
