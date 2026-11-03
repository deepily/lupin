"""
The judge's reading of each control entry, from tap to row to file.

The tap is checked over reuse_pack.packed_sweeper with the stand-in transport of test_reuse_pack_send.
"""
import asyncio
import json

import pytest

from cosa.repo.symindex.candidates import candidate_stage as cs

from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_tools as rt
from lupin_mcp.reuse_needset import control_report as cr
from lupin_mcp.reuse_needset import first_thousand as ft
from lupin_mcp.reuse_needset import judge_readings as jr
from tests.unit.test_reuse_pack_send import ENTRIES, NEED, PROBS, Fake
from tests.unit.test_reuse_needset_control_report import answer_of, real_pair, receipt


def context( tmp_path, transport, packed=True ):
    """Return a real reuse context, packed or one request per entry."""
    kw = { "sweeper": rp.packed_sweeper( 3, shape=rp.SHAPE_WHOLE ), "request_shape": rp.SHAPE_WHOLE } if packed else { }
    return rt.ReuseContext( tmp_path, tmp_path / "data", out_dir=tmp_path / "out", transport=transport, **kw )


def test_the_tap_returns_what_the_wrapped_sweeper_returns_and_records_keys_and_answers( tmp_path ):
    ctx    = context( tmp_path, Fake() )
    tap    = jr.SweepTap( ctx )
    out    = tap( ctx, NEED, ENTRIES[ :4 ] )
    plain  = rp.packed_sweeper( 3, shape=rp.SHAPE_WHOLE )( context( tmp_path, Fake() ), NEED, ENTRIES[ :4 ] )
    assert [ a[ "id" ] for a in out[ "answers" ] ] == [ a[ "id" ] for a in plain[ "answers" ] ] and out[ "failed" ] == plain[ "failed" ]
    sweep, = tap.sweeps
    assert sorted( sweep[ "keys" ] ) == sorted( e[ "id" ] for e in ENTRIES[ :4 ] ) and sweep[ "answers" ][ ENTRIES[ 0 ][ "id" ] ] == PROBS
    assert sweep[ "keys" ][ ENTRIES[ 0 ][ "id" ] ] == rp.candidate_key( NEED, rt.entry_text( ENTRIES[ 0 ] ), ctx.template, ctx.model, rp.SHAPE_WHOLE ), "the key is the one the cache holds"


def test_the_tap_records_an_entry_the_sweep_could_not_answer( tmp_path ):
    ctx = context( tmp_path, Fake( omit=[ ENTRIES[ 1 ][ "id" ] ] ) )
    tap = jr.SweepTap( ctx )
    tap( ctx, NEED, ENTRIES[ :3 ] )
    sweep, = tap.sweeps
    missing = ENTRIES[ 1 ][ "id" ]
    assert missing in sweep[ "keys" ] and missing not in sweep[ "answers" ] and missing in sweep[ "failed" ] + sweep[ "not_reached" ]
    assert jr.judge_reading( missing, tap.sweeps, True )[ "status" ] == jr.NOT_JUDGED and jr.judge_reading( ENTRIES[ 0 ][ "id" ], tap.sweeps, True )[ "status" ] == jr.JUDGED


def test_the_tap_over_the_one_request_path_keys_each_entry_by_its_request_hash( tmp_path ):
    ctx = context( tmp_path, Fake(), packed=False )
    tap = jr.SweepTap( ctx )
    assert ctx.sweeper is None
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr( rt, "sweep", lambda c, need, entries, **kw: { "answers": [ { "id": e[ "id" ], "probabilities": dict( PROBS ) } for e in entries ], "failed": [ ], "not_reached": [ ] } )
        tap( ctx, NEED, ENTRIES[ :2 ] )
    key = tap.sweeps[ 0 ][ "keys" ][ ENTRIES[ 0 ][ "id" ] ]
    assert key == rt.request_hash( rt.build_request( NEED, rt.entry_text( ENTRIES[ 0 ] ), ctx.template, ctx.model ) )
    assert jr.entry_key( NEED, ENTRIES[ 0 ], ctx.template, ctx.model, None ) == key


def test_rating_of_adds_reuse_and_extend_and_refuses_a_malformed_answer():
    assert jr.rating_of( { "reuse": 0.2, "extend": 0.1, "unrelated": 0.7 } ) == { "p_overlap": 0.3, "confidence": 0.7, "choice": "unrelated" }
    assert jr.rating_of( { "reuse": 0.2 } ) is None and jr.rating_of( None ) is None


GOOD = { "reuse": 0.6, "extend": 0.3, "unrelated": 0.1 }


def sweep_of( keys, answers=None, failed=(), not_reached=() ):
    """Return one tapped sweep."""
    return { "keys": dict( keys ), "answers": dict( answers or { } ), "failed": list( failed ), "not_reached": list( not_reached ) }


