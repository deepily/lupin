#!/usr/bin/env python3
"""
Unit tests for the Notification Proxy Agent.

Tests:
    - ExpediterRuleStrategy: keyword matching, YES_NO auto-confirm, batch handling
    - NotificationResponder: strategy routing, stats tracking
    - WebSocketListener: construction, event handling
    - Config: profiles, API key resolution
"""

import asyncio
import json
import pytest

from cosa.agents.notification_proxy.config import (
    TEST_PROFILES,
    EXPEDITER_SENDER_ID,
    DEFAULT_SERVER_PORT,
    SUBSCRIBED_EVENTS,
    RECONNECT_MAX_ATTEMPTS,
    get_anthropic_api_key,
    get_credentials,
)
from cosa.agents.notification_proxy.cosa_interface import SENDER_ID
from cosa.agents.notification_proxy.strategies.expediter_rules import (
    ExpediterRuleStrategy,
    KEYWORD_TO_ARG,
)
from cosa.agents.notification_proxy.strategies.llm_fallback import LLMFallbackStrategy
from cosa.agents.notification_proxy.listener import WebSocketListener
from cosa.agents.notification_proxy.responder import NotificationResponder


# ============================================================================
# Test Config
# ============================================================================

class TestConfig:
    """Tests for config module."""

    def test_profiles_exist( self ):
        """All expected profiles are present."""
        assert "deep_research" in TEST_PROFILES
        assert "podcast" in TEST_PROFILES
        assert "research_to_podcast" in TEST_PROFILES
        assert "minimal" in TEST_PROFILES

    def test_profiles_have_descriptions( self ):
        """Each profile has a description field."""
        for name, profile in TEST_PROFILES.items():
            assert "description" in profile, f"Profile '{name}' missing description"

    def test_deep_research_profile_has_required_args( self ):
        """Deep research profile has query, budget, audience."""
        profile = TEST_PROFILES[ "deep_research" ]
        assert "query" in profile
        assert "budget" in profile
        assert "audience" in profile

    def test_podcast_profile_has_required_args( self ):
        """Podcast profile has research, languages."""
        profile = TEST_PROFILES[ "podcast" ]
        assert "research" in profile
        assert "languages" in profile

    def test_connection_defaults( self ):
        """Connection defaults are sensible."""
        assert DEFAULT_SERVER_PORT == 7999
        assert len( SUBSCRIBED_EVENTS ) >= 3
        assert "notification_queue_update" in SUBSCRIBED_EVENTS
        assert "sys_ping" in SUBSCRIBED_EVENTS

    def test_sender_id_format( self ):
        """SENDER_ID follows the expected pattern."""
        assert SENDER_ID == "notification.proxy@lupin.deepily.ai"
        assert "@" in SENDER_ID
        assert ".deepily.ai" in SENDER_ID

    def test_api_key_resolution_returns_string_or_none( self ):
        """get_anthropic_api_key returns str or None."""
        key = get_anthropic_api_key()
        assert key is None or isinstance( key, str )


# ============================================================================
# Test Credential Resolution
# ============================================================================

class TestGetCredentials:
    """Tests for get_credentials() 2-tier priority resolution."""

    def test_cli_override_takes_priority( self ):
        """CLI values override everything."""
        email, password = get_credentials( "cli@test.com", "cli-pass" )
        assert email == "cli@test.com"
        assert password == "cli-pass"

    def test_env_fallback( self, monkeypatch ):
        """LUPIN_TEST_INTERACTIVE_MOCK_JOBS env vars used when CLI is None."""
        monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", "mock@test.com" )
        monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD", "mock-pass" )

        email, password = get_credentials()
        assert email == "mock@test.com"
        assert password == "mock-pass"

    def test_no_email_raises( self, monkeypatch ):
        """Raises ValueError when no email from any source."""
        monkeypatch.delenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", raising=False )

        with pytest.raises( ValueError, match="No email found" ):
            get_credentials( cli_password="some-pass" )

    def test_no_password_raises( self, monkeypatch ):
        """Raises ValueError when no password from any source."""
        monkeypatch.delenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD", raising=False )

        with pytest.raises( ValueError, match="No password found" ):
            get_credentials( cli_email="user@test.com" )

    def test_cli_password_overrides_env( self, monkeypatch ):
        """CLI password takes priority over env var password."""
        monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD", "env-pass" )
        monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", "mock@test.com" )
        email, password = get_credentials( cli_password="cli-pass" )
        assert password == "cli-pass"

    def test_cli_email_overrides_env( self, monkeypatch ):
        """CLI email takes priority over env var email."""
        monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", "env@test.com" )
        monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD", "env-pass" )
        email, password = get_credentials( cli_email="cli@test.com" )
        assert email == "cli@test.com"


