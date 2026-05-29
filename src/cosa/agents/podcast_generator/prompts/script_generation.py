#!/usr/bin/env python3
"""
Script Generation Prompts for COSA Podcast Generator Agent.

Contains system prompts and templates for generating podcast dialogue
from research documents. Designed for the "Dynamic Duo" format with
two hosts having complementary roles.
"""

import json
import re
from typing import Optional

from ..config import HostPersonality, LANGUAGE_NAMES


# =============================================================================
# Audience-Specific Dialogue Guidelines
# =============================================================================

AUDIENCE_DIALOGUE_GUIDELINES = {
    "beginner": """
## Target Audience: Beginner

### Dialogue Guidelines for Beginner Audience

For BEGINNER listeners:
- Define ALL technical terms when first introduced in dialogue
- Use everyday analogies and comparisons to familiar concepts
- Curious host should ask the "obvious" questions listeners would have
- Expert host should explain step-by-step, never assuming prior knowledge
- Include "why this matters" moments in the conversation
- Keep sentence structures simple and direct
- Summarize key points periodically throughout the episode
""",

    "general": """
## Target Audience: General

### Dialogue Guidelines for General Audience

For GENERAL listeners:
- Define specialized terms but assume general tech/science literacy
- Balance accessibility with depth — don't over-explain basics
- Curious host should ask practical "so what?" questions
- Expert host should use real-world examples and clear explanations
- Include trade-offs and nuance without going too deep
- Keep the conversation relatable and grounded in practical implications
""",

    "expert": """
## Target Audience: Expert

### Dialogue Guidelines for Expert Audience

For EXPERT listeners:
- Skip introductory explanations — assume strong domain knowledge
- Focus on: novel insights, trade-offs, edge cases, contrarian viewpoints
- Curious host should ask about implementation details and gotchas
- Expert host should compare approaches and highlight what's different/better
- Include production-level concerns and real-world failure modes
- Use precise technical language without over-explaining standard terminology
""",

    "academic": """
## Target Audience: Academic/Researcher

### Dialogue Guidelines for Academic Audience

For ACADEMIC listeners:
- Use precise academic terminology and methodology language
- Focus on: research gaps, conflicting findings, experimental design
- Curious host should ask about statistical significance and methodology
- Expert host should cite specific papers and research findings
- Include limitations, replication status, and open research questions
- Discuss theoretical foundations and their implications for future work
"""
}


# =============================================================================
# System Prompts
# =============================================================================

CONTENT_ANALYSIS_SYSTEM_PROMPT = """You are a content analyst preparing research material for podcast production.

Your task is to analyze a research document and extract:
1. The main topic and key subtopics
2. Interesting facts that would engage listeners
3. Discussion questions that would make good conversation
4. Analogies that could make complex concepts accessible
5. The appropriate complexity level for the content

Output your analysis as JSON with this structure:
{
    "main_topic": "string",
    "key_subtopics": ["string", ...],
    "interesting_facts": ["string", ...],
    "discussion_questions": ["string", ...],
    "analogies_suggested": ["string", ...],
    "target_audience": "string",
    "complexity_level": "beginner|intermediate|advanced",
    "estimated_coverage_minutes": number
}

Focus on extracting information that will create engaging dialogue between two hosts."""


