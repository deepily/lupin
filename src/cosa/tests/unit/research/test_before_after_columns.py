"""
The column runner replays one setting and writes one before-and-after column.

The asks are the retune tests' synthetic ones and the engine is the real one. The database is a fake.
"""

import contextlib
import json

import pytest

import cosa.research.preference_replay.before_after_columns as columns
from cosa.research.preference_replay.before_after_columns import build_column, main
from cosa.research.preference_replay.before_after_report import COLUMN_KEYS
from cosa.research.preference_replay.replay_loop import replay
from cosa.research.preference_replay.retune import ELIGIBLE_TYPES
from cosa.tests.unit.research.test_retune import SHA, _asks, _ask, _vector, engine  # noqa: F401 - engine is a fixture
from cosa.tests.unit.research.test_retune_run import FakeSession, _fake_cohort, _side_file

HEADER = { "label": "L", "commit": "c" * 40, "vector_source": "stored", "threshold": 0.5, "top_k": 10, "cohort_asks": 10, "produced_by": "p" }


def _run( engine, asks=None ):
    engine.retrieval_metric, engine.similarity_threshold, engine.cbr_top_k = "cosine", 0.5, 10
    return replay( asks if asks is not None else _asks( engine ), engine, SHA, target_types=ELIGIBLE_TYPES )


def test_a_column_holds_every_key_and_cuts_the_run_into_windows_by_position( engine ):
    run    = _run( engine )
    column = build_column( run, HEADER, fit_time="2026-11-19T00:00:00+00:00" )
    records = run[ "records" ][ "engine" ] if "engine" in run[ "records" ] else next( iter( run[ "records" ].values() ) )
    assert all( key in column for key in COLUMN_KEYS ) and "cohort_asks" not in column
    assert column[ "ask_count" ] == len( records ) == len( column[ "ask_ids" ] )
    tune_n = int( len( records ) * 0.7 )
    assert column[ "final_ids" ] == column[ "ask_ids" ][ tune_n: ]
    coverage = column[ "coverage" ]
    assert sum( coverage[ "tune_mix" ].values() ) == tune_n and sum( coverage[ "final_mix" ].values() ) == len( records ) - tune_n
    assert set( coverage[ "scores" ][ "final" ] ) == set( ELIGIBLE_TYPES ) and "tune_note" not in column
    assert column[ "yes_no_summary" ][ "baseline" ] == "always_yes" and set( column[ "calibration" ][ "cells" ] )


def test_the_windows_hold_seven_tune_asks_and_three_final_asks_with_their_own_scores_and_calibration( engine ):
    column = build_column( _run( engine ), HEADER )
    assert column[ "coverage" ][ "scores" ][ "tune" ][ "yes_no" ] == { "asks": 7, "correct": 6 }
    assert column[ "coverage" ][ "scores" ][ "final" ][ "yes_no" ] == { "asks": 3, "correct": 3 }
    assert column[ "calibration" ][ "tune_size" ] == 7 and column[ "calibration" ][ "final_size" ] == 3
    assert column[ "yes_no_summary" ][ "asks_replayed" ] == 3


def test_rescoring_scores_the_named_asks_from_anywhere_in_the_run_and_fits_without_them( engine ):
    run     = _run( engine )
    base    = build_column( run, HEADER )
    column  = build_column( run, HEADER, rescore_ids=[ "t0", "t4" ] )
    assert sorted( column[ "final_ids" ] ) == [ "t0", "t4" ] and column[ "ask_ids" ] == base[ "ask_ids" ]
    assert column[ "coverage" ][ "tune_mix" ] == {} and column[ "coverage" ][ "final_mix" ] == { "yes_no": 2 }
    assert column[ "coverage" ][ "scores" ][ "final" ][ "yes_no" ] == { "asks": 2, "correct": 2 }
    assert column[ "tune_note" ].startswith( "n/a" ) and column[ "yes_no_summary" ][ "asks_replayed" ] == 2
    assert column[ "calibration" ][ "final_size" ] == 2 and column[ "calibration" ][ "tune_size" ] == 6


def _go( engine, monkeypatch, tmp_path, extra, asks=None, name="col.json", setting=( "0.5", "10" ) ):
    _fake_cohort( monkeypatch, { "yes_no": asks if asks is not None else _asks( engine ), "multiple_choice": [] } )
    out, lines = tmp_path / name, []
    main( [ "--out", str( out ), "--label", "Col", "--threshold", setting[ 0 ], "--top-k", setting[ 1 ] ] + extra, printer=lines.append,
          session_factory=lambda: contextlib.nullcontext( FakeSession() ), engine_factory=lambda: engine, code_sha="d" * 40 )
    return json.loads( out.read_text( encoding="utf-8" ) ), lines, out


def test_the_command_on_stored_vectors_writes_a_column_naming_its_commit_and_command( engine, monkeypatch, tmp_path ):
    column, lines, _ = _go( engine, monkeypatch, tmp_path, [ "--stored-vectors" ] )
    assert column[ "commit" ] == "d" * 40 and column[ "vector_source" ].startswith( "stored vectors" )
    assert "--stored-vectors" in column[ "produced_by" ] and "side file" not in column[ "produced_by" ] and "ddddddddd" in column[ "produced_by" ]
    assert lines == [ f"Col: {column[ 'ask_count' ]} replayed, final correct {sum( s[ 'correct' ] for s in column[ 'coverage' ][ 'scores' ][ 'final' ].values() )}" ]


def test_the_command_on_a_side_file_names_the_model_revision_and_file_hash( engine, monkeypatch, tmp_path ):
    side   = _side_file( tmp_path )
    asks   = [ dict( ask, question_embedding=_vector( [ 1.0 ] ) ) for ask in _asks( engine ) ]
    column, _, _ = _go( engine, monkeypatch, tmp_path, [ "--vectors", side ], asks )
    assert column[ "vector_source" ] == { "model": "m", "revision": "r1" } and "side file sha256 " in column[ "produced_by" ]


