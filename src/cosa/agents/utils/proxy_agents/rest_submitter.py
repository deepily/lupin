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
            timeout = 10
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
