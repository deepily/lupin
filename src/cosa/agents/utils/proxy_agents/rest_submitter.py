#!/usr/bin/env python3
"""
REST response submission for proxy agents.

Standalone function for POSTing responses to the Lupin notification API.
Shared by notification proxy, decision proxy, and any future proxy agents.

Dependency Rule:
    This module NEVER imports from notification_proxy, decision_proxy, or swe_team.

References:
    - src/cosa/rest/routers/notifications.py (POST /api/notify/response)
"""

import requests
from typing import Any

from cosa.agents.utils.proxy_agents.base_config import (
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
)

# Transport budget for out-of-process HTTP calls to `:7999` (row 204911ca).
# ~30s = 1.60x the observed maximum reload window of 18.76s — a multiplier with
# explicit headroom, NOT a coverage guarantee. `:7999` runs `uvicorn --reload`
# and the reloader parent holds the listening socket across a restart, so the
# kernel ACCEPTS a request nothing is there to answer and the caller hangs
# instead of getting a fast ConnectionRefused. The prior 10s sat under the
# 18.76s observed max (measured n=143: min 6.59s, median 6.91s).
#
# 🔴 SHARED LAYER, BOTH PROXIES. This module sits under `notification_proxy`
# AND `decision_proxy`, so it rides both `python -m` entry points into a
# separate OS process. It was invisible to a per-package grep precisely
# because it lives in `utils/` rather than in either package: entry-point
# enumeration finds the packages, but only the transitive walk from them
# finds the shared libraries underneath.
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
# TRADE: a hung server now stalls a response submit ~30s instead of ~10s. Not free.
_SERVER_TRANSPORT_TIMEOUT_SECONDS = 30


def submit_notification_response(
    notification_id,
    response_value,
    host     = DEFAULT_SERVER_HOST,
    port     = DEFAULT_SERVER_PORT,
    endpoint = "/api/notify/response",
    debug    = False,
    verbose  = False
):
    """
    Submit a response to the Lupin notification API.

    Requires:
        - notification_id is a valid UUID string
        - response_value is a string or dict
        - Server is running at host:port

    Ensures:
        - POSTs to the specified endpoint
        - Returns True on success (HTTP 200)
        - Returns False on any error
        - Never raises exceptions

    Args:
        notification_id: UUID of the notification to respond to
        response_value: The answer to submit (str or dict)
        host: Server hostname
        port: Server port
        endpoint: REST endpoint path (default: /api/notify/response)
        debug: Enable debug output
        verbose: Enable verbose output

    Returns:
        bool: True if response was submitted successfully
    """
    url = f"http://{host}:{port}{endpoint}"

    payload = {
        "notification_id" : notification_id,
        "response_value"  : response_value
    }

    try:
        response = requests.post(
            url,
            json    = payload,
            headers = { "Content-Type": "application/json" },
            timeout = _SERVER_TRANSPORT_TIMEOUT_SECONDS
        )

        if response.status_code == 200:
            if verbose:
                data = response.json()
                print( f"[Submitter] API response: {data.get( 'status', '?' )} -- {data.get( 'message', '' )[ :80 ]}" )
            return True
        else:
            print( f"[Submitter] API error: HTTP {response.status_code} -- {response.text[ :200 ]}" )
            return False

    except requests.ConnectionError:
        print( f"[Submitter] API connection error: server not reachable at {url}" )
        return False
    except requests.Timeout:
        print( "[Submitter] API timeout submitting response" )
        return False
    except Exception as e:
        print( f"[Submitter] API error: {e}" )
        return False
