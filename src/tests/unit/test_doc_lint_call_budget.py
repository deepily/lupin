"""
The per-model call cap: it refuses before any model is contacted, counts from a ledger file, and prints its figures.

Every test stands a fake transport in for the SDK and counts the calls it saw, so a cap that
refused too late or too early would show in that count and not only in an exception.
"""

import asyncio
import json
import multiprocessing
import os
import queue as std_queue
import time

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from cosa.repo.doc_lint import harness_cli
from cosa.repo.doc_lint import model_transport as mt

FABLE = "claude-fable-5-1"
SONNET = "claude-sonnet-5-5"


@pytest.fixture( autouse=True )
def no_budget_left_over():
    mt.set_budget( None, {} )
    yield
    mt.set_budget( None, {} )


class Transport:
    """A stand-in for sdk_query that answers ok and remembers which model each call asked for."""

    def __init__( self ):
        self.seen = []

    async def __call__( self, prompt, options ):
        self.seen.append( options.model )
        yield AssistantMessage( content=[ TextBlock( "ok" ) ], model=options.model )


def call( model, transport ):
    return asyncio.run( mt.complete( model, "system", "user", query_fn=transport ) )


def test_a_cap_of_n_allows_exactly_n_calls_and_refuses_the_next_without_contacting_the_model( tmp_path ):
    mt.set_budget( str( tmp_path / "calls.jsonl" ), { FABLE: 3 } )
    transport = Transport()
    assert [ call( FABLE, transport ) for _ in range( 3 ) ] == [ "ok", "ok", "ok" ]
    with pytest.raises( mt.CallBudgetExceeded, match="used 3 of its 3 calls" ):
        call( FABLE, transport )
    assert transport.seen == [ FABLE ] * 3
    assert mt.calls_used( FABLE ) == 3


def test_a_restart_with_a_ledger_holding_n_rows_refuses_at_once_and_a_counter_in_memory_is_not_used( tmp_path ):
    path = tmp_path / "calls.jsonl"
    path.write_text( "".join( json.dumps( { "model": FABLE, "n": n } ) + "\n" for n in range( 1, 3 ) ) )
    mt.set_budget( str( path ), { FABLE: 2 } )
    transport = Transport()
    with pytest.raises( mt.CallBudgetExceeded ):
        call( FABLE, transport )
    assert transport.seen == []
    mt.set_budget( str( path ), { FABLE: 3 } )
    assert call( FABLE, transport ) == "ok" and transport.seen == [ FABLE ]


def test_each_model_id_has_its_own_count_and_an_uncapped_model_is_never_charged( tmp_path ):
    path = tmp_path / "calls.jsonl"
    mt.set_budget( str( path ), { FABLE: 1, "claude-opus-5-5": 1 } )
    transport = Transport()
    call( FABLE, transport )
    call( "claude-opus-5-5", transport )
    for _ in range( 3 ): call( SONNET, transport )
    with pytest.raises( mt.CallBudgetExceeded ): call( FABLE, transport )
    with pytest.raises( mt.CallBudgetExceeded ): call( "claude-opus-5-5", transport )
    assert transport.seen == [ FABLE, "claude-opus-5-5", SONNET, SONNET, SONNET ]
    assert [ json.loads( l )[ "model" ] for l in path.read_text().splitlines() ] == [ FABLE, "claude-opus-5-5" ]


def test_a_call_that_fails_still_counts_because_it_was_charged_before_the_model_was_contacted( tmp_path ):
    mt.set_budget( str( tmp_path / "calls.jsonl" ), { FABLE: 2 } )
    async def broken( prompt, options ):
        yield ResultMessage( subtype="error", duration_ms=1, duration_api_ms=1, is_error=True, num_turns=1, session_id="s", result="boom" )
    with pytest.raises( mt.ModelCallError ):
        asyncio.run( mt.complete( FABLE, "s", "u", query_fn=broken ) )
    assert mt.calls_used( FABLE ) == 1
    transport = Transport()
    call( FABLE, transport )
    with pytest.raises( mt.CallBudgetExceeded ): call( FABLE, transport )


def test_the_refusal_is_not_a_model_call_error_so_a_retry_loop_cannot_swallow_it():
    assert not issubclass( mt.CallBudgetExceeded, mt.ModelCallError )


