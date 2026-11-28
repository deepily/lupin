"""
Unit tests for the typed-reply predictor, src/scripts/typed_reply_test.py.

Each test runs on a throwaway archive and a stand-in model. The answers are stored in the shape the
live card stores them: a JSON string of answers under "value".
"""

import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert( 0, os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "scripts" ) )

import typed_reply_test as typed
from cosa.research.preference_replay import scratch_db  # noqa: F401  registers the SQLite hooks for JSONB and Vector
from cosa.rest.postgres_models import Notification, PredictionArmForecast, PredictionLog

T0      = datetime( 2026, 11, 10, 12, 0, tzinfo=timezone.utc )
CHOICES = { "questions": [
    { "header": "Plan", "question": "Which plan?", "options": [ { "label": "Plan A" }, { "label": "Plan B (Recommended)" } ] },
    { "header": "Extras", "question": "Which extras?", "multi_select": True, "options": [ { "label": "Docs" }, { "label": "Tests" } ] },
] }
PLAN_WORDS  = "Why does plan B cost more?"
EXTRA_WORDS = "Wait until Friday for the rest"
GOOD        = json.dumps( { "kind": "question", "reply": "What does it cost?" } )


def _card( index, message, answers ):
    """Return the columns of one answered multiple-choice card."""
    return dict( id=uuid.uuid4(), sender_id="claude.code@lupin.deepily.ai#ab12cd34", recipient_id=uuid.UUID( "00000000-0000-4000-8000-0000000000dd" ), title=f"Card {index}", message=message,
                 abstract="the plan", type="task", priority="medium", created_at=T0 + timedelta( minutes=index ),
                 responded_at=T0 + timedelta( minutes=index, seconds=30 ), response_requested=True, response_type="multiple_choice",
                 response_default=None, timeout_seconds=120, response_options=CHOICES, response_value={ "value": json.dumps( { "answers": answers } ), "source": "ui" } )


def _per_ask( card, typed_headers ):
    """Return a write-in run's line for one card, marking the named fields typed."""
    return { "id": str( card[ "id" ] ), "write_in_fields": [ { "header": header, "actual": header in typed_headers } for header in ( "Plan", "Extras" ) ] }


@pytest.fixture
def world( tmp_path ):
    """Build an archive of three cards: two with typed fields and one with none."""
    cards  = [ _card( 1, "Pick a plan", { "Plan": PLAN_WORDS, "Extras": [ "Docs", EXTRA_WORDS ] } ),
               _card( 2, "Pick nothing typed", { "Plan": "Plan A", "Extras": [ "Docs" ] } ),
               _card( 3, "Pick again", { "Plan": "Plan A", "Extras": EXTRA_WORDS } ) ]
    path   = tmp_path / "archive.sqlite"
    engine = create_engine( f"sqlite:///{path}" )
    for model in ( Notification, PredictionLog, PredictionArmForecast ): model.__table__.create( engine )
    with Session( engine ) as db:
        db.add_all( [ Notification( **row ) for row in cards ] )
        db.commit()
    engine.dispose()
    lines   = [ _per_ask( cards[ 0 ], ( "Plan", "Extras" ) ), _per_ask( cards[ 1 ], () ), _per_ask( cards[ 2 ], ( "Extras", ) ) ]
    per_ask = tmp_path / "per-ask.jsonl"
    per_ask.write_text( "".join( json.dumps( line ) + "\n" for line in lines ) )
    return { "tmp": tmp_path, "cards": cards, "lines": lines, "archive": path, "per_ask": per_ask, "work": tmp_path / "work" }


def _model( seen, reply=GOOD ):
    """Make a stand-in model that records each prompt and answers with reply, or raises it."""
    def query( prompt, options ):
        seen.append( ( prompt, options.model ) )

        async def stream():
            if isinstance( reply, Exception ): raise reply
            yield AssistantMessage( content=[ TextBlock( reply ) ], model=options.model )
        return stream()
    return query


def _run( world, query, *extra ):
    """Run main on the world's files and return the printed lines and the rows written."""
    printed = []
    argv    = [ "--per-ask", str( world[ "per_ask" ] ), "--archive", str( world[ "archive" ] ), "--work-dir", str( world[ "work" ] ), "--model", "stand-in-one", *extra ]
    assert typed.main( argv, query_fn=query, out=printed.append ) == 0
    return printed, [ json.loads( line ) for line in ( world[ "work" ] / typed.OUT_NAME ).read_text().splitlines() ]


