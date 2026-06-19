#!/usr/bin/env python3
"""
Trust Tracker for the Decision Proxy Agent.

Manages per-category trust scores with:
  - Rolling window for decision history
  - Time-weighted decay (older decisions count less)
  - L1-L5 graduated trust levels (count-based, Beta-Bernoulli, or BLR)
  - Category isolation (bad performance in one category doesn't affect others)
  - Runtime category registration (domain layers add their categories)

Trust Models:
  - "count": Original count-based thresholds (effective decision count)
  - "beta":  Beta-Bernoulli with 95% credible interval lower bound + min samples
  - "blr":   Bayesian Logistic Regression with 4-feature posterior mean rate

Dependency Rule:
    This module NEVER imports from notification_proxy or swe_team.
"""

import math
import time
from typing import Dict, List, Optional, Tuple

from cosa.agents.decision_proxy.config import (
    DEFAULT_BETA_L2_RATE_THRESHOLD,
    DEFAULT_BETA_L3_RATE_THRESHOLD,
    DEFAULT_BETA_L4_RATE_THRESHOLD,
    DEFAULT_BETA_L5_RATE_THRESHOLD,
    DEFAULT_BETA_L2_MIN_SAMPLES,
    DEFAULT_BETA_L3_MIN_SAMPLES,
    DEFAULT_BETA_L4_MIN_SAMPLES,
    DEFAULT_BETA_L5_MIN_SAMPLES,
)


