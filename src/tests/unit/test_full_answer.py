"""
The full-answer reply parser, tested over literal replies; no test calls a model.

Each test names what it would catch:
  - a reply field read wrongly or dropped                           -> test_parse_reads_*
  - a refusal stored under the wrong reason, or with a forecast      -> test_a_refused_reply_*, test_every_refusal_reason_*
  - the switch changing today's prompt, reply, version or episode    -> test_switch_off_*
  - a forecaster arm that bypasses parse_reply                       -> test_every_forecaster_arm_uses_parse_reply
"""

import asyncio
import copy
import json
import os
import uuid
from datetime import datetime, timezone

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import cosa.agents.prediction_engine.context_baseline as cb
import cosa.agents.prediction_engine.episode_view as ev
import cosa.agents.prediction_engine.full_answer as fa
from cosa.agents.prediction_engine.forecaster_arms import FORECASTER_ARMS
from cosa.agents.prediction_engine.principles_forecast import CapGate
from cosa.research.preference_replay import scratch_db  # noqa: F401  registers the one shared SQLite hooks for JSONB and Vector
from cosa.rest.postgres_models import Notification, PredictionArmForecast, PredictionLog

T0        = datetime( 2026, 11, 10, 12, 0, tzinfo=timezone.utc )
RECIPIENT = uuid.UUID( "00000000-0000-4000-8000-0000000000bb" )
SENDER    = "claude.code@lupin.deepily.ai#ab12cd34"
PLAN_A    = "o1-ed5327"
PLAN_B    = "o2-1f4725"
DOCS      = "o1-7af023"
TESTS     = "o2-e5c9d7"
CHOICES   = { "questions": [
    { "header": "Plan", "question": "Which plan?", "options": [ { "label": "Plan A", "description": "the safe one" }, { "label": "Plan B (Recommended)" } ] },
    { "header": "Extras", "question": "Which extras?", "multi_select": True, "options": [ { "label": "Docs" }, { "label": "Tests" } ] },
    { "header": "Note", "question": "Anything else?", "input_type": "text" },
] }
BATCH     = { "questions": [ { "header": "Why", "question": "Why?", "input_type": "text" }, { "header": "When", "question": "When?", "input_type": "text" } ] }


@pytest.fixture
def factory( monkeypatch ):
    """Give a session factory over empty copies of the three tables the job reads or writes."""
    engine = create_engine( "sqlite://", connect_args={ "check_same_thread": False }, poolclass=StaticPool )
    for model in ( Notification, PredictionLog, PredictionArmForecast ): model.__table__.create( engine )
    monkeypatch.setattr( ev, "pool_limit", lambda: 50 )
    yield lambda: Session( engine )
    engine.dispose()


@pytest.fixture
def on( monkeypatch ):
    """Switch the full-answer reply on wherever the modules read it."""
    monkeypatch.setattr( fa, "full_answer_enabled", lambda: True )


def ask( factory, **extra ):
    """Insert one ask to the test recipient and return its id as text."""
    row = dict( id=uuid.uuid4(), sender_id=SENDER, recipient_id=RECIPIENT, title="Ship it?", message="Should the worker ship?", abstract="Plan in [the task](/app/tasks/approve?row=abc)",
                type="task", priority="medium", created_at=T0, response_requested=True, response_type="yes_no", response_default="no", timeout_seconds=120 )
    row.update( extra )
    with factory() as db:
        db.add( Notification( **row ) )
        db.commit()
    return str( row[ "id" ] )


def card( factory, kind ):
    """Return the notification id of a card of one type."""
    return { "yes_no"           : lambda: ask( factory ),
             "multiple_choice"  : lambda: ask( factory, response_type="multiple_choice", response_options=CHOICES ),
             "open_ended"       : lambda: ask( factory, response_type="open_ended", response_default=None ),
             "open_ended_batch" : lambda: ask( factory, response_type="open_ended_batch", response_options=BATCH, response_default=None ) }[ kind ]()


def episode( factory, kind ):
    """Return episode_view's result for a new card of one type."""
    with factory() as db: return ev.episode_view( db, card( factory, kind ), limit=50 )


def good( kind ):
    """Return a reply for one card type that the parser accepts."""
    reply = { "acts"                   : { act: 0.1 for act in fa.ACTS },
              "qualification"          : { "probability": 0.25, "conditions": [ { "text": "leave the configuration alone", "modifies_option_id": None } ] },
              "gist"                   : "yes, but leave the configuration alone",
              "whole_card_probability" : 0.6 }
    if kind == "yes_no": reply[ "probabilities" ] = { "yes": 0.7, "no": 0.2, "neither": 0.1 }
    if kind == "multiple_choice": reply[ "fields" ] = { "Plan": { "option_ids": [ PLAN_B ] }, "Extras": { "option_ids": [ DOCS, TESTS ] } }
    if kind == "open_ended_batch": reply[ "fields" ] = { "Why": { "gist": "it is ready" }, "When": { "gist": "today" } }
    return reply


