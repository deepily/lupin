#!/usr/bin/env python3
"""
Pins for the task-store slice of the twin refactor.

Each block pins one pair of twins from its observable behaviour, so the same file passes
before and after the pair is merged. They were written and run against the old code first.

Blocks, in file order: the three boolean getters in `task_approval_settings`.
The two grouped counts in `TaskRepository`.
The completed and stalled job-history writers.
The `holding_is_active` and `park_is_active` predicates.
The two SQL clause builders beside them.
"""
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import cosa.rest.job_persistence as jp
import cosa.rest.task_approval_settings as approval
import cosa.rest.task_store_owed as owed
from cosa.rest.db.repositories.task_repository import TaskRepository
from cosa.rest.postgres_models import TaskItem

NOW = datetime( 2026, 9, 15, 16, 0, tzinfo=timezone.utc )


# ── exact:25  the three boolean getters ─────────────────────────────────────────

GETTERS = [
    ( "get_enforcement_active",      "enforcement_active",      "INI_KEY_ENFORCEMENT",           "FALLBACK_ENFORCEMENT_ACTIVE"      ),
    ( "get_manager_pull_disabled",   "manager_pull_disabled",   "INI_KEY_MANAGER_PULL_DISABLED", "FALLBACK_MANAGER_PULL_DISABLED" ),
    ( "get_sword_of_damocles_active", "sword_of_damocles_active", "INI_KEY_SWORD_OF_DAMOCLES",   "FALLBACK_SWORD_OF_DAMOCLES_ACTIVE" ),
]


def _wire( monkeypatch, override_key, override, ini ):
    """Stub the two layers and record every parse the getter asks for, as ( raw, label )."""
    parses   = []
    ini_asks = []
    real     = approval._as_bool_or_none

    def spy( raw, where ):
        parses.append( ( raw, where ) )
        return real( raw, where )

    monkeypatch.setattr( approval, "_read_overrides", lambda: { override_key: override } )
    monkeypatch.setattr( approval, "_ini_value", lambda key, return_type, fallback: ini_asks.append( ( key, return_type, fallback ) ) or ini )
    monkeypatch.setattr( approval, "_as_bool_or_none", spy )
    return parses, ini_asks


@pytest.mark.parametrize( "getter_name, override_key, ini_const, fallback_const", GETTERS )
def test_the_override_wins_and_the_ini_layer_is_not_consulted( monkeypatch, getter_name, override_key, ini_const, fallback_const ):
    parses, ini_asks = _wire( monkeypatch, override_key, "yes", "no" )

    assert getattr( approval, getter_name )() is True
    assert parses == [ ( "yes", approval.STORE_LABEL ) ]
    assert ini_asks == []


@pytest.mark.parametrize( "getter_name, override_key, ini_const, fallback_const", GETTERS )
def test_an_unparseable_override_falls_through_to_its_own_ini_key( monkeypatch, getter_name, override_key, ini_const, fallback_const ):
    ini_key           = getattr( approval, ini_const )
    parses, ini_asks  = _wire( monkeypatch, override_key, "banana", "off" )

    assert getattr( approval, getter_name )() is False
    assert ini_asks == [ ( ini_key, "string", None ) ]
    assert parses == [ ( "banana", approval.STORE_LABEL ), ( "off", f"config key '{ini_key}'" ) ]


@pytest.mark.parametrize( "getter_name, override_key, ini_const, fallback_const", GETTERS )
def test_neither_layer_decides_so_the_fallback_answers( monkeypatch, getter_name, override_key, ini_const, fallback_const ):
    _wire( monkeypatch, override_key, None, None )
    assert getattr( approval, getter_name )() is getattr( approval, fallback_const )

    for flipped in ( True, False ):
        monkeypatch.setattr( approval, fallback_const, flipped )
        assert getattr( approval, getter_name )() is flipped


# ── exact:72  the two grouped counts ────────────────────────────────────────────

