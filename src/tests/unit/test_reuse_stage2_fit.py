"""
Tests of the threshold-fitting script for the labelled-pair run.

It reads the rows of the labelled run, fits four cut-offs on the fit half only, and shows the same
numbers on the check half. The rate of false reuse it may tolerate is a required argument with no default.
No model is called. The last tests run it on a slice of the old run's real rows.
"""
import hashlib
import inspect
import json
import pathlib

import pytest

from cosa.repo.symindex import stage2_split as ss
from lupin_mcp import reuse_stage2_fit as ft

FIX = pathlib.Path( __file__ ).parent / "fixtures"


def _row( member, cand, label, provides, coverage=0.9, malformed=None, unasked=False, p_overlap=None ):
    """Ensures: returns one row in the labelled-run format."""
    return { "member": member, "candidate": cand, "label": label, "provides": provides, "coverage": coverage,
             "score": None if provides is None else round( provides * 2, 6 ), "p_overlap": p_overlap, "malformed": malformed, "unasked": unasked }


POLICY = { "reuse": 0.7, "threshold": 0.5, "floor": 0.3, "coverage": 0.5 }


def _two_members():
    """Ensures: returns the rows of two members worked out by hand in the tests below."""
    return [ _row( "m1", "t1", True, 0.8, 0.9 ), _row( "m1", "n1", False, 0.75 ), _row( "m1", "n2", False, 0.4 ), _row( "m1", "n3", False, 0.1 ),
             _row( "m2", "t2", True, 0.45, 0.6 ), _row( "m2", "n4", False, 0.2, 0.9 ), _row( "m2", "n5", False, 0.6, 0.2 ) ]


# --- the numbers the rulings fix -----------------------------------------------------------------------------------------

def test_the_constants_and_the_default_grid_are_the_rulings():
    assert ft.FORMAT == "stage2-fit-1"
    assert ft.SHORTLIST == 10                                  # the shortlist size is not fitted
    assert ft.GRID == { "reuse": ( 0.5, 0.6, 0.7, 0.8, 0.9 ), "threshold": ( 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7 ),
                        "floor": ( 0.1, 0.2, 0.3, 0.4 ), "coverage": ( 0.3, 0.5, 0.7 ) }
    assert ft.OLD_CUTS == ( 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.7 )
    assert "widened" in ft.GRID_NOTE and "0.05" in ft.GRID_NOTE and "0.1" in ft.GRID_NOTE
    assert ft.BINS == 10


def test_the_false_reuse_rate_is_required_and_has_no_default_anywhere():
    for fn in ( ft.fit_policy, ft.fit_old, ft.report, ft.old_report ):
        p = inspect.signature( fn ).parameters[ "rate" ]
        assert p.default is inspect.Parameter.empty, fn.__name__


def test_the_command_refuses_to_run_without_a_rate(tmp_path, capsys):
    with pytest.raises( SystemExit ) as caught: ft.main( [ "--rows", str( tmp_path / "r.json" ), "--split", str( tmp_path / "s.json" ) ] )
    assert caught.value.code == 2 and "--rate" in capsys.readouterr().err


# --- labels and rows -----------------------------------------------------------------------------------------------------

def _manifest():
    return json.loads( ( FIX / "stage2-manifest-slice.json" ).read_text() )


def test_the_twin_map_is_the_union_of_a_members_clusters_and_pairs_and_never_holds_the_member_itself():
    man = { "exact": [ { "members": [ { "id": "a" }, { "id": "b" }, { "id": "c" } ] } ], "near": [ { "members": [ { "id": "c" }, { "id": "d" } ] } ] }
    tm  = ft.twin_map_from_manifest( man )
    assert tm == { "a": { "b", "c" }, "b": { "a", "c" }, "c": { "a", "b", "d" }, "d": { "c" } }
    real = ft.twin_map_from_manifest( _manifest() )
    assert real and all( m not in t and m in real[ x ] for m, ts in real.items() for t in [ ts ] for x in ts )


def test_old_rows_become_rows_with_a_label_no_provides_and_the_old_overlap():
    old = [ { "member": "a", "candidate": "b", "probabilities": { "reuse": 0.5 }, "malformed": None, "p_overlap": 0.75 },
            { "member": "a", "candidate": "z", "probabilities": None, "malformed": "not a mapping", "p_overlap": None } ]
    rows = ft.rows_from_old( old, { "a": { "b" }, "b": { "a" } } )
    assert rows[ 0 ] == { "member": "a", "candidate": "b", "label": True, "provides": None, "coverage": None, "score": None, "p_overlap": 0.75, "malformed": None, "unasked": False }
    assert ( rows[ 1 ][ "label" ], rows[ 1 ][ "malformed" ], rows[ 1 ][ "p_overlap" ] ) == ( False, "not a mapping", None )