def changed( kind, edit ):
    """Return the good reply for a card type after an edit function changed it."""
    reply = copy.deepcopy( good( kind ) )
    edit( reply )
    return reply


def test_the_stable_option_id_is_the_position_id_and_a_label_hash_pinned_to_literals():
    assert fa.stable_option_id( "o1", "Plan A" ) == PLAN_A and fa.stable_option_id( "o2", " Docs " ) == "o2-7af023"
    assert fa.stable_option_id( "o1", "Plan A" ) != fa.stable_option_id( "o1", "Plan B" ), "a changed label is a new id"
    assert fa.stable_option_id( "o3", "Plan A" ) != PLAN_A, "and so is a changed position"


def test_the_episode_gives_each_option_a_stable_id_only_when_the_switch_is_on( factory, on ):
    with_ids = episode( factory, "multiple_choice" )
    assert [ o[ "stable_id" ] for o in with_ids[ "fields" ][ 0 ][ "options" ] ] == [ PLAN_A, PLAN_B ]
    assert [ o[ "id" ] for o in with_ids[ "fields" ][ 0 ][ "options" ] ] == [ "o1", "o2" ], "the position id the other readers use is unchanged"
    assert fa.option_ids_of( with_ids[ "fields" ][ 1 ] ) == [ DOCS, TESTS ]
    assert all( "stable_id" not in o for f in ev.fields_of( CHOICES, None )  for o in f[ "options" ] ), "fields_of adds the key only on request"


def test_switch_off_the_episode_has_no_stable_id( factory, monkeypatch ):
    monkeypatch.setattr( fa, "full_answer_enabled", lambda: False )
    assert all( "stable_id" not in o for f in episode( factory, "multiple_choice" )[ "fields" ] for o in f[ "options" ] )


def test_the_switch_ships_on_in_the_ini():
    # Rick turned the full-answer reply on for the re-run, 24 Nov 2026; the code default stays off for an unreadable INI
    lines = [ l for l in open( f"{os.environ[ 'LUPIN_ROOT' ]}/src/conf/lupin-app.ini" ) if l.startswith( fa.SWITCH_KEY ) ]
    assert len( lines ) == 1 and lines[ 0 ].split( "=" )[ 1 ].strip() == "true"


def test_the_switch_reads_the_ini_and_reads_off_when_it_is_unreadable( monkeypatch, capsys ):
    class Settings:
        answer = True
        def __init__( self, env_var_name ): pass
        def get( self, key, default=None, return_type=None ):
            assert key == fa.SWITCH_KEY and default is False and return_type == "boolean"
            return Settings.answer
    monkeypatch.setattr( fa, "ConfigurationManager", Settings )
    assert fa.full_answer_enabled() is True
    Settings.answer = False
    assert fa.full_answer_enabled() is False
    def broken( env_var_name ): raise OSError( "no settings" )
    monkeypatch.setattr( fa, "ConfigurationManager", broken )
    assert fa.full_answer_enabled() is False and "treated as off" in capsys.readouterr().out


def test_parse_reads_every_field_of_a_yes_no_reply( factory ):
    record = fa.parse_full_reply( json.dumps( good( "yes_no" ) ), episode( factory, "yes_no" ) )
    assert record == { "value": "yes", "probabilities": { "yes": 0.7, "no": 0.2, "neither": 0.1 }, "acts": { act: 0.1 for act in fa.ACTS },
                       "qualification": { "probability": 0.25, "conditions": [ { "text": "leave the configuration alone", "modifies_option_id": None } ] },
                       "qualifier": "leave the configuration alone", "gist": "yes, but leave the configuration alone", "whole_card_probability": 0.6, "confidence": 0.7 }


@pytest.mark.parametrize( "stances,value", [
    ( { "yes": 0.2, "no": 0.2, "neither": 0.6 }, "neither" ),
    ( { "yes": 0.1, "no": 0.7, "neither": 0.2 }, "no" ),
    ( { "yes": 0.4, "no": 0.4, "neither": 0.2 }, "yes" ),
    ( { "yes": 0.2, "no": 0.4, "neither": 0.4 }, "no" ),
] )
def test_parse_picks_the_likeliest_stance_with_ties_going_to_yes_then_no_then_neither( factory, stances, value ):
    reply  = changed( "yes_no", lambda r: r.update( probabilities=stances ) )
    record = fa.parse_full_reply( json.dumps( reply ), episode( factory, "yes_no" ) )
    assert record[ "value" ] == value and record[ "confidence" ] == stances[ value ]


def test_parse_reads_a_multiple_choice_reply_by_option_id_and_gives_the_labels_back( factory ):
    record = fa.parse_full_reply( json.dumps( good( "multiple_choice" ) ), episode( factory, "multiple_choice" ) )
    assert record[ "fields" ] == { "Plan": { "option_ids": [ PLAN_B ] }, "Extras": { "option_ids": [ DOCS, TESTS ] } }
    assert record[ "answers" ] == { "Plan": "Plan B (Recommended)", "Extras": [ "Docs", "Tests" ] }
    assert "value" not in record and record[ "confidence" ] == 0.6, "a card with fields has no yes/no value, and its confidence is the whole-card probability"


