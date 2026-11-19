"""
The before-and-after report shows four runs side by side.

The columns are hand-written literals. Each expected change is worked out by hand in its test.
A renderer that swapped two columns, or took a change from the wrong pair, would fail.
"""

import copy

import pytest

from cosa.research.preference_replay import before_after_report as bar


def _column( label, commit, source, asks, yn_final_correct, mc_tune_correct, ids=None, brier=( 0.2239, 0.1728 ), threshold=0.5 ):
    """One column in the shape the module documents."""
    column = {
        "label": label, "commit": commit, "vector_source": source, "ask_count": asks, "threshold": threshold, "top_k": 10,
        "coverage": {
            "cohort_asks": 3608, "replayable": asks,
            "tune_mix": { "multiple_choice": 100, "yes_no": 50 }, "final_mix": { "multiple_choice": 40, "yes_no": 200 },
            "scores": {
                "tune"  : { "multiple_choice": { "asks": 100, "correct": mc_tune_correct }, "yes_no": { "asks": 50, "correct": 25 } },
                "final" : { "multiple_choice": { "asks": 40, "correct": 4 }, "yes_no": { "asks": 200, "correct": yn_final_correct } },
            },
        },
        "calibration": { "tune_size": 150, "final_size": 240, "cells": {
            "yes_no/cbr": { "status": "evaluated", "brier_raw": brier[ 0 ], "brier_calibrated": brier[ 1 ] },
            "mc/cold": { "status": "not fitted" } } },
    }
    column[ "yes_no_summary" ] = { "engine_correct": yn_final_correct, "baseline_correct": 173, "engine_only_right": 3, "baseline_only_right": 10,
                                   "mcnemar": { "p_value": 0.046142578125 }, "verdict": "baseline better" }
    if ids is not None: column[ "ask_ids" ] = ids
    return column


NOTE = "n/a (scored on Before's 391 final asks)"


@pytest.fixture
def columns():
    """The four columns."""
    first = _column( "before", "8d748e033", "stored", 1302, 160, 10, ids=[ "a", "b" ] )
    first[ "produced_by" ] = "replay 086f95590, src/scripts/preference_step9_checkpoint_run.py"
    cols = [
        first,
        _column( "same asks, new vectors", "c2", { "model": "m", "revision": "r1" }, 1302, 170, 12, ids=[ "b", "a" ], brier=( 0.2, 0.15 ) ),
        _column( "all asks, new vectors", "c3", { "model": "m", "revision": "r1" }, 3610, 168, 12, ids=[ "a", "b", "c" ], threshold=0.6 ),
        _column( "all asks, before's final window", "c4", { "model": "m", "revision": "r1" }, 3610, 172, 11, ids=[ "a", "b", "c" ], threshold=0.6 ),
    ]
    cols[ 3 ][ "tune_note" ] = NOTE
    return cols


def test_check_columns_accepts_the_design( columns ):
    assert bar.check_columns( columns ) is None


def test_check_columns_refuses_wrong_count( columns ):
    with pytest.raises( bar.ReportMismatch, match="expected 4 columns, got 2" ):
        bar.check_columns( columns[ :2 ] )


def test_check_columns_refuses_different_ask_counts_three_and_four( columns ):
    columns[ 3 ][ "ask_count" ] = 3000
    with pytest.raises( bar.ReportMismatch, match="columns 3 and 4 must hold the same asks, got 3610 and 3000" ):
        bar.check_columns( columns )


def test_check_columns_final_ids_must_match_before( columns ):
    columns[ 0 ][ "final_ids" ] = [ "a", "b" ]
    columns[ 3 ][ "final_ids" ] = [ "b", "a" ]
    assert bar.check_columns( columns ) is None
    columns[ 3 ][ "final_ids" ] = [ "a", "x" ]
    with pytest.raises( bar.ReportMismatch, match="columns 1 and 4 do not score the same final-window asks" ):
        bar.check_columns( columns )


def test_check_columns_refuses_column_four_scoring_extra_asks_beyond_column_ones( columns ):
    columns[ 0 ][ "final_ids" ] = [ "a", "b" ]
    columns[ 3 ][ "final_ids" ] = [ "a", "b", "extra" ]
    with pytest.raises( bar.ReportMismatch, match="columns 1 and 4 do not score the same final-window asks" ):
        bar.check_columns( columns )


def test_check_control_passes_on_equal_and_refuses_otherwise():
    assert bar.check_control( 177, 177 ) is None
    with pytest.raises( bar.ReportMismatch, match="control run gave 170 final-window correct, the committed report has 177" ):
        bar.check_control( 177, 170 )


def test_check_columns_refuses_missing_key( columns ):
    del columns[ 1 ][ "commit" ]
    with pytest.raises( bar.ReportMismatch, match="lacks \\['commit'\\]" ):
        bar.check_columns( columns )


def test_check_columns_names_an_unlabelled_column_in_the_refusal( columns ):
    del columns[ 2 ][ "label" ]
    with pytest.raises( bar.ReportMismatch, match="'\\?'" ):
        bar.check_columns( columns )


