#!/usr/bin/env python3
"""
Gap-filling unit tests for Engineering Decisions (Phase 4e).

Tests for:
    - Engineering category keyword content validation
    - Config cap level constant values
    - Sender category hints edge cases
    - Classifier confidence formula precision
    - Strategy evaluate with real trust buildup
    - Strategy custom construction

Does NOT duplicate tests already in test_swe_engineering_proxy.py:
    - Categories: 6 defined, required exist, keywords/cap_level/description,
      deploy/destructive/arch at L3, testing at L5, general catch-all, get_names,
      unknown=5
    - Classifier: deploy/test/delete/deps/arch classification, general fallback,
      tester hint, hint vs keyword precedence, multi-keyword boost, get_categories,
      confidence bounded
    - Strategy: name, available, shadow/suggest/active gate modes, decide
      high/low risk, evaluate shadow/active pipeline, can_handle accepted/rejected/none,
      categories registered, CB tripped defers
    - Config: accepted senders x3, cap levels valid
"""

import time
import pytest
from unittest.mock import MagicMock


# ============================================================================
# TestEngineeringCategoryKeywords — Keyword content validation
# ============================================================================

class TestEngineeringCategoryKeywords:
    """Tests for specific keyword presence in engineering categories."""

    def test_deployment_has_core_keywords( self ):
        """Deployment category should contain deploy, production, rollback."""
        from cosa.agents.swe_team.proxy.engineering_categories import ENGINEERING_CATEGORIES

        keywords = ENGINEERING_CATEGORIES[ "deployment" ][ "keywords" ]
        for kw in [ "deploy", "production", "rollback" ]:
            assert kw in keywords, f"Missing keyword '{kw}' in deployment"

    def test_destructive_has_core_keywords( self ):
        """Destructive category should contain delete, rm -rf, force push."""
        from cosa.agents.swe_team.proxy.engineering_categories import ENGINEERING_CATEGORIES

        keywords = ENGINEERING_CATEGORIES[ "destructive" ][ "keywords" ]
        for kw in [ "delete", "rm -rf", "force push" ]:
            assert kw in keywords, f"Missing keyword '{kw}' in destructive"

    def test_testing_has_core_keywords( self ):
        """Testing category should contain pytest, coverage, unit test."""
        from cosa.agents.swe_team.proxy.engineering_categories import ENGINEERING_CATEGORIES

        keywords = ENGINEERING_CATEGORIES[ "testing" ][ "keywords" ]
        for kw in [ "pytest", "coverage", "unit test" ]:
            assert kw in keywords, f"Missing keyword '{kw}' in testing"

    def test_deps_has_core_keywords( self ):
        """Deps category should contain pip install, requirements, upgrade."""
        from cosa.agents.swe_team.proxy.engineering_categories import ENGINEERING_CATEGORIES

        keywords = ENGINEERING_CATEGORIES[ "deps" ][ "keywords" ]
        for kw in [ "pip install", "requirements", "upgrade" ]:
            assert kw in keywords, f"Missing keyword '{kw}' in deps"

    def test_architecture_has_core_keywords( self ):
        """Architecture category should contain refactor, schema, migration."""
        from cosa.agents.swe_team.proxy.engineering_categories import ENGINEERING_CATEGORIES

        keywords = ENGINEERING_CATEGORIES[ "architecture" ][ "keywords" ]
        for kw in [ "refactor", "schema", "migration" ]:
            assert kw in keywords, f"Missing keyword '{kw}' in architecture"

    def test_no_duplicate_keywords_across_categories( self ):
        """No keyword should appear in multiple categories."""
        from cosa.agents.swe_team.proxy.engineering_categories import ENGINEERING_CATEGORIES

        seen = {}
        for cat_name, cat_def in ENGINEERING_CATEGORIES.items():
            for kw in cat_def[ "keywords" ]:
                if kw in seen:
                    pytest.fail( f"Keyword '{kw}' duplicated in '{seen[ kw ]}' and '{cat_name}'" )
                seen[ kw ] = cat_name


