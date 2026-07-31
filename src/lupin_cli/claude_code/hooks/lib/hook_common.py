#!/usr/bin/env python3
"""
Shared library for all Claude Code hook scripts.

Provides common utilities for reading hook input from stdin, logging payloads,
emitting JSON responses, and sending TTS notifications via lupin_cli.notifications.

Usage from hook scripts:
    import sys
    import os
    sys.path.insert( 0, os.path.join( os.environ.get( "LUPIN_ROOT", "" ), "src" ) )
    from lupin_cli.claude_code.hooks.lib.hook_common import (
        read_hook_input, log_payload, emit_json, send_tts, get_target_email,
        is_tts_enabled, build_progress_group_id
    )
"""
import configparser
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


# ── Constants ─────────────────────────────────────────────────────────────────

# Canonical path resolution via cu.get_project_root() — keeps runtime output
# in io/ directory, consistent with existing io/log/ convention.
import cosa.utils.util as cu
from lupin_cli.claude_code.hooks.lib.sessions_dir import sessions_dir


def _logs_dir():
    """
    Runtime-resolved hook-log directory (Lever P, item 6fc8d78d, 2026-07-07).

    Resolved at CALL time — NOT bound to an import-time module constant — so a
    test fixture setting LUPIN_HOOK_LOG_DIR is honored regardless of import order.

    Why this exists: `LOGS_DIR`/`STREAM_LOG` were import-time constants off the
    real project root. A unit test driving log_to_stream/log_payload (e.g.
    test_heartbeat_integration, which monkeypatches the persona to "Mr. Radio 🦉"
    and drives _run_heartbeat with synthetic session ids) could NOT redirect them
    by monkeypatching cu.get_project_root — the constant was already bound. So test
    emissions appended to the REAL production io/claude_code_hooks/logs/
    hook-events.jsonl (1,259+ synthetic `sidC*` rows), manufacturing a false
    "Mr-Radio-only" arbiter false-poke signature. Resolving lazily + honoring an
    env override lets the conftest redirect writes to a per-test tmp dir.

    Requires:
        - (none)

    Ensures:
        - LUPIN_HOOK_LOG_DIR set (non-empty) → Path( that )  (test-hermetic override)
        - else → <project root>/io/claude_code_hooks/logs  (production default,
          byte-identical to the pre-Lever-P constant; production leaves it UNSET)
        - Never raises
    """
    override = os.environ.get( "LUPIN_HOOK_LOG_DIR" )
    if override:
        return Path( override )
    return Path( cu.get_project_root() ) / "io" / "claude_code_hooks" / "logs"

# Tool classification for smart TTS filtering (PostToolUse)
TOOLS_SILENT   = frozenset( { "Read", "Grep", "Glob", "TaskCreate", "TaskUpdate", "TaskGet", "TaskList" } )
TOOLS_ANNOUNCE = frozenset( { "Bash", "Write", "Edit" } )

# MCP voice tool prefix — skip drain when Claude is already talking to user
MCP_VOICE_PREFIX = "mcp__cosa-voice__"

# Stop hook safety valve — max consecutive blocks before allowing stop
MAX_STOP_BLOCKS = 3

# Delay before tmux injection after stop block (seconds)
TMUX_INJECTION_DELAY = 0.25

# Transport budget for the FIELD-CARRIED notification path (row 204911ca, F1
# 2026-07-20). Set to 6 — **deliberately NOT the cohort's 30.**
#
# 🔴 THIS MEMBER IS CARRIED IN A PYDANTIC FIELD, NOT PASSED AT THE CALL.
# `AsyncNotificationRequest( timeout=… )` is consumed at
# `notify_user_async.py:197-201` as a bare `requests.post( timeout=request.timeout )`
# — bare governs BOTH the connect and the read leg, so the read leg is exposed
# to a `:7999` reload just like a direct call site. The first pass raised the
# direct `urlopen` sites in this package and left this one at 3s, because
# `grep -rn _SERVER_TRANSPORT_TIMEOUT_SECONDS` cannot see a field assignment.
# At 3s a reload silently dropped the notification — the caller swallows the
# failure, so nothing observed the loss.
#
# 🔴 WHY 6 AND NOT 30 — THIS PATH RETRIES, AND THE SCHEDULE IS DERIVED FROM
# THIS VERY NUMBER. `calculate_retry_intervals( request.timeout )`
# (`notify_user_async.py:47`) builds the retry ladder FROM the timeout, so
# raising it inflates BOTH the per-attempt budget AND the attempt count. The
# cohort's 30 does not cost 30s here; it costs **267s**:
#
#   timeout │ attempt starts (s)        │ rides out an 18.76s reload? │ wall clock
#   ────────┼───────────────────────────┼─────────────────────────────┼───────────
#      3    │ 0, 4, 8                   │ NO — all inside the window  │   11s
#      5    │ 0, 6, 12, 19              │ yes, by 0.24s               │   24s
#    * 6 *  │ 0, 7, 14, 22              │ yes, TWO covering attempts  │   28s
#     10    │ 0, 11, 22, 34, 46, 59     │ yes                         │   69s
#     30    │ 0, 31, 63, …              │ yes                         │  267s
#
# These are fire-and-forget notifications on a HOOK path, wrapped in
# `except: pass` precisely so a notification failure never blocks Claude Code.
# A hook that stalls 267s is a far worse defect than a dropped best-effort
# notification — so the cohort value is not merely oversized here, it is wrong.
#
# At 6 the RETRY LOOP rides out the window rather than any single fat timeout:
# attempt 3 (14s→20s) is still open when a max-length window ends at 18.76s, and
# attempt 4 starts at 22s after it. Two independent covering attempts, for 28s
# worst case against the 11s this path already cost. That is the trade, and it
# is 2.5x — not the 24x that copying the cohort would have bought.
#
# ⚠️ DO NOT "fix" this by aligning it to _SERVER_TRANSPORT_TIMEOUT_SECONDS. The
# two numbers answer different questions: the cohort's covers ONE call with no
# retry; this one covers a RETRY SCHEDULE it also generates. They are not the
# same quantity and should not be made to match.
#
# Ceiling note: `AsyncNotificationRequest.timeout` is `Field( ge=1, le=30 )`
# (`notification_models.py:620-625`), so 6 sits well inside the bound.
#
# Full derivation: src/rnd/v0.1.9/2026.07.19-dev-server-reload-availability.md §9(a).
NOTIFY_TRANSPORT_TIMEOUT_SECONDS = 6

# Fails loudly at import if THIS module's budget is pushed past the Pydantic bound
# it has to fit through. A comment warning about the hazard is not a control; this is.
#
# This guard is deliberately DUPLICATED rather than shared with
# cc_notification_listener.py's identical assert. The two constants are separate by
# design (each module owns its own), so a guard in one module CANNOT protect the
# other — importing the sibling to share it would reintroduce the cross-package
# import edge on the hook boot path that this whole cohort exists to avoid.
# Each exposure needs its own guard, at its own definition.
assert NOTIFY_TRANSPORT_TIMEOUT_SECONDS <= 30, (
    "NOTIFY_TRANSPORT_TIMEOUT_SECONDS exceeds AsyncNotificationRequest.timeout's "
    "Field( le=30 ) — raise the field bound in notification_models.py first, or "
    "this fails as an opaque ValidationError inside a swallowed except"
)


# ── Core Functions ────────────────────────────────────────────────────────────

def read_hook_input():
    """
    Read and parse JSON payload from stdin (provided by Claude Code).

    Requires:
        - sys.stdin contains valid JSON

    Ensures:
        - Returns parsed dict with hook payload
        - Returns empty dict on parse failure (non-blocking: never crashes the hook)

    Returns:
        dict: Parsed hook input with session_id, hook_event_name, cwd, etc.
    """
    try:
        return json.load( sys.stdin )
    except ( json.JSONDecodeError, EOFError, ValueError ):
        return {}


def log_to_stream( hook_name, payload, extra=None ):
    """
    Append single-line JSON entry to hook-events.jsonl for tail -f debugging.

    Requires:
        - hook_name is a non-empty string
        - payload is a dict or None

    Ensures:
        - Creates logs directory if it doesn't exist
        - Appends one compact JSON line to STREAM_LOG
        - Includes hook name, timestamp, PID, and compact payload summary
        - Extra dict fields are merged into the entry when provided
        - Never raises exceptions (logging failure is non-fatal)

    Args:
        hook_name: Name of the hook (e.g., "stop", "mcp_ask_yes_no")
        payload: Hook input dict (only summary fields extracted)
        extra: Optional dict of hook-specific fields to merge into entry
    """
    try:
        logs_dir = _logs_dir()
        logs_dir.mkdir( parents=True, exist_ok=True )
        entry = {
            "ts"   : get_timestamp(),
            "hook" : hook_name,
            "pid"  : os.getpid(),
        }
        # Compact payload summary (avoid multi-MB last_assistant_message dumps)
        if isinstance( payload, dict ):
            entry[ "event" ]      = payload.get( "hook_event_name", "" )
            from lupin_cli.claude_code.hooks.lib.session_bridge import resolve_stable_session_id
            raw_sid = payload.get( "session_id", "" )
            entry[ "session_id" ] = resolve_stable_session_id( raw_sid )[:8]
            entry[ "tool" ]       = payload.get( "tool_name", "" )
        if extra:
            entry.update( extra )
        with open( logs_dir / "hook-events.jsonl", "a" ) as f:
            f.write( json.dumps( entry, default=str ) + "\n" )
    except Exception:
        pass  # Logging failure is non-fatal


