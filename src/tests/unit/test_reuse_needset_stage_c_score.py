"""
Scoring the judge-only run on synthetic reports, against the pre-registered mark.

Every report here is built by report_of(); no model, no search and no run folder is read.
"""
import json
import random

import pytest

from lupin_mcp import reuse_tools as rt
from lupin_mcp.reuse_needset import judge_probe as jp
from tests.unit.test_reuse_pack_send import ENTRIES, NEED, Fake

from lupin_mcp.reuse_needset import stage_c_score as sc

STRATA = { "flag": ( 20, 10 ), "monolith:structural": ( 10, 10 ), "monolith:neighbour": ( 5, 12 ) }
SMALL  = 200


def side( p, answered=True ):
    """Return one side's reading."""
    return { "answered": answered, "p_overlap": p, "confidence": 0.9, "choice": "reuse" }


def report_of( same_p=0.8, other_p=0.1, noise=0.02, a_p=0.97, seed=7, unsure=0, three=0, undrafted=0, cue=0, strata=None, tokens=True, status="answered", same_fn=None ):
    """
    Build a synthetic stage-c-report with three repeats per pair.

    The first `unsure` flag pairs carry an unsure mark, the first `three` pairs have a third rater, the first `cue` pairs carry the cue.
    """
    rng, results, n = random.Random( seed ), [ ], 0
    for stratum, ( ns, no ) in ( strata or STRATA ).items():
        for label, count, base in ( ( sc.SAME, ns, same_p ), ( sc.NOT_SAME, no, other_p ) ):
            for i in range( count ):
                n += 1
                mark = base if same_fn is None or label != sc.SAME else same_fn( i )
                for repeat in range( 1, 4 ):
                    p = min( 1.0, max( 0.0, mark + rng.uniform( -noise, noise ) ) )
                    results.append( { "pair": f"p{n:03}", "stratum": stratum, "label": label, "unsure": stratum == "flag" and n <= unsure, "raters": 3 if n <= three else 2, "cue": n <= cue,
                                      "repeat": repeat, "side_b": side( p ), "side_a": side( min( 1.0, a_p + rng.uniform( -noise, noise ) ) ), "request_hash": f"h{n}-{repeat}",
                                      "tokens_in": 100 if tokens else 0, "status": status } )
    lost = [ { "pair": f"u{i}", "stratum": "flag", "label": sc.SAME, "unsure": False, "raters": 2 } for i in range( undrafted ) ]
    return { "results": results, "undrafted": lost, "refused": [ ] }


# -- the arithmetic -----------------------------------------------------------------------------

def test_auc_counts_wins_and_ties_by_hand():
    assert sc.auc_counts( [ 0.9, 0.5 ], [ 0.5, 0.1 ] ) == ( 3.5, 4 )
    assert sc.auc_counts( [ ], [ 0.1 ] ) == ( 0.0, 0 )


def test_the_primary_auc_weights_strata_by_pairings_and_the_pooled_ignores_strata():
    groups = { "a": { sc.SAME: [ 0.9 ], sc.NOT_SAME: [ 0.1, 0.1 ] }, "b": { sc.SAME: [ 0.2, 0.2 ], sc.NOT_SAME: [ 0.8 ] }, "c": { sc.SAME: [ ], sc.NOT_SAME: [ 0.5 ] } }
    got    = sc.aucs( groups )
    assert got[ "by_stratum" ] == { "a": 1.0, "b": 0.0, "c": None }
    assert got[ "primary" ] == pytest.approx( 2 / 4 ), "wins 2 of 4 pairings, not the mean of 1.0 and 0.0 unweighted"
    assert got[ "pooled" ] == pytest.approx( sc.auc_counts( [ 0.9, 0.2, 0.2 ], [ 0.1, 0.1, 0.8, 0.5 ] )[ 0 ] / 12 )
    assert sc.aucs( { } ) == { "by_stratum": { }, "primary": None, "pooled": None }


def test_split_leaves_out_a_pair_with_no_rating():
    got = sc.split( [ { "stratum": "s", "label": sc.SAME, "r": 0.5 }, { "stratum": "s", "label": sc.NOT_SAME, "r": None } ] )
    assert got == { "s": { sc.SAME: [ 0.5 ], sc.NOT_SAME: [ ] } }


def test_percentile_interpolates_and_handles_none_and_the_top():
    assert sc.percentile( [ ], 0.5 ) is None and sc.percentile( [ 1.0, 3.0 ], 0.5 ) == 2.0 and sc.percentile( [ 1.0, 3.0 ], 1.0 ) == 3.0 and sc.percentile( [ 4.0 ], 0.25 ) == 4.0


