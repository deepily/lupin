#!/usr/bin/env python3
"""
Smoke test for Thompson Sampling + BLR end-to-end flow.

Validates the full pipeline:
  1. Create EngineeringStrategy with thompson_enabled=True
  2. Simulate 45 successes + 5 rejections in "testing" category
  3. Run 200 gate() calls, verify p_act > 0.5
  4. Call get_thompson_diagnostics(), verify structure
  5. Print summary table to console
"""

import os
import sys

# Bootstrap path for standalone execution
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root:
    src_path = os.path.join( lupin_root, "src" )
    if src_path not in sys.path:
        sys.path.insert( 0, src_path )

from cosa.agents.decision_proxy.trust_tracker import TrustTracker
from cosa.agents.decision_proxy.circuit_breaker import CircuitBreaker
from cosa.agents.decision_proxy.responder import DecisionResponder
from cosa.agents.swe_team.proxy.engineering_strategy import EngineeringStrategy


def test_thompson_sampling_smoke():
    """
    End-to-end smoke test for Thompson Sampling flow.

    Ensures:
        - EngineeringStrategy with TS produces sensible gate routing
        - High-success category (45/50) mostly produces "act"
        - Diagnostics structure is complete and probabilities sum to 1.0
        - DecisionResponder.get_decision_diagnostics() includes TS data
    """
    # --- Setup ---
    tracker = TrustTracker( trust_model="beta", debug=False )
    cb      = CircuitBreaker( trust_tracker=tracker, debug=False )
    strategy = EngineeringStrategy(
        trust_tracker              = tracker,
        circuit_breaker            = cb,
        trust_mode                 = "active",
        thompson_enabled           = True,
        thompson_act_threshold     = 0.90,
        thompson_suggest_threshold = 0.70,
        debug                      = False,
    )

    # --- Simulate 48 successes + 2 rejections in "testing" ---
    # alpha=49, beta=3, mean ≈ 0.942 → comfortably above act threshold 0.90
    cat = strategy.trust_tracker.categories[ "testing" ]
    for _ in range( 48 ):
        cat.record_decision( True )
    for _ in range( 2 ):
        cat.record_decision( False )

    # --- Run 200 gate() calls ---
    actions = { "act": 0, "suggest": 0, "shadow": 0, "defer": 0 }
    for _ in range( 200 ):
        action = strategy.gate( "testing", trust_level=3, confidence=0.9 )
        actions[ action ] += 1

    # Verify: with 48/50 successes (mean ≈ 0.94), should act frequently
    total = sum( actions.values() )
    p_act = actions[ "act" ] / total

    assert p_act > 0.50, f"Expected p_act > 0.50, got {p_act:.3f}"

    # --- Diagnostics ---
    diagnostics = strategy.get_thompson_diagnostics()

    assert len( diagnostics ) == 6
    assert "testing" in diagnostics

    testing_diag = diagnostics[ "testing" ]
    assert testing_diag[ "alpha" ] == 49  # 48 + 1 prior
    assert testing_diag[ "beta" ] == 3    # 2 + 1 prior
    assert testing_diag[ "observations" ] == 50

    prob_sum = testing_diag[ "p_act" ] + testing_diag[ "p_suggest" ] + testing_diag[ "p_shadow" ]
    assert abs( prob_sum - 1.0 ) < 0.01

    # --- Responder wiring ---
    responder = DecisionResponder( debug=False )
    responder.set_domain_strategy( strategy )

    resp_diag = responder.get_decision_diagnostics()
    assert "stats" in resp_diag
    assert "thompson_sampling" in resp_diag
    assert "testing" in resp_diag[ "thompson_sampling" ]

    # --- Print summary ---
    print( "\n" + "=" * 70 )
    print( "Thompson Sampling Smoke Test — Summary" )
    print( "=" * 70 )
    print( f"\n{'Category':<15} {'Alpha':>6} {'Beta':>6} {'Mean':>7} {'p_act':>7} {'p_suggest':>10} {'p_shadow':>9}" )
    print( "-" * 70 )
    for cat_name, diag in sorted( diagnostics.items() ):
        print( f"{cat_name:<15} {diag[ 'alpha' ]:>6} {diag[ 'beta' ]:>6} "
               f"{diag[ 'mean_rate' ]:>7.4f} {diag[ 'p_act' ]:>7.4f} "
               f"{diag[ 'p_suggest' ]:>10.4f} {diag[ 'p_shadow' ]:>9.4f}" )
    print( "-" * 70 )
    print( f"\nGate distribution (200 draws, 'testing' category):" )
    for action_name in [ "act", "suggest", "shadow", "defer" ]:
        count = actions[ action_name ]
        pct   = count / total * 100
        print( f"  {action_name:<10}: {count:>4} ({pct:>5.1f}%)" )
    print( f"\n  p_act = {p_act:.3f} (threshold: > 0.50)" )
    print( "=" * 70 )


if __name__ == "__main__":
    test_thompson_sampling_smoke()
    print( "\n✓ Thompson Sampling smoke test passed." )
