"""
DB-backed up→down→up round-trip for migration 53835fd51f1a
(i3_kind_aware_blocked_chase, eab1d7da). EXECUTES the migration's
upgrade()/downgrade() DDL against a live Postgres — the empirical complement to
the DB-free guards in src/tests/unit/test_i3_kind_aware_chase_migration.py.

What it proves (AC6 + the CHECK truth table at the wire):
  1. upgrade → the blocked-chase CHECK clause carries the persona-containment
     term; a persona+null-chase blocked row is REJECTED, a user/item+null-chase
     row is ACCEPTED (the honest "blocked on Rick, no chase" state, now legal).
  2. downgrade → the clause reverts to the ORIGINAL global predicate AND the
     BEHAVIOR reverts: a user+null-chase row that upgrade accepted is now
     REJECTED again. That behavioral flip is the strongest proof downgrade is a
     REAL reversal, not a stub.
  3. re-upgrade → idempotent; the kind-aware behavior returns.

SAFETY / venue: :7999-eligible (AI-discretionary) — it creates and DROPS its OWN
uniquely-named throwaway database on the dev Postgres server, mutating NO
persistent state outliving the test, in seconds, no monopoly. SKIPS (never
fails) when Postgres is unreachable, so the DB-free unit run / plain CI is
unaffected. The zero-violator proof against the REAL populated table (AC5) is a
separate :8000 integration concern (plan §7) — this file never touches
lupin_db_test.
"""
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, OperationalError

from alembic import command

from cosa.rest.db import database as db_module
from cosa.rest.db.auto_migrate import build_alembic_config


_REVISION       = "53835fd51f1a"   # the migration under test (stable id, not "head")
_PRIOR_REVISION = "d0caad3ee21e"   # its down_revision
_CONSTRAINT     = "ck_task_items_blocked_requires_chase_ts"
_THROWAWAY_DB   = f"cheech_i3_rt_{os.getpid()}"


def _server_url():
    """Borrow the test server's host/port/credentials; the round-trip runs against
    a separate throwaway DB, never lupin_db_test."""
    db_module.swap_database( "testing" )
    return db_module.engine.url


def _maintenance_engine( server_url ):
    return create_engine( server_url, isolation_level="AUTOCOMMIT" )


@pytest.fixture( scope="module" )
def throwaway_db_url():
    server_url = _server_url()
    try:
        eng = _maintenance_engine( server_url )
        with eng.connect() as conn:
            conn.execute( text( f'DROP DATABASE IF EXISTS "{_THROWAWAY_DB}"' ) )
            conn.execute( text( f'CREATE DATABASE "{_THROWAWAY_DB}"' ) )
        eng.dispose()
    except OperationalError as e:
        pytest.skip( f"Postgres unreachable — skipping DB-backed i3 round-trip: {e}" )

    throwaway_url = server_url.set( database=_THROWAWAY_DB )
    yield throwaway_url.render_as_string( hide_password=False )

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


def _truncate_task_items( url ):
    """
    Empty task_items if it exists. The throwaway DB is module-scoped and shared,
    so accepted-row inserts from one test would otherwise persist — and a leftover
    user+null-chase row makes a DOWNGRADE to the stricter global CHECK fail
    (violating rows block a stricter constraint). Each test starts on a clean
    table so the ONLY thing under test is the CHECK, not another test's residue.
    """
    eng = create_engine( url )
    try:
        with eng.begin() as conn:
            exists = conn.execute( text(
                "SELECT to_regclass( 'task_items' ) IS NOT NULL"
            ) ).scalar()
            if exists:
                conn.execute( text( "TRUNCATE task_items CASCADE" ) )
    finally:
        eng.dispose()


def _check_clause( url ):
    """The live definition of the blocked-chase CHECK, straight from pg_catalog."""
    eng = create_engine( url )
    try:
        with eng.connect() as conn:
            return conn.execute( text(
                "SELECT pg_get_constraintdef( oid ) FROM pg_constraint WHERE conname = :n"
            ), { "n": _CONSTRAINT } ).scalar()
    finally:
        eng.dispose()


def _try_insert_blocked( url, blocked_by_json, chase ):
    """
    Attempt to INSERT one status='blocked' row with the given blocked_by + chase.
    Returns True if the DB ACCEPTED it, False if the CHECK REJECTED it (IntegrityError).
    Every NOT-NULL column is supplied explicitly so the ONLY thing under test is
    the blocked-chase CHECK.
    """
    eng = create_engine( url )
    try:
        with eng.begin() as conn:
            conn.execute( text(
                "INSERT INTO task_items "
                "( id, item_class, title, project, created_by, status, blocked_by, "
                "  next_chase_ts, gate_class, priority, urgency, created_ts, updated_ts ) "
                "VALUES ( gen_random_uuid(), 'task', 't', 'lupin', 'me', 'blocked', "
                "         CAST( :bb AS jsonb ), :chase, 'none', 'P2', 'normal', now(), now() )"
            ), { "bb": blocked_by_json, "chase": chase } )
        return True
    except IntegrityError:
        return False
    finally:
        eng.dispose()


