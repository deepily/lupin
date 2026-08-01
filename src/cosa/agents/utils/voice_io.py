#!/usr/bin/env python3
"""
Consolidated Voice-First I/O Layer for COSA Agents.

This module provides a unified interface for user interaction that:
1. PRIMARILY uses voice I/O via cosa_interface (TTS + voice input)
2. Automatically falls back to CLI text when voice is unavailable
3. Allows explicit --cli-mode override to force text interaction

The voice service availability is cached for the session duration
to avoid repeated connection attempts.

Usage:
    from cosa.agents.utils import voice_io

    # Configure with agent-specific cosa_interface
    from cosa.agents.deep_research import cosa_interface
    voice_io.configure( cosa_interface )

    # Or use CLI mode
    voice_io.set_cli_mode( True )

    # Then use I/O functions
    await voice_io.notify( "Starting research..." )
    approved = await voice_io.ask_yes_no( "Proceed?" )

Priority Order:
    1. Voice I/O (cosa_interface functions) - PRIMARY
    2. CLI fallback (print/input) - when voice unavailable
    3. --cli-mode flag - forces CLI regardless of voice availability

Features (consolidated from deep_research and podcast_generator):
    - notify() with job_id support for job card routing
    - ask_yes_no() for binary yes/no questions
    - get_input() for open-ended text input
    - choose() for simple multiple-choice (returns label string)
    - present_choices() for complex multiple-choice (returns dict)
    - select_themes() and select_topics() for progressive narrowing
"""

import asyncio
import logging
import sys
from typing import Optional, List, Union

logger = logging.getLogger( __name__ )


# =============================================================================
# Module State
# =============================================================================

_force_cli_mode  : bool            = False
_voice_available : Optional[ bool ] = None  # None = not checked, True/False = cached
_cosa_interface  : Optional[ object ] = None  # Agent-specific cosa_interface module
_job_id          : Optional[ str ]   = None  # Agentic job ID for auto-injection into notify()


def _is_interactive() -> bool:
    """
    Check if stdin is attached to an interactive terminal.

    When running as a background queue job (Docker, daemon, etc.),
    stdin is not a TTY and calling input() would block indefinitely.

    Ensures:
        - Returns True only when stdin is a real terminal
        - Returns False for background/queue/Docker execution

    Returns:
        bool: True if input() is safe to call
    """
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except Exception:
        return False


# =============================================================================
# Configuration Functions
# =============================================================================

def configure( cosa_interface_module, job_id: str = None ) -> None:
    """
    Configure the voice_io module with an agent-specific cosa_interface.

    This must be called before using voice functions if you want voice I/O.
    If not configured, all functions will use CLI fallback.

    Requires:
        - cosa_interface_module has: notify_progress, ask_confirmation,
          get_feedback, present_choices functions

    Ensures:
        - Module is configured for voice I/O with the given interface
        - If job_id provided, auto-injection is enabled for notify()

    Args:
        cosa_interface_module: Agent's cosa_interface module (e.g.,
            cosa.agents.deep_research.cosa_interface)
        job_id: Optional agentic job ID for auto-injection into notify()
    """
    global _cosa_interface, _job_id, _voice_available
    _cosa_interface = cosa_interface_module
    if job_id is not None:
        _job_id = job_id
    # Reset voice availability cache — new cosa_interface may have different connectivity
    _voice_available = None
    logger.info( f"Voice I/O configured with: {cosa_interface_module.__name__}" )


def set_cli_mode( enabled: bool ) -> None:
    """
    Enable or disable forced CLI mode.

    When enabled, all interactions use CLI text (print/input)
    even if voice service is available.

    Requires:
        - enabled is a boolean

    Ensures:
        - Module state updated
        - Subsequent calls use appropriate mode

    Args:
        enabled: True to force CLI mode, False for voice-first
    """
    global _force_cli_mode
    _force_cli_mode = enabled
    if enabled:
        logger.info( "CLI mode enabled - voice I/O disabled" )


def reset_voice_check() -> None:
    """
    Reset the cached voice availability check.

    Call this if the voice service status may have changed
    and you want to re-check availability.

    Ensures:
        - Next call to is_voice_available() will re-check
    """
    global _voice_available
    _voice_available = None


