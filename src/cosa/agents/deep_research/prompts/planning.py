#!/usr/bin/env python3
"""
Research Planning Prompt Template for COSA Deep Research Agent.

This prompt helps the lead agent create a research plan by:
- Assessing query complexity (simple/moderate/complex)
- Decomposing into focused subqueries
- Determining appropriate subagent count
- Establishing research strategy

Based on patterns from:
- Anthropic Cookbook: Multi-agent coordination
- GPT Researcher: Planner/executor decomposition
- Anthropic Blog: Scaling heuristics
"""

from typing import Optional, Literal


# =============================================================================
# Audience-Specific Decomposition Guidelines
# =============================================================================

AUDIENCE_GUIDELINES = {
    "beginner": """
## Target Audience: Beginner

### Audience-Specific Decomposition Guidelines

For BEGINNER audience:
- Include foundational/introductory topics - do not assume prior knowledge
- Focus on: clear definitions, basic concepts, step-by-step explanations
- Include: "What is X?" topics for all key terms and concepts
- Prioritize: tutorials, getting-started guides, beginner-friendly resources
- Add subqueries for: prerequisites, learning paths, common pitfalls for newcomers
- Avoid: advanced optimizations, edge cases, implementation details

Example beginner decomposition for "LLM fine-tuning":
✓ "What is fine-tuning and why is it needed?"
✓ "Prerequisites for fine-tuning (hardware, software, data)"
✓ "Step-by-step guide to first fine-tuning project"
✗ "LoRA vs QLoRA memory trade-offs" (too advanced)
""",

    "general": """
## Target Audience: General

### Audience-Specific Decomposition Guidelines

For GENERAL audience:
- Balance foundational concepts with practical applications
- Focus on: clear explanations, real-world use cases, practical benefits
- Include: brief definitions of technical terms, accessible comparisons
- Prioritize: mainstream sources, well-documented approaches
- Add subqueries for: common use cases, typical workflows, popular tools
- Avoid: excessive jargon, highly specialized topics, academic minutiae

Example general decomposition for "LLM fine-tuning":
✓ "What is fine-tuning and when should you use it?"
✓ "Popular fine-tuning approaches and their trade-offs"
✓ "Tools and platforms for fine-tuning LLMs"
✓ "Real-world success stories and applications"
""",

    "expert": """
## Target Audience: Expert

### Audience-Specific Decomposition Guidelines

For EXPERT audience:
- Skip foundational/introductory topics - assume strong domain knowledge
- Focus on: novel approaches, architectural trade-offs, edge cases, failure modes
- Include: performance comparisons, scalability considerations, production concerns
- Prioritize: recent developments (last 12-18 months), contrarian viewpoints, implementation gotchas
- Add subqueries for: limitations, known issues, alternative approaches that experts debate
- Avoid: "What is X?" topics unless X is genuinely new (<6 months old)

Example expert decomposition for "LLM fine-tuning strategies":
✗ "What is fine-tuning?" (too basic)
✓ "LoRA vs QLoRA vs full fine-tuning: memory/quality trade-offs"
✓ "Catastrophic forgetting mitigation strategies comparison"
✓ "Production deployment considerations for fine-tuned models"
✓ "Recent advances in parameter-efficient fine-tuning (2025)"
""",

    "academic": """
## Target Audience: Academic/Researcher

### Audience-Specific Decomposition Guidelines

For ACADEMIC audience:
- Include methodological rigor and theoretical foundations
- Focus on: primary sources (papers, studies), methodology critique, open research questions
- Include: citations, experimental design considerations, statistical significance
- Prioritize: peer-reviewed sources, seminal papers, recent arXiv publications
- Add subqueries for: gaps in current research, conflicting findings, future directions
- Avoid: marketing content, surface-level overviews, non-peer-reviewed claims

Example academic decomposition for "LLM fine-tuning":
✓ "Theoretical foundations of transfer learning in LLMs"
✓ "Comparative analysis of PEFT methods: empirical findings"
✓ "Open questions in fine-tuning: catastrophic forgetting, alignment"
✓ "Methodological challenges in fine-tuning evaluation"
"""
}


