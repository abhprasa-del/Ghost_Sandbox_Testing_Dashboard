#!/usr/bin/env bash
# Weekly pg_dump of the ghost_dashboard database (custom format, compressed).
#
# The password is NOT stored here: put it in ~/.pgpass (chmod 600):
#   198.18.69.10:5432:ghost_dashboard:ghost_dash:<password>
#
# Settings can be overridden through the environment.
set -euo pipefail

DB_HOST="${DB_HOST:-198.18.69.10}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-ghost_dashboard}"
DB_USER="${DB_USER:-ghost_dash}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/ghost_dashboard}"
KEEP_DAYS="${KEEP_DAYS:-56}"   # about 8 weekly backups

mkdir -p "$BACKUP_DIR"
out="$BACKUP_DIR/${DB_NAME}_$(date +%F).dump"

pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -Fc -f "$out.tmp"
mv "$out.tmp" "$out"   # only a complete dump gets the final name

find "$BACKUP_DIR" -name "${DB_NAME}_*.dump" -mtime +"$KEEP_DAYS" -delete
echo "backup written: $out"
