#!/usr/bin/env python3
"""
Narrative Analysis Prompts for Presentation Generator.

Provides system prompts, prompt builders, and response parsers for the
narrative extraction phase (Orchestrator Phase 2: Analyze).

The LLM analyzes a source document and classifies its sections into
narrative arc positions, proposing a slide allocation for each.
"""

import json
import logging
from typing import List, Optional

from .json_recovery import recover_json_object

logger = logging.getLogger( __name__ )


# =============================================================================
# Arc Position Taxonomy
# =============================================================================

ARC_POSITIONS = [
    "setup",       # Problem statement, context, background
    "argument",    # Core claims, main points
    "evidence",    # Data, examples, case studies supporting arguments
    "transition",  # Bridges between major sections
    "conclusion",  # Summary, key takeaways
    "cta",         # Call to action, next steps, future work
]


# =============================================================================
# Audience Complexity Guidelines
# =============================================================================

AUDIENCE_COMPLEXITY_GUIDELINES = {
    "beginner" : (
        "The audience is new to this topic. "
        "Prioritize clarity over completeness. "
        "Allocate more slides to setup/context. "
        "Simplify technical details. "
        "Use analogies where possible."
    ),
    "general" : (
        "The audience has general knowledge but is not specialized. "
        "Balance context with substance. "
        "Include enough background to follow the argument. "
        "Keep technical depth moderate."
    ),
    "expert" : (
        "The audience has deep domain expertise. "
        "Minimize background — jump to the substance quickly. "
        "Allocate more slides to evidence and technical details. "
        "Use precise terminology without explanation."
    ),
    "academic" : (
        "The audience is academic/research-oriented. "
        "Focus on methodology, rigor, and citations. "
        "Allocate slides for literature context and methodology. "
        "Include limitations and future work."
    ),
}


# =============================================================================
# System Prompt
# =============================================================================

NARRATIVE_ANALYSIS_SYSTEM_PROMPT = """You are an expert presentation architect. Your task is to analyze a source document and decompose its narrative structure into sections suitable for a slide presentation.

For each section of the document, you must:
1. Identify its role in the narrative arc
2. Classify it into one of these arc positions: setup, argument, evidence, transition, conclusion, cta
3. Propose how many slides this section deserves based on content density
4. Extract the key points that should appear on slides

Arc position definitions:
- **setup**: Problem statement, context, background, motivation
- **argument**: Core claims, main points, thesis statements
- **evidence**: Data, examples, case studies, proof points supporting arguments
- **transition**: Bridges between major sections (usually 0-1 slides)
- **conclusion**: Summary, key takeaways, synthesis
- **cta**: Call to action, next steps, future work, recommendations

Guidelines:
- The total proposed slide count should approximately match the target slide budget
- Dense technical content may need more slides; transitions may need fewer
- Every section must have at least 1 key point
- Sections with code, data, or complex diagrams typically need their own slide

You MUST respond with valid JSON in the following format:
```json
{
    "sections": [
        {
            "heading": "Section heading from the document",
            "content_summary": "1-2 sentence summary of this section",
            "arc_position": "one of: setup, argument, evidence, transition, conclusion, cta",
            "proposed_slide_count": 2,
            "key_points": [
                "Key point 1 that should appear on a slide",
                "Key point 2"
            ]
        }
    ],
    "total_proposed_slides": 15,
    "narrative_assessment": "1-2 sentence assessment of the document's overall narrative strength"
}
```"""


# =============================================================================
# Prompt Builder
# =============================================================================