# ============================================================================
# Test Expediter Rule Strategy
# ============================================================================

class TestExpediterRulesConstruction:
    """Tests for ExpediterRuleStrategy construction."""

    def test_valid_profile( self ):
        """Constructs with valid profile name."""
        strategy = ExpediterRuleStrategy( "deep_research" )
        assert strategy.profile_name == "deep_research"

    def test_all_profiles( self ):
        """Constructs with every available profile."""
        for name in TEST_PROFILES:
            strategy = ExpediterRuleStrategy( name )
            assert strategy.profile_name == name

    def test_invalid_profile_raises( self ):
        """Raises KeyError for unknown profile."""
        with pytest.raises( KeyError ):
            ExpediterRuleStrategy( "nonexistent_profile" )


class TestExpediterRulesCanHandle:
    """Tests for can_handle method."""

    def test_handles_expediter_notification( self ):
        """Returns True for expediter notifications requesting response."""
        strategy = ExpediterRuleStrategy( "deep_research" )
        assert strategy.can_handle( {
            "sender_id"          : EXPEDITER_SENDER_ID,
            "response_requested" : True
        } )

    def test_rejects_non_expediter( self ):
        """Returns False for non-expediter sender."""
        strategy = ExpediterRuleStrategy( "deep_research" )
        assert not strategy.can_handle( {
            "sender_id"          : "claude.code@lupin.deepily.ai",
            "response_requested" : True
        } )

    def test_rejects_no_response_requested( self ):
        """Returns False when response not requested."""
        strategy = ExpediterRuleStrategy( "deep_research" )
        assert not strategy.can_handle( {
            "sender_id"          : EXPEDITER_SENDER_ID,
            "response_requested" : False
        } )

    def test_handles_expediter_with_session_suffix( self ):
        """Returns True even when sender_id has #session suffix."""
        strategy = ExpediterRuleStrategy( "deep_research" )
        assert strategy.can_handle( {
            "sender_id"          : EXPEDITER_SENDER_ID + "#abc12345",
            "response_requested" : True
        } )

    def test_empty_sender_id( self ):
        """Returns False for empty sender_id."""
        strategy = ExpediterRuleStrategy( "deep_research" )
        assert not strategy.can_handle( {
            "sender_id"          : "",
            "response_requested" : True
        } )


