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


def test_the_extractor_version_is_the_model_then_a_colon_then_the_prompt_version_and_the_job_stores_that_string():
    from cosa.agents.principle_learner import extractor_job
    from cosa.agents.principle_learner.extractor_prompt import current_extractor_version, extractor_version_of
    assert extractor_version_of( "m-1" ).startswith( "m-1:extractor-v2-vocab-" )
    assert extractor_job.current_extractor_version is current_extractor_version


def _answered( source, user="u-1", recipient="u-1" ):
    return SimpleNamespace( recipient_id=recipient, response_value={ "source": source, "answered_by": { "user_id": user }, "value": "yes" } )


def test_owners_own_answer_needs_the_recipient_to_have_answered_from_their_screen():
    assert rules.owners_own_answer( _answered( "ui" ) ) is True
    assert rules.owners_own_answer( _answered( "timeout" ) ) is False
    assert rules.owners_own_answer( _answered( "ui", user="u-2" ) ) is False
    assert rules.owners_own_answer( SimpleNamespace( recipient_id="u-1", response_value="yes" ) ) is False


def _bare( relations, **extra ):
    """Build a bare-yes field result that names principles and keeps no hypothesis."""
    return _field( hypotheses=[], relations=relations, **extra )


def _quote( pid="p1", quote="when the card names a deadline", lacks=True ):
    """Build the antecedents map the model returns for one uninformative relation."""
    return { pid: { "quote": quote, "card_lacks_it": lacks } }


def test_with_both_switches_off_a_bare_yes_still_keeps_only_supports_and_uninformative_is_an_unknown_word():
    got = _check( _bare( { "p1": "contradicts", "p2": "refines", "p3": "uninformative", "p4": "supports" }, antecedents=_quote( "p3" ) ), bare_yes=True, ids=( "p1", "p2", "p3", "p4" ) )
    assert got[ "relations" ] == { "p4": "supports" } and got[ "antecedents" ] == {}
    assert [ r[ "reason" ] for r in got[ "rejected" ] ] == [ "bare_yes_only_supports", "bare_yes_only_supports", "relation_unknown" ]


def test_a_bare_yes_may_contradict_or_refine_when_the_bare_yes_relations_switch_is_on():
    field = _bare( { "p1": "contradicts", "p2": "refines" } )
    got   = rules.check_field( field, "t", [], True, { "p1", "p2" }, bare_yes_relations=True )
    assert got[ "relations" ] == { "p1": "contradicts", "p2": "refines" } and got[ "rejected" ] == []
    assert rules.check_field( field, "t", [], True, { "p1", "p2" } )[ "relations" ] == {}


def test_an_unknown_word_is_still_refused_with_the_bare_yes_relations_switch_on():
    got = rules.check_field( _bare( { "p1": "likes" } ), "t", [], True, { "p1" }, bare_yes_relations=True )
    assert got[ "relations" ] == {} and got[ "rejected" ][ 0 ][ "reason" ] == "relation_unknown"


def test_an_uninformative_relation_is_kept_with_its_quote_when_the_switch_is_on():
    got = rules.check_field( _bare( { "p1": "uninformative" }, antecedents=_quote() ), "t", [], True, { "p1" }, uninformative=True )
    assert got[ "relations" ] == { "p1": "uninformative" } and got[ "antecedents" ] == { "p1": "when the card names a deadline" } and got[ "rejected" ] == []


@pytest.mark.parametrize( "antecedents", [ None, "x", {}, { "p1": "bare string" }, { "p1": { "quote": "  ", "card_lacks_it": True } },
                                           { "p1": { "quote": 5, "card_lacks_it": True } }, { "p1": { "quote": "q", "card_lacks_it": False } },
                                           { "p1": { "quote": "q" } } ] )
def test_an_uninformative_relation_without_the_quote_or_the_card_lacks_it_statement_is_refused( antecedents ):
    got = rules.check_field( _bare( { "p1": "uninformative" }, antecedents=antecedents ), "t", [], True, { "p1" }, uninformative=True )
    assert got[ "relations" ] == {} and got[ "antecedents" ] == {} and got[ "rejected" ][ 0 ][ "reason" ] == "uninformative_without_quote"


def test_an_uninformative_relation_needs_a_bare_yes_and_a_shown_principle():
    got = rules.check_field( _field( relations={ "p1": "uninformative" }, antecedents=_quote() ), "t", [], False, { "p1" }, uninformative=True )
    assert got[ "relations" ] == {} and got[ "rejected" ][ 0 ][ "reason" ] == "uninformative_only_bare_yes"
    got = rules.check_field( _bare( { "p9": "uninformative" }, antecedents=_quote( "p9" ) ), "t", [], True, { "p1" }, uninformative=True )
    assert got[ "rejected" ][ 0 ][ "reason" ] == "principle_not_shown"


def test_unread_entries_hands_the_raw_yes_no_text_to_the_writer_with_the_flag():
    assert rules.unread_entries( { "kind": "unread", "text": "yep, but only on fridays" }, "yes_no" ) == [
        { "field_key": "$answer", "text": "yep, but only on fridays", "bare_yes": False, "unread_stance": True } ]


