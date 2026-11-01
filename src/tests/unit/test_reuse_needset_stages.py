"""
The stage runner: four stages under one call cap, each reported.

The runner makes no model call itself. These tests hand it fake stages and a fake transport, so no model is contacted.
"""
import asyncio
import os
import subprocess
import sys

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock

from cosa.repo.doc_lint import harness_report, model_transport as mt
from cosa.repo.labelling import run_check
from lupin_mcp.reuse_needset import call_cap, hardness, loss_trace, stages
from lupin_mcp.reuse_needset import errors as er

FABLE = "claude-fable-5-1"


@pytest.fixture( autouse=True )
def no_hook_left_over():
    yield
    mt.set_charge_hook( None )


class Transport:
    """A stand-in for sdk_query that answers ok and counts the calls."""

    def __init__( self ):
        self.calls = 0

    async def __call__( self, prompt, options ):
        self.calls += 1
        yield AssistantMessage( content=[ TextBlock( "ok" ) ], model=options.model )


def spend( transport, n ):
    """Return an async stage function that makes n model calls and reports done."""
    async def stage():
        for _ in range( n ): await mt.complete( FABLE, "s", "u", query_fn=transport )
        return { "calls": n }
    return stage


def all_stages( transport, **over ):
    """Return the four stage functions, each spending one call, with some replaced."""
    base = { name: spend( transport, 1 ) for name in stages.ORDER }
    base.update( over )
    return base


def run( cap, funcs ):
    with cap.installed(): return asyncio.run( stages.run_stages( cap, funcs ) )


def new_cap( tmp_path, limit=1000 ): return call_cap.CallCap( str( tmp_path / "calls.jsonl" ), limit=limit )


def test_the_four_stages_run_in_the_plan_order_with_the_planned_allowances():
    assert stages.ORDER == ( "attribution", "yield", "control", "remainder" )
    assert stages.PLANNED_CALLS == { "attribution": 200, "yield": 300, "control": 200 } and stages.YIELD_SEEDS == 100


def test_each_stage_runs_in_order_and_its_calls_carry_its_name( tmp_path ):
    cap, transport = new_cap( tmp_path ), Transport()
    out = run( cap, all_stages( transport, **{ "attribution": spend( transport, 3 ), "control": spend( transport, 2 ) } ) )
    assert [ s[ "status" ] for s in out[ "stages" ].values() ] == [ "done" ] * 4 and list( out[ "stages" ] ) == list( stages.ORDER )
    assert out[ "by_stage" ] == { "attribution": 3, "control": 2, "remainder": 1, "yield": 1 } and out[ "used" ] == 7 and out[ "limit" ] == 1000
    assert [ r[ "stage" ] for r in cap.rows() ] == [ "attribution" ] * 3 + [ "yield" ] + [ "control" ] * 2 + [ "remainder" ]
    assert out[ "over_plan" ] == [] and out[ "stages" ][ "attribution" ][ "report" ] == { "calls": 3 }


def test_a_stage_that_reports_stop_ends_the_run_and_the_later_stages_never_start( tmp_path ):
    cap, transport = new_cap( tmp_path ), Transport()
    async def halting():
        await mt.complete( FABLE, "s", "u", query_fn=transport )
        return { "stop": True, "why": "no seed lost at any stage" }
    out = run( cap, all_stages( transport, **{ "yield": halting } ) )
    assert [ s[ "status" ] for s in out[ "stages" ].values() ] == [ "done", "stopped", "not_run", "not_run" ]
    assert transport.calls == 2 and out[ "stages" ][ "yield" ][ "report" ][ "why" ] == "no seed lost at any stage"


def test_the_cap_ending_a_stage_is_reported_by_name_and_nothing_after_it_runs( tmp_path ):
    cap, transport = new_cap( tmp_path, limit=5 ), Transport()
    out = run( cap, all_stages( transport, **{ "yield": spend( transport, 9 ) } ) )
    assert [ s[ "status" ] for s in out[ "stages" ].values() ] == [ "done", "cap_reached", "not_run", "not_run" ]
    assert out[ "stages" ][ "yield" ][ "code" ] == er.CALL_CAP_REACHED and out[ "used" ] == 5 and transport.calls == 5
    assert out[ "over_plan" ] == []


