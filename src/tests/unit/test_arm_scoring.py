#!/usr/bin/env python3
"""
The per-ask scorer of one arm, driven with a fake replay and a fake cohort.

The fake replay records the engine settings it ran under, so a test can name the settings in force.
Nothing reaches a database, a model server or a real engine.
"""

import hashlib
import json
from datetime import datetime, timezone
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import cosa.research.preference_replay.arm_scoring as scoring
from cosa.research.preference_replay.replay_loop import ENGINE_ARM
from cosa.research.preference_replay.retune import FROZEN_METRIC, METRIC_KEY, THRESHOLD_KEY, TOP_K_KEY


def _record( index, correct ):
    """
    Build one replay record.

    Requires:
        - index is an int and correct a bool

    Ensures:
        - returns a record with the fields the scorer re-indexes and the report reads
    """
    return { "arm": ENGINE_ARM, "row_index": index, "meta": { "notification_id": f"n{index}", "correct": correct, "response_type": "yes_no" if index % 2 else "multiple_choice",
                                                                        "forecast": { "value": index }, "confidence": index / 10 } }


def _run( count ):
    """
    Build a fake replay run of count asks, the engine right on the even ones.

    Requires:
        - count is a positive int

    Ensures:
        - returns the dict replay returns, with the engine and always_yes arms of equal length
    """
    return { "records": { ENGINE_ARM: [ _record( i, i % 2 == 0 ) for i in range( count ) ],
                          "always_yes": [ _record( i, i % 4 < 2 ) for i in range( count ) ] },
             "not_replayable": 2, "unrebuildable_cases": 3, "families": 4 }


def _report( tmp_path, metric=FROZEN_METRIC ):
    """
    Write a retune report holding frozen settings.

    Requires:
        - tmp_path is a directory path

    Ensures:
        - returns the path of a report whose settings are 0.55, top k 8 and the given metric
    """
    path = tmp_path / "report.json"
    path.write_text( json.dumps( { "frozen_settings": { THRESHOLD_KEY: 0.55, TOP_K_KEY: 8, METRIC_KEY: metric } } ) )
    return str( path )


def _engine():
    """
    Build an engine stand-in with the three settings the scorer sets.

    Ensures:
        - returns a namespace holding threshold 0.5, top k 5 and metric dot
    """
    return SimpleNamespace( similarity_threshold=0.5, cbr_top_k=5, retrieval_metric="dot" )


def test_load_frozen_reads_the_three_settings( tmp_path ):
    """Settings come out under the names the engine takes."""
    assert scoring.load_frozen( _report( tmp_path ) ) == { "threshold": 0.55, "top_k": 8, "metric": "cosine" }


def test_load_frozen_refuses_another_metric( tmp_path ):
    """A report that froze a different metric is refused, naming the metric."""
    with pytest.raises( ValueError, match="dot" ): scoring.load_frozen( _report( tmp_path, metric="dot" ) )


def test_final_window_keeps_the_last_thirty_percent_of_every_arm_reindexed():
    """Ten asks are cut to the last three in both arms, re-indexed."""
    cut = scoring.final_window( _run( 10 ) )
    engine = cut[ "records" ][ ENGINE_ARM ]
    assert [ r[ "meta" ][ "notification_id" ] for r in engine ] == [ "n7", "n8", "n9" ]
    assert [ r[ "row_index" ] for r in engine ] == [ 0, 1, 2 ]
    assert [ r[ "meta" ][ "notification_id" ] for r in cut[ "records" ][ "always_yes" ] ] == [ "n7", "n8", "n9" ]
    assert ( cut[ "not_replayable" ], cut[ "unrebuildable_cases" ], cut[ "families" ] ) == ( 2, 3, 4 )


def test_final_window_floors_the_tune_size_so_eleven_asks_leave_four():
    """Eleven asks give a tune window of seven and a final window of four, not three."""
    cut = scoring.final_window( _run( 11 ) )
    assert [ r[ "meta" ][ "notification_id" ] for r in cut[ "records" ][ ENGINE_ARM ] ] == [ "n7", "n8", "n9", "n10" ]


def test_compact_keeps_the_six_fields_per_ask_and_the_counts():
    """Each ask keeps six fields, and the always-yes flag comes from the baseline arm."""
    compacted = scoring.compact( scoring.final_window( _run( 10 ) ) )
    assert compacted[ "asks" ][ 0 ] == { "id": "n7", "response_type": "yes_no", "forecast": { "value": 7 }, "confidence": 0.7,
                                         "correct": False, "always_yes_correct": False }
    assert compacted[ "asks" ][ 1 ] == { "id": "n8", "response_type": "multiple_choice", "forecast": { "value": 8 }, "confidence": 0.8,
                                         "correct": True, "always_yes_correct": True }
    assert compacted[ "asks" ][ 2 ][ "always_yes_correct" ] is True
    assert ( compacted[ "not_replayable" ], compacted[ "unrebuildable_cases" ], compacted[ "families" ] ) == ( 2, 3, 4 )


