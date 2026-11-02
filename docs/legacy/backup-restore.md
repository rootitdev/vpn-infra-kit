# بکاپ استک + تلگرام

## BACKUP_PASSPHRASE

**در پیام تلگرام ارسال نمی‌شود.** کپشن فقط می‌گوید آفلاین نگه دارید.

محل‌ها:

1. روی Exit زنده: `/root/.vpn-secrets/.env` → کلید `BACKUP_PASSPHRASE`
2. داخل خود آرشیو GPG (بعد از باز شدن با همان passphrase): `exit/root/.vpn-secrets/.env`
3. باید یک کپی در password manager داشته باشی

بدون این عبارت، فایل تلگرام قابل‌باز شدن نیست.

## چه چیزی بکاپ می‌شود

هر شب (~۰۳:۱۷) اسکریپت `backup-stack.sh`:

**Exit:** `vpn-infra`، `.vpn-secrets`، کلیدهای `.ssh`، کانفیگ‌های `.pg_nodes` (بدون `bin`)، DB پنل، nginx، nft، letsencrypt (اگر باشد)، systemdهای vpn/iran/settle/ig/sni-watch، `settle.db`، ضریب IG.

**ایران (SSH):** sni-watch، nginx، nft، `pg-node`، certs، واحدهای sync/wrap.

همه داخل یک فایل **GPG** → تلگرام. محلی: `/root/.pg_nodes/backups/vpn-stack-*.tar.gz.gpg` (۱۴ روز).

## دستی

```bash
/root/vpn-infra/scripts/backup-stack.sh
```

## ریستور کامل (سرور خام)

پرامپت آماده برای چت جدید Cursor:

→ **`docs/RESTORE-CURSOR-PROMPT.md`**

بلوک OPERATOR VALUES را پر کن، فایل `.gpg` + passphrase آفلاین را آماده کن، کل فایل را به Cursor بده.
