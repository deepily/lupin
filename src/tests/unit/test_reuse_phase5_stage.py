"""
The stage mode of the fresh-needs driver: pinned asks, estimate and report.

Nothing here reaches Jev: the transport is the stand-in, the ledger a scratch file, and the needs file a scratch one under the reserved layout.
"""
import argparse
import json

import pytest

from lupin_mcp import reuse_band_fit_run as bf
from lupin_mcp import reuse_e2e as e2e
from lupin_mcp import reuse_e2e_run as e2r
from lupin_mcp import reuse_phase5_run as p5
from lupin_mcp import reuse_phase5_stage as stg
from lupin_mcp import reuse_stage1 as s1
from lupin_mcp import reuse_stage1_run as rr
from tests.unit.test_reuse_band_fit_run import FakeStage, Jittery
from tests.unit.test_reuse_phase5_run import Scratch

PIN = "b" * 64


@pytest.fixture
def scratch( tmp_path, monkeypatch ):
    monkeypatch.setattr( rr, "StandIn", Jittery )
    return Scratch( tmp_path, monkeypatch )


def stage_args( s, command, *extra, pin=True ):
    base = [ command, "--projects-data", s.projects_data, "--needs-sha", s.sha, "--data", str( s.data ), "--root", str( s.root ), "--ledger", str( s.ledger ) ]
    if pin and command in ( "stage-canary", "stage-run", "stage-report" ): base += [ "--manifest-hash", PIN ]
    return base + list( extra )


def drive( s, stage=None, steps=None ):
    stage = FakeStage() if stage is None else stage
    s.sample( arm="B1" )
    for step in steps or ( ( "stage-canary", "--ceiling", "1500000" ), ( "stage-approve", "--by", "cheech", "--why", "read it" ), ( "stage-run", "--ceiling", "7200000" ) ):
        assert p5.cli( stage_args( s, *step ), stage_factory=lambda root: stage ) == 0


def test_the_stage_steps_run_end_to_end_on_the_stand_in_and_the_report_prints_every_figure( scratch, capsys ):
    drive( scratch )
    capsys.readouterr()
    assert p5.cli( stage_args( scratch, "stage-report" ) ) == 0
    out = capsys.readouterr().out
    assert "flip rate (old question, route candidates)" in out and "tokens per need:" in out and "false reuse (verdict REUSE on an absent need), 15 absent needs" in out
    assert "recall and verdict agreement: not measured yet" in out



def write_sweep( s, picks ):
    """Write a stamped full-sweep result with one r1 row per need given."""
    searches = [ { "member": m, "question": stg.SWEEP_ASK, "status": "complete", "tokens": 0, "rows": [ { "repeat": 1, "route": "full", "question": "provides", "verdict": v, "shortlist": ids } ] } for m, ( v, ids ) in picks.items() ]
    ( s.data / "e2e-results" / f"{stg.SWEEP_RESULT}.json" ).write_text( json.dumps( { "sample_sha256": p5.sample_sha( s.data ), "searches": searches } ), encoding="utf-8" )


def test_the_sweep_result_adds_recall_and_verdict_agreement_over_the_sample( scratch, capsys ):
    drive( scratch )
    run     = json.loads( ( scratch.data / "e2e-results" / f"{stg.STAGE_PREFIX}-run.json" ).read_text( encoding="utf-8" ) )
    look    = { s[ "member" ]: s[ "rows" ][ 0 ] for s in run[ "searches" ] if s[ "question" ] == "lookup" }
    a, b, c = sorted( look )[ :3 ]
    other   = "REUSE" if look[ b ][ "verdict" ] != "REUSE" else "NEW"
    write_sweep( scratch, { a: ( look[ a ][ "verdict" ], [ look[ a ][ "nearest" ][ 0 ], "not.in.the.index" ] ), b: ( other, [ look[ b ][ "nearest" ][ 1 ] ] ), c: ( look[ c ][ "verdict" ], [] ) } )
    capsys.readouterr()
    assert p5.cli( stage_args( scratch, "stage-report" ) ) == 0
    out = capsys.readouterr().out
    assert "2 sampled needs with picks, picks pooled: 2 of 3, 66.7%" in out                                 # a holds one of its two picks, b holds its one, c picked nothing
    assert "final verdict agreement with the full search, 3 sampled needs: 2 of 3, 66.7%" in out
    assert "recall@10, agreement with the full search (not ground truth)" in out and "not measured yet" not in out


