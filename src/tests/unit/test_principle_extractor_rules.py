"""
The extractor's output rules and the prompt reader, as pure functions.

Each rule is checked on synthetic input, so a model that breaks it fails here whether it is live or recorded.
"""

import json

import pytest

from cosa.agents.principle_learner import extractor_rules as rules
from cosa.agents.principle_learner.extractor_prompt import SYSTEM_PROMPT, build_user_prompt, parse_reply
from types import SimpleNamespace

EPISODE = { "title": "Approve the held bugs", "abstract": "Rationale and a [Spec](/app/docs?path=lupin/x.md)",
            "fields": [ { "key": "held_bugs", "prompt": "Approve the held bugs?", "mode": "single", "default": None,
                          "options": [ { "id": "o1", "label": "Approve", "description": "Merge", "recommended": True } ] } ],
            "history": [ { "tier": "thread", "confidence": "certain", "status": "answered", "inferred": False, "answer": { "value": "yes" },
                           "notification_id": "must-not-appear" } ] }


def _hyp( statement="Approval asks should link the thing approved.", **extra ):
    """
    Build a hypothesis dict as a model would return it.

    Ensures:
        - returns a dict with a statement, a global scope and no condition, plus extra
    """
    return { "statement": statement, "scope": "global", **extra }


def _field( **extra ):
    """
    Build one field result with a valid kind and dimension.

    Ensures:
        - returns a dict with kind decision, dimension ask.approval_needs_link, one hypothesis and no relations, plus extra
    """
    return { "kind": "decision", "dimension": "ask.approval_needs_link", "hypotheses": [ _hyp() ], "relations": {}, **extra }


def _check( field=None, bare_yes=False, ids=(), text="card text and answer text", projects=( "lupin", ) ):
    """
    Run check_field with default grounding text and projects.

    Ensures:
        - returns check_field's result
    """
    return rules.check_field( field if field is not None else _field(), text, list( projects ), bare_yes, set( ids ) )


def test_card_text_gathers_title_abstract_prompts_and_option_labels_and_skips_blanks():
    text = rules.card_text( EPISODE )
    assert text.splitlines() == [ "Approve the held bugs", "Rationale and a [Spec](/app/docs?path=lupin/x.md)", "Approve the held bugs?", "Approve" ]
    assert rules.card_text( { "title": None, "abstract": None, "fields": [] } ) == ""


def test_project_names_come_from_the_sender_ids_and_skip_unknown_and_missing():
    assert rules.project_names( [ "claude.code@lupin.deepily.ai#a", "x@Cosa.deepily.ai", "bare", None, "y@lupin.deepily.ai" ] ) == [ "cosa", "lupin" ]
    assert rules.project_names( [ "x@unknown.deepily.ai" ] ) == []


@pytest.mark.parametrize( "answer,expected", [
    ( { "kind": "stance", "stance": "yes", "qualifier": None }, [ { "field_key": "$answer", "text": "yes", "bare_yes": True } ] ),
    ( { "kind": "stance", "stance": "yes", "qualifier": "but link it" }, [ { "field_key": "$answer", "text": "yes but link it", "bare_yes": False } ] ),
    ( { "kind": "stance", "stance": "no", "qualifier": None }, [ { "field_key": "$answer", "text": "no", "bare_yes": False } ] ),
    ( { "kind": "text", "text": "do it later" }, [ { "field_key": "$answer", "text": "do it later", "bare_yes": False } ] ),
    ( { "kind": "text", "text": None }, [ { "field_key": "$answer", "text": "", "bare_yes": False } ] ),
    ( { "kind": "none" }, [] ),
    ( { "kind": "unread", "text": "x" }, [] ),
] )
def test_field_answers_split_each_kind_of_answer_and_flag_only_a_bare_yes( answer, expected ):
    assert rules.field_answers( answer ) == expected


