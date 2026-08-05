#!/usr/bin/env python3
"""
Elaboration Prompts for Presentation Generator.

Provides system prompts, prompt builders, and response parsers for the
elaboration phase (Orchestrator Phase 4: Elaborate).

The LLM takes a slide outline and the source document, then produces
fully elaborated slide content with presenter notes.
"""

import json
import logging
from typing import List, Optional

from .narrative import AUDIENCE_COMPLEXITY_GUIDELINES
from .json_recovery import recover_json_object

logger = logging.getLogger( __name__ )


# =============================================================================
# Constants
# =============================================================================

DEFAULT_TIMING_PER_SLIDE = 60   # seconds
MIN_TIMING_PER_SLIDE     = 15   # seconds
MAX_TIMING_PER_SLIDE     = 180  # seconds


# =============================================================================
# System Prompt
# =============================================================================

ELABORATION_SYSTEM_PROMPT = """You are an expert presentation content writer and speaking coach. Your task is to take a slide outline and elaborate each slide with full content and presenter notes.

## Content Bullets

For each slide, write 3-5 content bullets that:
- Make substantive claims (not topic labels)
- Are self-contained — each bullet should make sense in isolation
- Progress logically — the sequence tells a mini-story
- Match the visual type — bullets for a diagram slide should reference the diagram

Exceptions:
- Title slides: 0-1 bullets (subtitle handles content)
- Q&A slides: 0-1 bullets (typically just "Questions?")

## Presenter Notes

For each slide, write presenter notes containing:

- **transition**: One sentence connecting this slide to the previous one. How does the speaker bridge from what was just said? First slide has no transition.
- **talking_points**: 2-4 bullet points of what to SAY (not what's on the slide). These expand on the slide content with examples, anecdotes, context, or emphasis. They are the speaker's script.
- **timing_seconds**: How many seconds this slide should take. Use the average provided but adjust — title slides are shorter (15-30s), dense content slides are longer (60-90s).
- **emphasis**: Optional — which point to stress, where to pause, what to gesture at.

## Visual Descriptions

For slides with visual_type other than `text_only`:
- Write a **visual_description** — a natural-language spec the renderer will use
- For `diagram`: describe the flow, nodes, and edges (e.g., "Flowchart: Request → L1 Cache → L2 Cache → L3 Storage")
- For `code_block`: describe what code to show (e.g., "Python: 3-line caching decorator with TTL parameter")
- For `chart`: describe the data and chart type (e.g., "Bar chart: Response time comparison — before (4.2s) vs after (0.8s)")
- For `table`: describe rows and columns (e.g., "3-column table: Feature | Before | After")
- For `before_after`: describe both sides (e.g., "Left: manual process (5 steps), Right: automated (2 steps)")
- For `screenshot`: describe what image to insert (e.g., "Screenshot of the monitoring dashboard showing latency spike")
- For `icon_only`: suggest an emoji or icon (e.g., "🔍 magnifying glass icon")

For `text_only` slides: set visual_description to null.

## Response Format

You MUST respond with valid JSON in the following format:
```json
{
    "slides": [
        {
            "number": 1,
            "arc_position": "opening",
            "type": "title",
            "title": "Assertion-style title",
            "subtitle": "Optional subtitle or speaker name",
            "visual_type": "text_only",
            "visual_description": null,
            "content_bullets": [],
            "presenter_notes": {
                "transition": null,
                "talking_points": ["Welcome the audience", "Introduce yourself"],
                "timing_seconds": 30,
                "emphasis": null
            }
        }
    ]
}
```"""


# =============================================================================
# Prompt Builder
# =============================================================================