def test_each_typed_field_gets_a_prediction_beside_the_words_actually_typed( world ):
    seen = []
    printed, rows = _run( world, _model( seen ) )
    first, third = str( world[ "cards" ][ 0 ][ "id" ] ), str( world[ "cards" ][ 2 ][ "id" ] )
    assert [ ( r[ "id" ], r[ "field" ], r[ "actual" ] ) for r in rows ] == [ ( first, "Plan", PLAN_WORDS ), ( first, "Extras", EXTRA_WORDS ), ( third, "Extras", EXTRA_WORDS ) ]
    assert all( ( r[ "kind" ], r[ "predicted" ], r[ "reason" ], r[ "raw" ], r[ "model" ] ) == ( "question", "What does it cost?", None, None, "stand-in-one" ) for r in rows )
    assert len( { r[ "prompt_version" ] for r in rows } ) == 1
    assert printed == [ "model stand-in-one: 3 typed fields on 2 cards, 3 predicted, 0 without a prediction" ]
    assert [ model for _, model in seen ] == [ "stand-in-one" ] * 3


def test_no_prompt_holds_anything_that_was_typed_and_each_names_its_field( world ):
    seen = []
    _run( world, _model( seen ), "--workers", "1" )
    prompts = sorted( prompt for prompt, _ in seen )
    assert len( prompts ) == 3
    assert not any( PLAN_WORDS in p or EXTRA_WORDS in p for p in prompts )
    assert all( "Which plan?" in p and "Plan B (Recommended)" in p and '{"answers"' not in p for p in prompts )
    assert sum( 'for the field "Plan"' in p for p in prompts ) == 1 and sum( 'for the field "Extras"' in p for p in prompts ) == 2


def test_the_limit_and_a_later_model_flag_cut_the_run_and_name_the_model( world ):
    seen = []
    _, rows = _run( world, _model( seen ), "--limit", "1", "--model", "stand-in-two" )
    assert [ r[ "field" ] for r in rows ] == [ "Plan" ]
    assert [ model for _, model in seen ] == [ "stand-in-two" ] and rows[ 0 ][ "model" ] == "stand-in-two"


@pytest.mark.parametrize( "reply", [ "I cannot say.", json.dumps( { "kind": "praise", "reply": "x" } ), json.dumps( { "kind": "defer", "reply": "  " } ), json.dumps( { "kind": "defer" } ) ] )
def test_an_unreadable_reply_is_kept_whole_and_counted_without_a_prediction( world, reply ):
    printed, rows = _run( world, _model( [], reply ), "--limit", "1" )
    assert ( rows[ 0 ][ "reason" ], rows[ 0 ][ "raw" ], rows[ 0 ][ "kind" ], rows[ 0 ][ "predicted" ] ) == ( "unreadable", reply, None, None )
    assert printed[ 0 ].endswith( "0 predicted, 1 without a prediction" )


def test_a_failed_call_is_recorded_as_such( world ):
    _, rows = _run( world, _model( [], typed.model_transport.ModelCallError( "the child died" ) ), "--limit", "1" )
    assert rows[ 0 ][ "reason" ] == "call_failed" and "the child died" in rows[ 0 ][ "raw" ]
    assert rows[ 0 ][ "predicted" ] is None


def test_a_second_run_in_the_same_folder_is_refused_before_any_call( world ):
    _run( world, _model( [] ) )
    seen = []
    with pytest.raises( FileExistsError ): _run( world, _model( seen ) )
    assert seen == []


def test_the_archive_is_not_changed( world ):
    before = world[ "archive" ].read_bytes()
    _run( world, _model( [] ) )
    assert world[ "archive" ].read_bytes() == before


def test_a_field_the_run_calls_typed_that_holds_only_offered_labels_is_refused( world ):
    world[ "per_ask" ].write_text( json.dumps( _per_ask( world[ "cards" ][ 1 ], ( "Plan", ) ) ) + "\n" )
    with pytest.raises( ValueError, match="every pick is an offered label" ): _run( world, _model( [] ) )
