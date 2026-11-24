"""
The engine retrieves and stores cases with an owner and an answer source.

Only a case whose answer_source is "human" and whose owner is the recipient casts a personal vote.
A stored answer carries the account that answered, and a thumbs vote is a hint_vote with no owner.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.agents.prediction_engine.prediction_result import PredictionResult

RECIPIENT = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def engine():
    """An engine with a stubbed store and provider, reset around each test."""
    PredictionEngine.reset()
    built = PredictionEngine( debug=False )
    built._embedding_store    = MagicMock()
    built._embedding_provider = MagicMock()
    built._embedding_provider.generate_embedding.return_value = [ 0.1 ] * 768
    built._embedding_store.find_similar.return_value = [ ( 99.0, { "decision_value": "yes" } ) ]
    yield built
    PredictionEngine.reset()


def _result( response_type="yes_no" ):
    return PredictionResult( response_type=response_type, category="permission", strategy="cold_start",
                             metadata={ "original_message": "Proceed?" } )


def _retrieval_kwargs( engine ):
    return engine._embedding_store.find_similar.call_args.kwargs


@pytest.mark.parametrize( "response_type, route", [
    ( "yes_no",           "_predict_yes_no" ),
    ( "multiple_choice",  "_predict_multiple_choice" ),
    ( "open_ended",       "_predict_open_ended" ),
    ( "open_ended_batch", "_predict_open_ended_batch" ),
] )
def test_every_retrieval_asks_for_the_recipients_human_cases( engine, response_type, route ):
    engine._generate_embedding = lambda text: [ 0.1 ] * 768
    engine.predict( { "message": "Proceed?", "response_type": response_type, "sender_id": "s", "recipient_id": RECIPIENT,
                      "response_options": { "questions": [ { "header": "H", "options": [ { "label": "A" } ] } ] } } )
    kwargs = _retrieval_kwargs( engine )
    assert ( kwargs[ "answer_source" ], kwargs[ "owner_user_id" ] ) == ( "human", RECIPIENT )
    assert kwargs[ "response_type" ] == response_type


def test_a_caller_that_names_no_recipient_gets_no_personal_cases( engine ):
    engine._predict_yes_no( "Proceed?", "permission", [ 0.1 ] * 768 )
    kwargs = _retrieval_kwargs( engine )
    assert ( kwargs[ "answer_source" ], kwargs[ "owner_user_id" ] ) == ( "human", "" )


def test_the_personal_vote_filter_is_the_one_both_retrievals_use():
    assert PredictionEngine._personal_vote_filter( None ) == { "answer_source": "human", "owner_user_id": "" }
    assert PredictionEngine._personal_vote_filter( RECIPIENT ) == { "answer_source": "human", "owner_user_id": RECIPIENT }


def test_a_stored_answer_carries_the_account_that_answered( engine ):
    engine._store_decision( "n-1", _result(), "yes", "yes_no", { "user_id": RECIPIENT, "method": "jwt" }, "human" )
    stored = engine._embedding_store.add_decision.call_args.kwargs
    assert ( stored[ "owner_user_id" ], stored[ "answer_source" ] ) == ( RECIPIENT, "human" )


@pytest.mark.parametrize( "label, stored_as", [
    ( "human", "human" ), ( "default", "timeout_default" ), ( "not_operator", "unknown" ), ( "unattributed", "unknown" ), ( None, "unknown" ),
] )
def test_the_stored_source_follows_the_answer_source_label_not_the_presence_of_a_user_id( engine, label, stored_as ):
    # Row 1b3202de (F7): an API-key stamp carries a user_id, and used to be filed as human
    engine._store_decision( "n-1", _result(), "yes", "yes_no", { "user_id": RECIPIENT, "method": "api_key" }, label )
    stored = engine._embedding_store.add_decision.call_args.kwargs
    assert ( stored[ "owner_user_id" ], stored[ "answer_source" ] ) == ( RECIPIENT, stored_as )


def test_a_stored_answer_with_no_account_is_unknown_and_casts_no_personal_vote( engine ):
    engine._store_decision( "n-2", _result(), "yes", "yes_no" )
    stored = engine._embedding_store.add_decision.call_args.kwargs
    assert ( stored[ "owner_user_id" ], stored[ "answer_source" ] ) == ( None, "unknown" )


def test_a_thumbs_vote_is_stored_as_a_hint_vote_with_no_owner( engine ):
    engine._embedding_store.exists.return_value = False
    engine.record_hint_vote( "n-3", "Proceed?", "yes", "permission", "yes_no", "up" )
    stored = engine._embedding_store.add_decision.call_args.kwargs
    assert ( stored[ "id" ], stored[ "owner_user_id" ], stored[ "answer_source" ] ) == ( "hintvote-n-3", None, "hint_vote" )
    assert datetime.fromisoformat( stored[ "created_at" ] )


def test_record_outcome_hands_the_answering_account_to_the_store( engine ):
    answered_by = { "user_id": RECIPIENT, "method": "jwt" }
    with patch( "cosa.rest.db.database.get_db" ), \
         patch( "cosa.rest.db.repositories.prediction_log_repository.PredictionLogRepository" ), \
         patch.object( engine, "_store_decision" ) as store_decision:
        engine.record_outcome( "n-4", _result(), "yes", "yes_no", answered_by=answered_by )
    assert store_decision.call_args.args[ 4 ] == answered_by


def test_record_outcome_hands_the_answer_source_to_the_store( engine ):
    with patch( "cosa.rest.db.database.get_db" ), \
         patch( "cosa.rest.db.repositories.prediction_log_repository.PredictionLogRepository" ), \
         patch.object( engine, "_store_decision" ) as store_decision:
        engine.record_outcome( "n-5", _result(), "yes", "yes_no", answered_by={ "user_id": RECIPIENT, "method": "api_key" }, answer_source="not_operator" )
    assert store_decision.call_args.args[ 5 ] == "not_operator"


def test_the_ledger_route_hands_the_answer_source_on_to_record_outcome( engine ):
    row = MagicMock()
    with patch( "cosa.rest.db.database.get_db" ), \
         patch( "cosa.rest.db.repositories.prediction_log_repository.PredictionLogRepository" ) as repo, \
         patch.object( engine, "_result_from_row", return_value=_result() ), \
         patch.object( engine, "record_outcome" ) as record:
        repo.return_value.get_by_notification_id.return_value = row
        assert engine.record_outcome_from_ledger( "n-6", "yes", { "user_id": RECIPIENT, "method": "api_key" }, None, "not_operator" ) is True
    assert record.call_args.args[ 6 ] == "not_operator"
