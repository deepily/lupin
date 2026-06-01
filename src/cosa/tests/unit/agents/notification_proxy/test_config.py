#!/usr/bin/env python3
"""
Unit tests for cosa.agents.notification_proxy.config.

config is a declarative module: re-exported shared connection constants,
notification-proxy-specific defaults, LLM config, the STRATEGY_CHOICES
list, and the TEST_PROFILES dictionary. These assertions are harvested
from the module's quick_smoke_test() so its coverage is preserved by
real pytest before that smoke block is retired.

No network / API-key access occurs here — only declarative data is read.
"""

import cosa.agents.notification_proxy.config as cfg


class TestReexportedConstants:
    """Shared connection constants are re-exported for backward compatibility."""

    def test_server_defaults_present( self ):
        """
        Ensures:
            - DEFAULT_SERVER_HOST / DEFAULT_SERVER_PORT are re-exported and usable
            - DEFAULT_SERVER_PORT is the canonical dev port (7999)
        """
        assert isinstance( cfg.DEFAULT_SERVER_HOST, str )
        assert cfg.DEFAULT_SERVER_PORT == 7999

    def test_reconnect_constants_present( self ):
        """
        Ensures:
            - the four reconnect-tuning constants are re-exported
        """
        assert cfg.RECONNECT_INITIAL_DELAY is not None
        assert cfg.RECONNECT_MAX_DELAY is not None
        assert cfg.RECONNECT_MAX_ATTEMPTS is not None
        assert cfg.RECONNECT_BACKOFF_FACTOR is not None

    def test_credential_helpers_reexported( self ):
        """
        Ensures:
            - get_credentials / get_anthropic_api_key are re-exported as callables
              (re-export only — they are NOT invoked here to avoid the API-key boundary)
        """
        assert callable( cfg.get_credentials )
        assert callable( cfg.get_anthropic_api_key )


class TestProxyDefaults:
    """Notification-proxy-specific defaults."""

    def test_agent_defaults( self ):
        """
        Ensures:
            - the mock-tester email, default session id, and default profile
              match the documented values
        """
        assert cfg.DEFAULT_EMAIL      == "mock.tester@lupin.deepily.ai"
        assert cfg.DEFAULT_SESSION_ID == "auto proxy"
        assert cfg.DEFAULT_PROFILE    == "deep_research"

    def test_subscribed_events( self ):
        """
        Ensures:
            - SUBSCRIBED_EVENTS lists at least the three required WebSocket events
        """
        assert "notification_queue_update" in cfg.SUBSCRIBED_EVENTS
        assert "job_state_transition"      in cfg.SUBSCRIBED_EVENTS
        assert "sys_ping"                  in cfg.SUBSCRIBED_EVENTS

    def test_llm_fallback_config( self ):
        """
        Ensures:
            - the LLM fallback model + token budget constants are set
        """
        assert cfg.LLM_FALLBACK_MODEL.startswith( "claude-" )
        assert cfg.LLM_FALLBACK_MAX_TOKENS > 0

    def test_llm_script_matcher_config( self ):
        """
        Ensures:
            - script-matcher template paths and scripts dir are configured
        """
        assert cfg.LLM_SCRIPT_MATCHER_SPEC_KEY
        assert cfg.LLM_SCRIPT_MATCHER_TEMPLATE.endswith( ".txt" )
        assert cfg.LLM_SCRIPT_MATCHER_BATCH_TEMPLATE.endswith( ".txt" )
        assert cfg.LLM_ANSWER_VERIFIER_TEMPLATE.endswith( ".txt" )
        assert cfg.NOTIFICATION_PROXY_SCRIPTS_DIR

    def test_strategy_choices( self ):
        """
        Ensures:
            - STRATEGY_CHOICES holds the three valid --strategy flag values
            - DEFAULT_STRATEGY is one of the valid choices
        """
        assert cfg.STRATEGY_CHOICES == [ "llm_script", "rules", "auto" ]
        assert cfg.DEFAULT_STRATEGY in cfg.STRATEGY_CHOICES


class TestAcceptedSenders:
    """Known expediter sender allow-list + deprecated alias."""

    def test_default_accepted_senders( self ):
        """
        Ensures:
            - the expeditor sender is on the default accept list
        """
        assert "arg.expeditor@lupin.deepily.ai" in cfg.DEFAULT_ACCEPTED_SENDERS

    def test_deprecated_alias_matches_first_sender( self ):
        """
        Ensures:
            - the backward-compat EXPEDITER_SENDER_ID alias equals the first
              entry of DEFAULT_ACCEPTED_SENDERS
        """
        assert cfg.EXPEDITER_SENDER_ID == cfg.DEFAULT_ACCEPTED_SENDERS[ 0 ]


class TestTestProfiles:
    """TEST_PROFILES maps profile names to auto-answer dictionaries."""

    def test_every_profile_has_description( self ):
        """
        Requires:
            - TEST_PROFILES is a non-empty dict

        Ensures:
            - there are at least three profiles
            - every profile carries a 'description' key
        """
        assert len( cfg.TEST_PROFILES ) >= 3
        for name, profile in cfg.TEST_PROFILES.items():
            assert "description" in profile, f"Profile '{name}' missing description"

    def test_default_profile_is_a_real_profile( self ):
        """
        Ensures:
            - DEFAULT_PROFILE names an actual entry in TEST_PROFILES
        """
        assert cfg.DEFAULT_PROFILE in cfg.TEST_PROFILES