def test_the_sweep_step_runs_after_the_stage_canary_is_approved( scratch, capsys ):
    drive( scratch )
    capsys.readouterr()
    assert p5.cli( stage_args( scratch, "stage-sweep", "--ceiling", "36000000" ) ) == 0
    assert ( scratch.data / "e2e-results" / f"{stg.SWEEP_RESULT}.json" ).exists() and "p5s-sample" in capsys.readouterr().out


def test_the_sweep_waits_for_the_stage_canary_approval_and_not_for_the_old_modes( scratch, capsys ):
    scratch.sample( arm="B1" )
    assert p5.cli( stage_args( scratch, "stage-sweep", "--ceiling", "36000000" ) ) == 2
    assert "canary has not been approved" in capsys.readouterr().err
    assert p5.canary_approved( scratch.data, stg.STAGE_PREFIX ) is False and p5.canary_approved( scratch.data ) is False


@pytest.mark.parametrize( "step", [ ( "stage-canary", "--ceiling", "1500000" ), ( "stage-run", "--ceiling", "7200000" ) ] )
def test_a_stage_on_another_vector_set_than_the_pin_is_refused_before_anything_is_opened( scratch, capsys, step ):
    scratch.sample( arm="B1" )
    assert p5.cli( stage_args( scratch, *step ), stage_factory=lambda root: FakeStage( manifest_hash="c" * 64 ) ) == 2
    assert f"the vector set is {'c' * 64}, the run is pinned to {PIN}" in capsys.readouterr().err and not ( scratch.data / "e2e-results" ).exists()


def test_a_vector_set_replaced_after_the_first_lookup_stops_the_stage_run_with_no_send_after_it( scratch, capsys ):
    from tests.unit.test_reuse_band_fit_run import Swapping
    scratch.sample( arm="B1" )
    stage = Swapping( after=1 )
    assert p5.cli( stage_args( scratch, "stage-canary", "--ceiling", "1500000" ), stage_factory=lambda root: stage ) == 2
    assert f"the run is pinned to {PIN}" in capsys.readouterr().err


def test_a_ceiling_above_the_estimate_times_the_factor_is_refused_before_a_stage_is_built( scratch, capsys ):
    scratch.sample( arm="B1" )
    built = []
    assert p5.cli( stage_args( scratch, "stage-run", "--ceiling", "8640001" ), stage_factory=lambda root: built.append( root ) ) == 2
    assert "is above 8640000" in capsys.readouterr().err and built == []


def test_the_pin_is_a_required_option_of_the_steps_that_ask_and_of_the_report( scratch ):
    scratch.sample( arm="B1" )
    for step in ( ( "stage-canary", "--ceiling", "1" ), ( "stage-run", "--ceiling", "1" ), ( "stage-report", ) ):
        with pytest.raises( SystemExit ): p5.cli( stage_args( scratch, *step, pin=False ) )


def test_a_stage_result_stamped_with_another_sample_hash_is_refused_by_the_next_stage_step( scratch, capsys ):
    drive( scratch )
    path = scratch.data / "e2e-results" / f"{stg.STAGE_PREFIX}-run.json"
    rec  = json.loads( path.read_text( encoding="utf-8" ) )
    rec[ "sample_sha256" ] = "0" * 64
    path.write_text( json.dumps( rec ), encoding="utf-8" )
    assert p5.cli( stage_args( scratch, "stage-report" ) ) == 2
    assert "does not carry the recorded sample's hash" in capsys.readouterr().err


def test_an_old_mode_result_with_another_sample_hash_is_refused_and_one_with_none_is_let_be( scratch, capsys ):
    scratch.sample( arm="B1" )
    folder = scratch.data / "e2e-results"
    folder.mkdir( parents=True )
    ( folder / "p5-canary.json" ).write_text( json.dumps( { "searches": [] } ), encoding="utf-8" )
    assert p5.cli( stage_args( scratch, "stage-report" ) ) == 2 and "no p5st result" in capsys.readouterr().err
    ( folder / "p5-canary.json" ).write_text( json.dumps( { "searches": [], "sample_sha256": "1" * 64 } ), encoding="utf-8" )
    assert p5.cli( stage_args( scratch, "stage-report" ) ) == 2 and "carries sample hash" in capsys.readouterr().err


