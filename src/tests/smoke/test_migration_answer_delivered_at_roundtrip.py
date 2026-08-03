"""
A-V3 (late-answer handback §4.1 / §5) — DB-backed round-trip proof for migration
3da5c0d1eee6 (add notifications.answer_delivered_at + the partial owed index).
Store row `7bb0a7df` (P1).

This EXECUTES the migration's upgrade()/downgrade() DDL against a live Postgres,
so it is the empirical complement to the DB-free model/structural guards in
``src/cosa/tests/unit/rest/test_postgres_models.py`` (A-V2/A-V4/A-V5). The two
things that can ONLY be proven on a real Postgres:

  1. ``CREATE INDEX CONCURRENTLY`` inside ``op.get_context().autocommit_block()``
     actually SUCCEEDS and leaves the index ``indisvalid`` (a CONCURRENTLY build
     that races or aborts leaves an INVALID index — SQLite/metadata cannot model
     this at all). This is the load-bearing assertion: A-V2 proves the ORM
     DECLARES the index; only this proves the migration BUILDS a valid one.
  2. the partial index's live predicate is character-identical to the owed
     predicate (the §3 design-level invariant — the ``responded_at IS NOT NULL``
     middle term is what stops a machine default being served as an answer).

What it proves:
  1. empty DB → ``alembic upgrade head`` reaches 3da5c0d1eee6; notifications
     gains ``answer_delivered_at`` (TIMESTAMPTZ, NULLable) and
     ``idx_notifications_answer_owed`` exists AND is ``indisvalid``, over
     (sender_persona, responded_at) with the owed predicate.
  2. ``downgrade -1`` drops BOTH cleanly and returns the chain to the prior head
     38e025169a73 (guards the symmetric concurrent-drop downgrade path).
  3. re-``upgrade head`` re-adds idempotently (the guarded add_column / create_index
     re-run path the auto-migrate startup hits on an already-migrated DB).

Venue: :7999-eligible (AI-discretionary). Creates and DROPS its OWN uniquely-named
throwaway database on the dev Postgres server, mutates NO persistent state
outliving the test, runs in seconds, needs no server monopoly, and SKIPS (never
fails) when Postgres is unreachable. This SUPERSEDES the plan's original ":8000
scheduled" framing for A-V3: the live :8000 DB cannot be downgraded mid-service,
so the up→down→up cycle the migration's symmetry needs can only be proven on a
throwaway DB. Venue call is the Tester's (María, 2026-08-01).

First run receipts (Rachel 🕊️, 2026-08-01): upgrade head → indisvalid=t
indisready=t, predicate character-identical; downgrade -1 → col_left=0 idx_left=0,
chain back at 38e025169a73.
"""
import os

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError

from alembic import command

from cosa.rest.db import database as db_module
from cosa.rest.db.auto_migrate import build_alembic_config


_HEAD_REVISION = "3da5c0d1eee6"
_PRIOR_HEAD    = "38e025169a73"

_COLUMN_NAME = "answer_delivered_at"
_INDEX_NAME  = "idx_notifications_answer_owed"
# The owed predicate, as PostgreSQL renders it in pg_indexes.indexdef — the §3
# invariant, character-identical to the ORM Index and §4.4's repo query.
_EXPECTED_PREDICATE = "(response_requested AND (responded_at IS NOT NULL) AND (answer_delivered_at IS NULL))"

# Unique throwaway DB name (pid-scoped so parallel runs never collide).
_THROWAWAY_DB = f"answer_owed_rt_{os.getpid()}"


def _server_url():
    """
    Borrow a credential-correct Postgres server URL via the suite's canonical
    test-DB path. Only host/port/credentials are used — the round-trip runs
    against a separate uniquely-named THROWAWAY database, never lupin_db_test.
    Returns the URL OBJECT (carries the REAL password); callers must NOT str() it.
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


def _answer_delivered_at_column( url ):
    """Return the mapped column dict for notifications.answer_delivered_at, or None."""
    eng = create_engine( url )
    try:
        for c in inspect( eng ).get_columns( "notifications" ):
            if c[ "name" ] == _COLUMN_NAME:
                return c
        return None
    finally:
        eng.dispose()


def _owed_index_row( url ):
    """
    Return (indisvalid, indisready, indexdef) for idx_notifications_answer_owed,
    or None if the index does not exist. indisvalid is the load-bearing check:
    a CONCURRENTLY build that did not complete leaves it False.
    """
    eng = create_engine( url )
    try:
        with eng.connect() as conn:
            row = conn.execute( text(
                "SELECT i.indisvalid, i.indisready, pg_get_indexdef( i.indexrelid ) AS indexdef "
                "FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid "
                "WHERE c.relname = :name"
            ), { "name": _INDEX_NAME } ).first()
            return None if row is None else ( row[ 0 ], row[ 1 ], row[ 2 ] )
    finally:
        eng.dispose()


def test_answer_delivered_at_migration_roundtrip( throwaway_db_url ):
    """
    Empty DB → upgrade head → answer_delivered_at (TIMESTAMPTZ NULL) + a VALID
    partial owed index exist; downgrade -1 → both gone, prior head; re-upgrade
    head → idempotent re-add.
    """
    config = build_alembic_config( database_url=throwaway_db_url )

    # ── 1) upgrade head on an empty DB (pure migration path, NO create_all) ────
    command.upgrade( config, "head" )
    assert _current_rev( throwaway_db_url ) == _HEAD_REVISION

    col = _answer_delivered_at_column( throwaway_db_url )
    assert col is not None, "after upgrade head, notifications.answer_delivered_at must exist"
    assert col[ "nullable" ] is True, "answer_delivered_at must be NULLable"
    assert "TIMESTAMP" in str( col[ "type" ] ).upper(), f"must be a TIMESTAMPTZ, got {col['type']!r}"

    idx = _owed_index_row( throwaway_db_url )
    assert idx is not None, "after upgrade head, idx_notifications_answer_owed must exist"
    indisvalid, indisready, indexdef = idx
    # The load-bearing assertion: CONCURRENTLY left a VALID, READY index.
    assert indisvalid is True, "idx_notifications_answer_owed must be indisvalid (CONCURRENTLY completed)"
    assert indisready is True, "idx_notifications_answer_owed must be indisready"
    assert "sender_persona" in indexdef and "responded_at" in indexdef, indexdef
    assert _EXPECTED_PREDICATE in indexdef, (
        f"partial predicate must be the owed predicate, got: {indexdef}"
    )

    # ── 2) downgrade -1 → prior head, BOTH column and index dropped cleanly ─────
    command.downgrade( config, "-1" )
    assert _current_rev( throwaway_db_url ) == _PRIOR_HEAD
    assert _answer_delivered_at_column( throwaway_db_url ) is None, (
        "after downgrade, answer_delivered_at must be gone"
    )
    assert _owed_index_row( throwaway_db_url ) is None, (
        "after downgrade, idx_notifications_answer_owed must be gone"
    )

    # ── 3) re-upgrade head → idempotent re-add (the guarded re-run path) ────────
    command.upgrade( config, "head" )
    assert _current_rev( throwaway_db_url ) == _HEAD_REVISION
    assert _answer_delivered_at_column( throwaway_db_url ) is not None
    reidx = _owed_index_row( throwaway_db_url )
    assert reidx is not None and reidx[ 0 ] is True, "re-upgrade must rebuild a valid index"
