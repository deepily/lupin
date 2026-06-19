"""
Unit tests for cosa.agents.deep_research.prompts.synthesis.

NEW FILE 2026-05-31 by Rio ⚡ (CoSA coverage campaign, deep_research lane). Pure
prompt-construction logic — no network/LLM. Covers the synthesis user-message
builder (plan_summary + audience + audience_context branches AND every per-finding
optional-field arc: findings/confidence/gaps-list-vs-str/sources-with-defaults+
truncation/empty-finding), plus the revision prompt + revision system prompt.
"""

import unittest

from cosa.agents.deep_research.prompts.synthesis import (
    SYNTHESIS_SYSTEM_PROMPT,
    SYNTHESIS_WITH_FEEDBACK_PROMPT,
    get_synthesis_prompt,
    get_revision_prompt,
    get_revision_system_prompt,
)


class TestSystemPrompts( unittest.TestCase ):

    def test_synthesis_system_prompt_shape( self ):
        self.assertGreater( len( SYNTHESIS_SYSTEM_PROMPT ), 1000 )
        self.assertIn( "Executive Summary", SYNTHESIS_SYSTEM_PROMPT )

    def test_revision_system_prompt_returned( self ):
        self.assertIs( get_revision_system_prompt(), SYNTHESIS_WITH_FEEDBACK_PROMPT )
        self.assertIn( "{feedback}", SYNTHESIS_WITH_FEEDBACK_PROMPT )


class TestGetSynthesisPrompt( unittest.TestCase ):

    def _full_finding( self ):
        return {
            "subquery_topic" : "React performance",
            "findings"       : "uses virtual DOM",
            "confidence"     : 0.9,
            "gaps"           : [ "gap a", "gap b" ],
            "sources"        : [ { "title": "React Docs", "url": "https://react.dev", "source_quality": "primary" } ],
        }

    def test_full_finding_all_fields_rendered( self ):
        msg = get_synthesis_prompt( "Compare frameworks", [ self._full_finding() ] )
        self.assertIn( "Subagent 1: React performance", msg )
        self.assertIn( "**Findings**: uses virtual DOM", msg )
        self.assertIn( "**Confidence**: 0.9", msg )
        self.assertIn( "**Gaps**: gap a; gap b", msg )       # list joined with "; "
        self.assertIn( "[React Docs](https://react.dev) (primary)", msg )

    def test_empty_finding_uses_defaults_and_skips_optionals( self ):
        msg = get_synthesis_prompt( "q", [ {} ] )
        self.assertIn( "Subagent 1: Unknown Topic", msg )    # subquery_topic default
        self.assertNotIn( "**Findings**", msg )              # all optional blocks skipped
        self.assertNotIn( "**Confidence**", msg )
        self.assertNotIn( "**Gaps**", msg )
        self.assertNotIn( "**Sources**", msg )

    def test_gaps_as_string_not_joined( self ):
        f = { "subquery_topic": "T", "gaps": "single gap string" }
        msg = get_synthesis_prompt( "q", [ f ] )
        self.assertIn( "**Gaps**: single gap string", msg )  # non-list → used as-is

    def test_sources_defaults_and_truncated_to_five( self ):
        sources = [ { } for _ in range( 7 ) ]                # 7 sources, all missing keys
        f = { "subquery_topic": "T", "sources": sources }
        msg = get_synthesis_prompt( "q", [ f ] )
        # defaults: Untitled / "" / unknown
        self.assertIn( "[Untitled]() (unknown)", msg )
        # only top 5 rendered
        self.assertEqual( msg.count( "[Untitled]() (unknown)" ), 5 )

    def test_plan_summary_present_and_absent( self ):
        with_plan = get_synthesis_prompt( "q", [], plan_summary="parallel approach" )
        self.assertIn( "Research Approach", with_plan )
        self.assertIn( "parallel approach", with_plan )
        without_plan = get_synthesis_prompt( "q", [] )
        self.assertNotIn( "Research Approach", without_plan )

    def test_each_audience_and_unknown_fallback( self ):
        for audience, marker in [
            ( "beginner", "Target Audience: Beginner" ),
            ( "general",  "Target Audience: General" ),
            ( "expert",   "Target Audience: Expert" ),
            ( "academic", "Target Audience: Academic" ),
        ]:
            with self.subTest( audience=audience ):
                self.assertIn( marker, get_synthesis_prompt( "q", [], audience=audience ) )
        self.assertIn( "Target Audience: Academic", get_synthesis_prompt( "q", [], audience="nonsense" ) )

    def test_audience_context_injected( self ):
        msg = get_synthesis_prompt( "q", [], audience="expert", audience_context="Senior architect" )
        self.assertIn( "Additional Audience Context", msg )
        self.assertIn( "Senior architect", msg )


class TestGetRevisionPrompt( unittest.TestCase ):

    def test_embeds_report_and_feedback( self ):
        msg = get_revision_prompt( "# Draft\n\nbody", "add benchmarks" )
        self.assertIn( "# Draft", msg )
        self.assertIn( "add benchmarks", msg )
        self.assertIn( "revised report", msg )


if __name__ == "__main__":
    unittest.main()