def test_bootstrap_is_seeded_brackets_the_point_and_gives_none_for_an_empty_class():
    groups = { "s": { sc.SAME: [ 0.9, 0.8, 0.7, 0.3 ], sc.NOT_SAME: [ 0.1, 0.2, 0.4, 0.6 ] }, "empty": { sc.SAME: [ ], sc.NOT_SAME: [ 0.5 ] } }
    one, two = sc.bootstrap( groups, 300 ), sc.bootstrap( groups, 300 )
    wide     = { "s": { sc.SAME: [ i / 40 for i in range( 40 ) ], sc.NOT_SAME: [ ( i * 7 % 40 ) / 40 for i in range( 40 ) ] } }
    assert one == two and sc.bootstrap( wide, 300 ) != sc.bootstrap( wide, 300, seed=1 )
    point = sc.aucs( groups )[ "primary" ]
    assert one[ "primary" ][ 0 ] <= point <= one[ "primary" ][ 1 ] and one[ "by_stratum" ][ "empty" ] == ( None, None )
    assert sc.bootstrap( { }, 5 ) == { "primary": ( None, None ), "pooled": ( None, None ), "by_stratum": { } }


def test_newcombe_and_wilson_agree_with_the_formula_on_a_known_case():
    got = sc.newcombe( 56, 70, 48, 80 )                       # Newcombe 1998, Table II, method 10: 0.2000, 0.0524 to 0.3339
    assert got[ "d" ] == pytest.approx( 0.2 ) and got[ "low" ] == pytest.approx( 0.0524, abs=0.0005 ) and got[ "high" ] == pytest.approx( 0.3339, abs=0.0005 )


def test_acceptance_counts_at_the_line_inclusive_and_names_an_empty_class():
    got = sc.acceptance( [ 0.3, 0.29, 0.9 ], [ 0.1, 0.3 ] )
    assert got[ "same" ][ "k" ] == 2 and got[ "same" ][ "n" ] == 3 and got[ "not_same" ][ "k" ] == 1 and got[ "not_same" ][ "rate" ] == 0.5, "0.30 itself is accepted"
    empty = sc.acceptance( [ ], [ 0.5 ] )
    assert empty[ "diff" ] is None and empty[ "same" ][ "rate" ] is None and empty[ "same" ][ "interval" ] == ( None, None )


def test_the_line_where_same_job_acceptance_is_eighty_percent_is_read_from_the_ratings():
    same = [ 0.1 * i for i in range( 1, 11 ) ]
    got  = sc.reach_line( same, [ 0.85, 0.2, 0.15 ] )
    assert got[ "line" ] == pytest.approx( 0.3 ) and got[ "not_same_rate" ] == pytest.approx( 1 / 3 )
    assert sc.reach_line( [ ], [ 0.1 ] ) == { "line": None, "not_same_rate": None } and sc.reach_line( [ 0.5 ], [ ] ) == { "line": None, "not_same_rate": None }


def test_spread_and_pair_sd_and_pearson():
    assert sc.spread( [ ] ) == { "n": 0 } and sc.spread( [ 1.0, 2.0, 3.0 ] )[ "median" ] == 2.0
    assert sc.pair_sd_median( [ { "repeats": { 1: 0.5, 2: 0.5, 3: 0.5 } }, { "repeats": { 1: 0.0, 2: 0.2 } }, { "repeats": { 1: 0.9 } } ] ) == pytest.approx( 0.07071068, abs=1e-6 )
    assert sc.pair_sd_median( [ { "repeats": { 1: 0.9 } } ] ) is None
    assert sc.pearson( [ 1, 2, 3 ], [ 2, 4, 6 ] ) == pytest.approx( 1.0 ) and sc.pearson( [ 1 ], [ 1 ] ) is None and sc.pearson( [ 1, 1 ], [ 1, 2 ] ) is None and sc.pearson( [ 1, 2 ], [ 3, 3 ] ) is None


# -- the levels, one row at a time ---------------------------------------------------------------

