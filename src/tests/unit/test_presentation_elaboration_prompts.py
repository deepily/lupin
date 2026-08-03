#!/usr/bin/env python3
"""
Unit tests for Presentation Generator Elaboration Prompts.

Tests cover:
    - ELABORATION_SYSTEM_PROMPT content validation
    - get_elaboration_prompt() parameter handling
    - parse_elaboration_response() with valid, wrapped, and malformed input
    - Timing constants and bounds
"""

import json
import pytest

from cosa.agents.presentation_generator.prompts.elaboration import (
    ELABORATION_SYSTEM_PROMPT,
    DEFAULT_TIMING_PER_SLIDE,
    MIN_TIMING_PER_SLIDE,
    MAX_TIMING_PER_SLIDE,
    get_elaboration_prompt,
    parse_elaboration_response,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def valid_elaboration_response():
    """Create a valid elaboration response JSON string."""
    return json.dumps( {
        "slides": [
            {
                "number"             : 1,
                "arc_position"       : "opening",
                "type"               : "title",
                "title"              : "Three-Layer Caching",
                "subtitle"           : "Eliminating Cold Starts at Scale",
                "visual_type"        : "text_only",
                "visual_description" : None,
                "content_bullets"    : [],
                "presenter_notes"    : {
                    "transition"     : None,
                    "talking_points" : [ "Welcome everyone", "Introduce yourself" ],
                    "timing_seconds" : 30,
                    "emphasis"       : None
                }
            },
            {
                "number"             : 2,
                "arc_position"       : "body",
                "type"               : "key_point",
                "title"              : "Current Tools Miss 40% of Edge Cases",
                "subtitle"           : None,
                "visual_type"        : "diagram",
                "visual_description" : "Flowchart: Request → L1 → L2 → L3",
                "content_bullets"    : [ "L1 handles 80%", "L2 catches 15%", "L3 covers the rest" ],
                "presenter_notes"    : {
                    "transition"     : "Now let's look at the architecture...",
                    "talking_points" : [ "Walk through each layer", "Explain hit rates" ],
                    "timing_seconds" : 75,
                    "emphasis"       : "Pause at L2 explanation"
                }
            },
            {
                "number"             : 3,
                "arc_position"       : "closing",
                "type"               : "qa",
                "title"              : "Questions?",
                "visual_type"        : "text_only",
                "visual_description" : None,
                "content_bullets"    : [],
                "presenter_notes"    : {
                    "transition"     : "Before we wrap up...",
                    "talking_points" : [ "Open the floor" ],
                    "timing_seconds" : 60,
                    "emphasis"       : None
                }
            }
        ]
    } )


@pytest.fixture
def sample_outlines():
    """Create sample slide outlines (as dicts) for prompt building."""
    return [
        { "number": 1, "type": "title",     "title": "My Talk",      "arc_position": "opening", "visual_type": "text_only" },
        { "number": 2, "type": "hook",      "title": "Did You Know?", "arc_position": "opening", "visual_type": "chart" },
        { "number": 3, "type": "key_point", "title": "Key Insight",  "arc_position": "body",    "visual_type": "diagram" },
        { "number": 4, "type": "qa",        "title": "Questions?",   "arc_position": "closing",  "visual_type": "text_only" },
    ]


# =============================================================================
# System Prompt Tests
# =============================================================================

class TestElaborationSystemPrompt:
    """Tests for ELABORATION_SYSTEM_PROMPT content."""

    def test_system_prompt_is_non_empty( self ):
        assert len( ELABORATION_SYSTEM_PROMPT ) > 100

    def test_mentions_presenter_notes( self ):
        assert "presenter notes" in ELABORATION_SYSTEM_PROMPT.lower()

    def test_mentions_talking_points( self ):
        assert "talking_points" in ELABORATION_SYSTEM_PROMPT

    def test_mentions_visual_description( self ):
        assert "visual_description" in ELABORATION_SYSTEM_PROMPT

    def test_mentions_timing( self ):
        assert "timing_seconds" in ELABORATION_SYSTEM_PROMPT


# =============================================================================
# Prompt Builder Tests
# =============================================================================

class TestGetElaborationPrompt:
    """Tests for get_elaboration_prompt() function."""

    def test_includes_duration( self, sample_outlines ):
        prompt = get_elaboration_prompt( sample_outlines, "Source text.", 15 )
        assert "15 minutes" in prompt

    def test_includes_source_content( self, sample_outlines ):
        prompt = get_elaboration_prompt( sample_outlines, "Unique source content here.", 15 )
        assert "Unique source content here." in prompt

    def test_includes_outline_titles( self, sample_outlines ):
        prompt = get_elaboration_prompt( sample_outlines, "Source.", 15 )
        assert "My Talk" in prompt
        assert "Key Insight" in prompt

    def test_includes_audience_context( self, sample_outlines ):
        prompt = get_elaboration_prompt(
            sample_outlines, "Source.", 15,
            audience="expert", audience_context="Security researchers"
        )
        assert "Security researchers" in prompt

    def test_includes_human_feedback( self, sample_outlines ):
        prompt = get_elaboration_prompt(
            sample_outlines, "Source.", 15,
            human_feedback="Add more data to slide 3"
        )
        assert "Add more data to slide 3" in prompt
        assert "Revision Feedback" in prompt

    def test_works_without_audience( self, sample_outlines ):
        prompt = get_elaboration_prompt( sample_outlines, "Source.", 15 )
        assert len( prompt ) > 50

    def test_calculates_avg_seconds_per_slide( self, sample_outlines ):
        prompt = get_elaboration_prompt( sample_outlines, "Source.", 15 )
        # 15 min = 900s / 4 slides = 225s
        assert "225 seconds" in prompt

    def test_source_truncation( self, sample_outlines ):
        long_source = "x" * 35000
        prompt = get_elaboration_prompt( sample_outlines, long_source, 15 )
        assert "truncated" in prompt.lower()
        assert len( prompt ) < len( long_source ) + 5000

    def test_single_slide_outline( self ):
        outlines = [ { "number": 1, "type": "title", "title": "Solo", "arc_position": "opening", "visual_type": "text_only" } ]
        prompt = get_elaboration_prompt( outlines, "Source.", 5 )
        assert "Solo" in prompt

    def test_supports_outline_objects( self ):
        """Test with objects that have number/type/title/arc_position/visual_type attrs."""
        class FakeOutline:
            def __init__( self ):
                self.number       = 1
                self.type         = "title"
                self.title        = "Object Title"
                self.arc_position = "opening"
                self.visual_type  = "text_only"
                self.source_hint  = "Intro section"

        prompt = get_elaboration_prompt( [ FakeOutline() ], "Source.", 10 )
        assert "Object Title" in prompt
        assert "Intro section" in prompt


# =============================================================================
# Response Parser Tests
# =============================================================================

class TestParseElaborationResponse:
    """Tests for parse_elaboration_response() function."""

    def test_valid_json_parses( self, valid_elaboration_response ):
        slides = parse_elaboration_response( valid_elaboration_response )
        assert len( slides ) == 3

    def test_markdown_wrapped_json( self, valid_elaboration_response ):
        wrapped = f"```json\n{valid_elaboration_response}\n```"
        slides = parse_elaboration_response( wrapped )
        assert len( slides ) == 3

    def test_bare_code_block_wrapper( self, valid_elaboration_response ):
        wrapped = f"```\n{valid_elaboration_response}\n```"
        slides = parse_elaboration_response( wrapped )
        assert len( slides ) == 3

    def test_malformed_raises( self ):
        """D6-STRICT: unrecoverable input raises ValueError (was: returned [])."""
        with pytest.raises( ValueError ):
            parse_elaboration_response( "not json" )

    def test_empty_string_raises( self ):
        """D6-STRICT: empty input raises ValueError (was: returned [])."""
        with pytest.raises( ValueError ):
            parse_elaboration_response( "" )

    def test_missing_slides_key_raises( self ):
        """D6-STRICT: missing 'slides' key raises ValueError (was: returned [])."""
        with pytest.raises( ValueError ):
            parse_elaboration_response( json.dumps( { "outline": [] } ) )

    def test_non_list_slides_raises( self ):
        """D6-STRICT: non-list 'slides' raises ValueError (was: returned [])."""
        with pytest.raises( ValueError ):
            parse_elaboration_response( json.dumps( { "slides": "not a list" } ) )

    def test_empty_slides_array_raises( self ):
        """D6-STRICT: empty 'slides' array raises ValueError (was: returned [])."""
        with pytest.raises( ValueError ):
            parse_elaboration_response( json.dumps( { "slides": [] } ) )

    def test_missing_presenter_notes_gets_defaults( self ):
        data = json.dumps( { "slides": [ { "title": "Test", "number": 1 } ] } )
        slides = parse_elaboration_response( data )
        notes = slides[ 0 ][ "presenter_notes" ]
        assert notes[ "timing_seconds" ] == DEFAULT_TIMING_PER_SLIDE
        assert notes[ "talking_points" ] == []
        assert notes[ "transition" ] is None
        assert notes[ "emphasis" ] is None

    def test_missing_content_bullets_defaults_empty( self ):
        data = json.dumps( { "slides": [ { "title": "Test", "number": 1 } ] } )
        slides = parse_elaboration_response( data )
        assert slides[ 0 ][ "content_bullets" ] == []

    def test_visual_description_defaults_to_none( self ):
        data = json.dumps( { "slides": [ { "title": "Test", "number": 1 } ] } )
        slides = parse_elaboration_response( data )
        assert slides[ 0 ][ "visual_description" ] is None

    def test_negative_timing_clamped_to_minimum( self ):
        data = json.dumps( { "slides": [ {
            "title": "Test", "number": 1,
            "presenter_notes": { "timing_seconds": -10 }
        } ] } )
        slides = parse_elaboration_response( data )
        assert slides[ 0 ][ "presenter_notes" ][ "timing_seconds" ] == MIN_TIMING_PER_SLIDE

    def test_excessive_timing_clamped_to_maximum( self ):
        data = json.dumps( { "slides": [ {
            "title": "Test", "number": 1,
            "presenter_notes": { "timing_seconds": 9999 }
        } ] } )
        slides = parse_elaboration_response( data )
        assert slides[ 0 ][ "presenter_notes" ][ "timing_seconds" ] == MAX_TIMING_PER_SLIDE

    def test_non_int_timing_defaults( self ):
        data = json.dumps( { "slides": [ {
            "title": "Test", "number": 1,
            "presenter_notes": { "timing_seconds": "sixty" }
        } ] } )
        slides = parse_elaboration_response( data )
        assert slides[ 0 ][ "presenter_notes" ][ "timing_seconds" ] == DEFAULT_TIMING_PER_SLIDE

    def test_non_dict_entries_skipped( self ):
        data = json.dumps( { "slides": [ "not a dict", { "title": "Valid", "number": 1 } ] } )
        slides = parse_elaboration_response( data )
        assert len( slides ) == 1

    def test_non_dict_presenter_notes_gets_defaults( self ):
        data = json.dumps( { "slides": [ {
            "title": "Test", "number": 1,
            "presenter_notes": "not a dict"
        } ] } )
        slides = parse_elaboration_response( data )
        assert slides[ 0 ][ "presenter_notes" ][ "timing_seconds" ] == DEFAULT_TIMING_PER_SLIDE

    def test_non_list_talking_points_defaults_empty( self ):
        data = json.dumps( { "slides": [ {
            "title": "Test", "number": 1,
            "presenter_notes": { "talking_points": "not a list" }
        } ] } )
        slides = parse_elaboration_response( data )
        assert slides[ 0 ][ "presenter_notes" ][ "talking_points" ] == []

    def test_non_list_content_bullets_defaults_empty( self ):
        data = json.dumps( { "slides": [ {
            "title": "Test", "number": 1,
            "content_bullets": "not a list"
        } ] } )
        slides = parse_elaboration_response( data )
        assert slides[ 0 ][ "content_bullets" ] == []

    def test_number_coerced_to_int( self ):
        data = json.dumps( { "slides": [ { "title": "Test", "number": "5" } ] } )
        slides = parse_elaboration_response( data )
        assert slides[ 0 ][ "number" ] == 5
        assert isinstance( slides[ 0 ][ "number" ], int )

    def test_preserves_visual_description( self, valid_elaboration_response ):
        slides = parse_elaboration_response( valid_elaboration_response )
        assert slides[ 1 ][ "visual_description" ] == "Flowchart: Request → L1 → L2 → L3"

    def test_preserves_subtitle( self, valid_elaboration_response ):
        slides = parse_elaboration_response( valid_elaboration_response )
        assert slides[ 0 ][ "subtitle" ] == "Eliminating Cold Starts at Scale"

    def test_preserves_content_bullets( self, valid_elaboration_response ):
        slides = parse_elaboration_response( valid_elaboration_response )
        assert len( slides[ 1 ][ "content_bullets" ] ) == 3
        assert "L1 handles 80%" in slides[ 1 ][ "content_bullets" ]

    def test_preserves_transition( self, valid_elaboration_response ):
        slides = parse_elaboration_response( valid_elaboration_response )
        assert slides[ 1 ][ "presenter_notes" ][ "transition" ] == "Now let's look at the architecture..."

    def test_preserves_emphasis( self, valid_elaboration_response ):
        slides = parse_elaboration_response( valid_elaboration_response )
        assert slides[ 1 ][ "presenter_notes" ][ "emphasis" ] == "Pause at L2 explanation"


# =============================================================================
# Constants Tests
# =============================================================================

class TestElaborationConstants:
    """Tests for module-level constants."""

    def test_default_timing_is_60( self ):
        assert DEFAULT_TIMING_PER_SLIDE == 60

    def test_min_timing_positive( self ):
        assert MIN_TIMING_PER_SLIDE > 0

    def test_max_timing_greater_than_min( self ):
        assert MAX_TIMING_PER_SLIDE > MIN_TIMING_PER_SLIDE

    def test_default_within_bounds( self ):
        assert MIN_TIMING_PER_SLIDE <= DEFAULT_TIMING_PER_SLIDE <= MAX_TIMING_PER_SLIDE

    def test_max_timing_reasonable( self ):
        assert MAX_TIMING_PER_SLIDE <= 300  # 5 minutes max per slide