def test_the_estimate_command_names_the_sweep_as_its_own_line_and_the_total_as_run_plus_sweep( scratch, capsys ):
    assert p5.cli( [ "stage-estimate", "--projects-data", scratch.projects_data, "--needs-sha", scratch.sha ] ) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[ 0 ].startswith( "run: 5.76 M tokens (30 needs x 6 asks x 128 entries x 250 tokens), ceiling 8640000" )
    assert lines[ 1 ].startswith( "canary: 0.96 M tokens, the first 5 needs of the run, ceiling 1440000" )
    assert lines[ 2 ].startswith( "sample: 24.5 M tokens" ) and lines[ 3 ].startswith( "total: 30.30 M tokens, about $1.27 at $0.042 per M" )


def test_the_estimate_lines_follow_the_needs_count_and_the_sample_given():
    lines = stg.estimate_lines( 40, 1_000_000, 0.5 )
    assert lines[ 0 ].startswith( "run: 7.68 M tokens (40 needs" ) and lines[ 2 ].startswith( "sample: 1.0 M" ) and "total: 8.68 M tokens, about $4.34 at $0.5 per M" in lines[ 3 ]


# ---- the figures, on data written by hand ---------------------------------------------------------

def row( verdict, nearest=(), shortlist=() ): return { "verdict": verdict, "nearest": list( nearest ), "shortlist": list( shortlist ) }


def test_recall_pools_the_sweeps_picks_that_the_first_ten_ranked_ids_hold_and_leaves_out_a_need_with_no_picks():
    lookups = { "a": row( "REUSE", [ "x1", "x2", "x3" ] ), "b": row( "NEW", [ "y1" ] + [ f"f{i}" for i in range( 10 ) ] + [ "y2" ] ), "c": row( "NEW", [ "z" ] ), "d": row( "NEW", [] ) }
    swept   = { "a": row( "REUSE", shortlist=[ "x1", "x9" ] ), "b": row( "EXTEND", shortlist=[ "y1", "y2" ] ), "c": row( "NEW" ), "e": row( "NEW", shortlist=[ "q" ] ) }
    a       = stg.agreement( lookups, swept )
    assert a[ "compared" ] == 3 and a[ "recall_needs" ] == 2                                       # e has no lookup, c has no picks
    assert a[ "per_need" ] == { "a": 0.5, "b": 0.5 }                                               # y2 sits at rank 12, so only y1 is held
    assert ( a[ "recall" ][ "k" ], a[ "recall" ][ "n" ] ) == ( 2, 4 ) and a[ "recall" ][ "rate" ] == 0.5
    assert ( a[ "verdict" ][ "k" ], a[ "verdict" ][ "n" ] ) == ( 2, 3 )                            # a and c agree, b does not
    assert a[ "recall" ][ "interval" ] == list( e2e.wilson( 2, 4 ) )


def test_pooled_recall_weighs_a_need_by_its_picks_not_by_one():
    lookups = { "a": row( "NEW", [ "p1" ] ), "b": row( "NEW", [] ) }
    swept   = { "a": row( "NEW", shortlist=[ "p1" ] ), "b": row( "NEW", shortlist=[ "q1", "q2", "q3" ] ) }
    a       = stg.agreement( lookups, swept )
    assert a[ "recall" ][ "rate" ] == 0.25 and sum( a[ "per_need" ].values() ) / 2 == 0.5            # the mean of the needs would say 0.5


def test_nothing_to_compare_gives_empty_figures_and_no_rate():
    a = stg.agreement( {}, {} )
    assert a[ "compared" ] == 0 and a[ "recall" ][ "rate" ] is None and a[ "recall" ][ "interval" ] == [ None, None ] and a[ "verdict" ][ "n" ] == 0


def items_of( kinds ): return [ { "member": f"n{i}", "need": f"need {i}", "exclude": None, "kind": k } for i, k in enumerate( kinds ) ]


