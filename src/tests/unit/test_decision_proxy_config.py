#!/usr/bin/env python3
"""
Unit tests for the Decision Proxy Agent framework (Phases 4b + 4c).

Tests config, smart router, base decision strategy, category classifier,
XML models, trust tracker, and circuit breaker.

Test Classes:
    TestDecisionProxyConfig: Config constants and defaults
    TestSmartRouter: Active hours and user availability routing
    TestDecisionResult: DecisionResult data object
    TestBaseDecisionStrategy: Abstract strategy pipeline
    TestCategoryClassifier: Abstract classifier interface
    TestXmlModels: Pydantic model serialization
    TestDecisionListener: Listener construction
    TestDecisionResponder: Responder construction and event handling
    TestCategoryTrust: Per-category trust scoring
    TestTrustTracker: Multi-category trust management
    TestCircuitBreaker: Anomaly detection and auto-demotion
"""

import time
import pytest
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch


# ============================================================================
# TestDecisionProxyConfig — Constants and defaults
# ============================================================================

class TestDecisionProxyConfig:
    """Tests for decision_proxy.config constants."""

    def test_sender_id( self ):
        from cosa.agents.decision_proxy.cosa_interface import SENDER_ID
        assert SENDER_ID == "decision.proxy@lupin.deepily.ai"
        assert "@" in SENDER_ID

    def test_default_session_id( self ):
        from cosa.agents.decision_proxy.config import DEFAULT_SESSION_ID
        assert DEFAULT_SESSION_ID == "decision proxy"

    def test_trust_levels_defined( self ):
        from cosa.agents.decision_proxy.config import TRUST_LEVELS
        assert len( TRUST_LEVELS ) == 5
        for level in range( 1, 6 ):
            assert level in TRUST_LEVELS
            assert "name" in TRUST_LEVELS[ level ]
            assert "min_decisions" in TRUST_LEVELS[ level ]

    def test_trust_levels_monotonically_increasing( self ):
        from cosa.agents.decision_proxy.config import TRUST_LEVELS
        prev = -1
        for level in range( 1, 6 ):
            current = TRUST_LEVELS[ level ][ "min_decisions" ]
            assert current >= prev, f"L{level} threshold {current} not >= L{level-1} threshold {prev}"
            prev = current

    def test_trust_mode_choices( self ):
        from cosa.agents.decision_proxy.config import TRUST_MODE_CHOICES, DEFAULT_TRUST_MODE
        assert "shadow" in TRUST_MODE_CHOICES
        assert "suggest" in TRUST_MODE_CHOICES
        assert "active" in TRUST_MODE_CHOICES
        assert DEFAULT_TRUST_MODE == "shadow"

    def test_subscribed_events( self ):
        from cosa.agents.decision_proxy.config import SUBSCRIBED_EVENTS
        assert "notification_queue_update" in SUBSCRIBED_EVENTS
        assert "sys_ping" in SUBSCRIBED_EVENTS

    def test_active_hours_defaults( self ):
        from cosa.agents.decision_proxy.config import (
            DEFAULT_ACTIVE_HOURS_START, DEFAULT_ACTIVE_HOURS_END, DEFAULT_TIMEZONE
        )
        assert DEFAULT_ACTIVE_HOURS_START == 9
        assert DEFAULT_ACTIVE_HOURS_END == 22
        assert DEFAULT_TIMEZONE == "America/Chicago"

    def test_circuit_breaker_defaults( self ):
        from cosa.agents.decision_proxy.config import (
            DEFAULT_CB_ERROR_RATE_THRESHOLD,
            DEFAULT_CB_CONFIDENCE_COLLAPSE_THRESHOLD,
            DEFAULT_CB_AUTO_DEMOTION_LEVELS,
            DEFAULT_CB_RECOVERY_COOLDOWN_SECONDS,
        )
        assert 0.0 < DEFAULT_CB_ERROR_RATE_THRESHOLD < 1.0
        assert 0.0 < DEFAULT_CB_CONFIDENCE_COLLAPSE_THRESHOLD < 1.0
        assert DEFAULT_CB_AUTO_DEMOTION_LEVELS >= 1
        assert DEFAULT_CB_RECOVERY_COOLDOWN_SECONDS > 0

    def test_shared_config_re_exported( self ):
        """Verify shared proxy_agents constants are re-exported."""
        from cosa.agents.decision_proxy.config import (
            DEFAULT_SERVER_HOST, DEFAULT_SERVER_PORT,
            get_credentials, get_anthropic_api_key,
        )
        assert DEFAULT_SERVER_HOST == "localhost"
        assert DEFAULT_SERVER_PORT == 7999

    def test_l4_audit_sample_rate( self ):
        from cosa.agents.decision_proxy.config import DEFAULT_L4_AUDIT_SAMPLE_RATE
        assert 0.0 < DEFAULT_L4_AUDIT_SAMPLE_RATE <= 1.0