def test_any_other_named_failure_stops_the_run_with_its_code( tmp_path ):
    cap, transport = new_cap( tmp_path ), Transport()
    async def broken():
        raise er.NeedsetError( er.RECEIPT_FIELD_ABSENT, "no candidate stage" )
    out = run( cap, all_stages( transport, **{ "attribution": broken } ) )
    assert [ s[ "status" ] for s in out[ "stages" ].values() ] == [ "failed", "not_run", "not_run", "not_run" ]
    assert out[ "stages" ][ "attribution" ] == { "status": "failed", "code": er.RECEIPT_FIELD_ABSENT, "detail": "no candidate stage" } and transport.calls == 0


def test_an_error_that_is_not_a_named_one_is_never_swallowed( tmp_path ):
    cap, transport = new_cap( tmp_path ), Transport()
    async def crash():
        raise RuntimeError( "boom" )
    with pytest.raises( RuntimeError, match="boom" ): run( cap, all_stages( transport, **{ "attribution": crash } ) )


def test_a_stage_that_spends_past_its_allowance_is_listed_but_only_the_cap_stops_the_run( tmp_path ):
    cap, transport = new_cap( tmp_path ), Transport()
    out = run( cap, all_stages( transport, **{ "attribution": spend( transport, 201 ), "yield": spend( transport, 300 ) } ) )
    assert out[ "over_plan" ] == [ "attribution" ] and out[ "stages" ][ "remainder" ][ "status" ] == "done"


def test_a_missing_stage_is_refused_before_anything_runs( tmp_path ):
    cap, transport = new_cap( tmp_path ), Transport()
    funcs = all_stages( transport )
    del funcs[ "control" ]
    with pytest.raises( ValueError, match="control" ): run( cap, funcs )
    assert transport.calls == 0


def lost_record( members ): return { "kind": "work_alike", "write_lang": "py", "members": members }


def test_the_attribution_report_stops_when_no_member_was_lost_at_a_named_stage():
    some = stages.attribution_report( [ lost_record( { "a": loss_trace.FOUND, "b": loss_trace.NOT_READ } ), lost_record( { "c": loss_trace.NOT_RETRIEVED } ) ] )
    assert ( some[ "members" ], some[ "lost" ], some[ "found" ] ) == ( 3, 2, 1 ) and some[ "can_name_a_stage" ] is True and some[ "stop" ] is False
    assert some[ "by_lost_at" ] == { "FOUND": 1, "NOT_READ": 1, "NOT_RETRIEVED": 1 } and some[ "summary" ][ "members" ] == 3
    none = stages.attribution_report( [ lost_record( { "a": loss_trace.FOUND } ) ] )
    assert ( none[ "lost" ], none[ "can_name_a_stage" ], none[ "stop" ] ) == ( 0, False, True )


def entry( i, name, doc="" ): return { "id": i, "module": "m", "name": name, "sig": "()", "doc": doc }


def yield_index():
    """Return an index where "banana" ranks m.easy first and never lists m.hidden."""
    return hardness.build_index( [ entry( "m.easy", "banana_easy", "banana banana" ), entry( "m.hidden", "hidden", "turns one text into another" ) ] )


def prepare_from( table ):
    """Return an async prepare_fn that answers from a table and records the seeds asked."""
    asked = []
    async def prepare( seed_id ):
        asked.append( seed_id )
        return table[ seed_id ]
    prepare.asked = asked
    return prepare


def row( seed, target, lang ): return { "seed": seed, "need": "banana", "targets": [ target ], "lang": lang }


def test_the_yield_counts_hard_seeds_per_language_in_order_with_intervals_and_skips():
    table   = { "s1": row( "s1", "m.hidden", "py" ), "s2": row( "s2", "m.easy", "py" ), "s3": None, "s4": row( "s4", "m.hidden", "ts" ) }
    prepare = prepare_from( table )
    out     = asyncio.run( stages.run_yield( [ "s1", "s2", "s3", "s4" ], prepare, yield_index() ) )
    assert prepare.asked == [ "s1", "s2", "s3", "s4" ] and out[ "skipped" ] == 1 and out[ "seeds" ] == 3 and out[ "hard" ] == 2 and out[ "k" ] == 10
    assert out[ "by_lang" ] == { "py": { "seeds": 2, "hard": 1, "per_100": 50.0 }, "ts": { "seeds": 1, "hard": 1, "per_100": 100.0 } }
    assert out[ "intervals" ] == { "py": harness_report.interval( 1, 2 ), "ts": harness_report.interval( 1, 1 ) }
    assert out[ "stop" ] is False and out[ "short" ] == [ "py", "ts" ]