SCRIPT_GENERATION_SYSTEM_PROMPT = """You are a podcast script writer creating dialogue for a "Dynamic Duo" format show.

The show features two hosts with complementary roles:
- One host asks questions and expresses curiosity (the "curious" role)
- One host explains concepts and provides expertise (the "expert" role)

Your task is to transform research content into natural, engaging conversation.

SCRIPT FORMAT:
Use this minimalist markdown format for each dialogue segment:

**[Host Name - Role]**: Dialogue text with *[prosody annotations]* as needed.

PROSODY ANNOTATIONS:
Embed these markers in the text where appropriate:
- *[pause]* - Brief pause for effect
- *[long_pause]* - Longer pause (2-3 seconds)
- *[laughs]* or *[chuckles]* - Light laughter
- *[whispers]* - Lower volume, conspiratorial tone
- *[excited]* - Higher energy, faster pace
- *[thoughtful]* - Slower, contemplative
- *[emphasis]* - Stress on next few words
- *[questioning]* - Upward inflection

DIALOGUE GUIDELINES:
1. Make conversation feel natural, not scripted
2. Curious host should ask genuine questions listeners might have
3. Expert host should use analogies and concrete examples
4. Include moments of humor and human connection
5. Build concepts progressively - don't front-load complexity
6. Have hosts reference each other by name occasionally
7. Include brief tangents that circle back to main points
8. End segments with hooks that lead to next topic

OUTPUT FORMAT:
Return a JSON object with this structure:
{
    "title": "Episode title",
    "segments": [
        {
            "speaker": "Host Name",
            "role": "curious|expert",
            "text": "Dialogue with *[prosody]* markers",
            "topic_reference": "which topic this covers"
        }
    ],
    "key_topics": ["topic1", "topic2", ...],
    "estimated_duration_minutes": number
}"""


# =============================================================================
# Prompt Templates
# =============================================================================

def get_content_analysis_prompt(
    research_content: str,
    max_topics: int = 5,
    audience: Optional[ str ] = None,
    audience_context: Optional[ str ] = None
) -> str:
    """
    Generate prompt for content analysis phase.

    Requires:
        - research_content is a non-empty string
        - max_topics is a positive integer

    Ensures:
        - Returns prompt requesting structured JSON analysis
        - Includes audience-specific analysis guidance if provided

    Args:
        research_content: The full text of the research document
        max_topics: Maximum number of subtopics to extract
        audience: Target audience level (beginner/general/expert/academic)
        audience_context: Custom audience description

    Returns:
        str: Complete prompt for content analysis
    """
    # Truncate if very long to stay within context limits
    content_preview = research_content[ :50000 ] if len( research_content ) > 50000 else research_content

    audience_instruction = ""
    if audience:
        audience_guidelines = AUDIENCE_DIALOGUE_GUIDELINES.get( audience, "" )
        if audience_guidelines:
            audience_instruction += f"\n{audience_guidelines}\n"
    if audience_context:
        audience_instruction += f"\n**Additional Audience Context**: {audience_context}\n"

    return f"""Analyze this research document for podcast conversion.

Extract up to {max_topics} key subtopics and the most engaging discussion points.
{audience_instruction}
RESEARCH DOCUMENT:
---
{content_preview}
---

Provide your analysis as JSON."""


