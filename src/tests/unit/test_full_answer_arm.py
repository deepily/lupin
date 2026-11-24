"""
Unit tests for the full-answer arm driver, src/scripts/full_answer_arm.py.

The driver forecasts the cards of record with the Haiku baseline under the full-answer reply and scores them.
Every test runs on a throwaway archive and a stand-in model; nothing reaches a service or a real archive.
"""

import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock
from sqlalchemy import create_engine

sys.path.insert( 0, os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "scripts" ) )

import cosa.agents.prediction_engine.full_answer as fa
import full_answer_arm as arm
from cosa.research.preference_replay import scratch_db  # noqa: F401  registers the one shared SQLite hooks for JSONB and Vector
from cosa.rest.postgres_models import Notification, PredictionArmForecast, PredictionLog
from sqlalchemy.orm import Session

T0        = datetime( 2026, 11, 10, 12, 0, tzinfo=timezone.utc )
RECIPIENT = uuid.UUID( "00000000-0000-4000-8000-0000000000dd" )
SENDER    = "claude.code@lupin.deepily.ai#ab12cd34"
PLAN_B    = "o2-1f4725"
DOCS      = "o1-7af023"
TESTS     = "o2-e5c9d7"
CHOICES   = { "questions": [
    { "header": "Plan", "question": "Which plan?", "options": [ { "label": "Plan A", "description": "the safe one" }, { "label": "Plan B (Recommended)" } ] },
    { "header": "Extras", "question": "Which extras?", "multi_select": True, "options": [ { "label": "Docs" }, { "label": "Tests" } ] },
    { "header": "Note", "question": "Anything else?", "input_type": "text" },
] }
ACTS      = { act: 0.1 for act in fa.ACTS }
TAIL      = { "acts": ACTS, "qualification": { "probability": 0.2, "conditions": [ { "text": "after the plan is read", "modifies_option_id": None } ] }, "gist": "yes", "whole_card_probability": 0.6 }
YES_REPLY = json.dumps( { "probabilities": { "yes": 0.7, "no": 0.2, "neither": 0.1 }, **TAIL } )
MC_REPLY  = json.dumps( { "fields": { "Plan": { "option_ids": [ PLAN_B ] }, "Extras": { "option_ids": [ DOCS, TESTS ] } }, **TAIL } )
MC_ANSWER = json.dumps( { "answers": { "Plan": "Plan B (Recommended)", "Extras": [ "Docs", "Tests" ], "Note": "ship it soon" } } )


def card( index, title, message, response_type, value, options=None ):
    """Return the columns of one answered card, created one minute after the one before."""
    return dict( id=uuid.uuid4(), sender_id=SENDER, recipient_id=RECIPIENT, title=title, message=message, abstract="the plan", type="task", priority="medium",
                 created_at=T0 + timedelta( minutes=index ), responded_at=T0 + timedelta( minutes=index, seconds=30 ), response_requested=True,
                 response_type=response_type, response_default="no", timeout_seconds=120, response_options=options, response_value=value )


@pytest.fixture
def world( tmp_path, monkeypatch ):
    """Build an archive of four cards with a records file, and turn the switch on."""
    monkeypatch.setattr( fa, "full_answer_enabled", lambda: True )
    cards   = [ card( 1, "Stop hook: Anything else?", "Anything else?", "yes_no", { "value": "no", "source": "timeout_default" } ),
                card( 2, "Ship it?", "Should the worker ship?", "yes_no", { "value": "yes", "source": "ui" } ),
                card( 3, "Pick", "Pick a plan", "multiple_choice", { "value": MC_ANSWER, "source": "ui" }, CHOICES ),
                card( 4, "Break it?", "Should the worker break it?", "yes_no", { "value": "yes", "source": "ui" } ) ]
    path    = tmp_path / "archive.sqlite"
    engine  = create_engine( f"sqlite:///{path}" )
    for model in ( Notification, PredictionLog, PredictionArmForecast ): model.__table__.create( engine )
    with Session( engine ) as db:
        db.add_all( [ Notification( **row ) for row in cards ] )
        db.add( PredictionArmForecast( notification_id=cards[ 1 ][ "id" ], arm="C0", forecast={ "value": "no" }, abstention_reason=None ) )
        db.add( PredictionArmForecast( notification_id=cards[ 1 ][ "id" ], arm="B1", forecast={ "value": "no" }, abstention_reason=None ) )
        db.add( PredictionArmForecast( notification_id=uuid.uuid4(), arm="C0", forecast={ "value": "no" }, abstention_reason=None ) )
        db.commit()
    engine.dispose()
    old     = [ False, False, True, False ]
    records = tmp_path / "records.jsonl"
    records.write_text( "".join( json.dumps( { "id": str( row[ "id" ] ), "response_type": row[ "response_type" ], "arms": { "C0": { "correct": was } } } ) + "\n" for row, was in zip( cards, old ) ) )
    work    = tmp_path / "work"
    return { "archive": str( path ), "records": str( records ), "work": str( work ), "cards": cards }


