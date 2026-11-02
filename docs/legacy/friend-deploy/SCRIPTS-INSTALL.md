# اسکریپت‌ها: چیست، کجا نصب می‌شود، چطور

بسته: `vpn-infra-portable-scripts.tar.gz` — بدون `__pycache__`، بدون لیست کاربر اینستا، بدون `.env` سکرت.

قبل از نصب روی سرور جدید این رشته‌ها را در فایل‌ها عوض کنید:

- `${IRAN_IP}` → IP رله ایران جدید
- `${EXIT_IP}` → IP Exit جدید
- `root@${IRAN_IP}` → `root@<ایران>`
- دامنه‌های `${MAIN_ZONE}` / `${ALT_ZONE}` / `${EXTRA_ZONE}` → دامنهٔ دوست
- مسیر `/root/vpn-infra` اگر ریپو جای دیگری است

فرض این سند: کد روی هر دو سرور در `/root/vpn-infra/` است.

---

## ۱) vpn-path (شما نوشتید vpn-patch — همان است)

**کار:** مسیر بک‌هال را در **هستهٔ پنل** عوض می‌کند (`TO-AMS-CF` / `XHTTP` / `DIRECT` / `TUIC` / `auto`). منبع حقیقت JSON هسته است نه فایل systemd ایران.

**کجا:** فقط **Exit (آلمان)**. روی ایران اگر چیزی به نام vpn-path باشد، stub است.

**فایل‌ها**

```
scripts/vpn-path                 → /usr/local/sbin/vpn-path
scripts/vpn-path-core.py
scripts/vpn_path_lib.py
scripts/vpn_paths.py
scripts/vpn-path-iran-stub.sh    → ایران /usr/local/sbin/vpn-path (اختیاری)
scripts/path_health.py           → سلامت از دید ایران (failover صدا می‌زند)
scripts/vpn_failover.py
configs/vpn-failover.service
configs/vpn-failover.timer
```

**نصب Exit**

```bash
install -m 755 /root/vpn-infra/scripts/vpn-path /usr/local/sbin/vpn-path
install -m 644 /root/vpn-infra/configs/vpn-failover.service \
               /root/vpn-infra/configs/vpn-failover.timer /etc/systemd/system/
# vpn_path_lib از /root/vpn-infra/scripts ایمپورت می‌شود — ریپو باید همان‌جا باشد
# یا PYTHONPATH را در unit مشخص کنید
mkdir -p /var/log/vpn-path
systemctl daemon-reload
systemctl enable --now vpn-failover.timer
vpn-path status
```

دستورات: `vpn-path status|auto|cf|xhttp|direct|tuic|publish|test`

**نصب ایران (stub)**

```bash
install -m 755 /root/vpn-infra/scripts/vpn-path-iran-stub.sh /usr/local/sbin/vpn-path
```

وابستگی: پنل Docker، `PG_CORE_ID` و API در `/root/.vpn-secrets/.env`، SSH به ایران برای health/publish.

---

## ۲) instagram-multiplier

**کار:** برای چند user id پنل، ترافیک دامنه‌های اینستاگرام جدا شمرده می‌شود و با ضریب (پیش‌فرض ۱٫۵) به `used_traffic` اضافه می‌شود. اتصال را قطع نمی‌کند؛ outbound کلون همان بک‌هال است.

**کجا:** CLI و inject روی **Exit**. قوانین CAT روی Xray **ایران** می‌نشینند (وسط export).

**فایل‌ها**

```
scripts/instagram-multiplier     → /usr/local/sbin/instagram-multiplier
scripts/instagram_multiplier.py
configs/monitor/instagram-multiplier.env  → /etc/vpn-monitor/instagram-multiplier.env
# لیست کاربر را نسازید از استک ما؛ خالی شروع کنید:
# /etc/vpn-monitor/instagram-multiplier-users.txt
```

حتماً `iran_sync_export.py` (مرحله inject) و `iran_stats_ingest.py` (وزن‌دهی آمار) هم از بسته نصب شوند وگرنه CLI تنها لیست را عوض می‌کند و روی هسته اثر ندارد.

**نصب Exit**

```bash
mkdir -p /etc/vpn-monitor
chmod 700 /etc/vpn-monitor
install -m 755 /root/vpn-infra/scripts/instagram-multiplier /usr/local/sbin/instagram-multiplier
cp /root/vpn-infra/configs/monitor/instagram-multiplier.env /etc/vpn-monitor/
chmod 600 /etc/vpn-monitor/instagram-multiplier.env
cat > /etc/vpn-monitor/instagram-multiplier-users.txt << 'EOF'
# Panel user ids, one per line. Comments allowed.
EOF
chmod 600 /etc/vpn-monitor/instagram-multiplier-users.txt
```

**استفاده**

```bash
instagram-multiplier add <username-پنل>
instagram-multiplier remove <username>
instagram-multiplier list
```

بعد از add، export همان لحظه زده می‌شود. لاگ وزن: `/var/log/vpn-path/stats.log` فیلدهای `u<id>_ig=`.

صفحه وب روی Exit (لاگین جدا): `https://panel…:2096/ig/` — بسته `scripts/ig-mult-web/`، سرویس `ig-mult-web` روی `127.0.0.1:8788`، `location /ig/` در nginx. مسیر وی‌پی‌ان را عوض نمی‌کند؛ فقط حسابداری حجم است.

لیست را در git نگذارید.

---

## ۳) sni-watch — صفحه `https://panel…:2096/watch/`

**کار:** محتوای HTTPS را نمی‌خواند. از access log Xray فقط **hostname (SNI)** را با فهرست دامنه مقایسه می‌کند. لاگین جدا از PasarGuard.