def set_job_id( job_id: str ) -> None:
    """
    Set the active job_id for auto-injection into notify() calls.

    When set, all notify() calls that don't provide an explicit job_id
    will automatically use this value. This routes notifications to the
    correct job card in the frontend UI.

    Requires:
        - job_id is a non-empty string (e.g., "pg-a1b2c3d4")

    Ensures:
        - Subsequent notify() calls auto-inject this job_id

    Args:
        job_id: Agentic job ID (e.g., "dr-a1b2c3d4", "pg-a1b2c3d4")
    """
    global _job_id
    _job_id = job_id


def clear_job_id() -> None:
    """
    Clear the active job_id (call at job completion).

    Prevents leaking job_id to subsequent jobs that reuse
    the same voice_io module state.

    Ensures:
        - _job_id is reset to None
        - Subsequent notify() calls will not auto-inject job_id
    """
    global _job_id
    _job_id = None


async def is_voice_available() -> bool:
    """
    Check if voice service is available (result cached).

    Attempts a minimal notification to test the voice service.
    The result is cached for the session to avoid repeated checks.

    Ensures:
        - Returns True if voice service responds
        - Returns False if voice service unavailable/fails
        - Returns False if cosa_interface not configured
        - Result is cached for subsequent calls

    Returns:
        bool: True if voice service is available
    """
    global _voice_available

    # Return cached result if available
    if _voice_available is not None:
        return _voice_available

    # If cosa_interface not configured, voice is unavailable
    if _cosa_interface is None:
        _voice_available = False
        logger.warning( "Voice unavailable - cosa_interface not configured" )
        return _voice_available

    # Try to ping the voice service
    try:
        # Send a silent/minimal notification to test connectivity
        await _cosa_interface.notify_progress( message="Initializing...", priority="low", job_id=_job_id )
        _voice_available = True
        logger.info( "Voice service available - using voice-first mode" )

    except Exception as e:
        _voice_available = False
        logger.warning( f"Voice service unavailable ({e}) - falling back to CLI mode" )

    return _voice_available


def get_mode_description() -> str:
    """
    Get a human-readable description of the current I/O mode.

    Returns:
        str: Description of current mode
    """
    if _force_cli_mode:
        return "CLI mode (forced)"
    elif _cosa_interface is None:
        return "CLI mode (not configured)"
    elif _voice_available is True:
        return "Voice mode (primary)"
    elif _voice_available is False:
        return "CLI mode (voice unavailable)"
    else:
        return "Mode not yet determined"


def is_cli_mode() -> bool:
    """
    Check if CLI mode is currently active (forced or not configured).

    Returns:
        bool: True if CLI mode is active
    """
    return _force_cli_mode or _cosa_interface is None


# =============================================================================
# Voice-First I/O Functions
# =============================================================================

async def notify(
    message: str,
    priority: str = "medium",
    abstract: Optional[ str ] = None,
    session_name: Optional[ str ] = None,
    job_id: Optional[ str ] = None,
    queue_name: Optional[ str ] = None,
    progress_group_id: Optional[ str ] = None
) -> None:
    """
    Send a progress notification (voice-first).

    In voice mode: Plays TTS announcement
    In CLI mode: Prints to console

    Requires:
        - message is a non-empty string
        - priority is "low", "medium", "high", or "urgent"

    Ensures:
        - Message is communicated to user via appropriate channel
        - Never raises (logs warnings on failure)

    Args:
        message: The message to announce
        priority: Notification priority level
        abstract: Optional supplementary context (markdown, URLs, details)
        session_name: Optional human-readable session name for UI display
        job_id: Optional agentic job ID for routing to job cards (e.g., "dr-a1b2c3d4")
        queue_name: Optional queue where job is running (run/todo/done) for provisional job card registration
    """
    # Auto-inject module-level job_id if caller didn't provide one
    if job_id is None and _job_id is not None:
        job_id = _job_id

    # If no cosa_interface is configured (pure CLI tools, tests), print only.
    # Voice availability (can user hear TTS?) is NOT a gate for persistence —
    # the UI's notification history + WebSocket fanout should always receive
    # the event so users can observe agent progress, with or without TTS.
    # Prior behavior cached is_voice_available() from a probe call; if that
    # probe threw on a test-env misconfiguration, every subsequent notify
    # silently degraded to print-only with no DB persistence.
    if _force_cli_mode or _cosa_interface is None:
        print( f"  {message}" )
        if abstract:
            print( f"\n  Context:\n{abstract}\n" )
        return

    # Always dispatch through cosa_interface — this persists to the
    # PostgreSQL notifications table AND fans out to the UI WebSocket
    # (including any subscribed voice bridge). TTS availability is
    # determined per-subscriber, not globally by the agent.
    try:
        await _cosa_interface.notify_progress(
            message=message, priority=priority, abstract=abstract,
            session_name=session_name, job_id=job_id, queue_name=queue_name,
            progress_group_id=progress_group_id
        )
    except Exception as e:
        logger.warning( f"Notification dispatch failed: {e}" )
        print( f"  {message}" )  # Fallback to print so progress is never invisible


