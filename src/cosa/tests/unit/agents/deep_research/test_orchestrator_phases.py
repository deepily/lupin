"""
Unit tests for cosa.agents.deep_research.orchestrator — do_all_async PHASES split.

NEW FILE 2026-05-31 by Extra 2 🪨 (CoSA coverage campaign, deep_research SDK/network
tier — the finale). Covers the do_all_async state machine: the 6 phases (clarify →
plan → parallel-research → synthesize → review → cite), the asyncio.gather result
filtering (SubagentFinding / Exception / NEITHER-type fall-through), all 4 _check_stop
checkpoints, the plan-choice arms (Execute / Cancel / Modify scope), the review
revise-vs-skip arms, and the top-level except handler.

The private async methods + cosa_interface are mocked so do_all_async's orchestration
branches are exercised in isolation (the methods themselves are covered in
test_orchestrator_helpers.py). __init__ patches ResearchAPIClient + CostTracker → NO
real SDK / firewalled key. ZERO network/voice/spend.

Must run via run-sdk-cov.sh.
"""

import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch, MagicMock, AsyncMock

import cosa.agents.deep_research.orchestrator as orch
from cosa.agents.deep_research.state import (
    OrchestratorState, ResearchPlan, SubQuery, SubagentFinding, SourceReference,
)


def a_finding( idx=0, topic="t" ):
    return SubagentFinding(
        subquery_index=idx, subquery_topic=topic, findings="f",
        sources=[ SourceReference( url="u", title="T", snippet="s",
                                   relevance_score=0.5, source_quality="unknown", access_date="" ) ],
        confidence=0.8, gaps=[ ], quality_notes="",
    )


def two_subquery_plan():
    return ResearchPlan(
        complexity="moderate",
        subqueries=[ SubQuery( topic="t0", objective="o0", output_format="summary" ),
                     SubQuery( topic="t1", objective="o1", output_format="summary" ) ],
        estimated_subagents=2, rationale="the rationale",
    )


@contextmanager
def make_agent( debug=False ):
    with patch.object( orch, "ResearchAPIClient", return_value=MagicMock() ), \
         patch.object( orch, "CostTracker", return_value=MagicMock() ):
        agent = orch.ResearchOrchestratorAgent( query="research q", user_id="u1", debug=debug )
        yield agent


def wire( agent, clarification=None, plan="default", subquery_results=None,
          synth="DRAFT", revised="REVISED", final="FINAL" ):
    agent._clarify_query_async = AsyncMock(
        return_value=clarification or { "needs_feedback": False, "understood_query": "uq" }
    )
    if plan == "default":
        plan = two_subquery_plan()
    agent._create_plan_async = AsyncMock( return_value=plan )
    if subquery_results is None:
        subquery_results = [ a_finding( 0 ), a_finding( 1 ) ]
    agent._research_subquery_async = AsyncMock( side_effect=subquery_results )
    agent._synthesize_async = AsyncMock( return_value=synth )
    agent._revise_report_async = AsyncMock( return_value=revised )
    agent._add_citations_async = AsyncMock( return_value=final )


@contextmanager
def cosa_patches( get_feedback="looks great", plan_choice="Execute plan", is_approval=True ):
    with patch.object( orch.cosa_interface, "notify_progress", new=AsyncMock() ) as np, \
         patch.object( orch.cosa_interface, "get_feedback", new=AsyncMock( return_value=get_feedback ) ) as gf, \
         patch.object( orch.cosa_interface, "present_choices",
                       new=AsyncMock( return_value={ "answers": { "Plan": plan_choice } } ) ) as pc, \
         patch.object( orch.cosa_interface, "is_approval", return_value=is_approval ) as ia:
        yield SimpleNamespace( notify=np, get_feedback=gf, present_choices=pc, is_approval=ia )


