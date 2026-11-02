#!/usr/bin/env python3
"""Monitor 1: connections, bandwidth %, path latency from health.json."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import (  # noqa: E402
    active_client_snapshot,
    cfg,
    evaluate,
    iface_counters,
    load_state,
    read_health,
    save_state,
    send,
)


def main() -> None:
    c = cfg()
    iface = c["IFACE"]
    link = float(c.get("LINK_MBPS") or 1000) or 1000
    conn_lim = int(c.get("CONN_THRESHOLD") or 100)
    bw_pct_lim = float(c.get("BW_PCT") or 75)
    sustain = int(c.get("SUSTAIN_SEC") or 300)
    cooldown = int(c.get("COOLDOWN_SEC") or 1800)

    st = load_state()
    now = time.time()
    cur = iface_counters(iface)
    prev = st.get("_bw") or {}
    rx_bps = tx_bps = 0.0
    if prev.get("ts") and now > float(prev["ts"]) + 1:
        dt = now - float(prev["ts"])
        rx_bps = max(0.0, (cur["rx_bytes"] - int(prev.get("rx_bytes") or 0)) / dt)
        tx_bps = max(0.0, (cur["tx_bytes"] - int(prev.get("tx_bytes") or 0)) / dt)
    st["_bw"] = {"ts": now, "rx_bytes": cur["rx_bytes"], "tx_bytes": cur["tx_bytes"]}
    save_state(st)

    link_bps = link * 1_000_000 / 8  # MBPS treated as megabits
    # User thinks in link %, use bits: rx_bps is bytes/s
    rx_mbps = rx_bps * 8 / 1_000_000
    tx_mbps = tx_bps * 8 / 1_000_000
    util = max(rx_mbps, tx_mbps) / link * 100 if link else 0

    snap = active_client_snapshot()
    conns = int(snap["clients"])
    health = read_health()
    paths = health.get("paths") or {}
    path_lines = []
    for name, info in paths.items():
        if not isinstance(info, dict):
            continue
        ok = "ok" if info.get("ok") else "FAIL"
        path_lines.append(f"{name} {ok} {info.get('ms', '?')}ms")
    inbound = health.get("inbound_ok")
    lim_s = "off" if conn_lim <= 0 else str(conn_lim)
    details = [
        f"clients={conns} unique IPs (lim {lim_s})",
        f"inbound_tcp={snap['sockets']} on {snap['ports']} dropped={snap['dropped']}",
        f"bw {iface} rx={rx_mbps:.1f} tx={tx_mbps:.1f} Mbps  util={util:.0f}% of {link:.0f} Mbps",
        f"inbound_ok={inbound}",
    ]
    if path_lines:
        details.append("paths: " + ", ".join(path_lines))

    # CONN_THRESHOLD=0 disables the connection alert (used while verifying the counter).
    if conn_lim > 0:
        ev_c = evaluate("capacity_conn", conns > conn_lim, sustain, cooldown)
        if ev_c == "breach":
            send("capacity", "breach", f"کلاینت فعال > {conn_lim} برای ۵+ دقیقه", details)
        elif ev_c == "rebreach":
            send("capacity", "breach", f"کلاینت‌ها همچنان بالای {conn_lim} (۳۰د دوباره)", details)
        elif ev_c == "recovery":
            send("capacity", "recovery", f"کلاینت فعال برگشت زیر {conn_lim}", details)

    ev_b = evaluate("capacity_bw", util >= bw_pct_lim, sustain, cooldown)
    if ev_b == "breach":
        send("capacity", "breach", f"مصرف لینک ≥ {bw_pct_lim:.0f}% برای ۵+ دقیقه", details)
    elif ev_b == "rebreach":
        send("capacity", "breach", f"مصرف لینک همچنان ≥ {bw_pct_lim:.0f}%", details)
    elif ev_b == "recovery":
        send("capacity", "recovery", f"مصرف لینک برگشت زیر {bw_pct_lim:.0f}%", details)


if __name__ == "__main__":
    main()
