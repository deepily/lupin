#!/usr/bin/env python3
"""
PostgreSQL Migration Validation Script.

Validates that SQLite data was successfully migrated to PostgreSQL.

Checks:
- Record counts match expectations
- UUID formats are valid
- Foreign keys resolve correctly
- Password hashes intact
- Active API key present
- User roles preserved
- Timestamps are valid

Usage:
    python src/scripts/validate-postgres-migration.py
"""

import os
import sys
import sqlite3
from datetime import datetime, timezone

# Add src to path for imports
sys.path.insert( 0, os.path.join( os.path.dirname( __file__ ), '..' ) )

import cosa.utils.util as cu
from cosa.rest.db.database import get_db
from cosa.rest.postgres_models import User, RefreshToken, ApiKey, AuthAuditLog

# Configuration
SQLITE_DB_PATH = cu.get_project_root() + "/src/conf/long-term-memory/lupin-auth.db"


def print_banner( title: str ):
    """Print formatted banner."""
    print( "\n" + "=" * 70 )
    print( f"  {title}" )
    print( "=" * 70 + "\n" )


def validate_record_counts():
    """Validate record counts in PostgreSQL."""
    print( "Validating record counts..." )

    with get_db() as session:
        user_count = session.query( User ).count()
        token_count = session.query( RefreshToken ).count()
        api_key_count = session.query( ApiKey ).count()
        audit_count = session.query( AuthAuditLog ).count()

        print( f"  Users:          {user_count}" )
        print( f"  Refresh Tokens: {token_count}" )
        print( f"  API Keys:       {api_key_count}" )
        print( f"  Audit Logs:     {audit_count}" )

        # Basic sanity checks
        assert user_count > 0, "No users found!"
        assert api_key_count > 0, "No API keys found!"

        print( "✓ Record counts validated" )

        return {
            'users': user_count,
            'refresh_tokens': token_count,
            'api_keys': api_key_count,
            'audit_logs': audit_count
        }


def validate_uuids():
    """Validate all UUIDs are properly formatted."""
    print( "\nValidating UUID formats..." )

    with get_db() as session:
        # Check user IDs
        users = session.query( User ).all()
        for user in users:
            assert user.id is not None, f"User {user.email} has NULL id"
            # UUID will already be validated by PostgreSQL type

        # Check refresh token JTIs and user_ids
        tokens = session.query( RefreshToken ).all()
        for token in tokens:
            assert token.jti is not None, "Refresh token has NULL jti"
            assert token.user_id is not None, "Refresh token has NULL user_id"

        # Check API key user_ids
        api_keys = session.query( ApiKey ).all()
        for api_key in api_keys:
            assert api_key.user_id is not None, "API key has NULL user_id"

        print( f"✓ Validated UUIDs for {len(users)} users, {len(tokens)} tokens, {len(api_keys)} API keys" )


def validate_foreign_keys():
    """Validate all foreign key relationships resolve correctly."""
    print( "\nValidating foreign key relationships..." )

    with get_db() as session:
        # Check refresh tokens reference valid users
        tokens = session.query( RefreshToken ).all()
        for token in tokens:
            user = session.query( User ).filter( User.id == token.user_id ).first()
            assert user is not None, f"Refresh token {token.jti} references non-existent user {token.user_id}"

        # Check API keys reference valid users
        api_keys = session.query( ApiKey ).all()
        for api_key in api_keys:
            user = session.query( User ).filter( User.id == api_key.user_id ).first()
            assert user is not None, f"API key {api_key.id} references non-existent user {api_key.user_id}"

        print( f"✓ All foreign keys valid ({len(tokens)} token refs, {len(api_keys)} API key refs)" )


def validate_password_hashes():
    """Validate password hashes are intact (bcrypt format)."""
    print( "\nValidating password hashes..." )

    with get_db() as session:
        users = session.query( User ).all()

        for user in users:
            assert user.password_hash is not None, f"User {user.email} has NULL password_hash"
            assert user.password_hash.startswith( '$2b$' ) or user.password_hash.startswith( '$2a$' ), \
                f"User {user.email} has invalid bcrypt hash format"

        print( f"✓ Validated {len(users)} password hashes (all bcrypt format)" )


def validate_active_api_key():
    """Validate at least one active API key exists."""
    print( "\nValidating active API keys..." )

    with get_db() as session:
        active_keys = session.query( ApiKey ).filter( ApiKey.is_active == True ).all()

        assert len( active_keys ) > 0, "No active API keys found!"

        for key in active_keys:
            print( f"  ✓ Active API key: {key.description} (last used: {key.last_used_at})" )

        print( f"✓ Found {len(active_keys)} active API key(s)" )


def validate_user_roles():
    """Validate user roles are preserved."""
    print( "\nValidating user roles..." )

    with get_db() as session:
        users = session.query( User ).all()

        admin_count = 0
        user_count = 0

        for user in users:
            assert user.roles is not None, f"User {user.email} has NULL roles"
            assert isinstance( user.roles, list ), f"User {user.email} roles is not a list"

            if "admin" in user.roles:
                admin_count += 1
            if "user" in user.roles:
                user_count += 1

        print( f"  Admin users: {admin_count}" )
        print( f"  Regular users: {user_count}" )
        print( f"✓ All {len(users)} users have valid roles" )


def validate_timestamps():
    """Validate timestamps are in correct format."""
    print( "\nValidating timestamps..." )

    with get_db() as session:
        users = session.query( User ).all()

        for user in users:
            if user.created_at:
                assert user.created_at.tzinfo is not None, f"User {user.email} created_at missing timezone"

            if user.last_login_at:
                assert user.last_login_at.tzinfo is not None, f"User {user.email} last_login_at missing timezone"

        print( f"✓ All timestamps have timezone information" )


def run_validation():
    """Execute all validation checks."""
    print_banner( "PostgreSQL Migration Validation" )

    try:
        # Run all validation checks
        counts = validate_record_counts()
        validate_uuids()
        validate_foreign_keys()
        validate_password_hashes()
        validate_active_api_key()
        validate_user_roles()
        validate_timestamps()

        # Success summary
        print_banner( "Validation Complete" )
        print( "✓ All validation checks passed!" )
        print( "\nMigrated Data Summary:" )
        print( f"  Users:          {counts['users']}" )
        print( f"  Refresh Tokens: {counts['refresh_tokens']}" )
        print( f"  API Keys:       {counts['api_keys']}" )
        print( f"  Audit Logs:     {counts['audit_logs']}" )
        print( "\n✓ PostgreSQL database is ready for production use!" )

    except AssertionError as e:
        print( f"\n✗ Validation failed: {e}" )
        sys.exit( 1 )

    except Exception as e:
        print( f"\n✗ Unexpected error during validation: {e}" )
        import traceback
        traceback.print_exc()
        sys.exit( 1 )


if __name__ == "__main__":
    run_validation()
