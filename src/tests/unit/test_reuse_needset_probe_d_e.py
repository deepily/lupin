"""Tests for the probe d and e replay over a saved control report."""

import json

import pytest

from cosa.repo.symindex.candidates import rank_fusion as rf
from lupin_mcp.reuse_needset import probe_d_e as pde


def reading( code=None, prose=None, vector=None, fused=None ):
    """Ensures: returns a reading in the shape the control report saves."""
    return { "id": "x", "retrieved": fused is not None, "ranks": { "code": code, "prose": prose, "vector_concat": vector, "fused": fused } }


def row( rewrite, same_job, line, bare, original, leak=( 0.1, 0.2 ), drafted=True ):
    """Ensures: returns a pair row with three readings and the saved overlaps."""
    if not drafted: return { "drafted": False, "history": [], "reason": "NEED_LEAKS_KEY", "rewrite": rewrite, "same_job": same_job }
    return { "drafted": True, "lang": "py", "leak": { "plant": leak[ 0 ], "original": leak[ 1 ] }, "original": original, "plant": line, "plant_bare": bare,
             "purpose_line": "x", "rewrite": rewrite, "same_job": same_job }


def report_of( rows, extra_pass=None ):
    """Ensures: returns a report of two passes, the second replaced by extra_pass if given."""
    passes = [ { "rows": rows }, { "rows": rows if extra_pass is None else extra_pass } ]
    return { "stages": { "control": { "report": { "rows": rows, "passes": passes } } } }


def small_rows():
    """Ensures: returns three drafted rows and one undrafted row."""
    return [ row( "a", True,  reading( None, 3, 1, 2 ),  reading( None, None, 25, 93 ),  reading( 1588, 104, 1280, 332 ), leak=( 0.2, 0.1 ) ),
             row( "b", True,  reading( 17, 119, 2, 1 ),  reading( 17, None, 210, 38 ),  reading( None, 9, 1, 4 ),         leak=( 0.1, 0.1 ) ),
             row( "c", False, reading( None, 2, 279, 23 ), reading( None, None, 8800, None ), reading( None, 5, 1000, 41 ), leak=( 0.15, None ) ),
             row( "u", True,  None, None, None, drafted=False ) ]


def test_term_is_none_absent_and_the_fusion_term_inside_the_depth_and_zero_beyond():
    assert pde.term( None ) is None
    assert pde.term( 1 ) == 1.0 / ( rf.FUSION_K + 1 )
    assert pde.term( rf.FUSION_DEPTH ) == 1.0 / ( rf.FUSION_K + rf.FUSION_DEPTH )
    assert pde.term( rf.FUSION_DEPTH + 1 ) == 0.0


def test_arm_view_gives_terms_total_and_shares_of_the_lists_that_hold_the_entry():
    v = pde.arm_view( reading( None, 3, 1, 2 ) )
    assert v[ "terms" ][ "code" ] is None
    assert v[ "total" ] == 1.0 / 63 + 1.0 / 61
    assert v[ "shares" ][ "prose" ] == ( 1.0 / 63 ) / v[ "total" ]
    assert v[ "shares" ][ "vector_concat" ] == ( 1.0 / 61 ) / v[ "total" ]
    assert v[ "shares" ][ "code" ] is None
    assert v[ "ranks" ] == { "code": None, "prose": 3, "vector_concat": 1, "fused": 2 }


def test_arm_view_gives_no_share_when_every_held_term_is_zero_beyond_the_depth():
    v = pde.arm_view( reading( 600, None, 700, None ) )
    assert v[ "total" ] == 0.0
    assert v[ "shares" ] == { "code": None, "prose": None, "vector_concat": None }
    assert v[ "terms" ][ "code" ] == 0.0


def test_inside_counts_a_place_at_the_cut_off_and_not_an_absent_one():
    assert pde.inside( 10, 10 ) and not pde.inside( 11, 10 ) and not pde.inside( None, 10 )


def test_presence_counts_each_source_and_the_fused_list_at_each_cut_off():
    views = [ pde.arm_view( reading( None, 3, 1, 2 ) ), pde.arm_view( reading( 40, 200, 2, 50 ) ) ]
    got   = pde.presence( views )
    assert got[ "prose" ] == { 10: 1, 32: 1, 128: 1 }
    assert got[ "vector_concat" ] == { 10: 2, 32: 2, 128: 2 }
    assert got[ "code" ] == { 10: 0, 32: 0, 128: 1 }
    assert got[ "fused" ] == { 10: 1, 32: 1, 128: 2 }


def test_mean_shares_averages_over_the_views_that_hold_the_list_and_is_none_when_none_do():
    views = [ pde.arm_view( reading( None, 3, 1, 2 ) ), pde.arm_view( reading( None, None, 2, 5 ) ) ]
    got   = pde.mean_shares( views )
    assert got[ "code" ] is None
    assert got[ "vector_concat" ] == ( views[ 0 ][ "shares" ][ "vector_concat" ] + 1.0 ) / 2
    assert got[ "prose" ] == views[ 0 ][ "shares" ][ "prose" ]


def test_newly_inside_lists_the_pair_inside_with_the_line_and_outside_without_it_and_names_the_lists():
    pairs = pde.probe_d( [ r for r in small_rows() if r[ "drafted" ] ] )[ "pairs" ]
    got   = pde.newly_inside( pairs, 10 )
    assert [ g[ "rewrite" ] for g in got ] == [ "a", "b" ]
    assert got[ 0 ][ "line_sources" ] == [ "prose", "vector_concat" ] and got[ 0 ][ "bare_sources" ] == []
    assert got[ 1 ][ "line_sources" ] == [ "vector_concat" ] and got[ 1 ][ "bare_sources" ] == []


