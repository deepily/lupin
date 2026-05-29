#!/usr/bin/env python3
"""
Seed companion credentials from lupin_db_dev into lupin_db_test.

Ensures the human admin user, system admin, service account, and API keys
exist in the test database so the operator can log into the test server
(port 8000) and monitor test runs with their normal credentials. Also
ensures the cosa-voice MCP API key resolves against the test database.

Runs at test container startup BEFORE uvicorn launches. Idempotent: uses
INSERT ... ON CONFLICT DO NOTHING so it's safe to run on every startup.

Records seeded:
    - Admin user identified by LUPIN_DEV_EMAIL env var (default: ricardo.felipe.ruiz@gmail.com)
    - System admin (admin@lupin.deepily.ai)
    - Service account (claude.code@deepily.ai) — API key owner
    - All api_keys rows owned by the service account

Environment variables:
    DB_HOST           - PostgreSQL hostname (default: lupin-postgres)
    DB_PORT           - PostgreSQL port (default: 5432)
    DB_USER           - PostgreSQL user (default: lupin_dev)
    DB_PASSWORD       - PostgreSQL password (default: dev_password)
    LUPIN_DEV_EMAIL   - Human admin email to seed (default: ricardo.felipe.ruiz@gmail.com)

Created: 2026-04-12 Session 248e740e (dual-container architecture)
"""

import os
import sys

import psycopg2


# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------

DB_HOST     = os.environ.get( "DB_HOST", "lupin-postgres" )
DB_PORT     = os.environ.get( "DB_PORT", "5432" )
DB_USER     = os.environ.get( "DB_USER", "lupin_dev" )
DB_PASSWORD = os.environ.get( "DB_PASSWORD", "dev_password" )

DEV_DB      = "lupin_db_dev"
TEST_DB     = "lupin_db_test"

# Companion emails to seed from dev → test
ADMIN_EMAIL        = os.environ.get( "LUPIN_DEV_EMAIL", "ricardo.felipe.ruiz@gmail.com" )
SYSTEM_ADMIN       = "admin@lupin.deepily.ai"
SERVICE_ACCT       = "claude.code@deepily.ai"             # cross-project service account (no project)
CC_LISTENER_LUPIN  = "claude.code@lupin.deepily.ai"       # 2026-04-28: Lupin-project CC listener identity
INTERACTIVE_TESTER = "interactive.job.tester@lupin.deepily.ai"
MOCK_TESTER        = "mock.job.tester@lupin.deepily.ai"

COMPANION_EMAILS = [ ADMIN_EMAIL, SYSTEM_ADMIN, SERVICE_ACCT, CC_LISTENER_LUPIN, INTERACTIVE_TESTER, MOCK_TESTER ]

# ANSI colors
GREEN  = "\033[0;32m"
YELLOW = "\033[1;33m"
BLUE   = "\033[0;34m"
NC     = "\033[0m"


def _info( msg ):    print( f"{BLUE}[SEED]{NC} {msg}" )
def _success( msg ): print( f"{GREEN}✓{NC} {msg}" )
def _warn( msg ):    print( f"{YELLOW}⚠{NC} {msg}" )


def _connect( dbname ):
    """
    Connect to a specific database on the shared postgres instance.

    Requires:
        - dbname is a valid database name on the configured host

    Ensures:
        - Returns a psycopg2 connection with autocommit=True

    Raises:
        - psycopg2.OperationalError if connection fails
    """
    conn = psycopg2.connect(
        host     = DB_HOST,
        port     = int( DB_PORT ),
        user     = DB_USER,
        password = DB_PASSWORD,
        dbname   = dbname,
        connect_timeout = 5,
    )
    conn.autocommit = True
    return conn


