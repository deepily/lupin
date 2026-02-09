"""
Unit tests for Runtime Argument Expeditor.

Tests 8 components:
1. ExpeditorResponse model (xml_models.py) - 16 tests
2. _parse_lora_args() (expeditor.py) - 9 tests
3. _inject_system_args() (expeditor.py) - 4 tests
4. Agent registry + get_cli_help() + get_user_visible_args() (agent_registry.py) - 18 tests
5. create_agentic_job() factory (agentic_job_factory.py) - 12 tests
6. ArgConfirmationResponse model (xml_models.py) - 8 tests
7. _confirm_and_iterate() (expeditor.py) - 9 tests
8. _batch_collect_args() + batch integration (expeditor.py) - 6 tests

All external dependencies mocked. No server, no LLM, no filesystem I/O.

Created: 2026-02-05
Updated: 2026-02-09 — batch open-ended question collection
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
from cosa.rest.agentic_job_factory import create_agentic_job


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
# Class 4: TestAgentRegistry (18 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentRegistry:
    """Tests for AGENTIC_AGENTS dict, get_cli_help(), and get_user_visible_args()."""

    def setup_method( self ):
        """Clear help and user-visible caches before each test."""
        _help_cache.clear()
        _user_visible_cache.clear()

    def test_registry_has_three_agents( self ):
        """Registry contains exactly 3 agentic agents."""
        assert len( AGENTIC_AGENTS ) == 3

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

    def test_all_agents_have_audience_in_arg_mapping( self ):
        """All three agents have 'audience' and 'audience_context' in arg_mapping."""
        for cmd_key, entry in AGENTIC_AGENTS.items():
            mapping = entry[ "arg_mapping" ]
            assert "audience" in mapping, f"Missing 'audience' in arg_mapping for '{cmd_key}'"
            assert mapping[ "audience" ] == "audience"
            assert "audience_context" in mapping, f"Missing 'audience_context' in arg_mapping for '{cmd_key}'"
            assert mapping[ "audience_context" ] == "audience_context"

    def test_all_agents_have_audience_fallback_question( self ):
        """All three agents have 'audience' and 'audience_context' in fallback_questions."""
        for cmd_key, entry in AGENTIC_AGENTS.items():
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
# Class 5: TestCreateAgenticJob (9 tests)
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
# Class 7: TestConfirmAndIterate (9 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfirmAndIterate:
    """Tests for RuntimeArgumentExpeditor._confirm_and_iterate() with mocked voice I/O."""

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
    @patch.object( RuntimeArgumentExpeditor, "_ask_for_arg" )
    def test_immediate_approval_yes( self, mock_ask, mock_uva ):
        """User says 'yes' → returns args immediately."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        mock_ask.return_value = "yes"
        args = { "query": "quantum computing" }

        result = self.expeditor._confirm_and_iterate( args, self.agent_entry, self.DR_COMMAND_KEY, "test@test.com" )

        assert result == args
        mock_ask.assert_called_once()

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_ask_for_arg" )
    def test_immediate_approval_looks_good( self, mock_ask, mock_uva ):
        """User says 'looks good' → returns args immediately."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        mock_ask.return_value = "looks good"
        args = { "query": "AI safety" }

        result = self.expeditor._confirm_and_iterate( args, self.agent_entry, self.DR_COMMAND_KEY, "test@test.com" )

        assert result == args

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_ask_for_arg" )
    def test_cancel_keyword( self, mock_ask, mock_uva ):
        """User says 'cancel' → returns None."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        mock_ask.return_value = "cancel"
        args = { "query": "test" }

        result = self.expeditor._confirm_and_iterate( args, self.agent_entry, self.DR_COMMAND_KEY, "test@test.com" )

        assert result is None

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_ask_for_arg" )
    def test_timeout_returns_none( self, mock_ask, mock_uva ):
        """_ask_for_arg returns None (timeout) → returns None."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        mock_ask.return_value = None
        args = { "query": "test" }

        result = self.expeditor._confirm_and_iterate( args, self.agent_entry, self.DR_COMMAND_KEY, "test@test.com" )

        assert result is None

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_parse_modification" )
    @patch.object( RuntimeArgumentExpeditor, "_ask_for_arg" )
    def test_modify_then_approve( self, mock_ask, mock_parse, mock_uva ):
        """User requests modification, then approves on second prompt."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        mock_ask.side_effect = [ "change the budget to 50", "yes" ]
        mock_parse.return_value = ArgConfirmationResponse(
            action="modify", arg_name="budget", new_value="50"
        )
        args = { "query": "quantum computing" }

        result = self.expeditor._confirm_and_iterate( args, self.agent_entry, self.DR_COMMAND_KEY, "test@test.com" )

        assert result is not None
        assert result[ "budget" ] == "50"
        assert result[ "query" ] == "quantum computing"

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_parse_modification" )
    @patch.object( RuntimeArgumentExpeditor, "_ask_for_arg" )
    def test_llm_parse_fails_treats_as_approval( self, mock_ask, mock_parse, mock_uva ):
        """LLM parse failure → treated as approval (safe fallback)."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        mock_ask.return_value = "something unparseable"
        mock_parse.return_value = None
        args = { "query": "test" }

        result = self.expeditor._confirm_and_iterate( args, self.agent_entry, self.DR_COMMAND_KEY, "test@test.com" )

        assert result == args

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_parse_modification" )
    @patch.object( RuntimeArgumentExpeditor, "_ask_for_arg" )
    def test_llm_returns_cancel( self, mock_ask, mock_parse, mock_uva ):
        """LLM parses user intent as cancel → returns None."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        mock_ask.return_value = "actually nevermind I don't want this"
        mock_parse.return_value = ArgConfirmationResponse(
            action="cancel", arg_name="", new_value=""
        )
        args = { "query": "test" }

        result = self.expeditor._confirm_and_iterate( args, self.agent_entry, self.DR_COMMAND_KEY, "test@test.com" )

        assert result is None

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_ask_for_arg" )
    def test_confirm_only_shows_user_visible_args( self, mock_ask, mock_uva ):
        """Engineering params (lead_model, debug) excluded from summary shown to user."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        # Capture the message passed to _ask_for_arg
        mock_ask.return_value = "yes"
        args = {
            "query"      : "quantum computing",
            "budget"     : "10",
            "lead_model" : "claude-opus-4-20250514",
            "debug"      : True,
        }

        result = self.expeditor._confirm_and_iterate( args, self.agent_entry, self.DR_COMMAND_KEY, "test@test.com" )

        assert result == args
        # Verify the summary message sent to _ask_for_arg
        call_args = mock_ask.call_args[ 0 ]
        message = call_args[ 1 ]  # second positional arg is the message
        assert "query" in message
        assert "budget" in message
        assert "lead_model" not in message
        assert "debug" not in message

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_ask_for_arg" )
    def test_confirm_fallback_when_no_user_visible( self, mock_ask, mock_uva ):
        """When get_user_visible_args returns None, falls back to fallback_questions keys."""
        mock_uva.return_value = None  # Simulate CLI not supporting --user-visible-args
        mock_ask.return_value = "yes"
        args = {
            "query"      : "quantum computing",
            "lead_model" : "claude-opus-4-20250514",
        }

        result = self.expeditor._confirm_and_iterate( args, self.agent_entry, self.DR_COMMAND_KEY, "test@test.com" )

        assert result == args
        # Verify the summary message uses fallback_questions keys
        call_args = mock_ask.call_args[ 0 ]
        message = call_args[ 1 ]
        assert "query" in message
        # lead_model is NOT in fallback_questions, so should be excluded
        assert "lead_model" not in message


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

        result = self.expeditor._batch_collect_args(
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

        result = self.expeditor._batch_collect_args(
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

        result = self.expeditor._batch_collect_args(
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

        result = self.expeditor._batch_collect_args(
            [ "budget", "audience" ], self.fallback_questions, "test@test.com"
        )

        assert result is None

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_batch_collect_args" )
    @patch.object( RuntimeArgumentExpeditor, "_confirm_and_iterate" )
    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.LlmClientFactory" )
    def test_expedite_uses_batch_for_multiple_missing( self, mock_factory, mock_confirm, mock_batch, mock_uva ):
        """When >1 batchable args missing, batch path is taken."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
        mock_batch.return_value = { "budget": "10", "audience": "expert" }
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

    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.get_user_visible_args" )
    @patch.object( RuntimeArgumentExpeditor, "_ask_for_arg" )
    @patch.object( RuntimeArgumentExpeditor, "_confirm_and_iterate" )
    @patch( "cosa.agents.runtime_argument_expeditor.expeditor.LlmClientFactory" )
    def test_expedite_uses_single_for_one_missing( self, mock_factory, mock_confirm, mock_ask, mock_uva ):
        """When exactly 1 batchable arg missing, single path is taken (no batch)."""
        mock_uva.return_value = [ "query", "budget", "audience", "audience_context" ]
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
