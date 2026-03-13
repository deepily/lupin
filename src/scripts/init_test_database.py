#!/usr/bin/env python3
"""
Initialize test database for Phase 2.5 integration tests.

Creates complete authentication schema in test database:
- users table (and all auth-related tables)
- api_keys table
- All indexes and foreign keys

Design reference: src/rnd/2025.11.10-phase-2.5-notification-authentication.md
"""

import sys
import os
from pathlib import Path

# Bootstrap: Use LUPIN_ROOT environment variable
lupin_root = os.environ.get( 'LUPIN_ROOT' )
if lupin_root is None:
    raise RuntimeError(
        "LUPIN_ROOT environment variable not set.\n"
        "Set it before running:\n"
        "  export LUPIN_ROOT=/path/to/project\n"
        "  python src/scripts/init_test_database.py"
    )

src_path = os.path.join( lupin_root, 'src' )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

# Import after bootstrap
from cosa.rest.sqlite_database import init_auth_database, get_auth_db_path
from cosa.config.configuration_manager import ConfigurationManager


def main():
    """
    Initialize test database with full authentication schema.

    Requires:
        - LUPIN_CONFIG_MGR_CLI_ARGS="config_block_id=Lupin:+Testing"
        - LUPIN_ROOT environment variable set

    Ensures:
        - Test database created with users table
        - All auth tables created (refresh_tokens, etc.)
        - Ready for api_keys table creation
        - Ready for integration tests

    Returns:
        int: 0 on success, 1 on error
    """
    print( "==================================================" )
    print( "  Test Database Initialization Script" )
    print( "  Phase 2.5 Integration Tests Setup" )
    print( "==================================================" )
    print()

    try:
        # Verify we're in test mode
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        test_mode = config_mgr.get( "app testing", default=False, return_type="boolean" )

        if not test_mode:
            print( "✗ ERROR: Not in test mode!" )
            print( "  Set environment variable:" )
            print( '  export LUPIN_CONFIG_MGR_CLI_ARGS="config_block_id=Lupin:+Testing"' )
            return 1

        print( "✓ Test mode confirmed" )
        print()

        # Get test database path
        db_path = get_auth_db_path()
        print( f"Test database: {db_path}" )
        print()

        # Initialize authentication database (creates users table + all auth tables)
        print( "Initializing authentication database..." )
        init_auth_database()
        print( "✓ Authentication database initialized" )
        print()

        # Now run create_api_keys_table.py
        print( "Creating api_keys table..." )
        create_api_keys_script = Path( lupin_root ) / 'src' / 'scripts' / 'create_api_keys_table.py'

        import subprocess
        result = subprocess.run(
            [ sys.executable, str( create_api_keys_script ) ],
            capture_output = True,
            text = True
        )

        print( result.stdout )

        if result.returncode != 0:
            print( "✗ ERROR: api_keys table creation failed" )
            print( result.stderr )
            return 1

        print()
        print( "==================================================" )
        print( "  ✓ SUCCESS: Test database initialized" )
        print( "==================================================" )
        print()
        print( "Test database ready for integration tests:" )
        print( f"  Location: {db_path}" )
        print( "  Tables: users, refresh_tokens, api_keys, ..." )
        print()
        print( "Run integration tests:" )
        print( "  ./src/tests/run-integration-tests.sh -v src/tests/integration/test_notification_auth.py" )
        print()

        return 0

    except Exception as e:
        print( f"\n✗ FATAL ERROR: {e}" )
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit( main() )
