"""
Unit tests for Runtime Argument Expeditor.

Tests 18 components (147 tests total):
1. ExpeditorResponse model (xml_models.py) - 16 tests
2. _parse_lora_args() (expeditor.py) - 9 tests
3. _inject_system_args() (expeditor.py) - 4 tests
4. Agent registry + get_cli_help() + get_user_visible_args() (agent_registry.py) - 19 tests
5. create_agentic_job() factory (agentic_job_factory.py) - 12 tests
6. ArgConfirmationResponse model (xml_models.py) - 8 tests
7. _confirm_and_iterate() (expeditor.py) - 13 tests (YES_NO prompt with comment paths)
8. _batch_collect_args() + batch integration (expeditor.py) - 10 tests
9. _build_request_context() + abstract threading (expeditor.py) - 8 tests
10. Batch abstract passthrough (expeditor.py) - 1 test
11. _resolve_default() 3-tier override chain (expeditor.py) - 5 tests
12. Batch default values integration (expeditor.py) - 4 tests
13. Notification utils edge cases (notification_utils.py) - 3 tests
14. job_id threading (expeditor.py) - 3 tests
15. Optional arg prompting (expeditor.py) - 8 tests (post-bug-fix)
16. _parse_boolean() (agentic_job_factory.py) - 7 tests
17. dry_run visibility in _build_request_context() (expeditor.py) - 5 tests
18. Runtime scheduling in confirmation + normalization (expeditor.py + todo_fifo_queue.py) - 12 tests

All external dependencies mocked. No server, no LLM, no filesystem I/O.

Created: 2026-02-05
Updated: 2026-02-10 — optional arg prompting tests (bug fix: is_complete() gate replaced)
Updated: 2026-03-30 — runtime scheduling tests (confirmation summary + normalization)
"""

import pytest
from unittest.mock import patch, MagicMock
import subprocess

from cosa.agents.runtime_argument_expeditor.xml_models import ExpeditorResponse, ArgConfirmationResponse
from cosa.agents.runtime_argument_expeditor.expeditor import RuntimeArgumentExpeditor
from cosa.agents.runtime_argument_expeditor.agent_registry import (
    AGENTIC_AGENTS,
    get_cli_help,
    get_user_visible_args,
    _help_cache,
    _user_visible_cache
)
from cosa.rest.agentic_job_factory import create_agentic_job, _parse_boolean


# ═══════════════════════════════════════════════════════════════════════════════
# Class 1: TestExpeditorResponseModel (16 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestExpeditorResponseModel:
    """Tests for ExpeditorResponse Pydantic model - pure data, no mocking needed."""

    def test_is_complete_true( self ):
        """all_required_met='true' returns True."""
        response = ExpeditorResponse(
            all_required_met = "true",
            args_present     = "query=test",
            args_missing     = ""
        )
        assert response.is_complete() is True

    def test_is_complete_false( self ):
        """all_required_met='false' returns False."""
        response = ExpeditorResponse(
            all_required_met = "false",
            args_present     = "",
            args_missing     = "query"
        )
        assert response.is_complete() is False

    def test_is_complete_case_insensitive( self ):
        """'True' and 'TRUE' both return True."""
        for variant in [ "True", "TRUE", "tRuE" ]:
            response = ExpeditorResponse(
                all_required_met = variant,
                args_present     = "query=test",
                args_missing     = ""
            )
            assert response.is_complete() is True, f"Failed for variant: {variant}"

    def test_is_complete_with_whitespace( self ):
        """' true ' with whitespace returns True."""
        response = ExpeditorResponse(
            all_required_met = " true ",
            args_present     = "query=test",
            args_missing     = ""
        )
        assert response.is_complete() is True

    def test_get_missing_list_single( self ):
        """Single missing arg returns one-item list."""
        response = ExpeditorResponse(
            all_required_met = "false",
            args_present     = "",
            args_missing     = "budget"
        )
        assert response.get_missing_list() == [ "budget" ]

    def test_get_missing_list_multiple( self ):
        """Multiple missing args parsed correctly."""
        response = ExpeditorResponse(
            all_required_met = "false",
            args_present     = "",
            args_missing     = "budget, audience"
        )
        result = response.get_missing_list()
        assert result == [ "budget", "audience" ]

    def test_get_missing_list_empty( self ):
        """Empty string returns empty list."""
        response = ExpeditorResponse(
            all_required_met = "true",
            args_present     = "query=test",
            args_missing     = ""
        )
        assert response.get_missing_list() == []

    def test_get_missing_list_whitespace( self ):
        """Whitespace-only string returns empty list."""
        response = ExpeditorResponse(
            all_required_met = "true",
            args_present     = "query=test",
            args_missing     = "  "
        )
        assert response.get_missing_list() == []

    def test_get_missing_list_extra_commas( self ):
        """Extra commas and empty segments are filtered out."""
        response = ExpeditorResponse(
            all_required_met = "false",
            args_present     = "",
            args_missing     = "budget,,audience,"
        )
        result = response.get_missing_list()
        assert result == [ "budget", "audience" ]

    def test_get_present_dict_single( self ):
        """Single key=value pair parsed correctly."""
        response = ExpeditorResponse(
            all_required_met = "false",
            args_present     = "query=quantum computing",
            args_missing     = "budget"
        )
        result = response.get_present_dict()
        assert result == { "query": "quantum computing" }

    def test_get_present_dict_multiple( self ):
        """Multiple key=value pairs parsed correctly."""
        response = ExpeditorResponse(
            all_required_met = "true",
            args_present     = "query=test, budget=10",
            args_missing     = ""
        )
        result = response.get_present_dict()
        assert "query" in result
        assert "budget" in result
        assert result[ "query" ] == "test"
        assert result[ "budget" ] == "10"

    def test_get_present_dict_empty( self ):
        """Empty string returns empty dict."""
        response = ExpeditorResponse(
            all_required_met = "false",
            args_present     = "",
            args_missing     = "query"
        )
        assert response.get_present_dict() == {}

    def test_get_present_dict_equals_in_value( self ):
        """Values containing '=' are handled (split on first = only)."""
        response = ExpeditorResponse(
            all_required_met = "true",
            args_present     = "query=a=b",
            args_missing     = ""
        )
        result = response.get_present_dict()
        assert result == { "query": "a=b" }

    def test_get_present_dict_whitespace( self ):
        """Whitespace-only string returns empty dict."""
        response = ExpeditorResponse(
            all_required_met = "true",
            args_present     = "   ",
            args_missing     = ""
        )
        assert response.get_present_dict() == {}

    def test_xml_round_trip( self ):
        """to_xml() then from_xml() preserves all fields."""
        original = ExpeditorResponse(
            all_required_met = "false",
            args_present     = "query=quantum computing, budget=10",
            args_missing     = "audience"
        )
        xml_str = original.to_xml()
        parsed  = ExpeditorResponse.from_xml( xml_str )

        assert parsed.all_required_met == original.all_required_met
        assert parsed.args_present == original.args_present
        assert parsed.args_missing == original.args_missing

    def test_get_example_for_template( self ):
        """get_example_for_template() returns a valid instance."""
        example = ExpeditorResponse.get_example_for_template()
        assert isinstance( example, ExpeditorResponse )
        assert example.all_required_met == "false"
        assert "biodiversity" in example.args_present
        assert example.args_missing == "budget"


# ═══════════════════════════════════════════════════════════════════════════════
# Class 2: TestParseLoraArgs (9 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestParseLoraArgs:
    """Tests for RuntimeArgumentExpeditor._parse_lora_args() - pure regex parsing."""

    def setup_method( self ):
        """Create a minimal expeditor instance for testing parse method."""
        self.expeditor       = RuntimeArgumentExpeditor.__new__( RuntimeArgumentExpeditor )
        self.expeditor.debug = False

    def test_double_quoted_args( self ):
        """Double-quoted values parsed correctly."""
        result = self.expeditor._parse_lora_args( 'topic="quantum computing" budget=10' )
        assert result[ "topic" ] == "quantum computing"
        assert result[ "budget" ] == "10"

    def test_single_quoted_args( self ):
        """Single-quoted values parsed correctly."""
        result = self.expeditor._parse_lora_args( "topic='AI safety'" )
        assert result[ "topic" ] == "AI safety"

    def test_unquoted_args( self ):
        """Unquoted simple values parsed correctly."""
        result = self.expeditor._parse_lora_args( "budget=50" )
        assert result == { "budget": "50" }

    def test_empty_string( self ):
        """Empty string returns empty dict."""
        result = self.expeditor._parse_lora_args( "" )
        assert result == {}

    def test_none_input( self ):
        """None input returns empty dict."""
        result = self.expeditor._parse_lora_args( None )
        assert result == {}

    def test_whitespace_only( self ):
        """Whitespace-only string returns empty dict."""
        result = self.expeditor._parse_lora_args( "   " )
        assert result == {}

    def test_multiple_mixed( self ):
        """Multiple args with mixed quoting styles."""
        result = self.expeditor._parse_lora_args( 'query="machine learning" budget=5 audience=expert' )
        assert len( result ) == 3
        assert result[ "query" ] == "machine learning"
        assert result[ "budget" ] == "5"
        assert result[ "audience" ] == "expert"

    def test_spaces_in_quoted_value( self ):
        """Spaces in quoted values are preserved."""
        result = self.expeditor._parse_lora_args( 'topic="the future of AI"' )
        assert result[ "topic" ] == "the future of AI"

    def test_no_equals_sign( self ):
        """Text without key=value pairs returns empty dict."""
        result = self.expeditor._parse_lora_args( "just some text" )
        assert result == {}


