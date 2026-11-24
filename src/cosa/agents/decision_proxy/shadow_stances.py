"""
The two stored forecasts a decision row records in shadow.

One is the lookup three-way stance the prediction engine stored on the ask's prediction_log row.
The other is the full-answer baseline arm's stance, stored on the ask's prediction_arm_forecast row.
Each reader names why it has no stance, so the row says so instead of staying empty.

Dependency Rule:
    - Reads through the session it is given; imports the database models only inside the functions.
"""
import uuid

from cosa.agents.decision_proxy.agreement import THREE_WAY_STANCES

STATUS_NO_FORECAST_ROW = "no_forecast_row"
STATUS_NOT_RECORDED    = "not_recorded"
STATUS_MALFORMED       = "malformed"
STATUS_NO_BASELINE_ROW = "no_baseline_row"
STATUS_UNAVAILABLE     = "unavailable"
STATUS_NO_PROBABILITIES = "no_probabilities"


def stored_three_way_stance( session, notification_id ):
    """
    Read the lookup three-way stance stored on an ask's prediction_log row.

    Requires:
        - session is a database session; notification_id is the asking notification's id as text

    Ensures:
        - returns the stored stance dict as it was stored
        - returns { status: no_forecast_row } when the notification has no row
        - returns { status: not_recorded } when the column holds nothing, or an empty value
        - returns { status: malformed, stored_type } when the column holds anything but a dict
        - changes nothing

    Raises:
        - whatever the database raises; the caller names that as an error status
    """
    from cosa.rest.db.repositories.prediction_log_repository import PredictionLogRepository
    row = PredictionLogRepository( session ).get_by_notification_id( notification_id )
    if row is None: return { "status": STATUS_NO_FORECAST_ROW }
    stored = row.three_way_shadow
    if not stored: return { "status": STATUS_NOT_RECORDED }
    if not isinstance( stored, dict ): return { "status": STATUS_MALFORMED, "stored_type": stored.__class__.__name__ }
    return stored


def full_answer_stance( session, notification_id ):
    """
    Read the full-answer baseline arm's yes, no or neither stance from an ask's row.

    Requires:
        - session is a database session; notification_id is the asking notification's id as text

    Ensures:
        - returns { value, confidence, probabilities } for a finished forecast that carries the three probabilities and a value that is one of the three stances
        - returns { status: no_baseline_row } when the ask has no baseline arm row
        - returns { status: unavailable, reason } when the row has no forecast or no ready time, the reason being its abstention reason
        - returns { status: no_probabilities } for a forecast of the old reply format, or one whose value is not a stance
        - changes nothing

    Raises:
        - ValueError if notification_id is not a UUID
        - whatever the database raises; the caller names either as an error status
    """
    from cosa.agents.prediction_engine import context_baseline
    from cosa.rest.postgres_models import PredictionArmForecast
    row = session.query( PredictionArmForecast ).filter( PredictionArmForecast.notification_id == uuid.UUID( str( notification_id ) ),
                                                         PredictionArmForecast.arm == context_baseline.ARM ).first()
    if row is None: return { "status": STATUS_NO_BASELINE_ROW }
    forecast = row.forecast
    if forecast is None or row.forecast_ready_at is None: return { "status": STATUS_UNAVAILABLE, "reason": row.abstention_reason }
    probabilities = forecast.get( "probabilities" ) if isinstance( forecast, dict ) else None
    if not isinstance( probabilities, dict ) or forecast.get( "value" ) not in THREE_WAY_STANCES: return { "status": STATUS_NO_PROBABILITIES }
    return { "value": forecast[ "value" ], "confidence": forecast.get( "confidence" ), "probabilities": probabilities }
