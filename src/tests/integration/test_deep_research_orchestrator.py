#!/usr/bin/env python3
"""
Integration test for Deep Research Orchestrator.

Tests each phase of the orchestrator in isolation with real API calls.
Designed to be run standalone from command line.

USAGE:
    # Run with defaults (via module)
    python -m tests.integration.test_deep_research_orchestrator

    # Custom query and budget
    python -m tests.integration.test_deep_research_orchestrator \
        --query "What is Rust?" \
        --budget 0.25

    # Skip web search phase (faster, cheaper)
    python -m tests.integration.test_deep_research_orchestrator --skip-research

    # Verbose output
    python -m tests.integration.test_deep_research_orchestrator --debug

    # Via pytest (for CI/CD integration)
    pytest src/tests/integration/test_deep_research_orchestrator.py -v
    pytest src/tests/integration/test_deep_research_orchestrator.py -v -k "not research"

PREREQUISITES:
    1. LUPIN_ROOT environment variable set
       export LUPIN_ROOT=/path/to/lupin

    2. Anthropic API key configured
       export ANTHROPIC_API_KEY=your_key

Created: 2026-01-17
"""

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass, field
from typing import Optional
from unittest import mock

import pytest

# Path bootstrapped by src/tests/conftest.py - cosa now importable
import cosa.utils.util as cu
from cosa.agents.deep_research.orchestrator import ResearchOrchestratorAgent
from cosa.agents.deep_research.state import OrchestratorState, SubQuery


# =============================================================================
# Constants
# =============================================================================

TRIVIAL_QUERY = "What is Rust?"


# =============================================================================
# Test Result Tracking
# =============================================================================

@dataclass
class TestResult:
    """Tracks result of a single test phase."""
    name: str
    passed: bool         = False
    error: Optional[str] = None
    duration_ms: float   = 0.0
    tokens_used: int     = 0
    cost_usd: float      = 0.0
    details: dict        = field( default_factory=dict )


# =============================================================================
# COSA Interface Mock
# =============================================================================

def get_mock_cosa_interface():
    """
    Create mock for cosa_interface that auto-approves everything.

    Ensures:
        - notify_progress: no-op (fire-and-forget)
        - get_feedback: returns None (no changes requested)
        - present_choices: returns "Execute plan" choice
        - ask_confirmation: returns True
    """
    mock_interface = mock.MagicMock()

    # notify_progress - just return immediately
    async def mock_notify_progress( message: str, priority: str = "medium" ):
        pass

    # get_feedback - return None (no feedback / auto-approve)
    async def mock_get_feedback( prompt: str, timeout: int = 300 ):
        return None

    # present_choices - return "Execute plan" for plan approval
    async def mock_present_choices( questions: list, timeout: int = 120 ):
        return { "answers": { "Plan": "Execute plan" } }

    # ask_confirmation - return True
    async def mock_ask_confirmation( question: str, default: str = "no", timeout: int = 60, abstract: Optional[str] = None ):
        return True

    mock_interface.notify_progress = mock_notify_progress
    mock_interface.get_feedback = mock_get_feedback
    mock_interface.present_choices = mock_present_choices
    mock_interface.ask_confirmation = mock_ask_confirmation
    mock_interface.is_approval = lambda feedback: True  # Always approve

    return mock_interface


# =============================================================================
# Rate Limit Handling
# =============================================================================

INTER_PHASE_DELAY_SECONDS = 3.0


async def run_with_rate_limit_handling( coro, phase_name: str, debug: bool = False ):
    """
    Run coroutine with rate limit error handling.

    Requires:
        - coro is an awaitable
        - phase_name is a non-empty string

    Ensures:
        - Returns (result, None) on success
        - Returns (None, error_string) on rate limit
        - Returns (None, error_string) on other errors
    """
    try:
        result = await coro
        return ( result, None )
    except Exception as e:
        error_str = str( e )
        if "rate" in error_str.lower() or "429" in error_str:
            if debug: print( f"  [!] Rate limited at {phase_name}" )
            return ( None, f"Rate limited: {error_str[:50]}" )
        if debug: print( f"  [!] Error at {phase_name}: {e}" )
        return ( None, error_str[:100] )


# =============================================================================
# Integration Test Phases
# =============================================================================

