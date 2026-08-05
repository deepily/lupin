#!/usr/bin/env python3
"""
Unit tests for the LLM-facing prompt builders + response parsers:
  prompts/narrative.py, prompts/outline.py, prompts/elaboration.py

Pure functions: get_*_prompt (string assembly with many optional blocks),
parse_*_response (markdown-fence stripping + JSON validation + field
defaulting), extract_*_metadata. No external boundaries.
"""

import json

import pytest

from cosa.agents.presentation_generator.prompts import narrative, outline, elaboration
from cosa.agents.presentation_generator.state import NarrativeSection, SlideOutline, ArcPosition


# ===========================================================================
# narrative.py
# ===========================================================================
class TestNarrativePrompt:
    def test_full_prompt_all_blocks( self ):
        raw_sections = [ ( "Intro", "some body words here", 1 ), ( "Plain", "", 0 ) ]
        ceiling = 100                               # the CONFIGURED ceiling, passed in
        p = narrative.get_narrative_analysis_prompt(
            source_content    = "x" * ( ceiling + 50 ),   # > ceiling → truncation note
            raw_sections      = raw_sections,
            target_duration   = 15,
            slides_per_minute = 1.0,
            audience          = "expert",
            audience_context  = "ML architects",
            max_source_chars  = ceiling,
        )
        assert "Pre-Parsed Document Structure" in p
        assert "H1" in p and "text" in p            # level>0 and level==0 indicators
        assert "deep domain expertise" in p          # expert audience guideline
        assert "ML architects" in p                  # audience_context
        assert f"truncated to {ceiling:,}" in p      # note cites the CONFIGURED ceiling, not a literal

    def test_minimal_prompt_no_optional_blocks( self ):
        p = narrative.get_narrative_analysis_prompt(
            source_content    = "short doc",
            raw_sections      = [],
            target_duration   = 10,
            slides_per_minute = 1.0,
            audience          = "unknown-audience",   # not in guidelines → no block
            audience_context  = None,
        )
        assert "Pre-Parsed Document Structure" not in p
        assert "truncated" not in p


class TestNarrativeParser:
    def test_parse_json_fence_full_validation( self ):
        raw = "```json\n" + json.dumps( {
            "sections": [
                { "heading": "A", "arc_position": "setup", "proposed_slide_count": 2 },
                { "heading": "B", "arc_position": "bogus", "proposed_slide_count": "notanint" },
                "not-a-dict",
            ]
        } ) + "\n```"
        out = narrative.parse_analysis_response( raw )
        assert len( out ) == 2                         # the string entry skipped
        assert out[ 0 ][ "arc_position" ] == "setup"
        assert out[ 1 ][ "arc_position" ] == "argument"   # bogus → default
        assert out[ 1 ][ "proposed_slide_count" ] == 1    # non-int → default

    def test_parse_empty_or_nondict_raises( self ):
        # D6-STRICT: empty sections (not sections arc) AND a bare non-dict JSON
        # value (else-ternary arc) are real defects → fail-loud.
        with pytest.raises( ValueError, match="no usable sections" ):
            narrative.parse_analysis_response( "```\n" + json.dumps( { "sections": [] } ) + "\n```" )
        with pytest.raises( ValueError, match="no usable sections" ):
            narrative.parse_analysis_response( json.dumps( [ 1, 2, 3 ] ) )   # non-dict

    def test_parse_unrecoverable_raises( self ):
        # D6-STRICT: no recoverable JSON object → raise (was: return []).
        with pytest.raises( ValueError, match="recoverable JSON object" ):
            narrative.parse_analysis_response( "not json at all" )

    def test_parse_sections_not_list_raises( self ):
        with pytest.raises( ValueError, match="no usable sections" ):
            narrative.parse_analysis_response( json.dumps( { "sections": "nope" } ) )

    def test_parse_all_nondict_entries_raises( self ):
        # D6-STRICT edge: a NON-EMPTY list whose entries are ALL non-dicts yields
        # zero usable sections after per-entry skip → fail-loud (was: return []).
        with pytest.raises( ValueError, match="no usable sections" ):
            narrative.parse_analysis_response( json.dumps( { "sections": [ 1, 2, 3 ] } ) )

    def test_extract_metadata_ok( self ):
        raw = "```json\n" + json.dumps( { "total_proposed_slides": 7, "narrative_assessment": "good" } ) + "\n```"
        md = narrative.extract_narrative_metadata( raw )
        assert md[ "total_proposed_slides" ] == 7
        assert md[ "narrative_assessment" ] == "good"

    def test_extract_metadata_bad_json( self ):
        assert narrative.extract_narrative_metadata( "```\nnope{\n```" ) == {}

    def test_extract_metadata_no_fence( self ):
        # no markdown fence at all → both fence checks False, no endswith strip
        md = narrative.extract_narrative_metadata( json.dumps( { "total_proposed_slides": 4 } ) )
        assert md[ "total_proposed_slides" ] == 4


