"""
Offline smoke tests for the Decision Proxy subsystem.

Covers TrustTracker, CircuitBreaker, and CategoryTrust — the three core
classes that have 175 unit tests but zero inline quick_smoke_test() functions.
This is a subsystem-level test that exercises cross-module interactions.

All tests are offline: no server, no LLM, no external dependencies.

Created: 2026-02-17 (Session 221 — Smoke Test Coverage Audit)
Converted to Pattern A: 2026-02-17 (Session 222 — Consistency Cleanup)
"""

import time

from cosa.agents.decision_proxy.trust_tracker import TrustTracker, CategoryTrust
from cosa.agents.decision_proxy.circuit_breaker import CircuitBreaker
from cosa.agents.decision_proxy.config import (
    DEFAULT_CB_ERROR_RATE_THRESHOLD,
    DEFAULT_CB_CONFIDENCE_COLLAPSE_THRESHOLD,
    DEFAULT_CB_AUTO_DEMOTION_LEVELS,
    DEFAULT_CB_RECOVERY_COOLDOWN_SECONDS,
)


def quick_smoke_test():
    """
    Quick smoke test for decision proxy offline components.

    Requires:
        - cosa.agents.decision_proxy package importable

    Ensures:
        - TrustTracker creates, registers categories, graduates, demotes
        - CircuitBreaker creates with defaults, trips, recovers after cooldown
        - CircuitBreaker trips on high error rate and low confidence
        - CategoryTrust serializes to dict with correct structure
        - Independent categories do not affect each other
        - Returns True on success
    """
    print( "\n" + "=" * 70 )
    print( "  Decision Proxy Offline Smoke Test" )
    print( "=" * 70 )

    try:
        # 1. TrustTracker instantiation and defaults
        print( "\n1. TrustTracker instantiation..." )
        tracker = TrustTracker( debug=True )
        assert tracker.categories == {}
        assert tracker.l2_threshold == 50
        assert tracker.rolling_window_days == 30
        print( "   PASS: TrustTracker defaults correct" )

        # 2. Register and get level
        print( "2. Register categories..." )
        tracker = TrustTracker( l2_threshold=3, debug=False )
        tracker.register_category( "routing", cap_level=5 )
        tracker.register_category( "math", cap_level=3 )
        assert tracker.get_level( "routing" ) == 1
        assert tracker.get_level( "unknown" ) == 1
        assert len( tracker.categories ) == 2
        print( "   PASS: Categories registered at level 1" )

        # 3. Graduation lifecycle
        print( "3. Graduation lifecycle..." )
        for _ in range( 5 ):
            tracker.record_decision( "routing", success=True )
        assert tracker.get_level( "routing" ) == 2
        print( "   PASS: Graduated routing to L2" )

        # 4. Demotion
        print( "4. Demotion..." )
        tracker.demote_category( "routing", levels=1 )
        assert tracker.get_level( "routing" ) == 1
        print( "   PASS: Demoted routing back to L1" )

        # 5. Independent categories
        print( "5. Independent categories..." )
        tracker2 = TrustTracker( l2_threshold=3 )
        tracker2.register_category( "routing" )
        tracker2.register_category( "math" )
        for _ in range( 5 ):
            tracker2.record_decision( "routing", success=True )
        for _ in range( 10 ):
            tracker2.record_decision( "math", success=False )
        assert tracker2.get_level( "routing" ) == 2
        assert tracker2.get_level( "math" ) == 1
        print( "   PASS: Categories are independent" )

        # 6. Stats and serialization
        print( "6. Stats and serialization..." )
        stats = tracker2.get_stats()
        assert "routing" in stats
        assert "level" in stats[ "routing" ]
        assert "total_decisions" in stats[ "routing" ]
        levels = tracker2.get_all_levels()
        assert "routing" in levels and "math" in levels
        print( "   PASS: get_stats and get_all_levels work" )

        # 7. CircuitBreaker instantiation
        print( "7. CircuitBreaker defaults..." )
        cb_tracker = TrustTracker()
        cb = CircuitBreaker( trust_tracker=cb_tracker )
        assert cb.error_rate_threshold == DEFAULT_CB_ERROR_RATE_THRESHOLD
        assert cb.confidence_collapse_threshold == DEFAULT_CB_CONFIDENCE_COLLAPSE_THRESHOLD
        assert cb.auto_demotion_levels == DEFAULT_CB_AUTO_DEMOTION_LEVELS
        assert cb.recovery_cooldown_seconds == DEFAULT_CB_RECOVERY_COOLDOWN_SECONDS
        assert not cb.is_tripped( "anything" )
        print( "   PASS: CircuitBreaker defaults correct" )

        # 8. Trip and recover
        print( "8. CircuitBreaker trip/recover..." )
        trip_tracker = TrustTracker( l2_threshold=5 )
        trip_tracker.register_category( "test_cat" )
        cb2 = CircuitBreaker( trust_tracker=trip_tracker, recovery_cooldown_seconds=1, debug=True )
        cb2.trip( "test_cat", reason="smoke test" )
        assert cb2.is_tripped( "test_cat" )
        time.sleep( 1.1 )
        assert not cb2.is_tripped( "test_cat" )
        print( "   PASS: Trip and auto-recovery work" )

        # 9. Error rate trip
        print( "9. Error rate trip..." )
        er_tracker = TrustTracker( l2_threshold=5 )
        er_tracker.register_category( "test_cat" )
        cb3 = CircuitBreaker( trust_tracker=er_tracker, error_rate_threshold=0.3, debug=True )
        for i in range( 10 ):
            er_tracker.record_decision( "test_cat", success=( i < 3 ) )
        result = cb3.check( "test_cat" )
        assert result is False
        assert cb3.is_tripped( "test_cat" )
        print( "   PASS: Error rate trips breaker" )

        # 10. Confidence collapse trip
        print( "10. Confidence collapse trip..." )
        cc_tracker = TrustTracker( l2_threshold=5 )
        cc_tracker.register_category( "test_cat" )
        cb4 = CircuitBreaker( trust_tracker=cc_tracker, confidence_collapse_threshold=0.5, debug=True )
        for _ in range( 5 ):
            cb4.record_confidence( "test_cat", 0.2 )
        result = cb4.check( "test_cat" )
        assert result is False
        assert cb4.is_tripped( "test_cat" )
        print( "   PASS: Confidence collapse trips breaker" )

        # 11. Reset
        print( "11. CircuitBreaker reset..." )
        cb4.reset( "test_cat" )
        assert not cb4.is_tripped( "test_cat" )
        assert cb4.get_average_confidence( "test_cat" ) == 1.0
        print( "   PASS: Reset clears state" )

        # 12. Trip callback
        print( "12. Trip callback..." )
        callbacks = []
        def on_trip( category, reason ):
            callbacks.append( ( category, reason ) )
        cb_cb_tracker = TrustTracker( l2_threshold=5 )
        cb_cb_tracker.register_category( "test_cat" )
        cb5 = CircuitBreaker( trust_tracker=cb_cb_tracker, on_trip_callback=on_trip, debug=True )
        cb5.trip( "test_cat", reason="callback test" )
        assert len( callbacks ) == 1
        assert callbacks[ 0 ][ 0 ] == "test_cat"
        print( "   PASS: Trip callback invoked" )

        # 13. get_status structure
        print( "13. get_status structure..." )
        status = cb5.get_status()
        assert "test_cat" in status
        assert "tripped" in status[ "test_cat" ]
        assert "cooldown_remaining" in status[ "test_cat" ]
        assert "avg_confidence" in status[ "test_cat" ]
        print( "   PASS: get_status returns correct structure" )

        # 14. CategoryTrust serialization
        print( "14. CategoryTrust serialization..." )
        cat = CategoryTrust( category_name="routing", cap_level=5, l2_threshold=10 )
        assert cat.level == 1
        assert cat.total_decisions == 0
        d = cat.to_dict()
        assert d[ "category_name" ] == "routing"
        assert d[ "level" ] == 1
        assert d[ "success_rate" ] == 0.0
        print( "   PASS: CategoryTrust serializes correctly" )

        # 15. CategoryTrust error rate
        print( "15. CategoryTrust error rate..." )
        cat2 = CategoryTrust( category_name="test", l2_threshold=100 )
        assert cat2.error_rate == 0.0
        cat2.record_decision( True )
        cat2.record_decision( False )
        assert abs( cat2.error_rate - 0.5 ) < 0.01
        print( "   PASS: Error rate tracking works" )

        print( "\n" + "=" * 70 )
        print( "  ALL DECISION PROXY OFFLINE SMOKE TESTS PASSED (15/15)" )
        print( "=" * 70 )
        return True

    except Exception as e:
        print( f"\n  FAIL: {e}" )
        import traceback
        traceback.print_exc()
        return False


def test_decision_proxy_offline():
    """Pytest entry point."""
    assert quick_smoke_test()


if __name__ == "__main__":
    quick_smoke_test()