# ============================================================================
# TestEngineeringCategoryCapConstants — config.py cap constant values
# ============================================================================

class TestEngineeringCategoryCapConstants:
    """Tests for exact cap level constant values in SWE proxy config."""

    def test_deployment_cap_constant_value( self ):
        """DEFAULT_DEPLOYMENT_CAP_LEVEL should be 3."""
        from cosa.agents.swe_team.proxy.config import DEFAULT_DEPLOYMENT_CAP_LEVEL
        assert DEFAULT_DEPLOYMENT_CAP_LEVEL == 3

    def test_destructive_cap_constant_value( self ):
        """DEFAULT_DESTRUCTIVE_CAP_LEVEL should be 3."""
        from cosa.agents.swe_team.proxy.config import DEFAULT_DESTRUCTIVE_CAP_LEVEL
        assert DEFAULT_DESTRUCTIVE_CAP_LEVEL == 3

    def test_architecture_cap_constant_value( self ):
        """DEFAULT_ARCHITECTURE_CAP_LEVEL should be 3."""
        from cosa.agents.swe_team.proxy.config import DEFAULT_ARCHITECTURE_CAP_LEVEL
        assert DEFAULT_ARCHITECTURE_CAP_LEVEL == 3

    def test_testing_cap_constant_value( self ):
        """DEFAULT_TESTING_CAP_LEVEL should be 5."""
        from cosa.agents.swe_team.proxy.config import DEFAULT_TESTING_CAP_LEVEL
        assert DEFAULT_TESTING_CAP_LEVEL == 5

    def test_deps_cap_constant_value( self ):
        """DEFAULT_DEPS_CAP_LEVEL should be 5."""
        from cosa.agents.swe_team.proxy.config import DEFAULT_DEPS_CAP_LEVEL
        assert DEFAULT_DEPS_CAP_LEVEL == 5

    def test_general_cap_constant_value( self ):
        """DEFAULT_GENERAL_CAP_LEVEL should be 5."""
        from cosa.agents.swe_team.proxy.config import DEFAULT_GENERAL_CAP_LEVEL
        assert DEFAULT_GENERAL_CAP_LEVEL == 5


# ============================================================================
# TestSenderCategoryHints — SENDER_CATEGORY_HINTS edge cases
# ============================================================================

class TestSenderCategoryHints:
    """Tests for sender category hint lookup edge cases."""

    def test_tester_hint_is_testing( self ):
        """swe.tester should hint to 'testing'."""
        from cosa.agents.swe_team.proxy.engineering_classifier import SENDER_CATEGORY_HINTS
        assert SENDER_CATEGORY_HINTS[ "swe.tester" ] == "testing"

    def test_coder_hint_is_none( self ):
        """swe.coder should hint to None (produces all categories)."""
        from cosa.agents.swe_team.proxy.engineering_classifier import SENDER_CATEGORY_HINTS
        assert SENDER_CATEGORY_HINTS[ "swe.coder" ] is None

    def test_lead_hint_is_none( self ):
        """swe.lead should hint to None (produces all categories)."""
        from cosa.agents.swe_team.proxy.engineering_classifier import SENDER_CATEGORY_HINTS
        assert SENDER_CATEGORY_HINTS[ "swe.lead" ] is None

    def test_unknown_prefix_returns_none( self ):
        """_get_sender_hint for unknown prefix should return None."""
        from cosa.agents.swe_team.proxy.engineering_classifier import EngineeringClassifier

        classifier = EngineeringClassifier()
        assert classifier._get_sender_hint( "unknown.agent@lupin.deepily.ai" ) is None

    def test_empty_sender_returns_none( self ):
        """_get_sender_hint for empty string should return None."""
        from cosa.agents.swe_team.proxy.engineering_classifier import EngineeringClassifier

        classifier = EngineeringClassifier()
        assert classifier._get_sender_hint( "" ) is None

    def test_sender_without_at_sign( self ):
        """_get_sender_hint for 'swe.tester' (no @) should use full string as prefix."""
        from cosa.agents.swe_team.proxy.engineering_classifier import EngineeringClassifier

        classifier = EngineeringClassifier()
        # "swe.tester" without @ → prefix = "swe.tester" → should match hint
        result = classifier._get_sender_hint( "swe.tester" )
        assert result == "testing"


