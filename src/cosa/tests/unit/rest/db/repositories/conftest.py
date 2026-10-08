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

import tests.helpers.template_database as td


def _server_url() -> str:
    """
    Build the URL of the maintenance database the throwaway database is made on.

    Ensures:
        - honors PGVECTOR_TEST_DATABASE_URL when set (a base URL ending in '/', no database name)
        - else uses the clone helper's login and server, on the "postgres" database
    """
    override = os.environ.get( "PGVECTOR_TEST_DATABASE_URL" )
    if override: return ( override if override.endswith( "/" ) else override + "/" ) + "postgres"
    return td.clone_server_url()


_THROWAWAY_DB = f"lupin_lane_b_test_{os.getpid()}"


def _server_reachable( server_url: str ) -> bool:
    """
    Probe whether the server accepts the login and can give the database a vector column.

    Ensures:
        - returns True iff the maintenance database connects and the extension is usable; False on any failure
    """
    try:
        eng = create_engine( server_url )
        with eng.connect() as conn:
            # A template clone brings the extension; a plain database needs it installable.
            if td.uses_template(): conn.execute( text( "SELECT 1" ) )
            else: assert conn.execute( text( "SELECT 1 FROM pg_available_extensions WHERE name = 'vector'" ) ).first() is not None
        eng.dispose()
        return True
    except Exception:
        return False


@pytest.fixture( scope="session" )
def pg_engine():
    """
    Session-scoped engine bound to a freshly-created disposable pgvector database.

    Ensures:
        - SKIPS the whole suite when no Postgres server is reachable
        - makes the throwaway database through the clone helper, so the vector extension comes with it
        - builds the 8 vector-store tables (+ HNSW indexes) on it
        - drops the throwaway DB at session teardown, and also when the build fails
    """
    server_url = _server_url()
    if not _server_reachable( server_url ):
        pytest.skip( "no Postgres reachable (set PGVECTOR_TEST_DATABASE_URL)" )

    td.drop_database( server_url, _THROWAWAY_DB )
    url = td.create_from_template( server_url, _THROWAWAY_DB )
    try:
        engine = create_engine( url )

        from cosa.rest.postgres_models import Base
        from cosa.rest.db.vector_store_models import VECTOR_STORE_MODELS

        # Already there in a template clone; a plain database made by a superuser needs it.
        with engine.begin() as conn:
            conn.execute( text( "CREATE EXTENSION IF NOT EXISTS vector" ) )
        for model in VECTOR_STORE_MODELS:
            Base.metadata.tables[ model.__tablename__ ].create( bind=engine, checkfirst=True )

        yield engine
        engine.dispose()
    finally:
        td.drop_database( server_url, _THROWAWAY_DB )


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
