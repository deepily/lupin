#!/usr/bin/env python3
"""
Create Service Account and Generate API Key (PostgreSQL).

Creates a service account user in the PostgreSQL authentication database
and generates a secure API key for programmatic access to Lupin
notification endpoints.

Design reference: src/rnd/2025.11.10-phase-2.5-notification-authentication.md
Section: API Key Security Requirements (lines 83-151)

PostgreSQL Migration: Phase 2.6.2 (November 2025)
- Uses SQLAlchemy ORM with repository pattern
- Stores in PostgreSQL-in-Docker (lupin-postgres)
- Replaces SQLite-based create_service_account.py

Usage:
    python src/scripts/create_service_account_postgres.py --env=dev
    python src/scripts/create_service_account_postgres.py --email=claude.code@deepily.ai --env=prod
    python src/scripts/create_service_account_postgres.py --description="Production key" --env=prod
"""

import os
import sys
import argparse
import secrets
import bcrypt
import uuid
from pathlib import Path
from datetime import datetime, timezone

# Bootstrap: Use LUPIN_ROOT environment variable for standalone execution
lupin_root = os.environ.get( 'LUPIN_ROOT' )
if lupin_root is None:
    print( "Error: LUPIN_ROOT environment variable not set.", file=sys.stderr )
    print( "Set it before running:", file=sys.stderr )
    print( "  export LUPIN_ROOT=/path/to/project", file=sys.stderr )
    print( "  python src/scripts/create_service_account_postgres.py", file=sys.stderr )
    sys.exit( 1 )

src_path = os.path.join( lupin_root, 'src' )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

# Now cosa is importable
import cosa.utils.util as cu
from cosa.rest.db.database import get_db
from cosa.rest.db.repositories import UserRepository, ApiKeyRepository


def generate_api_key() -> str:
    """
    Generate a secure API key with format: ck_live_{random}.

    Requires:
        - secrets module available (Python 3.6+)

    Ensures:
        - returns API key string (70 characters)
        - format: ck_live_ + 64 chars base64url
        - cryptographically secure (288 bits entropy)

    Returns:
        str: API key (e.g., "ck_live_9x7Kp3mN8vQ2jR5wT6yL...")
    """
    random_part = secrets.token_urlsafe( 48 )  # 64 chars base64url
    api_key = f"ck_live_{random_part}"
    return api_key


def get_or_create_service_account( email: str, description: str ) -> uuid.UUID:
    """
    Get existing service account or create new one (PostgreSQL).

    Requires:
        - email is valid email string
        - description is optional string
        - PostgreSQL database is running and initialized
        - LUPIN_ENV environment variable set (development/testing/production)

    Ensures:
        - returns user_id (UUID) of service account
        - creates user if doesn't exist
        - role set to ['service_account']
        - raises exception on error

    Args:
        email: Service account email
        description: Account description (not currently stored in users table)

    Returns:
        uuid.UUID: user_id of service account

    Raises:
        RuntimeError: If user exists but is not a service account
        Exception: Database errors
    """
    with get_db() as session:
        user_repo = UserRepository( session )

        # Check if user exists
        existing_user = user_repo.get_by_email( email )

        if existing_user:
            # Verify it's a service account
            if 'service_account' not in existing_user.roles:
                raise RuntimeError(
                    f"User '{email}' exists but is not a service account.\n"
                    f"Roles: {existing_user.roles}\n"
                    f"Cannot create API key for non-service account users."
                )

            print( f"  Using existing service account: {email}" )
            print( f"  User ID: {existing_user.id}" )
            print( f"  Roles: {existing_user.roles}" )
            return existing_user.id

        # Create new service account
        # Service accounts don't need passwords, but we need to store something
        # Use a high-entropy random value that cannot be guessed
        dummy_password = secrets.token_urlsafe( 32 )

        # Hash with bcrypt (matching password_service.py pattern)
        password_hash = bcrypt.hashpw(
            dummy_password.encode( 'utf-8' ),
            bcrypt.gensalt( rounds=12 )
        ).decode( 'utf-8' )

        # Create user via repository
        user = user_repo.create_user(
            email = email,
            password_hash = password_hash,
            roles = ['service_account']
        )

        # Set email_verified (service accounts don't need verification)
        user.email_verified = True

        print( f"  ✓ Created service account: {email}" )
        print( f"     User ID: {user.id}" )
        print( f"     Roles: {user.roles}" )

        return user.id


