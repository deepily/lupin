"""
Unit tests for POST /api/notify/prediction-vote/{notification_id}.

A thumbs up or down on a prediction hint becomes a human-confirmed training case, so
what is RECORDED matters more than what is returned. The endpoint resolves two of the
five recorded fields itself:

🔴 THE QUESTION AND THE RESPONSE TYPE ARE RESOLVED AUTHORITATIVELY, NOT ECHOED. The
client may omit either, and the endpoint fills them from the persisted notification —
because `notification.message` is stored and the predicted value is not. The tests
therefore give the client and the stored row DIFFERENT values, so "used the client's"
and "used the row's" are different recorded cases rather than the same one.

🔴 THE LOOKUP IS FAIL-SOFT AND MUST STAY THAT WAY. A malformed id or a failed read
falls through to whatever the client supplied — deliberately, so a vote is not lost to
a database hiccup. That `except: pass` is invisible to any test that only checks the
happy path, so both the non-UUID id and the exploding lookup are posed and asserted to
still record.

🔴 AND THE TWO 422s GUARD DIFFERENT THINGS. No resolvable question is one; a missing
predicted_value is the other, and it is checked even when the question resolved fine —
a case recorded with a null prediction is training noise that cannot be un-learned.

Fixture: `tests.helpers.notifications_endpoint_harness`.
"""

import pytest

from tests.helpers.notifications_endpoint_harness import (
    FROZEN_TIMESTAMP, a_uuid, assert_no_accidental_500, make_harness_fixture )

harness = make_harness_fixture()


_NID = a_uuid( "voted-notification" )
_URL = f"/api/notify/prediction-vote/{_NID}"


class _StoredRow:
    """The persisted notification. Its values differ from every client-supplied one."""
    message       = "STORED-QUESTION-VALUE"
    response_type = "STORED-RESPONSE-TYPE"


@pytest.fixture
def engine( monkeypatch ):
    """
    Replace the prediction engine at its factory, on its own module — the handler
    imports `get_prediction_engine` inside the function body, so patching the router's
    namespace would leave the real engine (and a LanceDB write) running.
    """
    import cosa.agents.prediction_engine as pe
    state = { "calls": [], "result": { "ratification_state": "approved", "updated": True },
              "raises": None }

    class _Engine:
        def record_hint_vote( self, **kwargs ):
            state[ "calls" ].append( kwargs )
            if state[ "raises" ] is not None:
                raise state[ "raises" ]
            return state[ "result" ]

    monkeypatch.setattr( pe, "get_prediction_engine", lambda: _Engine() )
    return state


def _body( **overrides ):
    body = { "vote": "up", "predicted_value": "PREDICTED-VALUE" }
    body.update( overrides )
    return body


class TestTheRecordedCase:

    def test_a_vote_is_recorded_and_its_outcome_reported( self, harness, engine ):
        harness.repo.returns( "get_by_id", _StoredRow() )
        r = harness.client.post( _URL, json=_body( question="CLIENT-QUESTION" ) )
        assert_no_accidental_500( r )
        body = r.json()
        assert body[ "status" ]             == "success"
        assert body[ "vote" ]               == "up"
        assert body[ "ratification_state" ] == "approved"
        assert body[ "updated" ]            is True
        assert body[ "timestamp" ]          == FROZEN_TIMESTAMP
        assert len( engine[ "calls" ] ) == 1

    def test_the_reported_outcome_comes_from_the_engine_not_from_the_vote( self, harness, engine ):
        """
        An up-vote that the engine REJECTS must report rejected. Hardcoding "approved"
        for an up-vote would pass every other test here, and would silently claim a
        case was accepted when it was not.
        """
        harness.repo.returns( "get_by_id", _StoredRow() )
        engine[ "result" ] = { "ratification_state": "rejected", "updated": False }
        body = harness.client.post( _URL, json=_body( question="Q" ) ).json()
        assert body[ "vote" ]               == "up"
        assert body[ "ratification_state" ] == "rejected"
        assert body[ "updated" ]            is False

    def test_a_missing_updated_flag_defaults_to_false_not_true( self, harness, engine ):
        """`updated` distinguishes a new case from a flipped one; absent must mean new."""
        harness.repo.returns( "get_by_id", _StoredRow() )
        engine[ "result" ] = { "ratification_state": "approved" }
        assert harness.client.post( _URL, json=_body( question="Q" ) ).json()[ "updated" ] is False

    def test_every_supplied_field_reaches_the_engine( self, harness, engine ):
        harness.repo.returns( "get_by_id", _StoredRow() )
        harness.client.post( _URL, json=_body( question="CLIENT-QUESTION",
                                               category="CATEGORY-VALUE",
                                               response_type="CLIENT-RESPONSE-TYPE" ) )
        call = engine[ "calls" ][ 0 ]
        assert call[ "notification_id" ] == _NID
        assert call[ "question" ]        == "CLIENT-QUESTION"
        assert call[ "predicted_value" ] == "PREDICTED-VALUE"
        assert call[ "category" ]        == "CATEGORY-VALUE"
        assert call[ "response_type" ]   == "CLIENT-RESPONSE-TYPE"
        assert call[ "vote" ]            == "up"

    def test_a_down_vote_travels_as_down( self, harness, engine ):
        harness.repo.returns( "get_by_id", _StoredRow() )
        harness.client.post( _URL, json=_body( vote="down", question="Q" ) )
        assert engine[ "calls" ][ 0 ][ "vote" ] == "down"


