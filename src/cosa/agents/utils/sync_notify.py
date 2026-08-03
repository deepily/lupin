#!/usr/bin/env python3
"""
Shared Synchronous REST Notification Helper for Proxy Agents.

Provides a fire-and-forget notify() function that sends status notifications
via the Lupin REST API. Used by proxy agents (decision_proxy, notification_proxy)
that run in synchronous contexts (no asyncio event loop).

This is intentionally simple — proxy agents only need fire-and-forget progress
notifications, not the full async notification dispatch pattern.
"""

import os
import requests

from cosa.agents.utils.proxy_agents.base_config import DEFAULT_SERVER_HOST, DEFAULT_SERVER_PORT
from cosa.utils.config_loader import get_api_config, load_api_key

# Transport budget for out-of-process HTTP calls to `:7999` (row 204911ca).
# ~30s = 1.60x the observed maximum reload window of 18.76s — a multiplier with
# explicit headroom, NOT a coverage guarantee. `:7999` runs `uvicorn --reload`
# and the reloader parent holds the listening socket across a restart, so the
# kernel ACCEPTS a request nothing is there to answer and the caller hangs
# instead of getting a fast ConnectionRefused. The prior 5s sat under the
# 18.76s observed max (measured n=143: min 6.59s, median 6.91s).
#
# 🔴 EXPOSED VIA CLI MODE. `peer.py:354` reaches this helper INSIDE `:7999`,
# where a reload tears the caller down too and a budget buys nothing. But
# `python -m cosa.agents.notification_proxy` and `python -m
# cosa.agents.decision_proxy` reach it in a SEPARATE OS process, and that mode
# is the documented, actually-exercised one. Exposure is a property of the
# INVOCATION, not of the call site — a per-site in/out classification cannot
# express that, and an earlier pass excluded this helper because of it.
#
# Full derivation: src/rnd/v0.1.9/2026.07.19-dev-server-reload-availability.md §9(a).
#
# 🔴 DRIFT CONTROL — TWO SEARCHES, AND IT TOOK BOTH.
# `grep -rn _SERVER_TRANSPORT_TIMEOUT_SECONDS` returns every DIRECT call site.
# It does NOT return members whose budget is carried in a Pydantic FIELD rather
# than passed at the call — `AsyncNotificationRequest( timeout=… )`, consumed at
# `notify_user_async.py:197-201` as a bare `requests.post( timeout=request.timeout )`.
# Two such members were missed on the first pass for exactly this reason.
# The second search is: `grep -rn "AsyncNotificationRequest(" -A14 | grep timeout`.
# Run BOTH, or the set you get back is the set the first grep can see.
#
# TRADE: a hung server now stalls a notify ~30s instead of ~5s.
# The failure path returns False behind a `debug`-gated print, so a dropped
# notification is SILENT by default — losing it is worse than waiting for it. Not free.
_SERVER_TRANSPORT_TIMEOUT_SECONDS = 30


def notify(
    message: str,
    sender_id: str,
    priority: str = "low",
    host: str = DEFAULT_SERVER_HOST,
    port: int = DEFAULT_SERVER_PORT,
    target_user: str = None,
    debug: bool = False
) -> bool:
    """
    Send a fire-and-forget notification about a proxy agent's status.

    Requires:
        - message is a non-empty string
        - sender_id is a valid sender_id string
        - Lupin server is running at host:port

    Ensures:
        - Sends POST to /api/notify with the given sender_id
        - Authenticates with X-API-Key header
        - Returns True on success, False on error
        - Never raises exceptions (fire-and-forget)

    Args:
        message: Status message to announce
        sender_id: The proxy agent's SENDER_ID
        priority: Notification priority level (low, medium, high, urgent)
        host: Server hostname
        port: Server port
        target_user: Target user email (defaults from env var)
        debug: Enable debug output

    Returns:
        bool: True if notification was sent successfully
    """
    if target_user is None:
        from lupin_cli.notifications.notification_models import resolve_target_user
        target_user = resolve_target_user(
            os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
        )

    url = f"http://{host}:{port}/api/notify"

    params = {
        "message"     : message,
        "type"        : "progress",
        "priority"    : priority,
        "target_user" : target_user,
        "sender_id"   : sender_id,
    }

    # Load API key for authentication
    headers = {}
    try:
        env     = os.getenv( "LUPIN_ENV", "local" )
        config  = get_api_config( env )
        api_key = load_api_key( config[ "api_key_file" ] )
        headers[ "X-API-Key" ] = api_key
    except Exception as e:
        if debug: print( f"[SyncNotify] Failed to load API key: {e}" )

    try:
        response = requests.post( url, params=params, headers=headers,
                                   timeout=_SERVER_TRANSPORT_TIMEOUT_SECONDS )
        if debug: print( f"[SyncNotify] Notification sent: {response.status_code}" )
        return response.status_code == 200
    except Exception as e:
        if debug: print( f"[SyncNotify] Notification failed: {e}" )
        return False


def quick_smoke_test():
    """Quick smoke test for sync_notify module."""
    import cosa.utils.util as cu

    cu.print_banner( "Sync Notify Helper Smoke Test", prepend_nl=True )

    try:
        # Test 1: Function exists and has correct signature
        print( "Testing function signature..." )
        import inspect
        sig = inspect.signature( notify )
        assert "message" in sig.parameters
        assert "sender_id" in sig.parameters
        assert "priority" in sig.parameters
        assert "host" in sig.parameters
        assert "port" in sig.parameters
        assert "target_user" in sig.parameters
        assert "debug" in sig.parameters
        print( "  Function signature correct" )

        # Test 2: Default values
        print( "Testing default values..." )
        params = sig.parameters
        assert params[ "priority" ].default == "low"
        assert params[ "debug" ].default is False
        print( "  Default values correct" )

        print( "\n  Sync notify helper smoke test completed successfully" )

    except Exception as e:
        print( f"\n  Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
