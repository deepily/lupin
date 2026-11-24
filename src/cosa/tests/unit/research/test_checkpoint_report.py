"""
The checkpoint report names its cohort, defers thin types and refuses a moved cohort.

The summaries are hand-written literals in the shape the replay's summarize returns. The metric values
are worked out by hand in each test, so a renderer that mixed up two arms or two labels would be caught.
"""

import copy
import hashlib
import json
import subprocess
import sys

import pytest

from cosa.research.phi4_flash_lite_study.freeze_corpus import sha256_of_rows
from cosa.research.preference_replay import checkpoint_report as cr

SHA = "c0" * 32
ROWS = [ { "id": "a", "answer": "yes" }, { "id": "b", "answer": "no" }, { "id": "c", "answer": "yes" } ]


def _summary( **over ):
    """A summarize result with every field the report reads."""
    base = { "baseline": "always_yes", "asks_replayed": 40, "not_replayable": 2, "unrebuildable_cases": 0, "families": 31,
             "engine_correct": 30, "engine_interval": ( 0.6, 0.85 ), "baseline_correct": 25, "baseline_interval": ( 0.47, 0.75 ),
             "engine_only_right": 8, "baseline_only_right": 3, "mcnemar": { "p_value": 0.2266 }, "operational_floor": 10,
             "floor_met": False, "verdict": "not decisive" }
    base.update( over )
    return base


CAL = { "tune_size": 70, "final_size": 30, "cells": { "yes_no|cbr_majority_vote": { "status": "evaluated", "brier_raw": 0.25, "brier_calibrated": 0.2 },
                                                      "open_ended|cbr_majority_vote": { "status": "not fitted" } } }
FINDINGS = [ { "title": "A moved ask", "detail": "ask 27b147e8 moves windows when keyed on asked_at" } ]


def _report( **over ):
    """Render with the shared inputs, overridden per test."""
    args = dict( summaries={ "yes_no": { "always_yes": _summary() } }, final_window_asks={ "yes_no": 30, "batch": 6 }, calibration=CAL,
                 findings=FINDINGS, cohort_sha256=SHA, settings_commit="abc1234", cohort_ids=[ "a", "b", "c" ] )
    args.update( over )
    return cr.render_report( **args )


def test_the_deferral_rule_counts_asks_and_flips_at_20():
    """19 eligible final-window asks defer a type; 20 do not."""
    assert cr.deferral( { "x": 19, "y": 20 } ) == { "x": { "asks": 19, "deferred": True }, "y": { "asks": 20, "deferred": False } }


def test_label_metrics_are_scikit_learns_values_for_a_worked_example():
    """Worked example: yes is 2 of 3 found and 2 of 2 right; no is 2 of 2 found and 2 of 3 right."""
    scored = cr.label_metrics( [ "yes", "yes", "no", "no", "yes" ], [ "yes", "no", "no", "no", "yes" ], [ "yes", "no" ] )
    assert scored[ "confusion_matrix" ] == [ [ 2, 1 ], [ 0, 2 ] ]
    assert scored[ "precision" ] == pytest.approx( [ 1.0, 2 / 3 ] ) and scored[ "recall" ] == pytest.approx( [ 2 / 3, 1.0 ] )
    assert scored[ "support" ] == [ 3, 2 ] and scored[ "jaccard" ] == pytest.approx( [ 2 / 3, 2 / 3 ] )


def test_the_report_carries_the_sha_the_commit_the_denominators_and_every_id():
    """Everything the plan lists is in the text."""
    text = _report()
    for needle in ( SHA, "abc1234", "asks replayed: 40", "not replayable: 2", "unique families: 31", "predictor only 8, baseline only 3",
                    "verdict: not decisive", "- a\n- b\n- c", "cohort asks: 3" ):
        assert needle in text, needle


def test_the_deferral_verdict_and_the_calibration_cells_and_findings_are_rendered():
    """A 6-ask type is deferred, a 30-ask type is not, a refused cell has no score."""
    text = _report()
    assert "## batch\n\nEligible final-window asks: 6. Deferred: fewer than 20 asks." in text
    assert "## yes_no\n\nEligible final-window asks: 30. Not deferred." in text
    assert "yes_no|cbr_majority_vote: evaluated, Brier raw 0.2500, calibrated 0.2000" in text
    assert "- open_ended|cbr_majority_vote: not fitted\n" in text
    assert "**A moved ask**: ask 27b147e8 moves windows when keyed on asked_at" in text


