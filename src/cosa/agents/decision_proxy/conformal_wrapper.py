#!/usr/bin/env python3
"""
Split Conformal Prediction wrapper for trust-gated decisions.

Provides distribution-free coverage guarantees by wrapping scalar
probabilities from the BLR model with conformal prediction sets.
When the prediction set contains both classes, the decision is ambiguous
and should be deferred.

Algorithm (split conformal inference):
    1. Calibration: compute nonconformity scores on held-out data
    2. Compute quantile at ceil((n+1)(1-alpha)) / n
    3. At prediction time: include class if its nonconformity score <= quantile

Dependency Rule:
    This module NEVER imports from notification_proxy or swe_team.
"""

import math


class ConformalDecisionWrapper:
    """
    Split conformal prediction wrapper for binary decisions.

    Operates on scalar probabilities from BLR.predict(x)[0], not raw
    feature vectors. This keeps it decoupled from the BLR model.

    Requires:
        - alpha is in (0, 1)
        - min_calibration_size is a positive integer

    Ensures:
        - predict_set() returns a set of class labels
        - should_defer() returns True when prediction set is ambiguous
        - Coverage guarantee: P(true class in set) >= 1 - alpha (asymptotically)
    """

    def __init__( self, alpha=0.10, min_calibration_size=30 ):
        """
        Initialize the conformal wrapper.

        Requires:
            - alpha is in (0, 1) — significance level
            - min_calibration_size is a positive integer

        Args:
            alpha: Significance level (1 - coverage). Default 0.10 = 90% coverage.
            min_calibration_size: Minimum calibration points before activating.
        """
        self.alpha                  = alpha
        self.min_calibration_size   = min_calibration_size
        self._scores                = []
        self._quantile              = None
        self._calibrated            = False
        self._calibration_size      = 0

    @property
    def is_calibrated( self ):
        """Whether the wrapper has been calibrated with sufficient data."""
        return self._calibrated

    def calibrate( self, probabilities, labels ):
        """
        Calibrate using held-out (probability, label) pairs.

        Computes nonconformity scores as 1 - p_true_class for each
        calibration point, then sets the quantile threshold.

        Requires:
            - probabilities is a list/array of floats in [0, 1]
            - labels is a list/array of ints (1 = approve/success, 0 = reject/failure)
            - len(probabilities) == len(labels)

        Ensures:
            - is_calibrated is True if len >= min_calibration_size
            - _quantile is set to the conformal threshold

        Args:
            probabilities: List of predicted P(approve) from BLR
            labels: List of true binary labels (1=approve, 0=reject)
        """
        n = len( probabilities )
        if n < self.min_calibration_size:
            self._calibrated = False
            return

        # Compute nonconformity scores: 1 - p(true class)
        scores = []
        for prob, label in zip( probabilities, labels ):
            if label == 1:
                scores.append( 1.0 - prob )
            else:
                scores.append( prob )

        self._scores = sorted( scores )
        self._calibration_size = n

        # Quantile: ceil((n+1)(1-alpha)) / n, clamped to valid index
        q_index = math.ceil( ( n + 1 ) * ( 1.0 - self.alpha ) ) - 1
        q_index = min( q_index, n - 1 )
        q_index = max( q_index, 0 )

        self._quantile  = self._scores[ q_index ]
        self._calibrated = True

    def predict_set( self, probability ):
        """
        Return the conformal prediction set for a given probability.

        Includes a class if its nonconformity score <= quantile threshold.

        Requires:
            - probability is a float in [0, 1]

        Ensures:
            - Returns a set containing "approve", "reject", or both
            - If uncalibrated, returns {"approve", "reject"} (conservative)
            - Empty set defaults to {"approve", "reject"} (safe fallback)

        Args:
            probability: Predicted P(approve) from BLR

        Returns:
            Set of class labels in the prediction set
        """
        if not self._calibrated:
            return { "approve", "reject" }

        prediction_set = set()

        # Include "approve" if its nonconformity score <= quantile
        approve_score = 1.0 - probability
        if approve_score <= self._quantile:
            prediction_set.add( "approve" )

        # Include "reject" if its nonconformity score <= quantile
        reject_score = probability
        if reject_score <= self._quantile:
            prediction_set.add( "reject" )

        # Empty set fallback → ambiguous (safe default)
        if len( prediction_set ) == 0:
            return { "approve", "reject" }

        return prediction_set

    def should_defer( self, probability ):
        """
        Check if the decision should be deferred due to ambiguity.

        Requires:
            - probability is a float in [0, 1]

        Ensures:
            - Returns True if prediction set has both classes (ambiguous)
            - Returns True if uncalibrated (conservative default)
            - Returns False if prediction set is a singleton

        Args:
            probability: Predicted P(approve) from BLR

        Returns:
            True if decision should be deferred
        """
        pred_set = self.predict_set( probability )
        return len( pred_set ) > 1

    def get_status( self ):
        """
        Return diagnostic status dict.

        Ensures:
            - Returns dict with calibrated, alpha, quantile, calibration_size

        Returns:
            Dict with conformal wrapper status
        """
        return {
            "calibrated"       : self._calibrated,
            "alpha"            : self.alpha,
            "quantile"         : self._quantile,
            "calibration_size" : self._calibration_size,
        }
