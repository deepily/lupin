#!/usr/bin/env python3
"""
Unit tests for conformal prediction integration in EngineeringStrategy.gate().

Tests that conformal deferral is correctly wired into the gate pipeline:
  - Disabled conformal has no effect
  - Calibrated conformal defers on ambiguous BLR probabilities
  - Confident BLR passes through to Thompson Sampling / fixed gate
"""

import numpy as np
import pytest

from cosa.agents.decision_proxy.trust_tracker import TrustTracker
from cosa.agents.decision_proxy.circuit_breaker import CircuitBreaker
from cosa.agents.decision_proxy.bayesian_trust import BayesianLogisticRegression
from cosa.agents.swe_team.proxy.engineering_strategy import EngineeringStrategy


def _make_strategy( conformal_enabled=False, conformal_alpha=0.10, trust_mode="active", **kwargs ):
    """Create an EngineeringStrategy with conformal configuration."""
    tracker = TrustTracker( trust_model="beta", debug=False )
    cb      = CircuitBreaker(
        trust_tracker        = tracker,
        error_rate_threshold = 1.0,  # Disable CB for these tests
        debug                = False,
    )
    return EngineeringStrategy(
        trust_tracker              = tracker,
        circuit_breaker            = cb,
        trust_mode                 = trust_mode,
        thompson_enabled           = kwargs.get( "thompson_enabled", False ),
        thompson_act_threshold     = kwargs.get( "thompson_act_threshold", 0.90 ),
        thompson_suggest_threshold = kwargs.get( "thompson_suggest_threshold", 0.70 ),
        conformal_enabled          = conformal_enabled,
        conformal_alpha            = conformal_alpha,
        debug                      = False,
    )


def _train_blr_on_category( strategy, category, n_success=30, n_failure=10 ):
    """Train a BLR model on a category with synthetic data."""
    cat = strategy.trust_tracker.categories[ category ]

    # Create BLR model manually
    blr = BayesianLogisticRegression( n_features=4 )

    for _ in range( n_success ):
        x = np.array( [ 0.5, 0.4, 0.5, 0.1 ] )
        blr.update( x, 1 )
        cat.record_decision( True )

    for _ in range( n_failure ):
        x = np.array( [ 0.5, 0.4, 0.5, 0.8 ] )
        blr.update( x, 0 )
        cat.record_decision( False )

    cat._blr_model = blr


class TestConformalGateIntegration:
    """Tests for conformal prediction in gate()."""

    def test_conformal_disabled_no_effect( self ):
        """When conformal_enabled=False, gate() never returns 'defer' from conformal."""
        strategy = _make_strategy( conformal_enabled=False, trust_mode="active" )
        _train_blr_on_category( strategy, "testing", n_success=30, n_failure=10 )

        # Gate should use fixed thresholds, not conformal
        action = strategy.gate( "testing", trust_level=3, confidence=0.9 )
        assert action == "act"

    def test_conformal_uncalibrated_no_defer( self ):
        """Uncalibrated conformal wrapper should NOT cause defer from gate (wrapper check guards)."""
        strategy = _make_strategy( conformal_enabled=True, trust_mode="active" )
        _train_blr_on_category( strategy, "testing", n_success=30, n_failure=10 )

        # Conformal is enabled but not calibrated — is_calibrated is False
        # so the gate should fall through to normal logic
        wrapper = strategy._get_conformal_wrapper()
        assert wrapper.is_calibrated is False

        action = strategy.gate( "testing", trust_level=3, confidence=0.9 )
        assert action == "act"

    def test_conformal_defer_overrides_fixed_gate( self ):
        """Ambiguous conformal probability → 'defer' even when fixed gate would 'act'."""
        strategy = _make_strategy( conformal_enabled=True, conformal_alpha=0.10, trust_mode="active" )

        # Train a weak BLR (ambiguous — BLR produces prob ≈ 0.43 at x_bar)
        _train_blr_on_category( strategy, "testing", n_success=20, n_failure=20 )

        # Calibrate conformal with tight data centered near the BLR output
        # Using well-separated calibration data → small quantile → both classes
        # included for mid-range probabilities like 0.43
        wrapper = strategy._get_conformal_wrapper()
        probs  = [ 0.90 ] * 25 + [ 0.10 ] * 25
        labels = [ 1 ] * 25 + [ 0 ] * 25
        wrapper.calibrate( probs, labels )
        assert wrapper.is_calibrated is True

        # BLR prob ≈ 0.43 is ambiguous under this calibration → conformal defers
        action = strategy.gate( "testing", trust_level=3, confidence=0.9 )
        assert action == "defer"

    def test_conformal_singleton_passes_through( self ):
        """Confident BLR probability → conformal singleton → proceeds to normal gate."""
        strategy = _make_strategy( conformal_enabled=True, conformal_alpha=0.10, trust_mode="active" )

        # Train a strong BLR (BLR produces prob ≈ 0.88 at x_bar)
        _train_blr_on_category( strategy, "testing", n_success=50, n_failure=2 )

        # Calibrate with noisy/wide data → high quantile → singleton for extreme probs
        wrapper = strategy._get_conformal_wrapper()
        probs  = [ 0.6 ] * 25 + [ 0.4 ] * 25
        labels = [ 1 ] * 25 + [ 0 ] * 25
        wrapper.calibrate( probs, labels )
        assert wrapper.is_calibrated is True

        # BLR prob ≈ 0.88 → approve nonconformity = 0.12 which is well below
        # the wide quantile → singleton {approve} → no defer
        action = strategy.gate( "testing", trust_level=3, confidence=0.9 )
        assert action == "act"

    def test_conformal_no_blr_passes_through( self ):
        """Category without BLR model → conformal check skipped."""
        strategy = _make_strategy( conformal_enabled=True, trust_mode="active" )

        # Calibrate the wrapper (it won't matter since no BLR)
        wrapper = strategy._get_conformal_wrapper()
        probs  = [ 0.55 ] * 30 + [ 0.45 ] * 30
        labels = [ 1 ] * 30 + [ 0 ] * 30
        wrapper.calibrate( probs, labels )

        # No BLR on "testing" → should fall through
        action = strategy.gate( "testing", trust_level=3, confidence=0.9 )
        assert action == "act"

    def test_calibrate_conformal_method( self ):
        """calibrate_conformal() collects BLR data and calibrates wrapper."""
        strategy = _make_strategy( conformal_enabled=True, trust_mode="active" )

        # Train BLR on two categories
        _train_blr_on_category( strategy, "testing", n_success=25, n_failure=5 )
        _train_blr_on_category( strategy, "deployment", n_success=20, n_failure=10 )

        status = strategy.calibrate_conformal()

        assert status[ "calibrated" ] is True
        assert status[ "calibration_size" ] == 60  # 30 + 30 decisions total
