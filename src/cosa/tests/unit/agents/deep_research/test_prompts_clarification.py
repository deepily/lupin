"""
Unit tests for cosa.agents.deep_research.prompts.clarification.

NEW FILE 2026-05-31 by Rio ⚡ (CoSA coverage campaign, deep_research lane). Pure
prompt-construction + JSON-parsing logic — no network/LLM. Covers the user-message
builder (with/without context) and the response parser's markdown-fence stripping
arms + ValueError on malformed JSON.
"""

import unittest

from cosa.agents.deep_research.prompts.clarification import (
    CLARIFICATION_SYSTEM_PROMPT,
    get_clarification_prompt,
    parse_clarification_response,
)


class TestSystemPrompt( unittest.TestCase ):

    def test_system_prompt_shape( self ):
        self.assertGreater( len( CLARIFICATION_SYSTEM_PROMPT ), 500 )
        self.assertIn( "needs_clarification", CLARIFICATION_SYSTEM_PROMPT )
        self.assertIn( "JSON", CLARIFICATION_SYSTEM_PROMPT )


class TestGetClarificationPrompt( unittest.TestCase ):

    def test_without_context( self ):
        msg = get_clarification_prompt( "What is quantum computing?" )
        self.assertIn( "quantum computing", msg )
        self.assertIn( "JSON", msg )
        self.assertNotIn( "Additional context", msg )

    def test_with_context( self ):
        msg = get_clarification_prompt( "Compare ML frameworks", context="beginner in Python" )
        self.assertIn( "ML frameworks", msg )
        self.assertIn( "Additional context: beginner in Python", msg )


class TestParseClarificationResponse( unittest.TestCase ):

    def test_plain_json( self ):
        out = parse_clarification_response( '{"needs_clarification": false, "confidence": 0.9}' )
        self.assertIs( out[ "needs_clarification" ], False )
        self.assertEqual( out[ "confidence" ], 0.9 )

    def test_json_fenced_block( self ):
        # ```json ... ``` → strips the ```json prefix AND trailing fence
        out = parse_clarification_response( '```json\n{"needs_clarification": true, "question": "scope?"}\n```' )
        self.assertIs( out[ "needs_clarification" ], True )
        self.assertEqual( out[ "question" ], "scope?" )

    def test_bare_fenced_block( self ):
        # ``` ... ``` (no json tag) → strips the bare ``` prefix arm AND trailing fence
        out = parse_clarification_response( '```\n{"options": [{"label": "Web"}]}\n```' )
        self.assertEqual( out[ "options" ][ 0 ][ "label" ], "Web" )

    def test_trailing_fence_only( self ):
        out = parse_clarification_response( '{"confidence": 0.5}\n```' )
        self.assertEqual( out[ "confidence" ], 0.5 )

    def test_invalid_json_raises_valueerror( self ):
        with self.assertRaises( ValueError ):
            parse_clarification_response( "this is not json at all" )


if __name__ == "__main__":
    unittest.main()
