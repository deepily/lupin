#!/usr/bin/env python3
"""
Unit tests for cosa.agents.decision_proxy.config.

Covers the module-level trust-framework constants and the
trust_proxy_config_from_config_mgr() factory that maps INI keys into a
runtime config dict. The ConfigurationManager is mocked at the boundary —
no real INI / filesystem access.
"""

from unittest.mock import MagicMock

from cosa.agents.decision_proxy import config as cfg


# ----------------------------------------------------------------------------
# Module-level constants
# ----------------------------------------------------------------------------
def test_trust_levels_structure():
    assert set( cfg.TRUST_LEVELS.keys() ) == { 1, 2, 3, 4, 5 }
    assert cfg.TRUST_LEVELS[ 1 ][ "name" ] == "Shadow"
    assert cfg.TRUST_LEVELS[ 5 ][ "min_decisions" ] == 1000
    for level in cfg.TRUST_LEVELS.values():
        assert { "name", "min_decisions", "description" } <= set( level.keys() )


def test_trust_mode_constants():
    assert cfg.DEFAULT_TRUST_MODE == "shadow"
    assert cfg.DEFAULT_TRUST_MODE in cfg.TRUST_MODE_CHOICES
    assert cfg.TRUST_MODE_CHOICES == [ "shadow", "suggest", "active" ]


def test_session_and_event_defaults():
    assert cfg.DEFAULT_SESSION_ID == "decision proxy"
    assert cfg.DEFAULT_PROFILE == "swe_team"
    assert cfg.SUBSCRIBED_EVENTS == [
        "notification_queue_update",
        "job_state_transition",
        "sys_ping",
    ]


# ----------------------------------------------------------------------------
# trust_proxy_config_from_config_mgr factory
# ----------------------------------------------------------------------------
def test_factory_falls_back_to_module_defaults():
    """
    Ensures:
        - when the config manager returns the supplied default for every key,
          the factory output equals the module-level defaults
        - all 36 generic trust-proxy keys are present
    """
    mgr = MagicMock()
    mgr.get.side_effect = lambda key, default=None, return_type=None: default

    out = cfg.trust_proxy_config_from_config_mgr( mgr )

    assert len( out ) == 36
    assert out[ "enabled" ] is False
    assert out[ "active_hours_start" ] == cfg.DEFAULT_ACTIVE_HOURS_START
    assert out[ "active_hours_end" ] == cfg.DEFAULT_ACTIVE_HOURS_END
    assert out[ "timezone" ] == cfg.DEFAULT_TIMEZONE
    assert out[ "l2_threshold" ] == cfg.DEFAULT_L2_THRESHOLD
    assert out[ "l5_threshold" ] == cfg.DEFAULT_L5_THRESHOLD
    assert out[ "decay_half_life_days" ] == cfg.DEFAULT_DECAY_HALF_LIFE_DAYS
    assert out[ "cb_error_rate_threshold" ] == cfg.DEFAULT_CB_ERROR_RATE_THRESHOLD
    assert out[ "similarity_threshold" ] == cfg.DEFAULT_SIMILARITY_THRESHOLD
    assert out[ "beta_l2_rate_threshold" ] == cfg.DEFAULT_BETA_L2_RATE_THRESHOLD
    assert out[ "beta_l5_min_samples" ] == cfg.DEFAULT_BETA_L5_MIN_SAMPLES
    assert out[ "cbr_top_k" ] == cfg.DEFAULT_CBR_TOP_K
    assert out[ "thompson_enabled" ] == cfg.DEFAULT_THOMPSON_ENABLED
    assert out[ "bald_defer_threshold" ] == cfg.DEFAULT_BALD_DEFER_THRESHOLD
    assert out[ "conformal_alpha" ] == cfg.DEFAULT_CONFORMAL_ALPHA
    assert out[ "icrl_top_k" ] == cfg.DEFAULT_ICRL_TOP_K


def test_factory_passes_through_config_values():
    """
    Ensures:
        - the factory returns exactly what the config manager supplies
          (it does not silently override managed values)
    """
    mgr = MagicMock()
    mgr.get.return_value = "SENTINEL"

    out = cfg.trust_proxy_config_from_config_mgr( mgr )

    assert len( out ) == 36
    assert all( v == "SENTINEL" for v in out.values() )
