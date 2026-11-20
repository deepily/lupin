"""
The cohorts the replay and the audits both count: scored asks in the audit windows.

An audit window is named by the row's ``predicted_at``, because the audit query groups on that column.
Asked time would move an ask that sat open across a cut-over into another window. The two cut-over
instants of each response type come from the audit query itself. A test reads them back out of that
query, so a drift here shows up.

A scored ask is a ``prediction_log`` row with a non-null ``accuracy_match``. The cohort leaves out the
rows the admin accuracy report leaves out. It calls the report's own clauses, so a rule changed there
is changed here.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import sqlalchemy as sa

from cosa.agents.prediction_engine.review_card import REVIEW_CARD_SOURCE, is_review_card
from cosa.rest.db.repositories.prediction_log_repository import (
    TEST_OVERRIDE_SOURCE, legacy_confidence_clause, legacy_similarity_clause )
from cosa.rest.postgres_models import Notification, PredictionLog
from cosa.rest.db.vector_store_models import PredictionDecision

WINDOW_NAMES = ( "before", "undetermined", "after" )

# The two cut-over instants per response type: the last forecast of the old behaviour, and the first of the new.
CUTOVERS = {
    "yes_no"          : ( datetime( 2026, 11, 4, 15, 54, 58, 965194, tzinfo=timezone.utc ),
                          datetime( 2026, 11, 11, 14, 59, 54, 960998, tzinfo=timezone.utc ) ),
    "multiple_choice" : ( datetime( 2026, 11, 6, 22, 55, 45, 152915, tzinfo=timezone.utc ),
                          datetime( 2026, 11, 9, 15, 27, 34, 357296, tzinfo=timezone.utc ) ),
}


def window_of( predicted_at: datetime, response_type: str ) -> str:
    """
    Name the audit window a forecast falls in.

    Requires:
        - predicted_at is an aware datetime
        - response_type is yes_no or multiple_choice

    Ensures:
        - returns before at or up to the first cut-over, undetermined up to the second, else after

    Raises:
        - ValueError if response_type has no audit windows
    """
    if response_type not in CUTOVERS: raise ValueError( f"no audit windows for response type {response_type!r}" )
    first, second = CUTOVERS[ response_type ]
    if predicted_at <= first:  return "before"
    if predicted_at <  second: return "undetermined"
    return "after"


def counted_scored_filter() -> Any:
    """
    The SQL condition for a row the admin report counts and has scored.

    Ensures:
        - true for a row that is not a test override, not a legacy similarity or confidence row, and has an accuracy_match
    """
    return sa.and_(
        sa.func.coalesce( PredictionLog.forecast_source, "" ) != TEST_OVERRIDE_SOURCE,
        sa.not_( sa.func.coalesce( legacy_similarity_clause(), False ) ),
        sa.not_( legacy_confidence_clause() ),
        PredictionLog.accuracy_match.isnot( None ),
    )


def scored_rows( session, response_type: str, window: Optional[str] = None ) -> List[PredictionLog]:
    """
    List the scored forecasts of one response type, optionally of one window.

    Requires:
        - session is an active SQLAlchemy session
        - window is None or one of WINDOW_NAMES

    Ensures:
        - returns the rows the admin report would count and score, in predicted_at order
        - leaves out an ask whose response_options carries the review-card marker (is_review_card, read from the ask-time field and nothing else); a review card is the learner's question, not a real ask
        - with a window, only the rows window_of puts there

    Raises:
        - ValueError if window is not None and not a window name
    """
    if window is not None and window not in WINDOW_NAMES: raise ValueError( f"window must be one of {WINDOW_NAMES}, got {window!r}" )
    pairs = session.query( PredictionLog, Notification.response_options ) \
                   .outerjoin( Notification, Notification.id == PredictionLog.notification_id ) \
                   .filter( PredictionLog.response_type == response_type, counted_scored_filter() ) \
                   .order_by( PredictionLog.predicted_at ).all()
    return [ row for row, options in pairs
             if not is_review_card( options ) and ( window is None or window_of( row.predicted_at, response_type ) == window ) ]


HUMAN_SOURCE = "ui"


def answer_source_of( response_value: Any, response_options: Any = None ) -> str:
    """
    Name where an answer came from: review card, human or unknown.

    Requires:
        - response_value is a dict, a JSON string, or None
        - response_options is the ask's stored schema (dict, JSON string or None); None means an unmarked ask

    Ensures:
        - returns "review_card" whenever the ask carries the marker, whatever the stored answer says
        - otherwise returns "human" only when the source field equals "ui"
    """
    if is_review_card( response_options ): return REVIEW_CARD_SOURCE
    if isinstance( response_value, str ): response_value = json.loads( response_value )
    if isinstance( response_value, dict ) and response_value.get( "source" ) == HUMAN_SOURCE: return "human"
    return "unknown"


def _question_vector( decision, ask_id: str, vectors: Optional[Dict[str, List[float]]] ) -> Optional[List[float]]:
    """
    Pick an ask's vector from the side file, or from its case row when no side file is given.

    Requires:
        - decision is a prediction_decisions row or None; vectors is a dict by ask id or None

    Ensures:
        - with vectors given, returns a copy of its entry for ask_id, or None when absent
        - with vectors None, returns a copy of the row's stored vector, or None when there is no row or vector
    """
    if vectors is not None: return list( vectors[ ask_id ] ) if ask_id in vectors else None
    return list( decision.question_embedding ) if decision is not None and decision.question_embedding is not None else None


def cohort_asks( session, response_type: str, window: Optional[str] = None, *, vectors: Optional[Dict[str, List[float]]] ) -> List[Dict[str, Any]]:
    """
    Build the replay's ask dicts for one cohort.

    Requires:
        - session is an active SQLAlchemy session
        - response_type and window are as for scored_rows
        - vectors maps ask id to its question vector, as load_side_file returns it, or is None to read the stored vectors

    Ensures:
        - returns one dict per scored row, in predicted_at order, with the store record fields, responded_at and
          the ask fields title, message, sender_id, asked_at, recipient_id, response_options and actual_value
        - with vectors given, question_embedding is the side file's vector for the ask id, for every ask; the case
          row's own vector is never read, and an id the side file lacks gets None and is not replayable
        - with vectors None, it is the case row's stored vector, or None when there is no row or no vector
        - a case's category, answer and owner come from its prediction_decisions row, keyed by the notification id
        - with no such row the owner is the notification's recipient_id, the field the engine compares against, and
          answer_source is "human" when the notification's response_value.source is "ui" and "unknown" when it is
          missing or anything else (Rick's ruling, 19 Nov); the engine votes only with human cases
        - asked_at is the ledger's stamp, or the notification's creation time for a row written before the ledger
        - carries logged_value and logged_match, what the log recorded, for a baseline arm to score
        - the cases hold their final value, because no revision history is stored
        - a multiple-choice row, which stores {"answers": ...}, gets that dict as sorted JSON text for its fallback decision_value

    Raises:
        - ValueError as scored_rows does
    """
    rows = scored_rows( session, response_type, window )
    asks = []
    for row in rows:
        notification = session.get( Notification, row.notification_id )
        decision     = session.get( PredictionDecision, str( row.notification_id ) )
        # yes/no and open-ended rows store {"value": ...}; multiple choice stores {"answers": {title: choice}}
        actual       = row.actual_value[ "value" ] if "value" in row.actual_value else json.dumps( row.actual_value, sort_keys=True )
        asks.append( {
            "id"                 : str( row.notification_id ),
            "question"           : decision.question if decision is not None else notification.message,
            "category"           : decision.category if decision is not None else row.category,
            "decision_value"     : decision.decision_value if decision is not None else actual,
            "ratification_state" : decision.ratification_state if decision is not None else "not_required",
            "data_origin"        : decision.data_origin if decision is not None else "organic",
            "response_type"      : row.response_type,
            "question_embedding" : _question_vector( decision, str( row.notification_id ), vectors ),
            "created_at"         : decision.created_at if decision is not None else row.predicted_at.isoformat(),
            "owner_user_id"      : decision.owner_user_id if decision is not None else str( notification.recipient_id ),
            "answer_source"      : decision.answer_source if decision is not None else answer_source_of( notification.response_value, notification.response_options ),
            "responded_at"       : row.responded_at,
            "title"              : notification.title,
            "message"            : notification.message,
            "sender_id"          : notification.sender_id,
            "asked_at"           : row.asked_at if row.asked_at is not None else notification.created_at,
            "recipient_id"       : str( notification.recipient_id ),
            "response_options"   : notification.response_options,
            "actual_value"       : row.actual_value,
            "logged_value"       : row.predicted_value,
            "logged_match"       : row.accuracy_match,
        } )
    return asks
