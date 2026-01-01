#!/usr/bin/env python3
"""
CoSA Voice MCP Server - Voice I/O bridge for Claude Code.

Provides three tools:
  - converse(): Speak to user, wait for voice/text response (blocking)
  - notify(): Announce to user without waiting (fire-and-forget)
  - ask_yes_no(): Quick yes/no decision (convenience wrapper)

Session ID Format: claude.code@{project}.deepily.ai

Configuration:
    COSA_PROJECT: Project name (required, will be lowercased)

Usage:
    export COSA_PROJECT="lupin"
    claude mcp add cosa -- python /path/to/cosa_voice_mcp.py

Works with both:
    - Option A: Print mode (bounded tasks)
    - Option B: SDK Client (interactive sessions)
"""

import os
import sys
from typing import Optional
from pydantic import ValidationError
from fastmcp import FastMCP

# Import from cosa.cli (the updated notification library)
from cosa.cli.notification_models import (
    NotificationRequest,
    AsyncNotificationRequest,
    NotificationResponse,
    AsyncNotificationResponse,
    NotificationType,
    NotificationPriority,
    ResponseType
)
from cosa.cli.notify_user_sync import notify_user_sync
from cosa.cli.notify_user_async import notify_user_async


# ============================================================================
# Session Configuration
# ============================================================================

def _get_project() -> str:
    """Get project name from environment, lowercased."""
    project = os.getenv("COSA_PROJECT", "").strip()
    if not project:
        print("Error: COSA_PROJECT environment variable required", file=sys.stderr)
        print("Example: export COSA_PROJECT='lupin'", file=sys.stderr)
        sys.exit(1)
    return project.lower()


def _get_sender_id(project: str) -> str:
    """Generate sender_id in format: claude.code@{project}.deepily.ai"""
    return f"claude.code@{project}.deepily.ai"


# Initialize at module load
PROJECT = _get_project()
SENDER_ID = _get_sender_id(PROJECT)


# ============================================================================
# MCP Server
# ============================================================================

mcp = FastMCP(
    name="CoSA Voice Bridge",
    description=f"Voice I/O for Claude Code [Session: {SENDER_ID}]"
)


@mcp.tool
def converse(
    message: str,
    response_type: str = "open_ended",
    timeout_seconds: int = 120,
    response_default: Optional[str] = None,
    priority: str = "medium",
    title: Optional[str] = None
) -> str:
    """
    Speak to the user and wait for their voice/text response.
    
    Use this when you need input, clarification, or a decision from the user.
    The message will be converted to speech (TTS) and played to the user.
    Their response (via voice or text) will be returned to you.
    
    Args:
        message: What to say to the user
        response_type: "yes_no" for binary choices, "open_ended" for free-form
        timeout_seconds: How long to wait (1-600, default 120)
        response_default: Fallback if timeout or user offline
        priority: "low", "medium", "high", or "urgent"
        title: Optional short title for the notification
    
    Returns:
        User's response as text, or error/timeout message
    
    Examples:
        converse("Should I proceed with the refactor?", response_type="yes_no")
        converse("What naming convention should I use for the new module?")
        converse("The tests are failing. Should I continue?", response_default="yes")
    """
    try:
        request = NotificationRequest(
            message=message,
            response_type=ResponseType(response_type),
            notification_type=NotificationType.CUSTOM,
            priority=NotificationPriority(priority),
            timeout_seconds=timeout_seconds,
            response_default=response_default,
            title=title,
            sender_id=SENDER_ID  # Native field in updated library
        )
    except (ValidationError, ValueError) as e:
        return f"[validation error: {e}]"

    response: NotificationResponse = notify_user_sync(request=request, debug=False)

    if response.exit_code == 0:
        prefix = "[default used] " if response.default_used else ""
        return f"{prefix}{response.response_value or ''}"
    elif response.exit_code == 2:
        if response_default is not None:
            return f"[timeout - using default] {response_default}"
        return "[timeout - no response received]"
    else:
        return f"[error: {response.status}]"


@mcp.tool
def notify(
    message: str,
    notification_type: str = "progress",
    priority: str = "medium"
) -> str:
    """
    Announce something to the user without waiting for response.
    
    Use this for status updates, progress reports, or FYI messages.
    The message will be converted to speech (TTS) and played to the user.
    This call returns immediately - it does not wait for acknowledgment.
    
    Args:
        message: What to announce to the user
        notification_type: "task", "progress", "alert", or "custom"
        priority: "low", "medium", "high", or "urgent"
    
    Returns:
        Delivery status message
    
    Examples:
        notify("Starting code analysis...", notification_type="progress")
        notify("Build completed successfully", notification_type="task")
        notify("Warning: deprecated API detected", notification_type="alert", priority="high")
    """
    try:
        request = AsyncNotificationRequest(
            message=message,
            notification_type=NotificationType(notification_type),
            priority=NotificationPriority(priority),
            sender_id=SENDER_ID  # Native field in updated library
        )
    except (ValidationError, ValueError) as e:
        return f"[validation error: {e}]"

    response: AsyncNotificationResponse = notify_user_async(request=request, debug=False)

    if response.success:
        return f"Notification sent ({response.status})"
    else:
        return f"Failed: {response.message}"


@mcp.tool
def ask_yes_no(
    question: str,
    default: str = "no",
    timeout_seconds: int = 60
) -> bool:
    """
    Ask a yes/no question and get a boolean result.
    
    Convenience wrapper for quick binary decisions.
    
    Args:
        question: The yes/no question to ask
        default: Default answer if timeout ("yes" or "no")
        timeout_seconds: How long to wait (default 60)
    
    Returns:
        True if user said yes, False otherwise
    
    Examples:
        if ask_yes_no("Delete the old backups?"):
            # User said yes
        if ask_yes_no("Continue despite warnings?", default="no"):
            # User said yes (or default was overridden)
    """
    try:
        request = NotificationRequest(
            message=question,
            response_type=ResponseType.YES_NO,
            notification_type=NotificationType.CUSTOM,
            priority=NotificationPriority.MEDIUM,
            timeout_seconds=timeout_seconds,
            response_default=default,
            sender_id=SENDER_ID
        )
    except (ValidationError, ValueError):
        return default == "yes"

    response: NotificationResponse = notify_user_sync(request=request, debug=False)

    if response.exit_code == 0 and response.response_value:
        return response.response_value.lower().strip() == "yes"

    return default == "yes"


@mcp.tool
def get_session_info() -> dict:
    """
    Get current session identification.
    
    Returns:
        dict with project name and sender_id
    """
    return {
        "project": PROJECT,
        "sender_id": SENDER_ID
    }


if __name__ == "__main__":
    print(f"Project: {PROJECT}", file=sys.stderr)
    print(f"Sender ID: {SENDER_ID}", file=sys.stderr)
    mcp.run()
