#!/usr/bin/env python3
"""
Claude Code headless fallback for CRUD intent extraction.

When the local Phi-4 14B model fails to produce a valid CRUDIntent,
this module calls `claude -p` (Claude Code headless) as a fallback
to extract intent from natural language queries.

Functions:
    extract_intent_via_claude_code: Calls claude -p, parses response into CRUDIntent
    build_claude_prompt: Builds the Claude Code prompt with operations and schemas
"""

import subprocess

from cosa.crud_for_dataframes.xml_models import CRUDIntent
from cosa.crud_for_dataframes.dispatcher import extract_intent_xml


def extract_intent_via_claude_code( query, available_lists_text, debug=False ):
    """
    Extract CRUD intent from a user query using Claude Code headless mode.

    Calls `claude -p` with a structured prompt and parses the response
    into a validated CRUDIntent object.

    Requires:
        - query is a non-empty string (the user's natural language request)
        - available_lists_text is a string describing user's current lists
        - claude CLI is available on PATH

    Ensures:
        - Returns a validated CRUDIntent on success
        - Returns None if extraction fails for any reason
    """
    prompt = build_claude_prompt( query, available_lists_text )

    try:
        if debug: print( f"intent_extractor: Calling claude -p for query: {query[ :80 ]}" )

        result = subprocess.run(
            [ "claude", "-p", prompt ],
            capture_output = True,
            text           = True,
            timeout        = 30
        )

        if result.returncode != 0:
            if debug: print( f"intent_extractor: claude -p returned non-zero: {result.returncode}" )
            return None

        raw_response = result.stdout.strip()
        if not raw_response:
            if debug: print( "intent_extractor: claude -p returned empty response" )
            return None

        if debug: print( f"intent_extractor: claude -p response length: {len( raw_response )}" )

        # Extract and parse the intent XML
        xml_text = extract_intent_xml( raw_response )
        intent   = CRUDIntent.from_xml( xml_text, root_tag="intent" )

        if debug: print( f"intent_extractor: Parsed intent: operation={intent.operation}, target_list={intent.target_list}" )

        return intent

    except subprocess.TimeoutExpired:
        if debug: print( "intent_extractor: claude -p timed out after 30s" )
        return None

    except Exception as e:
        if debug: print( f"intent_extractor: Failed to extract intent via Claude Code: {e}" )
        return None


def build_claude_prompt( query, available_lists_text ):
    """
    Build a structured prompt for Claude Code headless intent extraction.

    Requires:
        - query is a non-empty string
        - available_lists_text is a string (may be empty if no lists exist)

    Ensures:
        - Returns a prompt string instructing Claude to output <intent> XML
        - Includes the full list of valid operations and schema types
        - Includes the user's available lists for context
    """
    intent_example = CRUDIntent.get_example_for_template().to_xml( root_tag="intent" )

    prompt = f"""You are a CRUD intent extraction system. Parse the following natural language
query into a structured XML intent object.

Available operations: {', '.join( CRUDIntent.VALID_OPERATIONS )}
Available schema types: todo, calendar, generic

The user's current lists:
{available_lists_text if available_lists_text else "(no lists yet)"}

Respond with ONLY the XML intent block, no other text:
{intent_example}

Important:
- Use JSON format for match_fields, fields, and filters
- Leave unused fields empty (not null)
- Set confidence between 0.0 and 1.0

User query: {query}"""

    return prompt


def quick_smoke_test():
    """Module-level smoke test following CoSA convention."""

    print( "Testing intent_extractor module..." )
    passed = True

    try:
        # Test build_claude_prompt
        prompt = build_claude_prompt( "add buy milk to my groceries list", "- groceries (todo, 3 items)" )
        assert "add buy milk" in prompt
        assert "groceries" in prompt
        assert "<intent>" in prompt
        assert "Available operations:" in prompt
        print( "  ✓ build_claude_prompt: includes query, lists, and XML example" )

        # Test build_claude_prompt with no lists
        prompt = build_claude_prompt( "create a new grocery list", "" )
        assert "(no lists yet)" in prompt
        print( "  ✓ build_claude_prompt: handles empty lists" )

        # Note: extract_intent_via_claude_code requires the claude CLI
        # and is tested via mocked subprocess in unit tests
        print( "  ○ extract_intent_via_claude_code: requires claude CLI (tested in unit tests)" )

        print( "✓ intent_extractor module smoke test PASSED" )

    except Exception as e:
        print( f"✗ intent_extractor module smoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()
        passed = False

    return passed


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )
