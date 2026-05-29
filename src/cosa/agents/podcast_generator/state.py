#!/usr/bin/env python3
"""
State Schemas for COSA Podcast Generator Agent.

Uses Pydantic for structured outputs and TypedDict for graph state.
Designed for the podcast generation workflow with script review checkpoints.
"""

import re
from enum import Enum
from typing import TypedDict, Literal, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class OrchestratorState( Enum ):
    """
    State machine for the Podcast Orchestrator Agent.

    Active states represent work being done.
    Waiting states are yield points where control returns to event loop.
    Terminal states indicate completion or failure.
    External control states allow user intervention.
    """
    # Active states
    LOADING_RESEARCH   = "loading_research"
    ANALYZING_CONTENT  = "analyzing_content"
    GENERATING_SCRIPT  = "generating_script"
    GENERATING_AUDIO   = "generating_audio"
    STITCHING_AUDIO    = "stitching_audio"

    # Waiting states (yield control via await)
    WAITING_SCRIPT_REVIEW = "waiting_script_review"

    # Terminal states
    COMPLETED = "completed"
    FAILED    = "failed"

    # External control states
    PAUSED  = "paused"
    STOPPED = "stopped"


class ProsodyAnnotation( Enum ):
    """
    Prosody annotations for expressive TTS rendering.

    These annotations are embedded in the script and processed
    by the TTS client to adjust voice characteristics.
    """
    # Emotional markers
    LAUGH        = "laugh"
    CHUCKLE      = "chuckle"
    WHISPER      = "whisper"
    EXCITED      = "excited"
    THOUGHTFUL   = "thoughtful"
    SURPRISED    = "surprised"

    # Pacing markers
    PAUSE        = "pause"
    LONG_PAUSE   = "long_pause"
    SPEED_UP     = "speed_up"
    SLOW_DOWN    = "slow_down"

    # Emphasis markers
    EMPHASIS     = "emphasis"
    QUESTIONING  = "questioning"
    MATTER_OF_FACT = "matter_of_fact"


# =============================================================================
# Pydantic Models for Structured Outputs
# =============================================================================

class ScriptSegment( BaseModel ):
    """
    A single dialogue segment in the podcast script.

    Each segment represents one speaker's turn with optional
    prosody annotations for TTS rendering.
    """

    speaker           : str = Field( description="Name of the speaker (Host A or B name)" )
    role              : str = Field( description="Role: 'curious' or 'expert'" )
    text              : str = Field( description="The dialogue text" )
    prosody           : list[ str ] = Field(
        default_factory = list,
        description     = "Prosody annotations embedded in text"
    )
    topic_reference   : Optional[ str ] = Field(
        default     = None,
        description = "Topic from research doc this segment discusses"
    )
    estimated_duration_seconds : float = Field(
        default     = 0.0,
        description = "Estimated TTS duration in seconds"
    )

    def to_markdown( self ) -> str:
        """
        Convert segment to minimalist markdown format.

        Format:
            **[Speaker - Role]**: Text with *[prosody]* annotations

        Returns:
            str: Markdown formatted dialogue line
        """
        return f"**[{self.speaker} - {self.role.title()}]**: {self.text}"