def test_false_reuse_counts_reuse_and_extend_on_the_absent_needs_only():
    items   = items_of( [ "distinct", "distinct", "distinct", "duplicate", "distinct" ] )
    lookups = { "n0": row( "REUSE" ), "n1": row( "EXTEND" ), "n2": row( "NEW" ), "n3": row( "REUSE" ) }          # n4 has no lookup; n3 is a duplicate
    fr      = stg.false_reuse( lookups, items )
    assert fr[ "absent" ] == 4 and fr[ "asked" ] == 3
    assert ( fr[ "reuse" ][ "k" ], fr[ "reuse" ][ "n" ] ) == ( 1, 3 ) and ( fr[ "extend" ][ "k" ], fr[ "extend" ][ "n" ] ) == ( 1, 3 )


def rec( member, question, tokens, status="complete", rows=None ): return { "member": member, "question": question, "tokens": tokens, "status": status, "rows": [] if rows is None else rows }


def test_tokens_per_need_counts_a_need_only_when_its_lookup_and_every_repeat_are_complete():
    full = [ rec( "a", "lookup", 10 ) ] + [ rec( "a", f"r{i}", 20 ) for i in range( 1, 3 ) ]
    part = [ rec( "b", "lookup", 1000 ), rec( "b", "r1", 1000 ), rec( "b", "r2", 1000, status="incomplete" ) ]
    short = [ rec( "c", "lookup", 1000 ) ]
    t = stg.tokens_per_need( full + part + short, 2 )
    assert t == { "needs": 1, "total": 50, "mean": 50.0 }
    assert stg.tokens_per_need( part, 2 ) == { "needs": 0, "total": 0, "mean": None }


def run_of( searches, manifest=PIN, sha="s" * 64, questions=( "lookup", "r1", "r2" ) ):
    return { "run_name": "p5st-run", "stage": { "manifest_hash": manifest }, "sample_sha256": sha, "questions": list( questions ), "searches": searches }


def test_the_report_says_plainly_when_the_file_has_no_absent_needs_and_when_no_cost_can_be_counted():
    items = items_of( [ "duplicate", "duplicate" ] )
    lines = stg.report_lines( [ run_of( [] ) ], None, items, 2, 0.042 )
    assert lines[ 0 ] == "no searches have run yet"
    assert "false reuse: the file has no absent needs, so it is not measured" in lines
    assert "tokens per need: no need has its lookup and every repeat complete yet" in lines
    assert "recall and verdict agreement: not measured yet; the full sweep of the sample has not run" in lines


def test_the_report_words_recall_as_agreement_and_shows_each_figure_with_its_numbers():
    items    = items_of( [ "duplicate", "distinct" ] )
    look_a   = rec( "n0", "lookup", 100, rows=[ { **row( "REUSE", [ "x1" ], [ "x1" ] ), "repeat": 0 } ] )
    look_b   = rec( "n1", "lookup", 100, rows=[ { **row( "REUSE", [ "y1" ], [ "y1" ] ), "repeat": 0 } ] )
    repeats  = [ rec( m, f"r{i}", 50, rows=[ { "repeat": i, "route": "candidates", "question": "choice", "verdict": "REUSE", "shortlist": [ "x1" ] } ] ) for m in ( "n0", "n1" ) for i in ( 1, 2 ) ]
    sweep    = { "searches": [ rec( "n0", "r1", 1, rows=[ row( "REUSE", [], [ "x1", "x2" ] ) ] ), rec( "n1", "r1", 1, rows=[ row( "NEW" ) ] ) ] }
    lines    = stg.report_lines( [ run_of( [ look_a, look_b ] + repeats ) ], sweep, items, 2, 0.042 )
    text     = "\n".join( lines )
    assert "recall@10, agreement with the full search (not ground truth), 1 sampled needs with picks, picks pooled: 1 of 2, 50.0%" in text
    assert "final verdict agreement with the full search, 2 sampled needs: 1 of 2, 50.0%" in text
    assert "false reuse (verdict REUSE on an absent need), 1 absent needs: 1 of 1, 100.0%" in text and "false extend (verdict EXTEND on an absent need), reported beside it: 0 of 1, 0.0%" in text
    assert "tokens per need: 200 over 2 needs (400 in all), about $0.0000 a need at $0.042 per M" in text


def test_a_figure_with_no_cases_says_so_and_never_divides_by_zero():
    assert stg._figure( "recall", stg._interval( 0, 0 ) ) == "recall: no cases"


