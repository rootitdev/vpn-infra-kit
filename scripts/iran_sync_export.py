#!/usr/bin/env python3
"""Publish desired Iran Xray state. Does not call node /start (Germany→Iran /start is forbidden).

Writes proto+hash on Exit, then drops the same files on Iran via SCP.
The Iran agent applies locally. Idempotent: unchanged hash skips SCP body.
No secrets printed.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

IRAN = "root@${IRAN_IP}"
BUILD = Path("/root/vpn-infra/scripts/build_iran_start_proto.py")
IG_MOD = Path("/root/vpn-infra/scripts/instagram_multiplier.py")
IG_DIR = Path("/etc/vpn-monitor")
LOCAL_DIR = Path("/var/lib/pasarguard/iran-sync")
REMOTE_DIR = "/var/lib/pg-node/sync"
LOCK = Path("/var/lock/iran-sync-export.lock")


def _stage_instagram_module() -> None:
    subprocess.run(["docker", "cp", str(IG_MOD), "pasarguard:/tmp/instagram_multiplier.py"], check=True)
    subprocess.run(["docker", "exec", "pasarguard", "mkdir", "-p", "/tmp/ig-mult"], check=True)
    users = IG_DIR / "instagram-multiplier-users.txt"
    envf = IG_DIR / "instagram-multiplier.env"
    if users.exists():
        subprocess.run(["docker", "cp", str(users), "pasarguard:/tmp/ig-mult/instagram-multiplier-users.txt"], check=True)
    if envf.exists():
        subprocess.run(["docker", "cp", str(envf), "pasarguard:/tmp/ig-mult/instagram-multiplier.env"], check=True)


def build_proto() -> tuple[int, str, bytes]:
    _stage_instagram_module()
    subprocess.run(
        ["docker", "cp", str(BUILD), "pasarguard:/tmp/build_iran_start_proto.py"],
        check=True,
    )
    built = subprocess.run(
        [
            "docker",
            "exec",
            "-w",
            "/code",
            "-e",
            "PYTHONPATH=/code",
            "pasarguard",
            "/code/.venv/bin/python",
            "/tmp/build_iran_start_proto.py",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    line = built.stdout.strip().splitlines()[-1]
    nusers, digest, size = line.split()
    subprocess.run(
        ["docker", "cp", "pasarguard:/tmp/pg-start-users.bin", "/tmp/pg-start-users.bin"],
        check=True,
    )
    raw = Path("/tmp/pg-start-users.bin").read_bytes()
    got = hashlib.sha256(raw).hexdigest()
    if got != digest:
        raise SystemExit("proto hash mismatch")
    return int(nusers), digest, raw


def ssh(cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", IRAN, cmd],
        check=True,
        text=True,
        capture_output=True,
    )


def main() -> None:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open("w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        _main()


def _main() -> None:
    nusers, digest, raw = build_proto()
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    (LOCAL_DIR / "state.bin").write_bytes(raw)
    (LOCAL_DIR / "state.sha256").write_text(digest + "\n")
    meta = {
        "sha256": digest,
        "users": nusers,
        "bytes": len(raw),
        "ts": int(time.time()),
    }
    (LOCAL_DIR / "meta.json").write_text(json.dumps(meta) + "\n")
    for p in LOCAL_DIR.iterdir():
        p.chmod(0o600)

    remote_hash = ""
    try:
        r = ssh(f"cat {REMOTE_DIR}/state.sha256 2>/dev/null || true")
        remote_hash = (r.stdout or "").strip()
    except subprocess.CalledProcessError:
        remote_hash = ""
    if remote_hash == digest:
        print("unchanged", nusers, digest[:12])
        return

    ssh(f"mkdir -p {REMOTE_DIR} && chmod 700 {REMOTE_DIR}")
    tag = str(os.getpid())
    subprocess.run(
        ["scp", "-o", "BatchMode=yes", str(LOCAL_DIR / "state.bin"), f"{IRAN}:{REMOTE_DIR}/state.bin.tmp.{tag}"],
        check=True,
    )
    subprocess.run(
        ["scp", "-o", "BatchMode=yes", str(LOCAL_DIR / "state.sha256"), f"{IRAN}:{REMOTE_DIR}/state.sha256.tmp.{tag}"],
        check=True,
    )
    subprocess.run(
        ["scp", "-o", "BatchMode=yes", str(LOCAL_DIR / "meta.json"), f"{IRAN}:{REMOTE_DIR}/meta.json.tmp.{tag}"],
        check=True,
    )
    ssh(
        f"mv {REMOTE_DIR}/state.bin.tmp.{tag} {REMOTE_DIR}/state.bin && "
        f"mv {REMOTE_DIR}/meta.json.tmp.{tag} {REMOTE_DIR}/meta.json && "
        f"mv {REMOTE_DIR}/state.sha256.tmp.{tag} {REMOTE_DIR}/state.sha256 && "
        f"chmod 600 {REMOTE_DIR}/state.bin {REMOTE_DIR}/state.sha256 {REMOTE_DIR}/meta.json"
    )
    print("published", nusers, digest[:12], len(raw))


if __name__ == "__main__":
    main()
