#!/usr/bin/env python3
"""
COSA Voice Interface Integration Layer for Podcast Generator.

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

AGENT_TYPE = "podcast.gen"

# Internal dispatcher instance
_dispatcher = AgentNotificationDispatcher( agent_type=AGENT_TYPE, default_suffix="cli" )


def _get_sender_id( suffix: str = None ) -> str:
    """
    Get sender_id for Podcast Generator Agent notifications.

    Args:
        suffix: Optional override for the default suffix (e.g., job id_hash).
            When provided, replaces the default "cli" suffix to avoid
            double-hash fragments like "#cli#pg-abc123".

    Returns:
        str: Sender ID in format: podcast.gen@{project}.deepily.ai#{suffix}
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

    Args:
        message: Progress message to announce
        priority: "low", "medium", "high", or "urgent"
        abstract: Optional supplementary context (markdown)
        session_name: Optional human-readable session name
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
    job_id: Optional[ str ] = None
) -> bool:
    """
    Ask a yes/no question and return boolean result.

    Args:
        question: The yes/no question to ask
        default: Default answer if timeout
        timeout: Seconds to wait for response
        abstract: Optional supplementary context
        job_id: Optional job ID for routing to job card

    Returns:
        bool: True if user said yes, False otherwise
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

    Args:
        prompt: Text to speak to the user
        timeout: Maximum seconds to wait
        job_id: Optional job ID for routing to job card

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
    job_id: Optional[ str ] = None,
    priority: Optional[ str ] = None
) -> dict:
    """
    Present multiple-choice questions and get user's selection.

    Args:
        questions: List of question objects with options
        timeout: Seconds to wait for response
        title: Optional title for the notification
        abstract: Optional supplementary context
        job_id: Optional job ID for routing to job card
        priority: "low"/"medium"/"high"/"urgent". None → the dispatcher's
            default_priority. Blocking asks should pass "high" so the TTS alert
            reaches a remote user.

    Returns:
        dict: {"answers": {...}} with selections keyed by header
    """
    _dispatcher.sender_id   = SENDER_ID
    _dispatcher.target_user = TARGET_USER
    return await _dispatcher.present_choices(
        questions, timeout=timeout, title=title, abstract=abstract, job_id=job_id, priority=priority
    )


# =============================================================================
# Feedback Analysis Utilities
# =============================================================================
# NOTE: is_approval() and is_rejection() are now imported from
# cosa.agents.utils.feedback_analysis (see imports above).


def quick_smoke_test():
    """Quick smoke test for cosa_interface module."""
    import cosa.utils.util as cu

    cu.print_banner( "Podcast Generator COSA Interface Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import validation
        print( "Testing imports..." )
        assert NotificationRequest is not None
        assert NotificationType is not None
        assert ResponseType is not None
        print( "✓ Imports valid" )

        # Test 2: Sender ID generation
        print( "Testing sender_id generation..." )
        sender_id = _get_sender_id()
        assert "podcast.gen@" in sender_id
        assert ".deepily.ai" in sender_id
        print( f"✓ Sender ID: {sender_id}" )

        # Test 3: is_approval function
        print( "Testing is_approval..." )
        assert is_approval( "yes" ) is True
        assert is_approval( "Yes, proceed" ) is True
        assert is_approval( "sounds good" ) is True
        assert is_approval( "no" ) is False
        assert is_approval( "" ) is False
        print( "✓ is_approval works correctly" )

        # Test 4: is_rejection function
        print( "Testing is_rejection..." )
        assert is_rejection( "no" ) is True
        assert is_rejection( "wait, stop" ) is True
        assert is_rejection( "change it" ) is True
        assert is_rejection( "yes" ) is False
        print( "✓ is_rejection works correctly" )

        # Test 5: format_questions_for_tts
        print( "Testing format_questions_for_tts..." )
        questions = [ {
            "question" : "Which option?",
            "options"  : [
                { "label": "Option A" },
                { "label": "Option B" }
            ]
        } ]
        tts = format_questions_for_tts( questions )
        assert "Which option?" in tts
        assert "Option" not in tts
        print( "✓ format_questions_for_tts works" )

        # Test 6: Async function signatures
        print( "Testing async function signatures..." )
        import inspect
        assert inspect.iscoroutinefunction( notify_progress )
        assert inspect.iscoroutinefunction( ask_confirmation )
        assert inspect.iscoroutinefunction( get_feedback )
        assert inspect.iscoroutinefunction( present_choices )
        print( "✓ Async functions have correct signatures" )

        # Test 7: Dispatcher is properly configured
        print( "Testing dispatcher configuration..." )
        assert _dispatcher.agent_type == "podcast.gen"
        assert "podcast.gen@" in _dispatcher.sender_id
        print( f"✓ Dispatcher sender_id: {_dispatcher.sender_id}" )

        print( "\n✓ COSA Interface smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