class TestResolvingTheQuestion:

    def test_an_omitted_question_is_taken_from_the_stored_notification( self, harness, engine ):
        """
        🔴 THE STORED VALUE AND THE CLIENT VALUE ARE DIFFERENT STRINGS ON PURPOSE.
        If they matched, "resolved from the row" and "echoed the client" would record
        the same case and neither test could tell them apart.
        """
        harness.repo.returns( "get_by_id", _StoredRow() )
        harness.client.post( _URL, json=_body() )
        assert engine[ "calls" ][ 0 ][ "question" ] == "STORED-QUESTION-VALUE"

    def test_a_supplied_question_WINS_over_the_stored_one( self, harness, engine ):
        harness.repo.returns( "get_by_id", _StoredRow() )
        harness.client.post( _URL, json=_body( question="CLIENT-QUESTION" ) )
        assert engine[ "calls" ][ 0 ][ "question" ] == "CLIENT-QUESTION"

    def test_a_whitespace_only_question_counts_as_omitted( self, harness, engine ):
        """
        Blank is not the same as absent to a `or` chain, and a case recorded under a
        blank question is unmatchable forever. The strip is the behaviour.
        """
        harness.repo.returns( "get_by_id", _StoredRow() )
        harness.client.post( _URL, json=_body( question="   " ) )
        assert engine[ "calls" ][ 0 ][ "question" ] == "STORED-QUESTION-VALUE"

    def test_an_omitted_response_type_is_taken_from_the_stored_row( self, harness, engine ):
        harness.repo.returns( "get_by_id", _StoredRow() )
        harness.client.post( _URL, json=_body( question="Q" ) )
        assert engine[ "calls" ][ 0 ][ "response_type" ] == "STORED-RESPONSE-TYPE"

    def test_a_supplied_response_type_wins( self, harness, engine ):
        harness.repo.returns( "get_by_id", _StoredRow() )
        harness.client.post( _URL, json=_body( question="Q", response_type="CLIENT-RESPONSE-TYPE" ) )
        assert engine[ "calls" ][ 0 ][ "response_type" ] == "CLIENT-RESPONSE-TYPE"

    def test_the_lookup_is_a_pure_read( self, harness, engine ):
        harness.repo.returns( "get_by_id", _StoredRow() )
        harness.client.post( _URL, json=_body() )
        harness.repo.assert_only_called( "get_by_id" )


