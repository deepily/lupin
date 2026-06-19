#!/usr/bin/env python3
"""
CLI Entry Point for Deep Research → Podcast Generation Pipeline.

This module provides a command-line interface for running the chained
Deep Research → Podcast Generation workflow.

Usage:
    # Voice-driven mode (default)
    python -m cosa.agents.deep_research_to_podcast \\
        --query "Your research topic" \\
        --user-email user@example.com

    # CLI text mode
    python -m cosa.agents.deep_research_to_podcast \\
        --query "Your research topic" \\
        --user-email user@example.com \\
        --cli-mode

    # With budget control
    python -m cosa.agents.deep_research_to_podcast \\
        --query "State of quantum computing in 2026" \\
        --user-email researcher@example.com \\
        --budget 5.00

    # Dry run (show plan without executing)
    python -m cosa.agents.deep_research_to_podcast \\
        --query "AI safety research trends" \\
        --user-email user@example.com \\
        --dry-run

    # Full options example
    python -m cosa.agents.deep_research_to_podcast \\
        --query "Compare React and Vue frameworks" \\
        --user-email dev@example.com \\
        --budget 3.00 \\
        --languages en,es-MX \\
        --max-segments 10 \\
        --cli-mode \\
        --debug
"""

import argparse
import asyncio
import sys

import cosa.utils.util as cu

# User-visible args: the canonical list of args that end users should see
# and interact with. Engineering params (models, debug, etc.) are excluded.
USER_VISIBLE_ARGS = [ "query", "budget", "languages", "audience", "audience_context" ]


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description = "Deep Research → Podcast Generation Pipeline",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = """
Examples:
  # Basic usage (voice-driven)
  python -m cosa.agents.deep_research_to_podcast \\
      --query "State of quantum computing in 2026" \\
      --user-email researcher@example.com

  # CLI mode with budget control
  python -m cosa.agents.deep_research_to_podcast \\
      --query "AI safety research trends" \\
      --user-email user@example.com \\
      --budget 3.00 \\
      --cli-mode

  # Multi-language podcast
  python -m cosa.agents.deep_research_to_podcast \\
      --query "Global climate policies" \\
      --user-email user@example.com \\
      --languages en,es-MX

  # Dry run to see the plan
  python -m cosa.agents.deep_research_to_podcast \\
      --query "Test topic" \\
      --user-email user@example.com \\
      --dry-run

Mode Options:
  Default behavior is VOICE-DRIVEN:
    - Progress notifications via TTS (text-to-speech)
    - User confirmations via voice input
    - Automatic fallback to CLI if voice unavailable

  Use --cli-mode to force TEXT-ONLY:
    - Progress shown via print statements
    - User confirmations via keyboard input
    - Recommended for automated/scripted runs
"""
    )

    # Required arguments
    parser.add_argument(
        "--query", "-q",
        type     = str,
        required = True,
        help     = "Research topic/question for Deep Research"
    )

    parser.add_argument(
        "--user-email", "-u",
        type     = str,
        required = True,
        help     = "User email for output directories (multi-tenancy)"
    )

    # Deep Research options
    parser.add_argument(
        "--budget", "-b",
        type    = float,
        default = None,
        help    = "Maximum budget in USD for Deep Research (default: unlimited)"
    )

    parser.add_argument(
        "--lead-model",
        type    = str,
        default = None,
        help    = "Model for DR lead agent (default: claude-opus-4-6)"
    )

    parser.add_argument(
        "--no-confirm",
        action  = "store_true",
        help    = "Skip confirmation prompts in Deep Research (auto-approve)"
    )

    parser.add_argument(
        "--audience",
        type    = str,
        choices = [ "beginner", "general", "expert", "academic" ],
        default = None,
        help    = "Target audience level (default: academic from config)"
    )

    parser.add_argument(
        "--audience-context",
        type    = str,
        default = None,
        help    = "Custom audience description (e.g., 'AI architect familiar with LLMs')"
    )

    # Podcast Generator options
    parser.add_argument(
        "--languages", "-l",
        type    = str,
        default = None,
        help    = "Comma-separated ISO language codes (e.g., 'en' or 'en,es-MX'). Default: en"
    )

    parser.add_argument(
        "--max-segments", "-m",
        type    = int,
        default = None,
        help    = "Limit TTS generation to first N segments (cost control)"
    )

    # Mode options
    parser.add_argument(
        "--cli-mode",
        action  = "store_true",
        help    = "Force CLI text mode (default: voice-driven)"
    )

    parser.add_argument(
        "--dry-run",
        action  = "store_true",
        help    = "Show plan without executing"
    )

    # Debug options
    parser.add_argument(
        "--debug", "-d",
        action  = "store_true",
        help    = "Enable debug output"
    )

    parser.add_argument(
        "--verbose", "-v",
        action  = "store_true",
        help    = "Enable verbose output"
    )

    parser.add_argument(
        "--user-visible-args",
        action  = "store_true",
        default = False,
        help    = "Print user-visible argument names as JSON and exit"
    )

    return parser.parse_args()


def parse_languages( languages_str: str ) -> list:
    """
    Parse comma-separated language codes into a list.

    Args:
        languages_str: Comma-separated ISO codes (e.g., "en,es-MX")

    Returns:
        list: List of language codes, or None if empty
    """
    if not languages_str:
        return None
    return [ lang.strip() for lang in languages_str.split( "," ) if lang.strip() ]


