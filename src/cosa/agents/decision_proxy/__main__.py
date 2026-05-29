#!/usr/bin/env python3
"""
CLI entry point for the Decision Proxy Agent.

Connects to the Lupin WebSocket, subscribes to notification events,
and automatically handles decisions using a trust-aware strategy chain.

Usage:
    python -m cosa.agents.decision_proxy
    python -m cosa.agents.decision_proxy --profile swe_team --trust-mode shadow
    python -m cosa.agents.decision_proxy --debug --verbose
    python -m cosa.agents.decision_proxy --dry-run

Profiles:
    swe_team: SWE engineering decisions (deployment, testing, deps, etc.)
"""

import argparse
import asyncio
import signal
import sys

from cosa.agents.utils.proxy_agents.base_cli import add_common_args
from cosa.agents.decision_proxy.config import (
    DEFAULT_SESSION_ID,
    DEFAULT_PROFILE,
    DEFAULT_TRUST_MODE,
    TRUST_MODE_CHOICES,
    TRUST_LEVELS,
    get_credentials,
)
from cosa.agents.decision_proxy.listener import DecisionListener
from cosa.agents.decision_proxy.responder import DecisionResponder
from cosa.agents.decision_proxy.voice_io import notify


# Available profiles — domain layers register themselves here
AVAILABLE_PROFILES = {
    "swe_team" : {
        "description" : "SWE engineering decisions (deployment, testing, deps, architecture, destructive, general)",
        "loader"      : "_load_swe_team_profile",
    },
}


def _load_swe_team_profile( responder, debug=False ):
    """
    Load the SWE team engineering strategy into the responder.

    Requires:
        - cosa.agents.swe_team.proxy package is available

    Ensures:
        - Sets domain_strategy on the responder
        - Registers SWE categories with the responder
        - Returns True on success, False on import failure
    """
    try:
        from cosa.agents.swe_team.proxy.engineering_strategy import SweEngineeringStrategy
        from cosa.agents.swe_team.proxy.config import ACCEPTED_SENDERS

        strategy = SweEngineeringStrategy( debug=debug )
        responder.set_domain_strategy( strategy )
        responder.accepted_senders = ACCEPTED_SENDERS

        if debug: print( "[DecisionProxy] SWE team profile loaded" )
        return True

    except ImportError as e:
        print( f"[DecisionProxy] SWE team profile not available: {e}" )
        print( "[DecisionProxy] Running in shadow-only mode (no domain strategy)" )
        return False


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog        = "decision_proxy",
        description = "Decision Proxy Agent — trust-aware autonomous decision-making"
    )

    # Add shared args (host, port, email, password, session-id, debug, verbose, dry-run)
    add_common_args( parser )

    # Override session-id default
    for action in parser._actions:
        if hasattr( action, "dest" ) and action.dest == "session_id":
            action.default = DEFAULT_SESSION_ID
            break

    # Decision-proxy-specific args
    parser.add_argument(
        "--profile",
        default = DEFAULT_PROFILE,
        choices = list( AVAILABLE_PROFILES.keys() ),
        help    = f"Domain profile to load (default: {DEFAULT_PROFILE})"
    )
    parser.add_argument(
        "--trust-mode",
        default = DEFAULT_TRUST_MODE,
        choices = TRUST_MODE_CHOICES,
        help    = f"Trust operating mode (default: {DEFAULT_TRUST_MODE})"
    )

    return parser.parse_args()


async def main():
    """
    Main async entry point — sets up listener and responder, runs event loop.

    Ensures:
        - Connects to WebSocket and starts listening
        - Loads domain profile strategy
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

    # Resolve login credentials
    try:
        email, password = get_credentials( args.email, args.password )
    except ValueError as e:
        print( f"\n[DecisionProxy] Credential error: {e}" )
        sys.exit( 1 )

    # Show startup banner
    profile_info = AVAILABLE_PROFILES.get( args.profile, {} )
    print( "=" * 60 )
    print( "  Decision Proxy Agent" )
    print( "=" * 60 )
    print( f"  Server      : {args.host}:{args.port}" )
    print( f"  Email       : {email}" )
    print( f"  Session     : {args.session_id}" )
    print( f"  Profile     : {args.profile} -- {profile_info.get( 'description', '' )}" )
    print( f"  Trust Mode  : {args.trust_mode}" )
    print( f"  Debug       : {args.debug}" )
    print( f"  Dry Run     : {args.dry_run}" )

    # Print trust level table
    print( f"\n  Trust Levels:" )
    for level, info in TRUST_LEVELS.items():
        print( f"    L{level}: {info[ 'name' ]:25s} ({info[ 'min_decisions' ]:>5d} decisions) — {info[ 'description' ]}" )

    print( "=" * 60 )

    # Create responder
    responder = DecisionResponder(
        trust_mode = args.trust_mode,
        host       = args.host,
        port       = args.port,
        dry_run    = args.dry_run,
        debug      = args.debug,
        verbose    = args.verbose
    )

    # Load domain profile
    loader_name = profile_info.get( "loader", "" )
    loader_func = globals().get( loader_name )
    if loader_func:
        loader_func( responder, debug=args.debug )
    else:
        print( f"[DecisionProxy] No loader for profile '{args.profile}' — shadow mode" )

    print( "\nListening for decisions... (Ctrl+C to stop)\n" )

    # Create listener
    listener = DecisionListener(
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
        f"Decision Proxy connected. Mode: {args.trust_mode}, Profile: {args.profile}",
        priority = "low",
        host     = args.host,
        port     = args.port,
        debug    = args.debug
    )

    # Set up graceful shutdown
    loop = asyncio.get_running_loop()

    def shutdown_handler():
        print( "\n[DecisionProxy] Shutting down..." )
        asyncio.ensure_future( listener.stop() )

    try:
        loop.add_signal_handler( signal.SIGINT, shutdown_handler )
        loop.add_signal_handler( signal.SIGTERM, shutdown_handler )
    except NotImplementedError:
        pass

    try:
        await listener.run()
    except KeyboardInterrupt:
        pass
    finally:
        notify(
            "Decision Proxy disconnected.",
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
