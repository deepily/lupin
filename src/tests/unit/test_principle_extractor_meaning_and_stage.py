"""
Tests for the extractor meaning-record input, answer_read and stage prompt (rows 4 to 6).

Each switch is off by default. The first tests pin that, with every switch off, the prompt, summary, version
and stored rows are unchanged. The stage replies in fixtures/principle_stage/real_stage_replies.json came from the
real model (claude-sonnet-5-5, through model_transport.complete and parse_reply) on 24 Nov 2026.
"""

import asyncio
import json
import os
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest

import cosa.agents.principle_learner.extractor_job as job_module
import cosa.agents.principle_learner.extractor_prompt as prompt_module
from cosa.agents.prediction_engine.history_derive import meaning_structure
from cosa.agents.principle_learner.extractor_job import DECISION_STAGE_KEY, MEANING_INPUT_KEY, PrincipleExtractorJob
from cosa.agents.principle_learner.extractor_prompt import PROMPT_VERSION, STAGE_SYSTEM_PROMPT, SYSTEM_PROMPT, VERSION_TAGS, active_prompt_version, active_tags, build_user_prompt, current_extractor_version, extractor_version_of, parse_reply, switch_on
from cosa.rest.db.repositories.answer_meaning_repository import AnswerMeaningRepository
from cosa.rest.postgres_models import AnswerMeaning, PredictionLog, PreferenceEvidence
from tests.unit.test_principle_extractor_job import MODEL, NOW, OWNER, T0, Model, _ask, _counts, _hyp, _reply, _result, _run, db  # noqa: F401  (db is a fixture)

FIXTURE = os.path.join( os.path.dirname( __file__ ), "fixtures", "principle_stage", "real_stage_replies.json" )

OPTIONS = { "questions": [ { "header": "held_bugs", "question": "Approve the held bugs?", "options": [ { "label": "Approve" }, { "label": "Hold" } ] },
                           { "header": "budget", "question": "Budget?", "input_type": "text" } ] }

NATIVE  = { "held_bugs": { "kind": "selected_options", "selected_option_ids": [ "held_bugs#o2" ], "empty_selection": False, "write_in_text": None, "referred_option_ids": [ "held_bugs#o1" ], "text": None },
            "budget"   : { "kind": "open_ended_text", "selected_option_ids": [], "empty_selection": False, "write_in_text": "no limit", "referred_option_ids": [], "text": "no limit" } }

CONDITIONS = [ { "text": "only if linked", "modifies_option_id": "held_bugs#o2" }, { "text": "for everything", "modifies_option_id": None },
               { "text": "on another card", "modifies_option_id": "other#o9" } ]


@pytest.fixture( autouse=True )
def _meaning_table( db ):
    """
    Create the answer_meaning table, as the migration does on a real database.

    Ensures:
        - the table exists before each test, empty
    """
    AnswerMeaning.__table__.create( db.get_bind(), checkfirst=True )


def _fixture():
    """
    Read the committed real-model replies.

    Ensures:
        - returns the parsed fixture file
    """
    with open( FIXTURE ) as handle: return json.load( handle )


def _switches( monkeypatch, *keys ):
    """
    Turn the named switches on, and every other one off, for this test.

    Ensures:
        - PrincipleExtractorJob._flag answers True for the given keys and no others
    """
    monkeypatch.setattr( PrincipleExtractorJob, "_flag", lambda self, key: key in keys )


def _card_ask( db ):
    """
    Insert a two-field card answered by its owner and return its id as text.

    Ensures:
        - the answers are held_bugs: Hold and budget: no limit
    """
    return _ask( db, response_type="multiple_choice", response_options=OPTIONS,
                 response_value={ "value": json.dumps( { "answers": { "held_bugs": "Hold", "budget": "no limit" } } ), "source": "ui", "answered_by": { "user_id": str( OWNER ) } } )


