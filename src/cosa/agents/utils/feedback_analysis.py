#!/usr/bin/env python3
"""
Shared Feedback Analysis Utilities for COSA Agents.

Provides signal-based analysis of user voice/text feedback to determine
approval, rejection, or additional context intent. Used by agent
notification profiles that need to interpret human feedback.
"""


# =============================================================================
# Signal Lists
# =============================================================================

APPROVAL_SIGNALS = [
    "yes", "proceed", "go ahead", "sounds good", "perfect",
    "do it", "approved", "looks good", "that works", "okay",
    "ok", "sure", "fine", "great", "excellent", "continue",
    "start", "begin", "let's go", "go for it"
]

APPROVAL_EXACT_MATCHES = [ "y", "yep", "yup", "uh huh", "mm hmm" ]

REJECTION_SIGNALS = [
    "no", "change", "adjust", "modify", "different",
    "instead", "rather", "stop", "wait", "hold on",
    "not quite", "actually", "but", "however"
]


# =============================================================================
# Analysis Functions
# =============================================================================

def is_approval( feedback: str ) -> bool:
    """
    Determine if user feedback indicates approval.

    Requires:
        - feedback is a string (or None/falsy for early return)

    Ensures:
        - Returns True if feedback contains any approval signal
        - Returns True if feedback exactly matches a short approval word
        - Returns False for empty/None input

    Args:
        feedback: User's voice response text

    Returns:
        bool: True if approval detected
    """
    if not feedback:
        return False

    feedback_lower = feedback.lower().strip()

    for signal in APPROVAL_SIGNALS:
        if signal in feedback_lower:
            return True

    if feedback_lower in APPROVAL_EXACT_MATCHES:
        return True

    return False


def is_rejection( feedback: str ) -> bool:
    """
    Determine if user feedback indicates rejection/change request.

    Requires:
        - feedback is a string (or None/falsy for early return)

    Ensures:
        - Returns True if feedback contains any rejection signal
        - Returns False for empty/None input

    Args:
        feedback: User's voice response text

    Returns:
        bool: True if rejection/change request detected
    """
    if not feedback:
        return False

    feedback_lower = feedback.lower().strip()

    for signal in REJECTION_SIGNALS:
        if signal in feedback_lower:
            return True

    return False


def extract_feedback_intent( feedback: str ) -> dict:
    """
    Extract structured intent from user feedback.

    Requires:
        - feedback is a string

    Ensures:
        - Returns dict with is_approval, is_rejection, raw_feedback, feedback_type
        - feedback_type is "approval", "change_request", or "additional_context"

    Args:
        feedback: User's voice response text

    Returns:
        dict: Structured intent analysis
    """
    return {
        "is_approval"  : is_approval( feedback ),
        "is_rejection" : is_rejection( feedback ),
        "raw_feedback" : feedback,
        "feedback_type" : (
            "approval" if is_approval( feedback )
            else "change_request" if is_rejection( feedback )
            else "additional_context"
        ),
    }


def quick_smoke_test():
    """Quick smoke test for feedback_analysis module."""
    import cosa.utils.util as cu

    cu.print_banner( "Feedback Analysis Utilities Smoke Test", prepend_nl=True )

    try:
        # Test 1: is_approval
        print( "Testing is_approval..." )
        assert is_approval( "yes" ) is True
        assert is_approval( "Yes, proceed" ) is True
        assert is_approval( "sounds good" ) is True
        assert is_approval( "yep" ) is True
        assert is_approval( "no" ) is False
        assert is_approval( "" ) is False
        assert is_approval( None ) is False  # type: ignore
        print( "  is_approval works correctly" )

        # Test 2: is_rejection
        print( "Testing is_rejection..." )
        assert is_rejection( "no" ) is True
        assert is_rejection( "wait, stop" ) is True
        assert is_rejection( "change it" ) is True
        assert is_rejection( "yes" ) is False
        assert is_rejection( "" ) is False
        assert is_rejection( None ) is False  # type: ignore
        print( "  is_rejection works correctly" )

        # Test 3: extract_feedback_intent
        print( "Testing extract_feedback_intent..." )
        intent = extract_feedback_intent( "yes, go ahead" )
        assert intent[ "is_approval" ] is True
        assert intent[ "is_rejection" ] is False
        assert intent[ "feedback_type" ] == "approval"

        intent = extract_feedback_intent( "no, change it" )
        assert intent[ "is_approval" ] is False
        assert intent[ "is_rejection" ] is True
        assert intent[ "feedback_type" ] == "change_request"

        intent = extract_feedback_intent( "focus on performance" )
        assert intent[ "is_approval" ] is False
        assert intent[ "is_rejection" ] is False
        assert intent[ "feedback_type" ] == "additional_context"
        print( "  extract_feedback_intent works correctly" )

        # Test 4: Signal lists are non-empty
        print( "Testing signal lists..." )
        assert len( APPROVAL_SIGNALS ) > 0
        assert len( APPROVAL_EXACT_MATCHES ) > 0
        assert len( REJECTION_SIGNALS ) > 0
        print( "  Signal lists are populated" )

        print( "\n  Feedback analysis utilities smoke test completed successfully" )

    except Exception as e:
        print( f"\n  Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
