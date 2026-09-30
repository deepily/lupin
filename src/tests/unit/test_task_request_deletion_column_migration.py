#!/usr/bin/env python3
"""
MIGRATION ffbf50040d99 AND THE MODEL MUST AGREE ABOUT `request_deletion_id`.

Step 3 of the Sword of Damocles plan (row ab8c5728,
src/rnd/v0.2.1/2026.09.14-sword-of-damocles-enforcement-plan.md §3.3): an admit request stores the
ticket it pledges for deletion, so the verdict can drop that row without parsing an audit
string. One nullable UUID column plus one CHECK: a pledge only rides on an admit.

Modelled on test_task_request_columns_migration.py, whose guards are per-migration and so
do not cover this revision.
"""
import importlib.util
import os
import sys

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.db.auto_migrate import build_alembic_config

_REVISION      = "ffbf50040d99"
_DOWN_REVISION = "525a4ad4067a"
_TABLE         = "task_items"
_COLUMN        = "request_deletion_id"
_CHECK         = "ck_task_items_request_deletion_only_on_admit"
_CHECK_LITERAL = "request_deletion_id IS NULL OR request_move = 'admit'"


def _script_dir():
    return ScriptDirectory.from_config( build_alembic_config( database_url=None ) )


def _migration_module():
    path   = _script_dir().get_revision( _REVISION ).path
    spec   = importlib.util.spec_from_file_location( "task_request_deletion_column_migration", path )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


def _model_table():
    from cosa.rest.postgres_models import TaskItem
    return TaskItem.__table__


# ── the chain ────────────────────────────────────────────────────────────────

def test_revision_exists_and_names_the_head_it_was_written_against():
    rev = _script_dir().get_revision( _REVISION )
    assert rev is not None
    assert rev.down_revision == _DOWN_REVISION


def test_the_revision_is_on_the_single_chain_to_head():
    script = _script_dir()
    heads  = list( script.get_heads() )
    assert len( heads ) == 1, f"the chain forked: {heads!r}"
    chain, node = set(), script.get_revision( heads[ 0 ] )
    while node is not None:
        chain.add( node.revision )
        node = script.get_revision( node.down_revision ) if node.down_revision else None
    assert _REVISION in chain
    assert _DOWN_REVISION in chain, "positive control: the parent must be on the chain too"


# ── parity: migration and model say the same thing ─────────────────────────

def test_the_model_carries_the_PLEDGER_column_NULLABLE():
    """RB-2: `request_pledged_by` rides in the same revision, since no database had it yet."""
    assert _model_table().columns[ "request_pledged_by" ].nullable is True


def test_the_model_carries_the_column_NULLABLE():
    column = _model_table().columns[ _COLUMN ]
    assert column.nullable is True


def test_the_check_literal_matches_the_model_and_the_migration_VERBATIM():
    literals = { c.name: str( c.sqltext ) for c in _model_table().constraints
                 if getattr( c, "name", None ) and hasattr( c, "sqltext" ) }
    assert "ck_task_items_request_requires_move" in literals, "positive control: a known CHECK is found"
    assert literals[ _CHECK ] == _CHECK_LITERAL
    assert dict( _migration_module().CHECKS )[ _CHECK ] == _CHECK_LITERAL


# ── driven against a live table ─────────────────────────────────────────────

@pytest.fixture
def sqlite_task_items( monkeypatch ):
    """A scratch task_items with two pre-existing rows, the migration bound to it."""
    engine     = create_engine( "sqlite://" )
    connection = engine.connect()
    connection.execute( text(
        "CREATE TABLE task_items ( id TEXT PRIMARY KEY, status TEXT, request_move TEXT )" ) )
    connection.execute( text(
        "INSERT INTO task_items VALUES ( 'a', 'queued', NULL ), ( 'b', 'not_approved', 'admit' )" ) )
    connection.commit()
    module = _migration_module()
    monkeypatch.setattr( module, "op", Operations( MigrationContext.configure( connection ) ) )
    yield module, connection
    connection.close()


def _columns( connection ):
    return { c[ "name" ] for c in inspect( connection ).get_columns( _TABLE ) }


def test_the_upgrade_ADDS_the_column_and_keeps_existing_rows_NULL( sqlite_task_items ):
    module, connection = sqlite_task_items
    assert _COLUMN not in _columns( connection ), "the fixture started dirty"

    # SQLite cannot ALTER constraints; the column half is what this backend can prove.
    with pytest.raises( NotImplementedError, match="ALTER of constraints in SQLite" ):
        module.upgrade()

    assert _COLUMN in _columns( connection )
    rows = connection.execute( text( f"SELECT id, {_COLUMN} FROM task_items ORDER BY id" ) ).all()
    assert rows == [ ( "a", None ), ( "b", None ) ]


def test_the_upgrade_ADDS_the_PLEDGER_column_and_the_downgrade_DROPS_it( sqlite_task_items ):
    module, connection = sqlite_task_items
    assert "request_pledged_by" not in _columns( connection ), "the fixture started dirty"

    with pytest.raises( NotImplementedError, match="ALTER of constraints in SQLite" ):
        module.upgrade()
    assert "request_pledged_by" in _columns( connection )
    rows = connection.execute( text( "SELECT id, request_pledged_by FROM task_items ORDER BY id" ) ).all()
    assert rows == [ ( "a", None ), ( "b", None ) ]

    module.downgrade()
    assert "request_pledged_by" not in _columns( connection )


def test_re_running_the_column_step_does_not_raise_on_the_column( sqlite_task_items ):
    module, connection = sqlite_task_items
    with pytest.raises( NotImplementedError ):
        module.upgrade()
    with pytest.raises( NotImplementedError ):
        module.upgrade()
    assert _COLUMN in _columns( connection )


def test_the_upgrade_and_downgrade_are_NO_OPS_without_task_items( monkeypatch ):
    engine     = create_engine( "sqlite://" )
    connection = engine.connect()
    module     = _migration_module()
    monkeypatch.setattr( module, "op", Operations( MigrationContext.configure( connection ) ) )
    module.upgrade()
    module.downgrade()
    assert inspect( connection ).get_table_names() == [ ]


def test_the_downgrade_DROPS_the_column( sqlite_task_items ):
    module, connection = sqlite_task_items
    with pytest.raises( NotImplementedError ):
        module.upgrade()
    module.downgrade()
    assert _COLUMN not in _columns( connection )


# ── the full serializer carries the pledge ──────────────────────────────────

@pytest.mark.parametrize( "pledge", [ None, "22222222-2222-2222-2222-222222222222" ] )
def test_the_full_serializer_carries_the_pledge_as_a_string_or_None( pledge ):
    import uuid
    from datetime import datetime, timezone
    from cosa.rest.postgres_models import TaskItem
    from cosa.rest.routers import tasks as tasks_router

    now  = datetime( 2026, 9, 14, 23, 9, tzinfo=timezone.utc )
    item = TaskItem(
        id = uuid.uuid4(), item_class="task", title="t", project="lupin", status="not_approved",
        gate_class="none", priority="P2", urgency="normal", blocked_by=[ ],
        request_state="pending", request_move="admit", request_ts=now,
        request_deletion_id=uuid.UUID( pledge ) if pledge else None,
        created_ts=now, updated_ts=now,
    )
    assert tasks_router._serialize_item( item )[ "request_deletion_id" ] == pledge
    assert "request_deletion_id" not in tasks_router._serialize_item_terse( item ), (
        "full shape only — a terse key is a ruling nobody has made"
    )