def log_payload( hook_name, payload ):
    """
    Write timestamped JSON payload to logs directory for empirical analysis.

    Requires:
        - hook_name is a non-empty string
        - payload is a JSON-serializable dict

    Ensures:
        - Creates logs directory if it doesn't exist
        - Writes payload to logs/{hook_name}-{timestamp}.json
        - Appends compact summary to JSONL stream (via log_to_stream)
        - Never raises exceptions (logging failure is non-fatal)

    Args:
        hook_name: Name of the hook (e.g., "post_tool_use")
        payload: Full hook input dict to log
    """
    try:
        logs_dir  = _logs_dir()
        logs_dir.mkdir( parents=True, exist_ok=True )
        timestamp = datetime.now( timezone.utc ).strftime( "%Y%m%dT%H%M%S_%f" )
        log_file  = logs_dir / f"{hook_name}-{timestamp}.json"

        log_entry = {
            "hook_name"  : hook_name,
            "timestamp"  : get_timestamp(),
            "pid"        : os.getpid(),
            "ppid"       : os.getppid(),
            "payload"    : payload
        }

        with open( log_file, "w" ) as f:
            json.dump( log_entry, f, indent=2, default=str )

    except Exception:
        pass  # Logging failure is non-fatal

    log_to_stream( hook_name, payload )


def emit_json( data ):
    """
    Emit JSON response to stdout for Claude Code to consume.

    Requires:
        - data is a JSON-serializable dict

    Ensures:
        - Prints JSON string to stdout (single line)
        - Flushes stdout to ensure Claude Code receives it

    Args:
        data: Response dict (hook-specific output)
    """
    print( json.dumps( data ), flush=True )


def get_timestamp():
    """
    Get current US/Eastern timestamp in human-readable format.

    Uses the project's canonical US/Eastern timezone (matching the FastAPI
    server + `cosa.utils.util`), NOT host-local/UTC: the hook runs on the host
    which is often UTC, so we convert explicitly — otherwise hook-event times
    read 4-5h ahead of the EST the rest of the system reports. (2026-06-05)

    Ensures:
        - Returns formatted string with date, time, and milliseconds in EST/EDT

    Returns:
        str: Formatted timestamp (e.g., "2026.06.05 @ 21:15 56,123ms")
    """
    now = cu.get_current_datetime_raw( tz_name="US/Eastern" )
    return now.strftime( "%Y.%m.%d @ %H:%M %S" ) + f",{now.microsecond // 1000:03d}ms"


def _config_file_path():
    """
    Resolve the path to the ~/.lupin/config fallback file (bug ef10c5b6).

    Resolved at CALL time — not an import-time constant — so a test fixture
    setting LUPIN_CONFIG_FILE is honored regardless of import order (same
    hermetic-override pattern as _logs_dir / LUPIN_HOOK_LOG_DIR above).

    Requires:
        - (none)

    Ensures:
        - LUPIN_CONFIG_FILE set (non-empty) → Path( that )  (test-hermetic override)
        - else → ~/.lupin/config  (production default)
        - Never raises

    Returns:
        Path: The config file location (may not exist on disk)
    """
    override = os.environ.get( "LUPIN_CONFIG_FILE" )
    if override:
        return Path( override )
    return Path.home() / ".lupin" / "config"


def _read_email_from_config_file():
    """
    Resolve the notification target email from the ~/.lupin/config fallback file.

    ~/.lupin/config is the host's INI-format Lupin config (the same file the
    cosa-voice tooling reads). The operator's notification recipient lives at
    `[<active-env>] global_notification_recipient`, where the active environment
    name is the value of `[environments] default`. This is the defense-in-depth
    backstop for get_target_email() (bug ef10c5b6): env keeps precedence, so this
    runs ONLY when LUPIN_DEV_EMAIL is absent/empty.

    Requires:
        - (none)

    Ensures:
        - Returns the active environment's global_notification_recipient
          (stripped) when the file parses and that env pointer + section + key
          all resolve to a non-empty value
        - Returns None when the file is missing/unreadable, the [environments]
          default pointer is absent/empty, or the target recipient is
          absent/empty
        - Never raises (a missing, binary, or malformed file degrades to None)

    Returns:
        str or None: Configured notification recipient email
    """
    parser = configparser.ConfigParser()
    try:
        if not parser.read( _config_file_path(), encoding="utf-8" ):
            return None  # file missing/unreadable → read() returns [] (no raise)
        env_name = parser.get( "environments", "default", fallback="" ).strip()
        if not env_name:
            return None
        recipient = parser.get( env_name, "global_notification_recipient", fallback="" ).strip()
        return recipient or None
    except ( configparser.Error, UnicodeDecodeError ):
        return None  # malformed / binary config → no fallback available


def get_target_email():
    """
    Resolve the notification target email, env-first with a file fallback.

    Resolution order (first non-empty hit wins; the environment keeps
    precedence):
        1. LUPIN_DEV_EMAIL environment variable
        2. ~/.lupin/config INI — `[<active-env>] global_notification_recipient`,
           where the active env is `[environments] default`  (file fallback)

    Why the file fallback exists (bug ef10c5b6, 2026-07-15): the SessionStart
    hello-world notification is a fresh session's ONLY birth certificate on the
    operator's focus bar, and send_tts() no-ops SILENTLY when this returns None.
    A tmux-server restart froze a non-login global env with no LUPIN_DEV_EMAIL,
    so every new session went invisible until it happened to push an MCP-side
    notification. The file fallback means a lost env can never again silence
    registration; the env var still wins whenever it is present.

    Requires:
        - (none)

    Ensures:
        - Returns the env value (stripped) when LUPIN_DEV_EMAIL is set non-empty
        - Else returns the file-configured email when ~/.lupin/config supplies one
        - Returns None when neither source yields a non-empty email
        - Never raises

    Returns:
        str or None: Target email address
    """
    env_email = os.environ.get( "LUPIN_DEV_EMAIL" )
    if env_email and env_email.strip():
        return env_email.strip()
    return _read_email_from_config_file()


def is_tts_enabled():
    """
    Check if TTS notifications are enabled via HOOK_TTS_ENABLED env var.

    Default is True (enabled). Set HOOK_TTS_ENABLED=false to silence TTS
    while logging continues.

    Ensures:
        - Returns True if env var is missing, empty, or "true"
        - Returns False only if env var is explicitly "false" (case-insensitive)

    Returns:
        bool: Whether TTS notifications should be sent
    """
    value = os.environ.get( "HOOK_TTS_ENABLED", "true" ).strip().lower()
    return value != "false"


def build_progress_group_id( prefix, session_id ):
    """
    Build progress_group_id from hook prefix and session ID.

    Produces IDs like "pt-6c54ecc2" for in-place DOM counter updates.
    Extensible: any hook can call with its own prefix.

    Requires:
        - prefix is a 2-3 char lowercase string (e.g., "pt", "pu", "ss")
        - session_id is a string (may be full UUID or truncated hex)

    Ensures:
        - Returns string matching regex ^[a-z]{2,3}-[a-f0-9]{6,8}(-\\d+)?$
        - Truncates session_id to first 8 chars
        - Falls back to "00000000" if session_id is falsy

    Args:
        prefix: Hook type prefix (e.g., "pt" for PreToolUse, "pu" for PostToolUse)
        session_id: Claude Code session ID (full or truncated)

    Returns:
        str: Progress group ID (e.g., "pt-6c54ecc2")
    """
    hex_part = session_id[:8] if session_id else "00000000"
    return f"{prefix}-{hex_part}"