@pytest.mark.parametrize( "point, interval, level", [ ( 0.40, ( 0.30, 0.49 ), "inverted" ), ( 0.85, ( 0.75, 0.95 ), "strong" ), ( 0.80, ( 0.69, 0.9 ), "moderate" ), ( 0.72, ( 0.61, 0.8 ), "moderate" ),
                                                       ( 0.72, ( 0.60, 0.8 ), "weak" ), ( 0.45, ( 0.3, 0.50 ), "none shown" ), ( 0.80, ( 0.70, 0.9 ), "strong" ), ( 0.60, ( 0.51, 0.7 ), "weak" ), ( 0.55, ( 0.50, 0.7 ), "none shown" ), ( 0.5, ( 0.4, 0.6 ), "none shown" ),
                                                       ( None, ( None, None ), "none shown" ) ] )
def test_the_threshold_free_levels_follow_the_table( point, interval, level ):
    assert sc.threshold_free_level( point, interval ) == level


def test_the_line_level_needs_d_its_lower_bound_and_a_low_false_accept_rate():
    mk = lambda same, other: sc.acceptance( same, other )
    assert sc.line_level( mk( [ 0.9 ] * 20, [ 0.1 ] * 20 ) ) == "usable"
    assert sc.line_level( mk( [ 0.9 ] * 20, [ 0.9 ] * 11 + [ 0.1 ] * 9 ) ) == "not usable at the line", "D is 0.45 but the false-accept rate is 0.55"
    assert sc.line_level( mk( [ 0.9 ] * 8 + [ 0.1 ] * 12, [ 0.1 ] * 20 ) ) == "usable", "D is exactly 0.40, which is enough"
    assert sc.line_level( mk( [ 0.9 ] * 3 + [ 0.1 ] * 7, [ 0.1 ] * 10 ) ) == "not usable at the line", "D is 0.3, below 0.40"
    assert sc.line_level( mk( [ ], [ 0.1 ] ) ) == "not usable at the line"


def test_a_big_d_with_a_lower_bound_at_or_below_zero_is_not_usable():
    accept = { "diff": { "d": 0.5, "low": 0.0, "high": 0.9 }, "not_same": { "rate": 0.1 } }
    assert sc.line_level( accept ) == "not usable at the line"


# -- whole reports -------------------------------------------------------------------------------

def test_a_clean_separation_is_strong_and_usable_with_no_level_for_the_small_stratum():
    out  = sc.score( report_of(), SMALL )
    pop  = out[ "populations" ][ "all_drafted" ]
    assert out[ "headline" ] == { "covers": "67 of 67 pairs judged", "blocked_by": [ ], "threshold_free": "strong", "line": "usable" }
    assert pop[ "auc" ][ "primary" ] == 1.0 and pop[ "counts" ] == { sc.SAME: 35, sc.NOT_SAME: 32 }
    assert pop[ "strata" ][ "monolith:neighbour" ][ "levels" ] == { "threshold_free": sc.NO_LEVEL, "line": sc.NO_LEVEL }, "5 same-job pairs is under 10"
    assert pop[ "strata" ][ "flag" ][ "levels" ] == { "threshold_free": "strong", "line": "usable" } and pop[ "consistent" ] == { "flag": True, "monolith:structural": True }
    assert pop[ "floor" ][ "floor_primary" ] == 0.0 and len( pop[ "floor" ][ "primary" ] ) == 3 and pop[ "floor" ][ "pair_sd_median" ] > 0
    assert set( pop[ "descriptive" ][ "fixed_lines" ] ) == { "0.5", "0.7", "0.9" } and pop[ "descriptive" ][ "at_same_80" ][ "not_same_rate" ] == 0.0


def test_ratings_with_no_separation_show_none_and_are_not_usable():
    out = sc.score( report_of( same_p=0.4, other_p=0.4, noise=0.2 ), SMALL )
    assert out[ "headline" ][ "threshold_free" ] == "none shown" and out[ "headline" ][ "line" ] == "not usable at the line"


def test_inverted_ratings_are_named_inverted():
    out = sc.score( report_of( same_p=0.1, other_p=0.8 ), SMALL )
    assert out[ "headline" ][ "threshold_free" ] == "inverted"


def pairs_of( same, other, stratum="flag" ):
    """Return rated pairs of one stratum, each with the three repeats equal to its rating."""
    one = lambda name, label, r: { "pair": name, "stratum": stratum, "label": label, "r": r, "repeats": { 1: r, 2: r, 3: r } }
    return [ one( f"{stratum}-s{i}", sc.SAME, r ) for i, r in enumerate( same ) ] + [ one( f"{stratum}-n{i}", sc.NOT_SAME, r ) for i, r in enumerate( other ) ]


def repeats_of( pairs, flip=() ):
    """Return the by-repeat view of pairs, with every rating turned over in the repeats of flip."""
    return { n: [ { "stratum": p[ "stratum" ], "label": p[ "label" ], "r": 1 - p[ "r" ] if n in flip else p[ "r" ] } for p in pairs ] for n in ( 1, 2, 3 ) }


