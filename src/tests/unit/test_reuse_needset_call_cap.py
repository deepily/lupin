"""
The shared call cap: 1,000 model calls in all, refused by name at call 1,001.

Fable drafting, the checker's judge and the agent probe are different doors to a model. The cap counts all of them,
whichever stage makes the call, and a restarted run keeps the count because it lives in the file.
"""
import asyncio
import json
import multiprocessing

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock

from cosa.repo.doc_lint import model_transport as mt
from lupin_mcp.reuse_needset import call_cap, errors as er

FABLE = "claude-fable-5-1"
OPUS  = "claude-opus-5-5"


@pytest.fixture( autouse=True )
def no_hook_left_over():
    yield
    mt.set_charge_hook( None )
    mt.set_budget( None, {} )


class Transport:
    """A stand-in for sdk_query that answers ok and remembers each model asked."""

    def __init__( self ):
        self.seen = []

    async def __call__( self, prompt, options ):
        self.seen.append( options.model )
        yield AssistantMessage( content=[ TextBlock( "ok" ) ], model=options.model )


def call( model, transport ):
    return asyncio.run( mt.complete( model, "system", "user", query_fn=transport ) )


def test_the_limit_is_one_thousand():
    assert call_cap.CALL_LIMIT == 1000


def test_call_1001_is_refused_by_name_and_no_model_is_contacted( tmp_path ):
    cap, transport = call_cap.CallCap( str( tmp_path / "calls.jsonl" ) ), Transport()
    with cap.installed():
        with call_cap.stage( "bulk" ):
            for _ in range( 1000 ): call( FABLE, transport )
        assert cap.used() == 1000 and len( transport.seen ) == 1000
        with pytest.raises( er.NeedsetError ) as caught: call( FABLE, transport )
    assert caught.value.code == er.CALL_CAP_REACHED and "1000 of 1000" in caught.value.detail
    assert len( transport.seen ) == 1000 and cap.used() == 1000


def test_every_door_to_a_model_shares_one_count_whatever_the_model_or_the_stage( tmp_path ):
    cap, transport = call_cap.CallCap( str( tmp_path / "calls.jsonl" ), limit=4 ), Transport()
    probe_log = []
    async def probe( need ):
        probe_log.append( need )
        return "ruled"
    with cap.installed():
        with call_cap.stage( "drafting" ): call( FABLE, transport )
        with call_cap.stage( "judge" ): call( FABLE, transport )
        with call_cap.stage( "probe" ):
            assert asyncio.run( cap.guard( probe, OPUS )( "need one" ) ) == "ruled"
            call( OPUS, transport )
        with pytest.raises( er.NeedsetError ): call( FABLE, transport )
        with pytest.raises( er.NeedsetError ): asyncio.run( cap.guard( probe, OPUS )( "need two" ) )
    assert cap.by_stage() == { "drafting": 1, "judge": 1, "probe": 2 }
    assert [ r[ "model" ] for r in cap.rows() ] == [ FABLE, FABLE, OPUS, OPUS ] and [ r[ "n" ] for r in cap.rows() ] == [ 1, 2, 3, 4 ]
    assert probe_log == [ "need one" ] and transport.seen == [ FABLE, FABLE, OPUS ]


def test_a_new_cap_over_the_same_file_keeps_the_count_so_a_resumed_run_cannot_pass_the_limit( tmp_path ):
    path = str( tmp_path / "calls.jsonl" )
    first, transport = call_cap.CallCap( path, limit=3 ), Transport()
    with first.installed():
        call( FABLE, transport )
        call( FABLE, transport )
    second = call_cap.CallCap( path, limit=3 )
    assert second.used() == 2
    with second.installed():
        call( FABLE, transport )
        with pytest.raises( er.NeedsetError ): call( FABLE, transport )
    assert len( transport.seen ) == 3


def test_a_restart_after_37_calls_is_refused_at_1000_minus_37( tmp_path ):
    path  = str( tmp_path / "calls.jsonl" )
    first = call_cap.CallCap( path )
    for _ in range( 37 ): first.charge( FABLE )
    restarted = call_cap.CallCap( path )
    assert restarted.used() == 37
    for _ in range( 1000 - 37 ): restarted.charge( FABLE )
    with pytest.raises( er.NeedsetError ) as caught: restarted.charge( FABLE )
    assert caught.value.code == er.CALL_CAP_REACHED and restarted.used() == 1000 and [ r[ "n" ] for r in restarted.rows() ] == list( range( 1, 1001 ) )


def test_a_limit_of_zero_refuses_the_first_call( tmp_path ):
    cap, transport = call_cap.CallCap( str( tmp_path / "calls.jsonl" ), limit=0 ), Transport()
    with cap.installed(), pytest.raises( er.NeedsetError ) as caught: call( FABLE, transport )
    assert caught.value.code == er.CALL_CAP_REACHED and transport.seen == [] and cap.rows() == []


def test_a_call_with_no_stage_is_counted_under_the_unstaged_name_and_a_block_restores_the_earlier_stage( tmp_path ):
    cap = call_cap.CallCap( str( tmp_path / "calls.jsonl" ) )
    cap.charge( FABLE )
    with call_cap.stage( "outer" ):
        with call_cap.stage( "inner" ): cap.charge( FABLE )
        cap.charge( FABLE )
    with pytest.raises( RuntimeError ):
        with call_cap.stage( "broken" ): raise RuntimeError( "boom" )
    cap.charge( FABLE )
    assert [ r[ "stage" ] for r in cap.rows() ] == [ "unstaged", "inner", "outer", "unstaged" ]


