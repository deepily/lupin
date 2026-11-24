"""
Unit tests for the probability scores in calibration_fit.

They cover binary and multiclass Brier, the fixed confidence bands and neither recall and precision.
Every expected number is a literal.
"""

import pytest

from cosa.research.preference_replay.calibration_fit import (
    band_calibration, binary_brier, multiclass_brier, neither_recall_precision,
)


def _p( yes, no, neither ):
    return { "yes": yes, "no": no, "neither": neither }


def test_binary_brier_is_the_mean_squared_gap():
    assert binary_brier( [ 0.9, 0.2 ], [ True, False ] ) == pytest.approx( 0.025 )
    assert binary_brier( ( c for c in [ 1.0 ] ), ( r for r in [ True ] ) ) == 0.0


def test_bands_are_the_four_fixed_ones_with_edges_in_the_band_that_starts_there():
    report = band_calibration( [ 0.1, 0.3, 0.4, 0.79, 0.8, 1.0, 1.5, float( "nan" ) ], [ True, False, True, True, False, True, True, True ] )
    assert sorted( report ) == [ 0.0, 0.4, 0.6, 0.8 ]
    assert report[ 0.0 ] == { "n": 2, "mean_confidence": pytest.approx( 0.2 ), "accuracy": 0.5 }
    assert report[ 0.4 ] == { "n": 1, "mean_confidence": 0.4, "accuracy": 1.0 }
    assert report[ 0.6 ] == { "n": 1, "mean_confidence": 0.79, "accuracy": 1.0 }
    assert report[ 0.8 ] == { "n": 2, "mean_confidence": pytest.approx( 0.9 ), "accuracy": 0.5 }     # 1.5 and NaN belong to no band


def test_a_band_with_no_rows_is_absent_not_zero():
    assert sorted( band_calibration( [ 0.1, 0.9 ], [ True, True ] ) ) == [ 0.0, 0.8 ]


def test_multiclass_brier_perfect_certain_wrong_and_uniform():
    assert multiclass_brier( [ _p( 1, 0, 0 ) ], [ "yes" ] ) == 0.0
    assert multiclass_brier( [ _p( 1, 0, 0 ) ], [ "neither" ] ) == 2.0
    assert multiclass_brier( [ _p( 0.5, 0.25, 0.25 ), _p( 0.2, 0.2, 0.6 ) ], [ "yes", "neither" ] ) == pytest.approx( ( 0.375 + 0.24 ) / 2 )


def test_neither_recall_and_precision_at_a_frozen_threshold():
    rows    = [ _p( 0.2, 0.2, 0.6 ), _p( 0.2, 0.2, 0.6 ), _p( 0.5, 0.3, 0.2 ), _p( 0.4, 0.3, 0.3 ) ]
    actual  = [ "neither", "yes", "neither", "no" ]
    result  = neither_recall_precision( rows, actual, 0.5 )
    assert result == { "recall": 0.5, "precision": 0.5, "called": 2, "actual": 2 }
    assert neither_recall_precision( rows, actual, 0.3 )[ "called" ] == 3


def test_recall_and_precision_are_none_when_their_denominator_is_empty():
    rows = [ _p( 0.9, 0.05, 0.05 ) ]
    assert neither_recall_precision( rows, [ "yes" ], 0.5 ) == { "recall": None, "precision": None, "called": 0, "actual": 0 }