def model( prompt, options ):
    """Stand in for the model. The Break card gets text that is not JSON."""
    async def stream():
        if "Should the worker break it" in prompt: text = "I cannot say."
        elif '"probabilities"' in prompt: text = YES_REPLY
        else: text = MC_REPLY
        yield AssistantMessage( content=[ TextBlock( text ) ], model=options.model )
    return stream()


def run( world, *extra, out=None ):
    """Run main on the world's files and return its printed lines."""
    lines = []
    code  = arm.main( [ "--archive", world[ "archive" ], "--records", world[ "records" ], "--work-dir", world[ "work" ], *extra ], query_fn=model, out=lines.append if out is None else out )
    assert code == 0
    return lines


def test_the_arm_forecasts_every_card_and_scores_each_against_its_answer( world ):
    lines = run( world )
    rows  = [ json.loads( one ) for one in open( os.path.join( world[ "work" ], arm.OUT_NAME ) ) ]
    assert [ row[ "id" ] for row in rows ] == [ str( one[ "id" ] ) for one in world[ "cards" ] ], "one row per record, in record order"
    assert [ row[ "correct" ] for row in rows ] == [ False, True, True, False ], "stop-hook said no and yes was forecast; ship yes; plan right; break abstained"
    assert [ row[ "old_correct" ] for row in rows ] == [ False, False, True, False ], "the old flag is run 2's, read from the record"
    assert rows[ 3 ][ "forecast" ] is None and rows[ 3 ][ "reason" ] == fa.REASON_REPLY_NOT_JSON
    assert rows[ 1 ][ "forecast" ][ "value" ] == "yes" and rows[ 1 ][ "forecast" ][ "qualification" ][ "conditions" ][ 0 ][ "modifies_option_id" ] is None
    assert lines[ 0 ] == "[full-answer-arm] 4/4"
    assert any( "full answer True" in one and "per-field scoring on" in one for one in lines )


def test_the_report_counts_all_each_type_and_the_stop_hook_cards_on_their_own_line( world ):
    lines  = run( world )
    report = { one.split()[ 0 ]: one for one in "\n".join( lines ).splitlines() if one.split()[ 0 ] in ( "all", "yes_no", "multiple_choice", "stop-hook" ) }
    assert report[ "all" ].split()[ :5 ] == [ "all", "4", "3", "2", "1" ], "4 asks, 3 answered, 2 correct (abstention is a miss), old 1"
    assert report[ "yes_no" ].split()[ :5 ] == [ "yes_no", "3", "2", "1", "0" ]
    assert report[ "multiple_choice" ].split()[ :5 ] == [ "multiple_choice", "1", "1", "1", "1" ]
    assert report[ "stop-hook" ].split()[ :6 ] == [ "stop-hook", "cards", "1", "1", "0", "0" ], "the stop-hook card keeps its place in the totals and has its own line"
    assert "reply_not_json" in report[ "all" ]


def test_the_summary_always_has_a_stop_hook_line_even_with_no_such_card():
    rows  = [ { "response_type": "yes_no", "title": "Ship it?", "forecast": None, "reason": "no_row", "correct": False, "old_correct": True } ]
    lines = arm.summarize( rows )
    assert [ one[ "label" ] for one in lines ] == [ "all", "yes_no", "stop-hook cards" ]
    assert lines[ 2 ][ "asks" ] == 0 and lines[ 0 ][ "abstained" ] == { "no_row": 1 }
    untitled = arm.summarize( [ { **rows[ 0 ], "title": None } ] )
    assert untitled[ 2 ][ "asks" ] == 0, "a card with no title is not a stop-hook card"


def test_the_copy_clears_only_the_baseline_rows_of_the_cards_to_forecast( world ):
    os.makedirs( world[ "work" ] )
    ids  = [ str( world[ "cards" ][ 1 ][ "id" ] ) ]
    copy = arm.prepare_copy( world[ "archive" ], world[ "work" ], ids )
    data = sqlite3.connect( copy )
    arms = sorted( data.execute( "SELECT arm FROM prediction_arm_forecast" ).fetchall() )
    assert arms == [ ( "B1", ), ( "C0", ) ], "the record card's C0 row is gone; its B1 row and the other card's C0 row stay"
    original = sqlite3.connect( world[ "archive" ] )
    assert original.execute( "SELECT count(*) FROM prediction_arm_forecast" ).fetchone() == ( 3, ), "the archive itself is never written"
    data.close()
    original.close()
    data = sqlite3.connect( copy )
    data.execute( "DELETE FROM prediction_arm_forecast" )
    data.commit()
    data.close()
    assert arm.prepare_copy( world[ "archive" ], world[ "work" ], ids ) == copy
    data = sqlite3.connect( copy )
    assert data.execute( "SELECT count(*) FROM prediction_arm_forecast" ).fetchone() == ( 0, ), "an existing copy is left as it is"
    data.close()


