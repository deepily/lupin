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
    rows  = [ { "response_type": "yes_no", "title": "Ship it?", "forecast": None, "reason": "no_row", "correct": False, "old_correct": True, "write_in_fields": [] } ]
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


def cards_of( yes_no, choice ):
    """Return synthetic cards, y0.. for yes/no and m0.. for multiple choice, interleaved."""
    rows = [ { "id": f"y{i}", "response_type": "yes_no" } for i in range( yes_no ) ] + [ { "id": f"m{i}", "response_type": "multiple_choice" } for i in range( choice ) ]
    return sorted( rows, key=lambda row: row[ "id" ][ 1: ] + row[ "id" ][ 0 ] )


def test_the_sample_splits_the_size_by_type_in_the_cohorts_shares_by_largest_remainder():
    # The cohort of record: 769 yes/no and 1,157 multiple choice. 500 x 769 / 1,926 is 199.64 and 500 x 1,157 / 1,926 is 300.36.
    drawn = arm.draw_sample( cards_of( 769, 1157 ), 500, 20261124 )
    assert drawn[ "counts" ] == { "multiple_choice": 300, "yes_no": 200 } and len( drawn[ "ids" ] ) == 500 == len( set( drawn[ "ids" ] ) )
    assert sum( 1 for one in drawn[ "ids" ] if one.startswith( "y" ) ) == 200


def test_the_sample_is_the_same_for_the_same_seed_and_differs_for_another_and_keeps_record_order():
    rows = cards_of( 10, 20 )
    once = arm.draw_sample( rows, 6, 7 )
    assert once == arm.draw_sample( rows, 6, 7 ) and once[ "ids" ] != arm.draw_sample( rows, 6, 8 )[ "ids" ]
    assert once[ "ids" ] == [ row[ "id" ] for row in rows if row[ "id" ] in set( once[ "ids" ] ) ], "ids come back in record order"
    assert once[ "ids" ] == [ "m10", "m13", "m19", "y1", "m2", "y8" ] and once[ "counts" ] == { "multiple_choice": 4, "yes_no": 2 }, "a literal pins the draw for seed 7"


def test_a_tie_between_two_types_goes_to_the_type_that_sorts_first():
    drawn = arm.draw_sample( cards_of( 3, 1 ), 2, 1 )
    assert drawn[ "counts" ] == { "multiple_choice": 1, "yes_no": 1 }, "1.5 and 0.5 leave a remainder of 0.5 each; the spare place goes to multiple_choice"


@pytest.mark.parametrize( "size", [ 0, -1, 5 ] )
def test_a_sample_size_outside_the_cards_is_refused( size ):
    with pytest.raises( ValueError, match="sample size" ): arm.draw_sample( cards_of( 2, 2 ), size, 1 )


def test_a_sample_run_writes_its_ids_and_seed_first_and_forecasts_only_those_cards( world ):
    lines = run( world, "--sample", "2", "--seed", "5" )
    saved = json.load( open( os.path.join( world[ "work" ], arm.SAMPLE_NAME ) ) )
    rows  = [ json.loads( one ) for one in open( os.path.join( world[ "work" ], arm.OUT_NAME ) ) ]
    assert saved[ "seed" ] == 5 and saved[ "size" ] == 2 and saved[ "counts" ] == { "multiple_choice": 1, "yes_no": 1 }
    assert [ row[ "id" ] for row in rows ] == saved[ "ids" ] and lines[ 0 ] == "[full-answer-arm] 2/2"
    again = { **world, "work": world[ "work" ] + "-again" }
    run( again, "--sample", "2", "--seed", "5" )
    assert json.load( open( os.path.join( again[ "work" ], arm.SAMPLE_NAME ) ) ) == saved, "the same seed gives the same ids"


@pytest.mark.parametrize( "flags", [ [ "--sample", "2" ], [ "--seed", "5" ] ] )
def test_a_sample_and_a_seed_go_together( world, flags ):
    with pytest.raises( ValueError, match="go together" ): run( world, *flags )
    assert not os.path.exists( world[ "work" ] )


def test_the_model_flag_names_the_model_the_run_calls_in_place_of_the_ini_setting( world ):
    lines = run( world, "--model", "claude-sonnet-5-5" )
    assert any( one.startswith( "model claude-sonnet-5-5," ) for one in lines )


