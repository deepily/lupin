#!/usr/bin/env python3
"""
Trust Tracker for the Decision Proxy Agent.

Manages per-category trust scores with:
  - Rolling window for decision history
  - Time-weighted decay (older decisions count less)
  - Graduated trust levels 1 to 5 (count-based, Beta-Bernoulli, or BLR)
  - Category isolation (bad performance in one category doesn't affect others)
  - Runtime category registration (domain layers add their categories)

Trust Models:
  - "count": Original count-based thresholds (effective decision count)
  - "beta":  Beta-Bernoulli with 95% credible interval lower bound + min samples
  - "blr":   Bayesian Logistic Regression with 4-feature posterior mean rate

Dependency Rule:
    This module never imports from notification_proxy or swe_team.
"""

import math
from datetime import datetime, timezone
import time
from typing import Dict, List, Optional, Tuple

from cosa.agents.heartbeat_arbiter.ping_throttle import prune_window
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


BLR_MIN_OBSERVATIONS = 30   # decisions, and observations of the BLR model itself, before its posterior sets the level


class CategoryTrust:
    """
    Trust state for a single decision category.

    Tracks outcomes in a rolling window with time-weighted decay and computes a trust score.
    Trust models: "count" (effective decision count), "beta" (95% credible
    interval plus min samples), "blr" (4-feature posterior mean rate).

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

        # A recorded circuit-breaker trip: the demoted level and the success total when it happened.
        # None means no trip; while one is active the level cannot exceed trip_level (see trip_active).
        self.trip_level     = None
        self.trip_successes = None

    @property
    def level( self ):
        """
        Current trust level (1-5) for this category.

        Dispatches by trust model: "count" (count-based thresholds), "beta"
        (Beta-Bernoulli 95% credible interval), "blr" (posterior mean rate).

        Ensures:
            - Returns 1 if below level 2 threshold
            - Returns highest level where threshold is met
            - Capped at cap_level, and at trip_level while a recorded trip is active
        """
        if self.trust_model == "blr":
            computed = self._level_blr()
        elif self.trust_model == "beta":
            computed = self._level_beta()
        else:
            computed = self._level_count_based()
        return min( computed, self.trip_level ) if self.trip_active() else computed

    def trip_active( self ):
        """
        Say whether a recorded circuit-breaker trip still caps the level.

        Ensures:
            - returns False when no trip is recorded or the demoted level is already the top level
            - returns True until total_successes has grown past the trip total by the gap
            - the gap is the next level's threshold minus the demoted level's own
            - successes before the trip do not count

        Notes:
            The demotion pruned the history down to the demoted level's threshold,
            so the category earns the cap back with new successes.
        """
        if self.trip_level is None or self.trip_level >= 5: return False

        gap = self.thresholds[ self.trip_level + 1 ] - self.thresholds.get( self.trip_level, 0 )
        return ( self.total_successes - self.trip_successes ) < gap

    def trip_state( self ):
        """
        Return the trip as a plain dict for storage, or None when none is active.

        Ensures:
            - returns {"status": "tripped", "tripped_level", "successes_at_trip"} while the trip is active
            - the status key is what the admin dashboard reads; without it a stored trip shows as closed
            - returns None otherwise, which clears a stored trip
        """
        if not self.trip_active(): return None
        return { "status": "tripped", "tripped_level": self.trip_level, "successes_at_trip": self.trip_successes }

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

        Uses Beta(alpha, beta) posterior with uniform prior Beta(1,1) and its 95% lower bound.
        A level needs both: lower bound >= rate_threshold and observations >= min_samples.

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
        BLR trust level from the posterior mean rate.

        Falls back to Beta-Bernoulli when there are fewer than BLR_MIN_OBSERVATIONS decisions or no model.
        It also falls back when the model has fewer observations of its own, as after a demotion.

        Returns:
            int: Trust level 1-5
        """
        n = self.total_decisions

        # Fall back to Beta if insufficient data or no BLR model
        if n < BLR_MIN_OBSERVATIONS or self._blr_model is None or self._blr_model.n_observations < BLR_MIN_OBSERVATIONS:
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
    def build_feature_vector( question, category_index, hour_of_day=None, recent_error_rate=0.0 ):
        """
        Build a 4-dimensional feature vector for BLR.

        Features, all in [0, 1]: 0 category_index / 6.0, 1 min( word_count / 50, 1.0 ),
        2 hour_of_day / 24.0, 3 recent_error_rate from CategoryTrust.recent_error_rate().
        Feature 0 is constant inside one CategoryTrust and acts as a second bias term.

        Requires:
            - question is a string
            - category_index is 0-5

        Args:
            question: Question text for word count
            category_index: Ordinal category index (0-5)
            hour_of_day: Hour of day (0-23), defaults to current hour
            recent_error_rate: Share of recent decisions rejected, in [0, 1] (default 0.0)

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
            recent_error_rate,
        ] )

    def recent_error_rate( self, window=20 ):
        """
        Share of the most recent decisions that were rejected.

        Requires:
            - window is a positive integer

        Ensures:
            - returns a float in [0, 1]
            - looks at the latest window entries of the rolling history, by timestamp
            - returns 0.0 when the history is empty
        """
        recent = sorted( self.decisions, key=lambda d: d[ 0 ] )[ -window: ]
        if not recent: return 0.0
        return sum( 1 for _, ok in recent if not ok ) / len( recent )

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
        self.decisions = prune_window( self.decisions, time.time(), self.rolling_window_days * 86400, stamp=lambda decision: decision[ 0 ] )

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

        The "beta" and "blr" models read counters, so those are lowered too (_shed_totals_to).

        Args:
            levels: Number of levels to demote (default: 1)
        """
        target_level = max( 1, self.level - levels )

        if self.trust_model != "count": self._shed_totals_to( target_level )

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

    def _shed_totals_to( self, target_level ):
        """
        Lower the success counter until the Beta level is no higher than target_level.

        Requires:
            - trust_model is "beta" or "blr"
            - target_level is 1-5

        Ensures:
            - total_successes becomes the largest value whose Beta level is at most target_level
            - total_rejections is unchanged, and total_decisions is kept equal to the two counters' sum
            - the BLR model is dropped, because its posterior cannot be un-updated; the level then
              falls back to the Beta level until the BLR model is rebuilt by new decisions
            - the level is computed without the trip cap, which the caller applies
        """
        self._blr_model = None

        low, high = 0, self.total_successes
        while low < high:
            mid = ( low + high + 1 ) // 2
            self.total_successes = mid
            if self._level_beta() <= target_level: low = mid
            else: high = mid - 1

        self.total_successes = low
        self.total_decisions = low + self.total_rejections

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

    def restore_category( self, category_name, successes, rejections, as_of, trip=None, history=None, blr_state=None ):
        """
        Restore a category's counters and rolling history from stored totals.

        A row written before the history column existed has no per-day history. Every restored
        decision is then stamped with the row's last-update time and decays from there. With
        history, each day's decisions are stamped with that day, so old ones decay and age out.

        Requires:
            - successes and rejections are non-negative ints
            - as_of is an epoch timestamp in seconds
            - trip is the stored trip dict ("tripped_level", "successes_at_trip"), or None for no trip
            - history is the stored {"YYYY-MM-DD": [approved, rejected]} dict (UTC days), or None
            - blr_state is a stored BayesianLogisticRegression.to_dict() dict, or None

        Ensures:
            - returns True and sets the totals when the category is registered and empty
            - a stored trip caps the restored level until it is earned back (see trip_active), so a
              demotion, which changes the stored level but not the counters, survives the reload
            - with no stored trip the level is whatever the counters earn, so a category can climb
            - the rolling history gains one entry per restored decision, stamped as_of, or, when
              history is given, one entry per decision in it, stamped with its UTC day; totals older
              than the history are counted but not in the rolling history
            - the BLR model is rebuilt from blr_state only when the tracker's trust model is "blr";
              the "count" and "beta" models ignore it
            - returns False and changes nothing when the category is unknown or already has decisions
        """
        cat = self.categories.get( category_name )
        if cat is None or cat.total_decisions: return False

        cat.total_successes  = successes
        cat.total_rejections = rejections
        cat.total_decisions  = successes + rejections
        if history is None:
            cat.decisions = [ ( as_of, True ) ] * successes + [ ( as_of, False ) ] * rejections
        else:
            cat.decisions = []
            for day, ( approved, rejected ) in sorted( history.items() ):
                stamp = datetime.strptime( day, "%Y-%m-%d" ).replace( tzinfo=timezone.utc ).timestamp()
                cat.decisions += [ ( stamp, True ) ] * approved + [ ( stamp, False ) ] * rejected
        if trip is not None:
            cat.trip_level     = trip[ "tripped_level" ]
            cat.trip_successes = trip[ "successes_at_trip" ]
        if blr_state is not None and self.trust_model == "blr":
            from cosa.agents.decision_proxy.bayesian_trust import BayesianLogisticRegression
            cat._blr_model = BayesianLogisticRegression.from_dict( blr_state )
        cat._prune_rolling_window()
        return True

    def blr_state_for( self, category_name ):
        """
        Serialize a category's BLR model for storage.

        Requires:
            - category_name is a string

        Ensures:
            - returns the model's to_dict() when the trust model is "blr" and the category has a model
            - returns None for the "count" and "beta" models, an unknown category, or a category with no model yet
        """
        cat = self.categories.get( category_name )
        if self.trust_model != "blr" or cat is None or cat._blr_model is None: return None
        return cat._blr_model.to_dict()

    def record_trip( self, category_name ):
        """
        Record that a circuit-breaker trip just demoted a category.

        Requires:
            - the demotion has already been applied

        Ensures:
            - the category remembers its demoted level and success total, so the cap can outlive this tracker
            - an unknown category changes nothing
        """
        cat = self.categories.get( category_name )
        if cat is None: return

        cat.trip_level     = cat.level
        cat.trip_successes = cat.total_successes

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

    def record_decision_with_features( self, category_name, success, question, timestamp=None ):
        """
        Record a decision outcome and feed the category's BLR model.

        Requires:
            - category_name is a registered category
            - success is a bool
            - question is a string

        Ensures:
            - Builds the 4-feature vector from the question, the category's registration
              position, and the category's recent error rate before this decision
            - Updates the category's history and its BLR model
            - Returns 1 for an unknown category, and records nothing

        Args:
            category_name: Category name
            success: True if ratified, False if rejected
            question: Question text the feature vector is built from
            timestamp: Optional epoch timestamp

        Returns:
            int: New trust level after recording
        """
        cat = self.categories.get( category_name )
        if cat is None:
            if self.debug: print( f"[TrustTracker] Unknown category: {category_name}" )
            return 1

        features = CategoryTrust.build_feature_vector(
            question, list( self.categories ).index( category_name ), recent_error_rate=cat.recent_error_rate()
        )
        cat.record_decision_with_features( success, features, timestamp )
        return cat.level

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