def test_a_cap_of_zero_refuses_the_first_call( tmp_path ):
    mt.set_budget( str( tmp_path / "calls.jsonl" ), { FABLE: 0 } )
    transport = Transport()
    with pytest.raises( mt.CallBudgetExceeded ): call( FABLE, transport )
    assert transport.seen == [] and ( tmp_path / "calls.jsonl" ).read_text() == ""


def test_the_count_and_cap_are_readable_and_a_torn_or_missing_ledger_is_handled( tmp_path ):
    path = tmp_path / "calls.jsonl"
    assert mt.calls_used( FABLE, str( path ) ) == 0
    path.write_text( json.dumps( { "model": FABLE } ) + "\n" + json.dumps( { "model": SONNET } ) + "\n" + '{"model": "claude-fab' )
    assert mt.calls_used( FABLE, str( path ) ) == 1 and mt.calls_used( SONNET, str( path ) ) == 1
    assert mt.budget_summary() == {}
    mt.set_budget( str( path ), { FABLE: 5 } )
    assert mt.budget_summary() == { FABLE: { "used": 1, "cap": 5 } }
    mt.set_budget( None, {} )
    assert mt.calls_used( FABLE ) == 0


@pytest.mark.parametrize( "caps, path, why", [
    ( { FABLE: -1 }, "x", "int of zero or more" ),
    ( { FABLE: 1.5 }, "x", "int of zero or more" ),
    ( { FABLE: True }, "x", "int of zero or more" ),
    ( { "": 1 }, "x", "needs a model id" ),
    ( { FABLE: 1 }, None, "need a ledger path" ),
] )
def test_a_bad_cap_is_refused_and_leaves_no_cap_set( tmp_path, caps, path, why ):
    with pytest.raises( ValueError, match=why ):
        mt.set_budget( None if path is None else str( tmp_path / path ), caps )
    assert mt.BUDGET_CAPS == {}


def test_a_ledger_in_a_missing_directory_is_refused( tmp_path ):
    with pytest.raises( ValueError, match="does not exist" ):
        mt.set_budget( str( tmp_path / "nope" / "calls.jsonl" ), { FABLE: 1 } )


def _take( path, queue ):
    try:
        mt.set_budget( path, { FABLE: 5 } )
        async def transport( prompt, options ):
            yield AssistantMessage( content=[ TextBlock( "ok" ) ], model=options.model )
        got = 0
        for _ in range( 3 ):
            try:
                asyncio.run( mt.complete( FABLE, "s", "u", query_fn=transport ) )
                got += 1
            except mt.CallBudgetExceeded:
                pass
        queue.put( ( "ok", got ) )
    except Exception as e:
        queue.put( ( "error", repr( e ) ) )


def collect_children( procs, queue, what, timeout=30.0 ):
    """
    Gather one result per child process, or fail the test naming what it waited for; leave no child running.

    Requires:
        - procs are started multiprocessing.Process objects, each putting exactly one tuple on queue
        - what is a phrase naming the result awaited, for the failure message

    Ensures:
        - returns the list of ( "ok", value ) results once every child has reported
        - a child that ends without reporting fails the test within about a second, naming its pid and exit code
        - no result within timeout seconds fails the test, naming what was waited for
        - on every path, each child still alive is killed and joined before this returns or fails
    """
    deadline, results = time.monotonic() + timeout, []
    try:
        while len( results ) < len( procs ):
            try:
                results.append( queue.get( timeout=1.0 ) )
            except std_queue.Empty:
                gone = [ p for p in procs if p.exitcode is not None and p.exitcode != 0 ]
                if gone: pytest.fail( f"waiting for {what}: child pid {gone[ 0 ].pid} ended with exit code {gone[ 0 ].exitcode} without reporting ({len( results )} of {len( procs )} reported)", pytrace=False )
                if time.monotonic() > deadline: pytest.fail( f"waiting for {what}: {len( results )} of {len( procs )} children reported within {timeout} s", pytrace=False )
        errors = [ r[ 1 ] for r in results if r[ 0 ] == "error" ]
        if errors: pytest.fail( f"waiting for {what}: a child raised {errors[ 0 ]}", pytrace=False )
        return results
    finally:
        for p in procs:
            if p.is_alive(): p.kill()
            p.join( timeout=10.0 )


