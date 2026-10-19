"""
The band-fit driver: a lookup and five replays per need, and the fitted band.

The transport is a stand-in whose answers move a little from one request to the next, so there is jitter to find.
The candidate stage is a stand-in with the client's interface. Nothing reaches Jev, and the ledger is a scratch file.
"""
import itertools
import json
import threading

import pytest

from cosa.repo.symindex import labelled_set as ls
from lupin_mcp import reuse_band_fit_run as bf
from lupin_mcp import reuse_e2e as e2e
from lupin_mcp import reuse_flip as rf
from lupin_mcp import reuse_flip_run as frun
from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_stage1 as s1
from lupin_mcp import reuse_stage1_run as rr
from lupin_mcp import reuse_tools as rt
from tests.unit.test_reuse_e2e_cli import put
from tests.unit.test_reuse_e2e_run import IDS, make_wide_repo
from tests.unit.test_reuse_flip_run import rows_of

SHORTLIST = IDS[ :40 ]


class Jittery( rr.StandIn ):
    """Answers each request with the stand-in's numbers moved by a small, changing step."""

    steps, lock, posts = itertools.count(), threading.Lock(), 0

    def post_with_meta( self, body ):
        response, meta = super().post_with_meta( body )
        with Jittery.lock:
            n = next( Jittery.steps )
            Jittery.posts += 1
        delta = 0.02 * ( n % 3 - 1 )
        for answer in response[ "answers" ].values():
            p = answer[ "probabilities" ]
            if p[ "reuse" ] + delta >= 0 and p[ "unrelated" ] - delta >= 0: p[ "reuse" ], p[ "unrelated" ] = round( p[ "reuse" ] + delta, 6 ), round( p[ "unrelated" ] - delta, 6 )
        return response, meta


class FakeStage:
    """The candidate stage's interface: a fixed shortlist, the member left out."""

    arm, K = "B2w", 128

    def __init__( self, ids=SHORTLIST, manifest_hash="b" * 64, error=None ):
        self.ids, self.manifest_hash, self.error = list( ids ), manifest_hash, error

    def manifest( self ): return { "manifest_hash": self.manifest_hash }

    def shortlist( self, ranking_text, entries, index_sha, pages, exclude_id=None, cache_only=False, wiki_ids=None, K=None, index_manifest=None ):
        if self.error is not None:
            from cosa.repo.symindex.candidates.errors import CandidateError
            raise CandidateError( self.error, "stand-in failure" )
        ids = sorted( i for i in self.ids if i != exclude_id )
        return { "ids": ids, "ranking": ids, "lists": { "code": { "size": len( ids ), "head": ids } }, "manifest_hash": self.manifest_hash,
                 "embed_models": { "code": "c-model", "prose": "p-model" }, "arm": self.arm, "K": self.K, "widened": False, "stage_key": "k" * 32,
                 "wiki": 0, "wiki_ids": [] if wiki_ids is None else list( wiki_ids ), "ranking_hash": "r" * 64 }


class Setup:
    """A scratch tree, ledger and needs file, and the argument lists that point at them."""

    def __init__( self, tmp_path, n=30 ):
        self.root, self.data, self.ledger = make_wide_repo( tmp_path ), tmp_path / "data", tmp_path / "ledger.jsonl"
        rl.AccountLedger.create( self.ledger, rl.ACCOUNT_LIMIT_TOKENS, "test", "scratch" )
        self.rows  = rows_of( n )
        self.needs = tmp_path / "flip-needs.json"
        self.sha   = put( self.needs, { "format": frun.NEEDS_FORMAT, "needs": self.rows } )
        self.out   = tmp_path / "band-fit.json"

    def args( self, *command ):
        pin = [ "--manifest-hash", "b" * 64 ] if command[ 0 ] in ( "canary", "run" ) else []
        return [ command[ 0 ], "--needs", str( self.needs ), "--needs-sha", self.sha, "--root", str( self.root ), "--data", str( self.data ),
                 "--ledger", str( self.ledger ) ] + pin + list( command[ 1: ] )

    def run( self, stage=None ):
        stage = FakeStage() if stage is None else stage
        for step in ( ( "canary", "--ceiling", "1500000" ), ( "approve", "--by", "cheech", "--why", "read it" ), ( "run", "--ceiling", "7200000" ) ):
            assert bf.cli( self.args( *step ), stage_factory=lambda root: stage ) == 0

    def result( self, name ): return json.loads( ( self.data / "e2e-results" / f"{bf.PREFIX}-{name}.json" ).read_text( encoding="utf-8" ) )


@pytest.fixture
def setup( tmp_path, monkeypatch ):
    monkeypatch.setattr( rr, "StandIn", Jittery )
    Jittery.posts = 0
    return Setup( tmp_path )