# ============================================================================
# TestSmartRouter — Active hours and availability routing
# ============================================================================

class TestSmartRouter:
    """Tests for the SmartRouter schedule checking."""

    def test_construction( self ):
        from cosa.agents.decision_proxy.smart_router import SmartRouter
        router = SmartRouter()
        assert router.active_hours_start == 9
        assert router.active_hours_end == 22

    def test_is_active_hours_during_day( self ):
        from cosa.agents.decision_proxy.smart_router import SmartRouter
        router = SmartRouter( active_hours_start=9, active_hours_end=22 )
        noon = datetime( 2026, 2, 14, 12, 0, 0 )
        assert router.is_active_hours( noon ) is True

    def test_is_active_hours_before_start( self ):
        from cosa.agents.decision_proxy.smart_router import SmartRouter
        router = SmartRouter( active_hours_start=9, active_hours_end=22 )
        early = datetime( 2026, 2, 14, 5, 0, 0 )
        assert router.is_active_hours( early ) is False

    def test_is_active_hours_after_end( self ):
        from cosa.agents.decision_proxy.smart_router import SmartRouter
        router = SmartRouter( active_hours_start=9, active_hours_end=22 )
        late = datetime( 2026, 2, 14, 23, 0, 0 )
        assert router.is_active_hours( late ) is False

    def test_is_active_hours_at_boundary( self ):
        from cosa.agents.decision_proxy.smart_router import SmartRouter
        router = SmartRouter( active_hours_start=9, active_hours_end=22 )
        at_start = datetime( 2026, 2, 14, 9, 0, 0 )
        at_end   = datetime( 2026, 2, 14, 22, 0, 0 )
        assert router.is_active_hours( at_start ) is True
        assert router.is_active_hours( at_end ) is False  # 22:00 is end, not included

    def test_wrap_around_hours( self ):
        from cosa.agents.decision_proxy.smart_router import SmartRouter
        router = SmartRouter( active_hours_start=22, active_hours_end=6 )
        late_night = datetime( 2026, 2, 14, 23, 0, 0 )
        early_morning = datetime( 2026, 2, 15, 3, 0, 0 )
        daytime = datetime( 2026, 2, 14, 12, 0, 0 )
        assert router.is_active_hours( late_night ) is True
        assert router.is_active_hours( early_morning ) is True
        assert router.is_active_hours( daytime ) is False

    def test_should_defer_active_and_connected( self ):
        from cosa.agents.decision_proxy.smart_router import SmartRouter
        router = SmartRouter( active_hours_start=9, active_hours_end=22 )
        noon = datetime( 2026, 2, 14, 12, 0, 0 )
        assert router.should_defer_to_user( now=noon, user_connected=True ) is True

    def test_should_not_defer_outside_hours( self ):
        from cosa.agents.decision_proxy.smart_router import SmartRouter
        router = SmartRouter( active_hours_start=9, active_hours_end=22 )
        midnight = datetime( 2026, 2, 15, 2, 0, 0 )
        assert router.should_defer_to_user( now=midnight, user_connected=True ) is False

    def test_should_not_defer_disconnected( self ):
        from cosa.agents.decision_proxy.smart_router import SmartRouter
        router = SmartRouter( active_hours_start=9, active_hours_end=22 )
        noon = datetime( 2026, 2, 14, 12, 0, 0 )
        assert router.should_defer_to_user( now=noon, user_connected=False ) is False


# ============================================================================
# TestDecisionResult — Data object
# ============================================================================

