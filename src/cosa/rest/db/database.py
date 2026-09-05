"""
Database session management for PostgreSQL with SQLAlchemy.

Provides:
    - Environment-aware database URL builder (dev/testing/production)
    - SQLAlchemy engine with connection pooling
    - Session factory and scoped session
    - Context manager for automatic session lifecycle management

Usage:
    from cosa.rest.db.database import get_db

    with get_db() as session:
        user = session.query( User ).filter( User.email == email ).first()
        # session.commit() called automatically on success
        # session.rollback() called automatically on exception
"""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, scoped_session, Session
from sqlalchemy.pool import NullPool
from contextlib import contextmanager
import os
from typing import Generator

from cosa.rest.postgres_models import Base
from cosa.utils.dotenv_password import seed_db_password_from_dotenv


_CLOUD_BACKED_TRUTHY = ( "1", "true", "yes", "on" )


def is_cloud_backed() -> bool:
    """
    Decide whether this deployment uses cloud-backed Postgres (Cloud SQL).

    Cloud-backing is an explicit deployment property set via LUPIN_CLOUD_BACKED
    — it is NEVER inferred from the environment NAME. The GCP test env and any
    future production env opt in by setting the flag; local dev/test leave it
    unset and run against local Postgres-in-Docker.

    Requires:
        - reads os.environ for LUPIN_CLOUD_BACKED

    Ensures:
        - returns True iff LUPIN_CLOUD_BACKED is a truthy token (1/true/yes/on,
          case-insensitive); False for unset, blank, or any other value

    Returns:
        bool — True if the cloud (Cloud SQL) database path should be used
    """
    return os.environ.get( "LUPIN_CLOUD_BACKED", "" ).strip().lower() in _CLOUD_BACKED_TRUTHY


# Fires at most once per process — this module builds its URL at import time and callers may
# rebuild it, and an alarm repeated on every call is an alarm people filter out.
_ANNOUNCED_EMPTY_DB_PASSWORD = False


def announce_empty_db_password_once( venue: str ) -> bool:
    """
    Say out loud that this process has NO database password, and name the seam.

    🔴 WHY THIS EXISTS (row 2ab9961b, Rick's P1, 2026-09-04). `DB_PASSWORD` is read HERE and
    supplied NOWHERE for a host-side process: the untracked repo-root `.env` carries
    `POSTGRES_PASSWORD`, and `docker-compose.yml` is the ONLY thing that translates one name
    into the other — for CONTAINERS. A value produced in one place, read in another under a
    different name, with nothing saying so.

    The empty default below is DELIBERATE and stays (an unset password must not break every
    importer). But silent-and-empty is what let this run for months: the failure surfaced far
    downstream as a refused connection inside a gist cache read, which a caller's broad
    `except` then dressed up as a five-word summary. Measured across 2,479 listener logs, 158
    failures in seven days, every one of them this.

    ⚠️ WARNS, NEVER RAISES — the module docstring's invariant is load-bearing and this must not
    weaken it. Nearly everything imports this module at startup; raising here would take the
    fleet down to report a misconfiguration.

    Requires:
        - venue is a short label naming the resolved environment (e.g. "development")
    Ensures:
        - prints a named, actionable warning the FIRST time it is called in this process
        - returns True iff it printed, False on every subsequent call
        - never raises
    """
    global _ANNOUNCED_EMPTY_DB_PASSWORD
    if _ANNOUNCED_EMPTY_DB_PASSWORD: return False

    _ANNOUNCED_EMPTY_DB_PASSWORD = True
    print(
        f"[DB] WARNING: DB_PASSWORD is unset or empty for venue '{venue}' — every database "
        f"call from this process will be refused with 'fe_sendauth: no password supplied'.\n"
        f"[DB]          This is USUALLY A NAME MISMATCH, not a missing secret: the repo-root "
        f".env supplies POSTGRES_PASSWORD, docker-compose maps it to DB_PASSWORD for "
        f"CONTAINERS, and nothing does that for a host-side process.\n"
        f"[DB]          If this is a host-side process, export DB_PASSWORD yourself. "
        f"See row 2ab9961b."
    )
    return True


