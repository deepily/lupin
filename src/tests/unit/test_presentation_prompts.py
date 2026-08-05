#!/usr/bin/env python3
"""
Unit tests for Presentation Generator Narrative Prompts.

Tests cover:
    - parse_analysis_response() with valid, wrapped, and malformed input
    - get_narrative_analysis_prompt() context inclusion
    - AUDIENCE_COMPLEXITY_GUIDELINES coverage
    - extract_narrative_metadata()
    - ARC_POSITIONS taxonomy
"""

import json
import pytest

from cosa.agents.presentation_generator.prompts.narrative import (
    ARC_POSITIONS,
    AUDIENCE_COMPLEXITY_GUIDELINES,
    NARRATIVE_ANALYSIS_SYSTEM_PROMPT,
    get_narrative_analysis_prompt,
    parse_analysis_response,
    extract_narrative_metadata,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def valid_response():
    """Create a valid analysis response JSON string."""
    return json.dumps( {
        "sections": [
            {
                "heading"              : "Introduction",
                "content_summary"      : "Sets up the problem",
                "arc_position"         : "setup",
                "proposed_slide_count" : 2,
                "key_points"           : [ "Problem X", "Why it matters" ]
            },
            {
                "heading"              : "Our Approach",
                "content_summary"      : "Core method",
                "arc_position"         : "argument",
                "proposed_slide_count" : 3,
                "key_points"           : [ "Method Y", "Key insight" ]
            },
            {
                "heading"              : "Results",
                "content_summary"      : "What we found",
                "arc_position"         : "evidence",
                "proposed_slide_count" : 2,
                "key_points"           : [ "3x improvement" ]
            },
            {
                "heading"              : "Conclusion",
                "content_summary"      : "Summary",
                "arc_position"         : "conclusion",
                "proposed_slide_count" : 1,
                "key_points"           : [ "Key takeaway" ]
            }
        ],
        "total_proposed_slides" : 8,
        "narrative_assessment"  : "Well-structured argument"
    } )


# =============================================================================
# parse_analysis_response Tests
# =============================================================================

class TestParseAnalysisResponse:
    """Tests for parse_analysis_response()."""

    def test_valid_json( self, valid_response ):
        """Parses valid JSON response correctly."""
        sections = parse_analysis_response( valid_response )
        assert len( sections ) == 4
        assert sections[ 0 ][ "heading" ] == "Introduction"
        assert sections[ 0 ][ "arc_position" ] == "setup"
        assert sections[ 0 ][ "proposed_slide_count" ] == 2
        assert len( sections[ 0 ][ "key_points" ] ) == 2

    def test_markdown_wrapped_json( self, valid_response ):
        """Parses JSON wrapped in ```json ... ``` markers."""
        wrapped = f"```json\n{valid_response}\n```"
        sections = parse_analysis_response( wrapped )
        assert len( sections ) == 4

    def test_plain_code_fence_wrapped( self, valid_response ):
        """Parses JSON wrapped in ``` ... ``` markers (without json hint)."""
        wrapped = f"```\n{valid_response}\n```"
        sections = parse_analysis_response( wrapped )
        assert len( sections ) == 4

    def test_malformed_input_raises( self ):
        """D6-STRICT: non-JSON input raises ValueError (was: returned [])."""
        with pytest.raises( ValueError ):
            parse_analysis_response( "This is not JSON at all" )

    def test_empty_sections_raises( self ):
        """D6-STRICT: empty 'sections' raises ValueError (was: returned [])."""
        with pytest.raises( ValueError ):
            parse_analysis_response( json.dumps( { "sections": [] } ) )

    def test_missing_sections_key_raises( self ):
        """D6-STRICT: absent 'sections' key raises ValueError (was: returned [])."""
        with pytest.raises( ValueError ):
            parse_analysis_response( json.dumps( { "other": "data" } ) )

    def test_invalid_arc_position_defaults( self ):
        """Unknown arc position defaults to 'argument'."""
        response = json.dumps( { "sections": [ {
            "heading"              : "Test",
            "arc_position"         : "nonexistent_position",
            "proposed_slide_count" : 1,
        } ] } )
        sections = parse_analysis_response( response )
        assert len( sections ) == 1
        assert sections[ 0 ][ "arc_position" ] == "argument"

    def test_missing_fields_get_defaults( self ):
        """Missing optional fields get sensible defaults."""
        response = json.dumps( { "sections": [ { "heading": "Minimal" } ] } )
        sections = parse_analysis_response( response )
        assert len( sections ) == 1
        assert sections[ 0 ][ "heading" ] == "Minimal"
        assert sections[ 0 ][ "content_summary" ] == ""
        assert sections[ 0 ][ "arc_position" ] == "argument"
        assert sections[ 0 ][ "proposed_slide_count" ] == 1
        assert sections[ 0 ][ "key_points" ] == []

    def test_negative_slide_count_clamped( self ):
        """Negative proposed_slide_count is clamped to 0."""
        response = json.dumps( { "sections": [ {
            "heading"              : "Test",
            "proposed_slide_count" : -5,
        } ] } )
        sections = parse_analysis_response( response )
        assert sections[ 0 ][ "proposed_slide_count" ] == 0

    def test_non_integer_slide_count( self ):
        """Non-integer proposed_slide_count is coerced to int."""
        response = json.dumps( { "sections": [ {
            "heading"              : "Test",
            "proposed_slide_count" : 2.7,
        } ] } )
        sections = parse_analysis_response( response )
        assert sections[ 0 ][ "proposed_slide_count" ] == 2

    def test_all_arc_positions_accepted( self ):
        """All valid arc positions pass validation."""
        for pos in ARC_POSITIONS:
            response = json.dumps( { "sections": [ {
                "heading"      : f"Section for {pos}",
                "arc_position" : pos,
            } ] } )
            sections = parse_analysis_response( response )
            assert sections[ 0 ][ "arc_position" ] == pos


# =============================================================================
# get_narrative_analysis_prompt Tests
# =============================================================================

class TestGetNarrativeAnalysisPrompt:
    """Tests for get_narrative_analysis_prompt()."""

    def test_includes_duration( self ):
        """Prompt includes target duration."""
        prompt = get_narrative_analysis_prompt(
            source_content = "Test content",
            raw_sections   = [],
            target_duration   = 20,
            slides_per_minute = 1.0,
        )
        assert "20 minutes" in prompt

    def test_includes_slide_budget( self ):
        """Prompt calculates and includes slide budget."""
        prompt = get_narrative_analysis_prompt(
            source_content = "Test content",
            raw_sections   = [],
            target_duration   = 15,
            slides_per_minute = 1.0,
        )
        assert "15 slides" in prompt  # 15 * 1.0 = 15 total

    def test_includes_audience_guidelines( self ):
        """Prompt includes audience-specific guidelines when provided."""
        prompt = get_narrative_analysis_prompt(
            source_content = "Test",
            raw_sections   = [],
            target_duration   = 15,
            slides_per_minute = 1.0,
            audience          = "expert",
        )
        assert "expertise" in prompt.lower() or "expert" in prompt.lower()

    def test_includes_audience_context( self ):
        """Prompt includes free-text audience context."""
        prompt = get_narrative_analysis_prompt(
            source_content = "Test",
            raw_sections   = [],
            target_duration   = 15,
            slides_per_minute = 1.0,
            audience_context  = "ML engineers at a startup",
        )
        assert "ML engineers at a startup" in prompt

    def test_includes_raw_sections( self ):
        """Prompt includes pre-parsed section summary."""
        prompt = get_narrative_analysis_prompt(
            source_content = "Full content here",
            raw_sections   = [
                ( "Intro", "Some intro text here", 1 ),
                ( "Methods", "Method details", 2 ),
            ],
            target_duration   = 10,
            slides_per_minute = 1.0,
        )
        assert "Intro" in prompt
        assert "Methods" in prompt
        assert "H1" in prompt
        assert "H2" in prompt

    def test_includes_source_content( self ):
        """Prompt includes the full source document."""
        content = "This is the full article about machine learning."
        prompt = get_narrative_analysis_prompt(
            source_content = content,
            raw_sections   = [],
            target_duration   = 15,
            slides_per_minute = 1.0,
        )
        assert "machine learning" in prompt

    def test_truncation_note_at_configured_ceiling( self ):
        """Content over the configured ceiling gets clipped, and the note cites that ceiling."""
        ceiling = 100
        long_content = "A" * ceiling + "B" * 50   # only the A's survive the clip
        prompt = get_narrative_analysis_prompt(
            source_content = long_content,
            raw_sections   = [],
            target_duration   = 15,
            slides_per_minute = 1.0,
            max_source_chars  = ceiling,
        )
        assert "truncated" in prompt.lower()
        assert f"truncated to {ceiling:,}" in prompt   # the CONFIGURED ceiling, not a literal
        assert "B" * 50 not in prompt                  # dropped content really is dropped

    def test_no_truncation_when_ceiling_unset( self ):
        """With no ceiling (None), even very long content is passed through whole."""
        long_content = "A" * 40000 + "TAIL_MARKER"
        prompt = get_narrative_analysis_prompt(
            source_content = long_content,
            raw_sections   = [],
            target_duration   = 15,
            slides_per_minute = 1.0,
        )   # max_source_chars omitted → None → no clip
        assert "truncated" not in prompt.lower()
        assert "TAIL_MARKER" in prompt

    def test_no_audience_no_guidelines( self ):
        """Prompt works without audience parameter."""
        prompt = get_narrative_analysis_prompt(
            source_content = "Test",
            raw_sections   = [],
            target_duration   = 15,
            slides_per_minute = 1.0,
        )
        # Should still be a valid prompt
        assert "15 minutes" in prompt


# =============================================================================
# extract_narrative_metadata Tests
# =============================================================================

class TestExtractNarrativeMetadata:
    """Tests for extract_narrative_metadata()."""

    def test_extracts_total_slides( self, valid_response ):
        """Extracts total_proposed_slides from response."""
        meta = extract_narrative_metadata( valid_response )
        assert meta[ "total_proposed_slides" ] == 8

    def test_extracts_assessment( self, valid_response ):
        """Extracts narrative_assessment from response."""
        meta = extract_narrative_metadata( valid_response )
        assert "Well-structured" in meta[ "narrative_assessment" ]

    def test_malformed_returns_empty( self ):
        """Returns empty dict for malformed input."""
        meta = extract_narrative_metadata( "not json" )
        assert meta == {}


# =============================================================================
# Constants Tests
# =============================================================================

class TestConstants:
    """Tests for module-level constants."""

    def test_arc_positions_count( self ):
        """ARC_POSITIONS has exactly 6 positions."""
        assert len( ARC_POSITIONS ) == 6

    def test_arc_positions_values( self ):
        """ARC_POSITIONS contains expected values."""
        expected = { "setup", "argument", "evidence", "transition", "conclusion", "cta" }
        assert set( ARC_POSITIONS ) == expected

    def test_audience_guidelines_keys( self ):
        """AUDIENCE_COMPLEXITY_GUIDELINES covers all 4 levels."""
        expected = { "beginner", "general", "expert", "academic" }
        assert set( AUDIENCE_COMPLEXITY_GUIDELINES.keys() ) == expected

    def test_system_prompt_not_empty( self ):
        """System prompt is a non-empty string."""
        assert len( NARRATIVE_ANALYSIS_SYSTEM_PROMPT ) > 100
        assert "narrative" in NARRATIVE_ANALYSIS_SYSTEM_PROMPT.lower()
