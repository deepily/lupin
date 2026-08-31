"""
Shared fixtures for the Lane-B pgvector repository unit tests.

Runs against a REAL, DISPOSABLE Postgres+pgvector database so the ``<#>`` dot
search + HNSW indexes are exercised for real (MagicMock can't validate SQL). A
throwaway database is created for the whole test session, the 8 vector-store
tables are built on it, and it is dropped at teardown — zero shared-state risk.

Isolation per test: each test runs inside a connection-level transaction that is
ROLLED BACK afterwards (SQLAlchemy "join an external transaction" recipe), so the
tables are created once and every test sees a clean slate.

Honest skip predicate (design §7 / task): the whole module SKIPS when no
pgvector-enabled Postgres is reachable — local proof needs no gate (pgvector is
live), but CI environments without it skip rather than error. Override the target
with PGVECTOR_TEST_DATABASE_URL (a base URL WITHOUT the database name, e.g.
``postgresql+psycopg2://user:pw@host:5432/``).
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


def _base_url() -> str:
    """
    Build the base connection URL (WITHOUT a trailing database name).

    Ensures:
        - honors PGVECTOR_TEST_DATABASE_URL when set (must end with '/')
        - else builds from DB_USER/DB_PASSWORD/DB_HOST/DB_PORT with the
          documented local-Docker defaults (lupin_dev / $DB_PASSWORD)
    """
    override = os.environ.get( "PGVECTOR_TEST_DATABASE_URL" )
    if override:
        return override if override.endswith( "/" ) else override + "/"

    user = os.environ.get( "DB_USER", "lupin_dev" )
    pw   = os.environ.get( "DB_PASSWORD", "" )
    host = os.environ.get( "DB_HOST", "localhost" )
    port = os.environ.get( "DB_PORT", "5432" )
    return f"postgresql+psycopg2://{user}:{pw}@{host}:{port}/"


# Maintenance DB used only to CREATE/DROP the throwaway DB.
_MAINT_DB = os.environ.get( "PGVECTOR_TEST_MAINT_DB", "lupin_db_dev" )
_THROWAWAY_DB = f"lupin_lane_b_test_{os.getpid()}"


def _pgvector_reachable( base_url: str ) -> bool:
    """
    Probe whether a pgvector-enabled Postgres is reachable via the maintenance DB.

    Ensures:
        - returns True iff the maintenance DB connects AND the 'vector' extension
          is available (installed or installable); False on any failure
    """
    try:
        eng = create_engine( base_url + _MAINT_DB, isolation_level="AUTOCOMMIT" )
        with eng.connect() as conn:
            avail = conn.execute(
                text( "SELECT 1 FROM pg_available_extensions WHERE name = 'vector'" )
            ).first()
        eng.dispose()
        return avail is not None
    except Exception:
        return False


@pytest.fixture( scope="session" )
def pg_engine():
    """
    Session-scoped engine bound to a freshly-created disposable pgvector database.

    Ensures:
        - SKIPS the whole suite when no pgvector Postgres is reachable
        - creates the throwaway DB, installs the 'vector' extension, and builds
          the 8 vector-store tables (+ HNSW indexes) on it
        - drops the throwaway DB at session teardown
    """
    base_url = _base_url()
    if not _pgvector_reachable( base_url ):
        pytest.skip( "no pgvector-enabled Postgres reachable (set PGVECTOR_TEST_DATABASE_URL)" )

    # Create the throwaway DB (autocommit — CREATE DATABASE can't run in a txn).
    maint = create_engine( base_url + _MAINT_DB, isolation_level="AUTOCOMMIT" )
    with maint.connect() as conn:
        conn.execute( text( f"DROP DATABASE IF EXISTS {_THROWAWAY_DB} WITH (FORCE)" ) )
        conn.execute( text( f"CREATE DATABASE {_THROWAWAY_DB}" ) )
    maint.dispose()

    engine = create_engine( base_url + _THROWAWAY_DB )

    from cosa.rest.postgres_models import Base
    from cosa.rest.db.vector_store_models import VECTOR_STORE_MODELS

    with engine.begin() as conn:
        conn.execute( text( "CREATE EXTENSION IF NOT EXISTS vector" ) )
    for model in VECTOR_STORE_MODELS:
        Base.metadata.tables[ model.__tablename__ ].create( bind=engine, checkfirst=True )

    yield engine

    engine.dispose()
    maint = create_engine( base_url + _MAINT_DB, isolation_level="AUTOCOMMIT" )
    with maint.connect() as conn:
        conn.execute( text( f"DROP DATABASE IF EXISTS {_THROWAWAY_DB} WITH (FORCE)" ) )
    maint.dispose()


@pytest.fixture()
def db_session( pg_engine ):
    """
    Function-scoped transactional session — rolled back after each test.

    Ensures:
        - yields a Session bound to a connection-level transaction
        - all writes are rolled back on teardown (clean slate per test)
    """
    connection  = pg_engine.connect()
    transaction = connection.begin()
    session     = Session( bind=connection )
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