def get_database_url() -> str:
    """
    Build PostgreSQL connection string based on environment.

    Requires:
        - LUPIN_ENV environment variable (dev/testing/production)
        - Cloud-backed (LUPIN_CLOUD_BACKED truthy — see is_cloud_backed):
          CLOUD_SQL_CONNECTION_NAME, DB_USER, DB_PASSWORD, DB_NAME
        - Otherwise (local dev/testing): localhost PostgreSQL-in-Docker

    Ensures:
        - Returns valid PostgreSQL connection string
        - Uses appropriate connection method for environment

    Returns:
        PostgreSQL connection URL string

    Raises:
        ValueError: If required environment variables missing
    """
    # A blank DB_PASSWORD is filled from the untracked .env before any branch reads it
    # (row baac2474). An exported value always wins, so a container — which is given the
    # variable at create time — reaches that helper's early return and is unaffected.
    # This exists for the third consumer commit 765e7145 missed: host-run processes,
    # which are neither containers nor pytest. See cosa/utils/dotenv_password.py.
    seed_db_password_from_dotenv()

    env = os.environ.get( "LUPIN_ENV", "development" ).lower()

    if is_cloud_backed():
        # Cloud SQL via Unix socket (any cloud-backed env: GCP test or production)
        instance = os.environ.get( "CLOUD_SQL_CONNECTION_NAME" )
        user = os.environ.get( "DB_USER", "lupin_app" )
        password = os.environ.get( "DB_PASSWORD" )
        # Default DB name follows the env when DB_NAME is not explicitly set.
        default_db = "lupin_db_test" if env == "testing" else "lupin_db_prod"
        database = os.environ.get( "DB_NAME", default_db )

        if not instance or not password:
            raise ValueError(
                "Cloud-backed environment requires CLOUD_SQL_CONNECTION_NAME and DB_PASSWORD"
            )

        # Unix socket connection for Cloud SQL
        return f"postgresql+psycopg2://{user}:{password}@/{database}?host=/cloudsql/{instance}"

    elif env == "testing":
        # Testing environment (PostgreSQL-in-Docker, separate database)
        # Uses same Docker container but different database name
        user = os.environ.get( "DB_USER", "lupin_dev" )
        # No baked-in password default (row baac2474). This module builds the URL at
        # IMPORT time (see the create_engine call below), so an unset DB_PASSWORD must
        # NOT raise here — it would break every importer. Containers get the value from
        # docker-compose.yml, which reads the untracked .env; a host shell must export
        # it. Env resolves at container CREATE: `up -d --force-recreate`, not a restart.
        password = os.environ.get( "DB_PASSWORD", "" )
        if not password: announce_empty_db_password_once( "testing" )
        host = os.environ.get( "DB_HOST", "localhost" )
        port = os.environ.get( "DB_PORT", "5432" )
        database = os.environ.get( "DB_NAME", "lupin_db_test" )  # Separate test database

        return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"

    else:  # development (default)
        # Local PostgreSQL-in-Docker
        user = os.environ.get( "DB_USER", "lupin_dev" )
        # No baked-in password default (row baac2474). This module builds the URL at
        # IMPORT time (see the create_engine call below), so an unset DB_PASSWORD must
        # NOT raise here — it would break every importer. Containers get the value from
        # docker-compose.yml, which reads the untracked .env; a host shell must export
        # it. Env resolves at container CREATE: `up -d --force-recreate`, not a restart.
        password = os.environ.get( "DB_PASSWORD", "" )
        if not password: announce_empty_db_password_once( "development" )
        host = os.environ.get( "DB_HOST", "localhost" )
        port = os.environ.get( "DB_PORT", "5432" )
        database = os.environ.get( "DB_NAME", "lupin_db_dev" )

        return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"