def store_api_key( user_id: uuid.UUID, api_key: str, description: str, env: str ) -> uuid.UUID:
    """
    Store API key hash in PostgreSQL database.

    Requires:
        - user_id is valid UUID
        - api_key is valid API key (70+ chars)
        - description is optional string
        - env is environment name
        - PostgreSQL database is running

    Ensures:
        - returns api_key record id (UUID)
        - stores bcrypt hash (not plaintext)
        - sets created_at timestamp automatically
        - is_active = True (enabled)

    Args:
        user_id: Service account user ID (UUID)
        api_key: Plaintext API key to hash
        description: Key purpose description
        env: Environment name (dev, staging, prod)

    Returns:
        uuid.UUID: api_keys.id of new record

    Raises:
        Exception: Database errors
    """
    with get_db() as session:
        api_key_repo = ApiKeyRepository( session )

        # Hash the API key with bcrypt (cost factor 12)
        key_bytes = api_key.encode( 'utf-8' )
        salt = bcrypt.gensalt( rounds=12 )
        key_hash = bcrypt.hashpw( key_bytes, salt ).decode( 'utf-8' )

        # Build description if not provided
        if not description:
            description = f"Claude Code notification service ({env})"

        # Create API key via repository
        api_key_obj = api_key_repo.create_key(
            user_id = user_id,
            key_hash = key_hash,
            description = description
        )

        print( f"  ✓ Stored API key hash in PostgreSQL" )
        print( f"     API Key ID: {api_key_obj.id}" )
        print( f"     Description: {description}" )

        return api_key_obj.id


def write_key_to_file( api_key: str, env: str ) -> Path:
    """
    Write plaintext API key to environment-specific file.

    Requires:
        - api_key is valid API key string
        - env is environment name (dev, staging, prod)
        - LUPIN_ROOT environment variable set

    Ensures:
        - writes key to src/conf/keys/notification-api-claude-code-{env}
        - sets file permissions to 600 (owner read/write only)
        - creates directory if needed
        - returns Path to key file

    Args:
        api_key: Plaintext API key
        env: Environment name

    Returns:
        Path: Absolute path to key file

    Raises:
        OSError: File system errors
    """
    project_root = cu.get_project_root()

    # Determine key file path based on environment
    key_filename = f"notification-api-claude-code-{env}"
    key_file = Path( project_root ) / "src" / "conf" / "keys" / key_filename

    # Create directory if needed
    key_file.parent.mkdir( parents=True, exist_ok=True )

    # Write key to file
    key_file.write_text( api_key + "\n" )

    # Set restrictive permissions (owner read/write only)
    key_file.chmod( 0o600 )

    print( f"  ✓ Wrote key to file: {key_file}" )
    print( f"  ✓ Permissions set: 600 (owner read/write only)" )

    return key_file


