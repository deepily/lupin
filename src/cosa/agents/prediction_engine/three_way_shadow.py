#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
The three-way challenger run in shadow on a live yes/no ask.

The stance is stored beside today's forecast on the ask's prediction_log row.
It never reaches the card, the displayed forecast or the engine's own row fields.
"""

from typing import Any, Dict, List, Optional

import sqlalchemy as sa

from cosa.rest.db.vector_store_models import PredictionDecision
from cosa.rest.postgres_models import Notification, PredictionLog


def live_cases( session, owner_user_id: str ) -> List[Dict[str, Any]]:
    """
    Load the answered yes/no cases of one owner, in the shape the challenger reads.

    Requires:
        - session is an active SQLAlchemy session
        - owner_user_id is the owner's id as text

    Ensures:
        - returns one dict per answered yes/no ask of the owner that has a stored case row, in answer order
        - each dict holds id, decision_value, ratification_state, response_type, question_embedding,
          owner_user_id, answer_source, responded_at, category, title, message, sender_id and asked_at
        - asked_at is the ledger's stamp, or the notification's creation time for a row written before the ledger
        - an ask with no stored case row, or not yet answered, is left out
    """
    decisions = { d.id: d for d in session.execute( sa.select( PredictionDecision ).where(
        PredictionDecision.response_type == "yes_no", PredictionDecision.owner_user_id == str( owner_user_id ) ) ).scalars() }
    query     = ( sa.select( PredictionLog, Notification )
                  .join( Notification, Notification.id == PredictionLog.notification_id )
                  .where( PredictionLog.response_type == "yes_no", PredictionLog.responded_at.is_not( None ) )
                  .order_by( PredictionLog.responded_at ) )
    cases = []
    for log, notification in session.execute( query ).all():
        decision = decisions.get( str( log.notification_id ) )
        if decision is None: continue
        cases.append( {
            "id"                 : decision.id,
            "decision_value"     : decision.decision_value,
            "ratification_state" : decision.ratification_state,
            "response_type"      : log.response_type,
            "question_embedding" : None if decision.question_embedding is None else list( decision.question_embedding ),
            "owner_user_id"      : decision.owner_user_id,
            "answer_source"      : decision.answer_source,
            "responded_at"       : log.responded_at,
            "category"           : decision.category,
            "title"              : notification.title,
            "message"            : notification.message,
            "sender_id"          : notification.sender_id,
            "asked_at"           : log.asked_at if log.asked_at is not None else notification.created_at,
        } )
    return cases


def stance_of( forecast: Dict[str, Any] ) -> Dict[str, Any]:
    """
    Reduce a three-way forecast to what the row stores.

    Requires:
        - forecast is what three_way_stance.three_way_forecast returns

    Ensures:
        - returns { value, qualifier, confidence, probabilities, neighbours }, where neighbours is the count of neighbours that voted
    """
    return { "value": forecast[ "value" ], "qualifier": forecast[ "qualifier" ], "confidence": forecast[ "confidence" ],
             "probabilities": forecast[ "probabilities" ], "neighbours": len( forecast[ "neighbour_ids" ] ) }


def unavailable( reason: str, error_class: Optional[str] = None ) -> Dict[str, Any]:
    """
    Name why the challenger gave no stance, so the row says so rather than staying NULL.

    Requires:
        - reason is a short word such as no_embedding or error

    Ensures:
        - returns { status: reason }, plus error_class when one is given
    """
    stance = { "status": reason }
    if error_class is not None: stance[ "error_class" ] = error_class
    return stance
