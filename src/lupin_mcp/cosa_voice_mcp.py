#!/usr/bin/env python3
"""
CoSA Voice MCP Server - Voice I/O bridge for Claude Code.

Provides five tools:
  - converse(): Speak to user, wait for voice/text response (blocking)
  - notify(): Announce to user without waiting (fire-and-forget)
  - ask_yes_no(): Quick yes/no decision (convenience wrapper)
  - ask_multiple_choice(): Present options and get user's selection(s)
  - get_session_info(): Get current session identification

Sender ID Format: claude.code@{project}.deepily.ai#{session_id}
    - session_id is an 8-character hex string unique to each MCP server instance

Project Detection (automatic):
    1. Auto-detects from current working directory (checked in order):
       - cosa → "cosa" (checked first - may be submodule of lupin)
       - lupin → "lupin"
       - planning-is-prompting → "plan"
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
import uuid
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
from cosa.utils.notification_utils import format_questions_for_tts, convert_questions_for_api


def _normalize_abstract( abstract: Optional[ str ] ) -> Optional[ str ]:
    """
    Convert literal \\n to actual newlines in abstract text.

    Requires:
        - abstract is None or a string

    Ensures:
        - returns None if input is None
        - returns string with literal \\n converted to newlines
    """
    if abstract is None:
        return None
    return abstract.replace( '\\n', '\n' )


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

__version__ = "0.2.1"

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

    Known project patterns (checked in order):
        - cosa → "cosa" (checked first - may be submodule of lupin)
        - lupin → "lupin"
        - planning-is-prompting → "plan"
    """
    try:
        cwd = os.getcwd().lower()

        # CoSA detection (check FIRST - may be submodule of lupin)
        if "/cosa" in cwd:
            return "cosa"

        # Lupin project detection (only if not in cosa subdirectory)
        if "/lupin" in cwd:
            return "lupin"

        # Planning-is-Prompting project detection
        if "planning-is-prompting" in cwd:
            return "plan"

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


def _get_sender_id( project: str, session_id: str = None ) -> str:
    """
    Generate sender_id with optional session identifier.

    Requires:
        - project is a lowercase string
        - session_id is an 8-char hex string or None

    Ensures:
        - Returns claude.code@{project}.deepily.ai#{session_id} if session_id provided
        - Returns claude.code@{project}.deepily.ai if session_id is None (backward compatible)

    Examples:
        _get_sender_id( "lupin" ) -> "claude.code@lupin.deepily.ai"
        _get_sender_id( "lupin", "a1b2c3d4" ) -> "claude.code@lupin.deepily.ai#a1b2c3d4"
    """
    base = f"claude.code@{project}.deepily.ai"
    if session_id:
        return f"{base}#{session_id}"
    return base


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
SESSION_ID = uuid.uuid4().hex[:8]  # 8-char hex, e.g., "a1b2c3d4"
SENDER_ID  = _get_sender_id( PROJECT, SESSION_ID )
SERVER_URL = _get_server_url()