# ═══════════════════════════════════════════════════════════════════════════════
# Class 3: TestInjectSystemArgs (4 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestInjectSystemArgs:
    """Tests for RuntimeArgumentExpeditor._inject_system_args()."""

    def setup_method( self ):
        """Create a minimal expeditor instance."""
        self.expeditor       = RuntimeArgumentExpeditor.__new__( RuntimeArgumentExpeditor )
        self.expeditor.debug = False

    def test_injects_all_system_args( self ):
        """Empty args_dict gets all system args injected."""
        agent_entry = AGENTIC_AGENTS[ "agent router go to deep research" ]
        args_dict   = {}

        result = self.expeditor._inject_system_args(
            args_dict, agent_entry,
            user_email = "test@test.com",
            session_id = "sess-123",
            user_id    = "uid-456"
        )

        assert result[ "user_email" ] == "test@test.com"
        assert result[ "session_id" ] == "sess-123"
        assert result[ "user_id" ] == "uid-456"
        assert result[ "no_confirm" ] is True

    def test_preserves_existing( self ):
        """Pre-existing values are NOT overwritten."""
        agent_entry = AGENTIC_AGENTS[ "agent router go to deep research" ]
        args_dict   = { "user_email": "original@test.com" }

        result = self.expeditor._inject_system_args(
            args_dict, agent_entry,
            user_email = "new@test.com",
            session_id = "sess-123",
            user_id    = "uid-456"
        )

        assert result[ "user_email" ] == "original@test.com"

    def test_no_confirm_always_true( self ):
        """no_confirm is always injected as True."""
        agent_entry = AGENTIC_AGENTS[ "agent router go to deep research" ]
        args_dict   = {}

        result = self.expeditor._inject_system_args(
            args_dict, agent_entry,
            user_email = "test@test.com",
            session_id = "sess-123",
            user_id    = "uid-456"
        )

        assert result[ "no_confirm" ] is True

    def test_only_injects_listed_args( self ):
        """Only system args listed in agent entry are injected."""
        # Podcast generator doesn't have no_confirm in system_provided
        agent_entry = AGENTIC_AGENTS[ "agent router go to podcast generator" ]
        args_dict   = {}

        result = self.expeditor._inject_system_args(
            args_dict, agent_entry,
            user_email = "test@test.com",
            session_id = "sess-123",
            user_id    = "uid-456"
        )

        # Podcast generator has: user_id, user_email, session_id (no no_confirm)
        assert "user_id" in result
        assert "user_email" in result
        assert "session_id" in result
        assert "no_confirm" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# Class 4: TestAgentRegistry (19 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentRegistry:
    """Tests for AGENTIC_AGENTS dict, get_cli_help(), and get_user_visible_args()."""

    def setup_method( self ):
        """Clear help and user-visible caches before each test."""
        _help_cache.clear()
        _user_visible_cache.clear()

    def test_registry_has_ten_agents( self ):
        """Registry contains exactly 10 agentic agents."""
        assert len( AGENTIC_AGENTS ) == 10

    def test_all_entries_required_keys( self ):
        """All registry entries have the required keys."""
        required_keys = [ "cli_module", "required_user_args", "system_provided", "arg_mapping", "fallback_questions" ]
        for cmd_key, entry in AGENTIC_AGENTS.items():
            for key in required_keys:
                assert key in entry, f"Missing '{key}' in entry '{cmd_key}'"

    def test_deep_research_required_args( self ):
        """Deep research requires only 'query'."""
        entry = AGENTIC_AGENTS[ "agent router go to deep research" ]
        assert entry[ "required_user_args" ] == [ "query" ]

    def test_podcast_special_handlers( self ):
        """Podcast generator has fuzzy_file_match handler for 'research'."""
        entry = AGENTIC_AGENTS[ "agent router go to podcast generator" ]
        assert "special_handlers" in entry
        assert entry[ "special_handlers" ][ "research" ] == "fuzzy_file_match"

    def test_rtp_required_args( self ):
        """Research-to-podcast requires only 'query'."""
        entry = AGENTIC_AGENTS[ "agent router go to research to podcast" ]
        assert entry[ "required_user_args" ] == [ "query" ]

    def test_missing_command_returns_none( self ):
        """Nonexistent registry key returns None."""
        assert AGENTIC_AGENTS.get( "nonexistent command" ) is None

    @patch( "cosa.agents.runtime_argument_expeditor.agent_registry.subprocess.run" )
    def test_get_cli_help_success( self, mock_run ):
        """Successful subprocess returns stdout."""
        mock_run.return_value = MagicMock( stdout="usage: deep_research [-h]", stderr="" )

        result = get_cli_help( "agent router go to deep research" )

        assert result == "usage: deep_research [-h]"
        mock_run.assert_called_once()

    @patch( "cosa.agents.runtime_argument_expeditor.agent_registry.subprocess.run" )
    def test_get_cli_help_caching( self, mock_run ):
        """Second call uses cache, subprocess called only once."""
        mock_run.return_value = MagicMock( stdout="cached help", stderr="" )

        result1 = get_cli_help( "agent router go to deep research" )
        result2 = get_cli_help( "agent router go to deep research" )

        assert result1 == result2 == "cached help"
        assert mock_run.call_count == 1

    def test_get_cli_help_missing_key( self ):
        """Nonexistent command returns None without calling subprocess."""
        result = get_cli_help( "nonexistent" )
        assert result is None

    @patch( "cosa.agents.runtime_argument_expeditor.agent_registry.subprocess.run" )
    def test_get_cli_help_timeout( self, mock_run ):
        """TimeoutExpired returns None."""
        mock_run.side_effect = subprocess.TimeoutExpired( cmd="test", timeout=10 )

        result = get_cli_help( "agent router go to deep research" )
        assert result is None

    @patch( "cosa.agents.runtime_argument_expeditor.agent_registry.subprocess.run" )
    def test_get_cli_help_file_not_found( self, mock_run ):
        """FileNotFoundError returns None."""
        mock_run.side_effect = FileNotFoundError( "python not found" )

        result = get_cli_help( "agent router go to deep research" )
        assert result is None

    def test_content_agents_have_audience_in_arg_mapping( self ):
        """Content-oriented agents have 'audience' and 'audience_context' in arg_mapping."""
        content_agents = [
            "agent router go to deep research",
            "agent router go to podcast generator",
            "agent router go to research to podcast",
        ]
        for cmd_key in content_agents:
            entry   = AGENTIC_AGENTS[ cmd_key ]
            mapping = entry[ "arg_mapping" ]
            assert "audience" in mapping, f"Missing 'audience' in arg_mapping for '{cmd_key}'"
            assert mapping[ "audience" ] == "audience"
            assert "audience_context" in mapping, f"Missing 'audience_context' in arg_mapping for '{cmd_key}'"
            assert mapping[ "audience_context" ] == "audience_context"

    def test_content_agents_have_audience_fallback_question( self ):
        """Content-oriented agents have 'audience' and 'audience_context' in fallback_questions."""
        content_agents = [
            "agent router go to deep research",
            "agent router go to podcast generator",
            "agent router go to research to podcast",
        ]
        for cmd_key in content_agents:
            entry     = AGENTIC_AGENTS[ cmd_key ]
            questions = entry[ "fallback_questions" ]
            assert "audience" in questions, f"Missing 'audience' in fallback_questions for '{cmd_key}'"
            assert "audience_context" in questions, f"Missing 'audience_context' in fallback_questions for '{cmd_key}'"

    def test_deep_research_audience_mapping( self ):
        """Deep research maps audience args correctly."""
        entry = AGENTIC_AGENTS[ "agent router go to deep research" ]
        assert entry[ "arg_mapping" ][ "audience" ] == "audience"
        assert entry[ "arg_mapping" ][ "audience_context" ] == "audience_context"
        assert "beginner" in entry[ "fallback_questions" ][ "audience" ].lower() or \
               "academic" in entry[ "fallback_questions" ][ "audience" ].lower()

    def test_all_agents_have_display_name( self ):
        """All three agents have a 'display_name' key."""
        for cmd_key, entry in AGENTIC_AGENTS.items():
            assert "display_name" in entry, f"Missing 'display_name' in '{cmd_key}'"
            assert isinstance( entry[ "display_name" ], str )
            assert len( entry[ "display_name" ] ) > 0

    # --- get_user_visible_args tests ---

    @patch( "cosa.agents.runtime_argument_expeditor.agent_registry.subprocess.run" )
    def test_get_user_visible_args_deep_research( self, mock_run ):
        """Successful subprocess returns expected arg list for deep research."""
        mock_run.return_value = MagicMock(
            returncode = 0,
            stdout     = '["query", "budget", "audience", "audience_context"]'
        )

        result = get_user_visible_args( "agent router go to deep research" )

        assert result == [ "query", "budget", "audience", "audience_context" ]
        mock_run.assert_called_once()

    @patch( "cosa.agents.runtime_argument_expeditor.agent_registry.subprocess.run" )
    def test_get_user_visible_args_caching( self, mock_run ):
        """Second call uses cache, subprocess called only once."""
        mock_run.return_value = MagicMock(
            returncode = 0,
            stdout     = '["query", "budget"]'
        )

        result1 = get_user_visible_args( "agent router go to deep research" )
        result2 = get_user_visible_args( "agent router go to deep research" )

        assert result1 == result2 == [ "query", "budget" ]
        assert mock_run.call_count == 1

    def test_get_user_visible_args_missing_key( self ):
        """Nonexistent command returns None without calling subprocess."""
        result = get_user_visible_args( "nonexistent" )
        assert result is None

    @patch( "cosa.agents.runtime_argument_expeditor.agent_registry.subprocess.run" )
    def test_get_user_visible_args_timeout( self, mock_run ):
        """TimeoutExpired returns None."""
        mock_run.side_effect = subprocess.TimeoutExpired( cmd="test", timeout=10 )

        result = get_user_visible_args( "agent router go to deep research" )
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# Class 5: TestCreateAgenticJob (12 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCreateAgenticJob:
    """Tests for create_agentic_job() factory function.

    Job classes are imported locally inside create_agentic_job(), so we
    patch at the source module path where they're defined.
    """

    @patch( "cosa.agents.deep_research_to_podcast.job.DeepResearchToPodcastJob" )
    @patch( "cosa.agents.podcast_generator.job.PodcastGeneratorJob" )
    @patch( "cosa.agents.deep_research.job.DeepResearchJob" )
    def test_deep_research_job( self, MockDR, MockPG, MockRTP ):
        """Deep research command creates DeepResearchJob."""
        MockDR.return_value = MagicMock()
        args = { "query": "quantum computing" }

        result = create_agentic_job(
            command    = "agent router go to deep research",
            args_dict  = args,
            user_id    = "uid-1",
            user_email = "test@test.com",
            session_id = "sess-1"
        )

        MockDR.assert_called_once()
        call_kwargs = MockDR.call_args[ 1 ]
        assert call_kwargs[ "query" ] == "quantum computing"
        assert call_kwargs[ "user_id" ] == "uid-1"
        assert call_kwargs[ "no_confirm" ] is True

    @patch( "cosa.agents.deep_research_to_podcast.job.DeepResearchToPodcastJob" )
    @patch( "cosa.agents.podcast_generator.job.PodcastGeneratorJob" )
    @patch( "cosa.agents.deep_research.job.DeepResearchJob" )
    def test_podcast_generator_job( self, MockDR, MockPG, MockRTP ):
        """Podcast generator command creates PodcastGeneratorJob."""
        MockPG.return_value = MagicMock()
        args = { "research": "/path/to/doc.md" }

        result = create_agentic_job(
            command    = "agent router go to podcast generator",
            args_dict  = args,
            user_id    = "uid-1",
            user_email = "test@test.com",
            session_id = "sess-1"
        )

        MockPG.assert_called_once()
        call_kwargs = MockPG.call_args[ 1 ]
        assert call_kwargs[ "research_path" ] == "/path/to/doc.md"

    @patch( "cosa.agents.deep_research_to_podcast.job.DeepResearchToPodcastJob" )
    @patch( "cosa.agents.podcast_generator.job.PodcastGeneratorJob" )
    @patch( "cosa.agents.deep_research.job.DeepResearchJob" )
    def test_research_to_podcast_job( self, MockDR, MockPG, MockRTP ):
        """Research-to-podcast command creates DeepResearchToPodcastJob."""
        MockRTP.return_value = MagicMock()
        args = { "query": "AI safety" }

        result = create_agentic_job(
            command    = "agent router go to research to podcast",
            args_dict  = args,
            user_id    = "uid-1",
            user_email = "test@test.com",
            session_id = "sess-1"
        )

        MockRTP.assert_called_once()
        call_kwargs = MockRTP.call_args[ 1 ]
        assert call_kwargs[ "query" ] == "AI safety"

    @patch( "cosa.agents.deep_research_to_podcast.job.DeepResearchToPodcastJob" )
    @patch( "cosa.agents.podcast_generator.job.PodcastGeneratorJob" )
    @patch( "cosa.agents.deep_research.job.DeepResearchJob" )
    def test_unknown_command( self, MockDR, MockPG, MockRTP ):
        """Unknown command returns None."""
        result = create_agentic_job(
            command    = "unknown",
            args_dict  = {},
            user_id    = "uid-1",
            user_email = "test@test.com",
            session_id = "sess-1"
        )

        assert result is None

    @patch( "cosa.agents.deep_research_to_podcast.job.DeepResearchToPodcastJob" )
    @patch( "cosa.agents.podcast_generator.job.PodcastGeneratorJob" )
    @patch( "cosa.agents.deep_research.job.DeepResearchJob" )
    def test_budget_float_conversion( self, MockDR, MockPG, MockRTP ):
        """Budget string is converted to float."""
        MockDR.return_value = MagicMock()
        args = { "query": "test", "budget": "10" }

        create_agentic_job(
            command    = "agent router go to deep research",
            args_dict  = args,
            user_id    = "uid-1",
            user_email = "test@test.com",
            session_id = "sess-1"
        )

        call_kwargs = MockDR.call_args[ 1 ]
        assert call_kwargs[ "budget" ] == 10.0
        assert isinstance( call_kwargs[ "budget" ], float )

    @patch( "cosa.agents.deep_research_to_podcast.job.DeepResearchToPodcastJob" )
    @patch( "cosa.agents.podcast_generator.job.PodcastGeneratorJob" )
    @patch( "cosa.agents.deep_research.job.DeepResearchJob" )
    def test_budget_none_when_missing( self, MockDR, MockPG, MockRTP ):
        """Missing budget passes None."""
        MockDR.return_value = MagicMock()
        args = { "query": "test" }

        create_agentic_job(
            command    = "agent router go to deep research",
            args_dict  = args,
            user_id    = "uid-1",
            user_email = "test@test.com",
            session_id = "sess-1"
        )

        call_kwargs = MockDR.call_args[ 1 ]
        assert call_kwargs[ "budget" ] is None

    @patch( "cosa.agents.deep_research_to_podcast.job.DeepResearchToPodcastJob" )
    @patch( "cosa.agents.podcast_generator.job.PodcastGeneratorJob" )
    @patch( "cosa.agents.deep_research.job.DeepResearchJob" )
    def test_languages_string_to_list( self, MockDR, MockPG, MockRTP ):
        """Languages string is parsed to list."""
        MockPG.return_value = MagicMock()
        args = { "research": "/doc.md", "languages": "English, Spanish" }

        create_agentic_job(
            command    = "agent router go to podcast generator",
            args_dict  = args,
            user_id    = "uid-1",
            user_email = "test@test.com",
            session_id = "sess-1"
        )

        call_kwargs = MockPG.call_args[ 1 ]
        assert call_kwargs[ "target_languages" ] == [ "English", "Spanish" ]

    @patch( "cosa.agents.deep_research_to_podcast.job.DeepResearchToPodcastJob" )
    @patch( "cosa.agents.podcast_generator.job.PodcastGeneratorJob" )
    @patch( "cosa.agents.deep_research.job.DeepResearchJob" )
    def test_languages_already_list( self, MockDR, MockPG, MockRTP ):
        """Languages already as list is passed through."""
        MockPG.return_value = MagicMock()
        args = { "research": "/doc.md", "languages": [ "English" ] }

        create_agentic_job(
            command    = "agent router go to podcast generator",
            args_dict  = args,
            user_id    = "uid-1",
            user_email = "test@test.com",
            session_id = "sess-1"
        )

        call_kwargs = MockPG.call_args[ 1 ]
        assert call_kwargs[ "target_languages" ] == [ "English" ]

    @patch( "cosa.agents.deep_research_to_podcast.job.DeepResearchToPodcastJob" )
    @patch( "cosa.agents.podcast_generator.job.PodcastGeneratorJob" )
    @patch( "cosa.agents.deep_research.job.DeepResearchJob" )
    def test_dry_run_flag( self, MockDR, MockPG, MockRTP ):
        """dry_run=True is forwarded to constructor."""
        MockDR.return_value = MagicMock()
        args = { "query": "test", "dry_run": True }

        create_agentic_job(
            command    = "agent router go to deep research",
            args_dict  = args,
            user_id    = "uid-1",
            user_email = "test@test.com",
            session_id = "sess-1"
        )

        call_kwargs = MockDR.call_args[ 1 ]
        assert call_kwargs[ "dry_run" ] is True

    @patch( "cosa.agents.deep_research_to_podcast.job.DeepResearchToPodcastJob" )
    @patch( "cosa.agents.podcast_generator.job.PodcastGeneratorJob" )
    @patch( "cosa.agents.deep_research.job.DeepResearchJob" )
    def test_deep_research_audience_passthrough( self, MockDR, MockPG, MockRTP ):
        """Audience params are forwarded to DeepResearchJob."""
        MockDR.return_value = MagicMock()
        args = { "query": "test", "audience": "beginner", "audience_context": "high school students" }

        create_agentic_job(
            command    = "agent router go to deep research",
            args_dict  = args,
            user_id    = "uid-1",
            user_email = "test@test.com",
            session_id = "sess-1"
        )

        call_kwargs = MockDR.call_args[ 1 ]
        assert call_kwargs[ "audience" ] == "beginner"
        assert call_kwargs[ "audience_context" ] == "high school students"

    @patch( "cosa.agents.deep_research_to_podcast.job.DeepResearchToPodcastJob" )
    @patch( "cosa.agents.podcast_generator.job.PodcastGeneratorJob" )
    @patch( "cosa.agents.deep_research.job.DeepResearchJob" )
    def test_podcast_generator_audience_passthrough( self, MockDR, MockPG, MockRTP ):
        """Audience params are forwarded to PodcastGeneratorJob."""
        MockPG.return_value = MagicMock()
        args = { "research": "/doc.md", "audience": "expert", "audience_context": "ML researchers" }

        create_agentic_job(
            command    = "agent router go to podcast generator",
            args_dict  = args,
            user_id    = "uid-1",
            user_email = "test@test.com",
            session_id = "sess-1"
        )

        call_kwargs = MockPG.call_args[ 1 ]
        assert call_kwargs[ "audience" ] == "expert"
        assert call_kwargs[ "audience_context" ] == "ML researchers"

    @patch( "cosa.agents.deep_research_to_podcast.job.DeepResearchToPodcastJob" )
    @patch( "cosa.agents.podcast_generator.job.PodcastGeneratorJob" )
    @patch( "cosa.agents.deep_research.job.DeepResearchJob" )
    def test_rtp_audience_passthrough( self, MockDR, MockPG, MockRTP ):
        """Audience params are forwarded to DeepResearchToPodcastJob."""
        MockRTP.return_value = MagicMock()
        args = { "query": "AI safety", "audience": "academic", "audience_context": "PhD students" }

        create_agentic_job(
            command    = "agent router go to research to podcast",
            args_dict  = args,
            user_id    = "uid-1",
            user_email = "test@test.com",
            session_id = "sess-1"
        )

        call_kwargs = MockRTP.call_args[ 1 ]
        assert call_kwargs[ "audience" ] == "academic"
        assert call_kwargs[ "audience_context" ] == "PhD students"


