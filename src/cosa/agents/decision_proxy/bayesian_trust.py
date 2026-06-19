#!/usr/bin/env python3
"""
Bayesian Logistic Regression (BLR) for trust-level estimation.

Online Bayesian logistic regression with Laplace approximation for the
Decision Proxy trust system. Replaces scalar Beta-Bernoulli with a
4-feature regression that captures category context, question complexity,
temporal patterns, and recent error rate.

Features (all normalized to [0, 1]):
    0: category_index   — ordinal encoding / 6.0
    1: question_length  — min( word_count / 50, 1.0 )
    2: hour_of_day      — hour / 24.0
    3: recent_error_rate — category error_rate (already 0-1)

Uses online Laplace approximation with Sherman-Morrison rank-1 updates
to the Hessian inverse, giving O(d^2) per observation.

Dependency Rule:
    This module NEVER imports from notification_proxy or swe_team.
"""

import math
import numpy as np
from typing import Dict, Tuple


def _sigmoid( x ):
    """
    Numerically stable sigmoid function.

    Requires:
        - x is a float or numpy scalar

    Ensures:
        - Returns value in (0, 1)
        - No overflow for large positive or negative inputs
    """
    if x >= 0:
        z = math.exp( -x )
        return 1.0 / ( 1.0 + z )
    else:
        z = math.exp( x )
        return z / ( 1.0 + z )