@pytest.mark.parametrize( "level, point, floor, expect", [ ( "strong", 0.9, 0.3, "strong" ), ( "strong", 0.9, 0.4, "none shown" ), ( "weak", 0.6, 0.1, "none shown" ), ( "moderate", 0.75, 0.2, "moderate" ),
                                                            ( "inverted", 0.1, 0.3, "inverted" ), ( "inverted", 0.1, 0.4, "none shown" ), ( "inverted", 0.4, 0.2, "none shown" ),
                                                            ( "strong", 0.9, None, "none shown" ), ( "inverted", 0.1, None, "none shown" ), ( "none shown", 0.5, 0.0, "none shown" ) ] )
def test_the_floor_cap_is_symmetric( level, point, floor, expect ):
    assert sc.cap_level( level, point, floor ) == expect


def test_an_auc_above_half_by_no_more_than_the_repeat_floor_is_capped_and_so_is_an_inverted_one():
    good = pairs_of( [ 0.9 ] * 12, [ 0.1 ] * 12 )
    assert sc.figures( good, repeats_of( good ), 50 )[ "levels" ][ "threshold_free" ] == "strong"
    wild = sc.figures( good, repeats_of( good, flip=( 2, ) ), 50 )
    assert wild[ "floor" ][ "floor_primary" ] == 1.0 and wild[ "levels" ][ "threshold_free" ] == "none shown"
    bad = pairs_of( [ 0.1 ] * 12, [ 0.9 ] * 12 )
    assert sc.figures( bad, repeats_of( bad ), 50 )[ "levels" ][ "threshold_free" ] == "inverted"
    assert sc.figures( bad, repeats_of( bad, flip=( 2, ) ), 50 )[ "levels" ][ "threshold_free" ] == "none shown", "an inverted AUC is capped by the floor as a positive one is"


def test_each_stratum_is_capped_by_its_own_floor_and_not_the_overall_one():
    steady, shaky = pairs_of( [ 0.9 ] * 12, [ 0.1 ] * 12, "flag" ), pairs_of( [ 0.9 ] * 12, [ 0.1 ] * 12, "monolith:structural" )
    pairs = steady + shaky
    rep   = { n: repeats_of( steady )[ n ] + repeats_of( shaky, flip=( 2, ) )[ n ] for n in ( 1, 2, 3 ) }
    got   = sc.figures( pairs, rep, 50 )
    assert got[ "floor" ][ "floor_by_stratum" ] == { "flag": 0.0, "monolith:structural": 1.0 } and got[ "floor" ][ "floor_primary" ] == 0.5
    assert got[ "levels" ][ "threshold_free" ] == "none shown", "the overall AUC of 1.0 beats a floor of 0.5 by exactly the floor"
    assert got[ "strata" ][ "flag" ][ "levels" ][ "threshold_free" ] == "strong" and got[ "strata" ][ "flag" ][ "floor" ] == 0.0, "flag keeps its level: the overall floor does not apply"
    assert got[ "strata" ][ "monolith:structural" ][ "levels" ][ "threshold_free" ] == "none shown" and got[ "strata" ][ "monolith:structural" ][ "floor" ] == 1.0


def test_a_stratum_with_only_one_class_has_no_auc_and_no_level():
    pairs = pairs_of( [ 0.9 ] * 12, [ 0.1 ] * 12 ) + pairs_of( [ ], [ 0.2 ] * 3, "monolith:neighbour" )
    got   = sc.figures( pairs, repeats_of( pairs ), 50 )
    assert got[ "strata" ][ "monolith:neighbour" ][ "auc" ] is None and got[ "strata" ][ "monolith:neighbour" ][ "floor" ] is None
    assert got[ "strata" ][ "monolith:neighbour" ][ "levels" ] == { "threshold_free": sc.NO_LEVEL, "line": sc.NO_LEVEL }


def test_a_missing_repeat_makes_the_floor_unavailable_and_blocks_the_run():
    rep = report_of()
    rep[ "results" ] = [ r for r in rep[ "results" ] if not ( r[ "pair" ] == "p001" and r[ "repeat" ] == 3 ) ]
    out = sc.score( rep, SMALL )
    assert out[ "valid_run" ][ "short_pairs" ] == [ "p001" ] and sc.NO_LEVEL == out[ "headline" ][ "threshold_free" ] and any( "lack a repeat" in b for b in out[ "headline" ][ "blocked_by" ] )