def test_the_same_inputs_render_the_same_text():
    """No clock, no ordering luck."""
    assert _report() == _report()


def test_write_checkpoint_freezes_the_cohort_and_names_the_report( tmp_path ):
    """A 6-ask type is deferred, a 30-ask type is not, a refused cell has no score."""
    text = _report()
    out  = cr.write_checkpoint( text, ROWS, str( tmp_path / "cohort.jsonl" ), str( tmp_path / "manifest.json" ), str( tmp_path / "checkpoint.json" ),
                                "abc1234", frozen_at="2026-11-18T00:00:00+00:00" )
    assert out == json.load( open( tmp_path / "checkpoint.json" ) )
    assert out[ "report_sha256" ] == hashlib.sha256( text.encode() ).hexdigest()
    assert out[ "cohort_sha256" ] == sha256_of_rows( ROWS ) == hashlib.sha256( open( tmp_path / "cohort.jsonl", "rb" ).read() ).hexdigest()
    assert ( out[ "cohort_rows" ], out[ "settings_commit" ], out[ "frozen_at" ] ) == ( 3, "abc1234", "2026-11-18T00:00:00+00:00" )


def test_write_checkpoint_stamps_the_time_when_none_is_given( tmp_path ):
    """With no frozen_at the document carries a timezone-aware time."""
    out = cr.write_checkpoint( "r", ROWS, str( tmp_path / "c.jsonl" ), str( tmp_path / "m.json" ), str( tmp_path / "k.json" ), "abc" )
    assert out[ "frozen_at" ].endswith( "+00:00" )


def test_write_checkpoint_refuses_a_cohort_file_that_does_not_re_derive( tmp_path, monkeypatch ):
    """When the file on disk differs, no freeze file is written."""
    monkeypatch.setattr( cr, "verify_snapshot", lambda snapshot, manifest: ( False, "sha256 differs" ) )
    with pytest.raises( cr.CheckpointMismatch, match="sha256 differs" ):
        cr.write_checkpoint( "r", ROWS, str( tmp_path / "c.jsonl" ), str( tmp_path / "m.json" ), str( tmp_path / "k.json" ), "abc" )
    assert not ( tmp_path / "k.json" ).exists()


def _frozen( tmp_path ):
    """A real freeze file for the three-row cohort."""
    cr.write_checkpoint( "r", ROWS, str( tmp_path / "c.jsonl" ), str( tmp_path / "m.json" ), str( tmp_path / "k.json" ), "abc" )
    return str( tmp_path / "k.json" )


def test_a_report_on_the_frozen_cohort_is_allowed( tmp_path ):
    """Every record carries the frozen sha, so the code is 0 and nothing is printed."""
    said = []
    assert cr.refuse_post_checkpoint_report( [ { "snapshot_sha256": sha256_of_rows( ROWS ) } ] * 3, _frozen( tmp_path ), said.append ) == 0
    assert said == []


def test_a_planted_mismatched_sha_is_refused_and_both_shas_are_named( tmp_path ):
    """One record on another cohort gives code 3, and the message names both shas."""
    said = []
    code = cr.refuse_post_checkpoint_report( [ { "snapshot_sha256": sha256_of_rows( ROWS ) }, { "snapshot_sha256": "f" * 64 } ], _frozen( tmp_path ), said.append )
    assert code == 3 and sha256_of_rows( ROWS ) in said[ 0 ] and "f" * 64 in said[ 0 ]


def test_no_records_is_refused_because_it_matches_nothing( tmp_path ):
    """An empty arm does not pass for the frozen cohort."""
    said = []
    assert cr.refuse_post_checkpoint_report( [], _frozen( tmp_path ), said.append ) == 3 and "no records" in said[ 0 ]