class TestDecisionResult:
    """Tests for the DecisionResult data object."""

    def test_construction( self ):
        from cosa.agents.decision_proxy.base_decision_strategy import DecisionResult
        result = DecisionResult( action="shadow", category="testing", confidence=0.85 )
        assert result.action == "shadow"
        assert result.category == "testing"
        assert result.confidence == 0.85
        assert result.trust_level == 1
        assert result.value is None

    def test_repr( self ):
        from cosa.agents.decision_proxy.base_decision_strategy import DecisionResult
        result = DecisionResult( action="act", category="deps", confidence=0.92, trust_level=3 )
        r = repr( result )
        assert "act" in r
        assert "deps" in r
        assert "3" in r


# ============================================================================
# TestBaseDecisionStrategy — Abstract pipeline
# ============================================================================

class TestBaseDecisionStrategy:
    """Tests for the BaseDecisionStrategy abstract class."""

    def _make_concrete_strategy( self ):
        from cosa.agents.decision_proxy.base_decision_strategy import BaseDecisionStrategy

        class ConcreteStrategy( BaseDecisionStrategy ):
            @property
            def name( self ):
                return "test_strategy"

            def classify( self, question, sender_id="", context=None ):
                if "deploy" in question.lower():
                    return "deployment", 0.9
                return "general", 0.5

            def gate( self, category, trust_level, confidence ):
                if trust_level <= 1:
                    return "shadow"
                if trust_level <= 2:
                    return "suggest"
                return "act"

            def decide( self, question, category, context=None ):
                return "yes"

        return ConcreteStrategy()

    def test_evaluate_shadow_at_l1( self ):
        strategy = self._make_concrete_strategy()
        result = strategy.evaluate( "deploy to production" )
        assert result.action == "shadow"
        assert result.category == "deployment"
        assert result.confidence == 0.9
        assert result.value is None  # Shadow doesn't produce a value

    def test_classify_general_default( self ):
        strategy = self._make_concrete_strategy()
        cat, conf = strategy.classify( "random question" )
        assert cat == "general"
        assert conf == 0.5

    def test_available_default_true( self ):
        strategy = self._make_concrete_strategy()
        assert strategy.available is True

    def test_can_handle_default_true( self ):
        strategy = self._make_concrete_strategy()
        assert strategy.can_handle( {} ) is True


# ============================================================================
# TestCategoryClassifier — Abstract interface
# ============================================================================

class TestCategoryClassifier:
    """Tests for the CategoryClassifier abstract interface."""

    def test_cannot_instantiate_abstract( self ):
        from cosa.agents.decision_proxy.category_classifier import CategoryClassifier
        with pytest.raises( TypeError ):
            CategoryClassifier()

    def test_concrete_implementation( self ):
        from cosa.agents.decision_proxy.category_classifier import CategoryClassifier

        class TestClassifier( CategoryClassifier ):
            def classify( self, question, sender_id="", context=None ):
                return "general", 0.5
            def get_categories( self ):
                return { "general": { "keywords": [], "cap_level": 5 } }

        classifier = TestClassifier()
        cat, conf = classifier.classify( "test" )
        assert cat == "general"
        assert len( classifier.get_categories() ) == 1


# ============================================================================
# TestXmlModels — Pydantic model serialization
# ============================================================================

class TestXmlModels:
    """Tests for decision proxy Pydantic models."""

    def test_classification_result( self ):
        from cosa.agents.decision_proxy.xml_models import ClassificationResult
        result = ClassificationResult( category="testing", confidence=0.85 )
        assert result.category == "testing"
        assert result.confidence == 0.85
        assert result.method == "keyword"

    def test_trust_decision( self ):
        from cosa.agents.decision_proxy.xml_models import TrustDecision
        decision = TrustDecision(
            notification_id = "abc123",
            category        = "deployment",
            question        = "Deploy to production?",
            action          = "shadow",
            confidence      = 0.9,
            trust_level     = 1,
        )
        assert decision.domain == "swe"
        assert decision.action == "shadow"

    def test_trust_decision_json_serialization( self ):
        from cosa.agents.decision_proxy.xml_models import TrustDecision
        decision = TrustDecision(
            notification_id="abc123", category="testing",
            question="Run tests?", action="act", confidence=0.95,
            trust_level=3
        )
        data = decision.model_dump()
        assert data[ "notification_id" ] == "abc123"
        assert data[ "trust_level" ] == 3

    def test_ratification_request( self ):
        from cosa.agents.decision_proxy.xml_models import RatificationRequest
        req = RatificationRequest( decision_id="xyz789", approved=True, feedback="looks good" )
        assert req.approved is True
        assert req.feedback == "looks good"

    def test_decision_summary( self ):
        from cosa.agents.decision_proxy.xml_models import DecisionSummary
        summary = DecisionSummary( total_pending=5, by_category={ "testing": 3, "deps": 2 } )
        assert summary.total_pending == 5
        assert summary.by_category[ "testing" ] == 3