PLANNING_SYSTEM_PROMPT = """You are a research planning specialist. Your task is to create an optimal research plan by decomposing a query into focused, parallelizable subqueries.

## Your Planning Process

1. **Assess Complexity**:
   - **Simple**: Straightforward fact-finding, single perspective (1 subquery)
   - **Moderate**: Comparisons, multi-faceted topics, some analysis (2-4 subqueries)
   - **Complex**: Deep analysis, multiple perspectives, synthesis required (5-10 subqueries)

2. **Decompose into Subqueries**:
   - Each subquery should be independently researchable
   - Subqueries should be focused and specific
   - Avoid overlap between subqueries
   - Order by priority (1 = highest)

3. **Design for Parallelism**:
   - Most subqueries can run in parallel
   - Use `depends_on` only when information from one subquery is needed for another
   - Minimize sequential dependencies

## Subquery Design Principles

- **Focused**: Each subquery addresses ONE aspect of the topic
- **Actionable**: Clear objective that can be achieved with web search
- **Measurable**: Specific output format (list, summary, comparison, etc.)
- **Independent**: Can be researched without context from other subqueries (unless dependency specified)

## Output Format

You must respond with a JSON object:

```json
{
    "complexity": "simple" | "moderate" | "complex",
    "subqueries": [
        {
            "topic": "Specific topic to research",
            "objective": "What information to gather - be specific",
            "output_format": "Expected structure (e.g., 'list of 5 companies', 'comparison table', 'factual summary')",
            "tools_to_use": ["web_search", "web_fetch"],
            "priority": 1-5,
            "depends_on": null or [indices of dependencies]
        }
    ],
    "estimated_subagents": 1-10,
    "rationale": "Brief explanation of the research approach",
    "estimated_duration_minutes": 5-30
}
```

## Examples

**Query**: "What are the main differences between React and Vue?"
**Response**:
```json
{
    "complexity": "moderate",
    "subqueries": [
        {
            "topic": "React core concepts and architecture",
            "objective": "Summarize React's key features, virtual DOM, component model, and design philosophy",
            "output_format": "structured summary with bullet points",
            "tools_to_use": ["web_search"],
            "priority": 1,
            "depends_on": null
        },
        {
            "topic": "Vue core concepts and architecture",
            "objective": "Summarize Vue's key features, reactivity system, component model, and design philosophy",
            "output_format": "structured summary with bullet points",
            "tools_to_use": ["web_search"],
            "priority": 1,
            "depends_on": null
        },
        {
            "topic": "React vs Vue performance benchmarks",
            "objective": "Find recent performance comparisons and benchmark data",
            "output_format": "comparison table with metrics",
            "tools_to_use": ["web_search"],
            "priority": 2,
            "depends_on": null
        },
        {
            "topic": "React vs Vue ecosystem and community",
            "objective": "Compare ecosystem size, community activity, job market, and tooling",
            "output_format": "comparison summary",
            "tools_to_use": ["web_search"],
            "priority": 2,
            "depends_on": null
        }
    ],
    "estimated_subagents": 4,
    "rationale": "Parallel comparison approach: gather information about each framework independently, then compare specific aspects. All subqueries can run in parallel.",
    "estimated_duration_minutes": 10
}
```

**Query**: "Summarize the latest news about Tesla"
**Response**:
```json
{
    "complexity": "simple",
    "subqueries": [
        {
            "topic": "Recent Tesla news and developments",
            "objective": "Find the most recent and significant news about Tesla from the past week",
            "output_format": "chronological list of 5-7 key news items with brief summaries",
            "tools_to_use": ["web_search"],
            "priority": 1,
            "depends_on": null
        }
    ],
    "estimated_subagents": 1,
    "rationale": "Simple fact-finding query that can be handled by a single focused search for recent news.",
    "estimated_duration_minutes": 5
}
```"""


