#!/usr/bin/env python3
"""
The per-ask scorer of one arm, driven with a fake replay and a fake cohort.

The fake replay records the engine settings it ran under, so a test can name the settings in force.
Nothing reaches a database, a model server or a real engine.
"""

import json
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
    return { "arm": ENGINE_ARM, "row_index": index, "meta": { "notification_id": f"n{index}", "correct": correct } }


def _run( count ):
    """
    Build a fake replay run of count asks, the engine right on the even ones.

    Requires:
        - count is a positive int

    Ensures:
        - returns the dict replay returns, with the engine and always_yes arms of equal length
    """
    return { "records": { ENGINE_ARM: [ _record( i, i % 2 == 0 ) for i in range( count ) ],
                          "always_yes": [ _record( i, i % 3 == 0 ) for i in range( count ) ] },
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
        - returns ( argv, out_path, printed ) for one main call over two asks listed in an ids file
    """
    ids = tmp_path / "ids.jsonl"
    ids.write_text( "n0\nn1\n" )
    asks = [ { "id": f"n{i}", "question_embedding": [ 1.0 ] if f"n{i}" in vector_ids else None } for i in range( 3 ) ]

    @contextmanager
    def session():
        yield "session"

    monkeypatch.setattr( scoring, "read_cohort", lambda s, vectors: ( asks, {} ) )
    monkeypatch.setattr( scoring, "load_side_file", lambda path: ( { "rejects": [ { "id": "x" } ] }, {} ) )
    monkeypatch.setattr( scoring, "replay", lambda *a, **k: _run( 10 ) )
    out  = tmp_path / "out.json"
    argv = [ "--arm", "Q+A", "--vectors", "v.jsonl", "--settings", _report( tmp_path ), "--only-ids", str( ids ), "--out", str( out ) ]
    return argv, out, session


def test_main_writes_the_final_window_run_and_prints_the_count( monkeypatch, tmp_path ):
    """The file names its inputs and the printed line gives the window and the correct count."""
    argv, out, session = _main_fixture( monkeypatch, tmp_path )
    printed = []
    assert scoring.main( argv, printer=printed.append, session_factory=session, engine_factory=_engine ) == 0
    document = json.loads( out.read_text() )
    assert ( document[ "arm" ], document[ "frozen" ][ "top_k" ], document[ "vector_side_file" ], document[ "vector_rejects" ] ) == ( "Q+A", 8, "v.jsonl", 1 )
    assert document[ "ids" ][ "only_ids_count" ] == 2
    assert len( document[ "run" ][ "records" ][ ENGINE_ARM ] ) == 3
    assert printed == [ "Q+A: 3 final-window asks, 1 correct" ]


def test_main_refuses_a_listed_ask_with_no_vector( monkeypatch, tmp_path ):
    """An ask in the ids file with no vector and no reject entry stops the run before any replay."""
    argv, _, session = _main_fixture( monkeypatch, tmp_path, vector_ids=( "n0", ) )
    with pytest.raises( ValueError, match="no vector" ): scoring.main( argv, printer=lambda m: None, session_factory=session, engine_factory=_engine )