def get_script_generation_prompt(
    content_analysis        : dict,
    research_content        : str,
    host_a_personality      : HostPersonality,
    host_b_personality      : HostPersonality,
    target_duration_minutes : int = 10,
    min_exchanges           : int = 8,
    max_exchanges           : int = 20,
    target_language         : str = "en",
    audience                : Optional[ str ] = None,
    audience_context        : Optional[ str ] = None,
) -> str:
    """
    Generate prompt for script generation phase.

    Requires:
        - content_analysis contains analyzed topics and facts
        - host personalities are configured
        - target_duration is positive
        - target_language is a valid ISO language code

    Ensures:
        - Returns prompt with full context for dialogue generation
        - For non-English languages, includes instruction for native generation
        - Includes audience-specific dialogue guidelines if provided

    Args:
        content_analysis: Dictionary from analysis phase
        research_content: Original research for reference
        host_a_personality: Curious host configuration
        host_b_personality: Expert host configuration
        target_duration_minutes: Target podcast length
        min_exchanges: Minimum number of dialogue exchanges
        max_exchanges: Maximum number of dialogue exchanges
        target_language: ISO language code (e.g., "en", "es-MX")
        audience: Target audience level (beginner/general/expert/academic)
        audience_context: Custom audience description

    Returns:
        str: Complete prompt for script generation
    """
    # Truncate research for context window management
    research_preview = research_content[ :30000 ] if len( research_content ) > 30000 else research_content

    # Build host descriptions
    host_a_desc = host_a_personality.to_prompt_description()
    host_b_desc = host_b_personality.to_prompt_description()

    # Format analysis
    analysis_str = json.dumps( content_analysis, indent=2 )

    # Build language instruction for non-English
    language_instruction = ""
    if target_language != "en":
        language_name = LANGUAGE_NAMES.get( target_language, target_language )
        language_instruction = f"""
IMPORTANT - LANGUAGE REQUIREMENT:
Generate this podcast script in {language_name}.
- Write natural, conversational dialogue as native speakers would speak
- Preserve all prosody markers (*[pause]*, *[excited]*, etc.) UNCHANGED in English
- Keep host names (Nora, Quentin) UNCHANGED
- Adapt idioms, examples, and cultural references to be appropriate for {language_name} speakers
- Do NOT translate literally - create authentic, natural-sounding dialogue

"""

    # Build audience instruction block
    audience_instruction = ""
    if audience:
        audience_guidelines = AUDIENCE_DIALOGUE_GUIDELINES.get( audience, "" )
        if audience_guidelines:
            audience_instruction += f"\n{audience_guidelines}\n"
    if audience_context:
        audience_instruction += f"\n**Additional Audience Context**: {audience_context}\n"

    return f"""Create a podcast script based on the following analysis and source material.
{language_instruction}
TARGET SPECIFICATIONS:
- Duration: approximately {target_duration_minutes} minutes
- Exchanges: {min_exchanges}-{max_exchanges} dialogue turns
- Format: Natural conversation between two hosts
{audience_instruction}
HOST A (CURIOUS ROLE):
{host_a_desc}

HOST B (EXPERT ROLE):
{host_b_desc}

CONTENT ANALYSIS:
{analysis_str}

SOURCE RESEARCH (for reference):
---
{research_preview}
---

INSTRUCTIONS:
1. Start with an engaging hook that draws listeners in
2. Cover all key subtopics from the analysis
3. Include the interesting facts naturally in dialogue
4. Use suggested analogies where appropriate
5. Build complexity progressively
6. End with a memorable conclusion that summarizes key insights
7. Follow the audience-specific dialogue guidelines above for tone and depth

Generate the complete script as JSON."""


def get_script_revision_prompt(
    current_script: str,
    feedback: str,
    revision_number: int = 1
) -> str:
    """
    Generate prompt for script revision based on feedback.

    Requires:
        - current_script is non-empty
        - feedback contains specific change requests

    Ensures:
        - Returns prompt requesting targeted revisions

    Args:
        current_script: The current script markdown
        feedback: User feedback on changes needed
        revision_number: Which revision iteration this is

    Returns:
        str: Prompt for revision
    """
    return f"""Revise the podcast script based on user feedback.

This is revision #{revision_number}.

CURRENT SCRIPT:
---
{current_script}
---

USER FEEDBACK:
{feedback}

INSTRUCTIONS:
1. Address all points in the feedback
2. Maintain the same overall structure unless changes are requested
3. Keep prosody annotations where appropriate
4. Ensure the revised script still flows naturally

Return the revised script in the same JSON format."""


# =============================================================================
# Response Parsers
# =============================================================================

