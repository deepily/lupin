#!/usr/bin/env python3
"""
Unit tests for the prediction engine's calibration module and its off switch.

Fitting is by scikit-learn's isotonic regression, one cell per response type and strategy.
All synthetic data is deterministic, with no random draws. :7999-eligible.
"""

import re

import pytest

import cosa.agents.prediction_engine.calibration as cal
import cosa.utils.util as cu
from cosa.agents.prediction_engine.config import DEFAULT_CALIBRATION_ENABLED
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine

BINS = [ ( 0.4, 0.50 ), ( 0.5, 0.55 ), ( 0.6, 0.70 ), ( 0.8, 0.80 ), ( 1.0, 0.93 ) ]


def _bin_rows( confidence, rate, n=1000 ):
    """Return n rows at one confidence, exactly rate * n of them correct."""
    right = round( rate * n )
    return [ ( confidence, True ) ] * right + [ ( confidence, False ) ] * ( n - right )


def _split( pairs ):
    """Split ``( confidence, correct )`` pairs into the two sequences fit_cell takes."""
    return [ c for c, _ in pairs ], [ ok for _, ok in pairs ]


def _ini_value( path, key ):
    """Return the value of `key` on its single line in an INI file."""
    with open( path ) as handle:
        hits = re.findall( rf"^{re.escape( key )}\s*=\s*(.*?)\s*$", handle.read(), flags=re.MULTILINE )
    assert len( hits ) == 1, f"{key!r} must appear exactly once in {path}, found {len( hits )}"
    return hits[ 0 ]


class TestFitCell:

    def test_refuses_below_the_minimum_and_fits_nothing( self ):
        xs, ys = _split( _bin_rows( 0.6, 0.5, n=cal.MIN_ROWS_PER_CELL - 1 ) )
        cell   = cal.fit_cell( xs, ys )
        assert cell == { "status": "insufficient data", "n": 49, "needed": 50 }

    def test_fits_at_exactly_the_minimum( self ):
        xs, ys = _split( _bin_rows( 0.6, 0.5, n=cal.MIN_ROWS_PER_CELL ) )
        cell   = cal.fit_cell( xs, ys )
        assert cell[ "status" ] == "fit" and cell[ "n" ] == 50

    def test_minimum_is_fifty( self ):
        assert cal.MIN_ROWS_PER_CELL == 50

    def test_length_mismatch_raises( self ):
        with pytest.raises( ValueError, match="differ in length" ):
            cal.fit_cell( [ 0.5 ] * 60, [ True ] * 59 )

    @pytest.mark.parametrize( "confidence, rate", BINS )
    def test_recovers_each_bins_rate_within_two_points( self, confidence, rate ):
        pairs  = [ pair for c, r in BINS for pair in _bin_rows( c, r ) ]
        cell   = cal.fit_cell( *_split( pairs ) )
        assert abs( cal.calibrate( cell, confidence ) - rate ) <= 0.02

    def test_a_non_monotone_input_is_pooled_into_a_non_decreasing_map( self ):
        pairs = _bin_rows( 0.4, 0.8 ) + _bin_rows( 0.6, 0.6 )
        cell  = cal.fit_cell( *_split( pairs ) )
        assert cell[ "y" ] == sorted( cell[ "y" ] )
        assert cal.calibrate( cell, 0.4 ) == pytest.approx( 0.7 ) == cal.calibrate( cell, 0.6 )


class TestCalibrate:

    def _cell( self ):
        return cal.fit_cell( *_split( [ pair for c, r in BINS for pair in _bin_rows( c, r ) ] ) )

    def test_missing_and_refused_cells_give_none( self ):
        assert cal.calibrate( None, 0.7 ) is None
        assert cal.calibrate( { "status": "insufficient data", "n": 3, "needed": 50 }, 0.7 ) is None

    def test_clips_beyond_the_fitted_range( self ):
        cell = self._cell()
        assert cal.calibrate( cell, 0.0 ) == pytest.approx( 0.50 )
        assert cal.calibrate( cell, 1.5 ) == pytest.approx( 0.93 )

    def test_interpolates_between_fitted_points_and_stays_in_unit_range( self ):
        cell = self._cell()
        mid  = cal.calibrate( cell, 0.7 )
        assert 0.70 < mid < 0.80
        assert all( 0.0 <= cal.calibrate( cell, c / 100 ) <= 1.0 for c in range( 0, 101 ) )


