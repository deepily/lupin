"""
Unit tests for the kind scorer, src/scripts/typed_reply_score.py.

The sample is hand-built so that every count differs from its neighbours.
"""

import json
import os
import sys

import pytest

sys.path.insert( 0, os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "scripts" ) )

import typed_reply_score as score


def _row( actual, predicted, name ):
    """Return one prediction row."""
    return { "id": name, "actual": actual, "predicted": predicted }


ROWS = [ _row( "Why is that?", "What does it cost?", "both-question" ),
         _row( "How big is it", "Go ahead", "question-missed" ),
         _row( "Explain the risk", None, "question-no-prediction" ),
         _row( "Tell me more", "Hold on", "question-as-defer" ),
         _row( "Ask me later", "Wait until Friday", "both-defer" ),
         _row( "Go with the first one", "Do it, with tests", "both-other" ),
         _row( "Ship it", "Why now?", "other-as-question" ) ]


@pytest.mark.parametrize( "text, kind", [ ( "Why?", "question" ), ( "explain it", "question" ), ( "Is it done?", "question" ), ( "wait", "defer" ),
                                          ( "Why not wait?", "defer" ), ( "re-ask me", "defer" ), ( "approved, go", "other" ), ( "somewhat", "other" ), ( "", "other" ) ] )
def test_the_rule_sorts_defer_before_question_and_the_rest_as_other( text, kind ):
    assert score.kind_of( text ) == kind


def test_the_score_counts_each_side_and_the_control_names_the_commonest_typed_kind():
    got = score.score_kinds( ROWS )
    assert ( got[ "fields" ], got[ "control" ] ) == ( 7, "question" )
    assert got[ "typed" ] == { "question": 4, "defer": 1, "other": 2 }
    assert got[ "predicted" ] == { "question": 2, "defer": 2, "other": 2 }
    assert got[ "by_kind" ] == { "question": { "fields": 4, "model": 1, "control": 4 }, "defer": { "fields": 1, "model": 1, "control": 0 },
                                 "other": { "fields": 2, "model": 1, "control": 0 } }
    assert ( got[ "model_only" ], got[ "control_only" ] ) == ( 2, 3 )
    assert [ row[ "id" ] for row in got[ "question_pairs" ] ] == [ "both-question" ]


def test_a_tie_for_commonest_goes_to_the_kind_listed_first():
    assert score.score_kinds( [ _row( "go", "go", "a" ), _row( "wait", "go", "b" ) ] )[ "control" ] == "defer"


def test_main_prints_the_table_and_saves_only_the_question_pairs( tmp_path ):
    source, pairs = tmp_path / "p.jsonl", tmp_path / "pairs.jsonl"
    source.write_text( "".join( json.dumps( row ) + "\n" for row in ROWS ) )
    lines = []
    assert score.main( [ "--predictions", str( source ), "--pairs-out", str( pairs ) ], out=lines.append ) == 0
    text = "\n".join( lines )
    assert "| all | 3/7 (42.9%" in text and "| 4/7 (57.1%" in text
    assert "| question | 1/4 (25.0%" in text and "| 4/4 (100.0%" in text
    assert "only the model right 2, only the control right 3, exact McNemar p 1.0000" in text
    assert "pairs saved for a judge: 1" in text
    assert [ json.loads( line )[ "id" ] for line in pairs.read_text().splitlines() ] == [ "both-question" ]
    with pytest.raises( FileExistsError ): score.main( [ "--predictions", str( source ), "--pairs-out", str( pairs ) ], out=lines.append )
