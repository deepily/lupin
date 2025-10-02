#!/usr/bin/env python3
"""
Validate JWT Authentication Migration.

Verifies that all users were successfully migrated to JWT database.
"""

import sys
import json
from pathlib import Path

# Add project root to Python path
project_root = Path( __file__ ).parent.parent.parent.parent
sys.path.insert( 0, str( project_root / "src" ) )

from cosa.rest.user_service import get_user_by_email
from cosa.rest.password_service import verify_password
import cosa.utils.util as du


def validate_migration( debug=True ):
    """
    Validate migration results.

    Requires:
        - Migration has been executed
        - migration_results.json exists

    Ensures:
        - All users exist in database
        - Passwords can be verified
        - Roles assigned correctly
        - Returns validation results

    Returns:
        dict: Validation results with pass/fail status
    """

    du.print_banner( "Migration Validation", prepend_nl=True )

    # Load migration results
    results_path = Path( __file__ ).parent / "migration_results.json"

    if not results_path.exists():
        print( f"❌ Migration results not found: {results_path}" )
        print( "   Run migrate_mock_users.py first" )
        return { "status": "failed", "error": "migration_results.json not found" }

    with open( results_path, 'r' ) as f:
        migration_results = json.load( f )

    validation_results = {
        "total_users"   : 0,
        "validated"     : 0,
        "failed"        : 0,
        "users"         : {}
    }

    print()
    print( "Validating migrated users..." )
    print()

    for email, user_info in migration_results[ "users" ].items():
        validation_results[ "total_users" ] += 1

        if user_info[ "status" ] != "migrated":
            print( f"❌ {email:40s} - Skipped (migration failed)" )
            validation_results[ "failed" ] += 1
            continue

        try:
            # Check user exists in database
            user_dict = get_user_by_email( email )

            if not user_dict:
                print( f"❌ {email:40s} - User not found in database" )
                validation_results[ "failed" ] += 1
                validation_results[ "users" ][ email ] = { "status": "not_found" }
                continue

            # Verify password hash
            password = user_info[ "password" ]
            password_hash = user_dict[ "password_hash" ]

            if not verify_password( password, password_hash ):
                print( f"❌ {email:40s} - Password verification failed" )
                validation_results[ "failed" ] += 1
                validation_results[ "users" ][ email ] = { "status": "password_mismatch" }
                continue

            # Check roles
            expected_roles = set( user_info[ "roles" ] )
            actual_roles = set( user_dict[ "roles" ].split( "," ) if user_dict[ "roles" ] else [] )

            if expected_roles != actual_roles:
                print( f"❌ {email:40s} - Roles mismatch. Expected: {expected_roles}, Got: {actual_roles}" )
                validation_results[ "failed" ] += 1
                validation_results[ "users" ][ email ] = {
                    "status"         : "role_mismatch",
                    "expected_roles" : list( expected_roles ),
                    "actual_roles"   : list( actual_roles )
                }
                continue

            # All checks passed
            role_str = ", ".join( user_info[ "roles" ] )
            if "admin" in user_info[ "roles" ]:
                print( f"✅ {email:40s} - Verified (Roles: {role_str} ⭐)" )
            else:
                print( f"✅ {email:40s} - Verified (Roles: {role_str})" )

            validation_results[ "validated" ] += 1
            validation_results[ "users" ][ email ] = {
                "status"  : "validated",
                "user_id" : user_dict[ "user_id" ],
                "roles"   : user_info[ "roles" ]
            }

        except Exception as e:
            print( f"❌ {email:40s} - Validation error: {e}" )
            validation_results[ "failed" ] += 1
            validation_results[ "users" ][ email ] = {
                "status" : "error",
                "error"  : str( e )
            }

    # Print summary
    print()
    print( "=" * 80 )
    print( "  VALIDATION SUMMARY" )
    print( "=" * 80 )
    print( f"Total users:  {validation_results['total_users']}" )
    print( f"Validated:    {validation_results['validated']}" )
    print( f"Failed:       {validation_results['failed']}" )
    print()

    if validation_results[ "validated" ] == validation_results[ "total_users" ]:
        print( "✅ All users validated successfully!" )
        validation_results[ "status" ] = "passed"
    else:
        print( "❌ Some users failed validation" )
        validation_results[ "status" ] = "failed"

    print( "=" * 80 )
    print()

    return validation_results


if __name__ == "__main__":
    validate_migration()
