#!/usr/bin/env python3
"""
State Schemas for COSA Deep Research Agent.

Uses Pydantic for structured outputs and TypedDict for graph state.
Designed for the parallel subagent architecture with human-in-the-loop feedback.
"""

from enum import Enum
from typing import TypedDict, Literal, Any, Optional
from pydantic import BaseModel, Field


class OrchestratorState( Enum ):
    """
    State machine for the Research Orchestrator Agent.

    Active states represent work being done.
    Waiting states are yield points where control returns to event loop.
    Terminal states indicate completion or failure.
    External control states allow user intervention.
    """
    # Active states
    CLARIFYING   = "clarifying"
    PLANNING     = "planning"
    RESEARCHING  = "researching"
    GATHERING    = "gathering"
    SYNTHESIZING = "synthesizing"
    CITING       = "citing"

    # Waiting states (yield control via await)
    WAITING_CLARIFICATION = "waiting_clarification"
    WAITING_PLAN_APPROVAL = "waiting_plan_approval"
    WAITING_DRAFT_REVIEW  = "waiting_draft_review"

    # Terminal states
    COMPLETED = "completed"
    FAILED    = "failed"

    # External control states
    PAUSED  = "paused"
    STOPPED = "stopped"


class JobSubState( Enum ):
    """
    Sub-states for jobs within the RUNNING queue.

    These provide finer-grained status for jobs that are in progress
    but may be blocked on various conditions.
    """
    EXECUTING            = "executing"
    WAITING_FOR_HUMAN    = "waiting_for_human"
    WAITING_FOR_SUBTASKS = "waiting_for_subtasks"
    WAITING_FOR_LLM      = "waiting_for_llm"
    PAUSED               = "paused"


# =============================================================================
# Pydantic Models for Structured Outputs
# =============================================================================

class SubQuery( BaseModel ):
    """
    A focused research subquery for delegation to a subagent.

    Each subquery represents a narrow research task that can be
    executed independently in parallel.
    """

    topic         : str       = Field( description="The specific topic to research" )
    objective     : str       = Field( description="What information to gather" )
    output_format : str       = Field( description="Expected output structure" )
    tools_to_use  : list[str] = Field( default=[ "web_search", "web_fetch" ] )
    priority      : int       = Field( default=1, ge=1, le=5 )
    depends_on    : Optional[ list[int] ] = Field( default=None )


class ResearchPlan( BaseModel ):
    """
    The lead agent's complete research plan.

    Contains the strategy and breakdown of work into subqueries
    for parallel execution.
    """

    complexity                  : Literal[ "simple", "moderate", "complex" ]
    subqueries                  : list[ SubQuery ]
    estimated_subagents         : int
    rationale                   : str
    estimated_duration_minutes  : int = Field( default=5 )


class SourceReference( BaseModel ):
    """
    A reference to a source used in research.

    Tracks provenance and quality information for citations.
    """

    url             : str
    title           : str
    snippet         : str   = Field( default="" )
    relevance_score : float = Field( ge=0.0, le=1.0 )
    source_quality  : Literal[ "primary", "secondary", "aggregator", "unknown" ] = "unknown"
    access_date     : str   = Field( default="" )


class SubagentFinding( BaseModel ):
    """
    Compressed findings from a research subagent.

    Contains the results of executing a single subquery,
    including sources, confidence, and identified gaps.
    """

    subquery_index : int                    = Field( description="Index of the subquery" )
    subquery_topic : str                    = Field( description="Topic researched" )
    findings       : str                    = Field( description="Compressed findings" )
    sources        : list[ SourceReference ] = Field( default_factory=list )
    confidence     : float                  = Field( ge=0.0, le=1.0 )
    gaps           : list[str]              = Field( default_factory=list )
    quality_notes  : str                    = Field( default="" )


class ClarificationDecision( BaseModel ):
    """
    Decision on whether query clarification is needed.

    Used by the clarification phase to determine if user
    input is required before proceeding.
    """

    needs_clarification : bool
    question            : Optional[str]      = Field( default=None )
    understood_query    : str
    ambiguities         : list[str]          = Field( default_factory=list )


class Citation( BaseModel ):
    """
    A citation for the final report.

    Links a specific claim in the report to its source.
    """

    claim              : str
    source             : SourceReference
    location_in_report : str


# =============================================================================
# LangGraph State (TypedDict)
# =============================================================================

