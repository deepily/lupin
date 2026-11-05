#!/usr/bin/env python3
"""
Unit tests for Thompson Sampling gate in EngineeringStrategy.

Tests Thompson Sampling integration with the engineering decision proxy:
  - Backward compatibility (TS disabled)
  - Shadow mode and circuit breaker overrides
  - High/low/uncertain Beta posterior routing
  - Diagnostics structure and probability consistency
"""

import pytest

from cosa.agents.decision_proxy.trust_tracker import TrustTracker
from cosa.agents.decision_proxy.circuit_breaker import CircuitBreaker
from cosa.agents.swe_team.proxy.engineering_strategy import EngineeringStrategy


def _make_strategy( thompson_enabled=True, trust_mode="active", cb_error_rate=0.15, **kwargs ):
    """
    Create an EngineeringStrategy with Thompson Sampling configuration.

    Ensures:
        - Returns a strategy with all 6 engineering categories registered
        - Beta trust model for consistent TS behavior

    Args:
        cb_error_rate: Circuit breaker error rate threshold (default 0.15;
            set to 1.0 to effectively disable CB for negative-outcome tests)
    """
    tracker = TrustTracker( trust_model="beta", debug=False )
    cb      = CircuitBreaker(
        trust_tracker        = tracker,
        error_rate_threshold = cb_error_rate,
        debug                = False,
    )
    return EngineeringStrategy(
        trust_tracker              = tracker,
        circuit_breaker            = cb,
        trust_mode                 = trust_mode,
        thompson_enabled           = thompson_enabled,
        thompson_act_threshold     = kwargs.get( "thompson_act_threshold", 0.90 ),
        thompson_suggest_threshold = kwargs.get( "thompson_suggest_threshold", 0.70 ),
        audit_random               = kwargs.get( "audit_random" ),
        debug                      = False,
    )