# ============================================================================
# TestDecisionListener — Construction
# ============================================================================

class TestDecisionListener:
    """Tests for the DecisionListener construction."""

    def test_construction( self ):
        from cosa.agents.decision_proxy.listener import DecisionListener

        async def mock_handler( event_type, data ):
            pass

        listener = DecisionListener(
            email    = "test@example.com",
            password = "secret",
            on_event = mock_handler,
        )
        assert listener.session_id == "decision proxy"
        assert listener.LOG_PREFIX == "[DecisionListener]"
        assert "notification_queue_update" in listener.subscribed_events


# ============================================================================
# DecisionResponder — tests live in the COSA-side copy, NOT here (row 4b561b1a)
# ============================================================================
#
# The canonical responder tests are:
#
#     src/cosa/tests/unit/agents/decision_proxy/test_responder.py
#
# They sit next to the code they test (src/cosa/agents/decision_proxy/responder.py)
# and that is the copy a93aab3e updated when it made the sender allowlist FAIL
# CLOSED ("Option C", row 960a4ec9). A duplicate TestDecisionResponder class used
# to live here and was NOT updated, so it went on asserting the fail-OPEN
# behaviour that commit removed on purpose — a stale twin claiming the opposite of
# the maintained one. Deleted rather than patched: two live copies of one test
# disagreeing IS the defect, and fixing the assertion in the stale copy would only
# reset the clock until the next divergence.
#
# Every case it covered is covered better in the canonical file:
#     test_construction              -> test_init_defaults, test_init_with_accepted_senders
#     test_set_domain_strategy       -> test_set_domain_strategy
#     test_handle_non_response_skipped -> test_decision_event_skips_when_no_response_requested
#     test_handle_sender_rejected    -> test_decision_event_sender_rejected_quiet / _debug_prints
#     test_handle_no_strategy_shadows -> test_decision_event_no_strategy_shadows_quiet / _debug
#                                        AND test_empty_allowlist_rejects_every_sender_fail_closed,
#                                        which is the guard for the new behaviour
#     test_stats_extended            -> test_print_stats_outputs_all_counters
#
# Nothing was relaxed to make anything green. Add responder tests THERE, not here.


# ============================================================================
# TestCategoryTrust — Per-category trust scoring
# ============================================================================