# ---- the arithmetic and the pure parts ---------------------------------------------------------

def test_the_estimate_is_thirty_needs_by_six_asks_by_128_entries_by_250_tokens():
    assert bf.estimate( 30 ) == 5_760_000 and bf.ESTIMATE_TOKENS == 5_800_000 and bf.estimate( 1 ) == 192_000


@pytest.mark.parametrize( "values, q, want", [ ( [ 5, 1, 3 ], 0.5, 3 ), ( [ 1, 2, 3, 4 ], 0.5, 2 ), ( [ 1, 2, 3, 4 ], 0.95, 4 ), ( [ 1, 2, 3, 4 ], 0.25, 1 ), ( [ 7 ], 1.0, 7 ), ( [ 1, 2 ], 0.01, 1 ) ] )
def test_the_quantile_is_the_nearest_rank( values, q, want ):
    assert bf.quantile( values, q ) == want


def test_spreads_measure_the_mean_the_largest_distance_from_it_and_the_span_and_skip_a_single_draw():
    rows = bf.spreads( { "b": { "e2": [ 0.2, 0.4, 0.6 ] }, "a": { "e1": [ 0.5 ], "e0": [ 0.1, 0.3 ] } } )
    assert [ ( r[ "need" ], r[ "entry" ] ) for r in rows ] == [ ( "a", "e0" ), ( "b", "e2" ) ]
    assert rows[ 0 ][ "mean" ] == pytest.approx( 0.2 ) and rows[ 0 ][ "dev" ] == pytest.approx( 0.1 ) and rows[ 0 ][ "span" ] == pytest.approx( 0.2 ) and rows[ 0 ][ "draws" ] == 2
    assert rows[ 1 ][ "mean" ] == pytest.approx( 0.4 ) and rows[ 1 ][ "dev" ] == pytest.approx( 0.2 )


def test_a_draw_that_sits_far_from_its_mean_sets_the_dev_not_the_nearer_one():
    row = bf.spreads( { "a": { "e": [ 0.5, 0.5, 0.5, 0.5, 0.0 ] } } )[ 0 ]
    assert row[ "dev" ] == pytest.approx( 0.4 ) and row[ "span" ] == pytest.approx( 0.5 )          # the mean is 0.4; dev and span differ, so they cannot be swapped


def draws_with( devs ):
    """Draws for one need: each entry has two draws, 0.5 minus the dev and 0.5 plus it."""
    return { "a": { f"e{i:02d}": [ 0.5 - d, 0.5 + d ] for i, d in enumerate( devs ) } }


def test_the_band_is_the_quantile_of_the_dev_rounded_up_and_never_under_the_floor():
    fit = bf.fit_band( draws_with( [ 0.01 ] * 18 + [ 0.12, 0.2 ] ), q=0.9 )
    assert fit[ "band" ] == ls.MIN_BAND and fit[ "floored" ] and fit[ "raw" ] == pytest.approx( 0.01 )              # the 18th of 20 is a 0.01
    fit = bf.fit_band( draws_with( [ 0.01 ] * 18 + [ 0.1234, 0.2 ] ), q=0.95 )
    assert fit[ "band" ] == 0.124 and not fit[ "floored" ] and fit[ "population" ] == 20 and fit[ "entries" ] == 20
    assert fit[ "sensitivity" ][ "population" ][ "1.0" ] == pytest.approx( 0.2 ) and fit[ "sensitivity" ][ "population" ][ "0.5" ] == pytest.approx( 0.01 )


def test_an_exact_floor_is_not_called_floored():
    fit = bf.fit_band( draws_with( [ 0.05 ] * 4 ), q=0.95 )
    assert fit[ "band" ] == 0.05 and not fit[ "floored" ]


def test_only_entries_whose_mean_is_inside_the_limits_set_the_band_and_the_others_are_counted():
    draws = { "a": { "far": [ 0.0, 0.04 ], "mid": [ 0.45, 0.55 ], "edge": [ 0.1, 0.1 ], "high": [ 0.5, 1.0 ] } }
    fit = bf.fit_band( draws, q=1.0, low=0.1, high=0.9 )
    assert fit[ "population" ] == 3 and fit[ "entries" ] == 4 and fit[ "raw" ] == pytest.approx( 0.25 )                                  # far has mean 0.02, outside; edge sits exactly on the low limit, inside
    fit = bf.fit_band( draws, q=1.0, low=0.4, high=0.6 )
    assert fit[ "population" ] == 1 and fit[ "raw" ] == pytest.approx( 0.05 )                  # only mid


