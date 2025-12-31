#!/usr/bin/env python3
"""
Create Service Account and Generate API Key.

Creates a service account user in the authentication database
and generates a secure API key for programmatic access to Lupin
notification endpoints.

Design reference: src/rnd/2025.11.10-phase-2.5-notification-authentication.md
Section: API Key Security Requirements (lines 83-151)

Usage:
    python src/scripts/create_service_account.py --env=dev
    python src/scripts/create_service_account.py --email=claude.code@deepily.ai --env=prod
    python src/scripts/create_service_account.py --description="Production key" --env=prod
"""

import os
import sys
import argparse
import secrets
import sqlite3
from pathlib import Path
from datetime import datetime

# Bootstrap: Use LUPIN_ROOT environment variable for standalone execution
lupin_root = os.environ.get( 'LUPIN_ROOT' )
if lupin_root is None:
    print( "Error: LUPIN_ROOT environment variable not set.", file=sys.stderr )
    print( "Set it before running:", file=sys.stderr )
    print( "  export LUPIN_ROOT=/path/to/project", file=sys.stderr )
    print( "  python src/scripts/create_service_account.py", file=sys.stderr )
    sys.exit( 1 )

src_path = os.path.join( lupin_root, 'src' )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

# Now cosa is importable
import cosa.utils.util as cu
from cosa.rest.sqlite_database import get_auth_db_connection
from cosa.rest.password_service import hash_password


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


def get_or_create_service_account( email: str, description: str ) -> int:
    """
    Get existing service account or create new one.

    Requires:
        - email is valid email string
        - description is optional string
        - Database is initialized

    Ensures:
        - returns user_id of service account
        - creates user if doesn't exist
        - role set to 'service_account'
        - raises exception on error

    Args:
        email: Service account email
        description: Account description (for users table)

    Returns:
        int: user_id of service account

    Raises:
        RuntimeError: If user exists but is not a service account
        sqlite3.Error: Database errors
    """
    conn = get_auth_db_connection()
    cursor = conn.cursor()

    try:
        # Check if user exists
        cursor.execute( "SELECT id, roles FROM users WHERE email = ?", ( email, ) )
        result = cursor.fetchone()

        if result:
            user_id = result['id']
            roles = result['roles']

            # Verify it's a service account
            import json
            roles_list = json.loads( roles )

            if 'service_account' not in roles_list:
                raise RuntimeError(
                    f"User '{email}' exists but is not a service account.\n"
                    f"Roles: {roles_list}\n"
                    f"Cannot create API key for non-service account users."
                )

            print( f"  Using existing service account: {email} (user_id={user_id})" )
            return user_id

        # Create new service account
        import uuid
        import json

        user_id = str( uuid.uuid4() )

        # Service accounts don't need passwords, but we need to store something
        # Use a high-entropy random value that cannot be guessed
        dummy_password = secrets.token_urlsafe( 32 )
        password_hash = hash_password( dummy_password )

        cursor.execute(
            """
            INSERT INTO users ( id, email, password_hash, created_at, roles, is_active, email_verified )
            VALUES ( ?, ?, ?, ?, ?, ?, ? )
            """,
            (
                user_id,
                email,
                password_hash,
                datetime.utcnow().isoformat(),
                json.dumps( ['service_account'] ),
                1,  # is_active
                1   # email_verified (service accounts don't need email verification)
            )
        )

        conn.commit()
        print( f"  ✓ Created service account: {email} (user_id={user_id})" )

        return user_id

    finally:
        conn.close()


