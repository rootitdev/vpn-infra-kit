# راهنمای پیاده‌سازی استک VPN دوهاب — ۹ مرحله

نسخه: ۲۴ اوت ۲۰۲۶. این سند برای **شما** است تا روی سیستم شخصی نگه دارید. سکرت نمی‌خواهد. IP/دامنهٔ استک فعلی فقط مثال است؛ روی سرور دوست همه را عوض کنید.

**استک فعلی (مثال، کپی نکنید):** رله ایران `${IRAN_IP}` · Exit آلمان `${EXIT_IP}` · دامنه‌ها `${MAIN_ZONE}` / `${ALT_ZONE}`.

دو ماشین لازم است. کلاینت به ایران وصل می‌شود؛ اینترنت از آلمان خارج می‌شود. پنل PasarGuard روی Exit است.

قبل از شروع فایل `NODE-DISABLED.md` را بخوانید.

---

## مرحله ۱ — دامنه، Cloudflare، گواهی

**هدف:** نام‌ها resolve شوند و یک گواهی TLS با SAN درست برای پنل، ورود Vision، و بک‌هال XHTTP وجود داشته باشد.

**کارها**

1. دو دامنه (یا یکی با چند subdomain). از ایران `.ir` معمولاً بهتر از دامنه‌ای است که DNS-hijack می‌شود.
2. هر دو را روی Cloudflare بگذارید. توکن API با حداقل دسترسی Zone DNS (نه account-wide اگر می‌شود).
3. تنظیم زون: SSL **Full (Strict)**، **HTTP/3 خاموش** (وگرنه بعضی اندروید `ERR_QUIC_PROTOCOL_ERROR`).
4. رکوردها (نمونه نام؛ IP را مال خودتان بگذارید):

   - `ir.<دامنه>` → IP **ایران**، **خاکستری** (ورود Reality/Vision). هرگز نارنجی نکنید.
   - `panel.<دامنه-ایران>` → IP **ایران**، **خاکستری** اگر پنل را روی پورت ۲۰۹۶ از ایران می‌خواهید. نارنجی پورت ۲۰۹۶ را رد نمی‌کند.
   - `panel.<دامنه-آلمان>` → IP **آلمان**، **نارنجی** برای پنل روی ۴۴۳.
   - `cdn.<دامنه>` و `xhttp.<دامنه>` → IP **آلمان**، **نارنجی** — بک‌هال، ورود کلاینت نیست.

5. گواهی Let’s Encrypt با DNS challenge (Cloudflare)، یک cert با SAN همهٔ `panel.*` / `ir.*` / `cdn.*` / `xhttp.*`. روی آلمان صادر شود؛ fullchain+privkey به ایران کپی شود (مثلاً `/root/.pg_nodes/certs/` و `/etc/nginx/certs/`).

**چک**

- `dig +short ir.دامنه` = IP ایران
- `openssl s_client -connect ir.دامنه:2053 -servername ir.دامنه` بعد از مرحله ۴ باید verify شود
- سکرت توکن CF فقط در `/root/.vpn-secrets/.env` با mode 600

---

## مرحله ۲ — Exit: فایروال، Xray بک‌هال، nginx

**هدف:** آلمان XHTTP و DIRECT را گوش بدهد؛ پنل روی ۲۰۹۶ و SNI روی ۴۴۳ جدا شود.

**نصب**

- Ubuntu 22.04، nftables، SSH فقط کلید
- Xray + `geoip.dat` / `geosite.dat`
- nginx با ماژول **stream** (`ssl_preread`)

**کارها**

1. nftables شبیه `configs/nftables-exit.conf`:  
   باز از جهان: `22`, `80`, `443`, `2096`  
   فقط از IP ایران: `9443` TCP و UDP بک‌هال اگر استفاده می‌کنید  
   `127.0.0.1:8000` پنل از بیرون دیده نشود.
2. Xray Exit (جدا از JSON پنل):
   - XHTTP روی **`127.0.0.1:10443`** (نه `:443` عمومی) path مثلاً `${XHTTP_PATH}`
   - DIRECT/Vision+TLS روی `:9443` فقط برای ایران
   - outbound `PANEL-LOCAL` = redirect به `127.0.0.1:2096` برای دامنهٔ `panel.*`
   - اختیاری WARP برای گوگل
3. nginx stream روی `:443`: SNI `panel.*` → `127.0.0.1:2096`؛ پیش‌فرض → `127.0.0.1:10443`
4. nginx http روی `:2096` TLS → `http://127.0.0.1:8000` (بعد از مرحله ۳)

**چک**

- `ss -tlnp` : nginx `:443` و `:2096`؛ xray `:10443` لوپ‌بک و `:9443`
- از ایران، TCP به `:9443` آلمان باز باشد؛ از IP غریبه بسته

---

## مرحله ۳ — پنل PasarGuard روی Exit

**هدف:** UI و sqlite و API روی آلمان؛ هستهٔ `iran-xray` منبع حقیقت بک‌هال و اینباند کلاینت باشد.

**نصب**