@pytest.mark.skip( reason="Non-standard test format (raw async functions with params) — standalone CLI runner only" )
async def test_phase_instantiation(
    query: str,
    budget: float,
    debug: bool
) -> TestResult:
    """
    Phase 1: Test agent instantiation.

    Requires:
        - query is non-empty string
        - budget is positive float

    Ensures:
        - Agent is created with correct state
        - CostTracker and APIClient are initialized
        - No API calls made
    """
    result = TestResult( name="Instantiation" )
    start = time.time()

    try:
        agent = ResearchOrchestratorAgent(
            query           = query,
            user_id         = "integration-test",
            budget_limit_usd = budget,
            debug           = debug,
        )

        # Verify initialization
        assert agent.query == query
        assert agent.state == OrchestratorState.CLARIFYING
        assert agent.cost_tracker is not None
        assert agent.api_client is not None

        result.passed = True
        result.details = {
            "state"         : agent.state.value,
            "budget_limit"  : budget,
            "has_tracker"   : agent.cost_tracker is not None,
            "has_api_client": agent.api_client is not None,
        }

    except Exception as e:
        result.error = str( e )[:100]

    result.duration_ms = ( time.time() - start ) * 1000
    return result


@pytest.mark.skip( reason="Non-standard test format — standalone CLI runner only" )
async def test_phase_clarification(
    agent: ResearchOrchestratorAgent,
    debug: bool
) -> TestResult:
    """
    Phase 2: Test query clarification.

    Requires:
        - agent is initialized
        - API client has valid credentials

    Ensures:
        - Returns dict with needs_feedback, understood_query
        - Makes 1 API call
    """
    result = TestResult( name="Clarification" )
    start = time.time()

    try:
        # Add delay before API call
        await asyncio.sleep( INTER_PHASE_DELAY_SECONDS )

        clarification, error = await run_with_rate_limit_handling(
            agent._clarify_query_async(),
            "clarification",
            debug
        )

        if error:
            result.error = error
        elif clarification:
            # Verify response structure
            assert "needs_feedback" in clarification
            assert "understood_query" in clarification

            result.passed = True
            result.details = {
                "needs_feedback"   : clarification.get( "needs_feedback" ),
                "understood_query" : clarification.get( "understood_query", "" )[:50],
                "confidence"       : clarification.get( "confidence", 0 ),
            }

            # Get cost from tracker
            summary = agent.cost_tracker.get_summary()
            result.tokens_used = summary.get( "total_tokens", 0 )
            result.cost_usd = summary.get( "total_cost_usd", 0.0 )

    except Exception as e:
        result.error = str( e )[:100]

    result.duration_ms = ( time.time() - start ) * 1000
    return result


@pytest.mark.skip( reason="Non-standard test format — standalone CLI runner only" )
async def test_phase_planning(
    agent: ResearchOrchestratorAgent,
    debug: bool
) -> TestResult:
    """
    Phase 3: Test research planning.

    Requires:
        - agent has completed clarification (or will use fallback)
        - API client has valid credentials

    Ensures:
        - Returns ResearchPlan with subqueries
        - Makes 1 API call
    """
    result = TestResult( name="Planning" )
    start = time.time()
    tokens_before = agent.cost_tracker.get_summary().get( "total_tokens", 0 )
    cost_before = agent.cost_tracker.get_summary().get( "total_cost_usd", 0.0 )

    try:
        # Add delay before API call
        await asyncio.sleep( INTER_PHASE_DELAY_SECONDS )

        plan, error = await run_with_rate_limit_handling(
            agent._create_plan_async(),
            "planning",
            debug
        )

        if error:
            result.error = error
        elif plan:
            # Verify response structure
            assert plan.complexity in [ "simple", "moderate", "complex" ]
            assert len( plan.subqueries ) >= 1

            result.passed = True
            result.details = {
                "complexity"   : plan.complexity,
                "num_subqueries": len( plan.subqueries ),
                "rationale"    : plan.rationale[:50] if plan.rationale else "",
            }

            # Get incremental cost
            summary = agent.cost_tracker.get_summary()
            result.tokens_used = summary.get( "total_tokens", 0 ) - tokens_before
            result.cost_usd = summary.get( "total_cost_usd", 0.0 ) - cost_before

    except Exception as e:
        result.error = str( e )[:100]

    result.duration_ms = ( time.time() - start ) * 1000
    return result