def test_only_ids_cuts_the_cohort( engine, monkeypatch, tmp_path ):
    base, _, _ = _go( engine, monkeypatch, tmp_path, [ "--stored-vectors" ] )
    ids = tmp_path / "ids.txt"
    ids.write_text( "".join( ask_id + "\n" for ask_id in base[ "ask_ids" ][ :8 ] ), encoding="utf-8" )
    cut, _, _ = _go( engine, monkeypatch, tmp_path, [ "--stored-vectors", "--only-ids", str( ids ) ], name="cut.json" )
    assert cut[ "ask_count" ] == 8


def _rescore_args( tmp_path, final_ids ):
    source = tmp_path / "before.json"
    source.write_text( json.dumps( { "final_ids": final_ids } ), encoding="utf-8" )
    return [ "--stored-vectors", "--rescore-from", str( source ), "--rescored-out", str( tmp_path / "rescored.json" ), "--rescored-label", "Four" ]


def test_rescoring_writes_both_columns_from_one_replay_and_reads_the_ids_after_the_replay( engine, monkeypatch, tmp_path ):
    base, _, _ = _go( engine, monkeypatch, tmp_path, [ "--stored-vectors" ] )
    own, lines, _ = _go( engine, monkeypatch, tmp_path, _rescore_args( tmp_path, base[ "final_ids" ][ :2 ] ), name="own.json" )
    rescored = json.loads( ( tmp_path / "rescored.json" ).read_text( encoding="utf-8" ) )
    assert own[ "label" ] == "Col" and "tune_note" not in own and own[ "ask_ids" ] == base[ "ask_ids" ]
    assert rescored[ "label" ] == "Four" and rescored[ "final_ids" ] == base[ "final_ids" ][ :2 ] and rescored[ "tune_note" ]
    assert rescored[ "ask_ids" ] == own[ "ask_ids" ] and lines[ 1 ].startswith( "Four: scored on 2 asks" )
    text = ( tmp_path / "rescored.json" ).read_text( encoding="utf-8" )
    assert text == json.dumps( rescored, indent=1, sort_keys=True ) + "\n" and text.startswith( '{\n "ask_count": ' )
    assert [ p.name for p in tmp_path.iterdir() if p.name.endswith( ".tmp" ) ] == []


def test_a_rescore_id_that_is_not_in_the_run_is_refused_after_the_plain_column_is_written( engine, monkeypatch, tmp_path ):
    with pytest.raises( ValueError, match=r"1 ids of .* are not in this run, first: \['nowhere'\]" ):
        _go( engine, monkeypatch, tmp_path, _rescore_args( tmp_path, [ "nowhere" ] ) )
    assert ( tmp_path / "col.json" ).exists() and not ( tmp_path / "rescored.json" ).exists()


@pytest.mark.parametrize( "given", [ [ "--rescored-label", "x" ], [ "--rescore-from", "a", "--rescored-out", "b" ] ] )
def test_the_three_rescore_options_go_together( tmp_path, given, capsys ):
    with pytest.raises( SystemExit ) as raised:
        main( [ "--out", str( tmp_path / "c.json" ), "--label", "L", "--threshold", "0.5", "--top-k", "10", "--stored-vectors" ] + given )
    assert raised.value.code == 2 and "go together" in capsys.readouterr().err


def test_the_scores_and_mix_count_every_eligible_type_even_when_a_type_has_no_records():
    records = [ { "meta": { "response_type": "yes_no", "correct": True } }, { "meta": { "response_type": "yes_no", "correct": False } } ]
    assert columns._scores( records ) == { "yes_no": { "asks": 2, "correct": 1 }, "multiple_choice": { "asks": 0, "correct": 0 } }
    assert columns._mix( records ) == { "yes_no": 2 }
    assert columns._rows( [ { "meta": { "response_type": "yes_no", "strategy": "s", "confidence": None, "correct": True } } ] ) == []


def test_the_command_sets_the_engine_to_the_threshold_and_top_k_it_was_given( engine, monkeypatch, tmp_path ):
    column, _, _ = _go( engine, monkeypatch, tmp_path, [ "--stored-vectors" ], setting=( "0.7", "3" ) )
    assert ( engine.retrieval_metric, engine.similarity_threshold, engine.cbr_top_k ) == ( "cosine", 0.7, 3 )
    assert column[ "threshold" ] == 0.7 and column[ "top_k" ] == 3


def test_a_correct_forecast_reads_as_true_and_a_wrong_one_as_false_in_the_calibration_rows():
    meta = { "response_type": "yes_no", "strategy": "s", "confidence": 0.7 }
    assert columns._rows( [ { "meta": dict( meta, correct=True ) }, { "meta": dict( meta, correct=False ) } ] ) == [ ( "yes_no", "s", 0.7, True ), ( "yes_no", "s", 0.7, False ) ]


def test_the_column_file_holds_one_space_indented_sorted_json_with_a_closing_newline_and_no_temporary_file( engine, monkeypatch, tmp_path ):
    """
    The column file's bytes are the shape the committed column files have.

    The text is the indent-1, sorted-key dump of the column and one newline, and the folder holds no leftover temporary file.
    """
    column, _, out = _go( engine, monkeypatch, tmp_path, [ "--stored-vectors" ] )
    text = out.read_text( encoding="utf-8" )
    assert text == json.dumps( column, indent=1, sort_keys=True ) + "\n" and text.startswith( '{\n "ask_count": ' )
    assert [ p.name for p in tmp_path.iterdir() ] == [ "col.json" ]
