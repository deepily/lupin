#!/usr/bin/env python3
"""
Isolated Test Harness for Progressive Narrowing Phase.

This module extracts the progressive narrowing logic from cli.py into
reusable functions for isolated testing and debugging.

Progressive Narrowing Flow:
1. Theme Clustering - Calls Claude to group subqueries into 3-4 themes
2. Theme Selection - User picks which themes to research
3. Topic Refinement - User refines specific topics within selected themes
4. Final Filtering - Subqueries are filtered to the final selection

Interaction Modality:
- Voice-first with automatic CLI fallback (via voice_io module)
- Use --cli-mode to force CLI text interaction
- Use --mock for testing without API calls

Usage:
    # As module with smoke test
    python -m cosa.agents.deep_research.narrowing_harness

    # Theme clustering only
    python -m cosa.agents.deep_research.narrowing_harness \\
        --input plan.json --phase themes

    # Full narrowing with CLI interaction
    python -m cosa.agents.deep_research.narrowing_harness \\
        --input plan.json --cli-mode

    # Full narrowing with auto-approve
    python -m cosa.agents.deep_research.narrowing_harness \\
        --input plan.json --auto-approve --output result.json

    # Mock mode (no API calls)
    python -m cosa.agents.deep_research.narrowing_harness \\
        --input plan.json --mock
"""

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Any

from .prompts.planning import THEME_CLUSTERING_PROMPT, get_theme_clustering_prompt


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class NarrowingResult:
    """
    Complete output from progressive narrowing phase.

    Contains all intermediate states for debugging and inspection.
    """
    # Input
    original_subqueries   : List[ dict ]

    # Theme clustering output
    themes                : List[ dict ]
    clustering_raw        : dict = field( default_factory=dict )

    # Theme selection
    selected_theme_indices: List[ int ] = field( default_factory=list )

    # Topics from selected themes (index, subquery pairs)
    candidate_subqueries  : List[ tuple ] = field( default_factory=list )

    # Topic refinement
    selected_topic_indices: List[ int ] = field( default_factory=list )

    # Final output
    final_subqueries      : List[ dict ] = field( default_factory=list )
    final_indices         : List[ int ] = field( default_factory=list )

    # Metrics
    api_calls_made        : int   = 0
    duration_seconds      : float = 0.0
    cancelled             : bool  = False
    cancellation_reason   : str   = ""

    def to_dict( self ) -> dict:
        """Convert result to JSON-serializable dict."""
        return {
            "original_subqueries"   : self.original_subqueries,
            "themes"                : self.themes,
            "clustering_raw"        : self.clustering_raw,
            "selected_theme_indices": self.selected_theme_indices,
            "candidate_subqueries"  : [
                { "index": i, "subquery": sq }
                for i, sq in self.candidate_subqueries
            ],
            "selected_topic_indices": self.selected_topic_indices,
            "final_subqueries"      : self.final_subqueries,
            "final_indices"         : self.final_indices,
            "api_calls_made"        : self.api_calls_made,
            "duration_seconds"      : self.duration_seconds,
            "cancelled"             : self.cancelled,
            "cancellation_reason"   : self.cancellation_reason,
        }


# =============================================================================
# Narrowing Harness Class
# =============================================================================