def show_dry_run( args: argparse.Namespace ) -> None:
    """Show what the pipeline would do without executing."""
    target_languages = parse_languages( args.languages ) or [ "en" ]

    print( "\n[DRY RUN MODE - No API calls will be made]\n" )
    print( "Pipeline Configuration:" )
    print( f"  Query: {args.query}" )
    print( f"  User Email: {args.user_email}" )
    print( f"  Mode: {'CLI text' if args.cli_mode else 'Voice-driven'}" )
    if args.budget:
        print( f"  Budget: ${args.budget:.2f}" )
    if args.lead_model:
        print( f"  Lead Model: {args.lead_model}" )
    print( f"  Languages: {', '.join( target_languages )}" )
    if args.max_segments:
        print( f"  Max Segments: {args.max_segments}" )
    if args.audience:
        print( f"  Target Audience: {args.audience}" )
    if args.audience_context:
        print( f"  Audience Context: {args.audience_context}" )

    print( "\nExecution Plan:" )
    print( "  Phase 1: Deep Research" )
    print( "    1. Analyze query for clarification needs" )
    print( "    2. Create research plan with subqueries" )
    print( "    3. Execute parallel research subagents" )
    print( "    4. Synthesize findings into report" )
    print( "    5. Save report to /io/deep-research/{user_email}/" )

    print( "\n  Phase 2: Podcast Generation" )
    print( "    1. Load research report" )
    print( "    2. Analyze content for key topics" )
    print( "    3. Generate podcast script (English)" )
    if len( target_languages ) > 1:
        non_en = [ l for l in target_languages if l != "en" ]
        for lang in non_en:
            print( f"    3b. Translate script to {lang}" )
    print( "    4. Generate TTS audio segments" )
    print( "    5. Stitch audio into final MP3" )
    print( "    6. Save podcast to /io/podcasts/{user_email}/" )

    print( "\nExpected Outputs:" )
    print( "  - Research report: /io/deep-research/{user_email}/{date}-{topic}.md" )
    print( "  - Podcast script:  /io/podcasts/{user_email}/{date}-{topic}-script.md" )
    print( "  - Podcast audio:   /io/podcasts/{user_email}/{date}-{topic}.mp3" )


async def run_pipeline( args: argparse.Namespace ) -> int:
    """
    Run the Deep Research → Podcast Generation pipeline.

    Args:
        args: Parsed command-line arguments

    Returns:
        int: Exit code (0 = success, 1 = failure/cancelled)
    """
    from cosa.agents.deep_research_to_podcast import DeepResearchToPodcastAgent
    from cosa.agents.deep_research_to_podcast.state import PipelineState

    cu.print_banner( "Deep Research → Podcast Pipeline", prepend_nl=True )

    # Parse language codes
    target_languages = parse_languages( args.languages )

    # Show configuration
    print( f"Query: {args.query}" )
    print( f"User: {args.user_email}" )
    print( f"Mode: {'CLI text' if args.cli_mode else 'Voice-driven'}" )
    if args.budget:
        print( f"Budget: ${args.budget:.2f}" )
    if target_languages:
        print( f"Languages: {', '.join( target_languages )}" )
    print( "" )

    # Create agent
    agent = DeepResearchToPodcastAgent(
        query            = args.query,
        user_email       = args.user_email,
        budget           = args.budget,
        lead_model       = args.lead_model,
        no_confirm       = args.no_confirm,
        audience         = args.audience,
        audience_context = args.audience_context,
        target_languages = target_languages,
        max_segments     = args.max_segments,
        cli_mode         = args.cli_mode,
        debug            = args.debug,
        verbose          = args.verbose,
    )

    try:
        # Run the pipeline
        result = await agent.run_async()

        # Show results
        print( "\n" + "=" * 60 )
        print( "PIPELINE RESULTS" )
        print( "=" * 60 )

        if result.is_success():
            print( f"\n✓ Pipeline completed successfully!\n" )
            print( f"Research Report: {result.research_path}" )
            if result.research_abstract:
                print( f"Abstract: {result.research_abstract[ :100 ]}..." )
            print( f"\nPodcast Audio: {result.audio_path}" )
            if result.script_path:
                print( f"Podcast Script: {result.script_path}" )
            print( f"\nCost Summary:" )
            print( f"  Deep Research:     ${result.dr_cost:.4f}" )
            print( f"  Podcast Generator: ${result.pg_cost:.4f}" )
            print( f"  Total:             ${result.total_cost:.4f}" )
            print( f"\nDuration: {result.duration_seconds:.1f} seconds" )
            return 0

        elif result.is_partial():
            print( f"\n⚠ Pipeline partially completed\n" )
            print( f"Deep Research completed successfully:" )
            print( f"  Report: {result.research_path}" )
            print( f"  Cost: ${result.dr_cost:.4f}" )
            print( f"\nPodcast Generation failed:" )
            print( f"  Error: {result.error}" )
            print( f"\nYou can retry podcast generation separately with:" )
            print( f"  python -m cosa.agents.podcast_generator --research {result.research_path}" )
            return 1

        else:
            print( f"\n✗ Pipeline failed\n" )
            print( f"State: {result.state.value}" )
            print( f"Error: {result.error}" )
            return 1

    except KeyboardInterrupt:
        print( "\n\n⚠ Interrupted by user" )
        return 1

    except Exception as e:
        print( f"\n✗ Pipeline error: {e}" )
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1


def main():
    """Main entry point."""
    # Handle --user-visible-args early (before argparse enforces required args)
    if "--user-visible-args" in sys.argv:
        import json
        print( json.dumps( USER_VISIBLE_ARGS ) )
        sys.exit( 0 )

    args = parse_args()

    # Handle dry run
    if args.dry_run:
        show_dry_run( args )
        sys.exit( 0 )

    # Run the pipeline
    exit_code = asyncio.run( run_pipeline( args ) )
    sys.exit( exit_code )


if __name__ == "__main__":
    main()