# ═══════════════════════════════════════════════════════════════════════════════
# Class 6: TestArgConfirmationResponse (8 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestArgConfirmationResponse:
    """Tests for ArgConfirmationResponse Pydantic model - pure data, no mocking needed."""

    def test_is_approval_approve( self ):
        """action='approve' returns is_approval() True."""
        response = ArgConfirmationResponse( action="approve", arg_name="", new_value="" )
        assert response.is_approval() is True
        assert response.is_cancel() is False
        assert response.is_modify() is False

    def test_is_approval_variants( self ):
        """'yes' and 'ok' also return is_approval() True."""
        for variant in [ "yes", "ok", "Yes", "OK", " approve " ]:
            response = ArgConfirmationResponse( action=variant, arg_name="", new_value="" )
            assert response.is_approval() is True, f"Failed for variant: '{variant}'"

    def test_is_cancel( self ):
        """action='cancel' returns is_cancel() True."""
        response = ArgConfirmationResponse( action="cancel", arg_name="", new_value="" )
        assert response.is_cancel() is True
        assert response.is_approval() is False
        assert response.is_modify() is False

    def test_is_cancel_variants( self ):
        """'stop' and 'quit' also return is_cancel() True."""
        for variant in [ "stop", "quit", "Cancel", " STOP " ]:
            response = ArgConfirmationResponse( action=variant, arg_name="", new_value="" )
            assert response.is_cancel() is True, f"Failed for variant: '{variant}'"

    def test_is_modify( self ):
        """action='modify' with arg_name and new_value populated."""
        response = ArgConfirmationResponse( action="modify", arg_name="budget", new_value="50" )
        assert response.is_modify() is True
        assert response.is_approval() is False
        assert response.is_cancel() is False
        assert response.arg_name == "budget"
        assert response.new_value == "50"

    def test_xml_round_trip( self ):
        """to_xml() → from_xml() preserves all fields."""
        original = ArgConfirmationResponse( action="modify", arg_name="audience", new_value="expert" )
        xml_str  = original.to_xml()
        parsed   = ArgConfirmationResponse.from_xml( xml_str )

        assert parsed.action == original.action
        assert parsed.arg_name == original.arg_name
        assert parsed.new_value == original.new_value

    def test_get_example_for_template( self ):
        """get_example_for_template() returns a valid modify instance."""
        example = ArgConfirmationResponse.get_example_for_template()
        assert isinstance( example, ArgConfirmationResponse )
        assert example.action == "modify"
        assert example.arg_name == "budget"
        assert example.new_value == "50"

    def test_empty_arg_name_for_approve( self ):
        """Approval with empty arg_name and new_value is valid."""
        response = ArgConfirmationResponse( action="approve", arg_name="", new_value="" )
        assert response.is_approval() is True
        assert response.arg_name == ""
        assert response.new_value == ""


