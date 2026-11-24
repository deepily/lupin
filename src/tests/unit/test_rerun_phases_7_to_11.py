"""
Tests for src/scripts/rerun_phases_7_to_11.py.

The records are small hand-built dicts in the shape the replay returns. The replay, the cohort read and the guards are doubles.
Each figure the script computes is checked against a count worked out by hand in the test.
"""

import json
import pickle
import runpy
import subprocess
import sys
import types

import pytest

import cosa.utils.util as cu

sys.path.insert( 0, cu.get_project_root() + "/src/scripts" )
import rerun_phases_7_to_11 as rrm   # noqa: E402

from cosa.research.preference_replay import replay_loop, three_way_report   # noqa: E402
from cosa.research.preference_replay import calibration_fit   # noqa: E402


def rec( ask_id, kind="yes_no", correct=True, forecast=None, confidence=0.7, strategy="cbr_majority_vote" ):
    """One replay record."""
    forecast = { "value": "yes" } if forecast is None else forecast
    return { "arm": "x", "row_index": 0, "frozen_index": 0, "body": "b", "snapshot_sha256": "s",
             "meta": { "notification_id": ask_id, "correct": correct, "response_type": kind, "forecast": forecast,
                       "confidence": confidence, "strategy": strategy } }


def run_of( **arms ):
    return { "records": arms, "not_replayable": 3, "unrebuildable_cases": 2, "families": 5 }


# ---------------------------------------------------------------- small helpers

def test_the_two_sha_helpers_are_a_plain_sha_of_bytes_and_of_sorted_ids_without_a_trailing_newline( tmp_path ):
    path = tmp_path / "f.txt"
    path.write_bytes( b"abc" )
    assert rrm.sha256_of( str( path ) ) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert rrm.sha256_of_ids( [ "b", "a" ] ) == rrm.sha256_of( str( _file( tmp_path, "ids.txt", b"a\nb" ) ) )
    assert rrm.sha256_of_ids( [ "a", "b" ] ) != rrm.sha256_of( str( _file( tmp_path, "ids2.txt", b"a\nb\n" ) ) )


def _file( folder, name, data ):
    path = folder / name
    path.write_bytes( data )
    return path


def test_read_ids_reads_bare_lines_and_json_lines_and_skips_blank_lines( tmp_path ):
    bare = _file( tmp_path, "bare.txt", b"a\n\nb\n" )
    rows = _file( tmp_path, "rows.jsonl", b'{"id": "c"}\n\n{"id": "d", "x": 1}\n' )
    assert rrm.read_ids( str( bare ) ) == [ "a", "b" ]
    assert rrm.read_ids( str( rows ) ) == [ "c", "d" ]


def test_columns_are_cut_to_the_replayable_ids_and_the_record_ids_outside_them_are_in_no_column():
    columns = rrm.columns_of( [ "a", "b", "z" ], [ "a", "c", "d" ], [ "a" ], [ "a", "b", "c" ] )
    assert columns == { "second": { "a", "c" }, "record": { "a", "b" }, "old_1302": { "a" } }


def test_the_scripts_tune_fraction_is_the_retunes_own_not_a_second_copy():
    from cosa.research.preference_replay import retune
    assert rrm.TUNE_FRACTION is retune.TUNE_FRACTION and rrm.TUNE_FRACTION == 0.7


def test_split_by_time_cuts_one_hundred_ids_at_seventy_and_agrees_with_the_retunes_own_split():
    from cosa.research.preference_replay import retune
    tune, final = rrm.split_by_time( [ str( i ) for i in range( 100 ) ] )
    assert ( len( tune ), len( final ) ) == ( 70, 30 ) and tune[ -1 ] == "69" and final[ 0 ] == "70"
    assert retune.split_windows( 100 ) == ( 70, 30 )
    assert [ len( part ) for part in rrm.split_by_time( [ str( i ) for i in range( 1302 ) ] ) ] == [ 911, 391 ]   # the freeze's own windows


