#!/usr/bin/env python3
"""
Outline Generation Prompts for Presentation Generator.

Provides system prompts, prompt builders, and response parsers for the
outline generation phase (Orchestrator Phase 3: Outline).

The LLM takes narrative sections and generates a slide-by-slide outline
with assertion-style titles and visual type assignments.
"""

import json
import logging
from typing import List, Optional

from .narrative import AUDIENCE_COMPLEXITY_GUIDELINES
from .json_recovery import recover_json_object

logger = logging.getLogger( __name__ )


# =============================================================================
# Taxonomies
# =============================================================================

SLIDE_TYPES = [
    "title",       # Presentation title slide
    "hook",        # Opening hook — provocative question, surprising stat
    "agenda",      # Overview / table of contents
    "key_point",   # Core argument or claim
    "evidence",    # Data, examples, case studies
    "comparison",  # Before/after, option A vs B
    "summary",     # Recap of key takeaways
    "cta",         # Call to action, next steps
    "qa",          # Questions & discussion
]

VISUAL_TYPES = [
    "diagram",          # Architecture, flows, sequences (Mermaid)
    "code_block",       # Code snippets, configs, CLI output
    "chart",            # Data visualizations — bar, line, pie
    "screenshot",       # UI, tool output (user-supplied placeholder)
    "icon_only",        # Concept slides, transitions (emoji/icon)
    "text_only",        # Quotes, key statements, definitions
    "before_after",     # Side-by-side comparisons
    "table",            # Feature comparisons, data summaries
    "flowchart_d2",     # D2 flowcharts (Phase 9B)
    "architecture",     # D2 architecture diagrams (Phase 9B)
    "hero_image",       # AI-generated hero images (Phase 10A)
    "infographic",      # AI-generated infographics (Phase 10A)
    "title_background", # AI-generated title backgrounds (Phase 10A)
    "icon",             # AI-generated icons (Phase 10A)
    "title_video",      # Veo ambient title video (Phase 10B)
    "flow_animation",   # Veo process flow animation (Phase 10B)
    "process_video",    # Veo educational process video (Phase 10B)
]

STRUCTURAL_POSITIONS = [ "opening", "body", "closing" ]


# =============================================================================
# System Prompt
# =============================================================================

OUTLINE_SYSTEM_PROMPT = """You are an expert presentation architect specializing in narrative flow and visual storytelling. Your task is to transform a narrative analysis into a slide-by-slide outline.

## Structural Formula

Every presentation follows this structure:
- **Opening** (2-3 slides): title slide, hook, and optionally agenda
- **Body** (N slides): the core content — key points, evidence, comparisons
- **Closing** (2-3 slides): summary, call to action, Q&A

## Title Style: Assertion-Based

Every slide title must be an **assertion** — a complete thought, not a topic label.

✅ Good assertion titles:
- "Three-Layer Caching Eliminates Cold Starts"
- "Current Tools Miss 40% of Edge Cases"
- "Start With L1 — You'll See Results in a Week"

❌ Bad topic titles:
- "Caching"
- "Current Tools"
- "Next Steps"

Exception: title, agenda, and Q&A slides may use topic-style titles.

## Visual Type Taxonomy

Assign one visual type per slide from this list:

| Type | When to Use |
|------|------------|
| `diagram` | Architecture, flows, sequences, state machines |
| `code_block` | Code snippets, configs, CLI output |
| `chart` | Data, comparisons, trends (bar, line, pie) |
| `screenshot` | UI, tool output (user supplies image) |
| `icon_only` | Concept slides, transitions (minimal visual) |
| `text_only` | Quotes, key statements, definitions |
| `before_after` | Side-by-side comparisons, improvements |
| `table` | Feature comparisons, data summaries |
| `flowchart_d2` | High-quality flowcharts (D2 rendering, prettier than diagram) |
| `architecture` | System architecture diagrams (D2 containers + connections) |
| `hero_image` | AI-generated hero/splash images for impact slides |
| `infographic` | AI-generated visual summaries, information design |
| `title_background` | AI-generated ambient backgrounds for title slides |
| `icon` | AI-generated concept icons, visual accents |
| `title_video` | Cinematic ambient video for title slides (5s loop) |
| `flow_animation` | Animated process flow walkthrough (6s) |
| `process_video` | Step-by-step educational video explanation (8s) |

## Visual Rhythm Rule

**Never place more than 2 consecutive text_only slides.** Alternate between visual types to maintain audience engagement.

## Slide Type Taxonomy

Each slide has a type: title, hook, agenda, key_point, evidence, comparison, summary, cta, qa.

## Response Format

You MUST respond with valid JSON in the following format:
```json
{
    "outline": [
        {
            "number": 1,
            "arc_position": "opening",
            "type": "title",
            "title": "Assertion-style slide title",
            "visual_type": "text_only",
            "source_hint": "Which narrative section this maps to (optional)"
        }
    ],
    "total_slides": 15,
    "narrative_coherence_note": "Brief assessment of story flow"
}
```"""


