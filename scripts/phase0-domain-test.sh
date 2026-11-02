#!/bin/bash
# Domain viability from the current host (intended to run ON the Iran relay).
set -u
OUT="${1:-/tmp/phase0-results.txt}"
{
echo "PHASE0_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "HOST=$(hostname) IP=$(hostname -I | awk '{print $1}')"
echo "RESOLVER=$(grep -E '^nameserver' /etc/resolv.conf | awk '{print $2}' | paste -sd,)"
echo

probe_dns() {
  local h="$1"
  echo "=== DNS $h ==="
  local a
  a=$(dig +time=3 +tries=2 +short A "$h" 2>/dev/null | grep -E '^[0-9.]+$' | paste -sd,)
  echo "A=$a"
  local aaaa
  aaaa=$(dig +time=3 +tries=2 +short AAAA "$h" 2>/dev/null | paste -sd,)
  echo "AAAA=$aaaa"
}

probe_tls() {
  local h="$1"
  echo "=== TLS $h ==="
  local i
  for i in 1 2 3; do
    local code
    code=$(curl -sS -o /dev/null -w "%{http_code}|%{ssl_verify_result}|%{time_connect}|%{errormsg}" \
      --connect-timeout 8 --max-time 15 -vI "https://$h/" 2>/tmp/curl_$h.$i.err || true)
    echo "RUN$i HTTP=$code"
    # SNI / handshake signatures
    if grep -qiE 'Connection reset|sslv3 alert|handshake failure|Client hello' /tmp/curl_$h.$i.err; then
      echo "RUN$i SIG=$(grep -iE 'reset|alert|handshake|Connected|SSL connection' /tmp/curl_$h.$i.err | head -5 | tr '\n' ' ; ')"
    else
      echo "RUN$i TLS_SUMMARY=$(grep -iE 'SSL connection|Connected to|subject:|expire date|error' /tmp/curl_$h.$i.err | head -8 | tr '\n' ' ; ')"
    fi
  done
}

probe_sni_ip() {
  local h="$1"
  local ip="$2"
  echo "=== SNI $h -> $ip ==="
  local i
  for i in 1 2 3; do
    local out
    out=$(timeout 8 openssl s_client -connect "${ip}:443" -servername "$h" -tls1_3 </dev/null 2>&1 | tr -d '\r')
    local ok
    if echo "$out" | grep -q "Verify return code"; then
      ok=$(echo "$out" | grep "Verify return code" | head -1)
      echo "RUN$i OPENSSL_OK $ok"
    elif echo "$out" | grep -qiE 'reset|handshake failure|sslv3 alert|no peer certificate'; then
      echo "RUN$i OPENSSL_FAIL $(echo "$out" | grep -iE 'reset|failure|alert|error|errno' | head -3 | tr '\n' ' ; ')"
    else
      echo "RUN$i OPENSSL_OTHER $(echo "$out" | tail -5 | tr '\n' ' ; ')"
    fi
  done
}

for h in ${EXTRA_ZONE} cdn.${EXTRA_ZONE} ir.${EXTRA_ZONE} ${PANEL_DOMAIN_EXTRA} \
         ${MAIN_ZONE} ${XHTTP_DOMAIN} \
         ${ALT_ZONE} ${CF_GRAY_DOMAIN_ALT} ${IRAN_DOMAIN_ALT}; do
  probe_dns "$h"
  probe_tls "$h"
  echo
done

echo "=== SNI to Cloudflare-like / origin IPs if resolved ==="
for h in ${EXTRA_ZONE} cdn.${EXTRA_ZONE} ${MAIN_ZONE} ${ALT_ZONE}; do
  ip=$(dig +time=3 +tries=1 +short A "$h" 2>/dev/null | grep -E '^[0-9.]+$' | head -1)
  if [ -n "$ip" ]; then
    probe_sni_ip "$h" "$ip"
  else
    echo "NO_A $h"
  fi
  echo
done

echo "=== REALITY DEST CANDIDATES ==="
for h in www.microsoft.com www.apple.com www.samsung.com www.bing.com \
         www.cloudflare.com www.gstatic.com www.office.com update.microsoft.com; do
  echo "--- $h ---"
  probe_dns "$h"
  code=$(curl -sS -o /dev/null -w "%{http_code}|tls=%{ssl_verify_result}|t=%{time_appconnect}" \
    --connect-timeout 8 --max-time 12 -I "https://$h/" 2>/dev/null || echo FAIL)
  echo "HTTPS $code"
  # TLS1.3 check
  tls=$(timeout 8 openssl s_client -connect "${h}:443" -servername "$h" </dev/null 2>/dev/null | grep -E 'Protocol  :|Verify return code' | tr '\n' ' ')
  echo "OPENSSL $tls"
  echo
done

echo "=== IRAN to EXIT baseline ==="
ping -c 20 -W 2 ${EXIT_IP} | tail -5
echo "TCP 443"
timeout 5 bash -c 'echo >/dev/tcp/${EXIT_IP}/443' && echo TCP443_OPEN || echo TCP443_FAIL
echo "TCP 9443"
timeout 5 bash -c 'echo >/dev/tcp/${EXIT_IP}/9443' && echo TCP9443_OPEN || echo TCP9443_FAIL
echo "TCP 22"
timeout 5 bash -c 'echo >/dev/tcp/${EXIT_IP}/22' && echo TCP22_OPEN || echo TCP22_FAIL
echo "UDP 443 probe (nc)"
timeout 4 nc -u -z -w 3 ${EXIT_IP} 443 && echo UDP443_NC_OK || echo UDP443_NC_FAIL
echo "UDP 8443 probe"
timeout 4 nc -u -z -w 3 ${EXIT_IP} 8443 && echo UDP8443_NC_OK || echo UDP8443_NC_FAIL

echo "=== MTU binary search DF ping to exit ==="
# start from 1472 (1500-28) down
low=1200
high=1472
best=1200
while [ "$low" -le "$high" ]; do
  mid=$(( (low+high)/2 ))
  if ping -c 1 -W 2 -M do -s "$mid" ${EXIT_IP} >/dev/null 2>&1; then
    best=$mid
    low=$((mid+1))
  else
    high=$((mid-1))
  fi
done
echo "MAX_DF_PAYLOAD=$best  APPROX_MTU=$((best+28))"
echo "PHASE0_DONE"
} | tee "$OUT"
