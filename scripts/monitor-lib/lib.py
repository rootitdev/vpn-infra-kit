#!/usr/bin/env python3
"""Shared alerting + host metrics for vpn-monitor. Never prints secrets."""
from __future__ import annotations

import copy
import fcntl
import json
import os
import re
import socket
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

CFG_PATH = Path("/etc/vpn-monitor/config.env")
SECRETS = Path("/root/.vpn-secrets/.env")
SECRETS_IRAN = Path("/etc/vpn-monitor/secrets.env")
STATE_PATH = Path("/var/lib/vpn-monitor/state.json")
ALERT_LOG = Path("/var/log/monitoring/alerts.log")
LOCK = Path("/var/lock/vpn-monitor.lock")
STATE_LOCK = Path("/var/lock/vpn-monitor-state.lock")
HEALTH_IRAN = Path("/var/lib/pg-node/sync/health.json")
HEALTH_EXIT = Path("/var/lib/pasarguard/iran-health.json")
_STATE_SNAP: dict | None = None


def _parse_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for ln in path.read_text().splitlines():
        s = ln.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def cfg() -> dict[str, str]:
    d = {
        "ROLE": "exit",
        "DISPLAY_NAME": socket.gethostname(),
        "LINK_MBPS": "1000",
        "CONN_THRESHOLD": "100",
        "BW_PCT": "75",
        "CPU_PCT": "80",
        "RAM_PCT": "80",
        "SUSTAIN_SEC": "300",
        "COOLDOWN_SEC": "1800",
        "IFACE": "",
        "NIC_DROP_DELTA": "100",
        "IRAN_QUOTA_BYTES": "1500000000000",
        "IRAN_QUOTA_RESET_DAY": "26",
        "EXIT_QUOTA_BYTES": "",
        "EXIT_QUOTA_RESET_DAY": "19",
        "EXIT_ROLLING_LIMIT_BYTES": "2000000000000",
        "EXIT_THROTTLE_MBIT": "200",
        "NETCUP_VSERVER_NAME": "v2202608400527502404",
    }
    d.update(_parse_env(CFG_PATH))
    secrets = _parse_env(SECRETS)
    secrets.update(_parse_env(SECRETS_IRAN))
    d.update({k: secrets[k] for k in secrets})
    if not d.get("IFACE"):
        d["IFACE"] = default_iface()
    return d


def default_iface() -> str:
    try:
        for ln in Path("/proc/net/route").read_text().splitlines()[1:]:
            parts = ln.split()
            if parts[1] == "00000000":
                return parts[0]
    except Exception:
        pass
    return "eth0"


def role() -> str:
    return (cfg().get("ROLE") or "exit").strip().lower()


def display() -> str:
    return cfg().get("DISPLAY_NAME") or socket.gethostname()


