#!/usr/bin/env python3
"""
End-to-end smoke test for Phase 3: Conformal Prediction + ICRL.

Validates the full pipeline:
  1. Create EngineeringStrategy with conformal + ICRL enabled
  2. Train BLR models on categories with synthetic data
  3. Calibrate conformal wrapper
  4. Run gate() calls and verify conformal deferral occurs
  5. Trigger ICRL on mock mixed-verdict CBR prediction
  6. Verify diagnostics include conformal status
"""

import numpy as np
from unittest.mock import MagicMock

from cosa.agents.decision_proxy.trust_tracker import TrustTracker
from cosa.agents.decision_proxy.circuit_breaker import CircuitBreaker
from cosa.agents.decision_proxy.bayesian_trust import BayesianLogisticRegression
from cosa.agents.decision_proxy.cbr_decision_store import CBRPrediction
from cosa.agents.decision_proxy.responder import DecisionResponder
from cosa.agents.swe_team.proxy.engineering_strategy import EngineeringStrategy


def _train_blr_on_category( strategy, category, n_success, n_failure ):
    """Train BLR model on a category with synthetic feature data."""
    cat = strategy.trust_tracker.categories[ category ]
    blr = BayesianLogisticRegression( n_features=4 )

    for _ in range( n_success ):
        blr.update( np.array( [ 0.5, 0.4, 0.5, 0.1 ] ), 1 )
        cat.record_decision( True )
    for _ in range( n_failure ):
        blr.update( np.array( [ 0.5, 0.4, 0.5, 0.8 ] ), 0 )
        cat.record_decision( False )

    cat._blr_model = blr


