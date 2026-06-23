#!/usr/bin/env python3
"""
Unit tests for the task-store ORM models — TaskItem + TaskEvent
(cosa.rest.postgres_models, unified task store Phase 1).

Metadata-level verification: table registration, column nullability +
server defaults, every index the migration creates, the I3 CHECK constraint
(next_chase_ts required when blocked), relationship cascade, and reprs.
No database needed — pure SQLAlchemy metadata, :7999-eligible.
"""
import os
import sys
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import CheckConstraint

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.postgres_models import Base, TaskItem, TaskEvent


@pytest.fixture
def items_table():
    return Base.metadata.tables[ "task_items" ]


@pytest.fixture
def events_table():
    return Base.metadata.tables[ "task_events" ]


def test_both_tables_registered():
    assert "task_items" in Base.metadata.tables
    assert "task_events" in Base.metadata.tables


def test_item_required_columns_not_nullable( items_table ):
    for name in ( "id", "item_class", "title", "project", "created_by",
                  "status", "blocked_by", "gate_class", "priority",
                  "created_ts", "updated_ts" ):
        assert items_table.c[ name ].nullable is False, f"{name} must be NOT NULL"


def test_item_optional_columns_nullable( items_table ):
    for name in ( "body", "owner_persona", "accountable_manager",
                  "next_chase_ts", "source_qid", "correlation_key" ):
        assert items_table.c[ name ].nullable is True, f"{name} must be nullable"


def test_item_server_defaults( items_table ):
    assert items_table.c.status.server_default.arg     == "queued"
    assert items_table.c.gate_class.server_default.arg == "none"
    assert items_table.c.priority.server_default.arg   == "P2"
    assert items_table.c.blocked_by.server_default.arg == "[]"


def test_item_updated_ts_bumps_on_update( items_table ):
    """Tiberius build note (a): server_default alone won't bump on transition."""
    assert items_table.c.updated_ts.onupdate is not None


def test_item_indexes_match_migration( items_table ):
    expected = {
        "idx_task_items_correlation_key",
        "idx_task_items_owner_status",
        "ix_task_items_accountable_manager",
        "ix_task_items_gate_class",
        "ix_task_items_item_class",
        "ix_task_items_owner_persona",
        "ix_task_items_project",
        "ix_task_items_status",
        "ix_task_items_urgency",
    }
    assert { i.name for i in items_table.indexes } == expected


def test_item_composite_index_is_owner_then_status( items_table ):
    """The oracle query shape: WHERE owner_persona=? AND status IN (...)."""
    composite = next( i for i in items_table.indexes if i.name == "idx_task_items_owner_status" )
    assert [ c.name for c in composite.columns ] == [ "owner_persona", "status" ]


def test_item_blocked_requires_chase_ts_check( items_table ):
    checks = [ c for c in items_table.constraints if isinstance( c, CheckConstraint ) ]
    named  = [ c for c in checks if c.name == "ck_task_items_blocked_requires_chase_ts" ]
    assert len( named ) == 1
    assert "next_chase_ts IS NOT NULL" in str( named[ 0 ].sqltext )


def test_event_columns( events_table ):
    for name in ( "id", "item_id", "ts", "actor", "transition", "authority" ):
        assert events_table.c[ name ].nullable is False, f"{name} must be NOT NULL"
    assert events_table.c.receipt_refs.nullable is True
    assert events_table.c.authority.server_default.arg == "standing"


def test_event_reason_column_nullable_text( events_table ):
    # Phase 2 (C12 pulled forward): nullable by schema — requiredness for
    # ->dropped is the rules layer's job, additive for D1 convergence.
    from sqlalchemy import Text
    column = events_table.c.reason
    assert column.nullable is True
    assert isinstance( column.type, Text )
    assert column.server_default is None


def test_event_fk_cascades_on_delete( events_table ):
    fk = next( iter( events_table.c.item_id.foreign_keys ) )
    assert fk.column.table.name == "task_items"
    assert fk.ondelete == "CASCADE"


def test_event_index( events_table ):
    assert { i.name for i in events_table.indexes } == { "idx_task_events_item_id" }


def test_item_events_relationship_cascades():
    rel = TaskItem.events.property
    assert rel.cascade.delete_orphan is True
    assert TaskEvent.item.property.back_populates == "events"


def test_item_repr():
    item = TaskItem(
        id            = uuid.UUID( "550e8400-e29b-41d4-a716-446655440000" ),
        item_class    = "task",
        status        = "queued",
        owner_persona = "krishna",
    )
    text = repr( item )
    assert "TaskItem" in text and "item_class='task'" in text and "owner='krishna'" in text


def test_event_repr():
    event = TaskEvent(
        item_id    = uuid.UUID( "550e8400-e29b-41d4-a716-446655440000" ),
        actor      = "krishna 38d15e3b",
        transition = "queued->claimed",
    )
    text = repr( event )
    assert "TaskEvent" in text and "transition='queued->claimed'" in text and "actor='krishna 38d15e3b'" in text


def test_item_constructs_with_full_field_set():
    """The wire-shape field set round-trips through the constructor unchanged."""
    now  = datetime( 2026, 6, 12, 0, 0, tzinfo=timezone.utc )
    item = TaskItem(
        id                  = uuid.uuid4(),
        item_class          = "review_request",
        title               = "review the task store",
        body                = "framing payload",
        project             = "lupin",
        owner_persona       = "krishna",
        accountable_manager = "tiberius",
        created_by          = "krishna 38d15e3b",
        status              = "blocked",
        blocked_by          = [ { "kind": "user", "id": "rick" } ],
        next_chase_ts       = now,
        gate_class          = "operator",
        priority            = "P0",
        source_qid          = "c8c73fde-6ce4-4e8d-83d7-c55b5cce65a3",
        correlation_key     = "harness-task-42",
        created_ts          = now,
        updated_ts          = now,
    )
    assert item.status == "blocked" and item.blocked_by[ 0 ][ "kind" ] == "user"
    assert item.gate_class == "operator" and item.next_chase_ts == now


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