@contextmanager
def _state_lock():
    STATE_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with STATE_LOCK.open("w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        yield


def _read_unlocked() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            return {}
    return {}


def _write_unlocked(st: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_name(f"{STATE_PATH.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(st, indent=2) + "\n")
    tmp.chmod(0o600)
    tmp.replace(STATE_PATH)


def load_state() -> dict:
    """Load monitor state. Pair with save_state() in the same process."""
    global _STATE_SNAP
    with _state_lock():
        st = _read_unlocked()
    _STATE_SNAP = copy.deepcopy(st)
    return st


def save_state(st: dict) -> None:
    """Write only keys that changed since the last load_state() in this process.

    Full-document replaces raced with other 1-minute monitors and resurrected
    a stale hw_nic=breach, which made recovery Telegram fire twice.
    """
    global _STATE_SNAP
    snap = _STATE_SNAP if _STATE_SNAP is not None else {}
    with _state_lock():
        disk = _read_unlocked()
        for k, v in st.items():
            if k not in snap or snap[k] != v:
                disk[k] = v
        _write_unlocked(disk)
        _STATE_SNAP = copy.deepcopy(disk)


def log_alert(line: str) -> None:
    ALERT_LOG.parent.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with ALERT_LOG.open("a") as f:
        f.write(f"{ts} {line}\n")


def telegram_send(text: str) -> str:
    c = cfg()
    token = c.get("TELEGRAM_BOT_TOKEN") or ""
    chat = c.get("TELEGRAM_CHAT_ID") or ""
    if not token or not chat:
        return "skip_no_creds"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps(
        {"chat_id": chat, "text": text, "disable_web_page_preview": True}
    )
    cmd = [
        "curl", "-sS", "-o", "/tmp/tg-send.out", "-w", "%{http_code}",
        "--max-time", "15",
        "-H", "Content-Type: application/json",
        "-d", payload,
    ]
    if role() == "iran":
        cmd.extend(["--socks5-hostname", "127.0.0.1:11080"])
    cmd.append(url)
    try:
        import subprocess

        p = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        code = (p.stdout or "").strip()
        if code == "200":
            return "ok"
        return f"http_{code}"
    except Exception as e:
        return f"fail:{type(e).__name__}"


def send(monitor: str, severity: str, title: str, details: list[str]) -> None:
    """severity: breach | recovery | info | test"""
    icon = {"breach": "ALERT", "recovery": "OK", "info": "INFO", "test": "TEST"}.get(
        severity, severity.upper()
    )
    lines = [f"[{icon}] {display()} · {monitor}", title]
    lines.extend(details)
    text = "\n".join(lines)
    one = text.replace("\n", " | ")
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open("w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        log_alert(one)
        tg = telegram_send(text)
        if tg != "ok":
            log_alert(f"telegram_{tg} monitor={monitor}")


def evaluate(key: str, breached: bool, sustain: int, cooldown: int) -> str | None:
    """Return 'breach', 'rebreach', 'recovery', or None.

    Recovery is edge-triggered: it fires once when leaving kind=breach, never
    again while the condition stays healthy.
    """
    with _state_lock():
        st = _read_unlocked()
        rec = dict(st.get(key) or {})
        now = time.time()
        event = None
        if breached:
            since = float(rec.get("since") or now)
            rec["since"] = since
            rec["breached"] = True
            held = now - since
            last = float(rec.get("last_alert") or 0)
            kind = rec.get("kind") or ""
            if held >= sustain:
                if kind != "breach":
                    rec["kind"] = "breach"
                    rec["last_alert"] = now
                    event = "breach"
                elif now - last >= cooldown:
                    rec["last_alert"] = now
                    event = "rebreach"
            st[key] = rec
        else:
            alerting = rec.get("kind") == "breach"
            st[key] = {
                "breached": False,
                "kind": "ok",
                "since": None,
                "last_alert": rec.get("last_alert"),
            }
            event = "recovery" if alerting else None
        _write_unlocked(st)
        return event


def cpu_pct(st: dict) -> tuple[float, dict]:
    """Percent busy since last sample (or short 0.4s sample)."""
    def snap() -> tuple[int, int]:
        for ln in Path("/proc/stat").read_text().splitlines():
            if ln.startswith("cpu "):
                p = [int(x) for x in ln.split()[1:]]
                idle = p[3] + (p[4] if len(p) > 4 else 0)
                total = sum(p)
                return idle, total
        return 0, 1

    idle, total = snap()
    prev = st.get("_cpu")
    if not prev:
        time.sleep(0.4)
        idle2, total2 = snap()
        d_tot = max(1, total2 - total)
        d_idle = idle2 - idle
        pct = max(0.0, min(100.0, (1 - d_idle / d_tot) * 100))
        st["_cpu"] = {"idle": idle2, "total": total2}
        return pct, st
    d_tot = total - int(prev["total"])
    d_idle = idle - int(prev["idle"])
    st["_cpu"] = {"idle": idle, "total": total}
    if d_tot <= 0:
        return 0.0, st
    return max(0.0, min(100.0, (1 - d_idle / d_tot) * 100)), st


def ram_pct() -> float:
    info = {}
    for ln in Path("/proc/meminfo").read_text().splitlines():
        k, v = ln.split(":", 1)
        info[k] = int(v.strip().split()[0])
    total = info.get("MemTotal") or 1
    avail = info.get("MemAvailable") or info.get("MemFree") or 0
    return max(0.0, min(100.0, (1 - avail / total) * 100))


def iface_counters(iface: str) -> dict[str, int]:
    base = Path(f"/sys/class/net/{iface}/statistics")
    keys = (
        "rx_bytes",
        "tx_bytes",
        "rx_errors",
        "tx_errors",
        "rx_dropped",
        "tx_dropped",
        "rx_packets",
        "tx_packets",
        "rx_missed_errors",
        "rx_over_errors",
        "rx_fifo_errors",
        "tx_fifo_errors",
        "rx_crc_errors",
        "rx_frame_errors",
    )
    out = {}
    for k in keys:
        p = base / k
        out[k] = int(p.read_text().strip()) if p.exists() else 0
    return out


# Reality/VLESS scanners often complete TCP (and a tiny TLS record) then idle.
# Real clients send well above one packet after the handshake.
_MIN_CLIENT_RX = 1500
_LOOPBACK = {"127.0.0.1", "::1", "0.0.0.0", "::"}


def client_listen_ports() -> tuple[int, ...]:
    """Local TCP ports that end-users (Iran) or the Iran backhaul (Exit) hit."""
    if role() == "iran":
        return (443, 2053)
    return (443, 9443)


def _unmap_ip(host: str) -> str:
    h = (host or "").strip()
    if h.lower().startswith("::ffff:"):
        return h[7:]
    return h


def _parse_ss_endpoint(addr: str) -> tuple[str, int | None]:
    addr = (addr or "").strip()
    if not addr:
        return "", None
    if addr.startswith("["):
        br = addr.rfind("]:")
        if br == -1:
            return _unmap_ip(addr.strip("[]")), None
        host = _unmap_ip(addr[1:br])
        try:
            return host, int(addr[br + 2 :])
        except ValueError:
            return host, None
    if addr.count(":") == 1:
        host, _, port = addr.rpartition(":")
        try:
            return host, int(port)
        except ValueError:
            return host, None
    return _unmap_ip(addr), None


def _iter_ss_estab(text: str):
    header = None
    info: list[str] = []
    for ln in text.splitlines():
        if ln[:1] in ("\t", " ") and header is not None:
            info.append(ln)
            continue
        if header is not None:
            yield header, " ".join(info)
        header = ln
        info = []
    if header:
        yield header, " ".join(info)


def active_client_snapshot() -> dict:
    """Unique active *client* IPs on inbound listen ports.

    Counts ESTABLISHED TCP whose *local* port is a client/backhaul inbound,
    with real payload, excluding:
      - TIME_WAIT / CLOSE_WAIT (ss state established)
      - loopback (path_health tcp_tls to 127.0.0.1:443/:2053)
      - outbound HTTPS to CF/XHTTP/Google (remote :443)
      - handshake-only scanners (tiny bytes_received)
    One chatty client with many sockets still counts as 1.
    """
    ports = set(client_listen_ports())
    empty = {
        "clients": 0,
        "sockets": 0,
        "dropped": 0,
        "ports": sorted(ports),
        "ips": [],
    }
    try:
        import subprocess

        out = subprocess.check_output(
            ["ss", "-Htni", "state", "established"], text=True, timeout=5
        )
    except Exception:
        return empty

    by_ip: dict[str, dict] = {}
    dropped = 0
    sockets = 0
    for header, info in _iter_ss_estab(out):
        parts = header.split()
        if len(parts) < 4:
            continue
        local_host, local_port = _parse_ss_endpoint(parts[2])
        peer_host, _peer_port = _parse_ss_endpoint(parts[3])
        if local_port not in ports:
            continue
        if peer_host in _LOOPBACK or local_host in _LOOPBACK:
            dropped += 1
            continue
        rx = 0
        m = re.search(r"bytes_received:(\d+)", info)
        if m:
            rx = int(m.group(1))
        if rx < _MIN_CLIENT_RX:
            dropped += 1
            continue
        sockets += 1
        rec = by_ip.setdefault(peer_host, {"socks": 0, "rx": 0})
        rec["socks"] += 1
        rec["rx"] += rx

    ips = sorted(by_ip)
    return {
        "clients": len(ips),
        "sockets": sockets,
        "dropped": dropped,
        "ports": sorted(ports),
        "ips": ips,
    }


def established_vpn_conns() -> int:
    """Unique active client IPs (not raw ESTAB sockets)."""
    return int(active_client_snapshot()["clients"])


def read_health() -> dict:
    for p in (HEALTH_IRAN, HEALTH_EXIT):
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                return {}
    return {}


def fmt_bytes(n: int) -> str:
    x = float(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if x < 1024 or u == "TB":
            return f"{x:.2f} {u}"
        x /= 1024
    return f"{n} B"


def days_left_in_month(reset_day: int = 1) -> int:
    import datetime as dt

    today = dt.date.today()
    day = max(1, min(28, int(reset_day or 1)))
    if today.day >= day:
        if today.month == 12:
            nxt = dt.date(today.year + 1, 1, day)
        else:
            nxt = dt.date(today.year, today.month + 1, day)
    else:
        nxt = dt.date(today.year, today.month, day)
    return max(0, (nxt - today).days)
