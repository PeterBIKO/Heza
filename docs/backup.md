# Backup and restore

Three things need backing up:

* the **PostgreSQL database**: users, bookings, payments, ledger and audit log;
* **media**: property, room and venue photos;
* **private media**: vendor KYC documents.

Code and configuration live in git and your env file. Keep a copy of `.env` / `.env.production` in a password
manager, because it holds the secrets.

## Taking backups

`deploy/backup.sh` writes a timestamped folder containing:

* `db.dump` (`pg_dump` custom format);
* `media.tar.gz` and `private_media.tar.gz`;
* `SHA256SUMS`.

It deletes backups older than `BACKUP_KEEP_DAYS` (14 by default). Files are created with mode `600`.

**Native install.** The `heza-backup.timer` runs it nightly at 02:30 into `/srv/heza/backups`. To run it by
hand:

```bash
cd /srv/heza/app
sudo -u heza env $(grep -E '^(DATABASE_URL|MEDIA_ROOT|PRIVATE_MEDIA_ROOT)=' .env | xargs) \
  BACKUP_DIR=/srv/heza/backups deploy/backup.sh
```

**Docker Compose.** Add a root cron entry:

```cron
30 2 * * * cd /srv/heza/app && BACKUP_MODE=docker BACKUP_DIR=/srv/heza/backups COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production" deploy/backup.sh >> /var/log/heza-backup.log 2>&1
```

### Off-site copies

A backup on the same disk does not survive losing the server. Sync the backup folder to another location
every night, for example with rclone to any S3-compatible bucket, or with rsync to another machine:

```bash
rclone sync /srv/heza/backups remote:heza-backups --max-age 15d
```

Encrypt off-site copies, for example with an rclone `crypt` remote or `age`. They contain personal data and
identity documents.

## Restoring

`deploy/restore.sh <backup folder>` does the following:

1. checks the SHA-256 sums;
2. asks you to type `yes`;
3. replaces the database (`pg_restore --clean`) and the media folders.

In Docker mode it stops `web` and `scheduler` first.

```bash
# Native install
sudo systemctl stop heza
sudo -u heza env $(grep -E '^(DATABASE_URL|MEDIA_ROOT|PRIVATE_MEDIA_ROOT)=' .env | xargs) \
  deploy/restore.sh /srv/heza/backups/heza-20261113-023000
sudo -u heza .venv/bin/python manage.py migrate
sudo systemctl start heza

# Docker Compose
BACKUP_MODE=docker COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production" \
  deploy/restore.sh /srv/heza/backups/heza-20261113-023000
```

To rehearse without touching production, restore into a scratch database:

```bash
createdb heza_restore_test
CONFIRM=yes DATABASE_URL=postgres://heza:...@localhost/heza_restore_test \
  MEDIA_ROOT=/tmp/rt/media PRIVATE_MEDIA_ROOT=/tmp/rt/private_media deploy/restore.sh <folder>
psql heza_restore_test -c "select count(*) from bookings_booking;"
dropdb heza_restore_test
```

## After a restore

* Payments made after the backup was taken exist at the gateway but not in Heza. Find them in the Flutterwave
  dashboard by `tx_ref` (`HZP-...`). Flutterwave retries webhooks, and the maintenance job re-verifies pending
  payments. Reconcile anything older by hand from the admin panel.
* Spot-check vendor wallets. Each vendor's page in the admin panel shows the balance, which is the sum of their
  ledger entries.