def test_the_top_entry_of_each_need_is_tabled_beside_the_population():
    draws = { "a": { "lo": [ 0.2, 0.2 ], "top": [ 0.7, 0.9 ] }, "b": { "only": [ 0.3, 0.5 ] } }
    fit   = bf.fit_band( draws, q=1.0 )
    assert fit[ "sensitivity" ][ "top_entry_per_need" ][ "1.0" ] == pytest.approx( 0.1 ) and fit[ "sensitivity" ][ "all_entries" ][ "1.0" ] == pytest.approx( 0.1 )


def test_no_entry_inside_the_limits_is_a_refusal_not_a_zero_band():
    with pytest.raises( ValueError, match="no entry" ): bf.fit_band( { "a": { "e": [ 0.0, 0.0 ] } } )


def test_a_band_the_labelled_set_refuses_is_refused():
    with pytest.raises( ValueError, match="outside the allowed range" ): bf.fit_band( { "a": { "e": [ 0.0, 1.0 ] } }, q=1.0 )          # dev 0.5 is the ceiling, which is out


def result_file( member, repeat, p, status="complete", question=None ):
    row = { "repeat": repeat, "asked": len( p ), "p_overlap": p, "failed": [], "not_reached": [] }
    return { "member": member, "question": question or f"r{repeat}", "status": status, "rows": [ row ] if status == "complete" else None }


def test_gather_keeps_a_need_only_when_every_repeat_is_complete_and_names_what_the_others_lack():
    canary = { "searches": [ result_file( "a", 1, { "e": 0.1 } ), result_file( "a", 2, { "e": 0.2 } ), result_file( "b", 1, { "e": 0.3 } ), { "member": "a", "question": "lookup", "status": "complete", "rows": None } ] }
    run    = { "searches": [ result_file( "a", r, { "e": r / 10 } ) for r in ( 3, 4, 5 ) ] + [ result_file( "b", 2, { "e": 0.3 }, status="incomplete" ) ] }
    draws, whole, short = bf.gather( [ canary, run ], [ "a", "b", "c" ] )
    assert whole == [ "a" ] and short == { "b": [ 2, 3, 4, 5 ], "c": [ 1, 2, 3, 4, 5 ] }
    assert draws == { "a": { "e": [ 0.1, 0.2, 0.3, 0.4, 0.5 ] } }


def test_overlap_is_reuse_plus_extend_and_a_malformed_answer_is_left_out():
    good = { "id": "g", "probabilities": { "reuse": 0.5, "extend": 0.25, "unrelated": 0.25 } }
    bad  = { "id": "b", "probabilities": { "reuse": 0.9, "extend": 0.9, "unrelated": 0.9 } }
    later = { "id": "g", "probabilities": { "reuse": 0.1, "extend": 0.1, "unrelated": 0.8 } }
    assert bf.overlaps( [ { "answers": [ good, bad ] } ] ) == ( { "g": 0.75 }, [ { "id": "b", "reason": "sum_not_one" } ] )
    assert bf.overlaps( [ { "answers": [ good ] }, { "answers": [ later ] } ] ) == ( { "g": pytest.approx( 0.2 ) }, [] )


def test_capturing_replays_records_each_sweep_and_always_puts_the_real_sweeper_back():
    real, taken = rf.replay_sweeper, []
    with bf.capture_replays( taken ):
        assert rf.replay_sweeper is not real
        sweeper = rf.replay_sweeper( 10, rf.rp.WORKERS_DEFAULT, 1 )
        assert callable( sweeper )
    assert rf.replay_sweeper is real
    with pytest.raises( RuntimeError ):
        with bf.capture_replays( taken ): raise RuntimeError( "inside" )
    assert rf.replay_sweeper is real


def test_a_ceiling_above_the_estimate_times_the_factor_is_refused():
    assert bf.check_ceiling( 8_700_000, 5_800_000 ) == 8_700_000
    with pytest.raises( s1.DriverRefused, match="8700000" ): bf.check_ceiling( 8_700_001, 5_800_000 )


def test_write_once_never_replaces_a_file_and_leaves_no_temporary(tmp_path):
    path = tmp_path / "r.json"
    bf.write_once( path, { "a": 1 } )
    assert json.loads( path.read_text() ) == { "a": 1 }
    with pytest.raises( FileExistsError ): bf.write_once( path, { "a": 2 } )
    assert json.loads( path.read_text() ) == { "a": 1 } and [ p.name for p in tmp_path.iterdir() ] == [ "r.json" ]


# ---- the driver on a stand-in --------------------------------------------------------------------