def test_the_sample_file_is_on_disk_before_the_first_model_call_arrives( world ):
    seen = []
    def watching( prompt, options ):
        seen.append( os.path.exists( os.path.join( world[ "work" ], arm.SAMPLE_NAME ) ) )
        return model( prompt, options )
    arm.main( [ "--archive", world[ "archive" ], "--records", world[ "records" ], "--work-dir", world[ "work" ], "--sample", "2", "--seed", "5" ], query_fn=watching, out=lambda line: None )
    assert seen and all( seen ), "the ids and seed are written down before any call, so a crashed run still leaves them"


def test_each_scored_row_carries_the_answer_split_read_from_its_card( world ):
    run( world )
    rows = [ json.loads( one ) for one in open( os.path.join( world[ "work" ], arm.OUT_NAME ) ) ]
    assert [ ( row[ "scorable" ], row[ "write_in" ] ) for row in rows ] == [ ( True, False ) ] * 4, "the Note field lists no options, so it is never a write-in"


def _mc_row( correct, scorable, write_in ):
    """One scored multiple-choice row of the shape score_rows writes."""
    return { "response_type": "multiple_choice", "title": "Pick", "forecast": { "answers": {} }, "reason": None, "correct": correct, "old_correct": False,
             "scorable": scorable, "write_in": write_in, "write_in_fields": [] }


def test_a_line_gives_multiple_choice_right_over_scorable_and_the_table_prints_it_under_the_all_cards_figure():
    rows  = [ _mc_row( True, True, False ), _mc_row( False, True, True ), _mc_row( False, False, True ),
              { "response_type": "yes_no", "title": "Ship it?", "forecast": { "value": "yes" }, "reason": None, "correct": True, "old_correct": True, "scorable": True, "write_in": False, "write_in_fields": [] } ]
    lines = arm.summarize( rows )
    assert lines[ 0 ][ "correct" ] == 2 and lines[ 0 ][ "multiple_choice" ] == { "cards": 3, "scorable": 2, "unscored": 1, "right": 1, "unscored_right": 0,
                                                                                "correct_all_cards": 1, "accuracy_scorable": 0.5, "accuracy_all_cards": 1 / 3,
                                                                                "write_in_cards": 2, "write_in_rate": 2 / 3 }
    text  = arm.render( lines ).splitlines()
    assert text[ 1 ].split()[ :4 ] == [ "all", "4", "4", "2" ], "the correct column keeps the all-cards figure"
    assert text[ 2 ].strip() == "multiple choice: right 1 of 2 scorable, unscored 1 of 3, write-in cards 2 of 3, unscored right 0"
    assert [ one.split()[ 0 ] for one in text ] == [ "group", "all", "multiple", "multiple_choice", "multiple", "yes_no", "stop-hook" ], \
        "a line with no multiple-choice cards prints no split line"


@pytest.mark.parametrize( "answers, split", [
    ( { "Plan": "neither, ask me later", "Extras": [ "Docs" ], "Note": "ship it soon" }, ( True, True ) ),
    ( { "Plan": "neither, ask me later", "Extras": [ "my own pick" ], "Note": "ship it soon" }, ( False, True ) ),
] )
def test_a_card_with_a_typed_write_in_is_marked_and_one_with_every_option_field_typed_is_unscorable( world, answers, split ):
    engine = create_engine( f"sqlite:///{world[ 'archive' ]}" )
    with Session( engine ) as db:
        db.get( Notification, world[ "cards" ][ 2 ][ "id" ] ).response_value = { "value": json.dumps( { "answers": answers } ), "source": "ui" }
        db.commit()
    engine.dispose()
    run( world )
    rows = [ json.loads( one ) for one in open( os.path.join( world[ "work" ], arm.OUT_NAME ) ) ]
    assert ( rows[ 2 ][ "scorable" ], rows[ 2 ][ "write_in" ] ) == split and rows[ 2 ][ "correct" ] is False


MC_OUTCOME_REPLY = json.dumps( { "fields": { "Plan": { "option_ids": [ PLAN_B ], "write_in_probability": 0.8 }, "Extras": { "option_ids": [ DOCS, TESTS ], "write_in_probability": 0.1 } }, **TAIL } )


def outcome_model( prompt, options ):
    """Stand in for the model under --write-in, replying with the outcome."""
    async def stream():
        assert "write_in_probability" in prompt, "the run asked for the outcome"
        yield AssistantMessage( content=[ TextBlock( MC_OUTCOME_REPLY ) ], model=options.model )
    return stream()


