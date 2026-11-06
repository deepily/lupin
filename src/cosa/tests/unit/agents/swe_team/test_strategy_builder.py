#!/usr/bin/env python3
"""
Tests for the shared INI-configured EngineeringStrategy builder.

Three call sites use the builder.
These tests drive the actual strategy, tracker and circuit breaker.
Only the two INI factories are replaced, so each value is checked at the object that uses it.
"""

from unittest.mock import MagicMock, patch

import pytest

from cosa.agents.decision_proxy.errors import InvalidTrustModelError
from cosa.agents.swe_team.strategy_builder import build_ini_engineering_strategy


def ini_patches( proxy_cfg, swe_cfg ):
    """
    Replace the two INI factories so the builder reads these dicts.

    Requires:
        - proxy_cfg and swe_cfg are dicts, or an Exception instance to raise from the factory

    Ensures:
        - returns a list of started-on-enter patchers to use with ExitStack
    """
    def result( value ):
        return { "side_effect": value } if isinstance( value, Exception ) else { "return_value": value }

    return [
        patch( "cosa.config.configuration_manager.ConfigurationManager", MagicMock() ),
        patch( "cosa.agents.decision_proxy.config.trust_proxy_config_from_config_mgr", MagicMock( **result( proxy_cfg ) ) ),
        patch( "cosa.agents.swe_team.proxy.config.swe_proxy_config_from_config_mgr",   MagicMock( **result( swe_cfg ) ) ),
    ]


def build( proxy_cfg, swe_cfg, trust_mode="shadow", **kwargs ):
    from contextlib import ExitStack
    with ExitStack() as stack:
        for p in ini_patches( proxy_cfg, swe_cfg ): stack.enter_context( p )
        return build_ini_engineering_strategy( trust_mode=trust_mode, **kwargs )


def test_ini_caps_audit_rate_and_senders_reach_the_strategy():
    strategy, swe_cfg = build(
        { "l4_audit_sample_rate": 0.37 },
        { "accepted_senders": [ "a@x" ], "deployment_cap_level": 2, "destructive_cap_level": 3, "architecture_cap_level": 4 },
    )
    assert strategy.l4_audit_rate == 0.37
    assert { c : strategy.trust_tracker.categories[ c ].cap_level for c in ( "deployment", "destructive", "architecture" ) } == {
        "deployment": 2, "destructive": 3, "architecture": 4 }
    assert strategy.accepted_senders == [ "a@x" ]
    assert strategy.trust_mode == "shadow"
    assert swe_cfg[ "accepted_senders" ] == [ "a@x" ]


def test_absent_keys_keep_the_built_in_values():
    strategy, swe_cfg = build( {}, {} )
    assert strategy.l4_audit_rate == 0.10
    assert strategy.trust_tracker.trust_model == "count"
    assert swe_cfg == {}


def test_trust_model_and_beta_thresholds_reach_the_tracker_and_breaker_shares_it():
    cfg = { "trust_model": "blr" }
    for lvl, ( rate, n ) in zip( ( 2, 3, 4, 5 ), ( ( 0.1, 11 ), ( 0.2, 12 ), ( 0.3, 13 ), ( 0.4, 14 ) ) ):
        cfg[ f"beta_l{lvl}_rate_threshold" ] = rate
        cfg[ f"beta_l{lvl}_min_samples" ]    = n
    strategy, _ = build( cfg, {} )
    assert strategy.trust_tracker.trust_model == "blr"
    assert strategy.trust_tracker.rate_thresholds == { 2: 0.1, 3: 0.2, 4: 0.3, 5: 0.4 }
    assert strategy.trust_tracker.min_samples     == { 2: 11, 3: 12, 4: 13, 5: 14 }
    assert strategy.circuit_breaker.trust_tracker is strategy.trust_tracker


def test_trip_callback_reaches_the_circuit_breaker():
    callback = MagicMock()
    strategy, _ = build( {}, {}, on_trip_callback=callback )
    assert strategy.circuit_breaker.on_trip_callback is callback


def test_an_unknown_trust_model_is_refused_not_defaulted():
    with pytest.raises( InvalidTrustModelError, match="must be one of" ):
        build( InvalidTrustModelError( "trust model must be one of" ), {} )


def test_any_other_ini_failure_is_non_fatal_and_builds_on_defaults():
    strategy, swe_cfg = build( ValueError( "invalid literal for int()" ), {} )
    assert strategy.l4_audit_rate == 0.10
    assert swe_cfg == {}


@pytest.mark.parametrize( "mode", [ "shadow", "suggest", "active" ] )
def test_the_callers_trust_mode_reaches_the_strategy_unchanged( mode ):
    strategy, _ = build( {}, {}, trust_mode=mode )
    assert strategy.trust_mode == mode
