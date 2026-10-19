"""
COSA Voice Interface Integration Layer for Bug Fix Expediter.

Provides async wrappers for the cosa-voice notification tools,
bridging the async orchestrator with the blocking notification API.

Uses AgentNotificationDispatcher for shared async dispatch logic.
Module-level SENDER_ID and SESSION_NAME remain mutable for runtime
configuration by job.py callers.
"""

import logging
from typing import Optional

from lupin_cli.notifications.notification_models import (
    NotificationRequest,
    AsyncNotificationRequest,
    NotificationResponse,
    AsyncNotificationResponse,
    NotificationType,
    NotificationPriority,
    ResponseType
)
from cosa.utils.notification_utils import format_questions_for_tts, convert_questions_for_api

from cosa.agents.utils.sender_id import build_sender_id
from cosa.agents.utils.feedback_analysis import (
    is_approval, is_rejection, extract_feedback_intent,
    APPROVAL_SIGNALS, REJECTION_SIGNALS
)
from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher, make_interface_functions

logger = logging.getLogger( __name__ )


# =============================================================================
# Sender Identity Configuration
# =============================================================================

AGENT_TYPE = "bug.fix.expediter"

_dispatcher = AgentNotificationDispatcher( agent_type=AGENT_TYPE, default_priority="high" )


def _get_sender_id( suffix: str = None ) -> str:
    """
    Get sender_id for Bug Fix Expediter notifications.

    Args:
        suffix: Optional override for the default suffix (e.g., job id_hash).

    Ensures:
        - Returns sender_id in format: bug.fix.expediter@{project}.deepily.ai#{suffix}

    Returns:
        str: Sender ID for notification identity
    """
    if suffix is not None:
        return _dispatcher.build_sender_id( suffix=suffix )
    return _dispatcher.build_sender_id()


SENDER_ID: str                = _get_sender_id()
SESSION_NAME: Optional[ str ] = None
TARGET_USER: Optional[ str ]  = None


# =============================================================================
# Primary Interface Functions
# =============================================================================

notify_progress, ask_confirmation, get_feedback, present_choices = make_interface_functions( globals(), notify_extras=( "progress_group_id", ), ask_extras=( "priority", ), feedback_extras=( "priority", "response_default" ), choices_extras=( "priority", "response_default" ) )


# =============================================================================
# Feedback Analysis Utilities
# =============================================================================
# is_approval(), is_rejection(), and extract_feedback_intent() are imported
# from cosa.agents.utils.feedback_analysis (see imports above).
# They remain available at module level for convenience.


def quick_smoke_test():
    """Quick smoke test for BFE cosa_interface module."""
    import cosa.utils.util as cu
    import inspect

    cu.print_banner( "BFE COSA Interface Smoke Test", prepend_nl=True )

    try:
        # 1: Imports valid
        assert NotificationRequest is not None
        assert NotificationType is not None
        print( "✓ Imports valid" )

        # 2: is_approval / is_rejection
        assert is_approval( "yes" ) is True
        assert is_approval( "no" ) is False
        assert is_rejection( "no" ) is True
        assert is_rejection( "yes" ) is False
        print( "✓ Feedback analysis works" )

        # 3: extract_feedback_intent
        intent = extract_feedback_intent( "yes, go ahead" )
        assert intent[ "is_approval" ] is True
        print( "✓ extract_feedback_intent works" )

        # 4: Async function signatures
        assert inspect.iscoroutinefunction( notify_progress )
        assert inspect.iscoroutinefunction( ask_confirmation )
        assert inspect.iscoroutinefunction( get_feedback )
        assert inspect.iscoroutinefunction( present_choices )
        print( "✓ Async functions have correct signatures" )

        # 5: Dispatcher agent_type
        assert _dispatcher.agent_type == "bug.fix.expediter"
        assert "bug.fix.expediter@" in _dispatcher.sender_id
        print( f"✓ Dispatcher sender_id: {_dispatcher.sender_id}" )

        print( "\n✓ BFE COSA Interface smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
