#!/usr/bin/env python3
"""Post-boot check with timing. Exit also waits for panel :2096 HTTP 200."""
from __future__ import annotations

import socket
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import role, send  # noqa: E402

BOOT_LOG = Path("/var/log/monitoring/boot-test.log")
ISSUED = Path("/var/lib/vpn-monitor/reboot-issued-at")

EXIT_UNITS = [
    "docker.service",
    "xray.service",
    "nginx.service",
    "iran-sync-export.timer",
    "vpn-failover.timer",
    "iran-stats.timer",
    "vpn-mon-capacity.timer",
    "vpn-mon-hardware.timer",
    "vpn-mon-quota.timer",
    "vpn-mon-google.timer",
]
IRAN_UNITS = [
    "docker.service",
    "hysteria-inbound.service",
    "iran-sync-apply.timer",
    "vpn-mon-capacity.timer",
    "vpn-mon-hardware.timer",
    "vpn-mon-quota.timer",
    "vpn-mon-google.timer",
]


def uptime_sec() -> float:
    return float(Path("/proc/uptime").read_text().split()[0])


def unit_state(name: str) -> tuple[str, str]:
    def one(cmd: list[str]) -> str:
        p = subprocess.run(cmd, capture_output=True, text=True)
        return (p.stdout or "").strip() or "n/a"

    return one(["systemctl", "is-enabled", name]), one(["systemctl", "is-active", name])


def port_up(port: int, host: str = "127.0.0.1") -> bool:
    s = socket.socket()
    s.settimeout(0.4)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


def docker_up(name: str) -> str:
    p = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Status}}", name],
        capture_output=True,
        text=True,
    )
    return (p.stdout or p.stderr or "missing").strip()


def panel_http_ok() -> bool:
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request("https://127.0.0.1:2096/dashboard/", method="GET")
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=4) as resp:
            return 200 <= int(resp.status) < 400
    except Exception:
        return False


def wait_until(fn, deadline: float) -> float | None:
    while time.time() < deadline:
        if fn():
            return uptime_sec()
        time.sleep(1)
    return None


def main() -> None:
    r = role()
    units = EXIT_UNITS if r == "exit" else IRAN_UNITS
    deadline = time.time() + 120
    marks: dict[str, str] = {}
    issued = ISSUED.read_text().strip() if ISSUED.exists() else ""
    t_issue = float(issued) if issued else 0.0

    def mark(name: str, ok: bool) -> None:
        if ok and name not in marks:
            marks[name] = f"{uptime_sec():.1f}s"

    ports = [443] if r == "exit" else [443, 2053, 62050]
    while time.time() < deadline:
        for u in units:
            _en, act = unit_state(u)
            good = act in ("active", "waiting")
            mark(u, good)
        for p in ports:
            mark(f"tcp:{p}", port_up(p))
        if r == "exit":
            mark("docker:pasarguard", docker_up("pasarguard") == "running")
            mark("panel_http_2096", panel_http_ok())
        else:
            mark("docker:node", docker_up("node") == "running")
        need = [f"tcp:{p}" for p in ports] + list(units)
        if r == "exit":
            need += ["docker:pasarguard", "panel_http_2096"]
        else:
            need += ["docker:node"]
        if all(k in marks for k in need):
            break
        time.sleep(1)

    lines = [
        f"role={r}",
        f"kernel_uptime_now={uptime_sec():.1f}s",
        f"reboot_issued_at={issued or 'unknown'}",
    ]
    if t_issue:
        lines.append(f"wall_since_reboot_cmd={time.time() - t_issue:.1f}s")
    bad = []
    for u in units:
        en, act = unit_state(u)
        lines.append(f"{u} enabled={en} active={act} up_at={marks.get(u, 'NOT_READY')}")
        if u not in marks:
            bad.append(u)
    if r == "exit":
        st = docker_up("pasarguard")
        lines.append(f"docker:pasarguard={st} up_at={marks.get('docker:pasarguard', 'NOT_READY')}")
        if st != "running":
            bad.append("pasarguard")
        okp = "panel_http_2096" in marks
        lines.append(f"panel_http_2096={'ok' if okp else 'FAIL'} up_at={marks.get('panel_http_2096', 'NOT_READY')}")
        if not okp:
            bad.append("panel:2096")
    else:
        st = docker_up("node")
        lines.append(f"docker:node={st} up_at={marks.get('docker:node', 'NOT_READY')}")
        if st != "running":
            bad.append("node")
    for p in ports:
        k = f"tcp:{p}"
        lines.append(f"{k}={'up' if k in marks else 'DOWN'} up_at={marks.get(k, 'NOT_READY')}")
        if k not in marks:
            bad.append(k)
    lines.append(f"elapsed_uptime_sec={uptime_sec():.1f}")
    BOOT_LOG.parent.mkdir(parents=True, exist_ok=True)
    BOOT_LOG.write_text("\n".join(lines) + "\n")
    if bad:
        send("boot", "breach", f"بعد از بوت مشکل: {', '.join(bad)}", lines)
        sys.exit(1)
    send("boot", "recovery", f"بوت OK — uptime {uptime_sec():.0f}s", lines)


if __name__ == "__main__":
    main()
