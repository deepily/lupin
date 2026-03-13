#!/usr/bin/env python3
"""
Unit tests for BLR integration in TrustTracker.

Tests the Bayesian Logistic Regression trust model dispatch in
CategoryTrust and TrustTracker:
  - BLR model dispatch returns valid level
  - Fallback to Beta-Bernoulli under 30 observations
  - TrustTracker propagates model to registered categories
  - Serialization includes BLR state
  - record_decision_with_features updates BLR model
"""

import numpy as np
import pytest

from cosa.agents.decision_proxy.trust_tracker import CategoryTrust, TrustTracker


def _make_feature( error_rate=0.1 ):
    """Build a feature vector for testing."""
    return np.array( [ 0.5, 0.3, 0.5, error_rate ] )


class TestTrustTrackerBLR:
    """Tests for BLR integration in CategoryTrust and TrustTracker."""

    def test_blr_dispatch( self ):
        """trust_model='blr' returns valid level (1-5)."""
        cat = CategoryTrust(
            category_name = "testing",
            trust_model   = "blr",
            cap_level     = 5,
        )

        # With no data, falls back to Beta → L1
        assert cat.level == 1

        # Add 50 successful decisions with features (exceeds 30 threshold)
        feature = _make_feature( error_rate=0.05 )
        for _ in range( 50 ):
            cat.record_decision_with_features( True, feature )

        level = cat.level
        assert 1 <= level <= 5, f"Level should be 1-5, got {level}"
        # With 50 successes, BLR should produce level > 1
        assert level >= 2, f"Expected L2+ with 50 successes, got L{level}"

    def test_blr_fallback_under_30( self ):
        """BLR falls back to Beta-Bernoulli when n < 30."""
        cat = CategoryTrust(
            category_name = "testing",
            trust_model   = "blr",
            cap_level     = 5,
        )

        # Add 20 successes (under 30 threshold)
        feature = _make_feature()
        for _ in range( 20 ):
            cat.record_decision_with_features( True, feature )

        # Should use Beta path, which requires min_samples[2]=20
        # With 20 successes, Beta should give at least L2
        level_blr = cat.level

        # Compare with explicit Beta calculation
        cat_beta = CategoryTrust(
            category_name = "testing_beta",
            trust_model   = "beta",
            cap_level     = 5,
        )
        for _ in range( 20 ):
            cat_beta.record_decision( True )

        level_beta = cat_beta.level

        assert level_blr == level_beta, (
            f"BLR fallback should match Beta: blr={level_blr}, beta={level_beta}"
        )

    def test_blr_passes_through_tracker( self ):
        """TrustTracker propagates trust_model='blr' to registered categories."""
        tracker = TrustTracker( trust_model="blr", debug=False )
        tracker.register_category( "testing", cap_level=5 )

        cat = tracker.categories[ "testing" ]
        assert cat.trust_model == "blr"

        # Verify level works through tracker
        assert tracker.get_level( "testing" ) == 1  # No data → L1

    def test_to_dict_includes_blr_state( self ):
        """Serialization includes blr_state when model='blr' and BLR initialized."""
        cat = CategoryTrust(
            category_name = "testing",
            trust_model   = "blr",
            cap_level     = 5,
        )

        # Before any features, no BLR state
        d = cat.to_dict()
        assert "blr_state" not in d

        # Add feature-based observations
        feature = _make_feature()
        for _ in range( 10 ):
            cat.record_decision_with_features( True, feature )

        d = cat.to_dict()
        assert "blr_state" in d
        assert d[ "blr_state" ][ "n_observations" ] == 10
        assert d[ "blr_state" ][ "n_features" ] == 4

    def test_record_with_features_updates_blr( self ):
        """record_decision_with_features initializes and updates BLR model."""
        cat = CategoryTrust(
            category_name = "testing",
            trust_model   = "blr",
            cap_level     = 5,
        )

        assert cat._blr_model is None

        feature = _make_feature()
        cat.record_decision_with_features( True, feature )

        # BLR model should be lazy-initialized
        assert cat._blr_model is not None
        assert cat._blr_model.n_observations == 1

        # Add more and verify count
        for _ in range( 9 ):
            cat.record_decision_with_features( True, feature )

        assert cat._blr_model.n_observations == 10
        assert cat.total_decisions == 10
        assert cat.total_successes == 10
