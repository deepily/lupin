#!/usr/bin/env python3
"""
COSA Voice Interface Integration Layer for Test Suite Agent.

Provides async wrappers for cosa-voice notification tools,
configured with test_suite sender identity.

Uses AgentNotificationDispatcher for shared async dispatch logic.
Module-level SENDER_ID and SESSION_NAME remain mutable for runtime
configuration by job.py callers.
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
from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher

logger = logging.getLogger( __name__ )


# =============================================================================
# Sender Identity Configuration
# =============================================================================

AGENT_TYPE = "test.suite"

# Internal dispatcher instance for shared async dispatch logic
_dispatcher = AgentNotificationDispatcher( agent_type=AGENT_TYPE )


def _get_sender_id( suffix: str = None ) -> str:
    """
    Get sender_id for Test Suite Agent notifications.

    Requires:
        - suffix is a string or None

    Ensures:
        - Returns sender_id in format: test.suite@{project}.deepily.ai#{suffix}

    Args:
        suffix: Optional override for the default suffix (e.g., job id_hash).

    Returns:
        str: Sender ID for notification identity
    """
    if suffix is not None:
        return _dispatcher.build_sender_id( suffix=suffix )
    return _dispatcher.build_sender_id()


# Cache sender_id at module load
SENDER_ID = _get_sender_id()

# Session name for UI display (set by job.py before notifications)
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
        - priority is one of: low, medium, high, urgent

    Ensures:
        - Notification dispatched asynchronously
        - Returns immediately (non-blocking)

    Args:
        message: Notification text
        priority: Notification priority level
        abstract: Optional markdown abstract for notification body
        session_name: Optional session name override
        job_id: Optional job ID for activity log routing
        queue_name: Optional queue name for queue-specific routing
        progress_group_id: Optional group ID for in-place DOM updates
    """
    _dispatcher.sender_id    = SENDER_ID
    _dispatcher.session_name = session_name or SESSION_NAME
    _dispatcher.target_user  = TARGET_USER
    await _dispatcher.notify_progress(
        message, priority=priority, abstract=abstract,
        session_name=session_name or SESSION_NAME, job_id=job_id,
        queue_name=queue_name, progress_group_id=progress_group_id
    )


async def ask_yes_no(
    question: str,
    default: str = "no",
    abstract: Optional[ str ] = None,
    session_name: Optional[ str ] = None,
    job_id: Optional[ str ] = None,
    queue_name: Optional[ str ] = None
) -> str:
    """
    Ask a blocking yes/no question via cosa-voice.

    Requires:
        - question is a non-empty string
        - default is "yes" or "no"

    Ensures:
        - Returns "yes" or "no" string

    Args:
        question: The yes/no question text
        default: Default answer if user doesn't respond
        abstract: Optional markdown abstract
        session_name: Optional session name override
        job_id: Optional job ID for routing
        queue_name: Optional queue name for routing

    Returns:
        str: "yes" or "no"
    """
    return await _dispatcher.ask_yes_no(
        question     = question,
        sender_id    = SENDER_ID,
        target_user  = TARGET_USER,
        default      = default,
        abstract     = abstract,
        session_name = session_name or SESSION_NAME,
        job_id       = job_id,
        queue_name   = queue_name
    )