def send_tts( message, priority="low", sender_id=None, progress_group_id=None, suppress_ding=False ):
    """
    Send fire-and-forget TTS notification via lupin_cli.notifications.

    Uses AsyncNotificationRequest + notify_user_async() for non-blocking delivery.
    Respects HOOK_TTS_ENABLED env var toggle. Silently fails if notification
    infrastructure is unavailable (hooks must never block Claude Code).

    Requires:
        - message is a non-empty string
        - priority is one of: low, medium, high, urgent
        - LUPIN_DEV_EMAIL environment variable is set for target resolution

    Ensures:
        - Sends TTS notification if TTS is enabled and target email is available
        - Auto-resolves sender_id via session bridge when not explicitly provided
        - Passes progress_group_id through to AsyncNotificationRequest for counter grouping
        - Returns silently on any failure (non-blocking)
        - Never raises exceptions

    Args:
        message: TTS message text
        priority: Notification priority (default: "low")
        sender_id: Explicit sender_id string (default: None = auto-resolve from session bridge)
        progress_group_id: Progress group ID for in-place DOM updates (default: None)
    """
    if not is_tts_enabled():
        return

    target_email = get_target_email()
    if not target_email:
        return

    try:
        from lupin_cli.notifications.notification_models import (
            AsyncNotificationRequest,
            NotificationType,
            NotificationPriority
        )
        from lupin_cli.notifications.notify_user_async import notify_user_async

        # Auto-resolve sender_id from session bridge when not explicitly provided
        if sender_id is None:
            try:
                from lupin_cli.claude_code.hooks.lib.session_bridge import build_sender_id_for_cc
                sender_id = build_sender_id_for_cc()
            except Exception:
                pass  # Graceful degradation — notification fires without sender_id

        request = AsyncNotificationRequest(
            message            = message,
            notification_type  = NotificationType.PROGRESS,
            priority           = NotificationPriority( priority ),
            target_user        = target_email,
            sender_id          = sender_id,
            progress_group_id  = progress_group_id,
            suppress_ding      = suppress_ding,
            timeout            = NOTIFY_TRANSPORT_TIMEOUT_SECONDS
        )

        notify_user_async( request=request )

    except Exception:
        pass  # Hook must never block Claude Code due to notification failure


# ── Tool Summary + Voice Drain Helpers ────────────────────────────────────────

def format_tool_summary( tool_name, tool_input ):
    """
    Build a concise one-liner for TTS announcements in PostToolUse.

    Requires:
        - tool_name is a string
        - tool_input is a dict or None

    Ensures:
        - Bash: "Bash: <command>" (truncated at 60 chars)
        - Write/Edit: "Write: <basename>" or "Edit: <basename>"
        - Other: just tool_name

    Args:
        tool_name: Name of the tool (e.g., "Bash", "Write")
        tool_input: Tool input dict from hook payload

    Returns:
        str: TTS-friendly tool summary
    """
    if tool_input is None:
        tool_input = {}

    if tool_name == "Bash":
        command = tool_input.get( "command", "" )
        if len( command ) > 60:
            command = command[:60] + "..."
        return f"Bash: {command}" if command else "Bash"

    if tool_name in ( "Write", "Edit" ):
        file_path = tool_input.get( "file_path", "" )
        basename  = os.path.basename( file_path ) if file_path else ""
        return f"{tool_name}: {basename}" if basename else tool_name

    return tool_name


def acknowledge_drained( messages ):
    """
    No-op — gist auto-response is now handled by CCNotificationListener
    at message receipt time, not at drain time.

    Kept for API compatibility with drain_and_acknowledge().
    """
    pass


def drain_and_acknowledge( session_id ):
    """
    Convenience wrapper: drain voice buffer then acknowledge messages.

    Requires:
        - session_id is a non-empty string

    Ensures:
        - Calls drain_voice_buffer( session_id )
        - Calls acknowledge_drained( messages ) for any buffered messages
        - Returns the list of drained messages
        - Never raises exceptions

    Args:
        session_id: Claude Code session ID

    Returns:
        list[dict]: Drained messages (may be empty)
    """
    try:
        messages = drain_voice_buffer( session_id )
        if messages:
            acknowledge_drained( messages )
        return messages
    except Exception:
        return []


# ── Voice Context Injection Helpers ───────────────────────────────────────────

# Marker that prefixes every human-voice context line. Its PRESENCE in an
# assembled context string is the signal that a human spoke — used by
# enrich_voice_context() to decide whether to append the TTS-acknowledge rider.
# Peer-DM (ai_to_ai) blocks deliberately carry NO such marker (they are
# self-contained <system-reminder> blocks), so a pure-DM context skips the rider.
VOICE_LINE_PREFIX = "[Voice]: "


# bug d0d7f068 (Part 2 / option C): the peer-DM envelope's frame prefix as a SHARED
# constant. build_peer_dm_reminder emits it; is_injected_peer_dm + the Stop-hook
# poke-cap reset guard MATCH on it. Deriving both the emit and the match from ONE
# constant (never a re-typed literal) is the 46a17f5a literal-drift lesson — the
# "Heartbeat arbiter (" family is exactly how a match silently drifts from its source.
PEER_DM_FRAME_PREFIX = "PEER DM from "


# Rick's brevity mandate, 2026-07-19 (canonical: planning-is-prompting →
# workflow/brevity-mandate.md). The compact carrier form of KISS · Say 3LoL ·
# NoMC C2C, shared by BOTH injection riders below.
#
# The escape clause reads "ONLY WHEN ASKED" — never "when the content requires
# it". That earlier wording was drafted and rejected the same hour: a self-
# assessed exception hands length-discretion back to the verbose author, which
# makes the rule a receipt rather than a control. Do NOT soften this string.
BREVITY_TAG = (
    "[KISS · 3LoL · NoMC C2C · NoAA — verdict first, 3 lines or less; "
    "longer ONLY WHEN ASKED. Detail → abstract.]"
)


# The DM Style Contract tag (Phase 1 prompting-only DM brevity/tone experiment,
# Rick 2026-07-31, toggled by lupin-app.ini "dm style contract enabled" /
# cu.get_dm_style_contract_enabled()). Folds the ratified control-instruction
# language (src/rnd/v0.1.9/2026.07.31-dm-verbosity-reduction/2026.07.31-anthropic-
# opus-4-8-checkpoints-and-language-reviews.md) into the same bracketed-tag shape
# as BREVITY_TAG so it rides cheaply wherever it's quoted. Kept as a SEPARATE
# constant rather than merged into BREVITY_TAG: BREVITY_TAG's closing "Detail →
# abstract" clause doesn't apply to dm_send (no abstract parameter) and must not
# be misquoted onto a DM.
DM_STYLE_TAG = (
    "[DM Style Contract — lead with the result; plain, literal sentences; "
    "decisions/evidence/risks/required actions only; NoAA WaHH; 3 lines / "
    "~60 words; longer ONLY WHEN ASKED.]"
)


# The human-voice TTS-acknowledge rider (appended by enrich_voice_context when a
# drained message is human voice). Hoisted to a module constant so its BYTE COST
# is visible at the top of the file — this string rides EVERY spoken utterance.
#
# Sized deliberately (task 6a3941b8 × the pre-existing micro-prompt-reduction
# ask): the brevity tag was folded in while the rider was CUT from 325 chars /
# 47 words to 215 / 37 — a net-SMALLER payload that happens to carry the tag,
# never a straight addition. Any future edit must keep that ratchet: measure
# before and after, and do not let this grow back.
VOICE_ACK_RIDER = (
    "IMPORTANT: ack by voice — notify() or converse(), priority=high. "
    "The user is listening, not reading the terminal. "
    f"{BREVITY_TAG}"
)


# The peer-DM brevity rider (task 314671cd). Peer-to-peer DMs are the fleet's
# worst bloat surface — informality invites courtesy, context-setting, and mutual
# appreciation the recipient pays for and does not need. Session-boot CLAUDE.md
# decays into back-of-context; this rider is read fresh at the moment of
# composing a reply, which is where the leverage is.
#
# Scoped to the REPLY affordance on purpose: it governs how you answer, so it is
# suppressed on one_way=True advisories (no reply is possible — see
# build_peer_dm_reminder's bug 8894e597 branch).
PEER_DM_BREVITY_RIDER = f"↳ {BREVITY_TAG}"


def _peer_dm_reply_rider():
    """
    Resolve the reply-affordance rider at CALL TIME (not import time) — gated on
    lupin-app.ini "dm style contract enabled" (cu.get_dm_style_contract_enabled()),
    read fresh on every call so the toggle needs no daemon restart, matching the
    get_spoken_char_cap() uncached-per-call precedent.

    Ensures:
        - toggle OFF (control, default): returns PEER_DM_BREVITY_RIDER unchanged
          — today's shipped behavior, the control arm of the A/B
        - toggle ON (treatment): returns PEER_DM_BREVITY_RIDER + DM_STYLE_TAG

    Returns:
        str: the rider text for the reply-affordance line
    """
    if cu.get_dm_style_contract_enabled():
        return f"{PEER_DM_BREVITY_RIDER} {DM_STYLE_TAG}"
    return PEER_DM_BREVITY_RIDER


