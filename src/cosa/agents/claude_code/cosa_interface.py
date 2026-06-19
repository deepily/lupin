#!/usr/bin/env python3
"""
COSA Voice Interface for Claude Code Agent.

This module provides async wrappers for the cosa-voice notification tools,
enabling ClaudeCodeJob to send notifications to the UI with proper job_id
routing for job card display.

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

# Shared utilities
from cosa.agents.utils.sender_id import build_sender_id
from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher

logger = logging.getLogger( __name__ )


# =============================================================================
# Sender Identity Configuration
# =============================================================================

AGENT_TYPE = "claude.code.job"

# Internal dispatcher instance
_dispatcher = AgentNotificationDispatcher( agent_type=AGENT_TYPE )


def _get_sender_id() -> str:
    """
    Get sender_id for Claude Code job notifications.

    Returns:
        str: Sender ID in format: claude.code.job@{project}.deepily.ai
    """
    return _dispatcher.build_sender_id()


# Cache sender_id at module load
SENDER_ID = _get_sender_id()

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
    queue_name: Optional[ str ] = None
) -> None:
    """
    Send fire-and-forget progress notification.

    Args:
        message: Progress message to announce
        priority: "low", "medium", "high", or "urgent"
        abstract: Optional supplementary context
        session_name: Optional human-readable session name
        job_id: Agentic job ID for routing to job cards
        queue_name: Optional queue where job is running
    """
    _dispatcher.sender_id   = SENDER_ID
    _dispatcher.target_user = TARGET_USER
    await _dispatcher.notify_progress(
        message, priority=priority, abstract=abstract,
        session_name=session_name, job_id=job_id, queue_name=queue_name
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
        job_id: Agentic job ID for routing

    Returns:
        bool: True if user said yes, False otherwise
    """
    _dispatcher.sender_id   = SENDER_ID
    _dispatcher.target_user = TARGET_USER
    return await _dispatcher.ask_confirmation(
        question, default=default, timeout=timeout,
        abstract=abstract, job_id=job_id
    )


def quick_smoke_test():
    """Quick smoke test for claude_code cosa_interface module."""
    import cosa.utils.util as cu

    cu.print_banner( "Claude Code COSA Interface Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import validation
        print( "Testing imports..." )
        assert NotificationRequest is not None
        assert NotificationType is not None
        assert ResponseType is not None
        print( "  Import valid" )

        # Test 2: Sender ID format
        print( "Testing sender ID format..." )
        assert "claude.code.job@" in SENDER_ID
        assert ".deepily.ai" in SENDER_ID
        print( f"  Sender ID: {SENDER_ID}" )

        # Test 3: Async functions exist
        print( "Testing async function signatures..." )
        import inspect
        assert inspect.iscoroutinefunction( notify_progress )
        assert inspect.iscoroutinefunction( ask_confirmation )
        print( "  Async functions have correct signatures" )

        # Test 4: notify_progress signature includes job_id
        print( "Testing notify_progress has job_id parameter..." )
        sig = inspect.signature( notify_progress )
        assert "job_id" in sig.parameters
        print( "  notify_progress supports job_id parameter" )

        # Test 5: Dispatcher is properly configured
        print( "Testing dispatcher configuration..." )
        assert _dispatcher.agent_type == "claude.code.job"
        assert "claude.code.job@" in _dispatcher.sender_id
        print( f"  Dispatcher sender_id: {_dispatcher.sender_id}" )

        print( "\n  Claude Code COSA Interface smoke test completed successfully" )

    except Exception as e:
        print( f"\n  Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