@pytest.mark.skip( reason="Non-standard test format — standalone CLI runner only" )
async def test_phase_research(
    agent: ResearchOrchestratorAgent,
    debug: bool
) -> TestResult:
    """
    Phase 4: Test single subquery research with web search.

    Requires:
        - agent has a plan with at least 1 subquery
        - API client has valid credentials

    Ensures:
        - Returns SubagentFinding with findings and sources
        - Makes 1 API call with web search
    """
    result = TestResult( name="Research" )
    start = time.time()
    tokens_before = agent.cost_tracker.get_summary().get( "total_tokens", 0 )
    cost_before = agent.cost_tracker.get_summary().get( "total_cost_usd", 0.0 )

    try:
        # Create a test subquery
        test_subquery = SubQuery(
            topic         = agent.query,
            objective     = "Research the topic and provide key findings",
            output_format = "summary",
            tools_to_use  = [ "web_search" ],
            priority      = 1,
        )

        # Add delay before API call
        await asyncio.sleep( INTER_PHASE_DELAY_SECONDS )

        finding, error = await run_with_rate_limit_handling(
            agent._research_subquery_async( test_subquery, 0 ),
            "research",
            debug
        )

        if error:
            result.error = error
        elif finding:
            result.passed = True
            result.details = {
                "topic"      : finding.subquery_topic[:40],
                "num_sources": len( finding.sources ),
                "confidence" : finding.confidence,
                "has_gaps"   : len( finding.gaps ) > 0,
            }

            # Get incremental cost
            summary = agent.cost_tracker.get_summary()
            result.tokens_used = summary.get( "total_tokens", 0 ) - tokens_before
            result.cost_usd = summary.get( "total_cost_usd", 0.0 ) - cost_before

    except Exception as e:
        result.error = str( e )[:100]

    result.duration_ms = ( time.time() - start ) * 1000
    return result


@pytest.mark.skip( reason="Non-standard test format — standalone CLI runner only" )
async def test_phase_synthesis(
    agent: ResearchOrchestratorAgent,
    debug: bool
) -> TestResult:
    """
    Phase 5: Test report synthesis.

    Requires:
        - agent has findings (even if empty)
        - API client has valid credentials

    Ensures:
        - Returns markdown report string
        - Makes 1 API call
    """
    result = TestResult( name="Synthesis" )
    start = time.time()
    tokens_before = agent.cost_tracker.get_summary().get( "total_tokens", 0 )
    cost_before = agent.cost_tracker.get_summary().get( "total_cost_usd", 0.0 )

    try:
        # Add delay before API call
        await asyncio.sleep( INTER_PHASE_DELAY_SECONDS )

        report, error = await run_with_rate_limit_handling(
            agent._synthesize_async(),
            "synthesis",
            debug
        )

        if error:
            result.error = error
        elif report:
            # Verify response is a non-empty string
            assert isinstance( report, str )
            assert len( report ) > 0

            result.passed = True
            result.details = {
                "report_length": len( report ),
                "has_sections" : "#" in report,  # Markdown headers
            }

            # Get incremental cost
            summary = agent.cost_tracker.get_summary()
            result.tokens_used = summary.get( "total_tokens", 0 ) - tokens_before
            result.cost_usd = summary.get( "total_cost_usd", 0.0 ) - cost_before

    except Exception as e:
        result.error = str( e )[:100]

    result.duration_ms = ( time.time() - start ) * 1000
    return result


@pytest.mark.skip( reason="Non-standard test format — standalone CLI runner only" )
async def test_phase_revision(
    agent: ResearchOrchestratorAgent,
    debug: bool
) -> TestResult:
    """
    Phase 6: Test report revision.

    Requires:
        - agent can synthesize (for the test report)
        - API client has valid credentials

    Ensures:
        - Returns revised markdown report
        - Makes 1 API call
    """
    result = TestResult( name="Revision" )
    start = time.time()
    tokens_before = agent.cost_tracker.get_summary().get( "total_tokens", 0 )
    cost_before = agent.cost_tracker.get_summary().get( "total_cost_usd", 0.0 )

    try:
        # Create a simple test report
        test_report = f"# Research Report: {agent.query}\n\nThis is a test report."
        test_feedback = "Please add an executive summary at the beginning."

        # Add delay before API call
        await asyncio.sleep( INTER_PHASE_DELAY_SECONDS )

        revised, error = await run_with_rate_limit_handling(
            agent._revise_report_async( test_report, test_feedback ),
            "revision",
            debug
        )

        if error:
            result.error = error
        elif revised:
            # Verify response is a non-empty string
            assert isinstance( revised, str )
            assert len( revised ) > 0

            result.passed = True
            result.details = {
                "revised_length"  : len( revised ),
                "length_increased": len( revised ) > len( test_report ),
            }

            # Get incremental cost
            summary = agent.cost_tracker.get_summary()
            result.tokens_used = summary.get( "total_tokens", 0 ) - tokens_before
            result.cost_usd = summary.get( "total_cost_usd", 0.0 ) - cost_before

    except Exception as e:
        result.error = str( e )[:100]

    result.duration_ms = ( time.time() - start ) * 1000
    return result