def test_split_by_time_takes_the_first_floor_share_as_tune_and_the_rest_as_final_with_no_shared_id():
    tune, final = rrm.split_by_time( [ str( i ) for i in range( 10 ) ] )
    assert tune == [ "0", "1", "2", "3", "4", "5", "6" ] and final == [ "7", "8", "9" ]
    tune, final = rrm.split_by_time( [ "a", "b", "c" ] )
    assert tune == [ "a", "b" ] and final == [ "c" ]   # floor( 0.7 x 3 ) is 2


def test_the_sign_helpers_say_no_sign_when_either_difference_is_zero_and_a_reversal_only_when_the_signs_differ():
    assert [ rrm.sign_of( n ) for n in ( 5, 0, -2 ) ] == [ 1, 0, -1 ]
    assert rrm.reversal( 0, 4 ) == "no sign" and rrm.reversal( 4, 0 ) == "no sign"
    assert rrm.reversal( 10, 3 ) == "same sign" and rrm.reversal( -1, -9 ) == "same sign"
    assert rrm.reversal( 10, -1 ) == "sign reversed" and rrm.reversal( -3, 2 ) == "sign reversed"


def test_read_switches_reads_the_named_keys_skips_comments_and_lines_without_an_equals_and_gives_none_for_an_absent_key( tmp_path ):
    ini = _file( tmp_path, "x.ini", ( "# prediction engine full answer reply enabled = true\n"
                                     "not a setting line\n"
                                     "prediction engine per field multiple choice enabled         = true\n"
                                     "prediction engine calibration enabled=false\n" ).encode() )
    found = rrm.read_switches( str( ini ) )
    assert found[ "prediction engine per field multiple choice enabled" ] == "true"
    assert found[ "prediction engine calibration enabled" ] == "false"
    assert found[ "prediction engine full answer reply enabled" ] is None
    assert set( found ) == set( rrm.SWITCHES )


def test_code_sha_returns_the_trimmed_head_commit_or_the_word_unknown_when_git_fails( monkeypatch ):
    monkeypatch.setattr( subprocess, "run", lambda *a, **k: types.SimpleNamespace( returncode=0, stdout="abc123\n" ) )
    assert rrm.code_sha( "/x" ) == "abc123"
    monkeypatch.setattr( subprocess, "run", lambda *a, **k: types.SimpleNamespace( returncode=128, stdout="" ) )
    assert rrm.code_sha( "/x" ) == "unknown"


def test_write_json_writes_sorted_indented_json_and_returns_the_files_sha( tmp_path ):
    path = tmp_path / "o.json"
    sha  = rrm.write_json( str( path ), { "b": 1, "a": [ 2 ] } )
    assert json.loads( path.read_text() ) == { "a": [ 2 ], "b": 1 }
    assert path.read_text().index( '"a"' ) < path.read_text().index( '"b"' )
    assert sha == rrm.sha256_of( str( path ) )


# ---------------------------------------------------------------- replay_config

class _Engine:
    per_field_mc_enabled       = False
    failure_visibility_enabled = False

    def __init__( self ): self.seen = []

    def predict( self, notification, **kwargs ):
        self.seen.append( ( self.per_field_mc_enabled, self.failure_visibility_enabled ) )
        return types.SimpleNamespace( metadata={ "reason": notification[ "reason" ] } if "reason" in notification else {} )