def store_api_key( user_id: str, api_key: str, description: str ) -> int:
    """
    Store API key hash in database.

    Requires:
        - user_id is valid UUID string
        - api_key is valid API key (70+ chars)
        - description is optional string
        - Database is initialized

    Ensures:
        - returns api_key record id
        - stores bcrypt hash (not plaintext)
        - sets created_at timestamp
        - is_active = 1 (enabled)

    Args:
        user_id: Service account user ID
        api_key: Plaintext API key to hash
        description: Key purpose description

    Returns:
        int: api_keys.id of new record

    Raises:
        sqlite3.Error: Database errors
    """
    import bcrypt

    conn = get_auth_db_connection()
    cursor = conn.cursor()

    try:
        # Hash the API key with bcrypt
        key_bytes = api_key.encode( 'utf-8' )
        salt = bcrypt.gensalt( rounds=12 )  # Cost factor 12
        key_hash = bcrypt.hashpw( key_bytes, salt ).decode( 'utf-8' )

        # Insert into api_keys table
        cursor.execute(
            """
            INSERT INTO api_keys ( user_id, key_hash, description, created_at, is_active )
            VALUES ( ?, ?, ?, ?, ? )
            """,
            (
                user_id,
                key_hash,
                description,
                datetime.utcnow().isoformat(),
                1  # is_active
            )
        )

        conn.commit()
        key_id = cursor.lastrowid

        print( f"  ✓ Stored API key in database (key_id={key_id})" )

        return key_id

    finally:
        conn.close()


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
    Main entry point for service account creation.

    Returns:
        int: Exit code (0 = success, 1 = error)
    """
    parser = argparse.ArgumentParser(
        description='Create service account and generate API key',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create with defaults (dev environment)
  python src/scripts/create_service_account.py

  # Create for production
  python src/scripts/create_service_account.py --env=prod

  # Create with custom email and description
  python src/scripts/create_service_account.py \\
    --email=my.service@example.com \\
    --description="CI/CD pipeline key" \\
    --env=staging
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

    print( "=" * 60 )
    print( "  Service Account & API Key Generation" )
    print( "  Phase 2.5 Notification Authentication" )
    print( "=" * 60 )
    print()

    try:
        # Step 1: Create or get service account
        print( "Step 1: Service Account Creation" )
        user_id = get_or_create_service_account( args.email, args.description )
        print()

        # Step 2: Generate API key
        print( "Step 2: API Key Generation" )
        api_key = generate_api_key()
        print( f"  ✓ Generated API key: {api_key[:20]}...{api_key[-10:]} ({len( api_key )} chars)" )
        print()

        # Step 3: Store hashed key in database
        print( "Step 3: Database Storage" )
        key_id = store_api_key( user_id, api_key, args.description )
        print()

        # Step 4: Write plaintext key to file
        print( "Step 4: Key File Creation" )
        key_file = write_key_to_file( api_key, args.env )
        print()

        # Step 5: Display key (ONCE)
        print( "=" * 60 )
        print( "  ✓ SUCCESS: Service Account Created" )
        print( "=" * 60 )
        print()
        print( f"Service Account: {args.email}" )
        print( f"Environment: {args.env}" )
        print( f"Key ID: {key_id}" )
        print()
        print( "🔑 API Key (save this - shown only once):" )
        print( "─" * 60 )
        print( api_key )
        print( "─" * 60 )
        print()
        print( f"Key saved to: {key_file}" )
        print()
        print( "Next steps:" )
        print( f"  1. Verify key file exists: cat {key_file}" )
        print( f"  2. Test configuration: lupin-config test {args.env}" )
        print( f"  3. Send test notification: notify-claude-async 'Test message'" )
        print()
        print( "⚠️  IMPORTANT:" )
        print( "  - This key will not be shown again" )
        print( "  - Keep it secure (file permissions: 600)" )
        print( "  - Add to .gitignore (keys should never be committed)" )
        print( f"  - For production: Store in GCP Secret Manager" )
        print()

        return 0

    except Exception as e:
        print()
        print( "=" * 60 )
        print( "  ✗ FAILED: Service Account Creation" )
        print( "=" * 60 )
        print()
        print( f"Error: {e}", file=sys.stderr )
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit( main() )