def get_narrative_analysis_prompt(
    source_content: str,
    raw_sections: list,
    target_duration: int,
    slides_per_minute: float,
    audience: Optional[ str ] = None,
    audience_context: Optional[ str ] = None,
) -> str:
    """
    Build user message for narrative analysis.

    Requires:
        - source_content is a non-empty string
        - raw_sections is a list of (heading, body, level) tuples from ingest
        - target_duration > 0
        - slides_per_minute > 0

    Ensures:
        - Returns formatted prompt with all context for Claude
        - Includes slide budget calculation
        - Includes audience guidelines if provided

    Args:
        source_content: Full source document text
        raw_sections: Pre-parsed sections from ingest phase
        target_duration: Target presentation duration in minutes
        slides_per_minute: Slides-per-minute pacing heuristic
        audience: Audience level (beginner/general/expert/academic)
        audience_context: Optional free-text audience description

    Returns:
        str: Formatted user message for Claude
    """
    # Calculate slide budget
    slide_budget = int( target_duration * slides_per_minute )
    # Add structural slides (title, agenda, Q&A)
    structural_slides = 3
    content_slide_budget = slide_budget - structural_slides

    # Build section summary for pre-parsed structure
    section_summary = ""
    if raw_sections:
        section_summary = "\n\n## Pre-Parsed Document Structure\n\n"
        section_summary += "The document has been pre-parsed into these sections:\n\n"
        for i, ( heading, body, level ) in enumerate( raw_sections, 1 ):
            word_count = len( body.split() ) if body else 0
            level_indicator = f"H{level}" if level > 0 else "text"
            section_summary += f"{i}. **{heading}** ({level_indicator}, {word_count} words)\n"

    # Build audience context
    audience_block = ""
    if audience and audience in AUDIENCE_COMPLEXITY_GUIDELINES:
        audience_block = f"\n\n## Audience\n\n{AUDIENCE_COMPLEXITY_GUIDELINES[ audience ]}"
    if audience_context:
        audience_block += f"\n\nAdditional audience context: {audience_context}"

    # Truncate source content if very long (preserve first 30k chars)
    truncated = source_content
    truncation_note = ""
    if len( source_content ) > 30000:
        truncated = source_content[ :30000 ]
        truncation_note = "\n\n[NOTE: Document was truncated to 30,000 characters for analysis. Focus on the provided content.]"

    prompt = f"""Analyze the following document for presentation conversion.

## Target Parameters

- **Target duration**: {target_duration} minutes
- **Slides per minute**: {slides_per_minute}
- **Total slide budget**: {slide_budget} slides ({structural_slides} structural + {content_slide_budget} content)
- **Content slide budget**: {content_slide_budget} slides (for body content only)
{audience_block}
{section_summary}

## Source Document

```
{truncated}
```
{truncation_note}

Analyze this document and return a JSON object classifying each section into narrative arc positions with proposed slide counts. The total proposed slides for content sections should be close to {content_slide_budget}."""

    return prompt


# =============================================================================
# Response Parser
# =============================================================================

def parse_analysis_response( response_content: str ) -> List[ dict ]:
    """
    Parse Claude's narrative analysis response into section dicts.

    Handles markdown code block wrapping (```json ... ```) and
    gracefully falls back on parse errors.

    Requires:
        - response_content is a non-empty string

    Ensures:
        - Returns a non-empty list of section dicts with keys: heading,
          content_summary, arc_position, proposed_slide_count, key_points

    Raises:
        - ValueError (D6-STRICT fail-loud) when the response has no recoverable
          JSON object, the "sections" value is missing / not a list / empty, or
          every entry is a non-dict (zero usable sections). Slide data feeds pptx
          rendering downstream, so an empty/degenerate result is a real defect.

    Args:
        response_content: Raw response from Claude API

    Returns:
        List of section dicts (always non-empty on return)
    """
    # D6-STRICT: robustly recover the JSON object from chatty bounded-CC output,
    # then fail-loud on unrecoverable / missing / empty structured content
    # (slide data is consumed downstream by pptx rendering — an empty deck is a
    # real defect, not cosmetic drift).
    parsed = recover_json_object( response_content )
    if parsed is None:
        logger.error( "Failed to recover narrative analysis JSON" )
        logger.debug( f"Raw content (first 500 chars): {response_content[ :500 ]}" )
        raise ValueError( "Narrative analysis response did not contain a recoverable JSON object" )

    # Extract sections list (STRICT: missing / empty / non-list is a real defect)
    sections = parsed.get( "sections", [] ) if isinstance( parsed, dict ) else []
    if not isinstance( sections, list ) or not sections:
        logger.error( f"Narrative analysis 'sections' missing/empty/not-a-list: {type( sections )}" )
        raise ValueError( "Narrative analysis returned no usable sections" )

    # Validate each section has required keys
    validated = []
    for section in sections:
        if not isinstance( section, dict ):
            continue

        validated_section = {
            "heading"              : section.get( "heading", "(unknown)" ),
            "content_summary"      : section.get( "content_summary", "" ),
            "arc_position"         : section.get( "arc_position", "argument" ),
            "proposed_slide_count" : section.get( "proposed_slide_count", 1 ),
            "key_points"           : section.get( "key_points", [] ),
        }

        # Validate arc_position
        if validated_section[ "arc_position" ] not in ARC_POSITIONS:
            logger.warning( f"Unknown arc position '{validated_section[ 'arc_position' ]}', defaulting to 'argument'" )
            validated_section[ "arc_position" ] = "argument"

        # Ensure proposed_slide_count is int >= 0
        try:
            validated_section[ "proposed_slide_count" ] = max( 0, int( validated_section[ "proposed_slide_count" ] ) )
        except ( ValueError, TypeError ):
            validated_section[ "proposed_slide_count" ] = 1

        validated.append( validated_section )

    # D6-STRICT: a non-empty list whose entries are ALL non-dicts (e.g.
    # {"sections": [1, 2, 3]}) yields zero usable sections — a real defect.
    if not validated:
        logger.error( "Narrative analysis 'sections' contained no usable dict entries" )
        raise ValueError( "Narrative analysis returned no usable sections" )

    return validated