def test_replay_config_sets_the_two_switches_records_each_reason_in_order_and_puts_everything_back( monkeypatch ):
    engine = _Engine()
    real_predict = engine.predict
    seen = {}

    def fake_replay( asks, eng, label, baselines=None, target_types=None ):
        seen.update( label=label, baselines=sorted( baselines ), types=target_types )
        eng.predict( { "reason": "no_similar_cases" } )
        eng.predict( {} )
        return "the-run"

    monkeypatch.setattr( replay_loop, "replay", fake_replay )
    done = rrm.replay_config( [ "ask" ], engine, True, True, { "three_way": object() }, "lbl" )
    assert done == { "run": "the-run", "reasons": [ "no_similar_cases", None ] }
    assert engine.seen == [ ( True, True ), ( True, True ) ]
    assert seen == { "label": "lbl", "baselines": [ "always_yes", "three_way" ], "types": ( "yes_no", "multiple_choice" ) }
    assert ( engine.per_field_mc_enabled, engine.failure_visibility_enabled ) == ( False, False )
    assert engine.predict == real_predict


def test_replay_config_restores_the_engine_even_when_the_replay_raises( monkeypatch ):
    engine = _Engine()
    monkeypatch.setattr( replay_loop, "replay", lambda *a, **k: ( _ for _ in () ).throw( RuntimeError( "boom" ) ) )
    with pytest.raises( RuntimeError, match="boom" ): rrm.replay_config( [], engine, True, True, {}, "x" )
    assert ( engine.per_field_mc_enabled, engine.failure_visibility_enabled ) == ( False, False )
    assert engine.predict.__func__ is _Engine.predict


# ---------------------------------------------------------------- control

def test_window_counts_counts_the_final_window_after_the_seventy_percent_cut_by_type():
    records = [ rec( f"t{i}", correct=False ) for i in range( 7 ) ]                       # tune: 7 of 10
    records += [ rec( "y1", "yes_no", True ), rec( "y2", "yes_no", False ), rec( "m1", "multiple_choice", True ) ]
    counts = rrm.window_counts( records )
    assert counts == { "tune": 7, "final": 3, "final_all": 2, "final_yes_no_asks": 2, "final_yes_no": 1, "final_mc_asks": 1, "final_mc": 1 }


def test_control_mismatches_names_each_figure_that_differs_and_is_empty_for_a_match():
    assert rrm.control_mismatches( dict( rrm.OLD_CONTROL ) ) == []
    wrong = dict( rrm.OLD_CONTROL, final_all=173, final_yes_no=159 )
    assert rrm.control_mismatches( wrong ) == [ ( "final_all", 173, 177 ), ( "final_yes_no", 159, 163 ) ]


def test_the_old_control_figures_are_the_ones_the_old_reports_state():
    assert rrm.OLD_CONTROL[ "final_all" ] == rrm.OLD_CONTROL[ "final_yes_no" ] + rrm.OLD_CONTROL[ "final_mc" ]
    assert rrm.OLD_CONTROL[ "tune" ] + rrm.OLD_CONTROL[ "final" ] == 1302
    assert rrm.OLD_CONTROL[ "final_yes_no_asks" ] + rrm.OLD_CONTROL[ "final_mc_asks" ] == rrm.OLD_CONTROL[ "final" ]


# ---------------------------------------------------------------- records into documents

def test_with_reasons_puts_each_reason_in_its_records_meta_and_leaves_the_input_alone():
    records = [ rec( "a" ), rec( "b" ) ]
    out = rrm.with_reasons( records, [ "no_similar_cases", None ] )
    assert [ r[ "meta" ][ "reason" ] for r in out ] == [ "no_similar_cases", None ]
    assert "reason" not in records[ 0 ][ "meta" ]
    with pytest.raises( ValueError ): rrm.with_reasons( records, [ "only one" ] )


