#!/usr/bin/env python3
"""
COSA Voice Interface Integration Layer for Presentation Generator.

This module provides async wrappers for the cosa-voice notification tools,
bridging the async orchestrator with the blocking notification API.

Uses AgentNotificationDispatcher for shared async dispatch logic.
"""

import logging
from typing import Optional

# Import from lupin_cli.notifications
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

# Shared utilities
from cosa.agents.utils.sender_id import build_sender_id
from cosa.agents.utils.feedback_analysis import is_approval, is_rejection
from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher

logger = logging.getLogger( __name__ )


# =============================================================================
# Sender Identity Configuration
# =============================================================================

AGENT_TYPE = "presentation.gen"

# Internal dispatcher instance
_dispatcher = AgentNotificationDispatcher( agent_type=AGENT_TYPE, default_suffix="cli" )


def _get_sender_id( suffix: str = None ) -> str:
    """
    Get sender_id for Presentation Generator Agent notifications.

    Requires:
        - suffix is None or a non-empty string

    Ensures:
        - Returns sender_id in format: presentation.gen@{project}.deepily.ai#{suffix}

    Returns:
        str: Sender ID for notification identity
    """
    if suffix is not None:
        return _dispatcher.build_sender_id( suffix=suffix )
    return _dispatcher.build_sender_id()


# Cache sender_id at module load
# NOTE: Mutable — job.py callers may append suffixes at runtime
SENDER_ID = _get_sender_id()

# Session name for UI display (set by CLI before notifications)
SESSION_NAME: Optional[ str ] = None

# Target user email for notification routing (set by job.py at runtime)
TARGET_USER: Optional[ str ] = None


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

    Requires:
        - message is a non-empty string
        - priority is "low", "medium", "high", or "urgent"

    Ensures:
        - Notification dispatched to user via cosa-voice
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
    job_id: Optional[ str ] = None
) -> bool:
    """
    Ask a yes/no question and return boolean result.

    Requires:
        - question is a non-empty string
        - default is "yes" or "no"

    Ensures:
        - Returns True if user said yes, False otherwise

    Returns:
        bool: True if user approved, False otherwise
    """
    _dispatcher.sender_id   = SENDER_ID
    _dispatcher.target_user = TARGET_USER
    return await _dispatcher.ask_confirmation(
        question, default=default, timeout=timeout, abstract=abstract, job_id=job_id
    )


async def get_feedback(
    prompt: str,
    timeout: int = 300,
    job_id: Optional[ str ] = None
) -> Optional[ str ]:
    """
    Get open-ended feedback from user via voice.

    Requires:
        - prompt is a non-empty string

    Ensures:
        - Returns user's response or None on timeout

    Returns:
        str or None: User's response
    """
    _dispatcher.sender_id   = SENDER_ID
    _dispatcher.target_user = TARGET_USER
    return await _dispatcher.get_feedback( prompt, timeout=timeout, job_id=job_id )


async def present_choices(
    questions: list,
    timeout: int = 120,
    title: Optional[ str ] = None,
    abstract: Optional[ str ] = None,
    job_id: Optional[ str ] = None
) -> dict:
    """
    Present multiple-choice questions and get user's selection.

    Requires:
        - questions is a non-empty list of question objects

    Ensures:
        - Returns dict with "answers" key containing selections

    Returns:
        dict: {"answers": {...}} with selections keyed by header
    """
    _dispatcher.sender_id   = SENDER_ID
    _dispatcher.target_user = TARGET_USER
    return await _dispatcher.present_choices(
        questions, timeout=timeout, title=title, abstract=abstract, job_id=job_id
    )


# =============================================================================
# Smoke Test
# =============================================================================

def quick_smoke_test():
    """Quick smoke test for Presentation Generator cosa_interface module."""
    import inspect
    import cosa.utils.util as cu

    cu.print_banner( "Presentation Generator COSA Interface Smoke Test", prepend_nl=True )

    try:
        # Test 1: Sender ID generation
        print( "Testing sender_id generation..." )
        sender_id = _get_sender_id()
        assert "presentation.gen@" in sender_id
        assert ".deepily.ai" in sender_id
        print( f"  Sender ID: {sender_id}" )
        print( "  PASS" )

        # Test 2: Dispatcher configured
        print( "Testing dispatcher configuration..." )
        assert _dispatcher.agent_type == "presentation.gen"
        assert "presentation.gen@" in _dispatcher.sender_id
        print( "  PASS" )

        # Test 3: Async function signatures
        print( "Testing async function signatures..." )
        assert inspect.iscoroutinefunction( notify_progress )
        assert inspect.iscoroutinefunction( ask_confirmation )
        assert inspect.iscoroutinefunction( get_feedback )
        assert inspect.iscoroutinefunction( present_choices )
        print( "  PASS" )

        # Test 4: Feedback analysis imports
        print( "Testing feedback analysis imports..." )
        assert is_approval( "yes" ) is True
        assert is_rejection( "no" ) is True
        print( "  PASS" )

        print( "\nAll Presentation Generator COSA Interface smoke tests passed" )

    except Exception as e:
        print( f"\nSmoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