def test_the_report_refuses_results_off_the_pin_the_sample_or_the_repeats():
    ok = run_of( [] )
    assert stg.check_results( [ ok ], PIN, "s" * 64, 2 ) is None
    with pytest.raises( s1.DriverRefused, match="ran on vector set" ): stg.check_results( [ run_of( [], manifest="c" * 64 ) ], PIN, "s" * 64, 2 )
    with pytest.raises( s1.DriverRefused, match="recorded sample's hash" ): stg.check_results( [ run_of( [], sha="t" * 64 ) ], PIN, "s" * 64, 2 )
    unstamped = run_of( [] )
    del unstamped[ "sample_sha256" ]
    with pytest.raises( s1.DriverRefused, match="recorded sample's hash" ): stg.check_results( [ unstamped ], PIN, "s" * 64, 2 )
    with pytest.raises( s1.DriverRefused, match="with 2 repeats per need, but the report was given 3" ): stg.check_results( [ ok ], PIN, "s" * 64, 3 )


def test_the_report_refuses_a_full_sweep_result_stamped_for_another_sample( scratch, capsys ):
    drive( scratch )
    assert p5.cli( stage_args( scratch, "stage-sweep", "--ceiling", "36000000" ) ) == 0
    path = scratch.data / "e2e-results" / f"{stg.SWEEP_RESULT}.json"
    swept = json.loads( path.read_text( encoding="utf-8" ) )
    del swept[ "sample_sha256" ]
    path.write_text( json.dumps( swept ), encoding="utf-8" )
    capsys.readouterr()
    args  = argparse.Namespace( data=str( scratch.data ), prefix=stg.STAGE_PREFIX, manifest_hash=PIN, projects_data=scratch.projects_data, needs_sha=scratch.sha )
    with pytest.raises( s1.DriverRefused, match="full-sweep result does not carry" ): stg.report( args, p5.load_items( args ), p5.sample_sha( scratch.data ), 0.042 )


def test_an_error_result_is_returned_as_it_is_by_the_lookup_and_by_every_replay( monkeypatch ):
    err = { "status": "error", "error": "NO_LOOKUP_RECEIPT" }
    monkeypatch.setattr( bf, "make_asks", lambda stage, sink, repeats, pinned: { bf.LOOKUP: lambda c, i: err, "r1": lambda c, i: err } )
    asks = stg.stage_asks( None, bf.Sink(), 1, PIN )
    assert asks[ bf.LOOKUP ]( None, {} ) is err and asks[ "r1" ]( None, {} ) is err and list( asks ) == [ bf.LOOKUP, "r1" ]


def test_the_lookup_row_carries_the_first_ten_ranked_ids_and_the_replay_row_its_verdict_and_shortlist( monkeypatch ):
    near  = [ { "id": f"e{i:02d}" } for i in range( 14 ) ]
    look  = { "status": "ok", "verdict": "REUSE", "nearest": near, "shortlist": [ { "id": "e03" }, { "id": "e01" } ] }
    rep   = { "status": "ok", "verdict": "NEW", "shortlist": [ { "id": "e07" }, { "id": "e02" } ], "rows": [ { "repeat": 2, "p_overlap": { "e00": 0.5 } } ] }
    monkeypatch.setattr( bf, "make_asks", lambda stage, sink, repeats, pinned: { bf.LOOKUP: lambda c, i: look, "r2": lambda c, i: rep } )
    asks = stg.stage_asks( None, bf.Sink(), 2, PIN )
    assert asks[ bf.LOOKUP ]( None, {} )[ "rows" ] == [ { "repeat": 0, "route": "candidates", "question": "choice", "verdict": "REUSE", "nearest": [ f"e{i:02d}" for i in range( 10 ) ], "shortlist": [ "e01", "e03" ] } ]
    assert asks[ "r2" ]( None, {} )[ "rows" ] == [ { "repeat": 2, "p_overlap": { "e00": 0.5 }, "route": "candidates", "question": "choice", "verdict": "NEW", "shortlist": [ "e02", "e07" ] } ]



def lrow( verdict, nearest=(), shortlist=() ): return [ { **row( verdict, nearest, shortlist ), "repeat": 0 } ]


