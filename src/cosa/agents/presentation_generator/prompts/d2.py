#!/usr/bin/env python3
"""
D2 Diagram Generation Prompts for Presentation Generator.

System prompt and prompt builder for generating valid D2 syntax
from natural-language visual descriptions. Used by D2Renderer
during Phase 7 (Visual Rendering).

Pattern: Same 3-part structure as visual.py (Mermaid prompts)
  - System prompt constant
  - Prompt builder function
  - Supporting constants
"""


# =============================================================================
# Diagram Pattern Hints
# =============================================================================

D2_DIAGRAM_PATTERN_HINTS = {
    "flow"         : "sequential nodes with arrows (->)",
    "process"      : "sequential nodes with arrows (->)",
    "pipeline"     : "left-to-right sequential nodes (direction: right)",
    "architecture" : "containers with nested components",
    "system"       : "containers with nested components",
    "microservice" : "containers with nested components and connections",
    "sequence"     : "sequence diagram (shape: sequence_diagram)",
    "interaction"  : "sequence diagram (shape: sequence_diagram)",
    "hierarchy"    : "tree layout with parent-child connections",
    "tree"         : "tree layout with parent-child connections",
    "network"      : "interconnected nodes with bidirectional arrows (<->)",
    "layers"       : "stacked containers (top to bottom)",
    "comparison"   : "side-by-side containers with labels",
}

DEFAULT_D2_PATTERN = "sequential nodes with arrows (->)"


# =============================================================================
# System Prompt
# =============================================================================

D2_SYSTEM_PROMPT = """You are a D2 diagram expert generating diagrams for presentation slides.

RULES:
1. Output ONLY valid D2 syntax inside a ```d2 code block
2. Do NOT include any explanation, commentary, or text before or after the code block
3. Keep diagrams readable — max 12-15 nodes for presentation slides
4. Use descriptive node names (NOT single letters like a, b, c)
5. Use containers (curly braces) to group related components
6. Include connection labels where meaningful: a -> b: "sends data"
7. Do NOT include theme or style directives — themes are applied via CLI flag
8. Use appropriate patterns based on content:
   - Sequential processes: a -> b -> c
   - Architecture: container { nested_component }
   - Bidirectional: a <-> b
   - Sequence diagrams: shape: sequence_diagram
   - Grouping: container.component

FORMATTING:
- Node labels should be 2-5 words (concise but descriptive)
- Use containers to show system boundaries, services, or logical groups
- Add edge labels only when the relationship is not obvious
- Use line breaks between logical sections for readability
- Indent nested content inside containers

OUTPUT FORMAT:
```d2
<your diagram here>
```"""


# =============================================================================
# Prompt Builder
# =============================================================================

def get_d2_prompt( visual_type: str, visual_description: str, slide_title: str = "" ) -> str:
    """
    Build user message for D2 diagram generation.

    Requires:
        - visual_type is "flowchart_d2" or "architecture"
        - visual_description is a non-empty string

    Ensures:
        - Returns a prompt string with context and D2 pattern hint

    Returns:
        str: User message for Claude API
    """
    suggested_pattern = _suggest_d2_pattern( visual_description )

    parts = []

    if slide_title:
        parts.append( f"Slide title: {slide_title}" )

    parts.append( f"Visual type: {visual_type}" )
    parts.append( f"Suggested D2 pattern: {suggested_pattern}" )
    parts.append( f"\nDescription:\n{visual_description}" )
    parts.append( "\nGenerate a D2 diagram for this slide. Output ONLY the d2 code block." )

    return "\n".join( parts )


def _suggest_d2_pattern( description: str ) -> str:
    """
    Suggest a D2 diagram pattern based on keywords in the description.

    Requires:
        - description is a string

    Ensures:
        - Returns a D2 pattern description string

    Returns:
        str: D2 pattern hint (e.g., "containers with nested components")
    """
    if not description:
        return DEFAULT_D2_PATTERN

    description_lower = description.lower()

    for keyword, pattern in D2_DIAGRAM_PATTERN_HINTS.items():
        if keyword in description_lower:
            return pattern

    return DEFAULT_D2_PATTERN


# =============================================================================
# Smoke Test
# =============================================================================

def quick_smoke_test():
    """Quick smoke test for D2 prompts."""

    print( "=" * 60 )
    print( "D2 Prompts Smoke Test" )
    print( "=" * 60 )

    try:
        # Test 1: System prompt exists
        print( "\nTest 1: System prompt..." )
        assert "D2" in D2_SYSTEM_PROMPT
        assert "```d2" in D2_SYSTEM_PROMPT
        assert "container" in D2_SYSTEM_PROMPT.lower()
        print( "  PASS" )

        # Test 2: Prompt builder
        print( "\nTest 2: Prompt builder..." )
        prompt = get_d2_prompt(
            visual_type        = "architecture",
            visual_description = "Microservice architecture with API gateway, auth service, and database",
            slide_title        = "System Architecture",
        )
        assert "System Architecture" in prompt
        assert "architecture" in prompt.lower()
        assert "containers with nested components" in prompt
        print( "  PASS" )

        # Test 3: Pattern hints
        print( "\nTest 3: Pattern suggestion..." )
        assert _suggest_d2_pattern( "sequence of API interactions" ) == "sequence diagram (shape: sequence_diagram)"
        assert _suggest_d2_pattern( "data flow pipeline" ) == "left-to-right sequential nodes (direction: right)"
        assert _suggest_d2_pattern( "system architecture overview" ) == "containers with nested components"
        assert _suggest_d2_pattern( "something unknown" ) == DEFAULT_D2_PATTERN
        print( "  PASS" )

        # Test 4: Empty description
        print( "\nTest 4: Empty description..." )
        assert _suggest_d2_pattern( "" ) == DEFAULT_D2_PATTERN
        assert _suggest_d2_pattern( None ) == DEFAULT_D2_PATTERN
        print( "  PASS" )

        print( f"\n{'=' * 60}" )
        print( "All D2 prompt smoke tests passed" )
        print( f"{'=' * 60}" )

    except Exception as e:
        print( f"\nSmoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
