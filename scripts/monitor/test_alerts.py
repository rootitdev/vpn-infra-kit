#!/usr/bin/env python3
"""Send one test alert per monitor (always logs; Telegram if creds exist)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import cfg, send  # noqa: E402


def main() -> None:
    c = cfg()
    has_tg = bool(c.get("TELEGRAM_BOT_TOKEN") and c.get("TELEGRAM_CHAT_ID"))
    extra = ["telegram=configured" if has_tg else "telegram=NOT configured — فقط فایل لاگ"]
    send("capacity", "test", "تست مانیتور ظرفیت (اتصالات/پهنای باند/مسیر)", extra)
    send("hardware", "test", "تست مانیتور سخت‌افزار (CPU/RAM/NIC errors)", extra)
    send("quota", "test", "تست مانیتور سهمیه ترافیک", extra + ["ایران: فقط RX / ۱.۵TB"])
    send("google", "test", "تست مانیتور Google/Gemini sorry page", extra)
    send("boot", "test", "تست مانیتور پایداری بوت", extra)
    print("logged_tests=5 telegram=" + ("yes" if has_tg else "no"))


if __name__ == "__main__":
    main()