def test_a_row_with_a_missing_key_or_a_number_out_of_range_is_refused_and_named_by_position():
    good = _two_members()
    bad  = dict( good[ 1 ] ); del bad[ "label" ]
    with pytest.raises( ValueError, match = r"row 1.*label" ): ft.check_rows( [ good[ 0 ], bad ] )
    with pytest.raises( ValueError, match = r"row 0.*provides" ): ft.check_rows( [ _row( "m", "c", True, 1.5 ) ] )
    with pytest.raises( ValueError, match = r"row 0.*provides" ): ft.check_rows( [ _row( "m", "c", True, True ) ] )
    with pytest.raises( ValueError, match = r"row 0.*coverage" ): ft.check_rows( [ _row( "m", "c", True, 0.5, coverage = -0.1 ) ] )
    with pytest.raises( ValueError, match = r"row 0.*p_overlap" ): ft.check_rows( [ _row( "m", "c", True, None, p_overlap = 2 ) ] )
    assert ft.check_rows( good ) is None
    assert ft.check_rows( [ _row( "m", "c", True, None, coverage = None, p_overlap = 0.5 ), _row( "m", "d", False, None, coverage = None, malformed = "x" ) ] ) is None


def test_split_rows_cuts_by_the_members_half_and_refuses_a_member_the_split_does_not_know():
    halves = { "m1": "fit", "m2": "check" }
    fit, check = ft.split_rows( _two_members(), halves )
    assert { r[ "member" ] for r in fit } == { "m1" } and { r[ "member" ] for r in check } == { "m2" } and len( fit ) + len( check ) == 7
    with pytest.raises( ValueError, match = "m3" ): ft.split_rows( [ _row( "m3", "c", True, 0.5 ) ], halves )


# --- the shortlist and the figures, worked by hand -----------------------------------------------------------------------

def test_a_reuse_row_is_causal_and_the_shortlist_is_the_causal_rows_plus_everything_at_the_threshold():
    rows = [ r for r in _two_members() if r[ "member" ] == "m1" ]
    assert [ r[ "candidate" ] for r in ft.shortlist( rows, POLICY ) ] == [ "t1", "n1" ]


def test_an_extend_row_below_the_threshold_still_makes_the_shortlist_when_there_is_no_reuse():
    rows = [ r for r in _two_members() if r[ "member" ] == "m2" ]
    assert [ r[ "candidate" ] for r in ft.shortlist( rows, POLICY ) ] == [ "n5", "t2" ]
    assert [ r[ "candidate" ] for r in ft.shortlist( rows, { **POLICY, "coverage": 0.99 } ) ] == [ "n5" ]
    assert [ r[ "candidate" ] for r in ft.shortlist( rows, { **POLICY, "floor": 0.5 } ) ] == [ "n5" ]


def test_the_extend_band_is_closed_below_and_open_above():
    one = [ _row( "m", "e", False, 0.3, 0.5 ), _row( "m", "u", False, 0.7, 0.9 ) ]
    pol = { "reuse": 0.7, "threshold": 0.9, "floor": 0.3, "coverage": 0.5 }
    assert [ r[ "candidate" ] for r in ft.shortlist( one, pol ) ] == [ "u" ]            # reuse at 0.7 wins; 0.3 would be extend only without it
    assert [ r[ "candidate" ] for r in ft.shortlist( one[ :1 ], pol ) ] == [ "e" ]


def test_a_row_the_run_could_not_use_takes_the_causal_rows_away_and_counts_as_a_miss():
    rows = [ r for r in _two_members() if r[ "member" ] == "m2" ] + [ _row( "m2", "bad", True, None, None, malformed = "not a mapping" ) ]
    assert ft.shortlist( rows, POLICY ) == [ r for r in rows if r[ "candidate" ] == "n5" ]
    unasked = [ r for r in _two_members() if r[ "member" ] == "m2" ] + [ _row( "m2", "gone", False, None, None, unasked = True ) ]
    assert [ r[ "candidate" ] for r in ft.shortlist( unasked, POLICY ) ] == [ "n5" ]


