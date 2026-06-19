#!/usr/bin/env python3
"""
WebSocket Listener for the Decision Proxy Agent.

Extends BaseWebSocketListener with decision-proxy-specific event
subscription and log prefix.

Dependency Rule:
    This module NEVER imports from notification_proxy or swe_team.
"""

from cosa.agents.utils.proxy_agents.base_listener import BaseWebSocketListener
from cosa.agents.decision_proxy.config import (
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
    DEFAULT_SESSION_ID,
    SUBSCRIBED_EVENTS,
)


class DecisionListener( BaseWebSocketListener ):
    """
    WebSocket listener for the Decision Proxy Agent.

    Connects to the Lupin WebSocket, subscribes to decision-relevant
    events, and dispatches them to the decision responder.

    Requires:
        - Same as BaseWebSocketListener

    Ensures:
        - Subscribes to decision proxy events
        - Uses "[DecisionListener]" log prefix
    """

    LOG_PREFIX = "[DecisionListener]"

    def __init__(
        self,
        email,
        password,
        session_id = DEFAULT_SESSION_ID,
        on_event   = None,
        host       = DEFAULT_SERVER_HOST,
        port       = DEFAULT_SERVER_PORT,
        debug      = False,
        verbose    = False
    ):
        """
        Initialize the decision listener.

        Args:
            email: User email for JWT authentication
            password: User password for JWT authentication
            session_id: WebSocket session identifier (default: "decision proxy")
            on_event: Async callback for received events
            host: Server hostname
            port: Server port
            debug: Enable debug output
            verbose: Enable verbose output
        """
        super().__init__(
            email             = email,
            password          = password,
            session_id        = session_id,
            on_event          = on_event,
            subscribed_events = SUBSCRIBED_EVENTS,
            host              = host,
            port              = port,
            debug             = debug,
            verbose           = verbose
        )
