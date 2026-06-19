#!/usr/bin/env python3
"""
Unit tests for cosa.agents.podcast_generator.state

Targets: OrchestratorState / ProsodyAnnotation enums; the Pydantic models
ScriptSegment / PodcastScript / ContentAnalysis / PodcastMetadata; the
markdown round-trip parser PodcastScript.from_markdown; and the module helpers
validate_prosody_preservation + create_initial_state.

No external boundaries exist (pure data structures + regex parsing), so no
mocking is needed. quick_smoke_test() and __main__ are coverage-excluded.
"""

import pytest

from cosa.agents.podcast_generator.state import (
    OrchestratorState,
    ProsodyAnnotation,
    ScriptSegment,
    PodcastScript,
    ContentAnalysis,
    PodcastMetadata,
    validate_prosody_preservation,
    create_initial_state,
)


class TestEnums:
    """
    Pin the enum surfaces.

    Ensures member counts and representative values match the documented schema.
    """

    def test_orchestrator_state_values_and_count( self ):
        assert OrchestratorState.LOADING_RESEARCH.value      == "loading_research"
        assert OrchestratorState.WAITING_SCRIPT_REVIEW.value == "waiting_script_review"
        assert OrchestratorState.COMPLETED.value             == "completed"
        assert OrchestratorState.STOPPED.value               == "stopped"
        assert len( OrchestratorState ) == 10

    def test_prosody_annotation_values_and_count( self ):
        assert ProsodyAnnotation.LAUGH.value          == "laugh"
        assert ProsodyAnnotation.LONG_PAUSE.value     == "long_pause"
        assert ProsodyAnnotation.MATTER_OF_FACT.value == "matter_of_fact"
        assert len( ProsodyAnnotation ) == 13


class TestScriptSegment:
    """
    ScriptSegment defaults + markdown rendering.

    Ensures defaults (empty prosody, None topic_reference, 0.0 duration) and
    that to_markdown title-cases the role inside the speaker tag.
    """

    def test_defaults( self ):
        seg = ScriptSegment( speaker="Nora", role="curious", text="Hi" )
        assert seg.prosody == []
        assert seg.topic_reference is None
        assert seg.estimated_duration_seconds == 0.0

    def test_to_markdown_titlecases_role( self ):
        seg = ScriptSegment( speaker="Nora", role="curious", text="So... this changes everything?" )
        assert seg.to_markdown() == "**[Nora - Curious]**: So... this changes everything?"


class TestPodcastScriptMethods:
    """
    PodcastScript computed methods.

    Ensures to_markdown header + per-segment lines, segment count, per-speaker
    and total word counts, and the calculated_duration_minutes fallback (uses
    the estimate when > 0, else words / 150).
    """

    def _script( self, **kw ):
        defaults = dict(
            title="T", research_source="/r.md", host_a_name="Nora", host_b_name="Quentin",
            segments=[
                ScriptSegment( speaker="Nora", role="curious", text="one two three" ),
                ScriptSegment( speaker="Quentin", role="expert", text="four five" ),
                ScriptSegment( speaker="Nora", role="curious", text="six" ),
            ],
        )
        defaults.update( kw )
        return PodcastScript( **defaults )

    def test_to_markdown_header_and_segments( self ):
        md = self._script( estimated_duration_minutes=12.5 ).to_markdown()
        assert "# Podcast: T" in md
        assert "## Hosts: Nora, Quentin" in md
        assert "## Estimated Duration: 12.5 minutes" in md
        assert "**[Nora - Curious]**: one two three" in md
        assert "**[Quentin - Expert]**: four five"    in md

    def test_segment_count( self ):
        assert self._script().get_segment_count() == 3

    def test_speaker_word_counts_accumulates_per_speaker( self ):
        counts = self._script().get_speaker_word_counts()
        assert counts == { "Nora": 4, "Quentin": 2 }   # 3+1 / 2

    def test_total_word_count( self ):
        assert self._script().get_total_word_count() == 6

    def test_calculated_duration_uses_estimate_when_positive( self ):
        assert self._script( estimated_duration_minutes=7.5 ).calculated_duration_minutes == 7.5

    def test_calculated_duration_falls_back_to_word_count( self ):
        # estimate 0.0 => 6 words / 150 = 0.04
        assert self._script( estimated_duration_minutes=0.0 ).calculated_duration_minutes == pytest.approx( 6 / 150.0 )


