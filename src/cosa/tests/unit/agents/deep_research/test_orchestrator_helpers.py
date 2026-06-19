"""
Unit tests for cosa.agents.deep_research.orchestrator — HELPERS split.

NEW FILE 2026-05-31 by Extra 2 🪨 (CoSA coverage campaign, deep_research SDK/network
tier — the finale). Covers __init__, the sync state helpers (get_state, pause, resume,
stop, _check_stop, _handle_stop, _calculate_progress) and the private async API methods
(_clarify_query_async, _create_plan_async, _research_subquery_async, _synthesize_async,
_revise_report_async, _add_citations_async, _generate_abstract_async) — each on both its
success arm and its except fallback arm.

The do_all_async phase orchestration lives in test_orchestrator_phases.py.

COST-SAFETY: orchestrator.__init__ constructs a real ResearchAPIClient + CostTracker;
BOTH are patched at the module boundary so NO real AsyncAnthropic / firewalled key is
ever touched. The prompts.* parse_* functions are patched (already 100% in the prompts
tier) so these tests assert the orchestrator's call→parse→map logic, not parser internals.
ZERO network/voice/spend.

Must run via run-sdk-cov.sh (orchestrator imports the SDK chain).
"""

import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch, MagicMock, AsyncMock

import cosa.agents.deep_research.orchestrator as orch
from cosa.agents.deep_research.state import (
    OrchestratorState, ResearchPlan, SubQuery, SubagentFinding, SourceReference,
)


@contextmanager
def make_agent( query="research q", user_id="u1", config=None, budget=None,
                debug=False, verbose=False ):
    """Construct an orchestrator with ResearchAPIClient + CostTracker mocked."""
    with patch.object( orch, "ResearchAPIClient" ) as APICls, \
         patch.object( orch, "CostTracker" ) as CTCls:
        api = MagicMock()
        CTCls.return_value = MagicMock()
        APICls.return_value = api
        agent = orch.ResearchOrchestratorAgent(
            query=query, user_id=user_id, config=config,
            budget_limit_usd=budget, debug=debug, verbose=verbose,
        )
        yield agent, api


def a_finding( idx=0, topic="t", n_sources=1 ):
    sources = [ SourceReference( url=f"u{i}", title="T", snippet="s",
                                 relevance_score=0.5, source_quality="unknown", access_date="" )
                for i in range( n_sources ) ]
    return SubagentFinding(
        subquery_index=idx, subquery_topic=topic, findings="f",
        sources=sources, confidence=0.8, gaps=[ ], quality_notes="",
    )


class TestInit( unittest.TestCase ):

    def test_init_defaults_and_state( self ):
        with make_agent( debug=True ) as ( agent, api ):
            self.assertEqual( agent.state, OrchestratorState.CLARIFYING )
            self.assertEqual( agent.findings, [ ] )
            self.assertFalse( agent._pause_requested )
            self.assertFalse( agent._stop_requested )
            self.assertIs( agent.api_client, api )

    def test_init_with_explicit_config( self ):
        from cosa.agents.deep_research.config import ResearchConfig
        cfg = ResearchConfig()
        with make_agent( config=cfg ) as ( agent, _api ):
            self.assertIs( agent.config, cfg )


class TestSyncHelpers( unittest.TestCase ):

    def test_get_state_shape( self ):
        with make_agent() as ( agent, _api ):
            agent.findings = [ a_finding() ]
            t = MagicMock(); t.done.return_value=True; t.cancelled.return_value=False
            agent.sub_tasks = [ t ]
            state = agent.get_state()
        self.assertEqual( state[ "state" ], "clarifying" )
        self.assertEqual( state[ "findings_count" ], 1 )
        self.assertEqual( len( state[ "sub_tasks" ] ), 1 )

    def test_check_stop( self ):
        with make_agent() as ( agent, _api ):
            self.assertFalse( agent._check_stop() )
            agent._stop_requested = True
            self.assertTrue( agent._check_stop() )

    def test_calculate_progress_known_and_default( self ):
        with make_agent() as ( agent, _api ):
            self.assertEqual( agent._calculate_progress(), 10 )   # CLARIFYING
            agent.state = OrchestratorState.COMPLETED
            self.assertEqual( agent._calculate_progress(), 100 )
            agent.state = OrchestratorState.FAILED
            self.assertEqual( agent._calculate_progress(), 0 )


