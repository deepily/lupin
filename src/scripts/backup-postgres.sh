#!/bin/bash
# backup-postgres.sh v1.0
#
# PostgreSQL backup using pg_dump via Docker container.
# Creates a consistent SQL dump that can be restored without downtime concerns.
#
# Usage:
#   ./backup-postgres.sh           # Create backup
#   ./backup-postgres.sh --quiet   # Suppress output (for integration)
#
# Output: src/conf/long-term-memory/postgresql-backup.sql
#
# Restore command:
#   docker exec -i lupin-postgres psql -U lupin_dev lupin_db_dev < postgresql-backup.sql

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BACKUP_FILE="$SCRIPT_DIR/../conf/long-term-memory/postgresql-backup.sql"
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

# Run pg_dump inside the container
log "Creating PostgreSQL backup..."
docker exec "$CONTAINER_NAME" pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP_FILE" 2>/dev/null

if [[ $? -eq 0 && -s "$BACKUP_FILE" ]]; then
    BACKUP_SIZE=$( du -h "$BACKUP_FILE" | cut -f1 )
    log "✓ PostgreSQL backup created: $BACKUP_FILE"
    log "  Size: $BACKUP_SIZE"
    exit 0
else
    log "✗ PostgreSQL backup failed"
    # Remove empty/corrupt file if it exists
    [[ -f "$BACKUP_FILE" ]] && rm -f "$BACKUP_FILE"
    exit 1
fi
