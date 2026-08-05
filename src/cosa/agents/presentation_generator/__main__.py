#!/usr/bin/env python3
"""
Presentation Generator Agent — CLI entry point.

Run with: python -m cosa.agents.presentation_generator

Usage:
    # Generate presentation from source document
    python -m cosa.agents.presentation_generator --source path/to/document.md

    # Dry run (show what would happen)
    python -m cosa.agents.presentation_generator --source document.md --dry-run

    # Run all module smoke tests
    python -m cosa.agents.presentation_generator --smoke-test
"""

import argparse
import asyncio
import sys

# User-visible args: the canonical list of args that end users should see
# and interact with. Engineering params (models, debug, etc.) are excluded.
USER_VISIBLE_ARGS = [ "source", "target_duration_minutes", "target_slide_count", "audience", "audience_context", "theme" ]


def run_all_smoke_tests():
    """Run smoke tests for all Presentation Generator modules."""
    import cosa.utils.util as cu

    cu.print_banner( "Presentation Generator - Full Smoke Test Suite", prepend_nl=True )

    modules = [
        ( "config",         "cosa.agents.presentation_generator.config" ),
        ( "state",          "cosa.agents.presentation_generator.state" ),
        ( "cosa_interface", "cosa.agents.presentation_generator.cosa_interface" ),
        ( "voice_io",       "cosa.agents.presentation_generator.voice_io" ),
        ( "orchestrator",   "cosa.agents.presentation_generator.orchestrator" ),
        ( "job",            "cosa.agents.presentation_generator.job" ),
    ]

    results = []

    for name, module_path in modules:
        try:
            print( f"\n{'=' * 60}" )
            print( f"Running: {name}" )
            print( '=' * 60 )

            module = __import__( module_path, fromlist=[ "quick_smoke_test" ] )
            module.quick_smoke_test()
            results.append( ( name, "PASSED", None ) )

        except Exception as e:
            results.append( ( name, "FAILED", str( e ) ) )

    # Summary table
    print( f"\n{'=' * 60}" )
    print( "SMOKE TEST SUMMARY" )
    print( '=' * 60 )

    passed = sum( 1 for _, status, _ in results if status == "PASSED" )
    failed = sum( 1 for _, status, _ in results if status == "FAILED" )

    for name, status, error in results:
        status_icon = "✓" if status == "PASSED" else "✗"
        print( f"  {status_icon} {name}: {status}" )
        if error:
            print( f"      Error: {error[:80]}" )

    print( f"\nTotal: {passed} passed, {failed} failed out of {len( results )} modules" )

    return failed == 0