def test_the_write_in_flag_keeps_only_the_multiple_choice_cards_and_scores_each_fields_outcome( world ):
    lines = []
    code  = arm.main( [ "--archive", world[ "archive" ], "--records", world[ "records" ], "--work-dir", world[ "work" ], "--write-in" ], query_fn=outcome_model, out=lines.append )
    rows  = [ json.loads( one ) for one in open( os.path.join( world[ "work" ], arm.OUT_NAME ) ) ]
    assert code == 0 and [ row[ "id" ] for row in rows ] == [ str( world[ "cards" ][ 2 ][ "id" ] ) ]
    assert rows[ 0 ][ "write_in_fields" ] == [ { "header": "Plan", "probability": 0.8, "predicted": True, "actual": False },
                                               { "header": "Extras", "probability": 0.1, "predicted": False, "actual": False } ]
    assert any( "write-in outcome True" in one for one in lines )
    table = "\n".join( lines )
    assert "write-in forecast: 2 fields, 0 typed, 1 forecast typed, 0 both; precision 0.000, recall -, Brier 0.325" in table


def test_without_the_flag_no_card_has_an_outcome_and_no_write_in_line_is_printed( world ):
    lines = run( world )
    rows  = [ json.loads( one ) for one in open( os.path.join( world[ "work" ], arm.OUT_NAME ) ) ]
    assert all( row[ "write_in_fields" ] == [] for row in rows ) and not any( "write-in forecast" in one for one in lines )
    assert any( "write-in outcome False" in one for one in lines )


def _paired_row( ask_id, correct, scorable=True, kind="multiple_choice" ):
    """One scored row for pair_with."""
    return { "id": ask_id, "response_type": kind, "correct": correct, "scorable": scorable, "write_in": not scorable }


def test_pair_with_scores_both_runs_on_the_shared_multiple_choice_cards_with_this_runs_flags():
    rows = [ _paired_row( "a", True ), _paired_row( "b", False ), _paired_row( "c", False, scorable=False ), _paired_row( "d", True ), _paired_row( "y", True, kind="yes_no" ) ]
    old  = [ { "id": "a", "correct": False }, { "id": "b", "correct": True }, { "id": "c", "correct": False }, { "id": "y", "correct": False } ]
    pair = arm.pair_with( rows, old )
    assert pair[ "cards" ] == 3, "d is not in the earlier run and y is not multiple choice"
    assert ( pair[ "new" ][ "right" ], pair[ "new" ][ "scorable" ], pair[ "old" ][ "right" ], pair[ "old" ][ "scorable" ] ) == ( 1, 2, 1, 2 )
    assert ( pair[ "new_only_right" ], pair[ "old_only_right" ] ) == ( 1, 1 )
    assert arm.render_pair( pair ) == ( "paired with the earlier run on 3 multiple-choice cards: this run right 1 of 2 scorable (1 of 3 all cards), "
                                        "earlier run right 1 of 2 scorable (1 of 3 all cards)\nonly this run right 1, only the earlier run right 1" )


def test_the_pair_with_flag_prints_the_comparison_after_the_table( world, tmp_path ):
    earlier = tmp_path / "earlier.jsonl"
    earlier.write_text( json.dumps( { "id": str( world[ "cards" ][ 2 ][ "id" ] ), "correct": False } ) + "\n" )
    lines   = run( world, "--pair-with", str( earlier ) )
    first, second = lines[ -1 ].splitlines()
    assert first.startswith( "paired with the earlier run on 1 multiple-choice cards: this run right 1 of 1 scorable" ) and second == "only this run right 1, only the earlier run right 0"


def test_the_ratio_shows_a_dash_for_none():
    assert arm._ratio( None ) == "-" and arm._ratio( 0.5 ) == "0.500"


def test_the_tables_checked_for_missing_columns_can_be_named( world ):
    older = sqlite3.connect( world[ "archive" ] )
    older.execute( "ALTER TABLE prediction_log DROP COLUMN three_way_shadow" )
    older.commit()
    older.close()
    engine = create_engine( f"sqlite:///{world[ 'archive' ]}" )
    assert arm.add_missing_columns( engine, models=( Notification, ) ) == [], "a table not named is left alone"
    assert arm.add_missing_columns( engine, models=( PredictionLog, ) ) == [ "prediction_log.three_way_shadow" ]
    engine.dispose()