def test_field_answers_for_a_card_give_one_entry_per_header_with_picks_joined():
    answer = { "kind": "fields", "fields": {
        "held_bugs": { "mode": "single", "selected": [ "Approve" ], "text": "Approve" },
        "themes": { "mode": "multi", "selected": [ "A", "B" ], "text": None },
        "empty": { "mode": "multi", "selected": [], "text": None },
        "ok": { "mode": "single", "selected": [ "yes" ], "text": "yes", "stance": "yes", "qualifier": None },
        "ok2": { "mode": "single", "selected": [ "yes" ], "text": "yes", "stance": "yes", "qualifier": "if linked" } } }
    got = { e[ "field_key" ]: ( e[ "text" ], e[ "bare_yes" ] ) for e in rules.field_answers( answer ) }
    assert got == { "held_bugs": ( "Approve", False ), "themes": ( "A, B", False ), "empty": ( "", False ), "ok": ( "yes", True ), "ok2": ( "yes", False ) }


def test_a_card_header_equal_to_the_whole_answer_key_is_refused():
    answer = { "kind": "fields", "fields": { "$answer": { "mode": "single", "selected": [ "x" ], "text": "x" } } }
    with pytest.raises( ValueError, match="reserved for the whole answer" ): rules.field_answers( answer )
    assert rules.field_answers( { "kind": "fields", "fields": { "answer": { "mode": "single", "selected": [ "x" ], "text": "x" } } } )[ 0 ][ "field_key" ] == "answer"


REVEAL, ANSWERED = "2026-11-10T12:00:00+00:00", "2026-11-10T12:05:00+00:00"


def test_unaided_answer_reads_the_draft_in_the_shape_the_route_stores_and_never_marks_it_influenced():
    assert rules.unaided_answer( "final", { "value": "draft text" }, "$answer", REVEAL, ANSWERED ) == ( "draft text", False )
    card = { "value": json.dumps( { "answers": { "held_bugs": "Hold", "themes": [ "A", "B" ] } } ) }
    assert rules.unaided_answer( "Approve", card, "held_bugs", REVEAL, ANSWERED ) == ( "Hold", False )
    assert rules.unaided_answer( "x", card, "themes", REVEAL, ANSWERED ) == ( "A, B", False )
    assert rules.unaided_answer( "x", { "value": { "answers": { "held_bugs": "Hold" } } }, "held_bugs", REVEAL, ANSWERED ) == ( "Hold", False )


def test_a_blank_draft_or_a_field_with_no_draft_reads_the_final_answer():
    assert rules.drafted_text( None, "$answer" ) is None
    assert rules.drafted_text( { "value": "" }, "answer" ) is None and rules.drafted_text( { "value": None }, "held_bugs" ) is None
    card = { "value": json.dumps( { "answers": { "held_bugs": "Hold" } } ) }
    assert rules.drafted_text( card, "other_field" ) is None
    assert rules.drafted_text( { "value": json.dumps( { "answers": { "empty": [] } } ) }, "empty" ) is None
    assert rules.unaided_answer( "final", card, "other_field", None, ANSWERED ) == ( "final", False )


@pytest.mark.parametrize( "draft,key", [ ( "draft text", "$answer" ), ( { "text": "x" }, "$answer" ), ( { "value": 5 }, "$answer" ), ( { "value": "not json" }, "held_bugs" ),
                                         ( { "value": json.dumps( [ 1 ] ) }, "held_bugs" ), ( [ "x" ], "$answer" ) ] )
def test_a_draft_that_cannot_be_read_in_the_stored_shape_raises_and_is_never_skipped( draft, key ):
    with pytest.raises( ValueError ):
        rules.unaided_answer( "final", draft, key, REVEAL, ANSWERED )


def test_unaided_answer_without_a_draft_marks_only_a_reveal_strictly_before_the_answer_as_influenced():
    assert rules.unaided_answer( "final", None, "$answer", REVEAL, ANSWERED ) == ( "final", True )
    assert rules.unaided_answer( "final", None, "$answer", ANSWERED, ANSWERED ) == ( "final", False ), "a reveal at the answer time is unaided"
    assert rules.unaided_answer( "final", None, "answer", "2026-11-10T12:06:00+00:00", ANSWERED ) == ( "final", False )
    assert rules.unaided_answer( "final", None, "answer", None, ANSWERED ) == ( "final", False )