def test_per_ask_document_keeps_the_header_adds_the_arm_and_one_list_of_asks_per_column():
    with_probs = rec( "a", forecast={ "value": "no", "probabilities": { "yes": 0.1, "no": 0.8, "neither": 0.1 } }, confidence=0.8 )
    abstained  = rec( "b", "multiple_choice", correct=False, forecast=None )
    abstained[ "meta" ][ "forecast" ] = None
    abstained[ "meta" ][ "confidence" ] = None
    doc = rrm.per_ask_document( "arm-x", { "second": [ with_probs ], "record": [ abstained ] }, { "code_sha": "s1" } )
    assert doc[ "code_sha" ] == "s1" and doc[ "arm" ] == "arm-x"
    first = doc[ "run" ][ "asks_by_column" ][ "second" ][ 0 ]
    assert first[ "probabilities" ] == { "yes": 0.1, "no": 0.8, "neither": 0.1 } and first[ "correct" ] is True and first[ "confidence" ] == 0.8
    second = doc[ "run" ][ "asks_by_column" ][ "record" ][ 0 ]
    assert second[ "forecast" ] is None and second[ "probabilities" ] is None and second[ "correct" ] is False and second[ "reason" ] is None


# ---------------------------------------------------------------- column cuts and pairs

def test_column_run_keeps_the_records_in_the_column_re_indexes_them_and_carries_the_counts_over():
    run = run_of( engine=[ rec( "a" ), rec( "b", "multiple_choice" ), rec( "c" ) ], other=[ rec( "a" ), rec( "b", "multiple_choice" ), rec( "c" ) ] )
    cut = rrm.column_run( run, { "a", "b" } )
    assert [ r[ "meta" ][ "notification_id" ] for r in cut[ "records" ][ "engine" ] ] == [ "a", "b" ]
    assert [ r[ "row_index" ] for r in cut[ "records" ][ "other" ] ] == [ 0, 1 ]
    assert ( cut[ "not_replayable" ], cut[ "unrebuildable_cases" ], cut[ "families" ] ) == ( 3, 2, 5 )
    only_mc = rrm.column_run( run, { "a", "b", "c" }, "multiple_choice" )
    assert [ r[ "meta" ][ "notification_id" ] for r in only_mc[ "records" ][ "engine" ] ] == [ "b" ]


def test_paired_wins_counts_the_asks_only_one_arm_got_right_and_refuses_unequal_lengths():
    run = { "records": { "a": [ rec( "1", correct=True ), rec( "2", correct=True ), rec( "3", correct=False ), rec( "4", correct=False ) ],
                         "b": [ rec( "1", correct=True ), rec( "2", correct=False ), rec( "3", correct=True ), rec( "4", correct=False ) ] } }
    assert rrm.paired_wins( run, "a", "b" ) == ( 1, 1 )
    assert rrm.paired_wins( run, "b", "a" ) == ( 1, 1 )
    run[ "records" ][ "b" ].pop()
    with pytest.raises( ValueError ): rrm.paired_wins( run, "a", "b" )


def test_of_type_and_final_records_keep_one_type_and_the_window_after_the_cut():
    records = [ rec( "1" ), rec( "2", "multiple_choice" ), rec( "3" ) ]
    assert [ r[ "meta" ][ "notification_id" ] for r in rrm.of_type( records, "yes_no" ) ] == [ "1", "3" ]
    ten = [ rec( str( i ) ) for i in range( 10 ) ]
    assert [ r[ "meta" ][ "notification_id" ] for r in rrm.final_records( ten ) ] == [ "7", "8", "9" ]


# ---------------------------------------------------------------- phases

def _mc_runs():
    ids   = [ str( i ) for i in range( 10 ) ]
    # the first 7 records are tune; the last 3 are final. multiple-choice asks sit at positions 1, 3, 7, 8.
    kinds = [ "yes_no", "multiple_choice", "yes_no", "multiple_choice", "yes_no", "yes_no", "yes_no", "multiple_choice", "multiple_choice", "yes_no" ]
    control   = [ True,  True,  False, False, True, True, True,  True,  False, True ]
    per_field = [ True,  False, False, True,  True, True, True,  False, False, True ]
    old = [ rec( i, k, c ) for i, k, c in zip( ids, kinds, control ) ]
    new = [ rec( i, k, c ) for i, k, c in zip( ids, kinds, per_field ) ]
    return run_of( engine=old ), run_of( engine=new ), set( ids )