def test_check_columns_refuses_different_ask_counts( columns ):
    columns[ 1 ][ "ask_count" ] = 1300
    with pytest.raises( bar.ReportMismatch, match="same asks, got 1302 and 1300" ):
        bar.check_columns( columns )


def test_check_columns_refuses_different_asks_one_and_two( columns ):
    columns[ 1 ][ "ask_ids" ] = [ "a", "z" ]
    with pytest.raises( bar.ReportMismatch, match="different asks" ):
        bar.check_columns( columns )


def test_check_columns_refuses_column_three_missing_an_ask( columns ):
    columns[ 2 ][ "ask_ids" ] = [ "a" ]
    with pytest.raises( bar.ReportMismatch, match="column 3 does not contain" ):
        bar.check_columns( columns )


def test_check_columns_skips_id_checks_when_ids_absent( columns ):
    for column in columns: del column[ "ask_ids" ]
    assert bar.check_columns( columns ) is None
    del_one = copy.deepcopy( columns )
    del_one[ 0 ][ "ask_ids" ] = [ "q" ]
    assert bar.check_columns( del_one ) is None


def test_column_rows_reads_each_figure_from_its_source( columns ):
    rows = bar.column_rows( columns[ 0 ] )
    assert rows[ "asks" ] == 1302 and rows[ "threshold" ] == 0.5 and rows[ "top k" ] == 10
    assert rows[ "tune asks: yes_no" ] == 50 and rows[ "final asks: multiple_choice" ] == 40
    assert rows[ "final correct: yes_no" ] == 160
    assert rows[ "final correct per 100: yes_no" ] == 80.0
    assert rows[ "tune correct per 100: multiple_choice" ] == 10.0
    assert rows[ "calibration yes_no/cbr: Brier raw" ] == 0.2239
    assert rows[ "calibration yes_no/cbr: Brier calibrated" ] == 0.1728
    assert rows[ "calibration mc/cold" ] == "not fitted"
    assert "calibration mc/cold: Brier raw" not in rows


def test_column_rows_fills_a_type_missing_from_one_mix():
    column = _column( "x", "c", "stored", 10, 1, 1 )
    del column[ "coverage" ][ "tune_mix" ][ "yes_no" ]
    assert bar.column_rows( column )[ "tune asks: yes_no" ] == 0


@pytest.mark.parametrize( "value,text", [ ( None, "n/a" ), ( 7, "7" ), ( 0.1728, "0.1728" ), ( 80.0, "80.0" ), ( "same", "same" ) ] )
def test_shown( value, text ):
    assert bar._shown( value ) == text


@pytest.mark.parametrize( "earlier,later,text", [
    ( None, 3, "n/a" ), ( 3, None, "n/a" ),
    ( 160, 170, "+10" ), ( 12, 10, "-2" ),
    ( 80.0, 85.0, "+5.0" ), ( 0.2239, 0.2, "-0.0239" ),
    ( 0.5, 0.6, "+0.1000" ),
    ( "a", "a", "same" ), ( "a", "b", "changed" ),
    ( "a", 3, "n/a" ), ( 3, "a", "n/a" ),
] )
def test_change( earlier, later, text ):
    assert bar._change( earlier, later ) == text


def test_vector_source_string_and_dict():
    assert bar._vector_source( "stored" ) == "stored"
    assert bar._vector_source( { "model": "m", "revision": "r1" } ) == "m @ r1"


def test_render_provenance_names_commit_source_and_asks( columns ):
    text = bar.render_before_after( columns )
    assert "| 1 | before | `8d748e033` | stored | 1302 |" in text
    assert "| 2 | same asks, new vectors | `c2` | m @ r1 | 1302 | 390 | not stated |" in text
    assert "| 3 | all asks, new vectors | `c3` | m @ r1 | 3610 | 390 | not stated |" in text
    assert "| 1 | before | `8d748e033` | stored | 1302 | 390 | replay 086f95590, src/scripts/preference_step9_checkpoint_run.py |" in text


def test_render_changes_come_from_the_right_pairs( columns ):
    text = bar.render_before_after( columns )
    assert "| final correct: yes_no | 160 | 170 | 168 | 172 | +10 | -2 | +4 |" in text
    assert "| final correct per 100: yes_no | 80.0 | 85.0 | 84.0 | 86.0 | +5.0 | -1.0 | +2.0 |" in text
    assert f"| tune correct: multiple_choice | 10 | 12 | 12 | {NOTE} | +2 | +0 | n/a |" in text
    assert "| calibration yes_no/cbr: Brier raw | 0.2239 | 0.2000 | 0.2239 | 0.2239 | -0.0239 | +0.0239 | +0.0000 |" in text
    assert "| threshold | 0.5000 | 0.5000 | 0.6000 | 0.6000 | +0.0000 | +0.1000 | +0.0000 |" in text
    assert "| asks | 1302 | 1302 | 3610 | 3610 | +0 | +2308 | +0 |" in text
    assert "| calibration mc/cold | not fitted | not fitted | not fitted | not fitted | same | same | same |" in text


