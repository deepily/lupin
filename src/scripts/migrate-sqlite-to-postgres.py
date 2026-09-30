#!/usr/bin/env python3
"""
SQLite to PostgreSQL Migration Script for Lupin Authentication Database.

Migrates data from src/conf/long-term-memory/lupin-auth.db (SQLite)
to PostgreSQL lupin_auth database.

Features:
- Migrates users, active refresh tokens, API keys, recent audit logs
- Type conversions (INTEGER→BOOLEAN, TEXT→UUID, JSON→JSONB, etc.)
- Foreign key validation
- Transaction support (all-or-nothing)
- Dry-run mode for preview
- Detailed logging

Usage:
    python src/scripts/migrate-sqlite-to-postgres.py [--dry-run]
"""

import os
import sys
import sqlite3
import json
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Tuple, Optional

# Add src to path for imports.
#
# NORMALISED and GUARDED, both deliberately (bug bef58663). The unnormalised form
# `os.path.join( os.path.dirname( __file__ ), '..' )` resolves to the same directory but is a
# DIFFERENT STRING from `<root>/src`, so a `not in sys.path` check written the ordinary way
# elsewhere cannot recognise it as already present. Without the check below, every import also
# prepended another copy. Matches the idiom already used by create_service_account_postgres.py.
src_path = os.path.normpath( os.path.join( os.path.dirname( os.path.abspath( __file__ ) ), '..' ) )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

import cosa.utils.util as cu
from cosa.rest.db.database import get_db
from cosa.rest.postgres_models import (
    User, RefreshToken, ApiKey, AuthAuditLog,
    EmailVerificationToken, PasswordResetToken, FailedLoginAttempt
)

# Configuration
SQLITE_DB_PATH = cu.get_project_root() + "/src/conf/long-term-memory/lupin-auth.db"
RECENT_AUDIT_DAYS = 30  # Keep audit logs from last 30 days


def print_banner( title: str ):
    """Print formatted banner."""
    print( "\n" + "=" * 70 )
    print( f"  {title}" )
    print( "=" * 70 + "\n" )


def connect_sqlite() -> sqlite3.Connection:
    """Connect to SQLite database."""
    if not os.path.exists( SQLITE_DB_PATH ):
        print( f"✗ SQLite database not found: {SQLITE_DB_PATH}" )
        sys.exit( 1 )

    conn = sqlite3.connect( SQLITE_DB_PATH )
    conn.row_factory = sqlite3.Row  # Access columns by name
    return conn


def count_sqlite_records( conn: sqlite3.Connection ) -> Dict[str, int]:
    """Count records in each SQLite table."""
    cursor = conn.cursor()

    tables = [
        'users', 'refresh_tokens', 'api_keys', 'auth_audit_log',
        'email_verification_tokens', 'password_reset_tokens', 'failed_login_attempts'
    ]

    counts = {}
    for table in tables:
        cursor.execute( f"SELECT COUNT(*) FROM {table}" )
        counts[table] = cursor.fetchone()[0]

    return counts


def migrate_users( sqlite_conn: sqlite3.Connection, session, dry_run: bool ) -> int:
    """Migrate all users from SQLite to PostgreSQL."""
    cursor = sqlite_conn.cursor()
    cursor.execute( "SELECT * FROM users" )

    migrated = 0
    for row in cursor.fetchall():
        if dry_run:
            print( f"  [DRY-RUN] Would migrate user: {row['email']}" )
        else:
            # Parse roles JSON (TEXT → JSONB)
            roles = json.loads( row['roles'] ) if row['roles'] else ["user"]

            user = User(
                id                = row['id'],  # UUID already in correct format
                email             = row['email'],
                password_hash     = row['password_hash'],
                roles             = roles,
                email_verified    = bool( row['email_verified'] ),  # INTEGER → BOOLEAN
                is_active         = bool( row['is_active'] ),        # INTEGER → BOOLEAN
                created_at        = datetime.fromisoformat( row['created_at'] ) if row['created_at'] else None,
                last_login_at     = datetime.fromisoformat( row['last_login_at'] ) if row['last_login_at'] else None
            )
            session.add( user )

        migrated += 1

    return migrated


