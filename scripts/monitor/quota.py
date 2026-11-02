#!/usr/bin/env python3
"""Monitor 3: traffic quota.

Exit: rolling 24h vs 2TB fair-use (netcup throttles to ~200 Mbit/s). Not monthly.
Iran: monthly RX-only 1.5TB, reset day 26.
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import (  # noqa: E402
    cfg,
    days_left_in_month,
    evaluate,
    fmt_bytes,
    iface_counters,
    load_state,
    role,
    save_state,
    send,
)
from netcup_oauth import rolling_24h  # noqa: E402

IRAN_LEVELS = (70, 85, 95)
EXIT_ROLLING_LEVELS = (60, 80, 95)
SCP_FAIL_COOLDOWN = 6 * 3600

SCP_ERR_FA = {
    "missing_refresh_token": "ورود SCP منقضی یا تنظیم نشده — یک‌بار vpn-mon-netcup-login را بزنید.",
    "scp_refresh_network": "نت‌کاپ در دسترس نبود (خطای شبکه هنگام تمدید توکن).",
    "scp_network": "نت‌کاپ در دسترس نبود (خطای شبکه).",
    "scp_refresh_http_400": "توکن SCP رد شد — دوباره vpn-mon-netcup-login.",
    "scp_refresh_http_401": "توکن SCP رد شد — دوباره vpn-mon-netcup-login.",
    "no_server_id": "سرور در پاسخ SCP شناسه نداشت.",
}


def scp_err_fa(code: str) -> str:
    code = (code or "").strip()
    if code in SCP_ERR_FA:
        return SCP_ERR_FA[code]
    if code.startswith("scp_http_"):
        return f"API نت‌کاپ جواب HTTP {code.split('_')[-1]} داد (موقت یا محدودیت)."
    if code.startswith("scp_refresh_http_"):
        return f"تمدید توکن SCP با HTTP {code.split('_')[-1]} شکست خورد — vpn-mon-netcup-login."
    if code.startswith("no_server_match:"):
        return "نام سرور در SCP پیدا نشد؛ NETCUP_VSERVER_NAME را چک کنید."
    return f"خطای SCP: {code}"


def notify_cooldown(key: str, cooldown_sec: int) -> bool:
    st = load_state()
    bag = dict(st.get("_notify") or {})
    now = time.time()
    if now - float(bag.get(key) or 0) < cooldown_sec:
        return False
    bag[key] = now
    st["_notify"] = bag
    save_state(st)
    return True


def vnstat_rx_since(reset_day: int) -> tuple[int | None, str]:
    try:
        raw = subprocess.check_output(["vnstat", "--json", "d"], text=True, timeout=10)
        doc = json.loads(raw)
    except Exception:
        return proc_rx_estimate(reset_day), "proc"

    today = dt.date.today()
    day = max(1, min(28, reset_day))
    if today.day >= day:
        start = dt.date(today.year, today.month, day)
    else:
        if today.month == 1:
            start = dt.date(today.year - 1, 12, day)
        else:
            start = dt.date(today.year, today.month - 1, day)

    total = 0
    found = False
    for iface in doc.get("interfaces") or []:
        days = ((iface.get("traffic") or {}).get("day")) or []
        for row in days:
            y = int(row.get("date", {}).get("year") or 0)
            m = int(row.get("date", {}).get("month") or 0)
            d = int(row.get("date", {}).get("day") or 0)
            try:
                when = dt.date(y, m, d)
            except ValueError:
                continue
            if when >= start:
                total += int(row.get("rx") or 0)
                found = True
    if found:
        return total, "vnstat_rx"
    return proc_rx_estimate(reset_day), "proc"


def proc_rx_estimate(reset_day: int) -> int | None:
    c = cfg()
    iface = c["IFACE"]
    p = Path(f"/sys/class/net/{iface}/statistics/rx_bytes")
    if not p.exists():
        return None
    now_rx = int(p.read_text().strip())
    st = load_state()
    snap = st.get("quota_rx_snap") or {}
    cycle = f"{dt.date.today().year}-{dt.date.today().month:02d}-{int(reset_day):02d}"
    if snap.get("cycle") != cycle:
        st["quota_rx_snap"] = {"cycle": cycle, "rx": now_rx}
        save_state(st)
        return 0
    return max(0, now_rx - int(snap.get("rx") or 0))


def vnstat_rolling_24h() -> dict | None:
    """Local TX+RX over the last ~24 hourly buckets (fallback when SCP is down)."""
    try:
        raw = subprocess.check_output(["vnstat", "--json", "h"], text=True, timeout=10)
        doc = json.loads(raw)
    except Exception:
        return None
    hours: list[dict] = []
    for iface in doc.get("interfaces") or []:
        hours = ((iface.get("traffic") or {}).get("hour")) or []
        if hours:
            break
    if not hours:
        return None
    rows = hours[-24:]
    inn = sum(int(h.get("rx") or 0) for h in rows)
    out = sum(int(h.get("tx") or 0) for h in rows)
    return {
        "in_bytes": inn,
        "out_bytes": out,
        "total_bytes": inn + out,
        "recent_mbps": 0.0,
        "buckets": len(rows),
        "source": "vnstat_local_24h",
        "server_id": None,
        "name": "local",
    }


def maybe_iran_reminder(c: dict) -> None:
    reset_day = int(c.get("IRAN_QUOTA_RESET_DAY") or 26)
    now = dt.datetime.now()
    if now.day != reset_day or now.hour < 8 or now.hour > 11:
        return
    st = load_state()
    stamp = f"quota_reminder_IRAN_{now.year}_{now.month:02d}"
    if st.get(stamp):
        return
    st[stamp] = True
    save_state(st)
    send(
        "quota",
        "info",
        "یادآوری: امروز روز ریست سهمیه ترافیک ایران است",
        [
            "سقف ماهانه ایران: فقط دانلود (RX) ۱.۵ ترابایت.",
            f"روز ریست: {reset_day} هر ماه.",
            "عدد دقیق را در پنل ارائه‌دهنده هم چک کنید.",
        ],
    )


def fire_iran_levels(used: int, quota: int, source: str, extra: list[str], reset_day: int) -> None:
    if quota <= 0:
        return
    pct = used / quota * 100
    left = days_left_in_month(reset_day)
    st = load_state()
    cycle = dt.date.today().strftime("%Y-%m")
    rec = st.get("quota_levels") or {}
    if rec.get("cycle") != cycle:
        rec = {"cycle": cycle, "sent": []}
    sent = list(rec.get("sent") or [])
    details = [
        f"مصرف: {fmt_bytes(used)} از {fmt_bytes(quota)} ({pct:.1f}%)",
        f"تقریباً {left} روز تا ریست مانده",
        f"منبع عدد: {source}",
        *extra,
    ]
    for lv in IRAN_LEVELS:
        if pct >= lv and lv not in sent:
            sent.append(lv)
            rec["sent"] = sent
            rec["cycle"] = cycle
            st["quota_levels"] = rec
            save_state(st)
            send("quota", "breach", f"سهمیه ترافیک ایران به {lv}٪ رسید", details)


def current_band(pct: float) -> int:
    if pct >= 95:
        return 95
    if pct >= 80:
        return 80
    if pct >= 60:
        return 60
    return 0


def local_mbps() -> float:
    """Iface TX+RX bits/s since last quota run."""
    c = cfg()
    iface = c["IFACE"]
    cur = iface_counters(iface)
    now = time.time()
    st = load_state()
    prev = st.get("_exit_bw") or {}
    st["_exit_bw"] = {"ts": now, "rx": cur["rx_bytes"], "tx": cur["tx_bytes"]}
    save_state(st)
    if not prev.get("ts") or now <= float(prev["ts"]) + 1:
        return 0.0
    elapsed = now - float(prev["ts"])
    bps = (
        cur["rx_bytes"] - int(prev.get("rx") or 0) + cur["tx_bytes"] - int(prev.get("tx") or 0)
    ) / elapsed
    return max(0.0, bps * 8 / 1_000_000)


def exit_rolling() -> None:
    c = cfg()
    limit = int(c.get("EXIT_ROLLING_LIMIT_BYTES") or 2_000_000_000_000)
    throttle_mbit = float(c.get("EXIT_THROTTLE_MBIT") or 200)
    vname = c.get("NETCUP_VSERVER_NAME") or "v2202608400527502404"

    info = None
    scp_fail = ""
    try:
        info = rolling_24h(vname)
    except SystemExit as e:
        scp_fail = str(e)
    except Exception as e:
        scp_fail = type(e).__name__

    if info is None:
        info = vnstat_rolling_24h()
        if info is None:
            if notify_cooldown("scp_quota_fail", SCP_FAIL_COOLDOWN):
                send(
                    "quota",
                    "info",
                    "نتوانستم ترافیک ۲۴ساعته آلمان را بخوانم",
                    [
                        scp_err_fa(scp_fail) if scp_fail else "هم SCP و هم vnstat محلی شکست خوردند.",
                        "سقف آلمان ماهانه نیست؛ آستانه خطر: ۲ ترابایت در هر ۲۴ ساعت غلتان.",
                        f"اگر از ۲TB رد شود، نت‌کاپ لینک را حدود {throttle_mbit:.0f} مگابیت می‌کند.",
                    ],
                )
            return
        if scp_fail and notify_cooldown("scp_quota_fail", SCP_FAIL_COOLDOWN):
            send(
                "quota",
                "info",
                "API نت‌کاپ قطع بود — موقتاً از آمار محلی استفاده می‌کنم",
                [
                    scp_err_fa(scp_fail),
                    f"تخمین محلی ۲۴ساعته: {fmt_bytes(info['total_bytes'])} "
                    f"({100 * info['total_bytes'] / limit:.1f}% از ۲TB).",
                    "هشدار سهمیه همچنان کار می‌کند؛ فقط منبع عدد محلی است.",
                ],
            )

    used = int(info["total_bytes"])
    source = info["source"]
    recent = float(info.get("recent_mbps") or 0)
    pct = (used / limit * 100) if limit else 0
    loc = local_mbps()

    details = [
        f"مصرف ۲۴ساعته: {fmt_bytes(used)} از ۲ ترابایت ({pct:.1f}%)",
        f"ورود {fmt_bytes(info['in_bytes'])} · خروج {fmt_bytes(info['out_bytes'])}",
        f"سرعت تقریبی اخیر: API≈{recent:.0f} / کارت≈{loc:.0f} مگابیت",
        f"منبع: {'پنل نت‌کاپ' if source.startswith('scp') else 'آمار محلی سرور'} ({info.get('buckets') or '?'} نمونه)",
        f"اگر از ۲TB/۲۴ساعت رد شود → محدودیت حدود {throttle_mbit:.0f} مگابیت.",
    ]

    st = load_state()
    rec = st.get("exit_rolling") or {}
    prev_band = int(rec.get("band") or 0)
    band = current_band(pct)
    rec["band"] = band
    rec["used"] = used
    rec["pct"] = pct
    rec["source"] = source
    st["exit_rolling"] = rec
    save_state(st)

    if band > prev_band and band in EXIT_ROLLING_LEVELS:
        send("quota", "breach", f"ترافیک ۲۴ساعته آلمان به {band}٪ از ۲ ترابایت رسید", details)
    elif prev_band >= 60 and band < prev_band:
        send(
            "quota",
            "recovery",
            f"ترافیک ۲۴ساعته آلمان برگشت به {band or 'زیر ۶۰'}٪",
            details,
        )

    near_cap = 150 <= max(recent, loc) <= (throttle_mbit + 30)
    high_window = used >= limit or pct >= 95
    throttled = bool(used >= limit or (high_window and near_cap))
    ev = evaluate("exit_throttle", throttled, sustain=0, cooldown=int(c.get("COOLDOWN_SEC") or 1800))
    if ev in ("breach", "rebreach"):
        send(
            "quota",
            "breach",
            f"احتمال محدودیت سرعت نت‌کاپ (~{throttle_mbit:.0f} مگابیت)",
            details + [f"پنجره ۲۴ساعته الان {pct:.1f}% پر است."],
        )
    elif ev == "recovery":
        send("quota", "recovery", "محدودیت ~۲۰۰ مگابیت ظاهراً برداشته شد", details)


def main() -> None:
    c = cfg()
    if role() == "exit":
        exit_rolling()
        return

    # Iran monthly quota alerts disabled on purpose: the Iranian DC (${IRAN_PROVIDER})
    # already SMS/emails the operator. Local vnstat estimates disagreed with
    # their billing and only created noise on Telegram.
    return


if __name__ == "__main__":
    main()