**کجا:** سرویس روی **ایران** (همان‌جا که کلاینت وصل می‌شود و `email:` در لاگ id پنل است). روی Exit فقط تونل SSH و reverse-proxy nginx و resolve نام→id.

**فایل‌ها**

```
scripts/sni-watch/install.sh
scripts/sni-watch/app.py
scripts/sni-watch/adult-domains.txt
scripts/sni-watch/sni-watch.service
scripts/sni-watch/xray-stdin-wrap.*
scripts/sni-watch/ensure_xray_wrap.sh
scripts/sni-watch/resolve_watchlist.py
configs/sni-watch/sni-watch-tunnel.service   # Exit: ssh -L 8787
configs/sni-watch/sni-watch-resolve.timer
configs/nginx-panel.conf   # قطعه location /watch/
```

لاگ خام نود IP کلاینت است نه SNI کافی؛ wrap روی `xray -c stdin:` لاگ `sni-access.log` می‌سازد.

**نصب ایران**

```bash
cd /root/vpn-infra/scripts/sni-watch
sudo AUTH_USER=watch AUTH_PASS='رمز-قوی' ./install.sh
# listen پیش‌فرض 127.0.0.1:8787 — پورت را به جهان باز نکنید
# wrap:
# scripts/sni-watch/ensure_xray_wrap.sh را طبق docs/sni-watch.md بعد از بالا آمدن node اجرا کنید
```

رمز در `/etc/sni-watch/admin.pass` (mode 600).

**نصب Exit**

1. در nginx پنل (`:2096`):

```nginx
location = /watch { return 301 /watch/; }
location /watch/ {
    proxy_pass http://127.0.0.1:8787/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_read_timeout 60;
}
```

2. تونل: در `sni-watch-tunnel.service` IP ایران را عوض کنید، بعد:

```bash
install -m 644 /root/vpn-infra/configs/sni-watch/sni-watch-tunnel.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now sni-watch-tunnel.service
```

3. resolve نام کاربری (اختیاری ولی لازم برای UI):

```bash
install -m 644 /root/vpn-infra/configs/sni-watch/sni-watch-resolve.service \
               /root/vpn-infra/configs/sni-watch/sni-watch-resolve.timer /etc/systemd/system/
systemctl enable --now sni-watch-resolve.timer
```

صفحه: `https://panel.<دامنه>:2096/watch/` — مستندات داخلی: `/watch/docs`

---

## ۴) اسکریپت‌های دیگر که باید منتقل شوند (بازنویسی نکنید)

این‌ها «ابزار سوم» نیستند؛ ستون فقرات کنترل‌پلین‌اند. بدون این‌ها پنل کاربر را به ایران نمی‌رساند.

| اسکریپت / unit | سرور | کار |
|---|---|---|
| `iran_sync_export.py` | Exit | ساخت proto از sqlite + SCP |
| `build_iran_start_proto.py` | داخل container پنل (export کپی می‌کند) | protobuf Backend |
| `iran_sync_apply.py` | ایران | localhost `/start` |
| `iran_stats_ingest.py` | Exit | آمار Xray ایران → sqlite |
| `iran-sync-*.timer/service` | هر کدام روی سرور خودش | هر ۱۰ث |
| `iran-stats.timer/service` | Exit | هر ۳۰ث |
| `cf_dns.py` | Exit | upsert DNS کلادفلر |
| `panel-via-backhaul` | ایران | helper دسترسی پنل از SOCKS |
| nginx + `xray-subproxy.*` | ایران | پروکسی پنل ۲۰۹۶ |
| `scripts/monitor/install.sh` | هر دو | ظرفیت/هارد/سهمیه/گوگل |
| `backup-vpn.sh` | Exit | بکاپ |
| `sshd-key-only.sh` | هر دو | قطع پسورد SSH |
| `render_iran_configs.py` / `render_exit_configs.py` | یک‌بار | قالب JSON از سکرت؛ IP داخلشان مثال است |
| `pg_bootstrap_panel.py` | یک‌بار | موجودیت اولیه پنل |
| `netcup_oauth.py` | فقط اگر سرور نت‌کاپ دارید | به استک دوست مربوط نیست مگر همان ISP |

**نصب سینک (خلاصه)**

Exit:

```bash
install -m 644 /root/vpn-infra/configs/iran-sync-export.service \
               /root/vpn-infra/configs/iran-sync-export.timer \
               /root/vpn-infra/configs/iran-stats.service \
               /root/vpn-infra/configs/iran-stats.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now iran-sync-export.timer iran-stats.timer
```

ایران:

```bash
install -m 755 /root/vpn-infra/scripts/iran_sync_apply.py /usr/local/sbin/iran_sync_apply.py
install -m 644 /root/vpn-infra/configs/iran-sync-apply.service \
               /root/vpn-infra/configs/iran-sync-apply.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now iran-sync-apply.timer
```

مانیتور:

```bash
# روی آلمان:
/root/vpn-infra/scripts/monitor/install.sh exit
# روی ایران:
/root/vpn-infra/scripts/monitor/install.sh iran
# NETCUP_* را اگر سرور نت‌کاپ نیست از config.env حذف/خالی کنید
```

---

## ۵) آنچه نباید به‌عنوان «اسکریپت آماده» کپی شود

- `bootstrap-iran.sh` — با docker node زنده سازگار نیست مگر بازنویسی شود
- لیست اینستاگرام زنده
- هر فایل داخل `/root/.vpn-secrets/`
- `__pycache__`