def _meaning( db, notification_id, schema_version="answer-meaning-v1", annotator="a", native=None, conditions=None ):
    """
    Store one meaning record for a notification.

    Ensures:
        - the table exists and one row is added through the repository
        - native and conditions, when None, default to the module's sample card record
    """
    AnswerMeaning.__table__.create( db.get_bind(), checkfirst=True )
    native     = NATIVE if native is None else native
    conditions = CONDITIONS if conditions is None else conditions
    AnswerMeaningRepository( db ).add( notification_id, annotator, "human", native, [ { "act": "approve", "depends_on": [] } ], conditions, "aligned", [], schema_version=schema_version )
    db.commit()


def _card_reply():
    """
    Write a model reply covering both fields of the card.

    Ensures:
        - returns the JSON text with one result per field
    """
    return _reply( _result( "held_bugs", [ _hyp( "Hold bugs until linked.", condition="Hold" ) ] ), _result( "budget", [ _hyp( "Skip budgets.", condition="no limit" ) ], dimension="decision.budget", kind="decision" ) )


def _revealed( db, notification_id, draft ):
    """
    Log a forecast reveal after the ask, holding a draft of the answer.

    Ensures:
        - one prediction_log row names the notification with the draft taken at reveal
    """
    db.add( PredictionLog( id=uuid.uuid4(), notification_id=uuid.UUID( notification_id ), response_type="yes_no", category="c", prediction_strategy="s", predicted_at=T0,
                           prediction_confidence=0.5, similar_case_count=0, fold_opened_at=T0 + timedelta( seconds=30 ), draft_at_reveal=draft ) )
    db.commit()


# ---- every switch off: today's behaviour ----

def test_with_every_switch_off_a_stored_meaning_record_changes_nothing_the_prompt_the_summary_the_version_or_the_rows( db ):
    ask = _card_ask( db )
    _meaning( db, ask )
    model  = Model( _card_reply() )
    out, _ = _run( db, ask, model )
    assert "structure" not in model.sent[ 0 ] and "held_bugs#o2" not in model.sent[ 0 ] and "decision_stage" not in model.sent[ 0 ]
    assert "answer_read" not in out and out[ "status" ] == "extracted"
    assert { row.extractor_version for row in db.query( PreferenceEvidence ) } == { f"{MODEL}:{PROMPT_VERSION}" }
    assert { row.decision_stage for row in db.query( PreferenceEvidence ) } == { None }


def test_with_the_stage_switch_off_a_stage_in_the_reply_is_not_stored_and_the_old_system_prompt_is_sent( db, monkeypatch ):
    _switches( monkeypatch )
    ask   = _ask( db, answer="no" )
    seen  = []
    async def spy( model, system, user, **kwargs ):
        seen.append( system )
        return _reply( { **_result( hypotheses=[ _hyp() ] ), "decision_stage": "who_decides" } )
    monkeypatch.setattr( job_module.model_transport, "complete", spy )
    _run( db, ask, None )
    assert seen == [ SYSTEM_PROMPT ] and db.query( PreferenceEvidence ).one().decision_stage is None


def test_the_flag_reads_the_ini_file_and_is_false_for_both_new_keys_as_shipped():
    job = PrincipleExtractorJob( str( uuid.uuid4() ), str( OWNER ), "o@example.com" )
    assert job._flag( MEANING_INPUT_KEY ) is False and job._flag( DECISION_STAGE_KEY ) is False and switch_on( DECISION_STAGE_KEY ) is False


def test_the_flag_is_true_when_the_ini_value_is_true( monkeypatch ):
    class Config:
        def __init__( self, env_var_name ): self.env = env_var_name
        def get( self, key, default, return_type ):
            assert ( default, return_type ) == ( "false", "boolean" )
            return key == MEANING_INPUT_KEY
    monkeypatch.setattr( prompt_module, "ConfigurationManager", Config )
    job = PrincipleExtractorJob( str( uuid.uuid4() ), str( OWNER ), "o@example.com" )
    assert job._flag( MEANING_INPUT_KEY ) is True and job._flag( DECISION_STAGE_KEY ) is False


