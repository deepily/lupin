"""
The per-arm summary: timeliness, the late flag and the switch rate, one row for each arm.

Every arm writes one prediction_arm_forecast row for each card it forecast. This module joins those rows
to the card's prediction_log row, which holds the answer time, the reveal time, the draft and the final answer.

Timeliness is the share of an arm's answered cards whose forecast was ready at or before the answer.
A forecast ready after the answer is late. A forecast with no ready time on an answered card is not ready.
A forecast the concurrency cap turned away is capped, and the cap takes precedence over a missing ready time.
Timely, late, not ready and capped add up to the answered cards. A card with no answer yet is counted as a forecast only.
A forecast whose card has no prediction_log row is counted as orphaned, so it cannot drop out unseen.
An answered card the arm wrote no row for is counted in no_row, so a missing forecast cannot hide.
An answer time with no final answer is counted in no_final, since there is nothing to classify.

The exposure rules are not written here. The class of each card and the switch rate come from
cosa.agents.prediction_engine.exposure, so every report shares one rule.
A card revealed in time is exposed when its draft is missing or cannot be compared with its answer.
An exposed card is left out of the switch rate.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

import sqlalchemy as sa
from sqlalchemy.orm import Session

from cosa.agents.prediction_engine.exposure import EXPOSED, SWITCHED, UNAIDED, UNANSWERED, classify_exposure, revealed_before_answer, switch_rate
from cosa.rest.postgres_models import PredictionArmForecast, PredictionLog
from cosa.utils.iso_timestamp import aware_moment

# The abstention reason a forecast row carries when the concurrency cap turned its card away.
CAPPED_REASON = "capacity"

SUMMARY_KEYS = (
    "arm", "forecasts", "orphaned", "no_row", "answered", "timely", "late", "not_ready", "capped", "timeliness",
    "revealed", "unaided", "switched", "exposed", "no_final", "switch_rate",
)


def summarize_arm( arm: str, rows: List[Dict[str, Any]], orphaned: int = 0, no_row: int = 0 ) -> Dict[str, Any]:
    """
    Fold one arm's joined rows into its summary.

    Requires:
        - every row is a dict with forecast_ready_at, abstention_reason, responded_at, fold_opened_at, draft, final and response_type
        - times are datetimes, naive ones read as UTC
        - the rows are the arm's rows and no other arm's
        - orphaned counts the arm's forecast rows that have no card row; no_row counts the answered cards it has no row for

    Ensures:
        - returns a dict whose keys are SUMMARY_KEYS and no others
        - forecasts counts the rows; answered counts rows with an answer time
        - capped, not_ready, timely and late partition the answered rows, in that order of precedence:
          turned away by the cap, no ready time, ready at or before the answer, ready after it
        - timeliness is timely over answered, None when nothing is answered
        - revealed counts answered rows revealed in time; unaided, switched, exposed and no_final partition the
          answered rows by exposure class, no_final being a row with an answer time and no final answer
        - switch_rate is exposure.switch_rate over the answered rows, None when none could be measured
    """
    tally = { "timely": 0, "late": 0, "not_ready": 0, "capped": 0, "revealed": 0, UNAIDED: 0, SWITCHED: 0, EXPOSED: 0, "no_final": 0, "answered": 0 }
    cards = []
    for row in rows:
        if row[ "responded_at" ] is None: continue
        responded = aware_moment( row[ "responded_at" ] )
        opened    = aware_moment( row[ "fold_opened_at" ] )
        ready     = aware_moment( row[ "forecast_ready_at" ] )
        tally[ "answered" ] += 1
        if row[ "abstention_reason" ] == CAPPED_REASON: tally[ "capped" ] += 1
        elif ready is None:                              tally[ "not_ready" ] += 1
        elif ready <= responded:                         tally[ "timely" ] += 1
        else:                                            tally[ "late" ] += 1
        label    = classify_exposure( opened, row[ "draft" ], row[ "final" ], row[ "response_type" ], responded )
        revealed = revealed_before_answer( opened, responded )
        tally[ "no_final" if label == UNANSWERED else label ] += 1
        if revealed: tally[ "revealed" ] += 1
        cards.append( ( label, revealed ) )
    return {
        "arm"         : arm,
        "forecasts"   : len( rows ),
        "orphaned"    : orphaned,
        "no_row"      : no_row,
        "answered"    : tally[ "answered" ],
        "timely"      : tally[ "timely" ],
        "late"        : tally[ "late" ],
        "not_ready"   : tally[ "not_ready" ],
        "capped"      : tally[ "capped" ],
        "timeliness"  : tally[ "timely" ] / tally[ "answered" ] if tally[ "answered" ] else None,
        "revealed"    : tally[ "revealed" ],
        "unaided"     : tally[ UNAIDED ],
        "switched"    : tally[ SWITCHED ],
        "exposed"     : tally[ EXPOSED ],
        "no_final"    : tally[ "no_final" ],
        "switch_rate" : switch_rate( cards ),
    }


def per_arm_summary( session: Session, since: Optional[datetime] = None ) -> List[Dict[str, Any]]:
    """
    Read every arm's forecast rows with their cards and summarize each arm.

    Requires:
        - session is open on a database holding prediction_arm_forecast and prediction_log
        - since is None, or a datetime: only cards predicted at or after it are summarized

    Ensures:
        - returns one summary per arm that has a row, sorted by arm name
        - a forecast row whose card has no prediction_log row is counted in that arm's orphaned and in nothing else;
          an orphan carries no time, so since never removes one
        - no_row is the number of answered cards in range that the arm has no forecast row for
        - a card whose draft_at_reveal is NULL is exposed when revealed in time
    """
    query = sa.select(
        PredictionArmForecast.arm, PredictionArmForecast.forecast_ready_at, PredictionArmForecast.abstention_reason,
        PredictionLog.notification_id, PredictionLog.responded_at, PredictionLog.fold_opened_at, PredictionLog.draft_at_reveal,
        PredictionLog.actual_value, PredictionLog.response_type, PredictionLog.predicted_at,
    ).select_from( PredictionArmForecast ).outerjoin( PredictionLog, PredictionLog.notification_id == PredictionArmForecast.notification_id )
    by_arm: Dict[str, List[Dict[str, Any]]] = {}
    orphans: Dict[str, int] = {}
    for arm, ready, reason, card, responded, opened, draft, actual, response_type, predicted in session.execute( query ).all():
        by_arm.setdefault( arm, [] )
        if card is None:
            orphans[ arm ] = orphans.get( arm, 0 ) + 1
            continue
        if since is not None and aware_moment( predicted ) < aware_moment( since ): continue
        by_arm[ arm ].append( {
            "forecast_ready_at": ready, "abstention_reason": reason, "responded_at": responded, "fold_opened_at": opened,
            "draft": draft, "final": actual, "response_type": response_type,
        } )
    return [ summarize_arm( arm, by_arm[ arm ], orphans.get( arm, 0 ), _answered_cards_without_row( session, arm, since ) ) for arm in sorted( by_arm ) ]


def _answered_cards_without_row( session: Session, arm: str, since: Optional[datetime] ) -> int:
    """
    Count the answered cards in range that one arm has no forecast row for.

    Requires:
        - session is open on a database holding prediction_arm_forecast and prediction_log

    Ensures:
        - returns the number of prediction_log rows with an answer time, predicted at or after since when given,
          for which no prediction_arm_forecast row of this arm exists
    """
    has_row = sa.select( PredictionArmForecast.id ).where(
        PredictionArmForecast.notification_id == PredictionLog.notification_id, PredictionArmForecast.arm == arm ).exists()
    query = sa.select( sa.func.count() ).select_from( PredictionLog ).where( PredictionLog.responded_at.isnot( None ), ~has_row )
    if since is not None: query = query.where( PredictionLog.predicted_at >= since )
    return session.execute( query ).scalar_one()


def render_summary( summaries: List[Dict[str, Any]] ) -> str:
    """
    Lay the summaries out as a markdown table, one line per arm.

    Requires:
        - summaries is what per_arm_summary returns

    Ensures:
        - returns a header, a rule and one line per summary, in the order given
        - a rate that is None reads "n/a"; a rate is shown to three places
    """
    def cell( value ): return "n/a" if value is None else f"{value:.3f}" if isinstance( value, float ) else str( value )
    lines = [ "| " + " | ".join( SUMMARY_KEYS ) + " |", "|" + "---|" * len( SUMMARY_KEYS ) ]
    lines += [ "| " + " | ".join( cell( s[ key ] ) for key in SUMMARY_KEYS ) + " |" for s in summaries ]
    return "\n".join( lines )
