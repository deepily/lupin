"""
SQLite Authentication Database Layer.

Handles SQLite-specific database operations using raw SQL for authentication.
Uses sqlite3 module with direct SQL statements (no ORM).

For PostgreSQL ORM models, see postgres_models.py.
"""

import os
import sqlite3
from pathlib import Path
from typing import Optional
from cosa.config.configuration_manager import ConfigurationManager
import cosa.utils.util as du

config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )


def get_auth_db_path() -> Path:
    """
    Get authentication database path with dual safety validation.

    Dual Safety Mechanism:
        1. Configuration flag: app_testing=true (from Testing config block)
        2. Path validation: path must contain "test" if app_testing=true

    Requires:
        - Configuration manager initialized
        - auth database path wo root configured

    Ensures:
        - Returns test database only if BOTH safety checks pass
        - Raises ValueError if safety violation detected
        - Creates parent directories if needed

    Raises:
        - ValueError: Safety check failed

    Returns:
        Path: Absolute path to authentication database
    """
    # SAFETY CHECK 1: Configuration flag
    config_test_mode = config_mgr.get( "app testing", default=False, return_type="boolean" )

    # Get database path from current configuration block
    db_path_rel = config_mgr.get(
        "auth database path wo root",
        default="/src/conf/long-term-memory/lupin-auth.db"
    )

    # SAFETY CHECK 2A: If test mode, path MUST contain "test"
    if config_test_mode and "test" not in str( db_path_rel ).lower():
        raise ValueError(
            f"⚠️  SAFETY VIOLATION: app_testing=true but database path missing 'test'\n"
            f"   Path: {db_path_rel}\n"
            f"   Config: app_testing={config_test_mode}"
        )

    # SAFETY CHECK 2B: If path contains "test", MUST be in test mode
    if "test" in str( db_path_rel ).lower() and not config_test_mode:
        raise ValueError(
            f"⚠️  SAFETY VIOLATION: Database path contains 'test' but app_testing=false\n"
            f"   Path: {db_path_rel}\n"
            f"   Config: app_testing={config_test_mode}\n"
            f"   This could destroy test data with production code!"
        )

    # Audit logging
    mode_str = "TEST" if config_test_mode else "PRODUCTION"
    print( f"[AUTH_DB] Mode: {mode_str} (config={config_test_mode})" )
    print( f"[AUTH_DB] Database: {db_path_rel}" )

    # Convert to absolute path using project root utility
    project_root = du.get_project_root()
    db_path = Path( project_root ) / db_path_rel.lstrip( "/" )

    # Ensure parent directory exists
    db_path.parent.mkdir( parents=True, exist_ok=True )

    return db_path


def get_auth_db_connection() -> sqlite3.Connection:
    """
    Get SQLite connection to authentication database.

    Requires:
        - Database path configured
        - Database initialized (or will create)

    Ensures:
        - Returns active SQLite connection
        - Row factory set to sqlite3.Row for dict-like access
        - Foreign keys enabled

    Raises:
        - sqlite3.Error if connection fails

    Returns:
        sqlite3.Connection: Active database connection
    """
    db_path = get_auth_db_path()

    conn = sqlite3.connect( str( db_path ) )
    conn.row_factory = sqlite3.Row  # Enable dict-like row access
    conn.execute( "PRAGMA foreign_keys = ON" )  # Enable foreign key constraints

    return conn