def test_parse_reads_a_write_in_and_a_reframe_and_leaves_them_out_of_the_labels( factory ):
    reply  = changed( "multiple_choice", lambda r: r.update( fields={ "Plan": { "write_in": " Plan C " }, "Extras": { "reframe": "ask about docs first" } } ) )
    record = fa.parse_full_reply( json.dumps( reply ), episode( factory, "multiple_choice" ) )
    assert record[ "fields" ] == { "Plan": { "write_in": "Plan C" }, "Extras": { "reframe": "ask about docs first" } } and record[ "answers" ] == {}


def test_parse_ties_a_condition_to_the_option_it_changes( factory ):
    reply  = changed( "multiple_choice", lambda r: r[ "qualification" ][ "conditions" ].append( { "text": "only with the docs", "modifies_option_id": DOCS } ) )
    record = fa.parse_full_reply( json.dumps( reply ), episode( factory, "multiple_choice" ) )
    assert record[ "qualification" ][ "conditions" ][ 1 ] == { "text": "only with the docs", "modifies_option_id": DOCS }
    assert record[ "qualifier" ] == "leave the configuration alone; only with the docs"


# A reply Haiku (the context model) gave on 24 Nov 2026 to the yes/no prompt this file's cards build, taken verbatim from a bounded Claude Code call.
REAL_HAIKU_YES_NO = ( '{"probabilities": {"yes": 0.5, "no": 0.2, "neither": 0.3}, "acts": {"approve": 0.5, "decline": 0.15, "challenge_premise": 0.03, '
                      '"request_information": 0.15, "defer": 0.1, "propose_alternative": 0.05}, "qualification": {"probability": 0.4, "conditions": '
                      '[{"text": "The plan in the linked task is acceptable to them after they review it", "modifies_option_id": null}]}, '
                      '"gist": "Likely a yes to shipping, but only after they check the plan in the linked task; the card gives too little detail to be confident.", '
                      '"whole_card_probability": 0.45}' )


def test_a_real_haiku_yes_no_reply_parses_under_the_yes_no_format( factory ):
    record = fa.parse_full_reply( REAL_HAIKU_YES_NO, episode( factory, "yes_no" ) )
    assert record[ "value" ] == "yes" and record[ "confidence" ] == 0.5
    assert record[ "qualification" ][ "conditions" ] == [ { "text": "The plan in the linked task is acceptable to them after they review it", "modifies_option_id": None } ]


@pytest.mark.parametrize( "kind, written", [ ( "yes_no", "yes" ), ( "yes_no", "approve" ), ( "open_ended", "approve" ), ( "open_ended_batch", "o1-000000" ) ] )
def test_an_option_id_a_model_writes_on_a_card_with_no_option_ids_is_read_as_no_option( factory, kind, written ):
    # The probe's failure: 9 of 10 Haiku yes/no replies wrote yes or approve here and were refused as unknown_option_id.
    reply  = changed( kind, lambda r: r[ "qualification" ][ "conditions" ][ 0 ].update( { "modifies_option_id": written } ) )
    record = fa.parse_full_reply( json.dumps( reply ), episode( factory, kind ) )
    assert record[ "qualification" ][ "conditions" ] == [ { "text": "leave the configuration alone", "modifies_option_id": None } ]


def test_a_multiple_choice_card_still_refuses_a_condition_on_an_option_it_lacks( factory ):
    reply = changed( "multiple_choice", lambda r: r[ "qualification" ][ "conditions" ][ 0 ].update( { "modifies_option_id": "yes" } ) )
    with pytest.raises( fa.ReplyRefused ) as caught: fa.parse_full_reply( json.dumps( reply ), episode( factory, "multiple_choice" ) )
    assert caught.value.reason == fa.REASON_UNKNOWN_OPTION_ID


def test_the_formats_of_the_cards_with_no_option_ids_say_null_and_the_choice_format_asks_for_an_id():
    for kind in ( "yes_no", "open_ended", "open_ended_batch" ):
        assert '"modifies_option_id": null' in fa.FULL_FORMATS[ kind ] and "<an option id>" not in fa.FULL_FORMATS[ kind ]
        assert "no option ids, so modifies_option_id is always null" in fa.FULL_FORMATS[ kind ]
    assert '"modifies_option_id": "<an option id> or null"' in fa.CHOICE_FULL_FORMAT and "always null" not in fa.CHOICE_FULL_FORMAT


def test_parse_reads_an_open_ended_and_a_batch_reply_as_a_gist_with_acts_and_conditions( factory ):
    opened = fa.parse_full_reply( json.dumps( good( "open_ended" ) ), episode( factory, "open_ended" ) )
    assert opened[ "gist" ] == "yes, but leave the configuration alone" and opened[ "confidence" ] == 0.6 and "fields" not in opened and "value" not in opened
    assert opened[ "acts" ][ "approve" ] == 0.1 and opened[ "qualification" ][ "probability" ] == 0.25
    batch  = fa.parse_full_reply( json.dumps( good( "open_ended_batch" ) ), episode( factory, "open_ended_batch" ) )
    assert batch[ "fields" ] == { "Why": { "gist": "it is ready" }, "When": { "gist": "today" } } and "answers" not in batch


