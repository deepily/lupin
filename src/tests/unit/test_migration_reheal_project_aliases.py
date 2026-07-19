#!/usr/bin/env python3
"""
REAL-DB unit tests for the back-catalogue re-heal migration
(a7b8c9d0e1f2_reheal_task_project_aliases) — the fix-forward for Tiberius's
REQUEST-CHANGES on the project-name canonicalization work (8358ce1f).

WHY THIS TEST EXISTS (the false-green it kills)
-----------------------------------------------
The pre-existing canonicalization tests are MOCK-based — they assert the repo
was CALLED with a canonical value. They never prove a row already STORED under a
raw alias key becomes VISIBLE to the owed query. 8358ce1f canonicalizes the
query FILTER value only, never the stored `project` column, so a legacy row
(e.g. Rick's TODO-archival task, persisted as project="planning-is-prompting")
stays OUT of query_owed(project="plan") and its owner false-idles while owing
work. This suite proves the migration heals that: it drives the REAL
TaskRepository against a REAL (SQLite) DB and asserts a raw-alias row flips from
INVISIBLE -> VISIBLE under the canonical filter.

REAL-DB, NOT MOCK
-----------------
The DB is a genuine in-memory SQLite engine with a real `task_items` /
`task_events` schema, queried through the production TaskRepository.query_tasks /
count_tasks (the exact SQL the owed oracle runs). The PG-specific UUID/JSONB
column TYPES cannot render under SQLite's DDL compiler (the full ORM create_all
fails on unrelated JSONB columns), so the two tables are created with portable
column types — but every READ/WRITE flows through the real ORM models and their
bind/result processors. The migration's DML (`UPDATE ... WHERE project = :raw`)
and its inspector `has_table` guard are dialect-portable, so SQLite exercises the
re-stamp loop, the no-table early-return, and the visibility flip at 100%.

SINGLE SOURCE OF THE ALIAS MAP: the alias pairs are sourced from the SAME
`_PROJECT_ALIASES` table the migration imports — never duplicated here.

Venue: :7999-eligible (pure unit, in-memory SQLite, no server, no Postgres).
"""
import importlib.util

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from alembic.script import ScriptDirectory

from cosa.rest.db.auto_migrate import build_alembic_config
from cosa.rest.db.repositories.task_repository import TaskRepository
from cosa.agents.utils.sender_id import _PROJECT_ALIASES


_REVISION = "a7b8c9d0e1f2"


