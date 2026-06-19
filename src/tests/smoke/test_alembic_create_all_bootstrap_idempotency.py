"""
Regression guard for the ``DuplicateTable`` boot-crash class (origin: the
2026-06-18 :7999 lifespan abort on migration ``e5f6a7b8c9d0``).

THE BUG CLASS
-------------
A database bootstrapped via ``Base.metadata.create_all`` (which builds the FULL
current ORM schema) and stamped at an OLDER head (``d4e5f6a7b8c9``) is, on the
next boot, NOT at head — so ``run_migrations_to_head`` takes the case-3 path and
runs ``alembic upgrade head``. The newer migration ``e5f6a7b8c9d0`` then issued
``create_table`` over objects ``create_all`` had ALREADY built → ``DuplicateTable``
→ the FastAPI lifespan aborted. ``e5f6a7b8c9d0`` was made idempotent (guarded
against the live schema) in the b633d12a hotfix; this is the missing AUTOMATED
regression so the merge gate catches ANY future non-idempotent migration that
replays over a create_all-bootstrapped schema.

This test drives the REAL boot entry point
``cosa.rest.db.auto_migrate.run_migrations_to_head`` (not raw ``alembic`` only),
so it regresses the actual production startup path and all three of its DB-state
branches.

SAFETY / venue: :7999-eligible (AI-discretionary). Each test creates and DROPS
its OWN uniquely-named throwaway database on the dev Postgres server — it mutates
NO persistent state outliving the test, runs in seconds, needs no server
monopoly, and SKIPS (never fails) when Postgres is unreachable, so the DB-free
unit run / plain CI stays green. Mirrors test_alembic_migration_drift_roundtrip.py.
"""
import os

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError

from alembic import command
from alembic.script import ScriptDirectory

from cosa.rest.db import database as db_module
from cosa.rest.db import auto_migrate
from cosa.rest.db.auto_migrate import build_alembic_config, run_migrations_to_head


# The historical create_all bootstrap-stamp point — down_revision of the culprit
# migration e5f6a7b8c9d0. A DB stamped here but create_all-built at head is the
# exact crash setup.
_BOOTSTRAP_STAMP = "d4e5f6a7b8c9"

# Objects e5f6a7b8c9d0 adds — proof the empty-bootstrap path still builds them.
_DRIFT_TABLES  = [ "proxy_decisions", "trust_states", "prediction_log", "server_lifecycle" ]
_NOTIF_COLUMNS = [ "job_id", "progress_group_id", "abstract", "response_options", "is_hidden" ]


def _server_url():
    """
    Borrow the dev Postgres server's host/port/credentials via the suite's
    canonical test-DB path. The throwaway DBs created below are SEPARATE,
    uniquely-named databases — lupin_db_test itself is never touched.

    Returns the SQLAlchemy URL OBJECT (carries the REAL password); never
    ``str()`` it (that masks the password as '***' and breaks auth).
    """
    db_module.swap_database( "testing" )
    return db_module.engine.url


def _maintenance_engine( server_url ):
    """AUTOCOMMIT engine on the resolved server — used to CREATE/DROP throwaways."""
    return create_engine( server_url, isolation_level="AUTOCOMMIT" )


def _sanitize( name ):
    """Postgres-identifier-safe, length-bounded suffix from a test node name."""
    safe = "".join( c if c.isalnum() else "_" for c in name )
    return safe[ :40 ]


@pytest.fixture
def throwaway_db_url( request ):
    """
    Per-test fresh, empty throwaway DB on the dev Postgres server (function
    scope so every test starts pristine), dropped on teardown. SKIP the test if
    Postgres is unreachable (keeps DB-free CI green).
    """
    server_url = _server_url()
    db_name    = f"tiffany_idem_{os.getpid()}_{_sanitize( request.node.name )}"
    try:
        eng = _maintenance_engine( server_url )
        with eng.connect() as conn:
            conn.execute( text( f'DROP DATABASE IF EXISTS "{db_name}"' ) )
            conn.execute( text( f'CREATE DATABASE "{db_name}"' ) )
        eng.dispose()
    except OperationalError as e:
        pytest.skip( f"Postgres unreachable — skipping create_all idempotency regression: {e}" )

    # .set() returns a new URL carrying the real password; render WITH it.
    throwaway_url = server_url.set( database=db_name )
    yield throwaway_url.render_as_string( hide_password=False )

    eng = _maintenance_engine( server_url )
    with eng.connect() as conn:
        conn.execute( text(
            "SELECT pg_terminate_backend( pid ) FROM pg_stat_activity "
            "WHERE datname = :db AND pid <> pg_backend_pid()"
        ), { "db": db_name } )
        conn.execute( text( f'DROP DATABASE IF EXISTS "{db_name}"' ) )
    eng.dispose()


