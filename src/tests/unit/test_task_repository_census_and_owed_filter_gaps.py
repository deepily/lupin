"""
THE TaskRepository PATHS THE UNIT + COSA TIERS NEVER REACHED — row ab8c5728, AC7.

The Sword of Damocles plan requires 100% lines/branches/functions on every module it touched.
Coverage gate data for candidate d322aba1 (2026-09-15 12:37 EDT) left task_repository.py at
93%, and none of the missed lines came from that build:

    517           _db_clock_now: the naive-to-UTC conversion (SQLite's clock is naive)
    1244->1247    _apply_owed_filter with an explicit `now`
    1259-1282     _apply_owed_filter: hide_parked on an un-statused, non-terminal query
    1425-1433     count_tasks_by_priority
    1491-1499     count_tasks_by_project
    1678          count_admissions_since

HOW THESE TESTS AVOID MEASURING THEIR FIXTURE. A MagicMock session answers whatever it is told,
so every assertion below is on something the CODE chose rather than on what the mock returned:
the SQL a clause compiles to (rendered with the PostgreSQL dialect, literal values inlined), the
column a census groups by, the arguments forwarded to the shared filter helpers, and the dict
built from rows. Where a clause's meaning matters, the compiled SQL is what is asserted.
"""
import inspect
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.db.repositories import task_repository as task_repository_module
from cosa.rest.db.repositories.task_repository import TaskRepository
from cosa.rest.postgres_models import TaskItem

NOW = datetime( 2026, 9, 15, 16, 0, tzinfo=timezone.utc )


def _sql( clause ):
    return str( clause.compile( dialect=postgresql.dialect(), compile_kwargs={ "literal_binds": True } ) )


class _RecordingQuery:
    """Records each filter clause and returns itself, so a test reads exactly what the code filtered on."""
    def __init__( self ):
        self.clauses = [ ]

    def filter( self, clause ):
        self.clauses.append( clause )
        return self


# ---------------------------------------------------------------------------
# _db_clock_now
# ---------------------------------------------------------------------------

def test_a_NAIVE_database_clock_is_returned_as_UTC_aware():
    """SQLite hands back a naive datetime; comparing it to the tz-aware column would raise."""
    session = MagicMock()
    session.execute.return_value.scalar_one.return_value = datetime( 2026, 9, 15, 16, 0 )

    captured = TaskRepository( session )._db_clock_now()

    assert captured == NOW
    assert captured.tzinfo is timezone.utc


def test_an_AWARE_database_clock_is_returned_unchanged():
    session = MagicMock()
    aware   = datetime( 2026, 9, 15, 12, 0, tzinfo=timezone( timedelta( hours=-4 ) ) )
    session.execute.return_value.scalar_one.return_value = aware

    captured = TaskRepository( session )._db_clock_now()

    assert captured is aware


# ---------------------------------------------------------------------------
# _apply_owed_filter — hide_parked on an un-statused query
# ---------------------------------------------------------------------------

def test_hide_parked_on_an_unstatused_query_hides_terminal_rows_and_chase_holding_rows_then_park_active_rows():
    query = _RecordingQuery()

    result = TaskRepository._apply_owed_filter( query, owed_only=False, hide_parked=True, status=None,
                                                include_terminal=False, now=NOW )

    assert result is query
    assert len( query.clauses ) == 2, "expected the terminal/holding clause THEN the park-active clause"
    terminal = _sql( query.clauses[ 0 ] )
    assert "task_items.status NOT IN" in terminal
    assert "'not_approved'" in terminal
    # Anchored to its place in front of the NOT(...): holding_is_active_clause repeats the same text inside the NOT,
    # so a bare substring check stayed green with the conjunct deleted (mutation arm, 2026-09-15).
    assert "status = 'not_approved' AND task_items.next_chase_ts IS NOT NULL AND NOT (" in terminal, \
        "a held row with no chase must keep holding (P0 46799ba3)"
    assert "2026-09-15 16:00:00" in terminal, "the holding clause did not use the `now` it was given"
    assert "2026-09-15 16:00:00" in _sql( query.clauses[ 1 ] )


def test_hide_parked_with_include_terminal_applies_only_the_park_active_clause():
    query = _RecordingQuery()

    TaskRepository._apply_owed_filter( query, owed_only=False, hide_parked=True, status=None,
                                       include_terminal=True, now=NOW )

    assert len( query.clauses ) == 1
    assert "NOT IN" not in _sql( query.clauses[ 0 ] ), "include_terminal must not add the terminal exclusion"


