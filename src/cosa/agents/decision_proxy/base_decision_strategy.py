#!/usr/bin/env python3
"""
Abstract base for domain-specific decision strategies.

Defines the three-phase decision pipeline: classify → gate → decide.
Concrete implementations live in domain layers (e.g., swe_team/proxy/
engineering_strategy.py).

Dependency Rule:
    This module NEVER imports from notification_proxy or swe_team.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple


class DecisionResult:
    """
    Result of a decision strategy evaluation.

    Attributes:
        action: What the proxy should do ("shadow", "suggest", "act", "defer")
        value: The actual decision value (if action is "act" or "suggest")
        category: Category name from classification
        confidence: Classification confidence (0.0 - 1.0)
        trust_level: Current trust level for this category
        reason: Human-readable explanation of why this action was chosen
    """

    def __init__(
        self,
        action,
        value      = None,
        category   = "unknown",
        confidence = 0.0,
        trust_level = 1,
        reason     = ""
    ):
        self.action      = action
        self.value       = value
        self.category    = category
        self.confidence  = confidence
        self.trust_level = trust_level
        self.reason      = reason

    def __repr__( self ):
        return (
            f"DecisionResult(action={self.action!r}, category={self.category!r}, "
            f"trust_level={self.trust_level}, confidence={self.confidence:.2f})"
        )


class BaseDecisionStrategy( ABC ):
    """
    Abstract base for domain-specific decision strategies.

    Implements the three-phase pipeline: classify → gate → decide.
    Subclasses provide domain-specific classification and decision logic.

    Requires:
        - Subclass implements classify(), gate(), and decide()
        - Trust tracker and decision store are provided at construction

    Ensures:
        - evaluate() runs the full pipeline and returns DecisionResult
        - gate() enforces trust level caps and circuit breaker state
        - decide() produces the actual decision value
    """

    @property
    @abstractmethod
    def name( self ) -> str:
        """Strategy identifier for logging and stats."""
        ...

    @property
    def available( self ) -> bool:
        """Whether this strategy is ready to handle decisions."""
        return True

    def can_handle( self, item ):
        """
        Determine if this strategy can handle the given decision item.

        Requires:
            - item is a dict with notification/decision data

        Ensures:
            - Returns True if this domain strategy applies
            - Returns False otherwise

        Args:
            item: Event payload dict

        Returns:
            bool
        """
        return True

    @abstractmethod
    def classify( self, question, sender_id="", context=None ):
        """
        Classify the decision question into a domain category.

        Requires:
            - question is a non-empty string

        Ensures:
            - Returns ( category, confidence ) tuple

        Args:
            question: Decision question text
            sender_id: Requesting agent's sender ID
            context: Optional context dict

        Returns:
            Tuple of ( category_name, confidence )
        """
        ...

    @abstractmethod
    def gate( self, category, trust_level, confidence ):
        """
        Determine if the decision should be acted on at the current trust level.

        Requires:
            - category is a valid category name
            - trust_level is 1-5
            - confidence is 0.0-1.0

        Ensures:
            - Returns action string: "shadow", "suggest", "act", or "defer"
            - Respects category-specific caps
            - Returns "defer" if circuit breaker is tripped

        Args:
            category: Decision category name
            trust_level: Current trust level for this category
            confidence: Classification confidence

        Returns:
            Action string
        """
        ...

    @abstractmethod
    def decide( self, question, category, context=None ):
        """
        Produce the actual decision value.

        Requires:
            - question is a non-empty string
            - category is a valid category name

        Ensures:
            - Returns the decision value (str, dict, etc.)
            - Returns None if no decision can be made

        Args:
            question: Decision question text
            category: Classified category
            context: Optional context dict

        Returns:
            Decision value or None
        """
        ...

    def evaluate( self, question, sender_id="", context=None ):
        """
        Run the full classify → gate → decide pipeline.

        Requires:
            - question is a non-empty string

        Ensures:
            - Returns DecisionResult with action, value, and metadata
            - If gate returns "shadow" or "defer", value is None

        Args:
            question: Decision question text
            sender_id: Requesting agent's sender ID
            context: Optional context dict

        Returns:
            DecisionResult
        """
        category, confidence = self.classify( question, sender_id, context )

        # Default trust level 1 — overridden when trust tracker is wired in
        trust_level = 1

        action = self.gate( category, trust_level, confidence )

        value = None
        if action in ( "act", "suggest" ):
            value = self.decide( question, category, context )

        return DecisionResult(
            action      = action,
            value       = value,
            category    = category,
            confidence  = confidence,
            trust_level = trust_level,
            reason      = f"Category '{category}' at L{trust_level} → {action}"
        )