def test_compact_takes_each_id_from_the_engine_record():
    """The id comes from the engine arm even when the baseline record carries another."""
    cut = scoring.final_window( _run( 10 ) )
    for record in cut[ "records" ][ "always_yes" ]: record[ "meta" ][ "notification_id" ] = "other"
    assert [ a[ "id" ] for a in scoring.compact( cut )[ "asks" ] ] == [ "n7", "n8", "n9" ]


def test_expand_gives_back_the_figures_compact_kept():
    """Expanding a compact run restores the ids, types and flags of both arms."""
    cut = scoring.final_window( _run( 10 ) )
    back = scoring.expand( scoring.compact( cut ) )
    for arm in ( ENGINE_ARM, "always_yes" ):
        assert [ ( r[ "meta" ][ "notification_id" ], r[ "meta" ][ "response_type" ], r[ "meta" ][ "correct" ] ) for r in back[ "records" ][ arm ] ] == \
               [ ( r[ "meta" ][ "notification_id" ], r[ "meta" ][ "response_type" ], r[ "meta" ][ "correct" ] ) for r in cut[ "records" ][ arm ] ]
    assert [ r[ "row_index" ] for r in back[ "records" ][ "always_yes" ] ] == [ 0, 1, 2 ]
    assert [ r[ "row_index" ] for r in back[ "records" ][ ENGINE_ARM ] ] == [ 0, 1, 2 ]
    assert back[ "records" ][ ENGINE_ARM ][ 1 ][ "meta" ][ "forecast" ] == { "value": 8 } and back[ "records" ][ ENGINE_ARM ][ 1 ][ "meta" ][ "confidence" ] == 0.8
    assert ( back[ "not_replayable" ], back[ "unrebuildable_cases" ], back[ "families" ] ) == ( 2, 3, 4 )


def test_score_arm_runs_the_replay_under_the_frozen_settings_and_puts_them_back( monkeypatch ):
    """The replay sees 0.55, 8 and cosine in force, then the engine is restored."""
    seen = {}

    def fake_replay( asks, engine, snapshot, baselines, target_types ):
        seen.update( threshold=engine.similarity_threshold, top_k=engine.cbr_top_k, metric=engine.retrieval_metric,
                     baselines=sorted( baselines ), snapshot=snapshot, target_types=target_types )
        return _run( 10 )

    monkeypatch.setattr( scoring, "replay", fake_replay )
    engine = _engine()
    run    = scoring.score_arm( [], engine, { "threshold": 0.55, "top_k": 8, "metric": "cosine" }, "sha" )
    assert seen == { "threshold": 0.55, "top_k": 8, "metric": "cosine", "baselines": [ "always_yes" ], "snapshot": "sha",
                     "target_types": scoring.ELIGIBLE_TYPES }
    assert len( run[ "records" ][ ENGINE_ARM ] ) == 3
    assert ( engine.similarity_threshold, engine.cbr_top_k, engine.retrieval_metric ) == ( 0.5, 5, "dot" )


def test_score_arm_puts_the_settings_back_when_the_replay_raises( monkeypatch ):
    """A replay that raises still leaves the engine as it was."""
    def broken( *args, **kwargs ): raise RuntimeError( "boom" )

    monkeypatch.setattr( scoring, "replay", broken )
    engine = _engine()
    with pytest.raises( RuntimeError, match="boom" ): scoring.score_arm( [], engine, { "threshold": 0.9, "top_k": 3, "metric": "cosine" }, "sha" )
    assert ( engine.similarity_threshold, engine.cbr_top_k, engine.retrieval_metric ) == ( 0.5, 5, "dot" )


