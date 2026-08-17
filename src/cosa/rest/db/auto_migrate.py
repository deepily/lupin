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

# How long to keep trying to reach the database before giving up at boot.
#
# WHY THIS EXISTS (2026-08-17, lupin-host-test): the app connected exactly ONCE
# and any failure was fatal — `Application startup failed. Exiting.` On the
# cloud-gpu topology the database is reached through a Cloud SQL Auth Proxy
# sidecar, so "not ready yet" is a NORMAL transient state at boot, not an error.
# The compose file gates the app on `condition: service_healthy`, but Docker's
# RESTART POLICY ignores depends_on entirely — on a VM reboot or resume both
# containers come back independently, and the app can easily win the race.
#
# A bounded wait converts a permanent boot failure into a short delay. It does
# NOT paper over a real outage: when the budget is spent the original error is
# re-raised unchanged, so fail-loud still holds — it just stops treating a
# five-second startup skew as a reason to take the server down for good.
DB_WAIT_TIMEOUT_SECONDS  = 60.0
DB_WAIT_INITIAL_BACKOFF  = 1.0
DB_WAIT_MAX_BACKOFF      = 8.0


def next_backoff( current, maximum=DB_WAIT_MAX_BACKOFF ):
    """
    Double a retry delay, capped.

    Requires:
        - current is a positive number; maximum is a positive number

    Ensures:
        - returns min( current * 2, maximum )
        - never returns more than maximum, so a long budget cannot turn into
          one enormous sleep that blows past the deadline in a single step
    """
    return min( current * 2, maximum )


def wait_for_database( probe, timeout=DB_WAIT_TIMEOUT_SECONDS,
                       initial_backoff=DB_WAIT_INITIAL_BACKOFF,
                       sleep=None, now=None, on_retry=None ):
    """
    Call ``probe`` until it succeeds or the timeout is spent; re-raise the last error.

    ``probe`` is any zero-argument callable that raises on an unreachable
    database. Injecting it — along with ``sleep`` and ``now`` — is what keeps
    this testable without a database, a clock, or a real wait.

    Requires:
        - probe is callable and raises on failure
        - timeout and initial_backoff are non-negative numbers

    Ensures:
        - returns probe's return value on the first success
        - a probe that succeeds immediately costs ZERO sleeps — the common case
          pays nothing for this guard
        - retries with exponential backoff until the deadline passes
        - re-raises the LAST exception unchanged when the budget is spent, so
          the operator sees the real driver error and not a wrapper
        - never sleeps past the deadline
    """
    import time as _time

    sleep = sleep or _time.sleep
    now   = now   or _time.monotonic

    deadline = now() + timeout
    backoff  = initial_backoff
    attempt  = 0

    while True:
        attempt += 1
        try:
            return probe()
        except Exception as error:
            remaining = deadline - now()
            if remaining <= 0:
                raise
            if on_retry: on_retry( attempt, error, min( backoff, remaining ) )
            sleep( min( backoff, remaining ) )
            backoff = next_backoff( backoff )


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


def _read_current_revision( url ):
    """
    Best-effort read of the DB's currently-stamped alembic revision.

    Requires:
        - url is a concrete SQLAlchemy URL

    Ensures:
        - returns the stamped revision string, or None when there is none
          (fresh DB) or it could not be read
        - NEVER raises. This is observability, not a gate: a migration must not
          fail because the thing that reports on it could not read a revision

    Args:
        url: concrete SQLAlchemy URL

    Returns:
        str | None
    """
    try:
        from alembic.runtime.migration import MigrationContext
        engine = create_engine( url )
        try:
            with engine.connect() as conn:
                heads = MigrationContext.configure( conn ).get_current_heads()
        finally:
            engine.dispose()
        return ",".join( heads ) if heads else None
    except Exception:
        return None


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
        dict — { "before": str|None, "after": str|None, "applied": bool,
                 "bootstrapped": bool }. `applied` is True ONLY when the
        revision actually MOVED, which is what lets a caller distinguish a
        deploy from a no-op. Every existing caller ignores this and is
        unaffected; it is added because "did this run change the database?"
        was previously unanswerable from the outside (row 0aae1a28).

    Raises:
        RuntimeError: app tables exist but the DB was never alembic-stamped
        Exception: any error from Alembic / the DBAPI (propagated unchanged)
    """
    url    = resolve_database_url( database_url )
    config = build_alembic_config( database_url=url )

    # The database may not be reachable the instant this process boots — behind a
    # Cloud SQL Auth Proxy sidecar that is still coming up, "not yet" is normal.
    # Wait a bounded amount rather than exiting; a spent budget re-raises the
    # driver's own error, so a genuine outage still fails loud.
    def _report( attempt, error, delay ):
        print( f"[auto-migrate] database not reachable (attempt {attempt}): "
               f"{type( error ).__name__} — retrying in {delay:.1f}s" )

    has_version_table, has_app_tables = wait_for_database(
        lambda: _inspect_db_state( url ), on_retry=_report
    )
    before = _read_current_revision( url )

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
        # A bootstrap is NOT an "applied migration" — nothing was upgraded, the
        # schema was built from the models and stamped. Reporting it as applied
        # would make a first boot indistinguishable from a live schema change,
        # which is the exact distinction this return value exists to draw.
        return { "before": before, "after": _read_current_revision( url ),
                 "applied": False, "bootstrapped": True }

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

    # Read AFTER, and compare. The revision moving is the only honest evidence
    # that this call was a deploy rather than a no-op — `command.upgrade` returns
    # nothing and is silent either way, which is why nobody could see it happen.
    after = _read_current_revision( url )
    return { "before": before, "after": after,
             "applied": ( after is not None and after != before ), "bootstrapped": False }