def test_a_repeat_that_every_pair_lacks_leaves_the_floor_none_and_caps_the_level():
    rep = report_of()
    rep[ "results" ] = [ r for r in rep[ "results" ] if r[ "repeat" ] != 3 ]
    pop = sc.score( rep, SMALL )[ "populations" ][ "all_drafted" ]
    assert pop[ "floor" ][ "floor_primary" ] is None and pop[ "levels" ][ "threshold_free" ] == "none shown"


def test_drafting_that_loses_more_than_fifteen_percent_of_a_class_is_coverage_limited():
    out = sc.score( report_of( undrafted=8 ), SMALL )
    assert out[ "coverage" ][ "limited" ] is True and out[ "coverage" ][ "by_class" ][ sc.SAME ][ "undrafted" ] == 8 and COVERAGE in out[ "headline" ][ "blocked_by" ]
    ok = sc.score( report_of( undrafted=5 ), SMALL )
    assert ok[ "coverage" ][ "limited" ] is False and ok[ "coverage" ][ "by_stratum" ][ "flag" ][ "lost" ] == pytest.approx( 5 / 35 ) and ok[ "headline" ][ "blocked_by" ] == [ ]


COVERAGE = sc.COVERAGE_LIMITED


@pytest.mark.parametrize( "change, reason", [ ( "dup", "shares its request hash" ), ( "tokens", "reported no tokens" ), ( "status", "was not answered" ), ( "side", "was not answered" ), ( "empty", "no results" ) ] )
def test_a_run_that_is_not_valid_awards_no_level( change, reason ):
    rep = report_of()
    if change == "dup": rep[ "results" ][ 1 ][ "request_hash" ] = rep[ "results" ][ 0 ][ "request_hash" ]
    if change == "tokens": rep[ "results" ][ 0 ][ "tokens_in" ] = 0
    if change == "status": rep[ "results" ][ 0 ][ "status" ] = "failed"
    if change == "side": rep[ "results" ][ 0 ][ "side_a" ] = side( 0.0, answered=False )
    if change == "empty": rep = { "results": [ ], "undrafted": [ ], "refused": [ ] }
    if change == "empty":
        assert sc.valid_run( [ ] )[ "valid" ] is False and reason in sc.valid_run( [ ] )[ "reasons" ][ 0 ]
        return
    out = sc.score( rep, 20 )
    assert out[ "valid_run" ][ "valid" ] is False and out[ "headline" ][ "threshold_free" ] == sc.NO_LEVEL and out[ "headline" ][ "line" ] == sc.NO_LEVEL
    assert any( reason in r for r in out[ "valid_run" ][ "reasons" ] )


def test_a_side_a_that_the_judge_does_not_recognise_awards_no_level_and_lists_the_failing_pairs():
    out  = sc.score( report_of( a_p=0.1 ), SMALL )
    side_a = out[ "side_a" ]
    assert side_a[ "passed" ] is False and len( side_a[ "failing" ] ) == 67 and side_a[ "by_stratum" ][ "flag" ][ "below_line" ] == 30 and side_a[ "by_class" ][ sc.SAME ][ "below_line" ] == 35
    assert "did not recognise" in " ".join( out[ "headline" ][ "blocked_by" ] ) and out[ "headline" ][ "line" ] == sc.NO_LEVEL


def test_the_side_a_check_needs_both_the_share_and_the_median():
    pairs = lambda rs: { f"p{i}": { "stratum": "s", "label": sc.SAME, "r": r } for i, r in enumerate( rs ) }
    b     = lambda rs: { f"p{i}": { "stratum": "s", "label": sc.SAME, "r": r } for i, r in enumerate( rs ) }
    low_median = [ 0.5 ] * 20
    assert sc.side_a_check( pairs( low_median ), b( low_median ) )[ "passed" ] is False, "all at the line but the median is under 0.90"
    one_low    = [ 0.99 ] * 19 + [ 0.1 ]
    assert sc.side_a_check( pairs( one_low ), b( one_low ) )[ "passed" ] is True, "95% at the line and the median high"
    two_low    = [ 0.99 ] * 18 + [ 0.1 ] * 2
    assert sc.side_a_check( pairs( two_low ), b( two_low ) )[ "passed" ] is False
    nothing    = sc.side_a_check( { "p": { "stratum": "s", "label": sc.SAME, "r": None } }, { "p": { "stratum": "s", "label": sc.SAME, "r": 0.5 } } )
    assert nothing[ "passed" ] is False and nothing[ "median" ] is None and nothing[ "correlation" ][ sc.SAME ] is None


