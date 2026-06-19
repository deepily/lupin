#!/usr/bin/env python3
"""
Unit tests for cosa.agents.decision_proxy.bayesian_trust.

Covers the numerically-stable _sigmoid (both x>=0 and x<0 arms) and the
online BayesianLogisticRegression (Laplace approximation + Sherman-Morrison
update): init priors, predict's probit approximation, the online update's
counter/feature-mean bookkeeping + directionality, the conservative
posterior_mean_rate (no-data + with-data arms), and to_dict/from_dict
round-trip. The only stochastic boundary — np.random.multivariate_normal in
sample_rate — is mocked, so every assertion is deterministic.
"""

import numpy as np
import pytest
from unittest.mock import patch

from cosa.agents.decision_proxy import bayesian_trust as bt
from cosa.agents.decision_proxy.bayesian_trust import BayesianLogisticRegression, _sigmoid


# ----------------------------------------------------------------------------
# _sigmoid
# ----------------------------------------------------------------------------
def test_sigmoid_zero_is_half():
    assert _sigmoid( 0.0 ) == 0.5


def test_sigmoid_positive_branch():
    assert _sigmoid( 100.0 ) == pytest.approx( 1.0, abs=1e-6 )
    assert 0.5 < _sigmoid( 2.0 ) < 1.0


def test_sigmoid_negative_branch():
    assert _sigmoid( -100.0 ) == pytest.approx( 0.0, abs=1e-6 )
    assert 0.0 < _sigmoid( -2.0 ) < 0.5


def test_sigmoid_symmetry():
    assert _sigmoid( 1.5 ) + _sigmoid( -1.5 ) == pytest.approx( 1.0 )


# ----------------------------------------------------------------------------
# __init__
# ----------------------------------------------------------------------------
def test_init_defaults():
    m = BayesianLogisticRegression()
    assert m.n_features == 4
    assert m.prior_precision == 1.0
    assert np.array_equal( m.w, np.zeros( 4 ) )
    assert np.array_equal( m.H_inv, np.eye( 4 ) )
    assert np.array_equal( m._feature_sum, np.zeros( 4 ) )
    assert m._feature_count == 0
    assert m.n_observations == 0


def test_init_custom_prior_precision_scales_covariance():
    m = BayesianLogisticRegression( n_features=2, prior_precision=2.0 )
    assert m.n_features == 2
    assert np.allclose( m.H_inv, 0.5 * np.eye( 2 ) )


# ----------------------------------------------------------------------------
# predict
# ----------------------------------------------------------------------------
def test_predict_fresh_model_is_uninformative():
    m = BayesianLogisticRegression( n_features=4, prior_precision=1.0 )
    prob, uncertainty = m.predict( [ 1.0, 0.0, 0.0, 0.0 ] )
    assert prob == pytest.approx( 0.5 )          # mean 0 → sigmoid(0)
    assert uncertainty == pytest.approx( 1.0 )   # s^2 = ||x||^2 / prior_precision = 1


def test_predict_positive_weights_raise_probability():
    m = BayesianLogisticRegression( n_features=2, prior_precision=1.0 )
    m.w = np.array( [ 5.0, 0.0 ] )
    prob, uncertainty = m.predict( [ 1.0, 0.0 ] )
    assert prob > 0.5
    assert uncertainty >= 0.0


# ----------------------------------------------------------------------------
# update
# ----------------------------------------------------------------------------
def test_update_increments_counters_and_feature_sum():
    m = BayesianLogisticRegression( n_features=2 )
    m.update( [ 1.0, 2.0 ], 1 )
    assert m.n_observations == 1
    assert m._feature_count == 1
    assert np.array_equal( m._feature_sum, np.array( [ 1.0, 2.0 ] ) )


def test_update_with_success_moves_prediction_up():
    m = BayesianLogisticRegression( n_features=2, prior_precision=1.0 )
    x = [ 1.0, 0.0 ]
    before, _ = m.predict( x )
    for _ in range( 5 ):
        m.update( x, 1 )
    after, _ = m.predict( x )
    assert after > before


def test_update_with_failure_moves_prediction_down():
    m = BayesianLogisticRegression( n_features=2, prior_precision=1.0 )
    x = [ 1.0, 0.0 ]
    before, _ = m.predict( x )
    for _ in range( 5 ):
        m.update( x, 0 )
    after, _ = m.predict( x )
    assert after < before


def test_update_reduces_uncertainty_in_observed_direction():
    m = BayesianLogisticRegression( n_features=2, prior_precision=1.0 )
    x = [ 1.0, 0.0 ]
    _, unc_before = m.predict( x )
    m.update( x, 1 )
    _, unc_after = m.predict( x )
    assert unc_after < unc_before


# ----------------------------------------------------------------------------
# sample_rate (RNG boundary mocked)
# ----------------------------------------------------------------------------
def test_sample_rate_draws_from_posterior_and_sigmoids():
    m = BayesianLogisticRegression( n_features=2 )
    with patch.object( bt.np.random, "multivariate_normal",
                       return_value=np.array( [ 10.0, 0.0 ] ) ) as mock_draw:
        rate = m.sample_rate( [ 1.0, 0.0 ] )
    mock_draw.assert_called_once()
    assert rate == pytest.approx( _sigmoid( 10.0 ) )


def test_sample_rate_returns_unit_interval():
    m = BayesianLogisticRegression( n_features=2 )
    with patch.object( bt.np.random, "multivariate_normal",
                       return_value=np.array( [ -3.0, 1.0 ] ) ):
        rate = m.sample_rate( [ 1.0, 1.0 ] )
    assert 0.0 < rate < 1.0


# ----------------------------------------------------------------------------
# posterior_mean_rate
# ----------------------------------------------------------------------------
def test_posterior_mean_rate_no_data_returns_half():
    m = BayesianLogisticRegression()
    assert m.posterior_mean_rate() == 0.5


def test_posterior_mean_rate_after_observations():
    m = BayesianLogisticRegression( n_features=2, prior_precision=1.0 )
    m.update( [ 1.0, 0.0 ], 1 )
    rate = m.posterior_mean_rate()
    x_bar = m._feature_sum / m._feature_count
    assert rate == pytest.approx( _sigmoid( float( np.dot( m.w, x_bar ) ) ) )


# ----------------------------------------------------------------------------
# to_dict / from_dict
# ----------------------------------------------------------------------------
def test_to_dict_serializes_full_state():
    m = BayesianLogisticRegression( n_features=2, prior_precision=2.0 )
    m.update( [ 1.0, 1.0 ], 1 )
    d = m.to_dict()
    assert d[ "n_features" ] == 2
    assert d[ "prior_precision" ] == 2.0
    assert isinstance( d[ "w" ], list )
    assert isinstance( d[ "H_inv" ], list )
    assert isinstance( d[ "feature_sum" ], list )
    assert d[ "feature_count" ] == 1
    assert d[ "n_observations" ] == 1


def test_from_dict_round_trip_restores_state():
    m = BayesianLogisticRegression( n_features=2, prior_precision=2.0 )
    m.update( [ 1.0, 2.0 ], 1 )
    restored = BayesianLogisticRegression.from_dict( m.to_dict() )
    assert restored.n_features == m.n_features
    assert restored.prior_precision == m.prior_precision
    assert np.allclose( restored.w, m.w )
    assert np.allclose( restored.H_inv, m.H_inv )
    assert np.allclose( restored._feature_sum, m._feature_sum )
    assert restored._feature_count == m._feature_count
    assert restored.n_observations == m.n_observations
