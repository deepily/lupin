"""
The displayed arm's sibling row and the check that none is missing.

prediction_log keeps one row per card. prediction_arm_forecast keeps one row per card and arm.
The forecast a card showed is stored in both, in one commit.
A standing check names any card that has the first without the second.
"""

import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List

import sqlalchemy as sa
from sqlalchemy.orm import Session

from cosa.agents.prediction_engine.config import FORECAST_SOURCE_FOUNDATION, FORECAST_SOURCE_TEST_OVERRIDE
from cosa.rest.postgres_models import PredictionArmForecast, PredictionLog

# The arm a forecast source stands for, read from the row's own forecast_source and never assumed.
# The abstention reason of a forecast row the concurrency cap turned away. Defined here once; the summary and the writers import it.
CAPPED_ARM_REASON = "capacity"

DISPLAYED_ARM_BY_FORECAST_SOURCE = { FORECAST_SOURCE_FOUNDATION: "A1", FORECAST_SOURCE_TEST_OVERRIDE: "test_override" }


def displayed_arm_for( forecast_source: str ) -> str:
    """
    Name the arm whose forecast a card showed.

    Requires:
        - forecast_source is the value record_forecast stores in forecast_source

    Ensures:
        - returns the arm name that source stands for

    Raises:
        - KeyError if no arm is registered for that source, so a new source must be registered here
    """
    return DISPLAYED_ARM_BY_FORECAST_SOURCE[ forecast_source ]


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


def notifications_missing_displayed_sibling( session: Session, since: datetime ) -> List[uuid.UUID]:
    """
    Name the cards since go-live whose prediction_log row has no displayed-arm sibling row.

    Requires:
        - session is open on a database holding prediction_log and prediction_arm_forecast
        - since is the moment the hook went live; rows predicted before it never had a sibling

    Ensures:
        - returns the notification ids, sorted, of prediction_log rows predicted at or after since with no
          prediction_arm_forecast row for the same notification whose displayed flag is true
        - a row predicted before since is never listed, so the answer is empty on a live table that is reconciled
        - an empty list means every prediction_log row has its displayed-arm sibling row
        - a sibling row of an arm that was not displayed does not stand in for the displayed one
    """
    sibling = sa.select( PredictionArmForecast.id ).where(
        PredictionArmForecast.notification_id == PredictionLog.notification_id,
        PredictionArmForecast.displayed.is_( True ),
    ).exists()
    rows = session.execute( sa.select( PredictionLog.notification_id ).where( PredictionLog.predicted_at >= since, ~sibling ) ).scalars().all()
    return sorted( rows, key=str )