def test_render_figure_missing_from_a_column_reads_na( columns ):
    columns[ 2 ][ "calibration" ][ "cells" ][ "extra" ] = { "status": "evaluated", "brier_raw": 0.3, "brier_calibrated": 0.2 }
    text = bar.render_before_after( columns )
    assert "| calibration extra: Brier raw | n/a | n/a | 0.3000 | n/a | n/a | n/a | n/a |" in text


def test_render_refuses_bad_columns( columns ):
    with pytest.raises( bar.ReportMismatch ):
        bar.render_before_after( columns[ :1 ] )


def test_render_is_deterministic_and_titled( columns ):
    first = bar.render_before_after( columns, title="T" )
    assert first == bar.render_before_after( columns, title="T" )
    assert first.startswith( "# T\n" )
    assert "effect of the regenerated vectors alone" in first


def test_the_header_lists_the_labels_in_column_order_then_the_three_changes( columns ):
    text = bar.render_before_after( columns )
    assert "| figure | before | same asks, new vectors | all asks, new vectors | all asks, before's final window | change 1 to 2 | change 2 to 3 | change 3 to 4 |" in text


def test_every_figure_appears_in_exactly_one_row( columns ):
    rows = [ line.split( " | " )[ 0 ] for line in bar.render_before_after( columns ).splitlines() if line.startswith( "| " ) and line.count( "|" ) == 9 ]
    assert len( rows ) > 20 and len( rows ) == len( set( rows ) )


def test_check_columns_refuses_five_columns( columns ):
    with pytest.raises( bar.ReportMismatch, match="expected 4 columns, got 5" ):
        bar.check_columns( columns + [ columns[ 0 ] ] )


def test_check_control_refuses_above_the_committed_count_too():
    with pytest.raises( bar.ReportMismatch, match="control run gave 178" ):
        bar.check_control( 177, 178 )


def test_check_columns_refuses_different_frozen_settings_in_columns_three_and_four( columns ):
    columns[ 3 ][ "threshold" ] = 0.5
    with pytest.raises( bar.ReportMismatch, match="same frozen threshold and top k" ):
        bar.check_columns( columns )
    columns[ 3 ][ "threshold" ] = 0.6
    columns[ 3 ][ "top_k" ] = 5
    with pytest.raises( bar.ReportMismatch, match="same frozen threshold and top k" ):
        bar.check_columns( columns )


def test_a_type_with_no_asks_in_a_window_reads_na_not_a_divide_error( columns ):
    columns[ 0 ][ "coverage" ][ "scores" ][ "final" ][ "multiple_choice" ] = { "asks": 0, "correct": 0 }
    rows = bar.column_rows( columns[ 0 ] )
    assert rows[ "final correct per 100: multiple_choice" ] == "n/a"
    assert rows[ "final correct per 100: yes_no" ] == 80.0


def test_a_calibration_status_other_than_evaluated_shows_the_status_not_brier_scores( columns ):
    columns[ 0 ][ "calibration" ][ "cells" ][ "x/y" ] = { "status": "skipped", "brier_raw": 9.0, "brier_calibrated": 9.0 }
    rows = bar.column_rows( columns[ 0 ] )
    assert rows[ "calibration x/y" ] == "skipped"
    assert "calibration x/y: Brier raw" not in rows


def test_the_yes_no_comparison_against_always_yes_is_read_from_each_columns_summary( columns ):
    text = bar.render_before_after( columns )
    assert "| yes_no vs always-yes: predictor correct | 160 | 170 | 168 | 172 | +10 | -2 | +4 |" in text
    assert "| yes_no vs always-yes: baseline correct | 173 | 173 | 173 | 173 | +0 | +0 | +0 |" in text
    assert "| yes_no vs always-yes: predictor only right | 3 | 3 | 3 | 3 | +0 | +0 | +0 |" in text
    assert "| yes_no vs always-yes: baseline only right | 10 | 10 | 10 | 10 | +0 | +0 | +0 |" in text
    assert "| yes_no vs always-yes: McNemar exact p | 0.0461 | 0.0461 | 0.0461 | 0.0461 | +0.0000 | +0.0000 | +0.0000 |" in text
    assert "| yes_no vs always-yes: verdict | baseline better | baseline better | baseline better | baseline better | same | same | same |" in text


def test_a_column_with_a_tune_note_reports_final_window_figures_only( columns ):
    rows = bar.column_rows( columns[ 3 ] )
    tune = [ name for name in rows if name.startswith( "tune " ) ]
    assert len( tune ) == 6 and all( rows[ name ] == NOTE for name in tune )
    assert rows[ "final correct: yes_no" ] == 172
    assert rows[ "threshold" ] == 0.6
    plain = bar.column_rows( columns[ 2 ] )
    assert plain[ "tune correct: yes_no" ] == 25
