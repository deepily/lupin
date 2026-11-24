"""
Fit the first confidence calibration on the tune window and score it on the final window.

The fit uses the calibration module's own fitter, one isotonic map per response type and strategy.
The final window never reaches the fit. Each cell is scored there by the Brier score of the raw
confidence and of the calibrated one, from scikit-learn. The reliability bins of both are reported too.
A cell the fit refused for want of rows is reported as not evaluated. So is a cell that exists only
in the final window. Neither is ever scored as if it were calibrated.
"""

from typing import Dict, Iterable, Optional, Tuple

from sklearn.metrics import brier_score_loss

from cosa.agents.prediction_engine.accuracy_comparators import confidence_band
from cosa.agents.prediction_engine.calibration import calibrate, fit_calibration, group_by_cell, reliability_report

Row = Tuple[str, str, float, bool]


def fit_and_evaluate( tune_rows: Iterable[Row], final_rows: Iterable[Row], cohort_sha: str, fit_time: str,
                      n_bins: int = 5 ) -> Tuple[Dict, Dict]:
    """
    Fit on the tune rows and score on the final rows.

    Requires:
        - tune_rows and final_rows yield ( response_type, strategy, confidence, correct ) for scored rows only
        - the two sets come from disjoint windows, the tune window earlier in time
        - cohort_sha names the cohort; fit_time is an ISO-8601 string; n_bins is a positive int

    Ensures:
        - returns ( document, report ); document is what write_calibration stores
        - report carries tune_size, final_size and one entry per cell seen in either window
        - a cell fitted on the tune rows and present in the final rows has status "evaluated", with
          n_tune, n_final, the Brier score of the raw and of the calibrated confidence, and both reliability tables
        - a cell the fit refused has status "not fitted", and one with no tune rows has status "no tune rows"
        - a cell with no final rows has status "no final rows"
        - the final rows are never given to the fit
    """
    tune_rows  = list( tune_rows )
    final_rows = list( final_rows )
    document   = fit_calibration( tune_rows, cohort_sha, fit_time )
    final      = group_by_cell( final_rows )
    cells      = {}
    for key in sorted( set( document[ "cells" ] ) | set( final ) ):
        fitted = document[ "cells" ].get( key )
        if fitted is None:
            cells[ key ] = { "status": "no tune rows", "n_final": len( final[ key ][ 0 ] ) }
        elif key not in final:
            cells[ key ] = { "status": "no final rows", "n_tune": fitted[ "n" ] }
        elif fitted[ "status" ] != "fit":
            cells[ key ] = { "status": "not fitted", "n_tune": fitted[ "n" ], "n_final": len( final[ key ][ 0 ] ) }
        else:
            confidences, correct = final[ key ]
            calibrated           = [ calibrate( fitted, value ) for value in confidences ]
            cells[ key ] = {
                "status"              : "evaluated",
                "n_tune"              : fitted[ "n" ],
                "n_final"             : len( confidences ),
                "brier_raw"           : binary_brier( confidences, correct ),
                "brier_calibrated"    : binary_brier( calibrated, correct ),
                "reliability_raw"     : reliability_report( confidences, correct, n_bins ),
                "reliability_calibrated" : reliability_report( calibrated, correct, n_bins ),
            }
    return document, { "tune_size": len( tune_rows ), "final_size": len( final_rows ), "cells": cells }


STANCE_ORDER = ( "yes", "no", "neither" )


def binary_brier( confidences: Iterable[float], correct: Iterable[bool] ) -> float:
    """
    Score confidences against whether each forecast was right, by binary Brier.

    Requires:
        - confidences and correct are equal-length, non-empty, and confidences lie in [0, 1]

    Ensures:
        - returns the same float fit_and_evaluate stores as brier_raw, from the same scikit-learn call
    """
    return float( brier_score_loss( list( correct ), list( confidences ) ) )


def band_calibration( confidences: Iterable[float], correct: Iterable[bool] ) -> Dict[float, Dict]:
    """
    Report calibration in the four fixed confidence bands, not in equal-width bins.

    Requires:
        - confidences and correct are equal-length

    Ensures:
        - returns { band lower edge: { n, mean_confidence, accuracy } } for every band that holds a row, edges from confidence_band
        - a confidence outside [0, 1] or NaN belongs to no band and is left out
        - a band with no rows is absent, never reported as zero
    """
    grouped: Dict[float, list] = {}
    for confidence, right in zip( confidences, correct ):
        band = confidence_band( confidence )
        if band is not None: grouped.setdefault( band, [] ).append( ( confidence, bool( right ) ) )
    return { band: { "n": len( rows ), "mean_confidence": sum( c for c, _ in rows ) / len( rows ),
                     "accuracy": sum( 1 for _, r in rows if r ) / len( rows ) }
             for band, rows in sorted( grouped.items() ) }


def multiclass_brier( probabilities: Iterable[Dict[str, float]], actual: Iterable[str] ) -> float:
    """
    Score yes, no, neither probabilities against the answers, by multiclass Brier.

    Requires:
        - probabilities are dicts with a probability for each of yes, no and neither
        - actual holds one of those three words per row; both are equal-length and non-empty

    Ensures:
        - returns the mean over rows of the summed squared gaps between each probability and 1 for the answer, 0 for the others
        - a perfect forecast scores 0.0 and a certain wrong one 2.0
    """
    rows = list( zip( probabilities, actual ) )
    return sum( sum( ( row[ stance ] - ( 1.0 if stance == answer else 0.0 ) ) ** 2 for stance in STANCE_ORDER ) for row, answer in rows ) / len( rows )


def neither_recall_precision( probabilities: Iterable[Dict[str, float]], actual: Iterable[str], threshold: float ) -> Dict[str, Optional[float]]:
    """
    Measure how well forecasts find the neither answers, at a frozen threshold.

    Requires:
        - probabilities and actual are as multiclass_brier reads them
        - threshold is the frozen cut on the neither probability

    Ensures:
        - a row is called neither when its neither probability is at least threshold
        - returns { recall, precision, called, actual }; recall is None with no actual neither, precision None with no row called
        - the threshold is never chosen here
    """
    pairs  = list( zip( probabilities, actual ) )
    called = [ row[ "neither" ] >= threshold for row, _ in pairs ]
    truth  = [ answer == "neither" for _, answer in pairs ]
    hits   = sum( 1 for c, t in zip( called, truth ) if c and t )
    return { "recall": hits / sum( truth ) if sum( truth ) else None,
             "precision": hits / sum( called ) if sum( called ) else None,
             "called": sum( called ), "actual": sum( truth ) }
