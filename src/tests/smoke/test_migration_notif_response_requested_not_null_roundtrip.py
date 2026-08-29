"""
DB-backed round-trip proof for migration f2a3b4c5d6e7 (bug 11cda843 — tighten
notifications.response_requested to NOT NULL). This EXECUTES the migration's
upgrade()/downgrade() DDL against a live Postgres, so it is the empirical
complement to the DB-free structural/exec guards in
``src/tests/unit/test_migration_notif_response_requested_not_null.py`` (SQLite
cannot ``ALTER COLUMN ... SET NOT NULL``, so the real constraint flip can only
be proven on Postgres).

What it proves:
  1. empty DB → ``alembic upgrade head`` leaves notifications.response_requested
     NOT NULL (the baseline writes it NULLABLE; this migration tightens it) —
     i.e. the pure upgrade-head schema now matches the ORM intent.
  2. ``downgrade -1`` relaxes the column back to NULLABLE and returns the chain
     to the prior head e1f2a3b4c5d6.
  3. re-``upgrade head`` re-tightens idempotently.

SAFETY / venue: :7999-eligible (AI-discretionary) — creates and DROPS its OWN
uniquely-named throwaway database on the dev Postgres server, mutates NO
persistent state outliving the test, runs in seconds, needs no server monopoly,
and SKIPS (never fails) when Postgres is unreachable.
"""
import os

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError

from alembic import command

from cosa.rest.db import database as db_module
from cosa.rest.db.auto_migrate import build_alembic_config


# The revision UNDER TEST — the one that tightens notifications.response_requested
# to NOT NULL — and the revision immediately below it.
#
# Renamed from _HEAD_REVISION 2026-08-26. It was named "head" and the test
# upgraded to the literal "head", which was the same thing on the day it was
# written and has not been since: migrations landed after it (c1a7f0e2b9d4,
# d47487369407, ...) and head is now 3da5c0d1eee6, so the test failed with
# `assert '3da5c0d1eee6' == 'f2a3b4c5d6e7'` — nothing wrong, just a moving
# target. This test is about ONE migration's up/down behaviour, so it now
# upgrades to that revision by name and every future migration leaves it alone.
_TARGET_REVISION = "f2a3b4c5d6e7"
_PRIOR_REVISION  = "e1f2a3b4c5d6"

# Unique throwaway DB name (pid-scoped so parallel runs never collide).
_THROWAWAY_DB = f"notif_nn_rt_{os.getpid()}"


def _server_url():
    """
    Borrow a credential-correct Postgres server URL via the suite's canonical
    test-DB path. We use only the host/port/credentials — the round-trip itself
    runs against a separate uniquely-named THROWAWAY database, never
    lupin_db_test. Returns the URL OBJECT (carries the REAL password); callers
    must NOT ``str()`` it (that masks the password as '***').
    """
    db_module.swap_database( "testing" )
    return db_module.engine.url


def _maintenance_engine( server_url ):
    """AUTOCOMMIT engine on the resolved server — used to CREATE/DROP the throwaway."""
    return create_engine( server_url, isolation_level="AUTOCOMMIT" )


@pytest.fixture( scope="module" )
def throwaway_db_url():
    """
    Create a uniquely-named empty throwaway DB on the dev Postgres server, yield
    its URL, and DROP it on teardown. SKIP the whole module if Postgres is
    unreachable (keeps DB-free CI green).
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


def _current_rev( url ):
    eng = create_engine( url )
    try:
        with eng.connect() as conn:
            return conn.execute( text( "SELECT version_num FROM alembic_version" ) ).scalar()
    finally:
        eng.dispose()


def _response_requested_nullable( url ):
    """Return the live `nullable` flag of notifications.response_requested."""
    eng = create_engine( url )
    try:
        col = next(
            c for c in inspect( eng ).get_columns( "notifications" )
            if c[ "name" ] == "response_requested"
        )
        return col[ "nullable" ]
    finally:
        eng.dispose()


def test_response_requested_not_null_roundtrip( throwaway_db_url ):
    """
    Empty DB → upgrade to the target revision → response_requested is NOT NULL;
    downgrade -1 → NULLABLE again; re-upgrade → re-tightened idempotently.

    Upgrades to _TARGET_REVISION by name rather than to "head" (changed
    2026-08-26) — see the comment on that constant. Every migration added after
    it is irrelevant to this migration's own up/down contract.
    """
    config = build_alembic_config( database_url=throwaway_db_url )

    # ── 1) upgrade to the target on an empty DB (pure migration path, NO create_all) ──
    command.upgrade( config, _TARGET_REVISION )
    assert _current_rev( throwaway_db_url ) == _TARGET_REVISION
    assert _response_requested_nullable( throwaway_db_url ) is False, (
        "after upgrade, notifications.response_requested must be NOT NULL"
    )

    # ── 2) downgrade -1 → prior revision, column relaxed back to NULLABLE ──────
    command.downgrade( config, "-1" )
    assert _current_rev( throwaway_db_url ) == _PRIOR_REVISION
    assert _response_requested_nullable( throwaway_db_url ) is True, (
        "after downgrade, notifications.response_requested must be NULLABLE again"
    )

    # ── 3) re-upgrade → idempotent re-tighten ─────────────────────────────────
    command.upgrade( config, _TARGET_REVISION )
    assert _current_rev( throwaway_db_url ) == _TARGET_REVISION
    assert _response_requested_nullable( throwaway_db_url ) is False