async def run_presentation_generation( args ):
    """Run the presentation generation workflow."""
    from .job import PresentationGeneratorJob
    import cosa.utils.util as cu

    cu.print_banner( "COSA Presentation Generator", prepend_nl=True )

    # Validate source document exists
    import os
    source_path = args.source

    if not source_path.startswith( "/" ):
        source_path = cu.get_project_root() + "/" + source_path

    if not os.path.exists( source_path ):
        print( f"Error: Source document not found: {source_path}" )
        return 1

    print( f"Source document: {source_path}" )
    print( f"User: {args.user_email}" )
    if args.target_duration_minutes:
        print( f"Target duration: {args.target_duration_minutes} minutes" )
    if args.target_slide_count:
        print( f"Target slide count: {args.target_slide_count} slides" )
    if args.audience:
        print( f"Audience: {args.audience}" )
    if args.audience_context:
        print( f"Audience context: {args.audience_context}" )
    if args.theme:
        print( f"Theme: {args.theme}" )

    if args.dry_run:
        print( "\n[DRY RUN MODE — Real ingest, mock analysis/outline/elaborate, real YAML serialization]" )

    # Create job
    job = PresentationGeneratorJob(
        source_path             = source_path,
        user_id                 = args.user_id,
        user_email              = args.user_email,
        session_id              = args.session_id,
        target_duration_minutes = args.target_duration_minutes,
        target_slide_count      = args.target_slide_count,
        audience                = args.audience,
        audience_context        = args.audience_context,
        theme                   = args.theme,
        dry_run                 = args.dry_run,
        debug                   = args.debug,
        verbose                 = args.verbose
    )

    try:
        print( f"\nJob ID: {job.id_hash}" )
        print( "Starting presentation generation...\n" )

        result = await job._execute()
        job.answer_conversational = result

        if job.answer_conversational:
            print( f"\n✓ Presentation generation complete!" )
            print( f"  {job.answer_conversational}" )
            return 0
        else:
            print( "\n⚠ Presentation generation was cancelled or failed." )
            return 1

    except KeyboardInterrupt:
        print( "\n\n⚠ Interrupted by user." )
        return 1

    except Exception as e:
        print( f"\n✗ Presentation generation failed: {e}" )
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

    parser = argparse.ArgumentParser(
        description = "COSA Presentation Generator Agent - Transform documents into slide decks",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = """
Examples:
  # Generate presentation from research document
  python -m cosa.agents.presentation_generator --source io/deep-research/output.md

  # Specify audience and duration
  python -m cosa.agents.presentation_generator --source doc.md --audience expert --target-duration-minutes 20

  # Run all smoke tests
  python -m cosa.agents.presentation_generator --smoke-test

  # Dry run to see what would happen
  python -m cosa.agents.presentation_generator --source doc.md --dry-run
"""
    )

    parser.add_argument(
        "--source", "-s",
        help = "Path to source document (markdown or plain text)"
    )

    parser.add_argument(
        "--target-duration-minutes",
        type    = int,
        default = None,
        help    = "Target presentation duration in minutes (default: 15 from config)"
    )

    parser.add_argument(
        "--target-slide-count",
        type    = int,
        default = None,
        help    = "Explicit slide count, overriding the duration formula (default: derive from duration)"
    )

    parser.add_argument(
        "--audience",
        type    = str,
        choices = [ "beginner", "general", "expert", "academic" ],
        default = None,
        help    = "Target audience level (default: general from config)"
    )

    parser.add_argument(
        "--audience-context",
        type    = str,
        default = None,
        help    = "Custom audience description (e.g., 'AI architect familiar with LLMs')"
    )

    parser.add_argument(
        "--theme",
        type    = str,
        default = None,
        help    = "Presentation theme name (default: default from config)"
    )

    parser.add_argument(
        "--dry-run",
        action = "store_true",
        help   = "Show what would happen without making API calls"
    )

    parser.add_argument(
        "--smoke-test",
        action = "store_true",
        help   = "Run all module smoke tests"
    )

    parser.add_argument(
        "--debug",
        action = "store_true",
        help   = "Enable debug output"
    )

    parser.add_argument(
        "--verbose",
        action = "store_true",
        help   = "Enable verbose output"
    )

    # System-provided args (injected by expeditor, not user-facing)
    parser.add_argument(
        "--user-email",
        default = "user@example.com",
        help    = argparse.SUPPRESS
    )

    parser.add_argument(
        "--user-id",
        default = "user@example.com",
        help    = argparse.SUPPRESS
    )

    parser.add_argument(
        "--session-id",
        default = "cli-session",
        help    = argparse.SUPPRESS
    )

    parser.add_argument(
        "--no-confirm",
        action  = "store_true",
        default = False,
        help    = argparse.SUPPRESS
    )

    parser.add_argument(
        "--user-visible-args",
        action  = "store_true",
        default = False,
        help    = "Print user-visible argument names as JSON and exit"
    )

    args = parser.parse_args()

    # Run smoke tests if requested
    if args.smoke_test:
        success = run_all_smoke_tests()
        sys.exit( 0 if success else 1 )

    # Require source document for generation
    if not args.source:
        parser.print_help()
        print( "\nError: --source argument is required" )
        print( "       Use --smoke-test to run tests instead" )
        sys.exit( 1 )

    # Run presentation generation
    exit_code = asyncio.run( run_presentation_generation( args ) )
    sys.exit( exit_code )


if __name__ == "__main__":
    main()
