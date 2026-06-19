#!/usr/bin/env python3
"""
CLI Entry Point for COSA SWE Team Agent.

Usage:
    python -m cosa.agents.swe_team "Implement a health check endpoint"
    python -m cosa.agents.swe_team "Add JWT auth" --dry-run
    python -m cosa.agents.swe_team "Fix bug #42" --dry-run --debug
"""

import argparse
import asyncio
import sys

from .config import SweTeamConfig
from .orchestrator import SweTeamOrchestrator


def main():
    """
    CLI entry point for the SWE Team agent.

    Ensures:
        - Parses command-line arguments
        - Creates config and orchestrator
        - Runs the task and reports results
        - Returns appropriate exit code
    """
    parser = argparse.ArgumentParser(
        description="COSA SWE Team — Multi-Agent Engineering Team",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m cosa.agents.swe_team "Implement health check endpoint"
    python -m cosa.agents.swe_team "Add JWT auth" --dry-run
    python -m cosa.agents.swe_team "Fix tests" --dry-run --debug --verbose
        """,
    )

    parser.add_argument(
        "task",
        nargs="?",
        default=None,
        help="Task description for the SWE Team to execute",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Simulate execution without making API calls",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Enable debug output",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Enable verbose output",
    )
    parser.add_argument(
        "--lead-model",
        default=None,
        help="Override lead model (default: claude-opus-4-6)",
    )
    parser.add_argument(
        "--worker-model",
        default=None,
        help="Override worker model (default: claude-sonnet-4-6)",
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=None,
        help="Override budget limit in USD (default: 5.00)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Override wall-clock timeout in seconds (default: 1800)",
    )
    parser.add_argument(
        "--user-visible-args",
        action="store_true",
        default=False,
        help="Print user-visible args as JSON and exit (for expeditor)",
    )

    args = parser.parse_args()

    # Handle --user-visible-args early exit
    if args.user_visible_args:
        import json
        print( json.dumps( [ "task", "budget", "timeout", "dry_run" ] ) )
        sys.exit( 0 )

    # Guard: task is required for normal execution
    if not args.task:
        parser.error( "task is required" )

    # Build config from arguments
    config_kwargs = { "dry_run": args.dry_run }
    if args.lead_model:   config_kwargs[ "lead_model" ]             = args.lead_model
    if args.worker_model: config_kwargs[ "worker_model" ]           = args.worker_model
    if args.budget:       config_kwargs[ "budget_usd" ]             = args.budget
    if args.timeout:      config_kwargs[ "wall_clock_timeout_secs" ] = args.timeout

    config = SweTeamConfig( **config_kwargs )

    if args.debug:
        print( f"[CLI] Task: {args.task}" )
        print( f"[CLI] Config: dry_run={config.dry_run}, lead={config.lead_model}, worker={config.worker_model}" )
        print( f"[CLI] Budget: ${config.budget_usd:.2f}, Timeout: {config.wall_clock_timeout_secs}s" )

    # Create and run orchestrator
    orchestrator = SweTeamOrchestrator(
        task_description = args.task,
        config           = config,
        debug            = args.debug,
        verbose          = args.verbose,
    )

    result = asyncio.run( orchestrator.run() )

    if result:
        print( f"\n{'=' * 60}" )
        print( "SWE Team Result:" )
        print( f"{'=' * 60}" )
        print( result )
        print( f"{'=' * 60}" )

        state = orchestrator.get_state()
        if args.verbose:
            print( f"\nSession: {state[ 'session_id' ]}" )
            print( f"Guard:   {state[ 'guard_status' ]}" )

        sys.exit( 0 )
    else:
        print( "\nSWE Team task failed. Check logs for details." )
        sys.exit( 1 )


if __name__ == "__main__":
    main()