# ===========================================================================
# outline.py
# ===========================================================================
class TestOutlinePrompt:
    def test_prompt_with_objects_audience_topic_feedback( self ):
        sections = [
            NarrativeSection( heading="Setup", content="c", arc_position=ArcPosition.SETUP, proposed_slides=1 ),
            NarrativeSection( heading="Args", content="c", arc_position=ArcPosition.ARGUMENT, proposed_slides=3 ),
        ]
        p = outline.get_outline_prompt(
            narrative_sections = sections,
            slide_budget       = 12,
            title_style        = "topic",
            audience           = "beginner",
            audience_context   = "students",
            human_feedback     = "more examples",
        )
        assert "Setup" in p and "Args" in p
        assert "proposed: 1 slide\n" in p     # singular
        assert "proposed: 3 slides" in p      # plural
        assert "topic-style titles" in p
        assert "new to this topic" in p       # beginner guideline
        assert "students" in p
        assert "more examples" in p

    def test_prompt_with_dicts_minimal( self ):
        sections = [ { "heading": "X", "arc_position": "setup", "proposed_slides": 1 } ]
        p = outline.get_outline_prompt( narrative_sections=sections, slide_budget=2 )
        # body_budget floored at 1 even when budget tiny
        assert "Body**: 1 slides" in p
        assert "topic-style" not in p          # default assertion style


class TestOutlineParser:
    def test_parse_full_validation_defaults( self ):
        raw = "```json\n" + json.dumps( {
            "outline": [
                { "number": 1, "arc_position": "opening", "type": "title", "visual_type": "diagram", "title": "T" },
                { "number": "2", "arc_position": "bogus", "type": "bogus", "visual_type": "bogus" },
                12345,
            ]
        } ) + "\n```"
        out = outline.parse_outline_response( raw )
        assert len( out ) == 2                  # int entry skipped
        assert out[ 1 ][ "arc_position" ] == "body"       # bogus → default
        assert out[ 1 ][ "type" ] == "key_point"          # bogus → default
        assert out[ 1 ][ "visual_type" ] == "text_only"   # bogus → default
        assert out[ 1 ][ "number" ] == 2                  # "2" coerced to int

    def test_parse_number_not_intable( self ):
        raw = json.dumps( { "outline": [ { "number": "xx", "arc_position": "body", "type": "title", "visual_type": "text_only" } ] } )
        out = outline.parse_outline_response( raw )
        assert out[ 0 ][ "number" ] == 1        # fallback to len+1

    def test_parse_empty_or_nondict_raises( self ):
        # D6-STRICT: empty outline + bare non-dict JSON → fail-loud.
        with pytest.raises( ValueError, match="no usable entries" ):
            outline.parse_outline_response( "```\n" + json.dumps( { "outline": [] } ) + "\n```" )
        with pytest.raises( ValueError, match="no usable entries" ):
            outline.parse_outline_response( json.dumps( [ 1, 2 ] ) )   # non-dict

    def test_parse_unrecoverable_raises( self ):
        with pytest.raises( ValueError, match="recoverable JSON object" ):
            outline.parse_outline_response( "garbage no json" )

    def test_parse_outline_not_list_raises( self ):
        with pytest.raises( ValueError, match="no usable entries" ):
            outline.parse_outline_response( json.dumps( { "outline": 5 } ) )

    def test_parse_all_nondict_entries_raises( self ):
        # D6-STRICT edge: all-non-dict entries → zero usable entries → fail-loud.
        with pytest.raises( ValueError, match="no usable entries" ):
            outline.parse_outline_response( json.dumps( { "outline": [ 1, 2 ] } ) )

    def test_extract_metadata_json_fence( self ):
        raw = "```json\n" + json.dumps( { "total_slides": 10, "narrative_coherence_note": "n" } ) + "\n```"
        md = outline.extract_outline_metadata( raw )
        assert md[ "total_slides" ] == 10

    def test_extract_metadata_bare_fence( self ):
        raw = "```\n" + json.dumps( { "total_slides": 2 } ) + "\n```"
        assert outline.extract_outline_metadata( raw )[ "total_slides" ] == 2

    def test_extract_metadata_bad( self ):
        assert outline.extract_outline_metadata( "nope{" ) == {}