def test_two_processes_sharing_a_ledger_cannot_both_take_the_last_calls( tmp_path ):
    path  = str( tmp_path / "calls.jsonl" )
    ctx   = multiprocessing.get_context( "fork" )
    queue = ctx.Queue()
    procs = [ ctx.Process( target=_take, args=( path, queue ) ) for _ in range( 3 ) ]
    for p in procs: p.start()
    results = collect_children( procs, queue, "the three ledger children's call counts" )
    assert sum( r[ 1 ] for r in results ) == 5 and mt.calls_used( FABLE, path ) == 5


def _dies_without_reporting( queue ):
    os._exit( 3 )


def _hangs( queue ):
    time.sleep( 600 )


def _raises( queue ):
    queue.put( ( "error", "RuntimeError('boom')" ) )


def test_a_child_that_dies_without_reporting_fails_the_wait_fast_and_names_it():
    ctx   = multiprocessing.get_context( "fork" )
    queue = ctx.Queue()
    procs = [ ctx.Process( target=_dies_without_reporting, args=( queue, ) ) ]
    procs[ 0 ].start()
    started = time.monotonic()
    with pytest.raises( BaseException ) as caught:
        collect_children( procs, queue, "the dying child's count", timeout=30.0 )
    assert time.monotonic() - started < 10.0 and not procs[ 0 ].is_alive()
    assert "the dying child's count" in str( caught.value ) and "exit code 3" in str( caught.value ) and "0 of 1 reported" in str( caught.value )


def test_a_child_that_never_answers_fails_the_wait_at_the_timeout_and_is_killed():
    ctx   = multiprocessing.get_context( "fork" )
    queue = ctx.Queue()
    procs = [ ctx.Process( target=_hangs, args=( queue, ) ) ]
    procs[ 0 ].start()
    started = time.monotonic()
    with pytest.raises( BaseException ) as caught:
        collect_children( procs, queue, "the sleeping child's count", timeout=2.0 )
    assert 2.0 <= time.monotonic() - started < 10.0 and not procs[ 0 ].is_alive()
    assert "the sleeping child's count" in str( caught.value ) and "0 of 1 children reported within 2.0 s" in str( caught.value )


def test_a_child_that_reports_an_error_fails_the_wait_with_its_message():
    ctx   = multiprocessing.get_context( "fork" )
    queue = ctx.Queue()
    procs = [ ctx.Process( target=_raises, args=( queue, ) ) ]
    procs[ 0 ].start()
    with pytest.raises( BaseException ) as caught:
        collect_children( procs, queue, "the raising child's count" )
    assert "a child raised RuntimeError('boom')" in str( caught.value ) and not procs[ 0 ].is_alive()


# ---- the command line prints the count and the cap ----------------------------------------------

def cli_run( tmp_path, extra, query_fn ):
    pair = { "id": "p", "old": "Returns None when the row is parked.\nRaises ValueError if the id is blank.", "new": "x", "design": None, "seed_span": None }
    ( tmp_path / "pairs.json" ).write_text( json.dumps( [ pair ] ) )
    argv = [ "--pairs", str( tmp_path / "pairs.json" ), "--ledger", str( tmp_path / "l" ), "--out", str( tmp_path / "out.json" ),
             "--extractor-model", FABLE, "--judge-model", "judge-m", "--escalation-model", "esc-m", "--writer-model", "writer-m", "--extractor-lists", "1", "--judge-runs", "1" ] + extra
    return harness_cli.main( argv, query_fn=query_fn )


def test_the_command_line_caps_a_model_and_prints_its_count_and_cap( tmp_path, capsys ):
    class Quoting:
        async def __call__( self, prompt, options ):
            yield AssistantMessage( content=[ TextBlock( '{"claims": [], "verdicts": []}' ) ], model=options.model )
    code = cli_run( tmp_path, [ "--call-ledger", str( tmp_path / "calls.jsonl" ), "--model-cap", f"{FABLE}=40" ], Quoting() )
    assert code == 0
    written = json.loads( ( tmp_path / "out.json" ).read_text() )
    assert written[ "call_budget" ] == { FABLE: { "used": mt.calls_used( FABLE, str( tmp_path / "calls.jsonl" ) ), "cap": 40 } }
    assert written[ "call_budget" ][ FABLE ][ "used" ] >= 1
    assert f"call budget {FABLE}: {written[ 'call_budget' ][ FABLE ][ 'used' ]} of 40 calls used" in capsys.readouterr().out