class TestDoAllAsync( unittest.IsolatedAsyncioTestCase ):

    async def test_happy_full_path( self ):
        with make_agent( debug=True ) as agent:
            wire( agent )
            with cosa_patches( plan_choice="Execute plan", is_approval=True ):
                result = await agent.do_all_async()
        self.assertEqual( result, "FINAL" )
        self.assertEqual( agent.state, OrchestratorState.COMPLETED )
        self.assertEqual( len( agent.findings ), 2 )
        agent._revise_report_async.assert_not_awaited()   # feedback was an approval

    async def test_clarification_needs_feedback( self ):
        with make_agent() as agent:
            wire( agent, clarification={ "needs_feedback": True, "question": "Clarify?" } )
            with cosa_patches() as c:
                result = await agent.do_all_async()
        self.assertEqual( result, "FINAL" )
        # get_feedback called for clarification AND for draft review.
        self.assertGreaterEqual( c.get_feedback.await_count, 2 )

    async def test_plan_choice_cancel_returns_none( self ):
        with make_agent() as agent:
            wire( agent )
            with cosa_patches( plan_choice="Cancel" ):
                result = await agent.do_all_async()
        self.assertIsNone( result )
        self.assertEqual( agent.state, OrchestratorState.STOPPED )

    async def test_plan_choice_modify_scope_continues( self ):
        with make_agent() as agent:
            wire( agent )
            with cosa_patches( plan_choice="Modify scope" ):
                result = await agent.do_all_async()
        self.assertEqual( result, "FINAL" )

    async def test_plan_none_skips_research( self ):
        # _create_plan_async None → num_subqueries else-0 + 209 plan-falsy skip gather.
        with make_agent() as agent:
            wire( agent, plan=None )
            with cosa_patches():
                result = await agent.do_all_async()
        self.assertEqual( result, "FINAL" )
        agent._research_subquery_async.assert_not_called()

    async def test_empty_subqueries_skips_gather( self ):
        empty_plan = ResearchPlan( complexity="simple", subqueries=[ ], estimated_subagents=0, rationale="r" )
        with make_agent() as agent:
            wire( agent, plan=empty_plan )
            with cosa_patches():
                result = await agent.do_all_async()
        self.assertEqual( result, "FINAL" )

    async def test_gather_exception_filtered( self ):
        # one subquery yields a SubagentFinding, the other raises → Exception branch.
        with make_agent( debug=True ) as agent:
            wire( agent, subquery_results=[ a_finding( 0 ), ValueError( "subquery boom" ) ] )
            with cosa_patches():
                result = await agent.do_all_async()
        self.assertEqual( result, "FINAL" )
        self.assertEqual( len( agent.findings ), 1 )   # exception filtered out

    async def test_gather_exception_filtered_no_debug( self ):
        # debug=False covers the 226->221 `if self.debug` false arm in the filter loop.
        with make_agent( debug=False ) as agent:
            wire( agent, subquery_results=[ a_finding( 0 ), ValueError( "boom" ) ] )
            with cosa_patches():
                result = await agent.do_all_async()
        self.assertEqual( result, "FINAL" )
        self.assertEqual( len( agent.findings ), 1 )

    async def test_gather_neither_type_fall_through( self ):
        # gather yields values that are neither SubagentFinding nor Exception → both
        # isinstance arms false (Tiberius's neither-type fall-through arc).
        with make_agent() as agent:
            wire( agent, subquery_results=[ "not a finding", MagicMock() ] )
            with cosa_patches():
                result = await agent.do_all_async()
        self.assertEqual( result, "FINAL" )
        self.assertEqual( len( agent.findings ), 0 )

    async def test_review_feedback_triggers_revision( self ):
        with make_agent() as agent:
            wire( agent )
            with cosa_patches( get_feedback="please add a section", is_approval=False ):
                result = await agent.do_all_async()
        self.assertEqual( result, "FINAL" )
        agent._revise_report_async.assert_awaited_once()

    async def test_review_no_feedback_skips_revision( self ):
        with make_agent() as agent:
            wire( agent )
            with cosa_patches( get_feedback=None ):
                result = await agent.do_all_async()
        self.assertEqual( result, "FINAL" )
        agent._revise_report_async.assert_not_awaited()

    # --- the four _check_stop checkpoints (162, 200, 237, 265) -------------
    async def test_stop_after_clarification( self ):
        with make_agent() as agent:
            wire( agent )
            agent._check_stop = MagicMock( side_effect=[ True ] )
            with cosa_patches():
                result = await agent.do_all_async()
        self.assertIsNone( result )
        self.assertEqual( agent.state, OrchestratorState.STOPPED )

    async def test_stop_after_plan_approval( self ):
        with make_agent() as agent:
            wire( agent )
            agent._check_stop = MagicMock( side_effect=[ False, True ] )
            with cosa_patches():
                result = await agent.do_all_async()
        self.assertIsNone( result )

    async def test_stop_after_research( self ):
        with make_agent() as agent:
            wire( agent )
            agent._check_stop = MagicMock( side_effect=[ False, False, True ] )
            with cosa_patches():
                result = await agent.do_all_async()
        self.assertIsNone( result )

    async def test_stop_after_review( self ):
        with make_agent() as agent:
            wire( agent )
            agent._check_stop = MagicMock( side_effect=[ False, False, False, True ] )
            with cosa_patches():
                result = await agent.do_all_async()
        self.assertIsNone( result )

    async def test_exception_path_sets_failed_and_reraises( self ):
        with make_agent() as agent:
            wire( agent )
            agent._synthesize_async = AsyncMock( side_effect=RuntimeError( "synth boom" ) )
            with cosa_patches():
                with self.assertRaises( RuntimeError ):
                    await agent.do_all_async()
        self.assertEqual( agent.state, OrchestratorState.FAILED )


if __name__ == "__main__":
    unittest.main()
