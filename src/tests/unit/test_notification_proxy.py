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
import os
import pytest
from unittest.mock import patch, MagicMock

from cosa.agents.notification_proxy.config import (
    TEST_PROFILES,
    EXPEDITER_SENDER_ID,
    DEFAULT_ACCEPTED_SENDERS,
    DEFAULT_SERVER_PORT,
    DEFAULT_STRATEGY,
    STRATEGY_CHOICES,
    NOTIFICATION_PROXY_SCRIPTS_DIR,
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
from cosa.agents.notification_proxy.strategies.llm_script_matcher import (
    LlmScriptMatcherStrategy,
    resolve_script_path,
)
from cosa.agents.notification_proxy.xml_models import ScriptMatcherResponse, BatchScriptMatcherResponse, VerificationResponse
from cosa.agents.notification_proxy.verification import LlmAnswerVerifier
from cosa.agents.notification_proxy.listener import WebSocketListener
from cosa.agents.notification_proxy.responder import NotificationResponder
import cosa.utils.util as cu


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

    def test_default_accepted_senders_is_list( self ):
        """DEFAULT_ACCEPTED_SENDERS is a non-empty list."""
        assert isinstance( DEFAULT_ACCEPTED_SENDERS, list )
        assert len( DEFAULT_ACCEPTED_SENDERS ) >= 1
        assert DEFAULT_ACCEPTED_SENDERS[ 0 ] == "arg.expeditor@lupin.deepily.ai"

    def test_deprecated_sender_id_alias( self ):
        """EXPEDITER_SENDER_ID is a deprecated alias for DEFAULT_ACCEPTED_SENDERS[0]."""
        assert EXPEDITER_SENDER_ID == DEFAULT_ACCEPTED_SENDERS[ 0 ]

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

    def test_all_agents_profile_covers_all_arg_names( self ):
        """all_agents union profile covers every arg name across all 3 agents."""
        from cosa.agents.runtime_argument_expeditor.agent_registry import AGENTIC_AGENTS

        profile = TEST_PROFILES[ "all_agents" ]

        # Collect all unique arg names across all agents
        all_arg_names = set()
        for key, agent in AGENTIC_AGENTS.items():
            for arg_name in agent[ "fallback_questions" ]:
                all_arg_names.add( arg_name )

        for arg_name in all_arg_names:
            assert arg_name in profile, \
                f"Profile 'all_agents' missing answer for '{arg_name}'"


# ============================================================================
# Test Keyword Ordering Regression
# ============================================================================

class TestKeywordOrderingRegression:
    """Regression tests for keyword-to-arg mapping bug fix (Session 178)."""

    def test_research_keyword_maps_to_research_not_query( self ):
        """'research' keyword in OPEN_ENDED matches research arg, not query.

        Regression: Before fix, 'research' was in the query keyword group,
        causing PG scenarios to get profile['query'] instead of profile['research']
        when _ask_for_arg("research", ...) sent a message containing 'research'.
        """
        strategy = ExpediterRuleStrategy( "all_agents" )
        answer = strategy.respond( {
            "response_type" : "open_ended",
            "message"       : "I don't see any research documents. Please provide a path.",
            "title"         : "Missing: research"
        } )
        assert answer == "/tmp/mock-research-document.md", \
            f"Expected research path, got: {answer}"

    def test_research_keyword_not_in_query_group( self ):
        """Structural assertion: 'research' must NOT be in the query keyword group."""
        for keywords, arg_name in KEYWORD_TO_ARG:
            if arg_name == "query":
                assert "research" not in keywords, \
                    "'research' must not be in query keyword group (causes PG bug)"


# ============================================================================
# Test ScriptMatcherResponse XML Model
# ============================================================================

class TestScriptMatcherResponseModel:
    """Tests for ScriptMatcherResponse Pydantic XML model."""

    def test_creation_with_all_fields( self ):
        """Creates with all required and optional fields."""
        response = ScriptMatcherResponse(
            matched_entry = "2",
            answer        = "quantum computing",
            confidence    = "0.95",
            reasoning     = "Keyword match"
        )
        assert response.matched_entry == "2"
        assert response.answer == "quantum computing"
        assert response.confidence == "0.95"
        assert response.reasoning == "Keyword match"

    def test_xml_round_trip( self ):
        """Serializes to XML and parses back identically."""
        original = ScriptMatcherResponse(
            matched_entry = "1",
            answer        = "academic",
            confidence    = "0.9",
            reasoning     = "Audience question"
        )
        xml_str = original.to_xml()
        assert "<matched_entry>1</matched_entry>" in xml_str
        assert "<answer>academic</answer>" in xml_str

        parsed = ScriptMatcherResponse.from_xml( xml_str )
        assert parsed.matched_entry == original.matched_entry
        assert parsed.answer == original.answer
        assert parsed.confidence == original.confidence

    def test_is_match_true( self ):
        """is_match() returns True for valid matches."""
        response = ScriptMatcherResponse(
            matched_entry = "0",
            answer        = "yes",
            confidence    = "0.8"
        )
        assert response.is_match()

    def test_is_match_false_none( self ):
        """is_match() returns False when matched_entry is 'none'."""
        response = ScriptMatcherResponse(
            matched_entry = "none",
            answer        = "",
            confidence    = "0.0"
        )
        assert not response.is_match()

    def test_is_match_false_empty_answer( self ):
        """is_match() returns False when answer is empty."""
        response = ScriptMatcherResponse(
            matched_entry = "0",
            answer        = "",
            confidence    = "0.5"
        )
        assert not response.is_match()

    def test_get_confidence_float( self ):
        """get_confidence_float() parses string to clamped float."""
        response = ScriptMatcherResponse(
            matched_entry = "0", answer = "x", confidence = "0.85"
        )
        assert response.get_confidence_float() == 0.85

    def test_get_confidence_float_invalid( self ):
        """get_confidence_float() returns 0.0 for invalid string."""
        response = ScriptMatcherResponse(
            matched_entry = "0", answer = "x", confidence = "invalid"
        )
        assert response.get_confidence_float() == 0.0

    def test_get_confidence_float_clamped( self ):
        """get_confidence_float() clamps to [0.0, 1.0]."""
        response = ScriptMatcherResponse(
            matched_entry = "0", answer = "x", confidence = "1.5"
        )
        assert response.get_confidence_float() == 1.0

        response2 = ScriptMatcherResponse(
            matched_entry = "0", answer = "x", confidence = "-0.3"
        )
        assert response2.get_confidence_float() == 0.0

    def test_get_answers_dict_valid_json( self ):
        """get_answers_dict() parses JSON dict from answer field."""
        response = ScriptMatcherResponse(
            matched_entry = "0",
            answer        = '{"budget": "no limit", "audience": "academic"}',
            confidence    = "0.9"
        )
        answers = response.get_answers_dict()
        assert answers[ "budget" ] == "no limit"
        assert answers[ "audience" ] == "academic"

    def test_get_answers_dict_non_json( self ):
        """get_answers_dict() returns empty dict for non-JSON answer."""
        response = ScriptMatcherResponse(
            matched_entry = "0",
            answer        = "plain text",
            confidence    = "0.8"
        )
        assert response.get_answers_dict() == {}

    def test_get_answers_dict_empty( self ):
        """get_answers_dict() returns empty dict for empty answer."""
        response = ScriptMatcherResponse(
            matched_entry = "0",
            answer        = "",
            confidence    = "0.0"
        )
        assert response.get_answers_dict() == {}

    def test_get_example_for_template( self ):
        """Template example has placeholder-style values."""
        example = ScriptMatcherResponse.get_example_for_template()
        assert "index" in example.matched_entry.lower()
        assert "answer" in example.answer.lower()

    def test_none_coercion_optional_fields( self ):
        """None values on optional fields are coerced to empty string."""
        response = ScriptMatcherResponse(
            matched_entry = "0",
            answer        = "test",
            confidence    = None,
            reasoning     = None
        )
        assert response.confidence == ""
        assert response.reasoning == ""


# ============================================================================
# Test VerificationResponse XML Model
# ============================================================================

class TestVerificationResponseModel:
    """Tests for VerificationResponse Pydantic XML model."""

    def test_creation_with_all_fields( self ):
        """Creates with all required and optional fields."""
        response = VerificationResponse(
            match      = "true",
            confidence = "0.95",
            reasoning  = "Same meaning"
        )
        assert response.match == "true"
        assert response.confidence == "0.95"

    def test_xml_round_trip( self ):
        """Serializes to XML and parses back identically."""
        original = VerificationResponse(
            match      = "false",
            confidence = "0.8",
            reasoning  = "Different meanings"
        )
        xml_str = original.to_xml()
        assert "<match>false</match>" in xml_str

        parsed = VerificationResponse.from_xml( xml_str )
        assert parsed.match == original.match
        assert parsed.confidence == original.confidence

    def test_is_match_true( self ):
        """is_match() returns True for 'true' match."""
        response = VerificationResponse( match="true", confidence="0.9" )
        assert response.is_match()

    def test_is_match_false( self ):
        """is_match() returns False for 'false' match."""
        response = VerificationResponse( match="false", confidence="0.9" )
        assert not response.is_match()

    def test_is_match_case_insensitive( self ):
        """is_match() handles case and whitespace."""
        response = VerificationResponse( match=" True ", confidence="0.9" )
        assert response.is_match()

    def test_get_confidence_float( self ):
        """get_confidence_float() parses correctly."""
        response = VerificationResponse( match="true", confidence="0.75" )
        assert response.get_confidence_float() == 0.75

    def test_get_example_for_template( self ):
        """Template example has placeholder-style values."""
        example = VerificationResponse.get_example_for_template()
        assert "true" in example.match.lower()

    def test_none_coercion( self ):
        """None values on optional fields are coerced to empty string."""
        response = VerificationResponse(
            match      = "true",
            confidence = None,
            reasoning  = None
        )
        assert response.confidence == ""
        assert response.reasoning == ""


# ============================================================================
# Test LLM Script Matcher Construction
# ============================================================================

class TestLlmScriptMatcherConstruction:
    """Tests for LlmScriptMatcherStrategy construction and script loading."""

    def test_script_path_resolution( self ):
        """resolve_script_path maps profile names to JSON files."""
        path = resolve_script_path( "deep_research" )
        assert path.endswith( "deep-research.json" )

    def test_script_path_resolution_all_agents( self ):
        """resolve_script_path handles all_agents profile."""
        path = resolve_script_path( "all_agents" )
        assert path.endswith( "all-agents.json" )

    def test_script_path_resolution_custom_dir( self ):
        """resolve_script_path accepts custom scripts directory."""
        path = resolve_script_path( "deep_research", scripts_dir="/tmp" )
        assert path == "/tmp/deep-research.json"

    def test_missing_script_raises( self ):
        """FileNotFoundError for non-existent script file."""
        with pytest.raises( FileNotFoundError ):
            LlmScriptMatcherStrategy( script_path="/nonexistent/script.json" )

    def test_script_files_exist( self ):
        """All expected Q&A script files exist on disk."""
        scripts_dir = cu.get_project_root() + NOTIFICATION_PROXY_SCRIPTS_DIR
        for profile_name in [ "deep_research", "podcast", "research_to_podcast", "all_agents", "minimal" ]:
            path = resolve_script_path( profile_name, scripts_dir )
            assert os.path.exists( path ), f"Missing script: {path}"


# ============================================================================
# Test LLM Script Matcher can_handle
# ============================================================================

class TestLlmScriptMatcherCanHandle:
    """Tests for LlmScriptMatcherStrategy.can_handle()."""

    def _make_strategy( self ):
        """Create a strategy with mocked LLM client."""
        scripts_dir = cu.get_project_root() + NOTIFICATION_PROXY_SCRIPTS_DIR
        script_path = resolve_script_path( "deep_research", scripts_dir )

        with patch( "cosa.agents.notification_proxy.strategies.llm_script_matcher.LlmClientFactory" ) as MockFactory:
            mock_factory = MagicMock()
            mock_client  = MagicMock()
            MockFactory.return_value = mock_factory
            mock_factory.get_client.return_value = mock_client

            strategy = LlmScriptMatcherStrategy(
                script_path = script_path,
                debug       = False
            )
        return strategy

    def test_handles_expediter_notification( self ):
        """Returns True for expediter notifications requesting response."""
        strategy = self._make_strategy()
        assert strategy.can_handle( {
            "sender_id"          : EXPEDITER_SENDER_ID,
            "response_requested" : True
        } )

    def test_rejects_non_expediter( self ):
        """Returns False for non-expediter sender."""
        strategy = self._make_strategy()
        assert not strategy.can_handle( {
            "sender_id"          : "claude.code@lupin.deepily.ai",
            "response_requested" : True
        } )

    def test_rejects_no_response_requested( self ):
        """Returns False when response not requested."""
        strategy = self._make_strategy()
        assert not strategy.can_handle( {
            "sender_id"          : EXPEDITER_SENDER_ID,
            "response_requested" : False
        } )


# ============================================================================
# Test LLM Script Matcher respond (with mocked LLM)
# ============================================================================

class TestLlmScriptMatcherRespond:
    """Tests for LlmScriptMatcherStrategy.respond() with mocked LLM."""

    def _make_strategy_with_mock( self, xml_response ):
        """Create strategy with mocked LLM that returns the given XML."""
        scripts_dir = cu.get_project_root() + NOTIFICATION_PROXY_SCRIPTS_DIR
        script_path = resolve_script_path( "deep_research", scripts_dir )

        with patch( "cosa.agents.notification_proxy.strategies.llm_script_matcher.LlmClientFactory" ) as MockFactory:
            mock_factory = MagicMock()
            mock_client  = MagicMock()
            mock_client.run.return_value = xml_response
            MockFactory.return_value = mock_factory
            mock_factory.get_client.return_value = mock_client

            strategy = LlmScriptMatcherStrategy(
                script_path = script_path,
                debug       = False
            )
        return strategy

    def test_yes_no_returns_scripted_answer( self ):
        """YES_NO type returns 'yes' from script via LLM."""
        xml = ScriptMatcherResponse(
            matched_entry = "4",
            answer        = "yes",
            confidence    = "0.95",
            reasoning     = "Confirmation match"
        ).to_xml()

        strategy = self._make_strategy_with_mock( xml )
        answer = strategy.respond( {
            "response_type" : "yes_no",
            "message"       : "Would you like to proceed?",
            "title"         : "Confirm"
        } )
        assert answer == "yes"

    def test_open_ended_returns_scripted_answer( self ):
        """OPEN_ENDED type returns matched script answer via LLM."""
        xml = ScriptMatcherResponse(
            matched_entry = "0",
            answer        = "quantum computing breakthroughs 2026",
            confidence    = "0.92",
            reasoning     = "Topic question match"
        ).to_xml()

        strategy = self._make_strategy_with_mock( xml )
        answer = strategy.respond( {
            "response_type" : "open_ended",
            "message"       : "What topic would you like me to research?",
            "title"         : "Missing: query"
        } )
        assert answer == "quantum computing breakthroughs 2026"

    def test_open_ended_no_match_returns_none( self ):
        """OPEN_ENDED returns None when LLM finds no match."""
        xml = ScriptMatcherResponse(
            matched_entry = "none",
            answer        = "",
            confidence    = "0.1",
            reasoning     = "No matching entry"
        ).to_xml()

        strategy = self._make_strategy_with_mock( xml )
        answer = strategy.respond( {
            "response_type" : "open_ended",
            "message"       : "What is the meaning of life?",
            "title"         : "Philosophy"
        } )
        assert answer is None

    def test_multiple_choice_returns_option_label( self ):
        """MULTIPLE_CHOICE returns selected option label via LLM."""
        xml = ScriptMatcherResponse(
            matched_entry = "2",
            answer        = "academic",
            confidence    = "0.88",
            reasoning     = "Audience matches academic option"
        ).to_xml()

        strategy = self._make_strategy_with_mock( xml )
        answer = strategy.respond( {
            "response_type"    : "multiple_choice",
            "message"          : "Who is the target audience?",
            "title"            : "Audience",
            "response_options" : {
                "questions" : [ {
                    "options" : [
                        { "label": "beginner", "description": "New to the topic" },
                        { "label": "academic", "description": "Research audience" },
                        { "label": "general",  "description": "General public" },
                    ]
                } ]
            }
        } )
        assert answer == "academic"

    def test_batch_returns_json_dict( self ):
        """OPEN_ENDED_BATCH returns JSON dict via LLM."""
        xml = BatchScriptMatcherResponse(
            entries = [
                { "header" : "budget",   "matched_index" : "1", "answer" : "no limit" },
                { "header" : "audience", "matched_index" : "2", "answer" : "academic" },
            ],
            confidence = "0.90",
            reasoning  = "Batch match",
        ).to_xml()

        strategy = self._make_strategy_with_mock( xml )
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

    def test_batch_no_match_returns_none( self ):
        """OPEN_ENDED_BATCH returns None when no match."""
        xml = BatchScriptMatcherResponse(
            entries    = [],
            confidence = "0.0",
            reasoning  = "No match",
        ).to_xml()

        strategy = self._make_strategy_with_mock( xml )
        answer = strategy.respond( {
            "response_type"    : "open_ended_batch",
            "message"          : "Random questions",
            "title"            : "Unknown",
            "response_options" : {
                "questions" : [
                    { "header": "unknown", "question": "What?" },
                ]
            }
        } )
        assert answer is None

    def test_llm_error_returns_none( self ):
        """LLM exceptions are caught and return None."""
        scripts_dir = cu.get_project_root() + NOTIFICATION_PROXY_SCRIPTS_DIR
        script_path = resolve_script_path( "deep_research", scripts_dir )

        with patch( "cosa.agents.notification_proxy.strategies.llm_script_matcher.LlmClientFactory" ) as MockFactory:
            mock_factory = MagicMock()
            mock_client  = MagicMock()
            mock_client.run.side_effect = RuntimeError( "vLLM down" )
            MockFactory.return_value = mock_factory
            mock_factory.get_client.return_value = mock_client

            strategy = LlmScriptMatcherStrategy(
                script_path = script_path,
                debug       = False
            )

        answer = strategy.respond( {
            "response_type" : "open_ended",
            "message"       : "What topic?",
            "title"         : "Query"
        } )
        assert answer is None

    def test_agent_context_filtering( self ):
        """Entry filtering based on agent name in abstract."""
        scripts_dir = cu.get_project_root() + NOTIFICATION_PROXY_SCRIPTS_DIR
        script_path = resolve_script_path( "all_agents", scripts_dir )

        with patch( "cosa.agents.notification_proxy.strategies.llm_script_matcher.LlmClientFactory" ) as MockFactory:
            mock_factory = MagicMock()
            mock_client  = MagicMock()
            MockFactory.return_value = mock_factory
            mock_factory.get_client.return_value = mock_client

            strategy = LlmScriptMatcherStrategy(
                script_path = script_path,
                debug       = False
            )

        # Filter for deep_research — should include universal + deep_research-tagged entries
        notif_dr = { "abstract": "Agent: Deep Research\nJob: test" }
        filtered_dr = strategy._filter_entries_by_agent( notif_dr )

        # Filter for podcast — should include universal + podcast-tagged entries
        notif_pg = { "abstract": "Agent: Podcast\nJob: test" }
        filtered_pg = strategy._filter_entries_by_agent( notif_pg )

        # No context — should return all entries
        notif_none = { "abstract": "" }
        filtered_all = strategy._filter_entries_by_agent( notif_none )

        assert len( filtered_dr ) < len( filtered_all )
        assert len( filtered_pg ) < len( filtered_all )


# ============================================================================
# Test LLM Answer Verifier
# ============================================================================

class TestLlmAnswerVerifier:
    """Tests for LlmAnswerVerifier."""

    def test_exact_match_bypasses_llm( self ):
        """Exact case-insensitive match returns true without LLM."""
        with patch( "cosa.agents.notification_proxy.verification.LlmClientFactory" ) as MockFactory:
            MockFactory.return_value = MagicMock()
            MockFactory.return_value.get_client.return_value = MagicMock()
            verifier = LlmAnswerVerifier( debug=False )

        result = verifier.verify( "academic", "Academic" )
        assert result.is_match()
        assert result.get_confidence_float() == 1.0

    def test_exact_match_whitespace_stripped( self ):
        """Whitespace-stripped exact match returns true."""
        with patch( "cosa.agents.notification_proxy.verification.LlmClientFactory" ) as MockFactory:
            MockFactory.return_value = MagicMock()
            MockFactory.return_value.get_client.return_value = MagicMock()
            verifier = LlmAnswerVerifier( debug=False )

        result = verifier.verify( "  no limit  ", "no limit" )
        assert result.is_match()
        assert result.get_confidence_float() == 1.0

    def test_semantic_match_via_llm( self ):
        """Non-exact match goes through LLM and returns parsed result."""
        xml = VerificationResponse(
            match      = "true",
            confidence = "0.85",
            reasoning  = "Both mean unlimited budget"
        ).to_xml()

        with patch( "cosa.agents.notification_proxy.verification.LlmClientFactory" ) as MockFactory:
            mock_factory = MagicMock()
            mock_client  = MagicMock()
            mock_client.run.return_value = xml
            MockFactory.return_value = mock_factory
            mock_factory.get_client.return_value = mock_client

            verifier = LlmAnswerVerifier( debug=False )

        result = verifier.verify( "no limit", "unlimited", context="Budget question" )
        assert result.is_match()
        assert result.get_confidence_float() == 0.85

    def test_semantic_no_match( self ):
        """LLM returns false for semantically different answers."""
        xml = VerificationResponse(
            match      = "false",
            confidence = "0.90",
            reasoning  = "Answers differ in meaning"
        ).to_xml()

        with patch( "cosa.agents.notification_proxy.verification.LlmClientFactory" ) as MockFactory:
            mock_factory = MagicMock()
            mock_client  = MagicMock()
            mock_client.run.return_value = xml
            MockFactory.return_value = mock_factory
            mock_factory.get_client.return_value = mock_client

            verifier = LlmAnswerVerifier( debug=False )

        result = verifier.verify( "academic", "general public", context="Audience" )
        assert not result.is_match()

    def test_batch_verification( self ):
        """verify_batch returns list of VerificationResponse objects."""
        with patch( "cosa.agents.notification_proxy.verification.LlmClientFactory" ) as MockFactory:
            MockFactory.return_value = MagicMock()
            MockFactory.return_value.get_client.return_value = MagicMock()
            verifier = LlmAnswerVerifier( debug=False )

        # All exact matches — no LLM needed
        pairs = [
            ( "academic", "academic" ),
            ( "no limit", "no limit" ),
            ( "en", "en" ),
        ]
        results = verifier.verify_batch( pairs )
        assert len( results ) == 3
        assert all( r.is_match() for r in results )


# ============================================================================
# Test Q&A Script Format
# ============================================================================

class TestQAScriptFormat:
    """Tests for Q&A script JSON format correctness."""

    def _load_script( self, profile_name ):
        """Load a Q&A script by profile name."""
        scripts_dir = cu.get_project_root() + NOTIFICATION_PROXY_SCRIPTS_DIR
        path = resolve_script_path( profile_name, scripts_dir )
        with open( path, "r" ) as f:
            return json.load( f )

    def test_scripts_have_required_fields( self ):
        """All scripts have profile_name, description, and entries."""
        for profile in [ "deep_research", "podcast", "research_to_podcast", "all_agents", "minimal" ]:
            script = self._load_script( profile )
            assert "profile_name" in script, f"{profile} missing profile_name"
            assert "description" in script, f"{profile} missing description"
            assert "entries" in script, f"{profile} missing entries"
            assert len( script[ "entries" ] ) > 0, f"{profile} has no entries"

    def test_entries_have_required_fields( self ):
        """All script entries have question_pattern, answer, arg_name, response_types."""
        for profile in [ "deep_research", "podcast", "research_to_podcast", "all_agents", "minimal" ]:
            script = self._load_script( profile )
            for i, entry in enumerate( script[ "entries" ] ):
                assert "question_pattern" in entry, f"{profile} entry {i} missing question_pattern"
                assert "answer" in entry, f"{profile} entry {i} missing answer"
                assert "arg_name" in entry, f"{profile} entry {i} missing arg_name"
                assert "response_types" in entry, f"{profile} entry {i} missing response_types"

    def test_scripts_match_test_profiles( self ):
        """Q&A script answers are consistent with TEST_PROFILES values."""
        for profile_name in [ "deep_research", "podcast" ]:
            script   = self._load_script( profile_name )
            profile  = TEST_PROFILES[ profile_name ]

            for entry in script[ "entries" ]:
                arg_name = entry[ "arg_name" ]
                # Skip confirmation entries — not in TEST_PROFILES
                if arg_name == "confirmation":
                    continue
                if arg_name in profile:
                    assert entry[ "answer" ] == profile[ arg_name ], \
                        f"{profile_name}: script answer for '{arg_name}' ({entry[ 'answer' ]}) != " \
                        f"profile value ({profile[ arg_name ]})"


# ============================================================================
# Test Data-Driven Sender ID Filtering
# ============================================================================

class TestSenderIdFiltering:
    """Tests for data-driven sender_ids filtering in strategies."""

    def test_can_handle_multiple_senders_rules( self ):
        """ExpediterRuleStrategy matches against a list of 2+ senders."""
        strategy = ExpediterRuleStrategy(
            "deep_research",
            accepted_senders=[ "arg.expeditor@lupin.deepily.ai", "workflow.orchestrator@lupin.deepily.ai" ]
        )

        # First sender should match
        assert strategy.can_handle( {
            "sender_id"          : "arg.expeditor@lupin.deepily.ai",
            "response_requested" : True
        } )

        # Second sender should match
        assert strategy.can_handle( {
            "sender_id"          : "workflow.orchestrator@lupin.deepily.ai",
            "response_requested" : True
        } )

        # Second sender with session suffix should match
        assert strategy.can_handle( {
            "sender_id"          : "workflow.orchestrator@lupin.deepily.ai#abc123",
            "response_requested" : True
        } )

    def test_can_handle_unknown_sender_rejected_rules( self ):
        """ExpediterRuleStrategy rejects senders not in accepted list."""
        strategy = ExpediterRuleStrategy(
            "deep_research",
            accepted_senders=[ "arg.expeditor@lupin.deepily.ai" ]
        )

        assert not strategy.can_handle( {
            "sender_id"          : "unknown.sender@lupin.deepily.ai",
            "response_requested" : True
        } )

    def test_can_handle_multiple_senders_script_matcher( self ):
        """LlmScriptMatcherStrategy matches against a list of 2+ senders."""
        scripts_dir = cu.get_project_root() + NOTIFICATION_PROXY_SCRIPTS_DIR
        script_path = resolve_script_path( "deep_research", scripts_dir )

        with patch( "cosa.agents.notification_proxy.strategies.llm_script_matcher.LlmClientFactory" ) as MockFactory:
            mock_factory = MagicMock()
            mock_client  = MagicMock()
            MockFactory.return_value = mock_factory
            mock_factory.get_client.return_value = mock_client

            strategy = LlmScriptMatcherStrategy(
                script_path      = script_path,
                accepted_senders = [ "arg.expeditor@lupin.deepily.ai", "custom.sender@lupin.deepily.ai" ],
                debug            = False
            )

        # Both senders should be accepted
        assert strategy.can_handle( {
            "sender_id"          : "arg.expeditor@lupin.deepily.ai",
            "response_requested" : True
        } )
        assert strategy.can_handle( {
            "sender_id"          : "custom.sender@lupin.deepily.ai#xyz789",
            "response_requested" : True
        } )

    def test_can_handle_unknown_sender_rejected_script_matcher( self ):
        """LlmScriptMatcherStrategy rejects senders not in accepted list."""
        scripts_dir = cu.get_project_root() + NOTIFICATION_PROXY_SCRIPTS_DIR
        script_path = resolve_script_path( "deep_research", scripts_dir )

        with patch( "cosa.agents.notification_proxy.strategies.llm_script_matcher.LlmClientFactory" ) as MockFactory:
            mock_factory = MagicMock()
            mock_client  = MagicMock()
            MockFactory.return_value = mock_factory
            mock_factory.get_client.return_value = mock_client

            strategy = LlmScriptMatcherStrategy(
                script_path      = script_path,
                accepted_senders = [ "arg.expeditor@lupin.deepily.ai" ],
                debug            = False
            )

        assert not strategy.can_handle( {
            "sender_id"          : "unknown.sender@lupin.deepily.ai",
            "response_requested" : True
        } )

    def test_sender_ids_loaded_from_script( self ):
        """LlmScriptMatcherStrategy extracts sender_ids from script JSON."""
        scripts_dir = cu.get_project_root() + NOTIFICATION_PROXY_SCRIPTS_DIR
        script_path = resolve_script_path( "deep_research", scripts_dir )

        with patch( "cosa.agents.notification_proxy.strategies.llm_script_matcher.LlmClientFactory" ) as MockFactory:
            mock_factory = MagicMock()
            mock_client  = MagicMock()
            MockFactory.return_value = mock_factory
            mock_factory.get_client.return_value = mock_client

            strategy = LlmScriptMatcherStrategy(
                script_path = script_path,
                debug       = False
            )

        # Should have loaded sender_ids from the script file
        assert strategy.accepted_senders == [ "arg.expeditor@lupin.deepily.ai" ]

    def test_default_sender_ids_fallback( self ):
        """LlmScriptMatcherStrategy falls back to DEFAULT_ACCEPTED_SENDERS when script lacks sender_ids."""
        import tempfile

        # Create a script without sender_ids field
        script_no_senders = {
            "profile_name" : "test",
            "description"  : "Test script without sender_ids",
            "entries"      : []
        }

        with tempfile.NamedTemporaryFile( mode="w", suffix=".json", delete=False ) as f:
            json.dump( script_no_senders, f )
            tmp_path = f.name

        try:
            with patch( "cosa.agents.notification_proxy.strategies.llm_script_matcher.LlmClientFactory" ) as MockFactory:
                mock_factory = MagicMock()
                mock_client  = MagicMock()
                MockFactory.return_value = mock_factory
                mock_factory.get_client.return_value = mock_client

                strategy = LlmScriptMatcherStrategy(
                    script_path = tmp_path,
                    debug       = False
                )

            assert strategy.accepted_senders == DEFAULT_ACCEPTED_SENDERS
        finally:
            os.unlink( tmp_path )

    def test_script_sender_ids_field_format( self ):
        """All Q&A script files have a sender_ids field with valid format."""
        scripts_dir = cu.get_project_root() + NOTIFICATION_PROXY_SCRIPTS_DIR
        for profile in [ "deep_research", "podcast", "research_to_podcast", "all_agents", "minimal" ]:
            path = resolve_script_path( profile, scripts_dir )
            with open( path, "r" ) as f:
                script = json.load( f )
            assert "sender_ids" in script, f"{profile} missing sender_ids field"
            assert isinstance( script[ "sender_ids" ], list ), f"{profile} sender_ids is not a list"
            assert len( script[ "sender_ids" ] ) >= 1, f"{profile} sender_ids is empty"
            for sid in script[ "sender_ids" ]:
                assert isinstance( sid, str ), f"{profile} sender_ids contains non-string: {sid}"
                assert "@" in sid, f"{profile} sender_id missing @: {sid}"

    def test_accepted_senders_parameter_overrides_script( self ):
        """Explicit accepted_senders parameter takes priority over script field."""
        scripts_dir = cu.get_project_root() + NOTIFICATION_PROXY_SCRIPTS_DIR
        script_path = resolve_script_path( "deep_research", scripts_dir )

        custom_senders = [ "custom.sender@lupin.deepily.ai" ]

        with patch( "cosa.agents.notification_proxy.strategies.llm_script_matcher.LlmClientFactory" ) as MockFactory:
            mock_factory = MagicMock()
            mock_client  = MagicMock()
            MockFactory.return_value = mock_factory
            mock_factory.get_client.return_value = mock_client

            strategy = LlmScriptMatcherStrategy(
                script_path      = script_path,
                accepted_senders = custom_senders,
                debug            = False
            )

        assert strategy.accepted_senders == custom_senders

    def test_responder_passes_sender_ids_to_rules( self ):
        """NotificationResponder passes sender_ids from script to ExpediterRuleStrategy."""
        responder = NotificationResponder( "deep_research", strategy="rules" )
        assert responder.rule_strategy.accepted_senders == [ "arg.expeditor@lupin.deepily.ai" ]


# ============================================================================
# Test Config Additions
# ============================================================================

class TestConfigAdditions:
    """Tests for new config constants."""

    def test_strategy_choices( self ):
        """Strategy choices include expected values."""
        assert "llm_script" in STRATEGY_CHOICES
        assert "rules" in STRATEGY_CHOICES
        assert "auto" in STRATEGY_CHOICES

    def test_default_strategy( self ):
        """Default strategy is llm_script."""
        assert DEFAULT_STRATEGY == "llm_script"

    def test_scripts_dir_constant( self ):
        """Scripts directory constant is set."""
        assert NOTIFICATION_PROXY_SCRIPTS_DIR == "/src/conf/notification-proxy-scripts"


# ============================================================================
# Test Responder with Strategy Mode
# ============================================================================

class TestResponderStrategyMode:
    """Tests for NotificationResponder with different strategy modes."""

    def test_rules_mode_no_script_strategy( self ):
        """Rules mode does not create script strategy."""
        responder = NotificationResponder( "deep_research", strategy="rules" )
        assert responder.script_strategy is None
        assert responder.rule_strategy is not None
        assert responder.strategy_mode == "rules"

    def test_stats_include_script_matcher( self ):
        """Stats dict includes script_matcher_used counter."""
        responder = NotificationResponder( "deep_research", strategy="rules" )
        assert "script_matcher_used" in responder.stats
        assert responder.stats[ "script_matcher_used" ] == 0


# ============================================================================
# Test Multi-Sender Integration
# ============================================================================

class TestMultiSenderIntegration:
    """Tests for proxy_integration_test profile and multi-sender Q&A script."""

    def test_proxy_integration_test_profile_exists( self ):
        """proxy_integration_test profile is present in TEST_PROFILES."""
        assert "proxy_integration_test" in TEST_PROFILES

    def test_proxy_integration_test_profile_has_description( self ):
        """proxy_integration_test profile has a description field."""
        profile = TEST_PROFILES[ "proxy_integration_test" ]
        assert "description" in profile

    def test_proxy_integration_test_profile_covers_expediter_args( self ):
        """proxy_integration_test profile covers all expediter answer keys."""
        profile       = TEST_PROFILES[ "proxy_integration_test" ]
        expected_keys = [ "query", "budget", "audience", "audience_context", "research", "languages" ]
        for key in expected_keys:
            assert key in profile, f"proxy_integration_test missing '{key}'"

    def test_proxy_integration_test_profile_covers_crud_confirmation( self ):
        """proxy_integration_test profile includes confirmation answer."""
        profile = TEST_PROFILES[ "proxy_integration_test" ]
        assert "confirmation" in profile
        assert profile[ "confirmation" ] == "yes"

    def test_integration_script_has_multi_sender( self ):
        """proxy-integration-test.json has multiple sender_ids."""
        scripts_dir = cu.get_project_root() + NOTIFICATION_PROXY_SCRIPTS_DIR
        path = resolve_script_path( "proxy_integration_test", scripts_dir )
        with open( path, "r" ) as f:
            script = json.load( f )
        assert len( script[ "sender_ids" ] ) >= 2
        assert "arg.expeditor@lupin.deepily.ai" in script[ "sender_ids" ]
        assert "crud.agent@lupin.deepily.ai" in script[ "sender_ids" ]

    def test_integration_script_has_expediter_entries( self ):
        """proxy-integration-test.json includes expediter question entries."""
        scripts_dir = cu.get_project_root() + NOTIFICATION_PROXY_SCRIPTS_DIR
        path = resolve_script_path( "proxy_integration_test", scripts_dir )
        with open( path, "r" ) as f:
            script = json.load( f )

        query_entries = [ e for e in script[ "entries" ] if e[ "arg_name" ] == "query" ]
        assert len( query_entries ) >= 1, "No query entries found"

    def test_integration_script_has_crud_entries( self ):
        """proxy-integration-test.json includes CRUD confirmation entries."""
        scripts_dir = cu.get_project_root() + NOTIFICATION_PROXY_SCRIPTS_DIR
        path = resolve_script_path( "proxy_integration_test", scripts_dir )
        with open( path, "r" ) as f:
            script = json.load( f )

        crud_entries = [
            e for e in script[ "entries" ]
            if e.get( "agents" ) and "crud" in e[ "agents" ]
        ]
        assert len( crud_entries ) >= 2, f"Expected >= 2 CRUD entries, got {len( crud_entries )}"

    def test_responder_with_integration_profile_accepts_expediter( self ):
        """Responder with proxy_integration_test profile accepts expediter sender."""
        responder = NotificationResponder( "proxy_integration_test", strategy="rules" )
        assert responder.rule_strategy.can_handle( {
            "sender_id"          : "arg.expeditor@lupin.deepily.ai",
            "response_requested" : True
        } )

    def test_responder_with_integration_profile_accepts_crud( self ):
        """Responder with proxy_integration_test profile accepts CRUD sender."""
        responder = NotificationResponder( "proxy_integration_test", strategy="rules" )
        assert responder.rule_strategy.can_handle( {
            "sender_id"          : "crud.agent@lupin.deepily.ai",
            "response_requested" : True
        } )

    def test_all_agents_script_includes_crud_sender( self ):
        """all-agents.json sender_ids includes crud.agent sender."""
        scripts_dir = cu.get_project_root() + NOTIFICATION_PROXY_SCRIPTS_DIR
        path = resolve_script_path( "all_agents", scripts_dir )
        with open( path, "r" ) as f:
            script = json.load( f )
        assert "crud.agent@lupin.deepily.ai" in script[ "sender_ids" ]


# ============================================================================
# Run inline if needed
# ============================================================================

if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