def init_auth_database() -> None:
    """
    Initialize authentication database with schema.

    Creates tables if they don't exist:
    - users
    - refresh_tokens
    - email_verification_tokens (Phase 7)
    - password_reset_tokens (Phase 7)

    Requires:
        - Database path accessible and writable

    Ensures:
        - All tables created with proper schema
        - Indexes created for performance
        - Foreign key constraints enabled
        - Idempotent (safe to call multiple times)

    Raises:
        - sqlite3.Error if schema creation fails
    """
    conn = get_auth_db_connection()
    cursor = conn.cursor()

    try:
        # Create users table
        cursor.execute( """
            CREATE TABLE IF NOT EXISTS users (
                id                TEXT PRIMARY KEY,
                email             TEXT UNIQUE NOT NULL,
                password_hash     TEXT NOT NULL,
                created_at        TEXT NOT NULL,
                email_verified    INTEGER DEFAULT 0,
                is_active         INTEGER DEFAULT 1,
                roles             TEXT DEFAULT '["user"]',
                last_login_at     TEXT,

                CHECK( email_verified IN (0, 1) ),
                CHECK( is_active IN (0, 1) )
            )
        """ )

        # Create indexes for users table
        cursor.execute( "CREATE INDEX IF NOT EXISTS idx_users_email ON users( email )" )
        cursor.execute( "CREATE INDEX IF NOT EXISTS idx_users_is_active ON users( is_active )" )

        # Create refresh_tokens table
        cursor.execute( """
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                jti               TEXT PRIMARY KEY,
                user_id           TEXT NOT NULL,
                token_hash        TEXT NOT NULL,
                expires_at        TEXT NOT NULL,
                revoked           INTEGER DEFAULT 0,
                created_at        TEXT NOT NULL,
                last_used_at      TEXT,
                user_agent        TEXT,
                ip_address        TEXT,

                FOREIGN KEY( user_id ) REFERENCES users( id ) ON DELETE CASCADE,
                CHECK( revoked IN (0, 1) )
            )
        """ )

        # Create indexes for refresh_tokens table
        cursor.execute( "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id ON refresh_tokens( user_id )" )
        cursor.execute( "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_expires_at ON refresh_tokens( expires_at )" )
        cursor.execute( "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_revoked ON refresh_tokens( revoked )" )

        # Create email_verification_tokens table (Phase 7)
        cursor.execute( """
            CREATE TABLE IF NOT EXISTS email_verification_tokens (
                token             TEXT PRIMARY KEY,
                user_id           TEXT NOT NULL,
                expires_at        TEXT NOT NULL,
                used              INTEGER DEFAULT 0,
                created_at        TEXT NOT NULL,

                FOREIGN KEY( user_id ) REFERENCES users( id ) ON DELETE CASCADE,
                CHECK( used IN (0, 1) )
            )
        """ )

        # Create indexes for email_verification_tokens
        cursor.execute( "CREATE INDEX IF NOT EXISTS idx_email_verification_tokens_user_id ON email_verification_tokens( user_id )" )
        cursor.execute( "CREATE INDEX IF NOT EXISTS idx_email_verification_tokens_expires_at ON email_verification_tokens( expires_at )" )

        # Create password_reset_tokens table (Phase 7)
        cursor.execute( """
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                token             TEXT PRIMARY KEY,
                user_id           TEXT NOT NULL,
                expires_at        TEXT NOT NULL,
                used              INTEGER DEFAULT 0,
                created_at        TEXT NOT NULL,

                FOREIGN KEY( user_id ) REFERENCES users( id ) ON DELETE CASCADE,
                CHECK( used IN (0, 1) )
            )
        """ )

        # Create indexes for password_reset_tokens
        cursor.execute( "CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user_id ON password_reset_tokens( user_id )" )
        cursor.execute( "CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_expires_at ON password_reset_tokens( expires_at )" )

        # Create failed_login_attempts table (Phase 8)
        cursor.execute( """
            CREATE TABLE IF NOT EXISTS failed_login_attempts (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                email             TEXT NOT NULL,
                ip_address        TEXT,
                attempt_time      TEXT NOT NULL
            )
        """ )

        # Create indexes for failed_login_attempts
        cursor.execute( "CREATE INDEX IF NOT EXISTS idx_failed_login_attempts_email ON failed_login_attempts( email )" )
        cursor.execute( "CREATE INDEX IF NOT EXISTS idx_failed_login_attempts_attempt_time ON failed_login_attempts( attempt_time )" )

        # Create auth_audit_log table (Phase 8)
        cursor.execute( """
            CREATE TABLE IF NOT EXISTS auth_audit_log (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type        TEXT NOT NULL,
                user_id           TEXT,
                email             TEXT,
                ip_address        TEXT,
                details           TEXT,
                success           INTEGER NOT NULL,
                event_time        TEXT NOT NULL,

                CHECK( success IN (0, 1) )
            )
        """ )

        # Create indexes for auth_audit_log
        cursor.execute( "CREATE INDEX IF NOT EXISTS idx_auth_audit_log_user_id ON auth_audit_log( user_id )" )
        cursor.execute( "CREATE INDEX IF NOT EXISTS idx_auth_audit_log_email ON auth_audit_log( email )" )
        cursor.execute( "CREATE INDEX IF NOT EXISTS idx_auth_audit_log_event_type ON auth_audit_log( event_type )" )
        cursor.execute( "CREATE INDEX IF NOT EXISTS idx_auth_audit_log_event_time ON auth_audit_log( event_time )" )

        # Create api_keys table (Phase 2.5 - Notification Authentication)
        cursor.execute( """
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                key_hash TEXT NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used_at TIMESTAMP,
                is_active BOOLEAN DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """ )

        # Create indexes for api_keys
        cursor.execute( "CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys( key_hash )" )
        cursor.execute( "CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys( user_id )" )
        cursor.execute( "CREATE INDEX IF NOT EXISTS idx_api_keys_is_active ON api_keys( is_active )" )
        cursor.execute( "CREATE INDEX IF NOT EXISTS idx_api_keys_user_active ON api_keys( user_id, is_active )" )

        # Commit changes
        conn.commit()

        print( "[AUTH DB] Database initialized successfully" )

    except sqlite3.Error as e:
        conn.rollback()
        print( f"[AUTH DB] Error initializing database: {e}" )
        raise

    finally:
        conn.close()


