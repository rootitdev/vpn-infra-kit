#!/usr/bin/env python3
"""Iran local apply agent. Polls dropped desired-state files and POSTs localhost /start.

Never contacts Germany. Idempotent: same sha256 is a no-op.
Overlapping applies are serialized with flock.
No secrets printed.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import socket
import ssl
import time
import urllib.request
from pathlib import Path

SYNC = Path("/var/lib/pg-node/sync")
LOCK = Path("/var/lock/iran-sync-apply.lock")
LOG = Path("/var/log/vpn-path/sync.log")
NODE_ENV = Path("/opt/pg-node/.env")
GEN = Path("/var/lib/pg-node/generated/xray.json")


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + " " + msg + "\n"
    with LOG.open("a") as f:
        f.write(line)


def node_key() -> str:
    for ln in NODE_ENV.read_text().splitlines():
        if ln.startswith("API_KEY="):
            return ln.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("missing node API_KEY")


def client_summary() -> str:
    try:
        cfg = json.loads(GEN.read_text())
    except Exception:
        return "generated=missing"
    parts = []
    for ib in cfg.get("inbounds") or []:
        if ib.get("tag") in ("VLESS-REALITY", "VLESS-VISION"):
            n = len(((ib.get("settings") or {}).get("clients") or []))
            parts.append(f"{ib.get('tag')}:{n}")
    bal = ((cfg.get("routing") or {}).get("balancers") or [{}])[0]
    sel = ",".join(bal.get("selector") or [])
    return " ".join(parts) + " selector=" + sel


def inbound_down() -> bool:
    """True if live Xray inbounds are not accepting TCP (post-reboot /start needed)."""
    for port in (443, 2053):
        s = socket.socket()
        s.settimeout(0.4)
        try:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return True
        finally:
            s.close()
    return False


def apply(raw: bytes) -> int:
    key = node_key()
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(
        "https://127.0.0.1:62050/start",
        data=raw,
        method="POST",
        headers={"x-api-key": key, "Content-Type": "application/x-protobuf"},
    )
    t0 = time.time()
    with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
        status = resp.status
        resp.read()
    log(f"START {status} dt={time.time()-t0:.2f} {client_summary()}")
    return status


def main() -> None:
    want_p = SYNC / "state.sha256"
    bin_p = SYNC / "state.bin"
    applied_p = SYNC / "applied.sha256"
    if not want_p.exists() or not bin_p.exists():
        return
    want = want_p.read_text().strip()
    raw = bin_p.read_bytes()
    got = hashlib.sha256(raw).hexdigest()
    if got != want:
        log(f"skip hash_mismatch file={want[:12]} bin={got[:12]}")
        return
    have = applied_p.read_text().strip() if applied_p.exists() else ""
    need = have != want or inbound_down()
    if not need:
        return
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open("w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        have = applied_p.read_text().strip() if applied_p.exists() else ""
        if have == want and not inbound_down():
            return
        reason = "hash" if have != want else "inbound_down"
        apply(raw)
        applied_p.write_text(want + "\n")
        applied_p.chmod(0o600)
        log(f"applied {want[:12]} reason={reason}")


if __name__ == "__main__":
    main()