class TestControlMethods( unittest.IsolatedAsyncioTestCase ):

    async def test_pause( self ):
        with make_agent() as ( agent, _api ):
            self.assertTrue( await agent.pause() )
            self.assertTrue( agent._pause_requested )

    async def test_resume_when_paused( self ):
        with make_agent() as ( agent, _api ):
            agent.state = OrchestratorState.PAUSED
            self.assertTrue( await agent.resume() )
            self.assertFalse( agent._pause_requested )

    async def test_resume_when_not_paused( self ):
        with make_agent() as ( agent, _api ):
            self.assertFalse( await agent.resume() )

    async def test_stop_cancels_unfinished_tasks( self ):
        with make_agent() as ( agent, _api ):
            t_running = MagicMock(); t_running.done.return_value = False
            t_done    = MagicMock(); t_done.done.return_value = True
            agent.sub_tasks = [ t_running, t_done ]
            agent.findings = [ a_finding() ]
            result = await agent.stop()
            t_running.cancel.assert_called_once()
            t_done.cancel.assert_not_called()
            self.assertEqual( agent.state, OrchestratorState.STOPPED )
            self.assertEqual( result[ "stopped_at" ], "stopped" )

    async def test_handle_stop( self ):
        with make_agent() as ( agent, _api ):
            with patch.object( orch.cosa_interface, "notify_progress", new=AsyncMock() ):
                self.assertIsNone( await agent._handle_stop() )
            self.assertEqual( agent.state, OrchestratorState.STOPPED )


class TestClarifyQueryAsync( unittest.IsolatedAsyncioTestCase ):

    async def test_success_maps_fields( self ):
        with make_agent() as ( agent, api ):
            api.call_lead_agent = AsyncMock( return_value=SimpleNamespace( content="raw" ) )
            with patch.object( orch.clarification, "parse_clarification_response",
                               return_value={ "needs_clarification": True, "question": "Q?",
                                              "understood_query": "UQ", "ambiguities": [ "a" ],
                                              "confidence": 0.9 } ):
                result = await agent._clarify_query_async()
        self.assertTrue( result[ "needs_feedback" ] )
        self.assertEqual( result[ "question" ], "Q?" )
        self.assertEqual( result[ "understood_query" ], "UQ" )
        self.assertEqual( agent.metrics[ "api_calls" ], 1 )

    async def test_exception_failsafe( self ):
        with make_agent( debug=True ) as ( agent, api ):
            api.call_lead_agent = AsyncMock( side_effect=RuntimeError( "boom" ) )
            result = await agent._clarify_query_async()
        self.assertFalse( result[ "needs_feedback" ] )
        self.assertEqual( result[ "understood_query" ], agent.query )


class TestCreatePlanAsync( unittest.IsolatedAsyncioTestCase ):

    async def test_success_builds_plan( self ):
        with make_agent() as ( agent, api ):
            api.call_lead_agent = AsyncMock( return_value=SimpleNamespace( content="raw" ) )
            agent._research_state[ "clarification_response" ] = "clarified text"
            with patch.object( orch.planning, "parse_planning_response",
                               return_value={ "complexity": "complex",
                                              "subqueries": [ { "topic": "t1", "objective": "o1" },
                                                              { "topic": "t2" } ],
                                              "rationale": "r" } ):
                plan = await agent._create_plan_async()
        self.assertEqual( plan.complexity, "complex" )
        self.assertEqual( len( plan.subqueries ), 2 )
        self.assertEqual( plan.subqueries[ 0 ].topic, "t1" )

    async def test_success_without_clarification_uses_query( self ):
        # clarification_response absent → `or self.query` arm.
        with make_agent() as ( agent, api ):
            api.call_lead_agent = AsyncMock( return_value=SimpleNamespace( content="raw" ) )
            with patch.object( orch.planning, "parse_planning_response",
                               return_value={ "subqueries": [ { "topic": "t1" } ] } ):
                plan = await agent._create_plan_async()
        self.assertEqual( len( plan.subqueries ), 1 )

    async def test_exception_fallback_single_query_plan( self ):
        with make_agent( debug=True ) as ( agent, api ):
            api.call_lead_agent = AsyncMock( side_effect=RuntimeError( "boom" ) )
            plan = await agent._create_plan_async()
        self.assertEqual( plan.complexity, "simple" )
        self.assertEqual( len( plan.subqueries ), 1 )
        self.assertEqual( plan.subqueries[ 0 ].topic, agent.query )