async def ask_yes_no(
    question: str,
    default: str = "no",
    timeout: int = 60,
    abstract: Optional[ str ] = None,
    job_id: Optional[ str ] = None
) -> bool:
    """
    Ask a yes/no question (voice-first).

    In voice mode: Speaks question via TTS, waits for voice response
    In CLI mode: Prints question, waits for keyboard input

    Requires:
        - question is a non-empty string
        - default is "yes" or "no"
        - timeout is positive integer (1-600)

    Ensures:
        - Returns True if user said yes
        - Returns False if user said no
        - Returns default value on timeout or error

    Args:
        question: The yes/no question to ask
        default: Default answer if timeout ("yes" or "no")
        timeout: Seconds to wait for response
        abstract: Optional supplementary context (plan details, URLs, markdown)

    Returns:
        bool: True if user approved, False otherwise
    """
    # Auto-inject module-level job_id if caller didn't provide one
    if job_id is None and _job_id is not None:
        job_id = _job_id

    if _force_cli_mode or _cosa_interface is None or not await is_voice_available():
        # CLI fallback - show abstract if provided
        if abstract:
            print( f"\n  Context:\n{abstract}\n" )
        # Non-interactive (queue/Docker): use default without blocking on input()
        if not _is_interactive():
            logger.info( f"Non-interactive mode, using default='{default}' for: {question}" )
            print( f"  {question} → auto-default: {default}" )
            return default == "yes"
        default_hint = "Y/n" if default == "yes" else "y/N"
        response = input( f"  {question} [{default_hint}]: " ).strip().lower()
        if not response:
            return default == "yes"
        return response in [ "y", "yes", "yeah", "yep", "sure", "ok", "okay" ]

    try:
        return await _cosa_interface.ask_confirmation( question, default, timeout, abstract, job_id=job_id )
    except Exception as e:
        logger.warning( f"Voice ask_yes_no failed: {e}" )
        # Non-interactive fallback: use default
        if not _is_interactive():
            logger.info( f"Non-interactive mode, using default='{default}' for: {question}" )
            return default == "yes"
        # Interactive CLI fallback
        if abstract:
            print( f"\n  Context:\n{abstract}\n" )
        response = input( f"  {question} [y/N]: " ).strip().lower()
        return response in [ "y", "yes" ]


async def get_input(
    prompt: str,
    allow_empty: bool = True,
    timeout: int = 300,
    job_id: Optional[ str ] = None
) -> Optional[ str ]:
    """
    Get open-ended input from user (voice-first).

    In voice mode: Speaks prompt via TTS, captures voice response
    In CLI mode: Prints prompt, waits for keyboard input

    Requires:
        - prompt is a non-empty string
        - timeout is positive integer (1-600)

    Ensures:
        - Returns user's text response on success
        - Returns None on timeout, error, or empty (if not allowed)

    Args:
        prompt: The prompt to present to user
        allow_empty: If True, empty response returns empty string
        timeout: Seconds to wait for response

    Returns:
        str or None: User's response, or None on timeout/error
    """
    # Auto-inject module-level job_id if caller didn't provide one
    if job_id is None and _job_id is not None:
        job_id = _job_id

    if _force_cli_mode or _cosa_interface is None or not await is_voice_available():
        # Non-interactive (queue/Docker): return None without blocking on input()
        if not _is_interactive():
            logger.info( f"Non-interactive mode, returning None for get_input: {prompt[ :60 ]}" )
            return None
        # CLI fallback
        response = input( f"  {prompt}: " ).strip()
        if not response and not allow_empty:
            return None
        return response

    try:
        response = await _cosa_interface.get_feedback( prompt, timeout, job_id=job_id )
        if not response and not allow_empty:
            return None
        return response
    except Exception as e:
        logger.warning( f"Voice get_input failed: {e}" )
        # Non-interactive fallback: return None
        if not _is_interactive():
            logger.info( f"Non-interactive mode, returning None for get_input: {prompt[ :60 ]}" )
            return None
        # Interactive CLI fallback
        response = input( f"  {prompt}: " ).strip()
        return response if response or allow_empty else None