def build_peer_dm_reminder( body, persona=None, icon=None, msg_id=None, thread_id=None, one_way=False ):
    """
    Build the peer-DM <system-reminder> block — the SINGLE source of peer-DM
    framing for BOTH delivery paths: the listener's idle tmux-wake
    (cc_notification_listener._handle_peer_dm) and the active buffer-drain
    (format_voice_context's ai_to_ai branch). One framing, one name (no drift
    between the two paths).

    Per §6a of
    src/rnd/v0.1.8/2026.06.13-cosa-voice-token-reduction/02-notification-native-aixai-design.md:
    a peer DM is NOT human voice. The block carries the sender's persona + icon +
    message_id + thread_id and a dm_send reply affordance — and deliberately NO
    speakerphone voice rider / "user spoke" / notify-to-speak instruction. Peers
    reply via dm_send, never TTS.

    ONE-WAY variant (bug 8894e597, 2026-07-02): a genuine peer DM is bidirectional,
    but an ARBITER-authored poke/advisory is NOT — the arbiter is a pure observer
    with NO deliverable inbox by ratified design (bug 9694fb11: "there is NO
    deliverable tap-ACK path — a manager literally cannot DM the arbiter back").
    The default dm_send affordance is therefore a FALSE promise on arbiter pokes:
    every poked session burns a turn attempting the impossible reply, then falls
    back to hold-mtime as the de-facto ACK. When `one_way=True`, the affordance is
    replaced with an honest statement of the REAL signal path — resuming work
    (bridge / hold / store freshness IS the acknowledgment the arbiter reads),
    which composes with the 92c7ab1d bridge-mtime sign-of-life veto. Genuine peer
    DMs keep the default (one_way=False) affordance untouched.

    Requires:
        - body is the message text (any string; caller strips/validates emptiness)
        - persona, icon, msg_id, thread_id are strings or None
        - one_way is a bool (True only for arbiter-authored one-way advisories)

    Ensures:
        - Returns a complete "<system-reminder>...</system-reminder>" block
        - Missing persona falls back to "a peer session"; missing icon/ids → ""
        - one_way=False → the dm_send reply affordance (bidirectional peer DM),
          followed by PEER_DM_BREVITY_RIDER (task 314671cd — the rider governs
          how you REPLY, so it rides the reply affordance)
        - one_way=True  → an honest one-way notice (no dm_send line, and NO
          brevity rider — no reply is possible, so a reply-shaping rider would
          be pure byte cost); resuming work is named as the acknowledgment

    Args:
        body: The inline DM body
        persona: Sender's voice persona name
        icon: Sender's persona icon
        msg_id: Originating notification id (for reply_to threading)
        thread_id: Conversation thread id (for thread_id threading)
        one_way: True → arbiter-authored one-way advisory (no reply affordance)

    Returns:
        str: The peer-DM system-reminder block
    """
    persona      = persona or "a peer session"
    icon         = icon or ""
    msg_id       = msg_id or ""
    thread_id    = thread_id or ""
    sender_label = f"{persona} {icon}".strip()
    if one_way:
        # bug 8894e597: the arbiter has no inbox — state the honest signal path
        # instead of a dm_send affordance that cannot be delivered.
        reply_affordance = (
            "↳ This is a ONE-WAY advisory — the arbiter is an observer with no inbox "
            "and cannot receive a reply. Do NOT reply; signal by resuming work "
            "(your bridge / hold / store-transition freshness IS the acknowledgment)."
        )
    else:
        reply_affordance = (
            f'↳ Reply via dm_send( recipient="{persona}", body="<your reply>", '
            f'reply_to="{msg_id}", thread_id="{thread_id}" )\n'
            f'{_peer_dm_reply_rider()}'
        )
    reminder_body = (
        f"{PEER_DM_FRAME_PREFIX}{sender_label} (message_id {msg_id}, thread {thread_id}):\n\n"
        f"{body}\n\n"
        f"{reply_affordance}"
    )
    return f"<system-reminder>\n{reminder_body}\n</system-reminder>"


def is_injected_peer_dm( prompt ):
    """
    Is `prompt` an injected peer-DM (a build_peer_dm_reminder envelope delivered as
    the turn's prompt via the listener's idle tmux-wake), rather than genuine USER
    typing? (bug d0d7f068 Part 2 / option C.)

    A peer-DM inject / arbiter tap was never USER re-engagement — so the Stop-hook
    poke-cap reset (user_prompt_submit) must NOT treat it as such (that reset kept
    reopening the poke budget on every inbound DM/tap, so the cap relief valve never
    engaged). This predicate keys on the SHARED PEER_DM_FRAME_PREFIX (never a re-typed
    literal — 46a17f5a). The frame sits inside the <system-reminder> wrapper, so it is
    matched by SUBSTRING (mirrors the arbiter-poke ARBITER_POKE_SENTINEL match).

    Requires:
        - prompt is a string or None (foreign hook-payload data)

    Ensures:
        - Returns True iff prompt is a str containing PEER_DM_FRAME_PREFIX
        - Returns False for None / non-string / genuine user prompts; never raises
    """
    if not isinstance( prompt, str ):
        return False
    return PEER_DM_FRAME_PREFIX in prompt


def format_voice_context( messages ):
    """
    Format drained buffer messages into a context string for CC injection.

    Branches on each message's `direction` (notification-native AI↔AI messaging,
    Phase 3 §6a): a `human_to_ai`/voice message becomes a "[Voice]: ..." line; an
    `ai_to_ai` peer DM becomes a self-contained peer-DM <system-reminder> block
    (built by build_peer_dm_reminder) — NO "[Voice]:" prefix and NO voice rider.

    Requires:
        - messages is a list of dicts (from drain_voice_buffer)

    Ensures:
        - Returns empty string if messages is empty or all messages are blank
        - Each non-empty voice message gets a "[Voice]: " prefix
        - Each non-empty ai_to_ai message becomes a peer-DM reminder block
        - Lines/blocks are joined with newlines
        - Whitespace is stripped from each message body

    Args:
        messages: List of buffered message dicts from voice buffer drain

    Returns:
        str: Newline-joined context (voice lines and/or peer-DM blocks), or ""
    """
    if not messages:
        return ""
    lines = []
    for msg in messages:
        text = msg.get( "message", msg.get( "text", "" ) ).strip()
        if not text:
            continue
        if msg.get( "direction" ) == "ai_to_ai":
            lines.append( build_peer_dm_reminder(
                text,
                persona   = msg.get( "sender_persona" ),
                icon      = msg.get( "sender_icon" ),
                msg_id    = msg.get( "notification_id" ) or msg.get( "id" ),
                thread_id = msg.get( "thread_id" ),
            ) )
        else:
            lines.append( f"{VOICE_LINE_PREFIX}{text}" )
    return "\n".join( lines )


def build_additional_context( context_text, hook_event_name ):
    """
    Build hookSpecificOutput dict with additionalContext for UserPromptSubmit/PostToolUse/PreToolUse.

    Requires:
        - context_text is a string
        - hook_event_name is the event identifier expected by Claude Code's
          hook output schema, e.g. "UserPromptSubmit", "PostToolUse", "PreToolUse"

    Ensures:
        - Returns {} when context_text is empty or falsy (passthrough)
        - Returns { "hookSpecificOutput": { "hookEventName": ..., "additionalContext": ... } } when non-empty

    Args:
        context_text: Formatted voice context string
        hook_event_name: Hook event identifier required by Claude Code schema

    Returns:
        dict: Hook output ready for emit_json(), or empty dict
    """
    if not context_text:
        return {}
    return {
        "hookSpecificOutput": {
            "hookEventName"   : hook_event_name,
            "additionalContext": context_text
        }
    }


def _context_has_human_voice( messages ):
    """
    Structural §6a test: does the drained buffer carry at least one human-voice
    message (direction != "ai_to_ai") with a non-blank body?

    Mirrors format_voice_context's branch + blank-skip EXACTLY so the "is there
    a [Voice]: line in the rendered context?" question is answered from the
    message DIRECTION (structure), never by sniffing the assembled string for a
    "[Voice]: " substring — a peer-DM body that literally contains "[Voice]: "
    must NOT be misread as human voice (F2, Cheech 2026-06-15).

    Requires:
        - messages is a list of buffer dicts, or None

    Ensures:
        - Returns True iff some msg has direction != "ai_to_ai" AND a non-blank
          message/text body (the same predicate that yields a [Voice]: line)
        - Returns False for None/empty/all-ai_to_ai/all-blank

    Args:
        messages: The drained buffer list (same list passed to format_voice_context)

    Returns:
        bool: Whether a human-voice line is present in the rendered context
    """
    for msg in ( messages or [] ):
        if msg.get( "direction" ) == "ai_to_ai":
            continue
        text = msg.get( "message", msg.get( "text", "" ) ).strip()
        if text:
            return True
    return False


