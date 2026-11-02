# دیده‌بان کلاینت‌های انتخابی (sni-watch)

ابزار جدا برای **سیستم‌های خودتان**. محتوای HTTPS خوانده نمی‌شود؛ فقط hostname مقصد (SNI) از `access.log` Xray با فهرست دامنه‌های بزرگسال مقایسه می‌شود.

باید روی همان ماشینی نصب شود که کلاینت به آن وصل می‌شود و در لاگ فیلد `email:` دارد. در استک دوهاب این **رله ایران** است، نه Exit (آنجا همه چیز `backhaul-xhttp` است).

## نصب مستقل روی سرور دیگر

پوشه `scripts/sni-watch/` را کپی کنید، بعد:

```bash
cd sni-watch
sudo AUTH_USER=watch AUTH_PASS='رمز-دلخواه' ./install.sh
```

اگر `AUTH_PASS` ندهید، یک رمز ساخته می‌شود و در `/etc/sni-watch/admin.pass` (mode 600) نوشته می‌شود.

پیش‌فرض به `127.0.0.1:8787` گوش می‌دهد. برای دسترسی مستقیم:

```bash
sudo LISTEN=0.0.0.0:8787 AUTH_USER=watch AUTH_PASS='...' ./install.sh
```

و پورت را در فایروال همان سرور باز کنید. لاگ پیش‌فرض: `/var/log/xray/access.log`.

## این استک (ایران + Exit)

- سرویس روی ایران: `sni-watch.service` → `127.0.0.1:8787`
- تونل SSH از Exit: `sni-watch-tunnel.service`
صفحه: `https://${PANEL_DOMAIN}:2096/watch/` — منوی سمت راست: **گزارش‌ها** و **مستندات**.
- لاگ SNI: `/var/log/xray/sni-access.log` (لاگ `access.log` نود مقصد IP کلاینت است و برای این کار کافی نیست)
- نگاشت نام/UUID→id: `sni-watch-resolve.timer` روی Exit، فقط برای نام‌هایی که در دیده‌بان هستند. Xray در `email:` همان **id عددی پنل** را می‌نویسد نه UUID وی‌لس؛ UUID فقط برای ورود کلاینت است و به همان id وصل می‌شود.

رمز را از `/etc/sni-watch/admin.pass` روی ایران یا `/root/.vpn-secrets/sni-watch.env` روی Exit بخوانید.

## انتخاب کلاینت

در صفحه، **نام کاربری پنل** (مثل `RoOtIt`)، **id** یا **UUID وی‌لس** را بزنید. هسته Xray UUID را در لاگ نمی‌نویسد؛ `email:` همان id است و دیده‌بان نام و UUID را به آن id وصل می‌کند.

## CLI (ترمینال)

روی **ایران** (یا از Exit که خودکار SSH می‌زند):

```bash
sni-watch list                      # watchlist
sni-watch status                    # سرویس، DB، دامنه‌ها
sni-watch stats                     # hit از DB (retention پیش‌فرض ۲ روز)
sni-watch stats --scan-log --hours 24   # اسکن مستقیم sni-access.log
sni-watch domains pornhub.com       # آیا دامنه در لیست است؟
```

دامنه‌های اضافه: `/etc/sni-watch/extra-domains.txt` بعد `systemctl restart sni-watch`.

## محدودیت

- اگر SNI نباشد (فقط IP در لاگ) تشخیص داده نمی‌شود.
- DNS خام (`1.1.1.1:53`) دامنهٔ سایت را نشان نمی‌دهد؛ اتصال TLS بعدی اگر sniff شود کافی است.
- ECH در این استک پیاده نشده، پس SNI معمولاً هست.

نگهداری رویدادها **۲ روز** است و از صفحه هم می‌توان گزارش‌ها را یکجا پاک کرد. جمع‌آوری را می‌شود از همان صفحه متوقف کرد (صفحه وب می‌ماند).
