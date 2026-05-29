#!/usr/bin/env python3
"""
Strategy Protocol for proxy response strategies.

Defines the interface that all proxy response strategies must implement.
Used by both the notification proxy (expediter rules, LLM fallback) and
the decision proxy (trust-based gating, engineering classifier).

Dependency Rule:
    This module NEVER imports from notification_proxy, decision_proxy, or swe_team.
"""

from typing import Any, Optional, Protocol, runtime_checkable


@runtime_checkable
class BaseStrategy( Protocol ):
    """
    Protocol for proxy response strategies.

    All strategies in the proxy agent framework implement this interface.
    Strategies are arranged in a chain — the responder iterates through
    strategies until one produces a non-None answer.

    Requires:
        - Implementing classes define all four members

    Ensures:
        - available property indicates whether strategy can be used
        - can_handle() determines if strategy applies to a given item
        - respond() produces an answer or None
        - name property identifies the strategy for logging/stats
    """

    @property
    def name( self ) -> str:
        """
        Strategy identifier for logging and statistics.

        Ensures:
            - Returns a short, human-readable string (e.g., "rules", "llm_script")
        """
        ...

    @property
    def available( self ) -> bool:
        """
        Whether this strategy is ready to handle items.

        Ensures:
            - Returns True if required resources are loaded and services online
            - Returns False if strategy cannot produce answers
        """
        ...

    def can_handle( self, item: dict ) -> bool:
        """
        Determine if this strategy can handle the given item.

        Requires:
            - item is a dict with event/notification data

        Ensures:
            - Returns True if strategy applies to this item
            - Returns False if item should fall through to next strategy

        Args:
            item: Event payload dict (notification, decision, etc.)

        Returns:
            bool: True if strategy can respond to this item
        """
        ...

    def respond( self, item: dict ) -> Optional[Any]:
        """
        Produce a response for the given item.

        Requires:
            - can_handle( item ) returned True

        Ensures:
            - Returns a response value (str, dict, etc.) on success
            - Returns None if no answer could be determined
            - May be sync or async depending on strategy implementation

        Args:
            item: Event payload dict

        Returns:
            Response value or None
        """
        ...