def test_phase7_column_pairs_per_field_against_the_control_on_multiple_choice_whole_and_in_the_final_window():
    old, new, ids = _mc_runs()
    out = rrm.phase7_column( old, new, ids )
    # multiple-choice asks 1, 3, 7, 8: control right on 1 and 7; per-field right on 3 only
    assert out[ "column" ] == { "asks": 4, "control_correct": 2, "per_field_correct": 1, "only_per_field_right": 1, "only_control_right": 2, "difference": -1 }
    # final window is records 7 to 9: multiple choice 7 and 8; control right on 7, per-field on neither
    assert out[ "final" ] == { "asks": 2, "control_correct": 1, "per_field_correct": 0, "only_per_field_right": 0, "only_control_right": 1, "difference": -1 }
    assert out[ "old_difference" ] == 0 and out[ "sign_test" ] == "no sign"


def test_phase8_column_reports_the_final_yes_no_window_and_both_paired_comparisons_with_their_sign_tests( monkeypatch ):
    ids   = [ str( i ) for i in range( 10 ) ]
    kinds = [ "yes_no" ] * 10
    margin = [ rec( i, "yes_no", c ) for i, c in zip( ids, [ True ] * 7 + [ False, False, True ] ) ]
    yes    = [ rec( i, "yes_no", c ) for i, c in zip( ids, [ True ] * 7 + [ True, False, False ] ) ]
    three  = [ rec( i, "yes_no", c ) for i, c in zip( ids, [ True ] * 7 + [ True, True, False ] ) ]
    run    = run_of( engine=margin, always_yes=yes, three_way=three )
    captured = {}

    def fake_build( final, asks, floor ):
        captured.update( final=final, asks=asks, floor=floor )
        return { "verdict_text": "stub" }

    monkeypatch.setattr( three_way_report, "build_report", fake_build )
    out = rrm.phase8_column( run, set( ids ), { i: { "id": i } for i in ids } )
    # final window is records 7, 8, 9: margin right on 9 only, always-yes on 7, three-way on 7 and 8
    assert out[ "final_correct" ] == { "engine": 1, "always_yes": 1, "three_way": 2 }
    assert out[ "asks" ] == 10 and out[ "final_asks" ] == 3 and out[ "report" ] == { "verdict_text": "stub" }
    assert out[ "three_way_against_always_yes" ] == { "only_three_way": 1, "only_always_yes": 0, "difference": 1, "sign_test": "no sign" }
    assert out[ "three_way_against_margin_rule" ] == { "only_three_way": 2, "only_margin_rule": 1, "difference": 1, "sign_test": "same sign" }
    assert captured[ "asks" ] == [ { "id": "7" }, { "id": "8" }, { "id": "9" } ] and captured[ "floor" ] == rrm.OPERATIONAL_FLOOR
    assert [ r[ "meta" ][ "notification_id" ] for r in captured[ "final" ][ "records" ][ "engine" ] ] == [ "7", "8", "9" ]


