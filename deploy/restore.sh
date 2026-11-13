#!/usr/bin/env bash
# Restore a backup made by deploy/backup.sh. This REPLACES the current database and media.
#
#   Host install:   DATABASE_URL=postgres://... deploy/restore.sh backups/heza-20261113-023000
#   Docker Compose: BACKUP_MODE=docker deploy/restore.sh backups/heza-20261113-023000
set -euo pipefail

SRC="${1:?Usage: deploy/restore.sh <backup directory>}"
MODE="${BACKUP_MODE:-host}"
COMPOSE="${COMPOSE:-docker compose}"

(cd "$SRC" && sha256sum -c SHA256SUMS)

if [ "${CONFIRM:-}" != "yes" ]; then
  read -r -p "This overwrites the live database and uploads. Type 'yes' to continue: " answer
  [ "$answer" = "yes" ] || { echo "Aborted."; exit 1; }
fi

if [ "$MODE" = "docker" ]; then
  $COMPOSE stop web scheduler
  $COMPOSE exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' < "$SRC/db.dump"
  $COMPOSE run --rm --no-deps -T --entrypoint sh web -c 'rm -rf /app/media/* /app/private_media/* && tar -C /app -xzf - ' < "$SRC/media.tar.gz"
  $COMPOSE run --rm --no-deps -T --entrypoint sh web -c 'tar -C /app -xzf -' < "$SRC/private_media.tar.gz"
  $COMPOSE start web scheduler
else
  : "${DATABASE_URL:?Set DATABASE_URL}"
  MEDIA_ROOT="${MEDIA_ROOT:-./media}"
  PRIVATE_MEDIA_ROOT="${PRIVATE_MEDIA_ROOT:-./private_media}"
  pg_restore -d "$DATABASE_URL" --clean --if-exists --no-owner "$SRC/db.dump"
  rm -rf "${MEDIA_ROOT:?}"/* "${PRIVATE_MEDIA_ROOT:?}"/*
  tar -C "$(dirname "$MEDIA_ROOT")" -xzf "$SRC/media.tar.gz"
  tar -C "$(dirname "$PRIVATE_MEDIA_ROOT")" -xzf "$SRC/private_media.tar.gz"
fi

echo "Restored from $SRC. Run 'python manage.py migrate' if the backup predates the current code."
