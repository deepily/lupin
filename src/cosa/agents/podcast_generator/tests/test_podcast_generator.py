#!/usr/bin/env python3
"""
Unit tests for COSA Podcast Generator Agent.

Run with: pytest -v src/cosa/agents/podcast_generator/tests/
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock

# Import modules under test
from cosa.agents.podcast_generator.config import (
    PodcastConfig,
    HostPersonality,
    VoiceProfile,
    DEFAULT_CURIOUS_HOST,
    DEFAULT_EXPERT_HOST,
)
from cosa.agents.podcast_generator.state import (
    OrchestratorState,
    ProsodyAnnotation,
    ScriptSegment,
    PodcastScript,
    ContentAnalysis,
    PodcastMetadata,
    create_initial_state,
)
from cosa.agents.podcast_generator.prompts.script_generation import (
    get_content_analysis_prompt,
    get_script_generation_prompt,
    parse_analysis_response,
    parse_script_response,
    extract_prosody_from_text,
)
from cosa.agents.podcast_generator.prompts.personality import (
    get_personality_prompt_section,
    get_dynamic_duo_description,
    create_personality_from_description,
)


class TestPodcastConfig:
    """Tests for PodcastConfig dataclass."""

    def test_default_instantiation( self ):
        """Test default config values."""
        config = PodcastConfig()
        assert config.script_model == "claude-opus-4-6"
        assert config.target_duration_minutes == 10
        assert config.min_exchanges == 8
        assert config.max_exchanges == 20

    def test_default_host_personalities( self ):
        """Test default host configurations."""
        config = PodcastConfig()
        assert config.host_a_personality.name == "Maria"
        assert config.host_b_personality.name == "Mr. Radio"
        assert config.host_a_personality.role == "Curious Questioner"
        assert config.host_b_personality.role == "Knowledgeable Explainer"

    def test_custom_host_personality( self ):
        """Test custom host personality."""
        custom = HostPersonality(
            name = "Dr. Smith",
            role = "Academic Expert",
            tone = "scholarly",
        )
        config = PodcastConfig( host_a_personality=custom )
        assert config.host_a_personality.name == "Dr. Smith"

    def test_voice_profile_validation( self ):
        """Test VoiceProfile parameter validation."""
        # Valid profile
        valid = VoiceProfile( voice_id="test", stability=0.5 )
        assert valid.stability == 0.5

        # Invalid stability
        with pytest.raises( AssertionError ):
            VoiceProfile( voice_id="test", stability=1.5 )


class TestHostPersonality:
    """Tests for HostPersonality dataclass."""

    def test_to_prompt_description( self ):
        """Test prompt description generation."""
        host = HostPersonality(
            name            = "Alex",
            role            = "Curious Questioner",
            tone            = "enthusiastic",
            typical_phrases = [ "Wait, so...", "Help me understand..." ],
        )
        desc = host.to_prompt_description()
        assert "Alex" in desc
        assert "Curious Questioner" in desc
        assert "enthusiastic" in desc
        assert "Wait, so..." in desc


class TestOrchestratorState:
    """Tests for OrchestratorState enum."""

    def test_state_values( self ):
        """Test state enum values."""
        assert OrchestratorState.LOADING_RESEARCH.value == "loading_research"
        assert OrchestratorState.GENERATING_SCRIPT.value == "generating_script"
        assert OrchestratorState.COMPLETED.value == "completed"

    def test_state_count( self ):
        """Test total number of states."""
        assert len( OrchestratorState ) == 10


class TestProsodyAnnotation:
    """Tests for ProsodyAnnotation enum."""

    def test_annotation_values( self ):
        """Test prosody annotation values."""
        assert ProsodyAnnotation.LAUGH.value == "laugh"
        assert ProsodyAnnotation.PAUSE.value == "pause"
        assert ProsodyAnnotation.WHISPER.value == "whisper"

    def test_annotation_count( self ):
        """Test total number of annotations."""
        assert len( ProsodyAnnotation ) == 13


class TestScriptSegment:
    """Tests for ScriptSegment Pydantic model."""

    def test_segment_creation( self ):
        """Test basic segment creation."""
        segment = ScriptSegment(
            speaker = "Alex",
            role    = "curious",
            text    = "That's fascinating!",
        )
        assert segment.speaker == "Alex"
        assert segment.role == "curious"
        assert segment.prosody == []  # Default

    def test_to_markdown( self ):
        """Test markdown conversion."""
        segment = ScriptSegment(
            speaker = "Jordan",
            role    = "expert",
            text    = "Let me explain...",
        )
        md = segment.to_markdown()
        assert "**[Jordan - Expert]**:" in md
        assert "Let me explain..." in md


class TestPodcastScript:
    """Tests for PodcastScript Pydantic model."""

    def test_script_creation( self ):
        """Test script creation with segments."""
        segment1 = ScriptSegment( speaker="Alex", role="curious", text="Hello!" )
        segment2 = ScriptSegment( speaker="Jordan", role="expert", text="Hi there!" )

        script = PodcastScript(
            title           = "Test Podcast",
            research_source = "/test.md",
            host_a_name     = "Alex",
            host_b_name     = "Jordan",
            segments        = [ segment1, segment2 ],
        )

        assert script.get_segment_count() == 2
        assert script.title == "Test Podcast"

    def test_get_speaker_word_counts( self ):
        """Test word count per speaker."""
        segment1 = ScriptSegment( speaker="Alex", role="curious", text="one two three" )
        segment2 = ScriptSegment( speaker="Jordan", role="expert", text="four five" )
        segment3 = ScriptSegment( speaker="Alex", role="curious", text="six" )

        script = PodcastScript(
            title           = "Test",
            research_source = "/test.md",
            host_a_name     = "Alex",
            host_b_name     = "Jordan",
            segments        = [ segment1, segment2, segment3 ],
        )

        counts = script.get_speaker_word_counts()
        assert counts[ "Alex" ] == 4  # 3 + 1
        assert counts[ "Jordan" ] == 2

    def test_to_markdown( self ):
        """Test full markdown conversion."""
        segment = ScriptSegment( speaker="Alex", role="curious", text="Hello!" )
        script = PodcastScript(
            title           = "Test Podcast",
            research_source = "/test.md",
            host_a_name     = "Alex",
            host_b_name     = "Jordan",
            segments        = [ segment ],
        )

        md = script.to_markdown()
        assert "# Podcast: Test Podcast" in md
        assert "## Hosts: Alex, Jordan" in md
        assert "**[Alex - Curious]**" in md


class TestContentAnalysis:
    """Tests for ContentAnalysis Pydantic model."""

    def test_analysis_defaults( self ):
        """Test default values."""
        analysis = ContentAnalysis(
            main_topic = "Quantum Computing",
        )
        assert analysis.complexity_level == "intermediate"
        assert analysis.inferred_audience == "general audience"
        assert analysis.key_subtopics == []


class TestCreateInitialState:
    """Tests for create_initial_state function."""

    def test_state_initialization( self ):
        """Test initial state values."""
        state = create_initial_state(
            research_doc_path = "/path/to/doc.md",
            user_id           = "test@example.com",
        )

        assert state[ "research_doc_path" ] == "/path/to/doc.md"
        assert state[ "user_id" ] == "test@example.com"
        assert state[ "revision_count" ] == 0
        assert state[ "script_approved" ] is False
        assert state[ "current_state" ] == "loading_research"


class TestPromptGeneration:
    """Tests for prompt generation functions."""

    def test_content_analysis_prompt( self ):
        """Test content analysis prompt."""
        prompt = get_content_analysis_prompt(
            research_content = "This is research about AI.",
            max_topics       = 3,
        )
        assert "AI" in prompt
        assert "3" in prompt
        assert "JSON" in prompt

    def test_script_generation_prompt( self ):
        """Test script generation prompt."""
        prompt = get_script_generation_prompt(
            content_analysis       = { "main_topic": "AI" },
            research_content       = "Research content.",
            host_a_personality     = DEFAULT_CURIOUS_HOST,
            host_b_personality     = DEFAULT_EXPERT_HOST,
            target_duration_minutes = 10,
        )
        assert "Maria" in prompt
        assert "Mr. Radio" in prompt
        assert "10 minutes" in prompt


class TestResponseParsing:
    """Tests for response parsing functions."""

    def test_parse_analysis_response_valid( self ):
        """Test parsing valid JSON response."""
        json_str = '{"main_topic": "AI", "key_subtopics": ["ML", "DL"]}'
        result = parse_analysis_response( json_str )
        assert result[ "main_topic" ] == "AI"
        assert "ML" in result[ "key_subtopics" ]

    def test_parse_analysis_response_markdown( self ):
        """Test parsing JSON wrapped in markdown."""
        json_str = '```json\n{"main_topic": "Test"}\n```'
        result = parse_analysis_response( json_str )
        assert result[ "main_topic" ] == "Test"

    def test_parse_analysis_response_invalid( self ):
        """Test parsing invalid JSON falls back to defaults."""
        result = parse_analysis_response( "not json" )
        assert result[ "main_topic" ] == "Unknown Topic"
        assert result[ "key_subtopics" ] == []

    def test_parse_script_response_valid( self ):
        """Test parsing valid script JSON."""
        json_str = '{"title": "Test", "segments": [{"speaker": "Alex", "text": "Hi"}]}'
        result = parse_script_response( json_str )
        assert result[ "title" ] == "Test"
        assert len( result[ "segments" ] ) == 1


class TestProsodyExtraction:
    """Tests for prosody extraction."""

    def test_extract_single_annotation( self ):
        """Test extracting single prosody annotation."""
        text = "So *[pause]* what do you think?"
        clean, annotations = extract_prosody_from_text( text )
        assert "pause" in annotations
        assert "*[" not in clean

    def test_extract_multiple_annotations( self ):
        """Test extracting multiple annotations."""
        text = "That's *[excited]* amazing! *[laughs]* Really!"
        clean, annotations = extract_prosody_from_text( text )
        assert len( annotations ) == 2
        assert "excited" in annotations
        assert "laughs" in annotations

    def test_no_annotations( self ):
        """Test text with no annotations."""
        text = "Just plain text here."
        clean, annotations = extract_prosody_from_text( text )
        assert annotations == []
        assert clean == text


class TestPersonalityPrompts:
    """Tests for personality prompt functions."""

    def test_personality_prompt_section( self ):
        """Test personality prompt section generation."""
        section = get_personality_prompt_section(
            host_personality = DEFAULT_CURIOUS_HOST,
            is_curious_role  = True,
        )
        assert "Maria" in section
        assert "CURIOUS HOST" in section

    def test_dynamic_duo_description( self ):
        """Test duo description generation."""
        desc = get_dynamic_duo_description(
            host_a = DEFAULT_CURIOUS_HOST,
            host_b = DEFAULT_EXPERT_HOST,
        )
        assert "Maria" in desc
        assert "Mr. Radio" in desc
        assert "INTERACTION DYNAMICS" in desc

    def test_create_personality_from_description( self ):
        """Test personality creation from text."""
        custom = create_personality_from_description(
            name        = "Dr. Chen",
            description = "An enthusiastic professor who loves science",
            is_curious  = False,
        )
        assert custom.name == "Dr. Chen"
        assert custom.expertise_level == "expert"
        assert "enthusiastic" in custom.tone


class TestLoudFailureOnLLMError:
    """
    Bug 4c49cde4: when the bounded-CC LLM call fails, the orchestrator must fail
    LOUDLY (raise PodcastGenerationError) instead of silently returning a fake
    "Research Topic" / 0-segment placeholder that reaches the review gate looking
    review-ready.
    """

    def _make_orchestrator( self ):
        from cosa.agents.podcast_generator.orchestrator import PodcastOrchestratorAgent
        return PodcastOrchestratorAgent(
            research_doc_path = "/tmp/does-not-matter.md",
            user_id           = "test-user",
        )

    @pytest.mark.asyncio
    async def test_analysis_failure_raises_not_placeholder( self ):
        from cosa.agents.podcast_generator.orchestrator import PodcastGenerationError

        orch = self._make_orchestrator()
        # Inject a mock API client whose analysis call raises (the revoked-token 401 shape).
        mock_client = Mock()
        mock_client.call_for_analysis = AsyncMock(
            side_effect = Exception( "Claude Code returned an error result: success" )
        )
        orch._api_client = mock_client

        with pytest.raises( PodcastGenerationError ) as exc_info:
            await orch._analyze_content_async( "some research content" )

        # User-facing message, and the original error is chained (not swallowed).
        assert "Podcast generation failed" in str( exc_info.value )
        assert isinstance( exc_info.value.__cause__, Exception )

    @pytest.mark.asyncio
    async def test_script_failure_raises_not_empty_script( self ):
        from cosa.agents.podcast_generator.orchestrator import PodcastGenerationError

        orch = self._make_orchestrator()
        mock_client = Mock()
        mock_client.call_for_script = AsyncMock(
            side_effect = Exception( "Claude Code returned an error result: success" )
        )
        orch._api_client = mock_client

        analysis = ContentAnalysis( main_topic="Test Topic", key_subtopics=[] )

        with pytest.raises( PodcastGenerationError ) as exc_info:
            await orch._generate_script_async( "some research content", analysis )

        assert "Podcast generation failed" in str( exc_info.value )
        assert isinstance( exc_info.value.__cause__, Exception )


def quick_smoke_test():
    """Quick smoke test for unit tests module."""
    import cosa.utils.util as cu

    cu.print_banner( "Podcast Generator Unit Tests Smoke Test", prepend_nl=True )

    # Run basic assertions
    print( "Testing PodcastConfig..." )
    config = PodcastConfig()
    assert config.script_model is not None
    print( "✓ PodcastConfig works" )

    print( "Testing OrchestratorState..." )
    assert OrchestratorState.COMPLETED.value == "completed"
    print( "✓ OrchestratorState works" )

    print( "Testing ScriptSegment..." )
    seg = ScriptSegment( speaker="Test", role="curious", text="Hello" )
    assert "Test" in seg.to_markdown()
    print( "✓ ScriptSegment works" )

    print( "\n✓ Unit tests module smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()
