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
    - session_id is the first 8 chars of the Claude Code session UUID
    - Derived from the session bridge (env > file > fallback), shared with hooks
    - A background thread upgrades the ID once the SessionStart hook writes it

Project Detection (automatic — no MCP_PROJECT needed):
    1. Auto-detects from current working directory (checked in order):
       - cosa → "cosa" (checked first - may be submodule of lupin)
       - lupin → "lupin"
       - planning-is-prompting → "plan"
       - anything else → CWD basename (works in any repo)
    2. Falls back to MCP_PROJECT env var if cwd detection raises an exception
    3. Last resort: uses CWD basename with warning (never crashes)

Environment Variables:
    MCP_PROJECT: Optional override (auto-detection is preferred and sufficient)
    LUPIN_APP_SERVER_URL: Server URL (default: http://localhost:7999)
    MCP_DEBUG: Enable debug logging (optional)

Installation (global — one registration for all repos):
    install-cosa-voice.sh   # registers at user scope via claude mcp add --scope user
"""

if __name__ == "__main__":
    # 🔴 STDOUT IS THE JSON-RPC CHANNEL, SO IT IS RESERVED BEFORE ANYTHING CAN PRINT
    # (row e4dc53a9). A stray print with no newline once landed in front of an answer
    # frame and Claude Code dropped the frame: Rick's answer reached the server and
    # never reached the seat. Every print from here on goes to stderr. It runs ahead
    # of the imports below because they print too, and only here, never on import,
    # because it rewires fd 1 for the whole process.
    from lupin_mcp.jsonrpc_stdout import reserve_stdout_for_jsonrpc
    reserve_stdout_for_jsonrpc()

import anyio
import functools
import logging
import os
import re
import requests
import signal
import sys
import time
import threading
from pathlib import Path
from typing import List, Optional

from pydantic import ValidationError
from fastmcp import FastMCP

from lupin_mcp.persona_normalization import persona_slug
from lupin_mcp import validation_alert_throttle

# Import from lupin_cli.notifications (the notification library)
from lupin_cli.notifications.notification_models import (
    NotificationRequest,
    AsyncNotificationRequest,
    NotificationResponse,
    AsyncNotificationResponse,
    NotificationType,
    NotificationPriority,
    ResponseType
)
from lupin_cli.notifications.notify_user_sync import notify_user_sync
from lupin_cli.notifications.notify_user_async import notify_user_async

# The priorities speakerphone mode may LIFT to "high" — the RECOGNISED ones that are not
# already at or above it. Derived from the enum rather than written out, so a new member
# cannot silently fall outside the set. Anything NOT in here (including a typo) is left
# untouched so it reaches NotificationPriority(...) validation and gets reported.
_SPEAKERPHONE_LIFTABLE_PRIORITIES = frozenset(
    p.value for p in NotificationPriority if p.value not in ( "high", "urgent" )
)
from cosa.utils.notification_utils import (
    format_questions_for_tts,
    convert_questions_for_api,
    format_open_ended_batch_for_tts,
    convert_open_ended_batch_for_api,
    normalize_abstract as _normalize_abstract,
    extract_qualifier_comment,
    format_qualified_response,
    is_known_project
)
from cosa.agents.utils.sender_id import detect_project as _detect_project_shared
from lupin_cli.claude_code.hooks.lib.session_bridge import (
    get_claude_session_id, wait_for_session_id, get_session_metadata as _get_cc_metadata,
    get_claude_session_id_with_source, wait_for_session_id_with_source,
    SOURCE_CWD_FALLBACK, DEFINITIVE_SOURCES,
    clear_cached_session_id, _find_session_file, _read_session_file,
    get_speakerphone, set_speakerphone, atomic_write_json
)
from lupin_cli.claude_code.hooks.lib.hook_common import (
    log_to_stream,
    _brevity_rules,
    _routing_reminder,
    DM_STYLE_TAG,
)


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

__version__ = "0.3.0"

# ============================================================================
# Configuration
# ============================================================================

def _get_server_url() -> str:
    """Get Lupin server URL from environment."""
    return os.getenv( "LUPIN_APP_SERVER_URL", "http://localhost:7999" )


def _detect_project_from_cwd() -> Optional[ str ]:
    """Attempt to detect project name from current working directory.

    Delegates to the shared detect_project() utility from
    cosa.agents.utils.sender_id for consistent detection logic.

    Returns None only if detection fails entirely (exception).
    """
    try:
        return _detect_project_shared()
    except Exception as e:
        logger.debug( f"Could not detect project from cwd: {e}" )
        return None


_PROJECT_SOURCE    = "unknown"  # Set by _get_project(): "known" | "basename" | "env_var"
_ACCOUNT_VALIDATED = None       # Set by _validate_repo_account(): True | False | None (not yet checked)


def _get_project() -> str:
    """Get project name with dynamic detection — no silent fallback.

    Detection priority:
        1. Auto-detect from current working directory
        2. MCP_PROJECT environment variable
        3. RuntimeError + os._exit(1) — refuses to run as "unknown"

    Sets module-level _PROJECT_SOURCE to track how the project was resolved:
        - "known"    : auto-detected and in KNOWN_PROJECTS registry
        - "basename" : auto-detected as cwd basename (not in registry)
        - "env_var"  : from MCP_PROJECT environment variable

    Note: MCP_PROJECT can be set in MCP JSON config's env section as a default,
    but dynamic detection from cwd takes precedence for multi-project support.
    """
    global _PROJECT_SOURCE

    # Priority 1: Try dynamic detection from working directory
    detected = _detect_project_from_cwd()
    if detected:
        if is_known_project( detected ):
            _PROJECT_SOURCE = "known"
            logger.info( f"Project auto-detected (known): {detected}" )
        else:
            _PROJECT_SOURCE = "basename"
            logger.info( f"Project auto-detected (basename): {detected}" )
        return detected

    # Priority 2: Check environment variable
    project = os.getenv( "MCP_PROJECT", "" ).strip()
    if project:
        _PROJECT_SOURCE = "env_var"
        logger.info( f"Project from MCP_PROJECT env var: {project.lower()}" )
        return project.lower()

    # Priority 3: Last-resort fallback — use CWD basename with warning
    fallback = os.path.basename( os.getcwd() ).lower() or "unknown"
    _PROJECT_SOURCE = "basename"
    logger.warning( "=" * 60 )
    logger.warning( f"PROJECT DETECTION FALLBACK — using CWD basename: {fallback}" )
    logger.warning( "=" * 60 )
    logger.warning( f"Current working directory: {os.getcwd()}" )
    logger.warning( "Auto-detection raised an exception, and MCP_PROJECT env var not set." )
    logger.warning( f"Falling back to basename '{fallback}' — notifications may route incorrectly." )
    logger.warning( "=" * 60 )

    return fallback


def _resolve_canonical_project( detected: str ) -> str:
    """
    Resolve canonical project identifier from ~/.lupin/config.

    The cwd-detected project name (e.g., "ampe-to-meridian") may differ from
    the canonical identity used in the user's Lupin account email. For example,
    the user's config may map [ampe-to-meridian] -> claude.code@ampe2meridian.deepily.ai,
    and THAT canonical identifier ("ampe2meridian") is what should be used for
    sender_id construction — not the raw cwd basename.

    The config file is the source of truth: if a matching section exists and
    contains a parseable email, extract the identifier from between '@' and
    '.deepily.ai'. Otherwise, return the detected name unchanged.

    Requires:
        - detected is a non-empty string (project name from cwd detection)

    Ensures:
        - Returns canonical project identifier from ~/.lupin/config if mapped
        - Returns detected name unchanged if no config section or unparseable email
        - Never raises — all lookups are best-effort

    Args:
        detected: Project name detected from cwd

    Returns:
        str: Canonical project identifier for sender_id construction
    """
    try:
        from lupin_cli.claude_code.hooks.lib.hook_credentials import get_hook_credentials
        email, _ = get_hook_credentials( detected )
        # Parse: {agent}@{identifier}.deepily.ai -> identifier
        match = re.match( r"^[a-z]+(?:\.[a-z]+)+@([a-z][a-z0-9]*(?:-[a-z0-9]+)*)\.deepily\.ai$", email )
        if match:
            canonical = match.group( 1 )
            if canonical != detected:
                logger.info( f"Canonical project identity from config: {detected} -> {canonical}" )
            return canonical
        logger.warning( f"Config email for [{detected}] does not match expected format: {email}" )
    except ( FileNotFoundError, ValueError ) as e:
        logger.debug( f"No canonical project mapping for '{detected}' in ~/.lupin/config ({e.__class__.__name__})" )
    except Exception as e:
        logger.warning( f"Unexpected error resolving canonical project for '{detected}': {e}" )
    return detected


def _get_sender_id( project: str, session_id: str = None ) -> str:
    """
    Generate sender_id with optional session identifier.

    Delegates to the shared build_sender_id() utility. The caller is expected
    to pass the CANONICAL project identifier (from _resolve_canonical_project),
    not the raw cwd-detected name.

    Examples:
        _get_sender_id( "lupin" ) -> "claude.code@lupin.deepily.ai"
        _get_sender_id( "lupin", "a1b2c3d4" ) -> "claude.code@lupin.deepily.ai#a1b2c3d4"
    """
    from cosa.agents.utils.sender_id import build_sender_id
    return build_sender_id( "claude.code", project=project, suffix=session_id )


# ============================================================================
# Repo Account Validation
# ============================================================================

ERROR_SENDER_ID = "claude.code@errors.deepily.ai"


def _send_validation_error( detail: str, project: str ) -> None:
    """
    Send urgent notification about a validation failure, at most once per project per cooldown.

    Requires:
        - Lupin FastAPI server is running (for notification delivery)
        - project is the project name the failure belongs to

    Ensures:
        - Logs critical message regardless of notification success or suppression
        - Sends urgent-priority notification from ERROR_SENDER_ID unless this project already had
          one DELIVERED within `validation_alert_throttle.COOLDOWN_SECONDS`; a suppressed repeat
          logs a warning line instead of notifying
        - Records the send only after delivery succeeded, so an undelivered alert is retried by
          the next start; a missing or corrupt throttle file means send (fail open)
        - Never raises (all exceptions caught)
    """
    msg = f"COSA-VOICE MCP VALIDATION FAILED\n\n{detail}"
    logger.critical( msg )
    if validation_alert_throttle.is_suppressed( project ):
        logger.warning(
            f"MCP validation alert for project '{project}' not re-sent: one was already delivered "
            f"within the last {validation_alert_throttle.COOLDOWN_SECONDS // 3600}h"
        )
        return
    try:
        request = AsyncNotificationRequest(
            message           = msg,
            notification_type = NotificationType.TASK,
            priority          = NotificationPriority( "urgent" ),
            sender_id         = ERROR_SENDER_ID
        )
        response = notify_user_async( request=request, debug=False )
        if response.success:
            validation_alert_throttle.record_sent( project )
    except Exception as e:
        logger.warning( f"Could not send validation error notification: {e}" )


def _validate_repo_account( project: str ) -> None:
    """
    Validate that a Lupin service account exists for this project.

    Checks:
        1. Credentials exist in ~/.lupin/config for [project] section
        2. Login succeeds via POST /auth/login

    On failure, sends an urgent notification with setup instructions via
    the synthetic claude.code@errors.deepily.ai sender. Tools continue
    working in degraded mode — this does not crash the server.

    Requires:
        - SERVER_URL is set
        - project is a non-empty string

    Ensures:
        - On success: logs confirmation, returns normally
        - On failure: sends urgent notification, logs critical, returns normally
    """
    global _ACCOUNT_VALIDATED
    from lupin_cli.claude_code.hooks.lib.hook_credentials import get_hook_credentials

    expected_email = f"claude.code@{project}.deepily.ai"

    # Check 1: Credentials exist in config file
    try:
        email, password = get_hook_credentials( project )
    except ( FileNotFoundError, ValueError ) as e:
        _ACCOUNT_VALIDATED = False
        _send_validation_error(
            f"No credentials for project '{project}'.\n{e}\n\n"
            f"To fix:\n"
            f"1. Open the Admin UI: {SERVER_URL}/app/admin/users\n"
            f"2. Create a new user account with email: {expected_email}\n"
            f"3. Add credentials to ~/.lupin/config:\n"
            f"   [{project}]\n"
            f"   email = {expected_email}\n"
            f"   password = <the password you set in the admin UI>\n\n"
            f"Once the account exists, the CC Notification Listener can authenticate\n"
            f"via WebSocket and auto-start receiving hook events for this repo.",
            project
        )
        return

    # Check 2: Login works
    try:
        resp = requests.post(
            f"{SERVER_URL}/auth/login",
            json={ "email": email, "password": password },
            timeout=_SERVER_TRANSPORT_TIMEOUT_SECONDS
        )
        if resp.status_code != 200:
            _ACCOUNT_VALIDATED = False
            _send_validation_error(
                f"Login failed for {email} (HTTP {resp.status_code}).\n"
                f"Account may not exist or may be disabled.\n\n"
                f"To fix:\n"
                f"1. Open the Admin UI: {SERVER_URL}/app/admin/users\n"
                f"2. Verify or create the user account: {expected_email}\n"
                f"3. Check that the password in ~/.lupin/config [{project}] matches",
                project
            )
            return
    except ( requests.ConnectionError, requests.Timeout ) as e:
        # Catch BOTH ConnectionError (server down) AND Timeout (server up but
        # unresponsive). Without the Timeout case, a slow server propagates
        # `requests.ReadTimeout` out of module-import scope and breaks every
        # test that imports cosa_voice_mcp.
        _ACCOUNT_VALIDATED = False
        _send_validation_error(
            f"Cannot reach Lupin server at {SERVER_URL} ({type( e ).__name__}).\n"
            f"Ensure FastAPI is running: src/scripts/run-fastapi-lupin.sh",
            project
        )
        return
    except Exception as e:
        # Final fallback — never let validation explode at import time.
        _ACCOUNT_VALIDATED = False
        logger.warning( f"Repo account validation aborted: {type( e ).__name__}: {e}" )
        return

    _ACCOUNT_VALIDATED = True
    logger.info( f"Repo account validated: {email}" )


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

PROJECT           = _get_project()
CANONICAL_PROJECT = _resolve_canonical_project( PROJECT )  # Config-mapped identity for sender_id
_boot_session_id, SESSION_ID_SOURCE = get_claude_session_id_with_source()
SESSION_ID        = _boot_session_id[ :8 ]  # 8-char hex from session bridge (env > file > fallback)
# ⚠️ SESSION_ID_SOURCE TRAVELS WITH SESSION_ID AND MUST BE UPDATED WHEREVER IT IS.
# It is the whole of the fix: a `cwd_fallback` id is a live colleague's, adopted because
# we share a checkout with them, and nothing else on this box can tell that from a real
# match. Every reassignment of SESSION_ID below sets this in the same statement.
SENDER_ID         = _get_sender_id( CANONICAL_PROJECT, SESSION_ID )
SERVER_URL        = _get_server_url()

# Transport budget for out-of-process HTTP calls to SERVER_URL (row 204911ca,
# 2026-07-20). ~30s = 1.60x the observed maximum `:7999` reload window of 18.76s
# — a multiplier with explicit headroom, NOT a coverage guarantee.
#
# WHY THESE CALLS NEED IT. This MCP server runs in its OWN process, so a `:7999`
# reload does not tear it down alongside the request. `:7999` runs
# `uvicorn --reload`, and the reloader parent keeps the listening socket bound
# across a restart — the kernel ACCEPTS a request that nothing is there to
# answer, so the caller hangs and eventually raises TimeoutError rather than
# getting a fast ConnectionRefused. Measured over 8.4 days of container logs
# (current-config clean-reload class, n=143): min 6.59s, median 6.91s, max
# 18.76s. All 143 exceed the 5s these call sites used to allow, so every one of
# them failed on every reload it happened to land in.
#
# THE TRADE, stated plainly: a genuinely hung server now takes ~30s to report
# instead of ~5s. Accepted knowingly — these are low-frequency calls (login,
# speakerphone toggle, persona allocate) where a lost result is worse than a
# slow one. It is not free.
#
# ⚠️ Applies to READ budgets on out-of-process calls only. A split
# connect/read tuple is NOT exposed: connect SUCCEEDS during a reload (the
# kernel accepted), so only the read leg can hang.
_SERVER_TRANSPORT_TIMEOUT_SECONDS = 30

_session_ready    = threading.Event()   # Gate: blocks tool calls until session ID resolved
_session_failed   = False               # True if real ID never arrived (fallback only)

# POSITIVE SERVER DISCRIMINATOR — row 87ae7234.
# `_die_no_session_id` calls os._exit(1), which is correct for the MCP server and
# catastrophic for anything that merely IMPORTS this module: os._exit skips every
# flush, atexit hook and exception path, so an importing process dies with no
# traceback and no summary. Four call sites in this module can reach it.
#
# This flag decides which process we are, and it is set POSITIVELY at the single
# entry point (the `if __name__ == "__main__":` block at the bottom of this file)
# rather than inferred from an environment variable, from PYTEST_CURRENT_TEST, or
# from the ABSENCE of something. An inference stops matching silently when the
# world changes; a positive assignment at the entry point does not.
#
# It lives in that block because that is where this codebase ALREADY means "I am
# the server" — `_maybe_start_commons_archival_daemon()` is there for the same
# reason — so server-only state stays in one known place instead of inventing a
# second convention.
#
# WARNING: IF YOU ADD A NEW ENTRY POINT — a console_scripts / [project.scripts]
# shim that IMPORTS this module and calls into it rather than running the file —
# YOU MUST SET THIS FLAG THERE TOO. Otherwise a real server reads False and a
# genuine session-id failure raises instead of exiting, leaving a server up that
# cannot serve. There are none today: zero entry-points are declared, and every
# registered launch runs `python .../cosa_voice_mcp.py` in script mode.
_IS_MCP_SERVER    = False

# Validate repo service account (non-blocking — logs + notifies on failure)
_validate_repo_account( PROJECT )

# ── Startup banner (consolidated status to stderr) ──────────────────────
_account_status = "validated" if _ACCOUNT_VALIDATED else "FAILED" if _ACCOUNT_VALIDATED is False else "skipped"
_project_line   = f"  Project : {PROJECT} ({_PROJECT_SOURCE})" if PROJECT == CANONICAL_PROJECT else f"  Project : {PROJECT} ({_PROJECT_SOURCE}) -> {CANONICAL_PROJECT} (config)"
_banner_lines   = [
    "",
    "=" * 42,
    f"  cosa-voice MCP v{__version__} — Runtime",
    "=" * 42,
    _project_line,
    f"  Session : {SESSION_ID}",
    f"  Sender  : {SENDER_ID}",
    f"  Server  : {SERVER_URL}",
    f"  Account : {_account_status}",
    "=" * 42,
    "",
]
for _line in _banner_lines:
    logger.info( _line )


def _watch_bridge_for_changes( stop_event=None, poll_interval=2.0, max_iterations=None ):
    """
    Watch the resolved bridge file and update SESSION_ID / SENDER_ID when it changes.

    PHASE 2 of the session watcher, split out of `_session_watcher_thread` so a test
    can start it DELIBERATELY and assert on what it did — row `87ae7234`. Phase 1
    (the one-shot resolve that sets `_session_ready`) stays where it was and still
    runs at import: it is load-bearing, nothing here is.

    Requires:
        - phase 1 has run, so SESSION_ID / SENDER_ID hold their resolved values
        - poll_interval is a positive number of seconds

    Ensures:
        - returns when stop_event is set, or after max_iterations polls, or never
          (the server's case: both arguments omitted)
        - updates the SESSION_ID / SENDER_ID globals when the bridge file's session
          id changes, and logs the transition
        - a per-iteration exception is logged and the loop CONTINUES — one bad poll
          must never end the watch
        - does not raise
    """
    global SESSION_ID, SENDER_ID, SESSION_ID_SOURCE

    last_mtime      = 0.0
    last_session_id = SESSION_ID
    iterations      = 0

    logger.info( "Session watcher: entering persistent monitoring loop" )

    while stop_event is None or not stop_event.is_set():
        if max_iterations is not None and iterations >= max_iterations: return
        iterations += 1
        try:
            # A stop_event waits INTERRUPTIBLY so a test does not pay the poll
            # interval to shut the loop down; without one this is the original sleep.
            if stop_event is not None:
                if stop_event.wait( timeout=poll_interval ): return
            else:
                time.sleep( poll_interval )

            # Clear cache so _find_session_file() does a fresh lookup
            clear_cached_session_id()

            result = _find_session_file()
            if result is None:
                continue

            bridge_path, resolution_source = result

            # Check if file was modified
            try:
                current_mtime = bridge_path.stat().st_mtime
            except OSError:
                continue

            if current_mtime <= last_mtime:
                continue

            last_mtime = current_mtime

            # Re-read the session ID
            file_id = _read_session_file( bridge_path )
            if not file_id:
                continue

            new_suffix = file_id[:8]
            if new_suffix != last_session_id:
                old_sender        = SENDER_ID
                SESSION_ID        = new_suffix
                SESSION_ID_SOURCE = resolution_source
                SENDER_ID         = _get_sender_id( CANONICAL_PROJECT, SESSION_ID )
                last_session_id   = new_suffix
                logger.info(
                    f"Session ID changed: {old_sender} -> {SENDER_ID} "
                    f"(context clear detected)"
                )

        except Exception as e:
            logger.error( f"Session watcher error: {e}" )


def _session_watcher_thread():
    """
    Resolve the CC session_id once, then signal `_session_ready`. PHASE 1 ONLY.

    ⚠️ CHANGED 2026-08-26 (row `87ae7234`). This used to fall straight into phase 2's
    forever-poll, so IMPORTING this module started a loop that ran for the life of the
    process — including a test process, where it executed 31 lines of session_bridge.py
    that no test reached and coverage.py credited anyway. Phase 2 is now started
    SEPARATELY and only by the server; see `_start_bridge_watch`.

    Phase 1 STAYS at import and is load-bearing: `_wait_for_sender_id` blocks on
    `_session_ready`, which this sets in a `finally`. Suppressing phase 1 takes a suite
    from `333 passed` to a silent `EXIT=1` — measured, not assumed.

    Ensures:
        - sets `_session_ready` on every path, success or failure
        - sets `_session_failed` when resolution raised
        - RETURNS once resolution is done — it no longer watches
    """
    global SESSION_ID, SENDER_ID, SESSION_ID_SOURCE, _session_failed

    # ── Phase 1: Initial resolution ─────────────────────────────────────
    try:
        real_id, resolution_source = wait_for_session_id_with_source( timeout=10.0, poll_interval=1.0 )
        new_suffix        = real_id[:8]
        SESSION_ID_SOURCE = resolution_source

        if new_suffix != SESSION_ID:
            old_sender = SENDER_ID
            SESSION_ID = new_suffix
            SENDER_ID  = _get_sender_id( CANONICAL_PROJECT, SESSION_ID )
            logger.info( f"Session ID upgraded: {old_sender} -> {SENDER_ID}" )

        # ⚠️ A BORROWED IDENTITY IS NOT A FAILURE AND MUST NOT BE ALERTED AS ONE — it is a
        # colleague's, adopted because we share their checkout. Log it loudly; the refusal
        # at the write verbs is what actually stops it reaching anyone's board.
        if resolution_source == SOURCE_CWD_FALLBACK:
            logger.warning(
                f"Session identity was GUESSED from the working directory, not this "
                f"process tree — sender_id={SENDER_ID} may name another seat. "
                f"Identity-bearing writes will be refused."
            )

        # Verify we got a real session ID, not the fallback
        meta = _get_cc_metadata()
        if meta.get( "source" ) == "fallback":
            logger.warning( "No session bridge file found for this project" )
            logger.warning( f"Using stable fallback sender_id: {SENDER_ID}" )
        else:
            logger.info( f"Session ready (sender_id={SENDER_ID})" )

    except Exception as e:
        _session_failed = True
        logger.critical( f"Session ID resolution failed: {e}" )

    finally:
        _session_ready.set()


def _start_bridge_watch( ready_timeout=15.0 ):
    """
    Start phase 2 — THE SERVER ONLY, and only by explicit call.

    Row `87ae7234`. Phase 2 watches the bridge file so a context clear updates
    SESSION_ID mid-session. Only a long-lived MCP server needs that; an importing
    process does not, and a test process actively must not — a loop nobody drives
    still executes product lines, and coverage.py credits them to no test at all.

    THE GATE IS THE CALL ITSELF. There is no environment sniff and no
    PYTEST_CURRENT_TEST check: phase 2 runs because the entry point ASKED for it,
    beside `_IS_MCP_SERVER = True`, in the one block that already means "I am the
    server". A flag read from the environment would have to be set correctly in five
    separate launch configs, and a missed one would silently disable context-clear
    detection in a real server; a call in the main block cannot be missed.

    Requires:
        - phase 1 has been started (this waits for `_session_ready` before polling,
          because phase 2 reads the resolved SESSION_ID as its baseline)

    Ensures:
        - returns the started daemon Thread, or None if phase 1 never resolved
        - never raises
    """
    def _run():
        # Phase 2's baseline is the resolved id, so it must not start before phase 1.
        if not _session_ready.wait( timeout=ready_timeout ):
            logger.warning( "Bridge watch not started: session never resolved" )
            return
        _watch_bridge_for_changes()

    thread = threading.Thread( target=_run, name="session-id-watcher", daemon=True )
    thread.start()
    return thread


_watcher_thread = threading.Thread(
    target=_session_watcher_thread,
    name="session-id-resolver",
    daemon=True
)
_watcher_thread.start()


class SessionIdUnavailable( RuntimeError ):
    """
    Raised instead of hard-exiting when the session ID never resolved and this
    process is NOT the MCP server.

    The MCP server must die on this condition — it cannot serve tools without a
    session id. An importing process must NOT: a library that calls os._exit takes
    its host down with no traceback, which is how a test suite came to report a
    truncated run with nothing anywhere naming the cause.
    """


# ── The retry budget, and the words the operator actually reads ───────────────
#
# 🔴 BOTH OF THESE ARE Rick's P0 OF 2026-09-03 (store row f6a43e37), and the
# SECOND one is the half he actually experienced. Ten alerts reached him in
# fourteen minutes saying "MCP server failed … Restart Claude Code to fix".
# Measured against Claude Code's own per-session logs
# (~/.cache/claude-cli-nodejs/<project>/mcp-logs-cosa-voice/): every managed
# cosa-voice server in every project connected successfully across that whole
# window, with zero errors, disconnects or restarts.
#
# So the alarm was TRUE — something really could not resolve a session identity
# — and its LABEL was FALSE. It named a component that had not failed and
# prescribed a restart that could not have fixed anything. Noise is ignorable;
# a false instruction is acted on, which is why the words are a defect and not
# a presentation detail.
#
# ⚠️ THE FIX IS NOT SUPPRESSION. A process that genuinely has no session bridge
# must still alert, because sending traffic under a wrong identity is worse than
# a loud alarm. What changed is that resolution is RETRIED first, every attempt
# is LOGGED, and the operator is told ONCE, in words that name the mechanism.
#
# Worst case added latency on the failing path only: SESSION_RESOLVE_ATTEMPTS
# waits of at most SESSION_RESOLVE_ATTEMPT_SECONDS, plus linear backoff between
# them. The succeeding path is unchanged — the Event is already set by import-time
# phase 1, so `wait` returns instantly and no retry is ever entered.
SESSION_RESOLVE_ATTEMPTS         = 3
SESSION_RESOLVE_ATTEMPT_SECONDS  = 3.0
SESSION_RESOLVE_BACKOFF_SECONDS  = 1.0

# NO ACTION IS PRESCRIBED, DELIBERATELY. There is nothing the operator can do
# about another process's identity resolution, and inventing an instruction is
# exactly what made the old text harmful. It says what failed, what was NOT done
# as a result, and where to look if it persists.
_SESSION_IDENTITY_ALERT_TEXT = (
    "cosa-voice could not resolve a Claude Code session identity for one process, "
    f"after {SESSION_RESOLVE_ATTEMPTS} attempts. Nothing was sent under a wrong "
    "identity. No action is needed if a session was starting or clearing just then. "
    "If this repeats, the session bridge directory is where to look — the MCP "
    "servers themselves are unaffected."
)


def _reattempt_session_resolution( timeout ):
    """
    Re-run phase-1 resolution IN THE CALLER'S THREAD, once.

    ⚠️ RE-RUNS RESOLUTION RATHER THAN RE-WAITING ON THE EVENT, and the distinction
    is the whole reason this exists. `_session_ready` is set in a `finally` on every
    path, success or failure, so once a resolution has failed the Event is set
    FOREVER and waiting on it again returns instantly with the same bad answer.
    A retry that only waited would be a no-op wearing a loop's clothing.

    Requires:
        - `timeout` is the per-attempt budget in seconds

    Ensures:
        - returns True and leaves SESSION_ID / SENDER_ID naming the resolved seat
        - returns False on any failure, having logged it, and never raises
        - clears `_session_failed` only on success, so a later caller sees the truth
    """
    global SESSION_ID, SENDER_ID, SESSION_ID_SOURCE, _session_failed

    try:
        real_id, resolution_source = wait_for_session_id_with_source( timeout=timeout, poll_interval=1.0 )
    except Exception as e:
        logger.warning( f"Session identity resolution attempt failed: {e}" )
        return False

    if not real_id:
        logger.warning( "Session identity resolution attempt returned nothing" )
        return False

    suffix            = real_id[ :8 ]
    SESSION_ID_SOURCE = resolution_source
    if suffix != SESSION_ID:
        SESSION_ID = suffix
        SENDER_ID  = _get_sender_id( CANONICAL_PROJECT, SESSION_ID )

    _session_failed = False
    _session_ready.set()
    return True


def _die_no_session_id():
    """
    Send error notification, then hard-exit ON THE SERVER or raise off it.

    ⚠️ THE CONTRACT CHANGED 2026-08-26 (row `87ae7234`). This used to promise
    "never returns" unconditionally. It now branches on `_IS_MCP_SERVER`, because a
    library that calls `os._exit` takes its HOST process down with no traceback and
    no summary — which is how a test suite came to report a truncated run with
    nothing anywhere naming the cause.

    Requires:
        - Lupin FastAPI server is running (for notification delivery)
        - `_IS_MCP_SERVER` is True only in the MCP server process, set positively at
          the `if __name__ == "__main__":` entry point

    Ensures:
        - Sends high-priority alert from sender_id claude.code@{PROJECT}.deepily.ai#mcp-error
          on BOTH paths — the alert is not the server's privilege
        - ON THE SERVER: writes a named reason to flushed stderr, then terminates via
          os._exit( 1 ) and never returns
        - OFF THE SERVER: never returns either, but by RAISING — the host process
          survives and the caller gets something it can catch

    Raises:
        - SessionIdUnavailable when this process is not the MCP server
    """
    error_sender = f"claude.code@{PROJECT}.deepily.ai#mcp-error"
    logger.critical( "Sending error notification and terminating MCP server" )

    try:
        request = AsyncNotificationRequest(
            message           = _SESSION_IDENTITY_ALERT_TEXT,
            notification_type = NotificationType.ALERT,
            priority          = NotificationPriority( "high" ),
            sender_id         = error_sender
        )
        notify_user_async( request=request, debug=False )
    except Exception as e:
        logger.error( f"Failed to send error notification: {e}" )

    # SAY WHY ON THE WAY OUT. os._exit skips every flush, atexit hook and
    # exception path, so a caller that imports this module — a test process
    # above all — dies with no traceback, no summary and no logging record:
    # pytest reports a truncated run and nothing anywhere names the cause.
    # logger.critical above is captured by pytest and lost with it; an
    # explicitly-flushed stderr write is not. Two lines, no behaviour change
    # for the server, and the difference between a silent kill and a named one.
    if not _IS_MCP_SERVER:
        # NOT the server — raise, do not kill the host. The caller gets a named
        # exception it can catch and a traceback naming this function.
        raise SessionIdUnavailable(
            "Claude Code session ID never resolved and this process is not the MCP "
            "server, so _die_no_session_id() raised instead of calling os._exit(1). "
            "No session bridge file was detected."
        )

    sys.stderr.write(
        "[cosa-voice] FATAL: Claude Code session ID never resolved; "
        "os._exit(1) from _die_no_session_id(). No session bridge file was "
        "detected. If you are seeing this from a test run, the process was "
        "terminated here — the suite did not finish.\n"
    )
    sys.stderr.flush()

    os._exit( 1 )


def _refuse_borrowed_identity( verb: str, source: Optional[ str ] = None ) -> Optional[ dict ]:
    """
    Refuse an identity-bearing write when this seat's identity was GUESSED.

    🔴 WHY THIS EXISTS. `session_bridge` tier 4 resolves a session by matching the recorded
    working directory of every live bridge. On this fleet every seat shares one checkout, so
    that filter excludes nobody and the tier returns whichever colleague touched their bridge
    most recently. The process does not fail — it succeeds AS SOMEBODY ELSE, and a row written
    then lands on their board under their name with nothing anywhere saying otherwise.

    The tier is kept on purpose (María's ruling, 2026-09-03): deleting it turns a wrong-seat
    into a fail-to-resolve, and a false "your session is broken" is what cost Rick an
    afternoon. So the tier still answers, and THIS is what stops the answer being acted on.

    ⚠️ SCOPE IS DELIBERATELY NARROW — WRITES THAT CARRY AN IDENTITY, NOTHING ELSE. `notify`
    and the `commons_read` family are untouched: a notification from the wrong pane is noise,
    while a task row or a DM from the wrong seat is a durable misattribution. Refusing the
    alert path would also silence the very warning that says the identity is borrowed.

    ⚠️ AND `generated_fallback` IS ALLOWED THROUGH, WHICH LOOKS WRONG UNTIL YOU NAME THE
    DIFFERENCE. An invented id belongs to no one, so a write under it is orphaned and
    visibly odd. A borrowed id belongs to a real colleague. Only the second one files your
    work under somebody else's name, and only the second one is refused here.

    Requires:
        - verb is the caller's tool name, used verbatim in the refusal text

    Ensures:
        - Returns None for every definitive source, and for the generated fallback
        - Returns an error dict ONLY for SOURCE_CWD_FALLBACK
        - Never raises; never writes anything

    Args:
        verb:   name of the calling tool, e.g. "task_create"
        source: resolution source to judge; defaults to this process's live SESSION_ID_SOURCE

    Returns:
        dict or None: an error dict the verb should return unchanged, or None to proceed
    """
    effective = SESSION_ID_SOURCE if source is None else source
    if effective != SOURCE_CWD_FALLBACK:
        return None

    return {
        "status" : "error",
        "reason" : "borrowed_identity",
        "detail" : (
            f"{verb} refused: this process's session identity was GUESSED from the working "
            f"directory, not resolved from its own process tree. It currently reads as "
            f"'{SENDER_ID}', which on a shared checkout is most likely a colleague's seat. "
            f"Writing would file this work under their name. Set CLAUDE_SESSION_ID, or run "
            f"from a process whose parent is the Claude Code session you mean."
        ),
        "resolution_source" : effective,
        "sender_id"         : SENDER_ID,
    }


def _session_info_payload( cc_meta: dict ) -> dict:
    """
    Build the `claude_code` block of `get_session_info`, carrying HOW the id was resolved.

    `get_session_metadata` has computed `resolution_source` all along and this boundary
    dropped it, reporting only the coarse "session_file" — which is true of a definitive
    PPID match and of a borrowed guess alike. A field computed and then discarded at the
    boundary is the same defect the bare accessors had, one layer up.

    Requires:
        - cc_meta is the dict returned by session_bridge.get_session_metadata()

    Ensures:
        - Always returns the four keys, never raises on a missing one
        - resolution_source is "unknown" rather than absent when the metadata lacks it

    Args:
        cc_meta: session bridge metadata

    Returns:
        dict: the claude_code block
    """
    return {
        "session_id"        : cc_meta.get( "session_id", "" ),
        "stable_session_id" : cc_meta.get( "stable_session_id", "" ),
        "source"            : cc_meta.get( "source", "unknown" ),
        "resolution_source" : cc_meta.get( "resolution_source", "unknown" ),
    }


def _wait_for_sender_id( timeout: float = 12.0 ) -> str:
    """
    Block until the session ID is resolved, then return SENDER_ID.
    If resolution failed (fallback only), send error notification and exit.

    Requires:
        - _session_ready is a threading.Event set by _upgrade_session_id_background
        - _session_failed is a bool set by _upgrade_session_id_background
        - timeout exceeds background thread's 10s wait

    Ensures:
        - Returns SENDER_ID with real session ID on success
        - Calls _die_no_session_id() on failure, which exits the MCP server process
          and RAISES SessionIdUnavailable in any other process (row `87ae7234`) —
          either way this function does not return a value on that path
        - Zero overhead after first resolution (Event.wait on set event returns instantly)

    Raises:
        - SessionIdUnavailable (via _die_no_session_id) when resolution failed and
          this process is not the MCP server
    """
    if _session_ready.wait( timeout=timeout ) and not _session_failed:
        return SENDER_ID

    # ⚠️ UNRESOLVED IS NOT YET AN EMERGENCY. Retry before telling a human, and
    # LOG every attempt — a change that stopped alerting and also stopped logging
    # would hide the process that genuinely has no bridge rather than fix it.
    for attempt in range( 1, SESSION_RESOLVE_ATTEMPTS + 1 ):
        logger.warning(
            f"Session identity unresolved — retry {attempt}/{SESSION_RESOLVE_ATTEMPTS}"
        )
        if _reattempt_session_resolution( SESSION_RESOLVE_ATTEMPT_SECONDS ):
            logger.info( f"Session identity resolved on retry {attempt}" )
            return SENDER_ID
        time.sleep( SESSION_RESOLVE_BACKOFF_SECONDS * attempt )

    # Every attempt failed. NOW it is the operator's business — once.
    _die_no_session_id()

    return SENDER_ID


# ============================================================================
# Speakerphone TTS Contract (once-stated, single-sourced)
# ============================================================================
#
# Per src/rnd/v0.1.9/2026.06.27-cosa-voice-rider-slim.md §4: the full standing
# TTS contract is stated ONCE here in the session-init `instructions` payload.
# The per-turn `<system-reminder>` rider (hook_common._speakerphone_reminder_body)
# is now slim and only points at this section. The brevity prose is
# single-sourced from hook_common._brevity_rules() — the SAME function the
# rider historically composed from and the same cu.get_spoken_char_cap() source
# the caller-side enforcement guard reads — so the spoken-char cap never drifts
# between the rider, this contract, and the server reject boundary.
#
# The interactive-tool routing rule is NOT in this section. It lives in the
# "## Interactive Tool Routing" section of the `instructions` body below, built
# from hook_common._routing_reminder(), and the per-turn rider carries the
# routing line itself. A unit test ties the reminder text to the served
# instructions (test_the_routing_reminder_is_in_the_served_instructions.py).

_TTS_CONTRACT_SECTION = (
    "## Speakerphone TTS Contract (applies on every turn — speakerphone is the standing default)\n\n"
    "CLOSING TURN: after your user-facing reply, call "
    "notify(message=<full reply, recrafted for speech>, suppress_ding=True, priority='high').\n\n"
    + _brevity_rules() + "\n\n"
)


# ============================================================================
# DM Style Contract (DM brevity/tone contract, Rick 2026-07-31 — always on,
# no toggle. See src/rnd/v0.1.9/2026.07.31-dm-verbosity-reduction/)
# ============================================================================
#
# Closes the gap the research found: the fleet already reminds a peer how to
# REPLY (DM_STYLE_TAG on the reply affordance in hook_common.py), but nothing
# shaped how a DM is COMPOSED in the first place. This section states that
# explicitly, spliced unconditionally into the MCP `instructions` payload.
_DM_STYLE_CONTRACT_SECTION = (
    "## DM Style Contract (governs `dm_send`, composing and replying)\n\n"
    "Write every body before sending, in plain literal sentences a colleague would read; no metaphors or invented vocabulary. "
    # Rick, 2026-08-13: three sentences and a path, no word counts anywhere. The path clause is load-bearing: without it the
    # pointer reads as a fourth sentence and the compliant house style looks non-compliant (María, 2026-08-13). The rest of the
    # contract rides in DM_STYLE_TAG, which is also the reply-affordance tag.
    "Three sentences; a path replaces detail and is not a fourth. "
    f"{DM_STYLE_TAG}\n\n"
)


# ============================================================================
# MCP Server
# ============================================================================

mcp = FastMCP(
    name="CoSA Voice Bridge",
    instructions=(
        f"Voice I/O for Claude Code [Session: {SENDER_ID}]\n\n"

        f"## Startup (every session and after /clear, plan mode included)\n"
        f"\n"
        f"Before any user-facing text call `get_session_info()` and learn your `voice_persona`; never answer as 'Claude'. Then `notify(notification_type='custom', priority='medium')` a greeting by `display_name`. If `voice_persona` is None, ANNOUNCE THE NULL, never go quiet: speak 'no voice persona' plus the FIRST 8 CHARACTERS of `claude_code.session_id` (the one id allowed in speech); the full id goes in `abstract`.\n"
        f"\n"

        f"{_TTS_CONTRACT_SECTION}"

        f"{_DM_STYLE_CONTRACT_SECTION}"

        f"## Startup details (short form is at the top of this payload)\n"
        f"\n"
        f"**Phase A, before your first user-facing text, in ALL modes including plan mode** (these are communication tools, not code-changing tools). Finish it before any file reading, exploration, edits or planning:\n"
        f"\n"
        f"1. Call `get_session_info()` once. It returns `voice_persona` (`{{name, display_name, voice_id, icon, color, borrowed}}`), `speakerphone_on`, `tts_interaction_mode` (`solo` | `chorus`) and `claude_code.session_id` (your stable id for DM correlation). Extract `voice_persona` first: in chorus mode your persona voice is how the listener tells sessions apart.\n"
        f"2. Report MCP status in your first acknowledgment: project, session_id, server_url, version, resolved persona name.\n"
        f"3. Call `notify(notification_type='custom', priority='medium', suppress_ding=False)` — ALWAYS, in BOTH cases. Named persona: a time-of-day greeting using `display_name` (the proper noun, e.g. 'Maria', not the lowercase pool key `name`) plus a brief duty line, e.g. 'Good morning, Maria reporting for duty, setting things up.' Null persona: the alarm below. It fires again after /clear (the persona persists).\n"
        f"\n"
        f"**Phase B, as soon as the topic is knowable:** call `set_session_topic(topic='<3-8 word title>')`, from the user's first message, history.md/TODO.md or the approved plan. Skipping it is a session-start bug: the topic is what the 'Continue Session?' stop-hook notification shows.\n"
        f"\n"
        f"**If `voice_persona` is None (allocation failed), do NOT skip — ANNOUNCE THE NULL.** A session that boots healthy announces itself, so one that boots broken must not go quiet: skipping optimises the greeting's CONTENT and silences the ALARM. With no name to greet by, identify yourself by session id:\n"
        f"- spoken `message`: say this session has no voice persona and give the FIRST 8 CHARACTERS of `claude_code.session_id`. Example: 'Warning — this session booted with no voice persona assigned. Session a1b2c3d4, running unattributed.' **This is an explicit EXCEPTION to the standing TTS rule that ids and hashes belong in `abstract`, never in speech.** Everywhere else the persona badge and voice carry identity; a null session has neither, so the alarm would be anonymous. 8 characters is the whole cost: put them in the speech. Do NOT silently relocate the id to `abstract` only and consider the obligation met.\n"
        f"- `abstract`: the FULL `claude_code.session_id` plus the project name.\n"
        f"\n"
        f"**The session id is MANDATORY in both.** The UI persona badge is gated on `sender_id && voice_persona`, so a null session's card renders without its badge, and with no id in the text nobody can tell who sent it. Then follow Failure Mode 2: the notify and the manager DM come BEFORE any blocking `converse()`.\n"
        f"\n"
        f"## Speakerphone Mode\n"
        f"\n"
        f"Each session has a `speakerphone_on` flag (bridge file) and there is a global `tts_interaction_mode` (`solo` | `chorus`). Read both from `get_session_info()` at session start and after /clear.\n"
        f"\n"
        f"- **phone** (`speakerphone_on=false`): respond normally; speak only when YOU call `notify()`, `converse()` or `ask_*()`.\n"
        f"- **speakerphone** (`speakerphone_on=true`): the user is at a distance, listening. Send a short receipt-acknowledgment `notify(message=<short ack>, suppress_ding=True, priority='high')` BEFORE any tool call, even when the real answer comes in a later turn; a turn that opens with tool calls and never speaks breaks the contract. Speak every closing turn as the TTS Contract above says.\n"
        f"\n"
        f"When the user says 'enable speakerphone', 'disable speakerphone', 'enter conversation mode', 'exit conversation mode', 'speakerphone on' or 'speakerphone off' (or a close paraphrase), call `enable_speakerphone()` or `disable_speakerphone()` and continue in the new state.\n"
        f"\n"
        f"**USER-ONLY INITIATION (HARD RULE)**: NEVER call either on your own initiative; only in direct response to an explicit user instruction (voice phrase, typed request, slash command). 'Since this is a long task, let me enable speakerphone' is FORBIDDEN: the mic is the user's to direct. If unsure whether the user asked, do not call; ask.\n"
        f"\n"
        f"Across sessions: under `solo`, one session at a time holds speakerphone, so enabling it here displaces the other (its UI reverts to phone mode, in-flight TTS pauses, its sender card unpins; broadcast as `speakerphone_changed` with `displaced=true, displaced_by=<this session's id>`). Under `chorus` (the multi-voice default) N sessions hold it at once, persona voices tell them apart, and nothing is displaced. The flag survives /clear; a fresh session defaults to false in solo and true in chorus.\n"
        f"\n"
        f"## Inter-Session Commons and Peer DM\n"
        f"\n"
        f"The commons is a file-backed blackboard shared by the CC sessions on this host. Each per-tool docstring opens with a `**[TIER]**` marker (READ / SELF-DISCLOSURE / ATTENTION-DEMANDING / DM): check it when deciding whether a call needs a user trigger.\n"
        f"\n"
        f"| Tier | Tools | When you can fire on your own |\n"
        f"|---|---|---|\n"
        f"| **READ** | `commons_read`, `commons_who` | Always — inspecting the blackboard disturbs no one |\n"
        f"| **SELF-DISCLOSURE** | `commons_post` to free-form / presence / incident topics | When announcing your own state ('starting long migration', 'observed bug X'): fire-and-forget, no recipient is summoned |\n"
        f"| **ATTENTION-DEMANDING** | `commons_post` to coordination/help-wanted topics; `commons_ask_async` / `commons_ask_sync`; `dm_send`; broadcasts | Only with a clear coordination need or an explicit user trigger: it summons a peer's attention |\n"
        f"\n"
        f"Reserved topics: `broadcasts` (user-originated, read-only from CC sessions), `broadcast-acks` (auto-managed), `presence` (session lifecycle), `system-events` (server notices). Any other name is free-form and auto-creates on first post. Persona name, icon and color are stamped server-side at post time and are immutable: you cannot spoof another persona.\n"
        f"\n"
        f"**Directed peer messages use `dm_send(recipient='persona', body=...)`**: the body travels inline in the recipient's push (~204 tokens), with no re-fetch. `commons_ask_async(topic, body)` is polling-mode only (an open question to a topic at large; you poll for replies with `commons_read`), not a directed DM. `commons_ask_sync` blocks until a reply and is rarely justified.\n"
        f"\n"
        f"When a peer DM arrives (an inbound `dm_send`, direction='ai_to_ai'):\n"
        f"1. In speakerphone mode, acknowledge receipt before tool calls, as for a user prompt.\n"
        f"2. The body is inline in the DM framing; there is no `commons_read` re-fetch.\n"
        f"3. Reply with `dm_send(recipient=<sender>, body=<reply>, reply_to=<message_id>, thread_id=<thread_id>)`; both ids are in the inbound framing. A reply is just a DM back; there is no `expect_reply` flag.\n"
        f"4. Do not reply to a DM you sent yourself (compare the sender with `get_session_info()` if unsure).\n"
        f"\n"
        f"A DM is one peer-specific question or request: the recipient owes you attention and you owe them context. A `USER BROADCAST` `<system-reminder>` is the user talking to several sessions at once; sessions never initiate broadcasts.\n"
        f"\n"
        f"**Bug in a peer's domain: do BOTH** — `dm_send` the responsible session (low latency), and file a structured entry in their repo's `bug-fix-queue.md` (the durable backup if push fails or they are offline).\n"
        f"\n"
        f"Canonical doctrine (anti-patterns, sensitive-content rules, retention, broadcast receipts): planning-is-prompting → workflow/cross-session-communication.md (§1.5 DM mechanics and threading, §2 three-tier autonomy, §3 reserved topics, §4 broadcast receipts, §6.5.1 bug-filing pattern).\n"
        f"\n"
        f"## Interactive Tool Routing\n"
        f"\n"
        f"{_routing_reminder()}\n"
        f"\n"
        f"| Question shape | Use | Why |\n"
        f"|---|---|---|\n"
        f"| Yes / No (binary) | `ask_yes_no(question, default='yes'\\|'no')` | Three-button UI with an optional 'Neither' escape hatch when the question itself needs re-framing |\n"
        f"| 2-4 mutually-exclusive options | `ask_multiple_choice(questions=[{{...}}], default={{header: label}})` | Radio-button UI; supports multi-question batches; an optional `default` dict keyed by question header returns `{{\"answers\": default}}` on timeout instead of an error |\n"
        f"| Single open-ended | `converse(message=..., response_type='open_ended')` | Free-form text or voice response |\n"
        f"| Multiple open-ended at once | `ask_open_ended_batch(questions=[{{header, question}}, ...])` | One screen with per-question text+mic inputs; the user submits all at once |\n"
        f"\n"
        f"On 'Neither' from `ask_yes_no`: the question needs re-framing; it is NOT a soft yes/no. Read the comment (if present) and ask a clearer follow-up.\n"
        f"\n"
        f"All blocking tools use `priority='high'` so the TTS alert reaches the user in speakerphone mode.\n"
        f"\n"
        f"Every substantive `ask_yes_no` or `ask_multiple_choice` carries, in the `abstract`, per-option pros AND cons, a 'My recommendation: X because Y' block, and a flip-condition (what would make a different option correct). Pros and cons go in `abstract` ONLY, never in the spoken `message`.\n"
        f"\n"
        f"## Failure Modes + Debugging Signals\n"
        f"\n"
        f"How cosa-voice fails silently or partially, and what to read in the result dict:\n"
        f"\n"
        f"**1. `dm_send` returns `{{status: 'error', reason: 'recipient_unresolved'}}`** — the recipient persona/session could not be resolved (same-user scoped). `detail` carries the RecipientResolutionError chain (what was tried, candidate alternatives, suggested next action): read it before retrying with a corrected name. A transport/auth error returns `{{status: 'error', reason: ...}}` instead: the Lupin REST API may be down or the X-API-Key unavailable.\n"
        f"\n"
        f"**2. `voice_persona: None` in `get_session_info()`** — the allocator returned no assignment, or the pool was exhausted and you got the 'Sam' overflow fallback (`borrowed: true` on the legacy hash-borrow path). Rare; it means pool exhaustion or a corrupt bridge file. When None:\n"
        f"\n"
        f"- DO NOT respond as 'Claude' or a placeholder: that breaks the chorus-mode disambiguation contract.\n"
        f"- **DO NOT go quiet.** The remedies below are ORDERED BY COST, and the first two cost nothing. Work down the list; do not skip to the bottom.\n"
        f"\n"
        f"| # | Do this | Interrupt cost | Permission needed |\n"
        f"|---|---|---|---|\n"
        f"| 1 | `notify()` the null alarm, naming your `claude_code.session_id` INLINE (§ Startup) | **none** — fire-and-forget | none; self-disclosure tier |\n"
        f"| 2 | `dm_send()` your manager, if you have one, so they can allocate for you | **none** | none; DM tier |\n"
        f"| 3 | `converse(message='Which persona am I?', response_type='open_ended')` | **one blocking interrupt to the user** | escalate ONLY if the null blocks the work |\n"
        f"\n"
        f"**Why the order matters**: a standing drive-to-completion rule correctly prices out INTERRUPTS, so a worker that treats `converse()` as the only remedy will decline it and stay unnamed indefinitely. That rule does NOT price out NON-BLOCKING SIGNALS: steps 1 and 2 are always permitted, and someone with the authority to allocate can only help once they know you are null. `request_persona()` remains USER-INITIATED ONLY; do not self-heal (see its docstring).\n"
        f"\n"
        f"**3. (retired)** The legacy commons-DM failure modes no longer apply; use `dm_send` (Failure Mode 1).\n"
        f"\n"
        f"**4. Stale-bridge phantom personas in `commons_who`** — it may list sessions whose host process has died until the SessionStart prune cleans them. If a DM to a 'visible' peer never gets a reply, the recipient may be a phantom; cross-check with `commons_who(retention_hours=1)`.\n"
        f"\n"
        f"**5. Persona-allocation cache staleness across MCP restart** — after ANY MCP restart or pool-exhaustion event (especially a 'Sam' overflow), the running MCP subprocess may hold an in-memory allocation older than the bridge file. Re-call `get_session_info()` and trust the bridge file, which is the source of truth.\n"
    )
)


# ------------------------------------------------------------------------------
# v2.1 direct-state-visibility — SERVER per-MCP-call bridge-mtime stamp
# (arbiter design 03 §10.1 / §10.7). Bumps THIS session's bridge-file mtime on
# every inbound tool call so a heads-down (never-Stops) session still reports
# live liveness. Converges on the ONE host-side clock (redline C4) via
# touch_bridge_mtime — no parallel last-seen store. See bridge_liveness_middleware.
# ------------------------------------------------------------------------------
from lupin_mcp.bridge_liveness_middleware import BridgeLivenessMiddleware
mcp.add_middleware( BridgeLivenessMiddleware() )


# ------------------------------------------------------------------------------
# Spoken-brevity cap (caller-side TTS limit) — Rick 2026-06-02
# ------------------------------------------------------------------------------
# The spoken field (`message` / `question`) of the speaking tools is read aloud
# via TTS; long bodies become a "wall of text" in the user's ear. Detail belongs
# in the `abstract` parameter (rendered to the UI card, NEVER length-limited),
# not in the spoken channel. This cap is enforced CALLER-SIDE in the MCP layer
# ONLY — the notifications REST API stays unrestricted so agentic jobs / system
# events can still send longer payloads when they genuinely need to.
#
# The cap VALUE lives in lupin-app.ini (`cosa voice spoken char cap`, default 500)
# and is read via ConfigurationManager so it is TUNABLE AT RUNTIME: re-read
# mtime-gated (so the hot path stays cheap) on the next call after the INI changes
# — no MCP restart required. A spoken field over the cap is REJECTED unless the
# caller sets override_size_limitation=True (long is opt-in-and-intentional).
#
# SINGLE SOURCE OF TRUTH: the INI key + default are owned by cosa.utils.util so the
# per-turn TTS brevity rider (hook_common._brevity_rules, which names this number to
# the model) and this caller-side enforcement guard can NEVER drift. Do not inline a
# literal here — reference cu.
import cosa.utils.util as _cu_capsrc
SPOKEN_CHAR_CAP_DEFAULT = _cu_capsrc.SPOKEN_CHAR_CAP_DEFAULT
SPOKEN_ENFORCE_DEFAULT  = True   # default: guard ON. INI may flip it OFF for ALL callers.
_SPOKEN_CAP_INI_KEY     = _cu_capsrc.SPOKEN_CHAR_CAP_INI_KEY
_SPOKEN_ENFORCE_INI_KEY = "cosa voice enforce spoken char cap"
_spoken_cap_cache       = { "value": SPOKEN_CHAR_CAP_DEFAULT, "enforce": SPOKEN_ENFORCE_DEFAULT, "ini_mtime": None }


def _refresh_spoken_cfg():
    """
    Re-read the spoken cap + enforce flag from lupin-app.ini, mtime-gated.

    Ensures:
        - updates _spoken_cap_cache["value"] (int cap) AND ["enforce"] (bool) ONLY
          when the INI file mtime changed since the last read — cheap on the hot path
          (one ConfigurationManager re-read, atomic _reset_singleton)
        - never raises; on any error leaves the last good cached values in place
    """
    try:
        import os
        import cosa.utils.util as cu
        ini_path = cu.get_project_root() + "/src/conf/lupin-app.ini"
        mtime    = os.path.getmtime( ini_path )
        if mtime != _spoken_cap_cache[ "ini_mtime" ]:
            from cosa.config.configuration_manager import ConfigurationManager
            cm = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS", _reset_singleton=True )
            _spoken_cap_cache[ "value" ]     = cm.get( _SPOKEN_CAP_INI_KEY, default=SPOKEN_CHAR_CAP_DEFAULT, return_type="int", silent=True )
            _spoken_cap_cache[ "enforce" ]   = cm.get( _SPOKEN_ENFORCE_INI_KEY, default=SPOKEN_ENFORCE_DEFAULT, return_type="boolean", silent=True )
            _spoken_cap_cache[ "ini_mtime" ] = mtime
    except Exception as e:
        logger.warning( f"[brevity] cfg read failed; using last good cached values. Reason: {e}" )


def _get_spoken_char_cap():
    """
    Resolve the spoken-char cap (int) from lupin-app.ini at call time (runtime-tunable).

    Ensures:
        - returns an int cap (last good cached value, else SPOKEN_CHAR_CAP_DEFAULT)
    """
    _refresh_spoken_cfg()
    return _spoken_cap_cache.get( "value", SPOKEN_CHAR_CAP_DEFAULT )


def _get_spoken_enforce():
    """
    Resolve the global brevity-enforce flag (bool) from lupin-app.ini at call time.

    Ensures:
        - returns True when the spoken-length guard is ON (default), False to GLOBALLY
          disable it for ALL callers (Rick 2026-06-09 kill-switch). Runtime-tunable,
          mtime-gated — no MCP restart to flip once this code is loaded.
    """
    _refresh_spoken_cfg()
    return _spoken_cap_cache.get( "enforce", SPOKEN_ENFORCE_DEFAULT )


def _enforce_spoken_brevity( spoken, override_size_limitation, field="message" ):
    """
    Caller-side TTS spoken-length guard for the cosa-voice speaking tools.

    Requires:
        - spoken is either a str (the spoken field) OR a list of question dicts
          (each optionally carrying a "question" str)
        - override_size_limitation is a bool
        - field is the parameter name (used only in the error message)

    Ensures:
        - returns None when override_size_limitation is True
        - returns None when the global enforce flag is OFF (kill-switch)
        - returns None when every spoken unit is <= the configured cap
        - raises ValueError naming the over-cap unit + its measured length otherwise

    Raises:
        - ValueError if a spoken unit exceeds the configured cap and override is False
          and the global enforce flag is ON
    """
    if override_size_limitation:
        return

    if not _get_spoken_enforce():   # global kill-switch (Rick 2026-06-09): brevity guard OFF for all callers
        return

    cap = _get_spoken_char_cap()

    units = []
    if isinstance( spoken, str ):
        units.append( ( field, spoken ) )
    elif isinstance( spoken, list ):
        for i, q in enumerate( spoken ):
            if isinstance( q, dict ) and isinstance( q.get( "question" ), str ):
                units.append( ( f"{field}[{i}].question", q[ "question" ] ) )

    for label, text in units:
        n = len( text )
        if n > cap:
            raise ValueError(
                f"Spoken `{label}` is {n} chars (cap {cap}). The spoken channel is "
                f"read aloud via TTS — keep it to a headline plus one takeaway and "
                f"move the detail into `abstract` (rendered to the UI card, not "
                f"length-limited). To send a long spoken message deliberately, set "
                f"override_size_limitation=True."
            )


# ------------------------------------------------------------------------------
# Durable notify outbox wiring (Phase 1 / lever A — messaging-coordination plane)
# ------------------------------------------------------------------------------
# On a FINAL notify send-failure, persist the request to an on-disk outbox and let
# a background flusher retry it (reusing its idempotency_key, so the server de-dups)
# until ack or TTL. Rides only local disk — no fleet, no messaging dependency.
# Design: src/rnd/v0.1.8/2026.06.02-messaging-coordination-plane-design.md (lever A1).
import uuid as _uuid
from lupin_mcp import notify_outbox as _notify_outbox

_OUTBOX_DEFAULTS = { "enabled": True, "dir": "/io/notify-outbox", "flush_interval": 30, "ttl": 86400 }


def _outbox_config():
    """
    Resolve outbox config from lupin-app.ini.

    Ensures:
        - returns a dict {enabled, dir, flush_interval, ttl}
        - fails SAFE to _OUTBOX_DEFAULTS on any ConfigurationManager error
    """
    cfg = dict( _OUTBOX_DEFAULTS )
    try:
        from cosa.config.configuration_manager import ConfigurationManager
        cm = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        cfg[ "enabled" ]        = cm.get( "notify outbox enabled",                 default=cfg[ "enabled" ],        return_type="boolean", silent=True )
        cfg[ "dir" ]            = cm.get( "notify outbox dir",                     default=cfg[ "dir" ],            return_type="string",  silent=True )
        cfg[ "flush_interval" ] = cm.get( "notify outbox flush interval seconds", default=cfg[ "flush_interval" ], return_type="int",     silent=True )
        cfg[ "ttl" ]            = cm.get( "notify outbox ttl seconds",            default=cfg[ "ttl" ],            return_type="int",     silent=True )
    except Exception as e:
        logger.warning( f"[notify-outbox] config read failed; using defaults. Reason: {e}" )
    return cfg


def _outbox_dir_for_session( cfg ):
    """Per-session spool dir: `<project_root><cfg.dir>/<session_id>`."""
    import cosa.utils.util as cu
    sid = ( SESSION_ID or "default" ).replace( "/", "_" )
    return os.path.join( cu.get_project_root() + cfg[ "dir" ], sid )


def _outbox_send_fn( payload ):
    """
    Re-deliver a spooled request payload.

    Ensures:
        - reconstructs AsyncNotificationRequest from the JSON payload and re-sends
        - returns True iff the server acked; False on any failure (item stays spooled)
    """
    try:
        req  = AsyncNotificationRequest.model_validate( payload )
        resp = notify_user_async( request=req, debug=False )
        return bool( resp.success )
    except Exception:
        return False


def _spool_failed_notify( request ):
    """
    Persist a failed notify for durable retry + ensure the flusher is running.

    Ensures:
        - no-op returning False when the outbox is disabled in config
        - spools the request and lazily starts the once-only flusher daemon
        - NEVER raises — a spool error must not break the notify return path
        - returns True iff the request was spooled
    """
    try:
        cfg = _outbox_config()
        if not cfg[ "enabled" ]:
            return False
        outbox_dir = _outbox_dir_for_session( cfg )
        _notify_outbox.spool( request, outbox_dir )
        _notify_outbox.start_flusher(
            _outbox_send_fn, outbox_dir,
            ttl_seconds=cfg[ "ttl" ], interval_seconds=cfg[ "flush_interval" ], logger=logger
        )
        return True
    except Exception as e:
        logger.warning( f"[notify-outbox] spool failed: {e}" )
        return False


def _outbox_has_backlog():
    """
    Drain-first gate: does this session's outbox currently hold spooled items?

    Ensures:
        - returns False when the outbox is disabled in config
        - returns True iff at least one item is spooled for this session
        - NEVER raises (a check error must not break the live send path)
    """
    try:
        cfg = _outbox_config()
        if not cfg[ "enabled" ]:
            return False
        return len( _notify_outbox.list_spooled( _outbox_dir_for_session( cfg ) ) ) > 0
    except Exception:
        return False


# The ONE marker naming a value the USER DID NOT CHOOSE (row e5f21fff).
#
# `converse` has carried this prefix since before the row was filed and is the
# ruled reference (D3): the marker is STRUCTURAL — you cannot read the value
# without reading it — which is why it beats a sibling flag a consumer can
# ignore. `ask_yes_no` returns a bare string and therefore has nowhere to put a
# flag; it uses this same marker rather than inventing a third convention.
#
# Defined once so the two verbs cannot drift into two spellings of the same
# claim. Dict-returning verbs use `_stamp_answer_provenance` instead.
DEFAULT_USED_MARKER = "[default used] "


def _with_idempotency_key( request ):
    """
    Assign a fresh idempotency_key to a blocking-ask request if it lacks one, so a
    re-POST of the SAME request (notify_user_sync's retry_on_timeout loop, a durable
    resend) de-dups server-side instead of minting a second notification card
    (bug f433fbae D2). Mirrors the async notify() assignment (notify_user_async:160)
    and _notify_impl (cosa_voice_mcp.py:1374). The blocking-ask verbs never set one,
    so every retry used to look like a brand-new ask.

    Requires:
        - request is a NotificationRequest with an `idempotency_key` attribute

    Ensures:
        - returns a request whose idempotency_key is a non-None uuid4 string
        - a request that already carries a key is returned UNCHANGED (caller-supplied
          keys win; only None is filled)
    """
    if request.idempotency_key is None:
        return request.model_copy( update={ "idempotency_key": str( _uuid.uuid4() ) } )
    return request


def _offloaded_tool( fn ):
    """
    Register a BLOCKING sync handler as an ASYNC tool that runs off the event loop.

    THE DEFECT THIS CLOSES (row 97ff4426, Rick's ruling 2026-09-05). FastMCP calls
    a sync tool INLINE on the event loop — `func_metadata.py:92-95` is literally
    `if fn_is_async: await fn(...) else: fn(...)`, with no `anyio.to_thread`
    anywhere on the tool path. cosa-voice is registered STDIO, so a session has ONE
    subprocess serving every verb. While a human-waiting ask is in flight — up to
    `timeout_seconds + 10`, i.e. 610s at the fleet's 600 — that subprocess services
    NOTHING: not a second tool call, not a read of stdin, not a keepalive. From the
    caller's side the wait looks unbounded while every bound inside the ask still
    holds.

    🔴 `async def` ALONE IS A MEASURED NO-OP, AND THAT IS THE TRAP THIS HELPER
    EXISTS TO REMOVE. Heartbeats counted during a 1s call, real `Tool.run`
    dispatch, one variable:

        def  (the old shape)                ->   0
        async def, body still blocking      ->   0     <- IDENTICAL TO THE DEFECT
        async def + to_thread (this helper) ->  19

    An `async def` that calls a blocking function still owns the loop, and every
    test passes either way. So the offload is the fix and the keyword is not; the
    two are welded together here so a future edit cannot keep one and drop the
    other.

    SCOPE — the five handlers that block pending a HUMAN, and deliberately not the
    other 25, which block for milliseconds on an HTTP call. Harm scales with
    DURATION, and 30 handlers of blast radius against a defect that bites on five
    is the trade Rick declined.

    ⚠️ THE WAIT IS UNCHANGED. Same duration, same answer, same blocking for the
    caller — a purposely-blocking call must keep blocking. The ONLY thing that
    changes is that OTHER calls in the session stop sitting unread.

    Requires:
        - fn is a synchronous callable (never a coroutine function)

    Ensures:
        - returns a coroutine function whose __doc__, __name__ and signature are
          fn's, so FastMCP's schema and tool description are byte-identical to
          what the un-wrapped handler produced
        - awaiting it runs fn in a worker thread and returns fn's return value
        - exceptions raised by fn propagate to the awaiting caller unchanged
        - the wrapper carries `.sync`, the original callable, for the IN-PROCESS
          callers that must not spin an event loop to ask a question

    ⚠️ Cancellation is UNCHANGED, not improved: `to_thread.run_sync` defaults to
    non-cancellable, exactly as an inline sync call was. A client that walks away
    still leaves the ask running to its own timeout.
    """
    @functools.wraps( fn )
    async def _async( *args, **kwargs ):
        return await anyio.to_thread.run_sync( functools.partial( fn, *args, **kwargs ) )

    # Explicit escape hatch, not an attribute-fishing fallback: an in-process caller
    # already on a thread (self_respin_core._default_ask) needs the sync callable and
    # must fail loudly if this helper ever stops providing it.
    _async.sync = fn
    return _async


@mcp.tool
@_offloaded_tool
def converse(
    message: str,
    response_type: str = "open_ended",
    timeout_seconds: int = 120,
    response_default: Optional[ str ] = None,
    priority: str = "medium",
    title: Optional[ str ] = None,
    abstract: Optional[ str ] = None,
    job_id: Optional[ str ] = None,
    override_size_limitation: bool = False
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
        override_size_limitation: Default False. True sends a spoken `message` over the
            length cap (configured, default 500) knowingly; detail belongs in `abstract`,
            which has no length limit, not in speech.

    Returns:
        User's response as text, or error/timeout message

    Examples:
        converse("Should I proceed with the refactor?", response_type="yes_no")
        converse("What naming convention should I use for the new module?")
        converse("The tests are failing. Should I continue?", response_default="yes")
    """
    logger.debug( f"converse() called: {message[:50]}..." )

    _enforce_spoken_brevity( message, override_size_limitation, field="message" )

    try:
        request = NotificationRequest(
            message=message,
            response_type=ResponseType( response_type ),
            notification_type=NotificationType.CUSTOM,
            priority=NotificationPriority( priority ),
            timeout_seconds=timeout_seconds,
            response_default=response_default,
            title=title,
            sender_id=_wait_for_sender_id(),
            abstract=_normalize_abstract( abstract ),
            job_id=job_id
        )
    except ( ValidationError, ValueError ) as e:
        logger.error( f"Validation error: {e}" )
        return f"[validation error: {e}]"

    # D2 (bug f433fbae): stamp an idempotency_key so a re-POST of this same ask
    # de-dups server-side instead of minting a duplicate card.
    request = _with_idempotency_key( request )
    response: NotificationResponse = notify_user_sync( request=request, debug=False )

    if response.exit_code == 0:
        prefix = DEFAULT_USED_MARKER if response.default_used else ""
        return f"{prefix}{response.response_value or ''}"
    elif response.exit_code == 2:
        if response_default is not None:
            return f"[timeout - using default] {response_default}"
        return "[timeout - no response received]"
    else:
        return f"[error: {response.status}]"


def strip_fenced_code_blocks( text: str ) -> str:
    """
    Strip triple-backtick fenced code blocks from text.

    Used by _notify_impl to clean up conv-mode auto-narration messages
    before TTS — code is universally bad voice content. Per design doc
    Phase 3 spec.

    Requires:
        - text is a string (or empty)

    Ensures:
        - Returns text with all ```lang...``` blocks removed (any language tag)
        - Preserves single-backtick inline `code` spans (those are fine for TTS)
        - Returns empty string if input is None or empty
        - Multiple consecutive blocks all stripped
        - Idempotent

    Args:
        text: Markdown-formatted text potentially containing fenced code

    Returns:
        str: Text with fenced code blocks stripped
    """
    if not text: return ""
    import re
    # Match triple-backtick code blocks: optional language tag on the same
    # line as the opening fence, then content (lazy across newlines via
    # DOTALL), then a closing fence. Trailing whitespace/newline consumed
    # so consecutive blocks don't leave gaps.
    return re.sub( r"```[^\n`]*\n.*?\n```\s*", "", text, flags=re.DOTALL )


# ── The return-side witness (row 03355649) ────────────────────────────────────
# THE DEFECT THIS ANSWERS. A notify() delivered its message and then never
# returned; the harness reported "timed out after 660s" for work that had
# succeeded 30 seconds in. Measured across the fleet's hook log: 12,420 notify
# calls, 1,717 of them (13.8%) with a PreToolUse and no PostToolUse ever, against
# 0.27% for get_session_info and 2.60% for task_query. Of 414 such calls since
# 2026-08-20, 411 have a notifications row inside a 125s window — 239 already
# `delivered` — versus 15.8% for a shuffled-session control. So the message lands
# and the CALL is what goes missing.
#
# WHAT COULD NOT BE ANSWERED WITHOUT THIS. Every wait inside the handler is
# bounded — `_wait_for_sender_id` caps at 12s, and notify_user_async's worst case
# is 24s at the default request timeout and 267s at the model's maximum allowed
# value of 30 — so the handler cannot itself produce 660s. That says where the
# hang ISN'T. It cannot say whether the handler RETURNED and the response was
# lost downstream, because nothing recorded the return. `ask_yes_no` already logs
# `mcp_ask_yes_no` on its way out; notify logged nothing at all.
#
# THE DISCRIMINATOR. Two events sharing a `call_id`. Next occurrence:
#   entry, no return   → the handler is where it hangs
#   entry AND return, but no PostToolUse → the handler finished and the response
#                                          was lost above it
# One grep of hook-events.jsonl answers a question that has cost two sessions a
# database lookup each. The log write is best-effort and swallows its own errors,
# so an instrument can never break the path it measures.
def _notify_impl(
    message: str,
    notification_type: str = "progress",
    priority: str = "medium",
    abstract: Optional[ str ] = None,
    job_id: Optional[ str ] = None,
    suppress_ding: bool = False,
    progress_group_id: Optional[ str ] = None,
    session_name: Optional[ str ] = None,
    _internal_call: bool = False
) -> str:
    """
    Time `_notify_send` and record BOTH ends of the call.

    Ensures:
        - returns exactly what `_notify_send` returns, unchanged
        - an exception propagates unchanged, with a return event recorded first
        - the entry event carries the payload SIZE (never the payload), so row
          03355649's untested payload-size hypothesis becomes answerable from the
          log instead of needing a live reproduction
        - logging never raises and never changes the outcome
    """
    call_id = _uuid.uuid4().hex[ :12 ]
    _log_notify_event( "entry", call_id, None, None,
                       payload_bytes=_payload_bytes( message, abstract ) )
    started = time.monotonic()
    try:
        result = _notify_send(
            message=message, notification_type=notification_type, priority=priority,
            abstract=abstract, job_id=job_id, suppress_ding=suppress_ding,
            progress_group_id=progress_group_id, session_name=session_name,
            _internal_call=_internal_call )
    except BaseException as e:
        _log_notify_event( "raised", call_id, _elapsed_ms( started ), type( e ).__name__ )
        raise
    _log_notify_event( "return", call_id, _elapsed_ms( started ), result )
    return result


def _elapsed_ms( started ):
    """Ensures: whole milliseconds since the `time.monotonic()` reading `started`."""
    return int( ( time.monotonic() - started ) * 1000 )


def _payload_bytes( message, abstract ):
    """
    The size of what this call is carrying — LENGTH ONLY, never the content.

    WHY IT IS HERE (row 03355649). The row's own hypothesis: "WHETHER it
    correlates with payload size. This call carried a long `abstract` (a table
    plus several paragraphs). That is a hypothesis with one data point behind it
    and no negative control." Nothing in the hook log records a payload or a
    size, so the hypothesis could not be tested retrospectively against the 1,717
    calls already on record. Stamping the size makes it answerable going forward
    with a grep instead of a reproduction.

    SIZE, NOT CONTENT, DELIBERATELY. hook-events.jsonl is already 66 MB and every
    session in the fleet writes to it. Logging message bodies to answer a sizing
    question would cost more than the question is worth, and would put user-facing
    announcement text into a debug log nobody scoped for it.

    Requires:
        - message / abstract are strings or None

    Ensures:
        - returns the combined UTF-8 byte length of message and abstract
        - a None or non-string part counts as zero rather than raising
        - never raises
    """
    # No try/except here on purpose: `isinstance( part, str )` already guarantees
    # `.encode( "utf-8" )` succeeds, so a belt would be an unreachable branch
    # needing a pragma to explain itself. Fewer branches beats a justified one.
    total = 0
    for part in ( message, abstract ):
        if isinstance( part, str ): total += len( part.encode( "utf-8" ) )
    return total


def _log_notify_event( phase, call_id, elapsed_ms, outcome, payload_bytes=None ):
    """
    Append one `mcp_notify` line to hook-events.jsonl.

    Ensures:
        - writes { phase, call_id, elapsed_ms, outcome, payload_bytes }; each
          optional field is omitted when it does not apply — elapsed_ms and
          outcome are absent on the ENTRY event, where neither exists yet, and
          payload_bytes is absent on the RETURN event, where it would be a
          duplicate of the entry that shares its call_id
        - `outcome` is truncated to 120 chars — the status string is a label, and
          an instrument must not become the thing that bloats the log it writes to
        - NEVER raises. An instrument that can break the path it measures is worse
          than no instrument.
    """
    try:
        extra = { "phase": phase, "call_id": call_id }
        if elapsed_ms   is not None: extra[ "elapsed_ms" ]    = elapsed_ms
        if outcome      is not None: extra[ "outcome" ]       = str( outcome )[ :120 ]
        if payload_bytes is not None: extra[ "payload_bytes" ] = payload_bytes
        log_to_stream( "mcp_notify", {}, extra=extra )
    except Exception:
        pass


def _notify_send(
    message: str,
    notification_type: str = "progress",
    priority: str = "medium",
    abstract: Optional[ str ] = None,
    job_id: Optional[ str ] = None,
    suppress_ding: bool = False,
    progress_group_id: Optional[ str ] = None,
    session_name: Optional[ str ] = None,
    _internal_call: bool = False
) -> str:
    """
    Core notify implementation — plain Python function callable from anywhere.

    FastMCP 2.x @mcp.tool converts decorated functions into FunctionTool objects
    that are NOT callable as regular Python functions. This private function holds
    the actual logic so that both the MCP tool and internal callers (e.g.,
    set_session_topic) can invoke it directly.

    Phase 3 of the conv-mode three-layer enforcement plan adds a bidirectional
    gate: when conv mode is active for the calling session, force suppress_ding
    + priority=high + strip fenced code blocks; when conv mode is OFF and the
    sender is a CC session asking for suppress_ding, invert it so the user
    hears an audible cross-talk cue. Internal callers bypass via
    _internal_call=True.
    See: src/rnd/v0.1.7/2026.04.30-conv-mode-three-layer-enforcement/01-design.md

    Requires:
        - message is a non-empty string
        - notification_type is a valid NotificationType value
        - priority is a valid NotificationPriority value

    Ensures:
        - Returns a status string (never raises)
        - Sends notification via HTTP POST to /api/notify
        - Conv-mode gate applied unless _internal_call=True

    Args:
        message: What to announce to the user
        notification_type: "task", "progress", "alert", "custom", or "session_topic"
        priority: "low", "medium", "high", or "urgent"
        abstract: Optional supplementary context (plan details, URLs, markdown)
        job_id: Optional agentic job ID for routing to job cards (e.g., "dr-a1b2c3d4")
        suppress_ding: Suppress notification sound while still speaking via TTS (default False)
        progress_group_id: Optional progress group ID (pg-{8 hex chars}) for in-place DOM updates.
            Notifications sharing this ID update a single element instead of appending new ones.
        session_name: Optional human-readable session name for UI header display.
            When set, updates the sender-session-name span in notification history card.
        _internal_call: When True, bypass the conv-mode gate entirely (params pass through
            unchanged). Used by internal callers like set_session_topic that have their own
            specific param requirements.

    Returns:
        Delivery status message
    """
    logger.debug( f"_notify_impl() called: {message[:50]}..." )

    # ── Phase 3 bidirectional conv-mode gate ────────────────────────────────
    # Per src/rnd/v0.1.7/2026.04.30-conv-mode-three-layer-enforcement/01-design.md §2.5
    if not _internal_call:
        # Dynamic session_id resolution (matches _flip_speakerphone pattern)
        try:
            cc_meta = _get_cc_metadata()
            sid = cc_meta.get( "stable_session_id" ) or cc_meta.get( "session_id" ) or SESSION_ID
        except Exception:
            sid = SESSION_ID

        try:
            from lupin_cli.claude_code.hooks.lib.session_bridge import get_speakerphone
            active = get_speakerphone( sid ) if sid else False
        except Exception:
            active = False

        sender = _wait_for_sender_id() or ""

        if active:
            # Speakerphone ON — enforce speakerphone-render params
            suppress_ding = True
            # 🔴 LIFT ONLY A *VALID* PRIORITY (row e2099400, 2026-08-26).
            # This used to read `if priority not in ( "high", "urgent" )`, which swallowed
            # an INVALID value too: a typo'd `priority="urgnet"` was rewritten to "high",
            # sailed through the NotificationPriority(...) validation below because the bad
            # value no longer existed, and the call reported "Notification sent (delivered)".
            # Measured: caller asks "not-a-priority" → request ships NotificationPriority.HIGH.
            # A priority nobody chose is worse than a rejected call, so an unrecognised value
            # now falls through to the validation below and is REPORTED.
            if priority in _SPEAKERPHONE_LIFTABLE_PRIORITIES:
                priority = "high"
            message = strip_fenced_code_blocks( message )
            logger.debug( "_notify_impl speakerphone ON: forced priority=high, suppress_ding=True, stripped fenced code" )
        elif sender.startswith( "claude.code@" ) and suppress_ding:
            # Speakerphone OFF + CC sender + caller asked for silent TTS.
            # Mode-conditional cross-talk leak cue (Phase 4 of solo/chorus refactor):
            # - SOLO: inversion fires — only one session can hold speakerphone at a time,
            #   so a "silent TTS from a phone-mode session" is a leak symptom worth flagging
            #   audibly. Force ding ON so user knows this session leaked.
            # - CHORUS: passthrough — multiple sessions legitimately call notify() with
            #   suppress_ding=True (it's the normal pattern when a session is in phone mode
            #   but a sibling session is in speakerphone). No leak; no inversion.
            try:
                import cosa.utils.util as _cu
                _tts_mode = _cu.get_tts_interaction_mode()
            except Exception:
                _tts_mode = "chorus"
            if _tts_mode == "solo":
                suppress_ding = False
                logger.info( f"_notify_impl solo cross-talk cue: suppress_ding inverted for {sender}" )
            else:
                logger.debug( f"_notify_impl chorus passthrough: suppress_ding preserved for {sender}" )

    try:
        request = AsyncNotificationRequest(
            message=message,
            notification_type=NotificationType( notification_type ),
            priority=NotificationPriority( priority ),
            sender_id=_wait_for_sender_id(),
            abstract=_normalize_abstract( abstract ),
            job_id=job_id,
            suppress_ding=suppress_ding,
            progress_group_id=progress_group_id,
            session_name=session_name
        )
    except ( ValidationError, ValueError ) as e:
        logger.error( f"Validation error: {e}" )
        return f"[validation error: {e}]"

    # Assign the idempotency key HERE (before send) so a durable-outbox retry
    # reuses the SAME key → the server de-dups a maybe-already-delivered message.
    if request.idempotency_key is None:
        request = request.model_copy( update={ "idempotency_key": str( _uuid.uuid4() ) } )

    # Drain-first ordering: if a backlog already exists for this session, queue
    # behind it instead of sending live (preserves FIFO order during a degraded
    # window). The fast live path resumes once the flusher drains the backlog.
    if _outbox_has_backlog():
        if _spool_failed_notify( request ):
            return "Queued (ordered behind backlog)"
        # spool disabled/failed → fall through to a live attempt

    response: AsyncNotificationResponse = notify_user_async( request=request, debug=False )

    if response.success:
        return f"Notification sent ({response.status})"
    else:
        # Durable layer (lever A): persist for background retry instead of losing it.
        if _spool_failed_notify( request ):
            return f"Queued for durable retry ({response.message})"
        return f"Failed: {response.message}"


@mcp.tool
def notify(
    message: str,
    notification_type: str = "progress",
    priority: str = "medium",
    abstract: Optional[ str ] = None,
    job_id: Optional[ str ] = None,
    suppress_ding: bool = False,
    progress_group_id: Optional[ str ] = None,
    session_name: Optional[ str ] = None,
    override_size_limitation: bool = False
) -> str:
    """
    Announce something to the user without waiting for response.

    Use this for status updates, progress reports, or FYI messages.
    The message will be converted to speech (TTS) and played to the user.
    This call returns immediately - it does not wait for acknowledgment.

    Args:
        message: What to announce to the user
        notification_type: "task", "progress", "alert", "custom", or "session_topic"
        priority: "low", "medium", "high", or "urgent"
        abstract: Optional supplementary context (plan details, URLs, markdown)
        job_id: Optional agentic job ID for routing to job cards (e.g., "dr-a1b2c3d4")
        suppress_ding: Suppress notification sound while still speaking via TTS (default False)
        progress_group_id: Optional progress group ID (pg-{8 hex chars}) for in-place DOM updates.
            Notifications sharing this ID update a single element instead of appending new ones.
        session_name: Optional human-readable session name for UI header display.
            When set, updates the sender-session-name span in notification history card.
        override_size_limitation: Default False. True sends a spoken `message` over the
            length cap (configured, default 500) knowingly; detail belongs in `abstract`,
            which has no length limit, not in speech.

    Returns:
        Delivery status message

    Examples:
        notify("Starting code analysis...", notification_type="progress")
        notify("Build completed successfully", notification_type="task")
        notify("Warning: deprecated API detected", notification_type="alert", priority="high")
        notify("Task complete", suppress_ding=True)  # TTS only, no ding
    """
    _enforce_spoken_brevity( message, override_size_limitation, field="message" )

    return _notify_impl(
        message=message,
        notification_type=notification_type,
        priority=priority,
        abstract=abstract,
        job_id=job_id,
        suppress_ding=suppress_ding,
        progress_group_id=progress_group_id,
        session_name=session_name
    )


def _error_dict( response ) -> dict:
    """
    Build the caller-facing error dict for a genuine failure.

    Requires:
        - response is a NotificationResponse from notify_user_sync

    Ensures:
        - `error` keeps the exact `error: <status>` string callers already match on
        - `detail` carries the server's OWN sentence when it sent one, so the seat
          reading this can act on it instead of guessing from a status code
        - `detail` is omitted entirely when the server said nothing

    Raises:
        - None

    Row cd283a77: `error: http_error_503` sent a manager hunting a broken verb for
    six attempts across two boots while the body read "User is offline and no
    default response provided" — the sentence that names both the cause and the fix.
    """
    out = { "error": f"error: {response.status}" }
    if response.error_detail: out[ "detail" ] = response.error_detail
    return out


@mcp.tool
@_offloaded_tool
def ask_yes_no(
    question: str,
    default: str = "no",
    timeout_seconds: int = 60,
    priority: str = "medium",
    abstract: Optional[ str ] = None,
    job_id: Optional[ str ] = None,
    override_size_limitation: bool = False,
    human_only: bool = False
) -> str:
    """
    Ask a yes/no question and get the user's response as a string. A convenience wrapper for quick binary decisions, with a third "Neither" escape hatch for when the question itself needs re-framing. The user may attach a qualifying comment to any answer via the UI.

    Returns an annotated string: "yes", "no" or "neither", optionally suffixed with "[comment: ...]", and PREFIXED with "[default used] " (the same prefix `converse` uses) when the value is a substituted default rather than something the user chose. On ANY non-answer (timeout, expiry, user offline, transport error, server error, request-validation failure) it returns the default PREFIXED with "[default used] ": this verb has no error shape, and a bare default would be indistinguishable from a keypress. A genuine keypress is returned CLEAN. A prefixed value is NOT a ruling: do not treat it as authorization. On "neither", treat the response as a signal that the question needs re-framing, not as a soft yes or no: read the comment (if present) and ask a clearer follow-up.

    Requires:
        - question is a non-empty string
        - default is "yes" or "no" (Neither is never a default; it requires an explicit user click)
        - timeout_seconds is a positive integer

    Args:
        question: The yes/no question to ask
        default: Default answer if timeout ("yes" or "no")
        timeout_seconds: How long to wait (default 60)
        priority: "low", "medium", "high", or "urgent"
        abstract: Optional supplementary context (plan details, URLs, markdown)
        job_id: Optional agentic job ID for routing to job cards (e.g., "dr-a1b2c3d4")
        override_size_limitation: Default False. True sends a spoken `question` over the length cap (configured, default 500) knowingly; detail belongs in `abstract`, which has no length limit, not in speech.

    Examples:
        response = ask_yes_no("Delete the old backups?")
        # "yes", "no" or "neither"; with a qualifier: "yes [comment: only the March ones]"; signaling re-frame: "neither [comment: ambiguous which backups]"
    """
    logger.debug( f"ask_yes_no() called: {question[:50]}..." )

    _enforce_spoken_brevity( question, override_size_limitation, field="question" )

    try:
        request = NotificationRequest(
            message=question,
            response_type=ResponseType.YES_NO,
            notification_type=NotificationType.CUSTOM,
            priority=NotificationPriority( priority ),
            timeout_seconds=timeout_seconds,
            response_default=default,
            human_only=human_only,
            sender_id=_wait_for_sender_id(),
            abstract=_normalize_abstract( abstract ),
            job_id=job_id
        )
    except ( ValidationError, ValueError ):
        return f"{DEFAULT_USED_MARKER}{default}"

    # D2 (bug f433fbae): stamp an idempotency_key so a re-POST of this same ask
    # de-dups server-side instead of minting a duplicate card.
    request = _with_idempotency_key( request )
    response: NotificationResponse = notify_user_sync( request=request, debug=False )

    if response.exit_code == 0 and response.response_value:
        raw_value = response.response_value.strip()
        answer, qualifier = extract_qualifier_comment( raw_value )
        result = format_qualified_response( answer, qualifier ) if qualifier else raw_value
        log_to_stream( "mcp_ask_yes_no", {}, extra={
            "raw_value"    : raw_value,
            "answer"       : answer,
            "qualifier"    : qualifier,
            "enriched"     : bool( qualifier ),
            "default_used" : bool( response.default_used ),
            "return_len"   : len( result )
        } )
        # exit_code == 0 is NOT proof a human acted (row e5f21fff): an OfflineEvent
        # lands here with default_used=True (notify_user_sync.py:295-303), and the
        # server can flag a substitution on a RespondedEvent. Mark it.
        if response.default_used:
            return f"{DEFAULT_USED_MARKER}{result}"
        return result

    # 🔴 THE CATCH-ALL, and it is why this verb is worse than the one row
    # e5f21fff is titled after. It swallows timeout, expiry, offline-without-a-
    # value, transport error and server error alike — there is NO error shape —
    # and returned the default as a bare "yes"/"no" indistinguishable from a
    # keypress. This verb returns a STRING, so a `default_used` flag has nowhere
    # to live without changing the return TYPE; the marker is the converse
    # pattern (:1174), and it stays inside this verb's OWN documented contract,
    # which already promises an ANNOTATED string ("yes [comment: ...]").
    #
    # ⚠️ That a genuine ERROR is still indistinguishable from a timeout here is a
    # SEPARATE defect and is NOT fixed: converse returns "[error: <status>]" and
    # never substitutes a default, so making these agree would change what this
    # verb returns on failure — a breaking contract change on a live surface.
    # Recorded on the row for Rick's ruling, deliberately not smuggled in here.
    return f"{DEFAULT_USED_MARKER}{default}"


@mcp.tool
@_offloaded_tool
def ask_multiple_choice(
    questions: list,
    timeout_seconds: int = 120,
    priority: str = "medium",
    title: Optional[ str ] = None,
    abstract: Optional[ str ] = None,
    job_id: Optional[ str ] = None,
    default: Optional[ dict ] = None,
    override_size_limitation: bool = False
) -> dict:
    """
    Ask multiple-choice questions and get the user's selection(s). Presents questions with options via TTS and UI; supports single-select (radio buttons) and multi-select (checkboxes), and the user can give a custom "Other" answer.

    READ `answered` BEFORE TREATING THE RESULT AS A DECISION. The result is {"answers": {...}, "default_used": bool, "answered": bool}, and both flags are ALWAYS present. `default_used` is True when the user TIMED OUT (your `default` was substituted) and when the user was OFFLINE (the server substituted, returning through the success branch). Reading `answers` while ignoring `answered` turns silence into consent.

    `default` covers a TIMEOUT, not an absent user: an offline user gets a 503 from the FIRST ask whether or not you passed a default, because the offline path is decided server-side against a `response_default` this verb does not send (`ask_yes_no` plumbs it). So do NOT use `default` to leave a walkthrough running with nobody at the desk; it will stop on the first question.

    Returns:
        dict with answers keyed by header, plus the provenance of those answers:
        {"answers": {"Auth method": "OAuth", "Features": ["Dark mode", "Notifications"]}, "default_used": False, "answered": True}

    Args:
        questions: List of question objects in Claude Code's AskUserQuestion format: {"question": "Which auth method?", "header": "Auth method", "multiSelect": false, "options": [{"label": "OAuth", "description": "Use OAuth2 flow"}, {"label": "JWT", "description": "Use JWT tokens"}]}
        timeout_seconds: How long to wait for response (1-600, default 120)
        priority: "low", "medium", "high", or "urgent"
        title: Optional short title for the notification
        abstract: Optional supplementary context (plan details, URLs, markdown)
        job_id: Optional agentic job ID for routing to job cards (e.g., "dr-a1b2c3d4")
        default: Optional dict keyed by question header. On timeout the result is {"answers": <default>, "default_used": True, "answered": False} instead of the error dict; it is deliberately NOT the same shape as a real answer. Keys must match question headers; values must be option labels (a string for single-select, a list of strings for multi-select). Validated at call time: a mismatch returns an error dict before the notification fires. `default=None` keeps the legacy timeout return {"error": "timeout - no response received", "timeout": True}.
        override_size_limitation: Default False. True sends a spoken `question` over the length cap (configured, default 500) knowingly; detail belongs in `abstract`, which has no length limit, not in speech.

    Examples:
        result = ask_multiple_choice([{"question": "Which database should we use?", "header": "Database", "multiSelect": False, "options": [{"label": "PostgreSQL", "description": "Relational database"}, {"label": "MongoDB", "description": "Document database"}]}])
        # {"answers": {"Database": "PostgreSQL"}, "default_used": False, "answered": True}

        result = ask_multiple_choice(questions=[{"question": "Which database should we use?", "header": "Database", "multiSelect": False, "options": [{"label": "PostgreSQL"}, {"label": "MongoDB"}]}], default={"Database": "PostgreSQL"})
        # on timeout: {"answers": {"Database": "PostgreSQL"}, "default_used": True, "answered": False}
    """
    # Validate BEFORE logging. `len( questions )` on the line above this guard
    # raised TypeError for a null/unsized argument, so the guard right below it
    # was unreachable for exactly the input it was written to reject — the tool
    # crashed instead of returning its error dict.
    if not questions or not isinstance( questions, list ):
        return { "error": "questions must be a non-empty list" }

    logger.debug( f"ask_multiple_choice() called with {len( questions )} questions" )

    _enforce_spoken_brevity( questions, override_size_limitation, field="questions" )

    # Build TTS-friendly message from questions
    tts_message = format_questions_for_tts( questions )

    # Convert questions to response_options format (camelCase -> snake_case)
    response_options = convert_questions_for_api( questions )

    # Pre-call validation: if default provided, ensure it's structurally valid
    # against the questions schema so we fail loudly at call time, not at timeout.
    if default is not None:
        if not isinstance( default, dict ):
            return { "error": f"default must be a dict, got {type( default ).__name__}" }
        try:
            _validate_multiple_choice_default( default, questions )
        except ValueError as e:
            return { "error": f"default validation error: {e}" }

    # D1 (bug f433fbae) — plumb a server-side response_default so an OFFLINE
    # user does not 503. ask_yes_no has always passed its string default here
    # (:1528); the MULTIPLE_CHOICE path omitted it, so notifications.py raised
    # HTTPException(503, "User is offline and no default response provided")
    # whenever is_connected read False — including the FALSE-offline window right
    # after a server bounce wipes the in-memory ws_manager, i.e. a user at the
    # keyboard. Serialized as the SAME shape _parse_multiple_choice_response
    # expects ({"answers": <default>}), so if the server substitutes it on the
    # offline path it round-trips into answers verbatim. None when no caller
    # default — the honest 503 stays for "offline and no safe default to use".
    import json
    response_default = json.dumps( { "answers": default } ) if default is not None else None

    try:
        request = NotificationRequest(
            message=tts_message,
            response_type=ResponseType.MULTIPLE_CHOICE,
            notification_type=NotificationType.CUSTOM,
            priority=NotificationPriority( priority ),
            timeout_seconds=timeout_seconds,
            title=title,
            sender_id=_wait_for_sender_id(),
            response_options=response_options,
            response_default=response_default,
            abstract=_normalize_abstract( abstract ),
            job_id=job_id
        )
    except ( ValidationError, ValueError ) as e:
        logger.error( f"Validation error: {e}" )
        return { "error": f"validation error: {e}" }

    # D2 (bug f433fbae): stamp an idempotency_key so a re-POST of this same ask
    # de-dups server-side instead of minting a duplicate card.
    request = _with_idempotency_key( request )
    response: NotificationResponse = notify_user_sync( request=request, debug=False )

    if response.exit_code == 0:
        # 🔴 DROP SITE 1 of 2 (row e5f21fff) — and the one nobody filed.
        # exit_code == 0 is NOT proof a human acted. notify_user_sync.py:295-303
        # maps an OfflineEvent to exit_code=0 / default_used=True, commented
        # "Offline with default = success", so a PROVABLY ABSENT user returns
        # through this success branch, is parsed as an answer, and never reaches
        # the is_timeout branch below. The filed one-line fix at that branch
        # cannot touch this path. A RespondedEvent can also carry a server-side
        # default_used=True. `response.default_used` is the server's truth here
        # and it is the right one to forward.
        return _stamp_answer_provenance(
            _parse_multiple_choice_response( response.response_value ),
            default_used = bool( response.default_used ),
        )

    # Timeout / expiry — the user did not answer within the window. This must
    # cover BOTH notify_user_sync outcomes that mean "no answer in time":
    #   * exit_code == 2 (request_timeout, or a server-side expired-with-default)
    #   * exit_code == 1 with status "expired_no_default" — the MULTIPLE_CHOICE
    #     path NEVER plumbs a server-side response_default, so a genuine expiry
    #     ALWAYS lands here (is_timeout=True). Keying default application on
    #     exit_code == 2 alone (the original bug d13a3a30) dropped the caller's
    #     `default` dict on every real expiry and leaked
    #     {"error": "error: expired_no_default"} — the documented contract
    #     promised {"answers": <default>}. response.is_timeout is True for every
    #     timeout/expiry and False for genuine transport/server errors, so it is
    #     the correct discriminator across both exit codes.
    if response.is_timeout:
        if default is not None:
            # 🔴 DROP SITE 2 of 2 (row e5f21fff) — the filed one.
            # `default_used=True` here is a CLIENT-side truth: THIS function is
            # substituting the caller's `default` dict. It is deliberately NOT
            # `response.default_used`, which is FALSE on this path — the
            # MULTIPLE_CHOICE path never plumbs a server-side response_default
            # (see the comment above), so the server never substituted anything
            # and its flag says so. Forwarding the server's False here would
            # stamp `default_used: false` onto a defaulted answer, which is worse
            # than dropping it: it would assert the opposite of what happened.
            return { "answers": default, "default_used": True, "answered": False }
        return { "error": "timeout - no response received", "timeout": True }

    # Genuine error (connection, HTTP, stream, unexpected) — surface the status
    # so real failures stay visible rather than being masked by the default,
    # AND the server's reason with it (row cd283a77).
    return _error_dict( response )


def _stamp_answer_provenance( payload: dict, default_used: bool ) -> dict:
    """
    Stamp a dict-shaped ask response with whether a HUMAN actually answered.

    Row `e5f21fff`: a substituted default returned in the same shape as a real
    selection launders silence into consent. `default_used` is the only bit that
    separates "the user decided" from "the user was not there", and both MCP
    return sites discarded it — so a timeout, and an offline user, each read as a
    ruling. Five ratified decisions in one morning carry a permanent provenance
    caveat because the information was gone by the time anyone asked.

    Both keys are ALWAYS present on an answer-bearing payload, including an
    explicit `default_used: False` on a genuine selection (D4). An ABSENT key
    would leave a caller reading `.get("default_used")` unable to tell "the user
    answered" from "an older server that never sent the field" — a null that
    reads like a negative.

    `answered` is the affirmative twin, so the common check is a positive read
    (`if result["answered"]`) rather than a negation a reader can drop.

    ⚠️ THIS IS A DETECTION AID, NOT A PREVENTION. A consumer that ignores both
    keys still reads `answers` and still launders. Making a non-answer
    STRUCTURALLY un-mistakable — the answer key absent entirely — is a breaking
    contract change on a live agent-facing surface and is Rick's to rule.

    Requires:
        - payload is the dict returned by a response parser
        - default_used is a bool

    Ensures:
        - an error payload (carrying "error") is returned UNTOUCHED — provenance
          describes an answer, and an error is not one
        - otherwise returns the payload with `default_used` and `answered` set,
          `answered` always the negation of `default_used`
        - never raises; the input dict is not mutated
    """
    if "error" in payload:
        return payload
    return { **payload, "default_used": default_used, "answered": not default_used }


def _validate_multiple_choice_default( default: dict, questions: list ) -> None:
    """
    Validate a ``default`` dict against the ``questions`` schema for
    ``ask_multiple_choice``. Raises ``ValueError`` on any mismatch so the
    caller fails loudly at call time rather than at timeout.

    Requires:
        - default is a dict (caller has type-checked)
        - questions is a non-empty list of question dicts, each with "header"
          and "options" keys

    Ensures:
        - returns None if default is structurally valid against questions
        - raises ValueError with a precise message on first mismatch:
          * default key does not match any question header
          * default value type-wrong for the question's ``multiSelect`` flag
            (list required when multiSelect, string required when not)
          * default label does not match any option label in the question

    Args:
        default: dict keyed by question header; values are strings (single-select)
            or list of strings (multi-select), each matching an option label
        questions: the ``ask_multiple_choice`` questions list against which the
            default is being validated
    """
    headers_to_questions = { q[ "header" ]: q for q in questions }
    for header, value in default.items():
        if header not in headers_to_questions:
            raise ValueError(
                f"default header '{header}' does not match any question header "
                f"in questions list (available: {list( headers_to_questions.keys() )})"
            )
        question      = headers_to_questions[ header ]
        option_labels = { opt[ "label" ] for opt in question.get( "options", [] ) }
        multi_select  = question.get( "multiSelect", False )

        if multi_select:
            if not isinstance( value, list ):
                raise ValueError(
                    f"default for multi-select question '{header}' must be a list, "
                    f"got {type( value ).__name__}"
                )
            for label in value:
                if label not in option_labels:
                    raise ValueError(
                        f"default label '{label}' for question '{header}' does not "
                        f"match any option (available: {sorted( option_labels )})"
                    )
        else:
            if not isinstance( value, str ):
                raise ValueError(
                    f"default for single-select question '{header}' must be a string, "
                    f"got {type( value ).__name__}"
                )
            if value not in option_labels:
                raise ValueError(
                    f"default label '{value}' for question '{header}' does not match "
                    f"any option (available: {sorted( option_labels )})"
                )


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
@_offloaded_tool
def ask_open_ended_batch(
    questions: list,
    timeout_seconds: int = 300,
    priority: str = "high",
    title: Optional[ str ] = None,
    abstract: Optional[ str ] = None,
    job_id: Optional[ str ] = None,
    override_size_limitation: bool = False
) -> dict:
    """
    Ask multiple open-ended questions at once and get all answers as a dict.

    Presents all questions on a single screen with text input + mic button per question.
    User answers all questions and submits once. Much faster than asking one at a time.

    Args:
        questions: List of question objects, each with "question" and "header" keys.
            Optional "default_value" key pre-fills the text input so the user can
            accept the default by simply hitting Submit All:
            [
                {"question": "What topic would you like to research?", "header": "Topic"},
                {"question": "Would you like to set a budget limit?", "header": "Budget", "default_value": "no limit"},
                {"question": "Who is the target audience?", "header": "Audience", "default_value": "academic"}
            ]
        timeout_seconds: How long to wait for response (1-600, default 300)
        priority: "low", "medium", "high", or "urgent"
        title: Optional short title for the notification
        abstract: Optional supplementary context (plan details, URLs, markdown)
        job_id: Optional agentic job ID for routing to job cards (e.g., "dr-a1b2c3d4")
        override_size_limitation: Default False. True sends a spoken `question` over the
            length cap (configured, default 500) knowingly; detail belongs in `abstract`,
            which has no length limit, not in speech.

    Returns:
        dict with answers keyed by header:
        {
            "answers": {
                "Topic": "quantum computing",
                "Budget": "no limit",
                "Audience": "graduate students"
            }
        }

    Examples:
        result = ask_open_ended_batch([
            {"question": "What topic?", "header": "Topic"},
            {"question": "What budget?", "header": "Budget"}
        ])
        # Returns: {"answers": {"Topic": "quantum computing", "Budget": "10"}}
    """
    # Validate BEFORE logging. `len( questions )` on the line above this guard
    # raised TypeError for a null/unsized argument, so the guard right below it
    # was unreachable for exactly the input it was written to reject — the tool
    # crashed instead of returning its error dict.
    if not questions or not isinstance( questions, list ):
        return { "error": "questions must be a non-empty list" }

    logger.debug( f"ask_open_ended_batch() called with {len( questions )} questions" )

    _enforce_spoken_brevity( questions, override_size_limitation, field="questions" )

    # Build TTS-friendly message from questions
    tts_message = format_open_ended_batch_for_tts( questions )

    # Convert questions to response_options format
    response_options = convert_open_ended_batch_for_api( questions )

    try:
        request = NotificationRequest(
            message          = tts_message,
            response_type    = ResponseType.OPEN_ENDED_BATCH,
            notification_type = NotificationType.CUSTOM,
            priority         = NotificationPriority( priority ),
            timeout_seconds  = timeout_seconds,
            title            = title,
            sender_id        = _wait_for_sender_id(),
            response_options = response_options,
            abstract         = _normalize_abstract( abstract ),
            job_id           = job_id
        )
    except ( ValidationError, ValueError ) as e:
        logger.error( f"Validation error: {e}" )
        return { "error": f"validation error: {e}" }

    # D2 (bug f433fbae): stamp an idempotency_key so a re-POST of this same ask
    # de-dups server-side instead of minting a duplicate card.
    request = _with_idempotency_key( request )
    response: NotificationResponse = notify_user_sync( request=request, debug=False )

    if response.exit_code == 0:
        return _parse_open_ended_batch_response( response.response_value )
    elif response.exit_code == 2:
        return { "error": "timeout - no response received", "timeout": True }
    else:
        return _error_dict( response )


def _parse_open_ended_batch_response( response_value: Optional[ str ] ) -> dict:
    """
    Parse the response from an open-ended batch notification.

    Expects JSON string like: {"answers": {"Topic": "quantum computing", "Budget": "10"}}

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
        logger.warning( f"Could not parse open-ended batch response: {e}" )
        return { "answers": { "response": response_value } }


@mcp.tool
def set_session_topic( topic: str ) -> dict:
    """
    Set the current session's topic/description for context in stop hook notifications.

    The topic appears in the "Continue Session?" notification abstract so users
    know WHAT they'd be continuing. Call this at session start, after plan
    approval, or when switching tasks.

    The full topic is stored in the bridge file. For UI propagation, topics
    longer than 64 characters are truncated with "..." because the notification
    header has minimal display space.

    Args:
        topic: Brief description of current work (e.g., "Bug Fix: WS queue crash")

    Returns:
        dict with status and the topic that was set
    """
    import json

    meta        = _get_cc_metadata()
    bridge_path = meta.get( "_bridge_path" )
    if not bridge_path:
        return { "status": "error", "reason": "No bridge file found" }

    try:
        with open( bridge_path ) as f:
            data = json.load( f )
        data[ "session_topic" ] = topic
        if not atomic_write_json( bridge_path, data ):
            return { "status": "error", "reason": f"bridge write failed for {bridge_path}" }

        # Also push to notification UI for real-time header update
        # Truncate session_name for UI display (max 64 chars)
        MAX_SESSION_NAME = 64
        if len( topic ) > MAX_SESSION_NAME:
            display_topic = topic[ :MAX_SESSION_NAME - 3 ] + "..."
        else:
            display_topic = topic

        result = _notify_impl(
            message           = display_topic,
            notification_type = "session_topic",
            priority          = "low",
            session_name      = display_topic,
            suppress_ding     = True,
            _internal_call    = True   # Bypass conv-mode gate per Phase 3 design doc
        )
        ui_ok = not ( result.startswith( "[validation error" ) or result.startswith( "Failed:" ) )

        if not ui_ok:
            logger.warning( f"set_session_topic() UI push failed: {result}" )

        return { "status": "ok", "topic": topic, "ui_push": "ok" if ui_ok else result }
    except Exception as e:
        return { "status": "error", "reason": str( e ) }


@mcp.tool
def get_session_info() -> dict:
    """
    Get current session identification and server info.

    Returns:
        dict with project name, session_id, sender_id, server_url, version,
        speakerphone_on flag, claude_code metadata from the session bridge,
        and voice_persona dict (None if allocation failed; otherwise
        {name, voice_id, icon, color, borrowed, display_name?})
    """
    resolved_sender = _wait_for_sender_id()
    # Resolve the global TTS interaction mode (solo | chorus) so the consumer
    # (e.g. Claude) knows which cross-session semantics apply. Fail-closed to
    # "chorus" (the new operational default per the 2026-05-12 override).
    try:
        import cosa.utils.util as _cu
        _tts_mode = _cu.get_tts_interaction_mode()
    except Exception:
        _tts_mode = "chorus"
    info = {
        "project"              : PROJECT,
        "project_source"       : _PROJECT_SOURCE,
        "session_id"           : SESSION_ID,
        "sender_id"            : resolved_sender,
        "server_url"           : SERVER_URL,
        "version"              : __version__,
        "speakerphone_on"      : False,
        "tts_interaction_mode" : _tts_mode
    }

    # Include CC session bridge metadata when available
    try:
        cc_meta = _get_cc_metadata()
        info[ "claude_code" ] = _session_info_payload( cc_meta )
        # Read speakerphone_on from the same bridge metadata
        info[ "speakerphone_on" ] = bool( cc_meta.get( "speakerphone_on", False ) )
        # voice_persona stamped into the bridge by register_session.py Phase 4.5;
        # None if allocation failed (server falls back to "Sam" for TTS, per design).
        # Shape per src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/01-design.md:
        # {name, voice_id, icon, color, borrowed, display_name?}
        info[ "voice_persona" ] = cc_meta.get( "voice_persona" )
    except Exception:
        pass

    return info


@mcp.tool
def self_respin( memento_path: str, memento_nonce: str, delay_seconds: int = 20, cycle_window_seconds: int = 300 ) -> dict:  # pragma: no cover - live MCP boundary; all logic + branches are covered in self_respin_core
    """
    Self-re-spin: schedule a `/clear` into THIS session's OWN pane so it rehydrates as the same seat (same session id, tmux, persona, board, lineage). IRREVERSIBLE; every guard is inside this verb.

    BEFORE CALLING: generate the nonce uuid, then write your memento with it in ONE call:

        python3 $PLANNING_IS_PROMPTING_ROOT/workflow/scripts/memento_io.py write --slot root --persona <you> --session-id <from get_session_info()> --self-respin-nonce <uuid>

    Pass that uuid as `memento_nonce`. Do NOT stamp it afterwards by hand or via self_respin_core.stamp_nonce_into (retired). `write` exits 5 if record and mirror disagree.

    Already wrote your root memento this session? `write` refuses it as immutable (exit 3). Use `amend`, with the nonce line as the LAST line of the amendment body you pipe in (no flag needed). amend keeps record, mirror and pointer in step; the nonce proves only the amendment is fresh.

    The verb checks the exact nonce, a fresh timestamp, and a body with substance beyond the nonce line; a stale, partial or nonce-only memento aborts, and NOTHING is scheduled unless the memento verified AND the ask resolved yes (or default-yes) AND the observer marker is durable. It then asks you yes/no on the human surface, DEFAULTING TO YES so an absent user does not cost the fleet a manager (offline or timeout proceeds; a real "no" stops it), writes the observer's liveness marker and a one-shot fire token, and schedules a detached `/clear` that consumes the token. The session id comes from the local bridge, never an argument, so it can only aim at your own pane; nothing pre-supplies the confirmation or targets another session.

    Requires: your memento, written this cycle with the nonce line (`memento_path`; `memento_nonce` is its uuid); `delay_seconds`, the detached sleep before the clear; `cycle_window_seconds`, the oldest nonce allowed.

    Ensures:
        - returns { status: scheduled|declined|aborted, reason, marker_path, fire_token_path, expected_return_by }
        - makes NO task-store calls (the observer owns done-state)
    """
    refusal = _refuse_borrowed_identity( "self_respin" )
    if refusal is not None: return refusal

    from dataclasses import asdict
    from lupin_mcp.self_respin_core import self_respin_from_bridge, _live_own_pressure, resolve_own_identity

    result = self_respin_from_bridge(
        memento_path, memento_nonce,
        delay_seconds        = delay_seconds,
        cycle_window_seconds = cycle_window_seconds,
        identity_fn          = lambda: resolve_own_identity( _get_cc_metadata, SESSION_ID ),
        pressure_fn          = _live_own_pressure,
    )
    return asdict( result )


def _flip_speakerphone( active: bool ) -> dict:
    """
    Internal helper: flip speakerphone_on for this session.

    Routes through the canonical HTTP endpoint POST
    /api/cosa-voice/speakerphone/{session_id} when reachable, so:
      - Mutual exclusion across the user's sessions is enforced (any other
        active session is displaced atomically).
      - The speakerphone_changed WebSocket event broadcasts to all of
        the user's connected browser tabs for real-time UI sync.
      - Activate/deactivate flows behave identically whether triggered from
        the UI button, voice phrase, slash command, or this MCP tool.

    Falls back to a direct bridge-file write (today's pre-2026-04-28 behavior)
    when the HTTP endpoint is unreachable — preserves voice/MCP availability
    when the FastAPI server is offline. Degraded mode: no broadcast, no mutex
    enforcement; UI sync deferred until next page reload.

    Resolves session_id by stable_session_id (preferred for /clear-resistance),
    falling back to session_id then SESSION_ID prefix.

    Requires:
        - active is a bool

    Ensures:
        - Returns dict with status="ok", session_id, speakerphone_on=<new state>
          on success (whether via HTTP or fallback)
        - Returns dict with status="error" and reason on failure
        - Never raises exceptions
        - When HTTP succeeded: returned dict includes "displaced_sessions" (list)
          and "ui_sync" = "broadcast"
        - When fallback was used: returned dict includes "ui_sync" = "deferred (HTTP unreachable)"
    """
    try:
        cc_meta = _get_cc_metadata()
        sid = cc_meta.get( "stable_session_id" ) or cc_meta.get( "session_id" ) or SESSION_ID
    except Exception:
        sid = SESSION_ID

    if not sid:
        return { "status": "error", "reason": "No session_id available" }

    # ── Primary path: canonical HTTP endpoint ─────────────────────────────
    try:
        from lupin_cli.claude_code.hooks.lib.hook_credentials import get_hook_credentials
        project = _get_project()
        email, password = get_hook_credentials( project )

        # Login to obtain a JWT (each call — no caching for low-frequency toggles)
        login_resp = requests.post(
            f"{SERVER_URL}/auth/login",
            json    = { "email": email, "password": password },
            timeout = _SERVER_TRANSPORT_TIMEOUT_SECONDS
        )
        if login_resp.status_code != 200:
            raise RuntimeError( f"login HTTP {login_resp.status_code}" )

        access_token = login_resp.json()[ "tokens" ][ "access_token" ]

        # Call the canonical endpoint
        toggle_resp = requests.post(
            f"{SERVER_URL}/api/cosa-voice/speakerphone/{sid}",
            json    = { "active": active },
            headers = { "Authorization": f"Bearer {access_token}" },
            timeout = _SERVER_TRANSPORT_TIMEOUT_SECONDS
        )
        if toggle_resp.status_code != 200:
            raise RuntimeError( f"endpoint HTTP {toggle_resp.status_code}: {toggle_resp.text[:200]}" )

        body = toggle_resp.json()
        return {
            "status"                   : "ok",
            "session_id"               : sid,
            "speakerphone_on" : bool( body.get( "active", active ) ),
            "displaced_sessions"       : body.get( "displaced_sessions", [] ),
            "ui_sync"                  : "broadcast"
        }

    except ( requests.ConnectionError, requests.Timeout, RuntimeError, KeyError, FileNotFoundError, ValueError ) as http_err:
        # ── Fallback: direct bridge write (degraded mode) ────────────────
        ok = set_speakerphone( sid, active )
        if not ok:
            return {
                "status"     : "error",
                "reason"     : f"HTTP path failed ({http_err}) AND bridge fallback failed",
                "session_id" : sid
            }
        return {
            "status"                   : "ok",
            "session_id"               : sid,
            "speakerphone_on" : active,
            "ui_sync"                  : f"deferred (HTTP unreachable: {type( http_err ).__name__})"
        }


@mcp.tool
def enable_speakerphone() -> dict:
    """
    Enter conversation mode for this session.

    USER-ONLY INITIATION (HARD RULE): Call this ONLY in direct response to an explicit user instruction: a voice phrase like "enter conversation mode" (or a close paraphrase), a typed request, or a slash command. NEVER call it on your own initiative; preemptive activation ("since this is a long task...") is forbidden. The mic is the user's to direct, not yours to grab.

    While conversation mode is on, after every assistant turn call `notify(message=<full_response_text>, suppress_ding=True, priority='high')` so the response is spoken aloud (the user is listening at a distance). Strip fenced code blocks and tool-call narration from the spoken text.

    At most one CC session at a time can hold conversation mode across the user's sessions; activating here atomically displaces any other (its UI reverts, in-flight TTS pauses, sender card unpins). State is stored in the bridge file and survives /clear within this session.

    Returns:
        dict with status, session_id, speakerphone_on=True on success; when the HTTP path is reachable, also includes "displaced_sessions" and "ui_sync"="broadcast" (other tabs sync via WebSocket immediately)
    """
    return _flip_speakerphone( True )


@mcp.tool
def disable_speakerphone() -> dict:
    """
    Exit conversation mode (revert to default notification mode) for this session.

    USER-ONLY INITIATION (HARD RULE): Call this ONLY in direct response to an
    explicit user instruction — voice phrase like "exit conversation mode" (or
    close paraphrases), typed request, or slash command. NEVER call on your own
    initiative. The user owns the toggle; you respond to it, not drive it.

    In notification mode, TTS only fires when YOU explicitly call notify(), converse(), or ask_*().

    Returns:
        dict with status, session_id, speakerphone_on=False on success
    """
    return _flip_speakerphone( False )


def _persona_error_detail( resp ) -> dict:
    """
    Extract the structured `detail` dict from a voice-persona error response.

    The allocate endpoint raises HTTPException(detail={...}) for its 422
    (not-in-pool) and 409 (occupied) cases, so the JSON body is
    `{"detail": {...}}`. Defensive: returns `{}` when the body is not JSON or
    `detail` is not a dict, so the caller's `.get()` chains stay safe.

    Requires:
        - resp is a requests.Response

    Ensures:
        - returns the `detail` dict on a well-formed error body
        - returns {} on any parse failure or non-dict `detail`
    """
    try:
        detail = resp.json().get( "detail" )
        return detail if isinstance( detail, dict ) else { }
    except ( ValueError, AttributeError ):
        return { }


def _request_persona( name: Optional[ str ] = None ) -> dict:
    """
    Internal helper: request a named voice persona, or let the server pick one.

    Routes through the canonical allocate endpoint POST
    /api/cosa-voice/voice-persona/{session_id}/allocate. Two paths:

      - `name` supplied -> sends `requested_persona_name` (strict request-or-swap)
      - `name` omitted  -> sends NO `requested_persona_name`, reaching the
                           endpoint's auto-pick mode, which selects uniformly at
                           random from the unallocated pool

    The auto-pick path exists so a session holding `voice_persona: null` can be
    healed without guessing a specific free name. Previously the parameter was
    sent unconditionally, leaving auto-pick unreachable from the MCP surface
    even though the server implemented it.

    There is intentionally NO degraded bridge-write fallback (unlike
    `_flip_speakerphone`): persona allocation must pass through the server's
    locked allocator to keep pool-occupancy accounting correct — a direct
    bridge write would risk a double allocation.

    Resolves session_id by stable_session_id (preferred for /clear-resistance),
    falling back to session_id then the SESSION_ID prefix.

    Requires:
        - name is a non-empty string, or None to request auto-pick

    Ensures:
        - On HTTP 200: returns {status:"ok", session_id, voice_persona, swapped,
          message}
        - On HTTP 422: returns {status:"not_in_pool", requested, available}
        - On HTTP 409: returns {status:"occupied", requested,
          holding_session_id, holding_persona_name, available}
        - On any other HTTP status or transport failure: returns
          {status:"error", reason, ...}
        - Never raises exceptions
    """
    # An explicitly supplied name must be a usable string — an empty or
    # whitespace-only value is a caller error, NOT a request for auto-pick.
    # Auto-pick is reached by omitting the argument entirely, so that a bug
    # producing "" cannot silently allocate an arbitrary persona.
    if name is None:
        requested = None
    else:
        if not isinstance( name, str ) or not name.strip():
            return { "status": "error", "reason": "persona name must be a non-empty string" }
        requested = name.strip()

    try:
        cc_meta = _get_cc_metadata()
        sid     = cc_meta.get( "stable_session_id" ) or cc_meta.get( "session_id" ) or SESSION_ID
    except Exception:
        sid = SESSION_ID

    if not sid:
        return { "status": "error", "reason": "No session_id available" }

    try:
        from lupin_cli.claude_code.hooks.lib.hook_credentials import get_hook_credentials
        project         = _get_project()
        email, password = get_hook_credentials( project )

        # Login to obtain a JWT (each call — no caching for low-frequency swaps)
        login_resp = requests.post(
            f"{SERVER_URL}/auth/login",
            json    = { "email": email, "password": password },
            timeout = _SERVER_TRANSPORT_TIMEOUT_SECONDS
        )
        if login_resp.status_code != 200:
            return { "status": "error", "reason": f"login HTTP {login_resp.status_code}" }

        access_token = login_resp.json()[ "tokens" ][ "access_token" ]

        # Request-or-swap on the canonical allocate endpoint. Omitting
        # `requested_persona_name` entirely is what selects the server's
        # auto-pick mode — sending it as None/"" would not.
        alloc_params = { } if requested is None else { "requested_persona_name": requested }

        alloc_resp = requests.post(
            f"{SERVER_URL}/api/cosa-voice/voice-persona/{sid}/allocate",
            params  = alloc_params,
            headers = { "Authorization": f"Bearer {access_token}" },
            timeout = _SERVER_TRANSPORT_TIMEOUT_SECONDS
        )

        if alloc_resp.status_code == 200:
            body    = alloc_resp.json()
            persona = body.get( "voice_persona" ) or { }
            # On the auto-pick path `requested` is None, so the server's
            # returned name is the only source for the message.
            display = persona.get( "display_name" ) or persona.get( "name" ) or requested or "unnamed"
            return {
                "status"        : "ok",
                "session_id"    : sid,
                "voice_persona" : persona,
                "swapped"       : bool( body.get( "swapped", False ) ),
                "message"       : f"You are now {display}."
            }

        if alloc_resp.status_code == 422:
            detail = _persona_error_detail( alloc_resp )
            return {
                "status"    : "not_in_pool",
                "requested" : detail.get( "requested", requested ),
                "available" : detail.get( "available", [] )
            }

        if alloc_resp.status_code == 409:
            detail = _persona_error_detail( alloc_resp )
            return {
                "status"               : "occupied",
                "requested"            : detail.get( "requested", requested ),
                "holding_session_id"   : detail.get( "holding_session_id" ),
                "holding_persona_name" : detail.get( "holding_persona_name" ),
                "available"            : detail.get( "available", [] )
            }

        return {
            "status" : "error",
            "reason" : f"allocate HTTP {alloc_resp.status_code}: {alloc_resp.text[:200]}"
        }

    except ( requests.ConnectionError, requests.Timeout, RuntimeError, KeyError, FileNotFoundError, ValueError ) as http_err:
        return {
            "status"     : "error",
            "reason"     : f"{type( http_err ).__name__}: {http_err}",
            "session_id" : sid
        }


@mcp.tool
def request_persona( name: Optional[ str ] = None ) -> dict:
    """
    Request a named voice persona for this session, or let the server pick one.

    USER-INITIATED ONLY (HARD RULE): Call this ONLY in direct response to an explicit user instruction, e.g. "become Mr. Radio", "switch my voice to Rachel", or a request to reclaim a persona lost after a context compaction. NEVER call it on your own initiative: the persona pool is shared, and the voice is the user's to assign. This applies equally to the no-argument form: `request_persona()` is not a self-service fix for your own null persona; it only surrenders the choice of name to the server. Ask the user first, every time.

    It swaps this session's persona atomically under a server-side lock and broadcasts a `voice_persona_assigned` WebSocket event, so every connected browser tab re-badges immediately. If another LIVE session already holds the requested name you get status "occupied"; if the name is not in the configured pool you get status "not_in_pool".

    Args:
        name: The persona name to request (e.g. "Mr. Radio", "rachel", "Tiberius"); resolution is case-insensitive. OMIT ENTIRELY to have the server pick uniformly at random from the unallocated pool (the path for healing a session whose `voice_persona` is null, where no specific name is wanted). Passing "" or "   " is a caller error, not a request for auto-pick; only omission selects it.

    Returns:
        dict, one of:
          {status:"ok", session_id, voice_persona, swapped, message}
          {status:"not_in_pool", requested, available}
          {status:"occupied", requested, holding_session_id, holding_persona_name, available}
          {status:"error", reason, ...}

    Examples:
        request_persona("Mr. Radio")   # reclaim after a bad compaction re-roll
        request_persona("Rachel")      # deliberate voice swap
        request_persona()              # user asked for a persona, any free one
    """
    return _request_persona( name )


# ============================================================================
# Manager-Spawned Reviewer Sessions (host-side tmux spawn)
# ============================================================================
#
# Thin @mcp.tool wrappers over session_spawner. The cosa-voice MCP server runs
# HOST-side (stdio subprocess of `claude`), so it — and only it — can launch
# host tmux sessions; a container REST endpoint physically cannot. The testable
# orchestration lives in session_spawner (100% unit-covered); these wrappers
# only resolve the manager's identity + config and delegate.
#
# See: src/rnd/v0.1.7/2026.05.28-manager-spawned-reviewers.md

def _spawn_script_path() -> str:  # pragma: no cover  # trivial path join; exercised live, not in units
    return os.path.join( os.environ.get( "LUPIN_ROOT", "" ), "src", "scripts", "start-cc-with-tmux.sh" )


# Why the last _spawn_config_mgr() call returned None; None when it built a manager.
# spawn_sessions reads it to say so in its return (row c9252819).
_spawn_config_error = None


def _spawn_config_mgr():
    """
    Build the ConfigurationManager the spawn path reads its INI keys from.

    Ensures:
        - returns a ConfigurationManager when LUPIN_CONFIG_MGR_CLI_ARGS resolves
        - returns None otherwise, and records the cause in `_spawn_config_error`
          so spawn_sessions can report it instead of silently spawning on the
          user default model
        - clears `_spawn_config_error` on success
    """
    global _spawn_config_error
    try:
        from cosa.config.configuration_manager import ConfigurationManager
        mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        _spawn_config_error = None
        return mgr
    except Exception as e:
        _spawn_config_error = str( e )
        logger.warning( f"[spawn] ConfigurationManager unavailable; using defaults. Reason: {e}" )
        return None


@mcp.tool
def spawn_sessions(
    count              : int,
    task_prompt        : str,
    role               : str = "reviewer",
    project            : str = "lupin",
    persona_preference = None,
    seed_memento       = None,
    dry_run            : bool = False,
    model              : Optional[ str ] = None
) -> dict:
    """
    **[SPAWN — host-side; launches real Claude Code sessions]** Spin up `count` headless reviewer sessions for this manager.

    Each child boots as a real interactive `claude` in a detached tmux session, gets its own voice persona (Extra-N when the named pool is exhausted) and reads `task_prompt` as its brief. Lineage is recorded so `dismiss_sessions` and `list_spawned_sessions` find the children. Tell children in `task_prompt` to post findings to the returned `collection_topic` (`dm-{your-persona}`). Each child spends Max-plan OAuth from the shared window: batch work is scheduled 10 AM to 1 PM EDT, see CLAUDE.md for the table; no other hours. `config_warning` in the result means the INI config manager could not be built (INI model pins and the spawn cap were NOT applied); it names the cause.

    Args:
        count: number of reviewers (1..INI `cc session spawn max reviewers`)
        task_prompt: brief template; {role} {manager_session_id} {index} and tokens you supply are substituted
        role: reviewer | author | observer | manager (fills the brief's {role})
        project: child project (cwd, CLAUDE.md)
        persona_preference: str | list, an ordered chain ("Rio,Krishna,*" or a list) sent to each child as COSA_VOICE_PERSONA_CHAIN. SessionStart takes the first FREE name, then `*` takes anything free; exhausting the chain without `*` is a LOUD failure (persona-less child, never re-allocated); siblings take successive names.
        seed_memento: a PATH to a memento record (the child opens it) or the memento CONTENT as a blob, appended verbatim to the child's prompt, never read here. Truthy also arms the re-spin wake watch.
        dry_run: print the commands, do not launch
        model: explicit model id (e.g. "claude-opus-5"). Resolution: this param, INI `cc session spawn model <role>`, INI `cc session spawn model default`, then None (no `--model` flag: the child inherits the user default).

    Returns:
        dict: { spawned:[{session_name, requested_role, status, model}], manager_persona, collection_topic, model } or {status:"error"}
    """
    _wait_for_sender_id()
    from lupin_mcp import session_spawner
    sid, persona = session_spawner.resolve_manager_identity( _get_cc_metadata(), fallback_session_id=SESSION_ID )
    config_mgr   = _spawn_config_mgr()
    cfg          = session_spawner.resolve_spawn_config( config_mgr )
    # Resolve the child's model: explicit param wins; else the per-role INI key;
    # else the INI `default` key (covers unknown/new roles); else None (no flag →
    # inherit the user default, fail-open). See ruling #2 (2026-07-02): managers
    # get Fable-5 via Rick's user default, zero code — no `manager` INI key ships;
    # the cost goal is met entirely by the worker-side flag.
    spawn_models   = cfg[ "spawn_models" ]
    resolved_model = model or spawn_models.get( role ) or spawn_models.get( "default" )
    # Stamp the re-spin's fire time BEFORE the launch, not after it. The wake
    # check ignores any receipt older than `fired_at` — that guard is what stops
    # a self_respin's own pre-clear receipt from greening its successor. Taken
    # after the launch, it also swallows a HEALTHY successor: a seat that reaches
    # its SessionStart while later seats are still being launched leaves a receipt
    # the check then reads as too old, and the manager gets a false "it never
    # woke". Earlier is always safe; later is not.
    import datetime as _dt
    respin_fired_at = _dt.datetime.now().astimezone()
    try:
        result = session_spawner.spawn_sessions(
            count, task_prompt, sid,
            script_path        = _spawn_script_path(),
            manager_persona    = persona,
            role               = role,
            project            = project,
            persona_preference = persona_preference,
            seed_memento       = seed_memento,
            spawn_cap          = cfg[ "spawn_cap" ],
            dry_run            = dry_run,
            model              = resolved_model
        )
    except ValueError as e:
        return { "status": "error", "reason": str( e ) }

    # Say so when the INI could not be read (row c9252819). Without the config manager
    # every role resolves to no model, so the child silently inherits the user default.
    if config_mgr is None:
        result[ "config_warning" ] = (
            "ConfigurationManager unavailable; INI spawn settings (per-role model, spawn cap) were NOT applied. "
            f"Cause: {_spawn_config_error}. Pass model= explicitly, or register the cosa-voice MCP "
            "with LUPIN_CONFIG_MGR_CLI_ARGS (src/scripts/install-cosa-voice.sh)."
        )

    # Arm the wake check on a RE-SPIN (row b0570b67). A spawn carrying a
    # seed_memento is a seat being brought back, and that is the path where a
    # lost wake or a stale memento produces a successor that looks idle rather
    # than broken. A fresh spawn with no seed has no prior state to lose, so it
    # is left alone. Best-effort: the watch is a diagnostic and must never turn
    # a successful spawn into a failed call.
    if seed_memento and not dry_run:
        _arm_respin_wake_watch( result, persona, respin_fired_at )
    return result


def _data_root_of_spawn_record( record ):
    """
    The data root belonging to the SEAT a spawn record describes.

    Rick ruled 2026-09-03: a seat's data is keyed on the seat's OWN repo, everywhere.
    The boot-receipt writer already does this — register_session calls
    `fleet_data_root( repo_root )` with the spawned seat's root. The wake READER did
    not: it fell through to `fleet_data_root()` with no argument, which resolves the
    FIRING MANAGER's ambient LUPIN_ROOT. The two agree whenever manager and worker
    share a repo, which is nearly always, so the disagreement only surfaces on a
    cross-repo spawn — and then the finder globs a directory the receipt was never
    written to and reports DEAD_NO_WAKE for a seat that came back fine.

    ⚠️ THIS LIVES HERE, NOT IN THE ARBITER MODULE, AND THAT IS DELIBERATE.
    `_resolve_project_root` lives in session_spawner, whose import transitively pulls
    requests / urllib3 / certifi / charset_normalizer / idna / websockets. The :8001
    arbiter runs on a deliberately light venv where a missing import kills a worker
    thread while /health still answers 200. This process already has all of it.

    Requires:
        - record is one entry from spawn_sessions' `spawned` list, or any mapping

    Ensures:
        - returns the seat's data root as a string, or None when the record names no
          project, the name resolves to no repo on this host, or anything raises
        - None is the CALLER'S signal to keep the ambient default — never an error,
          because a resolver that cannot answer must not cost the watch
        - a worktree root collapses to its parent checkout's data root, because
          `fleet_data_root` does that itself (measured: a lupin worktree and the
          lupin checkout both resolve to projects-data/lupin)
    """
    try:
        project = ( record or {} ).get( "project" )
        if not project:
            return None
        from lupin_mcp.session_spawner import _resolve_project_root
        from lupin_cli.claude_code.hooks.lib.heartbeat_hold import fleet_data_root
        repo_root = _resolve_project_root( project )
        if not repo_root:
            return None
        return str( fleet_data_root( repo_root ) )
    except Exception:
        return None


def _arm_respin_wake_watch( spawn_result, manager_persona, fired_at ):
    """Start the post-re-spin wake watches, shouting at the firing manager by DM.

    `fired_at` is passed in rather than read here: it must be stamped BEFORE the
    launch, or a successor that boots quickly leaves a receipt the check dismisses
    as predating the re-spin."""
    try:
        from cosa.agents.heartbeat_arbiter.respin_wake_check import arm_watches_for_spawn
        arm_watches_for_spawn(
            spawn_result,
            alert_fn     = lambda message: _dm_send_fn( recipient=manager_persona, body=message ),
            fired_at     = fired_at,
            base_dir_for = _data_root_of_spawn_record,
        )
    except Exception as e:
        logger.warning( f"[spawn] re-spin wake watch not armed: {e}" )


def _retire_reaped_seat_tree( session_name, cwd ):
    """
    Adapt the spawner's ( session_name, cwd ) call to retire_seat_worktree( path, seat_name ).

    Ensures:
        - returns retire_seat_worktree's outcome for the seat's own tree
        - the cwd goes in as the path and the session name as the seat, in that order
    """
    from cosa.agents.shared import seat_teardown
    return seat_teardown.retire_seat_worktree( cwd, session_name )


@mcp.tool
def dismiss_sessions( session_names: Optional[ List[ str ] ] = None, reason: str = "", write_memento: Optional[ bool ] = None, respin_personas: Optional[ List[ str ] ] = None ) -> dict:
    """
    **[REAP — host-side]** Tear down reviewer sessions THIS manager spawned.

    Kills each target's tmux session (idempotent), drops it from the lineage manifest, frees its persona slot. `session_names` names the tmux sessions; None reaps ALL sessions this manager spawned. `reason` is recorded. Returns `dismissed`, `remaining`.

    Re-spinning? Pass `respin_personas=["cheech","rio"]` for every seat you are bringing back; their rows keep owner. By default a reap moves each worker's open store rows off them (closed if receipted, else reassigned to the accountable or reaping manager), so a re-spin that omits the name leaves its rows on YOU. The result echoes `retained_owner_personas` (skipped) and `retained_unmatched` (named but not reaped in this batch: a typo protects nothing: check it). A named seat that does not return leaves its rows on a persona with no live session, and nothing checks. Retention is keyed on the persona NAME and freed names are re-granted, so a re-granted name can retain the wrong seat's rows: reap and re-spin in one batch.

    Mementos: `write_memento` (None = INI `cc session spawn write memento default`, else a bool) makes the reap prove each seat has a fresh, complete memento at `io/mementos/<persona-slug>.md` before killing it; if none is there it DMs the live child to write one and waits (bounded). Pass that path back as `seed_memento` on respawn. Read `memento_alarm` first: names each seat killed without a proven memento, `None` if none. A seat with a fresh memento is not asked again.

    `memento_outcomes` gives one verdict per seat: verified, written, skipped, or a visible failure:
    - `unproven_present`: its own memento is there but a gate failed; the reason names which (small staleness: still writing).
    - `unparseable_present`: a file with no memento-record header (a writer bypassed memento_io): read it.
    - `prior_holder_present`: names ANOTHER session, so not theirs to read; look elsewhere (usually the repo root) or accept it was never written.
    - `timeout_no_memento`: nothing on disk; unrecoverable.
    """
    refusal = _refuse_borrowed_identity( "dismiss_sessions" )
    if refusal is not None: return refusal

    import functools
    import cosa.utils.util as cu
    from lupin_mcp import session_spawner, reap_memento, reap_branch
    _wait_for_sender_id()
    sid, _ = session_spawner.resolve_manager_identity( _get_cc_metadata(), fallback_session_id=SESSION_ID )
    cfg    = session_spawner.resolve_spawn_config( _spawn_config_mgr() )
    wm     = cfg[ "write_memento_default" ] if write_memento is None else write_memento
    # MEMENTO COORDINATION (row 0a36d83d) → wire the LIVE coordinator so each reaped
    # seat is proven to have (or is asked to write, then polled for) a fresh+complete
    # memento on disk BEFORE kill — the flag was a no-op for 3 production failures.
    # partial (not a closure) so the wrapper stays fully covered even when the inner
    # dismiss_sessions is stubbed; coordinate_mementos has its own direct unit tests.
    # NO project_root is passed (row 80b930e6). It used to be cu.get_project_root() —
    # LUPIN_ROOT, which describes THIS HOST, not the seat being reaped — and the
    # coordinator applied that single root to every seat in the batch, verifying each
    # non-lupin seat against lupin's io/mementos/ and so against a DIFFERENT persona's
    # live memento. Each seat's root now comes from its own bridge cwd; a seat whose
    # repo cannot be determined is refused, never guessed at. The parameter was
    # deleted rather than left unused, so there is no root here to fall back to.
    memento_coord = functools.partial(
        reap_memento.coordinate_mementos,
        write_memento     = wm,
        window_seconds    = cfg[ "reap_memento_window_seconds" ],
        min_bytes         = cfg[ "reap_memento_min_bytes" ],
        ask_timeout_sec   = cfg[ "reap_memento_ask_timeout_sec" ],
        poll_interval_sec = cfg[ "reap_memento_poll_interval_sec" ] )
    # POST-KILL RE-CHECK (row f94ab580) → the coordinator above judges at ASK TIME,
    # and the kill is what ends a seat's chance to write. A seat still mid-write when
    # the ask window expired was GUARANTEED to be reported as having failed to write
    # one — measured on a four-seat reap, two of four alarms were that race. Same
    # verify predicate, same INI window/floor, so this look and the first can never
    # disagree about what counts as proven; it can only upgrade a seat that re-proves
    # itself, never quiet an absent memento or another session's file.
    memento_recheck = functools.partial(
        reap_memento.recheck_losing_seats,
        window_seconds    = cfg[ "reap_memento_window_seconds" ],
        min_bytes         = cfg[ "reap_memento_min_bytes" ] )
    # THE BRANCH PROBE (Cheech's design 2026-09-06, Half A) → wire the LIVE probe so a
    # reap that walks away from unmerged commits SAYS SO. Without this line the module is
    # IMPLEMENTED BUT NOT INSTALLED: `reap_branch` stays at 100% with its own suite green
    # while every production reap silently orphans branches, which is the exact defect
    # CLAUDE.md names under that heading.
    #
    # 🔴 IT DOES NOT WITHHOLD. The memento seams above refuse a kill they cannot prove;
    # this one never does. A branch is already durable in git and the worktree janitor
    # provably preserves it, so withholding would buy an immortal seat and save nothing.
    #
    # partial, not a closure, for the same reason the memento seams are: the wrapper stays
    # covered when the inner dismiss_sessions is stubbed, and probe_seat_branches has its
    # own direct unit tests.
    # NO target_branch is passed, deliberately. `reap_branch.resolve_target_branch` reads
    # $CONTEXT_TICK_TARGET_BRANCH — the SAME variable the context-pressure tick already
    # resolves the working line from — and otherwise the branch checked out in the main
    # tree. A second INI key here would be a second definition of one value, and two
    # derivations of one fact coincide until the day they do not.
    branch_probe = functools.partial( reap_branch.probe_seat_branches )
    # SEAT TEARDOWN (row 129cc96b, P3) → wire the LIVE teardown so a reaped seat's own
    # tree and merged branch go with it, instead of waiting hours for the janitor. It
    # keeps and reports any tree holding uncommitted or unmerged work.
    # LIVE reap path → wire the real reap-RECONCILE producer (d647b531) so a reaped
    # worker's non-terminal store items are auto-reconciled (close-if-receipt /
    # reassign-to-live-manager / surface) instead of orphaning. session_spawner
    # defaults reconcile_items_fn=None (hermetic for unit reaps against live :7999);
    # THIS is the production entrypoint that opts into the mutation.
    return session_spawner.dismiss_sessions(
        sid, session_names=session_names, reason=reason, write_memento=wm,
        reconcile_items_fn=session_spawner._default_reconcile_store_items,
        respin_personas=respin_personas, memento_coord_fn=memento_coord,
        memento_recheck_fn=memento_recheck, branch_probe_fn=branch_probe,
        seat_teardown_fn=_retire_reaped_seat_tree )


@mcp.tool
def list_spawned_sessions() -> dict:
    """
    **[READ — host-side]** List the sessions THIS manager spawned, on two axes: LIVENESS (probed from tmux) and IDENTITY (read from each child's bridge).

    This is not a general health check, and a live row is not proof of who sits in it. A child's SessionStart writes its persona into its own bridge after the parent recorded the seat, so a seat can be alive and nameless. Before you address a seat by persona name, read `identity_complete`; if False, `identity_warning` names every seat you must NOT address by name.

    Per row, `persona_state` is one of:
        "allocated"         bridge found, persona named; `persona` is that name
        "none"              bridge found, persona explicitly null
        "unknown_no_bridge" no bridge on disk: the child is mid-boot, or its SessionStart never completed
        "unreadable"        bridge found, persona record malformed: an instrument failure, NOT an absent persona
    `persona` is null for every state but "allocated", and a null persona always comes with a state saying why.

    Neither "none" nor "unknown_no_bridge" is a failure by itself: a healthy child goes unknown_no_bridge, then none, then allocated in about a second. Both are normal at one second old and damning at forty minutes, so read them WITH `age_seconds`.

    An identity-verified row is NOT a promise the session is addressable by DM (`dm_send` can still answer recipient_unresolved), and `identity_complete: true` says nothing about other surfaces. This roster is not the fleet's source of truth for identity.

    Returns:
        dict: { sessions:[{session_name, requested_role, status, alive, model, persona, persona_state, identity_verified, age_seconds}], count, identity_complete, identity_warning, unattributable_bridges, manager_session_id }
    """
    _wait_for_sender_id()
    from lupin_mcp import session_spawner
    sid, _ = session_spawner.resolve_manager_identity( _get_cc_metadata(), fallback_session_id=SESSION_ID )
    return session_spawner.list_spawned_sessions( sid )


# ============================================================================
# Commons Tools (Phase 1 — file-based inter-session blackboard)
# ============================================================================
#
# Per src/rnd/v0.1.7/2026.05.09-inter-session-commons/02-phase1-file-commons-design.md
# AC3 + AC4 + AC5 + AC6 + AC7. Five thin MCP shims wrapping CommonsStore +
# commons_ask. The MCP server lazily constructs a single CommonsStore rooted at
# `<LUPIN_ROOT>/io/commons` (step 6 will wire INI-driven storage path override).
# Tools redundantly check `_commons_enabled()` at call-time as defense per AC12;
# step 6/8 will wire the actual INI key.

from lupin_mcp.outbound_api_key import load_outbound_api_key, outbound_key_failure_detail as _outbound_key_failure_detail
from lupin_mcp.commons_store import CommonsStore, DEFAULT_PERSONA_NAME, DEFAULT_PERSONA_ICON, DEFAULT_PERSONA_COLOR
from lupin_mcp.commons_ask import ask_sync as _commons_ask_sync_impl, ask_async as _commons_ask_async_impl
from lupin_mcp.commons_archival import CommonsArchiver


def _mcp_outbound_api_key() -> Optional[ str ]:
    """
    Load the X-API-Key value used for MCP-server outbound HTTP calls
    to the Lupin REST API (e.g. `/api/dm/send`).

    Mirrors the canonical pattern in
    `cosa/memory/embedding_provider.py:177` `_http_api_key()` — reads
    `src/conf/keys/notification-api-claude-code-dev` via the
    project-wide `du.get_api_key()` helper. This is the same long-lived
    `ck_live_*` API key used by the embedding HTTP endpoints and the
    notification authentication infrastructure (Phase 2.5).

    Replaces the prior `os.environ.get("LUPIN_MCP_API_KEY")` lookup —
    that env var was added in commit `9bbf298` (Inter-Session DM Phase 0)
    without matching set-side wiring, so it was always None and push-mode
    silently fell through to polling. Switching to the canonical helper
    eliminated the wire-up gap entirely.

    The load itself now lives in `lupin_mcp.outbound_api_key` so the failure
    REASON survives — the bare `except Exception: return None` that used to sit
    here erased a `PermissionError` on a mode-600 key file and left every caller
    reporting a blank "X-API-Key unavailable" (lupin-host-test, 2026-07-25).

    Ensures:
        - Returns the key string if `src/conf/keys/notification-api-claude-code-dev` is readable
        - Returns None on any error, with a concrete cause recorded for
          `_outbound_key_failure_detail()` to report
        - Never raises
    """
    return load_outbound_api_key()

_commons_store_singleton:    Optional[ CommonsStore ]     = None
_commons_archiver_singleton: Optional[ CommonsArchiver ]  = None

# 6 commons INI keys, paired in src/conf/lupin-app.ini + lupin-app-splainer.ini under
# the "Inter-Session Commons" block. Loaded once at module import via ConfigurationManager;
# falls back to these hardcoded defaults if the manager is unavailable (env var unset,
# config file missing, etc.). No hot-reload — restart the MCP server to pick up changes.
_COMMONS_CONFIG_DEFAULTS = {
    "commons_enabled"                       : True,
    "commons_storage_path"                  : "/io/commons",
    "commons_retention_hours"               : 24,
    "commons_archival_interval_seconds"     : 3600,
    "commons_broadcast_rate_limit_seconds"  : 30,
    "commons_ask_sync_grace_seconds"        : 1.0,
}


def _load_commons_config() -> dict:
    """
    Resolve the 6 commons INI keys via ConfigurationManager.

    Defensive: returns `_COMMONS_CONFIG_DEFAULTS` (a copy) on any failure
    (env var unset, config-mgr exception, key missing). The MCP server keeps
    working with sensible defaults even if the larger config infrastructure
    is unavailable.

    Test-only override: when `LUPIN_COMMONS_TEST_OVERRIDE` is set to a JSON
    object, its key/value pairs replace matching `_COMMONS_CONFIG_DEFAULTS`
    entries and the normal ConfigurationManager path is bypassed. This hatch
    is used exclusively by the AC12 config-toggle subprocess test — production
    behavior is unaffected when the env var is unset.
    """
    config = dict( _COMMONS_CONFIG_DEFAULTS )
    test_override_json = os.environ.get( "LUPIN_COMMONS_TEST_OVERRIDE" )
    if test_override_json:
        try:
            import json as _json
            overrides = _json.loads( test_override_json )
            if isinstance( overrides, dict ):
                config.update( overrides )
                logger.info( f"[commons] LUPIN_COMMONS_TEST_OVERRIDE applied: {overrides}" )
                return config
            logger.warning( f"[commons] LUPIN_COMMONS_TEST_OVERRIDE is not a JSON object; ignoring: {test_override_json!r}" )
        except Exception as e:
            logger.warning( f"[commons] LUPIN_COMMONS_TEST_OVERRIDE parse failed: {e}" )
    try:
        from cosa.config.configuration_manager import ConfigurationManager
        cm = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        config[ "commons_enabled" ]                      = cm.get( "commons enabled",                      default=config[ "commons_enabled" ],                      return_type="boolean", silent=True )
        config[ "commons_storage_path" ]                 = cm.get( "commons storage path",                 default=config[ "commons_storage_path" ],                 return_type="string",  silent=True )
        config[ "commons_retention_hours" ]              = cm.get( "commons retention hours",              default=config[ "commons_retention_hours" ],              return_type="int",     silent=True )
        config[ "commons_archival_interval_seconds" ]    = cm.get( "commons archival interval seconds",    default=config[ "commons_archival_interval_seconds" ],    return_type="int",     silent=True )
        config[ "commons_broadcast_rate_limit_seconds" ] = cm.get( "commons broadcast rate limit seconds", default=config[ "commons_broadcast_rate_limit_seconds" ], return_type="int",     silent=True )
        config[ "commons_ask_sync_grace_seconds" ]       = cm.get( "commons ask sync grace seconds",       default=config[ "commons_ask_sync_grace_seconds" ],       return_type="float",   silent=True )
    except Exception as e:
        logger.warning( f"[commons] ConfigurationManager unavailable; using hardcoded defaults. Reason: {e}" )
    return config


_COMMONS_CONFIG = _load_commons_config()


def _commons_project_root() -> str:
    """Resolve project root for commons file storage. Prefers LUPIN_ROOT env."""
    env_root = os.environ.get( "LUPIN_ROOT" )
    if env_root: return env_root
    return str( Path( __file__ ).resolve().parents[ 2 ] )


def _commons_storage_root() -> str:
    """
    Resolve the CommonsStore root path.

    `commons storage path` is interpreted as relative to LUPIN_ROOT (matches the
    project's existing config convention — see the `path to ... wo root` keys
    in lupin-app.ini). CommonsStore appends `io/commons` internally, so
    we strip a leading `/io/commons` segment when the user has left the default
    in place; otherwise we pass through.
    """
    raw = _COMMONS_CONFIG[ "commons_storage_path" ]
    # Default `/io/commons` → CommonsStore's hardcoded subpath already covers this;
    # pass the project root through. Custom values pass through directly.
    if raw == "/io/commons":
        return _commons_project_root()
    return _commons_project_root() + raw


def _commons_enabled() -> bool:
    """Defense-in-depth flag per AC12. Reads the cached INI value."""
    return bool( _COMMONS_CONFIG[ "commons_enabled" ] )


def _commons_ask_sync_grace_default() -> float:
    """Cached default for `commons_ask_sync` grace_seconds when caller omits it."""
    return float( _COMMONS_CONFIG[ "commons_ask_sync_grace_seconds" ] )


def _get_commons_store() -> CommonsStore:
    """Lazy singleton CommonsStore bound to the resolved storage root."""
    global _commons_store_singleton
    if _commons_store_singleton is None:
        _commons_store_singleton = CommonsStore( _commons_storage_root() )
    return _commons_store_singleton


def _maybe_start_commons_archival_daemon() -> Optional[ CommonsArchiver ]:
    """
    Boot the 24h archival daemon IF commons is enabled. Returns the archiver
    (started) or None (skipped). Called from `if __name__ == "__main__":` so
    the daemon does not start on bare module imports (tests, dev shells).
    """
    global _commons_archiver_singleton
    if not _commons_enabled():
        logger.info( "[commons] disabled — archival daemon NOT started" )
        return None
    if _commons_archiver_singleton is not None:
        return _commons_archiver_singleton
    _commons_archiver_singleton = CommonsArchiver(
        root             = _commons_storage_root(),
        interval_seconds = int( _COMMONS_CONFIG[ "commons_archival_interval_seconds" ] ),
        retention_hours  = int( _COMMONS_CONFIG[ "commons_retention_hours" ] ),
    )
    _commons_archiver_singleton.start()
    logger.info(
        f"[commons] archival daemon started "
        f"(interval={_COMMONS_CONFIG[ 'commons_archival_interval_seconds' ]}s, "
        f"retention={_COMMONS_CONFIG[ 'commons_retention_hours' ]}h)"
    )
    return _commons_archiver_singleton


def _commons_persona_fields() -> dict:
    """
    Extract (name, icon, color) from the session bridge's voice_persona block.

    Falls back to AC3 defaults (`<unknown>`, 💬, #888888) when the bridge is
    unavailable or the persona allocation failed.
    """
    try:
        cc_meta = _get_cc_metadata()
        vp      = cc_meta.get( "voice_persona" ) or { }
    except Exception:
        vp = { }
    return {
        "persona_name"  : vp.get( "name" )  or DEFAULT_PERSONA_NAME,
        "persona_icon"  : vp.get( "icon" )  or DEFAULT_PERSONA_ICON,
        "persona_color" : vp.get( "color" ) or DEFAULT_PERSONA_COLOR,
    }


@mcp.tool
def commons_post(
    topic    : str,
    body     : str,
    metadata : Optional[ dict ] = None,
) -> dict:
    """
    Append an entry to a commons topic (the file-based inter-session blackboard). The tier depends on the topic: **[SELF-DISCLOSURE]** for free-form, presence and incident topics (announcing your own state); **[ATTENTION-DEMANDING]** for coordination, help-wanted and contested-claim topics (summons peer attention).

    Free-form topics auto-create on first post and keep 7 days by default; reserved topics (`broadcast-acks`, `presence`, `system-events`) are pre-seeded and may differ. Persona fields are stamped from the session bridge and immutable, so you cannot spoof another persona. Posting user-sensitive data is prohibited (see cross-session-communication.md §5).

    For a directed peer reply use `dm_send(reply_to=..., thread_id=...)`: the body travels inline and the recipient acts on it directly. A reply posted here with `metadata={"in_reply_to": <qid>}` correlates to the original question but lands on the blackboard only; the asker sees it on their next `commons_read` poll.

    Args:
        topic: Topic name (free-form or one of the reserved topics)
        body: The message body (any string)
        metadata: Optional dict of extra fields. Common patterns: `{"kind": "status"}` for presence pings; `{"kind": "answer", "in_reply_to": <qid>}` for threaded replies; `{"kind": "incident", "severity": "warn|error|info"}` for incidents

    Returns:
        dict with `ts`, `sender_session_id`, `persona_name`, `persona_icon`, `persona_color`, `body`, `metadata`

    Examples:
        commons_post(topic="presence", body="starting long migration", metadata={"kind": "status"})
        commons_post(topic="dm-tiberius", body="yes, that fix landed in commit f4e0370", metadata={"in_reply_to": "<question_id_from_system_reminder>", "kind": "answer"})
    """
    if not _commons_enabled(): return { "status": "error", "reason": "commons disabled" }
    persona = _commons_persona_fields()
    return _get_commons_store().post(
        topic             = topic,
        body              = body,
        sender_session_id = SESSION_ID,
        persona_name      = persona[ "persona_name" ],
        persona_icon      = persona[ "persona_icon" ],
        persona_color     = persona[ "persona_color" ],
        metadata          = metadata,
    )


@mcp.tool
def commons_read(
    topic : str,
    since : Optional[ str ] = None,
    limit : int = 50,
) -> list:
    """
    **[READ — always allowed, no user permission needed]** Tail a commons topic. Returns newest-first when `since` is None, ascending when `since` is supplied. Honors `limit` strictly. A missing free-form topic returns an empty list (no error).

    When a `COMMONS PEER MESSAGE` system-reminder arrives, call `commons_read(topic=<topic>, limit=10)` and find the entry whose `metadata.question_id` matches the reminder's `question_id`.

    Args:
        topic: Topic name to read from
        since: Optional ISO-8601 timestamp; only entries with `ts > since` are returned
        limit: Maximum number of entries to return (default 50)

    Returns:
        List of entry dicts, each containing ts, sender_session_id, persona_*, body, metadata

    Examples:
        commons_read(topic="dm-maria", limit=10)    # the most recent 10 entries on the DM topic addressed to you
        commons_read(topic="dm-tiberius", since="2026-05-16T22:00:00+00:00")    # new entries since you last polled
    """
    if not _commons_enabled(): return [ ]
    return _get_commons_store().read( topic=topic, since=since, limit=limit )


@mcp.tool
def commons_who(
    topic            : Optional[ str ] = None,
    retention_hours  : int = 24,
) -> list:
    """
    **[READ — always allowed, no user permission needed]** "Who else is active right now?"

    Examples:
        # Who's been active across all topics in the last 24 hours (default)
        commons_who()

        # Narrow window — last hour only (helps filter stale-bridge phantoms)
        commons_who(retention_hours=1)

        # Who's posted to a specific topic in the last 24 hours
        commons_who(topic="broadcasts", retention_hours=24)

    If `topic` is supplied, scans only that topic; otherwise scans every active
    topic file. Each row gives the most recent post timestamp for that session
    plus their persona name/icon/color.

    **Failure-mode hint**: results may include phantom personas — sessions whose
    host process has died but whose bridge file lingers until the next host-side
    prune. If a DM to a "visible" peer never gets a reply, the recipient may
    be a phantom. Cross-reference with `retention_hours=1` for a narrower window.

    Args:
        topic: Optional topic name; if omitted, scans all topics
        retention_hours: Freshness window in hours (default 24)

    Returns:
        List of dicts `{session_id, persona_name, persona_icon, persona_color, last_post_ts}`,
        sorted by last_post_ts descending
    """
    if not _commons_enabled(): return [ ]
    return _get_commons_store().who( topic=topic, retention_hours=retention_hours )


@mcp.tool
@_offloaded_tool
def commons_ask_sync(
    topic            : str,
    body             : str,
    timeout_seconds  : float = 120.0,
    grace_seconds    : Optional[ float ] = None,
) -> dict:
    """
    **[ATTENTION-DEMANDING + BLOCKING — rarely justified; consider `commons_ask_async` first]** Post a question to commons and block until the first reply arrives plus a grace period.

    Prefer `commons_ask_async` in nearly all cases: it returns immediately, starts a watcher that pushes the recipient's reply back to your tmux, and frees your session meanwhile. Use this variant only when downstream logic LITERALLY cannot proceed without the reply AND a fixed timeout is acceptable.

    Timing: the call blocks until the FIRST matching reply arrives in `topic`, waits `grace_seconds` more to coalesce fast follow-ups, and returns the accumulated list. Replies are correlated via `metadata.in_reply_to` matching the question's auto-generated `question_id`. On timeout with zero replies it returns `{..., replies: []}`.

    Args:
        topic: Topic to post the question to (and listen on for replies)
        body: The question text
        timeout_seconds: Maximum wait for the first reply (default 120)
        grace_seconds: Additional wait after the first reply for follow-ups (default from the `commons ask sync grace seconds` INI key; falls back to 1.0)

    Returns:
        dict `{question_id, posted_ts, replies: [entry, ...]}`

    Example:
        result = commons_ask_sync(topic="builds", body="latest hash?", timeout_seconds=60)    # poll peers for the latest build hash, wait up to 60s
        for entry in result["replies"]: print(entry["body"])
    """
    if not _commons_enabled(): return { "status": "error", "reason": "commons disabled" }
    grace = grace_seconds if grace_seconds is not None else _commons_ask_sync_grace_default()
    persona = _commons_persona_fields()
    return _commons_ask_sync_impl(
        store             = _get_commons_store(),
        topic             = topic,
        body              = body,
        sender_session_id = SESSION_ID,
        persona_name      = persona[ "persona_name" ],
        persona_icon      = persona[ "persona_icon" ],
        persona_color     = persona[ "persona_color" ],
        timeout_seconds   = timeout_seconds,
        grace_seconds     = grace,
    )


@mcp.tool
def commons_ask_async(
    topic                : str,
    body                 : str,
    question_id          : Optional[ str ] = None,
) -> dict:
    """
    **[ATTENTION-DEMANDING — requires user trigger or clear coordination need]** Post a question to a topic at large and return immediately (fire-and-forget, polling-mode). For directed peer DMs use `dm_send` (body inline) instead.

    The message lands on the blackboard `topic` and is durable; peers see it on their next `commons_read` poll. Correlate replies via `metadata.in_reply_to == question_id`.

    Args:
        topic: Topic to post the question to
        body: The question text
        question_id: Optional UUID; if omitted, auto-generated

    Returns:
        dict `{question_id, posted_ts}`

    Example:
        result = commons_ask_async(topic="builds", body="latest hash?")    # poll-mode: ask the topic at large
        # later: commons_read(topic="builds", since=result["posted_ts"]) and filter on in_reply_to
    """
    return _commons_ask_async_dispatch(
        topic       = topic,
        body        = body,
        question_id = question_id,
    )


def _derive_dm_topic( recipient: str ) -> str:
    """
    Derive a server-pattern-safe DM topic from a recipient persona name.

    Phase 3 of the persona-name normalization plan
    (`src/rnd/v0.1.9/2026.06.19-persona-name-normalization/`) routes this through
    the shared `persona_slug` root so a DM topic ALWAYS equals the recipient's
    canonical persona key with spaces → `_`: "Mr. Radio" → "dm-mr_radio",
    "María"/"MARÍA" → "dm-maria". DM topics are always persona-derived, and the
    store/bridges hold the canonical (accent-stripped, ASCII) pool form, so this
    is the form that actually matches in practice.

    NOTE — this REVERSES the 2026-05-17 Q8 "unicode all the way down" directive
    that previously preserved exact unicode spelling ("María" → "dm-maría",
    "中文" → "dm-中文", "jean-luc" → "dm-jean-luc"). Under the canonical root,
    accents strip ("dm-maria"), non-Latin scripts reduce to "" ("中文" →
    "dm-"), and internal separators map to a single underscore boundary
    ("jean-luc" → "dm-jean_luc", bug 951a22be — they are NOT dropped). This
    is intentional for real personas (all ASCII/accented-Latin pool names), but
    it is a contract change on arbitrary input — see the Phase 3 flag.

    Pairs with the server-side topic pattern at
    `src/cosa/rest/routers/commons.py:100` (`_TOPIC_OR_QID_PATTERN`): the
    canonical output is `[a-z0-9_-]+`, a strict subset of the accepted `[\\w-]+`.

    Requires:
        - recipient is a string or None

    Ensures:
        - return value starts with `"dm-"`
        - the slug equals `persona_slug( recipient, sep='_' )` — canonical,
          accent-stripped, lowercased, ASCII-only
    """
    return f"dm-{persona_slug( recipient, sep='_' )}"


def _commons_ask_async_dispatch(
    topic                : str,
    body                 : str,
    question_id          : Optional[ str ]  = None,
) -> dict:
    """
    Dispatch helper for the `commons_ask_async` MCP tool (polling-mode).

    Necessary because `@mcp.tool`-decorated functions are wrapped into
    `FunctionTool` instances which are NOT directly callable as Python
    functions; the tool body delegates here so the persona/store construction
    lives in one plain callable.

    (The push-mode / directed-DM dispatch branch was removed in the cosa-voice
    token-reduction full-removal pass, 2026-06-17 — directed peer DMs now use
    `dm_send`. `commons_ask_async` is polling-only.)

    Requires:
        - `topic` and `body` are non-empty strings

    Ensures:
        - Returns the `_commons_ask_async_impl` result dict verbatim
        - On `_commons_enabled() is False`, returns `{"status": "error", "reason": "commons disabled"}`
    """
    if not _commons_enabled(): return { "status": "error", "reason": "commons disabled" }
    persona = _commons_persona_fields()

    return _commons_ask_async_impl(
        store             = _get_commons_store(),
        topic             = topic,
        body              = body,
        sender_session_id = SESSION_ID,
        persona_name      = persona[ "persona_name" ],
        persona_icon      = persona[ "persona_icon" ],
        persona_color     = persona[ "persona_color" ],
        question_id       = question_id,
    )


# ============================================================================
# Notification-native AI↔AI direct messaging (cosa-voice token reduction)
#
# `dm_send` is the PREFERRED peer-DM tool — it carries the body INLINE via a
# direction='ai_to_ai' notification (POST /api/dm/send), so the recipient
# processes it directly (~204 tokens) with zero `commons_read` re-fetch, vs the
# commons claim-check path's ~3,700 tokens/received DM. `commons_send_to` /
# `commons_ask_async` are deprecated in favor of this.
# Design: src/rnd/v0.1.8/2026.06.13-cosa-voice-token-reduction/02-notification-native-aixai-design.md
# ============================================================================

def _dm_send_impl(
    *,
    recipient,
    body,
    reply_to,
    thread_id,
    recipient_session_id,
    session_id,
    sender_persona,
    sender_icon,
    sender_project,
    api_base_url,
    api_key,
    post_fn,
):
    """
    Testable core for `dm_send` — HTTP is injected via `post_fn` so unit tests
    need no live server.

    Requires:
        - sender_project is THIS process's resolved project (CANONICAL_PROJECT).
          Required, never defaulted: the server cannot derive the caller's project
          from inside its own container and silently stamps @lupin when nobody
          tells it (row 12b5a766)
        - recipient (persona) OR recipient_session_id identifies the target
        - post_fn(url, json=, headers=, timeout=) -> response with .status_code,
          .json(), .text (the requests.post contract)

    Ensures:
        - missing api_key short-circuits to {"status":"error","reason":"missing_auth_header"}
        - 201 → {"status":"sent", **body_json}
        - 422 → {"status":"error","reason":"recipient_unresolved","detail":...}
        - 413 → {"status":"error","reason":"dm_too_long","detail":...} (rejecting arm)
        - other status → {"status":"error","reason":"http_<code>","detail":...}
        - transport exception → {"status":"error","reason":"request_failed","detail":str(e)}
    """
    if not api_key:
        return { "status": "error", "reason": "missing_auth_header",
                 "detail": _outbound_key_failure_detail( "/api/dm/send" ) }

    payload = {
        "sender_session_id" : session_id,
        "body"              : body,
        "sender_persona"    : sender_persona,
        "sender_icon"       : sender_icon,
        "reply_to"          : reply_to,
        "thread_id"         : thread_id,
        # The server CANNOT derive this: inside the container its resolver answers
        # "what project am I?" and stamps @lupin for every caller (row 12b5a766).
        # This process resolved the real answer host-side at module load; sending
        # it is the fix. `sender_project` is a REQUIRED argument of this core, not
        # a defaulted one — an omission that could be silent is the defect itself.
        "sender_project"    : sender_project,
    }
    if recipient_session_id:
        payload[ "recipient_session_id" ] = recipient_session_id
    else:
        payload[ "recipient_persona" ] = recipient

    url = f"{api_base_url}/api/dm/send"
    try:
        resp = post_fn( url, json=payload, headers={ "X-API-Key": api_key },
                        timeout=_SERVER_TRANSPORT_TIMEOUT_SECONDS )
    except Exception as e:
        return { "status": "error", "reason": "request_failed", "detail": str( e ) }

    if resp.status_code == 201:
        return { "status": "sent", **resp.json() }
    if resp.status_code == 422:
        try:
            detail = resp.json().get( "detail" )
        except Exception:
            detail = resp.text[ :200 ]
        return { "status": "error", "reason": "recipient_unresolved", "detail": detail }
    if resp.status_code == 413:
        # DM-verbosity pilot: the server refuses an over-long DM under the rejecting
        # arm with 413. Distinct from 422 (recipient_unresolved) — reusing it would
        # make a too-long DM report as a bad recipient. The server is authoritative;
        # forward its detail verbatim and never compute the arm client-side.
        try:
            detail = resp.json().get( "detail" )
        except Exception:
            detail = resp.text[ :200 ]
        return { "status": "error", "reason": "dm_too_long", "detail": detail }
    return { "status": "error", "reason": f"http_{resp.status_code}", "detail": resp.text[ :200 ] }


def _dm_send_fn(
    recipient            : str,
    body                 : str,
    reply_to             : Optional[ str ] = None,
    thread_id            : Optional[ str ] = None,
    recipient_session_id : Optional[ str ] = None,
) -> dict:
    """
    **[DM — directed attention-demanding]** Send a notification-native direct message to another CC persona session. **PREFERRED** over `commons_send_to` / `commons_ask_async`, which are deprecated.

    The body travels INLINE in the recipient's push (direction='ai_to_ai'), so the recipient acts on it directly: ~204 tokens, against ~3,700 for the commons claim-check path with its forced `commons_read` re-fetch.

    To answer a DM you received, call dm_send back to the sender with `reply_to` = the message_id from their system-reminder and `thread_id` = the conversation's thread_id (both in the inbound framing). A reply is just a DM; there is no separate watcher.

    Args:
        recipient: Recipient persona name (case/punctuation-tolerant resolution).
        body: Message body (delivered inline, no re-fetch).
        reply_to: message_id of the DM this answers. Omit for a new DM.
        thread_id: conversation id. Omit to start a fresh thread.
        recipient_session_id: precise session addressing; takes precedence over `recipient`.

    Returns:
        {"status":"sent","message_id","thread_id","recipient_session","recipient_session_hash8","recipient_persona","dispatched":True}, or {"status":"error","reason":"recipient_unresolved","detail":...}, or a transport/auth error {"status":"error","reason":...,"detail":...}. `recipient_session` is the FULL session id (feed it back as `recipient_session_id` for precise addressing); `recipient_session_hash8` is the persisted 8-character form that `dm_list` reports as the addressee. They are deliberately NOT the same value, so they will not compare equal (`dm_list`'s `session_id` filter accepts either).

    Example:
        dm_send(recipient="tiberius", body="yes — commit f4e0370", reply_to="<message_id>", thread_id="<thread_id>")
    """
    refusal = _refuse_borrowed_identity( "dm_send" )
    if refusal is not None: return refusal

    persona = _commons_persona_fields()
    return _dm_send_impl(
        recipient            = recipient,
        body                 = body,
        reply_to             = reply_to,
        thread_id            = thread_id,
        recipient_session_id = recipient_session_id,
        session_id           = SESSION_ID,
        sender_persona       = persona[ "persona_name" ],
        sender_icon          = persona[ "persona_icon" ],
        sender_project       = CANONICAL_PROJECT,
        api_base_url         = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" ),
        api_key              = _mcp_outbound_api_key(),
        post_fn              = requests.post,
    )


# Style addendum appended to the docstring BEFORE mcp.tool() registration (not
# via decorator syntax) — FastMCP may snapshot the tool description at
# decoration time, so the mutation must land first. Always appended (the DM
# Style Contract is unconditional — no toggle).
_DM_SEND_STYLE_ADDENDUM = (
    "\n\n    STYLE (governs the body you compose): see § DM Style Contract in "
    "this server's `instructions` — lead with the result, 3 lines / ~60 words. "
    f"{DM_STYLE_TAG}\n"
)
_dm_send_fn.__doc__ = _dm_send_fn.__doc__ + _DM_SEND_STYLE_ADDENDUM
dm_send = mcp.tool( _dm_send_fn )


# ============================================================================
# DM verb family — dm_respond / dm_get / dm_list (Phase 2)
#
# Mirrors of the /api/dm/<verb> REST routes (1:1). `dm_respond` is the threaded
# reply (POST /api/dm/respond — like dm_send but reply_to + thread_id required);
# `dm_get` fetches one DM by id; `dm_list` lists/polls a thread or the inbox.
# Each testable core injects HTTP (post_fn / get_fn) so unit tests need no server.
# Design: src/rnd/v0.1.8/2026.06.16-dm-api-namespace-design.md §3 + §5
#
# NOTE (post-Phase-1 unification): once dm_send's URL becomes /api/dm/send,
# _dm_send_impl and _dm_respond_impl can collapse into one `_dm_post_impl(path,...)`.
# Kept separate now for worktree isolation from the in-flight Phase-1 rename.
# ============================================================================

def _dm_respond_impl(
    *,
    recipient,
    body,
    reply_to,
    thread_id,
    recipient_session_id,
    session_id,
    sender_persona,
    sender_icon,
    sender_project,
    api_base_url,
    api_key,
    post_fn,
):
    """
    Testable core for `dm_respond` — POST /api/dm/respond (threaded reply).

    Identical contract to `_dm_send_impl` but targets /api/dm/respond and carries
    the mandatory `reply_to` + `thread_id`. HTTP is injected via `post_fn`.

    Requires:
        - sender_project is THIS process's resolved project (CANONICAL_PROJECT).
          Required, never defaulted — same reason as `_dm_send_impl`: the reply
          path shares the server's execution core, so an un-projected reply is
          stamped @lupin exactly like an un-projected send (row 12b5a766)

    Ensures:
        - missing api_key short-circuits to {"status":"error","reason":"missing_auth_header"}
        - 201 → {"status":"sent", **body_json}
        - 422 → {"status":"error","reason":"recipient_unresolved","detail":...}
        - 413 → {"status":"error","reason":"dm_too_long","detail":...} (rejecting arm)
        - other status → {"status":"error","reason":"http_<code>","detail":...}
        - transport exception → {"status":"error","reason":"request_failed","detail":str(e)}
    """
    if not api_key:
        return { "status": "error", "reason": "missing_auth_header",
                 "detail": _outbound_key_failure_detail( "/api/dm/respond" ) }

    payload = {
        "sender_session_id" : session_id,
        "body"              : body,
        "sender_persona"    : sender_persona,
        "sender_icon"       : sender_icon,
        "reply_to"          : reply_to,
        "thread_id"         : thread_id,
        # The server CANNOT derive this: inside the container its resolver answers
        # "what project am I?" and stamps @lupin for every caller (row 12b5a766).
        # This process resolved the real answer host-side at module load; sending
        # it is the fix. `sender_project` is a REQUIRED argument of this core, not
        # a defaulted one — an omission that could be silent is the defect itself.
        "sender_project"    : sender_project,
    }
    if recipient_session_id:
        payload[ "recipient_session_id" ] = recipient_session_id
    else:
        payload[ "recipient_persona" ] = recipient

    url = f"{api_base_url}/api/dm/respond"
    try:
        resp = post_fn( url, json=payload, headers={ "X-API-Key": api_key },
                        timeout=_SERVER_TRANSPORT_TIMEOUT_SECONDS )
    except Exception as e:
        return { "status": "error", "reason": "request_failed", "detail": str( e ) }

    if resp.status_code == 201:
        return { "status": "sent", **resp.json() }
    if resp.status_code == 422:
        try:
            detail = resp.json().get( "detail" )
        except Exception:
            detail = resp.text[ :200 ]
        return { "status": "error", "reason": "recipient_unresolved", "detail": detail }
    if resp.status_code == 413:
        # A too-long reply is refused with 413 the same way a send is (rejecting
        # arm). Map it to dm_too_long here too so the reply path reports the refusal
        # cleanly rather than falling through to a bare http_413.
        try:
            detail = resp.json().get( "detail" )
        except Exception:
            detail = resp.text[ :200 ]
        return { "status": "error", "reason": "dm_too_long", "detail": detail }
    return { "status": "error", "reason": f"http_{resp.status_code}", "detail": resp.text[ :200 ] }


def _dm_get_impl( *, message_id, api_base_url, api_key, get_fn ):
    """
    Testable core for `dm_get` — GET /api/dm/get?message_id=... (fetch one DM).

    Ensures:
        - missing api_key short-circuits to {"status":"error","reason":"missing_auth_header"}
        - 200 → {"status":"ok", **dm_json}
        - 404 → {"status":"error","reason":"not_found","detail":...}
        - 400 → {"status":"error","reason":"bad_request","detail":...}
        - other status → {"status":"error","reason":"http_<code>","detail":...}
        - transport exception → {"status":"error","reason":"request_failed","detail":str(e)}
    """
    if not api_key:
        return { "status": "error", "reason": "missing_auth_header",
                 "detail": _outbound_key_failure_detail( "/api/dm/get" ) }

    url = f"{api_base_url}/api/dm/get"
    try:
        resp = get_fn( url, params={ "message_id": message_id }, headers={ "X-API-Key": api_key },
                       timeout=_SERVER_TRANSPORT_TIMEOUT_SECONDS )
    except Exception as e:
        return { "status": "error", "reason": "request_failed", "detail": str( e ) }

    if resp.status_code == 200:
        return { "status": "ok", **resp.json() }
    if resp.status_code == 404:
        return { "status": "error", "reason": "not_found", "detail": resp.text[ :200 ] }
    if resp.status_code == 400:
        return { "status": "error", "reason": "bad_request", "detail": resp.text[ :200 ] }
    return { "status": "error", "reason": f"http_{resp.status_code}", "detail": resp.text[ :200 ] }


def _dm_list_impl( *, thread_id, since, limit, api_base_url, api_key, get_fn,
                   session_id=None, scope="session" ):
    """
    Testable core for `dm_list` — GET /api/dm/list (list/poll a thread or inbox).

    Sends this session's own id so the server can scope the read to DMs actually
    ADDRESSED here. The server authenticates a USER, not a session, so it cannot
    derive that on its own — if the caller does not say who it is, the read is
    account-wide and returns the whole fleet's traffic.

    Ensures:
        - missing api_key short-circuits to {"status":"error","reason":"missing_auth_header"}
        - params carry thread_id/since only when provided; limit always sent
        - session_id is sent whenever known, so the DEFAULT read is session-scoped
        - scope is sent only when it is "account" (the explicit wide read), so an
          audit-width read is always an affirmative request, never a silent default
        - 200 → {"status":"ok", **list_json}
        - 400 → {"status":"error","reason":"bad_request","detail":...}
        - other status → {"status":"error","reason":"http_<code>","detail":...}
        - transport exception → {"status":"error","reason":"request_failed","detail":str(e)}
    """
    if not api_key:
        return { "status": "error", "reason": "missing_auth_header",
                 "detail": _outbound_key_failure_detail( "/api/dm/list" ) }

    params = { "limit": limit }
    if thread_id:
        params[ "thread_id" ] = thread_id
    if since:
        params[ "since" ] = since
    if session_id:
        params[ "session_id" ] = session_id
    if scope == "account":
        params[ "scope" ] = "account"

    url = f"{api_base_url}/api/dm/list"
    try:
        resp = get_fn( url, params=params, headers={ "X-API-Key": api_key },
                       timeout=_SERVER_TRANSPORT_TIMEOUT_SECONDS )
    except Exception as e:
        return { "status": "error", "reason": "request_failed", "detail": str( e ) }

    if resp.status_code == 200:
        return { "status": "ok", **resp.json() }
    if resp.status_code == 400:
        return { "status": "error", "reason": "bad_request", "detail": resp.text[ :200 ] }
    return { "status": "error", "reason": f"http_{resp.status_code}", "detail": resp.text[ :200 ] }


@mcp.tool
def dm_respond(
    recipient            : str,
    body                 : str,
    reply_to             : str,
    thread_id            : str,
    recipient_session_id : Optional[ str ] = None,
) -> dict:
    """
    **[DM — directed attention-demanding]** Reply to a peer DM IN-THREAD. A `dm_respond` is a `dm_send` whose threading is mandatory: `reply_to` (the message_id you are answering) and `thread_id` (the conversation) are REQUIRED, and both are surfaced in the inbound DM framing. The body travels INLINE (direction='ai_to_ai'), zero re-fetch. It is equivalent to `dm_send(..., reply_to=..., thread_id=...)`.

    Args:
        recipient: Recipient persona name (case/punctuation-tolerant resolution).
        body: Reply body (delivered inline, no re-fetch).
        reply_to: message_id of the DM you are answering (required).
        thread_id: conversation id the reply belongs to (required).
        recipient_session_id: precise session addressing; takes precedence over `recipient` when supplied.

    Returns:
        Success: {"status":"sent","message_id","thread_id","recipient_session","recipient_session_hash8","recipient_persona","dispatched":True}.
        Recipient-resolution failure: {"status":"error","reason":"recipient_unresolved","detail":<RecipientResolutionError>}.
        Transport/auth failure: {"status":"error","reason":...,"detail":...}.
        The two id fields are the ones `dm_send` returns: `recipient_session` is the FULL session id (feed it back as `recipient_session_id`), `recipient_session_hash8` the persisted 8-character form that `dm_list` reports. They are deliberately not equal (`dm_list`'s `session_id` filter accepts either).
    """
    persona = _commons_persona_fields()
    return _dm_respond_impl(
        recipient            = recipient,
        body                 = body,
        reply_to             = reply_to,
        thread_id            = thread_id,
        recipient_session_id = recipient_session_id,
        session_id           = SESSION_ID,
        sender_persona       = persona[ "persona_name" ],
        sender_icon          = persona[ "persona_icon" ],
        sender_project       = CANONICAL_PROJECT,
        api_base_url         = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" ),
        api_key              = _mcp_outbound_api_key(),
        post_fn              = requests.post,
    )


@mcp.tool
def dm_get( message_id: str ) -> dict:
    """
    **[READ]** Fetch a single peer DM by its message id.

    Returns one direction='ai_to_ai' DM (scoped to you). Useful to re-read the
    full body/threading of a DM you only have the id for. 404 if it does not
    exist, is not a DM, or belongs to another user.

    Args:
        message_id: the DM's message_id (a UUID string).

    Returns:
        Success: {"status":"ok","message_id","thread_id","reply_to","sender_id",
                  "sender_persona","sender_icon","body","direction","state",
                  "job_id","created_at"}.
        Not found: {"status":"error","reason":"not_found","detail":...}.
        Bad id: {"status":"error","reason":"bad_request","detail":...}.
        Transport/auth failure: {"status":"error","reason":...,"detail":...}.
    """
    return _dm_get_impl(
        message_id   = message_id,
        api_base_url = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" ),
        api_key      = _mcp_outbound_api_key(),
        get_fn       = requests.get,
    )


@mcp.tool
def dm_list(
    thread_id : Optional[ str ] = None,
    since     : Optional[ str ] = None,
    limit     : int             = 50,
    scope     : str             = "session",
) -> dict:
    """
    **[READ]** List or poll peer DMs addressed to THIS session, or on request every DM on the account.

    With `thread_id`, returns that conversation oldest-first (read order). Without it, returns your DMs newest-first. `since` (an ISO-8601 timestamp) tails only messages newer than that instant, the lightweight poll for new replies. `limit` is clamped server-side to [1, 200].

    `scope="session"` (the DEFAULT) asks the server to return only DMs ADDRESSED to this session. `scope="account"` is the deliberate wide read for audit and forensics: the store scopes DMs to a service account, so it returns every session's traffic. READ THE RESPONSE'S `scope` FIELD, do not assume it: if this session's id cannot be resolved the server cannot narrow the read and returns `scope:"account"`. A DM's presence in an account-scoped result says only that it EXISTS; each message carries `recipient_session_hash8` (the addressee), so use that field to answer "was this for me?".

    Note the `_hash8` suffix: the addressee is persisted as the recipient's FIRST 8 CHARACTERS, while `dm_send` returns `recipient_session` holding the FULL id. They are different widths and will not compare equal (you may still pass a full id as a filter; the server truncates it).

    Args:
        thread_id: a conversation id (thread view), or omit for the inbox view.
        since: ISO-8601 timestamp; return only messages created after it (poll).
        limit: max messages to return (default 50, capped at 200).
        scope: "session" (default, only DMs addressed here) or "account" (every DM on the account; an explicit, auditable wide read). Anything else is REJECTED (422), never silently narrowed.

    Returns:
        Success: {"status":"ok","thread_id","since","count","scope","recipient_session_hash8","messages":[ {... ,"recipient_session_hash8"} ]}.
        Bad `since`: {"status":"error","reason":"bad_request","detail":...}.
        Transport/auth failure: {"status":"error","reason":...,"detail":...}.
    """
    return _dm_list_impl(
        thread_id    = thread_id,
        since        = since,
        limit        = limit,
        api_base_url = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" ),
        api_key      = _mcp_outbound_api_key(),
        get_fn       = requests.get,
        session_id   = SESSION_ID,
        scope        = scope,
    )


# ============================================================================
# Task-Store Tools (Phase 1 — unified work-queue wrappers)
# ============================================================================
#
# Per Lupin src/rnd/v0.1.8/2026.06.11-task-store-phase1/02-mcp-wrapper-spec.md:
# three thin TRANSPORT-only shims over :7999 /api/tasks/* — every structural
# rule (receipts on ->done, typed blocked_by + next_chase_ts on ->blocked,
# terminal lockout, enum membership) lives server-side in
# cosa.rest.task_store_rules; these tools never pre-validate. Identity
# (`created_by`/`actor`) is bridge-stamped, same stamping lane as commons_post
# — a session cannot impersonate. Day-to-day practice: planning-is-prompting
# workflow/task-store-discipline.md.

from lupin_mcp.task_store_tools import task_create_impl, task_transition_impl, task_correlate_impl, task_query_impl, task_reassign_impl, task_amend_impl, task_request_impl, task_ask_unpark_impl, task_edit_impl, task_get_impl, task_promotion_status_impl
from lupin_mcp.podcast_for_rick import podcast_for_rick_impl


def _task_store_identity() -> str:
    """
    Build the bridge-stamped identity for task-store writes.

    Ensures:
        - returns "<persona_name> <8-hex session id>" (e.g. "krishna 38d15e3b")
        - persona resolves via the same `_commons_persona_fields()` bridge
          lookup commons_post uses (falls back to the AC3 default on bridge
          failure — never raises)
    """
    return f"{_commons_persona_fields()[ 'persona_name' ]} {SESSION_ID}"


@mcp.tool
def task_create(
    item_class          : str,
    title               : str,
    project             : str,
    body                : Optional[ str ]  = None,
    owner_persona       : Optional[ str ]  = None,
    accountable_manager : Optional[ str ]  = None,
    gate_class          : str              = "none",
    priority            : str              = "P2",
    urgency             : str              = "normal",
    # None means THE CALLER DID NOT ASK, which is a different thing from asking for
    # "queued" — and until 2026-09-04 this door could not say it. The route mints a
    # new ticket into the holding area only when `status` is absent from the request
    # body, so a "queued" default here made every fleet-created row look like a
    # deliberate queued mint and the holding-area flag unreachable. See the comment
    # on the payload build in task_store_tools.task_create_impl.
    status              : Optional[ str ]  = None,
    blocked_by          : Optional[ list ] = None,
    next_chase_ts       : Optional[ str ]  = None,
    source_qid          : Optional[ str ]  = None,
    correlation_key     : Optional[ str ]  = None,
    authority           : str              = "standing",
) -> dict:
    """
    **[SELF-DISCLOSURE]** Create an item in the unified task store, the one door for owed work, your own included: an item created on the native harness `TaskCreate` list is invisible to the fleet, the arbiter and the operator's board. Use it for self-owned tasks, cross-persona assignments and typed items (decision, gate, bug, review_request) alike. Omit `status`: the row lands in the holding area (not_approved) and waits for Rick. It is NOT how DM-born tasks get created: `source_qid` only stamps provenance.

    FILING A P0 THAT RICK ORDERED. No seat sets P0 directly; a MANAGER relaying Rick's instruction files a PETITION, here, at create:
      1. Call with `priority="P0"` AND `authority="user_direct"`. Any other authority, or a worker seat, gets a flat 403; a worker escalates through its manager. Raising an EXISTING row to P0 through task_edit is also a 403: the petition exists only at create.
      2. The create answers 201 with a `petition` field: {ticket_id, minted_at: "P1", requesting: "P0", answer_by, resolves_by, deadlines, check_with: "task_promotion_status"}. The row is REAL and yours, but mints at P1 in the holding area (`not_approved`).
      3. `answer_by` is when his answer window closes: the promotion ask timeout (120s by default). `resolves_by` is NOT his window: it is the STALL deadline (ask timeout + notification grace + apply margin, 480s by default). Relay `answer_by`, never `resolves_by`, as his deadline.
      4. A TIMEOUT IS NOT A GRANT. An unanswered ask is refused and the row stays at P1 in holding. Never report the P0 as landed from the 201 — check `task_promotion_status(ticket_id)`: pending | approved | refused | superseded | stalled. One approval raises the row to P0 and admits it to `queued`.

    Returns:
        The item dict (server 201 body) verbatim, with `petition` when one was filed, or an error dict: {"status": "error", "reason": "server_unreachable"|"server_read_timeout"|"missing_auth_header"} or {"status": "error", "http_status": 422, "errors": [...]}.

    Args:
        item_class: task | decision | review_request | bug | gate
        title: One-line obligation statement
        project: Owning project (e.g. "lupin")
        body: Optional long-form payload (decision framing lives here)
        owner_persona: Who owes the work
        accountable_manager: Who chases it
        gate_class: none | operator (default "none")
        priority: P0..P5 (default "P2")
        urgency: urgent | normal | low (default "normal"); operator-gate TIME-sensitivity, NOT importance
        status: OMIT IT. Unset, the row lands in the holding area (not_approved) and waits for Rick. Naming "queued" or "blocked" is a 403 unless the row is P0 or the caller is Rick (a one-call blocked mint is MANAGER-ONLY). done/dropped/parked/claimed/in_progress/review are never mintable; transition after create.
        blocked_by: typed refs [{kind: item|persona|user, id}], REQUIRED (>=1) for a blocked mint
        next_chase_ts: ISO-8601 chase time, REQUIRED for a blocked mint whose blocked_by names a {kind:persona} ref
        source_qid: Originating commons question_id, when DM-born
        correlation_key: Upsert key for hook-mirrored items
        authority: standing | user_direct | manager_relay (default "standing"); "user_direct" with priority="P0" files a petition

    Examples:
        task_create(item_class="task", title="Review the wrapper build", project="lupin", owner_persona="tiffany", accountable_manager="tiberius")    # assign work to ANOTHER persona
        task_create(item_class="decision", title="Deploy window for MCP restart", project="lupin", body="Options: ... Recommendation: ...", gate_class="operator")    # a decision for the operator queue
        task_create(item_class="bug", title="Prod login is down", project="lupin", owner_persona="tiffany", priority="P0", authority="user_direct")    # a P0 Rick ordered (MANAGER seat; mints P1 + a petition)
        #   → then task_promotion_status(ticket_id=<petition.ticket_id>)
    """
    refusal = _refuse_borrowed_identity( "task_create" )
    if refusal is not None: return refusal

    return task_create_impl(
        api_base_url        = _get_server_url(),
        api_key             = _mcp_outbound_api_key(),
        created_by          = _task_store_identity(),
        item_class          = item_class,
        title               = title,
        project             = project,
        body                = body,
        owner_persona       = owner_persona,
        accountable_manager = accountable_manager,
        gate_class          = gate_class,
        priority            = priority,
        urgency             = urgency,
        status              = status,
        blocked_by          = blocked_by,
        next_chase_ts       = next_chase_ts,
        source_qid          = source_qid,
        correlation_key     = correlation_key,
        authority           = authority,
    )


@mcp.tool
def task_transition(
    task_id       : str,
    to_status     : str,
    receipt_refs  : Optional[ dict ] = None,
    next_chase_ts : Optional[ str ]  = None,
    blocked_by    : Optional[ list ] = None,
    reason        : Optional[ str ]  = None,
    authority     : str              = "standing",
    park_reason   : Optional[ str ]  = None,
    asynchronous  : Optional[ bool ] = True,
) -> dict:
    """
    **[SELF-DISCLOSURE]** Apply one state change to a task-store item. The server enforces the rules and surfaces them verbatim (a 422 carries its errors unedited); this tool pre-checks none of them. `asynchronous` defaults to True and matters only for a promotion out of `not_approved`.

    `->done` REQUIRES `receipt_refs`: no receipt, no done. Keys: commit · test_run · qid · doc_path · log_line · operator_attestation · manager_attestation, but only four CLOSE a row, and a worker seat can mint one of them, a manager seat two: `commit` (a sha you produced); `test_run` (harness only, `ts-<8 hex>`); `operator_attestation` (the OPERATOR's word; the router decides whether you may assert it); `manager_attestation` (MANAGER seats only, else 403; the server stores the manager identity, so put evidence in `reason`; closes decision and held rows, never `parked`). A worker with no commit asks its manager to close the row; do not name an unrelated sha.

    `->blocked` REQUIRES >=1 typed `blocked_by` ref ({kind: item|persona|user, id}), and `next_chase_ts` only when a ref is `persona` (a user-only or item-only block needs none). `->dropped` needs a `reason`. done and dropped are terminal.

    Returns:
        { item, event } (server 200 body) verbatim, or an error dict (422: the server's `errors`; 404: "task {id} not found"). On a PROMOTION whose 25s poll budget runs out you get the 202 body (`status: "awaiting_human_approval"`, `ticket_id`): still waiting. Do NOT retry (it 422s); call `task_promotion_status`.

    Args:
        task_id: The item's UUID
        to_status: in_progress | blocked | parked | done | dropped
        receipt_refs: Receipt dict, REQUIRED for ->done
        next_chase_ts: ISO-8601 time, REQUIRED for ->parked, and for ->blocked when `blocked_by` has a persona ref
        blocked_by: Typed refs [{kind, id}], REQUIRED for ->blocked
        park_reason: REQUIRED (non-blank, <=4000) for ->parked (only from queued / in_progress): the row's OWN decisive sentence, QUOTED. The chase IS the un-park (the row rejoins the owed count when `next_chase_ts` passes); an INDEFINITE hold is `dropped`. Cleared on unpark
        reason: Rationale (<=4000); REQUIRED for ->dropped
        authority: standing | user_direct | manager_relay (default "standing")
        asynchronous: default True (see above). Pass False for the synchronous path, None to omit the field. Must be a real boolean (the string "true" is a 422).

    `actor` is not a parameter: it is stamped from the session bridge.

    Examples:
        task_transition(task_id="<uuid>", to_status="done", receipt_refs={"commit": "f4e0370", "test_run": "ts-b51e63c9"})    # close with receipts
        task_transition(task_id="<uuid>", to_status="blocked", blocked_by=[{"kind": "persona", "id": "tiffany"}], next_chase_ts="2026-06-13T09:00:00-04:00")    # block with a typed wait and chase time
        task_transition(task_id="<uuid>", to_status="parked", park_reason="NOT TO BE WORKED per Rick's direct instruction", next_chase_ts="2026-07-22T09:00:00-04:00")    # park a held row, quoting its OWN decisive sentence
    """
    refusal = _refuse_borrowed_identity( "task_transition" )
    if refusal is not None: return refusal

    # 🔴 THIS VERB IS THE ONE CALLER THAT OPTS IN, AND IT IS WHY THE DEFAULT IS `True`
    # RATHER THAN `None` (row 8ed76594). Both gates were built, both were verified open,
    # and for a day nobody walked through: the single `asynchronous=True` anywhere in the
    # tree was a docstring. A capability every caller must REMEMBER to ask for is a
    # capability nobody uses, so the door opts in by default and a caller opts OUT.
    #
    # ⚠️ THE SEAM IS THIS VERB AND DELIBERATELY NOT `task_transition_impl`'s OWN DEFAULT.
    # `session_spawner.py` calls that impl too (a `->done` close during spawn); moving the
    # default down one layer would opt IT in as well, and "one caller" was the condition
    # this shipped under. The impl keeps its omit-unless-set contract, so every other
    # caller of it still sends a byte-identical request.
    #
    # Three states, on purpose: True opts in · False asks for today's synchronous path
    # explicitly · None OMITS the field, which is what `session_spawner` sends.
    #
    # ⚠️ IT IS ONLY THE SECOND OF TWO GATES — the operator's INI flag must also be on and
    # it fails CLOSED, so a `True` at a server that has not enabled it simply gets today's
    # behaviour. And the fork is reachable ONLY on a promotion out of `not_approved`
    # (`routers/tasks.py`, under enforcement-active + that status pair), so on every other
    # transition this field is one JSON key the handler never consults.
    #
    # On a 202 this still WAITS, for a 25s budget, and then answers
    # `awaiting_human_approval` with a ticket id you bring to `task_promotion_status`.
    # What changes is not whether you wait: it is that the wait holds no threadpool
    # worker, no pooled connection and no row lock ON THE SERVER, and that giving up
    # leaves you a DETERMINATE answer instead of today's indeterminate 10s read timeout
    # followed by a retry the server rejects 422 as a no-op (row 96cf5cec).
    return task_transition_impl(
        api_base_url  = _get_server_url(),
        api_key       = _mcp_outbound_api_key(),
        actor         = _task_store_identity(),
        task_id       = task_id,
        to_status     = to_status,
        receipt_refs  = receipt_refs,
        next_chase_ts = next_chase_ts,
        blocked_by    = blocked_by,
        reason        = reason,
        authority     = authority,
        park_reason   = park_reason,
        asynchronous  = asynchronous,
    )


@mcp.tool
def task_query(
    owner_persona       : Optional[ str ] = None,
    status              : Optional[ str ] = None,
    gate_class          : Optional[ str ] = None,
    urgency             : Optional[ str ] = None,
    accountable_manager : Optional[ str ] = None,
    project             : Optional[ str ] = None,
    item_class          : Optional[ str ] = None,
    correlation_key     : Optional[ str ] = None,
    limit               : Optional[ int ] = None,
    offset              : Optional[ int ] = None,
    terse               : bool            = False,
    include_terminal    : bool            = False,
    unscoped_audit      : bool            = False,
    include_parked      : bool            = False,
) -> dict:
    """
    **[READ — always allowed, no user permission needed]** Query the task store: exact-match filters, AND semantics, newest first. Bad enum values are a 422.

    Pass terse=True for any "see my list" / board glance (the at-a-glance projection, without `body`); terse=False only when you need a row's body or audit context.

    Scope every read: a BARE `task_query()` is REJECTED once the store holds more than the threshold of non-terminal rows. Add a filter (owner_persona / status / item_class / project / gate_class / accountable_manager / correlation_key) or pass `unscoped_audit=True` for a deliberate full-store audit.

    Hidden by default: terminal rows (`include_terminal=True` adds done/dropped), held rows (`status="not_approved"` shows them; an un-status'd query puts a HOLDING AREA notice in `warnings[]` when any match) and park-active rows (`include_parked=True` or `status="parked"`). The `in_progress` and `queued` passes cannot see held rows: add a `not_approved` pass before concluding nothing is owed.

    A `parked` row is a human's not-now ruling, with a `park_reason` quoting the row's decisive sentence. Parking is bounded and self-expiring: once `next_chase_ts` passes, the row rejoins the owed count and shows here. An indefinite hold is `dropped` with a reason, not parked.

    `park_reason_stale` (bool, also in terse rows) is True when the row's body changed after the quote was frozen: read the row, not its park_reason, and re-park. False means only "no body change", never "still true" (its basis can live outside the row), and a row parked before capture-time shipped reads False until its body next changes. Advisory: changes no owed-ness.

    Returns:
        { tasks, count, total, has_more, truncated, warnings } verbatim (terse rows when terse=True), or an error dict (a bare over-threshold pull is a 400). READ `total`, NOT `count`: `count` is this PAGE and saturates at `limit`. Branch on `has_more` (= offset + count < total). `truncated` is True when a CHARACTER budget, not the row limit, stopped serialization early.

    Args:
        owner_persona: Filter by who owes the work
        status: not_approved | queued | claimed | in_progress | blocked | parked | review | done | dropped | wont_fix
        gate_class: none | operator
        urgency: operator-gate urgency tier (urgent | normal | low)
        accountable_manager: Filter by chasing manager
        project: Filter by owning project
        item_class: task | decision | review_request | bug | gate
        correlation_key: Exact-match filter on the hook-upsert correlation key
        limit: Max rows (server default 100, cap 500)
        offset: Pagination offset
        terse: True for the at-a-glance projection; False (default) for the full wire shape including body
        include_terminal: True also returns done/dropped rows on an un-status'd query (default False)
        unscoped_audit: True is the deliberate full-sweep escape past the unscoped-size guard (default False)
        include_parked: True also returns park-ACTIVE rows (default False hides them). EXPIRED parked rows are returned either way: they have rejoined the owed count.

    Examples:
        task_query(owner_persona="sam", status="in_progress", terse=True)    # my owed work, the everyday scoped query
        task_query(gate_class="operator")    # operator queue, full rows
        task_query(unscoped_audit=True, include_terminal=True, terse=True)    # deliberate full-store audit
        task_query(status="parked", terse=True)    # what is parked, and why
    """
    return task_query_impl(
        api_base_url        = _get_server_url(),
        api_key             = _mcp_outbound_api_key(),
        owner_persona       = owner_persona,
        status              = status,
        gate_class          = gate_class,
        urgency             = urgency,
        accountable_manager = accountable_manager,
        project             = project,
        item_class          = item_class,
        correlation_key     = correlation_key,
        limit               = limit,
        offset              = offset,
        terse               = terse,
        include_terminal    = include_terminal,
        unscoped_audit      = unscoped_audit,
        include_parked      = include_parked,
    )


@mcp.tool
def task_get( task_id: str ) -> dict:
    """
    **[READ — always allowed, no user permission needed]** Fetch ONE store row by its UUID.

    Use it to ask about a row directly: an empty filtered `task_query` is not evidence a row is absent (a row at offset=15 of a limit=15 page reads as gone). It returns the FULL item including `body`, not the terse projection. An absent id is a 404 error dict carrying "task {id} not found" verbatim, never an empty success or None.

    Args:
        task_id: The item's UUID string. A malformed id is the server's reject to surface (422), never pre-checked here.

    Returns:
        The full serialized item (200 body) verbatim, or an error dict: a 404 carries "task {id} not found" under "detail"; a malformed UUID carries the server's 422 detail; auth/transport failures carry the shared missing_auth_header / server_unreachable / server_read_timeout contract. Never an empty success, never None.

    Example:
        task_get(task_id="4288dd53-6779-460a-88bd-a7365fb734b2")    # open one row by id, e.g. from a terse list's `id` field
    """
    return task_get_impl(
        api_base_url = _get_server_url(),
        api_key      = _mcp_outbound_api_key(),
        task_id      = task_id,
    )


@mcp.tool
def task_promotion_status( ticket_id: str ) -> dict:
    """
    **[READ — always allowed, no user permission needed]** How did that promotion go?

    When a promotion out of the holding area runs ASYNCHRONOUSLY, the door answers immediately with a ticket, and `task_transition` waits a budget for Rick's answer. If the budget runs out you get `awaiting_human_approval` plus a `ticket_id`, and THIS is the verb you come back with. So does a caller whose process died: the ticket is persisted, and the answer waits whenever you ask.

    WHAT THE STATES MEAN; two are easy to collapse and must not be:
        pending     the ask is out; Rick has not answered and the deadline has not passed
        approved    it went through; `response_body` is the { item, event } a synchronous call would have returned, and `approval_source` says whether it was his keypress or a timed-out default
        refused     Rick said no, OR the ask never reached him; `refusal` says which
        superseded  HE APPROVED IT AND THE WORLD MOVED: the transition was no longer legal when the answer landed. NOT a refusal, nobody said no; read `refusal` for what the row had become and look at what else touched it
        stalled     the ask died without an answer, usually a server bounce mid-ask; a human was already told by an urgent notification and nothing was promoted

    TWO DEADLINES, AND ONLY ONE IS RICK'S:
        answer_by    when his ANSWER WINDOW closes — the ask timeout (120s by default). Null on a ticket minted before the field existed.
        resolves_by  the STALL deadline — ask timeout + notification grace + apply margin (480s by default). Still `pending` after it means the ask died.
    The `deadlines` field repeats this, so a relay never reports the wrong one.

    Args:
        ticket_id: the id handed back in the 202, and repeated in every `awaiting_human_approval` answer.

    Returns:
        The ticket verbatim on success. A 404 carries "promotion ticket {id} not found" verbatim, NEVER an empty success: a missing ticket and an unresolved one are different facts and only one of them means "keep waiting".

    Example:
        task_promotion_status( ticket_id="4288dd53-6779-460a-88bd-a7365fb734b2" )
    """
    return task_promotion_status_impl(
        api_base_url = _get_server_url(),
        api_key      = _mcp_outbound_api_key(),
        ticket_id    = ticket_id,
    )


@mcp.tool
def task_correlate(
    task_id         : str,
    correlation_key : str,
    authority       : str = "standing",
) -> dict:
    """
    **[SELF-DISCLOSURE]** Re-stamp a task-store item's correlation_key. When a successor session inherits an item, ADOPT it by re-keying it onto your own harness id instead of forking a duplicate. The server appends an audited `re-correlated` event and REJECTS terminal items (no re-keying closed history); this tool does not pre-check that, and a 422 carries the server's words verbatim.

    Args:
        task_id: The item's UUID
        correlation_key: The new key to stamp (server validates 1..255 chars)
        authority: standing | user_direct | manager_relay (default "standing")

    Returns:
        { item, event } (server 200 body) verbatim, or an error dict: a 404 carries "task {id} not found" verbatim under "detail"; a 422 (terminal item / bad authority) carries the server's detail verbatim.

    `actor` is not a parameter: it is stamped from the session bridge.

    Example:
        task_correlate(task_id="<uuid>", correlation_key="cc-task:<my-stable-sid>:<harness-id>")    # adopt the inherited item onto this session's harness id
    """
    refusal = _refuse_borrowed_identity( "task_correlate" )
    if refusal is not None: return refusal

    return task_correlate_impl(
        api_base_url    = _get_server_url(),
        api_key         = _mcp_outbound_api_key(),
        actor           = _task_store_identity(),
        task_id         = task_id,
        correlation_key = correlation_key,
        authority       = authority,
    )


@mcp.tool
def task_reassign(
    task_id           : str,
    new_owner_persona : str,
    reason            : str,
    new_manager       : Optional[ str ] = None,
    authority         : str             = "manager_relay",
) -> dict:
    """
    **[SELF-DISCLOSURE]** Reassign a task-store item to a new owner persona: the manager's handoff primitive, to pull a worker off a queue and hand their in-flight work to another persona. Changes OWNERSHIP ONLY; it can NEVER change `status`. If the handoff should also re-queue the item, that is a SEPARATE `task_transition`. The server canonicalizes the new owner to the owed-query key (so the new owner's `task_query(owner_persona=…)` finds the row) and appends one `patched` event carrying your `reason`. A non-empty `reason` is REQUIRED here at the verb; a blank one is rejected before any server round-trip.

    Args:
        task_id: The item's UUID
        new_owner_persona: The handoff target (server normalizes to the canonical key)
        reason: Non-empty justification for the handoff (stamps the audit event)
        new_manager: Optional new accountable_manager; when omitted the chasing manager is left UNCHANGED
        authority: standing | user_direct | manager_relay (default "manager_relay")

    Returns:
        { item, event } (server 200 body) verbatim, or an error dict: {"status": "error", "reason": "empty_reason"} when `reason` is blank (verb-enforced, no round-trip); a 404 carries "task {id} not found" verbatim; a 422 (terminal item / bad authority) carries the server's detail verbatim.

    `actor` is not a parameter: it is stamped from the session bridge, so the handoff is auditable to the real session that issued it.

    Examples:
        task_reassign(task_id="<uuid>", new_owner_persona="marcus", reason="Tiffany pulled onto the P0 arbiter fix")    # hand an in-flight item to another persona, manager unchanged
        task_reassign(task_id="<uuid>", new_owner_persona="marcus", new_manager="tiberius", reason="lane handoff — Tiberius now chasing")    # reassign and move it under a new chasing manager
    """
    refusal = _refuse_borrowed_identity( "task_reassign" )
    if refusal is not None: return refusal

    if not ( reason and reason.strip() ):
        return { "status": "error", "reason": "empty_reason",
                 "detail": "task_reassign requires a non-empty reason (the manager's justification for the handoff)" }
    return task_reassign_impl(
        api_base_url      = _get_server_url(),
        api_key           = _mcp_outbound_api_key(),
        actor             = _task_store_identity(),
        task_id           = task_id,
        new_owner_persona = new_owner_persona,
        reason            = reason,
        new_manager       = new_manager,
        authority         = authority,
    )


@mcp.tool
def task_amend(
    task_id   : str,
    note      : str,
    reason    : Optional[ str ] = None,
    authority : str             = "standing",
) -> dict:
    """
    **[SELF-DISCLOSURE]** Append an amendment to a task-store item's body: the durable home for a LIVE item whose scope is legitimately reframed mid-flight, instead of leaving the current spec in scratchpad checklists, code comments or transition reasons, where a successor rehydrating from the store never sees it. APPEND-ONLY: the original body is preserved verbatim and your note lands below a persona-stamped, UTC-timestamped divider, so the amendment history reads inline. Reach for it when you would otherwise rewrite a body but must keep the prior spec.

    A TERMINAL item is ALLOWED: amend is the ONE write verb the store accepts on a done/dropped row, the durable home for a gate verdict written AFTER a worker self-closes their own row. On a terminal row the block is marked a post-terminal addendum (`[post-terminal addendum · ... · added after close, not a reopening]`) and the audit event is stamped 'amended_post_terminal'; status is NOT moved (a closed row stays closed; transition / edit / correlate remain refused on it). The server REJECTS a blank note and a bad authority, and this tool does not pre-check them; a 422 carries the server's words verbatim.

    Args:
        task_id: The item's UUID
        note: The amendment text to append (server validates 1..4000 + non-blank)
        reason: Optional justification stamping the audit event; when omitted the event records an auto-marker naming the appended length. The event transition is 'amended' on a live row, 'amended_post_terminal' on a terminal one
        authority: standing | user_direct | manager_relay (default "standing")

    Returns:
        { item, event } (server 200 body) verbatim, or an error dict: a 404 carries "task {id} not found" verbatim under "detail"; a 422 (blank note / bad authority) carries the server's detail verbatim.

    `actor` is not a parameter: it is stamped from the session bridge, so the amendment is auditable to the real session.

    Example:
        task_amend(task_id="<uuid>", note="SCOPE REFRAME (Rick 2026-07-02): scheduler-port -> request-initiation subscriber. Prior spec below stands as history.", reason="4f14d38f manager ruling on cited evidence")    # record a manager-ruled scope reframe on a live item
    """
    refusal = _refuse_borrowed_identity( "task_amend" )
    if refusal is not None: return refusal

    return task_amend_impl(
        api_base_url = _get_server_url(),
        api_key      = _mcp_outbound_api_key(),
        actor        = _task_store_identity(),
        task_id      = task_id,
        note         = note,
        reason       = reason,
        authority    = authority,
    )


@mcp.tool
def task_request(
    task_id          : str,
    move             : str,
    reason           : str,
    deletion_task_id : Optional[ str ] = None,
) -> dict:
    """
    **[MANAGER — directed at Rick]** Ask Rick to promote or demote ONE task-store row. Rick alone promotes and demotes; managers can only request, and requests default to no. This files a question on the row and NEVER moves it: the row stays exactly where it is until Rick answers from his board.

    What happens next, so you do not wait for the wrong thing:
      · the request waits on Rick's board with NO expiry: silence changes nothing, and NO ANSWER MEANS NO
      · if he APPROVES, the move is performed for you (admit -> queued; demote -> the holding area); you do not transition the row yourself
      · if he DENIES, the row stays put and you may file a fresh request
      · if the row moves another way first, the request is withdrawn, not denied

    AN ADMIT COSTS ONE OF YOUR OWN TICKETS while Rick's `sword_of_damocles_active` switch is on: an admit must name `deletion_task_id`, a live ticket YOU own. When he approves, the row is admitted and that ticket is dropped in the same step; if he denies, neither moves. Ownership is checked against your session's persona, not a name you type. A demote pays nothing.

    Args:
        task_id: The row's UUID; one row per call, never a batch
        move: "admit" (promote out of the holding area) or "demote" (off the live board)
        reason: Why the row should move. Rick reads it to decide: make it the one sentence he needs
        deletion_task_id: admit only; the UUID of a live ticket you own, dropped when Rick approves. Required while the switch is on

    Returns:
        The row (server 200 body) with request_state "pending", or an error dict carrying the server's detail verbatim.

    Refused by the server, with its words verbatim:
      · 403: you are not a manager (a worker asks its manager to file this), or the deletion ticket is not yours, or your persona could not be read
      · 409: the row cannot make that move from where it is (admit is only for a row in the holding area; demote only for a live, unfinished row), or a request is already pending on it (one at a time), or the deletion ticket is already finished or already pledged on another pending admit
      · 422: `move` is not "admit" or "demote", `reason` is blank, an admit named no deletion ticket while the switch is on, a demote named one, or the ticket does not exist or is the row itself

    `actor` is not a parameter: it is stamped from the session bridge, so the manager check reads your real session.

    Example:
        task_request(task_id="<uuid>", move="admit", reason="fix merged at 36a0a403; the row is ready to work", deletion_task_id="<uuid of a live ticket you own>")
    """
    refusal = _refuse_borrowed_identity( "task_request" )
    if refusal is not None: return refusal

    return task_request_impl(
        api_base_url = _get_server_url(),
        api_key      = _mcp_outbound_api_key(),
        actor        = _task_store_identity(),
        task_id          = task_id,
        move             = move,
        reason           = reason,
        deletion_task_id = deletion_task_id,
    )


@mcp.tool
def task_ask_unpark(
    task_id : str,
) -> dict:
    """
    Ask Rick to approve un-parking one parked row; the server makes the card.

    This asks and never moves the row. Manager seats only.

    Args:
        task_id: The parked row's UUID; one row per call

    Returns:
        { card_id, task_id, expires_at, pushed }, or an error dict carrying the server's detail verbatim.
        When pushed is false the card is saved but Rick was not shown it. A second ask is refused
        with a 409 until the card expires, 10 minutes after it was made.

    Next steps:
      1. Wait. Rick answers the card from his board, and silence refuses.
      2. After a yes, send task_transition with to_status "queued" and
         receipt_refs { "approval_card": "<card_id>" }.
      3. The card covers that one move once. A second use, a no, a default answer or a card made
         before the park is refused.

    Refused by the server:
      - 403: you are not a manager
      - 404: no such row, or the operator's account was not found
      - 409: the row is not parked, it has no recorded park time, or an unanswered card already exists (its id is in the message)

    The actor is not a parameter: it is stamped from the session bridge.

    Example:
        task_ask_unpark(task_id="<uuid of a parked row>")
    """
    refusal = _refuse_borrowed_identity( "task_ask_unpark" )
    if refusal is not None: return refusal

    return task_ask_unpark_impl(
        api_base_url = _get_server_url(),
        api_key      = _mcp_outbound_api_key(),
        actor        = _task_store_identity(),
        task_id      = task_id,
    )


@mcp.tool
@_offloaded_tool
def podcast_for_rick(
    path    : str = "",
    card_id : str = "",
) -> dict:
    """
    Ask Rick about a podcast of one file, wait for his answer, and start it on a yes.

    The server makes the card. This tool polls it until Rick answers or it expires, then starts the job.
    It blocks up to about 10 minutes, and only a person's yes starts anything. To resume after an error
    such as queue_failed, pass the card_id: the ask is skipped, and the path refuses a card for another file.

    Args:
        path: Absolute path to a file in the main checkout of a registered repo. A file inside a
            git worktree is refused: the server cannot see it, so write it to the main checkout's io/tmp.
        card_id: A card from an earlier call, to resume instead of asking again.

    Returns:
        { status: "started", card_id, job_id, ... } after a yes and a successful start;
        { status: "declined", card_id } for a no or neither;
        { status: "default_used", card_id } when the card timed out on its default;
        { status: "expired", card_id } when nobody answered in time;
        or { status: "error", reason, detail, stage? }. The reason is the server's own code
        (too_old, hash_mismatch, queue_failed and so on) or one of path_not_absolute, file_not_found,
        outside_any_repo, inside_a_worktree, path_or_card_required, card_for_a_different_file,
        card_already_waiting, card_already_spent, ask_answer_malformed, card_unreadable.
        A queue_failed error carries a retry hint: the card is still valid.

    The actor is not a parameter: it is stamped from the session bridge.

    Example:
        podcast_for_rick(path="/mnt/DATA01/include/www.deepily.ai/projects/lupin/io/tmp/2026.10.08-summary.md")
    """
    refusal = _refuse_borrowed_identity( "podcast_for_rick" )
    if refusal is not None: return refusal

    return podcast_for_rick_impl(
        api_base_url = _get_server_url(),
        api_key      = _mcp_outbound_api_key(),
        actor        = _task_store_identity(),
        host_path    = path,
        card_id      = card_id,
    )


@mcp.tool
def task_edit(
    task_id   : str,
    updates   : dict,
    reason    : Optional[ str ] = None,
    authority : str             = "standing",
) -> dict:
    """
    **[SELF-DISCLOSURE]** Edit one or more of the 5 FREE-EDIT fields of a task-store item: `title` · `body` · `priority` · `gate_class` · `urgency`. Most often used to DEMOTE a mis-inflated `priority`. A thin wrapper over `PATCH /api/tasks/{id}`: it OVERWRITES the named fields atomically (one txn, one `patched` audit event). Value validation stays server-side.

    REFUSED at the MCP layer: owner fields `owner_persona` and `accountable_manager`; use `task_reassign` (the single owner-change path, with a mandatory reason). REFUSED by the server (`extra="forbid"`, 422): `status` · `blocked_by` · `next_chase_ts` · `park_reason` · `park_reason_captured_at` · `receipt_refs` · `correlation_key`; use `task_transition`, which moves the coupled fields together. A bad enum (`priority` not P0–P5, `gate_class` not none/manager/operator, `urgency` not urgent/normal/low) or an empty `title` is a 422 with no row mutation. Terminal (done/dropped) items are rejected server-side.

    Args:
        task_id: The item's UUID
        updates: Dict of {field: value} to overwrite; non-empty. Owner keys are refused with a pointer to task_reassign; invariant keys 422 server-side
        reason: Optional justification stamping the 'patched' audit event; when omitted the event records the field delta
        authority: standing | user_direct | manager_relay (default "standing")

    Returns:
        { item, event } (server 200 body) verbatim, or an error dict: {"reason": "empty_updates"} when `updates` is empty or not a dict (verb-enforced, no round-trip); {"reason": "owner_field_refused"} → task_reassign; a 404 carries "task {id} not found" verbatim; a 422 (invariant field / bad enum / empty title / terminal item) carries the server's detail verbatim.

    `actor` is not a parameter: it is stamped from the session bridge, last, so an `updates` "actor" key cannot shadow it.

    Examples:
        task_edit(task_id="<uuid>", updates={"priority": "P3"}, reason="over-inflated at mint; not user-blocking")    # demote a mis-inflated priority
        task_edit(task_id="<uuid>", updates={"title": "Retitled", "urgency": "low"})    # multi-field atomic edit in one txn/event
    """
    refusal = _refuse_borrowed_identity( "task_edit" )
    if refusal is not None: return refusal

    if not isinstance( updates, dict ) or not updates:
        return { "status": "error", "reason": "empty_updates",
                 "detail": "task_edit requires a non-empty `updates` dict of {field: value} (the fields to overwrite)" }
    return task_edit_impl(
        api_base_url = _get_server_url(),
        api_key      = _mcp_outbound_api_key(),
        actor        = _task_store_identity(),
        task_id      = task_id,
        updates      = updates,
        reason       = reason,
        authority    = authority,
    )


# ============================================================================
# Reuse-review tools: check_exists, fetch_similar, read_capability, replay
# ============================================================================
#
# The logic lives in lupin_mcp/reuse_tools.py and is imported INSIDE each wrapper, never at
# module level, so a failure in that module cannot stop the voice tools from loading. A
# wrapper that cannot import it answers with an error dict. Design of record:
# src/rnd/v0.2.2/2026.09.30-wiki-and-jev-for-code-reuse-review/ (implementation plan, section 5).
# A fix to these tools reaches a seat only when its MCP server restarts; /clear does not reload it.


def _reuse_unavailable( e ) -> dict:
    """Ensures: returns the error dict a reuse wrapper answers with when reuse_tools cannot be used."""
    return { "status": "error", "error": "REUSE_TOOLS_UNAVAILABLE", "detail": f"{type( e ).__name__}: {e}" }


@mcp.tool
@_offloaded_tool
def check_exists( need: str, root: Optional[ str ] = None ) -> dict:
    """
    Should this be built? Returns REUSE, EXTEND, NEW or UNCERTAIN_READ_SOURCE for a planned capability.

    Describe the need in one or two sentences before writing new code. The answer carries a
    shortlist of existing symbols, the nearest entries, and a receipt_id to cite. UNCERTAIN_READ_SOURCE
    always carries a `cause`; it means read the source of the shortlist and nearest entries, and is
    never a NEW. NEW does not rule the need distinct: read the nearest entries first.

    Args:
        need: what the new code would do
        root: repository root to check; default is the git root of the working directory
    """
    try:
        from lupin_mcp import reuse_tools
        ctx = reuse_tools.context_from_environment( root )
    except Exception as e:
        return _reuse_unavailable( e )
    return reuse_tools.check_exists_impl( need, ctx )


@mcp.tool
@_offloaded_tool
def fetch_similar( entry: str, root: Optional[ str ] = None ) -> dict:
    """
    What does this symbol resemble? Returns the shortlist of similar existing symbols and a receipt_id.

    Use it on each new definition in a diff. `entry` is the symbol id as listed in the index, for
    example "cosa.rest.task_store_owed.park_reason_is_stale". The symbol itself is excluded.

    Args:
        entry: symbol id
        root: repository root; default is the git root of the working directory
    """
    try:
        from lupin_mcp import reuse_tools
        ctx = reuse_tools.context_from_environment( root )
    except Exception as e:
        return _reuse_unavailable( e )
    return reuse_tools.fetch_similar_impl( entry, ctx )


@mcp.tool
@_offloaded_tool
def read_capability( names: list, root: Optional[ str ] = None ) -> dict:
    """
    Read capability pages from the code wiki by slug. No model call; returns the page text and a receipt_id.

    Args:
        names: capability slugs, for example ["task-store"]
        root: repository root; default is the git root of the working directory
    """
    try:
        from lupin_mcp import reuse_tools
        ctx = reuse_tools.context_from_environment( root )
    except Exception as e:
        return _reuse_unavailable( e )
    return reuse_tools.read_capability_impl( names, ctx )


@mcp.tool
@_offloaded_tool
def replay( receipt_id: str, root: Optional[ str ] = None ) -> dict:
    """
    Re-check a receipt_id: the stored result, a re-run against the frozen index, and a re-run at HEAD.

    The frozen re-run tests that the receipt's inputs reproduce its result. The HEAD re-run tests
    whether the code or the model still agrees. A damaged or missing input answers with a named
    error and never a verdict.

    Args:
        receipt_id: id returned by another reuse tool
        root: repository root; default is the git root of the working directory
    """
    try:
        from lupin_mcp import reuse_tools
        ctx = reuse_tools.context_from_environment( root )
    except Exception as e:
        return _reuse_unavailable( e )
    return reuse_tools.replay_impl( receipt_id, ctx )


# The server-side call log is a second FastMCP middleware beside BridgeLivenessMiddleware. A failure
# to import or mount it is reported on stderr and the server starts without it.
try:
    from lupin_mcp.reuse_call_log_middleware import ReuseCallLogMiddleware
    mcp.add_middleware( ReuseCallLogMiddleware( identity=lambda: _task_store_identity(), session_id=SESSION_ID ) )
except Exception as _reuse_log_error:
    print( f"reuse call-log middleware not mounted: {type( _reuse_log_error ).__name__}: {_reuse_log_error}", file=sys.stderr )


if __name__ == "__main__":
    # THE POSITIVE ASSIGNMENT — the only place this is set. It must come BEFORE
    # mcp.run() so a resolution failure during startup still hard-exits the server
    # exactly as it always has. See the flag's definition for why this is not an
    # environment check, and for what a future console_scripts entry point owes.
    _IS_MCP_SERVER = True
    # PHASE 2 STARTS HERE AND NOWHERE ELSE (row `87ae7234`). Importing this module
    # must not start a poll loop that credits coverage to no test.
    _start_bridge_watch()
    _maybe_start_commons_archival_daemon()
    mcp.run()
