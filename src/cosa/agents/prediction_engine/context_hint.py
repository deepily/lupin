"""
The baseline forecast as a card shows it: payload, late event, fetch read and settle.

The card opens with its foundation hint. When the display switch is on, it also carries a context payload
that starts at the state forecasting. The background job stores its row, and this module turns the row into
the payload. A server event hands an open fold the new payload, and a fold opened later fetches it.

A restart kills a job in flight before it writes a row, so the row is the record of what happened.
A card with no row after the give-up time reads forecast_timed_out.
When the card is answered, the same reason is written as a row.
So the ledger holds a terminal state for every card the job was meant to forecast.
"""

import asyncio
import uuid
from datetime import datetime, timezone

from cosa.agents.prediction_engine import context_baseline
from cosa.agents.prediction_engine.principles_forecast import _row_present, _write_row
from cosa.agents.prediction_engine.review_card import is_review_card
from cosa.rest.db.repositories.prediction_log_repository import TEST_OVERRIDE_SOURCE
from cosa.rest.postgres_models import Notification, PredictionArmForecast, PredictionLog
from cosa.utils.iso_timestamp import aware_moment

EVENT_NAME            = "prediction_hint_updated"
PAYLOAD_KEY           = "context_forecast"
STATE_FORECASTING     = "forecasting"
STATE_READY           = "ready"
STATE_UNAVAILABLE     = "unavailable"
STATE_TIMED_OUT       = "forecast_timed_out"
REASON_TIMED_OUT      = "forecast_timed_out"
GIVE_UP_SECONDS       = 30
STRATEGY              = "context_baseline"


def should_forecast( response_type, review_card, overridden ):
    """
    Say whether a card gets the background forecast.

    Requires:
        - response_type is the card's response type; review_card and overridden are bools

    Ensures:
        - returns True only for a yes/no or multiple-choice card that is not a review card and carries no injected hint
        - does not read the switch; the caller and run_context_forecast do
    """
    return response_type in context_baseline.SUPPORTED_TYPES and not review_card and not overridden


def ready_payload( forecast, retrieval_metric ):
    """
    Build the payload of a ready forecast.

    Requires:
        - forecast is the typed forecast context_baseline.parse_reply returns
        - retrieval_metric is the metric name the card's other payload carries

    Ensures:
        - returns { state ready, retrieval_metric, strategy, predicted_value, confidence }
        - predicted_value is the answer string for a yes/no forecast and { answers } for a multiple-choice one, as the foundation hint shows them
    """
    value = forecast[ "value" ] if "value" in forecast else { "answers": forecast[ "answers" ] }
    return { "state": STATE_READY, "retrieval_metric": retrieval_metric, "strategy": STRATEGY, "predicted_value": value,
             "confidence": round( forecast[ "confidence" ], 3 ) }


def payload_for( row, asked_at, now, retrieval_metric ):
    """
    Turn the card's baseline row, or its absence, into the payload the card shows.

    Requires:
        - row is the card's prediction_arm_forecast row for the baseline arm, or None
        - asked_at and now are aware datetimes

    Ensures:
        - a row with a forecast and a ready time gives the ready payload
        - a row with the reason forecast_timed_out gives that state
        - any other row gives the state unavailable, naming the reason
        - no row gives forecasting until GIVE_UP_SECONDS after the ask, and forecast_timed_out from then on
    """
    if row is None:
        late = ( now - asked_at ).total_seconds() >= GIVE_UP_SECONDS
        return { "state": STATE_TIMED_OUT if late else STATE_FORECASTING }
    if row.forecast is not None and row.forecast_ready_at is not None: return ready_payload( row.forecast, retrieval_metric )
    if row.abstention_reason == REASON_TIMED_OUT: return { "state": STATE_TIMED_OUT }
    return { "state": STATE_UNAVAILABLE, "reason": row.abstention_reason }