def test_an_unreadable_settings_file_turns_the_switch_off_and_says_so( monkeypatch, capsys ):
    def broken( env_var_name ): raise OSError( "no ini" )
    monkeypatch.setattr( prompt_module, "ConfigurationManager", broken )
    job = PrincipleExtractorJob( str( uuid.uuid4() ), str( OWNER ), "o@example.com" )
    assert job._flag( MEANING_INPUT_KEY ) is False
    assert MEANING_INPUT_KEY in capsys.readouterr().out


# ---- row 4: the structure reaches the writer ----

def test_with_the_meaning_switch_on_the_writer_gets_option_ids_and_the_condition_link_as_fields_for_a_comment_on_a_multiple_choice_card( db, monkeypatch ):
    _switches( monkeypatch, MEANING_INPUT_KEY )
    ask = _card_ask( db )
    _meaning( db, ask )
    model  = Model( _card_reply() )
    _run( db, ask, model )
    answers = json.loads( model.sent[ 0 ].split( "ANSWERS\n" )[ 1 ].split( "\n\nEXISTING PRINCIPLES" )[ 0 ] )
    held    = next( a for a in answers if a[ "field_key" ] == "held_bugs" )[ "structure" ]
    assert held[ "option_ids" ] == [ "held_bugs#o2" ] and held[ "referred_option_ids" ] == [ "held_bugs#o1" ]
    assert held[ "conditions" ] == [ { "text": "only if linked", "modifies_option_id": "held_bugs#o2" }, { "text": "for everything", "modifies_option_id": None } ]
    assert next( a for a in answers if a[ "field_key" ] == "budget" )[ "structure" ][ "write_in_text" ] == "no limit"


def test_the_structure_comes_from_the_newest_record_of_the_current_schema_version_and_older_versions_are_ignored( db, monkeypatch ):
    _switches( monkeypatch, MEANING_INPUT_KEY )
    ask = _card_ask( db )
    _meaning( db, ask, schema_version="answer-meaning-v0", native={ "held_bugs": { **NATIVE[ "held_bugs" ], "selected_option_ids": [ "stale#o1" ] } } )
    _meaning( db, ask, annotator="a" )
    model = Model( _card_reply() )
    _run( db, ask, model )
    assert "held_bugs#o2" in model.sent[ 0 ] and "stale#o1" not in model.sent[ 0 ]


def test_with_no_meaning_record_the_prompt_has_no_structure_and_the_reading_is_still_logged( db, monkeypatch ):
    _switches( monkeypatch, MEANING_INPUT_KEY )
    ask = _card_ask( db )
    AnswerMeaning.__table__.create( db.get_bind(), checkfirst=True )
    model  = Model( _card_reply() )
    out, _ = _run( db, ask, model )
    assert "structure" not in model.sent[ 0 ] and out[ "answer_read" ] == { "held_bugs": "final", "budget": "final" }


def test_a_record_with_no_entry_for_a_field_gives_that_field_no_structure( db, monkeypatch ):
    _switches( monkeypatch, MEANING_INPUT_KEY )
    ask = _card_ask( db )
    _meaning( db, ask, native={ "budget": NATIVE[ "budget" ] } )
    model = Model( _card_reply() )
    _run( db, ask, model )
    answers = json.loads( model.sent[ 0 ].split( "ANSWERS\n" )[ 1 ].split( "\n\nEXISTING PRINCIPLES" )[ 0 ] )
    assert [ a[ "field_key" ] for a in answers if "structure" in a ] == [ "budget" ]


# ---- row 5: draft or final ----

def test_answer_read_is_final_for_an_answer_with_no_draft( db, monkeypatch ):
    _switches( monkeypatch, MEANING_INPUT_KEY )
    out, _ = _run( db, _ask( db, answer="no" ), Model( _reply( _result( hypotheses=[ _hyp() ] ) ) ) )
    assert out[ "answer_read" ] == { "$answer": "final" }