def test_the_command_exits_non_zero_on_a_mismatch_and_zero_on_a_match( tmp_path ):
    """As a process, the check exits 3 for a planted wrong sha and 0 for the frozen one."""
    checkpoint = _frozen( tmp_path )
    good, bad  = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text( json.dumps( [ { "snapshot_sha256": sha256_of_rows( ROWS ) } ] ) )
    bad.write_text( json.dumps( [ { "snapshot_sha256": "0" * 64 } ] ) )
    run = lambda records: subprocess.run( [ sys.executable, "-m", "cosa.research.preference_replay.checkpoint_report", "--records", str( records ),
                                            "--checkpoint", checkpoint ], capture_output=True, text=True )
    assert run( good ).returncode == 0
    refused = run( bad )
    assert refused.returncode == 3 and "REFUSED" in refused.stdout


def test_main_returns_the_refusal_code( tmp_path ):
    """main is what the process exits with."""
    checkpoint = _frozen( tmp_path )
    records    = tmp_path / "r.json"
    records.write_text( json.dumps( [ { "snapshot_sha256": "0" * 64 } ] ) )
    assert cr.main( [ "--records", str( records ), "--checkpoint", checkpoint ], printer=lambda message: None ) == 3


def test_label_metrics_score_a_label_nobody_used_as_zero():
    """A label in neither list scores 0 on every metric, never 1.

    It has no support, so precision, recall, f-score and Jaccard all read 0.
    """
    scored = cr.label_metrics( [ "yes", "no" ], [ "yes", "no" ], [ "yes", "no", "maybe" ] )
    assert scored[ "support" ] == [ 1, 1, 0 ]
    assert scored[ "precision" ][ 2 ] == 0.0 and scored[ "recall" ][ 2 ] == 0.0
    assert scored[ "f_score" ][ 2 ] == 0.0 and scored[ "jaccard" ][ 2 ] == 0.0


def test_types_baselines_and_calibration_cells_are_written_in_name_order_whatever_the_insert_order():
    """Everything is inserted z-first; the text lists it a-first.

    Two runs over one cohort then read alike.
    """
    cells = { "z|s": { "status": "not fitted" }, "a|s": { "status": "not fitted" } }
    text  = _report( summaries={ "yes_no": { "zeta": _summary(), "alpha": _summary() } },
                     final_window_asks={ "yes_no": 30, "batch": 6 }, calibration=dict( CAL, cells=cells ) )
    assert text.index( "## batch" ) < text.index( "## yes_no" )
    assert text.index( "against alpha" ) < text.index( "against zeta" )
    assert text.index( "- a|s:" ) < text.index( "- z|s:" )


def _point( threshold, top_k, **over ):
    """A retune point in the shape retune returns, answered figures included."""
    base = { "threshold": threshold, "top_k": top_k, "tune_correct": 30, "tune_per_100": 40.0, "final_correct": 12, "final_per_100": 48.0,
             "tune_answered": 50, "tune_answer_rate_per_100": 66.7, "tune_accuracy_answered_per_100": 60.0,
             "final_answered": 20, "final_answer_rate_per_100": 80.0, "final_accuracy_answered_per_100": 60.0 }
    base.update( over )
    return base


RETUNE = { "tune_size": 75, "final_size": 25, "eligible": 100, "tune_cohort_sha256": SHA,
           "points": [ _point( 0.5, 5, tune_per_100=41.0 ), _point( 0.3, 3, tune_answered=70, tune_answer_rate_per_100=93.3,
                                                                  tune_accuracy_answered_per_100=42.9 ) ],
           "best": _point( 0.5, 5, tune_per_100=41.0 ) }


def test_the_retune_sweep_is_a_table_of_each_points_answered_figures_in_threshold_order():
    """The 0.3 point, given second, is listed first with its own figures."""
    text = _report( retune=RETUNE )
    assert "## Retune sweep (report only)" in text and "Tune asks 75, final asks 25." in text
    row_low  = "| 0.3 | 3 | 70 | 93.3 | 42.9 | 40.0 | 20 | 80.0 | 60.0 | 48.0 | grid |"
    row_high = "| 0.5 | 5 | 50 | 66.7 | 60.0 | 41.0 | 20 | 80.0 | 60.0 | 48.0 | grid |"
    assert row_low in text and row_high in text and text.index( row_low ) < text.index( row_high )
    assert "Best on the tune window: threshold 0.5, top k 5." in text


