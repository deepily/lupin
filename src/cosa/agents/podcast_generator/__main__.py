#!/usr/bin/env python3
"""
Entry point for COSA Podcast Generator Agent.

Run with: python -m cosa.agents.podcast_generator

Usage:
    # Generate podcast script from research document
    python -m cosa.agents.podcast_generator --research path/to/research.md

    # Resume editing an existing script (skip generation, go to review)
    python -m cosa.agents.podcast_generator --edit-script path/to/script.md

    # Run all module smoke tests
    python -m cosa.agents.podcast_generator --smoke-test

    # Dry run (show what would happen)
    python -m cosa.agents.podcast_generator --research research.md --dry-run
"""

import argparse
import asyncio
import re
import sys

# User-visible args: the canonical list of args that end users should see
# and interact with. Engineering params (models, debug, etc.) are excluded.
USER_VISIBLE_ARGS = [ "research", "languages", "audience", "audience_context" ]


def extract_user_id_from_path( path: str ) -> str:
    """
    Extract user ID (email) from podcast script or audio path.

    Parses paths like:
        io/podcasts/{email}/script.md
        /full/path/io/podcasts/{email}/2026.01.19-script.md

    Requires:
        - path contains /podcasts/{email}/ pattern

    Ensures:
        - Returns extracted email if found
        - Returns None if pattern not found

    Args:
        path: File path to parse

    Returns:
        str or None: Extracted email or None
    """
    # Pattern: /podcasts/{email}/ where email contains @ and no slashes
    pattern = r'/podcasts/([^/]+@[^/]+)/'
    match = re.search( pattern, path )
    if match:
        return match.group( 1 )
    return None


def run_all_smoke_tests():
    """Run smoke tests for all podcast generator modules."""
    import cosa.utils.util as cu

    cu.print_banner( "Podcast Generator - Full Smoke Test Suite", prepend_nl=True )

    modules = [
        ( "config", "cosa.agents.podcast_generator.config" ),
        ( "state", "cosa.agents.podcast_generator.state" ),
        ( "prompts.script_generation", "cosa.agents.podcast_generator.prompts.script_generation" ),
        ( "prompts.personality", "cosa.agents.podcast_generator.prompts.personality" ),
        ( "cosa_interface", "cosa.agents.podcast_generator.cosa_interface" ),
        ( "voice_io", "cosa.agents.podcast_generator.voice_io" ),
        ( "api_client", "cosa.agents.podcast_generator.api_client" ),
        ( "tts_client", "cosa.agents.podcast_generator.tts_client" ),
        ( "audio_stitcher", "cosa.agents.podcast_generator.audio_stitcher" ),
        ( "orchestrator", "cosa.agents.podcast_generator.orchestrator" ),
    ]

    results = []

    for name, module_path in modules:
        try:
            print( f"\n{'='*60}" )
            print( f"Running: {name}" )
            print( '='*60 )

            module = __import__( module_path, fromlist=[ "quick_smoke_test" ] )
            module.quick_smoke_test()
            results.append( ( name, "PASSED", None ) )

        except Exception as e:
            results.append( ( name, "FAILED", str( e ) ) )

    # Summary table
    print( f"\n{'='*60}" )
    print( "SMOKE TEST SUMMARY" )
    print( '='*60 )

    passed = sum( 1 for _, status, _ in results if status == "PASSED" )
    failed = sum( 1 for _, status, _ in results if status == "FAILED" )

    for name, status, error in results:
        status_icon = "✓" if status == "PASSED" else "✗"
        print( f"  {status_icon} {name}: {status}" )
        if error:
            print( f"      Error: {error[:60]}" )

    print( f"\nTotal: {passed} passed, {failed} failed out of {len( results )} modules" )

    return failed == 0


def parse_languages_arg( languages_str: str ) -> list:
    """
    Parse comma-separated language codes into a list.

    Args:
        languages_str: Comma-separated ISO codes (e.g., "en,es-MX")

    Returns:
        list: List of language codes
    """
    if not languages_str:
        return None
    return [ lang.strip() for lang in languages_str.split( "," ) if lang.strip() ]