def seed_if_missing():
    """
    Copy companion user rows and API keys from dev DB to test DB.

    Requires:
        - Both lupin_db_dev and lupin_db_test are reachable
        - The users and api_keys tables exist in both databases
        - Companion emails exist in lupin_db_dev

    Ensures:
        - All companion users exist in lupin_db_test with the same UUID,
          email, password_hash, and roles as in lupin_db_dev
        - All api_keys owned by companion users exist in lupin_db_test
        - Idempotent: ON CONFLICT DO NOTHING prevents duplicates
        - Prints summary of what was seeded

    Raises:
        - None (catches and logs all exceptions)
    """
    _info( "Checking companion credentials in test database..." )

    try:
        dev_conn  = _connect( DEV_DB )
        test_conn = _connect( TEST_DB )
    except Exception as e:
        _warn( f"Cannot connect to databases: {e}" )
        _warn( "Companion seed skipped — test server will start without admin credentials" )
        return

    try:
        dev_cur  = dev_conn.cursor()
        test_cur = test_conn.cursor()

        # ── Step 1: Seed companion users ──
        users_seeded = 0
        for email in COMPANION_EMAILS:
            dev_cur.execute(
                "SELECT id, email, password_hash, created_at, email_verified, "
                "is_active, roles FROM users WHERE email = %s",
                ( email, )
            )
            row = dev_cur.fetchone()
            if row is None:
                if email == ADMIN_EMAIL:
                    # Primary admin missing from dev DB means the test server
                    # will lock the operator out on startup. Fail loud instead
                    # of silently continuing (which caused Session 2026-04-15's
                    # hours-long investigation when the E2E suite ran without
                    # subsequent reseed).
                    _warn( f"PRIMARY ADMIN '{email}' missing from {DEV_DB} — aborting seed" )
                    sys.exit( 2 )
                _warn( f"User '{email}' not found in {DEV_DB} — skipping" )
                continue

            uid, email, pw_hash, created_at, email_verified, is_active, roles = row

            # roles is jsonb in postgres — psycopg2 returns it as a Python
            # list but won't auto-cast back to jsonb on insert. Serialize
            # to JSON string and cast explicitly.
            import json as _json
            roles_json = _json.dumps( roles ) if isinstance( roles, ( list, dict ) ) else roles

            test_cur.execute(
                "INSERT INTO users ( id, email, password_hash, created_at, "
                "email_verified, is_active, roles ) "
                "VALUES ( %s, %s, %s, %s, %s, %s, %s::jsonb ) "
                "ON CONFLICT ( id ) DO NOTHING",
                ( uid, email, pw_hash, created_at, email_verified, is_active, roles_json )
            )
            # Check if the row was actually inserted (vs. already existed)
            if test_cur.rowcount > 0:
                users_seeded += 1
                _success( f"Seeded user: {email} ({uid})" )

            # Always ensure companion is marked protected (idempotent)
            test_cur.execute(
                "UPDATE users SET is_protected = TRUE WHERE email = %s",
                ( email, )
            )

        # ── Step 2: Seed API keys owned by companion users ──
        keys_seeded = 0
        for email in COMPANION_EMAILS:
            dev_cur.execute(
                "SELECT a.id, a.user_id, a.key_hash, a.description, a.is_active, "
                "a.created_at, a.last_used_at "
                "FROM api_keys a JOIN users u ON a.user_id = u.id "
                "WHERE u.email = %s",
                ( email, )
            )
            for key_row in dev_cur.fetchall():
                key_id, user_id, key_hash, description, is_active, created_at, last_used_at = key_row

                test_cur.execute(
                    "INSERT INTO api_keys ( id, user_id, key_hash, description, "
                    "is_active, created_at, last_used_at ) "
                    "VALUES ( %s, %s, %s, %s, %s, %s, %s ) "
                    "ON CONFLICT ( id ) DO NOTHING",
                    ( key_id, user_id, key_hash, description, is_active, created_at, last_used_at )
                )
                if test_cur.rowcount > 0:
                    keys_seeded += 1
                    _success( f"Seeded API key: {description or key_id} → {email}" )

        # ── Summary ──
        if users_seeded == 0 and keys_seeded == 0:
            _success( "All companion credentials already present in test database" )
        else:
            _success( f"Seeded {users_seeded} user(s) and {keys_seeded} API key(s) into {TEST_DB}" )

    except Exception as e:
        _warn( f"Companion seed error: {e}" )
        _warn( "Test server will start — some admin features may return 401" )

    finally:
        dev_conn.close()
        test_conn.close()


if __name__ == "__main__":
    seed_if_missing()