# =============================================================================
# Prompt Builder
# =============================================================================

def get_outline_prompt(
    narrative_sections: list,
    slide_budget: int,
    title_style: str = "assertion",
    audience: Optional[ str ] = None,
    audience_context: Optional[ str ] = None,
    human_feedback: Optional[ str ] = None,
) -> str:
    """
    Build user message for outline generation.

    Requires:
        - narrative_sections is a list of NarrativeSection or dicts with heading, arc_position, proposed_slides
        - slide_budget is a positive integer

    Ensures:
        - Returns formatted prompt with narrative sections and budget allocation
        - Includes audience guidelines if provided
        - Appends human feedback for revisions if provided

    Args:
        narrative_sections: Narrative sections from analysis phase
        slide_budget: Total slide budget
        title_style: Title generation style (assertion or topic)
        audience: Audience level (beginner/general/expert/academic)
        audience_context: Optional free-text audience description
        human_feedback: Optional revision feedback from Gate 2

    Returns:
        str: Formatted user message for Claude
    """
    # Calculate structural allocation
    opening_count = 2
    closing_count = 3
    body_budget   = max( 1, slide_budget - opening_count - closing_count )

    # Build narrative sections list
    sections_text = ""
    total_proposed = 0
    for i, section in enumerate( narrative_sections, 1 ):
        # Support both NarrativeSection objects and dicts
        if hasattr( section, "heading" ):
            heading   = section.heading
            arc_pos   = section.arc_position.value if hasattr( section.arc_position, "value" ) else str( section.arc_position )
            proposed  = section.proposed_slides
        else:
            heading   = section.get( "heading", "(unknown)" )
            arc_pos   = section.get( "arc_position", "argument" )
            proposed  = section.get( "proposed_slides", 1 )

        total_proposed += proposed
        sections_text += f"{i}. **{heading}** — arc: {arc_pos}, proposed: {proposed} slide{'s' if proposed != 1 else ''}\n"

    # Audience guidelines
    audience_block = ""
    if audience and audience in AUDIENCE_COMPLEXITY_GUIDELINES:
        audience_block = f"\n\n## Audience\n\n{AUDIENCE_COMPLEXITY_GUIDELINES[ audience ]}"
    if audience_context:
        audience_block += f"\n\nAdditional audience context: {audience_context}"

    # Title style instruction
    title_instruction = ""
    if title_style == "topic":
        title_instruction = "\n\nNote: Use **topic-style titles** for this presentation (short labels rather than full assertions)."

    # Revision feedback
    feedback_block = ""
    if human_feedback:
        feedback_block = f"\n\n## Revision Feedback\n\nThe user reviewed a previous outline and requested changes:\n\n> {human_feedback}\n\nPlease incorporate this feedback into the new outline."

    prompt = f"""Generate a slide outline for the following narrative analysis.

## Budget Allocation

- **Total slide budget**: {slide_budget} slides
- **Opening**: {opening_count} slides (title + hook)
- **Body**: {body_budget} slides (content)
- **Closing**: {closing_count} slides (summary + CTA + Q&A)
- **Narrative analysis proposed**: {total_proposed} slides across {len( narrative_sections )} sections
{audience_block}
{title_instruction}

## Narrative Sections

{sections_text}

## Instructions

1. Create exactly {slide_budget} slides following the structural formula
2. Map narrative sections to body slides, respecting their proposed counts where possible
3. Use assertion-style titles (complete thoughts, not topic labels)
4. Assign visual types that alternate appropriately — never 3+ consecutive text_only
5. Include source_hint to trace each slide back to its narrative section
{feedback_block}

Generate the slide outline as JSON."""

    return prompt