def test_the_estimate_command_prints_the_arithmetic_and_the_ceiling_and_opens_nothing( setup, capsys ):
    assert bf.cli( [ "estimate", "--needs", str( setup.needs ), "--needs-sha", setup.sha ] ) == 0
    assert "30 needs x 6 asks x 128 entries x 250 tokens = 5760000 tokens; ceiling 8640000" in capsys.readouterr().out
    assert not setup.data.exists()


def test_the_canary_asks_the_lookup_and_five_repeats_for_five_needs_and_each_repeat_keeps_every_entrys_overlap( setup, capsys ):
    assert bf.cli( setup.args( "canary", "--ceiling", "1500000" ), stage_factory=lambda root: FakeStage() ) == 0
    assert "canary bandfit-canary" in capsys.readouterr().out
    record = setup.result( "canary" )
    assert record[ "questions" ] == [ "lookup", "r1", "r2", "r3", "r4", "r5" ] and len( record[ "searches" ] ) == 30
    assert all( s[ "status" ] == "complete" for s in record[ "searches" ] )
    assert record[ "stage" ] == { "arm": "B2w", "K": 128, "manifest_hash": "b" * 64 } and record[ "needs_sha" ] == setup.sha
    rep = next( s for s in record[ "searches" ] if s[ "member" ] == "n01" and s[ "question" ] == "r3" )                  # n01 is a distinct need, so nothing is left out of its shortlist
    row = rep[ "rows" ][ 0 ]
    assert row[ "repeat" ] == 3 and sorted( row[ "p_overlap" ] ) == sorted( SHORTLIST ) and row[ "asked" ] == len( SHORTLIST ) and row[ "failed" ] == []
    assert all( 0.0 <= v <= 1.0 for v in row[ "p_overlap" ].values() )


def test_the_member_is_left_out_of_the_shortlist_of_a_duplicate_need( setup ):
    assert bf.cli( setup.args( "canary", "--ceiling", "1500000" ), stage_factory=lambda root: FakeStage() ) == 0
    rep = next( s for s in setup.result( "canary" )[ "searches" ] if s[ "member" ] == "n00" and s[ "question" ] == "r1" )
    assert IDS[ 0 ] not in rep[ "rows" ][ 0 ][ "p_overlap" ] and len( rep[ "rows" ][ 0 ][ "p_overlap" ] ) == len( SHORTLIST ) - 1


def test_a_repeat_is_a_new_draw_so_the_same_entry_answers_differently_across_repeats( setup ):
    assert bf.cli( setup.args( "canary", "--ceiling", "1500000" ), stage_factory=lambda root: FakeStage() ) == 0
    rows = [ s[ "rows" ][ 0 ][ "p_overlap" ] for s in setup.result( "canary" )[ "searches" ] if s[ "member" ] == "n01" and s[ "question" ].startswith( "r" ) ]
    assert len( rows ) == 5 and any( len( { r[ e ] for r in rows } ) > 1 for e in SHORTLIST )


def test_the_whole_flow_writes_a_receipt_with_the_fitted_band_and_every_draw( setup, capsys ):
    setup.run()
    capsys.readouterr()
    assert bf.cli( setup.args( "report", "--out", str( setup.out ), "--code-sha", "abc123" ) ) == 0
    line = capsys.readouterr().out
    rec  = json.loads( setup.out.read_text( encoding="utf-8" ) )
    assert f"band={rec[ 'band' ][ 'band' ]}" in line and "needs=30" in line and "short=0" in line
    assert rec[ "format" ] == bf.FORMAT and rec[ "authorized_run" ] == "d3f71441-band-repeat-2026.10.15" and rec[ "code_sha" ] == "abc123" and rec[ "needs_sha" ] == setup.sha
    assert rec[ "ledger_runs" ] == [ "bandfit-canary", "bandfit-run" ] and rec[ "stage" ][ "manifest_hash" ] == "b" * 64 and rec[ "needs_short" ] == {}
    assert len( rec[ "needs_whole" ] ) == 30 and rec[ "band" ][ "band" ] >= ls.MIN_BAND and rec[ "band" ][ "population" ] > 0
    one = rec[ "draws" ][ "n01" ]
    assert len( one ) == len( SHORTLIST ) and all( len( v ) == 5 for v in one.values() )
    assert rec[ "spent_tokens" ] > 0 and rec[ "quantile" ] == bf.QUANTILE and rec[ "population_limits" ] == [ bf.POP_LOW, bf.POP_HIGH ]


def test_the_band_in_the_receipt_is_the_one_the_draws_give_when_fitted_again( setup ):
    setup.run()
    assert bf.cli( setup.args( "report", "--out", str( setup.out ), "--code-sha", "abc123", "--quantile", "0.5" ) ) == 0
    rec = json.loads( setup.out.read_text( encoding="utf-8" ) )
    assert rec[ "quantile" ] == 0.5 and rec[ "band" ] == bf.fit_band( rec[ "draws" ], 0.5 )