def test_parse_reads_a_reply_inside_a_code_fence_and_with_no_conditions( factory ):
    reply  = changed( "yes_no", lambda r: r[ "qualification" ].update( conditions=[] ) )
    record = fa.parse_full_reply( "Here:\n```json\n" + json.dumps( reply ) + "\n```", episode( factory, "yes_no" ) )
    assert record[ "qualifier" ] is None and record[ "qualification" ][ "conditions" ] == []


def edit_and_expect( kind, edit, reason ):
    """Make one refusal case from a card type, an edit and the reason."""
    return pytest.param( kind, changed( kind, edit ), reason, id=f"{reason}-{kind}-{len( str( edit.__code__.co_consts ) )}-{edit.__code__.co_firstlineno}" )


def probs( value ):
    """Return an edit that replaces the stance probabilities."""
    return lambda reply: reply.update( probabilities=value )


def drop( *path ):
    """Return an edit that removes the member at a path."""
    def run( reply ):
        target = reply
        for key in path[ :-1 ]: target = target[ key ]
        del target[ path[ -1 ] ]
    return run


def put( path, value ):
    """Return an edit that sets the member at a path."""
    def run( reply ):
        target = reply
        for key in path[ :-1 ]: target = target[ key ]
        target[ path[ -1 ] ] = value
    return run


REFUSALS = [
    edit_and_expect( "yes_no", probs( { "yes": 0.5, "no": 0.2, "neither": 0.1 } ),                    fa.REASON_NOT_NORMALISED ),
    edit_and_expect( "yes_no", probs( { "yes": 1.5, "no": -0.5, "neither": 0.0 } ),                   fa.REASON_NOT_NORMALISED ),
    edit_and_expect( "yes_no", probs( { "yes": True, "no": 0.0, "neither": 0.0 } ),                   fa.REASON_NOT_NORMALISED ),
    edit_and_expect( "yes_no", probs( { "yes": "most", "no": 0.2, "neither": 0.1 } ),                 fa.REASON_NOT_NORMALISED ),
    edit_and_expect( "yes_no", put( ( "acts", "defer" ), 2 ),                                         fa.REASON_NOT_NORMALISED ),
    edit_and_expect( "yes_no", put( ( "qualification", "probability" ), "likely" ),                   fa.REASON_NOT_NORMALISED ),
    edit_and_expect( "yes_no", put( ( "whole_card_probability", ), -1 ),                              fa.REASON_NOT_NORMALISED ),
    edit_and_expect( "multiple_choice", put( ( "fields", "Plan", "option_ids" ), [ "o9-000000" ] ),   fa.REASON_UNKNOWN_OPTION_ID ),
    edit_and_expect( "multiple_choice", put( ( "fields", "Plan", "option_ids" ), [ "o1-ffffff" ] ),   fa.REASON_UNKNOWN_OPTION_ID ),
    edit_and_expect( "multiple_choice", put( ( "fields", "Plan", "option_ids" ), [ "Plan A" ] ),      fa.REASON_UNKNOWN_OPTION_ID ),
    edit_and_expect( "multiple_choice", put( ( "qualification", "conditions" ), [ { "text": "x", "modifies_option_id": "o7-123456" } ] ), fa.REASON_UNKNOWN_OPTION_ID ),
    edit_and_expect( "yes_no", drop( "probabilities" ),                                                fa.REASON_FIELD_MISSING ),
    edit_and_expect( "yes_no", probs( { "yes": 0.7, "no": 0.3 } ),                                    fa.REASON_FIELD_MISSING ),
    edit_and_expect( "yes_no", drop( "acts" ),                                                        fa.REASON_FIELD_MISSING ),
    edit_and_expect( "yes_no", drop( "acts", "defer" ),                                               fa.REASON_FIELD_MISSING ),
    edit_and_expect( "yes_no", drop( "qualification" ),                                               fa.REASON_FIELD_MISSING ),
    edit_and_expect( "yes_no", drop( "qualification", "probability" ),                                fa.REASON_FIELD_MISSING ),
    edit_and_expect( "yes_no", put( ( "qualification", "conditions" ), "none" ),                      fa.REASON_FIELD_MISSING ),
    edit_and_expect( "yes_no", put( ( "qualification", "conditions" ), [ "leave it" ] ),              fa.REASON_FIELD_MISSING ),
    edit_and_expect( "yes_no", put( ( "qualification", "conditions" ), [ { "modifies_option_id": None } ] ), fa.REASON_FIELD_MISSING ),
    edit_and_expect( "yes_no", put( ( "qualification", "conditions" ), [ { "text": "  ", "modifies_option_id": None } ] ), fa.REASON_FIELD_MISSING ),
    edit_and_expect( "yes_no", drop( "whole_card_probability" ),                                       fa.REASON_FIELD_MISSING ),
    edit_and_expect( "yes_no", drop( "gist" ),                                                        fa.REASON_FIELD_MISSING ),
    edit_and_expect( "yes_no", put( ( "gist", ), 7 ),                                                 fa.REASON_FIELD_MISSING ),
    edit_and_expect( "multiple_choice", drop( "fields" ),                                             fa.REASON_FIELD_MISSING ),
    edit_and_expect( "multiple_choice", drop( "fields", "Extras" ),                                   fa.REASON_FIELD_MISSING ),
    edit_and_expect( "multiple_choice", put( ( "fields", "Plan" ), PLAN_A ),                          fa.REASON_FIELD_MISSING ),
    edit_and_expect( "multiple_choice", put( ( "fields", "Plan" ), { "option_ids": [ PLAN_A ], "write_in": "C" } ), fa.REASON_FIELD_MISSING ),
    edit_and_expect( "multiple_choice", put( ( "fields", "Plan" ), {} ),                              fa.REASON_FIELD_MISSING ),
    edit_and_expect( "multiple_choice", put( ( "fields", "Plan", "option_ids" ), [ PLAN_A, PLAN_B ] ), fa.REASON_FIELD_MISSING ),
    edit_and_expect( "multiple_choice", put( ( "fields", "Extras", "option_ids" ), [] ),              fa.REASON_FIELD_MISSING ),
    edit_and_expect( "multiple_choice", put( ( "fields", "Extras", "option_ids" ), [ DOCS, DOCS ] ),  fa.REASON_FIELD_MISSING ),
    edit_and_expect( "multiple_choice", put( ( "fields", "Plan", "option_ids" ), PLAN_A ),            fa.REASON_FIELD_MISSING ),
    edit_and_expect( "multiple_choice", put( ( "fields", "Plan" ), { "write_in": " " } ),             fa.REASON_FIELD_MISSING ),
    edit_and_expect( "open_ended_batch", put( ( "fields", "Why" ), "because" ),                       fa.REASON_FIELD_MISSING ),
    edit_and_expect( "open_ended_batch", put( ( "fields", "Why" ), { "gist": "" } ),                  fa.REASON_FIELD_MISSING ),
    edit_and_expect( "open_ended_batch", drop( "fields", "When" ),                                    fa.REASON_FIELD_MISSING ),
    edit_and_expect( "yes_no", probs( { "yes": 0.5, "no": 0.2, "neither": 0.1, "maybe": 0.2 } ),      fa.REASON_STANCE_NOT_IN_VOCAB ),
    edit_and_expect( "yes_no", put( ( "acts", "shrug" ), 0.3 ),                                       fa.REASON_STANCE_NOT_IN_VOCAB ),
]


