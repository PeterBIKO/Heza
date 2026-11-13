#!/usr/bin/env bash
# Back up the Heza database and uploaded files.
#
#   Host install:   DATABASE_URL=postgres://... deploy/backup.sh
#   Docker Compose: BACKUP_MODE=docker deploy/backup.sh
#
# Writes BACKUP_DIR/heza-<timestamp>/{db.dump,media.tar.gz,private_media.tar.gz,SHA256SUMS}
# and deletes backups older than BACKUP_KEEP_DAYS (default 14).
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
MODE="${BACKUP_MODE:-host}"
COMPOSE="${COMPOSE:-docker compose}"
STAMP="$(date +%Y%m%d-%H%M%S)"
TARGET="$BACKUP_DIR/heza-$STAMP"

umask 077
mkdir -p "$TARGET"

if [ "$MODE" = "docker" ]; then
  $COMPOSE exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$TARGET/db.dump"
  $COMPOSE exec -T web tar -C /app -czf - media > "$TARGET/media.tar.gz"
  $COMPOSE exec -T web tar -C /app -czf - private_media > "$TARGET/private_media.tar.gz"
else
  : "${DATABASE_URL:?Set DATABASE_URL}"
  MEDIA_ROOT="${MEDIA_ROOT:-./media}"
  PRIVATE_MEDIA_ROOT="${PRIVATE_MEDIA_ROOT:-./private_media}"
  pg_dump "$DATABASE_URL" -Fc -f "$TARGET/db.dump"
  tar -C "$(dirname "$MEDIA_ROOT")" -czf "$TARGET/media.tar.gz" "$(basename "$MEDIA_ROOT")"
  tar -C "$(dirname "$PRIVATE_MEDIA_ROOT")" -czf "$TARGET/private_media.tar.gz" "$(basename "$PRIVATE_MEDIA_ROOT")"
fi

if [ ! -s "$TARGET/db.dump" ]; then
  echo "Database dump is empty; backup failed" >&2
  exit 1
fi

(cd "$TARGET" && sha256sum ./* > SHA256SUMS)
find "$BACKUP_DIR" -maxdepth 1 -type d -name 'heza-*' -mtime "+$KEEP_DAYS" -exec rm -rf {} +

echo "Backup written to $TARGET"
du -sh "$TARGET"
