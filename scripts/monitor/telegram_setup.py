#!/usr/bin/env python3
"""Resolve TELEGRAM_CHAT_ID from getUpdates after you message the bot. Never prints the token."""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import SECRETS, SECRETS_IRAN, cfg  # noqa: E402


def upsert(path: Path, key: str, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text().splitlines() if path.exists() else []
    out = []
    found = False
    for ln in lines:
        if ln.startswith(key + "="):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(ln)
    if not found:
        out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n")
    path.chmod(0o600)


def main() -> None:
    c = cfg()
    token = c.get("TELEGRAM_BOT_TOKEN") or ""
    if not token:
        print("missing TELEGRAM_BOT_TOKEN")
        print("1. In Telegram open @BotFather")
        print("2. /newbot  then copy the token")
        print("3. Put TELEGRAM_BOT_TOKEN=... in /root/.vpn-secrets/.env (Exit)")
        print("   and /etc/vpn-monitor/secrets.env (Iran)")
        print("4. Message your bot once, then rerun: python3 /usr/local/lib/vpn-monitor/telegram_setup.py")
        sys.exit(2)
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print("getUpdates_fail", type(e).__name__)
        sys.exit(1)
    if not data.get("ok"):
        print("telegram_api_not_ok")
        sys.exit(1)
    chat_id = None
    for upd in data.get("result") or []:
        msg = upd.get("message") or upd.get("edited_message") or {}
        chat = msg.get("chat") or {}
        if chat.get("id") is not None:
            chat_id = str(chat["id"])
    if not chat_id:
        print("no_chat_yet — send any message to the bot, then rerun")
        sys.exit(3)
    for p in (SECRETS, SECRETS_IRAN):
        if p == SECRETS and not p.exists():
            continue
        upsert(p if p.exists() or p == SECRETS else SECRETS_IRAN, "TELEGRAM_CHAT_ID", chat_id)
    print("chat_id_saved")


if __name__ == "__main__":
    main()