def test_the_shortlist_is_cut_to_ten_keeping_every_causal_row_it_can():
    many = [ _row( "m", f"t{k:02d}", True, 0.9 ) for k in range( 12 ) ]
    assert [ r[ "candidate" ] for r in ft.shortlist( many, POLICY ) ] == [ f"t{k:02d}" for k in range( 10 ) ]
    mixed = [ _row( "m", "a1", True, 0.9 ), _row( "m", "a2", True, 0.9 ) ] + [ _row( "m", f"n{k:02d}", False, 0.6 ) for k in range( 15 ) ]
    got   = [ r[ "candidate" ] for r in ft.shortlist( mixed, POLICY ) ]
    assert got == [ "a1", "a2" ] + [ f"n{k:02d}" for k in range( 8 ) ]
    assert len( ft.shortlist( mixed, POLICY, cap = 3 ) ) == 3


def test_a_row_exactly_at_the_threshold_is_in_the_pool_and_one_just_under_it_is_not():
    rows = [ _row( "m", "at", False, 0.5, 0.1 ), _row( "m", "under", False, 0.4999, 0.1 ) ]
    assert [ r[ "candidate" ] for r in ft.shortlist( rows, POLICY ) ] == [ "at" ]


def test_when_more_than_ten_rows_are_causal_the_best_ten_by_provides_stay_not_the_first_ten_by_id():
    many = [ _row( "m", f"t{k:02d}", True, round( 0.8 + k / 100, 2 ) ) for k in range( 12 ) ] + [ _row( "m", f"x{k}", False, 0.6 ) for k in range( 3 ) ]
    got  = [ r[ "candidate" ] for r in ft.shortlist( many, POLICY ) ]
    assert got == [ f"t{k:02d}" for k in range( 11, 1, -1 ) ]


def test_exactly_ten_causal_rows_leave_no_room_for_a_row_that_is_not_causal():
    rows = [ _row( "m", f"c{k}", True, 0.9 ) for k in range( 10 ) ] + [ _row( "m", "x", False, 0.6 ) ]
    assert len( ft.shortlist( rows, POLICY ) ) == 10 and "x" not in [ r[ "candidate" ] for r in ft.shortlist( rows, POLICY ) ]


def test_ranking_is_by_provides_high_to_low_then_candidate_id():
    rows = [ _row( "m", "b", False, 0.6 ), _row( "m", "a", False, 0.6 ), _row( "m", "c", False, 0.9 ) ]
    assert [ r[ "candidate" ] for r in ft.shortlist( rows, { **POLICY, "reuse": 0.95 } ) ] == [ "c", "a", "b" ]


def test_the_figures_of_two_members_worked_by_hand():
    r = ft.evaluate( _two_members(), POLICY )
    assert ( r[ "members" ], r[ "twins" ], r[ "twins_on_shortlist" ], r[ "hit_at_10" ], r[ "twin_recall" ] ) == ( 2, 2, 2, 1.0, 1.0 )
    assert ( r[ "non_twin_rows" ], r[ "false_reuse" ], r[ "false_reuse_rate" ], r[ "unusable" ] ) == ( 5, 1, 0.2, 0 )
    lost = ft.evaluate( _two_members(), { **POLICY, "floor": 0.5 } )
    assert ( lost[ "twins_on_shortlist" ], lost[ "hit_at_10" ], lost[ "twin_recall" ] ) == ( 1, 0.5, 0.5 )


def test_a_twin_the_run_could_not_use_stays_in_the_count_and_a_malformed_non_twin_stays_in_the_rate():
    rows = _two_members() + [ _row( "m1", "tb", True, None, None, malformed = "x" ), _row( "m1", "nb", False, None, None, unasked = True ) ]
    r = ft.evaluate( rows, POLICY )
    assert ( r[ "twins" ], r[ "non_twin_rows" ], r[ "unusable" ], r[ "false_reuse" ] ) == ( 3, 6, 2, 1 )
    assert r[ "false_reuse_rate" ] == round( 1 / 6, 6 )


def test_a_non_twin_exactly_at_the_reuse_cut_counts_as_false_reuse_and_one_just_under_does_not():
    rows = [ _row( "m", "t", True, 0.9 ), _row( "m", "at", False, 0.7 ), _row( "m", "under", False, 0.6999 ) ]
    assert ft.evaluate( rows, POLICY )[ "false_reuse" ] == 1


