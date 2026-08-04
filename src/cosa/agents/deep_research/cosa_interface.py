#!/usr/bin/env python3
"""
COSA Voice Interface Integration Layer for Deep Research.

This module provides async wrappers for the cosa-voice notification tools,
bridging the async orchestrator with the blocking notification API.

Uses AgentNotificationDispatcher for shared async dispatch logic.

Per-task isolation (OOS Phase 4 backlog #1, 2026-04-29):
    Module-level SENDER_ID / SESSION_NAME / TARGET_USER are kept for the CLI
    path and for backward compatibility, but agentic-pool jobs MUST use
    `set_dispatch_context()` (defined below) to isolate per-task state via
    ContextVars. The dispatcher reads ContextVar in priority over instance
    state, so concurrent DR jobs in the agentic pool no longer leak each
    other's sender_id through the shared module-global dispatcher instance.
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
from cosa.agents.utils.feedback_analysis import (
    is_approval, is_rejection, extract_feedback_intent,
    APPROVAL_SIGNALS, REJECTION_SIGNALS
)
from cosa.agents.utils.agent_notification_dispatcher import (
    AgentNotificationDispatcher,
    ctx_sender_id,
    ctx_target_user,
    ctx_session_name,
)

logger = logging.getLogger( __name__ )


# =============================================================================
# Sender Identity Configuration
# =============================================================================

AGENT_TYPE = "deep.research"

# Internal dispatcher instance for shared async dispatch logic
_dispatcher = AgentNotificationDispatcher( agent_type=AGENT_TYPE )


def _get_sender_id( suffix: str = None ) -> str:
    """
    Get sender_id for Deep Research Agent notifications.

    Args:
        suffix: Optional override for the default suffix (e.g., job id_hash).
            Prevents double-hash fragments when appending job IDs.

    Ensures:
        - Returns sender_id in format: deep.research@{project}.deepily.ai#{suffix}
        - Project is detected from current working directory

    Returns:
        str: Sender ID for notification identity
    """
    if suffix is not None:
        return _dispatcher.build_sender_id( suffix=suffix )
    return _dispatcher.build_sender_id()


# Cache sender_id at module load (avoids repeated os.getcwd calls)
# NOTE: Mutable — job.py and cli.py callers may append suffixes at runtime
SENDER_ID = _get_sender_id()

# Session name for UI display (set by CLI/job before notifications)
SESSION_NAME: Optional[ str ] = None

# Target user email for notification routing (set by job.py at runtime)
TARGET_USER: Optional[ str ] = None


def set_dispatch_context(
    sender_id    : Optional[ str ] = None,
    target_user  : Optional[ str ] = None,
    session_name : Optional[ str ] = None,
) -> dict:
    """
    Set the per-task dispatch context for this asyncio task / thread.

    Use this instead of mutating module-level SENDER_ID / TARGET_USER /
    SESSION_NAME when running inside the agentic pool — concurrent DR jobs
    share module globals (and the shared `_dispatcher` instance), so writing
    to module globals leaks state across jobs. ContextVars isolate per-task.

    Requires:
        - At least one of sender_id, target_user, session_name is provided.
          (None values are skipped — only set what's provided.)

    Ensures:
        - Each provided value is stored in its corresponding ContextVar.
        - Returns a dict of {var_name: token} that callers can pass to
          `reset_dispatch_context()` for explicit teardown.

    Args:
        sender_id    : Per-task sender_id override (None = leave ContextVar unchanged).
        target_user  : Per-task target_user override.
        session_name : Per-task session_name override.

    Returns:
        dict[str, contextvars.Token]: Tokens for resetting the ContextVars
            via `reset_dispatch_context()`. Pool workers running a single
            job typically don't need to reset (the asyncio.run() context
            ends when the worker finishes), but explicit cleanup is good
            hygiene.
    """
    tokens = { }
    if sender_id is not None:
        tokens[ "sender_id" ] = ctx_sender_id.set( sender_id )
    if target_user is not None:
        tokens[ "target_user" ] = ctx_target_user.set( target_user )
    if session_name is not None:
        tokens[ "session_name" ] = ctx_session_name.set( session_name )
    return tokens


def reset_dispatch_context( tokens: dict ) -> None:
    """
    Reset the per-task dispatch context to its prior state.

    Args:
        tokens: dict returned by `set_dispatch_context()`.

    Ensures:
        - Each ContextVar is reset to the value it held before the matching
          set_dispatch_context() call.
        - Missing keys in `tokens` are silently skipped.
    """
    if "sender_id" in tokens:
        ctx_sender_id.reset( tokens[ "sender_id" ] )
    if "target_user" in tokens:
        ctx_target_user.reset( tokens[ "target_user" ] )
    if "session_name" in tokens:
        ctx_session_name.reset( tokens[ "session_name" ] )


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

    Non-blocking — runs in thread pool to avoid blocking event loop.

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
    job_id: Optional[ str ] = None
) -> bool:
    """
    Ask a yes/no question and return boolean result.

    Args:
        question: The yes/no question to ask
        default: Default answer if timeout ("yes" or "no")
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
        timeout: Maximum seconds to wait for response
        job_id: Optional job ID for routing to job card

    Returns:
        str or None: User's transcribed voice response
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
        priority: Optional notification priority. Forwarded to the dispatcher
            when the caller set one; a blocking gate passes priority="high" so
            the gate notification reaches the user's TTS channel. Accepting this
            kwarg brings deep_research to parity with podcast/presentation:
            voice_io.present_choices forwards it here, and without the parameter
            a gate that passes priority would raise TypeError and fail-open
            before it could ever dispatch to a human. deep_research gates do not
            pass priority today (this closes the latent gap, not a live one).

    Returns:
        dict: {"answers": {...}} with selections keyed by header
    """
    _dispatcher.sender_id   = SENDER_ID
    _dispatcher.target_user = TARGET_USER
    return await _dispatcher.present_choices(
        questions, timeout=timeout, title=title, abstract=abstract, job_id=job_id,
        priority=priority
    )


# =============================================================================
# Feedback Analysis Utilities
# =============================================================================
# NOTE: is_approval(), is_rejection(), and extract_feedback_intent() are now
# imported from cosa.agents.utils.feedback_analysis (see imports above).
# They remain available at module level for backward compatibility.


def quick_smoke_test():
    """Quick smoke test for cosa_interface module."""
    import cosa.utils.util as cu

    cu.print_banner( "COSA Interface Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import validation
        print( "Testing imports..." )
        assert NotificationRequest is not None
        assert NotificationType is not None
        assert ResponseType is not None
        print( "✓ Imports valid" )

        # Test 2: is_approval function
        print( "Testing is_approval..." )
        assert is_approval( "yes" ) is True
        assert is_approval( "Yes, proceed" ) is True
        assert is_approval( "sounds good" ) is True
        assert is_approval( "no" ) is False
        assert is_approval( "" ) is False
        assert is_approval( None ) is False  # type: ignore
        print( "✓ is_approval works correctly" )

        # Test 3: is_rejection function
        print( "Testing is_rejection..." )
        assert is_rejection( "no" ) is True
        assert is_rejection( "wait, stop" ) is True
        assert is_rejection( "change it" ) is True
        assert is_rejection( "yes" ) is False
        assert is_rejection( "" ) is False
        print( "✓ is_rejection works correctly" )

        # Test 4: extract_feedback_intent
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
        print( "✓ extract_feedback_intent works correctly" )

        # Test 5: format_questions_for_tts (imported from notification_utils)
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
        assert "Option" not in tts  # Options NOT in TTS - they appear in UI only
        print( "✓ format_questions_for_tts works correctly" )

        # Test 6: convert_questions_for_api (imported from notification_utils)
        print( "Testing convert_questions_for_api..." )
        questions = [ {
            "question"    : "Which themes?",
            "header"      : "Themes",
            "multiSelect" : True,
            "options"     : [ { "label": "A" }, { "label": "B" } ]
        } ]
        converted = convert_questions_for_api( questions )
        assert "questions" in converted
        assert converted[ "questions" ][ 0 ][ "multi_select" ] is True
        assert "multiSelect" not in converted[ "questions" ][ 0 ]
        print( "✓ convert_questions_for_api correctly converts multiSelect -> multi_select" )

        # Test 7: Async functions exist (can't fully test without running server)
        print( "Testing async function signatures..." )
        import inspect
        assert inspect.iscoroutinefunction( notify_progress )
        assert inspect.iscoroutinefunction( ask_confirmation )
        assert inspect.iscoroutinefunction( get_feedback )
        assert inspect.iscoroutinefunction( present_choices )
        print( "✓ Async functions have correct signatures" )

        # Test 8: Dispatcher is properly configured
        print( "Testing dispatcher configuration..." )
        assert _dispatcher.agent_type == "deep.research"
        assert "deep.research@" in _dispatcher.sender_id
        print( f"✓ Dispatcher sender_id: {_dispatcher.sender_id}" )

        print( "\n✓ COSA Interface smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