# =============================================================================
# Main Test Runner
# =============================================================================

async def run_integration_tests(
    query: str,
    budget: float,
    skip_research: bool,
    debug: bool
) -> list[ TestResult ]:
    """
    Run all integration test phases.

    Requires:
        - query is non-empty string
        - budget is positive float

    Ensures:
        - Returns list of TestResult for each phase
        - Phases run sequentially with delays
        - Rate limits handled gracefully
    """
    results = []

    # Mock cosa_interface to prevent user interaction
    mock_interface = get_mock_cosa_interface()

    with mock.patch( "cosa.agents.deep_research.orchestrator.cosa_interface", mock_interface ):

        # Phase 1: Instantiation (no API call)
        if debug: print( "\n[Phase 1] Testing instantiation..." )
        result = await test_phase_instantiation( query, budget, debug )
        results.append( result )
        if debug and result.passed:
            print( f"  [+] Passed: state={result.details.get( 'state' )}" )
        elif debug:
            print( f"  [-] Failed: {result.error}" )

        if not result.passed:
            return results  # Can't continue without agent

        # Create agent for remaining phases
        agent = ResearchOrchestratorAgent(
            query            = query,
            user_id          = "integration-test",
            budget_limit_usd = budget,
            debug            = debug,
        )

        # Phase 2: Clarification (1 API call)
        if debug: print( "\n[Phase 2] Testing clarification..." )
        result = await test_phase_clarification( agent, debug )
        results.append( result )
        if debug and result.passed:
            print( f"  [+] Passed: needs_feedback={result.details.get( 'needs_feedback' )}" )
        elif debug:
            print( f"  [-] {'Rate limited' if 'Rate' in ( result.error or '' ) else 'Failed'}: {result.error}" )

        # Phase 3: Planning (1 API call)
        if debug: print( "\n[Phase 3] Testing planning..." )
        result = await test_phase_planning( agent, debug )
        results.append( result )
        if debug and result.passed:
            print( f"  [+] Passed: complexity={result.details.get( 'complexity' )}, subqueries={result.details.get( 'num_subqueries' )}" )
        elif debug:
            print( f"  [-] {'Rate limited' if 'Rate' in ( result.error or '' ) else 'Failed'}: {result.error}" )

        # Phase 4: Research (1 API call with web search) - optional
        if not skip_research:
            if debug: print( "\n[Phase 4] Testing research (web search)..." )
            result = await test_phase_research( agent, debug )
            results.append( result )
            if debug and result.passed:
                print( f"  [+] Passed: sources={result.details.get( 'num_sources' )}, confidence={result.details.get( 'confidence' )}" )
            elif debug:
                print( f"  [-] {'Rate limited' if 'Rate' in ( result.error or '' ) else 'Failed'}: {result.error}" )
        else:
            if debug: print( "\n[Phase 4] Skipping research (--skip-research)" )
            skip_result = TestResult( name="Research (skipped)" )
            skip_result.passed = True
            skip_result.details = { "skipped": True }
            results.append( skip_result )

        # Phase 5: Synthesis (1 API call)
        if debug: print( "\n[Phase 5] Testing synthesis..." )
        result = await test_phase_synthesis( agent, debug )
        results.append( result )
        if debug and result.passed:
            print( f"  [+] Passed: report_length={result.details.get( 'report_length' )}" )
        elif debug:
            print( f"  [-] {'Rate limited' if 'Rate' in ( result.error or '' ) else 'Failed'}: {result.error}" )

        # Phase 6: Revision (1 API call)
        if debug: print( "\n[Phase 6] Testing revision..." )
        result = await test_phase_revision( agent, debug )
        results.append( result )
        if debug and result.passed:
            print( f"  [+] Passed: revised_length={result.details.get( 'revised_length' )}" )
        elif debug:
            print( f"  [-] {'Rate limited' if 'Rate' in ( result.error or '' ) else 'Failed'}: {result.error}" )

    return results