def enrich_voice_context( voice_ctx, messages=None ):
    """
    Append notification reminder suffix to voice context string.

    Used by all hooks (PreToolUse, PostToolUse, Stop) to ensure Claude
    always gets the cosa-voice acknowledgment instruction alongside
    voice content.

    The §6a decision — whether to append the human-voice TTS-acknowledge rider —
    is made STRUCTURALLY from `messages` (the drained buffer list), NOT by
    sniffing `voice_ctx` for a "[Voice]: " substring. The old substring check
    leaked the rider onto a pure peer-DM context whenever a DM body happened to
    contain the literal "[Voice]: " marker (F2, Cheech 2026-06-15). Callers pass
    the same `messages` list they handed to format_voice_context.

    Requires:
        - voice_ctx is a string (may be empty)
        - messages is the drained buffer list (or None — treated as "no human
          voice", the §6a-safe default: never wrongly attach the human rider)

    Ensures:
        - Returns empty string if voice_ctx is empty/falsy (passthrough)
        - Returns voice_ctx UNCHANGED when no drained message is human voice
          (a pure peer-DM context, §6a): a peer DM must NOT be answered via TTS
          notify(), so the voice-acknowledge rider is suppressed — the peer-DM
          block already carries its own dm_send reply affordance.
        - Returns voice_ctx + notification reminder when human voice IS present
          (mixed voice+DM keeps the rider, since the voice line still needs it)

    Args:
        voice_ctx: Formatted voice context string from format_voice_context()
        messages:  The drained buffer list (direction-bearing); None → no rider

    Returns:
        str: Enriched voice context with reminder, or voice_ctx unchanged, or ""
    """
    if not voice_ctx:
        return ""
    if not _context_has_human_voice( messages ):
        # Pure peer-DM context (or no human voice) — no TTS-ack rider (§6a).
        return voice_ctx
    return f"{voice_ctx}\n\n{VOICE_ACK_RIDER}"


def build_voice_deny_response( voice_ctx, messages=None ):
    """
    Build PreToolUse deny response when voice buffer has content.

    Combines permissionDecision deny (blocks tool, forces attention)
    with additionalContext (persists voice message into subsequent turns).

    Requires:
        - voice_ctx is a non-empty string containing formatted voice messages
        - messages is the drained buffer list (threaded to enrich_voice_context
          for the structural §6a rider decision), or None

    Ensures:
        - Returns dict with hookSpecificOutput containing:
          - hookEventName: "PreToolUse"
          - permissionDecision: "deny"
          - permissionDecisionReason: instruction to address voice message first
          - additionalContext: voice content + notification reminder (rider added
            only when `messages` carries human voice, §6a)
        - Structure is ready for emit_json()

    Args:
        voice_ctx: Formatted voice context string from format_voice_context()
        messages:  The drained buffer list (direction-bearing); None → no rider

    Returns:
        dict: Hook output that denies the tool call and injects voice context
    """
    return {
        "hookSpecificOutput": {
            "hookEventName"            : "PreToolUse",
            "permissionDecision"       : "deny",
            "permissionDecisionReason" : (
                "A user-initiated voice message was received and takes precedence "
                "over this tool call. You must address the user's message before "
                "continuing. You may re-run this tool afterward if still needed."
            ),
            "additionalContext"        : enrich_voice_context( voice_ctx, messages )
        }
    }


def build_stop_block( reason ):
    """
    Build top-level decision block for Stop hook.

    The Stop hook uses a different structure than PreToolUse/PostToolUse —
    it emits a top-level "decision" + "reason" dict (NOT wrapped in
    hookSpecificOutput).

    Requires:
        - reason is a non-empty string

    Ensures:
        - Returns { "decision": "block", "reason": reason }

    Args:
        reason: Human-readable reason for blocking the stop

    Returns:
        dict: Stop hook decision block ready for emit_json()
    """
    return { "decision": "block", "reason": reason }


def build_stop_block_with_system_message( reason, system_message ):
    """
    Build top-level decision block for Stop hook with systemMessage injection.

    DEPRECATED (Session 336): systemMessage is silently ignored by CC Stop hooks.
    Qualifier injection now uses inject_qualifier_via_tmux(). Kept for test compatibility.

    When a qualifier is present, the stop hook needs BOTH:
    - "reason" for hook logging/metadata (low salience, not reliably acted on)
    - "systemMessage" for conversation injection (high salience, visible to model)

    Requires:
        - reason is a non-empty string (short metadata summary)
        - system_message is a non-empty string (full instruction for the model)

    Ensures:
        - Returns { "decision": "block", "reason": reason, "systemMessage": system_message }

    Args:
        reason: Short metadata reason for blocking the stop
        system_message: Full instruction injected into Claude's conversation context

    Returns:
        dict: Stop hook decision block with systemMessage, ready for emit_json()
    """
    return {
        "decision"      : "block",
        "reason"        : reason,
        "systemMessage" : system_message
    }