async def choose(
    question: str,
    options: Union[ List[ str ], List[ dict ] ],
    timeout: int = 120,
    allow_custom: bool = False,
    job_id: Optional[ str ] = None
) -> str:
    """
    Present multiple-choice options (voice-first).

    In voice mode: Speaks options via TTS, captures voice selection
    In CLI mode: Prints numbered options, waits for number input

    Options can be provided in two formats:
    - List of strings: ["Option 1", "Option 2"]
    - List of dicts: [{"label": "...", "description": "..."}]

    Requires:
        - question is a non-empty string
        - options is a non-empty list of strings or dicts
        - timeout is positive integer (1-600)

    Ensures:
        - Returns one of the provided option labels (or custom input if allowed)
        - Returns first option as default on timeout/error

    Args:
        question: The question introducing the choices
        options: List of option strings or dicts with label/description
        timeout: Seconds to wait for response
        allow_custom: If True, user can provide custom input via "Other"

    Returns:
        str: The selected option label (or custom input)
    """
    # Auto-inject module-level job_id if caller didn't provide one
    if job_id is None and _job_id is not None:
        job_id = _job_id

    if not options:
        raise ValueError( "Options list cannot be empty" )

    # Normalize options to dict format for consistent handling
    normalized_options = []
    for opt in options:
        if isinstance( opt, str ):
            normalized_options.append( { "label": opt, "description": "" } )
        elif isinstance( opt, dict ):
            normalized_options.append( {
                "label"       : opt.get( "label", str( opt ) ),
                "description" : opt.get( "description", "" )
            } )
        else:
            normalized_options.append( { "label": str( opt ), "description": "" } )

    # Extract labels for return values
    labels = [ opt[ "label" ] for opt in normalized_options ]

    if _force_cli_mode or _cosa_interface is None or not await is_voice_available():
        # Non-interactive (queue/Docker): use first option as default without blocking
        if not _is_interactive():
            logger.info( f"Non-interactive mode, using default '{labels[ 0 ]}' for: {question[ :60 ]}" )
            return labels[ 0 ]
        # CLI fallback - numbered menu with descriptions
        print( f"\n  {question}" )
        for i, opt in enumerate( normalized_options, 1 ):
            if opt[ "description" ]:
                print( f"    {i}. {opt[ 'label' ]} - {opt[ 'description' ]}" )
            else:
                print( f"    {i}. {opt[ 'label' ]}" )

        if allow_custom:
            print( f"    {len( normalized_options ) + 1}. Other (type your own)" )

        response = input( "  Enter number: " ).strip()
        try:
            idx = int( response ) - 1
            if 0 <= idx < len( labels ):
                return labels[ idx ]
            elif allow_custom and idx == len( labels ):
                custom = input( "  Enter your choice: " ).strip()
                return custom if custom else labels[ 0 ]
        except ValueError:
            pass

        print( f"  Invalid selection, using default: {labels[ 0 ]}" )
        return labels[ 0 ]

    try:
        # Build question format for cosa_interface
        questions = [ {
            "question"    : question,
            "header"      : "Choice",
            "multiSelect" : False,
            "options"     : normalized_options
        } ]

        result = await _cosa_interface.present_choices( questions, timeout, job_id=job_id )
        selection = result.get( "answers", {} ).get( "Choice" )

        # Handle custom "Other" response
        if selection and selection not in labels:
            return selection

        if selection and selection in labels:
            return selection

        return labels[ 0 ]  # Default

    except Exception as e:
        logger.warning( f"Voice choose failed: {e}" )
        return labels[ 0 ]