class CategoryTrust:
    """
    Trust state for a single decision category.

    Tracks decision outcomes within a rolling window, applies time-weighted
    decay, and computes a trust score for level graduation. Supports three
    trust models:
      - "count": Original count-based thresholds (effective decision count)
      - "beta":  Beta-Bernoulli with 95% credible interval + min samples
      - "blr":   Bayesian Logistic Regression with 4-feature posterior mean rate

    Requires:
        - category_name is a non-empty string
        - cap_level is 1-5
        - trust_model is "count", "beta", or "blr"

    Ensures:
        - record_decision() adds a decision to the rolling history
        - trust_score is computed from time-weighted success rate
        - level is derived from trust model vs. configurable thresholds
    """

    def __init__(
        self,
        category_name,
        cap_level            = 5,
        rolling_window_days  = 30,
        decay_half_life_days = 14,
        l2_threshold         = 50,
        l3_threshold         = 200,
        l4_threshold         = 500,
        l5_threshold         = 1000,
        trust_model          = "count",
        rate_thresholds      = None,
        min_samples          = None,
    ):
        self.category_name       = category_name
        self.cap_level           = cap_level
        self.rolling_window_days = rolling_window_days
        self.decay_half_life_days = decay_half_life_days
        self.trust_model         = trust_model

        # Count-based thresholds (trust_model="count")
        self.thresholds = {
            2 : l2_threshold,
            3 : l3_threshold,
            4 : l4_threshold,
            5 : l5_threshold,
        }

        # Beta-Bernoulli rate thresholds (trust_model="beta")
        self.rate_thresholds = rate_thresholds or {
            2 : DEFAULT_BETA_L2_RATE_THRESHOLD,
            3 : DEFAULT_BETA_L3_RATE_THRESHOLD,
            4 : DEFAULT_BETA_L4_RATE_THRESHOLD,
            5 : DEFAULT_BETA_L5_RATE_THRESHOLD,
        }

        # Beta-Bernoulli minimum samples per level (trust_model="beta")
        self.min_samples = min_samples or {
            2 : DEFAULT_BETA_L2_MIN_SAMPLES,
            3 : DEFAULT_BETA_L3_MIN_SAMPLES,
            4 : DEFAULT_BETA_L4_MIN_SAMPLES,
            5 : DEFAULT_BETA_L5_MIN_SAMPLES,
        }

        # Decision history: list of ( timestamp, success_bool )
        self.decisions       = []
        self.total_decisions  = 0
        self.total_successes  = 0
        self.total_rejections = 0

        # BLR state (lazy-initialized on first record_decision_with_features call)
        self._blr_model = None

    @property
    def level( self ):
        """
        Current trust level (1-5) for this category.

        Dispatches to the appropriate trust model:
          - "count": Count-based thresholds (original behavior)
          - "beta":  Beta-Bernoulli with 95% credible interval
          - "blr":   Bayesian Logistic Regression posterior mean rate

        Ensures:
            - Returns 1 if below L2 threshold
            - Returns highest level where threshold is met
            - Capped at cap_level
        """
        if self.trust_model == "blr":
            return self._level_blr()
        if self.trust_model == "beta":
            return self._level_beta()
        return self._level_count_based()

    def _level_count_based( self ):
        """
        Original count-based trust level computation.

        Uses time-weighted effective decision count against thresholds.

        Returns:
            int: Trust level 1-5
        """
        effective_count = self._effective_decision_count()
        computed_level  = 1

        for lvl in ( 2, 3, 4, 5 ):
            if effective_count >= self.thresholds[ lvl ]:
                computed_level = lvl
            else:
                break

        return min( computed_level, self.cap_level )

    def _level_beta( self ):
        """
        Beta-Bernoulli trust level computation.

        Uses Beta(alpha, beta) posterior with uniform prior Beta(1,1).
        Computes 95% credible interval lower bound. Level requires BOTH:
          - lower bound >= rate_threshold for that level
          - total observations >= min_samples for that level

        Returns:
            int: Trust level 1-5
        """
        from scipy.stats import beta as beta_dist

        alpha = self.total_successes  + 1  # Beta(1,1) uniform prior
        beta  = self.total_rejections + 1
        n     = alpha + beta - 2  # total observations

        if n == 0:
            return min( 1, self.cap_level )

        # 95% credible interval lower bound
        lower_bound = beta_dist.ppf( 0.05, alpha, beta )

        computed_level = 1
        for lvl in ( 2, 3, 4, 5 ):
            rate_ok    = lower_bound >= self.rate_thresholds[ lvl ]
            samples_ok = n >= self.min_samples[ lvl ]
            if rate_ok and samples_ok:
                computed_level = lvl
            else:
                break

        return min( computed_level, self.cap_level )

    def _level_blr( self ):
        """
        BLR trust level computation.

        Uses BayesianLogisticRegression.posterior_mean_rate() as a
        conservative rate estimate. Falls back to Beta-Bernoulli if
        fewer than 30 observations or BLR model not yet initialized.

        Returns:
            int: Trust level 1-5
        """
        n = self.total_decisions

        # Fall back to Beta if insufficient data or no BLR model
        if n < 30 or self._blr_model is None:
            return self._level_beta()

        rate = self._blr_model.posterior_mean_rate()

        computed_level = 1
        for lvl in ( 2, 3, 4, 5 ):
            rate_ok    = rate >= self.rate_thresholds[ lvl ]
            samples_ok = n >= self.min_samples[ lvl ]
            if rate_ok and samples_ok:
                computed_level = lvl
            else:
                break

        return min( computed_level, self.cap_level )

    @staticmethod
    def build_feature_vector( question, category_index, hour_of_day=None ):
        """
        Build a 4-dimensional feature vector for BLR.

        Features (all normalized to [0, 1]):
            0: category_index   — ordinal / 6.0
            1: question_length  — min( word_count / 50, 1.0 )
            2: hour_of_day      — hour / 24.0
            3: recent_error_rate — placeholder 0.0 (filled by caller)

        Requires:
            - question is a string
            - category_index is 0-5

        Args:
            question: Question text for word count
            category_index: Ordinal category index (0-5)
            hour_of_day: Hour of day (0-23), defaults to current hour

        Returns:
            numpy array of shape (4,)
        """
        import numpy as np
        from datetime import datetime

        if hour_of_day is None:
            hour_of_day = datetime.now().hour

        word_count = len( question.split() ) if question else 0

        return np.array( [
            category_index / 6.0,
            min( word_count / 50.0, 1.0 ),
            hour_of_day / 24.0,
            0.0,  # Placeholder — caller should set error_rate
        ] )

    def record_decision_with_features( self, success, feature_vector, timestamp=None ):
        """
        Record a decision outcome with BLR feature vector update.

        Calls record_decision() for backward compatibility, then updates
        the BLR model with the feature vector.

        Requires:
            - success is a bool
            - feature_vector is a numpy array of shape (4,)

        Ensures:
            - Existing record_decision() behavior preserved
            - BLR model lazy-initialized on first call
            - BLR model updated with (feature_vector, success)

        Args:
            success: True if decision was ratified, False if rejected
            feature_vector: 4-dimensional feature vector
            timestamp: Optional epoch timestamp
        """
        # Standard recording (backward compatible)
        self.record_decision( success, timestamp )

        # Lazy-initialize BLR model
        if self._blr_model is None:
            from cosa.agents.decision_proxy.bayesian_trust import BayesianLogisticRegression
            self._blr_model = BayesianLogisticRegression( n_features=4 )

        # Update BLR with observation
        self._blr_model.update( feature_vector, 1 if success else 0 )

    @property
    def success_rate( self ):
        """
        Overall success rate (0.0-1.0) from decision history.

        Ensures:
            - Returns 0.0 if no decisions recorded
            - Returns ratio of successes to total
        """
        if self.total_decisions == 0:
            return 0.0
        return self.total_successes / self.total_decisions

    @property
    def error_rate( self ):
        """
        Overall error (rejection) rate (0.0-1.0).

        Ensures:
            - Returns 0.0 if no decisions recorded
            - Returns ratio of rejections to total
        """
        if self.total_decisions == 0:
            return 0.0
        return self.total_rejections / self.total_decisions

    def record_decision( self, success, timestamp=None ):
        """
        Record a decision outcome.

        Requires:
            - success is a bool

        Ensures:
            - Adds decision to rolling history
            - Updates counters
            - Prunes old decisions outside rolling window

        Args:
            success: True if decision was ratified/correct, False if rejected
            timestamp: Optional epoch timestamp (defaults to now)
        """
        if timestamp is None:
            timestamp = time.time()

        self.decisions.append( ( timestamp, success ) )
        self.total_decisions += 1

        if success:
            self.total_successes += 1
        else:
            self.total_rejections += 1

        # Prune old decisions
        self._prune_rolling_window()

    def _prune_rolling_window( self ):
        """Remove decisions older than the rolling window."""
        cutoff = time.time() - ( self.rolling_window_days * 86400 )
        self.decisions = [ ( t, s ) for t, s in self.decisions if t >= cutoff ]

    def _effective_decision_count( self ):
        """
        Compute time-weighted effective decision count.

        Applies exponential decay: recent decisions count more.
        Uses the configured decay half-life.

        Returns:
            float: Effective decision count (weighted sum)
        """
        self._prune_rolling_window()
        now = time.time()
        half_life_seconds = self.decay_half_life_days * 86400
        total = 0.0

        for timestamp, success in self.decisions:
            if not success:
                continue  # Only count successes toward graduation
            age_seconds = now - timestamp
            weight = math.exp( -0.693 * age_seconds / half_life_seconds )  # ln(2) = 0.693
            total += weight

        return total

    def demote( self, levels=1 ):
        """
        Demote trust level by removing oldest decisions.

        This effectively drops the effective count below a lower threshold.

        Args:
            levels: Number of levels to demote (default: 1)
        """
        target_level = max( 1, self.level - levels )

        if target_level <= 1:
            # Drop to L1: clear all history
            self.decisions.clear()
            return

        # Keep only enough decisions to stay at target_level
        target_count = self.thresholds.get( target_level, 0 )

        # Sort by timestamp descending (most recent first)
        self.decisions.sort( key=lambda x: x[ 0 ], reverse=True )

        # Keep most recent decisions up to target count
        successes_kept = 0
        pruned = []
        for t, s in self.decisions:
            if s and successes_kept >= target_count:
                continue
            pruned.append( ( t, s ) )
            if s:
                successes_kept += 1

        self.decisions = pruned

    def to_dict( self ):
        """Serialize state for persistence."""
        result = {
            "category_name"    : self.category_name,
            "cap_level"        : self.cap_level,
            "trust_model"      : self.trust_model,
            "level"            : self.level,
            "total_decisions"  : self.total_decisions,
            "total_successes"  : self.total_successes,
            "total_rejections" : self.total_rejections,
            "success_rate"     : round( self.success_rate, 4 ),
            "window_size"      : len( self.decisions ),
        }

        if self.trust_model == "beta":
            result[ "alpha" ] = self.total_successes + 1
            result[ "beta" ]  = self.total_rejections + 1

        if self.trust_model == "blr" and self._blr_model is not None:
            result[ "blr_state" ] = self._blr_model.to_dict()

        return result