class PodcastScript( BaseModel ):
    """
    Complete podcast script with all dialogue segments.

    Contains the full script ready for TTS processing.
    """

    title                : str = Field( description="Podcast episode title" )
    research_source      : str = Field( description="Path or name of source research document" )
    generated_at         : str = Field(
        default_factory = lambda: datetime.now().isoformat(),
        description     = "Timestamp when script was generated"
    )
    host_a_name          : str = Field( description="Name of Host A" )
    host_b_name          : str = Field( description="Name of Host B" )
    segments             : list[ ScriptSegment ] = Field( default_factory=list )
    estimated_duration_minutes : float = Field( default=0.0 )
    key_topics           : list[ str ] = Field(
        default_factory = list,
        description     = "Main topics covered in the podcast"
    )
    revision_count       : int = Field( default=0 )

    def to_markdown( self ) -> str:
        """
        Convert entire script to minimalist markdown format.

        Returns:
            str: Full markdown script document
        """
        lines = [
            f"# Podcast: {self.title}",
            f"## Generated: {self.generated_at}",
            f"## Hosts: {self.host_a_name}, {self.host_b_name}",
            f"## Estimated Duration: {self.estimated_duration_minutes:.1f} minutes",
            "",
            "---",
            "",
        ]

        for segment in self.segments:
            lines.append( segment.to_markdown() )
            lines.append( "" )

        return "\n".join( lines )

    def get_segment_count( self ) -> int:
        """Get total number of dialogue segments."""
        return len( self.segments )

    def get_speaker_word_counts( self ) -> dict[ str, int ]:
        """Get word count per speaker."""
        counts = {}
        for segment in self.segments:
            words = len( segment.text.split() )
            counts[ segment.speaker ] = counts.get( segment.speaker, 0 ) + words
        return counts

    def get_total_word_count( self ) -> int:
        """Get total word count across all segments."""
        return sum( len( seg.text.split() ) for seg in self.segments )

    @property
    def calculated_duration_minutes( self ) -> float:
        """
        Calculate duration from word count (~150 words/minute speaking rate).

        Uses estimated_duration_minutes if > 0, otherwise calculates from
        total word count. This provides a fallback when the LLM-provided
        estimate is missing or invalid.

        Returns:
            float: Duration in minutes (estimated or calculated)
        """
        if self.estimated_duration_minutes > 0:
            return self.estimated_duration_minutes
        total_words = self.get_total_word_count()
        return total_words / 150.0

    @classmethod
    def from_markdown( cls, markdown_content: str ) -> "PodcastScript":
        """
        Parse a saved script markdown back into PodcastScript.

        Requires:
            - markdown_content is valid podcast script markdown
            - Contains header with title, hosts, duration
            - Contains **[Speaker - Role]**: Text segments

        Ensures:
            - Returns fully reconstructed PodcastScript object
            - Prosody annotations extracted from text
            - revision_count defaults to 0 (caller may override)

        Args:
            markdown_content: Full markdown content of saved script

        Returns:
            PodcastScript: Reconstructed script object

        Raises:
            ValueError: If markdown format is invalid
        """
        lines = markdown_content.strip().split( "\n" )

        # Parse header values
        title        = ""
        generated_at = datetime.now().isoformat()
        host_a_name  = "Host A"
        host_b_name  = "Host B"
        duration     = 0.0
        key_topics   = []
        research_source = ""
        revision_count = 0

        # Header parsing patterns
        title_pattern    = r'^#\s+Podcast:\s*(.+)$'
        gen_pattern      = r'^##\s+Generated:\s*(.+)$'
        hosts_pattern    = r'^##\s+Hosts:\s*(.+),\s*(.+)$'
        duration_pattern = r'^##\s+Estimated Duration:\s*([\d.]+)\s*minutes?$'
        source_pattern   = r'^##\s+Research Source:\s*(.+)$'
        topics_pattern   = r'^##\s+Key Topics:\s*(.+)$'
        revision_pattern = r'^##\s+Revision:\s*(\d+)$'

        # First pass: parse header
        for line in lines:
            line = line.strip()

            match = re.match( title_pattern, line )
            if match:
                title = match.group( 1 ).strip()
                continue

            match = re.match( gen_pattern, line )
            if match:
                generated_at = match.group( 1 ).strip()
                continue

            match = re.match( hosts_pattern, line )
            if match:
                host_a_name = match.group( 1 ).strip()
                host_b_name = match.group( 2 ).strip()
                continue

            match = re.match( duration_pattern, line )
            if match:
                try:
                    duration = float( match.group( 1 ) )
                except ValueError:
                    pass
                continue

            match = re.match( source_pattern, line )
            if match:
                research_source = match.group( 1 ).strip()
                continue

            match = re.match( topics_pattern, line )
            if match:
                topics_str = match.group( 1 ).strip()
                key_topics = [ t.strip() for t in topics_str.split( "," ) ]
                continue

            match = re.match( revision_pattern, line )
            if match:
                try:
                    revision_count = int( match.group( 1 ) )
                except ValueError:
                    pass
                continue

        # Parse segments
        # Pattern: **[Speaker - Role]**: Text
        segment_pattern = r'^\*\*\[([^\]]+)\s*-\s*([^\]]+)\]\*\*:\s*(.+)$'

        # Prosody extraction pattern: *[annotation]*
        prosody_pattern = r'\*\[([^\]]+)\]\*'

        segments = []
        for line in lines:
            line = line.strip()
            if not line:
                continue

            match = re.match( segment_pattern, line )
            if match:
                speaker = match.group( 1 ).strip()
                role    = match.group( 2 ).strip().lower()
                text    = match.group( 3 ).strip()

                # Extract prosody annotations
                prosody_annotations = []
                for prosody_match in re.finditer( prosody_pattern, text ):
                    annotation = prosody_match.group( 1 ).lower().strip()
                    prosody_annotations.append( annotation )

                segment = ScriptSegment(
                    speaker = speaker,
                    role    = role,
                    text    = text,
                    prosody = prosody_annotations,
                )
                segments.append( segment )

        if not title:
            raise ValueError( "Could not parse podcast title from markdown" )

        return cls(
            title                      = title,
            research_source            = research_source,
            generated_at               = generated_at,
            host_a_name                = host_a_name,
            host_b_name                = host_b_name,
            segments                   = segments,
            estimated_duration_minutes = duration,
            key_topics                 = key_topics,
            revision_count             = revision_count,
        )


