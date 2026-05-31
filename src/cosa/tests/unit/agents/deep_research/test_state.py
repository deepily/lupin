"""
Unit tests for cosa.agents.deep_research.state.

NEW FILE 2026-05-31 by Rio ⚡ (CoSA coverage campaign, deep_research lane). Pure
schema module — enums, Pydantic models, and create_initial_state(). No network/LLM.
Validation-constraint assertions are discriminating (out-of-range inputs must raise).
"""

import unittest

from pydantic import ValidationError

from cosa.agents.deep_research.state import (
    OrchestratorState,
    JobSubState,
    SubQuery,
    ResearchPlan,
    SourceReference,
    SubagentFinding,
    ClarificationDecision,
    Citation,
    create_initial_state,
)


class TestEnums( unittest.TestCase ):

    def test_orchestrator_state_values_and_count( self ):
        self.assertEqual( OrchestratorState.CLARIFYING.value, "clarifying" )
        self.assertEqual( OrchestratorState.COMPLETED.value, "completed" )
        self.assertEqual( OrchestratorState.STOPPED.value, "stopped" )
        self.assertEqual( len( OrchestratorState ), 13 )

    def test_job_substate_values_and_count( self ):
        self.assertEqual( JobSubState.EXECUTING.value, "executing" )
        self.assertEqual( JobSubState.WAITING_FOR_HUMAN.value, "waiting_for_human" )
        self.assertEqual( len( JobSubState ), 5 )


class TestSubQuery( unittest.TestCase ):

    def test_defaults( self ):
        sq = SubQuery( topic="t", objective="o", output_format="list" )
        self.assertEqual( sq.priority, 1 )
        self.assertEqual( sq.tools_to_use, [ "web_search", "web_fetch" ] )
        self.assertIsNone( sq.depends_on )

    def test_priority_bounds_enforced( self ):
        with self.assertRaises( ValidationError ):
            SubQuery( topic="t", objective="o", output_format="l", priority=0 )    # < 1
        with self.assertRaises( ValidationError ):
            SubQuery( topic="t", objective="o", output_format="l", priority=6 )    # > 5
        self.assertEqual( SubQuery( topic="t", objective="o", output_format="l", priority=5 ).priority, 5 )


class TestResearchPlan( unittest.TestCase ):

    def test_valid_plan( self ):
        sq   = SubQuery( topic="t", objective="o", output_format="l" )
        plan = ResearchPlan( complexity="moderate", subqueries=[ sq ], estimated_subagents=1, rationale="r" )
        self.assertEqual( plan.complexity, "moderate" )
        self.assertEqual( plan.estimated_duration_minutes, 5 )                     # default

    def test_invalid_complexity_rejected( self ):
        with self.assertRaises( ValidationError ):
            ResearchPlan( complexity="trivial", subqueries=[], estimated_subagents=0, rationale="r" )


class TestSourceReference( unittest.TestCase ):

    def test_defaults_and_quality( self ):
        src = SourceReference( url="https://x", title="T", relevance_score=0.85 )
        self.assertEqual( src.source_quality, "unknown" )
        self.assertEqual( src.snippet, "" )

    def test_relevance_score_bounds( self ):
        with self.assertRaises( ValidationError ):
            SourceReference( url="u", title="t", relevance_score=1.5 )
        with self.assertRaises( ValidationError ):
            SourceReference( url="u", title="t", relevance_score=-0.1 )


class TestSubagentFinding( unittest.TestCase ):

    def test_defaults( self ):
        f = SubagentFinding( subquery_index=0, subquery_topic="t", findings="f", confidence=0.9 )
        self.assertEqual( f.gaps, [] )
        self.assertEqual( f.sources, [] )
        self.assertEqual( f.quality_notes, "" )

    def test_confidence_bounds( self ):
        with self.assertRaises( ValidationError ):
            SubagentFinding( subquery_index=0, subquery_topic="t", findings="f", confidence=2.0 )


class TestClarificationAndCitation( unittest.TestCase ):

    def test_clarification_decision_defaults( self ):
        d = ClarificationDecision( needs_clarification=False, understood_query="q" )
        self.assertIsNone( d.question )
        self.assertEqual( d.ambiguities, [] )

    def test_citation_embeds_source( self ):
        src = SourceReference( url="https://x", title="T", relevance_score=0.5 )
        c   = Citation( claim="claim", source=src, location_in_report="p1" )
        self.assertEqual( c.source.url, "https://x" )


class TestCreateInitialState( unittest.TestCase ):

    def test_initial_state_defaults( self ):
        state = create_initial_state( "What is quantum computing?" )
        self.assertEqual( state[ "original_query" ], "What is quantum computing?" )
        self.assertEqual( state[ "clarification_rounds" ], 0 )
        self.assertIs( state[ "plan_approved" ], False )
        self.assertIs( state[ "needs_clarification" ], False )
        self.assertIsNone( state[ "plan" ] )
        self.assertIsNone( state[ "final_report" ] )
        self.assertEqual( state[ "active_subqueries" ], [] )
        self.assertEqual( state[ "subagent_findings" ], [] )
        self.assertEqual( state[ "citations" ], [] )
        self.assertEqual( state[ "research_metadata" ], {} )
        self.assertEqual( state[ "research_iterations" ], 0 )

    def test_distinct_calls_have_independent_collections( self ):
        a = create_initial_state( "q1" )
        b = create_initial_state( "q2" )
        a[ "active_subqueries" ].append( "x" )
        self.assertEqual( b[ "active_subqueries" ], [] )                            # no shared mutable default


if __name__ == "__main__":
    unittest.main()