def parse_analysis_response( response_content: str ) -> dict:
    """
    Parse the content analysis response from Claude.

    Requires:
        - response_content contains JSON (possibly with markdown)

    Ensures:
        - Returns dictionary with analysis fields
        - Returns default structure if parsing fails

    Args:
        response_content: Raw response from Claude API

    Returns:
        dict: Parsed content analysis
    """
    # Clean up markdown code blocks if present
    content = response_content.strip()
    if content.startswith( "```json" ):
        content = content[ 7: ]
    if content.startswith( "```" ):
        content = content[ 3: ]
    if content.endswith( "```" ):
        content = content[ :-3 ]

    try:
        return json.loads( content.strip() )
    except json.JSONDecodeError:
        # Return default structure if parsing fails
        return {
            "main_topic"              : "Unknown Topic",
            "key_subtopics"           : [],
            "interesting_facts"       : [],
            "discussion_questions"    : [],
            "analogies_suggested"     : [],
            "target_audience"         : "general audience",
            "complexity_level"        : "intermediate",
            "estimated_coverage_minutes" : 10,
        }


def parse_script_response( response_content: str ) -> dict:
    """
    Parse the script generation response from Claude.

    Requires:
        - response_content contains JSON script

    Ensures:
        - Returns dictionary with title, segments, key_topics
        - Returns default structure if parsing fails

    Args:
        response_content: Raw response from Claude API

    Returns:
        dict: Parsed script data
    """
    # Clean up markdown code blocks
    content = response_content.strip()
    if content.startswith( "```json" ):
        content = content[ 7: ]
    if content.startswith( "```" ):
        content = content[ 3: ]
    if content.endswith( "```" ):
        content = content[ :-3 ]

    try:
        parsed = json.loads( content.strip() )

        # Validate required fields
        if "segments" not in parsed:
            parsed[ "segments" ] = []
        if "title" not in parsed:
            parsed[ "title" ] = "Untitled Podcast"

        return parsed

    except json.JSONDecodeError:
        # Return default structure if parsing fails
        return {
            "title"                      : "Untitled Podcast",
            "segments"                   : [],
            "key_topics"                 : [],
            "estimated_duration_minutes" : 0,
        }


def extract_prosody_from_text( text: str ) -> tuple[ str, list[ str ] ]:
    """
    Extract prosody annotations from dialogue text.

    Finds all *[annotation]* patterns and returns clean text
    plus list of annotations.

    Requires:
        - text is a string

    Ensures:
        - Returns tuple of (clean_text, annotations_list)
        - Annotations are normalized to lowercase

    Args:
        text: Dialogue text with embedded annotations

    Returns:
        tuple: (clean_text, list_of_annotations)
    """
    # Pattern matches *[anything]*
    pattern = r'\*\[([^\]]+)\]\*'

    annotations = []
    for match in re.finditer( pattern, text ):
        annotation = match.group( 1 ).lower().strip()
        annotations.append( annotation )

    # Remove annotations from text for clean version
    clean_text = re.sub( pattern, '', text ).strip()
    # Clean up extra whitespace
    clean_text = re.sub( r'\s+', ' ', clean_text )

    return clean_text, annotations