class TrustTracker:
    """
    Manages trust state across all decision categories.

    Categories are registered at runtime by domain layers. Each category
    has independent trust scoring — bad performance in one category does
    not affect others.

    Requires:
        - Categories are registered before recording decisions

    Ensures:
        - Per-category trust levels are tracked independently
        - get_level() returns the current trust level for a category
        - record_decision() updates the correct category
    """

    def __init__(
        self,
        rolling_window_days  = 30,
        decay_half_life_days = 14,
        l2_threshold         = 50,
        l3_threshold         = 200,
        l4_threshold         = 500,
        l5_threshold         = 1000,
        trust_model          = "count",
        rate_thresholds      = None,
        min_samples          = None,
        debug                = False
    ):
        self.rolling_window_days  = rolling_window_days
        self.decay_half_life_days = decay_half_life_days
        self.l2_threshold         = l2_threshold
        self.l3_threshold         = l3_threshold
        self.l4_threshold         = l4_threshold
        self.l5_threshold         = l5_threshold
        self.trust_model          = trust_model
        self.rate_thresholds      = rate_thresholds
        self.min_samples          = min_samples
        self.debug                = debug

        self.categories = {}  # category_name → CategoryTrust

    def register_category( self, category_name, cap_level=5 ):
        """
        Register a new decision category.

        Requires:
            - category_name is a non-empty string
            - cap_level is 1-5

        Ensures:
            - Creates a CategoryTrust for the category
            - Does nothing if category already registered

        Args:
            category_name: Name of the category
            cap_level: Maximum trust level for this category
        """
        if category_name in self.categories:
            return

        self.categories[ category_name ] = CategoryTrust(
            category_name        = category_name,
            cap_level            = cap_level,
            rolling_window_days  = self.rolling_window_days,
            decay_half_life_days = self.decay_half_life_days,
            l2_threshold         = self.l2_threshold,
            l3_threshold         = self.l3_threshold,
            l4_threshold         = self.l4_threshold,
            l5_threshold         = self.l5_threshold,
            trust_model          = self.trust_model,
            rate_thresholds      = self.rate_thresholds,
            min_samples          = self.min_samples,
        )

        if self.debug: print( f"[TrustTracker] Registered category: {category_name} (cap L{cap_level}, model={self.trust_model})" )

    def get_level( self, category_name ):
        """
        Get current trust level for a category.

        Requires:
            - category_name is a registered category

        Ensures:
            - Returns trust level (1-5)
            - Returns 1 if category not registered

        Args:
            category_name: Name of the category

        Returns:
            int: Trust level (1-5)
        """
        cat = self.categories.get( category_name )
        if cat is None:
            return 1
        return cat.level

    def record_decision( self, category_name, success, timestamp=None ):
        """
        Record a decision outcome for a category.

        Requires:
            - category_name is a registered category
            - success is a bool

        Ensures:
            - Updates the category's decision history
            - Returns the new trust level for the category

        Args:
            category_name: Category name
            success: True if ratified, False if rejected
            timestamp: Optional epoch timestamp

        Returns:
            int: New trust level after recording
        """
        cat = self.categories.get( category_name )
        if cat is None:
            if self.debug: print( f"[TrustTracker] Unknown category: {category_name}" )
            return 1

        old_level = cat.level
        cat.record_decision( success, timestamp )
        new_level = cat.level

        if new_level != old_level and self.debug:
            direction = "graduated" if new_level > old_level else "demoted"
            print( f"[TrustTracker] {category_name}: {direction} L{old_level} -> L{new_level}" )

        return new_level

    def demote_category( self, category_name, levels=1 ):
        """
        Demote a category's trust level.

        Requires:
            - category_name is a registered category
            - levels is a positive integer

        Ensures:
            - Category trust level decreases by specified levels
            - Level never goes below 1

        Args:
            category_name: Category to demote
            levels: Number of levels to demote
        """
        cat = self.categories.get( category_name )
        if cat is None:
            return

        old_level = cat.level
        cat.demote( levels )
        new_level = cat.level

        if self.debug:
            print( f"[TrustTracker] Demoted {category_name}: L{old_level} -> L{new_level}" )

    def get_all_levels( self ):
        """
        Get trust levels for all registered categories.

        Returns:
            Dict mapping category_name → trust_level
        """
        return { name: cat.level for name, cat in self.categories.items() }

    def get_stats( self ):
        """
        Get detailed stats for all categories.

        Returns:
            Dict mapping category_name → category_stats_dict
        """
        return { name: cat.to_dict() for name, cat in self.categories.items() }
