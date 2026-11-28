"""
The meaning labeller's plain-code rules (plan sections 3, 3b and 5, second build step).

Every plain-code label is produced with no model in reach: the model transport is replaced by one that fails if called.
"""
import json
from types import SimpleNamespace

import pytest

from cosa.agents.answer_meaning import rules
from cosa.repo.doc_lint import model_transport
from cosa.rest.db.repositories.answer_meaning_repository import NATIVE_KINDS, RELATIONS_V2, UNKNOWN_KINDS

OPTIONS = { "questions": [ { "header": "DB", "question": "Which database?", "options": [
    { "label": "Postgres (Recommended)", "description": "the one we run" }, { "label": "SQLite" }, { "label": "DuckDB" } ] } ] }
PLAIN_OPTIONS = { "questions": [ { "header": "DB", "question": "Which database?", "options": [ { "label": "Postgres" }, { "label": "SQLite" } ] } ] }
BATCH = { "questions": [ { "header": h, "question": f"{h}?", "input_type": "text" } for h in ( "budget", "timeout", "theme" ) ] }


@pytest.fixture( autouse=True )
def no_model( monkeypatch ):
    def explode( *args, **kwargs ): raise AssertionError( "the rules layer called the model" )
    for name in ( "complete", "complete_sync" ): monkeypatch.setattr( model_transport, name, explode )


def card( response_type, value, options=None, source="ui", **extra ):
    stored = { "value": value }
    if source is not None: stored[ "source" ] = source
    made = dict( response_type=response_type, response_value=stored, response_options=options, response_default=None,
                 title="Title", message="Shall we?", abstract=None )
    made.update( extra )
    return SimpleNamespace( **made )


def picks( answers ): return json.dumps( { "answers": answers } )


@pytest.mark.parametrize( "stance", [ "yes", "no" ] )
def test_a_bare_stance_is_no_comment_and_calls_no_model( stance ):
    draft = rules.draft_of( card( "yes_no", stance ) )
    field = draft[ "fields" ][ "answer" ]
    assert ( field[ "kind" ], field[ "stance" ], field[ "comment" ], field[ "relation" ] ) == ( "yes_no_stance", stance, None, "no_comment" )
    assert draft[ "unknowns" ] == [] and draft[ "plain" ] == {}
    assert rules.pending_keys( draft ) == []


def test_a_bare_neither_is_no_comment_and_named_in_unknowns():
    draft = rules.draft_of( card( "yes_no", "neither" ) )
    assert draft[ "fields" ][ "answer" ][ "relation" ] == "no_comment"
    assert draft[ "unknowns" ] == [ "neither" ]


@pytest.mark.parametrize( "stance, unknowns", [ ( "yes", [] ), ( "no", [] ), ( "neither", [ "neither" ] ) ] )
def test_a_stance_with_a_comment_is_left_to_the_model( stance, unknowns ):
    value = f"{stance} [comment: not the migration]"
    draft = rules.draft_of( card( "yes_no", value ) )
    field = draft[ "fields" ][ "answer" ]
    assert ( field[ "stance" ], field[ "comment" ], field[ "relation" ], field[ "answer" ] ) == ( stance, "not the migration", None, value )
    assert draft[ "unknowns" ] == unknowns and rules.pending_keys( draft ) == [ "answer" ]


def test_a_stance_less_string_says_so_and_goes_to_the_model():
    draft = rules.draft_of( card( "yes_no", "Yeah, provided that you wait" ) )
    field = draft[ "fields" ][ "answer" ]
    assert ( field[ "stance" ], field[ "comment" ], field[ "relation" ] ) == ( None, None, None )
    assert draft[ "unknowns" ] == [ "no_explicit_stance" ]


@pytest.mark.parametrize( "response_type, options", [ ( "yes_no", None ), ( "multiple_choice", OPTIONS ) ] )
def test_a_timeout_default_is_a_cancellation_and_never_ricks_answer( response_type, options ):
    value = "yes" if response_type == "yes_no" else picks( { "DB": "SQLite" } )
    draft = rules.draft_of( card( response_type, value, options, source="timeout_default" ) )
    assert draft[ "fields" ] == {} and draft[ "plain" ] == {}
    assert draft[ "unknowns" ] == [ "cancellation" ]


@pytest.mark.parametrize( "response_type, value", [ ( "open_ended", "[cancelled]" ), ( "multiple_choice", '{"cancelled":true,"answers":{}}' ) ] )
def test_a_cancelled_card_is_a_cancellation( response_type, value ):
    draft = rules.draft_of( card( response_type, value, OPTIONS if response_type == "multiple_choice" else None ) )
    assert "cancellation" in draft[ "unknowns" ] and rules.pending_keys( draft ) == []


@pytest.mark.parametrize( "source", [ None, "robot" ] )
def test_an_answer_with_no_known_source_is_not_read_as_ricks( source ):
    draft = rules.draft_of( card( "yes_no", "yes", source=source ) )
    assert draft[ "fields" ] == {} and draft[ "unknowns" ] == [ "unreadable_payload" ]