# ============================================================================
# TestClassifierConfidenceFormula — Precise confidence calculation
# ============================================================================

class TestClassifierConfidenceFormula:
    """Tests for exact confidence formula behavior in EngineeringClassifier."""

    def _make_classifier( self ):
        from cosa.agents.swe_team.proxy.engineering_classifier import EngineeringClassifier
        return EngineeringClassifier( debug=False )

    def test_single_keyword_confidence_is_0_6( self ):
        """A single keyword match should yield confidence = 0.5 + 1*0.1 = 0.6."""
        classifier = self._make_classifier()
        # "deploy" matches one keyword in deployment
        _, conf = classifier.classify( "deploy" )
        assert abs( conf - 0.6 ) < 0.01

    def test_two_keywords_confidence_is_0_7( self ):
        """Two keyword matches should yield confidence = 0.5 + 2*0.1 = 0.7."""
        classifier = self._make_classifier()
        # "deploy to production" matches "deploy" and "production"
        _, conf = classifier.classify( "deploy to production" )
        assert abs( conf - 0.7 ) < 0.01

    def test_confidence_capped_at_0_95( self ):
        """Many keyword matches should cap at 0.95."""
        classifier = self._make_classifier()
        # Jam many deployment keywords together
        question = "deploy deployment release rollback production staging docker container kubernetes"
        _, conf = classifier.classify( question )
        assert abs( conf - 0.95 ) < 0.01

    def test_sender_boost_adds_0_15( self ):
        """Matching sender hint should add 0.15 boost to keyword confidence."""
        classifier = self._make_classifier()
        # "test" matches 1 keyword → base 0.6, + sender boost 0.15 = 0.75
        _, conf = classifier.classify( "test", sender_id="swe.tester@lupin.deepily.ai" )
        assert abs( conf - 0.75 ) < 0.01

    def test_sender_boost_capped_at_0_98( self ):
        """High base confidence + sender boost should cap at 0.98."""
        classifier = self._make_classifier()
        # Many testing keywords → base 0.95, + sender boost → capped at 0.98
        question = "test tests testing pytest unittest coverage smoke test regression"
        _, conf = classifier.classify( question, sender_id="swe.tester@lupin.deepily.ai" )
        assert abs( conf - 0.98 ) < 0.01

    def test_no_match_no_hint_returns_general_0_3( self ):
        """No keyword match and no hint should return ('general', 0.3)."""
        classifier = self._make_classifier()
        cat, conf = classifier.classify( "What color is the sky?" )
        assert cat == "general"
        assert abs( conf - 0.3 ) < 0.01

    def test_no_match_with_hint_returns_hint_0_45( self ):
        """No keyword match but with sender hint should return (hint, 0.45)."""
        classifier = self._make_classifier()
        cat, conf = classifier.classify(
            "What should I do next?",
            sender_id="swe.tester@lupin.deepily.ai"
        )
        assert cat == "testing"
        assert abs( conf - 0.45 ) < 0.01


# ============================================================================
# TestStrategyEvaluateWithTrust — Evaluate with real trust buildup
# ============================================================================

