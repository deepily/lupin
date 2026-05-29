#!/usr/bin/env python3
"""
CLI entry point for the Notification Proxy Agent.

Connects to the Lupin WebSocket, subscribes to notification events,
and automatically answers expediter questions using a hybrid strategy:
rules for known patterns, LLM fallback for unknowns.

Usage:
    python -m cosa.agents.notification_proxy
    python -m cosa.agents.notification_proxy --profile deep_research
    python -m cosa.agents.notification_proxy --email mock.tester@lupin.deepily.ai
    python -m cosa.agents.notification_proxy --debug --verbose
"""

import argparse
import asyncio
import signal
import sys

from cosa.agents.notification_proxy.config import (
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
    DEFAULT_SESSION_ID,
    DEFAULT_PROFILE,
    DEFAULT_STRATEGY,
    STRATEGY_CHOICES,
    TEST_PROFILES,
    get_credentials,
)
from cosa.agents.notification_proxy.listener import WebSocketListener
from cosa.agents.notification_proxy.responder import NotificationResponder
from cosa.agents.notification_proxy.voice_io import notify


def parse_args():
    """
    Parse command-line arguments.

    Ensures:
        - Returns argparse.Namespace with all config parameters
        - Provides sensible defaults for all options
    """
    parser = argparse.ArgumentParser(
        prog        = "notification_proxy",
        description = "Notification Proxy Agent — auto-responds to expediter questions"
    )

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
        default = DEFAULT_SESSION_ID,
        help    = f"WebSocket session ID (default: '{DEFAULT_SESSION_ID}')"
    )
    parser.add_argument(
        "--profile",
        default = DEFAULT_PROFILE,
        choices = list( TEST_PROFILES.keys() ),
        help    = f"Test profile for auto-answers (default: {DEFAULT_PROFILE})"
    )
    parser.add_argument(
        "--strategy",
        default = DEFAULT_STRATEGY,
        choices = STRATEGY_CHOICES,
        help    = f"Response strategy: llm_script (Phi-4), rules (keywords), auto (Phi-4 + rules fallback). Default: {DEFAULT_STRATEGY}"
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
        help    = "Display notifications without computing or submitting responses"
    )

    return parser.parse_args()


async def main():
    """
    Main async entry point — sets up listener and responder, runs event loop.

    Ensures:
        - Connects to WebSocket and starts listening
        - Handles Ctrl+C gracefully
        - Prints statistics on exit
    """
    args = parse_args()

    # Verbose implies debug
    if args.verbose:
        args.debug = True

    # Dry run implies debug
    if args.dry_run:
        args.debug = True

    # Resolve login credentials (CLI > env vars > defaults)
    try:
        email, password = get_credentials( args.email, args.password )
    except ValueError as e:
        print( f"\n[Proxy] Credential error: {e}" )
        sys.exit( 1 )

    # Show startup banner
    profile = TEST_PROFILES[ args.profile ]
    print( "=" * 60 )
    print( "  Notification Proxy Agent" )
    print( "=" * 60 )
    print( f"  Server   : {args.host}:{args.port}" )
    print( f"  Email    : {email}" )
    print( f"  Password : {'***' if password else '(none)'}" )
    print( f"  Session  : {args.session_id}" )
    print( f"  Profile  : {args.profile} — {profile.get( 'description', '' )}" )
    print( f"  Strategy : {args.strategy}" )
    print( f"  Debug    : {args.debug}" )
    print( f"  Dry Run  : {args.dry_run}" )
    print( f"  LLM      : checking..." )

    # Create responder
    responder = NotificationResponder(
        profile_name = args.profile,
        host         = args.host,
        port         = args.port,
        strategy     = args.strategy,
        dry_run      = args.dry_run,
        debug        = args.debug,
        verbose      = args.verbose
    )

    script_status = "n/a"
    if responder.script_strategy is not None:
        script_status = "available" if responder.script_strategy.available else "unavailable"
    print( f"  Phi-4    : {script_status}" )
    print( f"  Cloud    : {'available' if responder.llm_strategy.available else 'unavailable'}" )
    print( "=" * 60 )
    print( "\nListening for notifications... (Ctrl+C to stop)\n" )

    # Create listener with responder as callback
    listener = WebSocketListener(
        email      = email,
        password   = password,
        session_id = args.session_id,
        on_event   = responder.handle_event,
        host       = args.host,
        port       = args.port,
        debug      = args.debug,
        verbose    = args.verbose
    )

    # Send startup notification
    notify(
        "Notification Proxy connected. Listening for expediter questions...",
        priority = "low",
        host     = args.host,
        port     = args.port,
        debug    = args.debug
    )

    # Set up graceful shutdown
    loop = asyncio.get_running_loop()

    def shutdown_handler():
        print( "\n[Proxy] Shutting down..." )
        asyncio.ensure_future( listener.stop() )

    # Register signal handlers (Unix only)
    try:
        loop.add_signal_handler( signal.SIGINT, shutdown_handler )
        loop.add_signal_handler( signal.SIGTERM, shutdown_handler )
    except NotImplementedError:
        # Windows doesn't support add_signal_handler
        pass

    try:
        await listener.run()
    except KeyboardInterrupt:
        pass
    finally:
        # Send disconnect notification
        notify(
            "Notification Proxy disconnected.",
            priority = "low",
            host     = args.host,
            port     = args.port,
            debug    = args.debug
        )

        responder.print_stats()


if __name__ == "__main__":
    try:
        asyncio.run( main() )
    except KeyboardInterrupt:
        print( "\nBye." )
