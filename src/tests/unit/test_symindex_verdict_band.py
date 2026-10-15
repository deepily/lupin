"""
The uncertain band of the verdict layer.

A top score inside `band` of a cut-off reads UNCERTAIN_READ_SOURCE with the cause NEAR_CUTOFF. A policy with
no `band` decides as it does today, and so does a score outside the band.
"""
import importlib

import pytest

from cosa.repo.symindex import verdict as vd

BAND = 0.05


def _p( overlap ):
    """Return a valid answer whose p_overlap is overlap and whose confidence clears the bar."""
    return { "reuse": round( overlap, 6 ), "extend": 0.0, "unrelated": round( 1.0 - overlap, 6 ) }


def _decide( top, policy ):
    answers = [ { "id": "e0", "probabilities": _p( top ) }, { "id": "e1", "probabilities": _p( 0.0 ) } ]
    return vd.decide( answers, [ "e0", "e1" ], [], set(), policy )


# A confidence bar of 0 keeps LOW_CONFIDENCE out of these cases: near a cut-off of 0.5 no answer can be confident, so under the
# shipped bar of 0.9 that cause always holds first. The fitted policy moves the bar, so the band is tested on its own here.
BASE   = dict( vd.POLICY, confidence=0.0 )
BANDED = dict( BASE, band=BAND )


def test_the_cause_list_names_near_cutoff_after_the_existing_causes():
    assert vd.CAUSES[ -1 ] == "NEAR_CUTOFF" and vd.CAUSES[ :-1 ] == ( "NOT_LUPIN_TREE", "DEPENDENCY_MISSING", "INDEX_STALE", "KEY_UNREADABLE", "CALL_FAILED", "MALFORMED_ANSWER", "LOW_CONFIDENCE" )


CUTS = ( ( "threshold", 0.5 ), ( "strong", 0.9 ) )


@pytest.mark.parametrize( "name,cut", CUTS )
@pytest.mark.parametrize( "step", [ 0.0, 0.049, -0.049 ] )
def test_a_top_score_inside_the_band_is_uncertain_near_cutoff_on_both_sides_of_each_cut_off( name, cut, step ):
    got = _decide( round( cut + step, 6 ), BANDED )
    assert ( got[ "verdict" ], got[ "cause" ], got[ "causes" ] ) == ( "UNCERTAIN_READ_SOURCE", "NEAR_CUTOFF", [ "NEAR_CUTOFF" ] ), name


@pytest.mark.parametrize( "name,cut", CUTS )
@pytest.mark.parametrize( "step", [ 0.05, -0.05, 0.051, -0.051 ] )
def test_a_top_score_exactly_at_or_just_outside_the_band_edge_is_decided_as_today( name, cut, step ):
    top = round( cut + step, 6 )
    assert _decide( top, BANDED ) == _decide( top, BASE ), ( name, top )


def test_the_band_edge_is_exclusive_even_where_float_subtraction_lands_below_it():
    assert abs( 0.45 - 0.5 ) < BAND                                       # the arithmetic trap: 0.04999999999999999
    assert _decide( 0.45, BANDED ) == _decide( 0.45, BASE )


def test_the_strong_cut_off_has_its_own_band_in_both_directions():
    assert _decide( 0.86, BANDED )[ "causes" ] == [ "NEAR_CUTOFF" ]
    assert _decide( 0.94, BANDED )[ "causes" ] == [ "NEAR_CUTOFF" ]
    assert _decide( 0.96, BANDED ) == _decide( 0.96, BASE )


def test_a_policy_without_a_band_decides_exactly_as_before():
    for top in ( 0.0, 0.46, 0.5, 0.54, 0.9, 1.0 ): assert "NEAR_CUTOFF" not in _decide( top, BASE )[ "causes" ]


def test_the_band_adds_to_the_causes_that_already_hold_and_does_not_replace_them():
    answers = [ { "id": "e0", "probabilities": _p( 0.52 ) } ]
    got = vd.decide( answers, [ "e0" ], [], { "INDEX_STALE" }, BANDED )
    assert got[ "causes" ] == [ "INDEX_STALE", "NEAR_CUTOFF" ] and got[ "cause" ] == "INDEX_STALE"


def test_no_answered_entry_means_no_band_to_test():
    got = vd.decide( [], [ "e0" ], [ "e0" ], set(), BANDED )
    assert "NEAR_CUTOFF" not in got[ "causes" ]


@pytest.mark.parametrize( "band", [ 0.0, 0.01, 0.0499 ] )
def test_the_record_step_refuses_a_band_under_the_floor_while_decide_stays_a_pure_function_of_its_policy( band ):
    ls = importlib.import_module( "cosa.repo.symindex.labelled_set" )
    with pytest.raises( ValueError, match="0.05" ): ls.check_band( band )
    assert _decide( 0.5, dict( BASE, band=band ) )[ "verdict" ] in ( "UNCERTAIN_READ_SOURCE", "REUSE", "EXTEND", "NEW" )


@pytest.mark.parametrize( "band", [ 0.05, 0.08, 0.2 ] )
def test_the_record_step_accepts_a_band_at_or_above_the_floor( band ):
    ls = importlib.import_module( "cosa.repo.symindex.labelled_set" )
    assert ls.check_band( band ) == band