def test_phase9_column_fits_on_the_tune_rows_only_scores_the_final_rows_and_drops_rows_with_no_forecast( monkeypatch ):
    records = [ rec( str( i ), "yes_no", i % 2 == 0, confidence=0.5 + i / 100 ) for i in range( 10 ) ]
    records[ 0 ] = rec( "0", forecast=None, strategy="cold_start" )         # no forecast: dropped from the rows
    records[ 0 ][ "meta" ][ "forecast" ] = None
    records[ 1 ] = rec( "1", strategy=None )                                # no strategy: dropped
    records[ 2 ] = rec( "2", confidence=None )                              # no confidence: dropped
    seen = {}

    def fake_fit( tune_rows, final_rows, cohort_sha, fit_time ):
        seen.update( tune=tune_rows, final=final_rows, sha=cohort_sha, time=fit_time )
        return { "cells": { "yes_no|cbr_majority_vote": {} } }, { "cells": { "yes_no|cbr_majority_vote": { "status": "evaluated" } } }

    monkeypatch.setattr( calibration_fit, "fit_and_evaluate", fake_fit )
    out = rrm.phase9_column( run_of( engine=records ), { str( i ) for i in range( 10 ) }, "2026-11-24T00:00:00+00:00", "second" )
    assert out[ "tune_ids" ] == [ "0", "1", "2", "3", "4", "5", "6" ] and out[ "final_ids" ] == [ "7", "8", "9" ]
    assert out[ "tune_size" ] == 7 and out[ "final_size" ] == 3 and out[ "shared_ids" ] == 0 and out[ "column" ] == "second"
    assert out[ "tune_ids_sha256" ] == rrm.sha256_of_ids( out[ "tune_ids" ] ) and seen[ "sha" ] == out[ "tune_ids_sha256" ]
    assert [ row[ 2 ] for row in seen[ "tune" ] ] == [ 0.53, 0.54, 0.55, 0.56 ]
    assert [ row[ 3 ] for row in seen[ "tune" ] ] == [ False, True, False, True ]
    assert len( seen[ "final" ] ) == 3 and seen[ "time" ] == "2026-11-24T00:00:00+00:00"
    assert out[ "fitted_cells" ] == [ "yes_no|cbr_majority_vote" ] and out[ "report" ][ "cells" ][ "yes_no|cbr_majority_vote" ][ "status" ] == "evaluated"


def test_phase11_column_counts_each_reason_for_the_column_and_says_whether_the_two_settings_agree_ask_for_ask():
    run     = run_of( engine=[ rec( "a" ), rec( "b" ), rec( "c" ) ] )
    plain   = [ None, "no_similar_cases", "no_similar_cases" ]
    named   = [ None, "no_similar_cases", "no_similar_cases" ]
    out = rrm.phase11_column( run, run, plain, named, { "a", "b" } )
    assert out == { "reasons_off": { "None": 1, "no_similar_cases": 1 }, "reasons_on": { "None": 1, "no_similar_cases": 1 }, "identical_per_ask": True }
    out = rrm.phase11_column( run, run, plain, [ None, "no_similar_cases", "store_error: X" ], { "c" } )
    assert out[ "identical_per_ask" ] is False and out[ "reasons_on" ] == { "store_error: X": 1 }


# ---------------------------------------------------------------- main

class _MainEngine:
    similarity_threshold = 0.75
    cbr_top_k            = 5
    retrieval_metric     = "dot"
    recency_half_life_days = 14
    yes_no_no_margin     = 1.35
    confidence_threshold = 0.6
    three_way_enabled    = False
    lookup_neither_forecast_enabled = False
    calibration_enabled  = False
    raises               = True

    @classmethod
    def reset( cls ): pass

    def __init__( self, debug=False ): pass

    def _get_llm_client( self ):
        if self.raises: raise AssertionError( "MODEL CALL ATTEMPTED: double" )


def _stub_run():
    ids = [ f"a{i}" for i in range( 10 ) ]
    kinds = [ "yes_no", "multiple_choice" ] * 5
    engine = [ rec( i, k, True ) for i, k in zip( ids, kinds ) ]
    return { "records": { "engine": engine, "always_yes": engine, "three_way": engine }, "not_replayable": 0, "unrebuildable_cases": 0, "families": 0 }


