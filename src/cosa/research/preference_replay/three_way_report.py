#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Measure the three-way challenger in the replay, against always-yes and the margin rule.

The challenger joins a replay as one more baseline arm. The report gives each arm's wins over always-yes.
It also gives the genuine "no" and "neither" answers found, and the false alarms. The verdict follows the
plan's paired rule, mechanically. Unless the challenger is decisively better than always-yes, it stays in
shadow and the labelled always-yes baseline stays on display.
"""

from typing import Any, Callable, Dict, List, Optional

from cosa.agents.prediction_engine.three_way_stance import three_way_forecast
from cosa.research.preference_replay.calibration_fit import multiclass_brier, neither_recall_precision
from cosa.research.preference_replay.replay_loop import ENGINE_ARM, summarize
from cosa.utils.notification_utils import extract_qualifier_comment

STANCES        = ( "yes", "no", "neither" )
THREE_WAY_ARM  = "three_way"
BASELINE_ARM   = "always_yes"
DISPLAY_READY  = "decisively better than always-yes: may go on display"
STAYS_IN_SHADOW = "not decisively better than always-yes: stays in shadow, the labelled always-yes baseline stays on display"


def make_three_way_arm( half_life_days: float ) -> Callable[[ Dict[str, Any], List[Dict[str, Any]] ], Any]:
    """
    Build the replay baseline arm that forecasts with the three-way challenger.

    Requires:
        - half_life_days is positive

    Ensures:
        - returns arm( ask, visible_rows ) as replay calls a baseline
        - the arm returns None for an ask that is not yes/no, and for an ask with no vector
        - otherwise it returns { "value": stance, "probabilities": { yes, no, neither } } with a "qualifier" key when one was chosen
    """
    def arm( ask, visible_rows ):
        if ask[ "response_type" ] != "yes_no" or ask[ "question_embedding" ] is None: return None
        result   = three_way_forecast( ask, visible_rows, half_life_days )
        forecast = { "value": result[ "value" ], "probabilities": result[ "probabilities" ] }
        if result[ "qualifier" ]: forecast[ "qualifier" ] = result[ "qualifier" ]
        return forecast
    return arm


def _stance_counts( records: List[Dict[str, Any]], actual_stance: Dict[str, str] ) -> Dict[str, int]:
    """
    Count what one arm found and what it falsely raised.

    Requires:
        - records are one arm's replay records; actual_stance maps notification id to the answer's stance

    Ensures:
        - genuine_no is the asks answered no that the arm forecast no, genuine_neither likewise for neither
        - false_alarms is the asks answered yes that the arm forecast no or neither
        - no_forecast is the asks the arm gave no forecast for
        - answered_no and answered_neither are the denominators the genuine counts divide into
    """
    counts = { "genuine_no": 0, "genuine_neither": 0, "false_alarms": 0, "no_forecast": 0,
               "answered_no": 0, "answered_neither": 0 }
    for record in records:
        actual    = actual_stance[ record[ "meta" ][ "notification_id" ] ]
        forecast  = record[ "meta" ][ "forecast" ]
        predicted = None if forecast is None else forecast[ "value" ]
        if predicted is None: counts[ "no_forecast" ] += 1
        if actual == "no":      counts[ "answered_no" ] += 1
        if actual == "neither": counts[ "answered_neither" ] += 1
        if actual == "no" and predicted == "no":           counts[ "genuine_no" ] += 1
        if actual == "neither" and predicted == "neither": counts[ "genuine_neither" ] += 1
        if actual == "yes" and predicted in ( "no", "neither" ): counts[ "false_alarms" ] += 1
    return counts


def probability_scores( records: List[Dict[str, Any]], actual_stance: Dict[str, str], neither_threshold: Optional[float] = None ) -> Dict[str, Any]:
    """
    Score an arm's recorded yes, no and neither probabilities.

    Scores them by multiclass Brier, and by neither recall and precision.

    Requires:
        - records are one arm's replay records; actual_stance maps notification id to the answer's stance
        - neither_threshold is the frozen cut on the neither probability, or None when none was set

    Ensures:
        - a record is scored when its forecast holds probabilities for yes, no and neither and the answer's stance is one of the three
        - returns { scored, without_probabilities } alone when nothing is scored
        - otherwise adds multiclass_brier, and with a threshold adds neither_threshold and neither, calibration_fit's own results
        - no threshold is chosen here
    """
    probabilities, actual = [], []
    for record in records:
        forecast = record[ "meta" ][ "forecast" ]
        stance   = actual_stance[ record[ "meta" ][ "notification_id" ] ]
        given    = None if forecast is None else forecast.get( "probabilities" )
        if given is None or stance not in STANCES or any( word not in given for word in STANCES ): continue
        probabilities.append( given )
        actual.append( stance )
    scores = { "scored": len( actual ), "without_probabilities": len( records ) - len( actual ) }
    if not actual: return scores
    scores[ "multiclass_brier" ] = multiclass_brier( probabilities, actual )
    if neither_threshold is not None:
        scores[ "neither_threshold" ] = neither_threshold
        scores[ "neither" ]           = neither_recall_precision( probabilities, actual, neither_threshold )
    return scores


def build_report( run: Dict[str, Any], asks: List[Dict[str, Any]], operational_floor: int, arm: str = THREE_WAY_ARM, neither_threshold: Optional[float] = None ) -> Dict[str, Any]:
    """
    Report the challenger and the margin rule against always-yes, with a display verdict.

    Requires:
        - run is the dict replay returns, made with target_types ["yes_no"], holding the arms ENGINE_ARM,
          BASELINE_ARM and arm
        - asks are the asks the run replayed, each with id and actual_value
        - operational_floor is the discordant-pair floor stated before the run
        - neither_threshold is the frozen cut for the neither scores, or None to report the Brier alone

    Ensures:
        - returns { arms, verdict_text, display } where arms holds, for the challenger and for the margin
          rule, its stance counts and its summarize result against always-yes
        - each arm also holds probability_scores, the Brier and the neither scores over the probabilities it forecast
        - the challenger is also summarized against the margin rule, as "versus_margin_rule"
        - display is True only when the challenger's verdict against always-yes is "engine better", which
          summarize reaches only at or above the floor with McNemar's p below 0.05
        - in every other case, including "not decisive", "no difference" and "baseline better", display is
          False and verdict_text says the challenger stays in shadow
    """
    actual_stance = {}
    for ask in asks:
        value = ask[ "actual_value" ]
        actual_stance[ ask[ "id" ] ] = extract_qualifier_comment( value[ "value" ] if isinstance( value, dict ) else value )[ 0 ]
    arms = {}
    for name in ( arm, ENGINE_ARM ):
        arms[ name ] = {
            "counts"      : _stance_counts( run[ "records" ][ name ], actual_stance ),
            "versus_always_yes" : summarize( run, BASELINE_ARM, operational_floor, arm=name ),
            "probability_scores" : probability_scores( run[ "records" ][ name ], actual_stance, neither_threshold ),
        }
    arms[ arm ][ "versus_margin_rule" ] = summarize( run, ENGINE_ARM, operational_floor, arm=arm )
    display = arms[ arm ][ "versus_always_yes" ][ "verdict" ] == "engine better"
    return { "arms": arms, "display": display, "verdict_text": DISPLAY_READY if display else STAYS_IN_SHADOW }