def quick_smoke_test():
    """Quick smoke test for script generation prompts."""
    import cosa.utils.util as cu

    cu.print_banner( "Script Generation Prompts Smoke Test", prepend_nl=True )

    try:
        # Test 1: Content analysis prompt
        print( "Testing content analysis prompt generation..." )
        prompt = get_content_analysis_prompt(
            research_content = "This is sample research content about quantum computing.",
            max_topics       = 3,
        )
        assert "quantum computing" in prompt
        assert "JSON" in prompt
        print( "✓ Content analysis prompt generated" )

        # Test 2: Script generation prompt
        print( "Testing script generation prompt..." )
        from ..config import DEFAULT_CURIOUS_HOST, DEFAULT_EXPERT_HOST

        script_prompt = get_script_generation_prompt(
            content_analysis  = { "main_topic": "Quantum", "key_subtopics": [ "qubits" ] },
            research_content  = "Research content here.",
            host_a_personality = DEFAULT_CURIOUS_HOST,
            host_b_personality = DEFAULT_EXPERT_HOST,
            target_duration_minutes = 10,
        )
        assert "Nora" in script_prompt  # Default curious host
        assert "Quentin" in script_prompt  # Default expert host
        assert "10 minutes" in script_prompt
        print( "✓ Script generation prompt generated" )

        # Test 2b: Script generation prompt with Spanish
        print( "Testing script generation prompt with Spanish..." )
        spanish_prompt = get_script_generation_prompt(
            content_analysis  = { "main_topic": "Quantum", "key_subtopics": [ "qubits" ] },
            research_content  = "Research content here.",
            host_a_personality = DEFAULT_CURIOUS_HOST,
            host_b_personality = DEFAULT_EXPERT_HOST,
            target_duration_minutes = 10,
            target_language   = "es-MX",
        )
        assert "Mexican Spanish" in spanish_prompt
        assert "LANGUAGE REQUIREMENT" in spanish_prompt
        assert "Preserve all prosody markers" in spanish_prompt
        assert "Keep host names" in spanish_prompt
        print( "✓ Spanish script prompt includes language instruction" )

        # Test English prompt doesn't have language instruction
        english_prompt = get_script_generation_prompt(
            content_analysis  = { "main_topic": "Test", "key_subtopics": [] },
            research_content  = "Test.",
            host_a_personality = DEFAULT_CURIOUS_HOST,
            host_b_personality = DEFAULT_EXPERT_HOST,
            target_language   = "en",
        )
        assert "LANGUAGE REQUIREMENT" not in english_prompt
        print( "✓ English prompt has no language instruction" )

        # Test 3: Revision prompt
        print( "Testing revision prompt..." )
        revision_prompt = get_script_revision_prompt(
            current_script  = "**[Nora]**: Hello!",
            feedback        = "Make it more energetic",
            revision_number = 1,
        )
        assert "revision #1" in revision_prompt
        assert "more energetic" in revision_prompt
        print( "✓ Revision prompt generated" )

        # Test 4: Parse analysis response
        print( "Testing analysis response parsing..." )
        json_response = '{"main_topic": "AI", "key_subtopics": ["ML", "DL"], "complexity_level": "advanced"}'
        parsed = parse_analysis_response( json_response )
        assert parsed[ "main_topic" ] == "AI"
        assert "ML" in parsed[ "key_subtopics" ]

        # Test with markdown wrapper
        markdown_response = '```json\n{"main_topic": "Test"}\n```'
        parsed_md = parse_analysis_response( markdown_response )
        assert parsed_md[ "main_topic" ] == "Test"
        print( "✓ Analysis response parsing works" )

        # Test 5: Parse script response
        print( "Testing script response parsing..." )
        script_json = '{"title": "Test Episode", "segments": [{"speaker": "Alex", "text": "Hello"}]}'
        parsed_script = parse_script_response( script_json )
        assert parsed_script[ "title" ] == "Test Episode"
        assert len( parsed_script[ "segments" ] ) == 1

        # Test fallback on invalid JSON
        invalid_response = "This is not JSON"
        fallback = parse_script_response( invalid_response )
        assert fallback[ "title" ] == "Untitled Podcast"
        print( "✓ Script response parsing works" )

        # Test 6: Extract prosody from text
        print( "Testing prosody extraction..." )
        text_with_prosody = "So *[pause]* what you're saying is *[excited]* this is amazing!"
        clean_text, annotations = extract_prosody_from_text( text_with_prosody )
        assert "pause" in annotations
        assert "excited" in annotations
        assert "*[" not in clean_text
        print( f"✓ Prosody extraction: found {len( annotations )} annotations" )

        # Test 7: System prompts exist and have content
        print( "Testing system prompts..." )
        assert len( CONTENT_ANALYSIS_SYSTEM_PROMPT ) > 100
        assert len( SCRIPT_GENERATION_SYSTEM_PROMPT ) > 100
        assert "JSON" in CONTENT_ANALYSIS_SYSTEM_PROMPT
        assert "Dynamic Duo" in SCRIPT_GENERATION_SYSTEM_PROMPT
        print( "✓ System prompts defined" )

        print( "\n✓ Script Generation Prompts smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