def test_with_no_twin_rows_or_no_non_twin_rows_the_ratios_are_none_not_zero():
    r = ft.evaluate( [ _row( "m", "n", False, 0.6 ) ], POLICY )
    assert ( r[ "members" ], r[ "hit_at_10" ], r[ "twin_recall" ], r[ "false_reuse_rate" ] ) == ( 0, None, None, 0.0 )
    r = ft.evaluate( [ _row( "m", "t", True, 0.6 ) ], POLICY )
    assert ( r[ "non_twin_rows" ], r[ "false_reuse_rate" ] ) == ( 0, None )


def test_evaluate_does_not_depend_on_the_order_of_the_rows():
    rows = _two_members()
    assert ft.evaluate( list( reversed( rows ) ), POLICY ) == ft.evaluate( rows, POLICY )


# --- the fit -------------------------------------------------------------------------------------------------------------

GRID = { "reuse": ( 0.7, 0.9 ), "threshold": ( 0.4, 0.6 ), "floor": ( 0.3, ), "coverage": ( 0.5, ) }
HALVES = { "m": "fit", "k": "check" }


def _opt_rows( twin_provides=0.55 ):
    return [ _row( "m", "t", True, twin_provides, 0.1 ), _row( "m", "a", False, 0.5, 0.1 ), _row( "m", "b", False, 0.8, 0.1 ) ]


def test_a_known_optimum_is_found_and_the_rate_rules_out_the_values_that_break_it():
    r = ft.fit_policy( _opt_rows(), HALVES, 0.0, GRID )
    assert r[ "chosen" ] == { "reuse": 0.9, "threshold": 0.4, "floor": 0.3, "coverage": 0.5 }
    assert r[ "feasible" ] == 2 and len( r[ "table" ] ) == 4


def test_ties_go_to_the_lowest_threshold_then_the_lowest_reuse():
    assert ft.fit_policy( _opt_rows(), HALVES, 0.5, GRID )[ "chosen" ] == { "reuse": 0.7, "threshold": 0.4, "floor": 0.3, "coverage": 0.5 }
    both = ft.fit_policy( _opt_rows( 0.7 ), HALVES, 0.0, GRID )
    assert both[ "chosen" ][ "threshold" ] == 0.4 and both[ "chosen" ][ "reuse" ] == 0.9


def test_a_grid_point_with_the_floor_above_the_reuse_cut_is_never_tried():
    grid = { "reuse": ( 0.3, 0.9 ), "threshold": ( 0.4, ), "floor": ( 0.5, ), "coverage": ( 0.5, ) }
    r = ft.fit_policy( _opt_rows(), HALVES, 1.0, grid )
    assert [ t[ "policy" ][ "reuse" ] for t in r[ "table" ] ] == [ 0.9 ]


def test_a_point_with_the_floor_equal_to_the_reuse_cut_is_tried():
    r = ft.fit_policy( _opt_rows(), HALVES, 1.0, { "reuse": ( 0.3, ), "threshold": ( 0.4, ), "floor": ( 0.3, ), "coverage": ( 0.5, ) } )
    assert [ t[ "policy" ][ "reuse" ] for t in r[ "table" ] ] == [ 0.3 ]


def test_the_table_lists_every_point_in_a_fixed_order_with_its_figures():
    r = ft.fit_policy( _opt_rows(), HALVES, 0.5, GRID )
    assert [ ( t[ "policy" ][ "threshold" ], t[ "policy" ][ "reuse" ] ) for t in r[ "table" ] ] == [ ( 0.4, 0.7 ), ( 0.4, 0.9 ), ( 0.6, 0.7 ), ( 0.6, 0.9 ) ]
    assert all( set( t ) == { "policy", "figures", "feasible" } for t in r[ "table" ] ) and r[ "table" ][ 0 ][ "figures" ][ "twins_on_shortlist" ] == 1


def test_the_fit_refuses_any_row_of_the_check_half():
    with pytest.raises( ValueError, match = "check half" ): ft.fit_policy( _opt_rows() + [ _row( "k", "t", True, 0.9 ) ], HALVES, 0.1, GRID )
    with pytest.raises( ValueError, match = "check half" ): ft.fit_old( [ _row( "k", "t", True, None, None, p_overlap = 0.9 ) ], HALVES, 0.1 )


def test_the_fit_refuses_a_member_the_split_does_not_know_and_a_rate_outside_zero_to_one():
    with pytest.raises( ValueError, match = "zz" ): ft.fit_policy( [ _row( "zz", "t", True, 0.9 ) ], HALVES, 0.1, GRID )
    for bad in ( -0.01, 1.01, True, "0.05", None ):
        with pytest.raises( ValueError, match = "rate" ): ft.fit_policy( _opt_rows(), HALVES, bad, GRID )