@pytest.mark.parametrize( "stored", [ None, "yes", {}, { "source": "ui" }, { "source": "ui", "value": 3 } ] )
def test_a_payload_that_is_not_an_object_with_text_is_unreadable( stored ):
    made = card( "yes_no", "x" )
    made.response_value = stored
    assert rules.draft_of( made )[ "unknowns" ] == [ "unreadable_payload" ]


def test_a_response_type_the_rules_do_not_know_raises():
    with pytest.raises( ValueError, match="rating" ): rules.draft_of( card( "rating", "5" ) )


def test_a_recommended_pick_agrees():
    field = rules.draft_of( card( "multiple_choice", picks( { "DB": "Postgres (Recommended)" } ), OPTIONS ) )[ "fields" ][ "DB" ]
    assert ( field[ "kind" ], field[ "relation" ], field[ "selected_ids" ], field[ "write_in_text" ] ) == ( "selected_options", "agrees", [ "DB#o1" ], None )
    assert field[ "prompt" ] == "Which database?" and field[ "options" ][ 0 ][ "recommended" ] is True


def test_another_listed_pick_is_a_different_option():
    field = rules.draft_of( card( "multiple_choice", picks( { "DB": "SQLite" } ), OPTIONS ) )[ "fields" ][ "DB" ]
    assert ( field[ "relation" ], field[ "selected_ids" ] ) == ( "chose_different_listed_option", [ "DB#o2" ] )


def test_a_pick_on_a_card_with_no_recommendation_says_so():
    field = rules.draft_of( card( "multiple_choice", picks( { "DB": "SQLite" } ), PLAIN_OPTIONS ) )[ "fields" ][ "DB" ]
    assert field[ "relation" ] == "no_recommendation_on_card"


@pytest.mark.parametrize( "chosen, relation", [
    ( [ "Postgres (Recommended)" ], "agrees" ), ( [ "Postgres (Recommended)", "SQLite" ], "chose_different_listed_option" ) ] )
def test_a_multi_select_agrees_only_when_every_pick_is_recommended( chosen, relation ):
    field = rules.draft_of( card( "multiple_choice", picks( { "DB": chosen } ), OPTIONS ) )[ "fields" ][ "DB" ]
    assert ( field[ "kind" ], field[ "relation" ] ) == ( "multi_selected_options", relation )


def test_a_typed_answer_is_a_write_in_for_the_model():
    field = rules.draft_of( card( "multiple_choice", picks( { "DB": "Neither, use files" } ), OPTIONS ) )[ "fields" ][ "DB" ]
    assert ( field[ "kind" ], field[ "relation" ], field[ "write_in_text" ], field[ "selected_ids" ] ) == ( "write_in_text", None, "Neither, use files", [] )
    assert field[ "answer" ] == "Neither, use files"


def test_a_multi_select_with_a_typed_item_keeps_both_for_the_model():
    field = rules.draft_of( card( "multiple_choice", picks( { "DB": [ "SQLite", "and keep backups" ] } ), OPTIONS ) )[ "fields" ][ "DB" ]
    assert ( field[ "kind" ], field[ "relation" ], field[ "selected_ids" ] ) == ( "multi_selected_options", None, [ "DB#o2" ] )
    assert field[ "write_in_text" ] == "and keep backups" and field[ "answer" ] == "SQLite; and keep backups"


@pytest.mark.parametrize( "empty", [ [], "  " ] )
def test_an_empty_selection_is_plain_and_has_no_relation( empty ):
    draft = rules.draft_of( card( "multiple_choice", picks( { "DB": empty } ), OPTIONS ) )
    assert draft[ "fields" ] == {}
    assert draft[ "plain" ] == { "DB": { "kind": "empty_selection", "selected_option_ids": [], "empty_selection": True,
                                         "write_in_text": None, "referred_option_ids": [], "text": None } }


def test_a_question_with_no_answer_entry_is_an_absent_field():
    draft = rules.draft_of( card( "multiple_choice", picks( {} ), OPTIONS ) )
    assert draft[ "fields" ] == {} and draft[ "unknowns" ] == [ "absent_field" ]


def test_the_plain_string_form_of_a_one_question_card_is_read_as_its_pick():
    field = rules.draft_of( card( "multiple_choice", "SQLite", OPTIONS ) )[ "fields" ][ "DB" ]
    assert field[ "relation" ] == "chose_different_listed_option"


@pytest.mark.parametrize( "value, options", [ ( "{not json", OPTIONS ), ( "SQLite", None ), ( "SQLite", BATCH ) ] )
def test_a_card_answer_that_cannot_be_placed_is_unreadable( value, options ):
    assert rules.draft_of( card( "multiple_choice", value, options ) )[ "unknowns" ] == [ "unreadable_payload" ]


