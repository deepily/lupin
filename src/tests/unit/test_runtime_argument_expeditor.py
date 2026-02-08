"""
Unit tests for Runtime Argument Expeditor.

Tests 7 components:
1. ExpeditorResponse model (xml_models.py) - 16 tests
2. _parse_lora_args() (expeditor.py) - 9 tests
3. _inject_system_args() (expeditor.py) - 4 tests
4. Agent registry + get_cli_help() (agent_registry.py) - 14 tests
5. create_agentic_job() factory (agentic_job_factory.py) - 12 tests
6. ArgConfirmationResponse model (xml_models.py) - 8 tests
7. _confirm_and_iterate() (expeditor.py) - 7 tests

All external dependencies mocked. No server, no LLM, no filesystem I/O.

Created: 2026-02-05
Updated: 2026-02-07 — audience/audience_context normalization + confirmation loop
"""

import pytest
from unittest.mock import patch, MagicMock
import subprocess

from cosa.agents.runtime_argument_expeditor.xml_models import ExpeditorResponse, ArgConfirmationResponse
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
# Class 7: TestConfirmAndIterate (7 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfirmAndIterate:
    """Tests for RuntimeArgumentExpeditor._confirm_and_iterate() with mocked voice I/O."""

    def setup_method( self ):
        """Create a minimal expeditor instance with mocked dependencies."""
        self.expeditor                          = RuntimeArgumentExpeditor.__new__( RuntimeArgumentExpeditor )
        self.expeditor.debug                    = False
        self.expeditor.verbose                  = False
        self.expeditor.confirmation_prompt_path = "/src/conf/prompts/runtime-argument-confirmation.txt"
        self.expeditor.llm_spec_key             = "test_key"
        self.expeditor.llm_factory              = MagicMock()

        self.agent_entry = AGENTIC_AGENTS[ "agent router go to deep research" ]

    @patch.object( RuntimeArgumentExpeditor, "_ask_for_arg" )
    def test_immediate_approval_yes( self, mock_ask ):
        """User says 'yes' → returns args immediately."""
        mock_ask.return_value = "yes"
        args = { "query": "quantum computing" }

        result = self.expeditor._confirm_and_iterate( args, self.agent_entry, "test@test.com" )

        assert result == args
        mock_ask.assert_called_once()

    @patch.object( RuntimeArgumentExpeditor, "_ask_for_arg" )
    def test_immediate_approval_looks_good( self, mock_ask ):
        """User says 'looks good' → returns args immediately."""
        mock_ask.return_value = "looks good"
        args = { "query": "AI safety" }

        result = self.expeditor._confirm_and_iterate( args, self.agent_entry, "test@test.com" )

        assert result == args

    @patch.object( RuntimeArgumentExpeditor, "_ask_for_arg" )
    def test_cancel_keyword( self, mock_ask ):
        """User says 'cancel' → returns None."""
        mock_ask.return_value = "cancel"
        args = { "query": "test" }

        result = self.expeditor._confirm_and_iterate( args, self.agent_entry, "test@test.com" )

        assert result is None

    @patch.object( RuntimeArgumentExpeditor, "_ask_for_arg" )
    def test_timeout_returns_none( self, mock_ask ):
        """_ask_for_arg returns None (timeout) → returns None."""
        mock_ask.return_value = None
        args = { "query": "test" }

        result = self.expeditor._confirm_and_iterate( args, self.agent_entry, "test@test.com" )

        assert result is None

    @patch.object( RuntimeArgumentExpeditor, "_parse_modification" )
    @patch.object( RuntimeArgumentExpeditor, "_ask_for_arg" )
    def test_modify_then_approve( self, mock_ask, mock_parse ):
        """User requests modification, then approves on second prompt."""
        mock_ask.side_effect = [ "change the budget to 50", "yes" ]
        mock_parse.return_value = ArgConfirmationResponse(
            action="modify", arg_name="budget", new_value="50"
        )
        args = { "query": "quantum computing" }

        result = self.expeditor._confirm_and_iterate( args, self.agent_entry, "test@test.com" )

        assert result is not None
        assert result[ "budget" ] == "50"
        assert result[ "query" ] == "quantum computing"

    @patch.object( RuntimeArgumentExpeditor, "_parse_modification" )
    @patch.object( RuntimeArgumentExpeditor, "_ask_for_arg" )
    def test_llm_parse_fails_treats_as_approval( self, mock_ask, mock_parse ):
        """LLM parse failure → treated as approval (safe fallback)."""
        mock_ask.return_value = "something unparseable"
        mock_parse.return_value = None
        args = { "query": "test" }

        result = self.expeditor._confirm_and_iterate( args, self.agent_entry, "test@test.com" )

        assert result == args

    @patch.object( RuntimeArgumentExpeditor, "_parse_modification" )
    @patch.object( RuntimeArgumentExpeditor, "_ask_for_arg" )
    def test_llm_returns_cancel( self, mock_ask, mock_parse ):
        """LLM parses user intent as cancel → returns None."""
        mock_ask.return_value = "actually nevermind I don't want this"
        mock_parse.return_value = ArgConfirmationResponse(
            action="cancel", arg_name="", new_value=""
        )
        args = { "query": "test" }

        result = self.expeditor._confirm_and_iterate( args, self.agent_entry, "test@test.com" )

        assert result is None
