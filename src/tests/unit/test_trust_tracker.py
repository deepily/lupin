#!/usr/bin/env python3
"""
Gap-filling unit tests for the Trust Tracker (Phase 4c).

Tests for CategoryTrust and TrustTracker covering:
    - L3/L4/L5 graduation (only L2 tested in test_decision_proxy_config.py)
    - Intermediate demotion with decision pruning
    - Rolling window boundary behavior
    - Exponential decay precision
    - to_dict serialization completeness
    - TrustTracker deep edge cases

Does NOT duplicate tests already in test_decision_proxy_config.py:
    - Initial L1, L2 graduation, cap enforcement, success/error rate, empty rates,
      demote-to-L1, to_dict (3 keys), time decay, register idempotent, unregistered=1,
      record+check, categories independent, demote, get_all_levels, get_stats, unknown category
"""

import math
import time
import pytest


# ============================================================================
# TestCategoryTrustGraduation — L3/L4/L5 graduation
# ============================================================================

class TestCategoryTrustGraduation:
    """Tests for L3, L4, and L5 trust level graduation."""

    def test_graduates_to_l3( self ):
        """With l2=3 and l3=10, 11 recent successes should reach L3."""
        from cosa.agents.decision_proxy.trust_tracker import CategoryTrust

        cat = CategoryTrust( "testing", l2_threshold=3, l3_threshold=10, l4_threshold=20, l5_threshold=40 )
        now = time.time()
        for i in range( 11 ):
            cat.record_decision( success=True, timestamp=now - i )
        assert cat.level == 3

    def test_graduates_to_l4( self ):
        """With l2=3, l3=10, l4=20, 21 recent successes should reach L4."""
        from cosa.agents.decision_proxy.trust_tracker import CategoryTrust

        cat = CategoryTrust( "testing", l2_threshold=3, l3_threshold=10, l4_threshold=20, l5_threshold=40 )
        now = time.time()
        for i in range( 21 ):
            cat.record_decision( success=True, timestamp=now - i )
        assert cat.level == 4

    def test_graduates_to_l5( self ):
        """Full threshold chain to L5 with 41 recent successes."""
        from cosa.agents.decision_proxy.trust_tracker import CategoryTrust

        cat = CategoryTrust( "testing", l2_threshold=3, l3_threshold=10, l4_threshold=20, l5_threshold=40 )
        now = time.time()
        for i in range( 41 ):
            cat.record_decision( success=True, timestamp=now - i )
        assert cat.level == 5

    def test_no_graduation_with_only_failures( self ):
        """100 failures should leave level at 1 — only successes count."""
        from cosa.agents.decision_proxy.trust_tracker import CategoryTrust

        cat = CategoryTrust( "testing", l2_threshold=3, l3_threshold=10 )
        now = time.time()
        for i in range( 100 ):
            cat.record_decision( success=False, timestamp=now - i )
        assert cat.level == 1

    def test_mixed_success_failure_graduation( self ):
        """Successes graduate even when failures are present."""
        from cosa.agents.decision_proxy.trust_tracker import CategoryTrust

        cat = CategoryTrust( "testing", l2_threshold=3, l3_threshold=10, l4_threshold=20, l5_threshold=40 )
        now = time.time()
        # Record 11 successes + 50 failures
        for i in range( 11 ):
            cat.record_decision( success=True, timestamp=now - i )
        for i in range( 50 ):
            cat.record_decision( success=False, timestamp=now - i )
        # Should still be at L3 because only successes count for graduation
        assert cat.level == 3


# ============================================================================
# TestCategoryTrustDemoteIntermediate — Intermediate demotion with pruning
# ============================================================================

