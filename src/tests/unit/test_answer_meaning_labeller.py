"""
Unit tests for the model layer of the meaning labeller.

No test here calls a model: complete_sync is replaced, or the SDK query is a stand-in.
"""

import json
import os
from types import SimpleNamespace

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock

from cosa.agents.answer_meaning import labeller as lb
from cosa.agents.answer_meaning import rules
from cosa.repo.doc_lint import model_transport as mt
from cosa.rest.db.repositories.answer_meaning_repository import RELATIONS_V2

OPTIONS = [ { "id": "o1", "label": "Email (Recommended)", "description": "send it", "recommended": True },
            { "id": "o2", "label": "Page", "description": None, "recommended": False } ]


def field( kind="yes_no_stance", answer="yes [comment: only on Monday]", stance="yes", comment="only on Monday", relation=None, options=() ):
    return { "kind": kind, "prompt": "Q?", "options": list( options ), "answer": answer, "stance": stance, "comment": comment, "relation": relation }


def draft( unknowns=(), **fields ):
    return { "response_type": "yes_no", "card_text": "Do it?", "unknowns": list( unknowns ), "fields": fields or { "answer": field() } }


def entry( key="answer", relation="support", **extra ):
    return dict( { "field_key": key, "relation": relation }, **extra )


@pytest.fixture
def model( monkeypatch ):
    """Stand in for the model: .reply is entries, a string or an error; .calls records."""
    class Model:
        reply = []
        calls = []
        def __call__( self, name, system, user, **options ):
            self.calls.append( ( name, system, user, options ) )
            if isinstance( self.reply, BaseException ): raise self.reply
            return self.reply if isinstance( self.reply, str ) else json.dumps( { "fields": self.reply } )
    stand = Model()
    stand.calls = []
    monkeypatch.setattr( mt, "complete_sync", stand )
    return stand


def test_every_field_decided_by_plain_code_makes_no_call( model ):
    result = lb.label( draft( answer=field( relation="no_comment", comment=None ) ) )
    assert model.calls == []
    assert result[ "native_answer" ] == { "answer": { "kind": "yes_no_stance", "relation": "no_comment" } }
    assert result[ "acts" ] == [] and result[ "conditions" ] == [] and result[ "unknowns" ] == []
    assert result[ "supporting_spans" ] is None and result[ "uncertainty" ] is None


def test_a_labelled_field_keeps_spans_conditions_and_uncertainty( model ):
    model.reply = [ entry( conditions=[ { "text": "only on Monday", "modifies_option_id": "o9" } ], spans=[ "only on Monday", "invented" ], uncertainty=0.2 ) ]
    result = lb.label( draft() )
    assert result[ "native_answer" ][ "answer" ] == { "kind": "yes_no_stance", "relation": "support" }
    assert result[ "conditions" ] == [ { "text": "only on Monday", "modifies_option_id": None, "field_key": "answer" } ]
    assert result[ "supporting_spans" ] == [ { "field_key": "answer", "text": "only on Monday" } ]
    assert result[ "uncertainty" ] == 0.2
    assert model.calls[ 0 ][ 0 ] == "claude-sonnet-5-5"        # the INI value
    assert model.calls[ 0 ][ 3 ][ "timeout_seconds" ] == lb.TIMEOUT_SECONDS


def test_an_option_id_the_card_has_is_kept_and_unquoted_conditions_are_dropped( model ):
    picked      = field( kind="write_in_text", answer="Page, weekly", stance=None, comment=None, options=OPTIONS )
    model.reply = [ entry( "D", "expands_other_option", conditions=[ { "text": "weekly", "modifies_option_id": "o2" }, { "text": "daily" }, "junk", { "text": "  " } ] ) ]
    result      = lb.label( draft( D=picked ) )
    assert result[ "conditions" ] == [ { "text": "weekly", "modifies_option_id": "o2", "field_key": "D" } ]


@pytest.mark.parametrize( "kind,options,expected", [
    ( "yes_no_stance", [], ( "support", "dissent", "re_frame" ) ),
    ( "open_ended_text", [], ( "answers", "declines_or_defers", "re_frame" ) ),
    ( "batch_field_text", [], ( "answers", "declines_or_defers", "re_frame" ) ),
    ( "write_in_text", OPTIONS, ( "expands_recommendation", "expands_other_option", "wrote_own_answer" ) ),
    ( "write_in_text", OPTIONS[ 1: ], ( "no_recommendation_on_card", "wrote_own_answer" ) ),
] )
def test_allowed_relations_by_kind( kind, options, expected ):
    assert lb.allowed_relations( field( kind=kind, options=options ) ) == expected
    assert set( expected ) <= set( RELATIONS_V2 )