@pytest.mark.parametrize( "kind,reply,reason", REFUSALS )
def test_the_parser_refuses_each_bad_reply_with_the_reason_that_names_it( factory, kind, reply, reason ):
    with pytest.raises( fa.ReplyRefused ) as refusal: fa.parse_full_reply( json.dumps( reply ), episode( factory, kind ) )
    assert refusal.value.reason == reason and str( refusal.value ).startswith( reason + ": " )
    assert isinstance( refusal.value, ValueError )


@pytest.mark.parametrize( "text,detail", [
    ( "no braces at all", "the reply holds no JSON object" ),
    ( "[1]",              "the reply holds no JSON object" ),
    ( '"yes"',            "the reply holds no JSON object" ),
] )
def test_the_parser_refuses_text_that_is_not_a_json_object( factory, text, detail ):
    with pytest.raises( fa.ReplyRefused, match=detail ) as refusal: fa.parse_full_reply( text, episode( factory, "yes_no" ) )
    assert refusal.value.reason == fa.REASON_REPLY_NOT_JSON


@pytest.mark.parametrize( "reply,detail", [ ( { "abstain": True, "reason": "the card is unclear" }, "the card is unclear" ), ( { "abstain": True }, "no reason given" ) ] )
def test_the_parser_reports_the_models_own_abstention_as_model_abstained( factory, reply, detail ):
    with pytest.raises( fa.ReplyRefused, match=detail ) as refusal: fa.parse_full_reply( json.dumps( reply ), episode( factory, "yes_no" ) )
    assert refusal.value.reason == fa.REASON_MODEL_ABSTAINED


def test_a_multiple_choice_card_with_no_field_to_forecast_is_refused_as_a_missing_field( factory ):
    only_text = ask( factory, response_type="multiple_choice", response_options={ "questions": [ { "header": "Note", "question": "Why?", "input_type": "text" } ] } )
    with factory() as db: ep = ev.episode_view( db, only_text, limit=50 )
    with pytest.raises( fa.ReplyRefused, match="no field to forecast" ) as refusal: fa.parse_full_reply( json.dumps( { **good( "multiple_choice" ), "fields": {} } ), ep )
    assert refusal.value.reason == fa.REASON_FIELD_MISSING