class ContentAnalysis( BaseModel ):
    """
    Analysis of the research document for script generation.

    Extracts key topics, interesting facts, and discussion points
    from the source document.
    """

    main_topic           : str = Field( description="Primary topic of the research" )
    key_subtopics        : list[ str ] = Field(
        default_factory = list,
        description     = "Important subtopics to cover"
    )
    interesting_facts    : list[ str ] = Field(
        default_factory = list,
        description     = "Surprising or engaging facts to highlight"
    )
    discussion_questions : list[ str ] = Field(
        default_factory = list,
        description     = "Questions the hosts should explore"
    )
    analogies_suggested  : list[ str ] = Field(
        default_factory = list,
        description     = "Analogies to make concepts accessible"
    )
    inferred_audience    : str = Field(
        default     = "general audience",
        description = "Audience level inferred by LLM from content analysis (maps from JSON key 'target_audience')"
    )
    complexity_level     : Literal[ "beginner", "intermediate", "advanced" ] = Field(
        default = "intermediate"
    )
    estimated_coverage_minutes : float = Field( default=10.0 )


class PodcastMetadata( BaseModel ):
    """
    Metadata about the generated podcast.

    Tracks generation details, costs, and output locations.
    """

    podcast_id           : str = Field( description="Unique identifier for this podcast" )
    user_id              : str = Field( description="User who requested the podcast" )
    research_doc_path    : str = Field( description="Path to source research document" )
    script_path          : Optional[ str ] = Field( default=None )
    audio_path           : Optional[ str ] = Field( default=None )
    generated_at         : str = Field( default_factory=lambda: datetime.now().isoformat() )
    generation_duration_seconds : float = Field( default=0.0 )
    api_calls_count      : int = Field( default=0 )
    total_tokens_used    : int = Field( default=0 )
    estimated_cost_usd   : float = Field( default=0.0 )
    script_revision_count: int = Field( default=0 )


# =============================================================================
# TypedDict for Graph State
# =============================================================================

class PodcastState( TypedDict ):
    """
    Main graph state for the podcast generator agent.

    This TypedDict defines the complete state that flows through
    the generation workflow, tracking all phases and intermediate results.
    """

    # Input
    research_doc_path    : str
    research_content     : Optional[ str ]
    user_id              : str

    # Analysis Phase
    content_analysis     : Optional[ ContentAnalysis ]
    topics_extracted     : bool
    analysis_confidence  : float

    # Script Generation Phase
    draft_script         : Optional[ PodcastScript ]
    script_approved      : bool
    human_feedback       : Optional[ str ]
    revision_count       : int

    # Audio Generation Phase (Phase 2)
    audio_segments       : list[ str ]  # Paths to individual audio files
    audio_generation_progress : float

    # Final Output
    final_script_path    : Optional[ str ]
    final_audio_path     : Optional[ str ]
    metadata             : Optional[ PodcastMetadata ]

    # Control
    current_state        : str
    error_message        : Optional[ str ]


def validate_prosody_preservation(
    english_script   : "PodcastScript",
    translated_script: "PodcastScript"
) -> tuple[ bool, dict ]:
    """
    Verify that prosody markers are preserved during translation.

    Compares prosody marker counts between English and translated scripts.
    Warns if markers are missing or changed.

    Requires:
        - english_script is a valid PodcastScript
        - translated_script is a valid PodcastScript

    Ensures:
        - Returns True if prosody is preserved, False otherwise
        - Returns dict with comparison details

    Args:
        english_script: The original English script
        translated_script: The translated script

    Returns:
        tuple[bool, dict]: (is_preserved, details_dict)
            - is_preserved: True if prosody markers match
            - details_dict: Contains 'english_count', 'translated_count', 'missing', 'extra'
    """
    # Extract all prosody markers from English script
    english_markers = []
    for seg in english_script.segments:
        english_markers.extend( seg.prosody )

    # Extract all prosody markers from translated script
    translated_markers = []
    for seg in translated_script.segments:
        translated_markers.extend( seg.prosody )

    # Compare marker sets
    english_set    = set( english_markers )
    translated_set = set( translated_markers )

    missing = english_set - translated_set  # In English but not in translation
    extra   = translated_set - english_set  # In translation but not in English

    # Consider preserved if same marker types exist (counts may differ slightly)
    is_preserved = len( missing ) == 0 and len( extra ) == 0

    details = {
        "english_count"    : len( english_markers ),
        "translated_count" : len( translated_markers ),
        "missing"          : list( missing ),
        "extra"            : list( extra ),
    }

    return is_preserved, details