# =============================================================================
# Response Parser
# =============================================================================

def parse_outline_response( response_content: str ) -> List[ dict ]:
    """
    Parse Claude's outline generation response into slide outline dicts.

    Handles markdown code block wrapping and gracefully falls back on errors.

    Requires:
        - response_content is a non-empty string

    Ensures:
        - Returns list of outline dicts with keys: number, arc_position, type,
          title, visual_type, source_hint
        - Returns empty list on parse failure

    Args:
        response_content: Raw response from Claude API

    Returns:
        List of outline dicts, or empty list on error
    """
    # D6-STRICT: recover the JSON object from chatty bounded-CC output, then
    # fail-loud on unrecoverable / missing / empty structured content.
    parsed = recover_json_object( response_content )
    if parsed is None:
        logger.error( "Failed to recover outline JSON" )
        logger.debug( f"Raw content (first 500 chars): {response_content[ :500 ]}" )
        raise ValueError( "Outline response did not contain a recoverable JSON object" )

    # Extract outline list (STRICT: missing / empty / non-list is a real defect)
    outline = parsed.get( "outline", [] ) if isinstance( parsed, dict ) else []
    if not isinstance( outline, list ) or not outline:
        logger.error( f"Outline 'outline' missing/empty/not-a-list: {type( outline )}" )
        raise ValueError( "Outline generation returned no usable entries" )

    # Validate each entry
    validated = []
    for entry in outline:
        if not isinstance( entry, dict ):
            continue

        validated_entry = {
            "number"       : entry.get( "number", len( validated ) + 1 ),
            "arc_position" : entry.get( "arc_position", "body" ),
            "type"         : entry.get( "type", "key_point" ),
            "title"        : entry.get( "title", "(untitled)" ),
            "visual_type"  : entry.get( "visual_type", "text_only" ),
            "source_hint"  : entry.get( "source_hint", None ),
        }

        # Validate arc_position
        if validated_entry[ "arc_position" ] not in STRUCTURAL_POSITIONS:
            logger.warning( f"Unknown arc position '{validated_entry[ 'arc_position' ]}', defaulting to 'body'" )
            validated_entry[ "arc_position" ] = "body"

        # Validate visual_type
        if validated_entry[ "visual_type" ] not in VISUAL_TYPES:
            logger.warning( f"Unknown visual type '{validated_entry[ 'visual_type' ]}', defaulting to 'text_only'" )
            validated_entry[ "visual_type" ] = "text_only"

        # Validate slide type
        if validated_entry[ "type" ] not in SLIDE_TYPES:
            logger.warning( f"Unknown slide type '{validated_entry[ 'type' ]}', defaulting to 'key_point'" )
            validated_entry[ "type" ] = "key_point"

        # Ensure number is int
        try:
            validated_entry[ "number" ] = int( validated_entry[ "number" ] )
        except ( ValueError, TypeError ):
            validated_entry[ "number" ] = len( validated ) + 1

        validated.append( validated_entry )

    return validated


