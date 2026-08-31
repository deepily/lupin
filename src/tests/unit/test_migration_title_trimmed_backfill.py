"""
Migration 47513717b7e5 — the title_trimmed column and its backfill.

WHY THIS FILE EXISTS, and the credit is Rachel 🕊️'s. Reviewing c64da293 she found a
mutation that survived the whole suite: `len(title) == cap` changed to `>=`, sha
7b187f8b224d, 472 passed. Not an equivalent mutant — measured in lupin_db_dev, 333 of
2,281 rows carry titles LONGER than 60, written before the guard existed. Nothing was
CUT from those rows, so no tail is hiding in their bodies and False is the right answer.
`>=` would flag all 333.

Her fixture landed on the predicate at 7f846f51. Row 769b3574 then DELETED that
predicate and moved the answer onto a stored column, so her test would have gone with
the function — and the concern it guards would have gone with it silently. THIS FILE IS
THAT CONCERN, RE-EXPRESSED AGAINST THE THING THAT REPLACED THE PREDICATE.

⚠️ THE BACKFILL IS THE ONLY PLACE THE QUESTION STILL LIVES. Going forward the flag is
written from soft_guard_title's own verdict, so it cannot over-report. Every legacy row
gets its value from this one UPDATE, once — and if that UPDATE reaches for `>=` where it
means `=`, 333 rows are permanently mismarked with nothing to correct them.
"""
import importlib.util
import os
import sys

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from alembic.script import ScriptDirectory

from cosa.rest.db.auto_migrate import build_alembic_config
from cosa.rest.task_store_rules import TITLE_OVERFLOW_MARKER


_REVISION = "47513717b7e5"


