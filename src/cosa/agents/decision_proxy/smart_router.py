#!/usr/bin/env python3
"""
Smart Router for the Decision Proxy Agent.

Determines whether to route decisions to the user (via voice notification)
or handle them autonomously. Checks:
  1. Active hours schedule (is the user likely available?)
  2. WebSocket connectivity (is the user's client connected?)

Dependency Rule:
    This module NEVER imports from notification_proxy or swe_team.
"""

from datetime import datetime, time
from typing import Optional

from cosa.agents.decision_proxy.config import (
    DEFAULT_ACTIVE_HOURS_START,
    DEFAULT_ACTIVE_HOURS_END,
    DEFAULT_TIMEZONE,
)


class SmartRouter:
    """
    Routes decisions to user or proxy based on availability signals.

    Requires:
        - active_hours_start and active_hours_end are valid hour integers (0-23)
        - timezone is a valid IANA timezone string

    Ensures:
        - is_active_hours() returns True during configured active hours
        - should_defer_to_user() combines schedule + connectivity
    """

    def __init__(
        self,
        active_hours_start = DEFAULT_ACTIVE_HOURS_START,
        active_hours_end   = DEFAULT_ACTIVE_HOURS_END,
        timezone           = DEFAULT_TIMEZONE,
        debug              = False
    ):
        """
        Initialize the smart router.

        Args:
            active_hours_start: Hour (0-23) when active hours begin
            active_hours_end: Hour (0-23) when active hours end
            timezone: IANA timezone string (e.g., "America/Chicago")
            debug: Enable debug output
        """
        self.active_hours_start = active_hours_start
        self.active_hours_end   = active_hours_end
        self.timezone           = timezone
        self.debug              = debug

    def is_active_hours( self, now=None ):
        """
        Check if the current time is within configured active hours.

        Requires:
            - now is a datetime object or None (uses current time)

        Ensures:
            - Returns True if current hour is between start and end (inclusive)
            - Handles wrap-around (e.g., 22:00 to 06:00 for night shifts)

        Args:
            now: Optional datetime to check (defaults to current time in configured timezone)

        Returns:
            bool: True if within active hours
        """
        if now is None:
            try:
                from zoneinfo import ZoneInfo
                now = datetime.now( ZoneInfo( self.timezone ) )
            except ImportError:
                now = datetime.now()

        current_hour = now.hour

        if self.active_hours_start <= self.active_hours_end:
            # Normal range: e.g., 09:00 to 22:00
            return self.active_hours_start <= current_hour < self.active_hours_end
        else:
            # Wrap-around range: e.g., 22:00 to 06:00
            return current_hour >= self.active_hours_start or current_hour < self.active_hours_end

    def should_defer_to_user( self, now=None, user_connected=False ):
        """
        Determine if a decision should be deferred to the user.

        Requires:
            - now is a datetime or None
            - user_connected is a bool indicating WebSocket connectivity

        Ensures:
            - Returns True if user is available (active hours AND connected)
            - Returns False if user is unavailable (proxy should handle)

        Args:
            now: Optional datetime to check
            user_connected: Whether the user's WebSocket client is connected

        Returns:
            bool: True if decision should go to user
        """
        if not self.is_active_hours( now ):
            if self.debug: print( "[SmartRouter] Outside active hours — proxy handles" )
            return False

        if not user_connected:
            if self.debug: print( "[SmartRouter] User not connected — proxy handles" )
            return False

        if self.debug: print( "[SmartRouter] User available — defer to user" )
        return True
