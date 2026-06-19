#!/usr/bin/env python3
"""
SWE Engineering Classifier — classifies questions into engineering categories.

Uses a two-pass approach:
    1. Sender ID prefix hint (swe.tester → testing, swe.coder → general)
    2. Keyword analysis against category keyword sets

Falls back to "general" if no category matches.

Dependency Rule:
    This module imports from decision_proxy (Layer 3) for the ABC.
    This module NEVER imports from notification_proxy.
"""

from cosa.agents.decision_proxy.category_classifier import CategoryClassifier
from cosa.agents.swe_team.proxy.engineering_categories import ENGINEERING_CATEGORIES


# Sender ID prefix → category hint mapping
SENDER_CATEGORY_HINTS = {
    "swe.tester"  : "testing",
    "swe.coder"   : None,       # Coders produce all categories
    "swe.lead"    : None,       # Leads produce all categories
}


class EngineeringClassifier( CategoryClassifier ):
    """
    Classifies SWE team decision questions into engineering categories.

    Uses sender ID prefix for initial hint, then keyword analysis for
    category determination. Higher keyword match counts yield higher confidence.

    Requires:
        - question is a non-empty string

    Ensures:
        - classify() returns ( category_name, confidence ) tuple
        - Falls back to "general" with low confidence if no match
        - Sender ID hints boost confidence for matching categories
    """

    def __init__( self, debug=False ):
        """
        Initialize the engineering classifier.

        Args:
            debug: Enable debug output
        """
        self.debug = debug

    def classify( self, question, sender_id="", context=None ):
        """
        Classify a decision question into an engineering category.

        Requires:
            - question is a non-empty string

        Ensures:
            - Returns ( category_name, confidence ) tuple
            - confidence is between 0.0 and 1.0
            - Falls back to ( "general", 0.3 ) if no match

        Args:
            question: Decision question text
            sender_id: Sender ID (e.g., "swe.tester@lupin.deepily.ai")
            context: Optional context dict

        Returns:
            Tuple of ( category_name, confidence )
        """
        question_lower = question.lower()

        # Pass 1: Check sender ID prefix for category hint
        sender_hint = self._get_sender_hint( sender_id )

        # Pass 2: Keyword analysis — score each category
        scores = {}
        for cat_name, cat_def in ENGINEERING_CATEGORIES.items():
            if cat_name == "general":
                continue  # General is the fallback, not scored

            keywords = cat_def[ "keywords" ]
            match_count = sum( 1 for kw in keywords if kw in question_lower )

            if match_count > 0:
                # Base confidence: proportional to keyword matches (capped)
                base_confidence = min( 0.5 + ( match_count * 0.1 ), 0.95 )

                # Sender hint boost
                if sender_hint and sender_hint == cat_name:
                    base_confidence = min( base_confidence + 0.15, 0.98 )

                scores[ cat_name ] = base_confidence

        if not scores:
            # No keyword match — use sender hint if available
            if sender_hint:
                if self.debug: print( f"[EngineeringClassifier] No keyword match, using sender hint: {sender_hint}" )
                return ( sender_hint, 0.45 )

            if self.debug: print( f"[EngineeringClassifier] No match → general" )
            return ( "general", 0.3 )

        # Return highest scoring category
        best_category = max( scores, key=scores.get )
        best_confidence = scores[ best_category ]

        if self.debug:
            print( f"[EngineeringClassifier] '{question[:50]}...' → {best_category} ({best_confidence:.2f})" )

        return ( best_category, best_confidence )

    def get_categories( self ):
        """
        Return all registered engineering categories with metadata.

        Ensures:
            - Returns dict matching ENGINEERING_CATEGORIES structure
            - Each category has keywords, cap_level, description

        Returns:
            Dict of category definitions
        """
        return ENGINEERING_CATEGORIES

    def _get_sender_hint( self, sender_id ):
        """
        Extract a category hint from sender ID prefix.

        Requires:
            - sender_id is a string

        Ensures:
            - Returns category name if sender prefix has a hint
            - Returns None if no hint available

        Args:
            sender_id: Full sender ID string

        Returns:
            Category name or None
        """
        if not sender_id:
            return None

        # Extract prefix before '@' (e.g., "swe.tester" from "swe.tester@lupin.deepily.ai")
        prefix = sender_id.split( "@" )[ 0 ] if "@" in sender_id else sender_id

        return SENDER_CATEGORY_HINTS.get( prefix )