def get_elaboration_prompt(
    slide_outlines: list,
    source_content: str,
    target_duration_minutes: int,
    audience: Optional[ str ] = None,
    audience_context: Optional[ str ] = None,
    human_feedback: Optional[ str ] = None,
    max_source_chars: Optional[ int ] = None,
) -> str:
    """
    Build user message for slide elaboration.

    Requires:
        - slide_outlines is a list of SlideOutline objects or dicts
        - source_content is a non-empty string
        - target_duration_minutes > 0

    Ensures:
        - Returns formatted prompt with outline, source, and timing
        - Includes audience guidelines if provided
        - Appends human feedback for revisions if provided

    Args:
        slide_outlines: Slide outlines from Phase 3
        source_content: Original source document content
        target_duration_minutes: Target presentation duration in minutes
        audience: Audience level (beginner/general/expert/academic)
        audience_context: Optional free-text audience description
        human_feedback: Optional revision feedback from Gate 3

    Returns:
        str: Formatted user message for Claude
    """
    total_slides = len( slide_outlines )
    total_seconds = target_duration_minutes * 60
    avg_seconds_per_slide = total_seconds // max( 1, total_slides )

    # Format outlines as JSON-like list
    outlines_text = ""
    for outline in slide_outlines:
        if hasattr( outline, "number" ):
            outlines_text += (
                f"  {outline.number}. [{outline.type}] \"{outline.title}\" "
                f"— {outline.arc_position}, {outline.visual_type}"
            )
            if outline.source_hint:
                outlines_text += f" (source: {outline.source_hint})"
            outlines_text += "\n"
        else:
            outlines_text += (
                f"  {outline.get( 'number', '?' )}. [{outline.get( 'type', '?' )}] "
                f"\"{outline.get( 'title', '?' )}\" — {outline.get( 'arc_position', '?' )}, "
                f"{outline.get( 'visual_type', 'text_only' )}"
            )
            hint = outline.get( "source_hint" )
            if hint:
                outlines_text += f" (source: {hint})"
            outlines_text += "\n"

    # Audience guidelines
    audience_block = ""
    if audience and audience in AUDIENCE_COMPLEXITY_GUIDELINES:
        audience_block = f"\n\n## Audience\n\n{AUDIENCE_COMPLEXITY_GUIDELINES[ audience ]}"
    if audience_context:
        audience_block += f"\n\nAdditional audience context: {audience_context}"

    # Truncate source content if it exceeds the configured ceiling. The ceiling
    # is passed in from config (see PresentationConfig.max_source_chars, loaded
    # from the shared `agent source content max chars` INI key); None = no clip.
    truncated = source_content
    truncation_note = ""
    if max_source_chars is not None and len( source_content ) > max_source_chars:
        truncated = source_content[ :max_source_chars ]
        truncation_note = f"\n\n[NOTE: Document was truncated to {max_source_chars:,} characters. Focus on the provided content.]"

    # Revision feedback
    feedback_block = ""
    if human_feedback:
        feedback_block = f"\n\n## Revision Feedback\n\nThe user reviewed the previous elaboration and requested changes:\n\n> {human_feedback}\n\nPlease incorporate this feedback into the revised slides."

    prompt = f"""Elaborate the following slide outline with full content and presenter notes.

## Timing

- **Target duration**: {target_duration_minutes} minutes ({total_seconds} seconds)
- **Total slides**: {total_slides}
- **Average time per slide**: {avg_seconds_per_slide} seconds
- Adjust per slide: title slides shorter (15-30s), dense content longer (60-90s)
{audience_block}

## Slide Outline

{outlines_text}
{feedback_block}

## Source Document

Use this document as the authoritative source for content. Extract specific data, quotes, and examples.

```
{truncated}
```
{truncation_note}

## Instructions

1. Elaborate every slide from the outline above
2. Write 3-5 substantive content bullets per body slide
3. Write presenter notes with transition, talking points, timing, and emphasis
4. For non-text_only slides, write a visual_description the renderer can use
5. Keep total timing close to {total_seconds} seconds ({target_duration_minutes} minutes)
6. Preserve slide numbers, titles, types, and visual types from the outline

Generate the elaborated slides as JSON."""

    return prompt


# =============================================================================
# Response Parser
# =============================================================================