def test_a_reading_names_every_way_an_entry_is_judged_or_not():
    answered = jr.judge_reading( "a", [ sweep_of( { "a": "k1" }, { "a": GOOD } ) ], True )
    assert answered == { "status": jr.JUDGED, "key": "k1", "p_overlap": 0.9, "confidence": 0.6, "choice": "reuse" }
    assert jr.judge_reading( "a", [ sweep_of( { "a": "k1" }, { "a": { "reuse": 0.2 } } ) ], True ) == { "status": jr.NOT_JUDGED, "reason": jr.MALFORMED_ANSWER, "key": "k1" }
    assert jr.judge_reading( "a", [ sweep_of( { "a": "k1" }, failed=[ "a" ] ) ], True )[ "reason" ] == jr.FAILED
    assert jr.judge_reading( "a", [ sweep_of( { "a": "k1" }, not_reached=[ "a" ] ) ], True )[ "reason" ] == jr.NOT_REACHED
    assert jr.judge_reading( "a", [ sweep_of( { "a": "k1" } ) ], True )[ "reason" ] == jr.NO_ANSWER
    assert jr.judge_reading( "a", [ sweep_of( { "b": "k2" } ) ], True ) == { "status": jr.NOT_JUDGED, "reason": jr.RETRIEVED_NOT_SENT, "key": None }
    assert jr.judge_reading( "a", [ ], False ) == { "status": jr.NOT_JUDGED, "reason": jr.NOT_RETRIEVED, "key": None }


def test_a_later_sweep_that_answers_wins_over_an_earlier_one_that_did_not_and_the_first_miss_is_kept_otherwise():
    miss, hit = sweep_of( { "a": "k1" }, failed=[ "a" ] ), sweep_of( { "a": "k1" }, { "a": GOOD } )
    assert jr.judge_reading( "a", [ miss, hit ], True )[ "status" ] == jr.JUDGED
    both = jr.judge_reading( "a", [ miss, sweep_of( { "a": "k1" }, not_reached=[ "a" ] ) ], True )
    assert both[ "reason" ] == jr.FAILED, "the first miss is the one kept"


def row_with( sweeps ):
    """Return a pair row built with the sweeps."""
    pair = real_pair( 0 )
    rid, oid = pair[ "rewrite" ][ "id" ], "orig-0"
    answer = answer_of( [ rid, oid ] )
    return cr.pair_row( pair, True, "tears down the widget", ( receipt( [ rid, oid ], [ rid ] ), answer ), "Does the work.", { "id": oid, "line": None }, ( receipt( [ ], [ ] ), answer_of( [ ] ) ), sweeps ), rid, oid


def test_a_pair_row_without_sweeps_has_no_judge_or_fusion_and_with_them_both_sides_carry_both():
    plain, rid, oid = row_with( None )
    assert "judge" not in plain[ "plant" ] and "fusion" not in plain[ "original" ]
    row, rid, oid = row_with( [ sweep_of( { rid: "kp", oid: "ko" }, { rid: GOOD }, failed=[ oid ] ) ] )
    assert row[ "plant" ][ "judge" ][ "status" ] == jr.JUDGED and row[ "original" ][ "judge" ] == { "status": jr.NOT_JUDGED, "reason": jr.FAILED, "key": "ko" }
    assert row[ "plant" ][ "fusion" ] == cr.fusion_terms( answer_of( [ rid, oid ] ), rid ) and row[ "original" ][ "fusion" ] == cr.fusion_terms( answer_of( [ rid, oid ] ), oid )


def test_a_pair_row_whose_check_made_no_sweep_still_carries_a_reading_for_each_side():
    row, rid, oid = row_with( [ ] )
    assert row[ "plant" ][ "judge" ][ "status" ] == jr.NOT_JUDGED and row[ "original" ][ "judge" ][ "reason" ] == jr.RETRIEVED_NOT_SENT, "an empty list of sweeps is not no sweeps argument"


def test_readings_of_takes_each_pass_and_skips_rows_without_readings_and_reports_without_a_control():
    one, rid, oid = row_with( [ sweep_of( { "d-rew00": "kp", "orig-0": "ko" }, { "d-rew00": GOOD } ) ] )
    old, _r, _o   = row_with( None )
    single = { "stages": { "control": { "report": { "rows": [ one, old ] } } } }
    got    = jr.readings_of( single )
    assert got[ "format" ] == jr.FORMAT and len( got[ "passes" ] ) == 1 and [ r[ "rewrite" ] for r in got[ "passes" ][ 0 ][ "rows" ] ] == [ "d-rew00" ], "a row with no readings gives no entry"
    assert set( got[ "passes" ][ 0 ][ "rows" ][ 0 ][ "plant" ] ) == { "id", "retrieved", "ranks", "fusion", "judge" }
    many = { "stages": { "control": { "report": { "rows": [ ], "passes": [ { "rows": [ one ] }, { "rows": [ one ] } ] } } } }
    assert [ p[ "pass" ] for p in jr.readings_of( many )[ "passes" ] ] == [ 1, 2 ]
    assert jr.readings_of( { } ) == { "format": jr.FORMAT, "passes": [ ] } and jr.readings_of( { "stages": { "control": { "report": None } } } )[ "passes" ] == [ ]
    assert jr.readings_of( { "stages": { "control": { } } } )[ "passes" ] == [ ]