class ResearchState( TypedDict ):
    """
    Main graph state for the research agent.

    This TypedDict defines the complete state that flows through
    the research workflow, tracking all phases and intermediate results.
    """

    # Input
    original_query : str

    # Clarification Phase
    needs_clarification     : bool
    clarification_question  : Optional[str]
    clarification_response  : Optional[str]
    clarified_query         : Optional[str]
    clarification_rounds    : int

    # Planning Phase
    research_brief           : Optional[str]
    plan                     : Optional[ ResearchPlan ]
    human_feedback_on_plan   : Optional[str]
    plan_approved            : bool
    plan_revision_count      : int

    # Research Phase
    active_subqueries   : list[ SubQuery ]
    subagent_findings   : list[ SubagentFinding ]
    research_iterations : int
    total_sources_found : int

    # Synthesis Phase
    draft_report            : Optional[str]
    human_feedback_on_draft : Optional[str]
    draft_revision_count    : int

    # Final Output
    final_report      : Optional[str]
    citations         : list[ Citation ]
    research_metadata : dict[ str, Any ]


def create_initial_state( query: str ) -> ResearchState:
    """
    Create the initial state for a research task.

    Requires:
        - query is a non-empty string

    Ensures:
        - Returns fully initialized ResearchState with defaults
        - All counters start at 0
        - All optional fields are None or empty

    Args:
        query: The user's research query

    Returns:
        ResearchState: Initialized state dictionary
    """
    return ResearchState(
        original_query          = query,
        needs_clarification     = False,
        clarification_question  = None,
        clarification_response  = None,
        clarified_query         = None,
        clarification_rounds    = 0,
        research_brief          = None,
        plan                    = None,
        human_feedback_on_plan  = None,
        plan_approved           = False,
        plan_revision_count     = 0,
        active_subqueries       = [],
        subagent_findings       = [],
        research_iterations     = 0,
        total_sources_found     = 0,
        draft_report            = None,
        human_feedback_on_draft = None,
        draft_revision_count    = 0,
        final_report            = None,
        citations               = [],
        research_metadata       = {},
    )


def quick_smoke_test():
    """Quick smoke test for state schemas."""
    import cosa.utils.util as cu

    cu.print_banner( "Deep Research State Smoke Test", prepend_nl=True )

    try:
        # Test 1: OrchestratorState enum
        print( "Testing OrchestratorState enum..." )
        assert OrchestratorState.CLARIFYING.value == "clarifying"
        assert OrchestratorState.COMPLETED.value == "completed"
        assert len( OrchestratorState ) == 13
        print( f"✓ OrchestratorState enum valid ({len( OrchestratorState )} states)" )

        # Test 2: JobSubState enum
        print( "Testing JobSubState enum..." )
        assert JobSubState.EXECUTING.value == "executing"
        assert JobSubState.WAITING_FOR_HUMAN.value == "waiting_for_human"
        assert len( JobSubState ) == 5
        print( f"✓ JobSubState enum valid ({len( JobSubState )} states)" )

        # Test 3: SubQuery model validation
        print( "Testing SubQuery model..." )
        sq = SubQuery( topic="test", objective="test obj", output_format="list" )
        assert sq.priority == 1  # Default value
        assert sq.tools_to_use == [ "web_search", "web_fetch" ]  # Default value
        print( "✓ SubQuery model validates" )

        # Test 4: ResearchPlan model validation
        print( "Testing ResearchPlan model..." )
        plan = ResearchPlan(
            complexity="moderate",
            subqueries=[ sq ],
            estimated_subagents=1,
            rationale="Test plan"
        )
        assert plan.complexity == "moderate"
        assert len( plan.subqueries ) == 1
        print( "✓ ResearchPlan model validates" )

        # Test 5: SourceReference model validation
        print( "Testing SourceReference model..." )
        source = SourceReference(
            url="https://example.com",
            title="Test Source",
            relevance_score=0.85
        )
        assert source.source_quality == "unknown"  # Default
        print( "✓ SourceReference model validates" )

        # Test 6: SubagentFinding model validation
        print( "Testing SubagentFinding model..." )
        finding = SubagentFinding(
            subquery_index=0,
            subquery_topic="test topic",
            findings="Found some data",
            confidence=0.9
        )
        assert finding.gaps == []  # Default
        print( "✓ SubagentFinding model validates" )

        # Test 7: ClarificationDecision model validation
        print( "Testing ClarificationDecision model..." )
        decision = ClarificationDecision(
            needs_clarification=False,
            understood_query="Clear query"
        )
        assert decision.question is None  # Default
        print( "✓ ClarificationDecision model validates" )

        # Test 8: Citation model validation
        print( "Testing Citation model..." )
        citation = Citation(
            claim="This is true",
            source=source,
            location_in_report="paragraph 1"
        )
        assert citation.source.url == "https://example.com"
        print( "✓ Citation model validates" )

        # Test 9: create_initial_state
        print( "Testing create_initial_state..." )
        state = create_initial_state( "What is quantum computing?" )
        assert state[ "original_query" ] == "What is quantum computing?"
        assert state[ "clarification_rounds" ] == 0
        assert state[ "plan_approved" ] is False
        assert state[ "subagent_findings" ] == []
        print( f"✓ create_initial_state works ({len( state )} keys)" )

        print( "\n✓ Deep Research State smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