def test_a_relation_the_field_does_not_allow_is_unreadable( model ):
    model.reply = [ entry( relation="agrees" ) ]
    result = lb.label( draft() )
    assert result[ "native_answer" ][ "answer" ] == { "kind": "yes_no_stance" }
    assert result[ "unknowns" ] == [ "unreadable_payload" ]


@pytest.mark.parametrize( "reply", [ "not json at all", "[1, 2]", '{"fields": "x"}', '{"fields": ["x", {"relation": "support"}]}', [ ] ] )
def test_an_unusable_reply_records_unreadable_payload_and_keeps_the_row( model, reply ):
    model.reply = reply
    result = lb.label( draft( unknowns=[ "neither" ] ) )
    assert result[ "native_answer" ] == { "answer": { "kind": "yes_no_stance" } }
    assert result[ "unknowns" ] == [ "neither", "unreadable_payload" ]


@pytest.mark.parametrize( "error", [ mt.ModelCallError( "boom" ), mt.ModelCallTimeout( "slow" ) ] )
def test_a_failed_call_records_unreadable_payload( model, capsys, error ):
    model.reply = error
    assert lb.label( draft() )[ "unknowns" ] == [ "unreadable_payload" ]
    assert "model call failed" in capsys.readouterr().out


@pytest.mark.parametrize( "error", [ mt.ModelRateLimited( "r" ), mt.ModelLoginExpired( "l" ), mt.ModelUnavailableError( "u" ), mt.CallBudgetExceeded( "b" ) ] )
def test_an_error_that_would_fail_every_card_stops_the_run( model, error ):
    model.reply = error
    with pytest.raises( type( error ) ):
        lb.label( draft() )


def test_a_field_missing_from_the_reply_is_unreadable_while_the_other_is_labelled( model ):
    two         = { "A": field( kind="batch_field_text", answer="ship it", stance=None, comment=None ), "B": field( kind="batch_field_text", answer="later", stance=None, comment=None ) }
    model.reply = [ entry( "A", "answers", acts=[ "approve", "dance" ] ) ]
    result      = lb.label( draft( **two ) )
    assert result[ "native_answer" ] == { "A": { "kind": "batch_field_text", "relation": "answers" }, "B": { "kind": "batch_field_text" } }
    assert result[ "acts" ] == [ { "act": "approve", "field_key": "A" } ]
    assert result[ "unknowns" ] == [ "unreadable_payload" ]
    assert len( model.calls ) == 1


def test_only_undecided_fields_are_sent( model ):
    fields      = { "A": field( kind="batch_field_text", answer="", stance=None, comment=None, relation="no_answer" ), "B": field( kind="batch_field_text", answer="later", stance=None, comment=None ) }
    model.reply = [ entry( "B", "declines_or_defers" ) ]
    result      = lb.label( draft( **fields ) )
    assert '"field_key": "A"' not in model.calls[ 0 ][ 2 ]
    assert [ f[ "relation" ] for f in result[ "native_answer" ].values() ] == [ "no_answer", "declines_or_defers" ]


def test_acts_are_ignored_off_a_text_field( model ):
    model.reply = [ entry( acts=[ "approve" ] ) ]
    assert lb.label( draft() )[ "acts" ] == []


@pytest.mark.parametrize( "spans,expected", [
    ( [], "re_frame" ),
    ( [ "yes" ], "re_frame" ),          # quoted from the answer string, not from the comment
    ( [ "go ahead" ], "support" ),
] )
def test_a_neither_with_a_comment_is_re_frame_unless_a_comment_span_leans( model, spans, expected ):
    neither     = field( answer="neither [comment: go ahead later] yes", stance="neither", comment="go ahead later" )
    model.reply = [ entry( spans=spans ) ]
    result      = lb.label( draft( unknowns=[ "neither" ], answer=neither ) )
    assert result[ "native_answer" ][ "answer" ][ "relation" ] == expected
    assert result[ "unknowns" ] == [ "neither" ]


def test_a_stance_is_inferred_only_for_a_field_that_had_none( model ):
    raw         = field( answer="Yeah, provided that it is idle", stance=None, comment=None )
    model.reply = [ entry( stance="yes" ) ]
    inferred    = lb.label( draft( unknowns=[ "no_explicit_stance" ], answer=raw ) )
    assert inferred[ "native_answer" ][ "answer" ] == { "kind": "yes_no_stance", "relation": "support", "stance": "yes", "stance_source": "inferred" }
    assert inferred[ "unknowns" ] == [ "no_explicit_stance" ]
    assert "stance" not in lb.label( draft() )[ "native_answer" ][ "answer" ]