def test_a_report_without_a_retune_result_has_no_sweep_section():
    """The section is optional, so an earlier caller's report is unchanged."""
    assert "Retune sweep" not in _report()


def test_three_points_are_listed_by_threshold_then_top_k_the_best_is_named_apart_and_the_input_is_left_alone():
    """Points 0.5/3, 0.3/8 and 0.4/5 sort by threshold, and the best is the middle one."""
    points = [ _point( 0.5, 3, tune_per_100=40.0 ), _point( 0.3, 8, tune_per_100=35.0 ), _point( 0.4, 5, tune_per_100=44.0 ) ]
    before = copy.deepcopy( points )
    text   = _report( retune=dict( RETUNE, points=points, best=points[ 2 ] ) )
    rows   = [ line for line in text.splitlines() if line.startswith( "| 0." ) ]
    assert [ row.split( "|" )[ 1 ].strip() for row in rows ] == [ "0.3", "0.4", "0.5" ]
    assert [ row.split( "|" )[ 2 ].strip() for row in rows ] == [ "8", "5", "3" ]
    assert "Best on the tune window: threshold 0.4, top k 5." in text
    assert points == before, "rendering must not reorder the caller's points"


def test_a_sweep_point_that_beats_the_best_is_labelled_report_only_and_the_best_line_stays_the_frozen_one():
    """A 0.3 sweep point above the frozen best is labelled report only, never named best."""
    sweep = [ _point( 0.3, 3, tune_per_100=60.0 ) ]
    text  = _report( retune=RETUNE, sweep_points=sweep )
    assert "| 0.3 | 3 | 50 | 66.7 | 60.0 | 60.0 | 20 | 80.0 | 60.0 | 48.0 | report only |" in text
    assert "| 0.5 | 5 | 50 | 66.7 | 60.0 | 41.0 | 20 | 80.0 | 60.0 | 48.0 | grid |" in text
    assert "Best on the tune window: threshold 0.5, top k 5." in text and "threshold 0.3, top k 3." not in text


def test_a_sweep_is_not_shown_without_a_retune_result():
    """The sweep is an addition to the retune table, so alone it renders nothing."""
    assert "Retune sweep" not in _report( sweep_points=[ _point( 0.3, 3 ) ] )


def test_a_sweep_point_between_two_grid_points_is_listed_between_them():
    """Grid points 0.3 and 0.5 with a 0.4 sweep point give the rows grid, report only, grid."""
    grid  = dict( RETUNE, points=[ _point( 0.5, 5 ), _point( 0.3, 3 ) ] )
    text  = _report( retune=grid, sweep_points=[ _point( 0.4, 8 ) ] )
    rows  = [ line for line in text.splitlines() if line.startswith( "| 0." ) ]
    assert [ ( row.split( "|" )[ 1 ].strip(), row.split( "|" )[ -2 ].strip() ) for row in rows ] == [ ( "0.3", "grid" ), ( "0.4", "report only" ), ( "0.5", "grid" ) ]


COVERAGE = { "cohort_asks": 3608, "replayable": 1302, "tune_mix": { "yes_no": 364, "multiple_choice": 547 }, "final_mix": { "yes_no": 215, "multiple_choice": 176 } }


def test_a_coverage_section_states_the_replayable_share_and_each_windows_answer_type_mix():
    """The section sits before the first type, and its table rows carry both windows' counts."""
    text = _report( coverage=COVERAGE )
    assert "Only 1302 of 3608 asks were replayable: 2306 had no stored vector (64%)." in text
    assert "| window | multiple_choice | yes_no | total |" in text
    assert "| tune | 547 | 364 | 911 |" in text and "| final | 176 | 215 | 391 |" in text
    assert text.index( "## Coverage" ) < text.index( "## yes_no" )


def test_a_window_with_no_asks_of_a_type_shows_zero_for_it():
    """A type missing from one window's mix reads 0, not a key error."""
    text = _report( coverage=dict( COVERAGE, final_mix={ "yes_no": 10 } ) )
    assert "| final | 0 | 10 | 10 |" in text


def test_a_report_without_coverage_has_no_coverage_section():
    assert "## Coverage" not in _report()


