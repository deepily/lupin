#!/usr/bin/env python3
"""
Voice notification wrapper for the Notification Proxy Agent.

Sends fire-and-forget status notifications about the proxy's own state:
connected, answering, disconnected, errors.

Delegates to the shared sync_notify helper.
"""

from cosa.agents.notification_proxy.cosa_interface import SENDER_ID
from cosa.agents.utils.sync_notify import notify as _sync_notify


def notify( message, priority="low", host=None, port=None, target_user=None, debug=False ):
    """
    Send a fire-and-forget notification about the proxy agent's status.

    Args:
        message: Status message to announce
        priority: Notification priority level
        host: Server hostname (default from config)
        port: Server port (default from config)
        target_user: Target user email (default from env var)
        debug: Enable debug output

    Returns:
        bool: True if notification was sent successfully
    """
    kwargs = {
        "message"   : message,
        "sender_id" : SENDER_ID,
        "priority"  : priority,
        "debug"     : debug,
    }
    if host is not None: kwargs[ "host" ] = host
    if port is not None: kwargs[ "port" ] = port
    if target_user is not None: kwargs[ "target_user" ] = target_user

    return _sync_notify( **kwargs )
