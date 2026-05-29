#!/usr/bin/env python3
"""
Host Personality Prompts for COSA Podcast Generator Agent.

Contains templates and utilities for customizing host personalities
in the "Dynamic Duo" podcast format.
"""

from ..config import HostPersonality


# =============================================================================
# Default Personality Prompt Sections
# =============================================================================

CURIOUS_HOST_PROMPT_SECTION = """THE CURIOUS HOST:
- Asks questions that listeners would naturally have
- Expresses genuine wonder and interest
- Occasionally shares relatable experiences or confusions
- Uses phrases like "Wait, so..." and "Help me understand..."
- Builds bridges between complex ideas and everyday life
- Admits when something is confusing (makes listeners feel validated)
- Responds with enthusiasm to interesting revelations
- Sometimes plays devil's advocate to draw out more explanation"""


EXPERT_HOST_PROMPT_SECTION = """THE KNOWLEDGEABLE HOST:
- Explains concepts clearly without being condescending
- Uses analogies and concrete examples liberally
- Builds on the curious host's questions naturally
- Knows when to simplify and when to go deeper
- Shares relevant anecdotes and behind-the-scenes insights
- Uses phrases like "Great question..." and "Think of it this way..."
- Acknowledges complexity while making it accessible
- Connects ideas to broader themes and implications"""


# =============================================================================
# Personality Template Functions
# =============================================================================

def get_personality_prompt_section(
    host_personality: HostPersonality,
    is_curious_role: bool = True
) -> str:
    """
    Generate a prompt section describing a host's personality.

    Requires:
        - host_personality is a valid HostPersonality instance

    Ensures:
        - Returns formatted prompt section for system prompts
        - Includes all personality attributes

    Args:
        host_personality: The host's personality configuration
        is_curious_role: True if this is the curious/questioner role

    Returns:
        str: Formatted personality description for prompts
    """
    role_label = "CURIOUS HOST" if is_curious_role else "KNOWLEDGEABLE HOST"
    base_behavior = CURIOUS_HOST_PROMPT_SECTION if is_curious_role else EXPERT_HOST_PROMPT_SECTION

    # Build custom section from personality
    custom_desc = host_personality.to_prompt_description()

    # Format typical phrases as examples
    phrase_examples = ""
    if host_personality.typical_phrases:
        examples = '", "'.join( host_personality.typical_phrases[ :5 ] )
        phrase_examples = f'\nExample phrases: "{examples}"'

    return f"""{role_label} - {host_personality.name}:

PERSONALITY PROFILE:
{custom_desc}

BEHAVIORAL GUIDELINES:
{base_behavior}{phrase_examples}"""


def get_dynamic_duo_description(
    host_a: HostPersonality,
    host_b: HostPersonality
) -> str:
    """
    Generate a complete description of the Dynamic Duo hosts.

    Requires:
        - Both host personalities are configured

    Ensures:
        - Returns comprehensive prompt section for both hosts
        - Includes interaction dynamics between hosts

    Args:
        host_a: Curious/questioner host
        host_b: Expert/explainer host

    Returns:
        str: Complete duo description for prompts
    """
    section_a = get_personality_prompt_section( host_a, is_curious_role=True )
    section_b = get_personality_prompt_section( host_b, is_curious_role=False )

    interaction_dynamics = f"""
INTERACTION DYNAMICS:
The chemistry between {host_a.name} and {host_b.name} is key to engaging content:

1. COMPLEMENTARY ENERGY
   - {host_a.name}'s curiosity draws out {host_b.name}'s expertise
   - {host_b.name}'s explanations spark new questions from {host_a.name}
   - Natural back-and-forth creates momentum

2. LISTENER PROXY
   - {host_a.name} voices questions the audience might have
   - {host_b.name} addresses both {host_a.name} AND the listeners
   - Together they make complex topics accessible

3. HUMAN MOMENTS
   - Include brief personal tangents that relate to the topic
   - Show genuine reactions (surprise, amusement, skepticism)
   - Let moments breathe with natural pauses

4. BUILDING TOGETHER
   - One host's point should set up the other's response
   - Occasionally complete each other's thoughts
   - Reference earlier points in the conversation"""

    return f"""{section_a}

{section_b}

{interaction_dynamics}"""