async def run_podcast_generation( args ):
    """Run the podcast generation workflow."""
    from .orchestrator import PodcastOrchestratorAgent
    from .config import PodcastConfig, LANGUAGE_NAMES
    from . import voice_io
    import cosa.utils.util as cu

    cu.print_banner( "COSA Podcast Generator", prepend_nl=True )

    # Configure CLI mode if requested
    if args.cli_mode:
        voice_io.set_cli_mode( True )
        print( "  [CLI mode enabled - text-only interaction]" )

    # Parse target languages
    target_languages = parse_languages_arg( args.languages )
    if target_languages:
        # Validate language codes
        for lang in target_languages:
            if lang not in LANGUAGE_NAMES and lang.split( "-" )[ 0 ] not in LANGUAGE_NAMES:
                print( f"Warning: Unknown language code '{lang}'. Known codes: {', '.join( LANGUAGE_NAMES.keys() )}" )

    # Validate research document exists
    import os
    research_path = args.research

    if not research_path.startswith( "/" ):
        research_path = cu.get_project_root() + "/" + research_path

    if not os.path.exists( research_path ):
        print( f"Error: Research document not found: {research_path}" )
        return 1

    print( f"Research document: {research_path}" )
    print( f"User ID: {args.user_id}" )
    if target_languages:
        lang_names = [ LANGUAGE_NAMES.get( l, l ) for l in target_languages ]
        print( f"Target languages: {', '.join( lang_names )}" )

    if args.dry_run:
        print( "\n[DRY RUN MODE - No API calls will be made]" )
        print( "\nWould execute:" )
        print( "  1. Load research document" )
        print( "  2. Analyze content for key topics" )
        print( "  3. Generate podcast script (English)" )
        print( "  4. Wait for script review" )
        if target_languages and len( target_languages ) > 1:
            non_en_langs = [ l for l in target_languages if l != "en" ]
            for lang in non_en_langs:
                print( f"  4b. Generate {LANGUAGE_NAMES.get( lang, lang )} script" )
                print( f"      Wait for {LANGUAGE_NAMES.get( lang, lang )} script review" )
        print( "  5. Generate TTS audio (per language)" )
        print( "  6. Stitch audio into final MP3(s)" )
        return 0

    # Create config
    config = PodcastConfig()

    # Target audience configuration (CLI overrides config file)
    from cosa.config.configuration_manager import ConfigurationManager
    config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    config.audience = args.audience or config_mgr.get(
        "podcast generator audience",
        default="academic"
    )
    audience_context_from_config = config_mgr.get( "podcast generator audience context", default="" )
    config.audience_context = args.audience_context or audience_context_from_config or None

    # Create orchestrator with target languages
    agent = PodcastOrchestratorAgent(
        research_doc_path = research_path,
        user_id           = args.user_id,
        config            = config,
        target_languages  = target_languages,
        debug             = args.debug,
        verbose           = args.verbose,
    )

    print( f"Podcast ID: {agent.podcast_id}" )
    if config.audience:
        print( f"Target audience: {config.audience}" )
    if config.audience_context:
        print( f"Audience context: {config.audience_context}" )
    print( "" )

    # Run the workflow
    try:
        script = await agent.do_all_async()

        if script:
            print( f"\n✓ Podcast script generated successfully!" )
            print( f"  Title: {script.title}" )
            print( f"  Segments: {script.get_segment_count()}" )
            print( f"  Duration: ~{script.estimated_duration_minutes:.1f} minutes" )

            state = agent.get_state()
            print( f"  Cost: ${agent.api_client.cost_estimate.estimated_cost_usd:.4f}" )
            return 0
        else:
            print( "\n⚠ Podcast generation was cancelled." )
            return 1

    except KeyboardInterrupt:
        print( "\n\n⚠ Interrupted by user." )
        return 1

    except Exception as e:
        print( f"\n✗ Podcast generation failed: {e}" )
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1


