#!/usr/bin/env python3
"""
Shared configuration for all proxy agents.

Connection defaults, reconnection parameters, and credential resolution
used by both the notification proxy and decision proxy.

Dependency Rule:
    This module NEVER imports from notification_proxy, decision_proxy, or swe_team.
"""

import os


# ============================================================================
# Connection Defaults
# ============================================================================

DEFAULT_SERVER_HOST = "localhost"
DEFAULT_SERVER_PORT = 7999


# ============================================================================
# Reconnection Parameters
# ============================================================================

RECONNECT_INITIAL_DELAY  = 1.0     # seconds
RECONNECT_MAX_DELAY      = 30.0    # seconds
RECONNECT_MAX_ATTEMPTS   = 10
RECONNECT_BACKOFF_FACTOR = 2.0


# ============================================================================
# Credential Resolution
# ============================================================================

def get_credentials( cli_email=None, cli_password=None ):
    """
    Resolve login credentials with 2-tier priority: CLI > env vars.

    Requires:
        - At least one source provides both email and password

    Ensures:
        - Returns ( email, password ) tuple
        - Raises ValueError if either credential cannot be resolved

    Priority:
        1. CLI flags ( --email / --password )
        2. LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD

    Raises:
        ValueError: If email or password cannot be resolved from any source
    """
    # --- Email resolution ---
    email = (
        cli_email
        or os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    )

    if not email:
        raise ValueError(
            "No email found. Set one of:\n"
            "  --email <addr>                                (CLI flag)\n"
            "  LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL=<addr>  (env var)"
        )

    # --- Password resolution ---
    password = (
        cli_password
        or os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    )

    if not password:
        raise ValueError(
            "No password found. Set one of:\n"
            "  --password <pw>                                  (CLI flag)\n"
            "  LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD=<pw>   (env var)"
        )

    return email, password


# ============================================================================
# API Key Resolution
# ============================================================================

def get_anthropic_api_key():
    """
    Resolve Anthropic API key using the firewalled pattern.

    Requires:
        - ANTHROPIC_API_KEY_FIREWALLED env var is set, OR
        - src/conf/keys/anthropic-api-key-firewalled file exists

    Ensures:
        - Returns API key string on success
        - Returns None if no key found

    Returns:
        str or None: Anthropic API key
    """
    # Priority 1: Environment variable
    key = os.environ.get( "ANTHROPIC_API_KEY_FIREWALLED" )
    if key:
        return key

    # Priority 2: Local file
    try:
        import cosa.utils.util as cu
        key = cu.get_api_key( "anthropic-api-key-firewalled" )
        if key:
            return key
    except Exception:
        pass

    return None
