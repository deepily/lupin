#!/usr/bin/env python3
"""
Create notifications table for Phase 2 SSE notification system.

This is initial table creation (NOT migration - table does not currently exist).
Current notifications are in-memory only (NotificationItem objects).

Design reference: src/rnd/sse-notifications/05-phase2-design-decisions.md
Schema reference: Lines 136-179 (Area 1 Q1.3) + Line 267 (Q1.4 deleted_at field)

Database: lupin-notifications.db (new dedicated SQLite database)
Location: src/conf/long-term-memory/lupin-notifications.db
"""

import sqlite3
import sys
import os
from pathlib import Path

# Bootstrap: Use LUPIN_ROOT environment variable for standalone execution
lupin_root = os.environ.get( 'LUPIN_ROOT' )
if lupin_root is None:
    raise RuntimeError(
        "LUPIN_ROOT environment variable not set.\n"
        "Set it before running:\n"
        "  export LUPIN_ROOT=/path/to/project\n"
        "  python src/scripts/create_notifications_table.py"
    )

src_path = os.path.join( lupin_root, 'src' )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

# Now cosa is importable
import cosa.utils.util as cu


# SQL schema from design doc (Area 1 Q1.3 + Q1.4)
CREATE_NOTIFICATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS notifications (
    -- Identity
    id                      TEXT PRIMARY KEY,  -- UUID from uuid.uuid4()

    -- Routing
    sender_id               TEXT NOT NULL,     -- Specific user email-style ID (e.g., claude.code.cosa@deepily.ai)
    recipient_id            TEXT NOT NULL,     -- User UUID from auth database

    -- Source Context (splits old 'source' field)
    source_context          TEXT DEFAULT 'internal',  -- internal, external, claude_code, system
    source_sender           TEXT DEFAULT 'claude.code@deepily.ai',  -- Full email-style sender ID

    -- Content (title/message split for voice-first UX)
    title                   TEXT NOT NULL,     -- Terse, technical, specific (e.g., "JWT Token Refresh Failed")
    message                 TEXT NOT NULL,     -- Prose, no acronyms/abbrevs, TTS-friendly
    type                    TEXT NOT NULL,     -- task, progress, alert, custom
    priority                TEXT NOT NULL,     -- urgent, high, medium, low

    -- Timestamps
    created_at              TEXT NOT NULL,     -- ISO timestamp with timezone
    delivered_at            TEXT,              -- When sent via SSE/WebSocket (NULL until delivered)
    expires_at              TEXT,              -- NULL for fire-and-forget, set for response-required
    deleted_at              TEXT,              -- When user deleted (NULL if not deleted) - from Q1.4

    -- Response-Required Fields
    response_requested      INTEGER DEFAULT 0, -- Boolean: 0 = no, 1 = yes
    response_type           TEXT,              -- NULL, 'yes_no', 'open_ended'
    response_value          TEXT,              -- JSON object (e.g., {"answer": "yes", "raw_utterance": "sure!", "confidence": "high"})
    responded_at            TEXT,              -- When user responded (NULL until responded)
    timeout_seconds         INTEGER,           -- Per-notification timeout (nullable, falls back to config max)
    response_default        TEXT,              -- 'yes', 'no', NULL (for pre-selecting button, accepting default with Enter)

    -- State Management
    state                   TEXT NOT NULL DEFAULT 'created',  -- created, delivered, responded, expired, deleted

    -- Legacy Compatibility (for fire-and-forget notifications)
    played                  INTEGER DEFAULT 0, -- Boolean: 0 = unplayed, 1 = played
    play_count              INTEGER DEFAULT 0, -- How many times audio played
    last_played             TEXT               -- Last playback timestamp
);
"""

# Indexes for common queries (from design doc lines 177-179)
CREATE_INDEXES = [
    """
    CREATE INDEX IF NOT EXISTS idx_recipient_state
    ON notifications(recipient_id, state);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_recipient_created
    ON notifications(recipient_id, created_at);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_expires_at
    ON notifications(expires_at)
    WHERE expires_at IS NOT NULL;
    """
]


def create_notifications_table():
    """
    Create notifications table with full Phase 2 schema.

    Requires:
        - LUPIN_ROOT environment variable set
        - Database directory exists

    Ensures:
        - lupin-notifications.db created
        - notifications table created with 24 fields
        - 3 indexes created
        - Schema validated
    """
    # Database path using canonical pattern
    db_path = cu.get_project_root() + "/src/conf/long-term-memory/lupin-notifications.db"

    print( f"Creating notifications table in: {db_path}" )

    # Ensure directory exists
    db_dir = os.path.dirname( db_path )
    if not os.path.exists( db_dir ):
        raise RuntimeError( f"Database directory does not exist: {db_dir}" )

    # Connect to database (will create file if doesn't exist)
    conn = None
    try:
        conn = sqlite3.connect( db_path )
        cursor = conn.cursor()

        # Create table
        print( "  Creating notifications table..." )
        cursor.execute( CREATE_NOTIFICATIONS_TABLE )

        # Create indexes
        print( "  Creating indexes..." )
        for idx, index_sql in enumerate( CREATE_INDEXES, 1 ):
            cursor.execute( index_sql )
            print( f"    Index {idx}/3 created" )

        # Commit changes
        conn.commit()

        # Validate schema
        print( "  Validating schema..." )
        validation_result = validate_schema( conn )

        if validation_result["success"]:
            print( f"  ✓ Schema validated: {validation_result['field_count']} fields, {validation_result['index_count']} indexes" )
            return True
        else:
            print( f"  ✗ Schema validation failed: {validation_result['error']}", file=sys.stderr )
            return False

    except sqlite3.Error as e:
        print( f"  ✗ SQLite error: {e}", file=sys.stderr )
        return False
    except Exception as e:
        print( f"  ✗ Unexpected error: {e}", file=sys.stderr )
        return False
    finally:
        if conn:
            conn.close()


def validate_schema( conn ):
    """
    Verify all fields and indexes were created correctly.

    Requires:
        - conn: Active SQLite connection

    Ensures:
        - Returns validation report dict
    """
    try:
        cursor = conn.cursor()

        # Check table exists
        cursor.execute( """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='notifications'
        """ )
        table_result = cursor.fetchone()

        if not table_result:
            return {
                "success": False,
                "error": "Table 'notifications' not found"
            }

        # Count fields
        cursor.execute( "PRAGMA table_info(notifications)" )
        fields = cursor.fetchall()
        field_count = len( fields )

        # Expected: 23 fields total (including deleted_at from Q1.4)
        # Breakdown: id(1) + routing(2) + source(2) + content(4) + timestamps(4) + response(6) + state(1) + legacy(3) = 23
        expected_fields = 23
        if field_count != expected_fields:
            return {
                "success": False,
                "error": f"Expected {expected_fields} fields, found {field_count}",
                "field_count": field_count
            }

        # Count indexes (excluding SQLite's automatic PRIMARY KEY index)
        cursor.execute( """
            SELECT name FROM sqlite_master
            WHERE type='index' AND tbl_name='notifications'
            AND name NOT LIKE 'sqlite_autoindex%'
        """ )
        indexes = cursor.fetchall()
        index_count = len( indexes )

        # Expected: 3 indexes (idx_recipient_state, idx_recipient_created, idx_expires_at)
        # Note: SQLite auto-creates sqlite_autoindex_notifications_1 for PRIMARY KEY, which we exclude
        expected_indexes = 3
        if index_count != expected_indexes:
            return {
                "success": False,
                "error": f"Expected {expected_indexes} indexes, found {index_count}",
                "index_count": index_count
            }

        return {
            "success": True,
            "field_count": field_count,
            "index_count": index_count
        }

    except sqlite3.Error as e:
        return {
            "success": False,
            "error": f"Validation query failed: {e}"
        }


def main():
    """
    Main entry point.

    Returns:
        0 on success, 1 on error
    """
    print( "==================================================" )
    print( "  Notifications Table Creation Script" )
    print( "  Phase 2.0 Foundation - Week 1" )
    print( "==================================================" )
    print()

    try:
        success = create_notifications_table()

        if success:
            print()
            print( "==================================================" )
            print( "  ✓ SUCCESS: Notifications table created" )
            print( "==================================================" )
            return 0
        else:
            print()
            print( "==================================================" )
            print( "  ✗ FAILED: See errors above" )
            print( "==================================================" )
            return 1

    except Exception as e:
        print( f"\n✗ FATAL ERROR: {e}", file=sys.stderr )
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit( main() )