def test_an_incomplete_lookup_that_still_holds_rows_is_left_out_of_recall_agreement_and_false_reuse():
    items  = items_of( [ "duplicate", "distinct" ] )
    done   = rec( "n0", "lookup", 1, rows=lrow( "REUSE", [ "x1" ], [ "x1" ] ) )
    broken = rec( "n1", "lookup", 1, status="incomplete", rows=lrow( "REUSE", [ "y1" ], [ "y1" ] ) )
    sweep  = { "searches": [ rec( "n0", "r1", 1, rows=lrow( "REUSE", [], [ "x1" ] ) ), rec( "n1", "r1", 1, rows=lrow( "REUSE", [], [ "y1" ] ) ) ] }
    text   = "\\n".join( stg.report_lines( [ run_of( [ done, broken ] ) ], sweep, items, 2, 0.042 ) )
    assert "final verdict agreement with the full search, 1 sampled needs: 1 of 1" in text           # the broken lookup agrees with its sweep, yet it is not counted
    assert "1 sampled needs with picks, picks pooled: 1 of 1" in text
    assert "false reuse (verdict REUSE on an absent need), 1 absent needs: no cases" in text          # n1 is the only absent need and its lookup did not finish


def test_an_incomplete_full_sweep_that_still_holds_rows_is_left_out_of_recall_and_agreement():
    items  = items_of( [ "duplicate", "duplicate" ] )
    looks  = [ rec( "n0", "lookup", 1, rows=lrow( "REUSE", [ "x1" ], [ "x1" ] ) ), rec( "n1", "lookup", 1, rows=lrow( "REUSE", [ "y1" ], [ "y1" ] ) ) ]
    sweep  = { "searches": [ rec( "n0", "r1", 1, rows=lrow( "REUSE", [], [ "x1" ] ) ), rec( "n1", "r1", 1, status="incomplete", rows=lrow( "REUSE", [], [ "y1" ] ) ) ] }
    text   = "\\n".join( stg.report_lines( [ run_of( looks ) ], sweep, items, 2, 0.042 ) )
    assert "final verdict agreement with the full search, 1 sampled needs: 1 of 1" in text and "1 sampled needs with picks, picks pooled: 1 of 1" in text


def drive_prefixed( s, prefix, stage=None ):
    stage = FakeStage() if stage is None else stage
    for step in ( ( "stage-canary", "--ceiling", "1500000" ), ( "stage-approve", "--by", "cheech", "--why", "read it" ), ( "stage-run", "--ceiling", "7200000" ) ):
        assert p5.cli( stage_args( s, *step, "--prefix", prefix ), stage_factory=lambda root: stage ) == 0


def test_a_second_run_under_its_own_prefix_reuses_the_sample_and_leaves_the_first_results_alone( scratch, capsys ):
    drive( scratch )
    folder = scratch.data / "e2e-results"
    first  = ( folder / f"{stg.STAGE_PREFIX}-run.json" ).read_bytes()
    drive_prefixed( scratch, "p5st-b2" )
    assert ( folder / "p5st-b2-canary.json" ).exists() and ( folder / "p5st-b2-run.json" ).exists() and ( folder / f"{stg.STAGE_PREFIX}-run.json" ).read_bytes() == first
    capsys.readouterr()
    assert p5.cli( stage_args( scratch, "stage-report", "--prefix", "p5st-b2" ) ) == 0
    assert "flip rate (old question, route candidates)" in capsys.readouterr().out


def test_the_same_prefix_cannot_run_twice_and_a_report_reads_only_its_own_prefix( scratch, capsys ):
    drive( scratch )
    assert p5.cli( stage_args( scratch, "stage-canary", "--ceiling", "1500000" ), stage_factory=lambda root: FakeStage() ) == 2
    capsys.readouterr()
    assert p5.cli( stage_args( scratch, "stage-report", "--prefix", "p5st-b2" ) ) == 2
    assert "no p5st-b2 result" in capsys.readouterr().err


@pytest.mark.parametrize( "bad", [ "P5ST", "a,b", "x" * 17 ] )
def test_a_bad_prefix_is_refused_before_a_stage_is_built( scratch, capsys, bad ):
    scratch.sample( arm="B1" )
    built = []
    assert p5.cli( stage_args( scratch, "stage-canary", "--ceiling", "1500000", "--prefix", bad ), stage_factory=lambda root: built.append( root ) ) == 2
    assert built == [] and "prefix" in capsys.readouterr().err