class TestThompsonSamplingGate:
    """Tests for Thompson Sampling gate routing."""

    def test_ts_disabled_uses_fixed_gate( self ):
        """When TS is disabled, gate() uses fixed trust-level thresholds."""
        strategy = _make_strategy( thompson_enabled=False, trust_mode="active" )

        # With no observations, trust_level=1 → shadow
        action = strategy.gate( "testing", trust_level=1, confidence=0.9 )
        assert action == "shadow"

        # L2 → suggest
        action = strategy.gate( "testing", trust_level=2, confidence=0.9 )
        assert action == "suggest"

        # L3 → act
        action = strategy.gate( "testing", trust_level=3, confidence=0.9 )
        assert action == "act"

    def test_ts_shadow_mode_overrides( self ):
        """Shadow mode always returns 'shadow' even with TS enabled."""
        strategy = _make_strategy( thompson_enabled=True, trust_mode="shadow" )

        # Pump 50 successes to make Beta posterior very favorable
        cat = strategy.trust_tracker.categories[ "testing" ]
        for _ in range( 50 ):
            cat.record_decision( True )

        action = strategy.gate( "testing", trust_level=3, confidence=0.9 )
        assert action == "shadow"

    def test_ts_circuit_breaker_overrides( self ):
        """Circuit breaker tripped returns 'defer' even with TS enabled."""
        strategy = _make_strategy( thompson_enabled=True, trust_mode="active" )

        # Trip the circuit breaker by recording low confidence
        for _ in range( 20 ):
            strategy.circuit_breaker.record_confidence( "testing", 0.05 )

        action = strategy.gate( "testing", trust_level=3, confidence=0.05 )
        assert action == "defer"

    def test_ts_high_success_mostly_acts( self ):
        """With alpha=50, beta=3 the sampled rate should produce 'act' frequently."""
        strategy = _make_strategy( thompson_enabled=True, trust_mode="active" )

        cat = strategy.trust_tracker.categories[ "testing" ]
        for _ in range( 49 ):
            cat.record_decision( True )
        for _ in range( 2 ):
            cat.record_decision( False )

        # alpha=50, beta=3 → mean ≈ 0.94
        actions = [ strategy.gate( "testing", trust_level=3, confidence=0.9 ) for _ in range( 200 ) ]
        act_count = actions.count( "act" )

        # Should act > 70% of the time with this posterior
        assert act_count > 140, f"Expected >140 acts, got {act_count}"

    def test_ts_low_success_mostly_shadows( self ):
        """With alpha=3, beta=50 the sampled rate should produce 'shadow' frequently."""
        # Disable CB error-rate check (1.0) so high rejection rate doesn't trip it
        strategy = _make_strategy( thompson_enabled=True, trust_mode="active", cb_error_rate=1.0 )

        cat = strategy.trust_tracker.categories[ "testing" ]
        for _ in range( 2 ):
            cat.record_decision( True )
        for _ in range( 49 ):
            cat.record_decision( False )

        # alpha=3, beta=50 → mean ≈ 0.06
        actions = [ strategy.gate( "testing", trust_level=3, confidence=0.9 ) for _ in range( 200 ) ]
        shadow_count = actions.count( "shadow" )

        # Should shadow > 70% of the time
        assert shadow_count > 140, f"Expected >140 shadows, got {shadow_count}"

    def test_ts_uncertain_explores( self ):
        """With alpha=5, beta=5 (uncertain), all 3 actions should appear."""
        strategy = _make_strategy(
            thompson_enabled=True,
            trust_mode="active",
            thompson_act_threshold=0.80,
            thompson_suggest_threshold=0.40,
        )

        cat = strategy.trust_tracker.categories[ "testing" ]
        for _ in range( 4 ):
            cat.record_decision( True )
        for _ in range( 4 ):
            cat.record_decision( False )

        # alpha=5, beta=5 → mean=0.5, high variance
        actions = [ strategy.gate( "testing", trust_level=3, confidence=0.9 ) for _ in range( 500 ) ]

        assert "act" in actions, "Expected at least one 'act' with uncertain posterior"
        assert "suggest" in actions, "Expected at least one 'suggest' with uncertain posterior"
        assert "shadow" in actions, "Expected at least one 'shadow' with uncertain posterior"

    def test_ts_diagnostics_structure( self ):
        """Diagnostics returns valid dict with all 6 categories."""
        strategy = _make_strategy( thompson_enabled=True, trust_mode="active" )

        diagnostics = strategy.get_thompson_diagnostics()

        assert len( diagnostics ) == 6
        expected_categories = { "deployment", "testing", "deps", "architecture", "destructive", "general" }
        assert set( diagnostics.keys() ) == expected_categories

        for cat_name, diag in diagnostics.items():
            assert "alpha" in diag
            assert "beta" in diag
            assert "mean_rate" in diag
            assert "observations" in diag
            assert "p_act" in diag
            assert "p_suggest" in diag
            assert "p_shadow" in diag

    def test_ts_diagnostics_probabilities_sum( self ):
        """Diagnostic probabilities p_act + p_suggest + p_shadow ≈ 1.0."""
        strategy = _make_strategy( thompson_enabled=True, trust_mode="active" )

        # Add some observations to make it interesting
        cat = strategy.trust_tracker.categories[ "testing" ]
        for _ in range( 30 ):
            cat.record_decision( True )
        for _ in range( 5 ):
            cat.record_decision( False )

        diagnostics = strategy.get_thompson_diagnostics()

        for cat_name, diag in diagnostics.items():
            total = diag[ "p_act" ] + diag[ "p_suggest" ] + diag[ "p_shadow" ]
            assert abs( total - 1.0 ) < 0.01, (
                f"{cat_name}: p_act={diag[ 'p_act' ]}, p_suggest={diag[ 'p_suggest' ]}, "
                f"p_shadow={diag[ 'p_shadow' ]}, sum={total}"
            )