def _wire( monkeypatch, tmp_path, attempts=0, control_wrong=False, engine_raises=True, calls_log=None ):
    folder = tmp_path / "in"
    folder.mkdir( exist_ok=True )
    record = _file( folder, "records.jsonl", b'{"id": "a0"}\n{"id": "a1"}\n{"id": "zz"}\n' )
    cohort = _file( folder, "cohort.jsonl", b'{"id": "a0"}\n{"id": "a1"}\n{"id": "a2"}\n' )
    old    = _file( folder, "old.txt", b"a0\na1\n" )
    vectors = _file( folder, "vectors.jsonl", b"{}" )
    asks   = [ { "id": f"a{i}", "question_embedding": [ 0.1 ] } for i in range( 4 ) ] + [ { "id": "novec", "question_embedding": None } ]
    _MainEngine.raises = engine_raises
    log = [] if calls_log is None else calls_log

    def fake_install( calls ):
        if attempts: calls[ "fake.model" ] += attempts

    def fake_replay_config( pool, engine, per_field, failure_visibility, extra, label ):
        log.append( ( len( pool ), label ) )
        return { "run": _stub_run(), "reasons": [ None ] * 10 }

    class _Session:
        def __enter__( self ): return self
        def __exit__( self, *error ): return False

    monkeypatch.setattr( rrm.zmp, "install_guards", fake_install )
    monkeypatch.setattr( "cosa.agents.prediction_engine.prediction_engine.PredictionEngine", _MainEngine )
    monkeypatch.setattr( "cosa.research.preference_replay.question_vectors.load_side_file", lambda path: ( { "model": "m" }, {} ) )
    monkeypatch.setattr( "cosa.research.preference_replay.retune_run.read_cohort", lambda session, vectors: ( asks, { "database": "scratch_db" } ) )
    monkeypatch.setattr( "cosa.rest.db.database.get_db", lambda: _Session() )
    monkeypatch.setattr( three_way_report, "make_three_way_arm", lambda half_life: ( lambda ask, rows: None ) )
    monkeypatch.setattr( three_way_report, "build_report", lambda final, asks, floor: { "verdict_text": "stub" } )
    monkeypatch.setattr( calibration_fit, "fit_and_evaluate", lambda tune, final, sha, time: ( { "cells": {} }, { "cells": {} } ) )
    monkeypatch.setattr( rrm, "replay_config", fake_replay_config )
    monkeypatch.setattr( rrm, "control_mismatches", lambda counts: [ ( "final_all", 1, 2 ) ] if control_wrong else [] )
    monkeypatch.setattr( rrm, "read_switches", lambda path: { "a switch": "on" } )
    monkeypatch.setattr( rrm, "code_sha", lambda root: "deadbeef" )
    argv = [ "--vectors", str( vectors ), "--records", str( record ), "--out-dir", str( tmp_path / "out" ), "--cohort", str( cohort ), "--old-ids", str( old ) ]
    return argv, log


def test_main_writes_eight_per_ask_files_and_a_report_stamped_with_the_cohorts_and_returns_zero( monkeypatch, tmp_path, capsys ):
    argv, log = _wire( monkeypatch, tmp_path )
    assert rrm.main( argv ) == 0
    out = capsys.readouterr().out
    assert "control" in out and "model-call attempts: 0" in out and "positive control fired" in out
    assert "replayed {'second': 3, 'record': 2, 'old_1302': 2} record ids outside every column 1" in out
    report = json.loads( ( tmp_path / "out" / "prediction-rerun-phases-7-to-11-report.json" ).read_text() )
    files = sorted( p.name for p in ( tmp_path / "out" ).iterdir() )
    assert len( files ) == 9 and len( report[ "per_ask_files" ] ) == 8
    assert report[ "stamps" ][ "columns" ][ "record" ][ "count" ] == 2 and report[ "stamps" ][ "record_ids_outside_every_column" ] == 1
    assert report[ "stamps" ][ "code_sha" ] == "deadbeef" and report[ "stamps" ][ "frozen" ] == { "metric": "cosine", "threshold": 0.5, "top_k": 10 }
    assert report[ "stamps" ][ "checkpoint_cohort_sha256" ] == rrm.sha256_of( argv[ argv.index( "--cohort" ) + 1 ] )
    assert report[ "model_call_attempts" ] == 0 and report[ "phase10" ].startswith( "not run" )
    assert set( report[ "phase7" ] ) == set( report[ "phase8" ] ) == set( report[ "phase9" ] ) == set( report[ "phase11" ] ) == { "second", "record", "old_1302" }
    assert report[ "phase11" ][ "second" ][ "label" ].startswith( "identical by construction" )
    assert log[ 0 ] == ( 2, "control" ) and len( log ) == 1 + 3 * 3   # the control, then three configurations for each of three columns
    asked = json.loads( ( tmp_path / "out" / "prediction-rerun-phase8-three-way-per-ask.json" ).read_text() )
    assert set( asked[ "run" ][ "asks_by_column" ] ) == { "second", "record", "old_1302" } and asked[ "arm" ] == "phase8-three-way"
    reasons = json.loads( ( tmp_path / "out" / "prediction-rerun-phase11-failure-visibility-on-per-ask.json" ).read_text() )
    assert "reason" in reasons[ "run" ][ "asks_by_column" ][ "second" ][ 0 ]


