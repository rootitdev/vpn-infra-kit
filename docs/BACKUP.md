# RoOtIt-backup (per-host, GPG → Telegram)

Files: `scripts/rootit-backup.sh` → `/usr/local/sbin/RoOtIt-backup.sh`,
`systemd/common/RoOtIt-backup.{service,timer}` (daily 04:00 Asia/Tehran; stagger hosts by 10 min).

Config in `/root/.vpn-secrets/.env` (mode 600): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
`BACKUP_GPG_PASS` (random, symmetric AES256), `BACKUP_LABEL`, `BACKUP_PATHS`, optional
`BACKUP_EXCLUDES`, `BACKUP_PG_CONTAINER` (read-only `pg_dump -Fc` of the Pasarguard DB, no restarts),
`BACKUP_TG_PROXY` (Iran: api.telegram.org is filtered → `socks5h://127.0.0.1:<SOCKS_TEST_PORT>` via the tunnel).
Needs `gpg-agent` installed (Ubuntu 24.04 minimal lacks it). Archives >45 MB are split (`split -b 45M`).
Local copies: `/root/RoOtIt-backups/`. Retention: `BACKUP_RETENTION_DAYS` (default 14) — after each run,
only files matching `RoOtIt-*.tar.gz.gpg*` in that folder older than N days are deleted (0 = keep all).

Installer: `./install.sh --phase backup` (asked in setup group M of PROMPT.md: `INSTALL_BACKUP`, `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`, `BACKUP_TIME`, `BACKUP_RETENTION_DAYS`). It installs on Exit (local), Iran (`on_iran`, Telegram via the
tunnel SOCKS) and, in split mode, Master (`on_master`, read-only pg_dump), and generates `BACKUP_GPG_PASS` on each host.

Run now: `systemctl start RoOtIt-backup.service; journalctl -u RoOtIt-backup -n 20`

Restore:
```
cat RoOtIt-<label>-<stamp>.tar.gz.gpg.part* > a.gpg   # only if split
gpg --pinentry-mode loopback -d a.gpg > a.tar.gz        # asks for BACKUP_GPG_PASS
mkdir r && tar -xzf a.tar.gz -C r                       # inspect, then copy files back to /
# master DB: docker exec -i pasarguard-timescaledb-1 pg_restore -U <DB_USER> -d <DB_NAME> --clean < r/<label>/pasarguard-db.dump
```
Keep a copy of each host's BACKUP_GPG_PASS OFFLINE — the passphrase is inside the archive itself.