# ===========================================================================
# elaboration.py
# ===========================================================================
class TestElaborationPrompt:
    def test_prompt_with_objects_all_blocks( self ):
        outlines = [
            SlideOutline( number=1, arc_position="opening", type="title", title="T", visual_type="text_only" ),
            SlideOutline( number=2, arc_position="body", type="key_point", title="K", visual_type="diagram", source_hint="Sec1" ),
        ]
        ceiling = 100                             # the CONFIGURED ceiling, passed in
        p = elaboration.get_elaboration_prompt(
            slide_outlines          = outlines,
            source_content          = "y" * ( ceiling + 50 ),
            target_duration_minutes = 10,
            audience                = "academic",
            audience_context        = "researchers",
            human_feedback          = "tighten timing",
            max_source_chars        = ceiling,
        )
        assert "(source: Sec1)" in p
        assert "research-oriented" in p           # academic guideline
        assert "researchers" in p
        assert f"truncated to {ceiling:,}" in p   # note cites the CONFIGURED ceiling, not a literal
        assert "tighten timing" in p

    def test_prompt_with_dicts_minimal( self ):
        outlines = [ { "number": 1, "type": "title", "title": "T", "arc_position": "opening", "visual_type": "text_only" } ]
        p = elaboration.get_elaboration_prompt(
            slide_outlines          = outlines,
            source_content          = "short",
            target_duration_minutes = 5,
        )
        assert "(source:" not in p                # no source_hint
        assert "truncated" not in p

    def test_prompt_dict_with_source_hint( self ):
        outlines = [ { "number": 1, "type": "title", "title": "T", "arc_position": "opening", "visual_type": "text_only", "source_hint": "S" } ]
        p = elaboration.get_elaboration_prompt( slide_outlines=outlines, source_content="s", target_duration_minutes=5 )
        assert "(source: S)" in p


class TestElaborationParser:
    def test_parse_full_validation( self ):
        raw = "```json\n" + json.dumps( {
            "slides": [
                {
                    "number": 1, "title": "A", "content_bullets": [ "a" ],
                    "presenter_notes": { "timing_seconds": 9999, "talking_points": [ "tp" ] },
                },
                {
                    "number": "2", "presenter_notes": "not-a-dict", "content_bullets": "not-a-list",
                },
                "skip-me",
            ]
        } ) + "\n```"
        out = elaboration.parse_elaboration_response( raw )
        assert len( out ) == 2                                  # string skipped
        assert out[ 0 ][ "presenter_notes" ][ "timing_seconds" ] == 180   # clamped to MAX
        assert out[ 1 ][ "presenter_notes" ] == {
            "transition": None, "talking_points": [], "timing_seconds": 60, "emphasis": None
        }
        assert out[ 1 ][ "content_bullets" ] == []             # non-list → []
        assert out[ 1 ][ "number" ] == 2                       # coerced

    def test_parse_timing_not_intable_and_number_not_intable( self ):
        raw = json.dumps( { "slides": [
            { "number": "zz", "presenter_notes": { "timing_seconds": "abc" } },
        ] } )
        out = elaboration.parse_elaboration_response( raw )
        assert out[ 0 ][ "presenter_notes" ][ "timing_seconds" ] == 60   # default
        assert out[ 0 ][ "number" ] == 1                                  # fallback

    def test_parse_talking_points_not_list( self ):
        raw = json.dumps( { "slides": [ { "number": 1, "presenter_notes": { "talking_points": "nope" } } ] } )
        out = elaboration.parse_elaboration_response( raw )
        assert out[ 0 ][ "presenter_notes" ][ "talking_points" ] == []

    def test_parse_empty_or_nondict_raises( self ):
        # D6-STRICT: empty slides + bare non-dict JSON → fail-loud.
        with pytest.raises( ValueError, match="no usable slides" ):
            elaboration.parse_elaboration_response( "```\n" + json.dumps( { "slides": [] } ) + "\n```" )
        with pytest.raises( ValueError, match="no usable slides" ):
            elaboration.parse_elaboration_response( json.dumps( [ 1 ] ) )   # non-dict

    def test_parse_unrecoverable_raises( self ):
        with pytest.raises( ValueError, match="recoverable JSON object" ):
            elaboration.parse_elaboration_response( "totally not json" )

    def test_parse_slides_not_list_raises( self ):
        with pytest.raises( ValueError, match="no usable slides" ):
            elaboration.parse_elaboration_response( json.dumps( { "slides": 3 } ) )

    def test_parse_all_nondict_entries_raises( self ):
        # D6-STRICT edge: all-non-dict entries → zero usable slides → fail-loud.
        with pytest.raises( ValueError, match="no usable slides" ):
            elaboration.parse_elaboration_response( json.dumps( { "slides": [ 1, 2 ] } ) )


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
