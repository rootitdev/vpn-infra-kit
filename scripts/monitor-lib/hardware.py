#!/usr/bin/env python3
"""Monitor 2: CPU, RAM, NIC errors/drops. Breach + recovery + 30m cooldown."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import (  # noqa: E402
    cfg,
    cpu_pct,
    evaluate,
    iface_counters,
    load_state,
    ram_pct,
    save_state,
    send,
)


def main() -> None:
    c = cfg()
    iface = c["IFACE"]
    cpu_lim = float(c.get("CPU_PCT") or 80)
    ram_lim = float(c.get("RAM_PCT") or 80)
    sustain = int(c.get("SUSTAIN_SEC") or 300)
    cooldown = int(c.get("COOLDOWN_SEC") or 1800)

    drop_lim = int(c.get("NIC_DROP_DELTA") or 100)
    err_keys = (
        "rx_errors",
        "tx_errors",
        "rx_missed_errors",
        "rx_over_errors",
        "rx_fifo_errors",
        "tx_fifo_errors",
        "rx_crc_errors",
        "rx_frame_errors",
    )

    st = load_state()
    cpu, st = cpu_pct(st)
    ram = ram_pct()
    cur = iface_counters(iface)
    prev = st.get("_nic") or {}
    d_err = 0
    d_drop = 0
    if prev:
        d_err = sum(max(0, cur.get(k, 0) - int(prev.get(k) or 0)) for k in err_keys)
        d_drop = (cur["rx_dropped"] - int(prev.get("rx_dropped") or 0)) + (
            cur["tx_dropped"] - int(prev.get("tx_dropped") or 0)
        )
        d_drop = max(0, d_drop)
    st["_nic"] = cur
    save_state(st)

    tot_err = sum(cur.get(k, 0) for k in err_keys)
    details = [
        f"cpu={cpu:.0f}% (lim {cpu_lim:.0f}%)",
        f"ram={ram:.0f}% (lim {ram_lim:.0f}%)",
        f"nic {iface} Δerr={d_err} Δdrop={d_drop}  tot_err={tot_err} tot_drop={cur['rx_dropped']+cur['tx_dropped']}",
        f"آستانه drop={drop_lim} در هر دقیقه (زیر این، نویز virtio نادیده)",
    ]

    ev = evaluate("hw_cpu", cpu >= cpu_lim, sustain, cooldown)
    if ev == "breach":
        send("hardware", "breach", f"CPU پایدار ≥ {cpu_lim:.0f}% برای ۵+ دقیقه", details)
    elif ev == "rebreach":
        send("hardware", "breach", f"CPU همچنان ≥ {cpu_lim:.0f}%", details)
    elif ev == "recovery":
        send("hardware", "recovery", "CPU برگشت زیر آستانه", details)

    ev = evaluate("hw_ram", ram >= ram_lim, sustain, cooldown)
    if ev == "breach":
        send("hardware", "breach", f"RAM پایدار ≥ {ram_lim:.0f}% برای ۵+ دقیقه", details)
    elif ev == "rebreach":
        send("hardware", "breach", f"RAM همچنان ≥ {ram_lim:.0f}%", details)
    elif ev == "recovery":
        send("hardware", "recovery", "RAM برگشت زیر آستانه", details)

    # Errors (CRC/frame/fifo/missed): any increase. Software rx_dropped is
    # noisy on virtio — only alert at NIC_DROP_DELTA per 1-min interval.
    nic_bad = d_err > 0 or d_drop >= drop_lim
    ev = evaluate("hw_nic", nic_bad, sustain=0, cooldown=cooldown)
    if ev in ("breach", "rebreach"):
        if d_err > 0:
            title = f"خطای NIC {iface}: Δerrors={d_err} Δdrops={d_drop}"
        else:
            title = f"drop زیاد روی {iface}: Δdrops={d_drop} (lim {drop_lim})"
        send("hardware", "breach", title, details)
    elif ev == "recovery":
        send("hardware", "recovery", f"خطا/drop بالای آستانه روی {iface} متوقف شد", details)


if __name__ == "__main__":
    main()