def test_the_fit_refuses_an_empty_input_and_an_empty_or_out_of_range_grid():
    with pytest.raises( ValueError, match = "no rows" ): ft.fit_policy( [], HALVES, 0.1, GRID )
    with pytest.raises( ValueError, match = "grid" ): ft.fit_policy( _opt_rows(), HALVES, 0.1, { **GRID, "reuse": () } )
    with pytest.raises( ValueError, match = "grid" ): ft.fit_policy( _opt_rows(), HALVES, 0.1, { **GRID, "reuse": ( 1.2, ) } )
    with pytest.raises( ValueError, match = "grid" ): ft.fit_policy( _opt_rows(), HALVES, 0.1, { "reuse": ( 0.7, ) } )


def test_when_no_grid_point_keeps_false_reuse_within_the_rate_it_says_what_was_reachable():
    rows = [ _row( "m", "t", True, 0.9 ), _row( "m", "n", False, 0.95 ) ]
    with pytest.raises( ft.NoFeasiblePolicy, match = "lowest reachable rate is 1.0" ) as caught: ft.fit_policy( rows, HALVES, 0.1, { "reuse": ( 0.7, 0.9 ), "threshold": ( 0.5, ), "floor": ( 0.3, ), "coverage": ( 0.5, ) } )
    assert isinstance( caught.value, ValueError )


def test_the_fit_is_the_same_on_the_same_rows_whatever_their_order():
    rows = _opt_rows()
    assert ft.fit_policy( list( reversed( rows ) ), HALVES, 0.5, GRID ) == ft.fit_policy( rows, HALVES, 0.5, GRID )


def test_a_policy_fitted_on_the_fit_half_is_not_changed_by_what_the_check_half_holds():
    fit_rows = _opt_rows()
    a = ft.fit_policy( fit_rows, HALVES, 0.5, GRID )
    b = ft.fit_policy( [ r for r in fit_rows + [ _row( "k", "t", True, 0.99 ) ] if HALVES[ r[ "member" ] ] == "fit" ], HALVES, 0.5, GRID )
    assert a == b


def test_the_old_question_is_fitted_on_its_own_overlap_with_one_cut():
    rows = [ _row( "m", "t", True, None, None, p_overlap = 0.55 ), _row( "m", "a", False, None, None, p_overlap = 0.5 ), _row( "m", "b", False, None, None, p_overlap = 0.8 ),
             _row( "m", "bad", False, None, None, p_overlap = None, malformed = "x" ) ]
    r = ft.fit_old( rows, HALVES, 0.7, cuts = ( 0.4, 0.6, 0.85 ) )
    assert r[ "chosen" ] == { "cut": 0.4 } and r[ "feasible" ] == 3 and [ t[ "policy" ][ "cut" ] for t in r[ "table" ] ] == [ 0.4, 0.6, 0.85 ]
    assert r[ "table" ][ 1 ][ "figures" ][ "twins_on_shortlist" ] == 0 and r[ "table" ][ 0 ][ "figures" ][ "false_reuse" ] == 2
    assert ft.fit_old( rows, HALVES, 0.34, cuts = ( 0.4, 0.6, 0.85 ) )[ "chosen" ] == { "cut": 0.6 }                # 0.4 breaks the rate, 0.6 and 0.85 find no twin
    with pytest.raises( ft.NoFeasiblePolicy ): ft.fit_old( rows, HALVES, 0.0, cuts = ( 0.4, 0.6 ) )


# --- the reliability table, the groups and the report --------------------------------------------------------------------

def test_the_reliability_table_bins_provides_and_reports_an_empty_bin_instead_of_skipping_it():
    rows = [ _row( "m", "a", True, 0.0 ), _row( "m", "b", False, 0.1 ), _row( "m", "c", True, 0.15 ), _row( "m", "d", True, 1.0 ), _row( "m", "e", False, None, None, malformed = "x" ) ]
    t = ft.reliability( rows )
    assert len( t[ "bins" ] ) == 10 and t[ "unusable" ] == 1
    assert [ ( b[ "n" ], b[ "twins" ] ) for b in t[ "bins" ] ][ :3 ] == [ ( 1, 1 ), ( 2, 1 ), ( 0, 0 ) ] and t[ "bins" ][ 2 ][ "share" ] is None
    assert t[ "bins" ][ 1 ][ "share" ] == 0.5 and ( t[ "bins" ][ 9 ][ "n" ], t[ "bins" ][ 9 ][ "twins" ], t[ "bins" ][ 9 ][ "high" ] ) == ( 1, 1, 1.0 )
    assert ft.reliability( [ _row( "m", "a", True, None, None, p_overlap = 0.95 ) ], key = "p_overlap" )[ "bins" ][ 9 ][ "n" ] == 1


