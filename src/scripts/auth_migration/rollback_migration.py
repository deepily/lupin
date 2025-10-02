#!/usr/bin/env python3
"""
Rollback JWT Authentication Migration.

Deletes migrated users from JWT database and optionally reverts configuration.
"""

import sys
import json
from pathlib import Path

# Add project root to Python path
project_root = Path( __file__ ).parent.parent.parent.parent
sys.path.insert( 0, str( project_root / "src" ) )

from cosa.rest.user_service import delete_user_by_email
import cosa.utils.util as du


def rollback_migration( debug=True ):
    """
    Rollback migration by deleting migrated users.

    Requires:
        - migration_results.json exists

    Ensures:
        - All migrated users deleted from database
        - Returns rollback results

    Returns:
        dict: Rollback results with success/failure counts
    """

    du.print_banner( "Migration Rollback", prepend_nl=True )

    # Load migration results
    results_path = Path( __file__ ).parent / "migration_results.json"

    if not results_path.exists():
        print( f"❌ Migration results not found: {results_path}" )
        print( "   Nothing to rollback" )
        return { "status": "no_migration_found" }

    with open( results_path, 'r' ) as f:
        migration_results = json.load( f )

    rollback_results = {
        "total_users" : 0,
        "deleted"     : 0,
        "failed"      : 0,
        "users"       : {}
    }

    print()
    print( "⚠️  WARNING: This will DELETE all migrated users from the database!" )
    print()

    response = input( "Are you sure you want to rollback? (yes/no): " )

    if response.lower() != "yes":
        print( "Rollback cancelled" )
        return { "status": "cancelled" }

    print()
    print( "Rolling back migration..." )
    print()

    for email, user_info in migration_results[ "users" ].items():
        rollback_results[ "total_users" ] += 1

        if user_info[ "status" ] != "migrated":
            print( f"⊘ {email:40s} - Skipped (was not migrated)" )
            continue

        try:
            delete_user_by_email( email )
            print( f"✅ {email:40s} - Deleted" )
            rollback_results[ "deleted" ] += 1
            rollback_results[ "users" ][ email ] = { "status": "deleted" }

        except Exception as e:
            print( f"❌ {email:40s} - Failed to delete: {e}" )
            rollback_results[ "failed" ] += 1
            rollback_results[ "users" ][ email ] = {
                "status" : "failed",
                "error"  : str( e )
            }

    # Print summary
    print()
    print( "=" * 80 )
    print( "  ROLLBACK SUMMARY" )
    print( "=" * 80 )
    print( f"Total users:  {rollback_results['total_users']}" )
    print( f"Deleted:      {rollback_results['deleted']}" )
    print( f"Failed:       {rollback_results['failed']}" )
    print()

    if rollback_results[ "deleted" ] == rollback_results[ "total_users" ]:
        print( "✅ All users rolled back successfully!" )
        rollback_results[ "status" ] = "success"

        # Optionally delete migration results file
        print()
        response = input( "Delete migration_results.json? (yes/no): " )
        if response.lower() == "yes":
            results_path.unlink()
            print( f"✅ Deleted: {results_path}" )
    else:
        print( "❌ Some users failed to rollback" )
        rollback_results[ "status" ] = "partial"

    print( "=" * 80 )
    print()
    print( "⚠️  NOTE: You may want to revert auth_mode in lupin-app.ini back to 'mock'" )
    print()

    return rollback_results


if __name__ == "__main__":
    rollback_migration()