class BayesianLogisticRegression:
    """
    Online Bayesian Logistic Regression with Laplace approximation.

    Maintains a Gaussian posterior over weight vector w:
        p( w | D ) ≈ N( w_MAP, H^{-1} )

    where H is the Hessian of the negative log-posterior evaluated at w_MAP.

    Uses Sherman-Morrison rank-1 updates for O(d^2) online learning.

    Requires:
        - n_features > 0
        - prior_precision > 0

    Ensures:
        - predict() returns (probability, uncertainty) tuple
        - update() performs online Bayesian update
        - sample_rate() draws from posterior predictive
        - posterior_mean_rate() returns conservative rate estimate
        - to_dict() / from_dict() enable serialization
    """

    def __init__( self, n_features=4, prior_precision=1.0 ):
        """
        Initialize BLR with isotropic Gaussian prior.

        Requires:
            - n_features is a positive integer
            - prior_precision is a positive float

        Args:
            n_features: Dimensionality of feature vector (default 4)
            prior_precision: Precision (inverse variance) of the Gaussian prior
        """
        self.n_features      = n_features
        self.prior_precision = prior_precision

        # Weight vector (MAP estimate) — starts at prior mean (zeros)
        self.w = np.zeros( n_features )

        # Hessian inverse (covariance of the posterior)
        # Starts as prior covariance: (1/prior_precision) * I
        self.H_inv = ( 1.0 / prior_precision ) * np.eye( n_features )

        # Running feature mean for posterior_mean_rate()
        self._feature_sum   = np.zeros( n_features )
        self._feature_count = 0

        # Observation counter
        self.n_observations = 0

    def predict( self, x ):
        """
        Predict success probability with uncertainty for a feature vector.

        Uses probit approximation for the posterior predictive:
            p = sigma( w^T x / sqrt( 1 + pi * s^2 / 8 ) )

        where s^2 = x^T H^{-1} x is the predictive variance.

        Requires:
            - x is a numpy array of shape (n_features,)

        Ensures:
            - Returns (probability, uncertainty) tuple
            - probability is in (0, 1)
            - uncertainty is non-negative

        Args:
            x: Feature vector

        Returns:
            Tuple of (probability, uncertainty)
        """
        x = np.asarray( x, dtype=np.float64 )

        mean    = float( np.dot( self.w, x ) )
        s_sq    = float( np.dot( x, self.H_inv @ x ) )
        uncertainty = math.sqrt( max( s_sq, 0.0 ) )

        # Probit approximation: scale logit by uncertainty
        kappa = 1.0 / math.sqrt( 1.0 + math.pi * s_sq / 8.0 )
        prob  = _sigmoid( kappa * mean )

        return ( prob, uncertainty )

    def update( self, x, y ):
        """
        Online Bayesian update with a single observation.

        Uses Laplace approximation with Sherman-Morrison rank-1 update
        to the Hessian inverse.

        The update formula:
            1. Compute predicted probability: p = sigma( w^T x )
            2. Compute lambda = p * (1 - p)  (Hessian contribution)
            3. Sherman-Morrison update to H_inv
            4. Update w_MAP via Newton step

        Requires:
            - x is a numpy array of shape (n_features,)
            - y is 0 or 1

        Ensures:
            - Posterior is updated with the new observation
            - H_inv remains positive definite
            - Running feature mean is updated

        Args:
            x: Feature vector
            y: Binary outcome (1 = success, 0 = failure)
        """
        x = np.asarray( x, dtype=np.float64 )
        y = float( y )

        # Current prediction
        logit = float( np.dot( self.w, x ) )
        p     = _sigmoid( logit )

        # Hessian contribution: lambda = p * (1 - p)
        lam = p * ( 1.0 - p )
        lam = max( lam, 1e-8 )  # Numerical stability

        # Sherman-Morrison rank-1 update: H_inv -= (H_inv x)(x^T H_inv) * lam / (1 + lam * x^T H_inv x)
        H_inv_x = self.H_inv @ x
        denom   = 1.0 + lam * float( np.dot( x, H_inv_x ) )
        self.H_inv -= lam * np.outer( H_inv_x, H_inv_x ) / denom

        # Gradient of negative log-likelihood at current w
        # (Prior is already captured in the initial H_inv, not re-applied per observation)
        grad = ( p - y ) * x

        # Newton step: w -= H_inv @ grad
        self.w -= self.H_inv @ grad

        # Update running feature mean
        self._feature_sum   += x
        self._feature_count += 1
        self.n_observations += 1

    def sample_rate( self, x ):
        """
        Draw a sample from the posterior predictive for a feature vector.

        Draws w ~ N( w_MAP, H^{-1} ), then returns sigma( w^T x ).

        Requires:
            - x is a numpy array of shape (n_features,)

        Ensures:
            - Returns a float in (0, 1)

        Args:
            x: Feature vector

        Returns:
            Sampled success probability
        """
        x = np.asarray( x, dtype=np.float64 )

        # Draw from posterior
        w_sample = np.random.multivariate_normal( self.w, self.H_inv )

        return _sigmoid( float( np.dot( w_sample, x ) ) )

    def posterior_mean_rate( self ):
        """
        Conservative rate estimate using the posterior mean at the average feature vector.

        Computes sigma( w_MAP^T x_bar ) where x_bar is the running mean of
        all observed feature vectors. Returns 0.5 if no observations yet.

        Ensures:
            - Returns a float in (0, 1)
            - Returns 0.5 if no observations recorded

        Returns:
            Posterior mean success rate
        """
        if self._feature_count == 0:
            return 0.5

        x_bar = self._feature_sum / self._feature_count
        logit = float( np.dot( self.w, x_bar ) )
        return _sigmoid( logit )

    def to_dict( self ):
        """
        Serialize model state for persistence.

        Ensures:
            - Returns dict with all state needed to reconstruct the model
            - Numpy arrays are converted to lists for JSON compatibility
        """
        return {
            "n_features"      : self.n_features,
            "prior_precision" : self.prior_precision,
            "w"               : self.w.tolist(),
            "H_inv"           : self.H_inv.tolist(),
            "feature_sum"     : self._feature_sum.tolist(),
            "feature_count"   : self._feature_count,
            "n_observations"  : self.n_observations,
        }

    @classmethod
    def from_dict( cls, data ):
        """
        Reconstruct model from serialized state.

        Requires:
            - data is a dict from to_dict()

        Ensures:
            - Returns a BayesianLogisticRegression with restored state

        Args:
            data: Serialized model state dict

        Returns:
            BayesianLogisticRegression instance
        """
        model = cls(
            n_features      = data[ "n_features" ],
            prior_precision = data[ "prior_precision" ],
        )
        model.w               = np.array( data[ "w" ] )
        model.H_inv           = np.array( data[ "H_inv" ] )
        model._feature_sum    = np.array( data[ "feature_sum" ] )
        model._feature_count  = data[ "feature_count" ]
        model.n_observations  = data[ "n_observations" ]
        return model
