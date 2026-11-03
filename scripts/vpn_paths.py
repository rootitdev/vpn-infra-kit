"""Backhaul path names shared by vpn-path, health, and failover.

HY2/TUIC removed: UDP from Iranian DCs is reliably filtered.
CDN standbys (Gcore/Bunny) carry the same XHTTP origin as grey hosts.
CF orange is watched via TO-AMS-CFORANGE (not in auto failover until proven).
"""
from __future__ import annotations

# Live failover order. CFORANGE is intentionally excluded from auto switching.
import os as _os

# Mode-specific default failover order (override with PATH_PRIORITY in .env, comma-separated tags or short names).
DEFAULT_PRIORITY = {
    "standalone": ["TO-AMS-REALITY", "TO-AMS-SSH", "TO-AMS-GCORE", "TO-AMS-BUNNY", "TO-AMS-XHTTP", "TO-AMS-CF", "TO-AMS-DIRECT"],
    # master: CDN-first so the shared master's IP is exposed as little as possible
    "master": ["TO-AMS-XHTTP", "TO-AMS-GCORE", "TO-AMS-CF", "TO-AMS-REALITY", "TO-AMS-DIRECT"],
}
_SHORT = {"reality": "TO-AMS-REALITY", "ssh": "TO-AMS-SSH", "xhttp": "TO-AMS-XHTTP", "gcore": "TO-AMS-GCORE", "bunny": "TO-AMS-BUNNY",
          "cf": "TO-AMS-CF", "direct": "TO-AMS-DIRECT", "cforange": "TO-AMS-CFORANGE"}


def _env_file_value(key: str) -> str:
    v = _os.environ.get(key, "")
    if v:
        return v
    try:
        for line in open("/root/.vpn-secrets/.env"):
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"\'')
    except OSError:
        pass
    return ""


def _priority() -> list[str]:
    raw = _env_file_value("PATH_PRIORITY")
    if raw:
        tags = [_SHORT.get(t.strip().lower(), t.strip()) for t in raw.split(",") if t.strip()]
        tags = [t for t in tags if t != "TO-AMS-CFORANGE"]  # CFORANGE is never auto-selected
        if tags:
            return tags
    return list(DEFAULT_PRIORITY.get(_env_file_value("INSTALL_MODE") or "standalone", DEFAULT_PRIORITY["standalone"]))


# Live failover order. CFORANGE is intentionally excluded from auto switching.
PRIORITY = _priority()
# Probe + UI only: Cloudflare orange canary. Manual lock allowed; auto never picks it.
WATCH_ONLY = ["TO-AMS-CFORANGE"]
REMOVED = ["TO-AMS-HY2", "TO-AMS-TUIC"]
ALL_LIVE = list(PRIORITY) + list(WATCH_ONLY)
MAP = {
    "auto": list(PRIORITY),
    "direct": ["TO-AMS-DIRECT"],
    "reality": ["TO-AMS-REALITY"],
    "ssh": ["TO-AMS-SSH"],
    "xhttp": ["TO-AMS-XHTTP"],
    "gcore": ["TO-AMS-GCORE"],
    "bunny": ["TO-AMS-BUNNY"],
    "cf": ["TO-AMS-CF"],
    "cforange": ["TO-AMS-CFORANGE"],
}
FALLBACK = "TO-AMS-DIRECT"
FAIL_STREAK = 3
FAILBACK_STREAK = 5
# Anti-flap: switch target must pass this many runs in a row; no switch within cooldown.
NEXT_OK_STREAK = 2
SWITCH_COOLDOWN_SEC = 120
HEALTH_INTERVAL_SEC = 12
SYNC_INTERVAL_SEC = 10

# Admin panel hostnames. From Iran must use tunneled TO-AMS-DIRECT (not the VPN
# path selector): cleartext :2096 is DPI-dropped, but pinning panel.* to CF/XHTTP
# with the user path causes nginx 502 on /dashboard|/settle|/path when that path dies.
PANEL_DOMAINS = [
    "full:${PANEL_DOMAIN}",
    "full:${PANEL_DOMAIN_ALT}",
    "full:${PANEL_DOMAIN_EXTRA}",
]
PANEL_RULE_MARK = "full:${PANEL_DOMAIN}"

# Public hostnames for XHTTP CDN / grey probes (Iran → edge → Exit :443).
PATH_HOSTS = {
    "TO-AMS-CF": "${CF_GRAY_DOMAIN}",
    "TO-AMS-XHTTP": "${XHTTP_DOMAIN}",
    "TO-AMS-GCORE": "${GCORE_DOMAIN}",
    "TO-AMS-BUNNY": "${BUNNY_DOMAIN}",
    "TO-AMS-CFORANGE": "${CFORANGE_DOMAIN}",
    "TO-AMS-REALITY": "${EXIT_IP}:${REALITY_PORT} (sni ${REALITY_SERVER_NAME})",
}
