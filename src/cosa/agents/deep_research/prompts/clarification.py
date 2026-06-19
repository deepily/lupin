#!/usr/bin/env python3
"""
Query Clarification Prompt Template for COSA Deep Research Agent.

This prompt helps the lead agent decide if a query needs clarification
before research can begin. It identifies ambiguities and generates
focused clarification questions.

Based on patterns from:
- Anthropic Cookbook: Research clarification patterns
- LangChain Open Deep Research: Query understanding
"""

from typing import Optional


CLARIFICATION_SYSTEM_PROMPT = """You are a research query analyst. Your task is to analyze user queries and determine if clarification is needed before research can begin.

## Your Analysis Process

1. **Identify the core intent**: What is the user fundamentally trying to learn?
2. **Check for ambiguities**: Are there terms, timeframes, or scopes that could be interpreted multiple ways?
3. **Assess research feasibility**: Can this query be researched as-is, or does it need refinement?

## When to Request Clarification

Request clarification ONLY if the query has:
- **Critical ambiguity**: Multiple valid interpretations that would lead to very different research directions
- **Missing essential context**: Timeframe, geographic scope, or domain not specified when relevant
- **Overly broad scope**: Would require filtering down to be actionable

Do NOT request clarification for:
- Minor ambiguities that won't affect core research
- Queries that are already reasonably specific
- Cases where a reasonable default interpretation exists

## Output Format

You must respond with a JSON object:

```json
{
    "needs_clarification": true/false,
    "understood_query": "Your interpretation of what the user is asking",
    "question": "Brief clarification question header (when needs_clarification is true)",
    "options": [
        {"label": "Option 1", "description": "What this option means"},
        {"label": "Option 2", "description": "What this option means"},
        {"label": "Option 3", "description": "What this option means"}
    ],
    "ambiguities": ["List of identified ambiguities"],
    "confidence": 0.0-1.0
}
```

IMPORTANT for options:
- Provide 2-4 distinct options that address the main ambiguity
- Each option MUST have a concise "label" (1-5 words) and helpful "description"
- Options should be mutually exclusive or represent clearly different directions
- The user can always choose "Other" to provide custom input

## Examples

**User Query**: "What's the best programming language?"
**Response**:
```json
{
    "needs_clarification": true,
    "understood_query": "The user wants to know which programming language is optimal, but for an unspecified purpose",
    "question": "Best for what purpose?",
    "options": [
        {"label": "Web development", "description": "Building websites and web applications"},
        {"label": "Data science", "description": "Data analysis, ML, and scientific computing"},
        {"label": "Mobile apps", "description": "iOS or Android app development"},
        {"label": "Learning to program", "description": "Best language for beginners"}
    ],
    "ambiguities": ["No purpose/domain specified", "No experience level mentioned", "'Best' is subjective without criteria"],
    "confidence": 0.3
}
```

**User Query**: "Compare React and Vue for building modern web applications"
**Response**:
```json
{
    "needs_clarification": false,
    "understood_query": "Compare React and Vue.js frameworks for modern web application development, covering their strengths, weaknesses, and use cases",
    "question": null,
    "options": [],
    "ambiguities": [],
    "confidence": 0.9
}
```

**User Query**: "Tell me about AI"
**Response**:
```json
{
    "needs_clarification": true,
    "understood_query": "The user wants information about artificial intelligence, but the scope is too broad",
    "question": "What aspect of AI interests you most?",
    "options": [
        {"label": "Current capabilities", "description": "What AI can do today (ChatGPT, image generation, etc.)"},
        {"label": "Technical deep-dive", "description": "How AI/ML algorithms work under the hood"},
        {"label": "Societal impact", "description": "Effects on jobs, ethics, and society"},
        {"label": "Specific applications", "description": "AI in healthcare, finance, or other industries"}
    ],
    "ambiguities": ["Extremely broad topic", "No specific aspect mentioned", "Could be history, technology, ethics, applications, or future predictions"],
    "confidence": 0.2
}
```"""


