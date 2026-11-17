"""
Helpers shared by the one-off admin scripts under src/scripts.

The table-creation scripts and the service-account scripts repeat the same banner-and-exit-code
runner, the same table-shape check and the same key-file writer. Each script keeps its own public
function names and passes its own table name, banner text or project root.
"""

import sqlite3
import sys
import traceback
from pathlib import Path

BANNER_RULE = "=" * 50


def run_create_script( title, subtitle, success_label, create_fn ):
    """
    Run a table-creation script's main: banner, create, report, exit code.

    Requires:
        - title and subtitle are the two banner lines
        - success_label completes "SUCCESS: <success_label>"
        - create_fn takes no arguments and returns True on success

    Ensures:
        - prints the banner, then a success or failure banner
        - returns 0 when create_fn returns true, else 1
        - returns 1 after printing the error and a traceback when create_fn raises
    """
    print( BANNER_RULE )
    print( f"  {title}" )
    print( f"  {subtitle}" )
    print( BANNER_RULE )
    print()

    try:
        success = create_fn()

        if success:
            print()
            print( BANNER_RULE )
            print( f"  ✓ SUCCESS: {success_label}" )
            print( BANNER_RULE )
            return 0
        else:
            print()
            print( BANNER_RULE )
            print( "  ✗ FAILED: See errors above" )
            print( BANNER_RULE )
            return 1

    except Exception as e:
        print( f"\n✗ FATAL ERROR: {e}", file=sys.stderr )
        traceback.print_exc()
        return 1


def create_table_with_indexes( connect, table, create_sql, index_sqls, validate, precheck=None, table_done=None, index_mark="" ):
    """
    Create one table and its indexes, validate the schema and report each step.

    Requires:
        - connect takes no arguments and returns an open sqlite3 connection
        - create_sql creates the table and each of index_sqls one index
        - validate takes the connection and returns { success, field_count, index_count, error }
        - precheck is None, or takes the cursor, prints its own lines and raises when the work must not start
        - table_done is None, or the line to print after the table is created
        - index_mark is put before each "Index n/total created" line

    Ensures:
        - prints "Creating <table> table...", then the table line, the indexes and the validation result
        - commits before validating
        - returns True when validate says success
        - returns False, after printing the cause on stderr, when validate fails, sqlite3 raises or anything else raises
        - always closes the connection it opened
    """
    conn = None
    try:
        conn   = connect()
        cursor = conn.cursor()

        if precheck is not None: precheck( cursor )

        print( f"  Creating {table} table..." )
        cursor.execute( create_sql )
        if table_done is not None: print( table_done )

        print( "  Creating indexes..." )
        for idx, index_sql in enumerate( index_sqls, 1 ):
            cursor.execute( index_sql )
            print( f"    {index_mark}Index {idx}/{len( index_sqls )} created" )

        conn.commit()

        print( "  Validating schema..." )
        validation_result = validate( conn )

        if validation_result[ "success" ]:
            print( f"  ✓ Schema validated: {validation_result[ 'field_count' ]} fields, {validation_result[ 'index_count' ]} indexes" )
            return True
        print( f"  ✗ Schema validation failed: {validation_result[ 'error' ]}", file=sys.stderr )
        return False

    except sqlite3.Error as e:
        print( f"  ✗ SQLite error: {e}", file=sys.stderr )
        return False
    except Exception as e:
        print( f"  ✗ Unexpected error: {e}", file=sys.stderr )
        return False
    finally:
        if conn: conn.close()


def validate_table( conn, table, expected_fields, expected_indexes ):
    """
    Check that a table exists with the expected field and index counts.

    Requires:
        - conn is an open SQLite connection
        - table is the table name, a trusted constant (PRAGMA cannot bind a name, so it is interpolated there)
        - expected_fields and expected_indexes are ints

    Ensures:
        - returns {"success": True, "field_count": n, "index_count": m} when both counts match
        - returns {"success": False, "error": ...} when the table is missing, a count differs
          (with that count in the dict), or a query fails
        - SQLite's automatic primary-key index is not counted
    """
    try:
        cursor = conn.cursor()

        cursor.execute( "SELECT name FROM sqlite_master WHERE type='table' AND name=?", ( table, ) )
        table_result = cursor.fetchone()

        if not table_result:
            return {
                "success": False,
                "error": f"Table '{table}' not found"
            }

        cursor.execute( f"PRAGMA table_info({table})" )
        fields = cursor.fetchall()
        field_count = len( fields )

        if field_count != expected_fields:
            return {
                "success": False,
                "error": f"Expected {expected_fields} fields, found {field_count}",
                "field_count": field_count
            }

        cursor.execute( """
            SELECT name FROM sqlite_master
            WHERE type='index' AND tbl_name=?
            AND name NOT LIKE 'sqlite_autoindex%'
        """, ( table, ) )
        indexes = cursor.fetchall()
        index_count = len( indexes )

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


def write_key_file( project_root, api_key, env ):
    """
    Write a plaintext API key to src/conf/keys/notification-api-claude-code-<env>.

    Requires:
        - project_root is the repository root as a string or Path
        - api_key is the key string; env is the environment name (dev, staging, prod)

    Ensures:
        - creates src/conf/keys when missing
        - replaces any existing file with the key and a newline
        - sets mode 600 (owner read and write only)
        - prints two confirmation lines
        - returns the Path of the key file
    """
    key_filename = f"notification-api-claude-code-{env}"
    key_file     = Path( project_root ) / "src" / "conf" / "keys" / key_filename

    key_file.parent.mkdir( parents=True, exist_ok=True )
    key_file.write_text( api_key + "\n" )
    key_file.chmod( 0o600 )

    print( f"  ✓ Wrote key to file: {key_file}" )
    print( f"  ✓ Permissions set: 600 (owner read/write only)" )

    return key_file