def test_the_file_equals_the_readings_of_the_report( tmp_path ):
    one, _r, _o = row_with( [ sweep_of( { "d-rew00": "kp", "orig-0": "ko" }, { "d-rew00": GOOD } ) ] )
    report = { "stages": { "control": { "report": { "rows": [ one ] } } } }
    path   = jr.write_readings( tmp_path, report )
    assert path == tmp_path / jr.READINGS_FILE and json.loads( path.read_text( encoding="utf-8" ) ) == jr.readings_of( report )


def wired( monkeypatch, tmp_path ):
    """Run the live control over three pairs, the check sweeping through the context it gets."""
    from tests.unit import test_reuse_needset_first_thousand as t
    monkeypatch.setattr( ft, "planted_stage_for", lambda live, entries, cache, **kw: t.PLANTED )
    ctx, seen, turn = t.live_ctx(), [], { "n": -1 }
    ctx.sweeper = lambda c, need, entries, **kw: { "answers": [ { "id": e[ "id" ], "probabilities": dict( GOOD ) } for e in entries if e[ "id" ] == f"d-rew{turn[ 'n' ]:02d}" ], "failed": [ ], "not_reached": [ ] }
    ctx.template, ctx.model, ctx.request_shape = rt.PROMPT_TEMPLATE, rt.JEV_MODEL, rp.SHAPE_WHOLE

    def check( need, c, planted, entries ):
        seen.append( c )
        if isinstance( c.sweeper, jr.SweepTap ): turn[ "n" ] += 1                 # the plain sweeper of the bare check does not count
        c.sweeper( c, need[ "need" ], [ { "id": e[ "id" ], "sig": "()", "doc": "d", "file": "f" } for e in entries ] )
        return { "id": "r", "candidate_stage": { "ids": [ e[ "id" ] for e in entries ], "widened_ids": [] }, "shortlist": [] }

    ps  = [ t.real_pair( i ) for i in range( 3 ) ]
    out = asyncio.run( ft.control_stage_live( ctx, ps, "ask", "L", t.strip_of, lambda job, ask, ledger, **kw: { "ok": True, "need": t.SENTENCE }, "CACHE",
                                              prepare=lambda c: ( set(), t.live_pool(), "sha", "gen" ), check=check, build_stage=cs.build_stage )() )
    return ctx, seen, out


def test_the_live_check_runs_on_a_copy_with_a_fresh_tap_per_pair_and_the_callers_context_keeps_its_sweeper( monkeypatch, tmp_path ):
    ctx, seen, out = wired( monkeypatch, tmp_path )
    live = [ c for c in seen if isinstance( c.sweeper, jr.SweepTap ) ]
    bare = [ c for c in seen if not isinstance( c.sweeper, jr.SweepTap ) ]
    assert len( live ) == 3 and len( bare ) == 3 and len( { id( c.sweeper ) for c in live } ) == 3, "a fresh tap per pair; the bare check keeps the plain sweeper"
    assert all( c is not ctx for c in seen ) and not isinstance( ctx.sweeper, jr.SweepTap ), "the caller's context is not changed"
    assert all( len( c.sweeper.sweeps ) == 1 for c in live ), "each tap holds only its own pair's sweep"


def test_each_control_row_carries_the_judge_reading_and_fusion_of_both_sides( monkeypatch, tmp_path ):
    _ctx, _seen, out = wired( monkeypatch, tmp_path )
    first = out[ "rows" ][ 0 ]
    assert first[ "plant" ][ "judge" ][ "status" ] == jr.JUDGED and first[ "plant" ][ "judge" ][ "p_overlap" ] == 0.9
    assert [ r[ "plant" ][ "judge" ][ "status" ] for r in out[ "rows" ] ] == [ jr.JUDGED ] * 3, "each row reads its own pair's tap: the sweep of pair n answers plant n"
    assert first[ "original" ][ "judge" ][ "reason" ] == jr.NOT_RETRIEVED and set( first[ "plant" ][ "fusion" ] ) >= { "total" }


async def not_stopped():
    """Stand in for a first-thousand stage that finishes and does not stop the run."""
    return { "stop": False }


def test_a_full_run_writes_the_readings_file_beside_the_report_and_equal_to_its_rows( monkeypatch, tmp_path ):
    _ctx, _seen, out = wired( monkeypatch, tmp_path )
    async def control(): return out
    rep = asyncio.run( ft.run_first_thousand( str( tmp_path ), not_stopped, not_stopped, control, not_stopped ) )
    assert json.loads( ( tmp_path / jr.READINGS_FILE ).read_text( encoding="utf-8" ) ) == jr.readings_of( rep ) and jr.readings_of( rep )[ "passes" ][ 0 ][ "rows" ]


def test_a_run_that_fails_midway_still_writes_the_readings_of_the_stages_so_far( tmp_path ):
    async def crash(): raise RuntimeError( "boom" )
    with pytest.raises( RuntimeError ): asyncio.run( ft.run_first_thousand( str( tmp_path ), not_stopped, not_stopped, crash, not_stopped ) )
    assert json.loads( ( tmp_path / jr.READINGS_FILE ).read_text( encoding="utf-8" ) ) == { "format": jr.FORMAT, "passes": [ ] }
