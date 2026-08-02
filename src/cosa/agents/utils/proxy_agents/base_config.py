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
RECONNECT_MAX_DELAY      = 10.0    # seconds — see "why 10, not 30" below
RECONNECT_MAX_ATTEMPTS   = 10
RECONNECT_BACKOFF_FACTOR = 2.0

# Jitter is applied DOWNWARD ONLY: the delay is drawn from
# [ (1 - RECONNECT_JITTER_FRACTION) * base, base ]. It never lengthens a wait.
#
# Direction is deliberate. Symmetric jitter (the usual +/- form) can exceed
# RECONNECT_MAX_DELAY, which turns a "maximum" into an average and breaks the one
# property anything downstream can rely on. Measured over 20,000 simulated bounces,
# worst-case time for the LAST of 9 listeners to return, from server-ready:
#     cap 10, no jitter        p50  4.6s   p95  9.4s   max 10.0s
#     cap 10, jitter DOWN      p50  7.4s   p95  9.3s   max 10.0s   <- cap still holds
#     cap 10, jitter SYMMETRIC p50 10.7s   p95 13.8s   max 15.0s   <- cap exceeded by 50%
RECONNECT_JITTER_FRACTION = 0.5

# ── Why 10, not 30 (Rick's ruling, 2026-08-02) ──────────────────────────────
# These constants are read by two very different consumers and the second one is
# easy to forget:
#   1. the listener, deciding how long to sleep before retrying;
#   2. the managed-bounce all-clear settle gate on the SERVER, which holds its
#      announcement until every rostered session is back — so it waits out
#      whatever this cap allows.
# The gate fires on COVERAGE (everyone back), which means it waits for the SLOWEST
# session, which means the worst case it must sit through is exactly this cap. At
# 30 that made 30 the floor under any safe deadline; the shipped 30s deadline sat
# exactly ON that bound. Dropping the cap to 10 is what let the deadline come back
# DOWN to 15 with real margin instead of being raised to 40.
#
# ⚠️ THE DEADLINE IS DERIVED FROM THIS VALUE, NOT CHOSEN BESIDE IT. If you change
# this cap, `managed bounce all-clear settle deadline seconds` must change with it —
# `SettleDeadlinePinTests` computes the required deadline from these constants and
# goes RED if the two drift apart. Picking them independently is the defect that
# produced the 15-then-30 churn in the first place.
#
# Full derivation, the two live samples it explains, and why jitter is aimed at the
# herd rather than at this gate:
#   src/rnd/v0.1.9/2026.08.02-settle-deadline-arithmetic-30-vs-40.md


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