async def run_script_editing( args ):
    """Run the script editing workflow (skip generation, go to review)."""
    from .orchestrator import PodcastOrchestratorAgent
    from .config import PodcastConfig
    from . import voice_io
    import cosa.utils.util as cu

    cu.print_banner( "COSA Podcast Generator - Edit Mode", prepend_nl=True )

    # Configure CLI mode if requested
    if args.cli_mode:
        voice_io.set_cli_mode( True )
        print( "  [CLI mode enabled - text-only interaction]" )

    # Validate script file exists
    import os
    script_path = args.edit_script

    if not script_path.startswith( "/" ):
        script_path = cu.get_project_root() + "/" + script_path

    if not os.path.exists( script_path ):
        print( f"Error: Script file not found: {script_path}" )
        return 1

    print( f"Loading script: {script_path}" )
    print( f"User ID: {args.user_id}" )
    print( "" )

    # Create config
    config = PodcastConfig()

    try:
        # Create orchestrator from saved script
        agent = await PodcastOrchestratorAgent.from_saved_script(
            script_path = script_path,
            user_id     = args.user_id,
            config      = config,
            debug       = args.debug,
            verbose     = args.verbose,
        )

        print( f"Podcast ID: {agent.podcast_id}" )
        print( f"Loaded: {agent._podcast_state[ 'draft_script' ].title}" )
        print( f"Segments: {agent._podcast_state[ 'draft_script' ].get_segment_count()}" )
        print( f"Revision count: {agent._podcast_state[ 'revision_count' ]}" )
        print( "" )

        # Run review-only workflow
        script = await agent.do_review_only_async()

        if script:
            print( f"\n✓ Script editing complete!" )
            print( f"  Title: {script.title}" )
            print( f"  Segments: {script.get_segment_count()}" )
            print( f"  Revisions: {script.revision_count}" )
            return 0
        else:
            print( "\n⚠ Script editing was cancelled." )
            return 1

    except KeyboardInterrupt:
        print( "\n\n⚠ Interrupted by user." )
        return 1

    except Exception as e:
        print( f"\n✗ Script editing failed: {e}" )
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1


