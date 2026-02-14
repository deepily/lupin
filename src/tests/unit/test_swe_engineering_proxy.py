#!/usr/bin/env python3
"""
Unit tests for the SWE Engineering Proxy (Phase 4e).

Tests for:
    - Engineering categories (definitions, keyword sets, cap levels)
    - Engineering classifier (sender hints, keyword analysis, fallback)
    - Engineering strategy (classify → gate → decide, trust modes, circuit breaker)
    - Package exports

All tests are self-contained — no live database or WebSocket required.
"""

import pytest
from unittest.mock import MagicMock, patch


# ===========================================================================
# Engineering Categories Tests
# ===========================================================================

class TestEngineeringCategories:
    """Tests for engineering category definitions."""

    def test_six_categories_defined( self ):
        """Exactly 6 engineering categories are defined."""
        from cosa.agents.swe_team.proxy.engineering_categories import ENGINEERING_CATEGORIES
        assert len( ENGINEERING_CATEGORIES ) == 6

    def test_required_categories_exist( self ):
        """All 6 required categories exist."""
        from cosa.agents.swe_team.proxy.engineering_categories import ENGINEERING_CATEGORIES
        expected = [ "deployment", "testing", "deps", "architecture", "destructive", "general" ]
        for cat in expected:
            assert cat in ENGINEERING_CATEGORIES, f"Missing category: {cat}"

    def test_each_category_has_keywords( self ):
        """Each category has a keywords list."""
        from cosa.agents.swe_team.proxy.engineering_categories import ENGINEERING_CATEGORIES
        for name, cat in ENGINEERING_CATEGORIES.items():
            assert "keywords" in cat, f"Category '{name}' missing keywords"
            assert isinstance( cat[ "keywords" ], list )

    def test_each_category_has_cap_level( self ):
        """Each category has a cap_level."""
        from cosa.agents.swe_team.proxy.engineering_categories import ENGINEERING_CATEGORIES
        for name, cat in ENGINEERING_CATEGORIES.items():
            assert "cap_level" in cat, f"Category '{name}' missing cap_level"
            assert 1 <= cat[ "cap_level" ] <= 5

    def test_each_category_has_description( self ):
        """Each category has a description."""
        from cosa.agents.swe_team.proxy.engineering_categories import ENGINEERING_CATEGORIES
        for name, cat in ENGINEERING_CATEGORIES.items():
            assert "description" in cat, f"Category '{name}' missing description"
            assert len( cat[ "description" ] ) > 0

    def test_deployment_capped_at_l3( self ):
        """Deployment category is capped at L3."""
        from cosa.agents.swe_team.proxy.engineering_categories import get_category_cap_level
        assert get_category_cap_level( "deployment" ) == 3

    def test_destructive_capped_at_l3( self ):
        """Destructive category is capped at L3."""
        from cosa.agents.swe_team.proxy.engineering_categories import get_category_cap_level
        assert get_category_cap_level( "destructive" ) == 3

    def test_architecture_capped_at_l3( self ):
        """Architecture category is capped at L3."""
        from cosa.agents.swe_team.proxy.engineering_categories import get_category_cap_level
        assert get_category_cap_level( "architecture" ) == 3

    def test_testing_capped_at_l5( self ):
        """Testing category can reach L5."""
        from cosa.agents.swe_team.proxy.engineering_categories import get_category_cap_level
        assert get_category_cap_level( "testing" ) == 5

    def test_general_is_catch_all( self ):
        """General category has no keywords (catch-all)."""
        from cosa.agents.swe_team.proxy.engineering_categories import ENGINEERING_CATEGORIES
        assert ENGINEERING_CATEGORIES[ "general" ][ "keywords" ] == []

    def test_get_category_names_returns_all( self ):
        """get_category_names returns all 6 category names."""
        from cosa.agents.swe_team.proxy.engineering_categories import get_category_names
        names = get_category_names()
        assert len( names ) == 6
        assert "deployment" in names
        assert "general" in names

    def test_get_category_cap_level_unknown_returns_5( self ):
        """get_category_cap_level returns 5 for unknown categories."""
        from cosa.agents.swe_team.proxy.engineering_categories import get_category_cap_level
        assert get_category_cap_level( "nonexistent" ) == 5


