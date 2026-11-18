"""
Fit the first confidence calibration on the tune window and score it on the final window.

The fit uses the calibration module's own fitter, one isotonic map per response type and strategy.
The final window never reaches the fit. Each cell is scored there by the Brier score of the raw
confidence and of the calibrated one, from scikit-learn. The reliability bins of both are reported too.
A cell the fit refused for want of rows is reported as not evaluated. So is a cell that exists only
in the final window. Neither is ever scored as if it were calibrated.
"""

from typing import Dict, Iterable, List, Tuple

from sklearn.metrics import brier_score_loss

from cosa.agents.prediction_engine.calibration import calibrate, cell_key, fit_calibration, reliability_report

Row = Tuple[str, str, float, bool]


def _by_cell( rows: Iterable[Row] ) -> Dict[str, Tuple[List[float], List[bool]]]:
    """
    Group scored rows by calibration cell.

    Requires:
        - rows yields ( response_type, strategy, confidence, correct )

    Ensures:
        - returns cell key to ( confidences, correct ), each list in row order
    """
    grouped: Dict[str, Tuple[List[float], List[bool]]] = {}
    for response_type, strategy, confidence, was_correct in rows:
        confidences, correct = grouped.setdefault( cell_key( response_type, strategy ), ( [], [] ) )
        confidences.append( confidence )
        correct.append( was_correct )
    return grouped


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
    final      = _by_cell( final_rows )
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
                "brier_raw"           : float( brier_score_loss( correct, confidences ) ),
                "brier_calibrated"    : float( brier_score_loss( correct, calibrated ) ),
                "reliability_raw"     : reliability_report( confidences, correct, n_bins ),
                "reliability_calibrated" : reliability_report( calibrated, correct, n_bins ),
            }
    return document, { "tune_size": len( tune_rows ), "final_size": len( final_rows ), "cells": cells }