def print_results_table( results: list[ TestResult ] ):
    """Print tabular summary of test results."""
    print( "\n" + "=" * 70 )
    print( "  DEEP RESEARCH ORCHESTRATOR - INTEGRATION TEST RESULTS" )
    print( "=" * 70 )
    print( f"{'Phase':<25} {'Status':<15} {'Tokens':<10} {'Cost':<12} {'Time':<10}" )
    print( "-" * 70 )

    for r in results:
        if r.passed:
            status = "\033[92m\u2713 PASS\033[0m"  # Green checkmark
        elif r.error and "Rate" in r.error:
            status = "\033[93m~ RATE\033[0m"       # Yellow rate limit
        else:
            status = "\033[91m\u2717 FAIL\033[0m"  # Red X

        tokens_str = str( r.tokens_used ) if r.tokens_used > 0 else "-"
        cost_str = f"${r.cost_usd:.4f}" if r.cost_usd > 0 else "-"
        time_str = f"{r.duration_ms:.0f}ms"

        # Plain text for width calculation (without ANSI)
        status_plain = "PASS" if r.passed else ( "RATE" if r.error and "Rate" in r.error else "FAIL" )
        print( f"{r.name:<25} {status:<15} {tokens_str:<10} {cost_str:<12} {time_str:<10}" )

    print( "-" * 70 )

    total_cost = sum( r.cost_usd for r in results )
    total_tokens = sum( r.tokens_used for r in results )
    passed = sum( 1 for r in results if r.passed )
    rate_limited = sum( 1 for r in results if r.error and "Rate" in r.error )

    status_summary = f"{passed}/{len( results )} passed"
    if rate_limited > 0:
        status_summary += f", {rate_limited} rate-limited"

    print( f"{'TOTAL':<25} {status_summary:<15} {total_tokens:<10} ${total_cost:.4f}" )
    print( "=" * 70 )

    # Print errors if any
    errors = [ r for r in results if r.error and "Rate" not in r.error ]
    if errors:
        print( "\nErrors:" )
        for r in errors:
            print( f"  {r.name}: {r.error}" )


# =============================================================================
# Pytest Integration
# =============================================================================

