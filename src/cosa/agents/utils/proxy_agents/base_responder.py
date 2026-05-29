#!/usr/bin/env python3
"""
Base Responder for proxy agents.

Provides the strategy chain iteration pattern and response submission
shared by all proxy agents. Subclasses implement handle_event() with
domain-specific routing logic.

Dependency Rule:
    This module NEVER imports from notification_proxy, decision_proxy, or swe_team.

References:
    - src/cosa/rest/routers/notifications.py (POST /api/notify/response)
"""

import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from cosa.agents.utils.proxy_agents.base_config import (
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
)
from cosa.agents.utils.proxy_agents.rest_submitter import submit_notification_response


class BaseResponder( ABC ):
    """
    Abstract base for proxy agent responders.

    Provides shared infrastructure: strategy chain execution, REST response
    submission, statistics tracking, and dry-run gating. Subclasses implement
    handle_event() and initialize their own strategy chains.

    Requires:
        - Subclass implements handle_event()
        - At least one strategy is loaded

    Ensures:
        - Strategy chain executes in order until first non-None answer
        - Responses are submitted via REST API
        - Statistics are tracked for all operations
    """

    # Subclass override point: log prefix for all messages
    LOG_PREFIX = "[Responder]"

    def __init__(
        self,
        host    = DEFAULT_SERVER_HOST,
        port    = DEFAULT_SERVER_PORT,
        dry_run = False,
        debug   = False,
        verbose = False
    ):
        """
        Initialize the base responder.

        Requires:
            - host is a valid hostname string
            - port is a valid port number

        Ensures:
            - Stores connection parameters
            - Initializes empty stats dict
            - Subclass must add strategies after calling super().__init__()

        Args:
            host: Server hostname for REST API
            port: Server port for REST API
            dry_run: Display notifications without computing answers
            debug: Enable debug output
            verbose: Enable verbose output
        """
        self.host    = host
        self.port    = port
        self.dry_run = dry_run
        self.debug   = debug
        self.verbose = verbose

        # Base stats — subclasses may extend
        self.stats = {
            "events_received" : 0,
            "responses_sent"  : 0,
            "skipped"         : 0,
            "errors"          : 0,
        }

    @abstractmethod
    async def handle_event( self, event_type, event_data ):
        """
        Handle a WebSocket event — the main callback for the listener.

        Requires:
            - event_type is a string
            - event_data is a dict

        Ensures:
            - Routes event to appropriate handler
            - Subclass implements domain-specific routing

        Args:
            event_type: WebSocket event type string
            event_data: Event payload dict
        """
        ...

    def route_to_strategies( self, item, strategies ):
        """
        Execute strategy chain synchronously until first non-None answer.

        Requires:
            - item is a dict with event/notification data
            - strategies is a list of objects with can_handle() and respond() methods

        Ensures:
            - Returns ( answer, strategy_name ) on success
            - Returns ( None, None ) if no strategy produced an answer
            - Strategies are tried in order

        Args:
            item: Event payload dict
            strategies: Ordered list of strategy objects

        Returns:
            Tuple of ( answer, strategy_name ) or ( None, None )
        """
        for strategy in strategies:
            if not strategy.available:
                continue
            if strategy.can_handle( item ):
                answer = strategy.respond( item )
                if answer is not None:
                    return answer, strategy.name
        return None, None

    async def route_to_strategies_async( self, item, strategies ):
        """
        Execute strategy chain with async-capable strategies.

        Same as route_to_strategies but awaits respond() for strategies
        that return coroutines.

        Requires:
            - item is a dict with event/notification data
            - strategies is a list of strategy objects

        Ensures:
            - Returns ( answer, strategy_name ) on success
            - Returns ( None, None ) if no strategy produced an answer
            - Handles both sync and async respond() methods

        Args:
            item: Event payload dict
            strategies: Ordered list of strategy objects

        Returns:
            Tuple of ( answer, strategy_name ) or ( None, None )
        """
        import asyncio

        for strategy in strategies:
            if not strategy.available:
                continue
            if strategy.can_handle( item ):
                result = strategy.respond( item )
                # Support both sync and async respond()
                if asyncio.iscoroutine( result ):
                    answer = await result
                else:
                    answer = result
                if answer is not None:
                    return answer, strategy.name
        return None, None

    def submit_response( self, notification_id, response_value ):
        """
        Submit a response via the REST API.

        Requires:
            - notification_id is a valid UUID string
            - response_value is a string or dict

        Ensures:
            - Delegates to submit_notification_response()
            - Returns True on success, False on error

        Args:
            notification_id: UUID of the notification
            response_value: The answer to submit

        Returns:
            bool: True if response submitted successfully
        """
        return submit_notification_response(
            notification_id = notification_id,
            response_value  = response_value,
            host            = self.host,
            port            = self.port,
            debug           = self.debug,
            verbose         = self.verbose
        )

    def print_stats( self ):
        """Print summary statistics."""
        print( f"\n{'=' * 50}" )
        print( f"Proxy Agent Statistics" )
        print( f"{'=' * 50}" )
        for key, value in self.stats.items():
            label = key.replace( "_", " " ).title()
            print( f"  {label:30s} : {value}" )
        print( f"{'=' * 50}" )
