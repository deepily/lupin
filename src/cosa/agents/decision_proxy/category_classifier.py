#!/usr/bin/env python3
"""
Abstract category classifier interface for the Decision Proxy.

Concrete implementations live in domain layers (e.g., swe_team/proxy/
engineering_classifier.py). This module defines the abstract interface
that all classifiers must implement.

Dependency Rule:
    This module NEVER imports from notification_proxy or swe_team.
"""

from abc import ABC, abstractmethod
from typing import Tuple


class CategoryClassifier( ABC ):
    """
    Abstract interface for classifying decisions into categories.

    Domain-specific subclasses implement the classification logic
    using sender ID patterns, keyword analysis, and/or LLM inference.

    Requires:
        - Subclass implements classify() and get_categories()

    Ensures:
        - classify() returns ( category_name, confidence ) tuple
        - get_categories() returns dict of all registered categories
    """

    @abstractmethod
    def classify( self, question, sender_id="", context=None ):
        """
        Classify a decision question into a category.

        Requires:
            - question is a non-empty string
            - sender_id is a string (may be empty)

        Ensures:
            - Returns ( category_name, confidence ) tuple
            - category_name is a string from the domain's category set
            - confidence is a float between 0.0 and 1.0
            - Returns ( "general", low_confidence ) if no category matches

        Args:
            question: The decision question text
            sender_id: Sender ID of the requesting agent
            context: Optional additional context dict

        Returns:
            Tuple of ( category_name, confidence )
        """
        ...

    @abstractmethod
    def get_categories( self ):
        """
        Return all registered categories with their metadata.

        Ensures:
            - Returns dict mapping category_name → category_metadata
            - Each category has at least: keywords, cap_level, description

        Returns:
            Dict of category definitions
        """
        ...
