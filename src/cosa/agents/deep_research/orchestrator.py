#!/usr/bin/env python3
"""
Research Orchestrator Agent - Top-level coordinator for deep research.

This agent manages the entire research workflow internally as a single
queue entry, yielding control at I/O boundaries via async/await.

Design Pattern: Top-Level Orchestrator
- Single job in queue, multi-phase internal state machine
- Async execution for non-blocking queue behavior
- Queryable state for external monitoring
- Controllable via pause/resume/stop
"""

import asyncio
import time
import logging
from typing import Optional, Any

from .config import ResearchConfig
from .state import (
    OrchestratorState,
    ResearchState,
    ResearchPlan,
    SubQuery,
    SubagentFinding,
    SourceReference,
    create_initial_state
)
from . import cosa_interface
from .api_client import ResearchAPIClient
from .cost_tracker import CostTracker
from .prompts import clarification, planning, subagent, synthesis

logger = logging.getLogger( __name__ )


class ResearchOrchestratorAgent:
    """
    Top-level orchestrator - single job, multi-phase, async execution.

    This is a standalone class (not inheriting from AgentBase) because:
    - AgentBase is synchronous, this is async
    - Different execution model (yields on await vs blocking)
    - Composition over inheritance for COSA integration

    Requires:
        - query is a non-empty string
        - user_id is a valid system identifier

    Ensures:
        - Manages entire research workflow internally
        - Yields control at I/O boundaries (await points)
        - State is queryable via get_state()
        - Can be paused, resumed, or stopped externally
    """

    def __init__(
        self,
        query: str,
        user_id: str,
        config: Optional[ ResearchConfig ] = None,
        budget_limit_usd: Optional[ float ] = None,
        debug: bool = False,
        verbose: bool = False
    ):
        """
        Initialize the research orchestrator.

        Args:
            query: The user's research query
            user_id: System user ID for event routing
            config: Research configuration (uses defaults if None)
            budget_limit_usd: Optional spending cap for research session
            debug: Enable debug output
            verbose: Enable verbose output
        """
        self.query   = query
        self.user_id = user_id
        self.config  = config or ResearchConfig()
        self.debug   = debug
        self.verbose = verbose

        # State management
        self.state      = OrchestratorState.CLARIFYING
        self.sub_tasks  : list[ asyncio.Task ] = []
        self.findings   : list[ SubagentFinding ] = []
        self._pause_requested = False
        self._stop_requested  = False

        # Initialize research state (TypedDict for graph)
        self._research_state = create_initial_state( query )

        # Initialize cost tracking and API client
        self.cost_tracker = CostTracker(
            session_id       = f"research-{user_id}-{int( time.time() )}",
            budget_limit_usd = budget_limit_usd,
            debug            = debug,
        )
        self.api_client = ResearchAPIClient(
            config       = self.config,
            cost_tracker = self.cost_tracker,
            debug        = debug,
            verbose      = verbose,
        )

        # Metrics
        self.metrics = {
            "start_time"  : None,
            "end_time"    : None,
            "tokens_used" : 0,
            "api_calls"   : 0,
        }

        if self.debug: print( f"[ResearchOrchestratorAgent] Initialized for query: {query[:50]}..." )

    async def do_all_async( self ) -> Optional[str]:
        """
        Main execution - yields on I/O, doesn't block other jobs.

        Each `await` is a potential yield point where other jobs can execute.
        This method implements the full research workflow:
        1. Clarification - Understand the query
        2. Planning - Create research strategy
        3. Research - Execute parallel subagents
        4. Synthesis - Combine findings
        5. Review - Get user feedback
        6. Citation - Add sources

        Requires:
            - COSA interface is configured (for human feedback)

        Ensures:
            - Executes complete research workflow
            - Returns final report on success, None on cancellation
            - Updates state throughout execution

        Returns:
            str or None: Final research report, or None if cancelled
        """
        self.metrics[ "start_time" ] = time.time()

        try:
            # =================================================================
            # Phase 1: Clarification
            # =================================================================
            self.state = OrchestratorState.CLARIFYING
            await cosa_interface.notify_progress( "Starting research - analyzing your question..." )

            clarification = await self._clarify_query_async()

            if clarification.get( "needs_feedback" ):
                self.state = OrchestratorState.WAITING_CLARIFICATION
                response = await cosa_interface.get_feedback(
                    clarification.get( "question", "Could you clarify your question?" ),
                    timeout=self.config.feedback_timeout_seconds
                )
                self._research_state[ "clarification_response" ] = response
                self._research_state[ "clarification_rounds" ] += 1
                # TODO: Process clarification response in Phase 2

            if self._check_stop(): return await self._handle_stop()

            # =================================================================
            # Phase 2: Planning
            # =================================================================
            self.state = OrchestratorState.PLANNING
            await cosa_interface.notify_progress( "Creating research plan..." )

            plan = await self._create_plan_async()
            self._research_state[ "plan" ] = plan

            # Get user approval for plan
            self.state = OrchestratorState.WAITING_PLAN_APPROVAL

            num_subqueries = len( plan.subqueries ) if plan else 0
            choice = await cosa_interface.present_choices( questions=[ {
                "question"    : "Research plan ready. How should we proceed?",
                "header"      : "Plan",
                "multiSelect" : False,
                "options"     : [
                    { "label": "Execute plan", "description": f"{num_subqueries} research threads" },
                    { "label": "Modify scope", "description": "Adjust focus or depth" },
                    { "label": "Cancel", "description": "Abort research" }
                ]
            } ] )

            plan_choice = choice.get( "answers", {} ).get( "Plan", "" )

            if plan_choice == "Cancel":
                self.state = OrchestratorState.STOPPED
                return None

            if plan_choice == "Modify scope":
                # TODO: Handle plan modification in Phase 2
                pass

            self._research_state[ "plan_approved" ] = True

            if self._check_stop(): return await self._handle_stop()

            # =================================================================
            # Phase 3: Parallel Research
            # =================================================================
            self.state = OrchestratorState.RESEARCHING
            await cosa_interface.notify_progress( "Starting parallel research..." )

            plan = self._research_state.get( "plan" )
            if plan and plan.subqueries:
                # Create tasks for parallel execution
                self.sub_tasks = [
                    asyncio.create_task( self._research_subquery_async( sq, i ) )
                    for i, sq in enumerate( plan.subqueries )
                ]

                # Execute all subqueries in parallel
                results = await asyncio.gather( *self.sub_tasks, return_exceptions=True )

                # Filter out exceptions and store valid findings
                self.findings = []
                for i, result in enumerate( results ):
                    if isinstance( result, SubagentFinding ):
                        self.findings.append( result )
                    elif isinstance( result, Exception ):
                        logger.error( f"Subquery {i} failed with exception: {result}" )
                        if self.debug:
                            print( f"[ResearchOrchestratorAgent] Subquery {i} exception: {result}" )

                self._research_state[ "subagent_findings" ] = self.findings
                self._research_state[ "total_sources_found" ] = sum(
                    len( f.sources ) for f in self.findings
                )

                if self.debug:
                    print( f"[ResearchOrchestratorAgent] Completed {len( self.findings )}/{len( plan.subqueries )} subqueries" )

            if self._check_stop(): return await self._handle_stop()

            # =================================================================
            # Phase 4: Gathering & Synthesis
            # =================================================================
            self.state = OrchestratorState.GATHERING
            await cosa_interface.notify_progress( "Gathering and analyzing findings..." )

            self.state = OrchestratorState.SYNTHESIZING
            await cosa_interface.notify_progress( "Synthesizing report..." )

            report = await self._synthesize_async()
            self._research_state[ "draft_report" ] = report

            # =================================================================
            # Phase 5: Review
            # =================================================================
            self.state = OrchestratorState.WAITING_DRAFT_REVIEW
            feedback = await cosa_interface.get_feedback(
                "Draft ready. Any feedback or changes needed?",
                timeout=self.config.feedback_timeout_seconds
            )

            if feedback and not cosa_interface.is_approval( feedback ):
                self._research_state[ "human_feedback_on_draft" ] = feedback
                self._research_state[ "draft_revision_count" ] += 1
                report = await self._revise_report_async( report, feedback )

            if self._check_stop(): return await self._handle_stop()

            # =================================================================
            # Phase 6: Citations
            # =================================================================
            self.state = OrchestratorState.CITING
            await cosa_interface.notify_progress( "Adding citations..." )

            final_report = await self._add_citations_async( report )
            self._research_state[ "final_report" ] = final_report

            # =================================================================
            # Completion
            # =================================================================
            self.state = OrchestratorState.COMPLETED
            self.metrics[ "end_time" ] = time.time()
            await cosa_interface.notify_progress( "Research complete!" )

            return final_report

        except Exception as e:
            self.state = OrchestratorState.FAILED
            self.metrics[ "end_time" ] = time.time()
            logger.error( f"Research failed: {e}" )
            await cosa_interface.notify_progress(
                f"Research failed: {str( e )[:100]}",
                priority="urgent"
            )
            raise

    def get_state( self ) -> dict:
        """
        Query current orchestrator state for external monitoring.

        Ensures:
            - Returns dict with phase, progress, sub-task status, metrics

        Returns:
            dict: Current state summary
        """
        return {
            "state"          : self.state.value,
            "progress_pct"   : self._calculate_progress(),
            "sub_tasks"      : [
                {
                    "index"     : i,
                    "done"      : t.done(),
                    "cancelled" : t.cancelled()
                }
                for i, t in enumerate( self.sub_tasks )
            ],
            "findings_count" : len( [ f for f in self.findings if f ] ),
            "metrics"        : self.metrics,
            "query"          : self.query[ :100 ],  # Truncated for safety
        }

    async def pause( self ) -> bool:
        """
        Request graceful pause at next yield point.

        Ensures:
            - Sets pause flag
            - Returns True (pause always accepted)

        Returns:
            bool: True indicating pause requested
        """
        self._pause_requested = True
        return True

    async def resume( self ) -> bool:
        """
        Resume from paused state.

        Ensures:
            - Clears pause flag if in PAUSED state
            - Returns True if resumed, False if not paused

        Returns:
            bool: True if successfully resumed
        """
        if self.state == OrchestratorState.PAUSED:
            self._pause_requested = False
            return True
        return False

    async def stop( self ) -> dict:
        """
        Cancel all sub-tasks and return partial results.

        Ensures:
            - Cancels all running sub-tasks
            - Sets state to STOPPED
            - Returns partial findings

        Returns:
            dict: Partial results including findings and stop point
        """
        self._stop_requested = True
        for task in self.sub_tasks:
            if not task.done():
                task.cancel()
        self.state = OrchestratorState.STOPPED
        return {
            "partial_findings" : self.findings,
            "stopped_at"       : self.state.value,
            "partial_report"   : self._research_state.get( "draft_report" )
        }

    # =========================================================================
    # Private Methods (Placeholders for Phase 2)
    # =========================================================================

    def _check_stop( self ) -> bool:
        """Check if stop was requested."""
        return self._stop_requested

    async def _handle_stop( self ) -> None:
        """Handle stop request gracefully."""
        await cosa_interface.notify_progress( "Research stopped by user request." )
        self.state = OrchestratorState.STOPPED
        return None

    def _calculate_progress( self ) -> int:
        """
        Calculate completion percentage based on current state.

        Returns:
            int: Progress percentage (0-100)
        """
        state_progress = {
            OrchestratorState.CLARIFYING            : 10,
            OrchestratorState.WAITING_CLARIFICATION : 15,
            OrchestratorState.PLANNING              : 20,
            OrchestratorState.WAITING_PLAN_APPROVAL : 25,
            OrchestratorState.RESEARCHING           : 50,
            OrchestratorState.GATHERING             : 70,
            OrchestratorState.SYNTHESIZING          : 80,
            OrchestratorState.WAITING_DRAFT_REVIEW  : 85,
            OrchestratorState.CITING                : 95,
            OrchestratorState.COMPLETED             : 100,
            OrchestratorState.FAILED                : 0,
            OrchestratorState.PAUSED                : 0,
            OrchestratorState.STOPPED               : 0,
        }
        return state_progress.get( self.state, 0 )

    async def _clarify_query_async( self ) -> dict:
        """
        Analyze query for clarification needs using Claude.

        Requires:
            - API client is initialized
            - Query is non-empty

        Ensures:
            - Returns dict with needs_feedback, question, understood_query
            - Increments api_calls metric

        Returns:
            dict: {"needs_feedback": bool, "question": str, "understood_query": str}
        """
        try:
            response = await self.api_client.call_lead_agent(
                system_prompt = clarification.CLARIFICATION_SYSTEM_PROMPT,
                user_message  = clarification.get_clarification_prompt( self.query ),
                call_type     = "clarification",
            )
            self.metrics[ "api_calls" ] += 1

            result = clarification.parse_clarification_response( response.content )

            # Map API response format to orchestrator format
            return {
                "needs_feedback"   : result.get( "needs_clarification", False ),
                "question"         : result.get( "question" ),
                "understood_query" : result.get( "understood_query", self.query ),
                "ambiguities"      : result.get( "ambiguities", [] ),
                "confidence"       : result.get( "confidence", 0.5 ),
            }

        except Exception as e:
            logger.error( f"Clarification failed: {e}" )
            if self.debug: print( f"[ResearchOrchestratorAgent] Clarification error: {e}" )
            # Fail safe: proceed without clarification
            return {
                "needs_feedback"   : False,
                "understood_query" : self.query
            }

    async def _create_plan_async( self ) -> Optional[ ResearchPlan ]:
        """
        Create research plan using Claude.

        Requires:
            - API client is initialized
            - Clarification phase has completed

        Ensures:
            - Returns ResearchPlan with subqueries
            - Increments api_calls metric

        Returns:
            ResearchPlan or None
        """
        try:
            # Use clarified query if available
            clarified = self._research_state.get( "clarification_response" ) or self.query

            response = await self.api_client.call_lead_agent(
                system_prompt = planning.PLANNING_SYSTEM_PROMPT,
                user_message  = planning.get_planning_prompt(
                    query           = self.query,
                    clarified_query = clarified,
                    max_subagents   = self.config.max_subagents_complex,
                ),
                call_type = "planning",
            )
            self.metrics[ "api_calls" ] += 1

            plan_dict = planning.parse_planning_response( response.content )

            # Convert subqueries to Pydantic models
            subqueries = [
                SubQuery(
                    topic         = sq.get( "topic", "" ),
                    objective     = sq.get( "objective", "" ),
                    output_format = sq.get( "output_format", "summary" ),
                    tools_to_use  = sq.get( "tools_to_use", [ "web_search" ] ),
                    priority      = sq.get( "priority", 1 ),
                    depends_on    = sq.get( "depends_on" ),
                )
                for sq in plan_dict.get( "subqueries", [] )
            ]

            return ResearchPlan(
                complexity                 = plan_dict.get( "complexity", "moderate" ),
                subqueries                 = subqueries,
                estimated_subagents        = plan_dict.get( "estimated_subagents", len( subqueries ) ),
                rationale                  = plan_dict.get( "rationale", "" ),
                estimated_duration_minutes = plan_dict.get( "estimated_duration_minutes", 10 ),
            )

        except Exception as e:
            logger.error( f"Planning failed: {e}" )
            if self.debug: print( f"[ResearchOrchestratorAgent] Planning error: {e}" )
            # Fail safe: return a simple single-query plan
            return ResearchPlan(
                complexity          = "simple",
                subqueries          = [
                    SubQuery(
                        topic         = self.query,
                        objective     = "Research the topic comprehensively",
                        output_format = "summary",
                    )
                ],
                estimated_subagents = 1,
                rationale           = "Fallback plan due to planning error",
            )

    async def _research_subquery_async(
        self,
        sq: SubQuery,
        index: int
    ) -> SubagentFinding:
        """
        Execute a single subquery with web search.

        Requires:
            - API client is initialized
            - SubQuery has topic and objective

        Ensures:
            - Returns SubagentFinding with findings and sources
            - Increments api_calls metric

        Args:
            sq: The subquery to research
            index: Index of this subquery in the plan

        Returns:
            SubagentFinding: Research results for this subquery
        """
        try:
            if self.debug:
                print( f"[ResearchOrchestratorAgent] Researching subquery {index}: {sq.topic[:50]}..." )

            response = await self.api_client.call_subagent(
                system_prompt  = subagent.get_system_prompt_with_params(
                    min_sources = self.config.min_sources_per_subquery,
                    max_sources = self.config.max_sources_per_subquery,
                ),
                user_message   = subagent.get_subagent_prompt(
                    topic         = sq.topic,
                    objective     = sq.objective,
                    output_format = sq.output_format,
                ),
                subquery_index = index,
                call_type      = "research",
                use_web_search = True,
            )
            self.metrics[ "api_calls" ] += 1

            result = subagent.parse_subagent_response( response.content )

            # Convert sources to SourceReference objects
            sources = [
                SourceReference(
                    url             = src.get( "url", "" ),
                    title           = src.get( "title", "Untitled" ),
                    snippet         = src.get( "snippet", "" ),
                    relevance_score = src.get( "relevance_score", 0.5 ),
                    source_quality  = src.get( "source_quality", "unknown" ),
                    access_date     = src.get( "access_date", "" ),
                )
                for src in result.get( "sources", [] )
            ]

            return SubagentFinding(
                subquery_index = index,
                subquery_topic = sq.topic,
                findings       = result.get( "findings", "" ),
                sources        = sources,
                confidence     = result.get( "confidence", 0.5 ),
                gaps           = result.get( "gaps", [] ),
                quality_notes  = result.get( "quality_notes", "" ),
            )

        except Exception as e:
            logger.error( f"Subquery {index} research failed: {e}" )
            if self.debug: print( f"[ResearchOrchestratorAgent] Subquery {index} error: {e}" )
            # Return a minimal finding indicating failure
            return SubagentFinding(
                subquery_index = index,
                subquery_topic = sq.topic,
                findings       = f"Research failed: {str( e )[:100]}",
                sources        = [],
                confidence     = 0.0,
                gaps           = [ "Research could not be completed" ],
                quality_notes  = f"Error during research: {type( e ).__name__}",
            )

    async def _synthesize_async( self ) -> str:
        """
        Synthesize findings into report using Claude.

        Requires:
            - API client is initialized
            - Findings list is populated

        Ensures:
            - Returns comprehensive report in markdown format
            - Increments api_calls metric

        Returns:
            str: Draft report
        """
        try:
            # Convert findings to dictionaries for the prompt
            findings_dicts = [
                {
                    "subquery_topic" : f.subquery_topic,
                    "findings"       : f.findings,
                    "confidence"     : f.confidence,
                    "gaps"           : f.gaps,
                    "sources"        : [ s.model_dump() for s in f.sources ],
                }
                for f in self.findings
            ]

            plan = self._research_state.get( "plan" )
            plan_summary = plan.rationale if plan else None

            response = await self.api_client.call_lead_agent(
                system_prompt = synthesis.SYNTHESIS_SYSTEM_PROMPT,
                user_message  = synthesis.get_synthesis_prompt(
                    query        = self.query,
                    findings     = findings_dicts,
                    plan_summary = plan_summary,
                ),
                call_type  = "synthesis",
                max_tokens = 8192,  # Reports can be long
            )
            self.metrics[ "api_calls" ] += 1

            return response.content

        except Exception as e:
            logger.error( f"Synthesis failed: {e}" )
            if self.debug: print( f"[ResearchOrchestratorAgent] Synthesis error: {e}" )
            # Fallback: return a simple concatenation of findings
            sections = [ f"# Research Report: {self.query}\n\n## Findings\n" ]
            for f in self.findings:
                sections.append( f"### {f.subquery_topic}\n\n{f.findings}\n" )
            return "\n".join( sections )

    async def _revise_report_async( self, report: str, feedback: str ) -> str:
        """
        Revise report based on user feedback using Claude.

        Requires:
            - API client is initialized
            - Report and feedback are non-empty

        Ensures:
            - Returns revised report addressing feedback
            - Increments api_calls metric

        Args:
            report: Current report draft
            feedback: User feedback

        Returns:
            str: Revised report
        """
        try:
            response = await self.api_client.call_lead_agent(
                system_prompt = synthesis.SYNTHESIS_SYSTEM_PROMPT,
                user_message  = synthesis.get_revision_prompt( report, feedback ),
                call_type     = "revision",
                max_tokens    = 8192,
            )
            self.metrics[ "api_calls" ] += 1

            return response.content

        except Exception as e:
            logger.error( f"Revision failed: {e}" )
            if self.debug: print( f"[ResearchOrchestratorAgent] Revision error: {e}" )
            # Fallback: return unchanged report with feedback note
            return report + f"\n\n---\n*Note: Revision attempted but failed. Feedback: {feedback}*"

    async def _add_citations_async( self, report: str ) -> str:
        """
        Citation pass-through (handled by synthesis prompt).

        The synthesis prompt already requests inline citations, so this
        method serves as a pass-through. Future enhancements could:
        - Verify citations match sources
        - Standardize citation format
        - Add missing citations

        Args:
            report: Report (already contains inline citations from synthesis)

        Returns:
            str: Report with citations (unchanged)
        """
        # Synthesis prompt already requests inline citations
        # This method is kept for future enhancement
        return report

    async def _generate_abstract_async( self, report: str ) -> str:
        """
        Generate a 2-3 sentence abstract of the research report.

        Uses Haiku model for cost efficiency since abstracts are simple
        summarization tasks.

        Requires:
            - report is a non-empty markdown string
            - API client is initialized

        Ensures:
            - Returns concise abstract suitable for notifications
            - Captures key findings and conclusions
            - 2-3 sentences maximum

        Args:
            report: The full research report in markdown format

        Returns:
            str: 2-3 sentence abstract summarizing key findings
        """
        try:
            system_prompt = """You are a research summarizer. Generate a concise 2-3 sentence abstract of the research report.
Focus on:
- The main topic/question investigated
- Key findings or conclusions
- One notable insight or recommendation

Keep it factual and direct. No introductory phrases like "This report..." - just state the findings."""

            user_message = f"""Summarize this research report in 2-3 sentences:

{report[:8000]}"""  # Truncate to avoid token limits

            response = await self.api_client.call_lead_agent(
                system_prompt = system_prompt,
                user_message  = user_message,
                call_type     = "abstract",
                max_tokens    = 256,
            )
            self.metrics[ "api_calls" ] += 1

            return response.content.strip()

        except Exception as e:
            logger.error( f"Abstract generation failed: {e}" )
            if self.debug: print( f"[ResearchOrchestratorAgent] Abstract error: {e}" )
            # Fallback: extract first paragraph
            lines = report.split( "\n\n" )
            for line in lines:
                if line.strip() and not line.startswith( "#" ):
                    return line.strip()[ :300 ] + "..."
            return "Research report generated."