def test_a_condition_is_kept_only_when_its_text_is_in_the_card_or_the_answer_else_unknown():
    text = "Approve the Held Bugs? yes, but link it"
    assert rules.ground_condition( "held bugs", text ) == "held bugs"
    assert rules.ground_condition( "  but LINK it ", text ) == "but LINK it"
    for bad in ( "release day", "", "   ", None ): assert rules.ground_condition( bad, text ) == rules.UNKNOWN


def test_a_statement_of_two_hundred_forty_characters_or_more_is_rejected_and_one_shorter_is_kept():
    short, long = "x" * 239, "x" * 240
    assert _check( _field( hypotheses=[ _hyp( short ) ] ) )[ "hypotheses" ][ 0 ][ "statement" ] == short
    got = _check( _field( hypotheses=[ _hyp( long ) ] ) )
    assert got[ "hypotheses" ] == [] and got[ "rejected" ] == [ { "what": "hypothesis 0", "reason": "statement_too_long" } ]


def test_more_than_three_hypotheses_rejects_every_hypothesis_of_the_field():
    got = _check( _field( hypotheses=[ _hyp( f"s{n}" ) for n in range( 4 ) ] ) )
    assert got[ "hypotheses" ] == [] and got[ "rejected" ] == [ { "what": "hypotheses", "reason": "too_many_hypotheses" } ]
    assert len( _check( _field( hypotheses=[ _hyp( f"s{n}" ) for n in range( 3 ) ] ) )[ "hypotheses" ] ) == 3


@pytest.mark.parametrize( "hypothesis,reason", [
    ( { "statement": "" }, "statement_missing" ), ( { "statement": 5 }, "statement_missing" ), ( {}, "statement_missing" ),
    ( _hyp( scope="project:nobody" ), "scope_unknown" ), ( _hyp( scope="somewhere" ), "scope_unknown" ), ( _hyp( scope=7 ), "scope_unknown" ),
    ( _hyp( "Lupin asks need links." ), "global_statement_names_project" ),
    ( "not a dict", "hypothesis_not_an_object" ),
] )
def test_a_bad_hypothesis_is_rejected_with_its_reason( hypothesis, reason ):
    got = _check( _field( hypotheses=[ hypothesis ] ) )
    assert got[ "hypotheses" ] == [] and got[ "rejected" ][ 0 ][ "reason" ] == reason


def test_a_global_statement_names_no_project_but_a_project_scoped_one_may_and_part_of_a_word_is_not_a_name():
    assert _check( _field( hypotheses=[ _hyp( "A lupinesque habit." ) ] ) )[ "hypotheses" ] != []
    assert _check( _field( hypotheses=[ _hyp( "Lupin asks need links.", scope="project:lupin" ) ] ) )[ "hypotheses" ][ 0 ][ "scope" ] == "project:lupin"
    assert _check( _field( hypotheses=[ _hyp( "Ask about the lupin-mobile build." ) ] ) )[ "hypotheses" ] != []


def test_a_hypothesis_is_cleaned_with_a_grounded_condition_and_a_string_rationale_only():
    got = _check( _field( hypotheses=[ _hyp( condition="answer text", rationale=7, grounded_in="answer" ) ] ), text="card text and answer text" )[ "hypotheses" ][ 0 ]
    assert got == { "statement": "Approval asks should link the thing approved.", "rationale": None, "scope": "global", "condition": "answer text", "grounded_in": "answer" }
    got = _check( _field( hypotheses=[ _hyp( condition="never said", rationale="why" ) ] ) )[ "hypotheses" ][ 0 ]
    assert ( got[ "condition" ], got[ "rationale" ] ) == ( "unknown", "why" )


