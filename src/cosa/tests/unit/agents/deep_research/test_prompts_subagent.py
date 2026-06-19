"""
Unit tests for cosa.agents.deep_research.prompts.subagent.

NEW FILE 2026-05-31 by Rio ⚡ (CoSA coverage campaign, deep_research lane). Pure
prompt-construction + JSON-parsing logic — no network/LLM. Covers the subagent
user-message builder (context + audience + audience_context branches), the
parameterized system prompt, and the response parser's markdown-fence arms.
"""

import unittest

from cosa.agents.deep_research.prompts.subagent import (
    SUBAGENT_SYSTEM_PROMPT,
    AUDIENCE_RESEARCH_GUIDELINES,
    get_subagent_prompt,
    get_system_prompt_with_params,
    parse_subagent_response,
)


class TestSystemPrompt( unittest.TestCase ):

    def test_shape( self ):
        self.assertGreater( len( SUBAGENT_SYSTEM_PROMPT ), 1000 )
        self.assertIn( "findings", SUBAGENT_SYSTEM_PROMPT )
        self.assertIn( "sources", SUBAGENT_SYSTEM_PROMPT )

    def test_parameterized_fills_source_counts( self ):
        prompt = get_system_prompt_with_params( min_sources=5, max_sources=15 )
        self.assertIn( "5", prompt )
        self.assertIn( "15", prompt )
        self.assertNotIn( "{min_sources}", prompt )          # template token substituted


class TestGetSubagentPrompt( unittest.TestCase ):

    def _base( self, **kw ):
        kw.setdefault( "topic", "React performance" )
        kw.setdefault( "objective", "Find best practices" )
        kw.setdefault( "output_format", "bullet list" )
        return get_subagent_prompt( **kw )

    def test_core_fields_present( self ):
        msg = self._base( min_sources=3, max_sources=10 )
        self.assertIn( "React performance", msg )
        self.assertIn( "Find best practices", msg )
        self.assertIn( "bullet list", msg )
        self.assertIn( "Minimum sources: 3", msg )
        self.assertIn( "Maximum sources: 10", msg )

    def test_without_context_no_additional_context_block( self ):
        msg = self._base()
        self.assertNotIn( "**Additional Context**", msg )

    def test_with_context( self ):
        msg = self._base( context="comparing with React Hooks" )
        self.assertIn( "Additional Context", msg )
        self.assertIn( "comparing with React Hooks", msg )

    def test_each_audience_injects_guidelines( self ):
        for audience, marker in [
            ( "beginner", "Target Audience: Beginner" ),
            ( "general",  "Target Audience: General" ),
            ( "expert",   "Target Audience: Expert" ),
            ( "academic", "Target Audience: Academic" ),
        ]:
            with self.subTest( audience=audience ):
                self.assertIn( marker, self._base( audience=audience ) )

    def test_unknown_audience_falls_back_to_academic( self ):
        self.assertIn( "Target Audience: Academic", self._base( audience="nonsense" ) )

    def test_audience_context_injected( self ):
        msg = self._base( audience="expert", audience_context="ML engineer with PyTorch experience" )
        self.assertIn( "Additional Audience Context", msg )
        self.assertIn( "ML engineer with PyTorch experience", msg )


class TestParseSubagentResponse( unittest.TestCase ):

    def test_plain_json( self ):
        out = parse_subagent_response( '{"confidence": 0.85, "sources": []}' )
        self.assertEqual( out[ "confidence" ], 0.85 )

    def test_json_fenced( self ):
        out = parse_subagent_response( '```json\n{"findings": "x"}\n```' )
        self.assertEqual( out[ "findings" ], "x" )

    def test_bare_fenced( self ):
        out = parse_subagent_response( '```\n{"gaps": ["g"]}\n```' )
        self.assertEqual( out[ "gaps" ], [ "g" ] )

    def test_trailing_fence_only( self ):
        out = parse_subagent_response( '{"confidence": 0.5}\n```' )
        self.assertEqual( out[ "confidence" ], 0.5 )

    def test_invalid_raises_valueerror( self ):
        with self.assertRaises( ValueError ):
            parse_subagent_response( "not json" )


if __name__ == "__main__":
    unittest.main()
