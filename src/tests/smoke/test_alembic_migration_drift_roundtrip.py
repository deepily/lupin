"""
DB-backed round-trip proof for migration e5f6a7b8c9d0 (migration<->ORM drift
fix). This EXECUTES the migration's upgrade()/downgrade() DDL against a live
Postgres, so it is the empirical complement to the DB-free structural guards in
``src/tests/unit/test_alembic_migration_drift.py``.

What it proves (the acid test for "the drift is closed"):
  1. empty DB → ``alembic upgrade head`` builds the four previously-missing
     tables (proxy_decisions / trust_states / prediction_log / server_lifecycle)
     AND the five previously-missing notifications columns (job_id /
     progress_group_id / abstract / response_options / is_hidden) — i.e. the
     pure ``upgrade head`` path no longer depends on the create_all mask.
  2. ``downgrade -1`` cleanly drops all four tables + five columns and returns
     the chain to the prior head d4e5f6a7b8c9.
  3. re-``upgrade head`` re-applies idempotently.

SAFETY / venue: this is :7999-eligible (AI-discretionary) — it creates and
DROPS its OWN uniquely-named throwaway database on the dev Postgres server, so
it mutates NO persistent state outliving the test, runs in seconds, and needs
no server monopoly. It SKIPS (never fails) when Postgres is unreachable, so the
DB-free unit run / plain CI is unaffected.
"""
import os

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError

from alembic import command

from cosa.rest.db import database as db_module
from cosa.rest.db.auto_migrate import build_alembic_config


_HEAD_REVISION  = "e5f6a7b8c9d0"
_PRIOR_HEAD     = "d4e5f6a7b8c9"
_DRIFT_TABLES   = [ "proxy_decisions", "trust_states", "prediction_log", "server_lifecycle" ]
_NOTIF_COLUMNS  = [ "job_id", "progress_group_id", "abstract", "response_options", "is_hidden" ]

# Unique throwaway DB name (pid-scoped so parallel runs never collide; no
# Math.random / wall-clock needed for uniqueness within a host).
_THROWAWAY_DB = f"krishna_drift_rt_{os.getpid()}"


def _server_url():
    """
    Resolve a credential-correct Postgres server URL via the suite's canonical
    test-DB path (swap_database('testing') → lupin_db_test). We only borrow the
    server's host/port/credentials from it — the round-trip itself runs against
    a separate uniquely-named THROWAWAY database, never lupin_db_test, so the
    test DB is untouched.

    Returns the SQLAlchemy URL OBJECT (which carries the REAL password); callers
    must NOT ``str()`` it — ``str(url)`` masks the password as '***', which would
    silently break authentication. Use the object directly or
    ``render_as_string( hide_password=False )``.
    """
    db_module.swap_database( "testing" )
    return db_module.engine.url


def _maintenance_engine( server_url ):
    """AUTOCOMMIT engine on the resolved server — used to CREATE/DROP the throwaway."""
    return create_engine( server_url, isolation_level="AUTOCOMMIT" )


@pytest.fixture( scope="module" )
def throwaway_db_url():
    """
    Create a uniquely-named empty throwaway DB on the dev Postgres server,
    yield its URL, and DROP it on teardown. SKIP the whole module if Postgres
    is unreachable (keeps DB-free CI green).
    """
    server_url = _server_url()
    try:
        eng = _maintenance_engine( server_url )
        with eng.connect() as conn:
            conn.execute( text( f'DROP DATABASE IF EXISTS "{_THROWAWAY_DB}"' ) )
            conn.execute( text( f'CREATE DATABASE "{_THROWAWAY_DB}"' ) )
        eng.dispose()
    except OperationalError as e:
        pytest.skip( f"Postgres unreachable — skipping DB-backed migration round-trip: {e}" )

    # .set() returns a new URL object carrying the real password; render WITH
    # the password (str()/default render would mask it as '***').
    throwaway_url = server_url.set( database=_THROWAWAY_DB )
    yield throwaway_url.render_as_string( hide_password=False )

    # Teardown — drop the throwaway DB (terminate any lingering backends first).
    eng = _maintenance_engine( server_url )
    with eng.connect() as conn:
        conn.execute( text(
            "SELECT pg_terminate_backend( pid ) FROM pg_stat_activity "
            "WHERE datname = :db AND pid <> pg_backend_pid()"
        ), { "db": _THROWAWAY_DB } )
        conn.execute( text( f'DROP DATABASE IF EXISTS "{_THROWAWAY_DB}"' ) )
    eng.dispose()


def _table_names( url ):
    eng = create_engine( url )
    try:
        return set( inspect( eng ).get_table_names() )
    finally:
        eng.dispose()


def _notif_columns( url ):
    eng = create_engine( url )
    try:
        return { c[ "name" ] for c in inspect( eng ).get_columns( "notifications" ) }
    finally:
        eng.dispose()


def _current_rev( url ):
    eng = create_engine( url )
    try:
        with eng.connect() as conn:
            return conn.execute( text( "SELECT version_num FROM alembic_version" ) ).scalar()
    finally:
        eng.dispose()


def test_full_drift_roundtrip( throwaway_db_url ):
    """
    Empty DB → upgrade head → assert parity; downgrade -1 → assert reverted;
    re-upgrade head → assert idempotent re-application.
    """
    config = build_alembic_config( database_url=throwaway_db_url )

    # ── 1) upgrade head on an empty DB (pure migration path, NO create_all) ────
    command.upgrade( config, "head" )

    assert _current_rev( throwaway_db_url ) == _HEAD_REVISION
    tables = _table_names( throwaway_db_url )
    for t in _DRIFT_TABLES:
        assert t in tables, f"upgrade head did not create table {t!r}"
    cols = _notif_columns( throwaway_db_url )
    for c in _NOTIF_COLUMNS:
        assert c in cols, f"upgrade head did not add notifications column {c!r}"

    # ── 2) downgrade -1 → back to the prior head, drift objects gone ───────────
    command.downgrade( config, "-1" )

    assert _current_rev( throwaway_db_url ) == _PRIOR_HEAD
    tables = _table_names( throwaway_db_url )
    for t in _DRIFT_TABLES:
        assert t not in tables, f"downgrade did not drop table {t!r}"
    cols = _notif_columns( throwaway_db_url )
    for c in _NOTIF_COLUMNS:
        assert c not in cols, f"downgrade did not drop notifications column {c!r}"

    # ── 3) re-upgrade head → idempotent re-application ─────────────────────────
    command.upgrade( config, "head" )

    assert _current_rev( throwaway_db_url ) == _HEAD_REVISION
    tables = _table_names( throwaway_db_url )
    for t in _DRIFT_TABLES:
        assert t in tables, f"re-upgrade head did not re-create table {t!r}"


def test_prediction_log_fk_targets_notifications( throwaway_db_url ):
    """prediction_log.notification_id is a CASCADE FK onto notifications.id."""
    config = build_alembic_config( database_url=throwaway_db_url )
    command.upgrade( config, "head" )

    eng = create_engine( throwaway_db_url )
    try:
        fks = inspect( eng ).get_foreign_keys( "prediction_log" )
    finally:
        eng.dispose()

    assert any(
        fk[ "referred_table" ] == "notifications"
        and fk[ "constrained_columns" ] == [ "notification_id" ]
        and fk[ "options" ].get( "ondelete" ) == "CASCADE"
        for fk in fks
    ), f"expected CASCADE FK prediction_log.notification_id -> notifications.id, got {fks!r}"
