#!/usr/bin/env python3
"""
Profile-loading tests for cosa.agents.decision_proxy.__main__ (row 960a4ec9).

The defect these pin: the loader imported two names that never existed —
`SweEngineeringStrategy` and `ACCEPTED_SENDERS` — so it raised ImportError on
EVERY start and the SWE profile silently fell through to shadow-only with an
empty allowlist. From outside, that dead profile looked identical to a healthy
one: main() ignored the loader's return and connected/announced normally.

These assert the loader's contract — success loads the strategy AND sets the
three shipped addresses (the fail-closed evidence, pinned as a test not a claim);
a genuine import failure reports False and leaves the allowlist empty — so a
broken profile reds in CI instead of silently degrading.
"""

import sys
from unittest.mock import patch

from cosa.agents.decision_proxy import __main__ as dpmain
from cosa.agents.decision_proxy.responder import DecisionResponder
from cosa.agents.swe_team.proxy.config import DEFAULT_ACCEPTED_SENDERS


def test_profile_loads_and_sets_the_three_shipped_addresses():
    # RED if the swe_team profile ever fails to import or the shipped addresses
    # drift. This is the "__main__ sets the three addresses" evidence, pinned: the
    # whole fail-closed safety case rests on the shipped path supplying a NON-empty
    # allowlist, so it must be a test, not a claim.
    r = DecisionResponder( trust_mode="active" )
    assert r.accepted_senders == []                      # empty before load
    loaded = dpmain._load_swe_team_profile( r )
    assert loaded is True
    assert r.domain_strategy is not None                 # strategy actually attached
    assert r.accepted_senders == DEFAULT_ACCEPTED_SENDERS
    assert r.accepted_senders == [
        "swe.lead@lupin.deepily.ai",
        "swe.coder@lupin.deepily.ai",
        "swe.tester@lupin.deepily.ai",
    ]


def test_profile_load_failure_reports_false_and_leaves_allowlist_empty():
    # Simulate the swe_team.proxy package failing to import. The loader must report
    # False (a distinguishable failure), NOT silently succeed, and must leave the
    # allowlist empty — which fail-closed then rejects, so the dead profile submits
    # nothing. main() turns this False into a refuse-to-start.
    r = DecisionResponder()
    with patch.dict( sys.modules, { "cosa.agents.swe_team.proxy": None } ):
        loaded = dpmain._load_swe_team_profile( r )
    assert loaded is False
    assert r.accepted_senders == []
    assert r.domain_strategy is None


def test_profile_load_non_import_error_is_caught_not_propagated():
    # extra-2 review: a NON-ImportError out of the config factory or strategy
    # constructor must NOT escape and crash main() with a traceback. The widened
    # `except Exception` turns any load failure into a clean False (→ refuse-to-start).
    r = DecisionResponder()
    with patch( "cosa.agents.swe_team.proxy.EngineeringStrategy",
                side_effect=RuntimeError( "constructor blew up" ) ):
        loaded = dpmain._load_swe_team_profile( r )   # must return, not raise
    assert loaded is False
    assert r.accepted_senders == []
    assert r.domain_strategy is None


def test_profile_strategy_carries_the_ini_caps_and_audit_rate():
    # Row a9643589: the entry point built EngineeringStrategy with only senders, mode and debug,
    # so the INI cap levels and l4 audit rate were silently ignored.
    from unittest.mock import MagicMock
    r = DecisionResponder( trust_mode="active" )
    with patch( "cosa.config.configuration_manager.ConfigurationManager", MagicMock() ), \
         patch( "cosa.agents.decision_proxy.config.trust_proxy_config_from_config_mgr",
                return_value={ "l4_audit_sample_rate": 0.37 } ), \
         patch( "cosa.agents.swe_team.proxy.config.swe_proxy_config_from_config_mgr",
                return_value={ "accepted_senders": [ "a@x" ], "deployment_cap_level": 2 } ):
        assert dpmain._load_swe_team_profile( r ) is True
    assert r.domain_strategy.l4_audit_rate == 0.37
    assert r.domain_strategy.trust_tracker.categories[ "deployment" ].cap_level == 2
    assert r.accepted_senders == [ "a@x" ]