_PERSONA = '[{"kind": "persona", "id": "sam"}]'
_USER    = '[{"kind": "user", "id": "rick"}]'
_ITEM    = '[{"kind": "item", "id": "X"}]'
_CHASE   = "2026-07-22T09:00:00-04:00"


def test_upgrade_installs_kind_aware_check_and_truth_table( throwaway_db_url ):
    config = build_alembic_config( database_url=throwaway_db_url )
    command.upgrade( config, _REVISION )
    assert _current_rev( throwaway_db_url ) == _REVISION
    _truncate_task_items( throwaway_db_url )

    clause = _check_clause( throwaway_db_url )
    assert clause is not None and "persona" in clause, f"CHECK not kind-aware after upgrade: {clause!r}"

    # The four truth-table arms at the WIRE (plan §4.1):
    assert _try_insert_blocked( throwaway_db_url, _PERSONA, None )  is False   # persona + null → REJECT
    assert _try_insert_blocked( throwaway_db_url, _PERSONA, _CHASE ) is True    # persona + chase → OK
    assert _try_insert_blocked( throwaway_db_url, _USER,    None )  is True     # user only + null → OK (now expressible)
    assert _try_insert_blocked( throwaway_db_url, _ITEM,    None )  is True     # item only + null → OK


def test_downgrade_reverts_clause_AND_behavior_not_a_stub( throwaway_db_url ):
    config = build_alembic_config( database_url=throwaway_db_url )
    command.upgrade( config, _REVISION )
    _truncate_task_items( throwaway_db_url )               # clean slate: no violators to block the stricter downgrade CHECK
    command.downgrade( config, "-1" )
    assert _current_rev( throwaway_db_url ) == _PRIOR_REVISION

    clause = _check_clause( throwaway_db_url )
    assert clause is not None and "persona" not in clause, (
        f"downgrade did not restore the global predicate (a stub?): {clause!r}" )

    # THE strongest not-a-stub proof: a user+null-chase row the UPGRADE accepted is
    # REJECTED again under the restored global rule. Behavior flipped, not just text.
    assert _try_insert_blocked( throwaway_db_url, _USER, None ) is False
    assert _try_insert_blocked( throwaway_db_url, _USER, _CHASE ) is True       # chase still passes the old rule


def test_reupgrade_is_idempotent_and_restores_kind_aware_behavior( throwaway_db_url ):
    config = build_alembic_config( database_url=throwaway_db_url )
    command.upgrade( config, _REVISION )
    _truncate_task_items( throwaway_db_url )               # clean slate across the down/up cycle
    command.downgrade( config, "-1" )
    command.upgrade( config, _REVISION )
    assert _current_rev( throwaway_db_url ) == _REVISION

    clause = _check_clause( throwaway_db_url )
    assert "persona" in clause
    # kind-aware behavior is back: user+null accepted again.
    assert _try_insert_blocked( throwaway_db_url, _USER, None ) is True
    assert _try_insert_blocked( throwaway_db_url, _PERSONA, None ) is False


def test_zero_violators_on_the_migrated_throwaway_schema( throwaway_db_url ):
    """
    A local zero-violator proof: after upgrade, NO row violates the new CHECK. On a
    throwaway DB this is a floor (it seeds only valid rows), NOT the AC5 proof —
    AC5's teeth are the count against the REAL populated lupin_db_test on :8000
    (plan §7), where existing rows actually exist. Named so nobody mistakes this
    for the real thing (Plan-1 degenerate-sample lesson).
    """
    config = build_alembic_config( database_url=throwaway_db_url )
    command.upgrade( config, _REVISION )
    _truncate_task_items( throwaway_db_url )
    # Seed the rows the migration must tolerate, then assert the count of violators
    # of the new predicate is zero.
    assert _try_insert_blocked( throwaway_db_url, _USER, None ) is True
    assert _try_insert_blocked( throwaway_db_url, _PERSONA, _CHASE ) is True

    eng = create_engine( throwaway_db_url )
    try:
        with eng.connect() as conn:
            violators = conn.execute( text(
                "SELECT count(*) FROM task_items WHERE status = 'blocked' "
                "AND next_chase_ts IS NULL "
                "AND blocked_by @> '[{\"kind\": \"persona\"}]'::jsonb"
            ) ).scalar()
        assert violators == 0
    finally:
        eng.dispose()