def read_payload( session_factory, notification_id, now, retrieval_metric ):
    """
    Read the payload for one card from the database.

    Requires:
        - session_factory returns a context-managed session; notification_id is a UUID string

    Ensures:
        - returns payload_for's answer for the card's baseline row and its ask time
        - returns None when the notification does not exist

    Raises:
        - ValueError if notification_id is not a UUID
    """
    key     = uuid.UUID( str( notification_id ) )
    payload = None
    with session_factory() as session:
        card = session.get( Notification, key )
        if card is not None:
            row     = session.query( PredictionArmForecast ).filter( PredictionArmForecast.notification_id == key,
                                                                     PredictionArmForecast.arm == context_baseline.ARM ).first()
            payload = payload_for( row, aware_moment( card.created_at ), now, retrieval_metric )
    return payload


def settle_unfinished( session_factory, notification_id ):
    """
    Give a card that was answered with no baseline row its terminal state.

    Requires:
        - session_factory returns a context-managed session; notification_id names an ask that has been answered

    Ensures:
        - with the forecast switch off, a row already stored, a card type the job does not read, a review card or an injected hint, nothing is written
        - otherwise one baseline row is written with no forecast and the reason forecast_timed_out
        - returns True when it wrote a row

    Raises:
        - LookupError if the notification does not exist
    """
    if not context_baseline.context_forecast_enabled(): return False
    key = uuid.UUID( str( notification_id ) )
    skip, asked = True, None
    with session_factory() as session:
        card = session.get( Notification, key )
        if card is not None:
            injected = session.query( PredictionLog.forecast_source ).filter( PredictionLog.notification_id == key ).first()
            skip     = ( not should_forecast( card.response_type, is_review_card( card.response_options ), False )
                         or ( injected is not None and injected[ 0 ] == TEST_OVERRIDE_SOURCE )
                         or _row_present( session, key, context_baseline.ARM ) )
            asked    = aware_moment( card.created_at )
    if card is None: raise LookupError( f"notification {notification_id} does not exist" )
    if skip: return False
    return _write_row( session_factory, key, asked, None, None, context_baseline.predictor_version(), [], REASON_TIMED_OUT, context_baseline.ARM )


async def run_and_publish( notification_id, emit, retrieval_metric, session_factory=None, run=None, clock=None ):
    """
    Run the baseline job for one card, then tell an open fold what it found.

    Requires:
        - notification_id names a committed ask
        - emit( event, data ) sends a server event to the card's user; it may raise
        - run is None (context_baseline.run_context_forecast) or a stand-in with its signature, for tests
        - clock is None or a function returning an aware datetime

    Ensures:
        - the job's row is stored by the job itself, before this function looks at it
        - with the display switch on, one event named EVENT_NAME carries the notification id and the card's current payload, whatever the job's outcome
        - with the display switch off, nothing is sent and the job still ran
        - a failure of the job, the read or the emit is printed and never raised, so it cannot reach the ask
        - returns the job's { status, reason }, or None when the job itself raised
    """
    if session_factory is None:
        from cosa.rest.db.database import get_db
        session_factory = get_db
    now = clock if clock is not None else ( lambda: datetime.now( timezone.utc ) )
    try:
        result = await ( context_baseline.run_context_forecast if run is None else run )( notification_id, session_factory=session_factory )
    except Exception as job_error:
        print( f"[CONTEXT-FORECAST] ⚠️ Job for {notification_id} raised (non-fatal): {job_error}" )
        return None
    if context_baseline.context_display_enabled():
        try:
            payload = await asyncio.to_thread( read_payload, session_factory, notification_id, now(), retrieval_metric )
            if payload is not None: emit( EVENT_NAME, { "notification_id": str( notification_id ), PAYLOAD_KEY: payload } )
        except Exception as publish_error:
            print( f"[CONTEXT-FORECAST] ⚠️ Publish for {notification_id} failed (non-fatal): {publish_error}" )
    return result
