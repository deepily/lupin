#!/usr/bin/env python3
"""
Reset User Password - Simple password reset utility.

IMPORTANT: Run from inside the Docker container. The host .venv has bcrypt 5.x
which is incompatible with passlib. The container has bcrypt 3.2.2 which works.

Usage (Docker — recommended):
    docker exec -it lupin-rest python3 -m scripts.reset_user_password user@example.com "NewPassword123!"
    docker exec -it lupin-rest python3 -m scripts.reset_user_password --use-original user@example.com

Usage (host — only if bcrypt <4.1 is installed in .venv):
    python src/scripts/reset_user_password.py user@example.com "NewPassword123!"
    python src/scripts/reset_user_password.py --use-original user@example.com
"""

import sys
import os
import json
from pathlib import Path

# Bootstrap using LUPIN_ROOT environment variable
lupin_root = os.environ.get( 'LUPIN_ROOT' )
if lupin_root is None:
    raise RuntimeError(
        "LUPIN_ROOT environment variable not set.\n"
        "Set it before running:\n"
        "  export LUPIN_ROOT=/path/to/project\n"
        "  python src/scripts/reset_user_password.py"
    )

src_path = os.path.join( lupin_root, 'src' )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

# Now cosa is importable
import cosa.utils.util as du
from cosa.rest.user_service import update_user_password, get_user_by_email
from cosa.rest.password_service import hash_password


def reset_password( email, new_password=None, use_original=False, debug=True ):
    """
    Reset a user's password.

    Requires:
        - email is a valid registered user email
        - new_password is provided OR use_original=True

    Ensures:
        - User password is updated in database
        - Returns success status

    Args:
        email: User email address
        new_password: New password to set
        use_original: If True, use password from migration_results.json
        debug: Print debug output

    Returns:
        bool: True if password reset successful
    """

    du.print_banner( "Password Reset Utility", prepend_nl=True )

    # Get original password if requested
    if use_original:
        migration_file = Path( lupin_root ) / "src/scripts/auth_migration/migration_results.json"

        if not migration_file.exists():
            print( f"❌ Migration results not found: {migration_file}" )
            print( "   Cannot retrieve original password" )
            return False

        with open( migration_file, 'r' ) as f:
            migration_data = json.load( f )

        if email not in migration_data[ "users" ]:
            print( f"❌ User {email} not found in migration results" )
            return False

        new_password = migration_data[ "users" ][ email ][ "password" ]
        print( f"📋 Using original password from migration: {new_password}" )
        print()

    elif not new_password:
        print( "❌ No password provided. Use --use-original or provide a password" )
        return False

    # Verify user exists
    try:
        user = get_user_by_email( email )
        if not user:
            print( f"❌ User not found: {email}" )
            return False

        print( f"✓ Found user: {email}" )
        print( f"  User ID: {user['id']}" )
        print( f"  Roles: {user.get('roles', [])}" )
        print()

    except Exception as e:
        print( f"❌ Error finding user: {e}" )
        return False

    # Update password
    try:
        print( f"Updating password for {email}..." )
        print()

        # Hash the new password
        password_hash = hash_password( new_password )

        # Update in database using repository (bypass broken update_user_password function)
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories import UserRepository
        import uuid

        with get_db() as session:
            user_repo = UserRepository( session )
            user_obj = user_repo.get_by_id( uuid.UUID( user['id'] ) )

            if not user_obj:
                print( f"❌ User not found in database" )
                return False

            # Update password hash directly
            user_obj.password_hash = password_hash
            session.commit()

            print( f"✅ Password reset successful for {email}" )
            print()
            print( f"New password: {new_password}" )
            print()
            return True

    except Exception as e:
        print( f"❌ Error resetting password: {e}" )
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    if len( sys.argv ) < 2:
        print( "Usage (run from inside Docker container — host has bcrypt version mismatch):" )
        print()
        print( "  docker exec -it lupin-rest python3 -m scripts.reset_user_password <email> <new_password>" )
        print( "  docker exec -it lupin-rest python3 -m scripts.reset_user_password --use-original <email>" )
        print()
        print( "Examples:" )
        print( '  docker exec -it lupin-rest python3 -m scripts.reset_user_password user@example.com "NewPass123!"' )
        print( '  docker exec -it lupin-rest python3 -m scripts.reset_user_password --use-original user@example.com' )
        print()
        print( "Host usage (only if bcrypt <4.1 installed in .venv):" )
        print( '  python src/scripts/reset_user_password.py user@example.com "NewPass123!"' )
        sys.exit( 1 )

    use_original = False
    email = None
    new_password = None

    if sys.argv[1] == "--use-original":
        use_original = True
        email = sys.argv[2] if len( sys.argv ) > 2 else None
    else:
        email = sys.argv[1]
        new_password = sys.argv[2] if len( sys.argv ) > 2 else None

    if not email:
        print( "❌ Email address required" )
        sys.exit( 1 )

    success = reset_password( email, new_password, use_original )
    sys.exit( 0 if success else 1 )