def main():
    """
    Main entry point for service account creation (PostgreSQL).

    Returns:
        int: Exit code (0 = success, 1 = error)
    """
    parser = argparse.ArgumentParser(
        description='Create service account and generate API key (PostgreSQL)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create with defaults (dev environment)
  python src/scripts/create_service_account_postgres.py

  # Create for production
  python src/scripts/create_service_account_postgres.py --env=prod

  # Create with custom email and description
  python src/scripts/create_service_account_postgres.py \\
    --email=my.service@example.com \\
    --description="CI/CD pipeline key" \\
    --env=staging

Environment Variables:
  LUPIN_ROOT     - Project root directory (required)
  LUPIN_ENV      - development/testing/production (determines PostgreSQL connection)
        """
    )

    parser.add_argument(
        '--email',
        default='claude.code@deepily.ai',
        help='Service account email (default: claude.code@deepily.ai)'
    )

    parser.add_argument(
        '--description',
        default='',
        help='Key description (optional)'
    )

    parser.add_argument(
        '--env',
        default='dev',
        choices=['dev', 'staging', 'prod'],
        help='Environment (dev, staging, prod) - determines key file name (default: dev)'
    )

    args = parser.parse_args()

    # Display header
    print()
    print( "=" * 70 )
    print( "  Service Account & API Key Generation (PostgreSQL)" )
    print( "  Phase 2.5 Notification Authentication + Phase 2.6.2 PostgreSQL Migration" )
    print( "=" * 70 )
    print()

    # Check LUPIN_ENV
    lupin_env = os.environ.get( 'LUPIN_ENV', 'development' )
    print( f"PostgreSQL Environment: {lupin_env}" )
    print( f"Key File Environment: {args.env}" )
    print()

    try:
        # Step 1: Create or get service account
        print( "Step 1: Service Account Creation" )
        user_id = get_or_create_service_account( args.email, args.description )
        print()

        # Step 2: Generate API key
        print( "Step 2: API Key Generation" )
        api_key = generate_api_key()
        print( f"  ✓ Generated secure API key ({len( api_key )} characters)" )
        print()

        # Step 3: Store hashed key in PostgreSQL
        print( "Step 3: PostgreSQL Storage" )
        key_id = store_api_key( user_id, api_key, args.description, args.env )
        print()

        # Step 4: Write plaintext key to file
        print( "Step 4: Key File Creation" )
        try:
            key_file = write_key_to_file( api_key, args.env )
        except OSError as e:
            # A read-only project mount (e.g. running inside the app container, where
            # /var/lupin is bind-mounted read-only) must NOT lose the freshly-minted secret:
            # the DB now holds only the bcrypt hash, so this file was the only plaintext copy.
            # Warn and continue to Step 5, which prints the key for the operator to capture.
            reason = getattr( e, "strerror", None ) or str( e )
            key_file = f"<not written — {reason}; capture the printed key below>"
            print( f"  ⚠ Could not write key file ({reason})." )
            print( f"  ⚠ The plaintext key is printed in Step 5 — capture it NOW; it is not recoverable later." )
        print()

        # Step 5: Display success + key (ONCE)
        print( "=" * 70 )
        print( "  ✅ SUCCESS: Service Account Created in PostgreSQL" )
        print( "=" * 70 )
        print()
        print( f"Service Account: {args.email}" )
        print( f"User ID: {user_id}" )
        print( f"Environment: {args.env}" )
        print( f"API Key ID: {key_id}" )
        print()
        print( "🔑 API Key (save this - shown only once):" )
        print( "━" * 70 )
        print( api_key )
        print( "━" * 70 )
        print()
        print( f"Key saved to: {key_file}" )
        print()
        print( "Next steps:" )
        print( f"  1. Verify key file exists:" )
        print( f"     cat {key_file}" )
        print()
        print( f"  2. Verify PostgreSQL registration:" )
        print( f"     docker exec -it lupin-postgres psql -U lupin_dev -d lupin_auth -c \\" )
        print( f'       "SELECT id, email, roles FROM users WHERE email = \'{args.email}\';"' )
        print()
        print( f"  3. Test notification:" )
        print( f'     notify-claude-async "[LUPIN] Test message" --type=custom --priority=low' )
        print()
        print( "⚠️  IMPORTANT:" )
        print( "  - This key will not be shown again" )
        print( "  - Keep it secure (file permissions: 600)" )
        print( "  - Add to .gitignore (keys should never be committed)" )
        print( "  - For production: Store in GCP Secret Manager" )
        print( "  - The bcrypt hash is stored in PostgreSQL for validation" )
        print()

        return 0

    except Exception as e:
        print()
        print( "=" * 70 )
        print( "  ✗ FAILED: Service Account Creation" )
        print( "=" * 70 )
        print()
        print( f"Error: {e}", file=sys.stderr )
        import traceback
        traceback.print_exc()
        print()
        print( "Troubleshooting:" )
        print( "  - Check PostgreSQL is running: docker ps | grep lupin-postgres" )
        print( "  - Check LUPIN_ENV is set: echo $LUPIN_ENV" )
        print( "  - Check LUPIN_ROOT is set: echo $LUPIN_ROOT" )
        print( "  - Check database connection: docker exec -it lupin-postgres psql -U lupin_dev -d lupin_auth" )
        return 1


if __name__ == "__main__":  # pragma: no cover - unreachable under pytest: __name__ is the
                            #   module name, never "__main__"
    sys.exit( main() )