logger.info( f"Project: {PROJECT}" )
logger.info( f"Session ID: {SESSION_ID}" )
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
    title: Optional[ str ] = None,
    abstract: Optional[ str ] = None,
    job_id: Optional[ str ] = None
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
        abstract: Optional supplementary context (plan details, URLs, markdown)
        job_id: Optional agentic job ID for routing to job cards (e.g., "dr-a1b2c3d4")

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
            sender_id=SENDER_ID,
            abstract=_normalize_abstract( abstract ),
            job_id=job_id
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
    priority: str = "medium",
    abstract: Optional[ str ] = None,
    job_id: Optional[ str ] = None,
    suppress_ding: bool = False
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
        abstract: Optional supplementary context (plan details, URLs, markdown)
        job_id: Optional agentic job ID for routing to job cards (e.g., "dr-a1b2c3d4")
        suppress_ding: Suppress notification sound while still speaking via TTS (default False)

    Returns:
        Delivery status message

    Examples:
        notify("Starting code analysis...", notification_type="progress")
        notify("Build completed successfully", notification_type="task")
        notify("Warning: deprecated API detected", notification_type="alert", priority="high")
        notify("Task complete", suppress_ding=True)  # TTS only, no ding
    """
    logger.debug( f"notify() called: {message[:50]}..." )

    try:
        request = AsyncNotificationRequest(
            message=message,
            notification_type=NotificationType( notification_type ),
            priority=NotificationPriority( priority ),
            sender_id=SENDER_ID,
            abstract=_normalize_abstract( abstract ),
            job_id=job_id,
            suppress_ding=suppress_ding
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
    timeout_seconds: int = 60,
    priority: str = "medium",
    abstract: Optional[ str ] = None,
    job_id: Optional[ str ] = None
) -> str:
    """
    Ask a yes/no question and get the user's response as a string.

    Convenience wrapper for quick binary decisions. The user may optionally
    attach a qualifying comment to their answer via the UI.

    Requires:
        - question is a non-empty string
        - default is "yes" or "no"
        - timeout_seconds is a positive integer

    Ensures:
        - returns "yes", "no", "yes [comment: ...]", or "no [comment: ...]"
        - returns the default value (as string) on timeout or error

    Args:
        question: The yes/no question to ask
        default: Default answer if timeout ("yes" or "no")
        timeout_seconds: How long to wait (default 60)
        priority: "low", "medium", "high", or "urgent"
        abstract: Optional supplementary context (plan details, URLs, markdown)
        job_id: Optional agentic job ID for routing to job cards (e.g., "dr-a1b2c3d4")

    Returns:
        Annotated string: "yes", "no", "yes [comment: ...]", or "no [comment: ...]"

    Examples:
        response = ask_yes_no("Delete the old backups?")
        # response == "yes" or "no" or "yes [comment: only the March ones]"
    """
    logger.debug( f"ask_yes_no() called: {question[:50]}..." )

    try:
        request = NotificationRequest(
            message=question,
            response_type=ResponseType.YES_NO,
            notification_type=NotificationType.CUSTOM,
            priority=NotificationPriority( priority ),
            timeout_seconds=timeout_seconds,
            response_default=default,
            sender_id=SENDER_ID,
            abstract=_normalize_abstract( abstract ),
            job_id=job_id
        )
    except ( ValidationError, ValueError ):
        return default

    response: NotificationResponse = notify_user_sync( request=request, debug=False )

    if response.exit_code == 0 and response.response_value:
        return response.response_value.strip()

    return default


@mcp.tool
def ask_multiple_choice(
    questions: list,
    timeout_seconds: int = 120,
    priority: str = "medium",
    title: Optional[ str ] = None,
    abstract: Optional[ str ] = None,
    job_id: Optional[ str ] = None
) -> dict:
    """
    Ask multiple-choice questions and get user's selection(s).

    Presents questions with options via TTS and UI. Supports both single-select
    (radio buttons) and multi-select (checkboxes) questions. Users can select
    from predefined options or provide custom "Other" answers.

    Args:
        questions: List of question objects matching Claude Code's AskUserQuestion format:
            [
                {
                    "question": "Which auth method?",
                    "header": "Auth method",
                    "multiSelect": false,
                    "options": [
                        {"label": "OAuth", "description": "Use OAuth2 flow"},
                        {"label": "JWT", "description": "Use JWT tokens"}
                    ]
                }
            ]
        timeout_seconds: How long to wait for response (1-600, default 120)
        priority: "low", "medium", "high", or "urgent"
        title: Optional short title for the notification
        abstract: Optional supplementary context (plan details, URLs, markdown)
        job_id: Optional agentic job ID for routing to job cards (e.g., "dr-a1b2c3d4")

    Returns:
        dict with answers keyed by header:
        {
            "answers": {
                "Auth method": "OAuth",
                "Features": ["Dark mode", "Notifications"]
            }
        }

    Examples:
        # Single question, single select
        result = ask_multiple_choice([{
            "question": "Which database should we use?",
            "header": "Database",
            "multiSelect": False,
            "options": [
                {"label": "PostgreSQL", "description": "Relational database"},
                {"label": "MongoDB", "description": "Document database"}
            ]
        }])
        # Returns: {"answers": {"Database": "PostgreSQL"}}

        # Multiple questions
        result = ask_multiple_choice([
            {"question": "Which framework?", "header": "Framework", "multiSelect": False,
             "options": [{"label": "FastAPI"}, {"label": "Flask"}]},
            {"question": "Which features?", "header": "Features", "multiSelect": True,
             "options": [{"label": "Auth"}, {"label": "Caching"}]}
        ])
    """
    logger.debug( f"ask_multiple_choice() called with {len( questions )} questions" )

    if not questions or not isinstance( questions, list ):
        return { "error": "questions must be a non-empty list" }

    # Build TTS-friendly message from questions
    tts_message = format_questions_for_tts( questions )

    # Convert questions to response_options format (camelCase -> snake_case)
    response_options = convert_questions_for_api( questions )

    try:
        request = NotificationRequest(
            message=tts_message,
            response_type=ResponseType.MULTIPLE_CHOICE,
            notification_type=NotificationType.CUSTOM,
            priority=NotificationPriority( priority ),
            timeout_seconds=timeout_seconds,
            title=title,
            sender_id=SENDER_ID,
            response_options=response_options,
            abstract=_normalize_abstract( abstract ),
            job_id=job_id
        )
    except ( ValidationError, ValueError ) as e:
        logger.error( f"Validation error: {e}" )
        return { "error": f"validation error: {e}" }

    response: NotificationResponse = notify_user_sync( request=request, debug=False )

    if response.exit_code == 0:
        return _parse_multiple_choice_response( response.response_value )
    elif response.exit_code == 2:
        return { "error": "timeout - no response received", "timeout": True }
    else:
        return { "error": f"error: {response.status}" }


def _parse_multiple_choice_response( response_value: Optional[ str ] ) -> dict:
    """
    Parse the response from multiple choice notification.

    Expects JSON string like: {"answers": {"Header": "value"}}

    Requires:
        - response_value is None or a JSON string

    Ensures:
        - Returns parsed dict if valid JSON
        - Returns error dict if parsing fails

    Args:
        response_value: JSON string from notification response

    Returns:
        dict: Parsed answers or error
    """
    if not response_value:
        return { "answers": {} }

    try:
        import json
        parsed = json.loads( response_value )
        return parsed if isinstance( parsed, dict ) else { "answers": parsed }
    except ( json.JSONDecodeError, TypeError ) as e:
        logger.warning( f"Could not parse multiple choice response: {e}" )
        # Return raw value wrapped in answers
        return { "answers": { "response": response_value } }


@mcp.tool
def get_session_info() -> dict:
    """
    Get current session identification and server info.

    Returns:
        dict with project name, session_id, sender_id, server_url, and version
    """
    return {
        "project"    : PROJECT,
        "session_id" : SESSION_ID,
        "sender_id"  : SENDER_ID,
        "server_url" : SERVER_URL,
        "version"    : __version__
    }


if __name__ == "__main__":
    mcp.run()