def get_planning_prompt(
    query: str,
    clarified_query: Optional[ str ] = None,
    max_subagents: int = 10,
    audience: Literal[ "beginner", "general", "expert", "academic" ] = "academic",
    audience_context: Optional[ str ] = None
) -> str:
    """
    Generate the user message for research planning.

    Requires:
        - query is a non-empty string
        - audience is one of: beginner, general, expert, academic

    Ensures:
        - Returns formatted prompt with query, constraints, and audience guidelines
        - Audience-specific decomposition guidelines are included

    Args:
        query: The original research query
        clarified_query: The clarified version (if clarification was done)
        max_subagents: Maximum number of subagents to suggest
        audience: Expertise level of the audience (default: academic)
        audience_context: Optional custom audience description

    Returns:
        str: Formatted user message for the API call
    """
    effective_query = clarified_query if clarified_query else query

    message = f"Create a research plan for this query:\n\n\"{effective_query}\""

    if clarified_query and clarified_query != query:
        message += f"\n\n(Original query: \"{query}\")"

    # Add audience-specific guidelines
    audience_guidelines = AUDIENCE_GUIDELINES.get( audience, AUDIENCE_GUIDELINES[ "academic" ] )
    message += f"\n\n{audience_guidelines}"

    if audience_context:
        message += f"\n\n**Additional Audience Context**: {audience_context}"

    message += f"\n\nConstraints:"
    message += f"\n- Maximum subagents: {max_subagents}"
    message += f"\n- Prefer fewer, more focused subqueries over many shallow ones"
    message += f"\n- Prioritize parallelism when possible"
    message += f"\n- Follow the audience-specific guidelines above when decomposing"

    message += "\n\nRespond with a JSON object following the format specified in your instructions."

    return message


def parse_planning_response( response_text: str ) -> dict:
    """
    Parse the planning response JSON.

    Args:
        response_text: Raw response from the API

    Returns:
        dict: Parsed research plan

    Raises:
        ValueError: If response cannot be parsed as JSON
    """
    import json

    text = response_text.strip()

    # Handle markdown code blocks
    if text.startswith( "```json" ):
        text = text[ 7: ]
    if text.startswith( "```" ):
        text = text[ 3: ]
    if text.endswith( "```" ):
        text = text[ :-3 ]

    try:
        return json.loads( text.strip() )
    except json.JSONDecodeError as e:
        raise ValueError( f"Could not parse planning response as JSON: {e}" )


