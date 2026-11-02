#!/bin/bash
# Lightweight path health logger (no Telegram).
set -u
LOG=/var/log/vpn-monitor/health.log
mkdir -p "$(dirname "$LOG")"
ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
ok() { echo "$ts $1 OK $2" >> "$LOG"; }
bad() { echo "$ts $1 FAIL $2" >> "$LOG"; }

tls_ok() {
  timeout 5 openssl s_client -connect "127.0.0.1:$1" -servername ${CF_GRAY_DOMAIN} </dev/null 2>/dev/null | grep -q "Verify return code"
}

if tls_ok 443; then ok local-xhttp-443 ""; else bad local-xhttp-443 ""; fi
if tls_ok 9443; then ok local-direct-9443 ""; else bad local-direct-9443 ""; fi
if ss -ulnp | grep -qE ':(4443|443) '; then ok local-hy2-udp ""; else bad local-hy2-udp ""; fi
# tuic removed

code=$(timeout 15 curl -sS -o /dev/null -w "%{http_code}" --max-time 12 --socks5-hostname 127.0.0.1:10808 https://www.google.com/generate_204 || echo 000)
if [ "$code" = "204" ] || [ "$code" = "200" ]; then ok google-socks "$code"; else bad google-socks "$code"; fi
code2=$(timeout 15 curl -sS -o /dev/null -w "%{http_code}" --max-time 12 --socks5-hostname 127.0.0.1:10808 https://gemini.google.com/ || echo 000)
if [ "$code2" != "000" ]; then ok gemini-socks "$code2"; else bad gemini-socks "$code2"; fi

find /var/log/vpn-monitor -name '*.log' -mtime +3 -delete 2>/dev/null || true
