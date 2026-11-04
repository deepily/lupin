#!/usr/bin/env python3
"""
Voice notification wrapper for the Decision Proxy Agent.

Sends fire-and-forget status notifications about the proxy's own state:
connected, deciding, shadowing, errors.

Delegates to the shared sync_notify helper.

Dependency Rule:
    This module never imports from notification_proxy or swe_team.
"""

from cosa.agents.decision_proxy.cosa_interface import SENDER_ID
from cosa.agents.utils.sync_notify import notify as _sync_notify, build_notify_kwargs


def notify( message, priority="low", host=None, port=None, target_user=None, debug=False ):
    """
    Send a fire-and-forget notification about the decision proxy's status.

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
    return _sync_notify( **build_notify_kwargs( message, SENDER_ID, priority, host, port, target_user, debug ) )