def test_the_side_a_to_side_b_correlation_is_printed_per_class():
    out = sc.score( report_of( same_fn=lambda i: 0.5 + 0.02 * i, noise=0.001 ), SMALL )
    assert set( out[ "side_a" ][ "correlation" ] ) == { sc.SAME, sc.NOT_SAME }


def test_the_populations_drop_unsure_pairs_and_pairs_with_a_third_rater_and_cue_pairs_only_when_there_are_some():
    out = sc.score( report_of( unsure=3, three=10, cue=4 ), SMALL )
    pops = out[ "populations" ]
    assert set( pops ) == set( sc.POPULATIONS ) and pops[ "all_drafted" ][ "pairs" ] == 67 and pops[ "without_unsure" ][ "pairs" ] == 64
    assert pops[ "two_agreeing_raters" ][ "pairs" ] == 57 and pops[ "without_cue_pairs" ][ "pairs" ] == 63
    assert "without_cue_pairs" not in sc.score( report_of(), SMALL )[ "populations" ]


def test_the_headline_is_the_lowest_level_of_the_populations():
    levels = [ "strong", "moderate", "strong" ]
    assert sc.lowest( levels, sc.THRESHOLD_FREE ) == "moderate" and sc.lowest( [ "usable", "not usable at the line" ], sc.LINE_LEVELS ) == "not usable at the line"
    mixed = [ { "pair": "x", "unsure": True, "raters": 3, "cue": True }, { "pair": "y", "unsure": False, "raters": 2, "cue": False } ]
    assert [ [ p[ "pair" ] for p in sc.population_pairs( mixed, n ) ] for n in sc.POPULATIONS ] == [ [ "x", "y" ], [ "y" ], [ "y" ], [ "y" ] ]


def test_mean_ratings_averages_the_answered_repeats_and_gives_none_when_none_answered():
    row = lambda pair, repeat, p, ok=True: { "pair": pair, "stratum": "s", "label": sc.SAME, "unsure": False, "raters": 2, "cue": False, "repeat": repeat, "side_b": side( p, ok ), "side_a": side( 0.5 ) }
    got = sc.mean_ratings( [ row( "a", 1, 0.2 ), row( "a", 2, 0.4 ), row( "a", 3, 0.9, ok=False ), row( "b", 1, 0.5, ok=False ) ] )
    assert got[ "a" ][ "r" ] == pytest.approx( 0.3 ) and sorted( got[ "a" ][ "repeats" ] ) == [ 1, 2 ] and got[ "b" ][ "r" ] is None


def test_a_report_with_one_stratum_is_scored_and_the_missing_stratum_is_not_in_the_consistency_read():
    rep = report_of( strata={ "flag": ( 12, 12 ) } )
    out = sc.score( rep, 50 )
    assert out[ "populations" ][ "all_drafted" ][ "consistent" ] == { "flag": True }


# -- the command line ----------------------------------------------------------------------------

def test_main_prints_the_headline_and_writes_the_scored_json( tmp_path, capsys ):
    path, out = tmp_path / "stage-c-report.json", tmp_path / "scored.json"
    path.write_text( json.dumps( report_of( cue=2 ) ), encoding="utf-8" )
    assert sc.main( [ "--report", str( path ), "--out", str( out ), "--resamples", "50" ] ) == 0
    text = capsys.readouterr().out
    assert "headline: strong / usable" in text and "all_drafted" in text and "blocked by: nothing" in text and "drafting lost: not_same 0/32, same_job 0/35" in text and "population 67 of 67" in text
    assert json.loads( out.read_text( encoding="utf-8" ) )[ "headline" ][ "threshold_free" ] == "strong"
    assert sc.main( [ "--report", str( path ), "--resamples", "20" ] ) == 0 and not ( tmp_path / "other.json" ).exists()


def test_render_names_a_population_with_no_auc():
    scored = { "headline": { "covers": "1 of 2 pairs judged", "blocked_by": [ "x" ], "threshold_free": sc.NO_LEVEL, "line": sc.NO_LEVEL }, "coverage": { "by_class": { "c": { "drafted": 1, "undrafted": 1 } }, "population": { "judged": 2, "of": 2 }, "refused": { "total": 0, "by_class_stratum": { } } },
               "populations": { "p": { "pairs": 0, "auc": { "primary": None }, "levels": { "threshold_free": "none shown", "line": "not usable at the line" } } } }
    assert any( "n/a" in line for line in sc.render( scored ) ) and "blocked by: ['x']" in sc.render( scored )