class NarrowingHarness:
    """
    Isolated harness for testing progressive narrowing logic.

    Interaction modality is handled by voice_io module:
    - Voice-first with automatic CLI fallback
    - Call voice_io.set_cli_mode(True) before instantiation to force CLI

    Usage:
        # With real API client (voice-first, CLI fallback)
        from .api_client import ResearchAPIClient
        api_client = ResearchAPIClient()
        harness = NarrowingHarness( api_client=api_client )

        # With mock client + auto-approve
        from .narrowing_mocks import MockResearchAPIClient
        mock_client = MockResearchAPIClient()
        harness = NarrowingHarness( api_client=mock_client, auto_approve=True )

        # Run narrowing
        result = await harness.run_full_narrowing( subqueries )
    """

    def __init__(
        self,
        api_client: Any = None,
        auto_approve: bool = False,
        debug: bool = False,
        verbose: bool = False
    ):
        """
        Initialize the narrowing harness.

        Note: Interaction modality (voice vs CLI) is controlled by voice_io module.
        Call voice_io.set_cli_mode(True) before instantiation to force CLI mode.

        Args:
            api_client: API client (real or mock) for theme clustering
            auto_approve: If True, auto-approve all selections
            debug: Enable debug output
            verbose: Enable verbose output
        """
        self.api_client   = api_client
        self.auto_approve = auto_approve
        self.debug        = debug
        self.verbose      = verbose

        if self.debug:
            print( f"[NarrowingHarness] auto_approve={self.auto_approve}" )

    async def run_theme_clustering( self, subqueries: List[ dict ] ) -> dict:
        """
        Run ONLY theme clustering on existing subqueries.

        Requires:
            - subqueries is a non-empty list of dicts with 'topic' key
            - api_client is configured

        Ensures:
            - Returns dict with 'themes' key
            - Each theme has 'name', 'description', 'subquery_indices'

        Args:
            subqueries: List of subquery dicts from planning response

        Returns:
            dict: Theme clustering response
        """
        if self.debug:
            print( f"[NarrowingHarness] Clustering {len( subqueries )} subqueries into themes" )

        user_message = get_theme_clustering_prompt( subqueries )

        response = await self.api_client.call_with_json_output(
            system_prompt = THEME_CLUSTERING_PROMPT,
            user_message  = user_message,
            call_type     = "theme_clustering",
        )

        if self.debug:
            print( f"[NarrowingHarness] Got {len( response.get( 'themes', [] ) )} themes" )

        return response

    async def run_full_narrowing(
        self,
        subqueries: List[ dict ],
        auto_approve: Optional[ bool ] = None
    ) -> NarrowingResult:
        """
        Run complete narrowing pipeline.

        Requires:
            - subqueries is a non-empty list with >3 items
            - api_client is configured

        Ensures:
            - Returns NarrowingResult with all intermediate states
            - On cancellation, result.cancelled is True

        Args:
            subqueries: List of subquery dicts from planning response
            auto_approve: Override instance auto_approve setting

        Returns:
            NarrowingResult: Complete narrowing output
        """
        start_time = time.time()
        auto_approve = auto_approve if auto_approve is not None else self.auto_approve

        result = NarrowingResult(
            original_subqueries = subqueries,
            themes              = [],
        )

        # Import voice_io here to avoid circular imports
        from . import voice_io

        try:
            # Step A: Cluster into themes
            if self.verbose:
                await voice_io.notify( "Organizing topics into themes for selection...", priority="low" )

            clustering_response = await self.run_theme_clustering( subqueries )
            result.clustering_raw = clustering_response
            result.api_calls_made += 1

            themes = clustering_response.get( "themes", [] )

            # Handle edge cases for theme count
            if len( themes ) == 0:
                if self.debug:
                    print( "[NarrowingHarness] No themes returned, using fallback" )
                themes = [ {
                    "name"             : "All Topics",
                    "description"      : f"All {len( subqueries )} research topics",
                    "subquery_indices" : list( range( len( subqueries ) ) )
                } ]

            if len( themes ) > 6:
                if self.debug:
                    print( f"[NarrowingHarness] Truncating {len( themes )} themes to 6" )
                themes = themes[ :6 ]

            result.themes = themes

            # Step B: Theme selection
            if len( themes ) == 1:
                # Single theme - auto-select
                if self.verbose:
                    await voice_io.notify(
                        f"Topics grouped into one theme: {themes[ 0 ][ 'name' ]}.",
                        priority="low"
                    )
                selected_theme_indices = [ 0 ]

            elif auto_approve:
                # Auto-approve - select all themes
                if self.debug:
                    print( "[NarrowingHarness] Auto-approving all themes" )
                selected_theme_indices = list( range( len( themes ) ) )

            else:
                # Interactive theme selection
                if self.verbose:
                    await voice_io.notify(
                        f"I've organized your research into {len( themes )} themes.",
                        priority="medium"
                    )

                try:
                    selected_theme_indices = await voice_io.select_themes( themes )
                except RuntimeError as e:
                    # Technical failure - user already notified by select_themes
                    result.cancelled = True
                    result.cancellation_reason = f"Theme selection failed: {e}"
                    result.duration_seconds = time.time() - start_time
                    return result

            result.selected_theme_indices = selected_theme_indices

            if not selected_theme_indices:
                result.cancelled = True
                result.cancellation_reason = "No themes selected by user"
                result.duration_seconds = time.time() - start_time
                return result

            # Gather topics from selected themes
            selected_subquery_indices = set()
            for ti in selected_theme_indices:
                selected_subquery_indices.update( themes[ ti ].get( "subquery_indices", [] ) )

            candidate_subqueries = [
                ( i, subqueries[ i ] )
                for i in sorted( selected_subquery_indices )
            ]
            result.candidate_subqueries = candidate_subqueries

            # Step C: Topic refinement (only if multiple topics)
            if len( candidate_subqueries ) > 2:
                if auto_approve:
                    # Auto-approve - keep all candidates
                    if self.debug:
                        print( "[NarrowingHarness] Auto-approving all candidate topics" )
                    selected_indices = list( range( len( candidate_subqueries ) ) )

                else:
                    if self.verbose:
                        await voice_io.notify(
                            f"You selected {len( candidate_subqueries )} topics. "
                            "Refine further if needed.",
                            priority="low"
                        )

                    try:
                        selected_indices = await voice_io.select_topics(
                            [ sq for _, sq in candidate_subqueries ]
                        )
                    except RuntimeError as e:
                        # Technical failure - user already notified by select_topics
                        result.cancelled = True
                        result.cancellation_reason = f"Topic selection failed: {e}"
                        result.duration_seconds = time.time() - start_time
                        return result

                result.selected_topic_indices = selected_indices

                if not selected_indices:
                    result.cancelled = True
                    result.cancellation_reason = "No topics selected by user"
                    result.duration_seconds = time.time() - start_time
                    return result

                # Map back to original indices
                final_indices = [ candidate_subqueries[ i ][ 0 ] for i in selected_indices ]

            else:
                final_indices = [ i for i, _ in candidate_subqueries ]
                result.selected_topic_indices = list( range( len( candidate_subqueries ) ) )

            result.final_indices = final_indices
            result.final_subqueries = [ subqueries[ i ] for i in final_indices ]
            result.duration_seconds = time.time() - start_time

            if self.verbose:
                await voice_io.notify(
                    f"Narrowed to {len( result.final_subqueries )} topics.",
                    priority="medium"
                )

            return result

        except Exception as e:
            result.cancelled = True
            result.cancellation_reason = f"Error: {str( e )}"
            result.duration_seconds = time.time() - start_time
            raise

    async def run_from_plan_file( self, plan_path: str ) -> NarrowingResult:
        """
        Load plan from JSON file and run narrowing.

        The plan file should contain a 'subqueries' key with a list of
        subquery dicts.

        Args:
            plan_path: Path to JSON file with research plan

        Returns:
            NarrowingResult: Complete narrowing output
        """
        path = Path( plan_path )
        if not path.exists():
            raise FileNotFoundError( f"Plan file not found: {plan_path}" )

        with open( path, "r" ) as f:
            plan_data = json.load( f )

        subqueries = plan_data.get( "subqueries", [] )
        if not subqueries:
            raise ValueError( "Plan file has no subqueries" )

        if self.debug:
            print( f"[NarrowingHarness] Loaded {len( subqueries )} subqueries from {plan_path}" )

        return await self.run_full_narrowing( subqueries )