def test_a_value_just_under_a_bin_edge_in_floating_point_still_lands_in_the_bin_it_names():
    assert 0.29 * 100 < 29                                                                    # the float product falls short of 29
    t = ft.reliability( [ _row( "m", "a", True, 0.29 ) ], bins = 100 )
    assert t[ "bins" ][ 29 ][ "n" ] == 1 and t[ "bins" ][ 28 ][ "n" ] == 0


def test_the_report_carries_the_choice_the_check_half_the_reliability_and_the_counts():
    halves = { "m1": "fit", "m2": "fit", "c1": "check" }
    split  = { "fit": [ { "members": [ "m1", "m2" ] } ], "check": [ { "members": [ "c1" ] } ], "seed": 5, "groups": 2, "members": 3 }
    rows   = _two_members() + [ _row( "c1", "t3", True, 0.9 ), _row( "c1", "n6", False, 0.2 ) ]
    rep    = ft.report( rows, split, 0.5, GRID )
    assert rep[ "format" ] == ft.FORMAT and rep[ "rate" ] == 0.5
    assert rep[ "counts" ] == { "fit": { "groups": 1, "members": 2, "rows": 7, "twin_rows": 2 }, "check": { "groups": 1, "members": 1, "rows": 2, "twin_rows": 1 } }
    assert rep[ "fit" ][ "chosen" ] == rep[ "chosen" ] and rep[ "on_fit" ][ "members" ] == 2 and rep[ "on_check" ][ "members" ] == 1
    assert set( rep[ "reliability" ] ) == { "fit", "check" } and rep[ "reliability" ][ "check" ][ "bins" ][ 9 ][ "twins" ] == 1


def test_the_text_report_shows_the_rate_the_choice_both_halves_and_the_placeholder_note():
    split = { "fit": [ { "members": [ "m" ] } ], "check": [ { "members": [ "k" ] } ], "seed": 5, "groups": 2, "members": 2 }
    text  = ft.render( ft.report( _opt_rows() + [ _row( "k", "t", True, 0.9 ) ], split, 0.5, GRID ) )
    assert "false-reuse rate allowed: 0.5" in text and "chosen on the fit half" in text and "same policy on the check half" in text
    assert "reliability, fit half" in text and "bin 0.9 to 1.0" in text and "groups: fit 1, check 1" in text
    assert "fitted on overlapping data" not in text


# --- the grid edge ---------------------------------------------------------------------------------------------------------

def test_a_chosen_value_on_the_edge_of_its_grid_is_flagged_and_a_single_value_axis_never_is():
    chosen = { "reuse": 0.9, "threshold": 0.4, "floor": 0.3, "coverage": 0.5 }
    assert ft.edges( chosen, GRID ) == [ { "key": "reuse", "value": 0.9, "edge": "highest" }, { "key": "threshold", "value": 0.4, "edge": "lowest" } ]
    inner = { "reuse": 0.7, "threshold": 0.6, "floor": 0.3, "coverage": 0.5 }
    assert ft.edges( inner, { **GRID, "reuse": ( 0.5, 0.7, 0.9 ), "threshold": ( 0.4, 0.6, 0.8 ) } ) == []
    assert ft.edges( { "cut": 0.05 }, { "cut": ( 0.05, 0.1, 0.2 ) } ) == [ { "key": "cut", "value": 0.05, "edge": "lowest" } ]


def test_the_report_carries_the_grid_and_the_edges_and_the_text_prints_both_with_the_grid_note():
    split = { "fit": [ { "members": [ "m" ] } ], "check": [ { "members": [ "k" ] } ], "seed": 5, "groups": 2, "members": 2 }
    rep   = ft.report( _opt_rows() + [ _row( "k", "t", True, 0.9 ) ], split, 0.0, GRID )
    assert rep[ "grid" ] == GRID and [ e[ "key" ] for e in rep[ "edges" ] ] == [ "reuse", "threshold" ]
    text = ft.render( rep )
    assert "grid: reuse 0.7 to 0.9 (2 values); threshold 0.4 to 0.6 (2 values)" in text and ft.GRID_NOTE in text
    assert "warning: the chosen reuse 0.9 is the highest value of its grid" in text and "warning: the chosen threshold 0.4 is the lowest value of its grid" in text