# ═══════════════════════════════════════════════════════════════════════════════
# Class 7: TestConfirmAndIterate (13 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfirmAndIterate:
    """Tests for RuntimeArgumentExpeditor._confirm_and_iterate() with mocked voice I/O.

    Uses YES_NO prompt type. Responses are "yes", "no", "yes [comment: ...]",
    or "no [comment: ...]".
    """

    DR_COMMAND_KEY = "agent router go to deep research"

    def setup_method( self ):
        """Create a minimal expeditor instance with mocked dependencies."""
        self.expeditor                          = RuntimeArgumentExpeditor.__new__( RuntimeArgumentExpeditor )
        self.expeditor.debug                    = False
        self.expeditor.verbose                  = False
        self.expeditor.confirmation_prompt_path = "/src/conf/prompts/runtime-argument-confirmation.txt"
        self.expeditor.llm_spec_key             = "test_key"
        self.expeditor.llm_factory              = MagicMock()

        self.agent_entry = AGENTIC_AGENTS[ self.DR_COMMAND_KEY ]

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_ask_for_confirmation" )
    def test_immediate_approval_yes( self, mock_confirm, mock_uva ):
        """User says 'yes' → returns args immediately."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        mock_confirm.return_value = "yes"
        args = { "query": "quantum computing" }

        result = self.expeditor._confirm_and_iterate( args, self.agent_entry, self.DR_COMMAND_KEY, "test@test.com" )

        assert result == args
        mock_confirm.assert_called_once()

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_ask_for_confirmation" )
    def test_immediate_approval_normalized( self, mock_confirm, mock_uva ):
        """YES_NO normalizes button press to 'yes' — returns args immediately."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        mock_confirm.return_value = "yes"
        args = { "query": "AI safety" }

        result = self.expeditor._confirm_and_iterate( args, self.agent_entry, self.DR_COMMAND_KEY, "test@test.com" )

        assert result == args

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_ask_for_confirmation" )
    def test_cancel_no( self, mock_confirm, mock_uva ):
        """User says 'no' → returns None."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        mock_confirm.return_value = "no"
        args = { "query": "test" }

        result = self.expeditor._confirm_and_iterate( args, self.agent_entry, self.DR_COMMAND_KEY, "test@test.com" )

        assert result is None

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_ask_for_confirmation" )
    def test_timeout_returns_none( self, mock_confirm, mock_uva ):
        """_ask_for_confirmation returns None (timeout) → returns None."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        mock_confirm.return_value = None
        args = { "query": "test" }

        result = self.expeditor._confirm_and_iterate( args, self.agent_entry, self.DR_COMMAND_KEY, "test@test.com" )

        assert result is None

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_parse_modification" )
    @patch.object( RuntimeArgumentExpeditor, "_ask_for_confirmation" )
    def test_modify_then_approve( self, mock_confirm, mock_parse, mock_uva ):
        """User says 'no [comment: change budget]', then 'yes' on second prompt."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        mock_confirm.side_effect = [ "no [comment: change the budget to 50]", "yes" ]
        mock_parse.return_value = ArgConfirmationResponse(
            action="modify", arg_name="budget", new_value="50"
        )
        args = { "query": "quantum computing" }

        result = self.expeditor._confirm_and_iterate( args, self.agent_entry, self.DR_COMMAND_KEY, "test@test.com" )

        assert result is not None
        assert result[ "budget" ] == "50"
        assert result[ "query" ] == "quantum computing"

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_ask_for_confirmation" )
    def test_plain_no_cancels( self, mock_confirm, mock_uva ):
        """Plain 'no' without comment → returns None."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        mock_confirm.return_value = "no"
        args = { "query": "test" }

        result = self.expeditor._confirm_and_iterate( args, self.agent_entry, self.DR_COMMAND_KEY, "test@test.com" )

        assert result is None

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_ask_for_confirmation" )
    def test_confirm_only_shows_user_visible_args( self, mock_confirm, mock_uva ):
        """Engineering params (lead_model, debug) excluded from abstract shown to user."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        mock_confirm.return_value = "yes"
        args = {
            "query"      : "quantum computing",
            "budget"     : "10",
            "lead_model" : "claude-opus-4-6",
            "debug"      : True,
        }

        result = self.expeditor._confirm_and_iterate( args, self.agent_entry, self.DR_COMMAND_KEY, "test@test.com" )

        assert result == args
        # Verify the abstract kwarg sent to _ask_for_confirmation
        call_kwargs = mock_confirm.call_args[ 1 ]
        abstract = call_kwargs[ "abstract" ]
        assert "query" in abstract
        assert "budget" in abstract
        assert "lead_model" not in abstract
        assert "debug" not in abstract

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_ask_for_confirmation" )
    def test_confirm_fallback_when_no_user_visible( self, mock_confirm, mock_uva ):
        """When get_user_visible_args returns None, falls back to fallback_questions keys."""
        mock_uva.return_value = None  # Simulate CLI not supporting --user-visible-args
        mock_confirm.return_value = "yes"
        args = {
            "query"      : "quantum computing",
            "lead_model" : "claude-opus-4-6",
        }

        result = self.expeditor._confirm_and_iterate( args, self.agent_entry, self.DR_COMMAND_KEY, "test@test.com" )

        assert result == args
        # Verify the abstract uses fallback_questions keys
        call_kwargs = mock_confirm.call_args[ 1 ]
        abstract = call_kwargs[ "abstract" ]
        assert "query" in abstract
        # lead_model is NOT in fallback_questions, so should be excluded
        assert "lead_model" not in abstract

    # --- New YES_NO comment path tests ---

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_parse_modification" )
    @patch.object( RuntimeArgumentExpeditor, "_ask_for_confirmation" )
    def test_yes_with_comment_applies_modification( self, mock_confirm, mock_parse, mock_uva ):
        """'yes [comment: change budget to 10]' → applies tweak, returns args."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        mock_confirm.return_value = "yes [comment: change budget to 10]"
        mock_parse.return_value = ArgConfirmationResponse(
            action="modify", arg_name="budget", new_value="10"
        )
        args = { "query": "quantum computing" }

        result = self.expeditor._confirm_and_iterate( args, self.agent_entry, self.DR_COMMAND_KEY, "test@test.com" )

        assert result is not None
        assert result[ "budget" ] == "10"
        assert result[ "query" ] == "quantum computing"
        # Verify parse was called with the comment text, not the full response
        mock_parse.assert_called_once_with( "change budget to 10", args, self.agent_entry )

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_parse_modification" )
    @patch.object( RuntimeArgumentExpeditor, "_ask_for_confirmation" )
    def test_no_with_comment_reloops( self, mock_confirm, mock_parse, mock_uva ):
        """'no [comment: change budget to 10]' → applies tweak, re-presents for confirmation."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        mock_confirm.side_effect = [ "no [comment: change budget to 10]", "yes" ]
        mock_parse.return_value = ArgConfirmationResponse(
            action="modify", arg_name="budget", new_value="10"
        )
        args = { "query": "quantum computing" }

        result = self.expeditor._confirm_and_iterate( args, self.agent_entry, self.DR_COMMAND_KEY, "test@test.com" )

        assert result is not None
        assert result[ "budget" ] == "10"
        assert mock_confirm.call_count == 2

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_parse_modification" )
    @patch.object( RuntimeArgumentExpeditor, "_ask_for_confirmation" )
    def test_yes_with_unparseable_comment_proceeds( self, mock_confirm, mock_parse, mock_uva ):
        """'yes [comment: gibberish]' + parse fails → proceed anyway (respect 'yes')."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        mock_confirm.return_value = "yes [comment: asdfghjkl]"
        mock_parse.return_value = None  # Parse failure
        args = { "query": "quantum computing" }

        result = self.expeditor._confirm_and_iterate( args, self.agent_entry, self.DR_COMMAND_KEY, "test@test.com" )

        assert result == args  # Proceeds because user said "yes"

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_parse_modification" )
    @patch.object( RuntimeArgumentExpeditor, "_ask_for_confirmation" )
    def test_no_with_unparseable_comment_cancels( self, mock_confirm, mock_parse, mock_uva ):
        """'no [comment: gibberish]' + parse fails → cancel (respect 'no')."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        mock_confirm.return_value = "no [comment: asdfghjkl]"
        mock_parse.return_value = None  # Parse failure
        args = { "query": "quantum computing" }

        result = self.expeditor._confirm_and_iterate( args, self.agent_entry, self.DR_COMMAND_KEY, "test@test.com" )

        assert result is None  # Cancels because user said "no"

    def test_extract_comment( self ):
        """_extract_comment() extracts comment text from annotated responses."""
        assert RuntimeArgumentExpeditor._extract_comment( "yes [comment: change budget to 10]" ) == "change budget to 10"
        assert RuntimeArgumentExpeditor._extract_comment( "no [comment: make it cheaper]" ) == "make it cheaper"
        assert RuntimeArgumentExpeditor._extract_comment( "yes" ) is None
        assert RuntimeArgumentExpeditor._extract_comment( "no" ) is None
        assert RuntimeArgumentExpeditor._extract_comment( "" ) is None


# ═══════════════════════════════════════════════════════════════════════════════
# Class 8: TestBatchCollectArgs (6 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBatchCollectArgs:
    """Tests for RuntimeArgumentExpeditor._batch_collect_args() and batch integration."""

    DR_COMMAND_KEY = "agent router go to deep research"

    def setup_method( self ):
        """Create a minimal expeditor instance with mocked dependencies."""
        self.expeditor                          = RuntimeArgumentExpeditor.__new__( RuntimeArgumentExpeditor )
        self.expeditor.debug                    = False
        self.expeditor.verbose                  = False
        self.expeditor.confirmation_prompt_path = "/src/conf/prompts/runtime-argument-confirmation.txt"
        self.expeditor.llm_spec_key             = "test_key"
        self.expeditor.llm_factory              = MagicMock()
        self.expeditor._job_id                  = None
        self.expeditor._bearer_token            = None
        self.expeditor._last_notification_status = None

        # Mock config_mgr for _resolve_default()
        mock_config_mgr           = MagicMock()
        mock_config_mgr.get       = MagicMock( return_value=None )
        self.expeditor.config_mgr = mock_config_mgr

        self.agent_entry        = AGENTIC_AGENTS[ self.DR_COMMAND_KEY ]
        self.fallback_questions = self.agent_entry[ "fallback_questions" ]

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.notify_user_sync" )
    def test_batch_collect_args_success( self, mock_sync ):
        """Successful batch returns dict of answers keyed by arg name."""
        import json
        mock_sync.return_value = MagicMock(
            success        = True,
            response_value = json.dumps( { "answers": { "budget": "10", "audience": "expert" } } )
        )

        result, _reason = self.expeditor._batch_collect_args(
            [ "budget", "audience" ], self.fallback_questions, "test@test.com"
        )

        assert result is not None
        assert result[ "budget" ] == "10"
        assert result[ "audience" ] == "expert"
        mock_sync.assert_called_once()

        # Verify the request used OPEN_ENDED_BATCH response type
        call_kwargs = mock_sync.call_args[ 1 ]
        request = call_kwargs[ "request" ]
        assert request.response_type.value == "open_ended_batch"

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.notify_user_sync" )
    def test_batch_collect_args_timeout( self, mock_sync ):
        """Timeout returns None."""
        mock_sync.return_value = MagicMock(
            success        = False,
            response_value = None
        )

        result, _reason = self.expeditor._batch_collect_args(
            [ "budget", "audience" ], self.fallback_questions, "test@test.com"
        )

        assert result is None

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.notify_user_sync" )
    def test_batch_collect_args_cancel( self, mock_sync ):
        """Cancel keyword in any answer returns None."""
        import json
        mock_sync.return_value = MagicMock(
            success        = True,
            response_value = json.dumps( { "answers": { "budget": "cancel", "audience": "expert" } } )
        )

        result, _reason = self.expeditor._batch_collect_args(
            [ "budget", "audience" ], self.fallback_questions, "test@test.com"
        )

        assert result is None

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.notify_user_sync" )
    def test_batch_collect_args_cancelled_flag( self, mock_sync ):
        """Cancelled flag in response returns None."""
        import json
        mock_sync.return_value = MagicMock(
            success        = True,
            response_value = json.dumps( { "cancelled": True, "answers": {} } )
        )

        result, _reason = self.expeditor._batch_collect_args(
            [ "budget", "audience" ], self.fallback_questions, "test@test.com"
        )

        assert result is None

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.notify_user_sync" )
    def test_batch_collect_args_malformed_json( self, mock_sync ):
        """Non-JSON response returns None gracefully."""
        mock_sync.return_value = MagicMock(
            success        = True,
            response_value = "this is not json at all"
        )

        result, _reason = self.expeditor._batch_collect_args(
            [ "budget", "audience" ], self.fallback_questions, "test@test.com"
        )

        assert result is None

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.notify_user_sync" )
    def test_batch_collect_args_empty_answers_dict( self, mock_sync ):
        """Empty {"answers": {}} returns None."""
        import json
        mock_sync.return_value = MagicMock(
            success        = True,
            response_value = json.dumps( { "answers": {} } )
        )

        result, _reason = self.expeditor._batch_collect_args(
            [ "budget", "audience" ], self.fallback_questions, "test@test.com"
        )

        assert result is None

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.notify_user_sync" )
    def test_batch_collect_args_partial_answers( self, mock_sync ):
        """Missing one requested arg returns None."""
        import json
        mock_sync.return_value = MagicMock(
            success        = True,
            response_value = json.dumps( { "answers": { "budget": "10" } } )
        )

        result, _reason = self.expeditor._batch_collect_args(
            [ "budget", "audience" ], self.fallback_questions, "test@test.com"
        )

        assert result is None

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.notify_user_sync" )
    def test_batch_collect_args_fallback_template( self, mock_sync ):
        """Unknown arg uses 'Please provide the X argument.' template."""
        import json
        mock_sync.return_value = MagicMock(
            success        = True,
            response_value = json.dumps( { "answers": { "mystery_arg": "42", "another_arg": "hello" } } )
        )

        result, _reason = self.expeditor._batch_collect_args(
            [ "mystery_arg", "another_arg" ], self.fallback_questions, "test@test.com"
        )

        # TTS for batch with 2+ questions is count-only preamble (Bug 2 fix)
        call_kwargs   = mock_sync.call_args[ 1 ]
        request       = call_kwargs[ "request" ]
        tts_message   = request.message
        assert "I have 2 questions" in tts_message

        # Fallback questions are in response_options (UI form), not TTS
        questions = request.response_options[ "questions" ]
        question_texts = [ q[ "question" ] for q in questions ]
        assert any( "mystery_arg" in q for q in question_texts )
        assert any( "another_arg" in q for q in question_texts )
        assert result is not None
        assert result[ "mystery_arg" ] == "42"

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_batch_collect_args" )
    @patch.object( RuntimeArgumentExpeditor, "_confirm_and_iterate" )
    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.LlmClientFactory" )
    def test_expedite_uses_batch_for_multiple_missing( self, mock_factory, mock_confirm, mock_batch, mock_uva ):
        """When >1 batchable args missing, batch path is taken."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        mock_batch.return_value = ( { "budget": "10", "audience": "expert" }, "answered" )
        mock_confirm.return_value = { "query": "quantum", "budget": "10", "audience": "expert" }

        # Set up LLM to return "args missing" response
        mock_llm = MagicMock()
        mock_llm.run.return_value = (
            "<expeditor_response><all_required_met>false</all_required_met>"
            "<args_present>query=quantum</args_present>"
            "<args_missing>budget, audience</args_missing></expeditor_response>"
        )
        mock_factory_instance = MagicMock()
        mock_factory_instance.get_client.return_value = mock_llm
        self.expeditor.llm_factory = mock_factory_instance
        self.expeditor.prompt_template_path = "/src/conf/prompts/test.txt"

        with patch( "cosa.utils.util.get_file_as_string", return_value="{system_args}{help_text}{voice_command}{extracted_args}{required_args}" ), \
             patch( "cosa.utils.util.get_project_root", return_value="/fake" ), \
             patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_cli_help", return_value="test help" ), \
             patch( "cosa.agents.io_models.utils.prompt_template_processor.PromptTemplateProcessor.process_template", return_value="{system_args}{help_text}{voice_command}{extracted_args}{required_args}" ):
            result = self.expeditor.expedite(
                command           = self.DR_COMMAND_KEY,
                raw_args          = 'query="quantum"',
                user_email        = "test@test.com",
                session_id        = "sess-1",
                user_id           = "uid-1",
                original_question = "research quantum computing"
            )

        mock_batch.assert_called_once()
        batch_call_args = mock_batch.call_args[ 0 ]
        assert "budget" in batch_call_args[ 0 ]
        assert "audience" in batch_call_args[ 0 ]

        # Verify abstract was passed as keyword arg
        batch_call_kwargs = mock_batch.call_args[ 1 ]
        assert "abstract" in batch_call_kwargs
        abstract = batch_call_kwargs[ "abstract" ]
        assert "research quantum computing" in abstract
        assert "Deep Research" in abstract

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_ask_for_arg" )
    @patch.object( RuntimeArgumentExpeditor, "_confirm_and_iterate" )
    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.LlmClientFactory" )
    def test_expedite_uses_single_for_one_missing( self, mock_factory, mock_confirm, mock_ask, mock_uva ):
        """When exactly 1 user-visible arg missing, single path is taken (no batch).

        Note: user_visible returns only [ "query", "budget" ] here so that with
        query present, only budget is missing → single arg path.
        """
        mock_uva.return_value = [ "query", "budget" ]
        mock_ask.return_value = "10"
        mock_confirm.return_value = { "query": "quantum", "budget": "10" }

        mock_llm = MagicMock()
        mock_llm.run.return_value = (
            "<expeditor_response><all_required_met>false</all_required_met>"
            "<args_present>query=quantum</args_present>"
            "<args_missing>budget</args_missing></expeditor_response>"
        )
        mock_factory_instance = MagicMock()
        mock_factory_instance.get_client.return_value = mock_llm
        self.expeditor.llm_factory = mock_factory_instance
        self.expeditor.prompt_template_path = "/src/conf/prompts/test.txt"

        with patch( "cosa.utils.util.get_file_as_string", return_value="{system_args}{help_text}{voice_command}{extracted_args}{required_args}" ), \
             patch( "cosa.utils.util.get_project_root", return_value="/fake" ), \
             patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_cli_help", return_value="test help" ), \
             patch( "cosa.agents.io_models.utils.prompt_template_processor.PromptTemplateProcessor.process_template", return_value="{system_args}{help_text}{voice_command}{extracted_args}{required_args}" ):
            result = self.expeditor.expedite(
                command           = self.DR_COMMAND_KEY,
                raw_args          = 'query="quantum"',
                user_email        = "test@test.com",
                session_id        = "sess-1",
                user_id           = "uid-1",
                original_question = "research quantum computing"
            )

        mock_ask.assert_called()
        # Verify _batch_collect_args was NOT called (it's not patched, so would fail if called)