def inject_qualifier_via_tmux( session_id, text, delay=TMUX_INJECTION_DELAY, wrap=True ):
    """
    Inject text into Claude Code's tmux input via a detached background process.

    After a stop block, CC enters "waiting for user input" state. This spawns a
    background process that sleeps briefly, then uses tmux send-keys to inject the
    text as first-class user input. Uses bash positional args ($1, $2, $3) to
    safely pass text without shell escaping.

    Requires:
        - session_id is a non-empty string
        - text is a non-empty string (the content to inject)
        - delay is a positive float (seconds before injection)
        - wrap is a bool — True (default) applies the speakerphone voice rider
          (the original idle-qualifier use, where the text is the human's reply).
          False injects the text VERBATIM — for callers that have already built a
          complete <system-reminder> block (e.g. a peer-DM reminder, §6a), which
          must NOT receive the human-voice rider.

    Ensures:
        - Resolves tmux session name from session_id via find_session_by_id()
        - Spawns detached subprocess (start_new_session=True)
        - Background process: sleep → tmux send-keys -l → Enter
        - Returns silently if session not found or on any failure
        - Never raises exceptions

    Args:
        session_id: Claude Code session ID (full or truncated)
        text: Text to inject into CC's input
        delay: Seconds to wait before tmux injection (default: TMUX_INJECTION_DELAY)
        wrap: Apply the speakerphone voice rider (default True); False = verbatim
    """
    try:
        from lupin_cli.claude_code.hooks.lib.session_bridge import find_session_by_id

        session_data = find_session_by_id( session_id )
        if not session_data:
            log_to_stream( "stop", {}, extra={
                "phase"   : "qualifier_tmux_inject_skip",
                "reason"  : "no session found",
                "session" : session_id[:8] if session_id else ""
            } )
            return

        tmux_session = session_data.get( "tmux_session" )
        if not tmux_session:
            log_to_stream( "stop", {}, extra={
                "phase"   : "qualifier_tmux_inject_skip",
                "reason"  : "no tmux_session in bridge data",
                "session" : session_id[:8] if session_id else ""
            } )
            return

        # Phase 5b — speakerphone rider: wrap qualifier text with the per-turn
        # rider. The qualifier comes from the user's reply to the idle-aware
        # Stop hook's "Anything else?" prompt and is injected back into
        # Claude's input — clear inbound path. Skipped for wrap=False callers
        # (e.g. peer-DM reminders), which carry no human-voice contract.
        # See: src/rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/14-phase5-hook-rider-design.md
        if wrap:
            try:
                text = speakerphone_wrap(
                    text,
                    source     = "hook-idle-prompt",
                    session_id = session_id
                )
            except Exception:
                pass  # Non-fatal — fall through with raw text

        subprocess.Popen(
            [ "bash", "-c",
              'sleep "$1" && tmux send-keys -t "$2" -l -- "$3" && sleep 0.25 && tmux send-keys -t "$2" Enter',
              "_",              # $0 placeholder
              str( delay ),    # $1
              tmux_session,    # $2
              text             # $3
            ],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

    except Exception:
        pass  # Hook must never block Claude Code


def deliver_pending_peer_dms( session_id ):
    """
    Drain the voice buffer and tmux-deliver any pending peer DMs (direction=
    ai_to_ai) with NO voice rider, per §6 of
    src/rnd/v0.1.8/2026.06.13-cosa-voice-token-reduction/02-notification-native-aixai-design.md.

    Used by the two hook paths where the main format_voice_context drain does NOT
    run, so a buffered DM would otherwise be discarded/lost:
      - Stop hook, speakerphone branch (early-returns before the main drain;
        every manager runs speakerphone, so this is the manager DM-delivery path).
      - Notification hook at idle_prompt (formerly drain-and-discard).

    Each ai_to_ai entry is framed by the shared build_peer_dm_reminder and
    injected via inject_qualifier_via_tmux( wrap=False ) to wake the pane. Non-DM
    (voice) entries are NOT delivered here — they are returned for the caller's
    normal voice handling (in practice the buffer holds only DMs, since the voice
    path injects directly without buffering).

    Requires:
        - session_id is a non-empty string

    Ensures:
        - Drains the buffer exactly once (atomic drain_voice_buffer)
        - tmux-injects each non-empty ai_to_ai entry, no voice rider
        - Returns the list of non-DM (voice) messages drained but not delivered
        - Never raises (drain + inject are each self-isolating)

    Returns:
        list[dict]: the non-DM (voice) messages drained but not delivered here
    """
    voice_messages = []
    try:
        messages = drain_voice_buffer( session_id )
    except Exception:
        return voice_messages

    for msg in messages:
        if msg.get( "direction" ) != "ai_to_ai":
            voice_messages.append( msg )
            continue
        body = msg.get( "message", msg.get( "text", "" ) ).strip()
        if not body:
            continue
        reminder = build_peer_dm_reminder(
            body,
            persona   = msg.get( "sender_persona" ),
            icon      = msg.get( "sender_icon" ),
            msg_id    = msg.get( "notification_id" ) or msg.get( "id" ),
            thread_id = msg.get( "thread_id" ),
        )
        inject_qualifier_via_tmux( session_id, reminder, wrap=False )

    return voice_messages


def is_mcp_voice_tool( tool_name ):
    """
    Check if tool_name is a cosa-voice MCP tool (direct user communication).

    When Claude calls cosa-voice MCP tools, the LLM is already communicating
    directly with the user. Hooks should NOT drain the buffer or inject context
    during those calls — it would interfere with an active voice conversation.

    Requires:
        - tool_name is a string or None

    Ensures:
        - Returns True if tool_name starts with MCP_VOICE_PREFIX
        - Returns False if tool_name is empty, None, or doesn't match

    Args:
        tool_name: Name of the tool being called

    Returns:
        bool: True if this is a cosa-voice MCP tool
    """
    return tool_name.startswith( MCP_VOICE_PREFIX ) if tool_name else False


# ── Stop Block Counter (safety valve) ────────────────────────────────────────

def _stop_counter_path( session_id ):
    """
    Get the path to the stop block counter file for a CC session.

    Args:
        session_id: Claude Code session ID

    Returns:
        Path: Counter file path in /tmp/
    """
    hash_part = session_id[:8] if session_id else "00000000"
    return Path( f"/tmp/claude-hook-stop-count-{hash_part}" )


def get_stop_block_count( session_id ):
    """
    Read the current block count from the stop counter file.

    Requires:
        - session_id is a string

    Ensures:
        - Returns integer count (0 if file doesn't exist or is unreadable)
        - Never raises exceptions

    Args:
        session_id: Claude Code session ID

    Returns:
        int: Current block count
    """
    try:
        path = _stop_counter_path( session_id )
        if path.exists():
            return int( path.read_text().strip() )
    except ( ValueError, OSError ):
        pass
    return 0


def increment_stop_block_count( session_id ):
    """
    Increment and persist the stop block count. Returns the new count.

    Requires:
        - session_id is a string

    Ensures:
        - Increments count by 1
        - Persists to file
        - Returns new count
        - Returns 1 on first call (file created)
        - Never raises exceptions (returns 0 on failure)

    Args:
        session_id: Claude Code session ID

    Returns:
        int: New block count after increment
    """
    try:
        count = get_stop_block_count( session_id ) + 1
        path  = _stop_counter_path( session_id )
        path.write_text( str( count ) )
        return count
    except OSError:
        return 0


def reset_stop_block_count( session_id ):
    """
    Reset the stop block count to 0 (deletes the counter file).

    Requires:
        - session_id is a string

    Ensures:
        - Counter file is deleted if it exists
        - Never raises exceptions

    Args:
        session_id: Claude Code session ID
    """
    try:
        path = _stop_counter_path( session_id )
        path.unlink( missing_ok=True )
    except OSError:
        pass


# ── Turn Start Marker (duration gating for stop hook) ─────────────────────────

TURN_MARKER_DIR = Path( "/tmp" )


def write_turn_start_marker( session_id ):
    """
    Write epoch timestamp to /tmp/cc-turn-start-{session_id[:8]}.

    Called by UserPromptSubmit hook to record when the user's prompt was submitted.
    The stop hook reads this marker to compute turn duration for gating.

    Requires:
        - session_id is a non-empty string

    Ensures:
        - Creates/overwrites marker file with current epoch timestamp
        - Never raises exceptions
    """
    try:
        marker = TURN_MARKER_DIR / f"cc-turn-start-{session_id[ :8 ]}"
        marker.write_text( str( time.time() ) )
    except OSError:
        pass  # Marker write failure is non-fatal


def get_turn_elapsed_seconds( session_id ):
    """
    Read turn start marker and return elapsed seconds since user prompt.

    Requires:
        - session_id is a non-empty string

    Ensures:
        - Returns float elapsed seconds if marker exists and is readable
        - Returns None if marker missing or unreadable (safe fallback)
        - Never raises exceptions

    Returns:
        float or None: Elapsed seconds since turn start, or None
    """
    try:
        marker      = TURN_MARKER_DIR / f"cc-turn-start-{session_id[ :8 ]}"
        start_epoch = float( marker.read_text().strip() )
        return time.time() - start_epoch
    except ( FileNotFoundError, ValueError, OSError ):
        return None


# ── Voice Buffer Functions ────────────────────────────────────────────────────

# Row 8ccc20ab — derived from the one seam (see lib/sessions_dir.py).
SESSION_DIR = sessions_dir()


def get_buffer_path( session_id ):
    """
    Get the JSONL buffer file path for a CC session.

    Requires:
        - session_id is a non-empty string

    Ensures:
        - Returns Path to buffer file in ~/.claude/sessions/
        - Truncates session_id to first 8 chars

    Args:
        session_id: Claude Code session ID (full or truncated)

    Returns:
        Path: Buffer file path (e.g., ~/.claude/sessions/cc-buffer-abc12345.jsonl)
    """
    hash_part = session_id[:8] if session_id else "00000000"
    return SESSION_DIR / f"cc-buffer-{hash_part}.jsonl"


def drain_voice_buffer( session_id ):
    """
    Atomically drain the voice buffer for a CC session.

    Implements atomic rename-read-delete pattern:
    1. Rename buffer file to random /tmp/ path (atomic on same filesystem? no,
       but os.rename across filesystems will fail, so we copy+delete)
    2. Read all JSONL lines from temp file
    3. Delete temp file

    Only one concurrent drain succeeds — the first os.rename() wins, others
    get FileNotFoundError and return empty list.

    Requires:
        - session_id is a non-empty string

    Ensures:
        - Returns list of message dicts from buffer
        - Returns empty list if no buffer exists or drain fails
        - Buffer file is consumed (deleted) after successful drain
        - Thread-safe via atomic rename
        - Never raises exceptions

    Args:
        session_id: Claude Code session ID (full or truncated)

    Returns:
        list[dict]: List of buffered message dicts, in chronological order
    """
    buffer_path = get_buffer_path( session_id )

    if not buffer_path.exists():
        return []

    # Random drain path in /tmp to avoid collision with concurrent drains
    hash_part = session_id[:8] if session_id else "00000000"
    drain_id  = uuid.uuid4().hex[:8]
    drain_path = Path( f"/tmp/cc-drain-{hash_part}-{drain_id}.jsonl" )

    try:
        # Atomic rename — only one concurrent drain succeeds
        os.rename( str( buffer_path ), str( drain_path ) )
    except ( FileNotFoundError, OSError ):
        # Another hook already drained it, or file vanished
        return []

    messages = []
    try:
        with open( drain_path ) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        messages.append( json.loads( line ) )
                    except json.JSONDecodeError:
                        pass  # Skip malformed lines
    except OSError:
        pass  # File read error — return whatever we got
    finally:
        try:
            drain_path.unlink( missing_ok=True )
        except Exception:
            pass

    return messages


# ── Permission Decision Builder ──────────────────────────────────────────────

def build_permission_decision( behavior, message=None, interrupt=False ):
    """
    Build the hookSpecificOutput dict for a PermissionRequest hook.

    Constructs the JSON structure that Claude Code expects from a
    PermissionRequest hook to allow or deny a tool call.

    Requires:
        - behavior is "allow" or "deny"
        - message is a string or None (only used for deny)
        - interrupt is a bool (only used for deny)

    Ensures:
        - Returns dict with hookSpecificOutput.decision.behavior
        - For "allow": ignores message and interrupt
        - For "deny": includes message and interrupt if provided
        - Structure: { "hookSpecificOutput": { "decision": { ... } } }

    Args:
        behavior: "allow" or "deny"
        message: Optional denial reason (ignored for allow)
        interrupt: Whether to interrupt Claude Code (ignored for allow)

    Returns:
        dict: Hook output ready for emit_json()
    """
    decision = { "behavior": behavior }

    if behavior == "deny":
        if message is not None:
            decision[ "message" ] = message
        if interrupt:
            decision[ "interrupt" ] = True

    return {
        "hookSpecificOutput": {
            "decision": decision
        }
    }


# ── Speakerphone Wrap (per-turn rider) ────────────────────────────────────────
#
# Per src/rnd/v0.1.9/2026.06.27-cosa-voice-rider-slim.md (Rick-approved
# 2026-06-27; predecessors: .../2026.05.11-tts-interaction-mode-solo-chorus/
# 14-phase5-hook-rider-design.md + .../2026.04.30-conv-mode-three-layer-
# enforcement/01-design.md).
#
# The per-turn rider is now SLIM and UNCONDITIONAL: it carries only what is
# true-now-and-changed (the live input modality + the one catastrophic rule,
# the spoken-char reject cap) and points at the standing TTS contract that
# lives once in the cosa-voice MCP server's `instructions` payload. The
# predecessor 4-variant matrix — solo/chorus framing and speakerphone-state
# branching — is dropped: speakerphone is assumed ON unconditionally (the
# get_session_info speakerphone flag is unreliable; decision §0.3). No flag
# reads, no branching.
#
# Sanitization at the boundary still closes the prompt-injection escape vector
# (§2.4a of the predecessor design doc).

# Markers stripped by sanitize_for_wrap to prevent user content from escaping
# the wrapper or injecting a fake system-reminder. First-marker-wins; case
# insensitive.
_SANITIZE_MARKERS = ( "</voice-message", "<system-reminder" )

# Sentinel substring used to detect already-wrapped strings for idempotency.
# The slim rider always contains this phrase, so the check is universal.
_SPEAKERPHONE_WRAP_SENTINEL = "TTS contract ACTIVE"

# Chars-per-word used to convert the server's CHARACTER reject cap into the WORD
# budget the rider actually states (Rick, 2026-07-19: "LLMs suck at counting
# characters, but they know what words are").
#
# 8.3 is DELIBERATELY PESSIMISTIC. Spoken English averages ~6 chars/word incl.
# the space; budgeting at 8.3 means a compliant reply lands ~360 chars against a
# 500-char cap — roughly 28% headroom. The asymmetry is intentional: overshooting
# the char cap fails SILENTLY (the whole notify/ask is rejected and reads as the
# assistant going mute), while undershooting merely costs a few words. Round the
# error toward the recoverable side.
#
# Calibrated so the default cap (500) yields Rick's stated budget of 60 words.
_SPOKEN_CHARS_PER_WORD = 8.3


def spoken_word_budget( char_cap ):
    """
    Convert the server's spoken CHARACTER reject cap into a WORD budget.

    The enforcement threshold is and remains CHARACTERS — this is the guidance
    denomination only. It exists because the consumer of the rider (an LLM)
    cannot reliably count characters but counts words well, so a char figure is
    an unactionable instruction dressed as a precise one.

    Deriving rather than hardcoding keeps the single-source invariant intact: if
    cu.get_spoken_char_cap() ever moves, the stated word budget moves with it and
    cannot silently drift into permitting a payload the server will reject.

    Requires:
        - char_cap is a positive number

    Ensures:
        - returns a positive int, floored at 1 (never a zero/negative budget)
        - the budget is CONSERVATIVE: budget * average-real-chars-per-word stays
          comfortably under char_cap (see _SPOKEN_CHARS_PER_WORD)
        - never raises on a positive numeric input
    """
    return max( 1, int( char_cap / _SPOKEN_CHARS_PER_WORD ) )


def sanitize_for_wrap( text ):
    """
    Strip user content from the first occurrence of </voice-message or
    <system-reminder (case-insensitive) to end-of-string. Closes the
    prompt-injection escape vector at the wrapper boundary.

    Requires:
        - text is a string

    Ensures:
        - Returns text unchanged if neither marker present
        - Returns text[ :first_marker_index ] if either marker present
        - Whichever marker appears first wins (first-marker-wins)
        - Match is case-insensitive (lower() comparison)
        - Empty input returns empty

    Args:
        text: Raw user content prior to wrapping

    Returns:
        str: Sanitized content safe for substitution into the wrapper
    """
    if not text: return text

    lower   = text.lower()
    indices = [ lower.find( m ) for m in _SANITIZE_MARKERS ]
    indices = [ i for i in indices if i >= 0 ]
    if not indices: return text

    return text[ :min( indices ) ]


def _brevity_rules():
    """
    The TTS brevity-rules block migrated from CLAUDE.md per Phase 5 of the
    speakerphone refactor. Post rider-slim (2026-06-27) this is single-sourced
    into the cosa-voice MCP server's `instructions` payload (the once-stated
    § Speakerphone TTS Contract); it is no longer composed into the per-turn
    rider, which now only points at that contract. Kept here so the rider, the
    contract, and the caller-side enforcement guard all read ONE definition.

    Per ratified PIP S110 (Rick-approved, 2026-06-15): the spoken target is
    SENTENCE-based (max 3), NOT word/char COUNTING — LLMs count sentences
    reliably but not words/chars. The named char cap is the server REJECT
    BOUNDARY, not a target; it is single-sourced via cu.get_spoken_char_cap()
    (lupin-app.ini key "cosa voice spoken char cap") — the SAME source the
    caller-side enforcement guard reads — so the rider's number and the
    enforcement check can never drift.

    Ensures:
        - Returns a non-empty paragraph describing how the closing `notify()`
          spoken-text should differ from the terminal reply
        - Interpolates the live spoken-char reject boundary

    Returns:
        str: Brevity guidance text
    """
    cap = cu.get_spoken_char_cap()
    return (
        "Brevity for TTS: re-craft the spoken `message` for speech — don't pipe "
        "terminal markdown through `notify()`. Strip headings, bullets, code "
        "fences, inline backticks, file:line refs, JSON, hashes, URLs (all "
        "TTS-hostile). Max 3 sentences: s1 = headline/verdict, s2-3 = at most "
        "two takeaways. All rich detail goes in `abstract` (UI card; not "
        "length-limited). Speak the verdict, not the inventory. HARD LIMIT: the "
        f"server REJECTS a spoken payload over ~{cap} chars — the ENTIRE "
        "notify/ask fails (perceived silence + burned retries); if you're near "
        "it, cut to a headline, don't trim word-by-word. For ask_*/converse: the "
        "spoken question is ONE short line (the question only) — pros/cons + "
        "your recommended option go in the option descriptions + `abstract`, "
        "never in the spoken text. Acknowledge receipt in one sentence before "
        "tool calls."
    )


def _routing_reminder():
    """
    The cosa-voice routing-reminder block migrated from CLAUDE.md per Phase 5
    of the speakerphone refactor. Post rider-slim (2026-06-27) this is
    single-sourced into the cosa-voice MCP server's `instructions` payload (the
    once-stated § Speakerphone TTS Contract); it is no longer composed into the
    per-turn rider. Kept here so the contract reads ONE definition.

    Ensures:
        - Returns a non-empty paragraph mapping interaction types to cosa-voice
          MCP blocking tools

    Returns:
        str: Routing reminder text
    """
    return (
        "Interactive tool routing: PREFER cosa-voice MCP blocking tools over "
        "AskUserQuestion. Yes/no goes to `ask_yes_no`. Two to four options "
        "goes to `ask_multiple_choice`. Open-ended goes to `converse`. Multiple "
        "open-ended goes to `ask_open_ended_batch`. AskUserQuestion renders to "
        "the terminal only — the user is listening, not watching."
    )


def _speakerphone_reminder_body( source ):
    """
    Build the slim per-turn rider body for the given input source. The body is
    plain text — no wrapping <system-reminder> tags (those are added by the
    caller).

    Per src/rnd/v0.1.9/2026.06.27-cosa-voice-rider-slim.md (Rick-approved
    2026-06-27): the rider carries ONLY what is true-now-and-changed — the live
    input modality plus the one catastrophic rule (the spoken-char reject cap).

    BREVITY ACRONYMS PROMOTED TO BULLET 1 (Rick, 2026-07-19, direct order): the
    rider previously stated the cap MECHANICALLY ("spoken ≤3 sentences AND ≤N
    chars … cut to a headline") and never named the mandate the fleet is
    actually drilled on. Rick: "What's missing? The entire notion of KISS 3LoL,
    NoAA, etc." The acronyms now LEAD the list and carry the cap with them —
    substitution, not addition, so the rider does not grow. The reject-cap fact
    is KEPT on that same bullet deliberately: it is the one rule whose breach
    fails SILENTLY (the whole notify is rejected, read as the assistant going
    mute), so dropping it to seat the acronyms would trade a catastrophic
    warning for a mnemonic. Acronym text mirrors the peer-DM/STT riders
    (ac661631, bc2b5fe9) so all three surfaces read identically.
    The full standing TTS contract lives once in the cosa-voice MCP server's
    `instructions` payload, not repeated turn-to-turn. The predecessor
    4-variant matrix (solo/chorus framing + speakerphone-state branching) is
    dropped: speakerphone is assumed ON unconditionally (decision §0.2/§0.3 —
    the get_session_info speakerphone flag is currently unreliable). No flag
    reads, no branching — only the input-modality token is dynamic.

    The named char cap is single-sourced from cu.get_spoken_char_cap() — the
    SAME source the caller-side enforcement guard and the `instructions`
    contract read — so the rider's number can never drift between surfaces.

    Requires:
        - source is one of: "voice", "terminal-typed",
          "hook-idle-prompt", "hook-permission-prompt"

    Ensures:
        - Returns a non-empty string body
        - Always contains the _SPEAKERPHONE_WRAP_SENTINEL substring
          (idempotency check rides on this invariant)
        - The input-modality token is "voice(distance)" for source=="voice",
          "typed" for every other source

    Args:
        source: Which injection point the text came from

    Returns:
        str: System-reminder body text (the slim per-turn rider)
    """
    cap      = cu.get_spoken_char_cap()
    words    = spoken_word_budget( cap )
    modality = "voice(distance)" if source == "voice" else "typed"
    return (
        f"[turn-state] input={modality}\n"
        "TTS contract ACTIVE — full rules in session instructions. This turn:\n"
        f"• KISS · 3LoL · NoMC C2C · NoAA — verdict first, ≤3 sentences AND ≤{words} words; OVER = whole call REJECTED (silent fail). Longer ONLY WHEN ASKED\n"
        "• after replying, call notify(message=<reply>, suppress_ding=True, priority='high')\n"
        "• recraft for speech — no markdown/paths/JSON/URLs\n"
        "• rich detail → abstract (not length-capped)\n"
        "• questions → cosa-voice ask_yes_no / ask_multiple_choice / converse / ask_open_ended_batch — never AskUserQuestion\n"
        "• ack receipt in 1 line before tool calls"
    )


def speakerphone_wrap( text, *, source, session_id=None ):
    """
    Wrap inbound text with the slim per-turn speakerphone rider. The rider
    fires on every turn and is now UNCONDITIONAL — it no longer reads the
    speakerphone flag or the interaction mode (decision §0.3 of the rider-slim
    doc: the flag is unreliable, so speakerphone is assumed ON; only the input
    modality is dynamic). See _speakerphone_reminder_body for the body.

    For source="voice", the output also includes a <voice-message> envelope
    describing voice INPUT properties (from-distance, priority, suppress-ding).
    For non-voice sources, only the <system-reminder> rider is appended.

    Sanitization runs FIRST to close the prompt-injection escape vector
    documented as F2 in the adversarial-review pass of the predecessor
    three-layer-enforcement design.

    Idempotency: if the input already contains the wrapper sentinel, it is
    returned unchanged (safe to call multiple times on the same string).

    Per src/rnd/v0.1.9/2026.06.27-cosa-voice-rider-slim.md.

    Requires:
        - text is a string
        - source is one of: "voice", "terminal-typed",
          "hook-idle-prompt", "hook-permission-prompt" (keyword-only)
        - session_id is a non-empty string OR None (keyword-only). Caller
          must provide session_id explicitly; this helper does not resolve
          it implicitly to keep behavior predictable in subprocess contexts
          (e.g. cc_notification_listener).

    Ensures:
        - Returns text unchanged if text is empty, OR session_id is None or
          empty (fail-closed pass-through)
        - Returns text unchanged if input already contains the wrapper
          sentinel (idempotency)
        - Returns text unchanged if any error occurs building the rider body
          (fail-closed — safer than injecting a half-built rider)
        - Otherwise returns wrapped output: <voice-message> envelope (voice
          source only) + sanitized content + <system-reminder> slim rider body

    Args:
        text:       Raw text being injected into Claude's input stream
        source:     Which injection point the text came from (keyword-only)
        session_id: Session ID to look up in the bridge (keyword-only)

    Returns:
        str: Wrapped text or original text (when fail-closed)
    """
    if not text or not session_id: return text

    # Idempotency — don't re-wrap an already-wrapped string
    if _SPEAKERPHONE_WRAP_SENTINEL in text: return text

    try:
        reminder_body = _speakerphone_reminder_body( source )
    except Exception:
        # Fail-closed — any error building the rider body means pass through
        # unwrapped (safer than injecting a half-built rider).
        return text

    clean = sanitize_for_wrap( text )

    if source == "voice":
        return (
            f'<voice-message from-distance="true" priority="high" suppress-ding="true">\n'
            f'{clean}\n'
            f'</voice-message>\n'
            f'<system-reminder>\n'
            f'{reminder_body}\n'
            f'</system-reminder>'
        )

    return (
        f'{clean}\n\n'
        f'<system-reminder>\n'
        f'{reminder_body}\n'
        f'</system-reminder>'
    )


def speakerphone_exit_reminder( mode ):
    """
    Build the deactivation system-reminder injected when a session
    transitions out of speakerphone mode. Body content varies by mode:

      - Solo mode: deactivation can be either displacement (another session
        activated speakerphone, mutex flipped this one off) OR self-exit
        (UI toggle / MCP disable_speakerphone() / voice phrase / slash
        command). Body wording covers both.
      - Chorus mode: no displacement — deactivation is user-initiated only.
        Body wording omits the displacement framing.

    Unlike speakerphone_wrap and speakerphone_reminder_block (which gate on
    the bridge file's current state), this helper emits its body
    unconditionally. The caller is responsible for invoking it only at the
    moment of a transition. Callers go through the listener subprocess
    responding to an `action:disable_speakerphone` push from the
    speakerphone router; see src/cosa/rest/routers/speakerphone.py.

    The reminder is delivered as a synthetic user prompt via the listener's
    tmux injection path. By the time the deactivated session "comes up for
    air" at its prompt, this text has been queued in tmux's input buffer;
    when Claude Code processes the next prompt, it sees the reminder and
    reverts to notification-mode behavior (no auto-notify, no voice-message
    wrap on responses).

    Requires:
        - mode is "solo" or "chorus" (any other value falls through to the
          chorus body — safest default per Phase 1 INI default)

    Ensures:
        - Returns a non-empty <system-reminder>…</system-reminder> block
        - Body matches the quiet-mode rider's semantic (keep calling notify()
          for milestones / errors / closing-turn summary, BUT demote priority
          from 'high' to 'medium' and flip suppress_ding from True to False)
        - Body does NOT contain the entry-side wrapper sentinel
          (_SPEAKERPHONE_WRAP_SENTINEL) so idempotency in speakerphone_wrap
          doesn't false-positive when an exit reminder is itself wrapped
        - Output is safe to inject via tmux send-keys -l (no special chars
          beyond what tmux literal mode handles)

    2026-05-14 evening rewrite: the previous exit reminder said "stop calling
    notify(), resume terminal-only output" — that contradicted the new
    quiet-mode rider which says "keep calling notify() with demoted priority
    to preserve the historical record." The two rider sources were firing in
    the same turn on a fresh deactivation, producing conflicting instructions.
    The exit reminder now matches the quiet-mode body: same demotion
    directive, plus the one-time framing that the transition just happened.

    Args:
        mode: TTS interaction mode ("solo" or "chorus")

    Returns:
        str: <system-reminder> block ready for tmux injection
    """
    common_quiet_directive = (
        "This session has just transitioned to QUIET mode (per-session DND). "
        "The historical record matters — keep calling `notify()` for "
        "milestones, errors, action-required prompts, and the closing-turn "
        "summary — BUT use `priority='medium'` and `suppress_ding=False` (NOT "
        "the standard `priority='high', suppress_ding=True`). The user wants "
        "the small arrival ding without full TTS playback. Detail still goes "
        "in the `abstract` parameter. Acknowledge this transition silently — "
        "do not announce it to the user."
    )
    if mode == "solo":
        body = (
            "Speakerphone has just been deactivated for this session — either "
            "another session activated speakerphone and displaced you, or you "
            "toggled off. " + common_quiet_directive
        )
    else:  # chorus (or unknown — default to chorus per INI default)
        body = (
            "Speakerphone has just been deactivated for this session. "
            + common_quiet_directive
        )
    return f'<system-reminder>\n{body}\n</system-reminder>'


def speakerphone_reminder_block( source, session_id ):
    """
    Return just the <system-reminder> block (no <voice-message> envelope)
    for callers that can only emit additionalContext rather than transform
    the user's input — e.g., the user_prompt_submit hook.

    The rider fires on every turn (when session_id is resolvable) and is now
    UNCONDITIONAL — it no longer reads the speakerphone flag or the interaction
    mode (decision §0.3 of the rider-slim doc: speakerphone is assumed ON; only
    the input modality is dynamic). See _speakerphone_reminder_body.

    Requires:
        - source is one of: "voice", "terminal-typed",
          "hook-idle-prompt", "hook-permission-prompt"
        - session_id is a non-empty string OR None

    Ensures:
        - Returns empty string if session_id missing or any error building the
          rider body (fail-closed)
        - Returns formatted <system-reminder>…</system-reminder> block
          otherwise — the slim rider body for the given source

    Args:
        source:     Which injection point's reminder body to use
        session_id: Session ID to look up in the bridge

    Returns:
        str: Reminder block or empty string
    """
    if not session_id: return ""

    try:
        body = _speakerphone_reminder_body( source )
    except Exception:
        return ""

    return f'<system-reminder>\n{body}\n</system-reminder>'


# ── Quick smoke test ─────────────────────────────────────────────────────────

if __name__ == "__main__":

    print( f"LOGS_DIR:  {_logs_dir()}" )
    print( f"TTS enabled: {is_tts_enabled()}" )
    print( f"Target email: {get_target_email()}" )
    print( f"Timestamp: {get_timestamp()}" )

    # Test logging
    test_payload = { "test": True, "session_id": "smoke-test" }
    log_payload( "smoke_test", test_payload )
    print( f"Log written to: {_logs_dir()}/smoke_test-*.json" )

    # Test emit
    print( "\nEmit test:" )
    emit_json( { "status": "ok", "hook": "smoke_test" } )