def get_pool_config() -> dict:
    """
    Get connection pool configuration based on environment.

    Ensures:
        - Cloud-backed (Cloud SQL): Moderate pooling for Cloud SQL limits
        - Development: Higher pooling for local Docker (no limits)
        - Local testing: No pooling (NullPool for test isolation)

    Returns:
        Dictionary of pool configuration parameters
    """
    env = os.environ.get( "LUPIN_ENV", "development" ).lower()

    if is_cloud_backed():
        # Conservative pooling for Cloud SQL (db-f1-micro supports 25 connections)
        return {
            "pool_size": 5,           # 5 persistent connections
            "max_overflow": 10,       # Up to 15 total connections
            "pool_pre_ping": True,    # Verify connections before use (Cloud SQL can drop idle)
            "pool_recycle": 3600,     # Recycle connections hourly (prevent stale Cloud SQL connections)
            "pool_timeout": 30,       # Wait 30s for available connection
            "echo": False,            # No SQL logging in production
            "connect_args": {
                "connect_timeout": 10,  # 10s connection timeout
                "options": "-c timezone=utc"  # Force UTC timezone
            }
        }

    elif env == "testing":
        # No pooling for tests (ensures test isolation)
        return {
            "poolclass": NullPool,    # Disable connection pooling
            "echo": False,            # No SQL logging during tests
            "connect_args": {
                "options": "-c timezone=utc"
            }
        }

    else:  # development
        # Higher pooling for local Docker (no connection limits)
        return {
            "pool_size": 10,          # 10 persistent connections
            "max_overflow": 20,       # Up to 30 total connections
            "pool_pre_ping": True,    # Verify connections before use
            "pool_recycle": 7200,     # Recycle after 2 hours
            "pool_timeout": 30,       # Wait 30s for available connection
            "echo": False,            # Set True for SQL debugging
            "connect_args": {
                "connect_timeout": 10,
                "options": "-c timezone=utc"
            }
        }


# Create SQLAlchemy engine with connection pooling
engine = create_engine(
    get_database_url(),
    **get_pool_config()
)

# Session factory (not thread-safe, use get_db() context manager instead)
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# Thread-safe scoped session for web applications
ScopedSession = scoped_session( SessionLocal )


def swap_database( new_env: str ) -> str:
    """
    Hot-swap the database connection to a different environment.

    Requires:
        - new_env is one of: "development", "testing", "production"

    Ensures:
        - LUPIN_ENV is updated
        - engine, SessionLocal, ScopedSession are recreated
        - Old engine is disposed (connections released)
        - Returns the new database URL (password masked)

    Raises:
        - sqlalchemy.exc.OperationalError if new database is unreachable
    """
    global engine, SessionLocal, ScopedSession

    os.environ[ "LUPIN_ENV" ] = new_env

    # Dispose old engine (releases connection pool)
    engine.dispose()

    # Recreate with new settings
    engine        = create_engine( get_database_url(), **get_pool_config() )
    SessionLocal  = sessionmaker( autocommit=False, autoflush=False, bind=engine )
    ScopedSession = scoped_session( SessionLocal )

    # Verify connection works
    with engine.connect() as conn:
        conn.execute( text( "SELECT 1" ) )

    db_url = str( engine.url )
    masked = db_url.replace( str( engine.url.password or "" ), "***" )
    return masked


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """
    Context manager for database sessions with automatic lifecycle management.

    Ensures:
        - Session created from SessionLocal factory
        - Automatic commit on success
        - Automatic rollback on exception
        - Session always closed (prevents connection leaks)

    Yields:
        SQLAlchemy Session instance

    Example:
        with get_db() as session:
            user = session.query( User ).filter( User.email == email ).first()
            if user:
                user.last_login = datetime.now( timezone.utc )
            # Commits automatically if no exception

    Raises:
        Any exception from database operations (re-raised after rollback)
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def quick_smoke_test():
    """
    Quick smoke test for database connection and session management.

    Tests:
        - Database URL construction
        - Engine creation
        - Session factory
        - get_db() context manager
        - Connection to PostgreSQL
    """
    import cosa.utils.util as cu

    cu.print_banner( "Database Session Management Smoke Test", prepend_nl=True )

    try:
        # Test 1: Database URL
        print( "Testing database URL construction..." )
        db_url = get_database_url()
        env = os.environ.get( "LUPIN_ENV", "development" )
        print( f"✓ Database URL constructed for environment: {env}" )
        # Don't print full URL (contains password)

        # Test 2: Engine creation
        print( "Testing engine creation..." )
        assert engine is not None
        print( f"✓ Engine created: {engine.driver}" )

        # Test 3: Session factory
        print( "Testing session factory..." )
        assert SessionLocal is not None
        print( "✓ SessionLocal factory created" )

        # Test 4: get_db() context manager
        print( "Testing get_db() context manager..." )
        with get_db() as session:
            assert session is not None
            print( "✓ Session created via context manager" )

        # Test 5: Database connection
        print( "Testing actual database connection..." )
        with get_db() as session:
            # Execute simple query to verify connection
            result = session.execute( text( "SELECT 1 as test" ) )
            row = result.fetchone()
            assert row[0] == 1
            print( f"✓ Connected to PostgreSQL successfully" )

        print( "\n✓ Smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