def parse_elaboration_response( response_content: str ) -> List[ dict ]:
    """
    Parse Claude's elaboration response into slide dicts.

    Handles markdown code block wrapping and gracefully falls back on errors.

    Requires:
        - response_content is a non-empty string

    Ensures:
        - Returns a non-empty list of slide dicts matching SlideModel fields
        - Ensures presenter_notes has all required subfields

    Raises:
        - ValueError (D6-STRICT fail-loud) when the response has no recoverable
          JSON object, the "slides" value is missing / not a list / empty, or
          every entry is a non-dict (zero usable slides).

    Args:
        response_content: Raw response from Claude API

    Returns:
        List of slide dicts (always non-empty on return)
    """
    # D6-STRICT: recover the JSON object from chatty bounded-CC output, then
    # fail-loud on unrecoverable / missing / empty structured content.
    parsed = recover_json_object( response_content )
    if parsed is None:
        logger.error( "Failed to recover elaboration JSON" )
        logger.debug( f"Raw content (first 500 chars): {response_content[ :500 ]}" )
        raise ValueError( "Elaboration response did not contain a recoverable JSON object" )

    # Extract slides list (STRICT: missing / empty / non-list is a real defect)
    slides = parsed.get( "slides", [] ) if isinstance( parsed, dict ) else []
    if not isinstance( slides, list ) or not slides:
        logger.error( f"Elaboration 'slides' missing/empty/not-a-list: {type( slides )}" )
        raise ValueError( "Elaboration returned no usable slides" )

    # Validate each slide
    validated = []
    for slide in slides:
        if not isinstance( slide, dict ):
            continue

        # Validate presenter_notes substructure
        raw_notes = slide.get( "presenter_notes", {} )
        if not isinstance( raw_notes, dict ):
            raw_notes = {}

        timing = raw_notes.get( "timing_seconds", DEFAULT_TIMING_PER_SLIDE )
        try:
            timing = int( timing )
            timing = max( MIN_TIMING_PER_SLIDE, min( MAX_TIMING_PER_SLIDE, timing ) )
        except ( ValueError, TypeError ):
            timing = DEFAULT_TIMING_PER_SLIDE

        talking_points = raw_notes.get( "talking_points", [] )
        if not isinstance( talking_points, list ):
            talking_points = []

        presenter_notes = {
            "transition"     : raw_notes.get( "transition", None ),
            "talking_points" : talking_points,
            "timing_seconds" : timing,
            "emphasis"       : raw_notes.get( "emphasis", None ),
        }

        # Validate content_bullets
        content_bullets = slide.get( "content_bullets", [] )
        if not isinstance( content_bullets, list ):
            content_bullets = []

        validated_slide = {
            "number"             : slide.get( "number", len( validated ) + 1 ),
            "arc_position"       : slide.get( "arc_position", "body" ),
            "type"               : slide.get( "type", "key_point" ),
            "title"              : slide.get( "title", "(untitled)" ),
            "subtitle"           : slide.get( "subtitle", None ),
            "visual_type"        : slide.get( "visual_type", "text_only" ),
            "visual_description" : slide.get( "visual_description", None ),
            "content_bullets"    : content_bullets,
            "presenter_notes"    : presenter_notes,
        }

        # Ensure number is int
        try:
            validated_slide[ "number" ] = int( validated_slide[ "number" ] )
        except ( ValueError, TypeError ):
            validated_slide[ "number" ] = len( validated ) + 1

        validated.append( validated_slide )

    # D6-STRICT: a non-empty list whose entries are ALL non-dicts (e.g.
    # {"slides": [1, 2]}) yields zero usable slides — a real defect.
    if not validated:
        logger.error( "Elaboration 'slides' contained no usable dict entries" )
        raise ValueError( "Elaboration returned no usable slides" )

    return validated


# =============================================================================
# Smoke Test
# =============================================================================