- Docker
- تصویر PasarGuard؛ بایند `127.0.0.1:8000` (نه `0.0.0.0`)
- دیتابیس پایدار مثلاً `/var/lib/pasarguard/`

**کارها**

1. پنل را بالا بیاورید؛ ادمین بسازید.
2. یک **Core** بسازید (`iran-xray`) شامل:
   - inbound `VLESS-REALITY` پورت ۴۴۳
   - inbound `VLESS-VISION` پورت ۲۰۵۳
   - inbound `PANEL-ADMIN` SOCKS فقط `127.0.0.1:11080` (از assignment کاربر خارج)
   - outboundهای `TO-AMS-CF` / `TO-AMS-XHTTP` / `TO-AMS-DIRECT` (+ TUIC اگر خواستید)
   - balancer `backhaul` با selector اولویت CF → XHTTP → DIRECT
   - قبل از catch-all `.ir` DIRECT: دامنهٔ `panel.*` برود `backhaul` نه DIRECT
3. **کلاینت داخل JSON هسته خالی** باشد؛ کاربر از UI اضافه می‌شود.
4. یک ردیف **Node** برای ایران بسازید (آدرس، پورت API 62050، گواهی نود) ولی **Enable نکنید.** `keep_alive=0`.
5. Hostهای ساب: Reality با آدرس `ir.*` و/یا IP ایران پورت ۴۴۳؛ Vision پورت ۲۰۵۳ با SNI `ir.*`.

**چک**

- `https://panel.دامنه-آلمان:2096/dashboard/` از شبکهٔ غیر ایران یا از روی VPN باز شود
- نود در UI وضعیت disabled
- فایل API key پنل فقط mode 600 روی دیسک؛ در چت نگذارید

---

## مرحله ۴ — رله ایران: node، Reality، Vision

**هدف:** کلاینت به ایران وصل شود. Xray زنده از docker node است نه از unit قدیمی systemd.

**نصب**

- nftables (`configs/nftables-iran.conf`): TCP `22, 443, 2053, 8443, 2096`؛ UDP `443`؛ API نود `62050/62051` **فقط از IP Exit**
- Docker تصویر `pasarguard/node`، volume مثلاً `/var/lib/pg-node`
- گواهی SAN برای Vision و بعداً nginx پنل

**کارها**

1. نود را با گواهی و API key مطابق ردیف پنل اجرا کنید؛ **منتظر `/start` محلی بمانید** (مرحله ۵).
2. Reality روی `*:443` (مال nginx نباشد).
3. Vision روی `*:2053`.
4. اسکریپت `bootstrap-iran.sh` را چشم‌بسته اجرا نکنید؛ فرضش Xray systemd است و با معماری زنده فرق دارد.

**چک**

- بعد از اولین apply: `ss` نشان دهد `xray` روی `:443` و `:2053`
- از موبایل ایران یک لینک Reality با fragment (tlshello) وصل شود
- `openssl s_client` به `:2053` با SNI `ir.دامنه` گواهی شما را نشان دهد

---

## مرحله ۵ — صفحه کنترل: سینک SCP + apply محلی

**هدف:** ساخت/حذف کاربر در پنل ظرف ~۲۰ث روی ایران اعمال شود بدون Enable نود.

**کپی از بستهٔ اسکریپت (بازنویسی نکنید)**

- Exit: `iran_sync_export.py`, `build_iran_start_proto.py`, `iran_stats_ingest.py` + unitهای `iran-sync-export` و `iran-stats`
- ایران: `iran_sync_apply.py` → `/usr/local/sbin/iran_sync_apply.py` + unit `iran-sync-apply`

**کارها**

1. SSH کلید از root آلمان به root ایران بدون پسورد (`BatchMode=yes`).
2. در اسکریپت‌ها `IRAN=root@<IP-ایران>` را عوض کنید.
3. Export هر ۱۰ث proto را در `/var/lib/pasarguard/iran-sync/` می‌سازد؛ اگر hash عوض شد SCP به `/var/lib/pg-node/sync/`
4. Apply هر ۱۰ث اگر hash جدید است (یا پورت ۴۴۳/۲۰۵۳ خواب است) `POST https://127.0.0.1:62050/start`
5. Stats هر ۳۰ث از ایران `statsquery` می‌گیرد و `used_traffic` / `online_at` را در sqlite می‌نویسد
6. Instant Instagram inject داخل export است؛ لیست کاربر را از `/etc/vpn-monitor/` می‌خواند نه از git

**چک**

- یک کاربر تست در پنل → ظرف ۲۰ث در `/var/lib/pg-node/generated/xray.json` ایران `email`/id او باشد
- لاگ: Exit `/var/log/vpn-path/` (اگر اسکریپت همان path را دارد) · ایران sync.log
- نود همچنان disabled
- `systemctl list-timers` هر سه تایمر active

---

## مرحله ۶ — بک‌هال: CF، XHTTP، DIRECT

**هدف:** ترافیک کاربر از ایران به آلمان برسد. `vpn-path` روی **آلمان** selector را در هستهٔ پنل عوض می‌کند؛ بعد export همان را به ایران می‌رساند.