def test_there_are_exactly_six_refusal_reasons_pinned_to_their_strings():
    assert fa.REFUSAL_REASONS == ( "reply_not_json", "probabilities_not_normalised", "unknown_option_id", "field_missing", "stance_not_in_vocabulary", "model_abstained" )
    assert { param.values[ 2 ] for param in REFUSALS } | { fa.REASON_REPLY_NOT_JSON, fa.REASON_MODEL_ABSTAINED } == set( fa.REFUSAL_REASONS ), "every reason has a case"


def replying( text ):
    """Build an SDK stand-in that always answers with one text."""
    async def query( prompt, options ):
        yield AssistantMessage( content=[ TextBlock( text ) ], model=options.model )
    return query


def run_full( factory, tmp_path, kind, text ):
    """Run the baseline job on one card and return ( result, stored row )."""
    c0     = cb.ContextBaseline( "haiku-x", 5, cb.ALL_LAYERS, cb.open_ledger( str( tmp_path / "ledger.jsonl" ) ), query_fn=replying( text ), full=True )
    result = asyncio.run( cb.run_context_forecast( card( factory, kind ), session_factory=factory, c0=c0, gate=CapGate( 2 ), enabled=True ) )
    with factory() as db: return result, db.query( PredictionArmForecast ).one()


@pytest.mark.parametrize( "kind,text,reason", [
    ( "yes_no",          "no braces at all",                                                      fa.REASON_REPLY_NOT_JSON ),
    ( "yes_no",          json.dumps( changed( "yes_no", probs( { "yes": 0.5, "no": 0.2, "neither": 0.1 } ) ) ), fa.REASON_NOT_NORMALISED ),
    ( "multiple_choice", json.dumps( changed( "multiple_choice", put( ( "fields", "Plan", "option_ids" ), [ "o9-000000" ] ) ) ), fa.REASON_UNKNOWN_OPTION_ID ),
    ( "open_ended_batch", json.dumps( changed( "open_ended_batch", drop( "fields", "When" ) ) ),  fa.REASON_FIELD_MISSING ),
    ( "yes_no",          json.dumps( changed( "yes_no", put( ( "acts", "shrug" ), 0.3 ) ) ),      fa.REASON_STANCE_NOT_IN_VOCAB ),
    ( "yes_no",          json.dumps( { "abstain": True, "reason": "unclear" } ),                  fa.REASON_MODEL_ABSTAINED ),
] )
def test_every_refusal_reason_is_stored_on_an_abstention_row_with_no_forecast_value( factory, tmp_path, kind, text, reason ):
    result, row = run_full( factory, tmp_path, kind, text )
    assert result == { "status": "failed", "reason": reason }
    assert row.abstention_reason == reason, "the exact reason string is on the stored row"
    assert row.forecast is None and row.forecast_ready_at is None, "and no forecast value is"


def test_a_good_full_reply_is_stored_as_the_forecast_record_with_no_abstention( factory, tmp_path ):
    result, row = run_full( factory, tmp_path, "multiple_choice", json.dumps( good( "multiple_choice" ) ) )
    assert result == { "status": "ran", "reason": None } and row.abstention_reason is None
    assert row.forecast[ "answers" ] == { "Plan": "Plan B (Recommended)", "Extras": [ "Docs", "Tests" ] } and row.forecast[ "fields" ][ "Plan" ] == { "option_ids": [ PLAN_B ] }


def test_a_full_reply_for_an_open_ended_card_is_stored_where_the_old_reply_was_refused( factory, tmp_path ):
    result, row = run_full( factory, tmp_path, "open_ended", json.dumps( good( "open_ended" ) ) )
    assert result[ "status" ] == "ran" and row.forecast[ "gist" ] == "yes, but leave the configuration alone"


def test_the_full_prompt_names_each_option_by_its_stable_id_and_asks_for_the_full_reply( factory, on ):
    text = cb.build_full_user_prompt( episode( factory, "multiple_choice" ) )
    assert f'[{PLAN_A}] "Plan A"; [{PLAN_B}] "Plan B (Recommended)"' in text and f'[{DOCS}] "Docs"' in text and text.endswith( fa.CHOICE_FULL_FORMAT )
    assert cb.YES_NO_FORMAT not in text and cb.CHOICE_FORMAT not in text and '"Plan A" - the safe one' in text, "the old format is replaced and the card text is the old builder's"
    assert "Option ids" not in cb.build_full_user_prompt( episode( factory, "multiple_choice" ), ( "prompt", ) ), "no ids without the options layer"
    assert cb.build_full_user_prompt( episode( factory, "yes_no" ) ).endswith( fa.YES_NO_FULL_FORMAT ) and "Option ids" not in cb.build_full_user_prompt( episode( factory, "yes_no" ) )
    assert cb.build_full_user_prompt( episode( factory, "open_ended" ) ).endswith( fa.OPEN_FULL_FORMAT )
    assert cb.build_full_user_prompt( episode( factory, "open_ended_batch" ) ).endswith( fa.BATCH_FULL_FORMAT )
    assert set( fa.FULL_FORMATS ) == set( fa.FULL_ANSWER_TYPES )