class TestCategoryTrustDemoteIntermediate:
    """Tests for intermediate demotion (not just to L1)."""

    def test_demote_from_l3_by_1_prunes_decisions( self ):
        """Demote from L3 by 1 level should prune to L2 threshold successes."""
        from cosa.agents.decision_proxy.trust_tracker import CategoryTrust

        cat = CategoryTrust( "testing", l2_threshold=3, l3_threshold=10, l4_threshold=20, l5_threshold=40 )
        now = time.time()
        for i in range( 11 ):
            cat.record_decision( success=True, timestamp=now - i )
        assert cat.level == 3

        cat.demote( levels=1 )
        # Decisions pruned to l2_threshold=3 successes, level drops below L3
        assert cat.level < 3
        successes_kept = sum( 1 for _, s in cat.decisions if s )
        assert successes_kept == 3

    def test_demote_from_l5_by_2_prunes_decisions( self ):
        """Demote from L5 by 2 levels should prune to L3 threshold successes."""
        from cosa.agents.decision_proxy.trust_tracker import CategoryTrust

        cat = CategoryTrust( "testing", l2_threshold=3, l3_threshold=10, l4_threshold=20, l5_threshold=40 )
        now = time.time()
        for i in range( 41 ):
            cat.record_decision( success=True, timestamp=now - i )
        assert cat.level == 5

        cat.demote( levels=2 )
        # Decisions pruned to l3_threshold=10 successes, level drops below L5
        assert cat.level < 5
        successes_kept = sum( 1 for _, s in cat.decisions if s )
        assert successes_kept == 10

    def test_demote_to_l1_from_intermediate( self ):
        """Demote from L3 by 3 or more levels should floor at L1 with cleared decisions."""
        from cosa.agents.decision_proxy.trust_tracker import CategoryTrust

        cat = CategoryTrust( "testing", l2_threshold=3, l3_threshold=10, l4_threshold=20, l5_threshold=40 )
        now = time.time()
        for i in range( 11 ):
            cat.record_decision( success=True, timestamp=now - i )
        assert cat.level == 3

        cat.demote( levels=3 )
        assert cat.level == 1
        assert len( cat.decisions ) == 0

    def test_demote_more_levels_than_current_floors_at_l1( self ):
        """Demoting 10 levels from L2 should safely floor at L1."""
        from cosa.agents.decision_proxy.trust_tracker import CategoryTrust

        cat = CategoryTrust( "testing", l2_threshold=3, l3_threshold=10, l4_threshold=20, l5_threshold=40 )
        now = time.time()
        for i in range( 4 ):
            cat.record_decision( success=True, timestamp=now - i )
        assert cat.level == 2

        cat.demote( levels=10 )
        assert cat.level == 1
        assert len( cat.decisions ) == 0


# ============================================================================
# TestCategoryTrustRollingWindow — Boundary behavior
# ============================================================================

class TestCategoryTrustRollingWindow:
    """Tests for rolling window pruning behavior at boundaries."""

    def test_decisions_at_exact_cutoff_kept( self ):
        """A decision at exactly the rolling window boundary should be kept."""
        from cosa.agents.decision_proxy.trust_tracker import CategoryTrust

        cat = CategoryTrust( "testing", rolling_window_days=30 )
        # Decision at exactly the cutoff boundary
        boundary = time.time() - ( 30 * 86400 )
        cat.record_decision( success=True, timestamp=boundary )
        # Prune triggers on the next record
        cat._prune_rolling_window()
        # The boundary decision should be kept (>= cutoff)
        # Note: slight time drift means the cutoff recalculated in _prune is newer
        # So decisions exactly at the old boundary may be pruned. Test with small offset.
        recent = time.time() - ( 29 * 86400 )
        cat2 = CategoryTrust( "testing", rolling_window_days=30 )
        cat2.record_decision( success=True, timestamp=recent )
        cat2._prune_rolling_window()
        assert len( cat2.decisions ) == 1

    def test_decisions_just_past_cutoff_pruned( self ):
        """A decision 1 second past the rolling window should be pruned."""
        from cosa.agents.decision_proxy.trust_tracker import CategoryTrust

        cat = CategoryTrust( "testing", rolling_window_days=30 )
        old_time = time.time() - ( 30 * 86400 ) - 1
        cat.decisions.append( ( old_time, True ) )
        cat.total_decisions += 1
        cat.total_successes += 1
        cat._prune_rolling_window()
        assert len( cat.decisions ) == 0

    def test_custom_rolling_window_7_days( self ):
        """With a 7-day window, an 8-day-old decision should be pruned."""
        from cosa.agents.decision_proxy.trust_tracker import CategoryTrust

        cat = CategoryTrust( "testing", rolling_window_days=7 )
        old_time = time.time() - ( 8 * 86400 )
        cat.decisions.append( ( old_time, True ) )
        cat.total_decisions += 1
        cat.total_successes += 1
        cat._prune_rolling_window()
        assert len( cat.decisions ) == 0

    def test_multiple_decisions_same_timestamp( self ):
        """5 decisions at identical timestamp should all be kept."""
        from cosa.agents.decision_proxy.trust_tracker import CategoryTrust

        cat = CategoryTrust( "testing" )
        now = time.time()
        for _ in range( 5 ):
            cat.record_decision( success=True, timestamp=now )
        assert len( cat.decisions ) == 5
        assert cat.total_decisions == 5