# =============================================================================
# CLI Interface
# =============================================================================

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Progressive Narrowing Test Harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run smoke test (no args)
  python -m cosa.agents.deep_research.narrowing_harness

  # Theme clustering only
  python -m cosa.agents.deep_research.narrowing_harness \\
      --input plan.json --phase themes

  # Full narrowing with CLI interaction
  python -m cosa.agents.deep_research.narrowing_harness \\
      --input plan.json --cli-mode

  # Full narrowing with auto-approve
  python -m cosa.agents.deep_research.narrowing_harness \\
      --input plan.json --auto-approve --output result.json

  # Mock mode (no API calls)
  python -m cosa.agents.deep_research.narrowing_harness \\
      --input plan.json --mock
        """
    )

    parser.add_argument(
        "--input", "-i",
        type=str,
        help="Path to JSON file with plan/subqueries"
    )

    parser.add_argument(
        "--output", "-o",
        type=str,
        help="Path to write result JSON (optional)"
    )

    parser.add_argument(
        "--phase",
        type=str,
        choices=[ "themes", "full" ],
        default="full",
        help="Phase to run: 'themes' (clustering only) or 'full' (default)"
    )

    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock API client (no real API calls)"
    )

    parser.add_argument(
        "--cli-mode",
        action="store_true",
        help="Force CLI text interaction instead of voice"
    )

    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Auto-approve all selections (non-interactive)"
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug output"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output"
    )

    parser.add_argument(
        "--sample",
        type=int,
        choices=[ 5, 8 ],
        default=5,
        help="Sample subquery set size when no --input provided (5 or 8, default: 5)"
    )

    return parser.parse_args()


async def run_cli( args: argparse.Namespace ) -> None:
    """Run the harness based on CLI arguments."""
    import cosa.utils.util as cu

    # Configure voice_io modality (only if explicitly requested)
    # Default: voice-first with automatic CLI fallback (handled by voice_io)
    if args.cli_mode:
        from . import voice_io
        voice_io.set_cli_mode( True )

    # Create API client
    if args.mock:
        from .narrowing_mocks import MockResearchAPIClient
        api_client = MockResearchAPIClient( debug=args.debug )
    else:
        from .api_client import ResearchAPIClient
        api_client = ResearchAPIClient( debug=args.debug )

    # Create harness
    # Note: auto_approve is True for mock mode (no interactive prompts)
    harness = NarrowingHarness(
        api_client   = api_client,
        auto_approve = args.auto_approve or args.mock,
        debug        = args.debug,
        verbose      = args.verbose
    )

    # Load input
    if not args.input:
        # Use sample subqueries if no input provided
        from .narrowing_mocks import SAMPLE_SUBQUERIES_5, SAMPLE_SUBQUERIES_8
        subqueries = SAMPLE_SUBQUERIES_8 if args.sample == 8 else SAMPLE_SUBQUERIES_5
        print( f"No input file provided, using {len( subqueries )} sample subqueries (--sample {args.sample})" )
    else:
        path = Path( args.input )
        with open( path, "r" ) as f:
            data = json.load( f )
        subqueries = data.get( "subqueries", [] )
        print( f"Loaded {len( subqueries )} subqueries from {args.input}" )

    # Run appropriate phase
    if args.phase == "themes":
        cu.print_banner( "Theme Clustering Only", prepend_nl=True )
        result = await harness.run_theme_clustering( subqueries )
        print( json.dumps( result, indent=2 ) )

    else:
        cu.print_banner( "Full Progressive Narrowing", prepend_nl=True )
        result = await harness.run_full_narrowing( subqueries )

        print( "\nResult Summary:" )
        print( f"  Themes created: {len( result.themes )}" )
        print( f"  Themes selected: {len( result.selected_theme_indices )}" )
        print( f"  Candidate topics: {len( result.candidate_subqueries )}" )
        print( f"  Final topics: {len( result.final_subqueries )}" )
        print( f"  API calls: {result.api_calls_made}" )
        print( f"  Duration: {result.duration_seconds:.2f}s" )

        if result.cancelled:
            print( f"  Cancelled: {result.cancellation_reason}" )

        # Write output if requested
        if args.output:
            output_path = Path( args.output )
            with open( output_path, "w" ) as f:
                json.dump( result.to_dict(), f, indent=2 )
            print( f"\nResult written to: {args.output}" )

        # Show final subqueries
        if result.final_subqueries:
            print( "\nFinal Subqueries:" )
            for i, sq in enumerate( result.final_subqueries, 1 ):
                print( f"  {i}. {sq.get( 'topic', 'Unknown' )}" )


# =============================================================================
# Smoke Test
# =============================================================================

def quick_smoke_test():
    """Quick smoke test for narrowing harness."""
    import cosa.utils.util as cu

    # Force CLI mode for smoke test (no voice prompts)
    from . import voice_io
    voice_io.set_cli_mode( True )

    cu.print_banner( "Narrowing Harness Smoke Test", prepend_nl=True )

    try:
        # Test 1: NarrowingResult dataclass
        print( "Testing NarrowingResult dataclass..." )
        result = NarrowingResult(
            original_subqueries = [ { "topic": "Test" } ],
            themes              = [ { "name": "Theme1" } ],
        )
        assert result.api_calls_made == 0
        assert result.cancelled is False
        result_dict = result.to_dict()
        assert "original_subqueries" in result_dict
        assert "themes" in result_dict
        print( "✓ NarrowingResult dataclass works" )

        # Test 2: Harness instantiation with mock
        print( "Testing harness instantiation..." )
        from .narrowing_mocks import MockResearchAPIClient
        mock_client = MockResearchAPIClient( debug=True )
        harness = NarrowingHarness(
            api_client   = mock_client,
            auto_approve = True,
            debug        = True
        )
        assert harness.auto_approve is True
        print( "✓ Harness instantiated with mock client" )

        # Test 3: Theme clustering (mock)
        print( "Testing theme clustering (mock)..." )
        from .narrowing_mocks import SAMPLE_SUBQUERIES_5

        async def test_clustering():
            response = await harness.run_theme_clustering( SAMPLE_SUBQUERIES_5 )
            return response

        response = asyncio.run( test_clustering() )
        assert "themes" in response
        assert len( response[ "themes" ] ) > 0
        print( f"✓ Theme clustering returned {len( response[ 'themes' ] )} themes" )

        # Test 4: Full narrowing (mock + auto-approve)
        print( "Testing full narrowing (mock + auto-approve)..." )

        async def test_full_narrowing():
            result = await harness.run_full_narrowing( SAMPLE_SUBQUERIES_5 )
            return result

        result = asyncio.run( test_full_narrowing() )
        assert result.cancelled is False
        assert len( result.final_subqueries ) > 0
        assert result.api_calls_made == 1
        print( f"✓ Full narrowing completed: {len( result.final_subqueries )} final topics" )

        # Test 5: Result serialization
        print( "Testing result serialization..." )
        result_dict = result.to_dict()
        result_json = json.dumps( result_dict, indent=2 )
        assert len( result_json ) > 100
        print( "✓ Result serializes to JSON" )

        # Test 6: Empty themes fallback
        print( "Testing empty themes fallback..." )
        from .narrowing_mocks import MockResearchAPIClient
        empty_client = MockResearchAPIClient( debug=True, theme_variant="empty" )
        empty_harness = NarrowingHarness(
            api_client   = empty_client,
            auto_approve = True,
            debug        = True
        )

        async def test_empty_themes():
            result = await empty_harness.run_full_narrowing( SAMPLE_SUBQUERIES_5 )
            return result

        result = asyncio.run( test_empty_themes() )
        # Should have created fallback "All Topics" theme
        assert len( result.themes ) == 1
        assert result.themes[ 0 ][ "name" ] == "All Topics"
        print( "✓ Empty themes fallback works" )

        print( "\n✓ Narrowing harness smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


# =============================================================================
# Main Entry Point
# =============================================================================

def _has_cli_args( args: argparse.Namespace ) -> bool:
    """Check if any meaningful CLI arguments were provided."""
    return any( [
        args.input,
        args.output,
        args.mock,
        args.cli_mode,
        args.auto_approve,
        args.verbose,
        args.debug,
        args.phase != "full",   # non-default phase
        args.sample != 5,       # non-default sample size
    ] )


if __name__ == "__main__":
    args = parse_args()

    # Run smoke test only if NO arguments provided
    if not _has_cli_args( args ):
        quick_smoke_test()
    else:
        asyncio.run( run_cli( args ) )