def test_the_full_reply_refuses_a_card_type_it_does_not_read( factory ):
    ep = episode( factory, "yes_no" )
    ep[ "response_type" ] = "review"
    with pytest.raises( cb.UnsupportedAsk ): cb.build_full_user_prompt( ep )
    with pytest.raises( cb.UnsupportedAsk ): cb.parse_full( "{}", ep )


def test_the_baseline_reads_the_switch_once_and_uses_it_for_prompt_parser_and_version( factory, monkeypatch, tmp_path ):
    monkeypatch.setattr( fa, "full_answer_enabled", lambda: True )
    c0 = cb.ContextBaseline( "haiku-x", 5, cb.ALL_LAYERS, cb.open_ledger( str( tmp_path / "ledger.jsonl" ) ) )
    monkeypatch.setattr( fa, "full_answer_enabled", lambda: False )
    ep = episode( factory, "yes_no" )
    assert c0.full is True and c0.build_prompts( ep )[ 1 ].endswith( fa.YES_NO_FULL_FORMAT )
    assert c0.parse( json.dumps( good( "yes_no" ) ), ep )[ "value" ] == "yes"
    assert c0.predictor_version == cb.predictor_version( cb.ALL_LAYERS, True )


def test_a_change_to_the_full_answer_module_is_a_new_predictor_version( monkeypatch ):
    plain, full = cb.predictor_version(), cb.predictor_version( cb.ALL_LAYERS, True )
    assert plain != full
    real = cb.inspect.getsource
    monkeypatch.setattr( cb.inspect, "getsource", lambda target: real( target ) + "# a helper changed" if target is fa else real( target ) )
    assert cb.predictor_version( cb.ALL_LAYERS, True ) != full and cb.predictor_version() == plain, "the helper source joins the hash only while the switch is on"


@pytest.mark.parametrize( "entry", [ "build_full_user_prompt", "parse_full" ] )
def test_a_change_to_either_full_answer_entry_point_is_a_new_version_only_while_the_switch_is_on( monkeypatch, entry ):
    plain, full = cb.predictor_version(), cb.predictor_version( cb.ALL_LAYERS, True )
    real        = cb.inspect.getsource
    monkeypatch.setattr( cb.inspect, "getsource", lambda target: real( target ) + "# changed" if target is getattr( cb, entry ) else real( target ) )
    assert cb.predictor_version( cb.ALL_LAYERS, True ) != full and cb.predictor_version() == plain


# The switch-off pins. build_user_prompt, parse_reply and _choice_of are the hashed source, and this slice leaves them byte for byte
# as they were at a472c7bef, so a switch-off baseline keeps its version, its ledger and its stored rows' version string.
OLD_VERSION = "context-baseline-5352236008"
OLD_PROMPT_TAIL = 'Reply: {"answer": "yes" or "no", "confidence": a number from 0 to 1}.'


def test_switch_off_the_version_the_prompt_the_reply_and_the_row_are_what_they_were( factory, tmp_path, monkeypatch ):
    monkeypatch.setattr( fa, "full_answer_enabled", lambda: False )
    from cosa.repo.doc_lint import model_transport
    old_parts = [ "context-baseline", cb.SYSTEM_PROMPT, ",".join( cb.ALL_LAYERS ), cb.inspect.getsource( cb.build_user_prompt ), cb.inspect.getsource( cb.parse_reply ), cb.inspect.getsource( cb._choice_of ) ]
    assert cb.predictor_version() == model_transport.prompt_version( *old_parts ) == OLD_VERSION, "a switch-off version is the one a472c7bef gave, and hashes none of full_answer"
    ep = episode( factory, "yes_no" )
    assert cb.build_user_prompt( ep ).endswith( OLD_PROMPT_TAIL ) and cb.YES_NO_FORMAT == OLD_PROMPT_TAIL and cb.YES_NO_ANSWERS == ( "yes", "no" )
    assert cb.parse_reply( '{"answer": "yes", "confidence": 0.9}', ep ) == { "value": "yes", "confidence": 0.9 }
    with pytest.raises( ValueError ) as refusal: cb.parse_reply( json.dumps( good( "yes_no" ) ), ep )
    assert not isinstance( refusal.value, fa.ReplyRefused ), "the old parser raises its plain error, which run_arm stores as unreadable_forecast"
    with pytest.raises( cb.UnsupportedAsk ): cb.parse_reply( "{}", episode( factory, "open_ended" ) )
    c0  = cb.ContextBaseline( "haiku-x", 5, cb.ALL_LAYERS, cb.open_ledger( str( tmp_path / "ledger.jsonl" ) ), query_fn=replying( "I would rather not say" ) )
    out = asyncio.run( cb.run_context_forecast( card( factory, "yes_no" ), session_factory=factory, c0=c0, gate=CapGate( 2 ), enabled=True ) )
    with factory() as db: row = db.query( PredictionArmForecast ).one()
    assert c0.full is False and out == { "status": "failed", "reason": "unreadable_forecast" } and row.abstention_reason == "unreadable_forecast" and row.forecast is None


