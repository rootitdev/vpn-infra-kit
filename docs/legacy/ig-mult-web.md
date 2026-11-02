# ضریب اینستا (instagram-multiplier) — صفحه وب

ربات اینستاگرام نیست. برای چند کاربر پنل، ترافیک دامنه‌های تنظیم‌شده روی هستهٔ ایران به outbound جدا می‌رود (کلون همان بک‌هال) و روی Exit با ضریب به `used_traffic` اضافه می‌شود.

## ریسک فیلتر

این اسکریپت **امضای تازه برای DPI نمی‌سازد** و مسیر اینترنت را عوض نمی‌کند. کلاینت همان وی‌پی‌ان قبلی را دارد؛ اینستاگرام همان IP خروج را می‌بیند. ضریب فقط حسابداری پنل است. فیلتر اینستا در ایران را دور نمی‌زند.

ریسک واقعی عملیاتی: لیست دامنهٔ ناقص → کم‌شماری حجم؛ هر کاربر یک rule اضافه روی Xray ایران.

## صفحه

- آدرس: `https://${PANEL_DOMAIN}:2096/ig/`
- لاگین جدا از PasarGuard (و جدا از دیده‌بان)
- سرویس Exit: `ig-mult-web` → `127.0.0.1:8788`
- nginx: `location /ig/`
- رمز: `/etc/ig-mult-web/admin.pass` یا `/root/.vpn-secrets/ig-mult-web.env`

منو: کاربران، آمار، تنظیمات، مستندات.

افزودن/حذف مثل CLI همان لحظه `iran-sync-export` را می‌زند. تغییر ضریب export نمی‌خواهد؛ تغییر دامنه می‌خواهد.

## نصب Exit

```bash
sudo AUTH_USER=ig AUTH_PASS='رمز-دلخواه' /root/vpn-infra/scripts/ig-mult-web/install.sh
```

اگر `AUTH_PASS` ندهید ساخته می‌شود. پیش‌نیاز: CLI `instagram-multiplier` و فایل‌های `/etc/vpn-monitor/instagram-multiplier.*`.

## CLI

```bash
instagram-multiplier add <username>
instagram-multiplier remove <username>
instagram-multiplier list
instagram-multiplier stats --days 7
```