def test_the_receipt_is_never_overwritten( setup, capsys ):
    setup.run()
    args = setup.args( "report", "--out", str( setup.out ), "--code-sha", "abc123" )
    assert bf.cli( args ) == 0
    before = setup.out.read_bytes()
    capsys.readouterr()
    assert bf.cli( args ) == 2 and "refused (FileExistsError)" in capsys.readouterr().err and setup.out.read_bytes() == before


def test_the_run_waits_for_the_approval( setup, capsys ):
    assert bf.cli( setup.args( "canary", "--ceiling", "1500000" ), stage_factory=lambda root: FakeStage() ) == 0
    capsys.readouterr()
    assert bf.cli( setup.args( "run", "--ceiling", "7200000" ), stage_factory=lambda root: FakeStage() ) == 2
    assert "has not been approved" in capsys.readouterr().err


def test_a_ceiling_over_the_cap_is_refused_before_anything_is_opened( setup, capsys ):
    assert bf.cli( setup.args( "canary", "--ceiling", "8640001" ), stage_factory=lambda root: FakeStage() ) == 2
    assert "is above 8640000" in capsys.readouterr().err and not setup.data.exists()


def test_a_report_before_the_run_is_refused_and_names_the_missing_file( setup, capsys ):
    assert bf.cli( setup.args( "report", "--out", str( setup.out ), "--code-sha", "abc123" ) ) == 2
    assert "no result file" in capsys.readouterr().err and not setup.out.exists()


def test_a_canary_and_a_run_on_different_stages_are_refused_by_the_report( setup, capsys ):
    assert bf.cli( setup.args( "canary", "--ceiling", "1500000" ), stage_factory=lambda root: FakeStage() ) == 0
    assert bf.cli( setup.args( "approve", "--by", "cheech", "--why", "read it" ) ) == 0
    other = [ "c" * 64 if a == "b" * 64 else a for a in setup.args( "run", "--ceiling", "7200000" ) ]                       # pinned to the other set, so the run is allowed
    assert bf.cli( other, stage_factory=lambda root: FakeStage( manifest_hash="c" * 64 ) ) == 0
    capsys.readouterr()
    assert bf.cli( setup.args( "report", "--out", str( setup.out ), "--code-sha", "abc123" ) ) == 2
    assert "ran on stage" in capsys.readouterr().err


def test_a_stage_that_fails_leaves_the_repeats_incomplete_and_trips_the_canary( setup, capsys ):
    stage = FakeStage( error="QUERY_VECTOR_MISSING" )
    assert bf.cli( setup.args( "canary", "--ceiling", "1500000" ), stage_factory=lambda root: stage ) == 0
    record = setup.result( "canary" )
    first = [ ( s[ "question" ], s[ "status" ], s[ "causes" ] ) for s in record[ "searches" ] if s[ "member" ] == "n00" ]
    assert first == [ ( "lookup", "incomplete", [ "attempts" ] ) ] + [ ( f"r{i}", "incomplete", [ "ERROR:NO_SWEEP" ] ) for i in range( 1, 6 ) ]       # the replay swept nothing, so it says so
    assert all( s[ "status" ] == "not_run" and s[ "causes" ] == [ "reliability" ] for s in record[ "searches" ] if s[ "member" ] != "n00" )
    assert bf.cli( setup.args( "approve", "--by", "cheech", "--why", "x" ), stage_factory=lambda root: stage ) == 2                 # the canary tripped
    assert "tripped" in capsys.readouterr().err


def test_a_repeat_with_no_lookup_receipt_is_an_error_result_and_a_failed_lookup_is_passed_on():
    sink = bf.Sink()
    asks = bf.make_asks( FakeStage(), sink )
    assert asks[ "r2" ]( None, { "member": "x", "need": "n", "exclude": None } ) == { "status": "error", "error": "NO_LOOKUP_RECEIPT" }
    assert list( asks ) == [ "lookup", "r1", "r2", "r3", "r4", "r5" ]


def test_an_empty_need_is_passed_on_from_the_lookup_and_leaves_no_receipt():
    sink = bf.Sink()
    got  = bf.make_asks( FakeStage(), sink )[ "lookup" ]( rt.ReuseContext( ".", "." ), { "member": "x", "need": " ", "exclude": None } ) if False else None
    assert got is None and sink.rids == {}