class TestFromMarkdown:
    """
    PodcastScript.from_markdown round-trip parser.

    Ensures every header line type is parsed (title/generated/hosts/duration/
    source/topics/revision), segments with and without prosody are recovered,
    a non-floatable duration is swallowed, and a missing title raises.
    """

    FULL = """# Podcast: Voice Computing Revolution
## Generated: 2026-01-19T10:30:00
## Hosts: Nora, Quentin
## Estimated Duration: 15.5 minutes
## Research Source: /io/dr/voice.md
## Key Topics: voice, computing, future
## Revision: 3

---

**[Nora - Curious]**: So what you're saying is... *[pause]* this changes everything?

**[Quentin - Expert]**: Exactly! *[excited]* Big jump ahead.

**[Nora - Curious]**: No annotations here.
"""

    def test_full_header_and_segments( self ):
        script = PodcastScript.from_markdown( self.FULL )
        assert script.title           == "Voice Computing Revolution"
        assert script.generated_at    == "2026-01-19T10:30:00"
        assert script.host_a_name     == "Nora"
        assert script.host_b_name     == "Quentin"
        assert script.estimated_duration_minutes == 15.5
        assert script.research_source == "/io/dr/voice.md"
        assert script.key_topics      == [ "voice", "computing", "future" ]
        assert script.revision_count  == 3
        assert len( script.segments ) == 3
        # prosody extraction
        assert script.segments[ 0 ].prosody == [ "pause" ]
        assert script.segments[ 1 ].prosody == [ "excited" ]
        assert script.segments[ 2 ].prosody == []          # no annotations branch
        assert script.segments[ 0 ].role == "curious"       # lowercased

    def test_non_floatable_duration_is_swallowed( self ):
        # "1.2.3" matches [\d.]+ but float() raises ValueError -> swallowed, stays 0.0
        md = "# Podcast: X\n## Estimated Duration: 1.2.3 minutes\n\n**[A - Expert]**: hi\n"
        script = PodcastScript.from_markdown( md )
        assert script.estimated_duration_minutes == 0.0

    def test_missing_title_raises( self ):
        md = "## Hosts: A, B\n\n**[A - Expert]**: hi\n"
        with pytest.raises( ValueError, match="Could not parse podcast title" ):
            PodcastScript.from_markdown( md )


class TestModels:
    """
    ContentAnalysis + PodcastMetadata default-construction contracts.
    """

    def test_content_analysis_defaults( self ):
        ca = ContentAnalysis( main_topic="Quantum" )
        assert ca.key_subtopics        == []
        assert ca.inferred_audience    == "general audience"
        assert ca.complexity_level     == "intermediate"
        assert ca.estimated_coverage_minutes == 10.0

    def test_podcast_metadata_defaults( self ):
        md = PodcastMetadata( podcast_id="p-1", user_id="u@test.com", research_doc_path="/r.md" )
        assert md.script_path           is None
        assert md.audio_path            is None
        assert md.api_calls_count       == 0
        assert md.estimated_cost_usd    == 0.0
        assert md.script_revision_count == 0


class TestValidateProsodyPreservation:
    """
    validate_prosody_preservation compares prosody marker SETS across scripts.

    Ensures preserved (matching), missing (English-only), and extra
    (translation-only) cases are reported in the details dict.
    """

    def _script( self, segs ):
        return PodcastScript(
            title="T", research_source="/r.md", host_a_name="A", host_b_name="B", segments=segs
        )

    def test_preserved_when_marker_sets_match( self ):
        eng = self._script( [
            ScriptSegment( speaker="A", role="curious", text="x", prosody=[ "pause" ] ),
            ScriptSegment( speaker="B", role="expert", text="y", prosody=[ "excited" ] ),
        ] )
        trans = self._script( [
            ScriptSegment( speaker="A", role="curious", text="x", prosody=[ "pause" ] ),
            ScriptSegment( speaker="B", role="expert", text="y", prosody=[ "excited" ] ),
        ] )
        ok, details = validate_prosody_preservation( eng, trans )
        assert ok is True
        assert details[ "english_count" ]    == 2
        assert details[ "translated_count" ] == 2
        assert details[ "missing" ] == []
        assert details[ "extra" ]   == []

    def test_missing_marker_detected( self ):
        eng = self._script( [ ScriptSegment( speaker="A", role="expert", text="x", prosody=[ "pause", "excited" ] ) ] )
        trans = self._script( [ ScriptSegment( speaker="A", role="expert", text="x", prosody=[ "excited" ] ) ] )
        ok, details = validate_prosody_preservation( eng, trans )
        assert ok is False
        assert "pause" in details[ "missing" ]
        assert details[ "extra" ] == []

    def test_extra_marker_detected( self ):
        eng = self._script( [ ScriptSegment( speaker="A", role="expert", text="x", prosody=[ "pause" ] ) ] )
        trans = self._script( [ ScriptSegment( speaker="A", role="expert", text="x", prosody=[ "pause", "laugh" ] ) ] )
        ok, details = validate_prosody_preservation( eng, trans )
        assert ok is False
        assert details[ "missing" ] == []
        assert "laugh" in details[ "extra" ]


class TestCreateInitialState:
    """
    create_initial_state returns a fully-defaulted PodcastState.

    Ensures inputs flow through, counters start at 0/empty, and current_state
    is the LOADING_RESEARCH value.
    """

    def test_initial_state_defaults( self ):
        state = create_initial_state( research_doc_path="/r.md", user_id="u@test.com" )
        assert state[ "research_doc_path" ]   == "/r.md"
        assert state[ "user_id" ]             == "u@test.com"
        assert state[ "research_content" ]    is None
        assert state[ "topics_extracted" ]    is False
        assert state[ "analysis_confidence" ] == 0.0
        assert state[ "script_approved" ]     is False
        assert state[ "revision_count" ]      == 0
        assert state[ "audio_segments" ]      == []
        assert state[ "audio_generation_progress" ] == 0.0
        assert state[ "metadata" ]            is None
        assert state[ "current_state" ]       == "loading_research"
        assert state[ "error_message" ]       is None