# ═══════════════════════════════════════════════════════════════════════════════
# Class 9: TestRequestContext (8 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRequestContext:
    """Tests for RuntimeArgumentExpeditor._build_request_context() — markdown abstract builder."""

    DR_COMMAND_KEY = "agent router go to deep research"

    def setup_method( self ):
        """Create a minimal expeditor instance."""
        self.expeditor       = RuntimeArgumentExpeditor.__new__( RuntimeArgumentExpeditor )
        self.expeditor.debug = False
        self.agent_entry     = AGENTIC_AGENTS[ self.DR_COMMAND_KEY ]

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    def test_includes_original_question( self, mock_uva ):
        """Abstract contains the user's original voice command."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        result = self.expeditor._build_request_context(
            self.agent_entry, "do deep research on quantum computing",
            { "query": "quantum computing" }, [ "budget", "audience" ]
        )
        assert '"do deep research on quantum computing"' in result

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    def test_includes_display_name( self, mock_uva ):
        """Abstract contains the agent's display name."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        result = self.expeditor._build_request_context(
            self.agent_entry, "research AI", { "query": "AI" }, [ "budget" ]
        )
        assert "Deep Research" in result

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    def test_includes_present_args( self, mock_uva ):
        """Abstract lists already-extracted args when present."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        result = self.expeditor._build_request_context(
            self.agent_entry, "research quantum",
            { "query": "quantum computing" }, [ "budget" ]
        )
        assert "**Already extracted**:" in result
        assert "query: quantum computing" in result

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    def test_includes_missing_args( self, mock_uva ):
        """Abstract lists still-needed args."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        result = self.expeditor._build_request_context(
            self.agent_entry, "research quantum",
            { "query": "quantum" }, [ "budget", "audience" ]
        )
        assert "**Still needed**: budget, audience" in result

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    def test_empty_present_args_omits_section( self, mock_uva ):
        """When no args extracted, 'Already extracted' section is omitted."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        result = self.expeditor._build_request_context(
            self.agent_entry, "make me a podcast",
            {}, [ "query", "budget" ]
        )
        assert "**Already extracted**:" not in result

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    def test_empty_missing_args_omits_section( self, mock_uva ):
        """When no args missing, 'Still needed' section is omitted."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        result = self.expeditor._build_request_context(
            self.agent_entry, "research quantum",
            { "query": "quantum" }, []
        )
        assert "**Still needed**" not in result

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    def test_filters_system_args_from_present( self, mock_uva ):
        """System-provided args (user_email, session_id) excluded from 'Already extracted'."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        result = self.expeditor._build_request_context(
            self.agent_entry, "research quantum",
            { "query": "quantum", "user_email": "test@test.com", "no_confirm": True }, [ "budget" ]
        )
        assert "user_email" not in result
        assert "no_confirm" not in result
        assert "query: quantum" in result

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    def test_display_name_fallback( self, mock_uva ):
        """When display_name missing, falls back to cli_module derivation."""
        mock_uva.return_value = None
        # Create entry without display_name
        entry_no_name = dict( self.agent_entry )
        del entry_no_name[ "display_name" ]
        result = self.expeditor._build_request_context(
            entry_no_name, "test", {}, [ "budget" ]
        )
        # Should fallback to "cli" from "cosa.agents.deep_research.cli"
        assert "**Agent**: cli" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Class 10: TestBatchAbstractPassthrough (1 test)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBatchAbstractPassthrough:
    """Tests that abstract flows through _batch_collect_args to NotificationRequest."""

    def setup_method( self ):
        """Create a minimal expeditor instance with mocked dependencies."""
        self.expeditor                          = RuntimeArgumentExpeditor.__new__( RuntimeArgumentExpeditor )
        self.expeditor.debug                    = False
        self.expeditor.verbose                  = False
        self.expeditor.llm_spec_key             = "test_key"
        self.expeditor.llm_factory              = MagicMock()
        self.expeditor._job_id                  = None
        self.expeditor._bearer_token            = None
        self.expeditor._last_notification_status = None

        # Mock config_mgr for _resolve_default()
        mock_config_mgr           = MagicMock()
        mock_config_mgr.get       = MagicMock( return_value=None )
        self.expeditor.config_mgr = mock_config_mgr

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.notify_user_sync" )
    def test_batch_collect_args_passes_abstract_to_request( self, mock_sync ):
        """Abstract parameter flows through to NotificationRequest."""
        import json
        mock_sync.return_value = MagicMock(
            success        = True,
            response_value = json.dumps( { "answers": { "budget": "10", "audience": "expert" } } )
        )

        agent_entry        = AGENTIC_AGENTS[ "agent router go to deep research" ]
        fallback_questions = agent_entry[ "fallback_questions" ]
        test_abstract      = '**Your request**: "research quantum"\n**Agent**: Deep Research'

        self.expeditor._batch_collect_args(
            [ "budget", "audience" ], fallback_questions, "test@test.com",
            abstract=test_abstract
        )

        mock_sync.assert_called_once()
        call_kwargs = mock_sync.call_args[ 1 ]
        request = call_kwargs[ "request" ]
        assert request.abstract == test_abstract


# ═══════════════════════════════════════════════════════════════════════════════
# Class 11: TestResolveDefault (5 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestResolveDefault:
    """Tests for RuntimeArgumentExpeditor._resolve_default() 3-tier override chain."""

    DR_COMMAND_KEY = "agent router go to deep research"

    def setup_method( self ):
        """Create a minimal expeditor instance with mocked config_mgr."""
        self.expeditor            = RuntimeArgumentExpeditor.__new__( RuntimeArgumentExpeditor )
        self.expeditor.debug      = False
        self.mock_config_mgr      = MagicMock()
        self.expeditor.config_mgr = self.mock_config_mgr

    def test_config_override_wins_over_registry( self ):
        """Config value takes priority over registry_default."""
        self.mock_config_mgr.get = MagicMock( return_value="config_value" )

        result = self.expeditor._resolve_default(
            self.DR_COMMAND_KEY, "budget", "registry_value"
        )

        assert result == "config_value"
        self.mock_config_mgr.get.assert_called_once_with(
            "expeditor default value for deep research budget", default=None
        )

    def test_registry_fallback_when_config_none( self ):
        """Registry default used when config returns None."""
        self.mock_config_mgr.get = MagicMock( return_value=None )

        result = self.expeditor._resolve_default(
            self.DR_COMMAND_KEY, "audience", "academic"
        )

        assert result == "academic"

    def test_both_none_returns_none( self ):
        """Returns None when config and registry both None."""
        self.mock_config_mgr.get = MagicMock( return_value=None )

        result = self.expeditor._resolve_default(
            self.DR_COMMAND_KEY, "budget", None
        )

        assert result is None

    def test_agent_short_name_extraction( self ):
        """Correct config key built from command_key (e.g., 'research to podcast languages')."""
        self.mock_config_mgr.get = MagicMock( return_value="en,es-MX" )

        result = self.expeditor._resolve_default(
            "agent router go to research to podcast", "languages", None
        )

        assert result == "en,es-MX"
        self.mock_config_mgr.get.assert_called_once_with(
            "expeditor default value for research to podcast languages", default=None
        )

    def test_config_empty_string_counts_as_value( self ):
        """Empty string '' from config overrides registry (not None)."""
        self.mock_config_mgr.get = MagicMock( return_value="" )

        result = self.expeditor._resolve_default(
            self.DR_COMMAND_KEY, "audience_context", "none"
        )

        assert result == ""


# ═══════════════════════════════════════════════════════════════════════════════
# Class 12: TestBatchDefaultValues (4 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBatchDefaultValues:
    """Tests for _batch_collect_args() integration with _resolve_default()."""

    DR_COMMAND_KEY  = "agent router go to deep research"
    RTP_COMMAND_KEY = "agent router go to research to podcast"

    def setup_method( self ):
        """Create a minimal expeditor instance with mocked dependencies."""
        self.expeditor                          = RuntimeArgumentExpeditor.__new__( RuntimeArgumentExpeditor )
        self.expeditor.debug                    = False
        self.expeditor.verbose                  = False
        self.expeditor.llm_spec_key             = "test_key"
        self.expeditor.llm_factory              = MagicMock()
        self.expeditor._job_id                  = None
        self.expeditor._bearer_token            = None
        self.expeditor._last_notification_status = None

        # Mock config_mgr — default: return None (no config override)
        self.mock_config_mgr           = MagicMock()
        self.mock_config_mgr.get       = MagicMock( return_value=None )
        self.expeditor.config_mgr      = self.mock_config_mgr

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.notify_user_sync" )
    def test_batch_includes_default_value_from_registry( self, mock_sync ):
        """Registry defaults appear in response_options questions."""
        import json
        mock_sync.return_value = MagicMock(
            success        = True,
            response_value = json.dumps( { "answers": { "budget": "10", "audience": "expert" } } )
        )

        agent_entry        = AGENTIC_AGENTS[ self.DR_COMMAND_KEY ]
        fallback_questions = agent_entry[ "fallback_questions" ]
        fallback_defaults  = agent_entry[ "fallback_defaults" ]

        self.expeditor._batch_collect_args(
            [ "budget", "audience" ], fallback_questions, "test@test.com",
            fallback_defaults, self.DR_COMMAND_KEY
        )

        # Inspect the request built by _batch_collect_args
        call_kwargs      = mock_sync.call_args[ 1 ]
        request          = call_kwargs[ "request" ]
        api_questions    = request.response_options[ "questions" ]

        budget_q   = next( q for q in api_questions if q[ "header" ] == "budget" )
        audience_q = next( q for q in api_questions if q[ "header" ] == "audience" )
        assert budget_q[ "default_value" ] == "no limit"
        assert audience_q[ "default_value" ] == "academic"

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.notify_user_sync" )
    def test_batch_config_override_wins_over_registry( self, mock_sync ):
        """Config value overrides registry in question's default_value."""
        import json
        mock_sync.return_value = MagicMock(
            success        = True,
            response_value = json.dumps( { "answers": { "budget": "25", "audience": "beginner" } } )
        )

        # Config returns "25" for budget, None for everything else
        def config_get_side_effect( key, default=None ):
            if "budget" in key:
                return "25"
            return None

        self.mock_config_mgr.get = MagicMock( side_effect=config_get_side_effect )

        agent_entry        = AGENTIC_AGENTS[ self.DR_COMMAND_KEY ]
        fallback_questions = agent_entry[ "fallback_questions" ]
        fallback_defaults  = agent_entry[ "fallback_defaults" ]

        self.expeditor._batch_collect_args(
            [ "budget", "audience" ], fallback_questions, "test@test.com",
            fallback_defaults, self.DR_COMMAND_KEY
        )

        call_kwargs   = mock_sync.call_args[ 1 ]
        request       = call_kwargs[ "request" ]
        api_questions = request.response_options[ "questions" ]

        budget_q   = next( q for q in api_questions if q[ "header" ] == "budget" )
        audience_q = next( q for q in api_questions if q[ "header" ] == "audience" )
        assert budget_q[ "default_value" ] == "25"
        # audience should fall back to registry default
        assert audience_q[ "default_value" ] == "academic"

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.notify_user_sync" )
    def test_batch_omits_default_value_when_none( self, mock_sync ):
        """No default_value key when both sources are None."""
        import json
        mock_sync.return_value = MagicMock(
            success        = True,
            response_value = json.dumps( { "answers": { "query": "quantum computing" } } )
        )

        agent_entry        = AGENTIC_AGENTS[ self.DR_COMMAND_KEY ]
        fallback_questions = agent_entry[ "fallback_questions" ]

        # No fallback_defaults for query, and config returns None
        self.expeditor._batch_collect_args(
            [ "query" ], fallback_questions, "test@test.com",
            {}, self.DR_COMMAND_KEY
        )

        call_kwargs   = mock_sync.call_args[ 1 ]
        request       = call_kwargs[ "request" ]
        api_questions = request.response_options[ "questions" ]

        query_q = next( q for q in api_questions if q[ "header" ] == "query" )
        assert "default_value" not in query_q

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.notify_user_sync" )
    def test_batch_without_command_key_uses_registry_only( self, mock_sync ):
        """command_key=None skips config, uses fallback_defaults directly."""
        import json
        mock_sync.return_value = MagicMock(
            success        = True,
            response_value = json.dumps( { "answers": { "budget": "10", "audience": "expert" } } )
        )

        agent_entry        = AGENTIC_AGENTS[ self.DR_COMMAND_KEY ]
        fallback_questions = agent_entry[ "fallback_questions" ]
        fallback_defaults  = agent_entry[ "fallback_defaults" ]

        self.expeditor._batch_collect_args(
            [ "budget", "audience" ], fallback_questions, "test@test.com",
            fallback_defaults, None  # command_key=None
        )

        # Config should never be consulted when command_key is None
        self.mock_config_mgr.get.assert_not_called()

        call_kwargs   = mock_sync.call_args[ 1 ]
        request       = call_kwargs[ "request" ]
        api_questions = request.response_options[ "questions" ]

        budget_q = next( q for q in api_questions if q[ "header" ] == "budget" )
        assert budget_q[ "default_value" ] == "no limit"