def test_a_language_with_a_hundred_seeds_and_no_hard_one_stops_the_run_and_a_short_one_does_not():
    ids   = [ f"s{n}" for n in range( 100 ) ]
    table = { i: row( i, "m.easy", "py" ) for i in ids }
    table[ "t1" ] = row( "t1", "m.hidden", "ts" )
    out = asyncio.run( stages.run_yield( ids + [ "t1" ], prepare_from( table ), yield_index() ) )
    assert out[ "by_lang" ][ "py" ][ "seeds" ] == 100 and out[ "by_lang" ][ "py" ][ "hard" ] == 0 and out[ "stop" ] is True and out[ "short" ] == [ "ts" ]
    ninety_nine = asyncio.run( stages.run_yield( ids[ :99 ], prepare_from( table ), yield_index() ) )
    assert ninety_nine[ "stop" ] is False and ninety_nine[ "short" ] == [ "py" ]


def pairs():
    """Return 20 pairs: 3 drifted, 12 unsure, 5 others, each with a marker in its original."""
    return ( [ { "id": f"d{n}", "group": "drifted", "original": f"orig-d{n}", "rewrite": f"new-d{n}" } for n in range( 3 ) ]
             + [ { "id": f"u{n}", "group": "unsure", "original": f"orig-u{n}", "rewrite": f"new-u{n}" } for n in range( 12 ) ]
             + [ { "id": f"o{n}", "group": "other", "original": f"orig-o{n}", "rewrite": f"new-o{n}" } for n in range( 5 ) ] )


def scripted_check( script ):
    """Return a check_fn that rules by the marker in the original and records what it was given."""
    seen = []
    def check( original, rewrite, seed ):
        seen.append( ( original, rewrite, seed ) )
        route = script[ original.split( "-", 1 )[ 1 ] ]
        return { "route": route, "status": "x", "reason": f"ruled {route}", "cases": 8 }
    check.seen = seen
    return check


def test_the_remainder_counts_drifted_pairs_caught_and_unsure_pairs_resolved():
    script = { **{ f"d{n}": r for n, r in enumerate( [ "reject", "reject", "accept" ] ) },
               **{ f"u{n}": r for n, r in enumerate( [ "accept" ] * 7 + [ "reject" ] * 2 + [ "person_check" ] * 3 ) },
               **{ f"o{n}": "person_check" for n in range( 5 ) } }
    check = scripted_check( script )
    out   = stages.run_remainder( pairs(), 7, check )
    assert out[ "pairs" ] == 20 and out[ "drifted" ] == { "total": 3, "caught": 2 } and out[ "unsure" ] == { "total": 12, "resolved": 9 }
    assert out[ "routes" ] == { "accept": 8, "person_check": 8, "reject": 4 } and len( out[ "per_pair" ] ) == 20
    assert check.seen[ 0 ] == ( "orig-d0", "new-d0", 7 ) and all( s[ 2 ] == 7 for s in check.seen ) and out[ "per_pair" ][ 0 ][ "reason" ] == "ruled reject"


def test_a_drifted_pair_that_goes_to_a_person_is_not_caught_and_the_default_check_is_the_run_check():
    out = stages.run_remainder( [ { "id": "d", "group": "drifted", "original": "orig-d", "rewrite": "new-d" } ], 1, scripted_check( { "d": "person_check" } ) )
    assert out[ "drifted" ] == { "total": 1, "caught": 0 } and out[ "unsure" ] == { "total": 0, "resolved": 0 }
    assert stages.run_remainder.__defaults__[ 0 ] is run_check.check_pair


def test_the_runner_loads_no_labelling_tool_and_makes_no_packet():
    src  = os.path.join( os.environ[ "LUPIN_ROOT" ], "src" )
    code = ( f"import sys; sys.path.insert( 0, {src!r} ); import lupin_mcp.reuse_needset.stages; "
             "print( sorted( m for m in sys.modules if m.startswith( 'cosa.repo.labelling.' ) and m.rsplit( '.', 1 )[ 1 ] in ( 'packets', 'confirm', 'adjudicate', 'agreement', 'pair_labels' ) ) )" )
    out  = subprocess.run( [ sys.executable, "-I", "-c", code ], capture_output=True, text=True, timeout=120 )
    assert out.returncode == 0 and out.stdout.strip().splitlines()[ -1 ] == "[]", out.stderr[ -300: ]
