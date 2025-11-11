#!/usr/bin/env python3
"""
Create api_keys table for Phase 2.5 notification endpoint authentication.

This is initial table creation (NOT migration - table does not currently exist).
API keys will be used for service-to-service authentication (e.g., Claude Code CLI → Lupin server).

Design reference: src/rnd/2025.11.10-phase-2.5-notification-authentication.md
Schema reference: Lines 439-464 (Database Schema Design)

Database: lupin-auth.db (existing authentication database)
Location: src/conf/long-term-memory/lupin-auth.db (from configuration)
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
        "  python src/scripts/create_api_keys_table.py"
    )

src_path = os.path.join( lupin_root, 'src' )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

# Now cosa is importable
import cosa.utils.util as cu
from cosa.rest.auth_database import get_auth_db_connection, get_auth_db_path


# SQL schema from design doc (lines 439-448)
# FIXED: user_id changed from INTEGER to TEXT to match users.id (UUID)
CREATE_API_KEYS_TABLE = """
CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    key_hash TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMP,
    is_active BOOLEAN DEFAULT 1,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
"""

# Indexes for performance (from design doc lines 453-463)
CREATE_INDEXES = [
    """
    CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash
    ON api_keys(key_hash);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_api_keys_user_id
    ON api_keys(user_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_api_keys_is_active
    ON api_keys(is_active);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_api_keys_user_active
    ON api_keys(user_id, is_active);
    """
]


def create_api_keys_table():
    """
    Create api_keys table with full Phase 2.5 schema.

    Requires:
        - LUPIN_ROOT environment variable set
        - Authentication database exists (lupin-auth.db)
        - users table exists (for foreign key constraint)

    Ensures:
        - api_keys table created with 7 fields
        - 4 indexes created for performance
        - Foreign key to users table established
        - Schema validated

    Raises:
        - RuntimeError if database directory doesn't exist
        - sqlite3.Error if table creation fails

    Returns:
        bool: True on success, False on error
    """
    # Get database path using canonical auth database function
    db_path = get_auth_db_path()

    print( f"Creating api_keys table in: {db_path}" )

    # Ensure database file exists (should already exist if auth is initialized)
    if not db_path.exists():
        print( f"⚠️  Warning: Auth database does not exist. Will be created: {db_path}" )

    # Ensure directory exists
    db_dir = db_path.parent
    if not db_dir.exists():
        raise RuntimeError( f"Database directory does not exist: {db_dir}" )

    # Connect to database using canonical auth connection
    conn = None
    try:
        conn = get_auth_db_connection()
        cursor = conn.cursor()

        # Verify users table exists (required for foreign key)
        print( "  Verifying users table exists..." )
        cursor.execute( "SELECT name FROM sqlite_master WHERE type='table' AND name='users'" )
        if not cursor.fetchone():
            raise RuntimeError( "Users table does not exist. Run init_auth_database() first." )
        print( "    ✓ Users table found" )

        # Create table
        print( "  Creating api_keys table..." )
        cursor.execute( CREATE_API_KEYS_TABLE )
        print( "    ✓ Table created" )

        # Create indexes
        print( "  Creating indexes..." )
        for idx, index_sql in enumerate( CREATE_INDEXES, 1 ):
            cursor.execute( index_sql )
            print( f"    ✓ Index {idx}/4 created" )

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
        - conn: Active SQLite connection to auth database

    Ensures:
        - Returns validation report dict
        - Validates table exists
        - Validates field count (7 expected)
        - Validates index count (4 expected)

    Returns:
        dict: {"success": bool, "field_count": int, "index_count": int, "error": str}
    """
    try:
        cursor = conn.cursor()

        # Check table exists
        cursor.execute( """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='api_keys'
        """ )
        table_result = cursor.fetchone()

        if not table_result:
            return {
                "success": False,
                "error": "Table 'api_keys' not found"
            }

        # Count fields
        cursor.execute( "PRAGMA table_info(api_keys)" )
        fields = cursor.fetchall()
        field_count = len( fields )

        # Expected: 7 fields (id, user_id, key_hash, description, created_at, last_used_at, is_active)
        expected_fields = 7
        if field_count != expected_fields:
            return {
                "success": False,
                "error": f"Expected {expected_fields} fields, found {field_count}",
                "field_count": field_count
            }

        # Count indexes (excluding SQLite's automatic PRIMARY KEY index)
        cursor.execute( """
            SELECT name FROM sqlite_master
            WHERE type='index' AND tbl_name='api_keys'
            AND name NOT LIKE 'sqlite_autoindex%'
        """ )
        indexes = cursor.fetchall()
        index_count = len( indexes )

        # Expected: 4 indexes (key_hash, user_id, is_active, user_active composite)
        expected_indexes = 4
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
        int: 0 on success, 1 on error
    """
    print( "==================================================" )
    print( "  API Keys Table Creation Script" )
    print( "  Phase 2.5 Notification Authentication" )
    print( "==================================================" )
    print()

    try:
        success = create_api_keys_table()

        if success:
            print()
            print( "==================================================" )
            print( "  ✓ SUCCESS: API keys table created" )
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