def migrate_active_refresh_tokens( sqlite_conn: sqlite3.Connection, session, dry_run: bool ) -> int:
    """Migrate only active (non-expired, non-revoked) refresh tokens."""
    cursor = sqlite_conn.cursor()

    # Get only non-revoked, non-expired tokens
    now = datetime.now( timezone.utc ).isoformat()
    cursor.execute( """
        SELECT * FROM refresh_tokens
        WHERE revoked = 0
        AND expires_at > ?
    """, (now,) )

    migrated = 0
    for row in cursor.fetchall():
        if dry_run:
            print( f"  [DRY-RUN] Would migrate refresh token: {row['jti']}" )
        else:
            # Get optional fields
            user_agent = row['user_agent'] if 'user_agent' in row.keys() else None
            ip_address = row['ip_address'] if 'ip_address' in row.keys() else None

            token = RefreshToken(
                jti           = row['jti'],
                user_id       = row['user_id'],
                token_hash    = row['token_hash'],
                expires_at    = datetime.fromisoformat( row['expires_at'] ),
                created_at    = datetime.fromisoformat( row['created_at'] ) if row['created_at'] else None,
                last_used_at  = datetime.fromisoformat( row['last_used_at'] ) if row['last_used_at'] else None,
                revoked       = bool( row['revoked'] ),  # INTEGER → BOOLEAN
                user_agent    = user_agent,
                ip_address    = ip_address
            )
            session.add( token )

        migrated += 1

    return migrated


def migrate_api_keys( sqlite_conn: sqlite3.Connection, session, dry_run: bool ) -> int:
    """Migrate API keys."""
    cursor = sqlite_conn.cursor()
    cursor.execute( "SELECT * FROM api_keys" )

    migrated = 0
    for row in cursor.fetchall():
        if dry_run:
            print( f"  [DRY-RUN] Would migrate API key: {row['description']}" )
        else:
            # Don't pass id - let PostgreSQL generate UUID
            api_key = ApiKey(
                user_id       = row['user_id'],  # UUID string
                key_hash      = row['key_hash'],
                description   = row['description'],
                is_active     = bool( row['is_active'] ) if 'is_active' in row.keys() else True,
                created_at    = datetime.fromisoformat( row['created_at'] ) if row['created_at'] else None,
                last_used_at  = datetime.fromisoformat( row['last_used_at'] ) if row['last_used_at'] else None
            )
            session.add( api_key )

        migrated += 1

    return migrated


def migrate_recent_audit_logs( sqlite_conn: sqlite3.Connection, session, dry_run: bool ) -> int:
    """Migrate recent audit log entries (last RECENT_AUDIT_DAYS days)."""
    cursor = sqlite_conn.cursor()

    # Calculate cutoff date
    cutoff = (datetime.now( timezone.utc ) - timedelta( days=RECENT_AUDIT_DAYS )).isoformat()

    cursor.execute( """
        SELECT * FROM auth_audit_log
        WHERE event_time > ?
        ORDER BY event_time DESC
    """, (cutoff,) )

    migrated = 0
    for row in cursor.fetchall():
        if dry_run:
            print( f"  [DRY-RUN] Would migrate audit log: {row['event_type']} at {row['event_time']}" )
        else:
            # Parse details JSON (handle empty or invalid JSON)
            details = {}
            if row['details'] and row['details'].strip():
                try:
                    details = json.loads( row['details'] )
                except json.JSONDecodeError:
                    # If JSON is invalid, store as string message
                    details = {"message": row['details']}

            audit_log = AuthAuditLog(
                id           = row['id'],  # INTEGER (keep as-is)
                event_type   = row['event_type'],
                user_id      = row['user_id'],  # Can be NULL
                email        = row['email'],
                ip_address   = row['ip_address'],
                details      = details,  # JSONB
                success      = bool( row['success'] ),  # INTEGER → BOOLEAN
                event_time   = datetime.fromisoformat( row['event_time'] ) if row['event_time'] else None
            )
            session.add( audit_log )

        migrated += 1

    return migrated