@pytest.mark.parametrize( "answer, response_type", [ ( { "kind": "unread", "text": "x" }, "multiple_choice" ), ( { "kind": "unread", "text": None }, "yes_no" ),
                                                     ( { "kind": "unread", "text": "  " }, "yes_no" ), ( { "kind": "unread", "text": 5 }, "yes_no" ),
                                                     ( { "kind": "stance", "stance": "yes", "qualifier": "", "text": "x" }, "yes_no" ), ( { "kind": "none" }, "yes_no" ) ] )
def test_unread_entries_gives_nothing_for_any_other_answer( answer, response_type ):
    assert rules.unread_entries( answer, response_type ) == []


def test_the_prompt_addenda_names_tags_and_version_follow_the_switches():
    from cosa.agents.principle_learner import extractor_prompt as ep
    assert ep.system_prompt_for() == SYSTEM_PROMPT and ep.system_prompt_for( () ) == SYSTEM_PROMPT
    full = ep.system_prompt_for( ( ep.BARE_YES_TAG, ep.UNINFORMATIVE_TAG, ep.UNREAD_TAG ) )
    assert full.startswith( SYSTEM_PROMPT ) and "contradicts" in full and "card_lacks_it" in full and "unread_stance" in full
    assert ep.extractor_version_of( "m" ) == f"m:{ep.PROMPT_VERSION}"
    assert ep.extractor_version_of( "m", ( "bareyes", "unread" ) ) == f"m:{ep.PROMPT_VERSION}+bareyes+unread"


def test_an_entry_marked_unread_stance_carries_the_flag_in_the_prompt_and_no_other_entry_does():
    entries = [ { "field_key": "a", "text": "hm", "bare_yes": False, "possibly_influenced": False, "unread_stance": True },
                { "field_key": "b", "text": "no", "bare_yes": False, "possibly_influenced": False } ]
    answers = json.loads( build_user_prompt( EPISODE, entries, [] ).split( "ANSWERS\n" )[ 1 ].split( "\n\nEXISTING" )[ 0 ] )
    assert answers[ 0 ][ "unread_stance" ] is True and "unread_stance" not in answers[ 1 ]


def _real( case ):
    """Load a real model reply (claude-sonnet-5-5, 24 Nov 2026) through parse_reply."""
    import pathlib
    path    = pathlib.Path( __file__ ).resolve().parents[ 1 ] / "fixtures" / "principle_extractor" / f"real-reply-{case}.json"
    fixture = json.loads( path.read_text() )
    return fixture, parse_reply( fixture[ "reply" ] )[ 0 ]


def test_a_real_uninformative_reply_is_kept_with_its_quote_with_the_switch_on_and_refused_with_it_off():
    fixture, field = _real( "bare-yes-uninformative" )
    ids            = set( fixture[ "neighbour_ids" ] )
    kept           = rules.check_field( field, "", [], True, ids, bare_yes_relations=True, uninformative=True )
    assert list( kept[ "relations" ].values() ) == [ "uninformative" ] and list( kept[ "antecedents" ].values() ) == [ "When a deploy ask names a rollback plan" ] and kept[ "rejected" ] == []
    off = rules.check_field( field, "", [], True, ids )
    assert off[ "relations" ] == {} and off[ "rejected" ][ 0 ][ "reason" ] == "relation_unknown"


def test_a_real_bare_yes_contradicts_reply_is_kept_only_with_the_bare_yes_switch_on():
    fixture, field = _real( "bare-yes-contradicts" )
    ids            = set( fixture[ "neighbour_ids" ] )
    assert list( rules.check_field( field, "", [], True, ids, bare_yes_relations=True )[ "relations" ].values() ) == [ "contradicts" ]
    assert rules.check_field( field, "", [], True, ids )[ "rejected" ][ 0 ][ "reason" ] == "bare_yes_only_supports"


def test_a_real_reply_that_called_a_bare_yes_supports_is_kept_as_supports_under_every_switch_state():
    fixture, field = _real( "bare-yes-refines" )
    ids            = set( fixture[ "neighbour_ids" ] )
    for kwargs in ( {}, { "bare_yes_relations": True, "uninformative": True } ):
        assert list( rules.check_field( field, "", [], True, ids, **kwargs )[ "relations" ].values() ) == [ "supports" ]


def test_a_real_reply_to_an_unread_text_proposes_a_grounded_hypothesis_through_check_field():
    fixture, field = _real( "unread-text" )
    entries        = [ { "field_key": "$answer", "text": fixture[ "entries" ][ 0 ][ "text" ], "bare_yes": False, "unread_stance": True } ]
    assert rules.unread_entries( { "kind": "unread", "text": entries[ 0 ][ "text" ] }, "yes_no" ) == [ { **entries[ 0 ] } ]
    got = rules.check_field( field, rules.card_text( EPISODE ) + "\n" + entries[ 0 ][ "text" ], [], False, set() )
    assert len( got[ "hypotheses" ] ) == 1 and got[ "hypotheses" ][ 0 ][ "condition" ] == "unknown"  # the real condition words are not in this card or answer