def extract_outline_metadata( response_content: str ) -> dict:
    """
    Extract top-level metadata from outline generation response.

    Args:
        response_content: Raw response from Claude API

    Returns:
        dict with total_slides and narrative_coherence_note, or empty dict
    """
    content = response_content.strip()
    if content.startswith( "```json" ):
        content = content[ 7: ]
    elif content.startswith( "```" ):
        content = content[ 3: ]
    if content.endswith( "```" ):
        content = content[ :-3 ]

    try:
        parsed = json.loads( content.strip() )
        return {
            "total_slides"             : parsed.get( "total_slides", 0 ),
            "narrative_coherence_note" : parsed.get( "narrative_coherence_note", "" ),
        }
    except json.JSONDecodeError:
        return {}


# =============================================================================
# Smoke Test
# =============================================================================

def quick_smoke_test():
    """Quick smoke test for outline prompts module."""
    import cosa.utils.util as cu

    cu.print_banner( "Outline Prompts Smoke Test", prepend_nl=True )

    try:
        # Test 1: System prompt exists and has key content
        print( "Testing OUTLINE_SYSTEM_PROMPT..." )
        assert len( OUTLINE_SYSTEM_PROMPT ) > 100
        assert "assertion" in OUTLINE_SYSTEM_PROMPT.lower()
        assert "diagram" in OUTLINE_SYSTEM_PROMPT
        assert "text_only" in OUTLINE_SYSTEM_PROMPT
        print( "  ✓ System prompt has expected content" )

        # Test 2: Prompt builder
        print( "Testing get_outline_prompt..." )
        prompt = get_outline_prompt(
            narrative_sections = [
                { "heading": "Introduction", "arc_position": "setup", "proposed_slides": 2 },
                { "heading": "Methods", "arc_position": "argument", "proposed_slides": 3 },
            ],
            slide_budget     = 15,
            audience         = "expert",
            audience_context = "ML engineers",
        )
        assert "15 slides" in prompt
        assert "Introduction" in prompt
        assert "Methods" in prompt
        assert "expertise" in prompt.lower() or "expert" in prompt.lower()
        print( "  ✓ Prompt generated correctly" )

        # Test 3: Parse valid response
        print( "Testing parse_outline_response with valid JSON..." )
        valid_response = json.dumps( {
            "outline": [
                { "number": 1, "arc_position": "opening", "type": "title", "title": "Test Talk", "visual_type": "text_only" },
                { "number": 2, "arc_position": "opening", "type": "hook", "title": "Did You Know?", "visual_type": "chart" },
                { "number": 3, "arc_position": "body", "type": "key_point", "title": "Key Insight", "visual_type": "diagram" },
            ],
            "total_slides": 3,
            "narrative_coherence_note": "Good flow"
        } )
        outline = parse_outline_response( valid_response )
        assert len( outline ) == 3
        assert outline[ 0 ][ "arc_position" ] == "opening"
        assert outline[ 2 ][ "visual_type" ] == "diagram"
        print( "  ✓ Valid JSON parsed correctly" )

        # Test 4: Parse markdown-wrapped response
        print( "Testing markdown-wrapped JSON..." )
        wrapped = f"```json\n{valid_response}\n```"
        outline = parse_outline_response( wrapped )
        assert len( outline ) == 3
        print( "  ✓ Markdown-wrapped JSON parsed correctly" )

        # Test 5: Malformed input
        print( "Testing malformed input..." )
        outline = parse_outline_response( "not json" )
        assert outline == []
        print( "  ✓ Malformed input returns empty list" )

        # Test 6: Invalid arc position defaults
        print( "Testing invalid arc_position fallback..." )
        bad = json.dumps( { "outline": [ { "arc_position": "bogus", "title": "Test" } ] } )
        outline = parse_outline_response( bad )
        assert outline[ 0 ][ "arc_position" ] == "body"
        print( "  ✓ Invalid arc_position defaults to 'body'" )

        # Test 7: Constants
        print( "Testing constants..." )
        assert len( VISUAL_TYPES ) == 17
        assert len( SLIDE_TYPES ) == 9
        assert len( STRUCTURAL_POSITIONS ) == 3
        print( "  ✓ Constants have expected counts" )

        print( "\nAll outline prompt smoke tests passed" )

    except Exception as e:
        print( f"\nSmoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