def test_a_copy_of_an_older_archive_gains_the_columns_it_lacks( world ):
    older = sqlite3.connect( world[ "archive" ] )
    older.execute( "ALTER TABLE prediction_arm_forecast DROP COLUMN applicability" )
    older.execute( "ALTER TABLE prediction_log DROP COLUMN three_way_shadow" )
    older.commit()
    older.close()
    os.makedirs( world[ "work" ] )
    copy = arm.prepare_copy( world[ "archive" ], world[ "work" ], [] )
    data = sqlite3.connect( copy )
    assert "applicability" in [ row[ 1 ] for row in data.execute( "PRAGMA table_info( prediction_arm_forecast )" ) ]
    assert "three_way_shadow" in [ row[ 1 ] for row in data.execute( "PRAGMA table_info( prediction_log )" ) ]
    data.close()
    engine = create_engine( f"sqlite:///{copy}" )
    assert arm.add_missing_columns( engine ) == [], "a copy that is up to date adds nothing"
    engine.dispose()


def test_an_archive_missing_a_column_that_cannot_be_null_is_refused( world ):
    older = sqlite3.connect( world[ "archive" ] )
    older.execute( "ALTER TABLE notifications DROP COLUMN message" )
    older.commit()
    older.close()
    os.makedirs( world[ "work" ] )
    with pytest.raises( RuntimeError, match="notifications.message is missing" ): arm.prepare_copy( world[ "archive" ], world[ "work" ], [] )


def test_an_archive_missing_a_whole_table_is_refused( world ):
    older = sqlite3.connect( world[ "archive" ] )
    older.execute( "DROP TABLE prediction_log" )
    older.commit()
    older.close()
    os.makedirs( world[ "work" ] )
    with pytest.raises( RuntimeError, match="table prediction_log is missing" ): arm.prepare_copy( world[ "archive" ], world[ "work" ], [] )


def test_a_limit_cuts_the_cards_and_a_second_run_in_the_same_folder_is_refused( world ):
    lines = run( world, "--limit", "2" )
    assert sum( 1 for one in open( os.path.join( world[ "work" ], arm.OUT_NAME ) ) ) == 2
    assert lines[ 0 ] == "[full-answer-arm] 2/2"
    with pytest.raises( FileExistsError ): run( world )


@pytest.mark.parametrize( "done, total, due", [ ( 1, 151, False ), ( 99, 151, False ), ( 100, 151, True ), ( 150, 151, False ), ( 151, 151, True ), ( 200, 1926, True ), ( 1926, 1926, True ), ( 1925, 1926, False ) ] )
def test_the_progress_line_is_due_every_hundredth_card_and_at_the_last( done, total, due ):
    assert arm.progress_due( done, total ) is due


def test_the_run_is_refused_when_the_full_answer_switch_reads_off( world, monkeypatch ):
    monkeypatch.setattr( fa, "full_answer_enabled", lambda: False )
    with pytest.raises( RuntimeError, match="reads off" ): run( world )
    assert not os.path.exists( world[ "work" ] ), "nothing is written before the check"


def test_the_workers_flag_sets_how_many_calls_run_at_once( world, monkeypatch ):
    seen = []
    real = arm.forecast_all
    async def spy( factory, c0, ids, workers=arm.WORKERS, progress=None ):
        seen.append( workers )
        return await real( factory, c0, ids, workers, progress )
    monkeypatch.setattr( arm, "forecast_all", spy )
    run( world, "--workers", "1" )
    assert seen == [ 1 ] and arm.WORKERS == 2


def test_a_refused_reply_is_kept_whole_with_its_reason_and_an_answered_one_is_not( world ):
    lines = run( world )
    kept  = [ json.loads( one ) for one in open( os.path.join( world[ "work" ], arm.REFUSALS_NAME ) ) ]
    assert len( kept ) == 1 and "refused replies kept: 1" in lines
    assert kept[ 0 ][ "title" ] == "Break it?" and kept[ 0 ][ "reply" ] == "I cannot say."
    assert kept[ 0 ][ "reason" ] == fa.REASON_REPLY_NOT_JSON and kept[ 0 ][ "detail" ].startswith( f"{fa.REASON_REPLY_NOT_JSON}: " )


def test_the_refused_ids_are_the_cards_a_run_left_without_an_answer( world ):
    run( world )
    assert arm.refused_ids( os.path.join( world[ "work" ], arm.OUT_NAME ) ) == [ str( world[ "cards" ][ 3 ][ "id" ] ) ]


def test_only_refused_runs_just_those_cards_in_a_new_folder( world ):
    run( world )
    first = os.path.join( world[ "work" ], arm.OUT_NAME )
    again = { **world, "work": world[ "work" ] + "-again" }
    lines = run( again, "--only-refused", first )
    rows  = [ json.loads( one ) for one in open( os.path.join( again[ "work" ], arm.OUT_NAME ) ) ]
    assert [ row[ "id" ] for row in rows ] == [ str( world[ "cards" ][ 3 ][ "id" ] ) ], "the three answered cards are not asked again"
    assert lines[ 0 ] == "[full-answer-arm] 1/1" and any( "refused replies kept: 1" in one for one in lines )