# ===========================================================================
# Engineering Classifier Tests
# ===========================================================================

class TestEngineeringClassifier:
    """Tests for the EngineeringClassifier."""

    def _make_classifier( self ):
        from cosa.agents.swe_team.proxy.engineering_classifier import EngineeringClassifier
        return EngineeringClassifier( debug=False )

    def test_classify_deploy_question( self ):
        """Deploy keyword triggers deployment category."""
        classifier = self._make_classifier()
        cat, conf = classifier.classify( "Should I deploy this to production?" )
        assert cat == "deployment"
        assert conf >= 0.5

    def test_classify_test_question( self ):
        """Test keyword triggers testing category."""
        classifier = self._make_classifier()
        cat, conf = classifier.classify( "Should I run the full test suite?" )
        assert cat == "testing"
        assert conf >= 0.5

    def test_classify_delete_question( self ):
        """Delete keyword triggers destructive category."""
        classifier = self._make_classifier()
        cat, conf = classifier.classify( "Can I delete the old backup files?" )
        assert cat == "destructive"
        assert conf >= 0.5

    def test_classify_deps_question( self ):
        """Dependency keyword triggers deps category."""
        classifier = self._make_classifier()
        cat, conf = classifier.classify( "Should I upgrade the package dependencies?" )
        assert cat == "deps"
        assert conf >= 0.5

    def test_classify_architecture_question( self ):
        """Architecture keyword triggers architecture category."""
        classifier = self._make_classifier()
        cat, conf = classifier.classify( "Should we refactor the database schema?" )
        assert cat == "architecture"
        assert conf >= 0.5

    def test_classify_general_fallback( self ):
        """Unrecognized question falls back to general."""
        classifier = self._make_classifier()
        cat, conf = classifier.classify( "What color should the button be?" )
        assert cat == "general"
        assert conf <= 0.5

    def test_sender_hint_tester( self ):
        """swe.tester sender hints to testing category."""
        classifier = self._make_classifier()
        cat, conf = classifier.classify(
            "What should we do next?",
            sender_id="swe.tester@lupin.deepily.ai"
        )
        assert cat == "testing"

    def test_sender_hint_no_override_keywords( self ):
        """Keyword match takes precedence over sender hint when stronger."""
        classifier = self._make_classifier()
        cat, conf = classifier.classify(
            "Should I deploy to production?",
            sender_id="swe.tester@lupin.deepily.ai"
        )
        assert cat == "deployment"

    def test_multiple_keyword_matches_boost_confidence( self ):
        """Multiple keyword matches boost confidence."""
        classifier = self._make_classifier()
        _, single_conf = classifier.classify( "Run test" )
        _, multi_conf = classifier.classify( "Run the test suite with pytest and check coverage" )
        assert multi_conf >= single_conf

    def test_get_categories_returns_dict( self ):
        """get_categories returns the full category definitions dict."""
        classifier = self._make_classifier()
        cats = classifier.get_categories()
        assert isinstance( cats, dict )
        assert len( cats ) == 6

    def test_confidence_is_bounded( self ):
        """Confidence is always between 0.0 and 1.0."""
        classifier = self._make_classifier()
        for question in [
            "deploy deploy deploy deploy deploy deploy deploy deploy",
            "hello world",
            "",
        ]:
            if not question:
                continue
            _, conf = classifier.classify( question )
            assert 0.0 <= conf <= 1.0


# ===========================================================================
# Engineering Strategy Tests
# ===========================================================================