class TestStrategyEvaluateWithTrust:
    """Tests for EngineeringStrategy.evaluate() with real trust buildup."""

    def _make_strategy( self, trust_mode="active", **kwargs ):
        from cosa.agents.swe_team.proxy.engineering_strategy import EngineeringStrategy
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker

        tracker = TrustTracker(
            l2_threshold=3, l3_threshold=10, l4_threshold=20, l5_threshold=40,
            **kwargs
        )
        return EngineeringStrategy( trust_tracker=tracker, trust_mode=trust_mode )

    def test_evaluate_uses_tracker_level_not_default( self ):
        """After building to L3, evaluate should reflect trust_level >= 3."""
        strategy = self._make_strategy( trust_mode="active" )
        now = time.time()
        # Build testing to L3 (l3_threshold=10)
        for i in range( 11 ):
            strategy.trust_tracker.record_decision( "testing", success=True, timestamp=now - i )
        assert strategy.trust_tracker.get_level( "testing" ) == 3

        result = strategy.evaluate( "Should I run the full test suite?" )
        assert result.category == "testing"
        assert result.trust_level >= 3

    def test_evaluate_act_mode_produces_value( self ):
        """In active mode at L3, action should be 'act' with a decision value."""
        strategy = self._make_strategy( trust_mode="active" )
        now = time.time()
        for i in range( 11 ):
            strategy.trust_tracker.record_decision( "testing", success=True, timestamp=now - i )

        result = strategy.evaluate( "Should I run the full test suite?" )
        assert result.action == "act"
        assert result.value == "approved"

    def test_evaluate_shadow_mode_no_value( self ):
        """In shadow mode, value should be None even at high trust."""
        strategy = self._make_strategy( trust_mode="shadow" )
        now = time.time()
        for i in range( 11 ):
            strategy.trust_tracker.record_decision( "testing", success=True, timestamp=now - i )

        result = strategy.evaluate( "Should I run the full test suite?" )
        assert result.action == "shadow"
        assert result.value is None

    def test_evaluate_records_confidence_in_breaker( self ):
        """After evaluate(), circuit breaker should have a confidence entry."""
        strategy = self._make_strategy( trust_mode="active" )
        result = strategy.evaluate( "Should I deploy to production?" )

        window = strategy.circuit_breaker._confidence_window.get( result.category, [] )
        assert len( window ) >= 1
        assert 0.0 <= window[ -1 ] <= 1.0


# ============================================================================
# TestStrategyCustomConstruction — Custom parameters
# ============================================================================

class TestStrategyCustomConstruction:
    """Tests for EngineeringStrategy construction with custom components."""

    def test_custom_trust_tracker_used( self ):
        """Passing an external trust tracker should use it instead of creating one."""
        from cosa.agents.swe_team.proxy.engineering_strategy import EngineeringStrategy
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker

        custom_tracker = TrustTracker( l2_threshold=100 )
        strategy = EngineeringStrategy( trust_tracker=custom_tracker )
        assert strategy.trust_tracker is custom_tracker

    def test_custom_circuit_breaker_used( self ):
        """Passing an external circuit breaker should use it instead of creating one."""
        from cosa.agents.swe_team.proxy.engineering_strategy import EngineeringStrategy
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker
        from cosa.agents.decision_proxy.circuit_breaker import CircuitBreaker

        tracker = TrustTracker()
        custom_breaker = CircuitBreaker( trust_tracker=tracker, error_rate_threshold=0.5 )
        strategy = EngineeringStrategy( trust_tracker=tracker, circuit_breaker=custom_breaker )
        assert strategy.circuit_breaker is custom_breaker
        assert strategy.circuit_breaker.error_rate_threshold == 0.5

    def test_custom_accepted_senders( self ):
        """Custom accepted_senders should change can_handle routing."""
        from cosa.agents.swe_team.proxy.engineering_strategy import EngineeringStrategy

        custom_senders = [ "custom.agent@lupin.deepily.ai" ]
        strategy = EngineeringStrategy( accepted_senders=custom_senders )

        assert strategy.can_handle( { "sender_id": "custom.agent@lupin.deepily.ai" } ) is True
        assert strategy.can_handle( { "sender_id": "swe.lead@lupin.deepily.ai" } ) is False


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
