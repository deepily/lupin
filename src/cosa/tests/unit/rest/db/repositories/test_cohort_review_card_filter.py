"""
The replay cohort leaves out review-card asks.

This filter ships before the learner's first review card. Rachel's probe of 20 Nov: one review-card ask and one plain ask, both scored, gave two rows. The marker is
read from the ask's response_options and from nothing else, so the stored answer carries no copy of it here.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from cosa.research.preference_replay.cohorts import cohort_asks, scored_rows
from cosa.rest.postgres_models import Base, Notification, PredictionLog, User

SENDER = "claude.code@lupin.deepily.ai#00000002"
ASKED  = datetime( 2026, 11, 12, 12, 0, tzinfo=timezone.utc )


@pytest.fixture
def cohort_session( pg_engine, db_session ):
    """A rolled-back session on the throwaway database, with the three ledger tables present."""
    Base.metadata.create_all( bind=pg_engine, tables=[ User.__table__, Notification.__table__, PredictionLog.__table__ ], checkfirst=True )
    return db_session


def _plant( session, specs ):
    """
    Plant one user and a scored yes/no ask per ( key, options ).

    Ensures:
        - each ask's notification carries its options
        - returns the notification id of each spec, in order
    """
    uid = uuid.uuid4()
    session.add( User( id=uid, email=f"review-{uid.hex[:8]}@test.local", password_hash="x", email_verified=True, is_active=True,
                       is_protected=False, roles={ "roles": [ "user" ] }, created_at=datetime.now( timezone.utc ) ) )
    session.flush()
    ids = []
    for offset, ( key, options ) in enumerate( specs ):
        nid, at = uuid.uuid4(), ASKED + timedelta( hours=offset )
        session.add( Notification( id=nid, sender_id=SENDER, recipient_id=uid, title=f"Ask {key}", message=f"Should {key} proceed?",
                                   type="task", priority="high", created_at=at - timedelta( seconds=45 ), sender_persona="cohort",
                                   response_requested=True, state="created", response_options=options ) )
        session.flush()
        session.add( PredictionLog( notification_id=nid, response_type="yes_no", category="input", predicted_value={ "value": "yes" },
                                    prediction_confidence=0.9, prediction_strategy="cbr_majority_vote", similar_case_count=3,
                                    accuracy_match=True, predicted_at=at, asked_at=at - timedelta( seconds=30 ),
                                    actual_value={ "value": "yes" }, responded_at=at + timedelta( seconds=5 ) ) )
        ids.append( nid )
    session.flush()
    return ids


def test_a_review_card_ask_is_not_in_the_cohort( cohort_session ):
    plain, card = _plant( cohort_session, [ ( "plain", None ), ( "card", { "review_card": True } ) ] )
    assert [ r.notification_id for r in scored_rows( cohort_session, "yes_no" ) ] == [ plain ]
    assert [ a[ "id" ] for a in cohort_asks( cohort_session, "yes_no", vectors=None ) ] == [ str( plain ) ]
    assert card not in [ r.notification_id for r in scored_rows( cohort_session, "yes_no" ) ]


def test_only_the_exact_marker_excludes( cohort_session ):
    ids = _plant( cohort_session, [ ( "false", { "review_card": False } ), ( "text", { "review_card": "true" } ),
                                    ( "other", { "questions": [] } ), ( "none", None ), ( "card", { "review_card": True } ) ] )
    assert [ r.notification_id for r in scored_rows( cohort_session, "yes_no" ) ] == ids[ :4 ]


def test_the_window_and_the_marker_both_apply( cohort_session ):
    plain, _ = _plant( cohort_session, [ ( "plain", None ), ( "card", { "review_card": True } ) ] )
    assert [ r.notification_id for r in scored_rows( cohort_session, "yes_no", "after" ) ] == [ plain ]
    assert scored_rows( cohort_session, "yes_no", "before" ) == []
