#!/usr/bin/env python3
"""
Unit tests for Beta-Bernoulli trust model in CategoryTrust and TrustTracker.

Pure math tests — no mocks needed since Beta-Bernoulli uses only
internal counters and scipy.stats.beta.ppf().
"""

import time
import pytest

from cosa.agents.decision_proxy.trust_tracker import CategoryTrust, TrustTracker


class TestBetaBernoulliLevel:
    """Tests for _level_beta() computation in CategoryTrust."""

    def test_no_data_returns_l1( self ):
        """Beta(1,1) with no observations → L1."""
        cat = CategoryTrust( "testing", trust_model="beta" )
        assert cat.level == 1

    def test_high_success_sufficient_samples_reaches_l2( self ):
        """20+ successes with high rate → L2."""
        cat = CategoryTrust( "testing", trust_model="beta" )
        now = time.time()

        # 20 successes, 2 rejections (90.9% rate, 20+ samples)
        for i in range( 20 ):
            cat.record_decision( success=True, timestamp=now - i )
        for i in range( 2 ):
            cat.record_decision( success=False, timestamp=now - 20 - i )

        assert cat.level >= 2

    def test_many_successes_reaches_l3( self ):
        """50+ observations with ~96% success → L3."""
        cat = CategoryTrust( "testing", trust_model="beta" )
        now = time.time()

        # 51 successes, 1 rejection (98% rate, 52 total samples)
        for i in range( 51 ):
            cat.record_decision( success=True, timestamp=now - i )
        cat.record_decision( success=False, timestamp=now - 51 )

        assert cat.level >= 3

    def test_fifty_percent_rate_stays_l1( self ):
        """Beta(10,10) → 50% rate, well below all thresholds → L1."""
        cat = CategoryTrust( "testing", trust_model="beta" )
        now = time.time()

        for i in range( 10 ):
            cat.record_decision( success=True, timestamp=now - i )
            cat.record_decision( success=False, timestamp=now - 10 - i )

        assert cat.level == 1

    def test_too_few_samples_stays_l1_despite_high_rate( self ):
        """5 successes, 1 rejection (83% rate) — too few samples for L2 (min 20)."""
        cat = CategoryTrust( "testing", trust_model="beta" )
        now = time.time()

        for i in range( 5 ):
            cat.record_decision( success=True, timestamp=now - i )
        cat.record_decision( success=False, timestamp=now - 5 )

        # High rate but only 6 samples, min for L2 is 20
        assert cat.level == 1

    def test_count_model_unchanged( self ):
        """trust_model='count' gives identical behavior to original."""
        cat = CategoryTrust(
            "testing",
            trust_model  = "count",
            l2_threshold = 5,
            l3_threshold = 10,
        )
        now = time.time()

        # Record 6 successes at current time to exceed threshold of 5
        # (effective count uses time-weighted decay, so need slight margin)
        for i in range( 6 ):
            cat.record_decision( success=True, timestamp=now )

        assert cat.level == 2

    def test_cap_level_respected_in_beta( self ):
        """Beta model respects cap_level even with overwhelming evidence."""
        cat = CategoryTrust(
            "testing",
            trust_model = "beta",
            cap_level   = 2,
        )
        now = time.time()

        # 200 successes, 0 rejections — would be L5 without cap
        for i in range( 200 ):
            cat.record_decision( success=True, timestamp=now - i )

        assert cat.level <= 2

    def test_to_dict_includes_alpha_beta_for_beta_model( self ):
        """to_dict includes alpha and beta when trust_model='beta'."""
        cat = CategoryTrust( "testing", trust_model="beta" )
        cat.record_decision( success=True )
        cat.record_decision( success=True )
        cat.record_decision( success=False )

        d = cat.to_dict()

        assert d[ "trust_model" ] == "beta"
        assert d[ "alpha" ] == 3  # 2 successes + 1 prior
        assert d[ "beta" ] == 2   # 1 rejection + 1 prior

    def test_to_dict_no_alpha_beta_for_count_model( self ):
        """to_dict does NOT include alpha/beta when trust_model='count'."""
        cat = CategoryTrust( "testing", trust_model="count" )
        cat.record_decision( success=True )

        d = cat.to_dict()

        assert d[ "trust_model" ] == "count"
        assert "alpha" not in d
        assert "beta" not in d

    def test_custom_rate_thresholds( self ):
        """Custom rate thresholds are respected."""
        cat = CategoryTrust(
            "testing",
            trust_model     = "beta",
            rate_thresholds = { 2: 0.50, 3: 0.60, 4: 0.70, 5: 0.80 },
            min_samples     = { 2: 5,    3: 10,   4: 20,   5: 40 },
        )
        now = time.time()

        # 8 successes, 2 rejections (80% rate, 10 samples)
        for i in range( 8 ):
            cat.record_decision( success=True, timestamp=now - i )
        for i in range( 2 ):
            cat.record_decision( success=False, timestamp=now - 8 - i )

        # With custom thresholds: rate ≈ 80%, 10 samples
        # L2 needs 50% rate + 5 samples → pass
        # L3 needs 60% rate + 10 samples → may pass
        assert cat.level >= 2


class TestTrustTrackerBetaIntegration:
    """Tests for TrustTracker with beta model propagation."""

    def test_tracker_passes_beta_model_to_categories( self ):
        """TrustTracker propagates trust_model='beta' to registered categories."""
        tracker = TrustTracker( trust_model="beta", debug=True )
        tracker.register_category( "testing", cap_level=5 )

        cat = tracker.categories[ "testing" ]
        assert cat.trust_model == "beta"

    def test_tracker_passes_rate_thresholds( self ):
        """TrustTracker propagates custom rate_thresholds to categories."""
        custom_rates = { 2: 0.50, 3: 0.60, 4: 0.70, 5: 0.80 }
        tracker = TrustTracker( trust_model="beta", rate_thresholds=custom_rates )
        tracker.register_category( "testing" )

        cat = tracker.categories[ "testing" ]
        assert cat.rate_thresholds == custom_rates

    def test_tracker_passes_min_samples( self ):
        """TrustTracker propagates custom min_samples to categories."""
        custom_samples = { 2: 5, 3: 10, 4: 20, 5: 40 }
        tracker = TrustTracker( trust_model="beta", min_samples=custom_samples )
        tracker.register_category( "testing" )

        cat = tracker.categories[ "testing" ]
        assert cat.min_samples == custom_samples

    def test_tracker_default_count_model( self ):
        """Default TrustTracker uses count model (backward compatible)."""
        tracker = TrustTracker()
        tracker.register_category( "testing" )

        cat = tracker.categories[ "testing" ]
        assert cat.trust_model == "count"
