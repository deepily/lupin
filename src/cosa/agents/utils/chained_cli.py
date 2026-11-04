#!/usr/bin/env python3
"""
Shared command-line pieces for the chained Deep Research pipelines.

The podcast and presentation pipelines each run as a script and share the
Deep Research options, the mode options and the shape of ``main``. This
module holds those parts. Each package adds its own generator options.
"""

import argparse
import asyncio
import json
import sys


def add_deep_research_arguments( parser: argparse.ArgumentParser ) -> None:
    """
    Add the query, user and Deep Research options to a parser.

    Requires:
        - parser is an argparse.ArgumentParser

    Ensures:
        - adds --query, --user-email, --budget, --lead-model, --no-confirm,
          --audience and --audience-context, in that order
        - --query and --user-email are required

    Raises:
        - None
    """
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


def add_mode_arguments( parser: argparse.ArgumentParser ) -> None:
    """
    Add the mode and debug options to a parser.

    Requires:
        - parser is an argparse.ArgumentParser

    Ensures:
        - adds --cli-mode, --dry-run, --debug, --verbose and
          --user-visible-args, in that order

    Raises:
        - None
    """
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


def run_chained_cli( parse_args, show_dry_run, run_pipeline, user_visible_args ) -> None:
    """
    Run the shared main flow of a chained pipeline script, then exit.

    Requires:
        - parse_args is a callable returning an argparse.Namespace with dry_run
        - show_dry_run is a callable taking that namespace
        - run_pipeline is an async callable taking that namespace, returning an int
        - user_visible_args is a list that json.dumps can encode

    Ensures:
        - with --user-visible-args in sys.argv, prints the list as JSON and exits 0,
          before parse_args runs
        - on --dry-run, calls show_dry_run and exits 0
        - otherwise exits with the code run_pipeline returns

    Raises:
        - SystemExit always
    """
    # Handle --user-visible-args early (before argparse enforces required args)
    if "--user-visible-args" in sys.argv:
        print( json.dumps( user_visible_args ) )
        sys.exit( 0 )

    args = parse_args()

    # Handle dry run
    if args.dry_run:
        show_dry_run( args )
        sys.exit( 0 )

    # Run the pipeline
    exit_code = asyncio.run( run_pipeline( args ) )
    sys.exit( exit_code )
