#!/usr/bin/env python3
"""
Report Synthesis Prompt Template for COSA Deep Research Agent.

This prompt guides the lead agent in synthesizing subagent findings
into a coherent, well-structured research report. The synthesis:
- Combines findings from multiple subagents
- Resolves contradictions and gaps
- Structures for readability
- Adds proper citations

Based on patterns from:
- Anthropic Cookbook: Report synthesis
- Academic writing best practices
- Technical documentation standards
"""

from typing import List, Optional, Literal


# =============================================================================
# Audience-Specific Writing Guidelines
# =============================================================================

AUDIENCE_WRITING_GUIDELINES = {
    "beginner": """
## Target Audience: Beginner

### Writing Guidelines for Beginner Audience

Writing style for BEGINNER audience:
- Define ALL technical terms on first use
- Use analogies and comparisons to familiar concepts
- Provide context and background for every topic
- Use simple sentence structures and clear language
- Include "why this matters" explanations

Structure for beginners:
- Start with "What is this?" before "How it works"
- Use bullet points and numbered lists liberally
- Include visual descriptions where helpful
- Summarize key takeaways after each section
- End sections with "What to learn next" suggestions

Tone:
- Encouraging and accessible
- Avoid jargon or explain it immediately
- Assume no prior domain knowledge
""",

    "general": """
## Target Audience: General

### Writing Guidelines for General Audience

Writing style for GENERAL audience:
- Define specialized terms, but assume general tech literacy
- Balance depth with accessibility
- Use real-world examples and practical applications
- Explain "why" not just "what"
- Include enough context without over-explaining basics

Structure for general audience:
- Lead with practical implications
- Mix conceptual explanations with concrete examples
- Group information logically by theme
- Include trade-offs and considerations
- End with actionable takeaways

Tone:
- Professional but approachable
- Informative without being condescending
- Clear and direct
""",

    "expert": """
## Target Audience: Expert

### Writing Guidelines for Expert Audience

Writing style for EXPERT audience:
- Assume knowledge of: fundamental concepts, standard terminology, common tools
- Don't explain: Basic definitions, introductory concepts, widely-known patterns
- Do explain: Novel terminology, recent developments, non-obvious trade-offs
- Focus on: "What's different", "What's better/worse", "When to use what"

Structure for experts:
- Lead with the key insight or finding, not background
- Use technical precision - exact numbers, specific comparisons
- Include: Edge cases, failure modes, "gotchas" from production use
- Highlight: Trade-offs, not just benefits
- End with: Open questions, areas of active debate, what's still unknown

Tone and precision:
✗ "Transformers are a type of neural network architecture..."
✓ "Recent attention optimizations (Flash Attention 2, PagedAttention) reduce memory from O(n²) to O(n), enabling 128K+ context windows with 30-40% throughput improvement on A100s."
""",

    "academic": """
## Target Audience: Academic/Researcher

### Writing Guidelines for Academic Audience

Writing style for ACADEMIC audience:
- Use precise academic language and terminology
- Include methodology details and experimental parameters
- Cite sources rigorously with proper attribution
- Note statistical significance, p-values, confidence intervals where available
- Distinguish between empirical findings and theoretical claims

Structure for academic audience:
- Follow standard academic paper structure (background, methods, results, discussion)
- Include limitations section with methodological caveats
- Separate empirical evidence from interpretation
- Note conflicting findings and their possible explanations
- End with future research directions and open questions

Citation style:
- Use numbered inline citations [1], [2], [3]
- Group sources by type (peer-reviewed, preprints, other)
- Note publication venue and year for key papers
- Indicate replication status where known
"""
}