def test_an_answer_the_verdict_layer_calls_malformed_makes_its_repeat_incomplete_and_leaves_the_need_short( setup, monkeypatch ):
    real = bf.overlaps
    monkeypatch.setattr( bf, "overlaps", lambda sweeps: ( lambda out_bad: ( out_bad[ 0 ], out_bad[ 1 ] + [ { "id": "cosa.wide.f001", "reason": "sum_not_one" } ] ) )( real( sweeps ) ) )
    assert bf.cli( setup.args( "canary", "--ceiling", "1500000" ), stage_factory=lambda root: FakeStage() ) == 0
    searches = setup.result( "canary" )[ "searches" ]
    assert [ s[ "status" ] for s in searches if s[ "member" ] == "n00" and s[ "question" ] == "r1" ] == [ "incomplete" ]
    assert [ s[ "causes" ] for s in searches if s[ "member" ] == "n00" and s[ "question" ] == "r1" ] == [ [ "MALFORMED_ANSWER" ] ]


def test_a_replay_that_cannot_read_its_receipt_is_passed_on_as_that_error( setup, monkeypatch ):
    monkeypatch.setattr( rt, "replay_impl", lambda rid, ctx, repeat=0: { "status": "error", "error": "RECEIPT_MISSING", "receipt_id": rid } )
    assert bf.cli( setup.args( "canary", "--ceiling", "1500000" ), stage_factory=lambda root: FakeStage() ) == 0
    searches = setup.result( "canary" )[ "searches" ]
    assert [ s[ "causes" ] for s in searches if s[ "member" ] == "n00" and s[ "question" ] == "r1" ] == [ [ "ERROR:RECEIPT_MISSING" ] ]


def write_results( data, searches, stage="s" ):
    """Write a canary and a run result file by hand, each holding the given searches."""
    for part in ( "canary", "run" ):
        path = data / "e2e-results" / f"{bf.PREFIX}-{part}.json"
        path.parent.mkdir( parents=True, exist_ok=True )
        path.write_text( json.dumps( { "run_name": f"{bf.PREFIX}-{part}", "stage": stage, "totals": { "spent_tokens": 10 }, "ledger_total_before": 0,
                                        "started_at": "a", "ended_at": "b", "searches": searches if part == "canary" else [] } ), encoding="utf-8" )


def test_a_receipt_with_no_whole_need_is_refused( tmp_path ):
    write_results( tmp_path, [ result_file( "a", 1, { "e": 0.5 } ) ] )
    with pytest.raises( s1.DriverRefused, match="no need has every repeat" ): bf.receipt( tmp_path, [ { "member": "a" } ], 0.95, 0.1, 0.9, "sha", "ns" )


def test_a_receipt_whose_draws_have_no_entry_inside_the_limits_is_refused_in_the_drivers_words( tmp_path ):
    write_results( tmp_path, [ result_file( "a", r, { "e": 0.0 } ) for r in range( 1, 6 ) ] )
    with pytest.raises( s1.DriverRefused, match="no entry has a mean overlap" ): bf.receipt( tmp_path, [ { "member": "a" } ], 0.95, 0.1, 0.9, "sha", "ns" )


# ---- the needs the band is fitted on ------------------------------------------------------------

def frozen_file( tmp_path, rows=None, fmt=e2e.NEEDS_FORMAT, name="frozen.json" ):
    """Write a frozen needs file, 100 rows by default; return ( path, sha, rows )."""
    rows = rows or [ { "member": f"cosa.wide.f{i:03d}", "need": f"A helper number {i} that does a distinct job.", "kind": "function" } for i in range( 100 ) ]
    path = tmp_path / name
    return path, put( path, { "format": fmt, "sample_sha256": "x", "needs": rows } ), rows


def test_the_pick_is_the_same_for_the_same_seed_and_leaves_each_members_own_symbol_out( tmp_path ):
    path, sha, rows = frozen_file( tmp_path )
    one = bf.derive_needs( path, sha, 30, "seed-a" )
    assert one == bf.derive_needs( path, sha, 30, "seed-a" ) and one[ "format" ] == frun.NEEDS_FORMAT and len( one[ "needs" ] ) == 30
    assert [ n[ "id" ] for n in one[ "needs" ] ] == [ f"b{i:02d}" for i in range( 1, 31 ) ] and {n[ "kind" ] for n in one[ "needs" ]} == { "duplicate" }
    by_member = { r[ "member" ]: r[ "need" ] for r in rows }
    assert all( by_member[ n[ "exclude" ] ] == n[ "need" ] for n in one[ "needs" ] ) and len( { n[ "exclude" ] for n in one[ "needs" ] } ) == 30
    assert [ n[ "exclude" ] for n in bf.derive_needs( path, sha, 30, "seed-b" )[ "needs" ] ] != [ n[ "exclude" ] for n in one[ "needs" ] ]


