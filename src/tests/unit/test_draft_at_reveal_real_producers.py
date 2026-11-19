"""
Real producers' output, compared as a draft and a final answer, for three card types.

The cards are one yes/no, one multiple-choice and one batch card. They are synthetic; their shapes are not.
Three producers make the strings compared:

- The client: ActionRequiredStore.toWireResponseValue and actionRequiredInteractive.withComment.
  Their output for the cards below was captured under tsx on 19 Nov 2026.
  Multiple choice and batch use the committed fixture, whose wire_value the TypeScript store test pins byte for byte.
- The answer door: notifications._stored_response_dict, run here as written.
- The outcome recorder: PredictionEngine.record_outcome, run here as written over a recording repository.

No client sends a draft yet. The remediation plan's client change will add one. By agreement a draft is the string the submit
button would send with the controls as they stand.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

import cosa.utils.util as cu
from cosa.agents.prediction_engine import exposure as ex
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.agents.prediction_engine.prediction_result import PredictionResult
from cosa.rest.routers.notifications import _stored_response_dict

QUESTIONS = json.load( open( cu.get_project_root() + "/src/tests/unit/multiplexer/fixtures/action_required_questions_payload.json", encoding="utf-8" ) )
ANSWERED_BY = { "user_id": "22222222-2222-4222-8222-222222222222", "account_email": "owner@example.com", "method": "jwt" }

# What the client sent for each card: the final answer, and the draft taken when the forecast was opened.
YES_NO = { "response_type": "yes_no", "options": None,
           "final": "no [comment: not ready]", "draft_same": "no", "draft_other": "yes", "draft_empty": "" }
MULTI  = { "response_type": "multiple_choice", "options": QUESTIONS[ "multiple_choice" ][ "response_options" ],
           "final": QUESTIONS[ "multiple_choice" ][ "wire_value" ],
           "draft_same": '{"answers":{"Database":"PostgreSQL","Features":["Audit log","Search"]}}',
           "draft_other": '{"answers":{"Database":"SQLite","Features":["Search","Audit log"]}}',
           "draft_empty": '{"answers":{}}' }
BATCH  = { "response_type": "open_ended_batch", "options": QUESTIONS[ "open_ended_batch" ][ "response_options" ],
           "final": QUESTIONS[ "open_ended_batch" ][ "wire_value" ],
           "draft_same": '{"answers":{"Topic":"quantum computing","Budget":"no limit"}}',
           "draft_other": '{"answers":{"Topic":"quantum computing","Budget":"5"}}',
           "draft_empty": '{"answers":{"Topic":"quantum computing"}}' }
CARDS  = [ YES_NO, MULTI, BATCH ]


@pytest.fixture
def engine():
    """
    An engine with its stores stubbed, reset around each test.

    Ensures:
        - embeddings are a constant vector, and the case store is never written
    """
    PredictionEngine.reset()
    built = PredictionEngine( debug=False )
    built._embedding_store    = MagicMock()
    built._embedding_provider = MagicMock()
    built._generate_embedding = lambda text: [ 0.1 ] * 768
    yield built
    PredictionEngine.reset()


def _recorded_actual_value( engine, card ):
    """
    Run the real record_outcome and return what it stored as actual_value.

    Requires:
        - card is one of the three card dicts above

    Ensures:
        - returns the dict handed to the repository's update_outcome
    """
    repo   = MagicMock()
    result = PredictionResult( response_type=card[ "response_type" ], category="permission", strategy="cold_start", metadata={ "original_message": "Proceed?" } )
    with patch( "cosa.rest.db.database.get_db" ), \
         patch( "cosa.rest.db.repositories.prediction_log_repository.PredictionLogRepository", return_value=repo ), \
         patch.object( engine, "_store_decision" ):
        engine.record_outcome( "n-1", result, card[ "final" ], card[ "response_type" ], ANSWERED_BY, card[ "options" ] )
    assert repo.update_outcome.call_count == 1, "record_outcome stored nothing, so its error was swallowed"
    return repo.update_outcome.call_args.kwargs[ "actual_value" ]


def test_what_the_door_and_the_recorder_store_for_each_card_type( engine ):
    assert _stored_response_dict( YES_NO[ "final" ], ANSWERED_BY ) == { "value": "no [comment: not ready]", "source": "ui", "answered_by": ANSWERED_BY }
    assert _recorded_actual_value( engine, YES_NO ) == { "value": "no [comment: not ready]" }
    for card in ( MULTI, BATCH ):
        assert _stored_response_dict( card[ "final" ], ANSWERED_BY ) == { "value": card[ "final" ], "source": "ui", "answered_by": ANSWERED_BY }
        assert _recorded_actual_value( engine, card ) == json.loads( card[ "final" ] ), "a card answer is stored decoded, with no value key"


@pytest.mark.parametrize( "card", CARDS, ids=[ "yes_no", "multiple_choice", "open_ended_batch" ] )
def test_both_stored_forms_of_the_final_answer_compare_the_same_way_against_a_draft( engine, card ):
    kind    = card[ "response_type" ]
    door    = _stored_response_dict( card[ "final" ], ANSWERED_BY )
    outcome = _recorded_actual_value( engine, card )
    for name, expected in ( ( "draft_same", ex.SAME ), ( "draft_other", ex.SWITCHED ), ( "draft_empty", ex.UNDRAFTED ) ):
        draft = { "value": card[ name ] }
        via_door     = ex.compare_draft_to_answer( kind, draft, door )
        via_recorder = ex.compare_draft_to_answer( kind, draft, outcome )
        assert via_door == via_recorder, ( kind, name )
        assert via_door[ "outcome" ] == expected, ( kind, name, via_door )


def test_a_multiple_choice_draft_that_held_one_field_names_the_field_answered_after_the_reveal( engine ):
    draft  = { "value": '{"answers":{"Database":"PostgreSQL"}}' }
    result = ex.compare_draft_to_answer( "multiple_choice", draft, _recorded_actual_value( engine, MULTI ) )
    assert result == { "outcome": ex.UNDRAFTED, "fields": { "Database": ex.SAME, "Features": ex.UNDRAFTED } }
    assert ex.classify_exposure( "2026-11-19T12:00:00+00:00", draft, _recorded_actual_value( engine, MULTI ), response_type="multiple_choice" ) == ex.EXPOSED


def test_a_batch_field_changed_after_the_reveal_is_the_one_named_switched( engine ):
    result = ex.compare_draft_to_answer( "open_ended_batch", { "value": BATCH[ "draft_other" ] }, _recorded_actual_value( engine, BATCH ) )
    assert result[ "fields" ] == { "Topic": ex.SAME, "Budget": ex.SWITCHED } and result[ "outcome" ] == ex.SWITCHED


def test_the_draft_route_accepts_each_cards_draft_as_the_value_it_stores():
    from cosa.rest.routers.notifications import PredictionSeenRequest
    for card in CARDS:
        for name in ( "draft_same", "draft_other", "draft_empty" ):
            assert PredictionSeenRequest( fold_opened=True, draft_at_reveal={ "value": card[ name ] } ).draft_at_reveal == { "value": card[ name ] }
