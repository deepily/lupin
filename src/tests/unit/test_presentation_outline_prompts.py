#!/usr/bin/env python3
"""
Unit tests for Presentation Generator Outline Prompts.

Tests cover:
    - OUTLINE_SYSTEM_PROMPT content validation
    - get_outline_prompt() parameter handling
    - parse_outline_response() with valid, wrapped, and malformed input
    - SLIDE_TYPES, VISUAL_TYPES, STRUCTURAL_POSITIONS constants
    - extract_outline_metadata()
"""

import json
import pytest

from cosa.agents.presentation_generator.prompts.outline import (
    OUTLINE_SYSTEM_PROMPT,
    SLIDE_TYPES,
    VISUAL_TYPES,
    STRUCTURAL_POSITIONS,
    get_outline_prompt,
    parse_outline_response,
    extract_outline_metadata,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def valid_outline_response():
    """Create a valid outline response JSON string."""
    return json.dumps( {
        "outline": [
            { "number": 1, "arc_position": "opening", "type": "title",     "title": "Three-Layer Caching",     "visual_type": "text_only" },
            { "number": 2, "arc_position": "opening", "type": "hook",      "title": "Your Users Wait 4 Seconds", "visual_type": "chart" },
            { "number": 3, "arc_position": "body",    "type": "key_point", "title": "Current Tools Miss 40%",  "visual_type": "diagram", "source_hint": "Methods" },
            { "number": 4, "arc_position": "body",    "type": "evidence",  "title": "Benchmark Data Shows 3x", "visual_type": "chart" },
            { "number": 5, "arc_position": "closing",  "type": "summary",   "title": "Three Changes Cut Latency", "visual_type": "text_only" },
            { "number": 6, "arc_position": "closing",  "type": "cta",       "title": "Start With L1 Today",     "visual_type": "text_only" },
            { "number": 7, "arc_position": "closing",  "type": "qa",        "title": "Questions?",              "visual_type": "text_only" },
        ],
        "total_slides"             : 7,
        "narrative_coherence_note" : "Strong argumentative flow"
    } )


@pytest.fixture
def sample_narrative_sections():
    """Create sample narrative sections (as dicts) for prompt building."""
    return [
        { "heading": "Introduction",   "arc_position": "setup",      "proposed_slides": 2 },
        { "heading": "Methods",        "arc_position": "argument",   "proposed_slides": 3 },
        { "heading": "Results",        "arc_position": "evidence",   "proposed_slides": 4 },
        { "heading": "Discussion",     "arc_position": "conclusion", "proposed_slides": 2 },
        { "heading": "Next Steps",     "arc_position": "cta",        "proposed_slides": 1 },
    ]


# =============================================================================
# System Prompt Tests
# =============================================================================

class TestOutlineSystemPrompt:
    """Tests for OUTLINE_SYSTEM_PROMPT content."""

    def test_system_prompt_is_non_empty( self ):
        assert len( OUTLINE_SYSTEM_PROMPT ) > 100

    def test_system_prompt_mentions_assertion( self ):
        assert "assertion" in OUTLINE_SYSTEM_PROMPT.lower()

    def test_system_prompt_contains_all_visual_types( self ):
        for vt in VISUAL_TYPES:
            assert vt in OUTLINE_SYSTEM_PROMPT, f"Missing visual type: {vt}"

    def test_system_prompt_contains_structural_formula( self ):
        assert "opening" in OUTLINE_SYSTEM_PROMPT.lower()
        assert "closing" in OUTLINE_SYSTEM_PROMPT.lower()
        assert "body" in OUTLINE_SYSTEM_PROMPT.lower()

    def test_system_prompt_requires_json_response( self ):
        assert "json" in OUTLINE_SYSTEM_PROMPT.lower()


# =============================================================================
# Prompt Builder Tests
# =============================================================================

class TestGetOutlinePrompt:
    """Tests for get_outline_prompt() function."""

    def test_includes_slide_budget( self, sample_narrative_sections ):
        prompt = get_outline_prompt( sample_narrative_sections, slide_budget=15 )
        assert "15 slides" in prompt

    def test_includes_narrative_sections( self, sample_narrative_sections ):
        prompt = get_outline_prompt( sample_narrative_sections, slide_budget=15 )
        assert "Introduction" in prompt
        assert "Methods" in prompt
        assert "Results" in prompt

    def test_includes_audience_guidelines( self, sample_narrative_sections ):
        prompt = get_outline_prompt(
            sample_narrative_sections, slide_budget=15, audience="expert"
        )
        assert "expertise" in prompt.lower() or "expert" in prompt.lower()

    def test_includes_audience_context( self, sample_narrative_sections ):
        prompt = get_outline_prompt(
            sample_narrative_sections, slide_budget=15, audience_context="ML engineers"
        )
        assert "ML engineers" in prompt

    def test_works_without_audience( self, sample_narrative_sections ):
        prompt = get_outline_prompt( sample_narrative_sections, slide_budget=15 )
        assert len( prompt ) > 50

    def test_includes_human_feedback( self, sample_narrative_sections ):
        prompt = get_outline_prompt(
            sample_narrative_sections, slide_budget=15,
            human_feedback="Make slide 3 more specific"
        )
        assert "Make slide 3 more specific" in prompt
        assert "Revision Feedback" in prompt

    def test_handles_empty_sections( self ):
        prompt = get_outline_prompt( [], slide_budget=15 )
        assert "15 slides" in prompt

    def test_structural_allocation( self, sample_narrative_sections ):
        prompt = get_outline_prompt( sample_narrative_sections, slide_budget=15 )
        assert "Opening" in prompt or "opening" in prompt
        assert "Closing" in prompt or "closing" in prompt

    def test_title_style_topic( self, sample_narrative_sections ):
        prompt = get_outline_prompt(
            sample_narrative_sections, slide_budget=15, title_style="topic"
        )
        assert "topic-style" in prompt.lower()

    def test_supports_narrative_section_objects( self ):
        """Test with objects that have heading/arc_position/proposed_slides attrs."""
        class FakeSection:
            def __init__( self, heading, arc_position, proposed_slides ):
                self.heading         = heading
                self.arc_position    = type( "Enum", (), { "value": arc_position } )()
                self.proposed_slides = proposed_slides

        sections = [ FakeSection( "Test Heading", "setup", 3 ) ]
        prompt = get_outline_prompt( sections, slide_budget=10 )
        assert "Test Heading" in prompt
        assert "setup" in prompt


# =============================================================================
# Response Parser Tests
# =============================================================================

class TestParseOutlineResponse:
    """Tests for parse_outline_response() function."""

    def test_valid_json_parses( self, valid_outline_response ):
        outline = parse_outline_response( valid_outline_response )
        assert len( outline ) == 7

    def test_markdown_wrapped_json( self, valid_outline_response ):
        wrapped = f"```json\n{valid_outline_response}\n```"
        outline = parse_outline_response( wrapped )
        assert len( outline ) == 7

    def test_bare_code_block_wrapper( self, valid_outline_response ):
        wrapped = f"```\n{valid_outline_response}\n```"
        outline = parse_outline_response( wrapped )
        assert len( outline ) == 7

    def test_malformed_raises( self ):
        """D6-STRICT: unrecoverable input raises ValueError (was: returned [])."""
        with pytest.raises( ValueError ):
            parse_outline_response( "not json at all" )

    def test_empty_string_raises( self ):
        """D6-STRICT: empty input raises ValueError (was: returned [])."""
        with pytest.raises( ValueError ):
            parse_outline_response( "" )

    def test_missing_outline_key_raises( self ):
        """D6-STRICT: missing 'outline' key raises ValueError (was: returned [])."""
        with pytest.raises( ValueError ):
            parse_outline_response( json.dumps( { "slides": [] } ) )

    def test_non_list_outline_raises( self ):
        """D6-STRICT: non-list 'outline' raises ValueError (was: returned [])."""
        with pytest.raises( ValueError ):
            parse_outline_response( json.dumps( { "outline": "not a list" } ) )

    def test_empty_outline_array_raises( self ):
        """D6-STRICT: empty 'outline' array raises ValueError (was: returned [])."""
        with pytest.raises( ValueError ):
            parse_outline_response( json.dumps( { "outline": [] } ) )

    # Diagnostic-message regression (twin of bug 957cb7b8): each raise branch
    # must log the predicate it ACTUALLY failed, never the "not-a-list: <class
    # 'list'>" self-contradiction the empty path used to print.
    def test_empty_outline_logs_empty_not_type_contradiction( self, caplog ):
        with caplog.at_level( "ERROR" ):
            with pytest.raises( ValueError ):
                parse_outline_response( json.dumps( { "outline": [] } ) )
        assert "empty list" in caplog.text
        assert "not-a-list" not in caplog.text
        assert "<class 'list'>" not in caplog.text

    def test_missing_outline_key_logs_missing( self, caplog ):
        with caplog.at_level( "ERROR" ):
            with pytest.raises( ValueError ):
                parse_outline_response( json.dumps( { "sections": [] } ) )
        assert "missing 'outline' key" in caplog.text

    def test_non_list_outline_logs_not_a_list_with_real_type( self, caplog ):
        with caplog.at_level( "ERROR" ):
            with pytest.raises( ValueError ):
                parse_outline_response( json.dumps( { "outline": "not a list" } ) )
        assert "not a list" in caplog.text
        assert "str" in caplog.text

    def test_invalid_arc_position_defaults_to_body( self ):
        data = json.dumps( { "outline": [ { "arc_position": "bogus", "title": "Test" } ] } )
        outline = parse_outline_response( data )
        assert outline[ 0 ][ "arc_position" ] == "body"

    def test_invalid_visual_type_defaults_to_text_only( self ):
        data = json.dumps( { "outline": [ { "visual_type": "hologram", "title": "Test" } ] } )
        outline = parse_outline_response( data )
        assert outline[ 0 ][ "visual_type" ] == "text_only"

    def test_invalid_slide_type_defaults_to_key_point( self ):
        data = json.dumps( { "outline": [ { "type": "mystery", "title": "Test" } ] } )
        outline = parse_outline_response( data )
        assert outline[ 0 ][ "type" ] == "key_point"

    def test_missing_fields_get_defaults( self ):
        data = json.dumps( { "outline": [ { "title": "Minimal" } ] } )
        outline = parse_outline_response( data )
        assert outline[ 0 ][ "arc_position" ] == "body"
        assert outline[ 0 ][ "visual_type" ] == "text_only"
        assert outline[ 0 ][ "type" ] == "key_point"
        assert outline[ 0 ][ "number" ] == 1

    def test_number_coerced_to_int( self ):
        data = json.dumps( { "outline": [ { "number": "3", "title": "Test" } ] } )
        outline = parse_outline_response( data )
        assert outline[ 0 ][ "number" ] == 3
        assert isinstance( outline[ 0 ][ "number" ], int )

    def test_non_dict_entries_skipped( self ):
        data = json.dumps( { "outline": [ "not a dict", { "title": "Valid" } ] } )
        outline = parse_outline_response( data )
        assert len( outline ) == 1
        assert outline[ 0 ][ "title" ] == "Valid"

    def test_source_hint_preserved( self, valid_outline_response ):
        outline = parse_outline_response( valid_outline_response )
        assert outline[ 2 ][ "source_hint" ] == "Methods"

    def test_all_slide_types_accepted( self ):
        entries = [ { "type": st, "title": f"Slide {st}", "number": i + 1 }
                    for i, st in enumerate( SLIDE_TYPES ) ]
        data = json.dumps( { "outline": entries } )
        outline = parse_outline_response( data )
        assert len( outline ) == len( SLIDE_TYPES )

    def test_all_visual_types_accepted( self ):
        entries = [ { "visual_type": vt, "title": f"Slide {vt}", "number": i + 1 }
                    for i, vt in enumerate( VISUAL_TYPES ) ]
        data = json.dumps( { "outline": entries } )
        outline = parse_outline_response( data )
        assert len( outline ) == len( VISUAL_TYPES )


# =============================================================================
# Metadata Extraction Tests
# =============================================================================

class TestExtractOutlineMetadata:
    """Tests for extract_outline_metadata() function."""

    def test_extracts_total_slides( self, valid_outline_response ):
        metadata = extract_outline_metadata( valid_outline_response )
        assert metadata[ "total_slides" ] == 7

    def test_extracts_coherence_note( self, valid_outline_response ):
        metadata = extract_outline_metadata( valid_outline_response )
        assert "Strong" in metadata[ "narrative_coherence_note" ]

    def test_malformed_returns_empty( self ):
        assert extract_outline_metadata( "not json" ) == {}


# =============================================================================
# Constants Tests
# =============================================================================

class TestOutlineConstants:
    """Tests for module-level constants."""

    def test_visual_types_count( self ):
        assert len( VISUAL_TYPES ) == 17

    def test_slide_types_count( self ):
        assert len( SLIDE_TYPES ) == 9

    def test_structural_positions_count( self ):
        assert len( STRUCTURAL_POSITIONS ) == 3

    def test_structural_positions_values( self ):
        assert set( STRUCTURAL_POSITIONS ) == { "opening", "body", "closing" }

    def test_visual_types_include_key_types( self ):
        assert "diagram" in VISUAL_TYPES
        assert "text_only" in VISUAL_TYPES
        assert "code_block" in VISUAL_TYPES