FILTERS = dict( owner_persona="p1", status="s1", gate_class="g1", urgency="u1", accountable_manager="m1",
                project="pr1", item_class="c1", correlation_key="k1", id_prefix="ab12", blocked_by_persona="b1",
                updated_since=NOW - timedelta( days=1 ), updated_until=NOW, include_terminal=True,
                owed_only=True, hide_parked=False, now=NOW )


@pytest.mark.parametrize( "method, column, rows", [
    ( "count_tasks_by_status",   TaskItem.status,   [ ( "queued", 3 ), ( "done", 1 ) ] ),
    ( "count_tasks_by_priority", TaskItem.priority, [ ( "P0", 2 ) ] ),
] )
def test_each_grouped_count_forwards_all_sixteen_filters_and_groups_on_its_column( monkeypatch, method, column, rows ):
    session = MagicMock()
    query   = session.query.return_value
    query.group_by.return_value.all.return_value = rows
    seen    = {}
    monkeypatch.setattr( TaskRepository, "_apply_scalar_filters",
                         staticmethod( lambda q, *a, **kw: seen.update( scalar=( a, kw ) ) or q ) )
    monkeypatch.setattr( TaskRepository, "_apply_owed_filter",
                         staticmethod( lambda q, *a: seen.update( owed=a ) or q ) )

    result = getattr( TaskRepository( session ), method )( **FILTERS )

    assert result == dict( rows )
    assert session.query.call_args.args[ 0 ] is column
    assert query.group_by.call_args.args[ 0 ] is column
    assert seen[ "scalar" ] == ( ( "p1", "s1", "g1", "u1", "m1", "pr1", "c1", "k1", "ab12" ),
                                 dict( updated_since=FILTERS[ "updated_since" ], updated_until=NOW, blocked_by_persona="b1" ) )
    assert seen[ "owed" ] == ( True, False, "s1", True, NOW )


def test_the_two_grouped_counts_keep_the_same_public_signature():
    import inspect
    by_status   = inspect.signature( TaskRepository.count_tasks_by_status )
    by_priority = inspect.signature( TaskRepository.count_tasks_by_priority )
    assert list( by_status.parameters ) == list( by_priority.parameters )
    assert list( by_status.parameters )[ 1: ] == list( FILTERS )
    assert len( by_status.parameters ) == 17
    assert [ p.default for p in by_status.parameters.values() ] == [ p.default for p in by_priority.parameters.values() ]


# ── exact:78  completed and stalled writers ─────────────────────────────────────

@contextmanager
def _db( session ):
    yield session


