#!/usr/bin/env python3
"""
Unit tests for ConformalDecisionWrapper.

Tests split conformal prediction logic: calibration, prediction sets,
deferral, coverage guarantee, edge cases, and recalibration.
"""

import random
import pytest

from cosa.agents.decision_proxy.conformal_wrapper import ConformalDecisionWrapper


class TestConformalWrapper:
    """Tests for ConformalDecisionWrapper."""

    def test_uncalibrated_always_defers( self ):
        """Before calibrate(), should_defer() always returns True."""
        wrapper = ConformalDecisionWrapper( alpha=0.10 )

        assert wrapper.should_defer( 0.95 ) is True
        assert wrapper.should_defer( 0.50 ) is True
        assert wrapper.should_defer( 0.05 ) is True

    def test_calibration_sets_quantile( self ):
        """calibrate() populates the quantile threshold."""
        wrapper = ConformalDecisionWrapper( alpha=0.10, min_calibration_size=10 )

        probs  = [ 0.9 ] * 15 + [ 0.1 ] * 15
        labels = [ 1 ] * 15 + [ 0 ] * 15

        wrapper.calibrate( probs, labels )

        assert wrapper.is_calibrated is True
        assert wrapper._quantile is not None
        assert wrapper._calibration_size == 30

    def test_singleton_approve( self ):
        """High probability with well-calibrated model gives singleton {approve}."""
        wrapper = ConformalDecisionWrapper( alpha=0.10, min_calibration_size=10 )

        # Calibrate with well-separated data
        probs  = [ 0.95 ] * 20 + [ 0.05 ] * 20
        labels = [ 1 ] * 20 + [ 0 ] * 20

        wrapper.calibrate( probs, labels )

        pred_set = wrapper.predict_set( 0.95 )
        assert "approve" in pred_set
        assert wrapper.should_defer( 0.95 ) is False

    def test_singleton_reject( self ):
        """Low probability gives singleton {reject}."""
        wrapper = ConformalDecisionWrapper( alpha=0.10, min_calibration_size=10 )

        probs  = [ 0.95 ] * 20 + [ 0.05 ] * 20
        labels = [ 1 ] * 20 + [ 0 ] * 20

        wrapper.calibrate( probs, labels )

        pred_set = wrapper.predict_set( 0.05 )
        assert "reject" in pred_set
        assert wrapper.should_defer( 0.05 ) is False

    def test_ambiguous_defers( self ):
        """Borderline probability produces ambiguous set and defers."""
        wrapper = ConformalDecisionWrapper( alpha=0.10, min_calibration_size=10 )

        # Calibrate with noisy data (high nonconformity scores)
        probs  = [ 0.6 ] * 15 + [ 0.4 ] * 15
        labels = [ 1 ] * 15 + [ 0 ] * 15

        wrapper.calibrate( probs, labels )

        # Borderline probability should be ambiguous
        pred_set = wrapper.predict_set( 0.50 )
        assert pred_set == { "approve", "reject" }
        assert wrapper.should_defer( 0.50 ) is True

    def test_coverage_guarantee( self ):
        """Simulate 200 calibration points, verify empirical coverage >= 1 - alpha - 0.05."""
        random.seed( 42 )
        alpha = 0.10
        wrapper = ConformalDecisionWrapper( alpha=alpha, min_calibration_size=30 )

        n_cal  = 150
        n_test = 200

        # Generate well-calibrated synthetic data
        cal_probs  = [ random.betavariate( 5, 2 ) for _ in range( n_cal ) ]
        cal_labels = [ 1 if p > 0.5 else 0 for p in cal_probs ]

        wrapper.calibrate( cal_probs, cal_labels )
        assert wrapper.is_calibrated is True

        # Test coverage: true class should be in prediction set
        covered = 0
        for _ in range( n_test ):
            prob  = random.betavariate( 5, 2 )
            label = 1 if prob > 0.5 else 0

            pred_set = wrapper.predict_set( prob )
            true_class = "approve" if label == 1 else "reject"
            if true_class in pred_set:
                covered += 1

        coverage = covered / n_test
        # Allow 5% tolerance below nominal coverage
        assert coverage >= ( 1.0 - alpha - 0.05 ), (
            f"Coverage {coverage:.3f} below threshold {1.0 - alpha - 0.05:.3f}"
        )

    def test_predict_set_empty_fallback( self ):
        """Edge case: empty set defaults to ambiguous (both classes)."""
        wrapper = ConformalDecisionWrapper( alpha=0.01, min_calibration_size=10 )

        # Very tight alpha with extreme calibration data
        # Use perfectly separated data with very low quantile
        probs  = [ 0.99 ] * 20 + [ 0.01 ] * 20
        labels = [ 1 ] * 20 + [ 0 ] * 20

        wrapper.calibrate( probs, labels )

        # With alpha=0.01, quantile is very low — mid-range probability
        # should have high nonconformity for both classes → empty → fallback
        pred_set = wrapper.predict_set( 0.50 )
        # Should have at least something (fallback guarantees non-empty)
        assert len( pred_set ) > 0

    def test_get_status_structure( self ):
        """get_status() returns valid dict with expected keys."""
        wrapper = ConformalDecisionWrapper( alpha=0.10 )

        status = wrapper.get_status()

        assert "calibrated" in status
        assert "alpha" in status
        assert "quantile" in status
        assert "calibration_size" in status
        assert status[ "calibrated" ] is False
        assert status[ "alpha" ] == 0.10

    def test_recalibration( self ):
        """Calling calibrate() again updates quantile."""
        wrapper = ConformalDecisionWrapper( alpha=0.10, min_calibration_size=10 )

        # First calibration
        probs1  = [ 0.8 ] * 20 + [ 0.2 ] * 20
        labels1 = [ 1 ] * 20 + [ 0 ] * 20
        wrapper.calibrate( probs1, labels1 )
        q1 = wrapper._quantile

        # Second calibration with different data
        probs2  = [ 0.6 ] * 20 + [ 0.4 ] * 20
        labels2 = [ 1 ] * 20 + [ 0 ] * 20
        wrapper.calibrate( probs2, labels2 )
        q2 = wrapper._quantile

        assert q1 != q2, "Quantile should change after recalibration"

    def test_min_calibration_size( self ):
        """Fewer than min_calibration_size points → stays uncalibrated."""
        wrapper = ConformalDecisionWrapper( alpha=0.10, min_calibration_size=30 )

        probs  = [ 0.8 ] * 10
        labels = [ 1 ] * 10

        wrapper.calibrate( probs, labels )

        assert wrapper.is_calibrated is False
        assert wrapper._quantile is None
        assert wrapper.should_defer( 0.95 ) is True