@pytest.mark.parametrize( "stance", [ None, "maybe" ] )
def test_a_stance_the_model_cannot_name_is_not_stored( model, stance ):
    model.reply = [ entry( relation="re_frame", stance=stance ) ]
    result      = lb.label( draft( answer=field( answer="Does this append?", stance=None, comment=None ) ) )
    assert result[ "native_answer" ][ "answer" ] == { "kind": "yes_no_stance", "relation": "re_frame" }


@pytest.mark.parametrize( "number,expected", [ ( 0, 0.0 ), ( 1, 1.0 ), ( 1.5, None ), ( -1, None ), ( True, None ), ( "0.2", None ), ( None, None ) ] )
def test_uncertainty_is_a_number_from_0_to_1( model, number, expected ):
    model.reply = [ entry( uncertainty=number ) ]
    assert lb.label( draft() )[ "uncertainty" ] == expected


def test_unsure_adds_uncertain_annotator_once_and_uncertainty_is_the_largest( model ):
    two         = { "A": field( kind="batch_field_text", answer="x", stance=None, comment=None ), "B": field( kind="batch_field_text", answer="y", stance=None, comment=None ) }
    model.reply = [ entry( "A", "answers", unsure=True, uncertainty=0.1 ), entry( "B", "answers", unsure=True, uncertainty=0.6 ) ]
    result      = lb.label( draft( **two ) )
    assert result[ "unknowns" ] == [ "uncertain_annotator" ]
    assert result[ "uncertainty" ] == 0.6


def test_non_list_spans_conditions_and_acts_are_ignored( model ):
    model.reply = [ entry( "A", "answers", spans="x", conditions={ "text": "x" }, acts="approve" ) ]
    result      = lb.label( draft( A=field( kind="batch_field_text", answer="x", stance=None, comment=None ) ) )
    assert result[ "supporting_spans" ] is None and result[ "conditions" ] == [] and result[ "acts" ] == []


def test_the_prompt_holds_no_forecast_outcome_or_id():
    card = draft( answer=field( options=[ dict( OPTIONS[ 0 ], forecast="FORECAST-TEXT", stable_id="STABLE-ID" ) ] ) )
    card.update( forecast="FORECAST-TEXT", notification_id="NOTIFICATION-ID", outcome="OUTCOME-TEXT" )
    card[ "fields" ][ "answer" ].update( prediction="FORECAST-TEXT", predicted_value="FORECAST-TEXT" )
    prompt = lb.build_user_prompt( card, [ "answer" ] )
    for secret in ( "FORECAST-TEXT", "NOTIFICATION-ID", "OUTCOME-TEXT", "STABLE-ID" ):
        assert secret not in prompt
    assert "Do it?" in prompt and "only on Monday" in prompt and "Email (Recommended)" in prompt
    assert "forecast" not in lb.SYSTEM_PROMPT.lower()


def test_the_annotator_names_model_prompt_and_schema_and_moves_with_the_prompt( monkeypatch ):
    before = lb.annotator_of( "m-1" )
    assert before.startswith( "m-1:meaning-labeller-" ) and before.endswith( "+answer-meaning-v2" )
    assert len( lb.annotator_of( lb.model_id() ) ) <= 100
    monkeypatch.setattr( lb, "SYSTEM_PROMPT", lb.SYSTEM_PROMPT + " more" )
    assert lb.annotator_of( "m-1" ) != before


def test_a_given_model_wins_over_the_ini( model ):
    model.reply = [ entry() ]
    lb.label( draft(), model="m-2" )
    assert model.calls[ 0 ][ 0 ] == "m-2"


def test_the_sdk_query_reaches_the_real_transport():
    async def query( prompt, options ):
        assert options.tools == []
        yield AssistantMessage( content=[ TextBlock( text=json.dumps( { "fields": [ entry() ] } ) ) ], model="claude-sonnet-5-5" )
    result = lb.label( draft(), query_fn=query )
    assert result[ "native_answer" ][ "answer" ][ "relation" ] == "support"


# One real reply per label and per model-side unknown, captured from the model and replayed through the real reader.
FIXTURES = os.path.join( os.path.dirname( __file__ ), "fixtures", "answer_meaning_labeller_" )

CAPTURED = {
    "yes_support"               : ( { "answer": "support" }, [] ),
    "yes_dissent"               : ( { "answer": "dissent" }, [] ),
    "neither_re_frame"          : ( { "answer": "re_frame" }, [ "neither" ] ),
    "neither_leans"             : ( { "answer": "support" }, [ "neither" ] ),
    "expands_recommendation"    : ( { "Delivery": "expands_recommendation" }, [] ),
    "expands_other_option"      : ( { "Delivery": "expands_other_option" }, [] ),
    "wrote_own_answer"          : ( { "Delivery": "wrote_own_answer" }, [] ),
    "no_recommendation_on_card" : ( { "Day": "no_recommendation_on_card" }, [] ),
    "open_answers"              : ( { "answer": "answers" }, [] ),
    "open_declines_or_defers"   : ( { "answer": "declines_or_defers" }, [] ),
    "open_re_frame"             : ( { "answer": "re_frame" }, [] ),
    "two_header_batch"          : ( { "Notes": "answers", "Date": "declines_or_defers" }, [] ),
    "stance_less"               : ( { "answer": "support" }, [ "no_explicit_stance" ] ),
    "unsure"                    : ( { "answer": "re_frame" }, [ "uncertain_annotator" ] ),
}


