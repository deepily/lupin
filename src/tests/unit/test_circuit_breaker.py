#!/usr/bin/env python3
"""
Gap-filling unit tests for the Circuit Breaker (Phase 4c).

Tests for CircuitBreaker covering:
    - Minimum sample gate (error rate requires >= 10 decisions)
    - Confidence boundary (collapse requires >= 5 values)
    - Trip demotion integration with TrustTracker
    - Multi-category independence
    - Reset behavior (confidence window clearing)
    - Callback edge cases
    - Cooldown timing and auto-recovery
    - Confidence window management

Does NOT duplicate tests already in test_decision_proxy_config.py:
    - Initial not tripped, check healthy, error rate trips, confidence collapse trips,
      high confidence healthy, trip callback, manual reset, cooldown recovery,
      avg confidence empty/computed, get_status basic, window trimmed, unknown category healthy
"""

import time
import pytest
from unittest.mock import MagicMock


# ============================================================================
# Helper factory
# ============================================================================

def _make_breaker( **kwargs ):
    """Create a CircuitBreaker + TrustTracker pair with small test thresholds."""
    from cosa.agents.decision_proxy.trust_tracker import TrustTracker
    from cosa.agents.decision_proxy.circuit_breaker import CircuitBreaker

    tracker = TrustTracker( l2_threshold=5, l3_threshold=10, l4_threshold=20, l5_threshold=40 )
    tracker.register_category( "testing" )
    tracker.register_category( "deployment", cap_level=3 )

    defaults = {
        "trust_tracker"                 : tracker,
        "error_rate_threshold"          : 0.15,
        "confidence_collapse_threshold" : 0.3,
        "auto_demotion_levels"          : 1,
        "recovery_cooldown_seconds"     : 3600,
    }
    defaults.update( kwargs )
    return CircuitBreaker( **defaults ), tracker


# ============================================================================
# TestCircuitBreakerMinimumSample — Error rate min-sample gate
# ============================================================================

class TestCircuitBreakerMinimumSample:
    """Tests for the minimum 10-decision gate on error rate tripping."""

    def test_high_error_rate_below_min_sample_no_trip( self ):
        """3 out of 5 failures (60%) but total < 10 decisions, should not trip."""
        breaker, tracker = _make_breaker( error_rate_threshold=0.15 )
        now = time.time()
        for i in range( 2 ):
            tracker.record_decision( "testing", success=True, timestamp=now - i )
        for i in range( 3 ):
            tracker.record_decision( "testing", success=False, timestamp=now - i )
        # Total = 5 < 10, so error rate check is skipped
        assert breaker.check( "testing" ) is True
        assert breaker.is_tripped( "testing" ) is False

    def test_exactly_ten_decisions_with_high_error_trips( self ):
        """At exactly 10 decisions with high error rate, should trip."""
        breaker, tracker = _make_breaker( error_rate_threshold=0.15 )
        now = time.time()
        for i in range( 7 ):
            tracker.record_decision( "testing", success=True, timestamp=now - i )
        for i in range( 3 ):
            tracker.record_decision( "testing", success=False, timestamp=now - 10 - i )
        # Total = 10, error rate = 3/10 = 0.30 > 0.15
        assert breaker.check( "testing" ) is False
        assert breaker.is_tripped( "testing" ) is True

    def test_nine_decisions_with_high_error_no_trip( self ):
        """At 9 decisions (< 10), error rate check should be skipped."""
        breaker, tracker = _make_breaker( error_rate_threshold=0.15 )
        now = time.time()
        for i in range( 5 ):
            tracker.record_decision( "testing", success=True, timestamp=now - i )
        for i in range( 4 ):
            tracker.record_decision( "testing", success=False, timestamp=now - 10 - i )
        # Total = 9 < 10
        assert breaker.check( "testing" ) is True


# ============================================================================
# TestCircuitBreakerConfidenceBoundary — Window size boundaries
# ============================================================================

class TestCircuitBreakerConfidenceBoundary:
    """Tests for confidence collapse window size boundaries."""

    def test_four_low_confidence_values_no_trip( self ):
        """Fewer than 5 confidence values should not trigger collapse check."""
        breaker, _ = _make_breaker( confidence_collapse_threshold=0.3 )
        for _ in range( 4 ):
            breaker.record_confidence( "testing", 0.1 )
        assert breaker.check( "testing" ) is True

    def test_exactly_five_low_confidence_values_trips( self ):
        """Exactly 5 low confidence values should trigger collapse and trip."""
        breaker, _ = _make_breaker( confidence_collapse_threshold=0.3 )
        for _ in range( 5 ):
            breaker.record_confidence( "testing", 0.1 )
        assert breaker.check( "testing" ) is False
        assert breaker.is_tripped( "testing" ) is True

    def test_mixed_confidence_above_threshold_healthy( self ):
        """Average confidence of 0.34 (> 0.3) should remain healthy."""
        breaker, _ = _make_breaker( confidence_collapse_threshold=0.3 )
        # Values: 0.5, 0.5, 0.1, 0.3, 0.3 → avg = 0.34
        for val in [ 0.5, 0.5, 0.1, 0.3, 0.3 ]:
            breaker.record_confidence( "testing", val )
        assert breaker.check( "testing" ) is True

    def test_mixed_confidence_below_threshold_trips( self ):
        """Average confidence of 0.19 (< 0.3) should trip."""
        breaker, _ = _make_breaker( confidence_collapse_threshold=0.3 )
        # Values: 0.1, 0.2, 0.15, 0.2, 0.3 → avg = 0.19
        for val in [ 0.1, 0.2, 0.15, 0.2, 0.3 ]:
            breaker.record_confidence( "testing", val )
        assert breaker.check( "testing" ) is False