def test_the_text_has_no_edge_warning_when_the_choice_is_inside_its_grid():
    split = { "fit": [ { "members": [ "m" ] } ], "check": [ { "members": [ "k" ] } ], "seed": 5, "groups": 2, "members": 2 }
    rows  = [ _row( "m", "t", True, 0.55, 0.1 ), _row( "m", "a", False, 0.6, 0.1 ), _row( "k", "t", True, 0.9 ) ]
    rep   = ft.report( rows, split, 0.0, { "reuse": ( 0.5, 0.7, 0.9 ), "threshold": ( 0.4, ), "floor": ( 0.3, ), "coverage": ( 0.5, ) } )
    assert rep[ "chosen" ][ "reuse" ] == 0.7 and rep[ "edges" ] == [] and "warning" not in ft.render( rep ) and ft.GRID_NOTE in ft.render( rep )


def test_the_old_report_carries_its_cuts_as_the_grid_and_flags_a_choice_on_their_edge():
    rows = [ _row( "m", "t", True, None, None, p_overlap = 0.55 ), _row( "m", "a", False, None, None, p_overlap = 0.1 ), _row( "k", "t", True, None, None, p_overlap = 0.9 ) ]
    split = { "fit": [ { "members": [ "m" ] } ], "check": [ { "members": [ "k" ] } ], "seed": 5, "groups": 2, "members": 2 }
    rep  = ft.old_report( rows, split, 0.5, cuts = ( 0.2, 0.4, 0.6 ) )
    assert rep[ "grid" ] == { "cut": ( 0.2, 0.4, 0.6 ) } and rep[ "chosen" ] == { "cut": 0.2 } and rep[ "edges" ] == [ { "key": "cut", "value": 0.2, "edge": "lowest" } ]
    assert ft.old_report( rows, split, 0.5, cuts = ( 0.6, 0.2, 0.4 ) )[ "grid" ] == { "cut": ( 0.2, 0.4, 0.6 ) }
    assert "grid: cut 0.2 to 0.6 (3 values)" in ft.render( rep ) and "warning: the chosen cut 0.2 is the lowest value of its grid" in ft.render( rep )


# --- the second named condition: a rate that binds nowhere -----------------------------------------------------------------

def test_the_condition_text_is_the_one_cheech_named():
    assert ft.NOT_BINDING == "the false-reuse rate does not bind at any cut; the cut is not determined by it"


def test_a_rate_that_every_grid_point_keeps_is_named_in_the_report_and_the_text():
    split = { "fit": [ { "members": [ "m" ] } ], "check": [ { "members": [ "k" ] } ], "seed": 5, "groups": 2, "members": 2 }
    rows  = _opt_rows() + [ _row( "k", "t", True, 0.9 ) ]
    rep   = ft.report( rows, split, 0.5, GRID )
    assert rep[ "fit" ][ "feasible" ] == len( rep[ "fit" ][ "table" ] ) and rep[ "rate_binds" ] is False
    assert f"warning: {ft.NOT_BINDING}" in ft.render( rep )


def test_a_rate_that_rules_out_even_one_grid_point_binds_and_the_text_stays_silent_about_it():
    split = { "fit": [ { "members": [ "m" ] } ], "check": [ { "members": [ "k" ] } ], "seed": 5, "groups": 2, "members": 2 }
    rep   = ft.report( _opt_rows() + [ _row( "k", "t", True, 0.9 ) ], split, 0.0, GRID )
    assert rep[ "fit" ][ "feasible" ] < len( rep[ "fit" ][ "table" ] ) and rep[ "rate_binds" ] is True
    assert ft.NOT_BINDING not in ft.render( rep )


def test_the_old_question_gets_the_same_condition():
    rows  = [ _row( "m", "t", True, None, None, p_overlap = 0.55 ), _row( "m", "a", False, None, None, p_overlap = 0.1 ), _row( "k", "t", True, None, None, p_overlap = 0.9 ) ]
    split = { "fit": [ { "members": [ "m" ] } ], "check": [ { "members": [ "k" ] } ], "seed": 5, "groups": 2, "members": 2 }
    near  = [ rows[ 0 ], _row( "m", "a", False, None, None, p_overlap = 0.3 ), rows[ 2 ] ]                  # a non-twin that crosses the cut of 0.2 only
    free  = ft.old_report( rows, split, 0.5, cuts = ( 0.2, 0.4, 0.6 ) )
    tight = ft.old_report( near, split, 0.0, cuts = ( 0.2, 0.4, 0.6 ) )
    assert free[ "rate_binds" ] is False and ft.NOT_BINDING in ft.render( free )
    assert tight[ "rate_binds" ] is True and ft.NOT_BINDING not in ft.render( tight )


