"""
The first calibration fit learns from the tune window and is judged on the final window.

The data is deterministic, with no random draws. Each confidence has a stated number of rows,
and the stated number of them are right. So the Brier scores below are known by arithmetic.
A fit that peeked at the final window, or skipped a refused cell, would change them.
"""

import pytest

from cosa.agents.prediction_engine.calibration import MIN_ROWS_PER_CELL, fit_cell
from cosa.research.preference_replay.calibration_fit import fit_and_evaluate

SHA  = "ab" * 32
TIME = "2026-11-18T00:00:00+00:00"


def _rows( response_type, strategy, spec ):
    """Rows for ( confidence, how many, how many of them right ) triples, in a fixed order."""
    out = []
    for confidence, count, right in spec:
        out += [ ( response_type, strategy, confidence, index < right ) for index in range( count ) ]
    return out


# Overconfident: 0.9 is right 70 percent of the time and 0.5 right 50 percent.
TUNE  = _rows( "yes_no", "cbr_majority_vote", [ ( 0.9, 100, 70 ), ( 0.5, 100, 50 ) ] )
FINAL = _rows( "yes_no", "cbr_majority_vote", [ ( 0.9, 50, 35 ), ( 0.5, 50, 25 ) ] )


def test_a_fit_on_the_tune_window_beats_raw_confidence_on_the_final_window():
    """Raw 0.9 is wrong by 0.2 where calibrated 0.7 is exact, so the calibrated Brier is lower."""
    document, report = fit_and_evaluate( TUNE, FINAL, SHA, TIME )
    cell = report[ "cells" ][ "yes_no|cbr_majority_vote" ]
    assert cell[ "status" ] == "evaluated" and ( cell[ "n_tune" ], cell[ "n_final" ] ) == ( 200, 100 )
    assert cell[ "brier_raw" ] == pytest.approx( 0.5 * ( 0.7 * 0.01 + 0.3 * 0.81 ) + 0.5 * 0.25 )
    assert cell[ "brier_calibrated" ] == pytest.approx( 0.5 * 0.21 + 0.5 * 0.25 )
    assert cell[ "brier_calibrated" ] < cell[ "brier_raw" ]
    assert ( report[ "tune_size" ], report[ "final_size" ] ) == ( 200, 100 )
    assert ( document[ "cohort_sha" ], document[ "fit_time" ] ) == ( SHA, TIME )


def test_the_final_window_never_reaches_the_fit():
    """The stored map equals a fit on the tune rows alone, whatever the final rows say."""
    document, _ = fit_and_evaluate( TUNE, FINAL, SHA, TIME )
    opposite    = [ ( t, s, c, not ok ) for t, s, c, ok in FINAL ]
    other, _    = fit_and_evaluate( TUNE, opposite, SHA, TIME )
    alone       = fit_cell( [ c for _, _, c, _ in TUNE ], [ ok for _, _, _, ok in TUNE ] )
    assert document[ "cells" ] == other[ "cells" ] == { "yes_no|cbr_majority_vote": alone }


def test_the_reliability_tables_show_the_raw_and_the_calibrated_bins():
    """Raw confidence reads 0.9 over a 0.7 observed rate; the calibrated bin reads 0.7."""
    _, report = fit_and_evaluate( TUNE, FINAL, SHA, TIME )
    cell      = report[ "cells" ][ "yes_no|cbr_majority_vote" ]
    top_raw   = max( cell[ "reliability_raw" ], key=lambda b: b[ "mean_confidence" ] )
    top_cal   = max( cell[ "reliability_calibrated" ], key=lambda b: b[ "mean_confidence" ] )
    assert ( top_raw[ "mean_confidence" ], top_raw[ "observed_rate" ] ) == pytest.approx( ( 0.9, 0.7 ) )
    assert ( top_cal[ "mean_confidence" ], top_cal[ "observed_rate" ] ) == pytest.approx( ( 0.7, 0.7 ) )


def test_a_cell_the_fit_refused_is_reported_and_not_scored():
    """A cell with too few tune rows is not fitted, so no calibrated score is invented."""
    few   = _rows( "multiple_choice", "cbr_majority_vote", [ ( 0.8, MIN_ROWS_PER_CELL - 1, 10 ) ] )
    final = _rows( "multiple_choice", "cbr_majority_vote", [ ( 0.8, 20, 10 ) ] )
    document, report = fit_and_evaluate( few, final, SHA, TIME )
    assert document[ "cells" ][ "multiple_choice|cbr_majority_vote" ][ "status" ] == "insufficient data"
    assert report[ "cells" ][ "multiple_choice|cbr_majority_vote" ] == { "status": "not fitted", "n_tune": MIN_ROWS_PER_CELL - 1, "n_final": 20 }


def test_cells_present_in_only_one_window_are_named_not_dropped():
    """A final-only cell has no tune rows; a tune-only cell has no final rows."""
    tune_only  = _rows( "yes_no", "cold_start", [ ( 0.0, 60, 30 ) ] )
    final_only = _rows( "open_ended", "cbr_majority_vote", [ ( 0.7, 10, 5 ) ] )
    _, report  = fit_and_evaluate( TUNE + tune_only, FINAL + final_only, SHA, TIME )
    assert report[ "cells" ][ "yes_no|cold_start" ] == { "status": "no final rows", "n_tune": 60 }
    assert report[ "cells" ][ "open_ended|cbr_majority_vote" ] == { "status": "no tune rows", "n_final": 10 }


def test_a_generator_input_is_read_once_and_counted():
    """The sizes come from the rows given, even when they arrive as a one-shot iterator."""
    _, report = fit_and_evaluate( iter( TUNE ), iter( FINAL ), SHA, TIME )
    assert ( report[ "tune_size" ], report[ "final_size" ] ) == ( 200, 100 )


def test_the_reliability_tables_use_the_bin_count_asked_for():
    """Nine spread confidences fill five bins by default and three when asked.

    Both reliability tables follow the count.
    """
    levels = [ 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9 ]
    spread = _rows( "yes_no", "cbr_majority_vote", [ ( level, 20, int( round( 20 * level ) ) ) for level in levels ] )
    _, default = fit_and_evaluate( spread, spread, SHA, TIME )
    _, three   = fit_and_evaluate( spread, spread, SHA, TIME, n_bins=3 )
    cell_5     = default[ "cells" ][ "yes_no|cbr_majority_vote" ]
    cell_3     = three[ "cells" ][ "yes_no|cbr_majority_vote" ]
    assert ( len( cell_5[ "reliability_raw" ] ), len( cell_5[ "reliability_calibrated" ] ) ) == ( 5, 5 )
    assert ( len( cell_3[ "reliability_raw" ] ), len( cell_3[ "reliability_calibrated" ] ) ) == ( 3, 3 )
