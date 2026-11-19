"""
The displayed arm's sibling row and the check that none is missing.

prediction_log keeps one row per card. prediction_arm_forecast keeps one row per card and arm.
The forecast a card showed is stored in both, in one commit.
A standing check names any card that has the first without the second.
"""

import uuid
from typing import Any, Callable, Dict, List

import sqlalchemy as sa
from sqlalchemy.orm import Session

from cosa.rest.postgres_models import PredictionArmForecast, PredictionLog


def displayed_arm_hook( arm: str ) -> Callable[[ Session, Dict[str, Any] ], None]:
    """
    Make the pre-commit hook that writes the displayed arm's sibling row.

    Requires:
        - arm is a non-empty arm name

    Ensures:
        - returns a function( session, forecast ) for PredictionEngine.record_forecast's pre_commit_hook
        - the function adds one prediction_arm_forecast row, displayed true, from the forecast's
          notification_id, predictor_version, forecast, input_cutoff, evidence_ids, forecast_ready_at and
          abstention_reason, and flushes it so a constraint breach raises before the commit
        - it does not commit; the caller's commit stores this row with the prediction_log row

    Raises:
        - ValueError if arm is empty
    """
    if not arm: raise ValueError( "an arm name is required" )

    def write_displayed_sibling( session, forecast ):
        """
        Add the displayed arm's row on the caller's session.

        Requires:
            - forecast is the dict record_forecast hands a hook

        Ensures:
            - the row is flushed on the session, not committed
        """
        session.add( PredictionArmForecast(
            notification_id   = uuid.UUID( forecast[ "notification_id" ] ),
            arm               = arm,
            predictor_version = forecast[ "predictor_version" ],
            forecast          = forecast[ "forecast" ],
            input_cutoff      = forecast[ "input_cutoff" ],
            evidence_ids      = forecast[ "evidence_ids" ],
            forecast_ready_at = forecast[ "forecast_ready_at" ],
            abstention_reason = forecast[ "abstention_reason" ],
            displayed         = True,
        ) )
        session.flush()

    return write_displayed_sibling


def notifications_missing_displayed_sibling( session: Session ) -> List[uuid.UUID]:
    """
    Name every card whose prediction_log row has no displayed-arm sibling row.

    Requires:
        - session is open on a database holding prediction_log and prediction_arm_forecast

    Ensures:
        - returns the notification ids, sorted, of prediction_log rows with no prediction_arm_forecast
          row for the same notification whose displayed flag is true
        - an empty list means every prediction_log row has its displayed-arm sibling row
        - a sibling row of an arm that was not displayed does not stand in for the displayed one
    """
    sibling = sa.select( PredictionArmForecast.id ).where(
        PredictionArmForecast.notification_id == PredictionLog.notification_id,
        PredictionArmForecast.displayed.is_( True ),
    ).exists()
    rows = session.execute( sa.select( PredictionLog.notification_id ).where( ~sibling ) ).scalars().all()
    return sorted( rows, key=str )