def test_an_absent_now_is_defaulted_once_to_the_current_time( monkeypatch ):
    class _Clock:
        @staticmethod
        def now( tz ):
            assert tz is timezone.utc
            return datetime( 2031, 1, 2, 3, 4, tzinfo=timezone.utc )
    monkeypatch.setattr( task_repository_module, "datetime", _Clock )
    query = _RecordingQuery()

    TaskRepository._apply_owed_filter( query, owed_only=False, hide_parked=True, status=None,
                                       include_terminal=True, now=None )

    assert "2031-01-02 03:04:00" in _sql( query.clauses[ 0 ] )


# ---------------------------------------------------------------------------
# count_tasks_by_priority / count_tasks_by_project
# ---------------------------------------------------------------------------

def _census_repo( monkeypatch, rows ):
    session = MagicMock()
    query   = session.query.return_value
    query.group_by.return_value.all.return_value = rows
    calls   = { }
    # Bound by the REAL signature, so a test reads a filter by its parameter name, never by position.
    signature = inspect.signature( TaskRepository._apply_scalar_filters )
    monkeypatch.setattr( TaskRepository, "_apply_scalar_filters",
                         staticmethod( lambda q, *args, **kwargs: calls.setdefault( "scalar", signature.bind( q, *args, **kwargs ).arguments ) and q ) )
    monkeypatch.setattr( TaskRepository, "_apply_owed_filter",
                         staticmethod( lambda q, *args: calls.setdefault( "owed", args ) and q ) )
    return TaskRepository( session ), session, query, calls


def test_count_by_priority_groups_on_PRIORITY_and_forwards_every_filter( monkeypatch ):
    repo, session, query, calls = _census_repo( monkeypatch, [ ( "P0", 2 ), ( "P2", 5 ) ] )

    result = repo.count_tasks_by_priority( owner_persona="maria", status="queued", project="lupin",
                                           owed_only=True, hide_parked=True, include_terminal=False, now=NOW )

    assert result == { "P0": 2, "P2": 5 }, "an absent priority must stay absent, never a 0 bucket"
    assert session.query.call_args.args[ 0 ] is TaskItem.priority
    assert query.group_by.call_args.args[ 0 ] is TaskItem.priority
    scalar = calls[ "scalar" ]
    assert scalar[ "owner_persona" ] == "maria" and scalar[ "status" ] == "queued" and scalar[ "project" ] == "lupin"
    assert calls[ "owed" ] == ( True, True, "queued", False, NOW )


def test_count_by_project_groups_on_PROJECT_and_never_filters_by_project( monkeypatch ):
    """The census exists to see every spelling, so the project filter slot is forced to None."""
    repo, session, query, calls = _census_repo( monkeypatch, [ ( "lupin", 7 ), ( None, 1 ) ] )

    result = repo.count_tasks_by_project( owner_persona="maria", status="queued" )

    assert result == { "lupin": 7, None: 1 }, "a NULL-project row must land under None, not vanish"
    assert session.query.call_args.args[ 0 ] is TaskItem.project
    assert query.group_by.call_args.args[ 0 ] is TaskItem.project
    scalar = calls[ "scalar" ]
    assert scalar[ "owner_persona" ] == "maria"
    assert scalar[ "project" ] is None


# ---------------------------------------------------------------------------
# count_admissions_since
# ---------------------------------------------------------------------------

def _admissions_repo( scalar ):
    session = MagicMock()
    query   = _RecordingQuery()
    query.scalar = MagicMock( return_value=scalar )
    session.query.return_value = query
    return TaskRepository( session ), query


def test_count_admissions_counts_only_real_moves_out_of_holding_by_this_actor_since_the_instant():
    repo, query = _admissions_repo( 3 )

    assert repo.count_admissions_since( "mr radio 8d83dcbb", NOW ) == 3
    sql = [ _sql( c ) for c in query.clauses ]
    assert sql[ 0 ] == "task_events.actor = 'mr radio 8d83dcbb'"
    assert sql[ 1 ].startswith( "task_events.ts >= '2026-09-15 16:00:00" )
    # The PostgreSQL dialect escapes `%` as `%%` when it inlines a literal; the pattern is still "not_approved->%".
    assert sql[ 2 ] == "task_events.transition LIKE 'not_approved->%%'"
    assert sql[ 3 ] == "task_events.transition != 'not_approved->not_approved'"


def test_count_admissions_is_zero_when_the_database_returns_NULL():
    repo, _ = _admissions_repo( None )

    assert repo.count_admissions_since( "mr radio 8d83dcbb", NOW ) == 0