# ============================================================================
# TestCircuitBreakerTripDemotion — Trip → trust demotion
# ============================================================================

class TestCircuitBreakerTripDemotion:
    """Tests for trip() causing trust level demotion via tracker."""

    def test_trip_demotes_trust_level( self ):
        """After trip(), tracker level should be decreased."""
        breaker, tracker = _make_breaker( auto_demotion_levels=1 )
        now = time.time()
        # Build to L2 (l2_threshold=5)
        for i in range( 6 ):
            tracker.record_decision( "testing", success=True, timestamp=now - i )
        assert tracker.get_level( "testing" ) >= 2

        breaker.trip( "testing", "test demotion" )
        assert tracker.get_level( "testing" ) < 2 or tracker.get_level( "testing" ) == 1

    def test_trip_demotes_by_configured_levels( self ):
        """auto_demotion_levels=2 should demote by exactly 2 levels."""
        breaker, tracker = _make_breaker( auto_demotion_levels=2 )
        now = time.time()
        # Build to L3 (l3_threshold=10)
        for i in range( 11 ):
            tracker.record_decision( "testing", success=True, timestamp=now - i )
        assert tracker.get_level( "testing" ) == 3

        breaker.trip( "testing", "test 2-level demotion" )
        assert tracker.get_level( "testing" ) == 1

    def test_trip_at_l1_stays_at_l1( self ):
        """Tripping at L1 should stay at L1, not crash."""
        breaker, tracker = _make_breaker( auto_demotion_levels=2 )
        assert tracker.get_level( "testing" ) == 1
        breaker.trip( "testing", "already at L1" )
        assert tracker.get_level( "testing" ) == 1


# ============================================================================
# TestCircuitBreakerMultiCategory — Multi-category interactions
# ============================================================================

class TestCircuitBreakerMultiCategory:
    """Tests for independent multi-category circuit breaker behavior."""

    def test_trip_two_categories_independently( self ):
        """Trip both categories, reset one, other should remain tripped."""
        breaker, _ = _make_breaker()
        breaker.trip( "testing", "test trip" )
        breaker.trip( "deployment", "deploy trip" )
        assert breaker.is_tripped( "testing" ) is True
        assert breaker.is_tripped( "deployment" ) is True

        breaker.reset( "testing" )
        assert breaker.is_tripped( "testing" ) is False
        assert breaker.is_tripped( "deployment" ) is True

    def test_status_shows_both_tripped( self ):
        """get_status should reflect both categories as tripped."""
        breaker, _ = _make_breaker()
        breaker.trip( "testing", "trip 1" )
        breaker.trip( "deployment", "trip 2" )
        status = breaker.get_status()
        assert status[ "testing" ][ "tripped" ] is True
        assert status[ "deployment" ][ "tripped" ] is True

    def test_check_one_tripped_other_healthy( self ):
        """Tripping one category should not affect check() on the other."""
        breaker, _ = _make_breaker()
        breaker.trip( "testing", "test trip" )
        assert breaker.check( "testing" ) is False
        assert breaker.check( "deployment" ) is True


# ============================================================================
# TestCircuitBreakerReset — Reset behavior
# ============================================================================

class TestCircuitBreakerReset:
    """Tests for reset() clearing trip state and confidence window."""

    def test_reset_clears_confidence_window( self ):
        """After reset, avg confidence should return to default 1.0."""
        breaker, _ = _make_breaker()
        for _ in range( 10 ):
            breaker.record_confidence( "testing", 0.3 )
        assert breaker.get_average_confidence( "testing" ) < 0.5

        breaker.reset( "testing" )
        assert breaker.get_average_confidence( "testing" ) == 1.0

    def test_check_after_reset_returns_healthy( self ):
        """check() should return True immediately after reset."""
        breaker, _ = _make_breaker()
        breaker.trip( "testing", "test trip" )
        assert breaker.check( "testing" ) is False

        breaker.reset( "testing" )
        assert breaker.check( "testing" ) is True

    def test_reset_nonexistent_category_no_crash( self ):
        """Resetting a category that was never tripped should not raise."""
        breaker, _ = _make_breaker()
        breaker.reset( "nonexistent_category" )  # Should not crash


# ============================================================================
# TestCircuitBreakerCallback — Callback edge cases
# ============================================================================

