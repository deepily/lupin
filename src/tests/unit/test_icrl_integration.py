#!/usr/bin/env python3
"""
Unit tests for ICRL integration in EngineeringStrategy.decide().

Tests ICRL fallback logic using realistic CBRPrediction scenarios:
  - Unanimous vs mixed verdicts
  - High vs low CBR confidence
  - LLM response parsing (approved, requires_review, garbage, errors)
  - Graceful degradation on LLM failures
"""

from unittest.mock import MagicMock
import pytest

from cosa.agents.decision_proxy.trust_tracker import TrustTracker
from cosa.agents.decision_proxy.circuit_breaker import CircuitBreaker
from cosa.agents.decision_proxy.cbr_decision_store import CBRPrediction
from cosa.agents.swe_team.proxy.engineering_strategy import EngineeringStrategy


def _make_strategy( icrl_enabled=True, icrl_top_k=5, llm_client=None, cbr_confidence_threshold=0.60 ):
    """Create an EngineeringStrategy with ICRL configuration."""
    tracker = TrustTracker( trust_model="beta", debug=False )
    cb      = CircuitBreaker(
        trust_tracker        = tracker,
        error_rate_threshold = 1.0,
        debug                = False,
    )
    return EngineeringStrategy(
        trust_tracker            = tracker,
        circuit_breaker          = cb,
        trust_mode               = "active",
        icrl_enabled             = icrl_enabled,
        icrl_top_k               = icrl_top_k,
        llm_client               = llm_client,
        cbr_confidence_threshold = cbr_confidence_threshold,
        debug                    = False,
    )


def _make_cbr_prediction( cases, verdict="approved", confidence=0.40 ):
    """Build a CBRPrediction from case list."""
    return CBRPrediction(
        verdict       = verdict,
        confidence    = confidence,
        similar_cases = cases,
        case_count    = len( cases ),
    )


# Realistic case data matching CBRPrediction.similar_cases schema
APPROVE_CASE = {
    "question"           : "Should we run the test suite before deploying?",
    "decision_value"     : "approved",
    "ratification_state" : "ratified",
    "created_at"         : "2026-02-20T10:00:00+00:00",
    "category"           : "testing",
}

REJECT_CASE = {
    "question"           : "Should we skip code review for hotfix?",
    "decision_value"     : "requires_review",
    "ratification_state" : "pending",
    "created_at"         : "2026-02-21T14:30:00+00:00",
    "category"           : "deployment",
}


class TestHasMixedVerdicts:
    """Tests for _has_mixed_verdicts()."""

    def test_unanimous_approve( self ):
        """5 cases all 'approved' → False."""
        cases = [ { **APPROVE_CASE } for _ in range( 5 ) ]
        pred  = _make_cbr_prediction( cases )

        strategy = _make_strategy()
        assert strategy._has_mixed_verdicts( pred ) is False

    def test_unanimous_reject( self ):
        """5 cases all 'requires_review' → False."""
        cases = [ { **REJECT_CASE } for _ in range( 5 ) ]
        pred  = _make_cbr_prediction( cases )

        strategy = _make_strategy()
        assert strategy._has_mixed_verdicts( pred ) is False

    def test_mixed( self ):
        """3 approve + 2 reject → True."""
        cases = [ { **APPROVE_CASE } for _ in range( 3 ) ] + [ { **REJECT_CASE } for _ in range( 2 ) ]
        pred  = _make_cbr_prediction( cases )

        strategy = _make_strategy()
        assert strategy._has_mixed_verdicts( pred ) is True

    def test_empty( self ):
        """No cases → False."""
        pred = _make_cbr_prediction( [], verdict=None, confidence=0.0 )

        strategy = _make_strategy()
        assert strategy._has_mixed_verdicts( pred ) is False