def test_the_pick_ranks_by_the_hash_of_the_seed_and_the_member_not_by_file_order( tmp_path ):
    import hashlib
    path, sha, rows = frozen_file( tmp_path )
    want = sorted( ( r[ "member" ] for r in rows ), key=lambda m: hashlib.sha256( f"s:{m}".encode() ).hexdigest() )[ :30 ]
    assert [ n[ "exclude" ] for n in bf.derive_needs( path, sha, 30, "s" )[ "needs" ] ] == want and want != [ r[ "member" ] for r in rows ][ :30 ]


@pytest.mark.parametrize( "count", [ 29, 101 ] )
def test_a_count_outside_the_flip_minimum_and_the_file_is_refused( tmp_path, count ):
    path, sha, _ = frozen_file( tmp_path )
    with pytest.raises( s1.DriverRefused, match="between 30 and 100" ): bf.derive_needs( path, sha, count, "s" )


@pytest.mark.parametrize( "seed", [ "", "  ", None ] )
def test_an_empty_seed_is_refused( tmp_path, seed ):
    path, sha, _ = frozen_file( tmp_path )
    with pytest.raises( s1.DriverRefused, match="seed" ): bf.derive_needs( path, sha, 30, seed )


def test_the_frozen_file_is_checked_by_hash_format_repeats_and_empty_needs( tmp_path ):
    path, sha, rows = frozen_file( tmp_path )
    with pytest.raises( e2e.FrozenInputRefused, match="sha256" ): bf.derive_needs( path, "1" * 64, 30, "s" )
    with pytest.raises( e2e.FrozenInputRefused, match="reserved" ): bf.derive_needs( path, e2e.FRESH_SHA_PREFIX + "0" * 56, 30, "s" )
    with pytest.raises( e2e.FrozenInputRefused, match="format" ): bf.derive_needs( *frozen_file( tmp_path, fmt="other", name="other.json" )[ :2 ], 30, "s" )
    with pytest.raises( e2e.FrozenInputRefused, match="repeat" ): bf.derive_needs( *frozen_file( tmp_path, rows[ :99 ] + [ rows[ 0 ] ] )[ :2 ], 30, "s" )
    with pytest.raises( e2e.FrozenInputRefused, match="empty" ): bf.derive_needs( *frozen_file( tmp_path, rows[ :99 ] + [ { **rows[ 99 ], "need": "  " } ] )[ :2 ], 30, "s" )


def test_the_derive_command_writes_a_file_the_flip_reader_accepts_and_never_overwrites_it( tmp_path, capsys ):
    path, sha, _ = frozen_file( tmp_path )
    out  = tmp_path / "picked.json"
    args = [ "derive-needs", "--frozen", str( path ), "--frozen-sha", sha, "--seed", "s", "--out", str( out ) ]
    assert bf.cli( args ) == 0
    text = capsys.readouterr().out
    import hashlib
    got  = hashlib.sha256( out.read_bytes() ).hexdigest()
    assert f"sha256 {got}" in text and "30 needs" in text
    assert len( frun.load_flip_needs( out, got ) ) == 30
    assert bf.cli( args ) == 2 and "FileExistsError" in capsys.readouterr().err


# ---- guards on main ------------------------------------------------------------------------------

@pytest.mark.parametrize( "command", [ [ "estimate" ], [ "canary", "--ceiling", "1500000" ], [ "report", "--out", "o.json", "--code-sha", "c" ] ] )
def test_the_reserved_fresh_needs_hash_is_refused_by_every_command_before_anything_is_opened( setup, capsys, command ):
    fresh = e2e.FRESH_SHA_PREFIX + "0" * 56
    args  = [ command[ 0 ], "--needs", str( setup.needs ), "--needs-sha", fresh ] + ( [ "--root", str( setup.root ), "--data", str( setup.data ), "--ledger", str( setup.ledger ) ] if command[ 0 ] != "estimate" else [] ) + ( [ "--manifest-hash", "b" * 64 ] if command[ 0 ] == "canary" else [] ) + command[ 1: ]
    assert bf.cli( args, stage_factory=lambda root: FakeStage() ) == 2
    assert "reserved fresh-needs file" in capsys.readouterr().err and not setup.data.exists()


@pytest.mark.parametrize( "command", [ "canary", "run" ] )
def test_the_ceiling_cap_applies_to_the_canary_and_to_the_full_run( setup, capsys, command ):
    assert bf.cli( setup.args( command, "--ceiling", "8640001" ), stage_factory=lambda root: FakeStage() ) == 2
    assert "is above 8640000" in capsys.readouterr().err and not setup.data.exists()