class TestCategoryTrust:
    """Tests for CategoryTrust trust level computation."""

    def test_initial_level_is_1( self ):
        from cosa.agents.decision_proxy.trust_tracker import CategoryTrust
        cat = CategoryTrust( "testing" )
        assert cat.level == 1

    def test_level_graduates_to_l2( self ):
        from cosa.agents.decision_proxy.trust_tracker import CategoryTrust
        cat = CategoryTrust( "testing", l2_threshold=5 )
        now = time.time()
        for i in range( 6 ):
            cat.record_decision( success=True, timestamp=now - i )
        assert cat.level >= 2

    def test_cap_level_enforced( self ):
        from cosa.agents.decision_proxy.trust_tracker import CategoryTrust
        cat = CategoryTrust( "deployment", cap_level=3, l2_threshold=3, l3_threshold=10, l4_threshold=20 )
        now = time.time()
        for i in range( 30 ):
            cat.record_decision( success=True, timestamp=now - i )
        assert cat.level == 3  # Capped at 3

    def test_success_rate( self ):
        from cosa.agents.decision_proxy.trust_tracker import CategoryTrust
        cat = CategoryTrust( "testing" )
        cat.record_decision( success=True )
        cat.record_decision( success=True )
        cat.record_decision( success=False )
        assert abs( cat.success_rate - 2.0/3.0 ) < 0.01

    def test_error_rate( self ):
        from cosa.agents.decision_proxy.trust_tracker import CategoryTrust
        cat = CategoryTrust( "testing" )
        cat.record_decision( success=True )
        cat.record_decision( success=False )
        assert abs( cat.error_rate - 0.5 ) < 0.01

    def test_empty_rates( self ):
        from cosa.agents.decision_proxy.trust_tracker import CategoryTrust
        cat = CategoryTrust( "testing" )
        assert cat.success_rate == 0.0
        assert cat.error_rate == 0.0

    def test_demote_clears_history( self ):
        from cosa.agents.decision_proxy.trust_tracker import CategoryTrust
        cat = CategoryTrust( "testing", l2_threshold=5 )
        now = time.time()
        for i in range( 10 ):
            cat.record_decision( success=True, timestamp=now - i )
        assert cat.level >= 2
        cat.demote( levels=5 )  # Demote to L1
        assert cat.level == 1

    def test_to_dict( self ):
        from cosa.agents.decision_proxy.trust_tracker import CategoryTrust
        cat = CategoryTrust( "testing", cap_level=3 )
        cat.record_decision( success=True )
        d = cat.to_dict()
        assert d[ "category_name" ] == "testing"
        assert d[ "cap_level" ] == 3
        assert d[ "total_decisions" ] == 1

    def test_time_decay_reduces_effective_count( self ):
        from cosa.agents.decision_proxy.trust_tracker import CategoryTrust
        cat = CategoryTrust( "testing", l2_threshold=5, decay_half_life_days=1 )
        # Add decisions 30 days ago — should have very low weight
        old_time = time.time() - ( 30 * 86400 )
        for i in range( 10 ):
            cat.record_decision( success=True, timestamp=old_time + i )
        # Effective count should be much less than 10 due to decay
        assert cat._effective_decision_count() < 1.0


# ============================================================================
# TestTrustTracker — Multi-category management
# ============================================================================

class TestTrustTracker:
    """Tests for the TrustTracker multi-category trust management."""

    def test_register_category( self ):
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker
        tracker = TrustTracker()
        tracker.register_category( "testing", cap_level=5 )
        assert "testing" in tracker.categories

    def test_register_duplicate_ignored( self ):
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker
        tracker = TrustTracker()
        tracker.register_category( "testing", cap_level=5 )
        tracker.register_category( "testing", cap_level=3 )  # Should be ignored
        assert tracker.categories[ "testing" ].cap_level == 5

    def test_get_level_unregistered( self ):
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker
        tracker = TrustTracker()
        assert tracker.get_level( "nonexistent" ) == 1

    def test_record_and_check_level( self ):
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker
        tracker = TrustTracker( l2_threshold=3 )
        tracker.register_category( "testing" )
        now = time.time()
        for i in range( 5 ):
            tracker.record_decision( "testing", success=True, timestamp=now - i )
        assert tracker.get_level( "testing" ) >= 2

    def test_categories_independent( self ):
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker
        tracker = TrustTracker( l2_threshold=3 )
        tracker.register_category( "testing" )
        tracker.register_category( "deployment", cap_level=3 )

        now = time.time()
        for i in range( 5 ):
            tracker.record_decision( "testing", success=True, timestamp=now - i )
        # Only testing should graduate, deployment stays at L1
        assert tracker.get_level( "testing" ) >= 2
        assert tracker.get_level( "deployment" ) == 1

    def test_demote_category( self ):
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker
        tracker = TrustTracker( l2_threshold=3 )
        tracker.register_category( "testing" )
        now = time.time()
        for i in range( 10 ):
            tracker.record_decision( "testing", success=True, timestamp=now - i )
        assert tracker.get_level( "testing" ) >= 2
        tracker.demote_category( "testing", levels=5 )
        assert tracker.get_level( "testing" ) == 1

    def test_get_all_levels( self ):
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker
        tracker = TrustTracker()
        tracker.register_category( "testing" )
        tracker.register_category( "deployment" )
        levels = tracker.get_all_levels()
        assert "testing" in levels
        assert "deployment" in levels

    def test_get_stats( self ):
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker
        tracker = TrustTracker()
        tracker.register_category( "testing" )
        tracker.record_decision( "testing", success=True )
        stats = tracker.get_stats()
        assert stats[ "testing" ][ "total_decisions" ] == 1

    def test_record_unknown_category( self ):
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker
        tracker = TrustTracker()
        level = tracker.record_decision( "nonexistent", success=True )
        assert level == 1