def test_the_distance_to_a_cut_off_is_rounded_to_the_named_number_of_places_before_it_meets_the_band():
    assert vd.BAND_DECIMALS == 6
    assert _decide( 0.45, BANDED ) == _decide( 0.45, BASE )          # 0.5 - 0.45 is 0.04999999999999999 unrounded
    assert _decide( 0.450001, BANDED )[ "causes" ] == [ "NEAR_CUTOFF" ]   # one unit of the sixth place inside is inside
    assert _decide( 0.549999, BANDED )[ "causes" ] == [ "NEAR_CUTOFF" ]


def test_under_the_shipped_confidence_bar_a_score_near_the_threshold_holds_both_causes_in_table_order():
    got = _decide( 0.52, dict( vd.POLICY, band=BAND ) )
    assert got[ "causes" ] == [ "LOW_CONFIDENCE", "NEAR_CUTOFF" ] and got[ "cause" ] == "LOW_CONFIDENCE"


def _two_rows( second ):
    return vd.decide( [ { "id": "e0", "probabilities": { "reuse": 0.0, "extend": 0.8, "unrelated": 0.2 } },
                        { "id": "e1", "probabilities": { "reuse": second, "extend": 0.0, "unrelated": round( 1.0 - second, 6 ) } } ], [ "e0", "e1" ], [], set(), BANDED )


@pytest.mark.parametrize( "second", [ 0.5001, 0.4999, 0.5 ] )
def test_a_second_entry_inside_the_band_of_the_threshold_makes_the_verdict_uncertain_near_cutoff( second ):
    got = _two_rows( second )
    assert ( got[ "verdict" ], got[ "causes" ] ) == ( "UNCERTAIN_READ_SOURCE", [ "NEAR_CUTOFF" ] )


def test_a_second_entry_outside_the_band_leaves_the_verdict_as_it_was():
    assert _two_rows( 0.6 )[ "verdict" ] == "REUSE" and _two_rows( 0.4 )[ "verdict" ] == "EXTEND"


def test_a_second_entry_inside_the_band_of_the_strong_cut_off_is_near_cutoff_too():
    answers = [ { "id": "e0", "probabilities": { "reuse": 0.0, "extend": 0.7, "unrelated": 0.3 } }, { "id": "e1", "probabilities": _p( 0.91 ) } ]
    assert vd.decide( answers, [ "e0", "e1" ], [], set(), BANDED )[ "causes" ] == [ "NEAR_CUTOFF" ]


@pytest.mark.parametrize( "band", [ float( "nan" ), float( "inf" ), 0.5, 1, True, 0.6 ] )
def test_the_record_step_refuses_a_band_that_is_not_a_number_below_one_half_and_at_least_the_floor( band ):
    ls = importlib.import_module( "cosa.repo.symindex.labelled_set" )
    with pytest.raises( ValueError, match="band" ): ls.check_band( band )


def _strong_answer( top_probability ):
    """Return a strong answer: overlap 0.96, the largest single probability top_probability."""
    return { "reuse": top_probability, "extend": round( 0.96 - top_probability, 6 ), "unrelated": 0.04 }


@pytest.mark.parametrize( "confidence", [ 0.9001, 0.8999, 0.9, 0.9499, 0.8501 ] )
def test_a_confidence_inside_the_band_of_the_bar_is_near_cutoff_on_both_sides( confidence ):
    got = vd.decide( [ { "id": "e0", "probabilities": _strong_answer( confidence ) } ], [ "e0" ], [], set(), dict( vd.POLICY, band=BAND ) )
    assert "NEAR_CUTOFF" in got[ "causes" ]


@pytest.mark.parametrize( "confidence", [ 0.95, 0.85, 0.99 ] )
def test_a_confidence_outside_the_band_of_the_bar_is_decided_as_today( confidence ):
    policy = dict( vd.POLICY, band=BAND )
    answers = [ { "id": "e0", "probabilities": _strong_answer( confidence ) } ]
    assert vd.decide( answers, [ "e0" ], [], set(), policy )[ "causes" ] == vd.decide( answers, [ "e0" ], [], set(), vd.POLICY )[ "causes" ]


def test_a_confident_unrelated_entry_is_not_near_the_confidence_bar_whatever_its_confidence():
    answers = [ { "id": "e0", "probabilities": { "reuse": 0.0, "extend": 0.0, "unrelated": 1.0 } }, { "id": "e1", "probabilities": { "reuse": 0.02, "extend": 0.02, "unrelated": 0.96 } } ]
    assert vd.decide( answers, [ "e0", "e1" ], [], set(), dict( vd.POLICY, band=BAND ) )[ "causes" ] == []


def test_the_confidence_of_a_strong_candidate_is_banded_against_the_strong_cut_off_when_the_bar_differs():
    policy = dict( vd.POLICY, confidence=0.5, strong=0.8, band=BAND )
    answers = [ { "id": "e0", "probabilities": { "reuse": 0.81, "extend": 0.1, "unrelated": 0.09 } } ]
    assert "NEAR_CUTOFF" in vd.decide( answers, [ "e0" ], [], set(), policy )[ "causes" ]