def test_answer_read_is_draft_when_the_text_came_from_the_revealed_draft_and_that_field_gets_no_structure( db, monkeypatch ):
    _switches( monkeypatch, MEANING_INPUT_KEY )
    ask = _ask( db, answer="no" )
    _revealed( db, ask, { "value": "unaided draft text" } )
    _meaning( db, ask, native={ "$answer": { "kind": "yes_no_stance", "selected_option_ids": [ "x#o1" ], "empty_selection": False, "write_in_text": None, "referred_option_ids": [], "text": "no" } }, conditions=[] )
    model  = Model( _reply( _result( hypotheses=[ _hyp() ] ) ) )
    out, _ = _run( db, ask, model )
    assert out[ "answer_read" ] == { "$answer": "draft" } and "unaided draft text" in model.sent[ 0 ] and "x#o1" not in model.sent[ 0 ]


def test_an_unparseable_reply_still_reports_answer_read( db, monkeypatch ):
    _switches( monkeypatch, MEANING_INPUT_KEY )
    out, _ = _run( db, _ask( db, answer="no" ), Model( "not json" ) )
    assert out[ "status" ] == "unparseable" and out[ "answer_read" ] == { "$answer": "final" }


def test_a_skipped_answer_reports_no_answer_read( db, monkeypatch ):
    _switches( monkeypatch, MEANING_INPUT_KEY )
    out, _ = _run( db, _ask( db, answer="purple elephant" ), Model( _reply() ) )
    assert out[ "status" ] == "skipped_nothing_to_read" and "answer_read" not in out


# ---- meaning_structure ----

def test_meaning_structure_gives_none_for_a_field_the_record_lacks():
    assert meaning_structure( NATIVE, CONDITIONS, "missing" ) is None


def test_meaning_structure_keeps_a_condition_only_for_the_whole_answer_or_this_fields_own_ids():
    got = meaning_structure( NATIVE, CONDITIONS, "held_bugs" )
    assert [ c[ "modifies_option_id" ] for c in got[ "conditions" ] ] == [ "held_bugs#o2", None ]
    assert meaning_structure( NATIVE, [ { "text": "t", "modifies_option_id": "held_bugs#o1" } ], "held_bugs" )[ "conditions" ] == [ { "text": "t", "modifies_option_id": "held_bugs#o1" } ], "a referred option counts"
    assert meaning_structure( NATIVE, CONDITIONS, "budget" )[ "conditions" ] == [ { "text": "for everything", "modifies_option_id": None } ]


# ---- row 6: the decision stage ----

def test_the_stage_prompt_extends_the_old_one():
    assert STAGE_SYSTEM_PROMPT.startswith( SYSTEM_PROMPT ) and STAGE_SYSTEM_PROMPT != SYSTEM_PROMPT
    assert "who_decides" in STAGE_SYSTEM_PROMPT and "what_to_do_once_asked" in STAGE_SYSTEM_PROMPT and "who_decides" not in SYSTEM_PROMPT


def test_a_version_has_no_tag_with_every_switch_off_and_one_plus_tag_per_switch_that_is_on_in_registry_order():
    assert extractor_version_of( "m" ) == f"m:{PROMPT_VERSION}" and extractor_version_of( "m", ( "stage", ) ) == f"m:{PROMPT_VERSION}+stage"
    assert extractor_version_of( "m", ( "a", "b" ) ) == f"m:{PROMPT_VERSION}+a+b"
    only_stage = lambda key: key == DECISION_STAGE_KEY
    assert [ tag for _, tag in VERSION_TAGS ] == [ "bareyes", "uninformative", "unread", "dedup", "stage" ] and VERSION_TAGS[ -1 ] == ( DECISION_STAGE_KEY, "stage" )
    assert active_tags( lambda key: False ) == () and active_tags( only_stage ) == ( "stage", ) and active_tags( lambda key: True ) == ( "bareyes", "uninformative", "unread", "dedup", "stage" )
    assert current_extractor_version( "m", only_stage ) == f"m:{PROMPT_VERSION}+stage" and current_extractor_version( "m", lambda key: False ) == f"m:{PROMPT_VERSION}"
    assert current_extractor_version( "m", lambda key: True ) == f"m:{PROMPT_VERSION}+bareyes+uninformative+unread+dedup+stage"
    assert active_prompt_version( only_stage ) == f"{PROMPT_VERSION}+stage" and active_prompt_version( lambda key: False ) == PROMPT_VERSION


