"""
Unit tests for Bug Fix Expediter Orchestrator — Phase 2.

Tests prompt construction, JSON parsing, orchestrator construction,
SDK delegation, voice gate, notifications, cancellation, and user messages.
"""

import json
import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cosa.agents.bug_fix_expediter.state import (
    BFEPhase,
    DeadJobContext,
    DiagnosisResult,
)
from cosa.agents.bug_fix_expediter.config import BugFixExpediterConfig
from cosa.agents.bug_fix_expediter.prompts.diagnosis import (
    DIAGNOSIS_SYSTEM_PROMPT,
    build_diagnosis_prompt,
)
from cosa.agents.bug_fix_expediter.orchestrator import (
    BFEOrchestrator,
    SDK_AVAILABLE,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def dead_job_context():
    """Create a standard DeadJobContext for testing."""
    return DeadJobContext(
        id_hash          = "dr-abc12345::user1",
        job_type         = "deep_research",
        user_id          = "user1",
        user_email       = "test@example.com",
        session_id       = "wise-penguin",
        status           = "failed",
        question_text    = "What is quantum computing?",
        error            = "KeyError: 'missing_config_key'",
        stack_trace      = "Traceback (most recent call last):\n  File \"cli.py\", line 42, in run\n    config['missing_config_key']",
        routing_command  = "research",
        duration_seconds = 45.2,
        metadata_json    = { "model": "opus", "tokens_used": 1500 },
        created_at       = "2026-03-30T10:00:00",
        started_at       = "2026-03-30T10:00:05",
        completed_at     = "2026-03-30T10:00:50",
    )


@pytest.fixture
def minimal_context():
    """Create a DeadJobContext with minimal (None) optional fields."""
    return DeadJobContext(
        id_hash       = "bfe-min::u1",
        job_type      = "math_agent",
        user_id       = "u1",
        user_email    = "min@test.com",
        session_id    = "s1",
        status        = "interrupted",
        question_text = "2+2",
    )


@pytest.fixture
def config():
    """Create a default BugFixExpediterConfig."""
    return BugFixExpediterConfig()


@pytest.fixture
def orchestrator( dead_job_context, config ):
    """Create a BFEOrchestrator with standard test fixtures."""
    return BFEOrchestrator(
        dead_job_context = dead_job_context,
        extra_context    = "User says it worked yesterday",
        config           = config,
        session_id       = "wise-penguin",
        job_id           = "bfe-test123",
        debug            = True,
    )


@pytest.fixture
def sample_diagnosis():
    """Create a sample DiagnosisResult."""
    return DiagnosisResult(
        root_cause          = "Missing config key 'missing_config_key' in lupin-app.ini",
        error_category      = "config",
        confidence          = 0.85,
        evidence            = [ "KeyError at cli.py:42", "Key not in INI file" ],
        affected_components = [ "src/conf/lupin-app.ini", "src/cosa/agents/deep_research/cli.py" ],
        is_transient        = False,
    )


VALID_DIAGNOSIS_JSON = json.dumps( {
    "root_cause"          : "Missing config key",
    "error_category"      : "config",
    "confidence"          : 0.9,
    "evidence"            : [ "KeyError at line 42" ],
    "affected_components" : [ "config.py" ],
    "is_transient"        : False,
} )


# =============================================================================
# 1. Prompt Construction Tests (9 tests)
# =============================================================================

class TestPromptConstruction:
    """Tests for diagnosis prompt building."""

    def test_prompt_includes_error( self, dead_job_context ):
        prompt = build_diagnosis_prompt( dead_job_context )
        assert "KeyError: 'missing_config_key'" in prompt

    def test_prompt_includes_stack_trace( self, dead_job_context ):
        prompt = build_diagnosis_prompt( dead_job_context )
        assert "cli.py\", line 42" in prompt

    def test_prompt_includes_job_type( self, dead_job_context ):
        prompt = build_diagnosis_prompt( dead_job_context )
        assert "deep_research" in prompt

    def test_prompt_includes_question_text( self, dead_job_context ):
        prompt = build_diagnosis_prompt( dead_job_context )
        assert "quantum computing" in prompt

    def test_prompt_includes_metadata( self, dead_job_context ):
        prompt = build_diagnosis_prompt( dead_job_context )
        assert "opus" in prompt
        assert "1500" in prompt

    def test_prompt_handles_none_fields( self, minimal_context ):
        prompt = build_diagnosis_prompt( minimal_context )
        assert "No error message available" in prompt
        assert "No stack trace available" in prompt
        assert "None provided" in prompt

    def test_prompt_includes_extra_context( self, dead_job_context ):
        prompt = build_diagnosis_prompt( dead_job_context, extra_context="Check the config file" )
        assert "Check the config file" in prompt

    def test_refinement_prompt_includes_prior_diagnosis( self, dead_job_context, sample_diagnosis ):
        prompt = build_diagnosis_prompt(
            dead_job_context, iteration=2, prior_diagnosis=sample_diagnosis
        )
        assert "Missing config key" in prompt
        assert "investigate more deeply" in prompt.lower()

    def test_refinement_prompt_includes_confidence( self, dead_job_context, sample_diagnosis ):
        prompt = build_diagnosis_prompt(
            dead_job_context, iteration=2, prior_diagnosis=sample_diagnosis
        )
        assert "85%" in prompt


# =============================================================================
# 2. JSON Parsing Tests (7 tests)
# =============================================================================

class TestJSONParsing:
    """Tests for DiagnosisResult JSON parsing."""

    def test_parse_valid_json( self, orchestrator ):
        result = orchestrator._parse_diagnosis_result( VALID_DIAGNOSIS_JSON )
        assert result.root_cause == "Missing config key"
        assert result.confidence == 0.9
        assert result.error_category == "config"

    def test_parse_with_markdown_fences( self, orchestrator ):
        wrapped = f"Here is my diagnosis:\n\n```json\n{VALID_DIAGNOSIS_JSON}\n```\n\nDone."
        result = orchestrator._parse_diagnosis_result( wrapped )
        assert result.root_cause == "Missing config key"

    def test_parse_embedded_in_text( self, orchestrator ):
        embedded = f"After analysis, I found the issue.\n\n{VALID_DIAGNOSIS_JSON}\n\nThat concludes my investigation."
        result = orchestrator._parse_diagnosis_result( embedded )
        assert result.root_cause == "Missing config key"

    def test_parse_invalid_json_fallback( self, orchestrator ):
        result = orchestrator._parse_diagnosis_result( "No JSON here whatsoever" )
        assert result.confidence == 0.1
        assert result.error_category == "unknown"
        assert "No JSON here" in result.root_cause

    def test_parse_missing_optional_fields_defaults( self, orchestrator ):
        minimal = json.dumps( {
            "root_cause"     : "Some cause",
            "error_category" : "code_bug",
            "confidence"     : 0.7,
        } )
        result = orchestrator._parse_diagnosis_result( minimal )
        assert result.evidence == []
        assert result.affected_components == []
        assert result.is_transient == False

    def test_parse_all_error_categories( self, orchestrator ):
        for category in [ "config", "code_bug", "dependency", "timeout", "resource", "unknown" ]:
            data = json.dumps( {
                "root_cause"     : f"Cause for {category}",
                "error_category" : category,
                "confidence"     : 0.5,
            } )
            result = orchestrator._parse_diagnosis_result( data )
            assert result.error_category == category

    def test_extract_last_json_object( self ):
        text = 'Some text {"a": 1} more text {"b": 2}'
        result = BFEOrchestrator._extract_last_json_object( text )
        assert result == '{"b": 2}'


# =============================================================================
# 3. Orchestrator Construction Tests (2 tests)
# =============================================================================

class TestOrchestratorConstruction:
    """Tests for BFEOrchestrator initialization."""

    def test_default_init( self, orchestrator ):
        assert orchestrator.current_phase == BFEPhase.PACKAGING
        assert orchestrator.job_id == "bfe-test123"
        assert orchestrator._stop_requested == False
        assert orchestrator._diagnosis_group_id.startswith( "pg-" )

    def test_init_with_cancel_check( self, dead_job_context, config ):
        cancel_flag = False
        orch = BFEOrchestrator(
            dead_job_context = dead_job_context,
            extra_context    = "",
            config           = config,
            session_id       = "s1",
            job_id           = "bfe-test",
            cancel_check     = lambda: cancel_flag,
        )
        assert orch._is_cancelled() == False
        cancel_flag = True
        assert orch._is_cancelled() == True


# =============================================================================
# 4. Agent Options Tests (1 test)
# =============================================================================

class TestAgentOptions:
    """Tests for Lead agent option construction."""

    @pytest.mark.skipif( not SDK_AVAILABLE, reason="Claude Agent SDK not installed" )
    def test_build_lead_options_read_only( self, orchestrator ):
        opts = orchestrator._build_lead_options()
        assert opts.permission_mode == "plan"
        assert opts.model == "claude-opus-4-6"
        assert "Read" in opts.tools
        assert "Glob" in opts.tools
        assert "Grep" in opts.tools
        assert "Bash" in opts.tools


# =============================================================================
# 5. SDK Delegation Tests (5 tests)
# =============================================================================

class TestSDKDelegation:
    """Tests for SDK delegation and diagnosis flow."""

    @pytest.mark.skipif( not SDK_AVAILABLE, reason="Claude Agent SDK not installed" )
    def test_run_diagnosis_happy_path( self, orchestrator ):
        """Mock SDK returns valid JSON → DiagnosisResult."""
        from claude_agent_sdk import AssistantMessage, TextBlock

        mock_messages = [
            AssistantMessage( content=[ TextBlock( text=VALID_DIAGNOSIS_JSON ) ], model="claude-opus-4-6" ),
        ]

        mock_voice_io = MagicMock()
        mock_voice_io.notify = AsyncMock()
        mock_cosa = MagicMock()
        mock_cosa.ask_confirmation = AsyncMock( return_value=True )

        with patch( "cosa.agents.bug_fix_expediter.orchestrator.sdk_query" ) as mock_sdk:
            async def mock_gen( prompt, options ):
                for m in mock_messages:
                    yield m
            mock_sdk.side_effect = mock_gen

            with patch( "cosa.agents.bug_fix_expediter.orchestrator.BFEOrchestrator._voice_gate_diagnosis", new_callable=AsyncMock ) as mock_gate:
                mock_gate.side_effect = lambda d, *args, **kwargs: d  # pass through
                result = asyncio.run(
                    orchestrator.run_diagnosis()
                )

        assert result.root_cause == "Missing config key"
        assert result.confidence == 0.9

    @pytest.mark.skipif( not SDK_AVAILABLE, reason="Claude Agent SDK not installed" )
    def test_run_diagnosis_low_confidence_retries( self, orchestrator ):
        """Low confidence triggers refinement iteration."""
        from claude_agent_sdk import AssistantMessage, TextBlock

        low_conf  = json.dumps( { "root_cause": "Maybe X", "error_category": "unknown", "confidence": 0.3 } )
        high_conf = json.dumps( { "root_cause": "Definitely Y", "error_category": "config", "confidence": 0.9 } )

        call_count = [ 0 ]

        async def mock_gen( prompt, options ):
            call_count[ 0 ] += 1
            text = low_conf if call_count[ 0 ] == 1 else high_conf
            yield AssistantMessage( content=[ TextBlock( text=text ) ], model="claude-opus-4-6" )

        with patch( "cosa.agents.bug_fix_expediter.orchestrator.sdk_query", side_effect=mock_gen ):
            with patch( "cosa.agents.bug_fix_expediter.orchestrator.BFEOrchestrator._voice_gate_diagnosis", new_callable=AsyncMock ) as mock_gate:
                mock_gate.side_effect = lambda d, *args, **kwargs: d
                result = asyncio.run(
                    orchestrator.run_diagnosis()
                )

        assert call_count[ 0 ] == 2
        assert result.root_cause == "Definitely Y"
        assert result.confidence == 0.9

    @pytest.mark.skipif( not SDK_AVAILABLE, reason="Claude Agent SDK not installed" )
    def test_run_diagnosis_max_iterations_cap( self, orchestrator ):
        """Iterations cap at max_diagnosis_iterations."""
        from claude_agent_sdk import AssistantMessage, TextBlock

        low_conf   = json.dumps( { "root_cause": "Low", "error_category": "unknown", "confidence": 0.2 } )
        call_count = [ 0 ]

        async def mock_gen( prompt, options ):
            call_count[ 0 ] += 1
            yield AssistantMessage( content=[ TextBlock( text=low_conf ) ], model="claude-opus-4-6" )

        orchestrator.config.max_diagnosis_iterations = 2

        with patch( "cosa.agents.bug_fix_expediter.orchestrator.sdk_query", side_effect=mock_gen ):
            with patch( "cosa.agents.bug_fix_expediter.orchestrator.BFEOrchestrator._voice_gate_diagnosis", new_callable=AsyncMock ) as mock_gate:
                mock_gate.side_effect = lambda d, *args, **kwargs: d
                result = asyncio.run(
                    orchestrator.run_diagnosis()
                )

        assert call_count[ 0 ] == 2  # Capped at max
        assert result.confidence == 0.2

    def test_run_diagnosis_sdk_unavailable( self, dead_job_context, config ):
        """SDK_AVAILABLE=False → graceful fallback."""
        orch = BFEOrchestrator(
            dead_job_context = dead_job_context,
            extra_context    = "",
            config           = config,
            session_id       = "s1",
            job_id           = "bfe-test",
        )

        with patch( "cosa.agents.bug_fix_expediter.orchestrator.SDK_AVAILABLE", False ):
            result = asyncio.run(
                orch.run_diagnosis()
            )

        assert result.confidence == 0.1
        assert "SDK not installed" in result.root_cause

    @pytest.mark.skipif( not SDK_AVAILABLE, reason="Claude Agent SDK not installed" )
    def test_run_diagnosis_sdk_exception( self, orchestrator ):
        """SDK raises exception → None from delegate, fallback diagnosis."""
        async def mock_gen( prompt, options ):
            raise RuntimeError( "SDK connection failed" )
            yield  # Make it a generator

        with patch( "cosa.agents.bug_fix_expediter.orchestrator.sdk_query", side_effect=mock_gen ):
            with patch( "cosa.agents.bug_fix_expediter.orchestrator.BFEOrchestrator._voice_gate_diagnosis", new_callable=AsyncMock ) as mock_gate:
                mock_gate.side_effect = lambda d, *args, **kwargs: d
                result = asyncio.run(
                    orchestrator.run_diagnosis()
                )

        # Should get fallback diagnosis (all iterations returned None)
        assert result.confidence == 0.1


# =============================================================================
# 6. Voice Gate Tests (4 tests)
# =============================================================================

class TestVoiceGate:
    """Tests for voice-gated diagnosis confirmation."""

    def test_auto_approve_when_disabled( self, orchestrator, sample_diagnosis ):
        """require_user_confirm=False → auto-approve."""
        orchestrator.config.require_user_confirm = False
        mock_voice_io = MagicMock()
        mock_cosa     = MagicMock()

        result = asyncio.run(
            orchestrator._voice_gate_diagnosis( sample_diagnosis, mock_voice_io, mock_cosa )
        )
        assert result == sample_diagnosis

    def test_user_approves( self, orchestrator, sample_diagnosis ):
        """User says yes → diagnosis returned as-is."""
        mock_voice_io = MagicMock()
        mock_cosa     = MagicMock()
        mock_cosa.ask_confirmation = AsyncMock( return_value=True )

        result = asyncio.run(
            orchestrator._voice_gate_diagnosis( sample_diagnosis, mock_voice_io, mock_cosa )
        )
        assert result == sample_diagnosis

    @pytest.mark.skipif( not SDK_AVAILABLE, reason="Claude Agent SDK not installed" )
    def test_user_rejects_with_feedback( self, orchestrator, sample_diagnosis ):
        """User rejects + provides feedback → refinement iteration."""
        from claude_agent_sdk import AssistantMessage, TextBlock

        better_json = json.dumps( {
            "root_cause"     : "Refined cause",
            "error_category" : "code_bug",
            "confidence"     : 0.95,
        } )

        mock_voice_io         = MagicMock()
        mock_voice_io.notify  = AsyncMock()
        mock_cosa             = MagicMock()
        mock_cosa.ask_confirmation = AsyncMock( return_value=False )
        mock_cosa.get_feedback     = AsyncMock( return_value="The root cause is actually a code bug" )

        async def mock_gen( prompt, options ):
            yield AssistantMessage( content=[ TextBlock( text=better_json ) ], model="opus" )

        with patch( "cosa.agents.bug_fix_expediter.orchestrator.sdk_query", side_effect=mock_gen ):
            result = asyncio.run(
                orchestrator._voice_gate_diagnosis( sample_diagnosis, mock_voice_io, mock_cosa )
            )

        assert result.root_cause == "Refined cause"
        assert result.confidence == 0.95

    def test_user_rejects_no_feedback( self, orchestrator, sample_diagnosis ):
        """User rejects but no feedback → original diagnosis returned."""
        mock_voice_io = MagicMock()
        mock_cosa     = MagicMock()
        mock_cosa.ask_confirmation = AsyncMock( return_value=False )
        mock_cosa.get_feedback     = AsyncMock( return_value=None )

        result = asyncio.run(
            orchestrator._voice_gate_diagnosis( sample_diagnosis, mock_voice_io, mock_cosa )
        )
        assert result == sample_diagnosis


# =============================================================================
# 7. Notifications + Progress Tests (3 tests)
# =============================================================================

class TestNotifications:
    """Tests for notification routing."""

    def test_notify_includes_job_id( self, orchestrator ):
        mock_voice_io        = MagicMock()
        mock_voice_io.notify = AsyncMock()

        asyncio.run(
            orchestrator._notify( mock_voice_io, "test message" )
        )

        mock_voice_io.notify.assert_called_once()
        call_kwargs = mock_voice_io.notify.call_args[ 1 ]
        assert call_kwargs[ "job_id" ] == "bfe-test123"

    def test_notify_includes_queue_name( self, orchestrator ):
        mock_voice_io        = MagicMock()
        mock_voice_io.notify = AsyncMock()

        asyncio.run(
            orchestrator._notify( mock_voice_io, "test message" )
        )

        call_kwargs = mock_voice_io.notify.call_args[ 1 ]
        assert call_kwargs[ "queue_name" ] == "run"

    def test_notify_includes_progress_group_id( self, orchestrator ):
        mock_voice_io        = MagicMock()
        mock_voice_io.notify = AsyncMock()

        asyncio.run(
            orchestrator._notify( mock_voice_io, "test message" )
        )

        call_kwargs = mock_voice_io.notify.call_args[ 1 ]
        assert call_kwargs[ "progress_group_id" ].startswith( "pg-" )


# =============================================================================
# 8. Cancellation Tests (3 tests)
# =============================================================================

class TestCancellation:
    """Tests for cancellation support."""

    def test_is_cancelled_via_cancel_check( self, dead_job_context, config ):
        flag = [ False ]
        orch = BFEOrchestrator(
            dead_job_context = dead_job_context,
            extra_context    = "",
            config           = config,
            session_id       = "s1",
            job_id           = "bfe-test",
            cancel_check     = lambda: flag[ 0 ],
        )
        assert orch._is_cancelled() == False
        flag[ 0 ] = True
        assert orch._is_cancelled() == True

    def test_is_cancelled_via_stop_requested( self, orchestrator ):
        assert orchestrator._is_cancelled() == False
        orchestrator._stop_requested = True
        assert orchestrator._is_cancelled() == True

    @pytest.mark.skipif( not SDK_AVAILABLE, reason="Claude Agent SDK not installed" )
    def test_run_diagnosis_exits_on_cancellation( self, orchestrator ):
        """Cancellation between iterations → returns best diagnosis so far."""
        from claude_agent_sdk import AssistantMessage, TextBlock

        low_conf   = json.dumps( { "root_cause": "Partial", "error_category": "unknown", "confidence": 0.3 } )
        call_count = [ 0 ]

        async def mock_gen( prompt, options ):
            call_count[ 0 ] += 1
            # Cancel after first iteration
            orchestrator._stop_requested = True
            yield AssistantMessage( content=[ TextBlock( text=low_conf ) ], model="opus" )

        with patch( "cosa.agents.bug_fix_expediter.orchestrator.sdk_query", side_effect=mock_gen ):
            with patch( "cosa.agents.bug_fix_expediter.orchestrator.BFEOrchestrator._voice_gate_diagnosis", new_callable=AsyncMock ) as mock_gate:
                mock_gate.side_effect = lambda d, *args, **kwargs: d
                result = asyncio.run(
                    orchestrator.run_diagnosis()
                )

        assert call_count[ 0 ] == 1  # Only one iteration before cancellation
        assert result.root_cause == "Partial"


# =============================================================================
# 9. User Message Queue Tests (3 tests)
# =============================================================================

class TestUserMessageQueue:
    """Tests for ad hoc user message handling."""

    def test_queue_user_message( self, orchestrator ):
        orchestrator.queue_user_message( "test msg" )
        assert not orchestrator._user_messages.empty()

    def test_queue_urgent_sets_interrupt( self, orchestrator ):
        orchestrator.queue_user_message( "urgent!", urgent=True )
        assert orchestrator._urgent_interrupt.is_set()

    def test_drain_clears_queue_and_event( self, orchestrator ):
        orchestrator.queue_user_message( "msg1" )
        orchestrator.queue_user_message( "msg2", urgent=True )

        messages = orchestrator._drain_user_messages()
        assert len( messages ) == 2
        assert messages[ 0 ] == "msg1"
        assert messages[ 1 ] == "msg2"
        assert not orchestrator._urgent_interrupt.is_set()
        assert orchestrator._user_messages.empty()