def load( name ):
    with open( FIXTURES + name + ".json", encoding="utf-8" ) as handle:
        return json.load( handle )


def test_every_card_has_a_captured_reply_that_names_its_provenance():
    cards, replies = load( "cards" ), load( "replies" )[ "replies" ]
    assert set( cards ) == set( replies ) == set( CAPTURED )
    for captured in replies.values():
        assert captured[ "model" ] == "claude-sonnet-5-5"
        assert captured[ "captured" ] == "2026-11-27"
        assert captured[ "annotator" ].startswith( "claude-sonnet-5-5:meaning-labeller-" )


def test_the_captures_cover_every_relation_the_model_may_give():
    given = { relation for labels, _ in CAPTURED.values() for relation in labels.values() }
    assert given == set( lb.STANCE_RELATIONS + lb.TEXT_RELATIONS + lb.PICK_RELATIONS + lb.NO_PICK_RELATIONS )


@pytest.mark.parametrize( "name", sorted( CAPTURED ) )
def test_a_captured_reply_reads_as_its_label( model, name ):
    labels, unknowns = CAPTURED[ name ]
    model.reply = load( "replies" )[ "replies" ][ name ][ "reply" ]
    result      = lb.label( load( "cards" )[ name ] )
    assert { key: entry[ "relation" ] for key, entry in result[ "native_answer" ].items() } == labels
    assert result[ "unknowns" ] == unknowns


def test_the_captured_stance_less_reply_infers_yes( model ):
    model.reply = load( "replies" )[ "replies" ][ "stance_less" ][ "reply" ]
    entry_      = lb.label( load( "cards" )[ "stance_less" ] )[ "native_answer" ][ "answer" ]
    assert entry_[ "stance" ] == "yes" and entry_[ "stance_source" ] == "inferred"


@pytest.mark.parametrize( "bad", [ [ "o2" ], { "id": "o2" }, 2 ], ids=[ "list", "object", "number" ] )
def test_a_condition_whose_option_id_is_not_text_makes_the_field_unreadable( model, bad ):
    picked      = field( kind="write_in_text", answer="Page, weekly", stance=None, comment=None, options=OPTIONS )
    model.reply = [ entry( "D", "expands_other_option", conditions=[ { "text": "weekly", "modifies_option_id": bad } ] ) ]
    result      = lb.label( draft( D=picked ) )
    assert result[ "native_answer" ] == { "D": { "kind": "write_in_text" } }
    assert result[ "conditions" ] == [] and result[ "unknowns" ] == [ "unreadable_payload" ]


def test_the_prompt_sends_the_stance_and_the_comment_in_their_own_keys():
    prompt = lb.build_user_prompt( draft(), [ "answer" ] )
    assert '"stance": "yes"' in prompt and '"comment": "only on Monday"' in prompt


@pytest.mark.parametrize( "unsure", [ "false", "true", 1 ] )
def test_only_the_boolean_true_counts_as_unsure( model, unsure ):
    model.reply = [ entry( unsure=unsure ) ]
    assert lb.label( draft() )[ "unknowns" ] == []


def test_a_draft_from_the_rules_layer_keeps_its_prefixed_option_id( model ):
    options = { "questions": [ { "header": "DB", "question": "Which store?", "options": [ { "label": "Postgres (Recommended)" }, { "label": "Files" } ] } ] }
    card    = SimpleNamespace( response_type="multiple_choice", response_value={ "value": '{"answers": {"DB": "Files, for now"}}', "source": "ui" },
                               response_options=options, response_default=None, title="Store", message="Pick a store", abstract=None )
    model.reply = [ entry( "DB", "expands_other_option", conditions=[ { "text": "for now", "modifies_option_id": "DB#o2" } ] ) ]
    result      = lb.label( rules.draft_of( card ) )
    assert result[ "native_answer" ] == { "DB": { "kind": "write_in_text", "relation": "expands_other_option" } }
    assert result[ "conditions" ] == [ { "text": "for now", "modifies_option_id": "DB#o2", "field_key": "DB" } ]
    assert '"DB#o1"' in model.calls[ 0 ][ 2 ]