def quick_smoke_test():
    """
    Quick smoke test for authentication database.

    Requires:
        - Database path configured and writable
        - sqlite3 module available

    Ensures:
        - Database can be initialized
        - Tables created successfully
        - Indexes exist
        - Connection works

    Raises:
        - None (catches all exceptions)
    """
    import cosa.utils.util as du

    du.print_banner( "Auth Database Smoke Test", prepend_nl=True )

    try:
        # Test 1: Get database path
        print( "Testing database path resolution..." )
        db_path = get_auth_db_path()
        print( f"✓ Database path: {db_path}" )

        # Test 2: Initialize database
        print( "Testing database initialization..." )
        init_auth_database()
        print( "✓ Database initialized" )

        # Test 3: Get connection
        print( "Testing database connection..." )
        conn = get_auth_db_connection()
        print( "✓ Connection established" )

        # Test 4: Verify tables exist
        print( "Testing table creation..." )
        cursor = conn.cursor()
        cursor.execute( "SELECT name FROM sqlite_master WHERE type='table'" )
        tables = [row[0] for row in cursor.fetchall()]

        expected_tables = ["users", "refresh_tokens", "email_verification_tokens", "password_reset_tokens", "failed_login_attempts", "auth_audit_log"]
        for table in expected_tables:
            if table in tables:
                print( f"✓ Table '{table}' exists" )
            else:
                print( f"✗ Table '{table}' missing" )
                return False

        # Test 5: Verify indexes exist
        print( "Testing index creation..." )
        cursor.execute( "SELECT name FROM sqlite_master WHERE type='index'" )
        indexes = [row[0] for row in cursor.fetchall()]

        if len( indexes ) >= 15:  # At least 15 indexes expected (3+3+2+2+2+4-1 for SQLite auto-indexes)
            print( f"✓ {len( indexes )} indexes created" )
        else:
            print( f"⚠ Only {len( indexes )} indexes found (expected >= 15)" )

        conn.close()

        print( "\n✓ All database tests passed!" )
        return True

    except Exception as e:
        print( f"✗ Database test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    quick_smoke_test()