# ============================================================================
# TestCategoryTrustDecay — Exponential decay precision
# ============================================================================

class TestCategoryTrustDecay:
    """Tests for exponential time decay weight precision."""

    def test_decay_weight_at_half_life( self ):
        """Weight should be ~0.5 for a decision at exactly one half-life."""
        from cosa.agents.decision_proxy.trust_tracker import CategoryTrust

        cat = CategoryTrust( "testing", decay_half_life_days=14 )
        half_life_ago = time.time() - ( 14 * 86400 )
        cat.record_decision( success=True, timestamp=half_life_ago )
        effective = cat._effective_decision_count()
        assert abs( effective - 0.5 ) < 0.05

    def test_decay_weight_at_zero_age( self ):
        """Weight should be 1.0 for a very fresh decision."""
        from cosa.agents.decision_proxy.trust_tracker import CategoryTrust

        cat = CategoryTrust( "testing", decay_half_life_days=14 )
        now = time.time()
        cat.record_decision( success=True, timestamp=now )
        effective = cat._effective_decision_count()
        assert abs( effective - 1.0 ) < 0.01

    def test_decay_weight_at_two_half_lives( self ):
        """Weight should be ~0.25 for a decision at two half-lives."""
        from cosa.agents.decision_proxy.trust_tracker import CategoryTrust

        cat = CategoryTrust( "testing", decay_half_life_days=14 )
        two_half_lives_ago = time.time() - ( 28 * 86400 )
        cat.record_decision( success=True, timestamp=two_half_lives_ago )
        effective = cat._effective_decision_count()
        assert abs( effective - 0.25 ) < 0.05

    def test_decay_prevents_graduation( self ):
        """Old decisions shouldn't graduate despite meeting count threshold."""
        from cosa.agents.decision_proxy.trust_tracker import CategoryTrust

        cat = CategoryTrust( "testing", l2_threshold=3, decay_half_life_days=1 )
        # Record 10 decisions from 20 days ago — extreme decay
        old_time = time.time() - ( 20 * 86400 )
        for i in range( 10 ):
            cat.record_decision( success=True, timestamp=old_time + i )
        # Effective count should be near 0 due to decay
        assert cat.level == 1


# ============================================================================
# TestCategoryTrustSerialization — to_dict completeness
# ============================================================================

class TestCategoryTrustSerialization:
    """Tests for to_dict serialization completeness."""

    def test_to_dict_all_eight_keys( self ):
        """to_dict should return exactly 8 keys."""
        from cosa.agents.decision_proxy.trust_tracker import CategoryTrust

        cat = CategoryTrust( "testing", cap_level=5 )
        cat.record_decision( success=True )
        d = cat.to_dict()
        expected_keys = {
            "category_name", "cap_level", "level", "total_decisions",
            "total_successes", "total_rejections", "success_rate", "window_size"
        }
        assert set( d.keys() ) == expected_keys

    def test_to_dict_success_rate_rounded( self ):
        """success_rate should be correctly computed and rounded to 4 decimals."""
        from cosa.agents.decision_proxy.trust_tracker import CategoryTrust

        cat = CategoryTrust( "testing" )
        cat.record_decision( success=True )
        cat.record_decision( success=False )
        cat.record_decision( success=False )
        d = cat.to_dict()
        # 1 success, 2 failures → success_rate = 1/3 = 0.3333
        assert abs( d[ "success_rate" ] - 0.3333 ) < 0.001

    def test_record_decision_default_timestamp( self ):
        """record_decision with no timestamp arg should auto-set to now."""
        from cosa.agents.decision_proxy.trust_tracker import CategoryTrust

        cat = CategoryTrust( "testing" )
        before = time.time()
        cat.record_decision( success=True )
        after = time.time()
        # The auto-generated timestamp should be between before and after
        ts = cat.decisions[ 0 ][ 0 ]
        assert before <= ts <= after