def get_clarification_prompt( query: str, context: Optional[ str ] = None ) -> str:
    """
    Generate the user message for clarification analysis.

    Args:
        query: The user's research query
        context: Optional additional context about the research

    Returns:
        str: Formatted user message for the API call
    """
    message = f"Please analyze this research query:\n\n\"{query}\""

    if context:
        message += f"\n\nAdditional context: {context}"

    message += "\n\nRespond with a JSON object following the format specified in your instructions."

    return message


def parse_clarification_response( response_text: str ) -> dict:
    """
    Parse the clarification response JSON.

    Handles markdown code blocks and extracts JSON.

    Args:
        response_text: Raw response from the API

    Returns:
        dict: Parsed clarification decision

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
        raise ValueError( f"Could not parse clarification response as JSON: {e}" )


def quick_smoke_test():
    """Quick smoke test for clarification prompt."""
    import cosa.utils.util as cu

    cu.print_banner( "Clarification Prompt Smoke Test", prepend_nl=True )

    try:
        # Test 1: System prompt exists
        print( "Testing system prompt..." )
        assert len( CLARIFICATION_SYSTEM_PROMPT ) > 500
        assert "needs_clarification" in CLARIFICATION_SYSTEM_PROMPT
        assert "JSON" in CLARIFICATION_SYSTEM_PROMPT
        print( f"✓ System prompt exists ({len( CLARIFICATION_SYSTEM_PROMPT )} chars)" )

        # Test 2: User prompt generation
        print( "Testing get_clarification_prompt..." )
        prompt = get_clarification_prompt( "What is quantum computing?" )
        assert "quantum computing" in prompt
        assert "JSON" in prompt
        print( f"✓ User prompt generated ({len( prompt )} chars)" )

        # Test 3: With context
        print( "Testing prompt with context..." )
        prompt = get_clarification_prompt(
            "Compare ML frameworks",
            context="User is a beginner interested in Python"
        )
        assert "ML frameworks" in prompt
        assert "beginner" in prompt
        print( "✓ Context included in prompt" )

        # Test 4: Parse valid JSON response
        print( "Testing parse_clarification_response..." )
        valid_json = '{"needs_clarification": false, "understood_query": "Test", "question": null, "options": [], "ambiguities": [], "confidence": 0.9}'
        result = parse_clarification_response( valid_json )
        assert result[ "needs_clarification" ] is False
        assert result[ "confidence" ] == 0.9
        assert result[ "options" ] == []
        print( "✓ Parsed valid JSON response" )

        # Test 4b: Parse JSON response with options
        print( "Testing parse_clarification_response with options..." )
        json_with_options = '{"needs_clarification": true, "question": "What scope?", "options": [{"label": "Web", "description": "Web apps"}, {"label": "Mobile", "description": "Mobile apps"}], "confidence": 0.4}'
        result = parse_clarification_response( json_with_options )
        assert result[ "needs_clarification" ] is True
        assert len( result[ "options" ] ) == 2
        assert result[ "options" ][ 0 ][ "label" ] == "Web"
        print( "✓ Parsed JSON response with options" )

        # Test 5: Parse markdown-wrapped JSON
        print( "Testing markdown-wrapped JSON parsing..." )
        markdown_json = '```json\n{"needs_clarification": true, "question": "What scope?"}\n```'
        result = parse_clarification_response( markdown_json )
        assert result[ "needs_clarification" ] is True
        print( "✓ Parsed markdown-wrapped JSON" )

        # Test 6: Invalid JSON raises error
        print( "Testing invalid JSON handling..." )
        try:
            parse_clarification_response( "This is not JSON" )
            print( "✗ Should have raised ValueError" )
        except ValueError as e:
            print( f"✓ Correctly raised ValueError for invalid JSON" )

        print( "\n✓ Clarification prompt smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