SCORES = { "tune": { "yes_no": { "asks": 364, "correct": 100 }, "multiple_choice": { "asks": 547, "correct": 187 } },
           "final": { "yes_no": { "asks": 215, "correct": 163 }, "multiple_choice": { "asks": 176, "correct": 14 } } }


def test_coverage_scores_give_each_types_correct_count_and_rate_in_each_window():
    """Each row reads its own window and type, so a swap of two cells changes a named row."""
    text = _report( coverage=dict( COVERAGE, scores=SCORES ) )
    assert "| tune | multiple_choice | 547 | 187 | 34.2 |" in text and "| tune | yes_no | 364 | 100 | 27.5 |" in text
    assert "| final | multiple_choice | 176 | 14 | 8.0 |" in text and "| final | yes_no | 215 | 163 | 75.8 |" in text
    assert text.index( "| window | type |" ) < text.index( "## yes_no" )


def test_a_type_with_no_asks_in_a_window_reads_na_in_the_score_table():
    """A type with zero asks reads n/a, not a divide error; the other rows keep their rates."""
    scores = dict( SCORES, final=dict( SCORES[ "final" ], multiple_choice={ "asks": 0, "correct": 0 } ) )
    text   = _report( coverage=dict( COVERAGE, final_mix={ "yes_no": 215, "multiple_choice": 0 }, scores=scores ) )
    assert "| final | multiple_choice | 0 | 0 | n/a |" in text
    assert "| final | yes_no | 215 | 163 | 75.8 |" in text


def test_coverage_without_scores_has_no_score_table():
    assert "| window | type |" not in _report( coverage=COVERAGE )


def test_the_score_table_is_set_off_from_the_mix_table_by_a_blank_line():
    """A table row directly above the lead-in line would run the two together in Markdown."""
    lines = _report( coverage=dict( COVERAGE, scores=SCORES ) ).splitlines()
    index = lines.index( "Predictor score by answer type, in each window:" )
    assert lines[ index - 1 ] == "" and lines[ index + 1 ] == ""


# ---- the answer-handling (second) checkpoint: four bound shas -------------------------------------------------

BOUND = { "gold_sha256": "a1" * 32, "judge_version": "judge-v1", "scorer_version": "scorer-v1" }


def _second( tmp_path, bindings=None, name="second.json" ):
    """Write a second checkpoint over the three-row cohort; returns its path."""
    path = str( tmp_path / name )
    cr.write_checkpoint( "report", ROWS, str( tmp_path / "c.jsonl" ), str( tmp_path / "m.json" ), path, "abc1234", frozen_at="2026-11-24T00:00:00+00:00",
                         bindings=BOUND if bindings is None else bindings )
    return path


def _records():
    return [ { "snapshot_sha256": sha256_of_rows( ROWS ) } ]


def test_the_second_checkpoint_holds_the_three_bound_values_beside_the_cohort_sha_and_the_first_kind_holds_none( tmp_path ):
    document = json.load( open( _second( tmp_path ) ) )
    assert document[ "bindings" ] == BOUND and document[ "cohort_sha256" ] == sha256_of_rows( ROWS )
    assert "bindings" not in json.load( open( _frozen( tmp_path ) ) )
    assert cr.checkpoint_name( _second( tmp_path, name="again.json" ) ) == cr.SECOND_NAME
    assert cr.checkpoint_name( _frozen( tmp_path ) ) == cr.FIRST_NAME != cr.SECOND_NAME


def test_all_four_shas_unchanged_is_allowed( tmp_path ):
    said = []
    assert cr.refuse_post_checkpoint_report( _records(), _second( tmp_path ), said.append, dict( BOUND ) ) == 0 and said == []


@pytest.mark.parametrize( "key", [ "gold_sha256", "judge_version", "scorer_version" ] )
def test_a_change_to_any_one_bound_value_is_refused_and_names_that_value_only( tmp_path, key ):
    said = []
    assert cr.refuse_post_checkpoint_report( _records(), _second( tmp_path ), said.append, { **BOUND, key: "changed" } ) == 3
    assert key in said[ 0 ] and "changed" in said[ 0 ] and sum( name in said[ 0 ] for name in cr.BOUND_KEYS ) == 1


