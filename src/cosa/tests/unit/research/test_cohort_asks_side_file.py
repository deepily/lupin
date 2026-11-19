"""
cohort_asks reads each vector from the side file, and a rowless case is still a neighbour.

The replay tests run the real PredictionEngine over a fake session built from synthetic asks. The engine's
embedding call fails, so a pass shows the side-file vector was the one used.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cosa.research.preference_replay.cohorts import cohort_asks
from cosa.research.preference_replay.replay_loop import replay
from cosa.tests.unit.research.test_replay_loop import OWNER, SHA, _ask, _neighbours, _vector, engine  # noqa: F401 - engine is a fixture

CREATED = datetime( 2026, 11, 1, tzinfo=timezone.utc )


class _Session:
    """Answers session.get with a notification, and a decision row only for given ids."""

    def __init__( self, decisions=None, recipient="user-9", messages=None, response_value=None ):
        self.response_value = response_value
        self.decisions = decisions or {}
        self.recipient = recipient
        self.messages  = messages or {}

    def get( self, model, key ):
        if model.__name__ == "Notification":
            return SimpleNamespace( title="t", message=self.messages.get( key, "m" ), sender_id="s", created_at=CREATED,
                                    recipient_id=self.recipient, response_options=None, response_value=self.response_value )
        return self.decisions.get( key )


def _row( ask_id="n1", answered=None, category="c" ):
    return SimpleNamespace( notification_id=ask_id, category=category, response_type="yes_no", responded_at=answered, asked_at=None,
                            predicted_at=datetime( 2026, 11, 10, tzinfo=timezone.utc ), actual_value={ "value": "yes" },
                            predicted_value={ "value": "yes" }, accuracy_match=True )


def _decision( vector ):
    return SimpleNamespace( question="q", category="input", decision_value="yes", ratification_state="not_required", data_origin="organic",
                            question_embedding=vector, created_at="2026-11-10", owner_user_id="owner-1", answer_source="human" )


def _asks( session, rows, vectors ):
    with patch( "cosa.research.preference_replay.cohorts.scored_rows", return_value=rows ):
        return cohort_asks( session, "yes_no", vectors=vectors )


def test_the_vector_is_the_side_files_even_when_the_case_row_holds_another():
    asks = _asks( _Session( { "n1": _decision( [ 9.0, 9.0 ] ) } ), [ _row() ], { "n1": [ 1.0, 2.0 ] } )
    assert asks[ 0 ][ "question_embedding" ] == [ 1.0, 2.0 ]


def test_with_no_side_file_the_stored_vector_is_read_and_a_missing_row_or_vector_gives_none():
    assert _asks( _Session( { "n1": _decision( [ 9.0, 9.0 ] ) } ), [ _row() ], None )[ 0 ][ "question_embedding" ] == [ 9.0, 9.0 ]
    assert _asks( _Session( { "n1": _decision( None ) } ), [ _row() ], None )[ 0 ][ "question_embedding" ] is None
    assert _asks( _Session(), [ _row() ], None )[ 0 ][ "question_embedding" ] is None


def test_an_id_the_side_file_lacks_is_not_replayable_even_when_the_case_row_holds_a_vector():
    asks = _asks( _Session( { "n1": _decision( [ 9.0, 9.0 ] ) } ), [ _row() ], {} )
    assert asks[ 0 ][ "question_embedding" ] is None


@pytest.mark.parametrize( "response_value, source", [ ( { "source": "ui" }, "human" ), ( { "source": "proxy" }, "unknown" ),
                                                       ( {}, "unknown" ), ( None, "unknown" ) ] )
def test_an_ask_with_no_case_row_takes_its_owner_from_the_recipient_and_its_source_from_the_response_value( response_value, source ):
    ask = _asks( _Session( recipient="user-9", response_value=response_value ), [ _row() ], { "n1": [ 1.0 ] } )[ 0 ]
    assert ( ask[ "owner_user_id" ], ask[ "answer_source" ] ) == ( "user-9", source )


def test_an_ask_with_a_case_row_keeps_the_rows_owner_and_source_whatever_the_response_value_says():
    ask = _asks( _Session( { "n1": _decision( None ) }, recipient="user-9", response_value={ "source": "proxy" } ), [ _row() ], { "n1": [ 1.0 ] } )[ 0 ]
    assert ( ask[ "owner_user_id" ], ask[ "answer_source" ] ) == ( "owner-1", "human" )


def _as_row_and_notification( ask ):
    """Turn a synthetic replay ask into the row and the notification cohort_asks reads."""
    row = SimpleNamespace( notification_id=ask[ "id" ], category=ask[ "category" ], response_type="yes_no", responded_at=ask[ "responded_at" ],
                           asked_at=ask[ "asked_at" ], predicted_at=ask[ "asked_at" ], actual_value={ "value": ask[ "actual_value" ] },
                           predicted_value={ "value": "yes" }, accuracy_match=True )
    return row, ask[ "message" ]


def test_a_case_with_no_row_is_a_neighbour_of_a_later_ask( engine ):
    """A new case built from the side file and the notification is used by a later forecast."""
    synthetic = [ _ask( engine, "early", 3, 0, "yes" ), _ask( engine, "target", 3, 30, "no" ) ]
    rows      = [ _as_row_and_notification( ask )[ 0 ] for ask in synthetic ]
    session   = _Session( recipient=OWNER, response_value={ "source": "ui" }, messages={ ask[ "id" ]: ask[ "message" ] for ask in synthetic } )
    asks      = _asks( session, rows, { ask[ "id" ]: _vector( 3 ) for ask in synthetic } )
    run       = replay( asks, engine, SHA )
    assert _neighbours( run, "target", asks ) == [ "early" ]