def quick_smoke_test():
    """Quick smoke test for elaboration prompts module."""
    import cosa.utils.util as cu

    cu.print_banner( "Elaboration Prompts Smoke Test", prepend_nl=True )

    try:
        # Test 1: System prompt exists
        print( "Testing ELABORATION_SYSTEM_PROMPT..." )
        assert len( ELABORATION_SYSTEM_PROMPT ) > 100
        assert "presenter notes" in ELABORATION_SYSTEM_PROMPT.lower()
        assert "talking_points" in ELABORATION_SYSTEM_PROMPT
        assert "visual_description" in ELABORATION_SYSTEM_PROMPT
        print( "  ✓ System prompt has expected content" )

        # Test 2: Prompt builder
        print( "Testing get_elaboration_prompt..." )
        prompt = get_elaboration_prompt(
            slide_outlines = [
                { "number": 1, "type": "title", "title": "Test", "arc_position": "opening", "visual_type": "text_only" },
                { "number": 2, "type": "key_point", "title": "Key", "arc_position": "body", "visual_type": "diagram" },
            ],
            source_content          = "Some document content about testing.",
            target_duration_minutes = 15,
            audience                = "general",
        )
        assert "15 minutes" in prompt
        assert "Test" in prompt
        assert "Key" in prompt
        assert "Some document content" in prompt
        print( "  ✓ Prompt generated correctly" )

        # Test 3: Parse valid response
        print( "Testing parse_elaboration_response with valid JSON..." )
        valid_response = json.dumps( {
            "slides": [
                {
                    "number"             : 1,
                    "arc_position"       : "opening",
                    "type"               : "title",
                    "title"              : "My Presentation",
                    "subtitle"           : "A deep dive",
                    "visual_type"        : "text_only",
                    "visual_description" : None,
                    "content_bullets"    : [],
                    "presenter_notes"    : {
                        "transition"     : None,
                        "talking_points" : [ "Welcome everyone" ],
                        "timing_seconds" : 30,
                        "emphasis"       : None
                    }
                },
                {
                    "number"             : 2,
                    "arc_position"       : "body",
                    "type"               : "key_point",
                    "title"              : "Key Insight",
                    "visual_type"        : "diagram",
                    "visual_description" : "Flowchart: A → B → C",
                    "content_bullets"    : [ "Point 1", "Point 2", "Point 3" ],
                    "presenter_notes"    : {
                        "transition"     : "Now let's look at...",
                        "talking_points" : [ "Explain the flow", "Note the branching" ],
                        "timing_seconds" : 75,
                        "emphasis"       : "Pause at the branching point"
                    }
                }
            ]
        } )
        slides = parse_elaboration_response( valid_response )
        assert len( slides ) == 2
        assert slides[ 0 ][ "presenter_notes" ][ "timing_seconds" ] == 30
        assert slides[ 1 ][ "visual_description" ] == "Flowchart: A → B → C"
        assert len( slides[ 1 ][ "content_bullets" ] ) == 3
        print( "  ✓ Valid JSON parsed correctly" )

        # Test 4: Malformed input (D6-STRICT: now raises, was return [])
        print( "Testing malformed input..." )
        try:
            parse_elaboration_response( "not json" )
            assert False, "expected ValueError on unrecoverable input"
        except ValueError:
            pass
        print( "  ✓ Malformed input raises ValueError (fail-loud)" )

        # Test 5: Missing presenter_notes gets defaults
        print( "Testing missing presenter_notes defaults..." )
        minimal = json.dumps( { "slides": [ { "title": "Test", "number": 1 } ] } )
        slides = parse_elaboration_response( minimal )
        assert slides[ 0 ][ "presenter_notes" ][ "timing_seconds" ] == DEFAULT_TIMING_PER_SLIDE
        assert slides[ 0 ][ "presenter_notes" ][ "talking_points" ] == []
        print( "  ✓ Missing presenter_notes gets defaults" )

        # Test 6: Timing clamped
        print( "Testing timing bounds..." )
        extreme = json.dumps( { "slides": [ {
            "title": "Test", "number": 1,
            "presenter_notes": { "timing_seconds": -5 }
        } ] } )
        slides = parse_elaboration_response( extreme )
        assert slides[ 0 ][ "presenter_notes" ][ "timing_seconds" ] == MIN_TIMING_PER_SLIDE
        print( "  ✓ Negative timing clamped to minimum" )

        # Test 7: Constants
        print( "Testing constants..." )
        assert DEFAULT_TIMING_PER_SLIDE == 60
        assert MIN_TIMING_PER_SLIDE > 0
        assert MAX_TIMING_PER_SLIDE > MIN_TIMING_PER_SLIDE
        print( "  ✓ Constants valid" )

        print( "\nAll elaboration prompt smoke tests passed" )

    except Exception as e:
        print( f"\nSmoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