def test_newly_inside_skips_a_pair_inside_both_ways_and_one_outside_both_ways():
    both    = row( "p", True, reading( None, 1, 1, 1 ), reading( None, None, 1, 2 ), reading( None, 1, 1, 1 ) )
    neither = row( "q", True, reading( None, None, 900, 800 ), reading( None, None, 900, 800 ), reading( None, 1, 1, 1 ) )
    assert pde.newly_inside( pde.probe_d( [ both, neither ] )[ "pairs" ], 10 ) == []


def test_probe_d_keeps_pair_order_labels_and_all_three_arms():
    got = pde.probe_d( [ r for r in small_rows() if r[ "drafted" ] ] )
    assert [ p[ "rewrite" ] for p in got[ "pairs" ] ] == [ "a", "b", "c" ]
    assert [ p[ "same_job" ] for p in got[ "pairs" ] ] == [ True, True, False ]
    assert got[ "pairs" ][ 0 ][ "original" ][ "ranks" ][ "code" ] == 1588
    assert got[ "presence" ][ "line" ][ "fused" ][ 10 ] == 2
    assert got[ "presence" ][ "bare" ][ "fused" ][ 10 ] == 0
    assert set( got[ "newly_inside" ] ) == { 10, 32, 128 }
    assert got[ "mean_shares" ][ "bare" ][ "prose" ] is None


def test_leak_split_counts_each_direction_and_skips_a_missing_overlap():
    rows = [ r for r in small_rows() if r[ "drafted" ] ]
    got  = pde.leak_split( rows )
    assert got == { "pairs": 2, "plant_higher": 1, "tied": 1, "original_higher": 0, "median_difference": 0.05, "mean_difference": 0.05 }


def test_leak_split_counts_the_original_higher_case_and_a_missing_plant_overlap():
    rows = [ row( "a", True, None, None, None, leak=( 0.1, 0.3 ) ), row( "b", True, None, None, None, leak=( None, 0.3 ) ) ]
    got  = pde.leak_split( rows )
    assert ( got[ "pairs" ], got[ "original_higher" ], got[ "plant_higher" ], got[ "median_difference" ] ) == ( 1, 1, 0, -0.2 )


def test_leak_split_gives_none_for_an_empty_population():
    assert pde.leak_split( [] ) == { "pairs": 0, "plant_higher": 0, "tied": 0, "original_higher": 0, "median_difference": None, "mean_difference": None }


def test_probe_e_splits_by_label_and_keeps_the_overlaps_as_saved():
    got = pde.probe_e( [ r for r in small_rows() if r[ "drafted" ] ] )
    assert got[ "all" ][ "pairs" ] == 2 and got[ "same_job" ][ "pairs" ] == 2 and got[ "not_same" ][ "pairs" ] == 0
    assert got[ "pairs" ][ 2 ] == { "rewrite": "c", "same_job": False, "plant": 0.15, "original": None }


def test_drafted_rows_drops_the_undrafted_rows_and_keeps_order():
    assert [ r[ "rewrite" ] for r in pde.drafted_rows( report_of( small_rows() ) ) ] == [ "a", "b", "c" ]


def test_passes_agree_is_true_for_identical_passes_and_false_for_a_changed_one():
    rows = small_rows()
    assert pde.passes_agree( report_of( rows ) ) is True
    assert pde.passes_agree( report_of( rows, extra_pass=rows[ :1 ] ) ) is False


def test_replay_counts_drafted_and_undrafted_and_runs_both_probes():
    got = pde.replay( report_of( small_rows() ) )
    assert ( got[ "drafted" ], got[ "undrafted" ], got[ "passes_agree" ] ) == ( 3, 1, True )
    assert len( got[ "d" ][ "pairs" ] ) == 3 and got[ "e" ][ "all" ][ "pairs" ] == 2


def test_cell_prints_a_dash_for_none_three_places_for_a_float_and_text_for_an_int():
    assert ( pde.cell( None ), pde.cell( 0.5 ), pde.cell( 7 ) ) == ( "-", "0.500", "7" )


def test_render_holds_every_table_and_the_newly_inside_lines():
    text = pde.render( pde.replay( report_of( small_rows() ) ) )
    assert text.startswith( "3 drafted pairs, 1 undrafted; the two passes hold identical rows: True" )
    assert "| a | True | -/3/1/2 | -/-/25/93 | 1588/104/1280/332 |" in text
    assert "| line | vector_concat | 2 | 2 | 2 |" in text
    assert "Inside 10 fused with the line and not without it: 2" in text
    assert "- a: with line ['prose', 'vector_concat'], without []" in text
    assert "| all | 2 | 1 | 1 | 0 | 0.050 | 0.050 |" in text
    assert "| not_same | 0 | 0 | 0 | 0 | - | - |" in text


def test_main_writes_the_json_and_prints_the_tables( tmp_path, capsys ):
    src = tmp_path / "stage-reports.json"
    out = tmp_path / "out.json"
    src.write_text( json.dumps( report_of( small_rows() ) ) )
    assert pde.main( [ "--report", str( src ), "--out", str( out ) ] ) == 0
    assert json.loads( out.read_text() )[ "drafted" ] == 3
    assert "3 drafted pairs" in capsys.readouterr().out


def test_main_prints_without_writing_when_no_out_is_given( tmp_path, capsys ):
    src = tmp_path / "stage-reports.json"
    src.write_text( json.dumps( report_of( small_rows() ) ) )
    assert pde.main( [ "--report", str( src ) ] ) == 0
    assert "3 drafted pairs" in capsys.readouterr().out
    assert list( tmp_path.iterdir() ) == [ src ]


def test_main_needs_a_report():
    with pytest.raises( SystemExit ):
        pde.main( [] )
