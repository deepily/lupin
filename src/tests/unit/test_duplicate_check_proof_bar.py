"""Unit tests for semdup.proof.proof_bar: bar thresholds, agreement and strata."""
import pytest

from cosa.repo.doc_lint import harness_report
from cosa.repo.semdup import errors as err
from cosa.repo.semdup.proof import proof_bar as pb


def counts( true_pairs=100, found=80, flags=100, correct=80, both=100, agree=90 ):
    """Build the counts evaluate_bar reads, defaulting to the three thresholds."""
    return { "true_pairs": true_pairs, "found": found, "flags": flags, "correct": correct, "both": both, "agree": agree }


# ---- evaluate_bar ------------------------------------------------------------------------------------------------

def test_exactly_at_each_threshold_passes_and_one_unit_below_fails_that_figure_alone():
    assert pb.evaluate_bar( counts() )[ "passed" ] is True
    for key, low, figure in ( ( "found", 79, "found" ), ( "correct", 79, "correct" ), ( "agree", 89, "agreement" ) ):
        out = pb.evaluate_bar( counts( **{ key: low } ) )
        assert out[ "passed" ] is False and out[ figure ][ "passes" ] is False
        assert [ f for f in ( "found", "correct", "agreement" ) if not out[ f ][ "passes" ] ] == [ figure ]


def test_one_unit_above_each_threshold_passes():
    out = pb.evaluate_bar( counts( found=81, correct=81, agree=91 ) )
    assert out[ "passed" ] is True and out[ "found" ][ "fraction" ] == "81/100"


def test_each_figure_prints_its_counts_exact_fraction_value_and_interval():
    out = pb.evaluate_bar( counts( true_pairs=60, found=48, flags=75, correct=60, both=40, agree=36 ) )
    assert out[ "found" ] == { "successes": 48, "trials": 60, "fraction": "4/5", "value": 0.8, "interval": harness_report.interval( 48, 60 ), "passes": True }
    assert out[ "correct" ][ "fraction" ] == "4/5" and out[ "agreement" ][ "fraction" ] == "9/10" and out[ "agreement" ][ "interval" ] == harness_report.interval( 36, 40 )


def test_an_interval_that_reaches_below_the_bar_does_not_change_the_verdict():
    out = pb.evaluate_bar( counts( true_pairs=10, found=8, flags=10, correct=8, both=10, agree=9 ) )
    assert out[ "found" ][ "interval" ][ 0 ] < 0.8 and out[ "passed" ] is True


def test_no_flags_is_refused_by_name():
    with pytest.raises( err.SemdupError ) as caught: pb.evaluate_bar( counts( flags=0, correct=0 ) )
    assert caught.value.code == err.NO_FLAGS


@pytest.mark.parametrize( "over, message", [
    ( { "true_pairs": 0, "found": 0 }, "true_pairs must be 1 or more" ),
    ( { "both": 0, "agree": 0 }, "both must be 1 or more" ),
    ( { "found": 101 }, "found must be between 0 and true_pairs" ),
    ( { "correct": -1 }, "correct must be between 0 and flags" ),
    ( { "agree": 101 }, "agree must be between 0 and both" ),
] )
def test_counts_that_cannot_be_a_proof_are_refused(over, message):
    with pytest.raises( ValueError, match=message ): pb.evaluate_bar( counts( **over ) )


# ---- agreement ---------------------------------------------------------------------------------------------------

def row( n, verdict ):
    """Build a verdict row for the pair P<n>."""
    return { "id": "def", "candidate": f"P{n}", "verdict": verdict }


def test_the_worked_case_pass_zero_judges_p1_to_p6_and_pass_one_p2_to_p7():
    pass0 = [ row( 1, "duplicate" ), row( 2, "duplicate" ), row( 3, "duplicate" ), row( 4, "related" ), row( 5, "duplicate" ), row( 6, "distinct" ) ]
    pass1 = [ row( 2, "duplicate" ), row( 3, "near_duplicate" ), row( 4, "distinct" ), row( 5, "distinct" ), row( 6, "distinct" ), row( 7, "duplicate" ) ]
    out   = pb.agreement( pass0, pass1 )
    assert out == { "flag_agree": 4, "four_way_agree": 2, "pairs_in_both": 5, "pairs_one_pass": 2 }
    assert out[ "flag_agree" ] / out[ "pairs_in_both" ] == 0.8 and out[ "four_way_agree" ] / out[ "pairs_in_both" ] == 0.4


def test_the_pair_is_the_definition_and_candidate_together_so_the_same_candidate_for_another_definition_is_another_pair():
    a = [ { "id": "x", "candidate": "c", "verdict": "duplicate" }, { "id": "y", "candidate": "c", "verdict": "distinct" } ]
    b = [ { "id": "x", "candidate": "c", "verdict": "duplicate" }, { "id": "y", "candidate": "c", "verdict": "duplicate" } ]
    assert pb.agreement( a, b ) == { "flag_agree": 1, "four_way_agree": 1, "pairs_in_both": 2, "pairs_one_pass": 0 }


def test_no_overlap_gives_zero_in_both_and_everything_in_one_pass():
    assert pb.agreement( [ row( 1, "duplicate" ) ], [ row( 2, "duplicate" ) ] ) == { "flag_agree": 0, "four_way_agree": 0, "pairs_in_both": 0, "pairs_one_pass": 2 }
    assert pb.agreement( [], [] ) == { "flag_agree": 0, "four_way_agree": 0, "pairs_in_both": 0, "pairs_one_pass": 0 }


def test_a_pair_judged_twice_in_one_pass_is_refused():
    with pytest.raises( ValueError, match="judged twice" ): pb.agreement( [ row( 1, "duplicate" ), row( 1, "distinct" ) ], [] )


# ---- stratum_rates -----------------------------------------------------------------------------------------------

def test_each_stratum_gets_its_own_rate_and_interval_in_first_seen_order():
    outcomes = [ { "stratum": "opus", "found": True }, { "stratum": "fable", "found": True }, { "stratum": "opus", "found": False }, { "stratum": "opus", "found": True } ]
    out = pb.stratum_rates( outcomes )
    assert list( out ) == [ "opus", "fable" ]
    assert out[ "opus" ] == { "found": 2, "true": 3, "value": 2 / 3, "interval": harness_report.interval( 2, 3 ) }
    assert out[ "fable" ][ "found" ] == 1 and out[ "fable" ][ "true" ] == 1 and pb.stratum_rates( [] ) == {}