class TestExpediterRulesRespond:
    """Tests for respond method."""

    def test_yes_no_returns_yes( self ):
        """YES_NO confirmations always return 'yes'."""
        strategy = ExpediterRuleStrategy( "deep_research" )
        assert strategy.respond( {
            "response_type" : "yes_no",
            "message"       : "Does this look right?",
            "title"         : "Confirm"
        } ) == "yes"

    def test_open_ended_query_keyword( self ):
        """Matches 'query' keyword in title and returns profile value."""
        strategy = ExpediterRuleStrategy( "deep_research" )
        answer = strategy.respond( {
            "response_type" : "open_ended",
            "message"       : "What topic would you like me to research?",
            "title"         : "Missing: query"
        } )
        assert answer == "quantum computing breakthroughs 2026"

    def test_open_ended_budget_keyword( self ):
        """Matches 'budget' keyword and returns profile value."""
        strategy = ExpediterRuleStrategy( "deep_research" )
        answer = strategy.respond( {
            "response_type" : "open_ended",
            "message"       : "Would you like to set a budget limit?",
            "title"         : "Missing: budget"
        } )
        assert answer == "no limit"

    def test_open_ended_audience_keyword( self ):
        """Matches 'audience' keyword and returns profile value."""
        strategy = ExpediterRuleStrategy( "deep_research" )
        answer = strategy.respond( {
            "response_type" : "open_ended",
            "message"       : "Who is the target audience?",
            "title"         : "Missing: audience"
        } )
        assert answer == "academic"

    def test_open_ended_topic_keyword_in_message( self ):
        """Matches 'topic' keyword in message body."""
        strategy = ExpediterRuleStrategy( "deep_research" )
        answer = strategy.respond( {
            "response_type" : "open_ended",
            "message"       : "What topic would you like?",
            "title"         : ""
        } )
        assert answer == "quantum computing breakthroughs 2026"

    def test_open_ended_no_match_returns_none( self ):
        """Returns None when no keyword matches."""
        strategy = ExpediterRuleStrategy( "deep_research" )
        answer = strategy.respond( {
            "response_type" : "open_ended",
            "message"       : "What is the meaning of life?",
            "title"         : "Philosophy"
        } )
        assert answer is None

    def test_podcast_profile_languages( self ):
        """Podcast profile matches 'language' keyword."""
        strategy = ExpediterRuleStrategy( "podcast" )
        answer = strategy.respond( {
            "response_type" : "open_ended",
            "message"       : "What languages for the podcast?",
            "title"         : "Missing: languages"
        } )
        assert answer == "en"

    def test_podcast_profile_research( self ):
        """Podcast profile matches 'document' keyword for research arg."""
        strategy = ExpediterRuleStrategy( "podcast" )
        answer = strategy.respond( {
            "response_type" : "open_ended",
            "message"       : "Which research document should I use?",
            "title"         : "Missing: research"
        } )
        assert answer == "latest"

    def test_batch_response( self ):
        """OPEN_ENDED_BATCH returns JSON dict with answers."""
        strategy = ExpediterRuleStrategy( "deep_research" )
        answer = strategy.respond( {
            "response_type"    : "open_ended_batch",
            "message"          : "I need a few things...",
            "title"            : "Missing arguments",
            "response_options" : {
                "questions" : [
                    { "header": "budget",   "question": "Budget limit?" },
                    { "header": "audience", "question": "Who is the audience?" },
                ]
            }
        } )
        assert answer is not None
        parsed = json.loads( answer )
        assert parsed[ "answers" ][ "budget" ] == "no limit"
        assert parsed[ "answers" ][ "audience" ] == "academic"

    def test_batch_with_default_fallback( self ):
        """OPEN_ENDED_BATCH uses default_value when no profile match."""
        strategy = ExpediterRuleStrategy( "minimal" )
        answer = strategy.respond( {
            "response_type"    : "open_ended_batch",
            "message"          : "I need some info...",
            "title"            : "Missing arguments",
            "response_options" : {
                "questions" : [
                    { "header": "unknown_arg", "question": "What?", "default_value": "fallback_val" },
                ]
            }
        } )
        assert answer is not None
        parsed = json.loads( answer )
        assert parsed[ "answers" ][ "unknown_arg" ] == "fallback_val"

    def test_multiple_choice_picks_first( self ):
        """MULTIPLE_CHOICE picks the first option label."""
        strategy = ExpediterRuleStrategy( "deep_research" )
        answer = strategy.respond( {
            "response_type"    : "multiple_choice",
            "message"          : "Which approach?",
            "title"            : "Approach",
            "response_options" : {
                "questions" : [ {
                    "options" : [
                        { "label": "Option A" },
                        { "label": "Option B" },
                    ]
                } ]
            }
        } )
        assert answer == "Option A"


# ============================================================================
# Test LLM Fallback Strategy
# ============================================================================

class TestLLMFallback:
    """Tests for LLMFallbackStrategy (no API calls — just construction and prompts)."""

    def test_construction( self ):
        """Constructs without error."""
        strategy = LLMFallbackStrategy()
        assert isinstance( strategy.available, bool )

    def test_can_handle_when_unavailable( self ):
        """Returns False if no API key."""
        strategy = LLMFallbackStrategy()
        if not strategy.available:
            assert not strategy.can_handle( { "response_requested": True } )

    def test_can_handle_rejects_no_response( self ):
        """Returns False when response not requested."""
        strategy = LLMFallbackStrategy()
        assert not strategy.can_handle( { "response_requested": False } )

    def test_prompt_building_yes_no( self ):
        """Builds correct prompt for YES_NO type."""
        strategy = LLMFallbackStrategy()
        prompt = strategy._build_prompt( "Confirm?", "", "yes_no", "Title" )
        assert "yes" in prompt.lower() and "no" in prompt.lower()

    def test_prompt_building_open_ended( self ):
        """Builds correct prompt for open_ended type."""
        strategy = LLMFallbackStrategy()
        prompt = strategy._build_prompt( "What color?", "Context here", "open_ended", "" )
        assert "What color?" in prompt
        assert "Context here" in prompt
        assert "brief" in prompt.lower()

    def test_prompt_building_with_abstract( self ):
        """Includes abstract context in prompt."""
        strategy = LLMFallbackStrategy()
        prompt = strategy._build_prompt( "Question", "**Agent**: Deep Research", "open_ended", "Missing" )
        assert "Deep Research" in prompt