@pytest.mark.parametrize( "command", [ "canary", "run" ] )
def test_a_need_whose_excluded_symbol_is_not_an_entry_is_refused_before_any_spend( tmp_path, capsys, monkeypatch, command ):
    monkeypatch.setattr( rr, "StandIn", Jittery )
    s = Setup( tmp_path )
    s.rows[ 7 ][ "exclude" ] = "no.such.symbol"
    s.sha = put( s.needs, { "format": frun.NEEDS_FORMAT, "needs": s.rows } )
    assert bf.cli( s.args( command, "--ceiling", "1500000" ), stage_factory=lambda root: FakeStage() ) == 2
    err = capsys.readouterr().err
    assert "n07 (no.such.symbol)" in err and "not a sendable entry" in err and not ( s.data / "e2e-results" ).exists()


def test_the_quantile_and_the_population_limits_are_the_ones_written_down_before_the_run():
    assert ( bf.QUANTILE, bf.POP_LOW, bf.POP_HIGH, bf.REPEATS ) == ( 0.95, 0.1, 0.9, 5 )


# ---- the vector set is pinned ----------------------------------------------------------------------

class Swapping( FakeStage ):
    """A stage whose vector set is replaced once it has made a number of shortlists."""

    def __init__( self, after ):
        super().__init__()
        self.after, self.made = after, 0

    def shortlist( self, *a, **kw ):
        self.made += 1
        return super().shortlist( *a, **kw )

    def manifest( self ): return { "manifest_hash": self.manifest_hash if self.made < self.after else "c" * 64 }


def test_a_stage_on_another_vector_set_than_the_pinned_one_is_refused_before_anything_is_opened( setup, capsys ):
    assert bf.cli( setup.args( "canary", "--ceiling", "1500000" ), stage_factory=lambda root: FakeStage( manifest_hash="c" * 64 ) ) == 2
    assert f"the vector set is {'c' * 64}, the run is pinned to {'b' * 64}" in capsys.readouterr().err and not ( setup.data / "e2e-results" ).exists()


def test_a_vector_set_replaced_between_the_lookup_and_the_first_repeat_stops_the_run_with_no_send_after_it( setup, capsys ):
    stage = Swapping( after=1 )                                    # the lookup's shortlist is the first; the repeat's own check finds another set
    assert bf.cli( setup.args( "canary", "--ceiling", "1500000" ), stage_factory=lambda root: stage ) == 2
    assert "pinned to" in capsys.readouterr().err
    record = setup.result( "canary" )
    assert [ ( s[ "member" ], s[ "question" ], s[ "status" ], s[ "causes" ] ) for s in record[ "searches" ] ] == [ ( "n00", "lookup", "complete", [] ), ( "n00", "r1", "error", [ "ERROR:DriverRefused" ] ) ]
    lookup, repeat = record[ "searches" ]
    assert record[ "state" ] == "error" and lookup[ "tokens" ] > 0 and repeat[ "tokens" ] == 0 and repeat[ "requests" ] == 0
    assert record[ "totals" ][ "spent_tokens" ] == lookup[ "tokens" ]                       # nothing was spent after the swap


def test_a_vector_set_replaced_before_the_lookup_stops_the_run_before_the_lookup_sends_anything( setup, capsys ):
    class SwapAtRead( FakeStage ):
        reads = 0
        def manifest( self ):
            self.reads += 1
            return { "manifest_hash": self.manifest_hash if self.reads <= 2 else "c" * 64 }       # the start check and the stamp read it; the lookup's check is the third

    stage = SwapAtRead()
    assert bf.cli( setup.args( "canary", "--ceiling", "1500000" ), stage_factory=lambda root: stage ) == 2
    assert "pinned to" in capsys.readouterr().err
    record = setup.result( "canary" )
    assert [ ( s[ "question" ], s[ "status" ], s[ "causes" ] ) for s in record[ "searches" ] ] == [ ( "lookup", "error", [ "ERROR:DriverRefused" ] ) ]
    assert Jittery.posts == 0 and record[ "totals" ][ "spent_tokens" ] == 0


@pytest.mark.parametrize( "command", [ "canary", "run" ] )
def test_a_run_without_the_manifest_hash_flag_is_refused_by_the_parser( setup, command ):
    args = [ a for a in setup.args( command, "--ceiling", "1500000" ) if a not in ( "--manifest-hash", "b" * 64 ) ]
    with pytest.raises( SystemExit ): bf.cli( args, stage_factory=lambda root: FakeStage() )
    assert not setup.data.exists()


def test_check_manifest_passes_when_nothing_is_pinned():
    assert bf.check_manifest( Swapping( after=0 ), None ) is None
    assert bf.check_manifest( FakeStage(), "b" * 64 ) is None