def test_a_batch_of_three_headers_gives_three_entries():
    draft = rules.draft_of( card( "open_ended_batch", picks( { "budget": "no limit", "timeout": "yes", "theme": " " } ), BATCH ) )
    assert list( draft[ "fields" ] ) == [ "budget", "timeout", "theme" ]
    assert { k: f[ "relation" ] for k, f in draft[ "fields" ].items() } == { "budget": None, "timeout": None, "theme": "no_answer" }
    assert { f[ "kind" ] for f in draft[ "fields" ].values() } == { "batch_field_text" }
    assert draft[ "fields" ][ "timeout" ][ "stance" ] is None, "a stance-like word typed into a text field is not a stance"


def test_a_batch_header_the_card_did_not_list_is_still_read():
    draft = rules.draft_of( card( "open_ended_batch", picks( { "extra": "words" } ), None ) )
    assert list( draft[ "fields" ] ) == [ "extra" ]


def test_a_timed_out_batch_is_no_answer_per_header():
    draft = rules.draft_of( card( "open_ended_batch", picks( { "budget": "10" } ), BATCH, source="timeout_default" ) )
    assert { f[ "relation" ] for f in draft[ "fields" ].values() } == { "no_answer" } and len( draft[ "fields" ] ) == 3
    assert draft[ "unknowns" ] == [ "cancellation" ]


@pytest.mark.parametrize( "value, source, relation, unknowns", [
    ( "words", "ui", None, [] ), ( "   ", "ui", "no_answer", [] ), ( "words", "timeout_default", "no_answer", [ "cancellation" ] ),
    ( "[cancelled]", "ui", "no_answer", [ "cancellation" ] ) ] )
def test_an_open_ended_answer( value, source, relation, unknowns ):
    draft = rules.draft_of( card( "open_ended", value, source=source ) )
    field = draft[ "fields" ][ "answer" ]
    assert ( field[ "kind" ], field[ "relation" ] ) == ( "open_ended_text", relation )
    assert draft[ "unknowns" ] == unknowns


@pytest.mark.parametrize( "title, message, abstract, expected", [
    ( "Title", "Shall we?", None, "Title\nShall we?" ),
    ( "Shall", "Shall we?", "Detail", "Shall we?\nDetail" ),
    ( None, "Shall we?", None, "Shall we?" ) ] )
def test_card_text_is_title_message_and_abstract_without_repeating_the_title( title, message, abstract, expected ):
    draft = rules.draft_of( card( "yes_no", "yes", title=title, message=message, abstract=abstract ) )
    assert draft[ "card_text" ] == expected and draft[ "response_type" ] == "yes_no"


@pytest.mark.parametrize( "response_type, value, options, key, text", [
    ( "yes_no", "no [comment: later]", None, "answer", "no" ),
    ( "yes_no", "Maybe you want to", None, "answer", "Maybe you want to" ),
    ( "open_ended", " words ", None, "answer", "words" ),
    ( "multiple_choice", '{"answers":{"DB":"SQLite"}}', OPTIONS, "DB", None ) ] )
def test_entry_of_builds_the_stored_entry( response_type, value, options, key, text ):
    field = rules.draft_of( card( response_type, value, options ) )[ "fields" ][ key ]
    entry = rules.entry_of( field )
    assert entry[ "text" ] == text and entry[ "kind" ] == field[ "kind" ]
    assert entry[ "selected_option_ids" ] == field[ "selected_ids" ] and entry[ "empty_selection" ] is False
    assert entry.get( "comment" ) == field[ "comment" ]
    assert entry.get( "relation" ) == field[ "relation" ]


def test_every_value_the_rules_emit_is_on_the_repositorys_lists():
    drafts = [ rules.draft_of( card( "yes_no", v ) ) for v in ( "yes", "neither [comment: x]", "what" ) ]
    drafts += [ rules.draft_of( card( "multiple_choice", picks( { "DB": v } ), OPTIONS ) ) for v in ( "SQLite", [], "typed" ) ]
    for draft in drafts:
        assert set( draft[ "unknowns" ] ) <= set( UNKNOWN_KINDS )
        for field in draft[ "fields" ].values():
            assert field[ "kind" ] in NATIVE_KINDS and field[ "relation" ] in RELATIONS_V2 + ( None, )
        for entry in draft[ "plain" ].values(): assert entry[ "kind" ] in NATIVE_KINDS


def test_a_batch_answer_that_is_not_an_answers_map_is_unreadable():
    draft = rules.draft_of( card( "open_ended_batch", "just words", BATCH ) )
    assert draft[ "fields" ] == {} and draft[ "unknowns" ] == [ "unreadable_payload" ]


def test_a_cancelled_batch_is_no_answer_per_question():
    draft = rules.draft_of( card( "open_ended_batch", "[cancelled]", BATCH ) )
    assert { f[ "relation" ] for f in draft[ "fields" ].values() } == { "no_answer" } and draft[ "unknowns" ] == [ "cancellation" ]
