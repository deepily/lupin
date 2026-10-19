#!/usr/bin/env python3
"""
COSA Voice Interface for Claude Code Agent.

This module provides async wrappers for the cosa-voice notification tools.
They let ClaudeCodeJob send notifications to the UI, routed by job_id
so each one lands on the right job card.

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
from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher, make_interface_functions

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

notify_progress, ask_confirmation, _get_feedback, _present_choices = make_interface_functions( globals(), push_session_name=False )


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