def _main_fixture( monkeypatch, tmp_path, vector_ids=( "n0", "n1" ) ):
    """
    Wire main to a fake cohort, a fake side file and a fake replay.

    Requires:
        - monkeypatch and tmp_path are pytest fixtures; vector_ids names the asks the side file covers

    Ensures:
        - returns ( argv, out_path, session, seen ) for one main call over two asks listed in an ids file
    """
    ids = tmp_path / "ids.jsonl"
    ids.write_text( "n0\nn1\n" )
    asks = [ { "id": f"n{i}", "question_embedding": [ 1.0 ] if f"n{i}" in vector_ids else None } for i in range( 3 ) ]

    @contextmanager
    def session():
        yield "session"

    monkeypatch.setattr( scoring, "read_cohort", lambda s, vectors: ( asks, {} ) )
    monkeypatch.setattr( scoring, "load_side_file", lambda path: ( { "rejects": [ { "id": "x" } ] }, {} ) )
    seen = {}

    def fake_replay( asks, engine, snapshot, baselines, target_types ):
        seen[ "snapshot" ] = snapshot
        seen[ "ids" ]      = [ ask[ "id" ] for ask in asks ]
        return _run( 10 )

    monkeypatch.setattr( scoring, "replay", fake_replay )
    out  = tmp_path / "out.json"
    vectors = tmp_path / "v.jsonl"
    vectors.write_text( "side file bytes" )
    argv = [ "--arm", "Q+A", "--vectors", str( vectors ), "--settings", _report( tmp_path ), "--only-ids", str( ids ), "--out", str( out ) ]
    return argv, out, session, seen


def test_main_writes_the_final_window_run_and_prints_the_count( monkeypatch, tmp_path ):
    """The file names its inputs and the printed line gives the window and the correct count."""
    argv, out, session, seen = _main_fixture( monkeypatch, tmp_path )
    printed = []
    clock = lambda: datetime( 2026, 11, 19, 20, 0, tzinfo=timezone.utc )
    assert scoring.main( argv, printer=printed.append, session_factory=session, engine_factory=_engine, code_sha="abc123", clock=clock ) == 0
    document = json.loads( out.read_text() )
    assert ( document[ "arm" ], document[ "frozen" ][ "top_k" ], document[ "vector_side_file" ], document[ "vector_rejects" ] ) == ( "Q+A", 8, argv[ 3 ], 1 )
    assert document[ "ids" ][ "only_ids_count" ] == 2
    assert document[ "settings_report" ] == argv[ 5 ]
    assert seen[ "ids" ] == [ "n0", "n1" ]
    assert seen[ "snapshot" ] == scoring.sha256_of_rows( [ { "id": "n0" }, { "id": "n1" } ] )
    assert seen[ "snapshot" ] != scoring.sha256_of_rows( [ { "id": "n0" }, { "id": "n1" }, { "id": "n2" } ] )
    assert document[ "vector_side_file_sha256" ] == hashlib.sha256( b"side file bytes" ).hexdigest()
    assert document[ "settings_report_sha256" ] == hashlib.sha256( open( argv[ 5 ], "rb" ).read() ).hexdigest()
    assert ( document[ "code_sha" ], document[ "started" ] ) == ( "abc123", "2026-11-19T20:00:00+00:00" )
    assert document[ "command" ] == "python -m cosa.research.preference_replay.arm_scoring " + " ".join( argv )
    assert len( document[ "run" ][ "asks" ] ) == 3 and "records" not in document[ "run" ]
    assert out.read_text().count( "\n" ) == 1 and ", " not in out.read_text() and ": " not in out.read_text()
    assert printed == [ "Q+A: 3 final-window asks, 1 correct" ]


def test_main_reads_the_real_clock_and_commit_when_none_are_injected( monkeypatch, tmp_path ):
    """With no injected clock or sha, the file holds an aware time and the tree's own HEAD."""
    argv, out, session, seen = _main_fixture( monkeypatch, tmp_path )
    monkeypatch.setattr( scoring, "resolve_commit", lambda root, ref: f"head-of-{ref}" )
    scoring.main( argv, printer=lambda m: None, session_factory=session, engine_factory=_engine )
    document = json.loads( out.read_text() )
    assert document[ "code_sha" ] == "head-of-HEAD"
    assert datetime.fromisoformat( document[ "started" ] ).tzinfo is not None


def test_main_records_the_process_command_line_when_argv_is_none( monkeypatch, tmp_path ):
    """Called with no argv, main parses and records sys.argv."""
    argv, out, session, seen = _main_fixture( monkeypatch, tmp_path )
    monkeypatch.setattr( scoring.sys, "argv", [ "prog" ] + argv )
    scoring.main( None, printer=lambda m: None, session_factory=session, engine_factory=_engine, code_sha="x" )
    assert json.loads( out.read_text() )[ "command" ].endswith( " ".join( argv ) )


def test_main_refuses_a_listed_ask_with_no_vector( monkeypatch, tmp_path ):
    """An ask in the ids file with no vector and no reject entry stops the run before any replay."""
    argv, _, session, _seen = _main_fixture( monkeypatch, tmp_path, vector_ids=( "n0", ) )
    with pytest.raises( ValueError, match="no vector" ): scoring.main( argv, printer=lambda m: None, session_factory=session, engine_factory=_engine )