async def run_audio_generation( args ):
    """Run the audio generation workflow only (skip script generation/review)."""
    from .orchestrator import PodcastOrchestratorAgent
    from .config import PodcastConfig, LANGUAGE_NAMES
    from . import voice_io
    import cosa.utils.util as cu

    cu.print_banner( "COSA Podcast Generator - Audio Only Mode", prepend_nl=True )

    # Configure CLI mode if requested
    if args.cli_mode:
        voice_io.set_cli_mode( True )
        print( "  [CLI mode enabled - text-only interaction]" )

    # Parse target languages
    target_languages = parse_languages_arg( args.languages )

    # Validate script file exists
    import os
    script_path = args.generate_audio

    if not script_path.startswith( "/" ):
        script_path = cu.get_project_root() + "/" + script_path

    if not os.path.exists( script_path ):
        print( f"Error: Script file not found: {script_path}" )
        return 1

    # Determine user_id: extract from path if not explicitly provided
    user_id = args.user_id
    if user_id == "user@example.com":  # Default value - try to extract from path
        extracted = extract_user_id_from_path( script_path )
        if extracted:
            user_id = extracted
            print( f"  [User ID extracted from path: {user_id}]" )

    print( f"Loading script: {script_path}" )
    print( f"User ID: {user_id}" )
    if args.max_segments:
        print( f"Max segments: {args.max_segments}" )
    if target_languages:
        lang_names = [ LANGUAGE_NAMES.get( l, l ) for l in target_languages ]
        print( f"Target languages: {', '.join( lang_names )}" )
    print( "" )

    # Create config
    config = PodcastConfig()

    try:
        # Create orchestrator from saved script
        agent = await PodcastOrchestratorAgent.from_saved_script(
            script_path      = script_path,
            user_id          = user_id,
            config           = config,
            max_segments     = args.max_segments,
            target_languages = target_languages,
            debug            = args.debug,
            verbose          = args.verbose,
        )

        print( f"Podcast ID: {agent.podcast_id}" )
        print( f"Loaded: {agent._podcast_state[ 'draft_script' ].title}" )
        print( f"Segments: {agent._podcast_state[ 'draft_script' ].get_segment_count()}" )
        print( "" )

        # Run audio-only workflow (skip review, go directly to TTS)
        script = await agent.do_audio_only_async()

        if script:
            audio_path = agent._podcast_state.get( "final_audio_path", "unknown" )
            print( f"\n✓ Audio generation complete!" )
            print( f"  Title: {script.title}" )
            print( f"  Segments: {script.get_segment_count()}" )
            print( f"  Audio: {audio_path}" )
            return 0
        else:
            print( "\n⚠ Audio generation was cancelled." )
            return 1

    except KeyboardInterrupt:
        print( "\n\n⚠ Interrupted by user." )
        return 1

    except Exception as e:
        print( f"\n✗ Audio generation failed: {e}" )
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
        description = "COSA Podcast Generator Agent - Transform research into podcasts",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = """
Examples:
  # Generate podcast from research document (English only)
  python -m cosa.agents.podcast_generator --research io/deep-research/output.md

  # Generate podcast in English and Mexican Spanish
  python -m cosa.agents.podcast_generator --research research.md --languages en,es-MX

  # Generate Spanish-only podcast
  python -m cosa.agents.podcast_generator --research research.md --languages es-MX

  # Run all smoke tests
  python -m cosa.agents.podcast_generator --smoke-test

  # Dry run to see what would happen
  python -m cosa.agents.podcast_generator --research research.md --dry-run

Language codes:
  en      English (default)
  es      Spanish (generic)
  es-MX   Mexican Spanish
  es-ES   Castilian Spanish (Spain)
  es-AR   Argentinian Spanish
"""
    )

    parser.add_argument(
        "--research", "-r",
        help = "Path to Deep Research markdown document"
    )

    parser.add_argument(
        "--user-id", "-u",
        default = "user@example.com",
        help = "User ID for output directory (default: user@example.com)"
    )

    parser.add_argument(
        "--dry-run",
        action = "store_true",
        help = "Show what would happen without making API calls"
    )

    parser.add_argument(
        "--smoke-test",
        action = "store_true",
        help = "Run all module smoke tests"
    )

    parser.add_argument(
        "--debug", "-d",
        action = "store_true",
        help = "Enable debug output"
    )

    parser.add_argument(
        "--verbose", "-v",
        action = "store_true",
        help = "Enable verbose output"
    )

    parser.add_argument(
        "--cli-mode",
        action = "store_true",
        help = "Force CLI text mode (no voice notifications)"
    )

    parser.add_argument(
        "--edit-script", "-e",
        help = "Path to saved script markdown to resume editing (skips generation)"
    )

    parser.add_argument(
        "--generate-audio", "-a",
        help = "Path to saved script markdown to generate audio only (skips script generation/review)"
    )

    parser.add_argument(
        "--max-segments", "-m",
        type    = int,
        default = None,
        help    = "Limit TTS generation to first N segments (for cost control during testing)"
    )

    parser.add_argument(
        "--languages", "-l",
        default = None,
        help    = "Comma-separated ISO language codes (e.g., 'en' or 'en,es-MX'). Default: en only"
    )

    parser.add_argument(
        "--audience",
        type    = str,
        choices = [ "beginner", "general", "expert", "academic" ],
        default = None,
        help    = "Target audience level (default: academic from config). Options: beginner, general, expert, academic"
    )

    parser.add_argument(
        "--audience-context",
        type    = str,
        default = None,
        help    = "Custom audience description (e.g., 'AI architect familiar with LLMs')"
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

    # Route to appropriate mode
    if args.generate_audio:
        # Audio-only mode (skip script generation/review)
        exit_code = asyncio.run( run_audio_generation( args ) )
        sys.exit( exit_code )

    if args.edit_script:
        # Edit existing script (skip generation)
        exit_code = asyncio.run( run_script_editing( args ) )
        sys.exit( exit_code )

    # Require research document for generation
    if not args.research:
        parser.print_help()
        print( "\nError: --research or --edit-script argument is required" )
        print( "       Use --smoke-test to run tests instead" )
        sys.exit( 1 )

    # Run podcast generation
    exit_code = asyncio.run( run_podcast_generation( args ) )
    sys.exit( exit_code )


if __name__ == "__main__":
    main()