def test_the_boundaries_sit_where_the_mark_puts_them():
    edge = { "diff": { "d": 0.5, "low": 0.1, "high": 0.9 }, "not_same": { "rate": 0.5 } }
    assert sc.line_level( edge ) == "usable", "a false-accept rate of exactly 0.50 is allowed"
    rows = lambda _n: [ { "stratum": "s", "label": sc.SAME } for _ in range( 17 ) ]
    assert sc.coverage( rows( 0 ), [ { "stratum": "s", "label": sc.SAME } ] * 3 )[ "limited" ] is False, "3 of 20 is exactly 15%, which is allowed"
    assert sc.coverage( rows( 0 ), [ { "stratum": "s", "label": sc.SAME } ] * 4 )[ "limited" ] is True
    even = { f"p{i}": { "stratum": "s", "label": sc.SAME, "r": 0.90 } for i in range( 10 ) }
    assert sc.side_a_check( even, even )[ "passed" ] is True, "a median of exactly 0.90 passes"
    assert sc.reach_line( [ 0.1 * i for i in range( 1, 8 ) ], [ 0.25 ] )[ "line" ] == pytest.approx( 0.2 ), "6 of 7 reaches 0.80; the next line up gives 5 of 7"


def test_a_point_that_exceeds_one_half_by_exactly_the_floor_is_capped():
    pairs  = [ { "pair": f"s{i}", "stratum": "flag", "label": sc.SAME, "r": 0.9, "repeats": { 1: 0.9, 2: 0.5, 3: 0.9 } } for i in range( 12 ) ] + \
             [ { "pair": f"n{i}", "stratum": "flag", "label": sc.NOT_SAME, "r": 0.1, "repeats": { 1: 0.1, 2: 0.5, 3: 0.1 } } for i in range( 12 ) ]
    rep    = { n: [ { "stratum": p[ "stratum" ], "label": p[ "label" ], "r": p[ "repeats" ][ n ] } for p in pairs ] for n in ( 1, 2, 3 ) }
    got    = sc.figures( pairs, rep, 50 )
    assert got[ "floor" ][ "floor_primary" ] == 0.5 and got[ "auc" ][ "primary" ] == 1.0 and got[ "levels" ][ "threshold_free" ] == "none shown"


def test_the_scorer_reads_rows_made_by_the_real_request_poster():
    """Rows come from judge_probe.ask_request over the real pack sender, renamed as the runner."""
    rows = [ ]
    for repeat in ( 1, 2, 3 ):
        request = { "pair": "p1", "label": jp.SAME_JOB, "arm": "stage_c", "repeat": repeat, "need": f"{NEED} {repeat}", "entries": ENTRIES[ :2 ], "template": rt.PROMPT_TEMPLATE }
        got     = jp.ask_request( Fake(), request )
        rows.append( { **got, "stratum": "flag", "unsure": False, "raters": 2, "cue": False, "side_b": got[ "plant" ], "side_a": got[ "original" ] } )
    assert jp.SAME_JOB == sc.SAME and jp.NOT_SAME == sc.NOT_SAME
    pairs = sc.mean_ratings( rows )
    assert pairs[ "p1" ][ "r" ] == pytest.approx( 0.9 ) and sorted( pairs[ "p1" ][ "repeats" ] ) == [ 1, 2, 3 ] and sc.mean_ratings( rows, "side_a" )[ "p1" ][ "r" ] == pytest.approx( 0.9 )
    assert sc.valid_run( rows )[ "valid" ] is True and sc.valid_run( rows )[ "distinct_hashes" ] == 3


def refused_rows( n, label=sc.NOT_SAME, stratum="flag", reasons=( "planted side", ) ):
    """Return n refused rows of one class and stratum."""
    return [ { "pair": f"r{label}{stratum}{i}", "stratum": stratum, "label": label, "unsure": False, "raters": 2, "reasons": list( reasons ) } for i in range( n ) ]