def test_the_command_line_refuses_a_bad_cap_and_a_cap_without_a_ledger( tmp_path, capsys ):
    assert cli_run( tmp_path, [ "--model-cap", f"{FABLE}=3" ], Transport() ) == 2
    assert cli_run( tmp_path, [ "--call-ledger", str( tmp_path / "c.jsonl" ), "--model-cap", f"{FABLE}=many" ], Transport() ) == 2
    assert cli_run( tmp_path, [ "--call-ledger", str( tmp_path / "c.jsonl" ), "--model-cap", f"{FABLE}=-2" ], Transport() ) == 2
    assert capsys.readouterr().err.count( "REFUSED" ) == 3


def test_a_run_without_caps_reports_an_empty_budget( tmp_path ):
    assert cli_run( tmp_path, [], Transport() ) == 0
    assert json.loads( ( tmp_path / "out.json" ).read_text() )[ "call_budget" ] == {}


def test_a_capped_call_takes_the_exclusive_file_lock_and_an_uncapped_call_does_not( tmp_path, monkeypatch ):
    locks = []
    real  = mt.fcntl.flock
    monkeypatch.setattr( mt.fcntl, "flock", lambda f, how: ( locks.append( how ), real( f, how ) )[ 1 ] )
    mt.set_budget( str( tmp_path / "calls.jsonl" ), { FABLE: 2 } )
    transport = Transport()
    call( SONNET, transport )
    assert locks == []
    call( FABLE, transport )
    assert locks == [ mt.fcntl.LOCK_EX ]


# ---- Tiberius's three asks (row c020773b) ------------------------------------------------------

def test_a_ledger_torn_without_a_newline_does_not_hide_the_next_charge_so_the_cap_holds( tmp_path ):
    path = tmp_path / "calls.jsonl"
    path.write_text( json.dumps( { "model": FABLE, "n": 1 } ) + "\n" + '{"model": "claude-fab' )
    mt.set_budget( str( path ), { FABLE: 2 } )
    transport = Transport()
    assert call( FABLE, transport ) == "ok"
    with pytest.raises( mt.CallBudgetExceeded ): call( FABLE, transport )
    assert transport.seen == [ FABLE ] and mt.calls_used( FABLE ) == 2
    lines = path.read_text().split( "\n" )
    assert lines[ 1 ] == '{"model": "claude-fab' and json.loads( lines[ 2 ] )[ "n" ] == 2 and lines[ 3 ] == ""


def test_a_ledger_that_ends_in_a_newline_gets_no_extra_blank_line_and_a_multibyte_torn_tail_is_handled( tmp_path ):
    path = tmp_path / "calls.jsonl"
    mt.set_budget( str( path ), { FABLE: 9 } )
    transport = Transport()
    call( FABLE, transport )
    call( FABLE, transport )
    assert path.read_text().count( "\n" ) == 2 and "\n\n" not in path.read_text()
    path.write_bytes( path.read_bytes() + '{"model": "café'.encode( "utf-8" )[ :-1 ] )
    call( FABLE, transport )
    assert mt.calls_used( FABLE ) == 3


def test_model_ids_that_share_a_prefix_are_counted_apart( tmp_path ):
    mt.set_budget( str( tmp_path / "calls.jsonl" ), { FABLE: 1, FABLE + "x": 1 } )
    transport = Transport()
    call( FABLE + "x", transport )
    call( FABLE, transport )
    with pytest.raises( mt.CallBudgetExceeded ): call( FABLE, transport )
    with pytest.raises( mt.CallBudgetExceeded ): call( FABLE + "x", transport )
    assert mt.calls_used( FABLE ) == 1 and mt.calls_used( FABLE + "x" ) == 1


def test_the_guard_fails_a_test_that_reaches_the_real_sdk_and_an_except_exception_cannot_swallow_it():
    with pytest.raises( BaseException ) as caught:
        asyncio.run( mt.complete( "m", "s", "u" ) )
    assert not isinstance( caught.value, Exception ) and "reached the real SDK" in str( caught.value )


def test_a_test_may_put_its_own_stand_in_for_the_sdk_after_the_guard( monkeypatch ):
    seen = []
    async def stand_in( prompt, options ):
        seen.append( options.model )
        yield AssistantMessage( content=[ TextBlock( "ok" ) ], model=options.model )
    monkeypatch.setattr( mt, "sdk_query", stand_in )
    assert asyncio.run( mt.complete( "m", "s", "u" ) ) == "ok" and seen == [ "m" ]