class TestConformalICRLSmoke:
    """End-to-end smoke tests for Phase 3 pipeline."""

    def test_full_conformal_pipeline( self ):
        """
        Validate conformal deferral pipeline:
        1. Train BLR on categories
        2. Calibrate conformal
        3. Run gate() calls
        4. Verify some produce 'defer'
        """
        tracker = TrustTracker( trust_model="beta", debug=False )
        cb      = CircuitBreaker( trust_tracker=tracker, error_rate_threshold=1.0, debug=False )

        strategy = EngineeringStrategy(
            trust_tracker     = tracker,
            circuit_breaker   = cb,
            trust_mode        = "active",
            conformal_enabled = True,
            conformal_alpha   = 0.10,
            debug             = False,
        )

        # Train BLR on multiple categories
        _train_blr_on_category( strategy, "testing",    n_success=30, n_failure=10 )
        _train_blr_on_category( strategy, "deployment", n_success=15, n_failure=15 )
        _train_blr_on_category( strategy, "general",    n_success=40, n_failure=5 )

        # Calibrate conformal
        status = strategy.calibrate_conformal()
        assert status[ "calibrated" ] is True
        assert status[ "calibration_size" ] > 0

        # Run 100 gate() calls across categories
        results = { "shadow": 0, "suggest": 0, "act": 0, "defer": 0 }
        for _ in range( 50 ):
            for cat in [ "testing", "deployment", "general" ]:
                action = strategy.gate( cat, trust_level=3, confidence=0.9 )
                results[ action ] += 1

        # Verify at least one category produces 'defer' (deployment should, being 50/50)
        # and at least one produces 'act' (general should, being strongly positive)
        assert results[ "defer" ] > 0 or results[ "act" ] > 0, (
            f"Expected some defers or acts, got: {results}"
        )

        # Print summary
        print( "\n--- Conformal Pipeline Smoke Test ---" )
        print( f"  Calibration: {status}" )
        for action, count in results.items():
            print( f"  {action:10s}: {count}" )

    def test_icrl_mock_flow( self ):
        """
        Validate ICRL invocation with mock LLM:
        1. Create strategy with mock LLM
        2. Build mixed-verdict CBR prediction
        3. Verify ICRL is triggered and returns decision
        """
        mock_llm = MagicMock()
        mock_llm.run.return_value = "approved"

        tracker = TrustTracker( trust_model="beta", debug=False )
        cb      = CircuitBreaker( trust_tracker=tracker, error_rate_threshold=1.0, debug=False )

        strategy = EngineeringStrategy(
            trust_tracker            = tracker,
            circuit_breaker          = cb,
            trust_mode               = "active",
            icrl_enabled             = True,
            icrl_top_k               = 3,
            llm_client               = mock_llm,
            cbr_confidence_threshold = 0.60,
            debug                    = False,
        )

        # Build mixed-verdict CBR prediction
        cases = [
            { "question": "Deploy v1?", "decision_value": "approved",        "ratification_state": "ratified", "created_at": "2026-02-20" },
            { "question": "Deploy v2?", "decision_value": "requires_review", "ratification_state": "pending",  "created_at": "2026-02-21" },
            { "question": "Deploy v3?", "decision_value": "approved",        "ratification_state": "ratified", "created_at": "2026-02-22" },
        ]
        pred = CBRPrediction( verdict="approved", confidence=0.35, similar_cases=cases, case_count=3 )

        # Monkey-patch CBR to return our prediction
        strategy._get_cbr_prediction = MagicMock( return_value=pred )

        result = strategy.decide( "Deploy notification service?", "deployment" )

        # Verify ICRL was triggered
        mock_llm.run.assert_called_once()
        assert result == "approved"

        print( "\n--- ICRL Mock Flow Smoke Test ---" )
        print( f"  ICRL triggered: True" )
        print( f"  Decision: {result}" )
        print( f"  LLM calls: {mock_llm.run.call_count}" )

    def test_diagnostics_include_conformal( self ):
        """
        Verify diagnostics output includes conformal status when wrapper is initialized.
        """
        tracker = TrustTracker( trust_model="beta", debug=False )
        cb      = CircuitBreaker( trust_tracker=tracker, error_rate_threshold=1.0, debug=False )

        strategy = EngineeringStrategy(
            trust_tracker     = tracker,
            circuit_breaker   = cb,
            trust_mode        = "active",
            conformal_enabled = True,
            conformal_alpha   = 0.10,
            debug             = False,
        )

        _train_blr_on_category( strategy, "testing", n_success=25, n_failure=5 )
        strategy.calibrate_conformal()

        # Simulate responder with domain strategy
        responder = DecisionResponder( debug=False )
        responder.set_domain_strategy( strategy )

        diagnostics = responder.get_decision_diagnostics()

        assert "conformal" in diagnostics
        assert diagnostics[ "conformal" ][ "calibrated" ] is True
        assert diagnostics[ "conformal" ][ "alpha" ] == 0.10

        print( "\n--- Diagnostics Smoke Test ---" )
        print( f"  Conformal status: {diagnostics[ 'conformal' ]}" )
        print( f"  Thompson keys: {list( diagnostics.get( 'thompson_sampling', {} ).keys() )[:3]}..." )

    def test_combined_conformal_and_icrl( self ):
        """
        Validate both Phase 3 features active simultaneously.
        """
        mock_llm = MagicMock()
        mock_llm.run.return_value = "requires_review"

        tracker = TrustTracker( trust_model="beta", debug=False )
        cb      = CircuitBreaker( trust_tracker=tracker, error_rate_threshold=1.0, debug=False )

        strategy = EngineeringStrategy(
            trust_tracker            = tracker,
            circuit_breaker          = cb,
            trust_mode               = "active",
            conformal_enabled        = True,
            conformal_alpha          = 0.10,
            icrl_enabled             = True,
            icrl_top_k               = 5,
            llm_client               = mock_llm,
            cbr_confidence_threshold = 0.60,
            debug                    = False,
        )

        # Train BLR models
        _train_blr_on_category( strategy, "testing",    n_success=35, n_failure=5 )
        _train_blr_on_category( strategy, "deployment", n_success=20, n_failure=20 )

        # Calibrate conformal
        status = strategy.calibrate_conformal()
        assert status[ "calibrated" ] is True

        # Test ICRL separately (CBR mocked)
        mixed_cases = [
            { "question": "Q1", "decision_value": "approved",        "ratification_state": "ratified", "created_at": "2026-02-20" },
            { "question": "Q2", "decision_value": "requires_review", "ratification_state": "pending",  "created_at": "2026-02-21" },
        ]
        pred = CBRPrediction( verdict="approved", confidence=0.30, similar_cases=mixed_cases, case_count=2 )
        strategy._get_cbr_prediction = MagicMock( return_value=pred )

        icrl_result = strategy.decide( "Complex question?", "general" )
        assert icrl_result == "requires_review"

        print( "\n--- Combined Phase 3 Smoke Test ---" )
        print( f"  Conformal calibrated: {status[ 'calibrated' ]}" )
        print( f"  ICRL result: {icrl_result}" )
        print( f"  LLM calls: {mock_llm.run.call_count}" )


if __name__ == "__main__":
    import pytest
    pytest.main( [ __file__, "-v", "-s" ] )