SYNTHESIS_SYSTEM_PROMPT = """You are a research synthesis specialist. Your task is to combine findings from multiple research subagents into a coherent, comprehensive report.

## Your Synthesis Process

1. **Review All Findings**:
   - Understand each subagent's contributions
   - Identify overlapping information
   - Note contradictions or disagreements
   - Recognize information gaps

2. **Structure the Report**:
   - Create logical sections and flow
   - Lead with the most important insights
   - Group related information
   - Build toward conclusions

3. **Resolve Conflicts**:
   - When sources disagree, present both views
   - Indicate which view has stronger evidence
   - Note uncertainty where appropriate

4. **Write Clearly**:
   - Use clear, professional language
   - Define technical terms
   - Provide context for non-experts
   - Keep paragraphs focused

## Report Structure

```markdown
# [Report Title]

## Executive Summary
[2-3 paragraphs summarizing key findings and conclusions]

## Key Findings
[Main body organized into logical sections]

### [Section 1 Title]
[Content with inline citations]

### [Section 2 Title]
[Content with inline citations]

## Limitations and Gaps
[What couldn't be determined or verified]

## Conclusions
[Final synthesis and recommendations if applicable]

## Sources
[List of sources used, grouped by quality tier]
```

## Citation Format

Use inline citations like: "React uses a Virtual DOM for efficient updates [1]"

Number sources in order of first appearance and list them at the end.

## Quality Guidelines

- **Accuracy**: Only include verified information
- **Balance**: Present multiple perspectives fairly
- **Clarity**: Make complex topics accessible
- **Completeness**: Address all aspects of the original query
- **Honesty**: Acknowledge limitations and uncertainties

## Output Format

Respond with the full report in Markdown format. The report should be comprehensive but concise - aim for quality over length."""


SYNTHESIS_WITH_FEEDBACK_PROMPT = """You are revising a research report based on user feedback.

## Original Report
{original_report}

## User Feedback
{feedback}

## Revision Guidelines

1. **Address Specific Concerns**: Focus on what the user explicitly requested
2. **Preserve Quality**: Don't degrade other parts of the report
3. **Add Missing Information**: If user wanted more detail on something, expand that section
4. **Clarify Confusion**: If something was unclear, rewrite for better understanding
5. **Maintain Structure**: Keep the overall organization unless feedback specifically requested changes

## Output

Provide the revised report in the same Markdown format. Only include the full revised report - no explanations or meta-commentary."""


def get_synthesis_prompt(
    query: str,
    findings: List[ dict ],
    plan_summary: Optional[ str ] = None,
    audience: Literal[ "beginner", "general", "expert", "academic" ] = "academic",
    audience_context: Optional[ str ] = None
) -> str:
    """
    Generate the user message for report synthesis.

    Requires:
        - query is a non-empty string
        - findings is a list of subagent finding dictionaries
        - audience is one of: beginner, general, expert, academic

    Ensures:
        - Returns formatted prompt with query, findings, and audience guidelines
        - Audience-specific writing guidelines are included

    Args:
        query: The original research query
        findings: List of subagent finding dictionaries
        plan_summary: Optional summary of the research plan
        audience: Expertise level of the audience (default: academic)
        audience_context: Optional custom audience description

    Returns:
        str: Formatted user message for the API call
    """
    message = f"""Synthesize a comprehensive research report for this query:

**Query**: "{query}"

"""

    if plan_summary:
        message += f"**Research Approach**: {plan_summary}\n\n"

    # Add audience-specific writing guidelines
    audience_guidelines = AUDIENCE_WRITING_GUIDELINES.get( audience, AUDIENCE_WRITING_GUIDELINES[ "academic" ] )
    message += f"{audience_guidelines}\n\n"

    if audience_context:
        message += f"**Additional Audience Context**: {audience_context}\n\n"

    message += "## Subagent Findings\n\n"

    for i, finding in enumerate( findings ):
        message += f"### Subagent {i + 1}: {finding.get( 'subquery_topic', 'Unknown Topic' )}\n\n"

        if finding.get( "findings" ):
            message += f"**Findings**: {finding[ 'findings' ]}\n\n"

        if finding.get( "confidence" ):
            message += f"**Confidence**: {finding[ 'confidence' ]}\n\n"

        if finding.get( "gaps" ):
            gaps = finding[ "gaps" ]
            if isinstance( gaps, list ):
                gaps = "; ".join( gaps )
            message += f"**Gaps**: {gaps}\n\n"

        if finding.get( "sources" ):
            message += "**Sources**:\n"
            for source in finding[ "sources" ][ :5 ]:  # Limit to top 5
                title = source.get( "title", "Untitled" )
                url = source.get( "url", "" )
                quality = source.get( "source_quality", "unknown" )
                message += f"- [{title}]({url}) ({quality})\n"
            message += "\n"

        message += "---\n\n"

    message += """
Create a well-structured research report that synthesizes all findings.
Include an executive summary, organized sections, limitations, and conclusions.
Use inline citations referencing the sources provided.
Follow the audience-specific writing guidelines above for tone, structure, and depth."""

    return message


