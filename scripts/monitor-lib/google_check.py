#!/usr/bin/env python3
"""Monitor 4 (ongoing): Google/Gemini abuse interstitial via local SOCKS or direct."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import cfg, evaluate, role, send  # noqa: E402


def fetch(url: str, socks: str | None) -> tuple[int, str]:
    cmd = [
        "curl", "-sS", "-o", "-", "-w", "\n__HTTP__%{http_code}",
        "-L", "--max-redirs", "5", "--max-time", "15",
        "-A", "Mozilla/5.0 (Windows NT 10.0; rv:128.0) Gecko/20100101 Firefox/128.0",
    ]
    if socks:
        cmd.extend(["--socks5-hostname", socks])
    cmd.append(url)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except Exception as e:
        return 0, str(e)[:200]
    body = p.stdout or ""
    code = 0
    if "__HTTP__" in body:
        body, _, tail = body.rpartition("__HTTP__")
        try:
            code = int(tail.strip() or "0")
        except ValueError:
            code = 0
    return code, body


def blocked(body: str, code: int) -> bool:
    b = body.lower()
    if "/sorry/" in b or "sorry/index" in b:
        return True
    if "unusual traffic" in b or "detected unusual traffic" in b:
        return True
    if "not supported in your country" in b or "isn't available in your country" in b:
        return True
    if "not available in your country" in b:
        return True
    return False


def main() -> None:
    socks = "127.0.0.1:10808" if role() == "exit" else "127.0.0.1:11080"
    url = "https://gemini.google.com/"
    code, body = fetch(url, socks)
    bad = blocked(body, code)
    details = [
        f"url={url}",
        f"http={code} socks={socks}",
        "اگر /sorry باشد تشخیص سوءاستفاده گوگل است (IP دیتاسنتر/VPN)، نه لزوماً کشور آلمان.",
    ]
    c = cfg()
    cooldown = int(c.get("COOLDOWN_SEC") or 1800)
    # daily-ish re-alert: 12h
    ev = evaluate("google_sorry", bad, sustain=0, cooldown=max(cooldown, 43200))
    if ev in ("breach", "rebreach"):
        send("google", "breach", "Gemini/Google صفحه sorry یا geo-block برگرداند", details)
    elif ev == "recovery":
        send("google", "recovery", "پاسخ Gemini دیگر sorry/geo-block نیست", details)


if __name__ == "__main__":
    main()
