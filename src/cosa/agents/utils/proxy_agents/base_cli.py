#!/usr/bin/env python3
"""
Shared CLI argument helpers for proxy agents.

Provides common argparse arguments used by all proxy agent CLI entry points:
connection settings, credentials, debugging flags, and dry-run mode.

Dependency Rule:
    This module NEVER imports from notification_proxy, decision_proxy, or swe_team.
"""

from cosa.agents.utils.proxy_agents.base_config import (
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
)


def add_common_args( parser ):
    """
    Add shared CLI arguments to an argparse parser.

    Requires:
        - parser is an argparse.ArgumentParser instance

    Ensures:
        - Adds --host, --port, --email, --password, --session-id,
          --debug, --verbose, --dry-run arguments
        - Does NOT call parse_args() — caller does that

    Args:
        parser: argparse.ArgumentParser to add arguments to

    Returns:
        The parser (for chaining)
    """
    parser.add_argument(
        "--host",
        default = DEFAULT_SERVER_HOST,
        help    = f"Server hostname (default: {DEFAULT_SERVER_HOST})"
    )
    parser.add_argument(
        "--port",
        type    = int,
        default = DEFAULT_SERVER_PORT,
        help    = f"Server port (default: {DEFAULT_SERVER_PORT})"
    )
    parser.add_argument(
        "--email",
        default = None,
        help    = "Login email (overrides env vars)"
    )
    parser.add_argument(
        "--password",
        default = None,
        help    = "Login password (overrides env vars)"
    )
    parser.add_argument(
        "--session-id",
        default = None,
        help    = "WebSocket session ID"
    )
    parser.add_argument(
        "--debug",
        action  = "store_true",
        help    = "Enable debug output"
    )
    parser.add_argument(
        "--verbose",
        action  = "store_true",
        help    = "Enable verbose output (implies debug)"
    )
    parser.add_argument(
        "--dry-run",
        action  = "store_true",
        help    = "Display events without computing or submitting responses"
    )

    return parser