def extract_narrative_metadata( response_content: str ) -> dict:
    """
    Extract top-level metadata from narrative analysis response.

    Args:
        response_content: Raw response from Claude API

    Returns:
        dict with total_proposed_slides and narrative_assessment, or empty dict
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
            "total_proposed_slides" : parsed.get( "total_proposed_slides", 0 ),
            "narrative_assessment"  : parsed.get( "narrative_assessment", "" ),
        }
    except json.JSONDecodeError:
        return {}


# =============================================================================
# Smoke Test
# =============================================================================

def quick_smoke_test():
    """Quick smoke test for narrative prompts module."""
    import cosa.utils.util as cu

    cu.print_banner( "Narrative Prompts Smoke Test", prepend_nl=True )

    try:
        # Test 1: Prompt generation
        print( "Testing get_narrative_analysis_prompt..." )
        prompt = get_narrative_analysis_prompt(
            source_content = "# Title\n\nSome content about AI.\n\n## Methods\n\nWe used transformers.",
            raw_sections   = [ ( "Title", "Some content about AI.", 1 ), ( "Methods", "We used transformers.", 2 ) ],
            target_duration   = 15,
            slides_per_minute = 1.0,
            audience          = "expert",
            audience_context  = "ML engineers"
        )
        assert "15 minutes" in prompt
        assert "expert" in prompt.lower() or "expertise" in prompt.lower()
        assert "ML engineers" in prompt
        print( "  ✓ Prompt generated correctly" )

        # Test 2: Parse valid response
        print( "Testing parse_analysis_response with valid JSON..." )
        valid_response = json.dumps( {
            "sections": [
                {
                    "heading"              : "Introduction",
                    "content_summary"      : "Sets up the problem",
                    "arc_position"         : "setup",
                    "proposed_slide_count" : 2,
                    "key_points"           : [ "Problem X exists", "Current solutions fail" ]
                },
                {
                    "heading"              : "Our Approach",
                    "content_summary"      : "Describes the solution",
                    "arc_position"         : "argument",
                    "proposed_slide_count" : 3,
                    "key_points"           : [ "We built Y", "Y solves X" ]
                }
            ],
            "total_proposed_slides" : 5,
            "narrative_assessment"  : "Strong argumentative structure"
        } )
        sections = parse_analysis_response( valid_response )
        assert len( sections ) == 2
        assert sections[ 0 ][ "arc_position" ] == "setup"
        assert sections[ 1 ][ "proposed_slide_count" ] == 3
        print( "  ✓ Valid JSON parsed correctly" )

        # Test 3: Parse markdown-wrapped response
        print( "Testing parse_analysis_response with markdown wrapping..." )
        wrapped = f"```json\n{valid_response}\n```"
        sections = parse_analysis_response( wrapped )
        assert len( sections ) == 2
        print( "  ✓ Markdown-wrapped JSON parsed correctly" )

        # Test 4: Parse malformed response (D6-STRICT: now raises, was return [])
        print( "Testing parse_analysis_response with malformed input..." )
        try:
            parse_analysis_response( "not json at all" )
            assert False, "expected ValueError on unrecoverable input"
        except ValueError:
            pass
        print( "  ✓ Malformed input raises ValueError (fail-loud)" )

        # Test 5: Invalid arc position defaults to argument
        print( "Testing invalid arc position fallback..." )
        bad_arc = json.dumps( { "sections": [ { "arc_position": "bogus", "heading": "Test" } ] } )
        sections = parse_analysis_response( bad_arc )
        assert len( sections ) == 1
        assert sections[ 0 ][ "arc_position" ] == "argument"
        print( "  ✓ Invalid arc position defaults to 'argument'" )

        # Test 6: Metadata extraction
        print( "Testing extract_narrative_metadata..." )
        metadata = extract_narrative_metadata( valid_response )
        assert metadata[ "total_proposed_slides" ] == 5
        assert "Strong" in metadata[ "narrative_assessment" ]
        print( "  ✓ Metadata extracted correctly" )

        print( "\nAll narrative prompt smoke tests passed" )

    except Exception as e:
        print( f"\nSmoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
