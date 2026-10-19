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
from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher, make_interface_functions

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

notify_progress, ask_confirmation, get_feedback, present_choices = make_interface_functions( globals(), notify_extras=( "progress_group_id", ), choices_extras=( "priority", ) )


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