**کپی:** کل خانوادهٔ `vpn-path` + `vpn_failover.py` + `path_health.py` + timer failover. IP/دامنه را عوض کنید.

**کارها**

1. اولویت پیشنهادی: `TO-AMS-CF` → `TO-AMS-XHTTP` → `TO-AMS-DIRECT` (TUIC آخر؛ UDP اغلب از دیتاسنتر ایران فیلتر است)
2. نصب: `install -m 755 scripts/vpn-path /usr/local/sbin/vpn-path`
3. روی ایران stub بگذارید که بگوید vpn-path را روی Exit بزن (یا status از generated بخواند)
4. `vpn-failover.timer` هر ۱۵ث از ایران health بگیرد؛ ۳ شکست پیاپی → مسیر بعدی
5. Fragment روی outboundهای TLS بک‌هال (dialerProxy) طبق JSON هسته

**چک از ایران**

```bash
curl -sS --max-time 20 -x socks5h://127.0.0.1:11080 -o /dev/null -w '%{http_code}\n' https://www.google.com/generate_204
```

روی Exit: `vpn-path status` و `vpn-path test`

اگر CF فیلتر شد: `vpn-path xhttp` یا `direct`.

---

## مرحله ۷ — پروکسی پنل روی ایران (لینک ساب بدون تغییر)

**هدف:** کلاینت‌های ایران همان URL ذخیره‌شده `https://panel.<دامنه>:2096/sub/<token>` را باز کنند؛ DNS به IP ایران باشد.

**کپی:** `configs/nginx-iran-subproxy.conf` + snippets، `xray-subproxy.json`، `xray-subproxy.service`، nft پورت ۲۰۹۶.

**کارها**

1. nginx ایران listen `2096` و `8443` با همان گواهی SAN
2. `proxy_pass` به `https://127.0.0.1:10444` (dokodemo)
3. dokodemo مقصدش دامنه‌ای باشد که **بعد از عوض شدن DNS پنل ایران حلقه نزند** — در استک فعلی `${PANEL_DOMAIN}:2096` (آن یکی روی آلمان ماند)
4. Host هدر همان hostname لینک کلاینت
5. `location /` کل پنل را پروکسی کنید (نه فقط `/dashboard/`) چون اسکریپت‌ها زیر `/statics/`اند
6. DNS `panel.<دامنه-ایران>` خاکستری به IP ایران

**چک از خود ایران**

```bash
curl -sS -o /dev/null -w '%{http_code}\n' --resolve panel.دامنه:2096:127.0.0.1 https://panel.دامنه:2096/dashboard/
# باید 200 و HTML شامل /statics/ باشد
```

از آلمان به IP ایران `:2096` ممکن است HTTP بعد از TLS hang شود؛ کلاینت هدف نت ایران است.

---

## مرحله ۸ — سه ابزار عملیاتی + بقیهٔ اسکریپت‌ها

نصب جزئی در `SCRIPTS-INSTALL.md`. خلاصه:

| ابزار | کجا | کار |
|---|---|---|
| **vpn-path** | Exit | تعویض دستی/اتومات بک‌هال |
| **instagram-multiplier** | Exit CLI + inject در export | ضریب حجم اینستا برای چند یوزر |
| **sni-watch** (`/watch/`) | ایران سرویس + Exit تونل SSH + nginx `/watch/` | گزارش SNI کلاینت‌های انتخابی |

همین مرحله مانیتور (`scripts/monitor/install.sh exit|iran`) را هم می‌توانید نصب کنید.

**چک**

- `vpn-path status` روی آلمان
- `instagram-multiplier list` روی آلمان
- `https://panel.…:2096/watch/` با لاگین جدا از پنل

---

## مرحله ۹ — کلاینت واقعی، بکاپ، سخت‌گیری

**کارها**

1. ساب را روی v2rayNG / v2rayN / iOS تست کنید (MCI شب اوج). Reality fragment روشن.
2. SSH آلمان را به IP ادمین محدود کنید اگر می‌شود.
3. بکاپ رمزشدهٔ پنل+کانفیگ (در این استک `backup-vpn.sh` + GPG).
4. توکن‌هایی که در چت آمده‌اند rotate.
5. Quota/مانیتور تلگرام اختیاری است (BotFather روی موبایل شما).

**چک نهایی**

- کلاینت ایران اینترنت دارد
- ساب از `panel.*:2096` روی نت ایران ۲۰۰ می‌دهد
- نود پنل هنوز disabled
- Reality روی ۴۴۳ ایران هنوز xray است نه nginx
- `ir.*` DNS دست‌نخورده روی IP ایران

---

## چیزهایی که هرگز از استک فعلی کپی نکنید

- `/root/.vpn-secrets/.env` و هر UUID / کلید Reality / توکن CF / API پنل
- `/etc/vpn-monitor/instagram-multiplier-users.txt` (لیست زندهٔ کاربر)
- sqlite پنل و بکاپ رمزنشده
- IPهای نت‌کاپ/شتابان به‌عنوان پیش‌فرض دائمی داخل کانفیگ دوست (جایگزین کنید)