class TestICRLDecide:
    """Tests for ICRL integration in decide()."""

    def test_icrl_not_triggered_high_confidence( self ):
        """CBR confidence 0.85 (above threshold) → ICRL skipped."""
        mock_llm = MagicMock()
        strategy = _make_strategy( icrl_enabled=True, llm_client=mock_llm, cbr_confidence_threshold=0.60 )

        cases = [ { **APPROVE_CASE } for _ in range( 3 ) ] + [ { **REJECT_CASE } for _ in range( 2 ) ]
        pred  = _make_cbr_prediction( cases, confidence=0.85 )

        # Monkey-patch CBR to return our prediction
        strategy._get_cbr_prediction = MagicMock( return_value=pred )

        result = strategy.decide( "Should we deploy?", "testing" )

        # LLM should NOT be called — confidence above threshold
        mock_llm.run.assert_not_called()
        assert result == "approved"  # Heuristic for "testing"

    def test_icrl_not_triggered_unanimous( self ):
        """Unanimous verdicts → ICRL skipped even with low confidence."""
        mock_llm = MagicMock()
        strategy = _make_strategy( icrl_enabled=True, llm_client=mock_llm )

        cases = [ { **APPROVE_CASE } for _ in range( 5 ) ]
        pred  = _make_cbr_prediction( cases, confidence=0.30 )

        strategy._get_cbr_prediction = MagicMock( return_value=pred )

        result = strategy.decide( "Run tests?", "testing" )

        mock_llm.run.assert_not_called()
        assert result == "approved"

    def test_icrl_triggered_returns_approved( self ):
        """Mock LLM returns 'approved' → strategy returns 'approved'."""
        mock_llm = MagicMock()
        mock_llm.run.return_value = "approved"

        strategy = _make_strategy( icrl_enabled=True, llm_client=mock_llm )

        cases = [ { **APPROVE_CASE } for _ in range( 3 ) ] + [ { **REJECT_CASE } for _ in range( 2 ) ]
        pred  = _make_cbr_prediction( cases, confidence=0.40 )

        strategy._get_cbr_prediction = MagicMock( return_value=pred )

        result = strategy.decide( "Should we deploy?", "deployment" )

        mock_llm.run.assert_called_once()
        assert result == "approved"

    def test_icrl_triggered_returns_requires_review( self ):
        """Mock LLM returns 'requires_review' → strategy returns 'requires_review'."""
        mock_llm = MagicMock()
        mock_llm.run.return_value = "requires_review"

        strategy = _make_strategy( icrl_enabled=True, llm_client=mock_llm )

        cases = [ { **APPROVE_CASE } for _ in range( 2 ) ] + [ { **REJECT_CASE } for _ in range( 3 ) ]
        pred  = _make_cbr_prediction( cases, confidence=0.35 )

        strategy._get_cbr_prediction = MagicMock( return_value=pred )

        result = strategy.decide( "Run tests?", "testing" )

        mock_llm.run.assert_called_once()
        assert result == "requires_review"

    def test_icrl_graceful_degradation_on_error( self ):
        """Mock LLM raises Exception → returns None, falls through to heuristic."""
        mock_llm = MagicMock()
        mock_llm.run.side_effect = RuntimeError( "API connection failed" )

        strategy = _make_strategy( icrl_enabled=True, llm_client=mock_llm )

        cases = [ { **APPROVE_CASE } for _ in range( 3 ) ] + [ { **REJECT_CASE } for _ in range( 2 ) ]
        pred  = _make_cbr_prediction( cases, confidence=0.40 )

        strategy._get_cbr_prediction = MagicMock( return_value=pred )

        # Should fall through to heuristic ("approved" for "testing")
        result = strategy.decide( "Run tests?", "testing" )

        mock_llm.run.assert_called_once()
        assert result == "approved"

    def test_icrl_graceful_degradation_on_garbage( self ):
        """Mock LLM returns 'maybe' → returns None, falls through to heuristic."""
        mock_llm = MagicMock()
        mock_llm.run.return_value = "maybe I should think about this more"

        strategy = _make_strategy( icrl_enabled=True, llm_client=mock_llm )

        cases = [ { **APPROVE_CASE } for _ in range( 3 ) ] + [ { **REJECT_CASE } for _ in range( 2 ) ]
        pred  = _make_cbr_prediction( cases, confidence=0.40 )

        strategy._get_cbr_prediction = MagicMock( return_value=pred )

        # Should fall through to heuristic ("requires_review" for "deployment")
        result = strategy.decide( "Deploy to production?", "deployment" )

        mock_llm.run.assert_called_once()
        assert result == "requires_review"