def quick_smoke_test():
    """Quick smoke test for ResearchOrchestratorAgent."""
    import cosa.utils.util as cu
    import asyncio

    cu.print_banner( "Research Orchestrator Smoke Test", prepend_nl=True )

    try:
        # Test 1: Instantiation
        print( "Testing instantiation..." )
        agent = ResearchOrchestratorAgent(
            query="What is quantum computing?",
            user_id="test-user-123",
            debug=True
        )
        assert agent.query == "What is quantum computing?"
        assert agent.state == OrchestratorState.CLARIFYING
        print( "✓ Agent instantiated correctly" )

        # Test 2: get_state
        print( "Testing get_state..." )
        state = agent.get_state()
        assert "state" in state
        assert "progress_pct" in state
        assert "metrics" in state
        assert state[ "state" ] == "clarifying"
        print( f"✓ get_state works (state={state[ 'state' ]}, progress={state[ 'progress_pct' ]}%)" )

        # Test 3: _calculate_progress
        print( "Testing _calculate_progress..." )
        assert agent._calculate_progress() == 10  # CLARIFYING = 10%
        agent.state = OrchestratorState.RESEARCHING
        assert agent._calculate_progress() == 50  # RESEARCHING = 50%
        agent.state = OrchestratorState.COMPLETED
        assert agent._calculate_progress() == 100  # COMPLETED = 100%
        print( "✓ _calculate_progress returns correct values" )

        # Test 4: API integration (requires API key)
        print( "Testing API integration..." )

        async def test_api_integration():
            agent2 = ResearchOrchestratorAgent(
                query="Test query",
                user_id="test-user",
                budget_limit_usd=0.10,  # Low budget for testing
                debug=True
            )

            # Test _clarify_query_async - returns dict with expected keys
            clarification = await agent2._clarify_query_async()
            assert "needs_feedback" in clarification
            assert "understood_query" in clarification
            # Check types, not specific values (API response varies)
            assert isinstance( clarification[ "needs_feedback" ], bool )
            print( f"  ✓ _clarify_query_async returns valid structure" )

            # Test _create_plan_async - returns ResearchPlan
            plan = await agent2._create_plan_async()
            assert plan is not None
            assert plan.complexity in [ "simple", "moderate", "complex" ]
            assert len( plan.subqueries ) >= 1
            print( f"  ✓ _create_plan_async returns ResearchPlan (complexity={plan.complexity})" )

            # Test _synthesize_async with mock findings
            agent2.findings = []  # Empty findings for test
            report = await agent2._synthesize_async()
            assert isinstance( report, str )
            print( f"  ✓ _synthesize_async returns report ({len( report )} chars)" )

            return True

        try:
            result = asyncio.run( test_api_integration() )
            assert result is True
            print( "✓ API integration tests passed" )
        except ImportError as e:
            print( f"⚠ Skipping API tests (anthropic SDK not installed): {e}" )
        except ValueError as e:
            if "API key" in str( e ):
                print( f"⚠ Skipping API tests (no API key): {e}" )
            else:
                raise

        # Test 5: pause/resume/stop
        print( "Testing control methods..." )

        async def test_control():
            agent3 = ResearchOrchestratorAgent(
                query="Control test",
                user_id="test-user"
            )

            # Test pause
            paused = await agent3.pause()
            assert paused is True
            assert agent3._pause_requested is True

            # Test resume (not paused state, so returns False)
            resumed = await agent3.resume()
            assert resumed is False  # Not in PAUSED state

            # Test stop
            result = await agent3.stop()
            assert agent3.state == OrchestratorState.STOPPED
            assert "partial_findings" in result

            return True

        result = asyncio.run( test_control() )
        assert result is True
        print( "✓ Control methods (pause/resume/stop) work correctly" )

        print( "\n✓ Research Orchestrator smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