@pytest.mark.skip( reason="Requires Anthropic API access — rate-limited in CI" )
class TestDeepResearchOrchestratorIntegration:
    """Pytest test class for integration testing."""

    @pytest.fixture( scope="class" )
    def mock_cosa_interface( self ):
        """Provide mock cosa_interface for all tests."""
        return get_mock_cosa_interface()

    @pytest.mark.integration
    def test_instantiation( self ):
        """Test that orchestrator can be instantiated."""
        result = asyncio.run( test_phase_instantiation(
            query  = "What is quantum computing?",
            budget = 0.50,
            debug  = False
        ) )
        assert result.passed, f"Instantiation failed: {result.error}"

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_clarification( self, mock_cosa_interface ):
        """Test query clarification phase."""
        with mock.patch( "cosa.agents.deep_research.orchestrator.cosa_interface", mock_cosa_interface ):
            agent = ResearchOrchestratorAgent(
                query            = "What is quantum computing?",
                user_id          = "pytest",
                budget_limit_usd = 0.50,
            )
            result = await test_phase_clarification( agent, debug=False )

            # Allow rate limit as partial success
            if result.error and "Rate" in result.error:
                pytest.skip( "Rate limited - partial test" )

            assert result.passed, f"Clarification failed: {result.error}"

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_planning( self, mock_cosa_interface ):
        """Test research planning phase."""
        with mock.patch( "cosa.agents.deep_research.orchestrator.cosa_interface", mock_cosa_interface ):
            agent = ResearchOrchestratorAgent(
                query            = "What is quantum computing?",
                user_id          = "pytest",
                budget_limit_usd = 0.50,
            )
            result = await test_phase_planning( agent, debug=False )

            if result.error and "Rate" in result.error:
                pytest.skip( "Rate limited - partial test" )

            assert result.passed, f"Planning failed: {result.error}"

    @pytest.mark.integration
    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_research( self, mock_cosa_interface ):
        """Test single subquery research with web search (slow)."""
        with mock.patch( "cosa.agents.deep_research.orchestrator.cosa_interface", mock_cosa_interface ):
            agent = ResearchOrchestratorAgent(
                query            = "What is Rust programming language?",
                user_id          = "pytest",
                budget_limit_usd = 0.50,
            )
            result = await test_phase_research( agent, debug=False )

            if result.error and "Rate" in result.error:
                pytest.skip( "Rate limited - partial test" )

            assert result.passed, f"Research failed: {result.error}"

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_synthesis( self, mock_cosa_interface ):
        """Test report synthesis phase."""
        with mock.patch( "cosa.agents.deep_research.orchestrator.cosa_interface", mock_cosa_interface ):
            agent = ResearchOrchestratorAgent(
                query            = "What is quantum computing?",
                user_id          = "pytest",
                budget_limit_usd = 0.50,
            )
            # Add mock findings for synthesis
            agent.findings = []
            result = await test_phase_synthesis( agent, debug=False )

            if result.error and "Rate" in result.error:
                pytest.skip( "Rate limited - partial test" )

            assert result.passed, f"Synthesis failed: {result.error}"

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_revision( self, mock_cosa_interface ):
        """Test report revision phase."""
        with mock.patch( "cosa.agents.deep_research.orchestrator.cosa_interface", mock_cosa_interface ):
            agent = ResearchOrchestratorAgent(
                query            = "What is quantum computing?",
                user_id          = "pytest",
                budget_limit_usd = 0.50,
            )
            result = await test_phase_revision( agent, debug=False )

            if result.error and "Rate" in result.error:
                pytest.skip( "Rate limited - partial test" )

            assert result.passed, f"Revision failed: {result.error}"


# =============================================================================
# Command Line Interface
# =============================================================================

def main():
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        description="Integration test for Deep Research Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tests.integration.test_deep_research_orchestrator
  python -m tests.integration.test_deep_research_orchestrator --query "What is Rust?"
  python -m tests.integration.test_deep_research_orchestrator --budget 0.25 --skip-research
  python -m tests.integration.test_deep_research_orchestrator --debug
        """
    )

    parser.add_argument(
        "--query", "-q",
        type=str,
        default="What are the key differences between Python and Rust?",
        help="Research query to test (default: Python vs Rust comparison)"
    )

    parser.add_argument(
        "--budget", "-b",
        type=float,
        default=0.50,
        help="Budget limit in USD (default: 0.50)"
    )

    parser.add_argument(
        "--skip-research",
        action="store_true",
        help="Skip the research phase (faster, cheaper, no web search)"
    )

    parser.add_argument(
        "--debug", "-d",
        action="store_true",
        help="Enable verbose debug output"
    )

    parser.add_argument(
        "--trivial", "-t",
        action="store_true",
        help="Use a trivial query for quick/cheap testing (overrides --query)"
    )

    args = parser.parse_args()

    # Override query if trivial flag set
    if args.trivial:
        args.query = TRIVIAL_QUERY

    # Print header
    cu.print_banner( "Deep Research Orchestrator Integration Test", prepend_nl=True )
    print( f"Query:  {args.query[:60]}{'...' if len( args.query ) > 60 else ''}" )
    print( f"Budget: ${args.budget:.2f}" )
    print( f"Skip research: {args.skip_research}" )
    print( f"Debug: {args.debug}" )

    # Run tests
    try:
        results = asyncio.run( run_integration_tests(
            query         = args.query,
            budget        = args.budget,
            skip_research = args.skip_research,
            debug         = args.debug
        ) )

        # Print results table
        print_results_table( results )

        # Exit code based on results
        passed = sum( 1 for r in results if r.passed )
        if passed == len( results ):
            sys.exit( 0 )  # All passed
        elif passed > 0:
            sys.exit( 1 )  # Partial success
        else:
            sys.exit( 2 )  # All failed

    except KeyboardInterrupt:
        print( "\n\nTest interrupted by user." )
        sys.exit( 130 )
    except Exception as e:
        print( f"\n\nTest runner error: {e}" )
        if args.debug:
            import traceback
            traceback.print_exc()
        sys.exit( 3 )


if __name__ == "__main__":
    main()