@pytest.mark.parametrize( "fn_name, status, warning", [
    ( "persist_job_completed_from_metadata", "completed", "persist_job_completed_from_metadata failed for j1" ),
    ( "persist_job_stalled_from_metadata",   "stalled",   "persist_job_stalled_from_metadata failed for j1" ),
] )
class TestTerminalWriters:

    def _run( self, fn_name, row, metadata=None ):
        session = MagicMock()
        first   = MagicMock(); first.one_or_none.return_value = row
        session.execute.side_effect = [ first, MagicMock() ]
        with patch.object( jp, "_is_persistence_enabled", return_value=True ), \
             patch.object( jp, "get_db", lambda: _db( session ) ):
            getattr( jp, fn_name )( "j1", { "response_text": "r" } if metadata is None else metadata )
        return session

    @staticmethod
    def _written( session ):
        return session.execute.call_args_list[ 1 ].args[ 0 ].compile( dialect=postgresql.dialect() ).params

    def test_it_writes_its_status_the_merged_metadata_and_the_duration( self, fn_name, status, warning ):
        started = datetime.now( timezone.utc ) - timedelta( seconds=30 )
        session = self._run( fn_name, SimpleNamespace( started_at=started, metadata_json={ "original_args": { "x": 1 } } ) )

        params = self._written( session )
        assert params[ "status" ] == status
        assert params[ "metadata_json" ][ "original_args" ] == { "x": 1 }
        assert params[ "metadata_json" ] == { **{ "original_args": { "x": 1 } }, **jp._build_metadata_json( { "response_text": "r" } ) }
        assert 29 < params[ "duration_seconds" ] < 60
        assert params[ "completed_at" ] == params[ "updated_at" ]

    def test_a_missing_row_or_start_time_writes_no_duration( self, fn_name, status, warning ):
        for row in ( None, SimpleNamespace( started_at=None, metadata_json=None ) ):
            params = self._written( self._run( fn_name, row ) )
            assert "duration_seconds" not in params
            assert params[ "status" ] == status

    def test_disabled_persistence_touches_nothing( self, fn_name, status, warning ):
        session = MagicMock()
        with patch.object( jp, "_is_persistence_enabled", return_value=False ), \
             patch.object( jp, "get_db", lambda: _db( session ) ):
            getattr( jp, fn_name )( "j1", {} )
        session.execute.assert_not_called()

    def test_a_failure_prints_the_public_name_and_never_raises( self, fn_name, status, warning ):
        session = MagicMock(); session.execute.side_effect = RuntimeError( "boom" )
        with patch.object( jp, "_is_persistence_enabled", return_value=True ), \
             patch.object( jp, "get_db", lambda: _db( session ) ), \
             patch( "builtins.print" ) as printed:
            getattr( jp, fn_name )( "j1", {} )
        assert printed.call_args_list[ -1 ].args[ 0 ] == f"[WARN] {warning}: boom"


# ── exact:83 and exact:84  the active predicates and their SQL clauses ──────────

PREDICATES = [
    ( owed.holding_is_active, owed.holding_is_active_clause, owed.NOT_APPROVED_STATUS, owed.PARK_STATUS ),
    ( owed.park_is_active,    owed.park_is_active_clause,    owed.PARK_STATUS,        owed.NOT_APPROVED_STATUS ),
]


@pytest.mark.parametrize( "predicate, clause, own, other", PREDICATES )
def test_the_predicate_is_true_only_for_its_own_status_with_a_future_chase( predicate, clause, own, other ):
    future = NOW + timedelta( hours=1 )
    assert predicate( own, future, NOW ) is True
    assert predicate( own, future.isoformat(), NOW ) is True
    assert predicate( own, future.isoformat().replace( "+00:00", "Z" ), NOW ) is True
    assert predicate( own, "  " + future.isoformat() + " ", NOW ) is True
    assert predicate( own, future.replace( tzinfo=None ), NOW.replace( tzinfo=None ) ) is True
    assert predicate( own, future.replace( tzinfo=None ), NOW ) is True
    assert predicate( own, future, NOW.replace( tzinfo=None ) ) is True
    for status in ( other, "queued", "", None ):
        assert predicate( status, future, NOW ) is False


@pytest.mark.parametrize( "predicate, clause, own, other", PREDICATES )
def test_the_predicate_is_false_when_the_chase_is_due_missing_or_unreadable( predicate, clause, own, other ):
    assert predicate( own, NOW, NOW ) is False
    assert predicate( own, NOW - timedelta( seconds=1 ), NOW ) is False
    for junk in ( None, "", "not a date", 12345, [ ] ):
        assert predicate( own, junk, NOW ) is False


@pytest.mark.parametrize( "predicate, clause, own, other", PREDICATES )
def test_the_clause_asks_its_own_status_a_non_null_chase_and_a_strict_future( predicate, clause, own, other ):
    for now in ( NOW, NOW.replace( tzinfo=None ) ):
        sql = str( clause( TaskItem, now ).compile( dialect=postgresql.dialect(), compile_kwargs={ "literal_binds": True } ) )
        assert sql == ( f"task_items.status = '{own}' AND task_items.next_chase_ts IS NOT NULL "
                        f"AND task_items.next_chase_ts > '2026-09-15 16:00:00+00:00'" )
