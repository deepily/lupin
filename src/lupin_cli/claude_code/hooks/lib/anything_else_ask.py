"""
Shared "Anything else?" ask helper.

Refactored out of `stop.py:_ask_anything_else()` so both the Stop-hook-time
caller (legacy immediate-ask fallback) and the deferred `idle_waiter.py`
helper can build and fire the same prompt without code duplication.

Returns a structured AnythingElseResult that each caller interprets:
    - Stop hook: builds the emit_json dict (block-stop on yes / qualifier-inject
      on no+comment / allow-stop on plain no/timeout)
    - idle_waiter: tmux-injects qualifier if present, exits on yes, schedules
      successor on no/timeout

Design: src/rnd/v0.1.7/2026.04.29-idle-aware-stop-hook/01-design.md §Components
"""

import subprocess
import sys
from dataclasses import dataclass
from typing import Optional, Tuple

# Lazy import — these can fail in test contexts without the venv
from lupin_cli.notifications.notify_user_sync import notify_user_sync
from lupin_cli.notifications.notification_models import (
    NotificationRequest, ResponseType, NotificationPriority
)
from cosa.utils.notification_utils import extract_qualifier_comment
from lupin_cli.claude_code.hooks.lib.session_bridge import (
    build_sender_id_for_cc, get_session_metadata
)


@dataclass
class AnythingElseResult:
    """
    Structured outcome of a single fire of the "Anything else?" ask.

    answer    : "yes" | "no" | "timeout" | "error"
                ("error" indicates a transport/parse failure; treat as no-op)
    qualifier : The "[comment: ...]" text if present, else None
    raw_value : Full server response_value (for logging / debugging)
    error     : Exception message on transport failure, else None
    """
    answer    : str
    qualifier : Optional[ str ]
    raw_value : str
    error     : Optional[ str ]


def summarize_task( last_assistant_message: Optional[ str ] ) -> Optional[ str ]:
    """
    Summarize the last assistant message using Gister (default mode).

    Requires:
        - last_assistant_message is a string or None

    Ensures:
        - Returns a concise gist string on success
        - Returns None on any failure or empty input

    Args:
        last_assistant_message: Claude's last response text

    Returns:
        str or None: Gist suitable for embedding in the "Anything else?" message
    """
    if not last_assistant_message or not last_assistant_message.strip():
        return None

    try:
        from cosa.memory.gister import Gister
        gister = Gister( debug=False, verbose=False )
        gist   = gister.get_gist( last_assistant_message, prompt_key="prompt template for stop hook gist" )
        return gist if gist else None
    except Exception:
        return None


def get_session_context( cwd: Optional[ str ] ) -> Tuple[ Optional[ str ], Optional[ str ] ]:
    """
    Read session topic from bridge file + git branch name.

    Requires:
        - cwd is a string path or None

    Ensures:
        - Returns (topic, branch) tuple
        - topic is a string or None (from bridge file's session_topic)
        - branch is a string or None (from git rev-parse)
        - Never raises exceptions

    Args:
        cwd: Working directory for `git rev-parse` resolution

    Returns:
        (topic, branch): Both Optional[str]
    """
    topic  = None
    branch = None

    # Session topic from bridge file
    try:
        meta  = get_session_metadata()
        topic = meta.get( "session_topic" )
    except Exception:
        pass

    # Git branch
    if cwd:
        try:
            branch = subprocess.check_output(
                [ "git", "rev-parse", "--abbrev-ref", "HEAD" ],
                cwd=cwd, text=True, timeout=5
            ).strip()
        except Exception:
            pass

    return topic, branch


def build_ask_request(
    session_id        : str,
    *,
    gist              : Optional[ str ]  = None,
    cwd               : Optional[ str ]  = None,
    timeout_seconds   : int              = 60,
) -> NotificationRequest:
    """
    Build the NotificationRequest for a single "Anything else?" ask.

    Caller may use this to inspect/mutate before passing to notify_user_sync,
    or to log the exact payload that will be sent.

    Requires:
        - session_id is a non-empty string
        - gist is a non-empty pre-computed gist or None (Stop hook computes
          via summarize_task; waiter reads from bridge state)
        - timeout_seconds is a positive int (1-600)

    Ensures:
        - Returns a NotificationRequest configured for ResponseType.YES_NO
        - Message embeds the gist if provided, else a generic finish message
        - Abstract embeds session topic + git branch when available

    Returns:
        NotificationRequest: Ready to pass to notify_user_sync
    """
    sender_id = build_sender_id_for_cc( session_id )

    if gist:
        message = f'I\'m finished *"...{gist}"*. Is there anything else you want me to do?'
    else:
        message = "I've finished the current task. Is there anything else you'd like me to do?"

    topic, branch = get_session_context( cwd )
    parts = [ ]
    if topic:
        parts.append( f"**Session**: {topic}" )
    if branch:
        parts.append( f"**Branch**: `{branch}`" )
    abstract = "  \n".join( parts ) if parts else None

    return NotificationRequest(
        message                  = message,
        response_type            = ResponseType.YES_NO,
        priority                 = NotificationPriority.MEDIUM,
        timeout_seconds          = timeout_seconds,
        response_default         = "no",
        title                    = "Stop hook: Anything else?",
        sender_id                = sender_id,
        abstract                 = abstract,
        display_qualifier_widget = True,
    )


def fire_anything_else_ask(
    session_id        : str,
    *,
    gist              : Optional[ str ]  = None,
    cwd               : Optional[ str ]  = None,
    timeout_seconds   : int              = 60,
) -> AnythingElseResult:
    """
    Fire one "Anything else?" prompt and return a structured result.

    The single source of truth for the ask: builds the NotificationRequest,
    invokes the blocking REST call via notify_user_sync, parses the response.
    Each caller (Stop hook or idle waiter) interprets the result for its own
    flow without duplicating any of the fire logic.

    Requires:
        - session_id is a non-empty string
        - gist is None or a non-empty pre-computed gist
        - cwd is None or a string path
        - timeout_seconds is a positive int (1-600)

    Ensures:
        - Returns AnythingElseResult with answer in {"yes", "no", "timeout", "error"}
        - On transport/parse failure: answer="error", error=str(exc)
        - Never raises — all exceptions handled internally

    Args:
        session_id     : CC session ID for sender_id resolution
        gist           : Pre-computed Gister gist (caller's responsibility)
        cwd            : Working dir for git-branch resolution
        timeout_seconds: Server-side response wait

    Returns:
        AnythingElseResult: Structured outcome
    """
    try:
        request  = build_ask_request(
            session_id      = session_id,
            gist            = gist,
            cwd             = cwd,
            timeout_seconds = timeout_seconds,
        )
        response = notify_user_sync( request )

        answer, qualifier = extract_qualifier_comment( response.response_value )

        # Normalize timeout / no-response into a stable answer string
        if answer not in ( "yes", "no" ):
            normalized = "timeout"
        else:
            normalized = answer

        return AnythingElseResult(
            answer    = normalized,
            qualifier = qualifier,
            raw_value = response.response_value or "",
            error     = None,
        )

    except Exception as e:
        # Server unreachable / parse failure / etc. Caller decides what to do
        # with this; typically: log and treat as no-op (no successor, no inject).
        # Per `feedback_no_defensive_programming`: don't add fallback chains
        # here — let the caller see the error and decide.
        print( f"[anything_else_ask] fire failed: {e}", file=sys.stderr )
        return AnythingElseResult(
            answer    = "error",
            qualifier = None,
            raw_value = "",
            error     = str( e ),
        )
