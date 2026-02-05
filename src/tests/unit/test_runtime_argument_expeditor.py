"""
Unit tests for Runtime Argument Expeditor.

Tests 5 components:
1. ExpeditorResponse model (xml_models.py) - 16 tests
2. _parse_lora_args() (expeditor.py) - 9 tests
3. _inject_system_args() (expeditor.py) - 4 tests
4. Agent registry + get_cli_help() (agent_registry.py) - 11 tests
5. create_agentic_job() factory (agentic_job_factory.py) - 9 tests

All external dependencies mocked. No server, no LLM, no filesystem I/O.

Created: 2026-02-05
"""

import pytest
from unittest.mock import patch, MagicMock
import subprocess

from cosa.agents.runtime_argument_expeditor.xml_models import ExpeditorResponse
from cosa.agents.runtime_argument_expeditor.expeditor import RuntimeArgumentExpeditor
from cosa.agents.runtime_argument_expeditor.agent_registry import (
    AGENTIC_AGENTS,
    get_cli_help,
    _help_cache
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
# Class 4: TestAgentRegistry (11 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentRegistry:
    """Tests for AGENTIC_AGENTS dict and get_cli_help() function."""

    def setup_method( self ):
        """Clear the help cache before each test."""
        _help_cache.clear()

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
