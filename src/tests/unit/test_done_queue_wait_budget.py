"""
The wait for a job to reach the done queue is worked out from the queue depth.

Two waiters used to wait a fixed 30 s. In the cold run they had 11 and 8 jobs ahead of them,
at 7 to 9 s each. Their jobs finished 92 s and 55 s after submit. The budget is now the jobs ahead,
plus one, times a named ceiling. A cap fails fast and names the depth.

Venue: :7999 (unit, a stubbed /api/busy and the test file's syntax tree, no server).
"""

import ast
import os

import pytest

from tests.helpers import done_queue_budget as dqb
from tests.helpers import file_budget

PATH    = os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "tests", "integration", "test_job_queue_progressive_disclosure.py" )
WAITERS = [ "test_done_queue_metadata_includes_session_fields", "test_job_interactions_unauthorized_access" ]


def _function( name ):
    with open( PATH, encoding="utf-8" ) as handle: tree = ast.parse( handle.read() )
    found = [ n for n in ast.walk( tree ) if isinstance( n, ast.FunctionDef ) and n.name == name ]
    assert len( found ) == 1, f"expected one {name}, found {len( found )}"
    return found[ 0 ]


def _calls( function, attr ):
    return [ n for n in ast.walk( function ) if isinstance( n, ast.Call )
             and isinstance( n.func, ast.Attribute ) and n.func.attr == attr ]


# ── the arithmetic ───────────────────────────────────────────────────────────

@pytest.mark.parametrize( "ahead, expected", [ ( 0, 20 ), ( 1, 40 ), ( 14, 300 ), ( 29, 600 ) ] )
def test_the_budget_is_jobs_ahead_plus_one_times_twenty_seconds( ahead, expected ):
    assert dqb.budget_for( ahead ) == expected


def test_the_ceiling_is_twenty_seconds_and_more_than_twice_the_slowest_cold_job_measured():
    assert dqb.PER_JOB_CEILING_SECONDS == 20
    assert dqb.PER_JOB_CEILING_SECONDS >= 2 * 9


def test_one_job_over_the_cap_fails_and_the_message_names_the_depth():
    with pytest.raises( dqb.QueueTooDeep ) as caught: dqb.budget_for( 30 )
    assert "30 jobs are ahead" in str( caught.value )
    assert "620s" in str( caught.value ) and "600s cap" in str( caught.value )


def test_the_cap_sits_under_the_file_budget_so_a_runaway_queue_fails_here_first():
    assert dqb.MAX_BUDGET_SECONDS == 600
    assert dqb.MAX_BUDGET_SECONDS < file_budget.DEFAULT_MINUTES * 60


def test_a_negative_depth_is_refused():
    with pytest.raises( ValueError, match="cannot be negative" ): dqb.budget_for( -1 )


# ── reading the queue ────────────────────────────────────────────────────────

def test_jobs_ahead_is_the_run_queue_plus_the_todo_queue_and_nothing_else():
    busy = { "run_queue_size": 2, "todo_queue_size": 5, "inflight_agentic_jobs": 40, "monopolize_inflight": True }
    assert dqb.jobs_ahead( busy ) == 7


@pytest.mark.parametrize( "busy, name", [
    ( { "todo_queue_size": 1 }, "run_queue_size" ),
    ( { "run_queue_size": 1 }, "todo_queue_size" ),
    ( { "run_queue_size": None, "todo_queue_size": 1 }, "run_queue_size" ),
    ( { "run_queue_size": True, "todo_queue_size": 1 }, "run_queue_size" ),
    ( { "run_queue_size": -1, "todo_queue_size": 1 }, "run_queue_size" ),
] )
def test_a_missing_or_unusable_depth_signal_raises_and_names_the_field( busy, name ):
    with pytest.raises( ValueError, match=name ): dqb.jobs_ahead( busy )


class _Reply:
    def __init__( self, status, body ): self.status_code, self._body, self.text = status, body, str( body )
    def json( self ): return self._body


def test_budget_before_submit_reads_busy_at_the_given_server_and_returns_depth_and_budget( monkeypatch ):
    seen = { }
    def fake_get( url, timeout ):
        seen[ "url" ] = url
        return _Reply( 200, { "run_queue_size": 1, "todo_queue_size": 13 } )
    monkeypatch.setattr( dqb.requests, "get", fake_get )
    assert dqb.budget_before_submit( "http://x:1" ) == ( 14, 300 )
    assert seen[ "url" ] == "http://x:1/api/busy"


def test_budget_before_submit_fails_on_a_server_that_does_not_answer_busy( monkeypatch ):
    monkeypatch.setattr( dqb.requests, "get", lambda url, timeout: _Reply( 503, "down" ) )
    with pytest.raises( AssertionError, match="answered 503" ): dqb.budget_before_submit( "http://x:1" )


def test_budget_before_submit_raises_too_deep_on_a_runaway_queue( monkeypatch ):
    monkeypatch.setattr( dqb.requests, "get", lambda url, timeout: _Reply( 200, { "run_queue_size": 0, "todo_queue_size": 200 } ) )
    with pytest.raises( dqb.QueueTooDeep, match="200 jobs are ahead" ): dqb.budget_before_submit( "http://x:1" )


# ── the two waiters in the integration file ──────────────────────────────────

@pytest.mark.parametrize( "name", WAITERS )
def test_each_waiter_waits_for_the_budget_and_never_for_a_literal_number( name ):
    waits = _calls( _function( name ), "_wait_for_jobs_in_done_queue" )
    assert len( waits ) == 1
    keywords = { k.arg: k.value for k in waits[ 0 ].keywords }
    assert isinstance( keywords[ "timeout_seconds" ], ast.Name ) and keywords[ "timeout_seconds" ].id == "budget"
    assert not any( isinstance( a, ast.Constant ) and isinstance( a.value, ( int, float ) ) and a.value > 1 for a in waits[ 0 ].args )


@pytest.mark.parametrize( "name", WAITERS )
def test_each_waiter_reads_the_queue_depth_before_it_submits( name ):
    function = _function( name )
    reads, submits = _calls( function, "_budget_before_submit" ), _calls( function, "_submit_job" )
    assert len( reads ) == 1 and len( submits ) == 1
    assert reads[ 0 ].lineno < submits[ 0 ].lineno


def _stores_of_budget( function ):
    """Every place the function binds the name budget, by any construct."""
    return [ n for n in ast.walk( function ) if isinstance( n, ast.Name ) and n.id == "budget" and isinstance( n.ctx, ast.Store ) ]


@pytest.mark.parametrize( "name", WAITERS )
def test_budget_is_bound_once_and_only_from_the_queue_depth_read( name ):
    function = _function( name )
    assert len( _stores_of_budget( function ) ) == 1, "budget is bound more than once, so a literal could replace the read"
    assigns = [ n for n in ast.walk( function ) if isinstance( n, ast.Assign )
                and any( isinstance( t, ast.Tuple ) and any( isinstance( e, ast.Name ) and e.id == "budget" for e in t.elts ) for t in n.targets ) ]
    assert len( assigns ) == 1
    value = assigns[ 0 ].value
    assert isinstance( value, ast.Call ) and isinstance( value.func, ast.Attribute ) and value.func.attr == "_budget_before_submit"
    assert [ e.id for e in assigns[ 0 ].targets[ 0 ].elts ] == [ "ahead", "budget" ]