# Portable pre-migration schema: task_items WITHOUT title_trimmed, which is the state
# the migration actually meets. Mirrors postgres_models.TaskItem minus the new column.
_TASK_ITEMS_DDL_PRE = """
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
    park_reason_captured_at TEXT,
    body_changed_ts     TEXT,
    gate_class          TEXT NOT NULL DEFAULT 'none',
    priority            TEXT NOT NULL DEFAULT 'P2',
    urgency             TEXT NOT NULL DEFAULT 'normal',
    source_qid          TEXT,
    correlation_key     TEXT,
    created_ts          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_ts          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


class _FakeOp:
    """Minimal alembic `op` over a live connection: get_bind + add_column + drop_column."""

    def __init__( self, bind ):
        self._bind = bind

    def get_bind( self ):
        return self._bind

    def add_column( self, table, column ):
        # SQLite renders NOT NULL ... DEFAULT false fine via ALTER TABLE ADD COLUMN.
        self._bind.execute( sa.text(
            f"ALTER TABLE {table} ADD COLUMN {column.name} BOOLEAN NOT NULL DEFAULT 0"
        ) )

    def drop_column( self, table, column_name ):
        self._bind.execute( sa.text( f"ALTER TABLE {table} DROP COLUMN {column_name}" ) )


def _load_migration_module():
    """Load revision 47513717b7e5 straight from its on-disk path."""
    script = ScriptDirectory.from_config( build_alembic_config( database_url=None ) )
    path   = script.get_revision( _REVISION ).path
    spec   = importlib.util.spec_from_file_location( "mig_title_trimmed", path )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


@pytest.fixture
def engine():
    """Shared-connection in-memory SQLite carrying the PRE-migration schema."""
    eng = sa.create_engine(
        "sqlite://", connect_args={ "check_same_thread": False }, poolclass=StaticPool
    )
    with eng.begin() as conn:
        conn.execute( sa.text( _TASK_ITEMS_DDL_PRE ) )
    yield eng
    eng.dispose()


def _seed( engine, rows ):
    """Insert ( id, title, body ) triples directly — bypassing the write path, exactly
    as rows already sitting in the store did before the guard existed."""
    with engine.begin() as conn:
        for row_id, title, body in rows:
            conn.execute(
                sa.text(
                    "INSERT INTO task_items ( id, item_class, title, body, project, created_by ) "
                    "VALUES ( :i, 'task', :t, :b, 'lupin', 'pocholo' )"
                ),
                { "i": row_id, "t": title, "b": body },
            )


def _flags( engine ):
    with engine.begin() as conn:
        return dict( conn.execute( sa.text( "SELECT id, title_trimmed FROM task_items" ) ).all() )


def _upgrade( engine, module, monkeypatch ):
    with engine.begin() as conn:
        monkeypatch.setattr( module, "op", _FakeOp( conn ), raising=True )
        module.upgrade()


_MARKED_BODY = f"a body\n\n{TITLE_OVERFLOW_MARKER}\nthe tail that was cut"


def test_a_legacy_over_cap_row_is_NOT_flagged_by_the_backfill( monkeypatch, engine ):
    """
    🔴 RACHEL 🕊️'s S1, TRANSLATED FROM THE DELETED PREDICATE ONTO THE COLUMN THAT
    REPLACED IT — and it is the assertion this whole file exists for.

    A row whose title EXCEEDS the cap was never trimmed: the guard did not exist when it
    was written, so nothing was cut and no tail is hiding in its body. False is correct.

    THIS IS THE ARM THAT DISCRIMINATES. The backfill says `length( title ) = 60`. Change
    that one character to `>=` and this row flips to True — which is precisely the
    mutation that survived the entire pre-existing suite, now mismarking 333 live rows
    permanently, because the backfill runs once and nothing re-derives it afterwards.
    """
    module = _load_migration_module()
    _seed( engine, [ ( "legacy", "X" * 90, "a plain body with no marker" ) ] )
    _upgrade( engine, module, monkeypatch )
    assert _flags( engine )[ "legacy" ] == 0


def test_the_backfill_flags_a_trimmed_row_by_its_marker_and_by_the_cap( monkeypatch, engine ):
    """
    The positive arms, both of them, so the negative above means something. A flag that
    is False on every row is not a flag — the same argument Rachel made for the
    predicate's own negative control.

    `marked` carries the overflow marker: PROVABLY trimmed, whatever its length.
    `at_cap` sits at exactly 60 with no marker: the value the board shows today, frozen
    rather than re-derived. Keeping it is what makes the backfill a SUPERSET of the
    current display, so nothing a reader sees flagged stops being flagged.
    """
    module = _load_migration_module()
    _seed( engine, [
        ( "marked", "a short repaired title", _MARKED_BODY ),
        ( "at_cap", "N" * 60,                 "a plain body" ),
        ( "short",  "an ordinary title",      "a plain body" ),
    ] )
    _upgrade( engine, module, monkeypatch )
    flags = _flags( engine )
    assert flags[ "marked" ] == 1
    assert flags[ "at_cap" ] == 1
    assert flags[ "short"  ] == 0


def test_the_backfill_runs_only_with_the_add_so_a_re_run_cannot_re_stamp( monkeypatch, engine ):
    """
    Re-run safety, and it is not ceremony. The PATCH path clears this flag when a retitle
    repairs a title, so a second upgrade that re-ran the backfill would silently undo
    that repair and re-assert a trim that no longer exists.

    Driven by CLEARING a flag between the two upgrades: if the second run re-stamps, the
    cleared value comes back.
    """
    module = _load_migration_module()
    _seed( engine, [ ( "at_cap", "N" * 60, "a plain body" ) ] )
    _upgrade( engine, module, monkeypatch )
    assert _flags( engine )[ "at_cap" ] == 1

    with engine.begin() as conn:
        conn.execute( sa.text( "UPDATE task_items SET title_trimmed = 0 WHERE id = 'at_cap'" ) )

    _upgrade( engine, module, monkeypatch )        # column already present -> early return
    assert _flags( engine )[ "at_cap" ] == 0       # the repair survived


def test_upgrade_is_a_no_op_when_task_items_is_absent( monkeypatch ):
    """A fresh DB built from metadata never has the table; the guard must not raise."""
    module = _load_migration_module()
    eng = sa.create_engine(
        "sqlite://", connect_args={ "check_same_thread": False }, poolclass=StaticPool
    )
    try:
        with eng.begin() as conn:
            monkeypatch.setattr( module, "op", _FakeOp( conn ), raising=True )
            module.upgrade()
            module.downgrade()
    finally:
        eng.dispose()