def test_a_ledger_that_does_not_exist_yet_counts_zero( tmp_path ):
    cap = call_cap.CallCap( str( tmp_path / "calls.jsonl" ) )
    assert cap.rows() == [] and cap.used() == 0 and cap.by_stage() == {}


def test_a_stage_needs_a_name_and_a_charge_needs_a_model():
    with pytest.raises( ValueError ), call_cap.stage( "" ): pass
    with pytest.raises( ValueError ): call_cap.CallCap( "/tmp/x.jsonl" ).charge( "" )


@pytest.mark.parametrize( "limit", [ -1, 1.5, True, "3" ] )
def test_a_limit_must_be_an_int_of_zero_or_more( tmp_path, limit ):
    with pytest.raises( ValueError ): call_cap.CallCap( str( tmp_path / "calls.jsonl" ), limit=limit )


def test_a_ledger_in_a_missing_directory_is_refused( tmp_path ):
    with pytest.raises( ValueError ): call_cap.CallCap( str( tmp_path / "gone" / "calls.jsonl" ) )


def test_a_torn_last_line_is_not_counted_and_cannot_hide_the_next_row( tmp_path ):
    path = tmp_path / "calls.jsonl"
    path.write_text( json.dumps( { "n": 1, "stage": "s", "model": FABLE } ) + "\n" + '{"n": 2, "sta' )
    cap = call_cap.CallCap( str( path ), limit=5 )
    assert cap.used() == 1
    cap.charge( FABLE )
    assert cap.used() == 2 and [ r[ "n" ] for r in cap.rows() ] == [ 1, 2 ]


def test_the_hook_that_was_set_before_comes_back_and_the_per_model_cap_still_applies( tmp_path ):
    seen = []
    mt.set_charge_hook( seen.append )
    cap = call_cap.CallCap( str( tmp_path / "calls.jsonl" ) )
    with cap.installed(): pass
    assert mt.CHARGE_HOOK == seen.append
    mt.set_budget( str( tmp_path / "per-model.jsonl" ), { FABLE: 1 } )
    transport = Transport()
    call( FABLE, transport )
    with pytest.raises( mt.CallBudgetExceeded ): call( FABLE, transport )
    assert seen == [ FABLE, FABLE ]


def take_one( path, out ):
    """Charge one call to the ledger at path and put True on the queue if it was allowed."""
    try:
        call_cap.CallCap( path, limit=10 ).charge( FABLE )
        out.put( True )
    except er.NeedsetError:
        out.put( False )


def test_two_processes_cannot_both_take_the_last_call( tmp_path ):
    path, out = str( tmp_path / "calls.jsonl" ), multiprocessing.Queue()
    ctx       = multiprocessing.get_context( "fork" )
    procs     = [ ctx.Process( target=take_one, args=( path, out ) ) for _ in range( 16 ) ]
    for p in procs: p.start()
    for p in procs: p.join()
    answers = [ out.get() for _ in procs ]
    assert answers.count( True ) == 10 and answers.count( False ) == 6 and call_cap.CallCap( path, limit=10 ).used() == 10


class Busy:
    """A stand-in for one agy try that answers unavailable until the given try, then answers."""

    def __init__( self, answer_on ):
        self.tries, self.answer_on = 0, answer_on

    def __call__( self, model, prompt, timeout_seconds ):
        self.tries += 1
        if self.tries < self.answer_on: raise mt.agy_runtime.AgyUnavailable( "busy" )
        return "answer"


def quick_waits( monkeypatch, once, cut_short=False ):
    """Put the agy retry under test: no real waits, and a stand-in for the single try."""
    monkeypatch.setattr( mt, "_agy_call_once", once )
    monkeypatch.setattr( mt, "AGY_UNAVAILABLE_WAITS", ( 0, 0 ) )
    monkeypatch.setattr( mt, "AGY_SLEEP", lambda wait: cut_short )


def test_each_retried_agy_try_is_charged_after_its_wait( tmp_path, monkeypatch ):
    cap, once = call_cap.CallCap( str( tmp_path / "calls.jsonl" ), limit=3 ), Busy( answer_on=3 )
    quick_waits( monkeypatch, once )
    with cap.installed():
        cap.charge( FABLE )          # the first try, which complete charges before _agy_call runs
        text, _ = mt._agy_call( FABLE, "p", 5 )
    assert text == "answer" and once.tries == 3 and cap.used() == 3


def test_the_cap_can_stop_an_agy_retry_before_the_try_is_made( tmp_path, monkeypatch ):
    cap, once = call_cap.CallCap( str( tmp_path / "calls.jsonl" ), limit=2 ), Busy( answer_on=9 )
    quick_waits( monkeypatch, once )
    with cap.installed():
        cap.charge( FABLE )
        with pytest.raises( er.NeedsetError ) as caught: mt._agy_call( FABLE, "p", 5 )
    assert caught.value.code == er.CALL_CAP_REACHED and once.tries == 2 and cap.used() == 2


def test_a_wait_cut_short_charges_nothing_more( tmp_path, monkeypatch ):
    cap, once = call_cap.CallCap( str( tmp_path / "calls.jsonl" ) ), Busy( answer_on=9 )
    quick_waits( monkeypatch, once, cut_short=True )
    with cap.installed():
        cap.charge( FABLE )
        with pytest.raises( mt.ModelWaitCutShort ): mt._agy_call( FABLE, "p", 5 )
    assert once.tries == 1 and cap.used() == 1