class TestEngineeringStrategy:
    """Tests for the EngineeringStrategy pipeline."""

    def _make_strategy( self, trust_mode="shadow", debug=False ):
        from cosa.agents.swe_team.proxy.engineering_strategy import EngineeringStrategy
        return EngineeringStrategy( trust_mode=trust_mode, debug=debug )

    def test_name_is_swe_engineering( self ):
        """Strategy name is 'swe_engineering'."""
        strategy = self._make_strategy()
        assert strategy.name == "swe_engineering"

    def test_available_is_true( self ):
        """Strategy is always available."""
        strategy = self._make_strategy()
        assert strategy.available is True

    def test_shadow_mode_always_shadows( self ):
        """In shadow mode, gate always returns 'shadow'."""
        strategy = self._make_strategy( trust_mode="shadow" )
        assert strategy.gate( "testing", 5, 0.99 ) == "shadow"
        assert strategy.gate( "deployment", 3, 0.80 ) == "shadow"

    def test_suggest_mode_at_l2( self ):
        """In suggest mode, L2+ returns 'suggest'."""
        strategy = self._make_strategy( trust_mode="suggest" )
        assert strategy.gate( "testing", 2, 0.80 ) == "suggest"
        assert strategy.gate( "testing", 3, 0.80 ) == "suggest"

    def test_suggest_mode_at_l1( self ):
        """In suggest mode, L1 returns 'shadow'."""
        strategy = self._make_strategy( trust_mode="suggest" )
        assert strategy.gate( "testing", 1, 0.80 ) == "shadow"

    def test_active_mode_l1_shadows( self ):
        """In active mode, L1 returns 'shadow'."""
        strategy = self._make_strategy( trust_mode="active" )
        assert strategy.gate( "testing", 1, 0.80 ) == "shadow"

    def test_active_mode_l2_suggests( self ):
        """In active mode, L2 returns 'suggest'."""
        strategy = self._make_strategy( trust_mode="active" )
        assert strategy.gate( "testing", 2, 0.80 ) == "suggest"

    def test_active_mode_l3_acts( self ):
        """In active mode, L3+ returns 'act'."""
        strategy = self._make_strategy( trust_mode="active" )
        assert strategy.gate( "testing", 3, 0.80 ) == "act"
        assert strategy.gate( "testing", 4, 0.80 ) == "act"

    def test_decide_high_risk_requires_review( self ):
        """High-risk categories return 'requires_review'."""
        strategy = self._make_strategy()
        assert strategy.decide( "Deploy?", "deployment" ) == "requires_review"
        assert strategy.decide( "Delete?", "destructive" ) == "requires_review"
        assert strategy.decide( "Refactor?", "architecture" ) == "requires_review"

    def test_decide_low_risk_approved( self ):
        """Low-risk categories return 'approved'."""
        strategy = self._make_strategy()
        assert strategy.decide( "Run tests?", "testing" ) == "approved"
        assert strategy.decide( "What next?", "general" ) == "approved"

    def test_evaluate_pipeline_shadow_mode( self ):
        """evaluate() runs full pipeline and returns DecisionResult in shadow mode."""
        from cosa.agents.decision_proxy.base_decision_strategy import DecisionResult
        strategy = self._make_strategy( trust_mode="shadow" )
        result = strategy.evaluate( "Should I run the full test suite?" )

        assert isinstance( result, DecisionResult )
        assert result.action == "shadow"
        assert result.category == "testing"
        assert result.value is None
        assert result.trust_level == 1
        assert result.confidence > 0

    def test_evaluate_pipeline_active_mode( self ):
        """evaluate() in active mode at L1 still shadows (no trust earned)."""
        strategy = self._make_strategy( trust_mode="active" )
        result = strategy.evaluate( "Deploy to production?" )

        assert result.action == "shadow"  # L1 → shadow
        assert result.category == "deployment"

    def test_can_handle_accepted_sender( self ):
        """can_handle returns True for accepted SWE senders."""
        strategy = self._make_strategy()
        assert strategy.can_handle( { "sender_id": "swe.lead@lupin.deepily.ai" } ) is True
        assert strategy.can_handle( { "sender_id": "swe.coder@lupin.deepily.ai" } ) is True
        assert strategy.can_handle( { "sender_id": "swe.tester@lupin.deepily.ai" } ) is True

    def test_can_handle_rejected_sender( self ):
        """can_handle returns False for non-SWE senders."""
        strategy = self._make_strategy()
        assert strategy.can_handle( { "sender_id": "devops.agent@lupin.deepily.ai" } ) is False

    def test_can_handle_no_sender( self ):
        """can_handle returns True when no sender_id (generic routing)."""
        strategy = self._make_strategy()
        assert strategy.can_handle( {} ) is True
        assert strategy.can_handle( { "sender_id": "" } ) is True

    def test_categories_registered_with_tracker( self ):
        """All 6 categories are registered with the trust tracker."""
        strategy = self._make_strategy()
        registered = list( strategy.trust_tracker.categories.keys() )
        assert len( registered ) == 6
        assert "deployment" in registered
        assert "testing" in registered
        assert "general" in registered

    def test_circuit_breaker_tripped_defers( self ):
        """Tripped circuit breaker returns 'defer' from gate."""
        strategy = self._make_strategy( trust_mode="active" )
        # Trip the circuit breaker for testing category
        strategy.circuit_breaker.trip( "testing", "test trip" )
        assert strategy.gate( "testing", 3, 0.80 ) == "defer"


