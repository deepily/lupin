#!/usr/bin/env python3
"""
Migrate Mock Authentication Users to JWT Database.

Migrates mock users to JWT authentication system:
- ricardo.felipe.ruiz@gmail.com → ['user', 'admin'] ⭐ SUPERUSER
- alice@example.com → ['user']
- bob@example.com → ['user']

Generates secure random passwords and stores them in migration_results.json
for initial login.
"""

import sys
import os
import json
import secrets
import string
from datetime import datetime
from pathlib import Path

# Add project root to Python path
project_root = Path( __file__ ).parent.parent.parent.parent
sys.path.insert( 0, str( project_root / "src" ) )

from cosa.rest.user_service import create_user
from cosa.config.configuration_manager import ConfigurationManager
import cosa.utils.util as du


def generate_secure_password( length=16 ):
    """
    Generate cryptographically secure random password.

    Requires:
        - length is positive integer (default: 16)

    Ensures:
        - Returns random password with letters, numbers, symbols
        - Password is cryptographically secure using secrets module
        - Password meets complexity requirements

    Args:
        length: Password length (default: 16)

    Returns:
        str: Secure random password
    """
    # Character sets for password generation
    letters     = string.ascii_letters  # a-z, A-Z
    digits      = string.digits         # 0-9
    punctuation = "!@#$%^&*"            # Safe special characters

    # Combine all character sets
    all_chars = letters + digits + punctuation

    # Ensure password has at least one of each type
    password = [
        secrets.choice( string.ascii_lowercase ),
        secrets.choice( string.ascii_uppercase ),
        secrets.choice( digits ),
        secrets.choice( punctuation )
    ]

    # Fill remaining length with random characters
    password += [ secrets.choice( all_chars ) for _ in range( length - 4 ) ]

    # Shuffle to avoid predictable patterns
    secrets.SystemRandom().shuffle( password )

    return ''.join( password )


def migrate_users( debug=True ):
    """
    Migrate mock users to JWT authentication database.

    Requires:
        - Auth database initialized
        - User service available
        - Password service available

    Ensures:
        - All 3 users created in database
        - Passwords hashed securely with bcrypt
        - Ricardo gets admin + user roles
        - Alice and Bob get user role only
        - Migration results saved to JSON file
        - Returns migration results dictionary

    Args:
        debug: Enable debug output (default: True)

    Returns:
        dict: Migration results with user details and passwords

    Raises:
        Exception: If migration fails
    """

    config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

    du.print_banner( "JWT Authentication Migration - Mock to JWT", prepend_nl=True )

    # Define users to migrate
    users_to_migrate = [
        {
            "email" : "ricardo.felipe.ruiz@gmail.com",
            "roles" : [ "user", "admin" ]  # SUPERUSER!
        },
        {
            "email" : "alice@example.com",
            "roles" : [ "user" ]  # Regular user
        },
        {
            "email" : "bob@example.com",
            "roles" : [ "user" ]  # Regular user
        }
    ]

    migration_results = {
        "migration_date" : datetime.now().isoformat(),
        "users"          : {}
    }

    print( "\n" + "=" * 80 )
    print( "  MIGRATING USERS FROM MOCK TO JWT AUTHENTICATION" )
    print( "=" * 80 )
    print()

    for user_data in users_to_migrate:
        email = user_data[ "email" ]
        roles = user_data[ "roles" ]

        if debug:
            role_str = ", ".join( roles )
            if "admin" in roles:
                print( f"Creating {email:40s} → Roles: {role_str} ⭐ SUPERUSER" )
            else:
                print( f"Creating {email:40s} → Roles: {role_str}" )

        # Generate secure random password
        password = generate_secure_password( 16 )

        try:
            # Create user in database (password is hashed inside create_user)
            success, message, user_id = create_user(
                email    = email,
                password = password,
                roles    = roles
            )

            if not success:
                raise Exception( message )

            # Store migration results
            migration_results[ "users" ][ email ] = {
                "password" : password,  # ⚠️ SENSITIVE - Only in migration_results.json
                "user_id"  : user_id,
                "roles"    : roles,
                "status"   : "migrated"
            }

            if debug: print( f"  ✅ Created user_id: {user_id}" )

        except Exception as e:
            print( f"  ❌ Error creating user {email}: {e}" )
            migration_results[ "users" ][ email ] = {
                "status" : "failed",
                "error"  : str( e )
            }

    # Save migration results to JSON file
    results_path = Path( __file__ ).parent / "migration_results.json"

    with open( results_path, 'w' ) as f:
        json.dump( migration_results, f, indent=2 )

    print()
    print( "=" * 80 )
    print( "  MIGRATION COMPLETE" )
    print( "=" * 80 )
    print()

    # Display passwords prominently
    print( "🔐 INITIAL PASSWORDS (Save these for first login):" )
    print()

    for email, user_info in migration_results[ "users" ].items():
        if user_info[ "status" ] == "migrated":
            password = user_info[ "password" ]
            roles    = user_info[ "roles" ]
            role_str = ", ".join( roles )

            if "admin" in roles:
                print( f"✅ {email}" )
                print( f"   Password: {password}" )
                print( f"   Roles: {role_str} ⭐ SUPERUSER" )
            else:
                print( f"✅ {email}" )
                print( f"   Password: {password}" )
                print( f"   Roles: {role_str}" )
            print()

    print( f"Results saved to: {results_path}" )
    print( "=" * 80 )
    print()
    print( "⚠️  IMPORTANT:")
    print( "   1. Save the passwords above - they won't be shown again")
    print( "   2. migration_results.json is gitignored (contains plaintext passwords)")
    print( "   3. Use these passwords for first login via web UI")
    print( "   4. Change your password immediately after first login")
    print()
    print( "Next steps:")
    print( "   1. Open browser: http://localhost:7999/static/html/auth/login.html")
    print( "   2. Login with ricardo.felipe.ruiz@gmail.com + password above")
    print( "   3. Go to profile → Change password")
    print( "   4. Logout and login with YOUR new password")
    print()

    return migration_results


def quick_smoke_test():
    """
    Quick smoke test for migration script.

    Tests password generation and validates format.
    """
    du.print_banner( "Migration Script Smoke Test", prepend_nl=True )

    try:
        # Test password generation
        print( "Testing password generation..." )
        password = generate_secure_password( 16 )
        assert len( password ) == 16, f"Password length incorrect: {len(password)}"
        assert any( c.isupper() for c in password ), "Password missing uppercase"
        assert any( c.islower() for c in password ), "Password missing lowercase"
        assert any( c.isdigit() for c in password ), "Password missing digit"
        assert any( c in "!@#$%^&*" for c in password ), "Password missing special char"
        print( f"  ✓ Generated password: {password}" )
        print( f"  ✓ Password meets complexity requirements" )

        print( "\n✅ Migration script smoke test passed!" )
        return True

    except Exception as e:
        print( f"\n❌ Smoke test failed: {e}" )
        return False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser( description="Migrate mock users to JWT authentication" )
    parser.add_argument( "--test", action="store_true", help="Run smoke test instead of migration" )
    parser.add_argument( "--debug", action="store_true", default=True, help="Enable debug output" )

    args = parser.parse_args()

    if args.test:
        quick_smoke_test()
    else:
        migrate_users( debug=args.debug )
