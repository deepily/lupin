#!/bin/bash
#
# sync-to-backup.sh
#
# Syncs the Lupin project from DATA01 to DATA02 partition using rsync
# with configurable exclusions. Runs in DRY RUN mode by default.
#
# Usage:
#   ./sync-to-backup.sh           # Dry run (preview only)
#   ./sync-to-backup.sh --write   # Execute actual sync
#   ./sync-to-backup.sh -w        # Execute actual sync (short form)

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Paths
SOURCE_DIR="/mnt/DATA01/include/www.deepily.ai/projects/genie-in-the-box/"
DEST_DIR="/mnt/DATA02/include/www.deepily.ai/projects/genie-in-the-box/"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
EXCLUDE_FILE="$SCRIPT_DIR/conf/rsync-exclude.txt"

# Default to dry run
DRY_RUN="--dry-run"
MODE_DESC="DRY RUN"
MODE_COLOR="$YELLOW"

# Parse command line arguments
if [[ "$1" == "--write" || "$1" == "-w" ]]; then
    DRY_RUN=""
    MODE_DESC="WRITE MODE"
    MODE_COLOR="$GREEN"
fi

# Print header
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Lupin Backup Sync${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "Mode: ${MODE_COLOR}${MODE_DESC}${NC}"
echo -e "Source: ${SOURCE_DIR}"
echo -e "Destination: ${DEST_DIR}"
echo -e "Exclusions: ${EXCLUDE_FILE}"
echo -e "${BLUE}========================================${NC}\n"

# Validate exclusion file exists
if [[ ! -f "$EXCLUDE_FILE" ]]; then
    echo -e "${RED}ERROR: Exclusion file not found: ${EXCLUDE_FILE}${NC}"
    exit 1
fi

# Validate destination directory parent exists
DEST_PARENT="$( dirname "$DEST_DIR" )"
if [[ ! -d "$DEST_PARENT" ]]; then
    echo -e "${RED}ERROR: Destination parent directory does not exist: ${DEST_PARENT}${NC}"
    exit 1
fi

# Show what will be excluded
echo -e "${BLUE}Exclusion patterns:${NC}"
grep -v '^#' "$EXCLUDE_FILE" | grep -v '^$' | sed 's/^/  - /'
echo ""

# Run rsync
echo -e "${MODE_COLOR}Running rsync...${NC}\n"

rsync -avh $DRY_RUN \
    --delete \
    --stats \
    --exclude-from="$EXCLUDE_FILE" \
    "$SOURCE_DIR" \
    "$DEST_DIR"

RSYNC_EXIT=$?

# Check rsync exit status
echo ""
if [[ $RSYNC_EXIT -eq 0 ]]; then
    if [[ -n "$DRY_RUN" ]]; then
        echo -e "${YELLOW}========================================${NC}"
        echo -e "${YELLOW}  DRY RUN COMPLETE${NC}"
        echo -e "${YELLOW}========================================${NC}"
        echo -e "No files were modified. To execute sync, run:"
        echo -e "  ${GREEN}./sync-to-backup.sh --write${NC}"
    else
        echo -e "${GREEN}========================================${NC}"
        echo -e "${GREEN}  SYNC COMPLETE${NC}"
        echo -e "${GREEN}========================================${NC}"
        echo -e "Backup successfully synced to DATA02"
    fi
else
    echo -e "${RED}========================================${NC}"
    echo -e "${RED}  SYNC FAILED${NC}"
    echo -e "${RED}========================================${NC}"
    echo -e "Rsync exited with code: $RSYNC_EXIT"
    exit $RSYNC_EXIT
fi