# ===========================================================================
# SWE Proxy Config Tests
# ===========================================================================

class TestSweProxyConfig:
    """Tests for SWE proxy configuration."""

    def test_accepted_senders_list( self ):
        """Default accepted senders contains 3 SWE team senders."""
        from cosa.agents.swe_team.proxy.config import DEFAULT_ACCEPTED_SENDERS
        assert len( DEFAULT_ACCEPTED_SENDERS ) == 3
        assert "swe.lead@lupin.deepily.ai" in DEFAULT_ACCEPTED_SENDERS
        assert "swe.coder@lupin.deepily.ai" in DEFAULT_ACCEPTED_SENDERS
        assert "swe.tester@lupin.deepily.ai" in DEFAULT_ACCEPTED_SENDERS

    def test_cap_levels_are_valid( self ):
        """All cap level defaults are between 1 and 5."""
        from cosa.agents.swe_team.proxy.config import (
            DEFAULT_DEPLOYMENT_CAP_LEVEL,
            DEFAULT_DESTRUCTIVE_CAP_LEVEL,
            DEFAULT_ARCHITECTURE_CAP_LEVEL,
        )
        for cap in [ DEFAULT_DEPLOYMENT_CAP_LEVEL, DEFAULT_DESTRUCTIVE_CAP_LEVEL, DEFAULT_ARCHITECTURE_CAP_LEVEL ]:
            assert 1 <= cap <= 5


# ===========================================================================
# Package Export Tests
# ===========================================================================

class TestSweProxyExports:
    """Tests for swe_team.proxy package exports."""

    def test_engineering_categories_export( self ):
        """ENGINEERING_CATEGORIES exported from package."""
        from cosa.agents.swe_team.proxy import ENGINEERING_CATEGORIES
        assert isinstance( ENGINEERING_CATEGORIES, dict )

    def test_engineering_classifier_export( self ):
        """EngineeringClassifier exported from package."""
        from cosa.agents.swe_team.proxy import EngineeringClassifier
        assert EngineeringClassifier is not None

    def test_engineering_strategy_export( self ):
        """EngineeringStrategy exported from package."""
        from cosa.agents.swe_team.proxy import EngineeringStrategy
        assert EngineeringStrategy is not None

    def test_config_exports( self ):
        """Config constants exported from package."""
        from cosa.agents.swe_team.proxy import (
            DEFAULT_ACCEPTED_SENDERS,
            DEFAULT_DEPLOYMENT_CAP_LEVEL,
            DEFAULT_DESTRUCTIVE_CAP_LEVEL,
            DEFAULT_ARCHITECTURE_CAP_LEVEL,
        )
        assert DEFAULT_ACCEPTED_SENDERS is not None
        assert DEFAULT_DEPLOYMENT_CAP_LEVEL == 3

    def test_helper_functions_export( self ):
        """Helper functions exported from package."""
        from cosa.agents.swe_team.proxy import get_category_names, get_category_cap_level
        assert callable( get_category_names )
        assert callable( get_category_cap_level )


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