# ============================================================================
# Test WebSocket Listener
# ============================================================================

class TestWebSocketListener:
    """Tests for WebSocketListener construction and configuration."""

    def test_construction( self ):
        """Constructs with required parameters."""
        async def handler( et, ed ):
            pass

        listener = WebSocketListener(
            email      = "test@example.com",
            password   = "test-password",
            session_id = "test proxy",
            on_event   = handler
        )
        assert listener.email == "test@example.com"
        assert listener.password == "test-password"
        assert listener.session_id == "test proxy"
        assert not listener.is_connected
        assert listener._user_id is None
        assert listener._token is None

    def test_default_host_port( self ):
        """Uses default host and port."""
        async def handler( et, ed ):
            pass

        listener = WebSocketListener(
            email      = "test@example.com",
            password   = "test-password",
            session_id = "test proxy",
            on_event   = handler
        )
        assert listener.host == "localhost"
        assert listener.port == 7999

    def test_custom_host_port( self ):
        """Accepts custom host and port."""
        async def handler( et, ed ):
            pass

        listener = WebSocketListener(
            email      = "test@example.com",
            password   = "test-password",
            session_id = "test proxy",
            on_event   = handler,
            host       = "example.com",
            port       = 8080
        )
        assert listener.host == "example.com"
        assert listener.port == 8080


# ============================================================================
# Test Notification Responder
# ============================================================================

class TestNotificationResponder:
    """Tests for NotificationResponder routing and stats."""

    def test_construction( self ):
        """Constructs with valid profile."""
        responder = NotificationResponder( "deep_research" )
        assert responder.rule_strategy is not None
        assert responder.llm_strategy is not None
        assert responder.dry_run is False

    def test_dry_run_construction( self ):
        """Constructs with dry_run enabled."""
        responder = NotificationResponder( "deep_research", dry_run=True )
        assert responder.dry_run is True

    def test_stats_initialized( self ):
        """Stats start at zero."""
        responder = NotificationResponder( "deep_research" )
        for key, value in responder.stats.items():
            assert value == 0, f"Stats[{key}] should be 0, got {value}"

    def test_strategy_routing_expediter_yes_no( self ):
        """Expediter YES_NO is handled by rules."""
        responder = NotificationResponder( "deep_research" )
        notif = {
            "sender_id"          : EXPEDITER_SENDER_ID,
            "response_requested" : True,
            "response_type"      : "yes_no",
            "message"            : "Confirm?",
            "title"              : "Confirm"
        }
        assert responder.rule_strategy.can_handle( notif )
        assert responder.rule_strategy.respond( notif ) == "yes"

    def test_strategy_routing_expediter_open_ended( self ):
        """Expediter OPEN_ENDED is handled by rules with correct answer."""
        responder = NotificationResponder( "deep_research" )
        notif = {
            "sender_id"          : EXPEDITER_SENDER_ID,
            "response_requested" : True,
            "response_type"      : "open_ended",
            "message"            : "What topic?",
            "title"              : "Missing: query"
        }
        assert responder.rule_strategy.can_handle( notif )
        answer = responder.rule_strategy.respond( notif )
        assert answer == "quantum computing breakthroughs 2026"

    def test_non_expediter_falls_through_rules( self ):
        """Non-expediter notifications are not handled by rules."""
        responder = NotificationResponder( "deep_research" )
        notif = {
            "sender_id"          : "claude.code@lupin.deepily.ai",
            "response_requested" : True,
            "response_type"      : "open_ended",
            "message"            : "Question?",
            "title"              : "Info"
        }
        assert not responder.rule_strategy.can_handle( notif )

    @pytest.mark.asyncio
    async def test_handle_event_skips_non_notification( self ):
        """Non-notification events don't increment stats."""
        responder = NotificationResponder( "deep_research" )
        await responder.handle_event( "job_state_transition", { "state": "running" } )
        assert responder.stats[ "notifications_received" ] == 0

    @pytest.mark.asyncio
    async def test_handle_event_skips_no_response_needed( self ):
        """Notifications without response_requested are skipped."""
        responder = NotificationResponder( "deep_research" )
        await responder.handle_event( "notification_queue_update", {
            "notification" : {
                "id_hash"            : "test-id-123",
                "sender_id"          : EXPEDITER_SENDER_ID,
                "response_requested" : False,
                "message"            : "FYI message",
                "title"              : "Info"
            }
        } )
        assert responder.stats[ "notifications_received" ] == 1
        assert responder.stats[ "skipped" ] == 1

    @pytest.mark.asyncio
    async def test_handle_event_errors_on_missing_id( self ):
        """Events without notification_id produce error."""
        responder = NotificationResponder( "deep_research" )
        await responder.handle_event( "notification_queue_update", {
            "notification" : {
                "response_requested" : True,
                "sender_id"          : EXPEDITER_SENDER_ID,
                "response_type"      : "yes_no",
                "message"            : "Confirm?",
                "title"              : "Confirm"
                # Missing id_hash
            }
        } )
        assert responder.stats[ "errors" ] == 1