class VoiceGateNoDefaultError( RuntimeError ):
    """
    Raised when a choice gate cannot reach a human and the caller named no
    explicit default.

    Position in an options list is not consent. Before 2026-08-01 every
    unreachable-human path here answered `options[0]["label"]` and returned
    it in a payload identical to a real selection, so a podcast script
    review gate offering [Approve, Revise, Cancel] "approved" itself while
    the user was offline (row be8830a3). A gate with nothing to fall back
    on now fails loudly instead of guessing.

    Attributes:
        reason:  which unreachable path fired (see _DEFAULT_SOURCES)
        headers: the question headers that had no answer
    """

    def __init__( self, reason: str, headers: list ):
        self.reason  = reason
        self.headers = headers
        super().__init__(
            f"voice gate unreachable ({reason}) and no response_default was given "
            f"for {headers} — refusing to answer on the user's behalf"
        )


# Provenance markers for the `default_source` field. A caller that wants to
# treat some of these differently (e.g. accept a CLI blank-entry default but
# not a transport failure) can branch on the exact value.
_DEFAULT_SOURCE_NON_INTERACTIVE = "non_interactive"   # no tty, queue/Docker
_DEFAULT_SOURCE_CLI_BLANK       = "cli_blank_entry"   # prompt shown, user hit enter
_DEFAULT_SOURCE_CLI_BAD_INDEX   = "cli_bad_index"     # number outside the option range
_DEFAULT_SOURCE_DISPATCH_FAILED = "dispatch_failed"   # voice call raised (503, timeout…)


def _resolve_default( questions: list, response_default: Optional[ dict ], source: str ) -> dict:
    """
    Build the answer payload for a path where no human answered.

    Requires:
        - questions is a list of question objects
        - response_default is None, or a dict keyed by question header

    Ensures:
        - returns a payload carrying default_used=True and default_source
        - the payload is NOT shape-identical to a genuine selection

    Raises:
        - VoiceGateNoDefaultError if response_default does not cover every
          header, because a partial default is still a guess
    """
    missing = [
        q.get( "header", "Choice" ) for q in questions
        if not response_default or q.get( "header", "Choice" ) not in response_default
    ]
    if missing:
        raise VoiceGateNoDefaultError( reason=source, headers=missing )

    answers = { q.get( "header", "Choice" ): response_default[ q.get( "header", "Choice" ) ] for q in questions }
    logger.info( f"present_choices default used (source={source}): {answers}" )
    return {
        "answers"        : answers,
        "default_used"   : True,
        "answered"       : False,
        "default_source" : source,
    }


