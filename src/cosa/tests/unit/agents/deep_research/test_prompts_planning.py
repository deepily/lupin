"""
Unit tests for cosa.agents.deep_research.prompts.planning.

NEW FILE 2026-05-31 by Rio ⚡ (CoSA coverage campaign, deep_research lane). Pure
prompt-construction + JSON-parsing logic — no network/LLM. Covers the planning
user-message builder (clarified-query + audience + context branches), the response
parser's markdown-fence arms, and the theme-clustering prompt builder.
"""

import unittest

from cosa.agents.deep_research.prompts.planning import (
    PLANNING_SYSTEM_PROMPT,
    THEME_CLUSTERING_PROMPT,
    AUDIENCE_GUIDELINES,
    get_planning_prompt,
    parse_planning_response,
    get_theme_clustering_prompt,
)


class TestSystemPrompts( unittest.TestCase ):

    def test_planning_system_prompt_shape( self ):
        self.assertGreater( len( PLANNING_SYSTEM_PROMPT ), 1000 )
        self.assertIn( "complexity", PLANNING_SYSTEM_PROMPT )
        self.assertIn( "subqueries", PLANNING_SYSTEM_PROMPT )

    def test_theme_clustering_prompt_shape( self ):
        self.assertGreater( len( THEME_CLUSTERING_PROMPT ), 500 )
        self.assertIn( "themes", THEME_CLUSTERING_PROMPT )
        self.assertIn( "subquery_indices", THEME_CLUSTERING_PROMPT )


class TestGetPlanningPrompt( unittest.TestCase ):

    def test_no_clarified_uses_original_query( self ):
        msg = get_planning_prompt( "Compare Python and JavaScript" )
        self.assertIn( "Compare Python and JavaScript", msg )
        self.assertIn( "Maximum subagents: 10", msg )
        self.assertNotIn( "Original query", msg )            # no clarified → no original line

    def test_clarified_distinct_adds_original_line( self ):
        msg = get_planning_prompt( query="Tell me about AI", clarified_query="State of generative AI in 2025" )
        self.assertIn( "State of generative AI in 2025", msg )
        self.assertIn( 'Original query: "Tell me about AI"', msg )

    def test_clarified_equal_to_query_no_original_line( self ):
        # clarified provided but identical → effective uses it, but Original line suppressed
        msg = get_planning_prompt( query="same q", clarified_query="same q" )
        self.assertIn( "same q", msg )
        self.assertNotIn( "Original query", msg )

    def test_each_audience_injects_its_guidelines( self ):
        for audience, marker in [
            ( "beginner", "Target Audience: Beginner" ),
            ( "general",  "Target Audience: General" ),
            ( "expert",   "Target Audience: Expert" ),
            ( "academic", "Target Audience: Academic" ),
        ]:
            with self.subTest( audience=audience ):
                self.assertIn( marker, get_planning_prompt( "q", audience=audience ) )

    def test_unknown_audience_falls_back_to_academic( self ):
        msg = get_planning_prompt( "q", audience="nonsense" )
        self.assertIn( "Target Audience: Academic", msg )    # .get fallback

    def test_audience_context_injected( self ):
        msg = get_planning_prompt( "q", audience="expert", audience_context="AI architect with ML background" )
        self.assertIn( "Additional Audience Context", msg )
        self.assertIn( "AI architect with ML background", msg )

    def test_max_subagents_constraint_reflected( self ):
        msg = get_planning_prompt( "q", max_subagents=3 )
        self.assertIn( "Maximum subagents: 3", msg )


class TestParsePlanningResponse( unittest.TestCase ):

    def test_plain_json( self ):
        out = parse_planning_response( '{"complexity": "simple", "subqueries": []}' )
        self.assertEqual( out[ "complexity" ], "simple" )

    def test_json_fenced( self ):
        out = parse_planning_response( '```json\n{"complexity": "moderate"}\n```' )
        self.assertEqual( out[ "complexity" ], "moderate" )

    def test_bare_fenced( self ):
        out = parse_planning_response( '```\n{"estimated_subagents": 4}\n```' )
        self.assertEqual( out[ "estimated_subagents" ], 4 )

    def test_trailing_fence_only( self ):
        out = parse_planning_response( '{"complexity": "complex"}\n```' )
        self.assertEqual( out[ "complexity" ], "complex" )

    def test_invalid_raises_valueerror( self ):
        with self.assertRaises( ValueError ):
            parse_planning_response( "definitely not json" )


class TestThemeClusteringPrompt( unittest.TestCase ):

    def test_lists_all_subqueries( self ):
        subs = [
            { "topic": "React features", "objective": "Summarize React" },
            { "topic": "Vue features", "objective": "Summarize Vue" },
            { "topic": "Performance", "objective": "Compare benchmarks" },
        ]
        out = get_theme_clustering_prompt( subs )
        self.assertIn( "3 research topics", out )
        self.assertIn( "React features", out )
        self.assertIn( "2. Performance", out )               # 0-indexed enumeration

    def test_missing_keys_use_defaults( self ):
        # 'topic' absent → "Unknown"; 'objective' absent → "" (truncated [:60] of "")
        out = get_theme_clustering_prompt( [ {} ] )
        self.assertIn( "0. Unknown:", out )

    def test_objective_truncated_to_60_chars( self ):
        long_obj = "x" * 100
        out = get_theme_clustering_prompt( [ { "topic": "T", "objective": long_obj } ] )
        self.assertIn( "x" * 60, out )
        self.assertNotIn( "x" * 61, out )


if __name__ == "__main__":
    unittest.main()