def create_initial_state(
    research_doc_path: str,
    user_id: str
) -> PodcastState:
    """
    Create the initial state for a podcast generation task.

    Requires:
        - research_doc_path is a non-empty string
        - user_id is a valid identifier

    Ensures:
        - Returns fully initialized PodcastState with defaults
        - All counters start at 0
        - All optional fields are None or empty

    Args:
        research_doc_path: Path to the research document
        user_id: User identifier for output directory

    Returns:
        PodcastState: Initialized state dictionary
    """
    return PodcastState(
        research_doc_path   = research_doc_path,
        research_content    = None,
        user_id             = user_id,
        content_analysis    = None,
        topics_extracted    = False,
        analysis_confidence = 0.0,
        draft_script        = None,
        script_approved     = False,
        human_feedback      = None,
        revision_count      = 0,
        audio_segments      = [],
        audio_generation_progress = 0.0,
        final_script_path   = None,
        final_audio_path    = None,
        metadata            = None,
        current_state       = OrchestratorState.LOADING_RESEARCH.value,
        error_message       = None,
    )


def quick_smoke_test():
    """Quick smoke test for state schemas."""
    import cosa.utils.util as cu

    cu.print_banner( "Podcast Generator State Smoke Test", prepend_nl=True )

    try:
        # Test 1: OrchestratorState enum
        print( "Testing OrchestratorState enum..." )
        assert OrchestratorState.LOADING_RESEARCH.value == "loading_research"
        assert OrchestratorState.COMPLETED.value == "completed"
        assert len( OrchestratorState ) == 10
        print( f"✓ OrchestratorState enum valid ({len( OrchestratorState )} states)" )

        # Test 2: ProsodyAnnotation enum
        print( "Testing ProsodyAnnotation enum..." )
        assert ProsodyAnnotation.LAUGH.value == "laugh"
        assert ProsodyAnnotation.PAUSE.value == "pause"
        assert len( ProsodyAnnotation ) == 13
        print( f"✓ ProsodyAnnotation enum valid ({len( ProsodyAnnotation )} annotations)" )

        # Test 3: ScriptSegment model
        print( "Testing ScriptSegment model..." )
        segment = ScriptSegment(
            speaker         = "Nora",
            role            = "curious",
            text            = "So what you're saying is... *[pause]* this changes everything?",
            prosody         = [ "pause" ],
            topic_reference = "quantum computing",
        )
        assert segment.speaker == "Nora"
        assert "pause" in segment.prosody
        markdown = segment.to_markdown()
        assert "**[Nora - Curious]**" in markdown
        print( "✓ ScriptSegment model validates and converts to markdown" )

        # Test 4: PodcastScript model
        print( "Testing PodcastScript model..." )
        script = PodcastScript(
            title           = "Understanding Quantum Computing",
            research_source = "/path/to/research.md",
            host_a_name     = "Nora",
            host_b_name     = "Quentin",
            segments        = [ segment ],
            estimated_duration_minutes = 12.5,
            key_topics      = [ "quantum", "computing", "future" ],
        )
        assert script.get_segment_count() == 1
        word_counts = script.get_speaker_word_counts()
        assert "Nora" in word_counts
        markdown_full = script.to_markdown()
        assert "# Podcast: Understanding Quantum Computing" in markdown_full
        print( "✓ PodcastScript model validates" )

        # Test 4b: PodcastScript.from_markdown() round-trip
        print( "Testing PodcastScript.from_markdown()..." )
        test_markdown = """# Podcast: Voice Computing Revolution
## Generated: 2026-01-19T10:30:00
## Hosts: Nora, Quentin
## Estimated Duration: 15.5 minutes

---

**[Nora - Curious]**: So what you're saying is... *[pause]* this changes everything?

**[Quentin - Expert]**: Exactly! *[excited]* The market is growing from $14 billion to $61 billion by 2033.

**[Nora - Curious]**: Wait, that's a huge jump! *[surprised]* How is that even possible?
"""
        parsed = PodcastScript.from_markdown( test_markdown )
        assert parsed.title == "Voice Computing Revolution"
        assert parsed.host_a_name == "Nora"
        assert parsed.host_b_name == "Quentin"
        assert parsed.estimated_duration_minutes == 15.5
        assert len( parsed.segments ) == 3
        assert parsed.segments[ 0 ].speaker == "Nora"
        assert parsed.segments[ 0 ].role == "curious"
        assert "pause" in parsed.segments[ 0 ].prosody
        assert parsed.segments[ 1 ].speaker == "Quentin"
        assert "excited" in parsed.segments[ 1 ].prosody
        print( f"✓ from_markdown() works (parsed {len( parsed.segments )} segments)" )

        # Test 5: ContentAnalysis model
        print( "Testing ContentAnalysis model..." )
        analysis = ContentAnalysis(
            main_topic        = "Quantum Computing",
            key_subtopics     = [ "qubits", "entanglement", "applications" ],
            interesting_facts = [ "Quantum computers can be 100M times faster" ],
            discussion_questions = [ "Will quantum computers replace classical?" ],
        )
        assert analysis.complexity_level == "intermediate"  # Default
        assert len( analysis.key_subtopics ) == 3
        print( "✓ ContentAnalysis model validates" )

        # Test 6: PodcastMetadata model
        print( "Testing PodcastMetadata model..." )
        metadata = PodcastMetadata(
            podcast_id        = "podcast-123",
            user_id           = "user@example.com",
            research_doc_path = "/path/to/research.md",
            api_calls_count   = 5,
            total_tokens_used = 10000,
        )
        assert metadata.script_revision_count == 0  # Default
        print( "✓ PodcastMetadata model validates" )

        # Test 7: create_initial_state
        print( "Testing create_initial_state..." )
        state = create_initial_state(
            research_doc_path = "/path/to/research.md",
            user_id           = "user@example.com",
        )
        assert state[ "research_doc_path" ] == "/path/to/research.md"
        assert state[ "user_id" ] == "user@example.com"
        assert state[ "revision_count" ] == 0
        assert state[ "script_approved" ] is False
        assert state[ "current_state" ] == "loading_research"
        print( f"✓ create_initial_state works ({len( state )} keys)" )

        # Test 8: validate_prosody_preservation
        print( "Testing validate_prosody_preservation..." )
        english = PodcastScript(
            title           = "English Test",
            research_source = "/test.md",
            host_a_name     = "Nora",
            host_b_name     = "Quentin",
            segments        = [
                ScriptSegment( speaker="Nora", role="curious", text="Test *[pause]* one", prosody=[ "pause" ] ),
                ScriptSegment( speaker="Quentin", role="expert", text="Test *[excited]* two", prosody=[ "excited" ] ),
            ],
        )
        # Translation with same markers
        translated_good = PodcastScript(
            title           = "Spanish Test",
            research_source = "/test.md",
            host_a_name     = "Nora",
            host_b_name     = "Quentin",
            segments        = [
                ScriptSegment( speaker="Nora", role="curious", text="Prueba *[pause]* uno", prosody=[ "pause" ] ),
                ScriptSegment( speaker="Quentin", role="expert", text="Prueba *[excited]* dos", prosody=[ "excited" ] ),
            ],
        )
        is_preserved, details = validate_prosody_preservation( english, translated_good )
        assert is_preserved is True
        assert details[ "missing" ] == []
        assert details[ "extra" ] == []
        print( "✓ Prosody validation passes for matching markers" )

        # Translation with missing marker
        translated_bad = PodcastScript(
            title           = "Spanish Test",
            research_source = "/test.md",
            host_a_name     = "Nora",
            host_b_name     = "Quentin",
            segments        = [
                ScriptSegment( speaker="Nora", role="curious", text="Prueba uno", prosody=[] ),  # Missing pause
                ScriptSegment( speaker="Quentin", role="expert", text="Prueba *[excited]* dos", prosody=[ "excited" ] ),
            ],
        )
        is_preserved2, details2 = validate_prosody_preservation( english, translated_bad )
        assert is_preserved2 is False
        assert "pause" in details2[ "missing" ]
        print( "✓ Prosody validation detects missing markers" )

        print( "\n✓ Podcast Generator State smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