def test_every_forecaster_arm_uses_parse_reply( factory, monkeypatch, tmp_path ):
    assert list( FORECASTER_ARMS ) == [ "C0", "B1", "C0-opus", "B1-opus", "answer_history" ], "the registry is pinned to the five forecasters the plan names"
    seen = []
    monkeypatch.setattr( cb, "parse_reply", lambda text, episode: seen.append( ( "old", text ) ) or { "routed": True } )
    monkeypatch.setattr( fa, "parse_full_reply", lambda text, episode: seen.append( ( "full", text ) ) or { "routed": True } )
    ep = episode( factory, "yes_no" )
    for full, route in ( ( False, "old" ), ( True, "full" ) ):
        c0 = cb.ContextBaseline( "haiku-x", 5, cb.ALL_LAYERS, cb.open_ledger( str( tmp_path / f"ledger-{route}.jsonl" ) ), full=full )
        for arm, parse_of in FORECASTER_ARMS.items():
            assert parse_of( c0 )( arm, ep ) == { "routed": True }
        assert seen == [ ( route, arm ) for arm in FORECASTER_ARMS ], f"each arm's reply reached the {route} parser, in registry order"
        seen.clear()


STANCE_OK = { "yes": 0.5, "no": 0.3, "neither": 0.2 }
ACTS_OK   = { act: 0.1 for act in fa.ACTS }


@pytest.mark.parametrize( "call, parsed, reason, message", [
    ( fa._stance_probabilities, { "probabilities": { **STANCE_OK, "maybe": 0.1 } }, fa.REASON_STANCE_NOT_IN_VOCAB, f"{fa.REASON_STANCE_NOT_IN_VOCAB}: ['maybe'] are not among {fa.STANCES}" ),
    ( fa._stance_probabilities, { "probabilities": { "yes": 0.5, "no": 0.5 } },     fa.REASON_FIELD_MISSING,       f"{fa.REASON_FIELD_MISSING}: probabilities leaves out ['neither']" ),
    ( fa._stance_probabilities, { "probabilities": { **STANCE_OK, "no": "most" } }, fa.REASON_NOT_NORMALISED,      f"{fa.REASON_NOT_NORMALISED}: probability of no must be a number from 0 to 1, got 'most'" ),
    ( fa._stance_probabilities, { "probabilities": "x" },                           fa.REASON_FIELD_MISSING,       f"{fa.REASON_FIELD_MISSING}: probabilities must be an object" ),
    ( fa._acts,                 { "acts": { **ACTS_OK, "shrug": 0.3 } },            fa.REASON_STANCE_NOT_IN_VOCAB, f"{fa.REASON_STANCE_NOT_IN_VOCAB}: ['shrug'] are not among {fa.ACTS}" ),
    ( fa._acts,                 { "acts": { "approve": 0.1 } },                     fa.REASON_FIELD_MISSING,       f"{fa.REASON_FIELD_MISSING}: acts leaves out {[ act for act in fa.ACTS if act != 'approve' ]}" ),
    ( fa._acts,                 { "acts": { **ACTS_OK, "defer": 2 } },              fa.REASON_NOT_NORMALISED,      f"{fa.REASON_NOT_NORMALISED}: act defer must be a number from 0 to 1, got 2" ),
    ( fa._acts,                 {},                                                 fa.REASON_FIELD_MISSING,       f"{fa.REASON_FIELD_MISSING}: acts must be an object" ),
] )
def test_the_stance_and_act_refusal_messages_are_the_words_they_were_before_the_shared_helper( call, parsed, reason, message ):
    with pytest.raises( fa.ReplyRefused ) as refused: call( parsed )
    assert refused.value.reason == reason and str( refused.value ) == message


def test_named_probabilities_reads_every_name_in_vocabulary_order_and_keeps_the_values_unsummed():
    assert fa._named_probabilities( { "acts": ACTS_OK }, "acts", fa.ACTS, "act" ) == ACTS_OK
    assert list( fa._named_probabilities( { "k": { "b": 0.9, "a": 0.9 } }, "k", ( "a", "b" ), "p" ) ) == [ "a", "b" ]
    assert fa._stance_probabilities( { "probabilities": STANCE_OK } ) == STANCE_OK
    with pytest.raises( fa.ReplyRefused, match="stances add up to" ): fa._stance_probabilities( { "probabilities": { "yes": 0.5, "no": 0.3, "neither": 0.1 } } )


def test_an_object_with_one_unknown_name_and_names_left_out_is_refused_for_the_unknown_name_first():
    """The unknown-name check runs before the missing-name check, so that reason wins."""
    with pytest.raises( fa.ReplyRefused ) as refused: fa._named_probabilities( { "acts": { "approve": 0.1, "shrug": 0.3 } }, "acts", fa.ACTS, "act" )
    assert refused.value.reason == fa.REASON_STANCE_NOT_IN_VOCAB and str( refused.value ) == f"{fa.REASON_STANCE_NOT_IN_VOCAB}: ['shrug'] are not among {fa.ACTS}"
