"""
The agent probe is counted: every attempt is charged, and no stage reaches it uncounted.

Rachel's finding: trace_all defaults to the probe, which calls the SDK directly. Nothing wrapped it, so its calls fell outside the 1,000.
"""
import asyncio

import pytest

from lupin_mcp.reuse_needset import agent_probe as ap
from lupin_mcp.reuse_needset import call_cap, errors as er
from tests.unit.test_reuse_needset_agent_probe import GOOD, RESULT, assistant, done, stream_of
from claude_agent_sdk import TextBlock

UNCLEAR = [ assistant( TextBlock( text="I could not tell" ) ), done() ]
RULED   = [ assistant( TextBlock( text=GOOD ) ), done() ]


def probe( query ): return asyncio.run( ap.run_probe( "n", RESULT, "/t", "claude-opus-5-5", query_fn=query ) )


def new_cap( tmp_path, limit=1000 ): return call_cap.CallCap( str( tmp_path / "calls.jsonl" ), limit=limit )


def test_each_probe_attempt_is_charged_so_a_retry_counts_as_a_call( tmp_path ):
    cap, query = new_cap( tmp_path ), stream_of( UNCLEAR, RULED )
    with cap.installed(), call_cap.stage( "attribution" ): out = probe( query )
    assert out[ "rulings" ] and len( query.calls ) == 2 and cap.used() == 2 and cap.by_stage() == { "attribution": 2 }
    assert [ r[ "model" ] for r in cap.rows() ] == [ "claude-opus-5-5" ] * 2


def test_a_probe_that_rules_on_the_first_attempt_is_charged_once( tmp_path ):
    cap, query = new_cap( tmp_path ), stream_of( RULED )
    with cap.installed(): probe( query )
    assert cap.used() == 1 and len( query.calls ) == 1


def test_the_1001st_probe_attempt_is_refused_by_name_and_the_stream_never_starts( tmp_path ):
    cap, query = new_cap( tmp_path ), stream_of( RULED )
    for _ in range( 1000 ): cap.charge( "claude-fable-5-1" )
    with cap.installed(), pytest.raises( er.NeedsetError ) as caught: probe( query )
    assert caught.value.code == er.CALL_CAP_REACHED and query.calls == [] and cap.used() == 1000


def test_a_cap_that_runs_out_between_the_two_attempts_stops_the_retry( tmp_path ):
    cap, query = new_cap( tmp_path, limit=1 ), stream_of( UNCLEAR, RULED )
    with cap.installed(), pytest.raises( er.NeedsetError ) as caught: probe( query )
    assert caught.value.code == er.CALL_CAP_REACHED and len( query.calls ) == 1 and cap.used() == 1


def test_a_probe_inside_a_stage_with_no_cap_installed_is_refused_by_name_and_makes_no_call():
    query = stream_of( RULED )
    with call_cap.stage( "attribution" ), pytest.raises( er.NeedsetError ) as caught: probe( query )
    assert caught.value.code == er.CAP_NOT_INSTALLED and "attribution" in caught.value.detail and query.calls == []


def test_outside_any_stage_and_with_no_cap_the_probe_runs_as_it_always_did():
    query = stream_of( RULED )
    assert probe( query )[ "rulings" ] and len( query.calls ) == 1


def test_the_default_probe_is_counted_when_a_stage_function_calls_it_under_the_runner( tmp_path ):
    from lupin_mcp.reuse_needset import stages
    cap, query = new_cap( tmp_path ), stream_of( UNCLEAR, RULED )
    async def attribution():
        await ap.run_probe( "n", RESULT, "/t", "claude-opus-5-5", query_fn=query )
        return {}
    async def nothing(): return {}
    with cap.installed(): out = asyncio.run( stages.run_stages( cap, { "attribution": attribution, "yield": nothing, "control": nothing, "remainder": nothing } ) )
    assert out[ "by_stage" ] == { "attribution": 2 } and out[ "used" ] == 2