def test_the_live_version_reads_the_ini_file_and_is_untagged_as_shipped():
    assert active_tags() == () and current_extractor_version( "m" ) == f"m:{PROMPT_VERSION}" and active_prompt_version() == PROMPT_VERSION


def test_the_job_writes_under_the_version_every_reader_asks_for( db, monkeypatch ):
    _switches( monkeypatch, DECISION_STAGE_KEY )
    _run( db, _ask( db, answer="no" ), Model( _reply( _result( hypotheses=[ _hyp() ] ) ) ) )
    assert { row.extractor_version for row in db.query( PreferenceEvidence ) } == { current_extractor_version( MODEL, lambda key: key == DECISION_STAGE_KEY ) }


def test_the_committed_prompts_are_what_build_user_prompt_writes_today():
    for case in _fixture()[ "cases" ].values():
        entries = [ { "field_key": "respin", "text": case[ "answer_text" ], "bare_yes": False, "possibly_influenced": False,
                      "structure": { "option_ids": [ "respin#o1" ], "write_in_text": None, "referred_option_ids": [], "conditions": [] } } ]
        assert build_user_prompt( _fixture()[ "episode" ], entries, [] ) == case[ "prompt" ]


@pytest.mark.parametrize( "case, stage", [ ( "what_to_do_once_asked", "what_to_do_once_asked" ), ( "who_decides", "who_decides" ) ] )
def test_a_real_model_reply_is_read_by_the_real_reader_and_its_stage_is_stored_on_the_evidence_row( db, monkeypatch, case, stage ):
    _switches( monkeypatch, DECISION_STAGE_KEY )
    reply = _fixture()[ "cases" ][ case ][ "reply" ]
    ask   = _ask( db, response_type="multiple_choice", response_options={ "questions": [ { "header": "respin", "question": "Re-spin the idle agent?",
                                                                                     "options": [ { "label": "Yes, re-spin this agent now" }, { "label": "Ask me before re-spinning" } ] } ] },
                  response_value={ "value": json.dumps( { "answers": { "respin": _fixture()[ "cases" ][ case ][ "answer_text" ] } } ), "source": "ui", "answered_by": { "user_id": str( OWNER ) } } )
    assert parse_reply( reply )[ 0 ][ "decision_stage" ] == stage
    out, _ = _run( db, ask, Model( reply ) )
    rows   = db.query( PreferenceEvidence ).all()
    assert out[ "status" ] == "extracted" and rows and { row.decision_stage for row in rows } == { stage }
    assert { row.extractor_version for row in rows } == { f"{MODEL}:{PROMPT_VERSION}+stage" }


@pytest.mark.parametrize( "given", [ "third_value", None, 7 ] )
def test_a_stage_that_is_not_one_of_the_two_values_is_stored_as_none( db, monkeypatch, given ):
    _switches( monkeypatch, DECISION_STAGE_KEY )
    out, _ = _run( db, _ask( db, answer="no" ), Model( _reply( { **_result( hypotheses=[ _hyp() ] ), "decision_stage": given } ) ) )
    assert out[ "status" ] == "extracted" and db.query( PreferenceEvidence ).one().decision_stage is None


def test_a_reply_with_no_stage_key_stores_none_under_the_stage_switch( db, monkeypatch ):
    _switches( monkeypatch, DECISION_STAGE_KEY )
    _run( db, _ask( db, answer="no" ), Model( _reply( _result( hypotheses=[ _hyp() ] ) ) ) )
    assert db.query( PreferenceEvidence ).one().decision_stage is None and _counts( db ) == ( 1, 1 )