def test_a_bare_yes_keeps_no_hypothesis_and_only_supports_relations_to_principles_it_was_shown():
    field = _field( relations={ "p1": "supports", "p2": "contradicts", "p3": "supports", "p4": "bogus" } )
    got   = _check( field, bare_yes=True, ids=[ "p1", "p2", "p4" ] )
    assert got[ "hypotheses" ] == [] and got[ "relations" ] == { "p1": "supports" }
    assert { ( r[ "what" ], r[ "reason" ] ) for r in got[ "rejected" ] } == {
        ( "hypotheses", "bare_yes_creates_none" ), ( "relation p2", "bare_yes_only_supports" ), ( "relation p3", "principle_not_shown" ), ( "relation p4", "relation_unknown" ) }
    assert _check( _field( hypotheses=[] ), bare_yes=True )[ "rejected" ] == []


def test_a_field_with_a_bad_kind_or_dimension_keeps_nothing_even_its_relations():
    for bad in ( _field( kind="other" ), _field( dimension="  " ), _field( dimension=None ) ):
        got = _check( { **bad, "relations": { "p1": "supports" } }, ids=[ "p1" ] )
        assert ( got[ "hypotheses" ], got[ "relations" ], got[ "rejected" ][ 0 ][ "reason" ] ) == ( [], {}, "kind_or_dimension_invalid" )


def test_a_field_with_no_hypothesis_list_or_relation_dict_is_read_as_empty():
    got = rules.check_field( { "kind": "ask_form", "dimension": "d", "hypotheses": "x", "relations": [ 1 ] }, "", [], False, set() )
    assert ( got[ "hypotheses" ], got[ "relations" ], got[ "rejected" ], got[ "kind" ], got[ "dimension" ] ) == ( [], {}, [], "ask_form", "d" )


def test_parse_reply_reads_json_through_a_fence_and_refuses_everything_else():
    body = '{"fields": [{"field_key": "a"}]}'
    assert parse_reply( body ) == [ { "field_key": "a" } ]
    assert parse_reply( "Here you go:\n```json\n" + body + "\n```" ) == [ { "field_key": "a" } ]
    assert parse_reply( "```json\n" + body + "\n```\nHope that helps {as always}." ) == [ { "field_key": "a" } ]
    assert parse_reply( '{"note": "first"}\n' + body ) == [ { "field_key": "a" } ]
    for bad in ( "no json", "} {", "{broken", "{not json}", '{"fields": "x"}', '{"fields": [1]}', "[1, 2]", '{"other": []}' ):
        assert parse_reply( bad ) is None


def test_the_user_prompt_carries_card_history_answers_and_principles_and_no_ids():
    neighbour = SimpleNamespace( id="pid-1", dimension="ask.x", statement="A principle.", scope="global" )
    entries   = [ { "field_key": "held_bugs", "text": "no", "bare_yes": False, "possibly_influenced": True } ]
    prompt    = build_user_prompt( EPISODE, entries, [ neighbour ] )
    for block in ( "CARD", "EARLIER QUESTIONS", "ANSWERS", "EXISTING PRINCIPLES" ): assert block in prompt
    assert '"possibly_influenced": true' in prompt and "pid-1" in prompt and "ask.x" in prompt
    assert "must-not-appear" not in prompt and "notification_id" not in prompt
    assert "JSON only" in SYSTEM_PROMPT and "bare yes" in SYSTEM_PROMPT


def test_an_old_dimension_name_is_shown_to_the_model_as_its_heading_and_an_unknown_one_as_stored():
    old     = SimpleNamespace( id="pid-old", dimension="fix_depth", statement="Fix roots.", scope="global" )
    unknown = SimpleNamespace( id="pid-new", dimension="ask.x", statement="Other.", scope="global" )
    prompt  = build_user_prompt( EPISODE, [ { "field_key": "a", "text": "no", "bare_yes": False, "possibly_influenced": False } ], [ old, unknown ] )
    shown   = json.loads( prompt.split( "EXISTING PRINCIPLES\n" )[ 1 ] )
    assert { row[ "id" ]: row[ "dimension" ] for row in shown } == { "pid-old": "Fix the real cause", "pid-new": "ask.x" }
    assert "fix_depth" not in prompt