# ============================================================================
# Test Keyword Mapping
# ============================================================================

class TestKeywordMapping:
    """Tests for keyword-to-argument-name mapping."""

    def test_keyword_groups_are_non_empty( self ):
        """Every keyword group has at least one keyword."""
        for keywords, arg_name in KEYWORD_TO_ARG:
            assert len( keywords ) > 0, f"Empty keyword group for {arg_name}"

    def test_all_arg_names_are_strings( self ):
        """All arg_name values are strings."""
        for keywords, arg_name in KEYWORD_TO_ARG:
            assert isinstance( arg_name, str )

    def test_audience_context_before_audience( self ):
        """'audience context' is matched before 'audience' to prevent false matches."""
        audience_context_idx = None
        audience_idx         = None
        for i, ( keywords, arg_name ) in enumerate( KEYWORD_TO_ARG ):
            if arg_name == "audience_context":
                audience_context_idx = i
            elif arg_name == "audience":
                audience_idx = i

        if audience_context_idx is not None and audience_idx is not None:
            assert audience_context_idx < audience_idx, \
                "audience_context must appear before audience in KEYWORD_TO_ARG"


# ============================================================================
# Test Profile Coverage
# ============================================================================

class TestProfileCoverage:
    """Tests that profiles cover all expediter question patterns."""

    def test_deep_research_covers_all_fallback_questions( self ):
        """Deep research profile covers all known question args."""
        from cosa.agents.runtime_argument_expeditor.agent_registry import AGENTIC_AGENTS

        agent = AGENTIC_AGENTS[ "agent router go to deep research" ]
        profile = TEST_PROFILES[ "deep_research" ]

        for arg_name in agent[ "fallback_questions" ]:
            assert arg_name in profile, \
                f"Profile 'deep_research' missing answer for '{arg_name}'"

    def test_podcast_covers_all_fallback_questions( self ):
        """Podcast profile covers all known question args."""
        from cosa.agents.runtime_argument_expeditor.agent_registry import AGENTIC_AGENTS

        agent = AGENTIC_AGENTS[ "agent router go to podcast generator" ]
        profile = TEST_PROFILES[ "podcast" ]

        for arg_name in agent[ "fallback_questions" ]:
            assert arg_name in profile, \
                f"Profile 'podcast' missing answer for '{arg_name}'"

    def test_research_to_podcast_covers_all_fallback_questions( self ):
        """Research-to-podcast profile covers all known question args."""
        from cosa.agents.runtime_argument_expeditor.agent_registry import AGENTIC_AGENTS

        agent = AGENTIC_AGENTS[ "agent router go to research to podcast" ]
        profile = TEST_PROFILES[ "research_to_podcast" ]

        for arg_name in agent[ "fallback_questions" ]:
            assert arg_name in profile, \
                f"Profile 'research_to_podcast' missing answer for '{arg_name}'"


# ============================================================================
# Run inline if needed
# ============================================================================

if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