class TestResearchSubqueryAsync( unittest.IsolatedAsyncioTestCase ):

    def _sq( self ):
        return SubQuery( topic="quantum", objective="explain", output_format="summary" )

    async def test_success_builds_finding( self ):
        # debug=False covers the 549->552 `if self.debug` false arm (the exception
        # test below covers the true arm + the except-path debug print).
        with make_agent( debug=False ) as ( agent, api ):
            api.call_subagent = AsyncMock( return_value=SimpleNamespace( content="raw" ) )
            with patch.object( orch.subagent, "parse_subagent_response",
                               return_value={ "findings": "F", "confidence": 0.7,
                                              "sources": [ { "url": "u", "title": "T" } ],
                                              "gaps": [ ], "quality_notes": "qn" } ):
                finding = await agent._research_subquery_async( self._sq(), 0 )
        self.assertEqual( finding.findings, "F" )
        self.assertEqual( len( finding.sources ), 1 )
        self.assertEqual( finding.confidence, 0.7 )

    async def test_exception_returns_failure_finding( self ):
        with make_agent( debug=True ) as ( agent, api ):
            api.call_subagent = AsyncMock( side_effect=RuntimeError( "net down" ) )
            finding = await agent._research_subquery_async( self._sq(), 3 )
        self.assertEqual( finding.confidence, 0.0 )
        self.assertEqual( finding.subquery_index, 3 )
        self.assertIn( "Research failed", finding.findings )


class TestSynthesizeAsync( unittest.IsolatedAsyncioTestCase ):

    async def test_success_returns_content( self ):
        with make_agent() as ( agent, api ):
            agent.findings = [ a_finding( n_sources=2 ) ]
            agent._research_state[ "plan" ] = ResearchPlan(
                complexity="moderate", subqueries=[ ], estimated_subagents=0, rationale="the plan",
            )
            api.call_lead_agent = AsyncMock( return_value=SimpleNamespace( content="THE REPORT" ) )
            report = await agent._synthesize_async()
        self.assertEqual( report, "THE REPORT" )

    async def test_exception_concatenates_findings( self ):
        with make_agent( debug=True ) as ( agent, api ):
            agent.findings = [ a_finding( topic="alpha" ) ]
            api.call_lead_agent = AsyncMock( side_effect=RuntimeError( "boom" ) )
            report = await agent._synthesize_async()
        self.assertIn( "Research Report", report )
        self.assertIn( "alpha", report )


class TestReviseReportAsync( unittest.IsolatedAsyncioTestCase ):

    async def test_success( self ):
        with make_agent() as ( agent, api ):
            api.call_lead_agent = AsyncMock( return_value=SimpleNamespace( content="REVISED" ) )
            result = await agent._revise_report_async( "old", "add detail" )
        self.assertEqual( result, "REVISED" )

    async def test_exception_returns_report_with_note( self ):
        with make_agent( debug=True ) as ( agent, api ):
            api.call_lead_agent = AsyncMock( side_effect=RuntimeError( "boom" ) )
            result = await agent._revise_report_async( "old report", "feedback text" )
        self.assertIn( "old report", result )
        self.assertIn( "feedback text", result )


class TestAddCitationsAsync( unittest.IsolatedAsyncioTestCase ):

    async def test_passthrough( self ):
        with make_agent() as ( agent, _api ):
            self.assertEqual( await agent._add_citations_async( "report body" ), "report body" )


class TestGenerateAbstractAsync( unittest.IsolatedAsyncioTestCase ):
    """ORPHANED METHOD (zero callers repo-wide — reported to Tiberius). Tested for
    coverage via direct call; success + both exception-fallback arms."""

    async def test_success( self ):
        with make_agent() as ( agent, api ):
            api.call_lead_agent = AsyncMock( return_value=SimpleNamespace( content="  Abstract.  " ) )
            result = await agent._generate_abstract_async( "report" )
        self.assertEqual( result, "Abstract." )

    async def test_exception_fallback_paragraph( self ):
        with make_agent( debug=True ) as ( agent, api ):
            api.call_lead_agent = AsyncMock( side_effect=RuntimeError( "boom" ) )
            report = "# Heading\n\nFirst real paragraph here.\n\nmore"
            result = await agent._generate_abstract_async( report )
        self.assertTrue( result.startswith( "First real paragraph" ) )

    async def test_exception_fallback_default( self ):
        with make_agent() as ( agent, api ):
            api.call_lead_agent = AsyncMock( side_effect=RuntimeError( "boom" ) )
            result = await agent._generate_abstract_async( "# Only\n\n## Headers" )
        self.assertEqual( result, "Research report generated." )


if __name__ == "__main__":
    unittest.main()
