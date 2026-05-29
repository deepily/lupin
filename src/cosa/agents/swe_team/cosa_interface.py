#!/usr/bin/env python3
"""
COSA Voice Interface Integration Layer for SWE Team Agent.

Role-aware notification wrappers that bridge the async orchestrator
with the blocking notification API. Each notification carries a
role-specific sender_id for routing and display.

Uses AgentNotificationDispatcher for shared async dispatch logic.

CONTRACT:
    This module is the orchestrator's notification layer. It provides:
    - Role-aware sender IDs (swe.lead@, swe.coder@, swe.tester@)
    - job_id routing for CJ Flow integration
    - Blocking confirmations and decisions (ask_confirmation, request_decision)
    - Fire-and-forget progress notifications (notify_progress)
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
from cosa.agents.utils.sender_id import detect_project, build_sender_id
from cosa.agents.utils.feedback_analysis import is_approval, is_rejection
from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher

logger = logging.getLogger( __name__ )


# =============================================================================
# Sender Identity Configuration
# =============================================================================

AGENT_TYPE_PREFIX = "swe"

# Internal dispatcher instance (role-aware)
_dispatcher = AgentNotificationDispatcher(
    agent_type=AGENT_TYPE_PREFIX, supports_role=True, default_priority="high"
)


def get_sender_id( role: str = "lead", session_id: str = None ) -> str:
    """
    Construct sender_id for a given SWE Team agent role.

    Requires:
        - role is a valid role name string

    Ensures:
        - Returns sender_id in format: swe.{role}@{project}.deepily.ai[#{session_id}]
        - Conforms to existing Lupin sender_id regex

    Args:
        role: The agent role name (lead, coder, tester, etc.)
        session_id: Optional session ID suffix

    Returns:
        str: Sender ID string
    """
    # Strip user-scope suffix (::user_id) — only the base hash is needed for routing
    suffix = None
    if session_id:
        suffix = session_id.split( "::" )[ 0 ] if "::" in session_id else session_id

    return build_sender_id( f"swe.{role}", project=PROJECT, suffix=suffix )


# Cache at module load
PROJECT = detect_project()

# Session name for UI display (set by orchestrator before notifications)
SESSION_NAME: Optional[ str ] = None

# Session ID for sender_id suffix (set by orchestrator)
SESSION_ID: Optional[ str ] = None

# Target user email for notification routing (set by job.py at runtime)
TARGET_USER: Optional[ str ] = None


# =============================================================================
# Primary Interface Functions
# =============================================================================

async def notify_progress(
    message: str,
    role: str = "lead",
    priority: str = "medium",
    abstract: Optional[ str ] = None,
    session_name: Optional[ str ] = None,
    job_id: Optional[ str ] = None,
    queue_name: Optional[ str ] = None,
    progress_group_id: Optional[ str ] = None,
) -> None:
    """
    Send fire-and-forget progress notification from a specific agent role.

    Args:
        message: Progress message to announce
        role: Agent role sending the notification
        priority: "low", "medium", "high", or "urgent"
        abstract: Optional supplementary context
        session_name: Optional human-readable session name
        job_id: Optional agentic job ID for routing
        queue_name: Optional queue where job is running
        progress_group_id: Optional progress group ID for in-place DOM updates
    """
    _dispatcher.session_id   = SESSION_ID
    _dispatcher.session_name = SESSION_NAME
    _dispatcher.target_user  = TARGET_USER
    await _dispatcher.notify_progress(
        message, priority=priority, abstract=abstract,
        session_name=session_name, job_id=job_id,
        queue_name=queue_name, progress_group_id=progress_group_id,
        role=role
    )


async def ask_confirmation(
    question: str,
    role: str = "lead",
    default: str = "no",
    timeout: int = 120,
    abstract: Optional[ str ] = None,
) -> bool:
    """
    Ask a yes/no question and return boolean result.

    Args:
        question: The yes/no question to ask
        role: Agent role asking the question
        default: Default answer if timeout
        timeout: Seconds to wait for response
        abstract: Optional supplementary context

    Returns:
        bool: True if approved, False otherwise
    """
    _dispatcher.session_id   = SESSION_ID
    _dispatcher.target_user  = TARGET_USER
    return await _dispatcher.ask_confirmation(
        question, default=default, timeout=timeout,
        abstract=abstract, role=role
    )


async def request_decision(
    question: str,
    options: list,
    role: str = "lead",
    timeout: int = 300,
    abstract: Optional[ str ] = None,
) -> dict:
    """
    Present multiple-choice decision to user/proxy.

    Args:
        question: The decision question
        options: List of question objects with header, options, multiSelect
        role: Agent role requesting the decision
        timeout: Seconds to wait
        abstract: Optional supplementary context

    Returns:
        dict: {"answers": {...}} with selections
    """
    _dispatcher.session_id   = SESSION_ID
    _dispatcher.target_user  = TARGET_USER
    return await _dispatcher.present_choices(
        options, timeout=timeout, abstract=abstract, role=role
    )


async def get_feedback(
    prompt: str,
    role: str = "lead",
    timeout: int = 300,
) -> Optional[ str ]:
    """
    Get open-ended feedback from user via voice.

    Args:
        prompt: Text to speak to the user
        role: Agent role requesting feedback
        timeout: Maximum seconds to wait

    Returns:
        str or None: User's transcribed response
    """
    _dispatcher.session_id   = SESSION_ID
    _dispatcher.target_user  = TARGET_USER
    return await _dispatcher.get_feedback( prompt, timeout=timeout, role=role )


# =============================================================================
# Feedback Analysis Utilities
# =============================================================================
# NOTE: is_approval() and is_rejection() are now imported from
# cosa.agents.utils.feedback_analysis (see imports above).


def quick_smoke_test():
    """Quick smoke test for SWE Team cosa_interface module."""
    import cosa.utils.util as cu

    cu.print_banner( "SWE Team COSA Interface Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import validation
        print( "Testing imports..." )
        assert NotificationRequest is not None
        assert NotificationType is not None
        assert ResponseType is not None
        print( "✓ Imports valid" )

        # Test 2: Sender ID generation
        print( "Testing sender ID generation..." )
        sid = get_sender_id( "lead" )
        assert "swe.lead@" in sid
        assert ".deepily.ai" in sid
        sid_session = get_sender_id( "coder", "abc123" )
        assert sid_session.endswith( "#abc123" )
        # Test compound hash stripping (Bug F fix)
        sid_compound = get_sender_id( "lead", "swe-4637f1cd::0cf47e2d-d5a1-4cd4-addf-79810fd32b15" )
        assert sid_compound.endswith( "#swe-4637f1cd" ), f"Expected stripped hash, got: {sid_compound}"
        assert "::" not in sid_compound, f"Compound hash not stripped: {sid_compound}"
        print( f"✓ Sender IDs: {sid}, {sid_session}, {sid_compound}" )

        # Test 3: is_approval
        print( "Testing is_approval..." )
        assert is_approval( "yes" ) is True
        assert is_approval( "sounds good" ) is True
        assert is_approval( "no" ) is False
        assert is_approval( "" ) is False
        assert is_approval( None ) is False  # type: ignore
        print( "✓ is_approval works correctly" )

        # Test 4: is_rejection
        print( "Testing is_rejection..." )
        assert is_rejection( "no" ) is True
        assert is_rejection( "wait, stop" ) is True
        assert is_rejection( "yes" ) is False
        assert is_rejection( "" ) is False
        print( "✓ is_rejection works correctly" )

        # Test 5: Async function signatures
        print( "Testing async function signatures..." )
        import inspect
        assert inspect.iscoroutinefunction( notify_progress )
        assert inspect.iscoroutinefunction( ask_confirmation )
        assert inspect.iscoroutinefunction( request_decision )
        assert inspect.iscoroutinefunction( get_feedback )
        print( "✓ Async functions have correct signatures" )

        # Test 6: notify_progress has role parameter
        print( "Testing role-aware signatures..." )
        sig = inspect.signature( notify_progress )
        assert "role" in sig.parameters
        assert "job_id" in sig.parameters
        sig = inspect.signature( ask_confirmation )
        assert "role" in sig.parameters
        print( "✓ All functions accept role parameter" )

        # Test 7: Dispatcher is role-aware
        print( "Testing dispatcher configuration..." )
        assert _dispatcher.supports_role is True
        assert _dispatcher.default_priority == "high"
        print( "✓ Dispatcher is role-aware with high default priority" )

        print( "\n✓ SWE Team COSA Interface smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