def test_main_stops_before_writing_anything_when_the_control_does_not_reproduce( monkeypatch, tmp_path, capsys ):
    argv, log = _wire( monkeypatch, tmp_path, control_wrong=True )
    assert rrm.main( argv ) == 2
    assert "CONTROL MISMATCH, nothing written" in capsys.readouterr().out
    assert not ( tmp_path / "out" ).exists() and len( log ) == 1


def test_main_returns_one_when_a_model_call_was_attempted_after_writing_the_report( monkeypatch, tmp_path, capsys ):
    argv, _ = _wire( monkeypatch, tmp_path, attempts=2 )
    assert rrm.main( argv ) == 1
    report = json.loads( ( tmp_path / "out" / "prediction-rerun-phases-7-to-11-report.json" ).read_text() )
    assert report[ "model_call_attempts" ] == 2 and "model-call attempts: {'fake.model': 2}" in capsys.readouterr().out


def test_main_returns_one_when_the_positive_control_did_not_fire( monkeypatch, tmp_path, capsys ):
    argv, _ = _wire( monkeypatch, tmp_path, engine_raises=False )
    assert rrm.main( argv ) == 1
    assert "positive control fired" not in capsys.readouterr().out


def test_main_writes_the_replay_cache_and_a_second_run_reads_it_instead_of_replaying( monkeypatch, tmp_path ):
    argv, log = _wire( monkeypatch, tmp_path )
    cache = str( tmp_path / "runs.pkl" )
    assert rrm.main( argv + [ "--cache", cache ] ) == 0
    assert len( log ) == 10
    with open( cache, "rb" ) as handle: cached = pickle.load( handle )
    assert set( cached ) == { "second", "record", "old_1302" } and set( cached[ "second" ] ) == { "old", "new", "vis" }
    assert rrm.main( argv + [ "--cache", cache ] ) == 0
    assert len( log ) == 11   # only the control ran again


def test_main_uses_the_committed_default_cohort_and_old_id_files_when_they_are_not_given( monkeypatch, tmp_path ):
    argv, _ = _wire( monkeypatch, tmp_path )
    seen = []
    monkeypatch.setattr( rrm, "read_ids", lambda path: seen.append( path ) or [ "a0" ] )
    keep = [ a for i, a in enumerate( argv ) if a not in ( "--cohort", "--old-ids" ) and ( i < 1 or argv[ i - 1 ] not in ( "--cohort", "--old-ids" ) ) ]
    assert rrm.main( keep ) == 0
    root = cu.get_project_root()
    assert root + "/src/conf/prediction-checkpoint-cohort.jsonl" in seen and root + "/src/conf/prediction-before-replayable-ids.txt" in seen


def test_run_as_a_script_exits_with_the_argument_parsers_code_when_required_arguments_are_missing( monkeypatch ):
    monkeypatch.setattr( sys, "argv", [ "rerun_phases_7_to_11.py" ] )
    with pytest.raises( SystemExit ) as raised: runpy.run_path( rrm.__file__, run_name="__main__" )
    assert raised.value.code == 2