def run_migration( dry_run: bool = False ):
    """Execute the migration."""
    mode = "[DRY-RUN]" if dry_run else ""

    print_banner( f"SQLite to PostgreSQL Migration {mode}" )

    # Connect to SQLite
    print( "Connecting to SQLite database..." )
    sqlite_conn = connect_sqlite()
    print( f"✓ Connected: {SQLITE_DB_PATH}" )

    # Count SQLite records
    print( "\nCounting SQLite records..." )
    sqlite_counts = count_sqlite_records( sqlite_conn )
    print( "\nSQLite Record Counts:" )
    for table, count in sqlite_counts.items():
        print( f"  {table:30} {count:5}" )

    # Connect to PostgreSQL
    print( "\nConnecting to PostgreSQL database..." )
    try:
        with get_db() as session:
            print( "✓ Connected to PostgreSQL (lupin_auth database)" )

            # Migrate data
            print( "\n" + "-" * 70 )
            print( "Starting Data Migration..." )
            print( "-" * 70 )

            # Users (all)
            print( "\n1. Migrating users..." )
            user_count = migrate_users( sqlite_conn, session, dry_run )
            print( f"✓ Migrated {user_count} users" )

            # Refresh tokens (active only)
            print( "\n2. Migrating active refresh tokens..." )
            token_count = migrate_active_refresh_tokens( sqlite_conn, session, dry_run )
            print( f"✓ Migrated {token_count} active refresh tokens (filtered from {sqlite_counts['refresh_tokens']})" )

            # API keys
            print( "\n3. Migrating API keys..." )
            api_key_count = migrate_api_keys( sqlite_conn, session, dry_run )
            print( f"✓ Migrated {api_key_count} API keys" )

            # Audit logs (recent only)
            print( "\n4. Migrating recent audit logs (last {RECENT_AUDIT_DAYS} days)..." )
            audit_count = migrate_recent_audit_logs( sqlite_conn, session, dry_run )
            print( f"✓ Migrated {audit_count} audit log entries (filtered from {sqlite_counts['auth_audit_log']})" )

            # Commit transaction
            if not dry_run:
                print( "\nCommitting transaction..." )
                session.commit()
                print( "✓ Transaction committed successfully" )
            else:
                print( "\n[DRY-RUN] Would commit transaction here" )

            # Summary
            print_banner( "Migration Summary" )
            print( f"Users:                {user_count}" )
            print( f"Active Refresh Tokens: {token_count} (of {sqlite_counts['refresh_tokens']} total)" )
            print( f"API Keys:             {api_key_count}" )
            print( f"Recent Audit Logs:    {audit_count} (of {sqlite_counts['auth_audit_log']} total)" )
            print( f"\nTotal Records Migrated: {user_count + token_count + api_key_count + audit_count}" )

            if not dry_run:
                print( "\n✓ Migration completed successfully!" )
            else:
                print( "\n[DRY-RUN] Migration preview complete. Run without --dry-run to execute." )

    except Exception as e:
        print( f"\n✗ Migration failed: {e}" )
        import traceback
        traceback.print_exc()
        sys.exit( 1 )

    finally:
        sqlite_conn.close()


if __name__ == "__main__":  # pragma: no cover - unreachable under pytest: __name__ is the
                            #   module name, never "__main__"
    # Check for dry-run flag
    dry_run = "--dry-run" in sys.argv

    if dry_run:
        print( "\n⚠️  DRY-RUN MODE: No data will be written to PostgreSQL\n" )

    run_migration( dry_run=dry_run )