# --- the dry run on the old run's real rows ------------------------------------------------------------------------------

def _old_world():
    man   = _manifest()
    split = ss.split_record( man, hashlib.sha256( b"slice" ).hexdigest(), 20261008 )
    old   = json.loads( ( FIX / "stage2-old-results-slice.json" ).read_text() )[ "rows" ]
    return man, split, ft.rows_from_old( old, ft.twin_map_from_manifest( man ) )


def test_the_old_rows_slice_is_real_rows_labelled_from_the_manifest():
    man, split, rows = _old_world()
    assert len( rows ) == 1165 and sum( r[ "label" ] for r in rows ) > 0 and all( r[ "p_overlap" ] is not None for r in rows )
    ft.check_rows( rows )
    assert set( ss.half_by_member( split ) ) >= { r[ "member" ] for r in rows }


def test_the_old_report_on_real_rows_fits_on_the_fit_half_and_reads_the_check_half():
    man, split, rows = _old_world()
    rep = ft.old_report( rows, split, 0.05, cuts = ft.OLD_CUTS )
    assert rep[ "chosen" ][ "cut" ] in ft.OLD_CUTS and rep[ "counts" ][ "fit" ][ "rows" ] + rep[ "counts" ][ "check" ][ "rows" ] == 1165
    assert rep[ "on_fit" ][ "false_reuse_rate" ] <= 0.05 and rep[ "on_check" ][ "members" ] > 0
    assert ft.old_report( list( reversed( rows ) ), split, 0.05 ) == rep


def test_the_old_report_names_the_rate_as_a_placeholder_only_when_the_caller_says_so():
    man, split, rows = _old_world()
    assert "placeholder" not in ft.render( ft.old_report( rows, split, 0.05 ) )
    assert "placeholder" in ft.render( ft.old_report( rows, split, 0.05, placeholder = True ) )


# --- the command ---------------------------------------------------------------------------------------------------------

def test_the_command_reads_old_results_with_the_manifest_and_the_split_and_prints_the_report(tmp_path, capsys):
    man, split, _ = _old_world()
    ( tmp_path / "man.json" ).write_text( json.dumps( man ) ); ( tmp_path / "split.json" ).write_text( json.dumps( split ) )
    assert ft.main( [ "--old-results", str( FIX / "stage2-old-results-slice.json" ), "--manifest", str( tmp_path / "man.json" ),
                      "--split", str( tmp_path / "split.json" ), "--rate", "0.05", "--placeholder" ] ) == 0
    out = capsys.readouterr().out
    assert "false-reuse rate allowed: 0.05 (placeholder)" in out and "chosen on the fit half" in out


def test_the_command_reads_a_rows_file_of_the_new_question(tmp_path, capsys):
    split = { "fit": [ { "members": [ "m" ] } ], "check": [ { "members": [ "k" ] } ], "seed": 5, "groups": 2, "members": 2 }
    ( tmp_path / "rows.json" ).write_text( json.dumps( { "rows": _opt_rows() + [ _row( "k", "t", True, 0.9 ) ] } ) )
    ( tmp_path / "split.json" ).write_text( json.dumps( split ) )
    assert ft.main( [ "--rows", str( tmp_path / "rows.json" ), "--split", str( tmp_path / "split.json" ), "--rate", "0.5" ] ) == 0
    assert "chosen on the fit half" in capsys.readouterr().out


def test_the_command_needs_exactly_one_source_of_rows(tmp_path):
    ( tmp_path / "s.json" ).write_text( "{}" )
    with pytest.raises( SystemExit ): ft.main( [ "--split", str( tmp_path / "s.json" ), "--rate", "0.1" ] )
    with pytest.raises( SystemExit ): ft.main( [ "--rows", "a", "--old-results", "b", "--split", str( tmp_path / "s.json" ), "--rate", "0.1" ] )
    with pytest.raises( SystemExit ): ft.main( [ "--old-results", "b", "--split", str( tmp_path / "s.json" ), "--rate", "0.1" ] )
