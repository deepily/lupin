"""
NotificationCategoryClassifier — keyword-based classifier for notification messages.

Implements the CategoryClassifier ABC with 6 fixed categories + uncategorized catch-all.
Designed for classifying cosa-voice MCP notification messages into prediction-relevant
categories for the Universal Prediction Engine.

Categories:
    - Permission:    "proceed", "continue", "should i", "allow", "go ahead"
    - Confirmation:  "confirm", "correct", "right", "sure", "delete", "overwrite"
    - Approach:      "which approach", "option", "alternative", "strategy", "how should"
    - Input:         "what", "name", "value", "path", "describe", "provide", "specify"
    - Workflow:      "commit", "push", "merge", "deploy", "test", "run", "install"
    - Meta:          "session", "plan", "todo", "history", "documentation", "priority"
    - Uncategorized: catch-all (no keywords matched)
"""

from typing import Tuple, Dict, Optional

from cosa.agents.decision_proxy.category_classifier import CategoryClassifier


# Category definitions with keywords and metadata
NOTIFICATION_CATEGORIES = {
    "permission" : {
        "keywords"    : [ "proceed", "continue", "should i", "allow", "go ahead", "may i", "can i", "shall i", "is it ok", "permission" ],
        "description" : "Requests for permission to take an action",
    },
    "confirmation" : {
        "keywords"    : [ "confirm", "correct", "right", "sure", "delete", "overwrite", "remove", "destroy", "are you sure", "verify" ],
        "description" : "Confirmation of a proposed action or statement",
    },
    "approach" : {
        "keywords"    : [ "which approach", "option", "alternative", "strategy", "how should", "which method", "which way", "what approach", "choose between" ],
        "description" : "Selection between multiple approaches or strategies",
    },
    "input" : {
        "keywords"    : [ "what", "name", "value", "path", "describe", "provide", "specify", "enter", "type", "input" ],
        "description" : "Request for user-provided input or data",
    },
    "workflow" : {
        "keywords"    : [ "commit", "push", "merge", "deploy", "test", "run", "install", "build", "release", "branch" ],
        "description" : "Git/CI/CD workflow operations",
    },
    "meta" : {
        "keywords"    : [ "session", "plan", "todo", "history", "documentation", "priority", "schedule", "timeline", "review" ],
        "description" : "Meta-level project management and documentation",
    },
}

DEFAULT_CATEGORY = "uncategorized"


class NotificationCategoryClassifier( CategoryClassifier ):
    """
    Keyword-based classifier for notification messages.

    Implements CategoryClassifier ABC with two-pass keyword analysis:
    1. Exact phrase matching (multi-word keywords)
    2. Single-word keyword matching

    Requires:
        - NOTIFICATION_CATEGORIES dict is populated with keyword lists

    Ensures:
        - classify() returns (category, confidence) where confidence is 0.0-1.0
        - Falls back to ("uncategorized", 0.0) when no keywords match
        - Confidence scales with match count: 0.5 + (match_count * 0.1), capped at 0.95
    """

    def __init__( self, debug=False ):
        """
        Initialize the notification category classifier.

        Requires:
            - No preconditions

        Ensures:
            - Classifier is ready to classify messages
            - Category definitions loaded from module-level constant
        """
        self.debug      = debug
        self.categories = NOTIFICATION_CATEGORIES

    def classify( self, question: str, sender_id: str = "", context: Optional[dict] = None ) -> Tuple[str, float]:
        """
        Classify a notification message into one of the predefined categories.

        Requires:
            - question is a non-empty string

        Ensures:
            - Returns (category_name, confidence) tuple
            - confidence is between 0.0 and 0.95
            - Falls back to ("uncategorized", 0.0) if no match

        Raises:
            - None (graceful degradation on empty input)
        """
        if not question or not question.strip():
            return ( DEFAULT_CATEGORY, 0.0 )

        question_lower = question.lower().strip()

        best_category   = DEFAULT_CATEGORY
        best_match_count = 0

        for category, definition in self.categories.items():
            keywords    = definition[ "keywords" ]
            match_count = 0

            for keyword in keywords:
                if keyword in question_lower:
                    match_count += 1

            if match_count > best_match_count:
                best_match_count = match_count
                best_category    = category

        if best_match_count == 0:
            return ( DEFAULT_CATEGORY, 0.0 )

        # Confidence: 0.5 base + 0.1 per keyword match, capped at 0.95
        confidence = min( 0.5 + ( best_match_count * 0.1 ), 0.95 )

        if self.debug: print( f"[NotificationClassifier] '{question[:50]}...' → {best_category} (confidence={confidence:.2f}, matches={best_match_count})" )

        return ( best_category, confidence )

    def get_categories( self ) -> Dict[str, dict]:
        """
        Return the full category definitions dictionary.

        Requires:
            - No preconditions

        Ensures:
            - Returns dict of category name → definition
            - Each definition has 'keywords' and 'description' keys
        """
        return self.categories


def quick_smoke_test():
    """Quick smoke test for NotificationCategoryClassifier."""
    import cosa.utils.util as cu

    cu.print_banner( "NotificationCategoryClassifier Smoke Test", prepend_nl=True )

    try:
        classifier = NotificationCategoryClassifier( debug=True )

        # Test cases: (message, expected_category)
        test_cases = [
            ( "Should I proceed with the refactor?",                "permission" ),
            ( "Are you sure you want to delete this file?",         "confirmation" ),
            ( "Which approach should we use for caching?",          "approach" ),
            ( "What name should the new module have?",              "input" ),
            ( "Should I commit and push these changes?",            "workflow" ),
            ( "Do you want to update the session plan?",            "meta" ),
            ( "The sky is blue today.",                              "uncategorized" ),
        ]

        passed = 0
        for message, expected in test_cases:
            category, confidence = classifier.classify( message )
            status = "✓" if category == expected else "✗"
            if category == expected:
                passed += 1
            print( f"  {status} '{message[:50]}...' → {category} (expected: {expected}, conf: {confidence:.2f})" )

        print( f"\n✓ {passed}/{len( test_cases )} classification tests passed" )

        # Test get_categories
        cats = classifier.get_categories()
        assert len( cats ) == 6, f"Expected 6 categories, got {len( cats )}"
        print( f"✓ get_categories() returns {len( cats )} categories" )

        # Test empty input
        cat, conf = classifier.classify( "" )
        assert cat == "uncategorized" and conf == 0.0
        print( "✓ Empty input returns uncategorized with 0.0 confidence" )

        print( "\n✓ All NotificationCategoryClassifier smoke tests passed!" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        cu.print_stack_trace( e, caller="notification_category_classifier.quick_smoke_test()" )


if __name__ == "__main__":
    quick_smoke_test()