class TestTheLookupIsFailSoft:
    """
    🔴 A VOTE MUST NOT BE LOST TO A DATABASE HICCUP. The resolution step swallows its
    own failures on purpose and falls back to what the client sent. Every test here
    asserts the vote WAS STILL RECORDED — a 500 would be the regression, and it is
    exactly what removing the except clause produces.
    """

    def test_a_non_uuid_id_still_records_with_the_clients_question( self, harness, engine ):
        r = harness.client.post( "/api/notify/prediction-vote/not-a-uuid",
                                 json=_body( question="CLIENT-QUESTION" ) )
        assert r.status_code == 200
        assert engine[ "calls" ][ 0 ][ "question" ]        == "CLIENT-QUESTION"
        assert engine[ "calls" ][ 0 ][ "notification_id" ] == "not-a-uuid"
        assert harness.repo.calls == [], "a non-uuid id must not reach the database"

    def test_an_absent_notification_still_records( self, harness, engine ):
        harness.repo.returns( "get_by_id", None )
        r = harness.client.post( _URL, json=_body( question="CLIENT-QUESTION" ) )
        assert r.status_code == 200
        assert engine[ "calls" ][ 0 ][ "question" ] == "CLIENT-QUESTION"

    def test_a_row_that_cannot_answer_an_attribute_still_records( self, harness, engine ):
        """
        🔴 ADDED AFTER A MUTATION SURVIVED, AND THE FIXTURE WAS THE DEFECT, NOT THE
        ASSERTIONS. Narrowing `except ( ValueError, AttributeError, TypeError )` down
        to `except ( ValueError, )` changed nothing anywhere in this file: every case
        posed reached the block through `uuid.UUID( "not-a-uuid" )`, which raises
        ValueError, so two of the three named exceptions were never exercised at all.

        This poses the AttributeError arm directly. The question is supplied, so
        resolution skips to `notif.response_type` on a row that does not have one —
        which is what a repo handing back a dict, or a partially-loaded row, produces.
        The vote must still be recorded: the resolution step is a convenience, and an
        answer a human already gave must not be lost to it.
        """
        class _RowWithoutAResponseType:
            message = "STORED-QUESTION-VALUE"
            def __getattr__( self, name ):
                raise AttributeError( name )

        harness.repo.returns( "get_by_id", _RowWithoutAResponseType() )
        r = harness.client.post( _URL, json=_body( question="CLIENT-QUESTION" ) )
        assert r.status_code == 200
        assert engine[ "calls" ][ 0 ][ "question" ]      == "CLIENT-QUESTION"
        assert engine[ "calls" ][ 0 ][ "response_type" ] is None

    def test_a_dead_database_is_a_500_and_the_vote_IS_lost( self, harness, engine ):
        """
        🔴 THE FAIL-SOFT IS NARROWER THAN IT LOOKS, AND I EXPECTED THE OPPOSITE.
        The except clause names only ValueError, AttributeError and TypeError, so a
        connection fault propagates out of the resolution block, past the guards, into
        the blanket handler — a 500, and the vote is never recorded.

        Pinned as it BEHAVES rather than as it reads. A `get_by_id` that RETURNS None
        falls through and still records (the test above); a `get_db` that RAISES does
        not. Both are "the notification could not be read", and they end differently.
        A widened except would make this a 200 and should be a deliberate decision,
        not a silent one.
        """
        harness.fail_db()
        r = harness.client.post( _URL, json=_body( question="CLIENT-QUESTION" ) )
        assert r.status_code == 500
        assert engine[ "calls" ] == []


class TestTheRefusals:

    def test_no_question_anywhere_is_a_422_and_records_nothing( self, harness, engine ):
        """Neither supplied nor resolvable — there is nothing to train on."""
        harness.repo.returns( "get_by_id", None )
        r = harness.client.post( _URL, json=_body() )
        assert r.status_code == 422
        assert engine[ "calls" ] == []

    def test_a_missing_predicted_value_is_a_422_even_with_a_good_question( self, harness, engine ):
        """
        The second guard is checked independently of the first. A case recorded with a
        null prediction is training noise, and it cannot be un-learned later.
        """
        harness.repo.returns( "get_by_id", _StoredRow() )
        r = harness.client.post( _URL, json={ "vote": "up", "question": "Q" } )
        assert r.status_code == 422
        assert "predicted_value" in r.json()[ "detail" ]
        assert engine[ "calls" ] == []

    def test_a_vote_that_is_neither_up_nor_down_is_a_422_from_the_schema( self, harness, engine ):
        r = harness.client.post( _URL, json={ "vote": "sideways", "predicted_value": "X",
                                              "question": "Q" } )
        assert r.status_code == 422
        assert engine[ "calls" ] == []

    def test_an_engine_ValueError_is_a_422_and_not_a_500( self, harness, engine ):
        """
        🔴 THE ENGINE REJECTING THE VOTE IS THE CALLER'S FAULT, NOT THE SERVER'S. The
        `except ValueError` clause sits ahead of the blanket handler; deleting it makes
        every rejected vote look like an outage, and the client retries forever.
        """
        harness.repo.returns( "get_by_id", _StoredRow() )
        engine[ "raises" ] = ValueError( "unknown vote polarity" )
        r = harness.client.post( _URL, json=_body( question="Q" ) )
        assert r.status_code == 422
        assert "unknown vote polarity" in r.json()[ "detail" ]

    def test_any_other_engine_fault_is_a_500( self, harness, engine ):
        harness.repo.returns( "get_by_id", _StoredRow() )
        engine[ "raises" ] = RuntimeError( "embedding service down" )
        assert harness.client.post( _URL, json=_body( question="Q" ) ).status_code == 500