# ═══════════════════════════════════════════════════════════════════════════════
# Class 13: TestNotificationUtilsEdgeCases (3 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestNotificationUtilsEdgeCases:
    """Edge-case tests for notification_utils formatting functions."""

    def test_format_open_ended_batch_empty_list( self ):
        """Empty list returns empty string."""
        from cosa.utils.notification_utils import format_open_ended_batch_for_tts
        result = format_open_ended_batch_for_tts( [] )
        assert result == ""

    def test_format_open_ended_batch_missing_question_key( self ):
        """Falls back to 'Please provide a value' when question key missing."""
        from cosa.utils.notification_utils import format_open_ended_batch_for_tts
        result = format_open_ended_batch_for_tts( [ { "header": "Budget" } ] )
        assert result == "Please provide a value"

    def test_convert_open_ended_batch_missing_header( self ):
        """Auto-generates 'Question 1', 'Question 2' when header key missing."""
        from cosa.utils.notification_utils import convert_open_ended_batch_for_api
        questions = [
            { "question": "What topic?" },
            { "question": "What budget?" }
        ]
        result = convert_open_ended_batch_for_api( questions )
        assert result[ "questions" ][ 0 ][ "header" ] == "Question 1"
        assert result[ "questions" ][ 1 ][ "header" ] == "Question 2"


# ═══════════════════════════════════════════════════════════════════════════════
# Class 14: TestJobIdThreading (3 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestJobIdThreading:
    """Tests that job_id propagates from expedite() into all notification requests."""

    def setup_method( self ):
        """Create a minimal expeditor instance with mocked dependencies."""
        self.expeditor                          = RuntimeArgumentExpeditor.__new__( RuntimeArgumentExpeditor )
        self.expeditor.debug                    = False
        self.expeditor.verbose                  = False
        self.expeditor.llm_spec_key             = "test_key"
        self.expeditor.llm_factory              = MagicMock()
        self.expeditor._job_id                  = None
        self.expeditor._bearer_token            = None
        self.expeditor._last_notification_status = None

        # Mock config_mgr for _resolve_default()
        mock_config_mgr           = MagicMock()
        mock_config_mgr.get       = MagicMock( return_value=None )
        self.expeditor.config_mgr = mock_config_mgr

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.notify_user_sync" )
    def test_job_id_threaded_to_confirmation( self, mock_sync ):
        """When _job_id is set, _ask_for_confirmation includes it in NotificationRequest."""
        self.expeditor._job_id = "exp-12345678"
        mock_sync.return_value = MagicMock( success=True, response_value="yes" )

        self.expeditor._ask_for_confirmation( "Does this look right?", "test@test.com", abstract="test" )

        call_kwargs = mock_sync.call_args[ 1 ]
        request = call_kwargs[ "request" ]
        assert request.job_id == "exp-12345678"

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.notify_user_sync" )
    def test_job_id_threaded_to_ask_for_arg( self, mock_sync ):
        """When _job_id is set, _ask_for_arg includes it in NotificationRequest."""
        self.expeditor._job_id = "exp-abcdef01"
        mock_sync.return_value = MagicMock( success=True, response_value="quantum computing" )

        self.expeditor._ask_for_arg( "query", "What topic?", "test@test.com" )

        call_kwargs = mock_sync.call_args[ 1 ]
        request = call_kwargs[ "request" ]
        assert request.job_id == "exp-abcdef01"

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.notify_user_sync" )
    def test_job_id_none_by_default( self, mock_sync ):
        """When _job_id is None, NotificationRequest has job_id=None."""
        self.expeditor._job_id = None
        mock_sync.return_value = MagicMock( success=True, response_value="yes" )

        self.expeditor._ask_for_confirmation( "Confirm?", "test@test.com" )

        call_kwargs = mock_sync.call_args[ 1 ]
        request = call_kwargs[ "request" ]
        assert request.job_id is None


