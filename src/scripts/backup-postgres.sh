#!/bin/bash
# backup-postgres.sh v2.0
#
# PostgreSQL backup using pg_dump via Docker container.
# Creates a consistent, compressed dump that can be restored without downtime concerns.
#
# Usage:
#   ./backup-postgres.sh           # Create backup
#   ./backup-postgres.sh --quiet   # Suppress output (for integration)
#
# Output: src/conf/long-term-memory/postgresql-backup.dump
#
#   pg_dump custom format (-Fc), compressed with zstd level 3. Measured 6 Nov 2026 on
#   the 8.9 GB dev database: 2.72 GB in 85 s, against 17.4 GB for the plain-SQL dump
#   v1.0 wrote (row b08f6dd9). The saving is the compression: the custom format still
#   stores each table's rows as COPY text, and the 949k notification rows' vectors are
#   highly repetitive.
#
#   The dump is written to a temporary file and moved into place only after
#   pg_restore can read its table of contents, so a failed run leaves the previous
#   good backup where it was. (v1.0 wrote over it directly, then deleted the file
#   on failure, leaving no backup at all.)
#
# Restore command (into an empty database):
#   docker exec -i lupin-postgres pg_restore -U lupin_dev -d lupin_db_dev --no-owner < postgresql-backup.dump
#
# List what a dump holds:
#   docker exec -i lupin-postgres pg_restore --list < postgresql-backup.dump

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BACKUP_FILE="$SCRIPT_DIR/../conf/long-term-memory/postgresql-backup.dump"
TEMP_FILE="$BACKUP_FILE.tmp"
CONTAINER_NAME="lupin-postgres"
DB_NAME="lupin_db_dev"
DB_USER="lupin_dev"

# Parse arguments
QUIET=false
if [[ "$1" == "--quiet" || "$1" == "-q" ]]; then
    QUIET=true
fi

# Helper function for output
log() {
    if [[ "$QUIET" == false ]]; then
        echo "$@"
    fi
}

# Check if container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    log "PostgreSQL container not running - skipping database backup"
    exit 0
fi

# Run pg_dump inside the container, into the temporary file
log "Creating PostgreSQL backup..."
docker exec "$CONTAINER_NAME" pg_dump -U "$DB_USER" -Fc -Z zstd:3 "$DB_NAME" > "$TEMP_FILE" 2>/dev/null
DUMP_EXIT=$?

# Check the dump is readable before it replaces the previous one
if [[ $DUMP_EXIT -eq 0 && -s "$TEMP_FILE" ]] && docker exec -i "$CONTAINER_NAME" pg_restore --list < "$TEMP_FILE" > /dev/null 2>&1; then
    mv -f "$TEMP_FILE" "$BACKUP_FILE"
    BACKUP_SIZE=$( du -h "$BACKUP_FILE" | cut -f1 )
    log "✓ PostgreSQL backup created: $BACKUP_FILE"
    log "  Size: $BACKUP_SIZE"
    exit 0
else
    log "✗ PostgreSQL backup failed (pg_dump exit $DUMP_EXIT); the previous backup was left in place"
    rm -f "$TEMP_FILE"
    exit 1
fi
