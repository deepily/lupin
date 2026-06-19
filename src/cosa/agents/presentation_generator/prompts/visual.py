#!/usr/bin/env python3
"""
Mermaid Visual Generation Prompts for Presentation Generator.

System prompt and prompt builder for generating valid Mermaid diagram
syntax from natural-language visual descriptions. Used by MermaidRenderer
during Phase 7 (Visual Rendering).

Pattern: Same 3-part structure as narrative.py, outline.py, elaboration.py
  - System prompt constant
  - Prompt builder function
  - Supporting constants
"""


# =============================================================================
# Diagram Type Hints
# =============================================================================

MERMAID_DIAGRAM_TYPE_HINTS = {
    "flow"        : "flowchart TD",
    "process"     : "flowchart TD",
    "pipeline"    : "flowchart LR",
    "sequence"    : "sequenceDiagram",
    "interaction" : "sequenceDiagram",
    "request"     : "sequenceDiagram",
    "class"       : "classDiagram",
    "inheritance" : "classDiagram",
    "hierarchy"   : "classDiagram",
    "state"       : "stateDiagram-v2",
    "lifecycle"   : "stateDiagram-v2",
    "relationship": "erDiagram",
    "entity"      : "erDiagram",
    "pie"         : "pie",
    "distribution": "pie",
    "breakdown"   : "pie",
    "timeline"    : "gantt",
    "schedule"    : "gantt",
    "gantt"       : "gantt",
    "mindmap"     : "mindmap",
    "comparison"  : "flowchart LR",
}

DEFAULT_DIAGRAM_TYPE = "flowchart TD"


# =============================================================================
# System Prompt
# =============================================================================

MERMAID_SYSTEM_PROMPT = """You are a Mermaid diagram expert generating diagrams for presentation slides.

RULES:
1. Output ONLY valid Mermaid syntax inside a ```mermaid code block
2. Do NOT include any explanation, commentary, or text before or after the code block
3. Keep diagrams simple and readable — max 15 nodes for presentation slides
4. Use descriptive node labels (NOT single letters like A, B, C)
5. Use appropriate diagram types based on the content:
   - flowchart TD/LR for processes, architectures, pipelines
   - sequenceDiagram for interactions, request flows
   - classDiagram for hierarchies, inheritance
   - stateDiagram-v2 for state machines, lifecycles
   - erDiagram for entity relationships
   - pie for distributions, breakdowns
   - gantt for timelines, schedules
   - mindmap for concept maps
6. Include style directives for visual clarity when appropriate
7. Use subgraphs to group related nodes in flowcharts
8. Prefer left-to-right (LR) for pipelines/sequences, top-down (TD) for hierarchies

FORMATTING:
- Node labels should be 2-5 words (concise but descriptive)
- Use different node shapes for different roles: [] for process, () for data, {} for decision
- Add edge labels only when the relationship is not obvious from context
- For pie charts, use percentages that sum to 100

OUTPUT FORMAT:
```mermaid
<your diagram here>
```"""


# =============================================================================
# Prompt Builder
# =============================================================================

def get_mermaid_prompt( visual_type: str, visual_description: str, slide_title: str = "" ) -> str:
    """
    Build user message for Mermaid diagram generation.

    Requires:
        - visual_type is "diagram" or "chart"
        - visual_description is a non-empty string

    Ensures:
        - Returns a prompt string with context and diagram type hint

    Returns:
        str: User message for Claude API
    """
    # Suggest diagram type based on keywords in description
    suggested_type = _suggest_diagram_type( visual_description )

    parts = []

    if slide_title:
        parts.append( f"Slide title: {slide_title}" )

    parts.append( f"Visual type: {visual_type}" )
    parts.append( f"Suggested Mermaid type: {suggested_type}" )
    parts.append( f"\nDescription:\n{visual_description}" )
    parts.append( "\nGenerate a Mermaid diagram for this slide. Output ONLY the mermaid code block." )

    return "\n".join( parts )


def _suggest_diagram_type( description: str ) -> str:
    """
    Suggest a Mermaid diagram type based on keywords in the description.

    Requires:
        - description is a string

    Ensures:
        - Returns a valid Mermaid diagram type directive

    Returns:
        str: Mermaid diagram type (e.g., "flowchart TD", "sequenceDiagram")
    """
    if not description:
        return DEFAULT_DIAGRAM_TYPE

    description_lower = description.lower()

    for keyword, diagram_type in MERMAID_DIAGRAM_TYPE_HINTS.items():
        if keyword in description_lower:
            return diagram_type

    return DEFAULT_DIAGRAM_TYPE


# =============================================================================
# Smoke Test
# =============================================================================

def quick_smoke_test():
    """Quick smoke test for visual prompts."""

    print( "=" * 60 )
    print( "Visual Prompts Smoke Test" )
    print( "=" * 60 )

    try:
        # Test 1: System prompt exists
        print( "\nTest 1: System prompt..." )
        assert "Mermaid" in MERMAID_SYSTEM_PROMPT
        assert "```mermaid" in MERMAID_SYSTEM_PROMPT
        print( "  PASS" )

        # Test 2: Prompt builder
        print( "\nTest 2: Prompt builder..." )
        prompt = get_mermaid_prompt(
            visual_type        = "diagram",
            visual_description = "Flowchart showing L1 -> L2 -> L3 cache layers",
            slide_title        = "Three-Layer Cache",
        )
        assert "Three-Layer Cache" in prompt
        assert "Flowchart" in prompt
        assert "flowchart" in prompt.lower()
        print( "  PASS" )

        # Test 3: Diagram type hints
        print( "\nTest 3: Diagram type suggestion..." )
        assert _suggest_diagram_type( "sequence of API requests" ) == "sequenceDiagram"
        assert _suggest_diagram_type( "data flow pipeline" ) == "flowchart LR"
        assert _suggest_diagram_type( "pie chart of usage" ) == "pie"
        assert _suggest_diagram_type( "something unknown" ) == DEFAULT_DIAGRAM_TYPE
        print( "  PASS" )

        # Test 4: Empty description
        print( "\nTest 4: Empty description..." )
        assert _suggest_diagram_type( "" ) == DEFAULT_DIAGRAM_TYPE
        assert _suggest_diagram_type( None ) == DEFAULT_DIAGRAM_TYPE
        print( "  PASS" )

        print( f"\n{'=' * 60}" )
        print( "All visual prompt smoke tests passed" )
        print( f"{'=' * 60}" )

    except Exception as e:
        print( f"\nSmoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