# Portable (SQLite-renderable) DDL for the two tables the migration + repository
# touch. Column NAMES + nullability mirror postgres_models.TaskItem/TaskEvent;
# the PG-specific UUID/JSONB TYPES are stored as TEXT (the ORM's bind/result
# processors round-trip uuids and JSON onto TEXT without complaint on SQLite).
_TASK_ITEMS_DDL = """
CREATE TABLE task_items (
    id                  TEXT PRIMARY KEY,
    item_class          TEXT NOT NULL,
    title               TEXT NOT NULL,
    body                TEXT,
    project             TEXT NOT NULL,
    owner_persona       TEXT,
    accountable_manager TEXT,
    created_by          TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'queued',
    blocked_by          TEXT NOT NULL DEFAULT '[]',
    next_chase_ts       TEXT,
    park_reason         TEXT,
    gate_class          TEXT NOT NULL DEFAULT 'none',
    priority            TEXT NOT NULL DEFAULT 'P2',
    urgency             TEXT NOT NULL DEFAULT 'normal',
    source_qid          TEXT,
    correlation_key     TEXT,
    created_ts          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_ts          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

_TASK_EVENTS_DDL = """
CREATE TABLE task_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id      TEXT NOT NULL,
    ts           TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor        TEXT NOT NULL,
    transition   TEXT NOT NULL,
    receipt_refs TEXT,
    authority    TEXT NOT NULL,
    reason       TEXT
)
"""


class _FakeOp:
    """Minimal alembic-op stand-in: only get_bind() is exercised by the migration."""

    def __init__( self, bind ):
        self._bind = bind

    def get_bind( self ):
        return self._bind


def _load_migration_module():
    """Load the re-heal revision script as a module straight from its on-disk path."""
    script = ScriptDirectory.from_config( build_alembic_config( database_url=None ) )
    path   = script.get_revision( _REVISION ).path
    spec   = importlib.util.spec_from_file_location( "mig_reheal_project_aliases", path )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


def _new_engine( with_schema=True ):
    """
    A shared-connection in-memory SQLite engine (StaticPool => one underlying
    DBAPI connection, so every Session/Connection sees the SAME database).

    with_schema=True creates the portable task_items + task_events tables;
    with_schema=False leaves the DB empty (drives the migration's no-table guard).
    """
    engine = sa.create_engine(
        "sqlite://",
        connect_args = { "check_same_thread": False },
        poolclass    = StaticPool,
    )
    if with_schema:
        with engine.begin() as conn:
            conn.execute( sa.text( _TASK_ITEMS_DDL ) )
            conn.execute( sa.text( _TASK_EVENTS_DDL ) )
    return engine


@pytest.fixture
def make_engine():
    """Factory yielding shared-connection SQLite engines; disposes all at teardown."""
    engines = [ ]
    def _make( with_schema=True ):
        engine = _new_engine( with_schema=with_schema )
        engines.append( engine )
        return engine
    yield _make
    for engine in engines:
        engine.dispose()


def _seed_raw_row( engine, project, owner_persona="rick" ):
    """Seed ONE owed task row under the given (raw) project via the REAL repository."""
    with Session( engine ) as session:
        repo = TaskRepository( session )
        repo.create_item(
            item_class    = "task",
            title         = f"owed work under {project}",
            project       = project,
            created_by    = "rick host",
            authority     = "standing",
            owner_persona = owner_persona,
        )
        session.commit()


def _run_upgrade( engine, module, monkeypatch ):
    """Run the migration upgrade() against `engine` inside a committing transaction."""
    with engine.begin() as conn:
        monkeypatch.setattr( module, "op", _FakeOp( conn ), raising=True )
        module.upgrade()


def _visible_count( engine, project ):
    """(query_tasks length, count_tasks) for `project` via the REAL repository."""
    with Session( engine ) as session:
        repo = TaskRepository( session )
        return len( repo.query_tasks( project=project ) ), repo.count_tasks( project=project )


# ---------------------------------------------------------------------------
# THE false-green killer: a stored raw-alias row flips INVISIBLE -> VISIBLE.
# ---------------------------------------------------------------------------

def test_real_db_raw_row_invisible_then_visible_after_reheal( monkeypatch, make_engine ):
    module = _load_migration_module()
    engine = make_engine( with_schema=True )

    # Invariant the assertions below rely on: an alias RENAMES (key != value) —
    # the map never carries a degenerate identity entry ("plan" -> "plan"). Stated
    # once so the per-row checks can be UNCONDITIONAL (no data-dependent branch).
    assert all( raw != canonical for raw, canonical in _PROJECT_ALIASES.items() )

    # One owed row per raw alias key (the back-catalogue), plus a non-aliased
    # control row ("lupin") that must survive the re-heal untouched.
    for raw in _PROJECT_ALIASES.keys():
        _seed_raw_row( engine, raw )
    _seed_raw_row( engine, "lupin", owner_persona="krishna" )

    # PRE: every raw row is INVISIBLE to a query under its CANONICAL name — the
    # 8358ce1f filter-only canonicalization cannot reach a row stored raw. This
    # is the bug Tiberius flagged; the mock tests never asserted it.
    for raw, canonical in _PROJECT_ALIASES.items():
        q, c = _visible_count( engine, canonical )
        assert q == 0 and c == 0, f"PRE: {canonical!r} should be invisible, got query={q} count={c}"

    _run_upgrade( engine, module, monkeypatch )

    # POST: each raw row is now stored under (and VISIBLE to) its canonical name;
    # no row survives under the raw key.
    for raw, canonical in _PROJECT_ALIASES.items():
        q, c = _visible_count( engine, canonical )
        assert q >= 1 and c >= 1, f"POST: {canonical!r} should be visible, got query={q} count={c}"
        raw_q, raw_c = _visible_count( engine, raw )
        assert raw_q == 0 and raw_c == 0, f"POST: raw {raw!r} should be orphaned, got query={raw_q} count={raw_c}"

    # The specific re-stamped row's project column is healed, and NO other column
    # changed (project-column-only invariant — owner/status/title untouched). The
    # row is read back through the REAL repository (matched by its seed title).
    with Session( engine ) as session:
        repo = TaskRepository( session )
        for raw, canonical in _PROJECT_ALIASES.items():
            rows   = repo.query_tasks( project=canonical )
            healed = next( r for r in rows if r.title == f"owed work under {raw}" )
            assert healed.project       == canonical
            assert healed.owner_persona == "rick"
            assert healed.status        == "queued"

    # The non-aliased control row is undisturbed.
    ctrl_q, ctrl_c = _visible_count( engine, "lupin" )
    assert ctrl_q == 1 and ctrl_c == 1


# ---------------------------------------------------------------------------
# Idempotency: a second upgrade re-stamps zero rows and leaves the DB identical.
# ---------------------------------------------------------------------------

def test_reheal_is_idempotent( monkeypatch, make_engine ):
    module = _load_migration_module()
    engine = make_engine( with_schema=True )
    _seed_raw_row( engine, "planning-is-prompting" )

    _run_upgrade( engine, module, monkeypatch )
    first_q, first_c = _visible_count( engine, "plan" )
    _run_upgrade( engine, module, monkeypatch )   # second run: nothing left to re-stamp
    second_q, second_c = _visible_count( engine, "plan" )

    assert first_q == first_c == 1
    assert ( second_q, second_c ) == ( first_q, first_c )


# ---------------------------------------------------------------------------
# No-table guard: upgrade short-circuits (no raise) when task_items is absent.
# ---------------------------------------------------------------------------

def test_reheal_no_table_is_noop( monkeypatch, make_engine ):
    module = _load_migration_module()
    engine = make_engine( with_schema=False )   # empty DB — no task_items table

    _run_upgrade( engine, module, monkeypatch )   # must not raise

    with engine.connect() as conn:
        assert not sa.inspect( conn ).has_table( "task_items" )


# ---------------------------------------------------------------------------
# Downgrade is a deliberate, lossy-safe no-op.
# ---------------------------------------------------------------------------

def test_downgrade_is_noop():
    module = _load_migration_module()
    assert module.downgrade() is None   # pure pass — no DB touch, no raise


# ---------------------------------------------------------------------------
# DDL drift guard (bug 6e9a8520): the hand-rolled portable DDL MUST carry EXACTLY
# the ORM model's columns — else the real-repository INSERT fails cryptically.
# ---------------------------------------------------------------------------

def test_portable_ddl_matches_orm_columns( make_engine ):
    """The portable task_items / task_events DDL mirrors the ORM models column-for-
    column. Guards the exact drift that made these tests look env-flaky (6e9a8520):
    `urgency` was added to postgres_models.TaskItem (2c8ed5ac, 2026-06-23) the day
    AFTER this DDL was written, without mirroring it here — so create_item's INSERT
    hit "no column named urgency" buried in a stack trace, deterministic on any
    current tree. This asserts the column SETS match, failing LOUDLY and NAMING the
    drifted column the moment a model column is added without updating the DDL."""
    from cosa.rest.postgres_models import TaskItem, TaskEvent

    engine = make_engine( with_schema=True )
    insp   = sa.inspect( engine )
    for model in ( TaskItem, TaskEvent ):
        ddl_cols   = { c[ "name" ] for c in insp.get_columns( model.__tablename__ ) }
        model_cols = { c.name for c in model.__table__.columns }
        assert ddl_cols == model_cols, (
            f"{model.__tablename__} portable-DDL drift vs ORM model: "
            f"missing={sorted( model_cols - ddl_cols )}, extra={sorted( ddl_cols - model_cols )}"
        )