async def present_choices(
    questions: list,
    timeout: int = 120,
    title: Optional[ str ] = None,
    abstract: Optional[ str ] = None,
    job_id: Optional[ str ] = None,
    response_default: Optional[ dict ] = None
) -> dict:
    """
    Present multiple-choice questions (voice-first).

    In voice mode: Uses TTS and voice UI
    In CLI mode: Prints numbered options, waits for number input

    This function supports the full question format with headers and
    multi-select capability. For simpler use cases, see choose().

    Every path that cannot obtain a human answer either applies the
    caller's explicit `response_default` — flagged as such in the return —
    or raises. None of them invent an answer from option ordering.

    Requires:
        - questions is a list of question objects
        - Each question has: question, header, multiSelect, options
        - response_default, if given, has a key per question header

    Ensures:
        - a genuine selection returns {"answers": {...}, "default_used": False,
          "answered": True}
        - an unanswered gate returns default_used=True, answered=False and a
          default_source naming the path — deliberately NOT the same shape as
          a real answer, so callers can distinguish consent from silence
        - option order never decides the outcome

    Args:
        questions: List of question objects with options
        timeout: Seconds to wait for response
        title: Optional title for the notification
        abstract: Optional supplementary context
        job_id: Optional job ID for routing to job cards
        response_default: Explicit per-header fallback, keyed by question
            header. Required for any gate expected to run unattended.

    Returns:
        dict: {"answers": {...}, "default_used": bool, "answered": bool}
              plus "default_source" when default_used is True

    Raises:
        - VoiceGateNoDefaultError when no human can answer and no
          response_default covers the questions
    """
    # Auto-inject module-level job_id if caller didn't provide one
    if job_id is None and _job_id is not None:
        job_id = _job_id

    if _force_cli_mode or _cosa_interface is None or not await is_voice_available():
        # Non-interactive (queue/Docker): nobody can answer. Use the caller's
        # declared default or fail — never option[0].
        if not _is_interactive():
            return _resolve_default( questions, response_default, _DEFAULT_SOURCE_NON_INTERACTIVE )

        # CLI fallback - numbered menu
        if abstract:
            print( f"\n{abstract}" )

        answers = {}
        for q in questions:
            question_text = q.get( "question", "Choose an option:" )
            header = q.get( "header", "Choice" )
            options = q.get( "options", [] )
            multi_select = q.get( "multiSelect", False )

            print( f"\n  {question_text}" )
            for i, opt in enumerate( options, 1 ):
                label = opt.get( "label", f"Option {i}" )
                desc = opt.get( "description", "" )
                if desc:
                    print( f"    {i}. {label} - {desc}" )
                else:
                    print( f"    {i}. {label}" )

            # A blank entry or an out-of-range number is NOT a selection. Both
            # defer to the caller's declared default (or raise) rather than
            # silently landing on whichever option happens to be listed first.
            if multi_select:
                response = input( "  Enter numbers (comma-separated) or text for 'Other': " ).strip()
                if not response:
                    return _resolve_default( questions, response_default, _DEFAULT_SOURCE_CLI_BLANK )
                try:
                    indices  = [ int( x.strip() ) - 1 for x in response.split( "," ) ]
                    selected = [ options[ i ][ "label" ] for i in indices if 0 <= i < len( options ) ]
                    if not selected:
                        return _resolve_default( questions, response_default, _DEFAULT_SOURCE_CLI_BAD_INDEX )
                    answers[ header ] = selected
                except ValueError:
                    # User typed custom text — that IS their answer
                    answers[ header ] = [ response ]
            else:
                response = input( "  Enter number (or text for 'Other'): " ).strip()
                if not response:
                    return _resolve_default( questions, response_default, _DEFAULT_SOURCE_CLI_BLANK )
                try:
                    idx = int( response ) - 1
                    if 0 <= idx < len( options ):
                        answers[ header ] = options[ idx ][ "label" ]
                    else:
                        return _resolve_default( questions, response_default, _DEFAULT_SOURCE_CLI_BAD_INDEX )
                except ValueError:
                    # User typed custom text — that IS their answer
                    answers[ header ] = response

        return { "answers": answers, "default_used": False, "answered": True }

    try:
        result = await _cosa_interface.present_choices(
            questions=questions, timeout=timeout, title=title, abstract=abstract, job_id=job_id
        )
    except Exception as e:
        # The dispatcher raises deliberately here (VoiceGateTimeoutError on a
        # 503 "user is offline", transport errors, pre-MCP validation failures)
        # precisely so a caller can stall and checkpoint. Swallowing it into
        # options[0] defeated that one layer up — row be8830a3.
        logger.warning( f"Voice present_choices failed: {e}" )
        return _resolve_default( questions, response_default, _DEFAULT_SOURCE_DISPATCH_FAILED )

    # A real answer came back. Stamp provenance so callers never have to infer
    # it from the payload's shape.
    if isinstance( result, dict ):
        result.setdefault( "default_used", False )
        result.setdefault( "answered", True )
    return result


# =============================================================================
# Progressive Narrowing Functions (Theme/Topic Selection)
# =============================================================================