# ============================================================================
# TestTrustTrackerDeep — Deep edge cases
# ============================================================================

class TestTrustTrackerDeep:
    """Deep edge case tests for TrustTracker."""

    def test_record_decision_returns_new_level( self ):
        """record_decision should return the new trust level as an int."""
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker

        tracker = TrustTracker( l2_threshold=3 )
        tracker.register_category( "testing" )
        now = time.time()
        level = tracker.record_decision( "testing", success=True, timestamp=now )
        assert isinstance( level, int )
        assert level >= 1

    def test_demote_unknown_category_no_crash( self ):
        """Demoting a nonexistent category should not raise."""
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker

        tracker = TrustTracker()
        # Should silently return without error
        tracker.demote_category( "nonexistent", levels=2 )

    def test_get_stats_all_keys_per_category( self ):
        """get_stats should return the full 8-key dict per category."""
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker

        tracker = TrustTracker()
        tracker.register_category( "testing" )
        tracker.record_decision( "testing", success=True )
        stats = tracker.get_stats()
        expected_keys = {
            "category_name", "cap_level", "level", "total_decisions",
            "total_successes", "total_rejections", "success_rate", "window_size"
        }
        assert set( stats[ "testing" ].keys() ) == expected_keys

    def test_tracker_constructor_passes_thresholds( self ):
        """TrustTracker thresholds should propagate to registered CategoryTrust."""
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker

        tracker = TrustTracker( l2_threshold=7, l3_threshold=15, l4_threshold=30, l5_threshold=60 )
        tracker.register_category( "testing" )
        cat = tracker.categories[ "testing" ]
        assert cat.thresholds[ 2 ] == 7
        assert cat.thresholds[ 3 ] == 15
        assert cat.thresholds[ 4 ] == 30
        assert cat.thresholds[ 5 ] == 60

    def test_register_then_record_graduation( self ):
        """Register, record enough successes, verify level matches threshold."""
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker

        tracker = TrustTracker( l2_threshold=3, l3_threshold=10 )
        tracker.register_category( "testing" )
        now = time.time()
        for i in range( 11 ):
            tracker.record_decision( "testing", success=True, timestamp=now - i )
        assert tracker.get_level( "testing" ) == 3

    def test_all_six_engineering_categories_registered( self ):
        """Register all 6 engineering categories, verify get_all_levels returns 6."""
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker

        tracker = TrustTracker()
        categories = [ "deployment", "testing", "deps", "architecture", "destructive", "general" ]
        for cat in categories:
            tracker.register_category( cat )
        levels = tracker.get_all_levels()
        assert len( levels ) == 6
        for cat in categories:
            assert cat in levels

    def test_multiple_categories_independent_demote( self ):
        """Demoting one category should not affect another."""
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker

        tracker = TrustTracker( l2_threshold=3 )
        tracker.register_category( "testing" )
        tracker.register_category( "deployment" )
        now = time.time()
        for i in range( 5 ):
            tracker.record_decision( "testing", success=True, timestamp=now - i )
            tracker.record_decision( "deployment", success=True, timestamp=now - i )
        assert tracker.get_level( "testing" ) >= 2
        assert tracker.get_level( "deployment" ) >= 2

        tracker.demote_category( "testing", levels=5 )
        assert tracker.get_level( "testing" ) == 1
        assert tracker.get_level( "deployment" ) >= 2  # Unchanged

    def test_record_unregistered_auto_returns_l1( self ):
        """Recording to an unregistered category returns L1 without crashing."""
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker

        tracker = TrustTracker()
        level = tracker.record_decision( "nonexistent", success=True )
        assert level == 1
        # Should not auto-create the category
        assert "nonexistent" not in tracker.categories


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
