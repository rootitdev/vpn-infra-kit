#!/usr/bin/env python3
"""Pull Iran Xray stats (localhost API) into panel sqlite.

Does not call node /start. Does not enable the panel node row.
Deltas vs last snapshot so xray restarts do not double-count or go negative.
No secrets printed.
"""
from __future__ import annotations

import fcntl
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from instagram_multiplier import (
    instagram_bytes,
    is_cat_tag,
    load_settings,
    user_raw_bytes,
    weighted_user_deltas,
)

IRAN = "root@${IRAN_IP}"
SNAP = Path("/var/lib/pasarguard/iran-stats-snapshot.json")
LOG = Path("/var/log/vpn-path/stats.log")
LOCK = Path("/var/lock/iran-stats.lock")
NODE_ID = 1
REMOTE = r'''
python3 - << "PY"
import json, subprocess
from pathlib import Path
c=json.loads(Path("/var/lib/pg-node/generated/xray.json").read_text())
port=next((ib.get("port") for ib in c.get("inbounds") or [] if ib.get("tag")=="API_INBOUND"), None)
if not port:
    print("{}")
    raise SystemExit(0)
r=subprocess.run(
    ["xray","api","statsquery","--server=127.0.0.1:%s"%port],
    capture_output=True, text=True, timeout=8,
)
print(r.stdout if r.returncode==0 else "{}")
PY
'''


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with LOG.open("a") as f:
        f.write(f"{ts} {msg}\n")


def fetch() -> dict[str, int]:
    r = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", IRAN, REMOTE],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    raw = json.loads(r.stdout or "{}")
    out: dict[str, int] = {}
    for st in raw.get("stat") or []:
        name = st.get("name") or ""
        val = int(st.get("value") or 0)
        if name:
            out[name] = val
    return out


def delta(now: dict[str, int], prev: dict[str, int]) -> dict[str, int]:
    d: dict[str, int] = {}
    for k, v in now.items():
        old = int(prev.get(k) or 0)
        if v >= old:
            dv = v - old
        else:
            dv = v  # counter reset after xray restart
        if dv:
            d[k] = dv
    return d


def parse_users(d: dict[str, int]) -> dict[int, int]:
    """email is panel user id. Sum uplink+downlink."""
    users: dict[int, int] = {}
    for name, val in d.items():
        # user>>>ID>>>traffic>>>uplink|downlink
        parts = name.split(">>>")
        if len(parts) >= 4 and parts[0] == "user" and parts[2] == "traffic":
            try:
                uid = int(parts[1])
            except ValueError:
                continue
            users[uid] = users.get(uid, 0) + val
    return users


def parse_node(d: dict[str, int]) -> tuple[int, int]:
    up = down = 0
    for name, val in d.items():
        parts = name.split(">>>")
        if len(parts) < 4 or parts[0] != "outbound" or parts[2] != "traffic":
            continue
        tag = parts[1]
        if not (tag.startswith("TO-AMS-") or is_cat_tag(tag)):
            continue
        if parts[3] == "uplink":
            up += val
        elif parts[3] == "downlink":
            down += val
    return up, down


INGEST_PY = r"""
import sqlite3, time
from pathlib import Path
sql = Path("/tmp/iran-stats.sql").read_text()
err = None
for i in range(8):
    try:
        c = sqlite3.connect("/var/lib/pasarguard/db.sqlite3", timeout=30.0)
        c.execute("PRAGMA busy_timeout=30000")
        mode = c.execute("PRAGMA journal_mode=WAL").fetchone()
        c.executescript(sql)
        c.close()
        print("ok", mode[0] if mode else "")
        break
    except sqlite3.OperationalError as e:
        err = e
        msg = str(e).lower()
        if "locked" not in msg and "busy" not in msg:
            raise
        time.sleep(0.05 * (2 ** i))
else:
    raise SystemExit("sqlite locked: %s" % err)
"""


def ingest_sqlite(users: dict[int, int], up: int, down: int) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    sql_path = Path(tempfile.mkstemp(prefix="pg-stats-", suffix=".sql")[1])
    lines = ["BEGIN IMMEDIATE;"]
    for uid, val in users.items():
        if val <= 0:
            continue
        lines.append(
            f"UPDATE users SET used_traffic = used_traffic + {int(val)}, "
            f"online_at = '{now}' WHERE id = {int(uid)};"
        )
    if up or down:
        lines.append(
            f"UPDATE nodes SET uplink = uplink + {int(up)}, downlink = downlink + {int(down)} WHERE id = {int(NODE_ID)};"
        )
    lines.append("COMMIT;")
    sql_path.write_text("\n".join(lines) + "\n")
    subprocess.run(
        ["docker", "cp", str(sql_path), "pasarguard:/tmp/iran-stats.sql"],
        check=True,
    )
    sql_path.unlink(missing_ok=True)
    r = subprocess.run(
        ["docker", "exec", "pasarguard", "/code/.venv/bin/python", "-c", INGEST_PY],
        check=True,
        capture_output=True,
        text=True,
    )
    if "ok" not in (r.stdout or ""):
        raise SystemExit("sqlite ingest failed: " + (r.stderr or r.stdout or "")[:300])


def main() -> None:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open("w") as lf:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("SKIP locked", flush=True)
            return
        now = fetch()
        prev = json.loads(SNAP.read_text()) if SNAP.exists() else {}
        d = delta(now, prev)
        SNAP.parent.mkdir(parents=True, exist_ok=True)
        SNAP.write_text(json.dumps(now) + "\n")
        SNAP.chmod(0o600)
        settings = load_settings()
        users = weighted_user_deltas(d, settings)
        up, down = parse_node(d)
        if not users and not up and not down:
            return
        ingest_sqlite(users, up, down)
        extra = []
        for uid in settings.user_ids:
            raw = user_raw_bytes(d, uid)
            igb = instagram_bytes(d, uid)
            if raw or igb:
                extra.append(f"u{uid}_raw={raw}_cat={igb}_w={users.get(uid, 0)}")
        log(
            f"users { {k: users[k] for k in sorted(users)} } node_up {up} node_down {down}"
            + ((" " + " ".join(extra)) if extra else "")
        )


if __name__ == "__main__":
    main()