async def select_themes(
    themes: list,
    timeout: int = 180
) -> list:
    """
    Present themes for multi-select and return selected theme indices.

    Requires:
        - themes is a list of {"name": str, "description": str, "subquery_indices": list}
        - At least 2 themes provided

    Ensures:
        - Returns list of selected theme indices (0-based)
        - Returns empty list if user cancels

    Args:
        themes: List of theme dicts from clustering response
        timeout: Seconds to wait for response

    Returns:
        list[int]: Selected theme indices (0-based)
    """
    if _force_cli_mode or _cosa_interface is None or not await is_voice_available():
        # Non-interactive (queue/Docker): select all themes without blocking
        if not _is_interactive():
            logger.info( f"Non-interactive mode, selecting all {len( themes )} themes" )
            return list( range( len( themes ) ) )
        # CLI fallback
        print( "\n  Select research themes (comma-separated numbers, or 'all'):" )
        for i, theme in enumerate( themes, 1 ):
            topic_count = len( theme.get( "subquery_indices", [] ) )
            print( f"    {i}. {theme[ 'name' ]} ({topic_count} topics)" )
            print( f"       {theme.get( 'description', '' )}" )

        response = input( "  Your selection: " ).strip().lower()
        if response == "all":
            return list( range( len( themes ) ) )

        try:
            indices = [ int( x.strip() ) - 1 for x in response.split( "," ) ]
            return [ i for i in indices if 0 <= i < len( themes ) ]
        except ValueError:
            return []

    # Voice mode - use present_choices with multiSelect
    questions = [ {
        "question"    : "Which research themes interest you? Select all that apply.",
        "header"      : "Themes",
        "multiSelect" : True,
        "options"     : [
            {
                "label"       : theme[ "name" ],
                "description" : f"{len( theme.get( 'subquery_indices', [] ) )} topics: {theme.get( 'description', '' )}"
            }
            for theme in themes
        ]
    } ]

    try:
        result = await _cosa_interface.present_choices( questions, timeout )
        selected_names = result.get( "answers", {} ).get( "Themes", [] )

        # Handle single selection (string) vs multi (list)
        if isinstance( selected_names, str ):
            selected_names = [ selected_names ]

        # Map names back to indices
        return [
            i for i, theme in enumerate( themes )
            if theme[ "name" ] in selected_names
        ]

    except Exception as e:
        error_msg = str( e )
        logger.warning( f"Voice select_themes failed: {error_msg}" )

        # Notify the user about the failure
        await notify(
            f"Theme selection failed: {error_msg[:100]}. Please try again or use CLI mode.",
            priority="urgent"
        )

        # Re-raise so the caller knows this was an error, not a user cancellation
        raise RuntimeError( f"Theme selection failed: {error_msg}" ) from e


async def select_topics(
    topics: list,
    preselected: bool = True,
    timeout: int = 180
) -> list:
    """
    Present specific topics for refinement.

    Requires:
        - topics is a list of {"topic": str, "objective": str}

    Ensures:
        - Returns list of selected topic indices
        - Returns empty list if user cancels

    Args:
        topics: List of topic dicts (subqueries)
        preselected: Whether topics should be pre-selected (for deselection flow)
        timeout: Seconds to wait for response

    Returns:
        list[int]: Selected topic indices (0-based)
    """
    if _force_cli_mode or _cosa_interface is None or not await is_voice_available():
        # Non-interactive (queue/Docker): select all topics without blocking
        if not _is_interactive():
            logger.info( f"Non-interactive mode, selecting all {len( topics )} topics" )
            return list( range( len( topics ) ) )
        # CLI fallback
        print( "\n  Refine topic selection (comma-separated numbers, 'all', or 'none'):" )
        for i, topic in enumerate( topics, 1 ):
            print( f"    {i}. {topic.get( 'topic', 'Unknown' )}" )

        response = input( "  Your selection: " ).strip().lower()
        if response == "all":
            return list( range( len( topics ) ) )
        if response == "none":
            return []

        try:
            indices = [ int( x.strip() ) - 1 for x in response.split( "," ) ]
            return [ i for i in indices if 0 <= i < len( topics ) ]
        except ValueError:
            return list( range( len( topics ) ) )  # Default to all on error

    # Voice mode
    questions = [ {
        "question"    : "Which specific topics should I research? Deselect any you want to skip.",
        "header"      : "Topics",
        "multiSelect" : True,
        "options"     : [
            {
                "label"       : topic.get( "topic", "Unknown" )[ :50 ],
                "description" : topic.get( "objective", "" )[ :80 ]
            }
            for topic in topics
        ]
    } ]

    try:
        result = await _cosa_interface.present_choices( questions, timeout )
        selected = result.get( "answers", {} ).get( "Topics", [] )

        if isinstance( selected, str ):
            selected = [ selected ]

        # Map back to indices
        topic_names = [ t.get( "topic", "" )[ :50 ] for t in topics ]
        return [ i for i, name in enumerate( topic_names ) if name in selected ]

    except Exception as e:
        error_msg = str( e )
        logger.warning( f"Voice select_topics failed: {error_msg}" )

        # Notify the user about the failure
        await notify(
            f"Topic selection failed: {error_msg[:100]}. Please try again or use CLI mode.",
            priority="urgent"
        )

        # Re-raise so the caller knows this was an error, not a user cancellation
        raise RuntimeError( f"Topic selection failed: {error_msg}" ) from e