class TestThompsonRespectsLevelAndMode:
    """The sampled action may lower the level-and-mode action, never raise it."""

    @staticmethod
    def _always( strategy, action ):
        """Force the Thompson draw to a fixed action."""
        strategy._gate_thompson = lambda category: action

    def test_ts_act_cannot_raise_level_1_shadow( self ):
        strategy = _make_strategy( thompson_enabled=True, trust_mode="active" )
        self._always( strategy, "act" )
        assert strategy.gate( "testing", trust_level=1, confidence=0.99 ) == "shadow"

    def test_ts_act_cannot_raise_level_2_suggest( self ):
        strategy = _make_strategy( thompson_enabled=True, trust_mode="active" )
        self._always( strategy, "act" )
        assert strategy.gate( "testing", trust_level=2, confidence=0.99 ) == "suggest"

    def test_ts_act_cannot_exceed_suggest_mode( self ):
        strategy = _make_strategy( thompson_enabled=True, trust_mode="suggest" )
        self._always( strategy, "act" )
        assert strategy.gate( "testing", trust_level=5, confidence=0.99 ) == "suggest"

    def test_ts_act_cannot_raise_low_confidence_level_3( self ):
        strategy = _make_strategy( thompson_enabled=True, trust_mode="active" )
        self._always( strategy, "act" )
        assert strategy.gate( "testing", trust_level=3, confidence=0.0 ) == "suggest"

    def test_ts_can_still_lower_level_5_act( self ):
        strategy = _make_strategy( thompson_enabled=True, trust_mode="active" )
        self._always( strategy, "shadow" )
        assert strategy.gate( "testing", trust_level=5, confidence=0.99 ) == "shadow"

    def test_ts_agreeing_with_graded_action_keeps_it( self ):
        strategy = _make_strategy( thompson_enabled=True, trust_mode="active" )
        self._always( strategy, "act" )
        assert strategy.gate( "testing", trust_level=5, confidence=0.99 ) == "act"


class TestGradedActionLevelFour:
    """The level-and-mode action that the sampled action is compared against."""

    def test_level_4_destructive_suggests( self ):
        """Destructive category at level 4 asks the human."""
        strategy = _make_strategy( thompson_enabled=False, trust_mode="active" )
        assert strategy.gate( "destructive", trust_level=4, confidence=0.99 ) == "suggest"

    def test_level_4_low_confidence_suggests( self ):
        """Level 4 below the minimum confidence asks the human."""
        strategy = _make_strategy( thompson_enabled=False, trust_mode="active" )
        assert strategy.gate( "testing", trust_level=4, confidence=0.1 ) == "suggest"

    def test_level_4_audit_draw_suggests( self ):
        """A draw under the audit rate sends a level 4 act to the human."""
        strategy = _make_strategy( thompson_enabled=False, trust_mode="active", audit_random=lambda: 0.0 )
        assert strategy.gate( "testing", trust_level=4, confidence=0.99 ) == "suggest"

    def test_level_4_acts_without_audit_draw( self ):
        """A draw at or above the audit rate lets level 4 act."""
        strategy = _make_strategy( thompson_enabled=False, trust_mode="active", audit_random=lambda: 0.99 )
        assert strategy.gate( "testing", trust_level=4, confidence=0.99 ) == "act"


class TestThompsonGateEdges:
    """Edges of the Thompson draw itself."""

    def test_unknown_category_samples_shadow( self ):
        """A category the tracker does not know samples to shadow."""
        strategy = _make_strategy( thompson_enabled=True, trust_mode="active" )
        assert strategy._gate_thompson( "no-such-category" ) == "shadow"

    def test_debug_prints_the_draw( self, capsys ):
        """Debug mode prints the Beta parameters and the sample."""
        strategy       = _make_strategy( thompson_enabled=True, trust_mode="active" )
        strategy.debug = True
        strategy._gate_thompson( "testing" )
        assert "TS draw: testing alpha=1, beta=1" in capsys.readouterr().out