def quick_smoke_test():
    """Quick smoke test for planning prompt."""
    import cosa.utils.util as cu

    cu.print_banner( "Planning Prompt Smoke Test", prepend_nl=True )

    try:
        # Test 1: System prompt exists
        print( "Testing system prompt..." )
        assert len( PLANNING_SYSTEM_PROMPT ) > 1000
        assert "complexity" in PLANNING_SYSTEM_PROMPT
        assert "subqueries" in PLANNING_SYSTEM_PROMPT
        print( f"✓ System prompt exists ({len( PLANNING_SYSTEM_PROMPT )} chars)" )

        # Test 2: User prompt generation
        print( "Testing get_planning_prompt..." )
        prompt = get_planning_prompt( "Compare Python and JavaScript" )
        assert "Compare Python and JavaScript" in prompt
        assert "Maximum subagents" in prompt
        print( f"✓ User prompt generated ({len( prompt )} chars)" )

        # Test 3: With clarified query
        print( "Testing prompt with clarification..." )
        prompt = get_planning_prompt(
            query="Tell me about AI",
            clarified_query="Explain the current state of generative AI in 2025"
        )
        assert "generative AI" in prompt
        assert "Original query" in prompt
        print( "✓ Clarified query included" )

        # Test 3b: Audience injection
        print( "Testing audience injection..." )
        prompt_expert = get_planning_prompt(
            query="LLM fine-tuning",
            audience="expert"
        )
        assert "Target Audience: Expert" in prompt_expert
        assert "Skip foundational" in prompt_expert
        print( "✓ Expert audience guidelines injected" )

        prompt_beginner = get_planning_prompt(
            query="LLM fine-tuning",
            audience="beginner"
        )
        assert "Target Audience: Beginner" in prompt_beginner
        assert "do not assume prior knowledge" in prompt_beginner
        print( "✓ Beginner audience guidelines injected" )

        prompt_context = get_planning_prompt(
            query="LLM fine-tuning",
            audience="expert",
            audience_context="AI architect with ML background"
        )
        assert "AI architect with ML background" in prompt_context
        print( "✓ Audience context injected" )

        # Test 4: Parse valid response
        print( "Testing parse_planning_response..." )
        valid_json = '''{
            "complexity": "moderate",
            "subqueries": [
                {"topic": "Topic 1", "objective": "Obj 1", "output_format": "summary", "priority": 1}
            ],
            "estimated_subagents": 2,
            "rationale": "Test rationale"
        }'''
        result = parse_planning_response( valid_json )
        assert result[ "complexity" ] == "moderate"
        assert len( result[ "subqueries" ] ) == 1
        print( "✓ Parsed valid planning response" )

        # Test 5: Theme clustering prompt exists
        print( "Testing theme clustering prompt..." )
        assert len( THEME_CLUSTERING_PROMPT ) > 500
        assert "themes" in THEME_CLUSTERING_PROMPT
        assert "subquery_indices" in THEME_CLUSTERING_PROMPT
        print( f"✓ Theme clustering prompt exists ({len( THEME_CLUSTERING_PROMPT )} chars)" )

        # Test 6: Theme clustering user prompt generation
        print( "Testing get_theme_clustering_prompt..." )
        test_subqueries = [
            { "topic": "React features", "objective": "Summarize React" },
            { "topic": "Vue features", "objective": "Summarize Vue" },
            { "topic": "Performance", "objective": "Compare benchmarks" },
        ]
        cluster_prompt = get_theme_clustering_prompt( test_subqueries )
        assert "3 research topics" in cluster_prompt
        assert "React features" in cluster_prompt
        print( f"✓ Theme clustering prompt generated ({len( cluster_prompt )} chars)" )

        print( "\n✓ Planning prompt smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


# =============================================================================
# Theme Clustering (for Progressive Narrowing UX)
# =============================================================================

THEME_CLUSTERING_PROMPT = """You are organizing research topics into thematic groups for user selection.

Given a list of research subqueries, cluster them into 3-4 high-level themes.

## Rules
- Create 3-4 themes (never more than 4, never fewer than 2)
- Each theme should group related subqueries
- Theme names should be concise (2-4 words)
- Every subquery must belong to exactly one theme

## Output Format

```json
{
    "themes": [
        {
            "name": "Theme Name",
            "description": "One sentence describing this theme",
            "subquery_indices": [0, 2, 5]
        }
    ]
}
```

## Example

Input topics:
0. React core concepts: Summarize React's key features
1. Vue core concepts: Summarize Vue's key features
2. Performance benchmarks: Compare performance metrics
3. Community size: Compare ecosystem activity
4. Learning curve: Analyze documentation quality

Output:
```json
{
    "themes": [
        {
            "name": "Framework Foundations",
            "description": "Core architecture and key features of each framework",
            "subquery_indices": [0, 1]
        },
        {
            "name": "Technical Comparison",
            "description": "Performance benchmarks and metrics",
            "subquery_indices": [2]
        },
        {
            "name": "Ecosystem & Adoption",
            "description": "Community, learning resources, and adoption factors",
            "subquery_indices": [3, 4]
        }
    ]
}
```
"""


def get_theme_clustering_prompt( subqueries: list ) -> str:
    """
    Generate prompt for clustering subqueries into themes.

    Requires:
        - subqueries is a non-empty list of dicts with 'topic' and optionally 'objective'

    Ensures:
        - Returns formatted prompt listing all subqueries for clustering

    Args:
        subqueries: List of subquery dicts from planning response

    Returns:
        str: User message for theme clustering API call
    """
    topics_list = "\n".join(
        f"{i}. {sq.get( 'topic', 'Unknown' )}: {sq.get( 'objective', '' )[ :60 ]}"
        for i, sq in enumerate( subqueries )
    )
    return f"Cluster these {len( subqueries )} research topics into 3-4 themes:\n\n{topics_list}"


if __name__ == "__main__":
    quick_smoke_test()