# =============================================================================
# Smoke Test
# =============================================================================

def quick_smoke_test():
    """Quick smoke test for consolidated voice_io module."""
    import cosa.utils.util as cu

    cu.print_banner( "Consolidated Voice I/O Smoke Test", prepend_nl=True )

    try:
        # Test 1: Module state functions
        print( "Testing module state functions..." )
        assert _force_cli_mode is False
        set_cli_mode( True )
        assert _force_cli_mode is True
        set_cli_mode( False )
        assert _force_cli_mode is False
        print( "✓ set_cli_mode works correctly" )

        # Test 2: reset_voice_check
        print( "Testing reset_voice_check..." )
        global _voice_available
        _voice_available = True
        reset_voice_check()
        assert _voice_available is None
        print( "✓ reset_voice_check works correctly" )

        # Test 3: get_mode_description
        print( "Testing get_mode_description..." )
        _voice_available = None
        desc = get_mode_description()
        assert "not configured" in desc.lower() or "not yet determined" in desc.lower()

        set_cli_mode( True )
        desc = get_mode_description()
        assert "forced" in desc.lower()
        set_cli_mode( False )
        print( "✓ get_mode_description works correctly" )

        # Test 4: is_cli_mode
        print( "Testing is_cli_mode..." )
        assert is_cli_mode() is True  # Not configured, so CLI mode
        set_cli_mode( True )
        assert is_cli_mode() is True
        set_cli_mode( False )
        print( "✓ is_cli_mode works correctly" )

        # Test 5: Async function signatures
        print( "Testing async function signatures..." )
        import inspect
        assert inspect.iscoroutinefunction( is_voice_available )
        assert inspect.iscoroutinefunction( notify )
        assert inspect.iscoroutinefunction( ask_yes_no )
        assert inspect.iscoroutinefunction( get_input )
        assert inspect.iscoroutinefunction( choose )
        assert inspect.iscoroutinefunction( present_choices )
        assert inspect.iscoroutinefunction( select_themes )
        assert inspect.iscoroutinefunction( select_topics )
        print( "✓ All async functions have correct signatures" )

        # Test 6: notify() has job_id parameter
        print( "Testing notify() has job_id parameter..." )
        sig = inspect.signature( notify )
        assert "job_id" in sig.parameters
        print( "✓ notify() supports job_id parameter" )

        # Test 7: choose() accepts both List[str] and List[dict]
        print( "Testing choose() option normalization..." )
        sig = inspect.signature( choose )
        params = list( sig.parameters.keys() )
        assert "options" in params
        assert "allow_custom" in params
        print( "✓ choose() accepts Union[List[str], List[dict]] and allow_custom param" )

        # Test 8: present_choices has title and abstract params
        print( "Testing present_choices() parameters..." )
        sig = inspect.signature( present_choices )
        assert "title" in sig.parameters
        assert "abstract" in sig.parameters
        print( "✓ present_choices() supports title and abstract parameters" )

        # Test 9: CLI mode fallback
        print( "Testing CLI mode fallback..." )
        set_cli_mode( True )

        async def test_cli_fallback():
            mode = get_mode_description()
            assert "forced" in mode.lower()

        asyncio.run( test_cli_fallback() )
        set_cli_mode( False )
        print( "✓ CLI mode fallback configured correctly" )

        # Reset state
        _voice_available = None

        print( "\n✓ Consolidated voice_io smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