class TestFitCalibration:

    def test_one_cell_per_type_and_strategy_with_a_refusal_for_the_small_one( self ):
        rows  = [ ( "yes_no", "cbr_majority_vote", c, ok ) for c, ok in [ pair for cc, rr in BINS for pair in _bin_rows( cc, rr, n=100 ) ] ]
        rows += [ ( "multiple_choice", "cbr_retrieval", 0.7, True ) ] * 10
        doc   = cal.fit_calibration( rows, cohort_sha="abc123", fit_time="2026-11-18T18:00:00Z" )
        assert list( doc[ "cells" ] ) == [ "multiple_choice|cbr_retrieval", "yes_no|cbr_majority_vote" ]
        assert doc[ "cells" ][ "yes_no|cbr_majority_vote" ][ "status" ] == "fit"
        assert doc[ "cells" ][ "multiple_choice|cbr_retrieval" ] == { "status": "insufficient data", "n": 10, "needed": 50 }
        assert ( doc[ "version" ], doc[ "cohort_sha" ], doc[ "fit_time" ] ) == ( 1, "abc123", "2026-11-18T18:00:00Z" )

    def test_cell_key_format( self ):
        assert cal.cell_key( "yes_no", "cbr_majority_vote" ) == "yes_no|cbr_majority_vote"


class TestReliabilityReport:

    def test_reports_each_nonempty_bin_low_to_high( self ):
        pairs  = _bin_rows( 0.1, 0.2, n=100 ) + _bin_rows( 0.9, 0.9, n=100 )
        report = cal.reliability_report( *_split( pairs ), n_bins=5 )
        assert len( report ) == 2
        assert report[ 0 ] == { "mean_confidence": pytest.approx( 0.1 ), "observed_rate": pytest.approx( 0.2 ) }
        assert report[ 1 ] == { "mean_confidence": pytest.approx( 0.9 ), "observed_rate": pytest.approx( 0.9 ) }


class TestStorage:

    def test_round_trip( self, tmp_path ):
        doc  = cal.fit_calibration( [ ( "yes_no", "s", c, ok ) for cc, rr in BINS for c, ok in _bin_rows( cc, rr, n=100 ) ], "sha", "t" )
        path = cal.write_calibration( doc, str( tmp_path / "c.json" ) )
        assert cal.load_calibration( path ) == doc

    def test_default_path_is_the_committed_file( self, tmp_path, monkeypatch ):
        ( tmp_path / "src" / "conf" ).mkdir( parents=True )
        monkeypatch.setattr( cu, "get_project_root", lambda: str( tmp_path ) )
        written = cal.write_calibration( cal.empty_document() )
        assert written == str( tmp_path ) + "/src/conf/prediction-calibration.json"
        assert cal.load_calibration() == cal.empty_document()

    def test_wrong_version_and_missing_file_fail_loudly( self, tmp_path ):
        path = tmp_path / "old.json"
        path.write_text( '{ "version": 99, "cells": {} }' )
        with pytest.raises( ValueError, match="version 99" ):
            cal.load_calibration( str( path ) )
        with pytest.raises( FileNotFoundError ):
            cal.load_calibration( str( tmp_path / "missing.json" ) )

    def test_committed_file_loads_and_is_a_calibration_document( self ):
        doc = cal.load_calibration()
        assert doc[ "version" ] == cal.FORMAT_VERSION
        assert set( doc ) == { "version", "cohort_sha", "fit_time", "cells" }


class TestOffSwitch:

    def test_committed_ini_value_is_false( self ):
        root = cu.get_project_root()
        assert _ini_value( root + "/src/conf/lupin-app.ini", "prediction engine calibration enabled" ) == "false"

    def test_key_has_an_explainer( self ):
        root = cu.get_project_root()
        assert _ini_value( root + "/src/conf/lupin-app-splainer.ini", "prediction engine calibration enabled" ).endswith( "Default is false." )

    def test_engine_default_is_off_and_the_ini_is_read( self ):
        from unittest.mock import MagicMock
        PredictionEngine._instance = None
        try:
            assert DEFAULT_CALIBRATION_ENABLED is False
            assert PredictionEngine().calibration_enabled is False
            PredictionEngine._instance = None
            config = MagicMock()
            config.get.side_effect = lambda key, default=None, return_type=None: True if key == "prediction engine calibration enabled" else default
            assert PredictionEngine( config_mgr=config ).calibration_enabled is True
        finally:
            PredictionEngine._instance = None