# ── small inspection helpers ───────────────────────────────────────────────

def _head_revision():
    """The single current migration head (resolved dynamically — never hardcoded)."""
    sd    = ScriptDirectory.from_config( build_alembic_config( database_url="postgresql://x/y" ) )
    heads = sd.get_heads()
    assert len( heads ) == 1, f"expected a single head, got {heads!r}"
    return heads[ 0 ]


def _current_rev( url ):
    eng = create_engine( url )
    try:
        with eng.connect() as conn:
            return conn.execute( text( "SELECT version_num FROM alembic_version" ) ).scalar()
    finally:
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


def _create_all( url ):
    """Bootstrap the FULL current ORM schema (the create_all path) on the DB."""
    from cosa.rest.postgres_models import Base
    eng = create_engine( url )
    try:
        Base.metadata.create_all( eng )
    finally:
        eng.dispose()


# ── the regression ─────────────────────────────────────────────────────────

def test_upgrade_head_is_clean_over_create_all_bootstrap_stamped_below_head( throwaway_db_url ):
    """
    THE regression: create_all (full schema) + stamp at the older head
    d4e5f6a7b8c9, then run the real boot path. Pre-fix this raised DuplicateTable
    on e5f6a7b8c9d0; post-fix it must reach head cleanly.
    """
    _create_all( throwaway_db_url )
    command.stamp( build_alembic_config( database_url=throwaway_db_url ), _BOOTSTRAP_STAMP )
    assert _current_rev( throwaway_db_url ) == _BOOTSTRAP_STAMP        # case-3 setup confirmed

    # TEETH: create_all has ALREADY built the objects e5f6a7b8c9d0 will try to
    # create — so the upgrade genuinely runs the guarded DDL over pre-existing
    # tables/columns. Without this, the regression could pass vacuously.
    pre_tables = _table_names( throwaway_db_url )
    for t in _DRIFT_TABLES:
        assert t in pre_tables, f"create_all should pre-build {t!r} (else the regression is vacuous)"
    pre_cols = _notif_columns( throwaway_db_url )
    for c in _NOTIF_COLUMNS:
        assert c in pre_cols, f"create_all should pre-build notifications.{c} (else the regression is vacuous)"

    # Real production boot entry point — must NOT raise (no DuplicateTable).
    run_migrations_to_head( database_url=throwaway_db_url )

    assert _current_rev( throwaway_db_url ) == _head_revision()
    # The drift objects exist (create_all built them; the guarded migration left them intact).
    tables = _table_names( throwaway_db_url )
    for t in _DRIFT_TABLES:
        assert t in tables, f"expected table {t!r} present after upgrade over create_all"
    cols = _notif_columns( throwaway_db_url )
    for c in _NOTIF_COLUMNS:
        assert c in cols, f"expected notifications column {c!r} present after upgrade over create_all"


def test_second_run_is_a_clean_idempotent_noop( throwaway_db_url ):
    """Running the boot path twice over a create_all+stamped DB is a clean no-op at head."""
    _create_all( throwaway_db_url )
    command.stamp( build_alembic_config( database_url=throwaway_db_url ), _BOOTSTRAP_STAMP )

    run_migrations_to_head( database_url=throwaway_db_url )
    head = _head_revision()
    assert _current_rev( throwaway_db_url ) == head

    # Second invocation: already at head → no-op, no error, still at head.
    run_migrations_to_head( database_url=throwaway_db_url )
    assert _current_rev( throwaway_db_url ) == head


def test_empty_db_bootstrap_builds_full_schema_at_head( throwaway_db_url ):
    """
    auto_migrate case-1: a truly empty DB → create_all from models + stamp head.
    Confirms the empty-provision path lands the full schema (incl. the drift
    objects) and stamps head — the other side of the boot contract.
    """
    run_migrations_to_head( database_url=throwaway_db_url )

    assert _current_rev( throwaway_db_url ) == _head_revision()
    tables = _table_names( throwaway_db_url )
    assert "users" in tables
    for t in _DRIFT_TABLES:
        assert t in tables, f"empty bootstrap did not build table {t!r}"
    cols = _notif_columns( throwaway_db_url )
    for c in _NOTIF_COLUMNS:
        assert c in cols, f"empty bootstrap did not build notifications column {c!r}"


def test_legacy_unstamped_schema_fails_loud( throwaway_db_url ):
    """
    auto_migrate case-2: app tables exist but the DB was NEVER alembic-stamped
    (legacy schema.sql). The boot path must REFUSE (fail loud) rather than replay
    the chain into a DuplicateTable — with explicit reconcile guidance.
    """
    _create_all( throwaway_db_url )   # app tables present, but NO alembic_version (no stamp)

    with pytest.raises( RuntimeError, match="Auto-migrate refused" ):
        run_migrations_to_head( database_url=throwaway_db_url )
