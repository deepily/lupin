#!/usr/bin/env python3
"""
Integration test pre-flight: verify the Postgres test database is ready.

Context-agnostic replacement for src/scripts/run-postgresql-dev.sh's role as a
pre-flight gate in src/tests/run-integration-tests.sh. Works identically from
the host shell and from inside the lupin-rest Docker container, using only
psycopg2 + the same get_database_url() path the FastAPI app uses. No docker
CLI, no docker-compose.yml, and no docker socket required.

Checks performed (all must pass for exit 0):
    1. TCP reachability + authentication against the [Lupin: Testing] DSN
    2. current_database() == "lupin_db_test"
    3. public.users table exists (proxy for "schema applied")

Usage:
    python3 src/tests/preflight_test_db.py

Exit codes:
    0 = test database ready
    1 = any check failed; stderr carries details
"""

import os
import sys


# Bootstrap using LUPIN_ROOT environment variable
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    sys.stderr.write(
        "LUPIN_ROOT environment variable not set.\n"
        "Set it before running the pre-flight:\n"
        "  export LUPIN_ROOT=/path/to/lupin\n"
    )
    sys.exit( 1 )

_src_path = os.path.join( lupin_root, "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

# Force testing DSN BEFORE importing the database module
os.environ[ "LUPIN_ENV" ] = "testing"

import psycopg2
from sqlalchemy.engine.url import make_url

from cosa.rest.db.database import get_database_url


# ANSI colors matching run-integration-tests.sh output style
RED    = "\033[0;31m"
GREEN  = "\033[0;32m"
YELLOW = "\033[1;33m"
BLUE   = "\033[0;34m"
NC     = "\033[0m"

EXPECTED_DB_NAME = "lupin_db_test"


def _info( msg ):    print( f"{BLUE}[POSTGRES]{NC} {msg}" )
def _success( msg ): print( f"{GREEN}✓{NC} {msg}" )
def _error( msg ):   print( f"{RED}✗{NC} {msg}" )


def _mask_dsn( url ):
    """
    Render a SQLAlchemy URL with the password elided.

    Requires:
        - url is a sqlalchemy.engine.url.URL instance

    Ensures:
        - returns a string of the form "driver://user:***@host:port/db"
        - never exposes the raw password
    """
    password = "***" if url.password else ""
    userinfo = url.username or ""
    if password:
        userinfo = f"{userinfo}:{password}"
    host_part = url.host or ""
    if url.port:
        host_part = f"{host_part}:{url.port}"
    return f"{url.drivername}://{userinfo}@{host_part}/{url.database or ''}"


def main():
    """
    Verify the Postgres test database is ready for integration tests.

    Requires:
        - LUPIN_ROOT is set and points at the repo root
        - psycopg2 is importable
        - [Lupin: Testing] resolves to a reachable Postgres with lupin_db_test

    Ensures:
        - exits 0 only when all three readiness checks pass
        - exits 1 with a clear stderr message on any failure
        - never prints the raw database password
    """
    _info( "Ensuring PostgreSQL test database is ready..." )

    url = make_url( get_database_url() )

    if url.database != EXPECTED_DB_NAME:
        _error(
            f"DSN database is '{url.database}', expected '{EXPECTED_DB_NAME}'. "
            f"Ensure LUPIN_ENV=testing and DB_NAME override is not set."
        )
        return 1

    masked = _mask_dsn( url )
    _info( f"Target: {masked}" )

    try:
        conn = psycopg2.connect(
            host     = url.host,
            port     = url.port or 5432,
            user     = url.username,
            password = url.password,
            dbname   = url.database,
            connect_timeout = 5,
        )
    except psycopg2.OperationalError as e:
        _error( f"Cannot connect to {masked}: {e}" )
        return 1

    try:
        with conn.cursor() as cur:
            cur.execute( "SELECT 1" )
            cur.fetchone()

            cur.execute( "SELECT current_database()" )
            active_db = cur.fetchone()[ 0 ]
            if active_db != EXPECTED_DB_NAME:
                _error( f"Connected to '{active_db}', expected '{EXPECTED_DB_NAME}'" )
                return 1
            _success( f"Connected to {EXPECTED_DB_NAME}" )

            cur.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = 'users'"
            )
            users_count = cur.fetchone()[ 0 ]
            if users_count != 1:
                _error(
                    f"'users' table missing from {EXPECTED_DB_NAME}. "
                    f"Apply schema via src/scripts/run-postgresql-dev.sh from the host."
                )
                return 1
            _success( "Schema present (users table exists)" )
    finally:
        conn.close()

    _success( "PostgreSQL test database ready" )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
