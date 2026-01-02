#!/usr/bin/env python3
"""
CoSA Voice MCP Server - Voice I/O bridge for Claude Code.

Provides four tools:
  - converse(): Speak to user, wait for voice/text response (blocking)
  - notify(): Announce to user without waiting (fire-and-forget)
  - ask_yes_no(): Quick yes/no decision (convenience wrapper)
  - get_session_info(): Get current session identification

Session ID Format: claude.code@{project}.deepily.ai

Project Detection (automatic):
    1. Auto-detects from current working directory:
       - genie-in-the-box, lupin → "lupin"
       - planning-is-prompting → "plan"
       - cosa (standalone) → "cosa"
    2. Falls back to MCP_PROJECT env var if cwd detection fails
    3. Falls back to "unknown" with console warning if neither works

Environment Variables:
    MCP_PROJECT: Fallback project name (optional, auto-detection preferred)
    LUPIN_APP_SERVER_URL: Server URL (default: http://localhost:7999)
    MCP_DEBUG: Enable debug logging (optional)

Usage:
    # One MCP registration works for all projects via auto-detection
    claude mcp add cosa-voice -- python /path/to/cosa_voice_mcp.py
"""

import logging
import os
import signal
import sys
from typing import Optional

from pydantic import ValidationError
from fastmcp import FastMCP

# Import from cosa.cli (the notification library)
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
# Logging Configuration
# ============================================================================

logging.basicConfig(
    level=logging.DEBUG if os.getenv( "MCP_DEBUG" ) else logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    stream=sys.stderr
)
logger = logging.getLogger( __name__ )

# ============================================================================
# Version
# ============================================================================

__version__ = "0.1.0"

# ============================================================================
# Configuration
# ============================================================================

def _get_server_url() -> str:
    """Get Lupin server URL from environment."""
    return os.getenv( "LUPIN_APP_SERVER_URL", "http://localhost:7999" )


def _detect_project_from_cwd() -> Optional[ str ]:
    """Attempt to detect project name from current working directory.

    Requires:
        - Current working directory is accessible

    Ensures:
        - Returns lowercase project name if detected
        - Returns None if no known project pattern found

    Known project patterns:
        - genie-in-the-box, lupin → "lupin"
        - planning-is-prompting → "plan"
        - cosa (standalone, not as subdir) → "cosa"
    """
    try:
        cwd = os.getcwd().lower()

        # Lupin project detection (main repo)
        if "genie-in-the-box" in cwd or "/lupin" in cwd:
            return "lupin"

        # Planning-is-Prompting project detection
        if "planning-is-prompting" in cwd:
            return "plan"

        # CoSA standalone (not as submodule within genie-in-the-box)
        # Check it's not inside genie-in-the-box first
        if "/cosa" in cwd and "genie-in-the-box" not in cwd:
            return "cosa"

        return None

    except Exception as e:
        logger.debug( f"Could not detect project from cwd: {e}" )
        return None


def _get_project() -> str:
    """Get project name with dynamic detection and fallback.

    Detection priority:
        1. Auto-detect from current working directory
        2. MCP_PROJECT environment variable
        3. Fallback to "unknown" (with warning)

    Note: MCP_PROJECT can be set in MCP JSON config's env section as a default,
    but dynamic detection from cwd takes precedence for multi-project support.
    """
    # Priority 1: Try dynamic detection from working directory
    detected = _detect_project_from_cwd()
    if detected:
        logger.info( f"Project auto-detected from cwd: {detected}" )
        return detected

    # Priority 2: Check environment variable
    project = os.getenv( "MCP_PROJECT", "" ).strip()
    if project:
        logger.info( f"Project from MCP_PROJECT env var: {project.lower()}" )
        return project.lower()

    # Priority 3: Fallback to unknown with prominent warning
    logger.warning( "=" * 60 )
    logger.warning( "⚠️  PROJECT DETECTION FAILED - USING 'unknown'" )
    logger.warning( "=" * 60 )
    logger.warning( f"Current working directory: {os.getcwd()}" )
    logger.warning( "Could not detect project from path, and MCP_PROJECT env var not set." )
    logger.warning( "" )
    logger.warning( "Notifications will appear as: claude.code@unknown.deepily.ai" )
    logger.warning( "" )
    logger.warning( "To fix, either:" )
    logger.warning( "  1. Run Claude Code from within a known project directory" )
    logger.warning( "  2. Set MCP_PROJECT in your MCP config's env section:" )
    logger.warning( '     "env": { "MCP_PROJECT": "your-project-name" }' )
    logger.warning( "=" * 60 )

    return "unknown"


def _get_sender_id( project: str ) -> str:
    """Generate sender_id in format: claude.code@{project}.deepily.ai"""
    return f"claude.code@{project}.deepily.ai"


# ============================================================================
# Signal Handlers
# ============================================================================

def _handle_sigterm( signum, frame ):
    """Handle SIGTERM for graceful shutdown."""
    logger.info( "Received SIGTERM, shutting down gracefully" )
    sys.exit( 0 )


signal.signal( signal.SIGTERM, _handle_sigterm )

# ============================================================================
# Initialize at module load
# ============================================================================

PROJECT    = _get_project()
SENDER_ID  = _get_sender_id( PROJECT )
SERVER_URL = _get_server_url()

logger.info( f"Project: {PROJECT}" )
logger.info( f"Sender ID: {SENDER_ID}" )
logger.info( f"Server URL: {SERVER_URL}" )

# ============================================================================
# MCP Server
# ============================================================================

mcp = FastMCP(
    name="CoSA Voice Bridge",
    instructions=f"Voice I/O for Claude Code [Session: {SENDER_ID}]"
)


@mcp.tool
def converse(
    message: str,
    response_type: str = "open_ended",
    timeout_seconds: int = 120,
    response_default: Optional[ str ] = None,
    priority: str = "medium",
    title: Optional[ str ] = None
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
    logger.debug( f"converse() called: {message[:50]}..." )

    try:
        request = NotificationRequest(
            message=message,
            response_type=ResponseType( response_type ),
            notification_type=NotificationType.CUSTOM,
            priority=NotificationPriority( priority ),
            timeout_seconds=timeout_seconds,
            response_default=response_default,
            title=title,
            sender_id=SENDER_ID
        )
    except ( ValidationError, ValueError ) as e:
        logger.error( f"Validation error: {e}" )
        return f"[validation error: {e}]"

    response: NotificationResponse = notify_user_sync( request=request, debug=False )

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
    logger.debug( f"notify() called: {message[:50]}..." )

    try:
        request = AsyncNotificationRequest(
            message=message,
            notification_type=NotificationType( notification_type ),
            priority=NotificationPriority( priority ),
            sender_id=SENDER_ID
        )
    except ( ValidationError, ValueError ) as e:
        logger.error( f"Validation error: {e}" )
        return f"[validation error: {e}]"

    response: AsyncNotificationResponse = notify_user_async( request=request, debug=False )

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
    logger.debug( f"ask_yes_no() called: {question[:50]}..." )

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
    except ( ValidationError, ValueError ):
        return default == "yes"

    response: NotificationResponse = notify_user_sync( request=request, debug=False )

    if response.exit_code == 0 and response.response_value:
        return response.response_value.lower().strip() == "yes"

    return default == "yes"


@mcp.tool
def get_session_info() -> dict:
    """
    Get current session identification and server info.

    Returns:
        dict with project name, sender_id, server_url, and version
    """
    return {
        "project"    : PROJECT,
        "sender_id"  : SENDER_ID,
        "server_url" : SERVER_URL,
        "version"    : __version__
    }


if __name__ == "__main__":
    mcp.run()
