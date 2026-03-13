#!/usr/bin/env python3
"""
Unit tests for BayesianLogisticRegression.

Tests the online Bayesian logistic regression model used for trust-level
estimation in the decision proxy:
  - Prior prediction (no data → p ≈ 0.5)
  - Positive / negative / mixed convergence
  - Uncertainty decrease with more data
  - Serialization roundtrip
  - Posterior mean rate behavior
"""

import numpy as np
import pytest

from cosa.agents.decision_proxy.bayesian_trust import BayesianLogisticRegression


def _positive_feature():
    """Feature vector associated with positive outcomes."""
    return np.array( [ 0.5, 0.3, 0.5, 0.1 ] )


def _negative_feature():
    """Feature vector associated with negative outcomes."""
    return np.array( [ 0.5, 0.3, 0.5, 0.9 ] )


class TestBayesianLogisticRegression:
    """Tests for BayesianLogisticRegression model."""

    def test_blr_prior_prediction( self ):
        """With no data, prediction should be approximately 0.5."""
        model = BayesianLogisticRegression( n_features=4 )
        x     = np.array( [ 0.5, 0.5, 0.5, 0.5 ] )
        prob, uncertainty = model.predict( x )

        assert abs( prob - 0.5 ) < 0.05, f"Expected ~0.5, got {prob}"
        assert uncertainty > 0, "Uncertainty should be positive"

    def test_blr_positive_convergence( self ):
        """After 50 positive observations, probability should be > 0.80."""
        model = BayesianLogisticRegression( n_features=4 )
        x     = _positive_feature()

        for _ in range( 50 ):
            model.update( x, 1 )

        prob, _ = model.predict( x )
        assert prob > 0.80, f"Expected prob > 0.80 after 50 positives, got {prob:.4f}"

    def test_blr_negative_convergence( self ):
        """After 50 negative observations, probability should be < 0.20."""
        model = BayesianLogisticRegression( n_features=4 )
        x     = _negative_feature()

        for _ in range( 50 ):
            model.update( x, 0 )

        prob, _ = model.predict( x )
        assert prob < 0.20, f"Expected prob < 0.20 after 50 negatives, got {prob:.4f}"

    def test_blr_mixed_observations( self ):
        """With 25 positive + 25 negative, probability should be near 0.5."""
        model = BayesianLogisticRegression( n_features=4 )
        x     = np.array( [ 0.5, 0.5, 0.5, 0.5 ] )

        for _ in range( 25 ):
            model.update( x, 1 )
        for _ in range( 25 ):
            model.update( x, 0 )

        prob, _ = model.predict( x )
        assert 0.30 < prob < 0.70, f"Expected prob ≈ 0.5, got {prob:.4f}"

    def test_blr_uncertainty_decreases( self ):
        """Uncertainty at n=50 should be less than at n=10."""
        model = BayesianLogisticRegression( n_features=4 )
        x     = _positive_feature()

        for _ in range( 10 ):
            model.update( x, 1 )
        _, uncertainty_10 = model.predict( x )

        for _ in range( 40 ):
            model.update( x, 1 )
        _, uncertainty_50 = model.predict( x )

        assert uncertainty_50 < uncertainty_10, (
            f"Uncertainty should decrease: n=10 ({uncertainty_10:.4f}) vs n=50 ({uncertainty_50:.4f})"
        )

    def test_blr_serialization_roundtrip( self ):
        """to_dict → from_dict should preserve model state."""
        model = BayesianLogisticRegression( n_features=4 )
        x     = _positive_feature()

        for _ in range( 30 ):
            model.update( x, 1 )
        for _ in range( 5 ):
            model.update( x, 0 )

        prob_before, unc_before = model.predict( x )

        # Serialize and restore
        state    = model.to_dict()
        restored = BayesianLogisticRegression.from_dict( state )

        prob_after, unc_after = restored.predict( x )

        assert abs( prob_before - prob_after ) < 1e-10, "Probability should survive roundtrip"
        assert abs( unc_before - unc_after ) < 1e-10, "Uncertainty should survive roundtrip"
        assert restored.n_observations == model.n_observations
        assert restored._feature_count == model._feature_count

    def test_blr_posterior_mean_rate_no_data( self ):
        """With no data, posterior mean rate should be approximately 0.5."""
        model = BayesianLogisticRegression( n_features=4 )
        rate  = model.posterior_mean_rate()

        assert abs( rate - 0.5 ) < 0.01, f"Expected ~0.5, got {rate}"

    def test_blr_posterior_mean_rate_with_data( self ):
        """After 50 positive observations, posterior mean rate should be > 0.7."""
        model = BayesianLogisticRegression( n_features=4 )
        x     = _positive_feature()

        for _ in range( 50 ):
            model.update( x, 1 )

        rate = model.posterior_mean_rate()
        assert rate > 0.70, f"Expected rate > 0.70, got {rate:.4f}"
