"""
Programmatic Alembic auto-migration on application startup.

Runs the equivalent of ``alembic upgrade head`` from WITHIN the process so a
freshly-booted container always serves against a schema that matches the ORM
models — the reproducible, hands-off alternative to a human running SQL/ALTER
by hand.

Why programmatic (not the ``alembic`` CLI)?
    The deployment image bind-mounts only ``./src`` into the container, so
    ``alembic.ini`` (which lives at the repo ROOT) is NOT present at any
    container path. Building the Alembic ``Config`` in code removes that
    dependency entirely: ``script_location`` is computed from the project root,
    and the database URL is resolved by the migrations' own ``env.py`` (which
    reuses the app's ``cosa.rest.db.database.get_database_url`` builder — the
    single URL-construction source of truth across dev, testing, and the cloud
    Cloud-SQL socket).

DB-state handling (so fresh provisioning is automatic, never a hand-step):
    1. ``alembic_version`` table PRESENT  → plain ``upgrade head`` (idempotent;
       a DB already at head is a no-op). Individual migrations are written to be
       idempotent where a baseline ``schema.sql`` may have pre-created columns.
    2. table ABSENT + NO app tables (truly empty DB) → ``Base.metadata.create_all``
       then ``stamp head``. Schema == models exactly; stamped at head so future
       deltas apply cleanly.
    3. table ABSENT + app tables EXIST (legacy ``schema.sql`` DB never stamped) →
       FAIL LOUD with an explicit one-time reconcile instruction. Replaying the
       whole chain over an existing schema would raise ``DuplicateTable``; the
       correct recovery (``alembic stamp <baseline>`` once) is an operator
       decision, not something to guess silently.

Design contract:
    - Idempotent  : re-running against a DB already at head is a no-op.
    - Fail-loud   : any migration error PROPAGATES. The caller MUST let it abort
                    boot — never serve a half-migrated database.
    - Once-per-process: called exactly once from ``lupin_app.main`` lifespan.
"""

import os

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

import cosa.utils.util as cu


# Sentinel table proving the schema was bootstrapped (any env). If app tables
# exist but ``alembic_version`` does not, the DB is an unstamped legacy schema.
_SENTINEL_APP_TABLE = "users"


def resolve_database_url( database_url=None ):
    """
    Resolve the effective database URL for inspection + migration.

    Resolution order (first hit wins) — mirrors src/migrations/env.py, and
    delegates URL CONSTRUCTION to the app's single builder so no connection
    logic is duplicated here:
        1. explicit ``database_url`` argument (e.g. a throwaway test DB)
        2. ``DATABASE_URL`` env var (explicit override)
        3. ``cosa.rest.db.database.get_database_url()`` (the app builder)

    Args:
        database_url: optional explicit URL

    Returns:
        str — a concrete SQLAlchemy URL
    """
    if database_url:
        return database_url
    env_url = os.environ.get( "DATABASE_URL" )
    if env_url:
        return env_url
    from cosa.rest.db.database import get_database_url
    return get_database_url()


def build_alembic_config( database_url=None ):
    """
    Build an Alembic ``Config`` programmatically (no alembic.ini dependency).

    Requires:
        - ``cu.get_project_root()`` resolves the project root (LUPIN_ROOT)
        - ``<project_root>/src/migrations`` contains env.py + versions/

    Ensures:
        - returns an ``alembic.config.Config`` whose ``script_location`` points
          at ``<project_root>/src/migrations``
        - when ``database_url`` is provided, it is stashed on
          ``config.attributes["injected_db_url"]`` for env.py to consume
          (interpolation-free); when None, env.py resolves the URL itself

    Args:
        database_url: optional explicit URL for env.py to use

    Returns:
        alembic.config.Config ready for ``command.*``
    """
    project_root    = cu.get_project_root()
    script_location = os.path.join( project_root, "src", "migrations" )

    config = Config()
    config.set_main_option( "script_location", script_location )
    if database_url is not None:
        config.attributes[ "injected_db_url" ] = database_url
    return config


def _inspect_db_state( url ):
    """
    Probe whether the DB has an ``alembic_version`` table and any app tables.

    Args:
        url: concrete SQLAlchemy URL

    Returns:
        tuple( has_version_table: bool, has_app_tables: bool )
    """
    engine = create_engine( url )
    try:
        inspector  = inspect( engine )
        tables     = set( inspector.get_table_names() )
    finally:
        engine.dispose()
    return ( "alembic_version" in tables, _SENTINEL_APP_TABLE in tables )


def run_migrations_to_head( database_url=None, debug=False ):
    """
    Bring the target database up to the latest migration head (auto-bootstrapping
    a truly-empty DB), idempotently and fail-loud.

    Requires:
        - the target database is reachable with the resolved URL
        - the migration scripts under src/migrations/versions/ form a single,
          consistent head

    Ensures:
        - on return, the database schema is at the migration head (is_protected
          column present, etc.) and stamped accordingly
        - idempotent: a no-op when the database is already at head
        - empty DB: created from Base.metadata + stamped head
        - FAIL-LOUD: re-raises any Alembic/DBAPI error so the caller aborts boot;
          a legacy-unstamped schema raises RuntimeError with reconcile guidance

    Args:
        database_url: optional explicit URL (None → DATABASE_URL or app builder)
        debug: when True, print before/after one-liners

    Returns:
        None

    Raises:
        RuntimeError: app tables exist but the DB was never alembic-stamped
        Exception: any error from Alembic / the DBAPI (propagated unchanged)
    """
    url    = resolve_database_url( database_url )
    config = build_alembic_config( database_url=url )

    has_version_table, has_app_tables = _inspect_db_state( url )

    if not has_version_table and not has_app_tables:
        # Truly fresh, empty database → build the baseline from the models and
        # stamp it at head. Reproducible bootstrap, no hand-SQL.
        if debug: print( "[auto-migrate] Empty DB — create_all from models + stamp head..." )
        from cosa.rest.postgres_models import Base
        engine = create_engine( url )
        try:
            # pgvector (v0.2.0 vector store): the `vector` type must exist BEFORE
            # create_all builds any Vector column / HNSW index. Idempotent — a no-op
            # when the extension is already present. Requires the base image to
            # bundle pgvector (docker-compose: pgvector/pgvector:pg16; Cloud-SQL native).
            with engine.begin() as conn:
                conn.execute( text( "CREATE EXTENSION IF NOT EXISTS vector" ) )
            Base.metadata.create_all( engine )
        finally:
            engine.dispose()
        command.stamp( config, "head" )
        if debug: print( "[auto-migrate] Fresh DB bootstrapped and stamped at head." )
        return

    if not has_version_table and has_app_tables:
        # Legacy schema.sql DB that was never alembic-stamped. Replaying the
        # chain over it would raise DuplicateTable — refuse, with the exact
        # one-time recovery (operator runs it once; never guessed here).
        raise RuntimeError(
            "Auto-migrate refused: database has application tables but no "
            "'alembic_version' table (legacy/unstamped schema). Reconcile ONCE "
            "with an explicit baseline stamp — e.g. 'alembic stamp <baseline_rev>' "
            "matching the bootstrapped schema — then restart so 'upgrade head' "
            "can apply the remaining deltas. Refusing to replay the full chain "
            "over an existing schema."
        )

    # Normal alembic-managed DB → apply any pending deltas (idempotent at head).
    if debug: print( "[auto-migrate] Running 'alembic upgrade head'..." )
    command.upgrade( config, "head" )
    if debug: print( "[auto-migrate] Database is at migration head." )
