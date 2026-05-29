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
from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher

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

async def notify_progress(
    message: str,
    priority: str = "medium",
    abstract: Optional[ str ] = None,
    session_name: Optional[ str ] = None,
    job_id: Optional[ str ] = None,
    queue_name: Optional[ str ] = None,
    progress_group_id: Optional[ str ] = None
) -> None:
    """
    Send fire-and-forget progress notification.

    Args:
        message: Progress message to announce
        priority: "low", "medium", "high", or "urgent"
        abstract: Optional supplementary context (markdown, URLs, details)
        session_name: Optional human-readable session name for UI display
        job_id: Optional agentic job ID for routing to job cards
        queue_name: Optional queue where job is running
        progress_group_id: Optional progress group ID for in-place DOM updates
    """
    _dispatcher.sender_id    = SENDER_ID
    _dispatcher.session_name = SESSION_NAME
    _dispatcher.target_user  = TARGET_USER
    await _dispatcher.notify_progress(
        message, priority=priority, abstract=abstract,
        session_name=session_name, job_id=job_id,
        queue_name=queue_name, progress_group_id=progress_group_id
    )


async def ask_confirmation(
    question: str,
    default: str = "no",
    timeout: int = 60,
    abstract: Optional[ str ] = None,
    job_id: Optional[ str ] = None,
    priority: str = None
) -> bool:
    """
    Ask a yes/no question and return boolean result.

    Args:
        question: The yes/no question to ask
        default: Default answer if timeout ("yes" or "no")
        timeout: Seconds to wait for response
        abstract: Optional supplementary context
        job_id: Optional job ID for routing to job card
        priority: "low"/"medium"/"high"/"urgent" (default: dispatcher default, which is "high" for SWE)

    Returns:
        bool: True if user said yes, False otherwise
    """
    _dispatcher.sender_id   = SENDER_ID
    _dispatcher.target_user = TARGET_USER
    return await _dispatcher.ask_confirmation(
        question, default=default, timeout=timeout, abstract=abstract, job_id=job_id, priority=priority
    )


async def get_feedback(
    prompt: str,
    timeout: int = 300,
    job_id: Optional[ str ] = None,
    priority: str = None,
    response_default: Optional[ str ] = None
) -> Optional[ str ]:
    """
    Get open-ended feedback from user via voice.

    Args:
        prompt: Text to speak to the user
        timeout: Maximum seconds to wait for response
        job_id: Optional job ID for routing to job card
        priority: "low"/"medium"/"high"/"urgent" (default: dispatcher default, "high" for SWE)
        response_default: Optional default returned when user is offline (else 503).

    Returns:
        str or None: User's transcribed voice response
    """
    _dispatcher.sender_id   = SENDER_ID
    _dispatcher.target_user = TARGET_USER
    return await _dispatcher.get_feedback(
        prompt, timeout=timeout, job_id=job_id, priority=priority,
        response_default=response_default,
    )


async def present_choices(
    questions: list,
    timeout: int = 120,
    title: Optional[ str ] = None,
    abstract: Optional[ str ] = None,
    job_id: Optional[ str ] = None,
    priority: str = None,
    response_default: Optional[ str ] = None
) -> dict:
    """
    Present multiple-choice questions and get user's selection.

    Args:
        questions: List of question objects with options
        timeout: Seconds to wait for response
        title: Optional title for the notification
        abstract: Optional supplementary context
        job_id: Optional job ID for routing to job card
        priority: "low"/"medium"/"high"/"urgent" (default: dispatcher default, "high" for SWE)
        response_default: Optional default (e.g. "{}") returned when user is offline;
                          otherwise /api/notify returns 503. Clean-stall path for
                          unattended runs — empty-answers normalization (Bug 7)
                          then raises VoiceGateTimeoutError for the caller.

    Returns:
        dict: {"answers": {...}} with selections keyed by header
    """
    _dispatcher.sender_id   = SENDER_ID
    _dispatcher.target_user = TARGET_USER
    return await _dispatcher.present_choices(
        questions, timeout=timeout, title=title, abstract=abstract, job_id=job_id,
        priority=priority, response_default=response_default,
    )


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