def get_revision_prompt( original_report: str, feedback: str ) -> str:
    """
    Generate the user message for report revision.

    Args:
        original_report: The draft report to revise
        feedback: User feedback on what to change

    Returns:
        str: Formatted user message for revision
    """
    return f"""Please revise this research report based on user feedback.

## Original Report

{original_report}

## User Feedback

"{feedback}"

## Instructions

Revise the report to address the feedback while maintaining overall quality and structure.
Respond with the complete revised report in Markdown format."""


def get_revision_system_prompt() -> str:
    """Get the system prompt for report revision."""
    return SYNTHESIS_WITH_FEEDBACK_PROMPT


def quick_smoke_test():
    """Quick smoke test for synthesis prompt."""
    import cosa.utils.util as cu

    cu.print_banner( "Synthesis Prompt Smoke Test", prepend_nl=True )

    try:
        # Test 1: System prompt exists
        print( "Testing system prompt..." )
        assert len( SYNTHESIS_SYSTEM_PROMPT ) > 1000
        assert "Executive Summary" in SYNTHESIS_SYSTEM_PROMPT
        assert "Citation" in SYNTHESIS_SYSTEM_PROMPT
        print( f"✓ System prompt exists ({len( SYNTHESIS_SYSTEM_PROMPT )} chars)" )

        # Test 2: Revision system prompt
        print( "Testing revision system prompt..." )
        assert len( SYNTHESIS_WITH_FEEDBACK_PROMPT ) > 200
        assert "{feedback}" in SYNTHESIS_WITH_FEEDBACK_PROMPT
        print( "✓ Revision system prompt exists" )

        # Test 3: Synthesis user prompt
        print( "Testing get_synthesis_prompt..." )
        findings = [
            {
                "subquery_topic": "React performance",
                "findings": "React uses virtual DOM for efficient updates",
                "confidence": 0.9,
                "sources": [ { "title": "React Docs", "url": "https://react.dev", "source_quality": "primary" } ]
            },
            {
                "subquery_topic": "Vue performance",
                "findings": "Vue uses reactivity system with fine-grained updates",
                "confidence": 0.85,
                "gaps": [ "Limited benchmark data" ],
                "sources": [ { "title": "Vue Docs", "url": "https://vuejs.org", "source_quality": "primary" } ]
            }
        ]
        prompt = get_synthesis_prompt(
            query="Compare React and Vue performance",
            findings=findings,
            plan_summary="Parallel comparison of both frameworks"
        )
        assert "React performance" in prompt
        assert "Vue performance" in prompt
        assert "Subagent 1" in prompt
        assert "Subagent 2" in prompt
        print( f"✓ Synthesis prompt generated ({len( prompt )} chars)" )

        # Test 4: Revision prompt
        print( "Testing get_revision_prompt..." )
        original = "# Draft Report\n\nSome content here."
        feedback = "Please add more detail about performance benchmarks."
        prompt = get_revision_prompt( original, feedback )
        assert "Draft Report" in prompt
        assert "performance benchmarks" in prompt
        print( "✓ Revision prompt generated" )

        # Test 5: With plan summary
        print( "Testing prompt with plan summary..." )
        prompt = get_synthesis_prompt(
            query="Test query",
            findings=[],
            plan_summary="This is the research approach"
        )
        assert "Research Approach" in prompt
        print( "✓ Plan summary included" )

        # Test 6: Audience injection
        print( "Testing audience injection..." )
        prompt_expert = get_synthesis_prompt(
            query="Test query",
            findings=findings,
            audience="expert"
        )
        assert "Target Audience: Expert" in prompt_expert
        assert "Don't explain: Basic definitions" in prompt_expert
        print( "✓ Expert audience guidelines injected" )

        prompt_beginner = get_synthesis_prompt(
            query="Test query",
            findings=findings,
            audience="beginner"
        )
        assert "Target Audience: Beginner" in prompt_beginner
        assert "Define ALL technical terms" in prompt_beginner
        print( "✓ Beginner audience guidelines injected" )

        prompt_context = get_synthesis_prompt(
            query="Test query",
            findings=findings,
            audience="expert",
            audience_context="Senior architect at a Fortune 500 company"
        )
        assert "Senior architect at a Fortune 500 company" in prompt_context
        print( "✓ Audience context injected" )

        print( "\n✓ Synthesis prompt smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