def test_a_change_to_the_cohort_sha_is_refused_and_the_bound_values_are_not_blamed( tmp_path ):
    said = []
    assert cr.refuse_post_checkpoint_report( [ { "snapshot_sha256": "f" * 64 } ], _second( tmp_path ), said.append, dict( BOUND ) ) == 3
    assert "snapshot_sha256" in said[ 0 ] and not any( name in said[ 0 ] for name in cr.BOUND_KEYS )


def test_two_changes_are_both_named_in_the_one_refusal( tmp_path ):
    said = []
    assert cr.refuse_post_checkpoint_report( [ { "snapshot_sha256": "f" * 64 } ], _second( tmp_path ), said.append, { **BOUND, "judge_version": "x" } ) == 3
    assert "snapshot_sha256" in said[ 0 ] and "judge_version" in said[ 0 ] and len( said ) == 1


def test_a_second_checkpoint_refuses_a_report_that_brings_no_current_bound_values( tmp_path ):
    said = []
    assert cr.refuse_post_checkpoint_report( _records(), _second( tmp_path ), said.append ) == 3
    assert all( name in said[ 0 ] for name in cr.BOUND_KEYS )


@pytest.mark.parametrize( "unset", [ None, "" ] )
def test_an_unset_value_is_stored_as_null_and_matches_nothing_not_even_an_unset_one( tmp_path, unset ):
    path = _second( tmp_path, { **BOUND, "gold_sha256": unset } )
    assert json.load( open( path ) )[ "bindings" ][ "gold_sha256" ] is None
    for current in ( { **BOUND, "gold_sha256": unset }, BOUND, { **BOUND, "gold_sha256": "b" * 64 } ):
        said = []
        assert cr.refuse_post_checkpoint_report( _records(), path, said.append, current ) == 3 and "gold_sha256" in said[ 0 ]


def test_a_set_frozen_value_is_not_matched_by_an_unset_current_one( tmp_path ):
    said = []
    assert cr.refuse_post_checkpoint_report( _records(), _second( tmp_path ), said.append, { **BOUND, "scorer_version": None } ) == 3 and "scorer_version" in said[ 0 ]


def test_the_18_nov_kind_of_checkpoint_ignores_current_values_and_keeps_its_cohort_only_check( tmp_path ):
    path = _frozen( tmp_path )
    assert cr.refuse_post_checkpoint_report( _records(), path, lambda line: None ) == 0
    assert cr.refuse_post_checkpoint_report( _records(), path, lambda line: None, { "gold_sha256": "whatever" } ) == 0
    said = []
    assert cr.refuse_post_checkpoint_report( [ { "snapshot_sha256": "0" * 64 } ], path, said.append, dict( BOUND ) ) == 3
    assert said == [ f"REFUSED: the baseline arm's snapshot_sha256 ['{'0' * 64}'] is not the frozen cohort sha256 {sha256_of_rows( ROWS )}" ]


def test_writing_a_second_checkpoint_over_the_18_nov_file_is_refused_and_leaves_it_untouched( tmp_path ):
    path   = _frozen( tmp_path )
    before = open( path ).read()
    with pytest.raises( cr.CheckpointMismatch, match="never over it" ): _second( tmp_path, name="k.json" )
    assert open( path ).read() == before


def test_a_second_checkpoint_may_be_written_again_beside_itself_and_must_hold_exactly_the_bound_keys( tmp_path ):
    path = _second( tmp_path )
    assert _second( tmp_path, { **BOUND, "judge_version": "v2" } ) == path
    with pytest.raises( ValueError, match="exactly" ): _second( tmp_path, { "gold_sha256": "a" }, name="bad.json" )


def test_the_command_reads_the_current_values_from_a_file( tmp_path ):
    path    = _second( tmp_path )
    records = tmp_path / "r.json"
    records.write_text( json.dumps( _records() ) )
    current = tmp_path / "cur.json"
    current.write_text( json.dumps( BOUND ) )
    base = [ "--records", str( records ), "--checkpoint", path ]
    assert cr.main( base + [ "--current", str( current ) ], lambda line: None ) == 0
    current.write_text( json.dumps( { **BOUND, "judge_version": "x" } ) )
    assert cr.main( base + [ "--current", str( current ) ], lambda line: None ) == 3
    assert cr.main( base, lambda line: None ) == 3