def test_refused_pairs_print_as_a_fixed_row_with_reasons_and_stay_out_of_the_fifteen_percent_rule():
    rep = report_of()
    rep[ "refused" ] = refused_rows( 20 ) + refused_rows( 2, sc.SAME, "monolith:structural", ( "planted side", "anonymous callback" ) )
    out = sc.score( rep, 50 )
    gone = out[ "coverage" ][ "refused" ]
    assert out[ "coverage" ][ "limited" ] is False and out[ "headline" ][ "blocked_by" ] == [ ], "20 refused of 52 not-same pairs would have fired the rule over the whole population"
    assert out[ "coverage" ][ "by_class" ][ sc.NOT_SAME ] == { "drafted": 32, "undrafted": 0, "lost": 0.0 } and out[ "coverage" ][ "population" ] == { "judged": 67, "of": 89 }
    assert gone[ "total" ] == 22 and gone[ "by_class" ] == { sc.NOT_SAME: 20, sc.SAME: 2 } and gone[ "by_stratum" ][ "flag" ] == 20 and gone[ "by_stratum" ][ "monolith:neighbour" ] == 0
    assert gone[ "by_reason" ] == { "planted side": 22, "anonymous callback": 2 }
    cells = gone[ "by_class_stratum" ]
    assert cells[ "not_same/flag" ] == { "n": 20, "reasons": { "planted side": 20 } } and cells[ "same_job/monolith:structural" ][ "reasons" ] == { "planted side": 2, "anonymous callback": 2 }
    assert cells[ "same_job/monolith:neighbour" ] == { "n": 0, "reasons": { } } and len( cells ) == 6, "a cell for every class and stratum, zero where none"


def test_the_fifteen_percent_rule_counts_drafting_losses_over_the_judged_population_only():
    rep = report_of( undrafted=8 )
    rep[ "refused" ] = refused_rows( 40, sc.SAME )
    out = sc.score( rep, 50 )
    assert out[ "coverage" ][ "by_class" ][ sc.SAME ] == { "drafted": 35, "undrafted": 8, "lost": 8 / 43 } and out[ "coverage" ][ "limited" ] is True and COVERAGE in out[ "headline" ][ "blocked_by" ]
    ok = report_of( undrafted=5 )
    ok[ "refused" ] = refused_rows( 40, sc.SAME )
    assert sc.score( ok, 50 )[ "coverage" ][ "limited" ] is False, "5 of 40 is under 15%, whatever was refused"


def test_the_printed_output_opens_with_the_population_and_the_refused_row_before_any_figure():
    rep = report_of()
    rep[ "refused" ] = refused_rows( 3, reasons=( "planted side", "anonymous callback" ) )
    lines = sc.render( sc.score( rep, 50 ) )
    assert lines[ 0 ] == "population 67 of 70; 3 pairs refused, not judged, outside the population"
    scored = sc.score( rep, 50 )
    assert scored[ "headline" ][ "covers" ] == "67 of 70 pairs judged" and "headline: strong / usable ( 67 of 70 pairs judged; the refused row above is not judged )" in lines
    assert "refused not_same/flag: 3 anonymous callback 3, planted side 3" in lines and "refused same_job/flag: 0" in lines
    last_refused = max( i for i, line in enumerate( lines ) if line.startswith( "refused" ) )
    first_other  = min( i for i, line in enumerate( lines ) if line.startswith( ( "drafting lost", "blocked by", "headline", "all_drafted" ) ) )
    assert last_refused < first_other and last_refused == 6, "six cells ( two classes, three strata ) print before drafting, the headline or a figure"


def test_the_numbers_of_the_mark_are_pinned_to_literals():
    """Each constant is written here as the mark gives it, so a drift in the module is seen."""
    assert ( sc.LINE, sc.FIXED_LINES, sc.SAME_REACH, sc.RESAMPLES, sc.SEED, sc.REPEATS ) == ( 0.30, ( 0.50, 0.70, 0.90 ), 0.80, 10000, 20261102, 3 )
    assert ( sc.MIN_PER_CLASS, sc.MAX_LOSS, sc.SIDE_A_SHARE, sc.SIDE_A_MEDIAN ) == ( 10, 0.15, 0.95, 0.90 )
    assert ( sc.STRONG, sc.MODERATE, sc.D_USABLE, sc.FALSE_ACCEPT ) == ( ( 0.80, 0.70 ), ( 0.70, 0.60 ), 0.40, 0.50 )


def test_a_report_with_no_refused_key_is_not_valid_so_a_forgotten_write_cannot_read_as_no_refusals():
    rep = report_of()
    del rep[ "refused" ]
    out = sc.score( rep, 50 )
    assert out[ "valid_run" ][ "valid" ] is False and any( "no refused list" in r for r in out[ "valid_run" ][ "reasons" ] ) and out[ "headline" ][ "threshold_free" ] == sc.NO_LEVEL
    assert sc.score( report_of(), 50 )[ "valid_run" ][ "valid" ] is True