# ============================================================================
# TestCircuitBreaker — Anomaly detection and auto-demotion
# ============================================================================

class TestCircuitBreaker:
    """Tests for the CircuitBreaker anomaly detection."""

    def _make_breaker( self, **kwargs ):
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker
        from cosa.agents.decision_proxy.circuit_breaker import CircuitBreaker

        tracker = TrustTracker( l2_threshold=5 )
        tracker.register_category( "testing" )
        tracker.register_category( "deployment", cap_level=3 )

        defaults = {
            "trust_tracker"              : tracker,
            "error_rate_threshold"       : 0.15,
            "confidence_collapse_threshold" : 0.3,
            "auto_demotion_levels"       : 2,
            "recovery_cooldown_seconds"  : 3600,
        }
        defaults.update( kwargs )
        return CircuitBreaker( **defaults ), tracker

    def test_initial_state_not_tripped( self ):
        breaker, _ = self._make_breaker()
        assert breaker.is_tripped( "testing" ) is False

    def test_check_healthy( self ):
        breaker, _ = self._make_breaker()
        assert breaker.check( "testing" ) is True

    def test_error_rate_trips_breaker( self ):
        breaker, tracker = self._make_breaker( error_rate_threshold=0.15 )
        # Record enough decisions with high error rate
        now = time.time()
        for i in range( 8 ):
            tracker.record_decision( "testing", success=True, timestamp=now - i )
        for i in range( 3 ):
            tracker.record_decision( "testing", success=False, timestamp=now - i )
        # Error rate = 3/11 = 0.27 > 0.15
        assert breaker.check( "testing" ) is False
        assert breaker.is_tripped( "testing" ) is True

    def test_confidence_collapse_trips_breaker( self ):
        breaker, _ = self._make_breaker( confidence_collapse_threshold=0.3 )
        # Record low confidence values
        for _ in range( 10 ):
            breaker.record_confidence( "testing", 0.1 )
        assert breaker.check( "testing" ) is False
        assert breaker.is_tripped( "testing" ) is True

    def test_high_confidence_healthy( self ):
        breaker, _ = self._make_breaker()
        for _ in range( 10 ):
            breaker.record_confidence( "testing", 0.9 )
        assert breaker.check( "testing" ) is True

    def test_trip_callback( self ):
        callback = MagicMock()
        breaker, _ = self._make_breaker( on_trip_callback=callback )
        breaker.trip( "testing", reason="test trip" )
        callback.assert_called_once_with( "testing", "test trip" )

    def test_manual_reset( self ):
        breaker, _ = self._make_breaker()
        breaker.trip( "testing", reason="test" )
        assert breaker.is_tripped( "testing" ) is True
        breaker.reset( "testing" )
        assert breaker.is_tripped( "testing" ) is False

    def test_cooldown_recovery( self ):
        breaker, _ = self._make_breaker( recovery_cooldown_seconds=1 )
        breaker.trip( "testing", reason="test" )
        assert breaker.is_tripped( "testing" ) is True
        # Simulate cooldown expiry
        breaker._tripped[ "testing" ] = time.time() - 2
        assert breaker.is_tripped( "testing" ) is False

    def test_get_average_confidence_empty( self ):
        breaker, _ = self._make_breaker()
        assert breaker.get_average_confidence( "testing" ) == 1.0

    def test_get_average_confidence_computed( self ):
        breaker, _ = self._make_breaker()
        breaker.record_confidence( "testing", 0.8 )
        breaker.record_confidence( "testing", 0.6 )
        avg = breaker.get_average_confidence( "testing" )
        assert abs( avg - 0.7 ) < 0.01

    def test_get_status( self ):
        breaker, _ = self._make_breaker()
        status = breaker.get_status()
        assert "testing" in status
        assert "deployment" in status
        assert status[ "testing" ][ "tripped" ] is False

    def test_confidence_window_trimmed( self ):
        breaker, _ = self._make_breaker()
        for i in range( 50 ):
            breaker.record_confidence( "testing", 0.5 )
        assert len( breaker._confidence_window[ "testing" ] ) == breaker._confidence_window_size

    def test_check_unknown_category_healthy( self ):
        breaker, _ = self._make_breaker()
        assert breaker.check( "nonexistent" ) is True
