"""
Tests for card_stage_of: the decision stage of the asking card, read from its own words.

One fixture card per case the rule names, in fixtures/principle_stage/card_stage_cards.json. The last test
runs the re-spin fixture through real retrieval, the retrieval half of plan section 3's re-spin fixture.
"""

import json
import os
import uuid

import pytest

import cosa.agents.prediction_engine.principles_forecast as forecast_module
from cosa.agents.prediction_engine.card_stage import DELEGATION_PHRASES, WHAT_TO_DO_ONCE_ASKED, WHO_DECIDES, card_stage_of, question_text
from cosa.agents.prediction_engine.principle_retrieval import principle_block
from tests.unit.test_principle_retrieval import add_evidence, add_notification, add_principle, db, retrieve, stand_in_topk, support, two_sessions  # noqa: F401  (fixtures)

FIXTURE = os.path.join( os.path.dirname( __file__ ), "fixtures", "principle_stage", "card_stage_cards.json" )
CARDS   = json.load( open( FIXTURE ) )[ "cards" ]


@pytest.mark.parametrize( "name", sorted( CARDS ) )
def test_each_fixture_card_gets_the_stage_the_rule_names( name ):
    assert card_stage_of( CARDS[ name ][ "episode" ] ) == CARDS[ name ][ "expected" ]


def test_the_fixtures_cover_both_stage_values_and_none():
    assert { card[ "expected" ] for card in CARDS.values() } == { WHO_DECIDES, WHAT_TO_DO_ONCE_ASKED, None }


def test_only_the_question_is_read_never_an_option_label_or_the_abstract():
    text = question_text( CARDS[ "act_now_offering_delegation_as_an_option" ][ "episode" ] )
    assert "ask me before" not in text and "re-spin the idle agent?" in text
    assert "without asking" not in question_text( CARDS[ "delegation_words_only_in_the_abstract" ][ "episode" ] )


@pytest.mark.parametrize( "phrase", DELEGATION_PHRASES )
def test_every_delegation_phrase_makes_a_card_who_decides_in_any_case( phrase ):
    episode = { "title": "T", "message": phrase.upper() + " please", "abstract": "", "response_type": "open_ended", "fields": [] }
    assert card_stage_of( episode ) == WHO_DECIDES


def test_a_card_with_an_option_list_but_no_decision_response_type_is_a_decision():
    episode = { "title": "T", "message": "Pick one", "abstract": "", "response_type": "open_ended_batch",
                "fields": [ { "key": "k", "prompt": "Which?", "mode": "single", "options": [ { "id": "o1", "label": "A" } ] } ] }
    assert card_stage_of( episode ) == WHAT_TO_DO_ONCE_ASKED


def test_a_card_with_no_title_or_message_is_still_read():
    episode = { "title": None, "message": None, "abstract": "", "response_type": "yes_no", "fields": [] }
    assert question_text( episode ) == "" and card_stage_of( episode ) == WHAT_TO_DO_ONCE_ASKED


def test_prepare_hands_retrieval_the_card_stage_it_reads_from_the_episode( monkeypatch ):
    seen = []
    episode = CARDS[ "act_now_yes_no" ][ "episode" ] | { "owner_id": "o", "project": None, "asked_at": "2026-11-10T12:00:00+00:00" }
    class Session:
        def __enter__( self ): return self
        def __exit__( self, *args ): return False
    monkeypatch.setattr( forecast_module, "episode_view", lambda session, key: episode )
    monkeypatch.setattr( forecast_module, "retrieval_limits", lambda: { "bound": 5, "multiplier": 0 } )
    monkeypatch.setattr( forecast_module, "switch_enabled", lambda key: True )
    monkeypatch.setattr( forecast_module, "retrieve_principles", lambda *args, **kwargs: seen.append( kwargs[ "applicability" ] ) or { "principles": [], "applicability": [] } )
    monkeypatch.setattr( forecast_module, "with_principles", lambda system, user, block: ( system, user ) )
    c0 = type( "C0", ( ), { "build_prompts": staticmethod( lambda ep: ( "s", "u" ) ) } )
    forecast_module._prepare( lambda: Session(), str( uuid.uuid4() ), c0, type( "E", ( ), { "encode": staticmethod( lambda text: [ 0.0 ] ) } ), "enc", "ext", 5 )
    assert seen[ 0 ][ "card_stage" ] == WHAT_TO_DO_ONCE_ASKED


def test_the_respin_principle_is_dropped_for_the_card_at_the_what_to_do_stage_and_the_log_names_the_stage_rule( db ):
    respin  = add_principle( db, 1, statement="Ask me before re-spinning an idle agent." )
    plain   = add_principle( db, 2, statement="Link the thing being approved." )
    two_sessions( db )
    for principle in ( respin, plain ):
        for note in ( 1, 2 ): add_evidence( db, principle, note )
    db.add( support( respin.id, stage=WHO_DECIDES ) )
    db.commit()
    asked   = CARDS[ "act_now_offering_delegation_as_an_option" ][ "episode" ]
    check   = { "card": question_text( asked ), "card_stage": card_stage_of( asked ) }
    found   = retrieve( db, applicability=check )
    block   = principle_block( found[ "principles" ] )[ "text" ]
    assert check[ "card_stage" ] == WHAT_TO_DO_ONCE_ASKED
    assert found[ "applicability" ] == [ { "principle_id": respin.id, "rule": "stage" } ]
    assert "re-spinning" not in block and "Link the thing being approved." in block


def test_the_same_principle_is_kept_for_the_card_at_the_who_decides_stage( db ):
    respin = add_principle( db, 1, statement="Ask me before re-spinning an idle agent." )
    two_sessions( db )
    for note in ( 1, 2 ): add_evidence( db, respin, note )
    db.add( support( respin.id, stage=WHO_DECIDES ) )
    db.commit()
    asked  = CARDS[ "delegation_question" ][ "episode" ]
    found  = retrieve( db, applicability={ "card": question_text( asked ), "card_stage": card_stage_of( asked ) } )
    assert found[ "applicability" ] == [] and "re-spinning" in principle_block( found[ "principles" ] )[ "text" ]