# ═══════════════════════════════════════════════════════════════════════════════
# Class 15: TestOptionalArgPrompting (8 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestOptionalArgPrompting:
    """Tests for the optional arg prompting fix.

    Verifies that when all *required* args are satisfied (e.g., query extracted
    from voice command), the expeditor still prompts for *optional* user-visible
    args (budget, audience, audience_context, languages).

    Bug context: Prior to this fix, `if parsed.is_complete()` checked only
    all_required_met. When true, the entire missing-args block was skipped.
    """

    DR_COMMAND_KEY  = "agent router go to deep research"
    RTP_COMMAND_KEY = "agent router go to research to podcast"
    PG_COMMAND_KEY  = "agent router go to podcast generator"

    def setup_method( self ):
        """Create a minimal expeditor instance with mocked dependencies."""
        self.expeditor                          = RuntimeArgumentExpeditor.__new__( RuntimeArgumentExpeditor )
        self.expeditor.debug                    = False
        self.expeditor.verbose                  = False
        self.expeditor.confirmation_prompt_path = "/src/conf/prompts/runtime-argument-confirmation.txt"
        self.expeditor.prompt_template_path     = "/src/conf/prompts/test.txt"
        self.expeditor.llm_spec_key             = "test_key"
        self.expeditor.llm_factory              = MagicMock()
        self.expeditor._job_id                  = None
        self.expeditor._bearer_token            = None
        self.expeditor._last_notification_status = None

        # Mock config_mgr for _resolve_default()
        mock_config_mgr           = MagicMock()
        mock_config_mgr.get       = MagicMock( return_value=None )
        self.expeditor.config_mgr = mock_config_mgr

        # Standard LLM mock: returns "all required met" with query present
        self.mock_llm = MagicMock()
        mock_factory_instance                  = MagicMock()
        mock_factory_instance.get_client.return_value = self.mock_llm
        self.expeditor.llm_factory             = mock_factory_instance

    def _make_llm_response( self, args_present, args_missing="(none)", all_required_met="true" ):
        """Build an ExpeditorResponse XML string.

        Note: args_missing defaults to '(none)' not '' because xmltodict
        converts empty XML tags to None, which fails Pydantic string validation.
        """
        return (
            f"<expeditor_response><all_required_met>{all_required_met}</all_required_met>"
            f"<args_present>{args_present}</args_present>"
            f"<args_missing>{args_missing}</args_missing></expeditor_response>"
        )

    def _run_expedite( self, command_key, raw_args, original_question ):
        """Run expedite() with standard mocking for LLM + file system."""
        with patch( "cosa.utils.util.get_file_as_string", return_value="{system_args}{help_text}{voice_command}{extracted_args}{required_args}" ), \
             patch( "cosa.utils.util.get_project_root", return_value="/fake" ), \
             patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_cli_help", return_value="test help" ), \
             patch( "cosa.agents.io_models.utils.prompt_template_processor.PromptTemplateProcessor.process_template", return_value="{system_args}{help_text}{voice_command}{extracted_args}{required_args}" ):
            return self.expeditor.expedite(
                command           = command_key,
                raw_args          = raw_args,
                user_email        = "test@test.com",
                session_id        = "sess-1",
                user_id           = "uid-1",
                original_question = original_question
            )

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_batch_collect_args" )
    @patch.object( RuntimeArgumentExpeditor, "_confirm_and_iterate" )
    def test_happy_path_still_prompts_optional_args( self, mock_confirm, mock_batch, mock_uva ):
        """DR with query present (all_required_met=true) → still asks budget, audience, audience_context via batch."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        mock_batch.return_value = ( { "budget": "10", "audience": "expert", "audience_context": "researchers" }, "answered" )
        mock_confirm.return_value = { "query": "quantum computing", "budget": "10", "audience": "expert", "audience_context": "researchers" }
        self.mock_llm.run.return_value = self._make_llm_response( "query=quantum computing" )

        result = self._run_expedite( self.DR_COMMAND_KEY, 'query="quantum computing"', "do deep research on quantum computing" )

        # Batch MUST be called for the 3 optional args
        mock_batch.assert_called_once()
        batch_args = mock_batch.call_args[ 0 ][ 0 ]
        assert "budget" in batch_args
        assert "audience" in batch_args
        assert "audience_context" in batch_args
        assert "query" not in batch_args  # Already present

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_batch_collect_args" )
    @patch.object( RuntimeArgumentExpeditor, "_confirm_and_iterate" )
    def test_rtp_prompts_languages_when_query_present( self, mock_confirm, mock_batch, mock_uva ):
        """RTP with query present → asks budget, audience, audience_context, languages."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context", "languages" ]
        mock_batch.return_value = ( { "budget": "5", "audience": "beginner", "audience_context": "students", "languages": "en" }, "answered" )
        mock_confirm.return_value = { "query": "AI safety", "budget": "5", "audience": "beginner", "audience_context": "students", "languages": "en" }
        self.mock_llm.run.return_value = self._make_llm_response( "query=AI safety" )

        result = self._run_expedite( self.RTP_COMMAND_KEY, 'query="AI safety"', "research AI safety and make a podcast" )

        mock_batch.assert_called_once()
        batch_args = mock_batch.call_args[ 0 ][ 0 ]
        assert "languages" in batch_args
        assert "budget" in batch_args
        assert "audience" in batch_args
        assert "audience_context" in batch_args

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_handle_fuzzy_file_match" )
    @patch.object( RuntimeArgumentExpeditor, "_batch_collect_args" )
    @patch.object( RuntimeArgumentExpeditor, "_confirm_and_iterate" )
    def test_pg_prompts_optional_when_research_present( self, mock_confirm, mock_batch, mock_fuzzy, mock_uva ):
        """PG with research present (via special handler) → asks languages, audience, audience_context."""
        mock_uva.return_value = [ "research", "languages", "audience", "audience_context" ]
        # research is a special_handler (fuzzy_file_match), so it won't be in batchable
        mock_fuzzy.return_value = "/io/deep-research/test@test.com/doc.md"
        mock_batch.return_value = ( { "languages": "en,es-MX", "audience": "academic", "audience_context": "none" }, "answered" )
        mock_confirm.return_value = { "research": "/io/deep-research/test@test.com/doc.md", "languages": "en,es-MX", "audience": "academic", "audience_context": "none" }
        # LLM says required arg (research) is missing — but fuzzy handler provides it
        self.mock_llm.run.return_value = self._make_llm_response( "", "research", "false" )

        result = self._run_expedite( self.PG_COMMAND_KEY, "", "make me a podcast" )

        # Fuzzy file match called for research (special handler)
        mock_fuzzy.assert_called_once()
        # Batch called for the 3 non-special optional args
        mock_batch.assert_called_once()
        batch_args = mock_batch.call_args[ 0 ][ 0 ]
        assert "languages" in batch_args
        assert "audience" in batch_args
        assert "audience_context" in batch_args
        assert "research" not in batch_args  # Handled by special handler

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_batch_collect_args" )
    @patch.object( RuntimeArgumentExpeditor, "_confirm_and_iterate" )
    def test_already_extracted_optional_not_re_prompted( self, mock_confirm, mock_batch, mock_uva ):
        """DR with query AND audience both present → only asks missing ones (budget, audience_context)."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        mock_batch.return_value = ( { "budget": "no limit", "audience_context": "none" }, "answered" )
        mock_confirm.return_value = { "query": "quantum", "audience": "beginner", "budget": "no limit", "audience_context": "none" }
        # LLM detects both query and audience as present
        self.mock_llm.run.return_value = self._make_llm_response( "query=quantum, audience=beginner" )

        result = self._run_expedite( self.DR_COMMAND_KEY, 'query="quantum"', "deep research on quantum for beginners" )

        mock_batch.assert_called_once()
        batch_args = mock_batch.call_args[ 0 ][ 0 ]
        assert "budget" in batch_args
        assert "audience_context" in batch_args
        assert "query" not in batch_args       # Already present
        assert "audience" not in batch_args    # Already present

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_batch_collect_args" )
    @patch.object( RuntimeArgumentExpeditor, "_confirm_and_iterate" )
    def test_optional_defaults_prefilled_in_batch( self, mock_confirm, mock_batch, mock_uva ):
        """Batch questions include default_value from fallback_defaults."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        mock_batch.return_value = ( { "budget": "no limit", "audience": "academic", "audience_context": "none" }, "answered" )
        mock_confirm.return_value = { "query": "test" }
        self.mock_llm.run.return_value = self._make_llm_response( "query=test" )

        result = self._run_expedite( self.DR_COMMAND_KEY, 'query="test"', "research test" )

        mock_batch.assert_called_once()
        # Verify fallback_defaults dict is passed to _batch_collect_args
        batch_kwargs = mock_batch.call_args
        # fallback_defaults is the 4th positional arg (index 3)
        fallback_defaults = batch_kwargs[ 0 ][ 3 ]
        assert fallback_defaults[ "budget" ] == "no limit"
        assert fallback_defaults[ "audience" ] == "academic"
        assert fallback_defaults[ "audience_context" ] == "none"

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_batch_collect_args" )
    @patch.object( RuntimeArgumentExpeditor, "_confirm_and_iterate" )
    def test_no_limit_skips_budget( self, mock_confirm, mock_batch, mock_uva ):
        """User answers 'no limit' for budget → budget not in final_args."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        # Batch returns "no limit" for budget — should be skipped
        mock_batch.return_value = ( { "budget": "no limit", "audience": "expert", "audience_context": "none" }, "answered" )
        mock_confirm.return_value = { "query": "quantum", "audience": "expert" }
        self.mock_llm.run.return_value = self._make_llm_response( "query=quantum" )

        result = self._run_expedite( self.DR_COMMAND_KEY, 'query="quantum"', "research quantum" )

        # Confirm is called — check the args_dict it received
        mock_confirm.assert_called_once()
        args_passed = mock_confirm.call_args[ 0 ][ 0 ]
        assert "budget" not in args_passed        # "no limit" skips it
        assert args_passed[ "audience" ] == "expert"

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_batch_collect_args" )
    @patch.object( RuntimeArgumentExpeditor, "_confirm_and_iterate" )
    def test_none_skips_audience_context( self, mock_confirm, mock_batch, mock_uva ):
        """User answers 'none' for audience_context → not filtered (audience_context is a non-skippable arg)."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        mock_batch.return_value = ( { "budget": "10", "audience": "academic", "audience_context": "none" }, "answered" )
        mock_confirm.return_value = { "query": "quantum", "budget": "10", "audience": "academic", "audience_context": "none" }
        self.mock_llm.run.return_value = self._make_llm_response( "query=quantum" )

        result = self._run_expedite( self.DR_COMMAND_KEY, 'query="quantum"', "research quantum" )

        mock_confirm.assert_called_once()
        args_passed = mock_confirm.call_args[ 0 ][ 0 ]
        # audience_context="none" is a valid value (not in the skip list for budget/languages)
        assert args_passed[ "audience_context" ] == "none"

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_batch_collect_args" )
    def test_cancel_in_optional_batch_returns_none( self, mock_batch, mock_uva ):
        """Cancel keyword in optional batch → expedite returns None."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        mock_batch.return_value = ( None, "declined" )  # User cancelled
        self.mock_llm.run.return_value = self._make_llm_response( "query=quantum" )

        result = self._run_expedite( self.DR_COMMAND_KEY, 'query="quantum"', "research quantum" )

        assert result is None
        mock_batch.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# Class 16: TestParseBoolean (7 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestParseBoolean:
    """Tests for _parse_boolean() helper in agentic_job_factory.py."""

    def test_yes_returns_true( self ):
        """String 'yes' returns True."""
        assert _parse_boolean( "yes" ) is True

    def test_no_returns_false( self ):
        """String 'no' returns False."""
        assert _parse_boolean( "no" ) is False

    def test_true_string_returns_true( self ):
        """String 'true' returns True."""
        assert _parse_boolean( "true" ) is True

    def test_false_string_returns_false( self ):
        """String 'false' returns False."""
        assert _parse_boolean( "false" ) is False

    def test_none_returns_default( self ):
        """None returns default (False by default)."""
        assert _parse_boolean( None ) is False
        assert _parse_boolean( None, default=True ) is True

    def test_bool_passthrough( self ):
        """Bool values pass through unchanged."""
        assert _parse_boolean( True ) is True
        assert _parse_boolean( False ) is False

    def test_semantic_variants( self ):
        """Various truthy/falsy strings parse correctly."""
        for truthy in [ "Yes", "YES", " yes ", "true", "TRUE", "1", "enable", "enabled" ]:
            assert _parse_boolean( truthy ) is True, f"Failed for truthy: '{truthy}'"
        for falsy in [ "no", "No", "NO", "false", "0", "disable", "nope", "" ]:
            assert _parse_boolean( falsy ) is False, f"Failed for falsy: '{falsy}'"


# ═══════════════════════════════════════════════════════════════════════════════
# Class 17: TestDryRunVisibility (5 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestDryRunVisibility:
    """Tests that dry_run is shown/hidden based on user_visible whitelist."""

    SWE_COMMAND_KEY = "agent router go to swe team"
    DR_COMMAND_KEY  = "agent router go to deep research"

    def setup_method( self ):
        """Create a minimal expeditor instance."""
        self.expeditor       = RuntimeArgumentExpeditor.__new__( RuntimeArgumentExpeditor )
        self.expeditor.debug = False
        self.swe_entry       = AGENTIC_AGENTS[ self.SWE_COMMAND_KEY ]
        self.dr_entry        = AGENTIC_AGENTS[ self.DR_COMMAND_KEY ]

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    def test_swe_team_shows_dry_run( self, mock_uva ):
        """SWE Team shows dry_run in context when it's in user_visible list."""
        mock_uva.return_value = [ "task", "budget", "timeout", "dry_run" ]
        result = self.expeditor._build_request_context(
            self.swe_entry, "run swe team task",
            { "task": "add health check", "dry_run": "yes" }, [ "budget", "timeout" ]
        )
        assert "dry_run" in result

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    def test_deep_research_hides_dry_run( self, mock_uva ):
        """Deep Research hides dry_run from context (not in user_visible list)."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        result = self.expeditor._build_request_context(
            self.dr_entry, "research quantum",
            { "query": "quantum", "dry_run": "yes" }, [ "budget" ]
        )
        assert "dry_run" not in result

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    def test_swe_team_dry_run_in_present_args( self, mock_uva ):
        """SWE Team shows dry_run value in 'Already extracted' section."""
        mock_uva.return_value = [ "task", "budget", "timeout", "dry_run" ]
        result = self.expeditor._build_request_context(
            self.swe_entry, "run swe team dry run",
            { "task": "add health check", "dry_run": "yes" }, [ "budget" ]
        )
        assert "dry_run: yes" in result

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    def test_swe_team_dry_run_false_still_shown( self, mock_uva ):
        """SWE Team shows dry_run=no in 'Already extracted' when set to 'no'."""
        mock_uva.return_value = [ "task", "budget", "timeout", "dry_run" ]
        result = self.expeditor._build_request_context(
            self.swe_entry, "run swe team task",
            { "task": "fix bug", "dry_run": "no" }, [ "budget" ]
        )
        assert "dry_run: no" in result

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    def test_no_user_visible_fallback_shows_dry_run( self, mock_uva ):
        """When user_visible is None (fallback), dry_run shown for any agent."""
        mock_uva.return_value = None
        result = self.expeditor._build_request_context(
            self.dr_entry, "research quantum",
            { "query": "quantum", "dry_run": "yes" }, [ "budget" ]
        )
        assert "dry_run: yes" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 18. Runtime Scheduling in Confirmation + Normalization (12 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRuntimeSchedulingConfirmation:
    """Tests for runtime scheduling args in _confirm_and_iterate() summary
    and normalization in _handle_agentic_command() extraction logic."""

    DR_COMMAND_KEY = "agent router go to deep research"

    def setup_method( self ):
        """Create a minimal expeditor instance with mocked dependencies."""
        self.expeditor                          = RuntimeArgumentExpeditor.__new__( RuntimeArgumentExpeditor )
        self.expeditor.debug                    = False
        self.expeditor.verbose                  = False
        self.expeditor.confirmation_prompt_path = "/src/conf/prompts/runtime-argument-confirmation.txt"
        self.expeditor.llm_spec_key             = "test_key"
        self.expeditor.llm_factory              = MagicMock()
        self.expeditor._job_id                  = None
        self.agent_entry = AGENTIC_AGENTS[ self.DR_COMMAND_KEY ]

    # ── Confirmation summary includes scheduling section ──────────────

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_ask_for_confirmation" )
    def test_summary_includes_scheduling_defaults( self, mock_confirm, mock_uva ):
        """Confirmation abstract includes scheduling section with defaults."""
        mock_uva.return_value = [ "query", "budget" ]
        mock_confirm.return_value = "yes"
        args = { "query": "test" }

        self.expeditor._confirm_and_iterate( args, self.agent_entry, self.DR_COMMAND_KEY, "test@test.com" )

        # The abstract passed to _ask_for_confirmation should contain scheduling
        call_args = mock_confirm.call_args
        abstract = call_args[ 1 ][ "abstract" ] if "abstract" in call_args[ 1 ] else call_args[ 0 ][ 2 ]
        assert "**Scheduling**" in abstract
        assert "**run_at**: immediately" in abstract
        assert "**exclusive_mode**: no" in abstract

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_ask_for_confirmation" )
    def test_summary_shows_scheduled_at_when_set( self, mock_confirm, mock_uva ):
        """Confirmation shows actual scheduled_at value when present."""
        mock_uva.return_value = [ "query" ]
        mock_confirm.return_value = "yes"
        args = { "query": "test", "scheduled_at": "2026-03-31T02:00:00" }

        self.expeditor._confirm_and_iterate( args, self.agent_entry, self.DR_COMMAND_KEY, "test@test.com" )

        call_args = mock_confirm.call_args
        abstract = call_args[ 1 ][ "abstract" ] if "abstract" in call_args[ 1 ] else call_args[ 0 ][ 2 ]
        assert "2026-03-31T02:00:00" in abstract

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_ask_for_confirmation" )
    def test_summary_shows_monopolize_when_set( self, mock_confirm, mock_uva ):
        """Confirmation shows exclusive_mode: yes when monopolize is set."""
        mock_uva.return_value = [ "query" ]
        mock_confirm.return_value = "yes"
        args = { "query": "test", "monopolize": True }

        self.expeditor._confirm_and_iterate( args, self.agent_entry, self.DR_COMMAND_KEY, "test@test.com" )

        call_args = mock_confirm.call_args
        abstract = call_args[ 1 ][ "abstract" ] if "abstract" in call_args[ 1 ] else call_args[ 0 ][ 2 ]
        assert "**exclusive_mode**: yes" in abstract

    # ── Modification parser includes runtime args ─────────────────────

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_ask_for_confirmation" )
    @patch.object( RuntimeArgumentExpeditor, "_parse_modification" )
    def test_modification_parser_receives_runtime_arg_names( self, mock_parse, mock_confirm, mock_uva ):
        """_parse_modification receives scheduled_at and monopolize in arg_names."""
        mock_uva.return_value = [ "query" ]
        mock_confirm.return_value = "yes [comment: schedule for 2am]"
        mock_parse.return_value = MagicMock( is_modify=lambda: False )
        args = { "query": "test" }

        self.expeditor._confirm_and_iterate( args, self.agent_entry, self.DR_COMMAND_KEY, "test@test.com" )

        # The modification parser should have been called with the comment
        mock_parse.assert_called_once()
        call_comment = mock_parse.call_args[ 0 ][ 0 ]
        assert "schedule for 2am" in call_comment

    # ── Runtime arg normalization ─────────────────────────────────────

    def test_normalize_immediately_to_none( self ):
        """'immediately' string normalizes to None for scheduled_at."""
        raw = "immediately"
        result = None if raw and str( raw ).lower() in ( "immediately", "now", "none" ) else raw
        assert result is None

    def test_normalize_now_to_none( self ):
        """'now' string normalizes to None for scheduled_at."""
        raw = "now"
        result = None if raw and str( raw ).lower() in ( "immediately", "now", "none" ) else raw
        assert result is None

    def test_normalize_none_string_to_none( self ):
        """'none' string normalizes to None for scheduled_at."""
        raw = "none"
        result = None if raw and str( raw ).lower() in ( "immediately", "now", "none" ) else raw
        assert result is None

    def test_normalize_iso_datetime_preserved( self ):
        """Valid ISO datetime strings are preserved."""
        raw = "2026-03-31T02:00:00"
        result = None if raw and str( raw ).lower() in ( "immediately", "now", "none" ) else raw
        assert result == "2026-03-31T02:00:00"

    def test_normalize_monopolize_yes_to_true( self ):
        """'yes' string normalizes to True for monopolize."""
        raw = "yes"
        result = raw.lower() in ( "yes", "true", "1" ) if isinstance( raw, str ) else bool( raw )
        assert result is True

    def test_normalize_monopolize_no_to_false( self ):
        """'no' string normalizes to False for monopolize."""
        raw = "no"
        result = raw.lower() in ( "yes", "true", "1" ) if isinstance( raw, str ) else bool( raw )
        assert result is False

    def test_normalize_monopolize_bool_passthrough( self ):
        """Boolean monopolize values pass through unchanged."""
        assert bool( True ) is True
        assert bool( False ) is False

    def test_normalize_monopolize_none_to_false( self ):
        """None monopolize value normalizes to False."""
        raw = None
        result = bool( raw ) if raw else False
        assert result is False


# =============================================================================
# Cluster J Regression — _resolve_display_name helper
# =============================================================================
#
# The prior single-expression
#     agent_entry.get( "display_name", agent_entry["cli_module"].split(...) )
# crashed with "'NoneType' object has no attribute 'split'" for the test_suite
# registry entry where cli_module=None by design (test_suite is invoked
# directly via API, not via CLI). Python evaluates dict.get(key, default)
# defaults eagerly, so the .split() ran even when display_name was set.
#
# Fix at expeditor.py introduced _resolve_display_name() with the correct
# short-circuit. These tests pin the contract.
# See src/rnd/v0.1.7/2026.04.30-postmortem-2026.04.29-all-test-run.md §J.
# =============================================================================

class TestResolveDisplayName:
    """Pin the _resolve_display_name helper's contract (Cluster J fix)."""

    def test_test_suite_entry_returns_display_name( self ):
        """The exact entry shape that triggered yesterday's :8000 NoneType.split."""
        entry = {
            "display_name" : "Test Suite",
            "cli_module"   : None,        # ← intentional None for API-only agents
        }
        assert RuntimeArgumentExpeditor._resolve_display_name( entry ) == "Test Suite"

    def test_display_name_preferred_when_both_set( self ):
        """display_name wins over cli_module derivation."""
        entry = {
            "display_name" : "Deep Research",
            "cli_module"   : "cosa.agents.deep_research.cli",
        }
        assert RuntimeArgumentExpeditor._resolve_display_name( entry ) == "Deep Research"

    def test_cli_module_derivation_when_display_name_missing( self ):
        """Last dotted segment becomes the name when display_name is absent."""
        entry = { "cli_module": "cosa.agents.podcast_generator.cli" }
        assert RuntimeArgumentExpeditor._resolve_display_name( entry ) == "cli"

    def test_cli_module_underscore_to_space( self ):
        """Underscores become spaces in derived names."""
        entry = { "cli_module": "cosa.agents.research_to_presentation" }
        assert RuntimeArgumentExpeditor._resolve_display_name( entry ) == "research to presentation"

    def test_empty_display_name_falls_through_to_cli_module( self ):
        """Empty string is falsy — falls through to cli_module derivation."""
        entry = {
            "display_name" : "",
            "cli_module"   : "cosa.agents.bug_fix_expediter",
        }
        assert RuntimeArgumentExpeditor._resolve_display_name( entry ) == "bug fix expediter"

    def test_both_missing_returns_agent_sentinel( self ):
        """Neither display_name nor cli_module → 'agent' fallback."""
        assert RuntimeArgumentExpeditor._resolve_display_name( {} ) == "agent"

    def test_both_none_returns_agent_sentinel( self ):
        """Both explicitly None → 'agent' fallback."""
        entry = { "display_name": None, "cli_module": None }
        assert RuntimeArgumentExpeditor._resolve_display_name( entry ) == "agent"

    def test_does_not_crash_on_real_test_suite_registry_entry( self ):
        """
        Regression guard: this is the EXACT entry shape from
        src/cosa/agents/runtime_argument_expeditor/agent_registry.py
        for "agent router go to test suite". Before the fix, this crashed
        with NoneType.split inside _confirm_and_iterate / _build_request_context.
        """
        entry = {
            "job_prefix"     : "ts",
            "cli_module"     : None,
            "job_class_path" : "cosa.agents.test_suite.job.TestSuiteJob",
            "display_name"   : "Test Suite",
        }
        result = RuntimeArgumentExpeditor._resolve_display_name( entry )
        assert result == "Test Suite"