class TestCircuitBreakerCallback:
    """Tests for on_trip_callback edge cases."""

    def test_trip_without_callback_no_crash( self ):
        """Tripping with callback=None should work fine."""
        breaker, _ = _make_breaker( on_trip_callback=None )
        breaker.trip( "testing", "no callback" )
        assert breaker.is_tripped( "testing" ) is True

    def test_trip_callback_receives_category_and_reason( self ):
        """Callback should receive ( category_name, reason ) args."""
        callback = MagicMock()
        breaker, _ = _make_breaker( on_trip_callback=callback )
        breaker.trip( "testing", reason="confidence too low" )
        callback.assert_called_once_with( "testing", "confidence too low" )

    def test_check_triggered_trip_fires_callback( self ):
        """Auto-trip from check() should also fire the callback."""
        callback = MagicMock()
        breaker, _ = _make_breaker(
            on_trip_callback=callback,
            confidence_collapse_threshold=0.3
        )
        for _ in range( 5 ):
            breaker.record_confidence( "testing", 0.1 )
        breaker.check( "testing" )
        assert callback.called
        args = callback.call_args[ 0 ]
        assert args[ 0 ] == "testing"
        assert "confidence" in args[ 1 ].lower() or "Avg" in args[ 1 ]


# ============================================================================
# TestCircuitBreakerCooldown — Cooldown timing
# ============================================================================

class TestCircuitBreakerCooldown:
    """Tests for cooldown timing and auto-recovery."""

    def test_get_status_with_positive_cooldown_remaining( self ):
        """Tripped category should have positive cooldown_remaining in status."""
        breaker, _ = _make_breaker( recovery_cooldown_seconds=3600 )
        breaker.trip( "testing", "cooldown test" )
        status = breaker.get_status()
        assert status[ "testing" ][ "cooldown_remaining" ] > 0

    def test_get_status_cooldown_remaining_zero_after_expiry( self ):
        """Expired cooldown should show cooldown_remaining = 0."""
        breaker, _ = _make_breaker( recovery_cooldown_seconds=100 )
        breaker.trip( "testing", "cooldown test" )
        # Backdate the trip time to simulate expiry
        breaker._tripped[ "testing" ] = time.time() - 200
        status = breaker.get_status()
        assert status[ "testing" ][ "cooldown_remaining" ] == 0
        assert status[ "testing" ][ "tripped" ] is False

    def test_is_tripped_auto_recovers_and_cleans_up( self ):
        """After cooldown expires, is_tripped should remove from _tripped dict."""
        breaker, _ = _make_breaker( recovery_cooldown_seconds=100 )
        breaker.trip( "testing", "auto-recovery test" )
        assert "testing" in breaker._tripped

        # Backdate to simulate expiry
        breaker._tripped[ "testing" ] = time.time() - 200
        assert breaker.is_tripped( "testing" ) is False
        assert "testing" not in breaker._tripped

    def test_cooldown_at_exact_boundary( self ):
        """At elapsed == cooldown, should recover (>= threshold)."""
        breaker, _ = _make_breaker( recovery_cooldown_seconds=100 )
        breaker.trip( "testing", "boundary test" )
        # Set trip time so elapsed is exactly 100 seconds
        breaker._tripped[ "testing" ] = time.time() - 100
        # elapsed (100) >= recovery_cooldown_seconds (100) → recovered
        assert breaker.is_tripped( "testing" ) is False


# ============================================================================
# TestCircuitBreakerConfidenceWindow — Window management
# ============================================================================

class TestCircuitBreakerConfidenceWindow:
    """Tests for confidence window internal management."""

    def test_window_size_default_is_20( self ):
        """Default confidence window size should be 20."""
        breaker, _ = _make_breaker()
        assert breaker._confidence_window_size == 20

    def test_window_retains_most_recent_values( self ):
        """Window should keep the most recent values after overflow."""
        breaker, _ = _make_breaker()
        # Record 25 values: 0.1 * 20, then 0.9 * 5
        for _ in range( 20 ):
            breaker.record_confidence( "testing", 0.1 )
        for _ in range( 5 ):
            breaker.record_confidence( "testing", 0.9 )
        window = breaker._confidence_window[ "testing" ]
        assert len( window ) == 20
        # The last 5 values should be 0.9
        assert all( abs( v - 0.9 ) < 0.01 for v in window[ -5: ] )

    def test_separate_windows_per_category( self ):
        """Each category should have its own independent confidence window."""
        breaker, _ = _make_breaker()
        breaker.record_confidence( "testing", 0.9 )
        breaker.record_confidence( "deployment", 0.1 )
        assert abs( breaker.get_average_confidence( "testing" ) - 0.9 ) < 0.01
        assert abs( breaker.get_average_confidence( "deployment" ) - 0.1 ) < 0.01

    def test_empty_confidence_window_for_category( self ):
        """New category with no confidence data should return default 1.0."""
        breaker, _ = _make_breaker()
        assert breaker.get_average_confidence( "never_seen" ) == 1.0


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