def create_personality_from_description(
    name: str,
    description: str,
    is_curious: bool = True
) -> HostPersonality:
    """
    Create a HostPersonality from a natural language description.

    This is a simple version - could be enhanced with LLM parsing
    for more sophisticated personality extraction.

    Requires:
        - name is a non-empty string
        - description provides personality context

    Ensures:
        - Returns HostPersonality with reasonable defaults

    Args:
        name: Host's name
        description: Natural language personality description
        is_curious: Whether this is the curious (True) or expert (False) role

    Returns:
        HostPersonality: Configured personality
    """
    # Simple keyword detection for tone
    desc_lower = description.lower()

    if "enthusiastic" in desc_lower or "energetic" in desc_lower:
        tone = "enthusiastic and energetic"
    elif "calm" in desc_lower or "measured" in desc_lower:
        tone = "calm and measured"
    elif "humorous" in desc_lower or "funny" in desc_lower:
        tone = "humorous and witty"
    elif "scholarly" in desc_lower or "academic" in desc_lower:
        tone = "scholarly and precise"
    else:
        tone = "conversational"

    # Determine expertise level
    if "professor" in desc_lower or "expert" in desc_lower or "specialist" in desc_lower:
        expertise = "expert"
    elif "student" in desc_lower or "learning" in desc_lower:
        expertise = "learning"
    else:
        expertise = "knowledgeable" if not is_curious else "educated layperson"

    # Determine curiosity level
    if is_curious:
        curiosity = "high" if "very curious" in desc_lower else "moderate"
    else:
        curiosity = "low" if "focused" in desc_lower else "moderate"

    return HostPersonality(
        name              = name,
        role              = "Curious Questioner" if is_curious else "Knowledgeable Explainer",
        tone              = tone,
        expertise_level   = expertise,
        curiosity_level   = curiosity,
        speaking_style    = "clear and engaging",
        typical_phrases   = [],  # Could be extracted with LLM
        interaction_style = "asks follow-up questions" if is_curious else "explains with examples",
    )


def get_prosody_guidelines() -> str:
    """
    Get guidelines for prosody annotation usage.

    Returns:
        str: Prosody annotation guidelines for prompts
    """
    return """PROSODY ANNOTATION GUIDELINES:

Use these markers sparingly for natural expressiveness:

EMOTIONAL MARKERS (use 2-3 per minute of content):
- *[laughs]* or *[chuckles]* - Light laughter at humor or irony
- *[whispers]* - Conspiratorial or surprising information
- *[excited]* - Genuine enthusiasm about a discovery
- *[thoughtful]* - Considering implications deeply

PACING MARKERS (use strategically):
- *[pause]* - Brief 0.5s pause for emphasis or breath
- *[long_pause]* - 2-3s pause for dramatic effect or topic transition
- *[emphasis]* - Stress on the following word or phrase

USAGE TIPS:
1. Don't over-annotate - let natural dialogue shine
2. Use *[pause]* before important revelations
3. Use *[excited]* sparingly to maintain impact
4. *[chuckles]* is more subtle than *[laughs]*
5. Place annotations before the affected text"""


def quick_smoke_test():
    """Quick smoke test for personality prompts."""
    import cosa.utils.util as cu

    cu.print_banner( "Personality Prompts Smoke Test", prepend_nl=True )

    try:
        # Test 1: Get personality prompt section
        print( "Testing get_personality_prompt_section..." )
        from ..config import DEFAULT_CURIOUS_HOST, DEFAULT_EXPERT_HOST

        section = get_personality_prompt_section( DEFAULT_CURIOUS_HOST, is_curious_role=True )
        assert "Nora" in section
        assert "CURIOUS HOST" in section
        assert "Wait, so..." in section or "typical_phrases" in section.lower()
        print( "✓ Curious host prompt section generated" )

        section_expert = get_personality_prompt_section( DEFAULT_EXPERT_HOST, is_curious_role=False )
        assert "Quentin" in section_expert
        assert "KNOWLEDGEABLE HOST" in section_expert
        print( "✓ Expert host prompt section generated" )

        # Test 2: Get dynamic duo description
        print( "Testing get_dynamic_duo_description..." )
        duo_desc = get_dynamic_duo_description( DEFAULT_CURIOUS_HOST, DEFAULT_EXPERT_HOST )
        assert "Nora" in duo_desc
        assert "Quentin" in duo_desc
        assert "INTERACTION DYNAMICS" in duo_desc
        assert "COMPLEMENTARY ENERGY" in duo_desc
        print( "✓ Dynamic duo description generated" )

        # Test 3: Create personality from description
        print( "Testing create_personality_from_description..." )
        custom = create_personality_from_description(
            name        = "Dr. Chen",
            description = "An enthusiastic professor who loves making complex topics fun",
            is_curious  = False,
        )
        assert custom.name == "Dr. Chen"
        assert custom.expertise_level == "expert"  # "professor" keyword
        assert "enthusiastic" in custom.tone.lower()
        print( f"✓ Created custom personality: {custom.name} ({custom.tone})" )

        curious_custom = create_personality_from_description(
            name        = "Sam",
            description = "A very curious student always eager to learn",
            is_curious  = True,
        )
        assert curious_custom.curiosity_level == "high"  # "very curious" keyword
        print( f"✓ Created curious personality: {curious_custom.name} (curiosity: {curious_custom.curiosity_level})" )

        # Test 4: Get prosody guidelines
        print( "Testing get_prosody_guidelines..." )
        guidelines = get_prosody_guidelines()
        assert "*[pause]*" in guidelines
        assert "*[excited]*" in guidelines
        assert "EMOTIONAL MARKERS" in guidelines
        print( "✓ Prosody guidelines generated" )

        # Test 5: Default prompt sections exist
        print( "Testing default prompt sections..." )
        assert len( CURIOUS_HOST_PROMPT_SECTION ) > 50
        assert len( EXPERT_HOST_PROMPT_SECTION ) > 50
        assert "questions" in CURIOUS_HOST_PROMPT_SECTION.lower()
        assert "analogies" in EXPERT_HOST_PROMPT_SECTION.lower()
        print( "✓ Default prompt sections defined" )

        print( "\n✓ Personality Prompts smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
