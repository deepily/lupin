#!/usr/bin/env python3
"""
CC Notification Listener — stateful WebSocket client for Claude Code sessions.

Subclasses BaseWebSocketListener to buffer user_initiated_message notifications
targeted at a specific CC session. Instead of auto-responding (like the
notification proxy), this listener writes matching messages to a local JSONL
buffer file that hooks drain atomically.

Lifecycle:
    1. SessionStart hook spawns this as a background subprocess
    2. Authenticates via JWT (credentials from ~/.lupin/config)
    3. Connects via WebSocket, subscribes to notification_queue_update
    4. Filters by job_id matching CC session hash
    5. Appends matching messages to ~/.claude/sessions/cc-buffer-{session_id[:8]}.jsonl
    6. Hooks call drain_voice_buffer() to atomically consume buffered messages
    7. SessionEnd hook sends SIGTERM for graceful shutdown

Usage:
    python -m lupin_cli.claude_code.hooks.lib.cc_notification_listener \\
        --session-id abc12345 \\
        --debug

    # Or from SessionStart hook:
    subprocess.Popen( [sys.executable, "-m",
        "lupin_cli.claude_code.hooks.lib.cc_notification_listener",
        "--session-id", session_hash, "--buffer-path", buffer_path] )
"""

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from cosa.agents.utils.proxy_agents.base_listener import BaseWebSocketListener
from cosa.agents.utils.proxy_agents.base_config import (
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
)
from lupin_cli.claude_code.hooks.lib.session_bridge import build_sender_id_for_cc
from lupin_cli.claude_code.hooks.lib.listener_processes import tmux_injection_lock
from lupin_cli.claude_code.hooks.lib.sessions_dir import sessions_dir


# ── Constants ─────────────────────────────────────────────────────────────────

# Row 8ccc20ab — derived from the one seam (see lib/sessions_dir.py).
SESSION_DIR       = sessions_dir()
CENTRALIZED_LOG   = SESSION_DIR / "cc-listeners.log"
SUBSCRIBED_EVENTS = [ "notification_queue_update" ]

# Transport budget for this listener's out-of-process HTTP calls to `:7999`
# (row 204911ca). ~30s = 1.60x the observed maximum reload window of 18.76s — a
# multiplier with explicit headroom, NOT a coverage guarantee. `:7999` runs
# `uvicorn --reload`; the reloader parent keeps the listening socket bound
# across a restart, so the kernel ACCEPTS a request nothing is there to answer
# and the caller hangs rather than getting a fast ConnectionRefused. The prior
# 10.0s was the closest of the cohort but still under the 18.76s max.
#
# Full derivation: src/rnd/v0.1.9/2026.07.19-dev-server-reload-availability.md §9(a).
#
# 🔴 DRIFT CONTROL — TWO SEARCHES, AND IT TOOK BOTH.
# `grep -rn _SERVER_TRANSPORT_TIMEOUT_SECONDS` returns every DIRECT call site.
# It does NOT return members whose budget is carried in a Pydantic FIELD rather
# than passed at the call — `AsyncNotificationRequest( timeout=… )`, consumed at
# `notify_user_async.py:197-201` as a bare `requests.post( timeout=request.timeout )`.
# Two such members were missed on the first pass for exactly this reason.
# The second search is: `grep -rn "AsyncNotificationRequest(" -A14 | grep timeout`.
# Run BOTH, or the set you get back is the set the first grep can see.
#
# ⚠️ SCOPE — this covers the HTTP user_id stamp calls ONLY. It does NOT apply to
# the WebSocket read in base_listener.py, where a reload does not HANG the
# connection, it KILLS it. That is a reconnect problem, not a budget problem;
# bumping a timeout there fixes nothing.
#
# TRADE: a genuinely hung server stalls a stamp ~30s instead of ~10s. This is a
# long-lived daemon with no latency pressure on these calls, so the cost is low.
_SERVER_TRANSPORT_TIMEOUT_SECONDS = 30

# 🔴 F5 — THE FIELD-CARRIED BUDGET IS A SEPARATE NUMBER, NOT THE COHORT'S.
# The gist notification at `_send_gist_response` does NOT pass its budget at the
# call; it sets `AsyncNotificationRequest( timeout=… )`, which
# `notify_user_async.py` consumes as a bare `requests.post( timeout=… )`. Two
# things make the cohort constant the wrong value there:
#
#   1. THAT PATH RETRIES, and `calculate_retry_intervals( request.timeout )`
#      derives the retry schedule FROM the number — so the cohort's 30 would
#      cost **267s** of wall clock, not 30s, on a listener callback. 6 rides out
#      the same 18.76s window in 28s. Full table in `hook_common.py`.
#   2. THE FIELD IS BOUNDED. `AsyncNotificationRequest.timeout` is
#      `Field( ge=1, le=30 )` (`notification_models.py:620-625`). Wiring the
#      cohort constant in here armed a tripwire: a future re-measure raising it
#      to, say, 45 would make the two `urlopen` sites take it correctly while
#      THIS site threw ValidationError inside `except Exception: self._log(…)` —
#      gist responses would stop SILENTLY, and the traceback would say
#      "validation error", not "budget too high".
#
# The assert below is the guard, and it fails at import rather than at runtime.
NOTIFY_TRANSPORT_TIMEOUT_SECONDS = 6

# Fails loudly at import if THIS MODULE'S budget is pushed past the Pydantic bound
# it has to fit through. A comment warning about this hazard is not a control;
# this is.
#
# 🔴 SCOPE, stated because the earlier wording here said "either budget" and that was
# FALSE: this assert guards `cc_notification_listener.NOTIFY_TRANSPORT_TIMEOUT_SECONDS`
# and NOTHING ELSE. `hook_common.py` declares a same-named constant feeding the same
# `Field( le=30 )` through the same swallowed-except consumer, and it carries its OWN
# duplicate assert — because a guard in this module cannot run for that one. Raising
# only one of the two is caught only by the guard beside it.
assert NOTIFY_TRANSPORT_TIMEOUT_SECONDS <= 30, (
    "NOTIFY_TRANSPORT_TIMEOUT_SECONDS exceeds AsyncNotificationRequest.timeout's "
    "Field( le=30 ) — raise the field bound in notification_models.py first, or "
    "this fails as an opaque ValidationError inside a swallowed except"
)

# ── Pane-idle probe sentinels (bug d1bb1456) ────────────────────────────────────
# The pane-idle probe (`_pane_is_idle_at_prompt`) reads the RECIPIENT tmux pane's
# real state to decide whether it is safe to inject/wake a peer DM. These sentinel
# sets are the ONLY CLI-UI-coupled surface: they are strings the Claude Code TUI
# paints, and a CLI upgrade can change them. That coupling is DELIBERATELY isolated
# here (+ pinned by test_pane_probe_sentinels_documented) so a UI change is a
# one-line edit, and — critically — an UNRECOGNISED status line fails the positive
# idle check and degrades to BUFFER (fail-open direction: never a false inject).
#
# Empirically confirmed on live panes 2026-07-02 (see the triage doc).

# A RUNNING turn paints the interrupt affordance in its live status line; a pane
# parked at an idle prompt does not. Presence ⇒ BUSY ⇒ never inject.
BUSY_STATUS_SENTINELS = ( "esc to interrupt", )

# Permission / trust / AskUserQuestion dialogs show NO "esc to interrupt", so naive
# absence-logic would type INTO the dialog and could select an option. Presence of
# any of these ⇒ a modal is up ⇒ never inject (Mr. Radio hardening #2, 2026-07-02).
DIALOG_SENTINELS = (
    "Do you want to proceed",
    "Would you like to",
    "No, and tell Claude",
    "Yes, and don't ask again",
    "esc to reject",
    "❯ 1.",
    "1. Yes",
)

# POSITIVE idle signal (Mr. Radio hardening #1): the normal input prompt paints a
# full-width horizontal-rule divider around the entry box. Requiring it means mere
# busy-sentinel ABSENCE never classifies idle — an unknown/blank state has no
# divider ⇒ not-injectable ⇒ buffer. 40 rules is well below the real width (~128+)
# yet long enough to never match incidental box-drawing.
IDLE_PROMPT_DIVIDER   = "─" * 40          # "────…" (40×)

# Transition-race guard (Mr. Radio hardening #1): a turn that is STARTING may not
# have painted "esc to interrupt" yet. Require TWO captures this far apart to BOTH
# classify idle before injecting.
PANE_PROBE_RECHECK_SECONDS = 0.3

# How often the owner watchdog asks "is the Claude Code process that owns me still
# alive?". The listener is spawned with start_new_session=True (setsid), so it is
# reparented to init and NEVER receives the SIGHUP tmux sends its panes when the
# tmux server dies. Its only other reaper is the SessionEnd hook, which by
# definition cannot run when the session is killed abruptly. Without this poll a
# hard death (tmux kill-server, crash, SIGKILL) strands the listener forever,
# still authenticated and still holding its WebSocket to the notifications UI.
OWNER_WATCHDOG_INTERVAL_SECONDS = 30

# Memory sampler (opt-in, --memory-trace). On 2026-07-14 two orphaned listeners held
# 684 MB each against a ~35 MB baseline while logging only ~13 notifications — a
# one-time large allocation, not message accumulation. The orphans were reaped before
# they could be profiled, so the leak has no root cause yet. This sampler exists to
# catch the NEXT one with a real allocation traceback instead of archaeology. It is
# OFF by default (zero tracemalloc overhead) and only arms under the flag.
MEMORY_SAMPLE_INTERVAL_SECONDS = 60
# Log a tracemalloc top-N dump when RSS grows by at least this much since the last dump.
MEMORY_GROWTH_DUMP_THRESHOLD_MB = 100
MEMORY_TOP_ALLOCATIONS          = 10


def read_self_rss_mb():
    """
    This process's resident set size in MB, from /proc/self/status.

    Ensures:
        - Returns RSS in MB as a float, or None if /proc is unreadable
    """
    try:
        with open( "/proc/self/status" ) as fh:
            for line in fh:
                if line.startswith( "VmRSS:" ):
                    return int( line.split()[ 1 ] ) / 1024.0
    except ( OSError, ValueError, IndexError ):
        return None
    return None


# ── Owner liveness (PID-reuse safe) ───────────────────────────────────────────

def read_proc_starttime( pid ):
    """
    Read a process's start-time (field 22 of /proc/<pid>/stat) as a string.

    This is the PID-reuse guard. A bare os.kill( pid, 0 ) is not sufficient: if the
    owner dies and the kernel recycles its PID onto an unrelated process, the naive
    check reports "alive" forever and the listener never reaps itself — the exact bug
    this watchdog exists to close. Start-time pins the identity: a recycled PID always
    carries a different start-time.

    Requires:
        - pid is a positive integer

    Ensures:
        - Returns the start-time field as a string, or None if the process is gone
          or /proc is unreadable

    Args:
        pid: Process ID to inspect

    Returns:
        str or None: start-time (clock ticks since boot), or None if unreadable
    """
    try:
        with open( f"/proc/{pid}/stat" ) as fh:
            data = fh.read()
    except ( FileNotFoundError, ProcessLookupError, PermissionError, OSError ):
        return None

    # Format: pid (comm) state ppid ... — comm can itself contain spaces and parens,
    # so split AFTER the final ')'. fields_after_comm[0] is state (field 3), hence
    # start-time (field 22) sits at index 19.
    close_paren = data.rfind( ")" )
    if close_paren == -1:
        return None

    fields_after_comm = data[ close_paren + 2 : ].split()
    if len( fields_after_comm ) < 20:
        return None

    return fields_after_comm[ 19 ]


def owner_is_alive( owner_pid, owner_starttime ):
    """
    Is the Claude Code process that owns this listener still running?

    Requires:
        - owner_pid is a positive integer
        - owner_starttime is the start-time captured when the listener booted, or
          None if it could not be captured

    Ensures:
        - Returns False when the PID is gone
        - Returns False when the PID exists but carries a DIFFERENT start-time
          (the PID was recycled onto a new process — the owner is still dead)
        - Returns True only when the PID exists AND its start-time matches

    Args:
        owner_pid: PID of the owning Claude Code process
        owner_starttime: start-time pinned at listener startup

    Returns:
        bool: True if the original owner process is still alive
    """
    current = read_proc_starttime( owner_pid )
    if current is None:
        return False

    # No pinned start-time (couldn't read /proc at boot) — fall back to bare
    # existence. Weaker, but strictly better than never checking at all.
    if owner_starttime is None:
        return True

    return current == owner_starttime


# ── Listener ──────────────────────────────────────────────────────────────────

class CCNotificationListener( BaseWebSocketListener ):
    """
    WebSocket listener that buffers user_initiated_message notifications
    for a specific Claude Code session.

    Requires:
        - email and password are valid credentials
        - session_id_hash is the 8-char CC session hash
        - buffer_path is a writable file path

    Ensures:
        - Only buffers notifications where job_id matches session_id_hash
        - Only buffers notifications of type user_initiated_message
        - Writes one JSON object per line (JSONL format)
        - Flushes after each write for immediate availability
        - Handles SIGTERM for graceful shutdown
    """

    LOG_PREFIX = "[CC-Listener]"

    def __init__(
        self,
        email,
        password,
        session_id_hash,
        buffer_path          = None,
        tmux_session         = None,
        accepted_ids         = None,
        host                 = DEFAULT_SERVER_HOST,
        port                 = DEFAULT_SERVER_PORT,
        debug                = False,
        verbose              = False,
        log_file_path        = None,
        centralized_log_path = None,
        owner_pid            = None,
        memory_trace         = False,
    ):
        """
        Initialize the CC Notification Listener.

        Requires:
            - email is a non-empty string
            - password is a non-empty string
            - session_id_hash is a non-empty string (8-char hex)

        Ensures:
            - Stores session hash for job_id filtering
            - Builds accepted_ids set from explicit list or falls back to {session_id_hash}
            - Computes default buffer path if not provided
            - Does NOT connect (call run() to start)

        Args:
            email: User email for JWT authentication
            password: User password for JWT authentication
            session_id_hash: 8-char CC session hash for filtering
            buffer_path: Path to JSONL buffer file (default: auto-computed)
            tmux_session: Explicit tmux session name override (default: auto-resolve)
            accepted_ids: Set of 8-char hashes to accept (default: {session_id_hash})
            host: Server hostname (default: localhost)
            port: Server port (default: 7999)
            debug: Enable debug output
            verbose: Enable verbose output (implies debug)
            log_file_path: Optional path to tee all output to a log file
            centralized_log_path: Path to centralized log (default: CENTRALIZED_LOG)
            owner_pid: PID of the owning Claude Code process. When given, the listener
                reaps ITSELF once that process dies — the only cleanup path that
                survives an abrupt death (tmux kill-server, crash, SIGKILL), because
                the SessionEnd hook cannot run in those cases. None disables the
                watchdog and is logged loudly at startup.
        """
        ws_session_name = f"cc-listener-{session_id_hash}"

        super().__init__(
            email             = email,
            password          = password,
            session_id        = ws_session_name,
            on_event          = self._handle_event,
            subscribed_events = SUBSCRIBED_EVENTS,
            host              = host,
            port              = port,
            debug             = debug,
            verbose           = verbose,
        )

        self.session_id_hash       = session_id_hash
        self.accepted_ids          = set( accepted_ids ) if accepted_ids else { session_id_hash }
        self.buffer_path           = Path( buffer_path ) if buffer_path else self._default_buffer_path()
        self._tmux_session_arg     = tmux_session  # CLI override
        self._tmux_session         = None          # Cached resolved value
        self.log_file_path         = Path( log_file_path ) if log_file_path else None
        self._log_file             = None
        self._centralized_log_path = Path( centralized_log_path ) if centralized_log_path else CENTRALIZED_LOG
        self._centralized_log      = None
        self._message_count        = 0

        # Pin the owner's identity NOW, while it is certainly alive. Comparing this
        # start-time on every poll is what makes the watchdog safe against PID reuse.
        self.owner_pid             = owner_pid
        self._owner_starttime      = read_proc_starttime( owner_pid ) if owner_pid else None

        self.memory_trace          = memory_trace

    def _default_buffer_path( self ) -> Path:
        """
        Compute default buffer file path.

        Ensures:
            - Returns path in ~/.claude/sessions/
            - Path includes session hash for uniqueness

        Returns:
            Path: Buffer file path
        """
        return SESSION_DIR / f"cc-buffer-{self.session_id_hash}.jsonl"

    def _setup_logging( self ):
        """
        Set up log file output and centralized log.

        Ensures:
            - Opens per-session log file in append mode (if log_file_path specified)
            - Opens centralized log in append mode (line-buffered for tail -f)
        """
        if self.log_file_path:
            self.log_file_path.parent.mkdir( parents=True, exist_ok=True )
            self._log_file = open( self.log_file_path, "a", buffering=1 )

        try:
            self._centralized_log_path.parent.mkdir( parents=True, exist_ok=True )
            self._centralized_log = open( self._centralized_log_path, "a", buffering=1 )
        except Exception:
            self._centralized_log = None

    def _timestamp( self ):
        """Return human-readable timestamp for centralized log lines."""
        now = datetime.now( timezone.utc )
        return now.strftime( "%Y.%m.%d @ %H:%M %S" ) + f",{now.microsecond // 1000:03d}ms"

    def _write_central( self, line ):
        """
        Write a single line to centralized log (best-effort).

        Args:
            line: Pre-formatted log line (no trailing newline)
        """
        if self._centralized_log:
            try:
                self._centralized_log.write( line + "\n" )
                self._centralized_log.flush()
            except Exception:
                pass

    def _log( self, message ):
        """
        Print a message, write to per-session log, and write to centralized log.

        Args:
            message: Message string to output
        """
        print( message, flush=True )
        if self._log_file:
            try:
                self._log_file.write( message + "\n" )
                self._log_file.flush()
            except Exception:
                pass

        self._write_central( f"{self._timestamp()} [{self.session_id_hash}] {message}" )

    def _log_central( self, message ):
        """
        Write a lifecycle marker to centralized log only (not per-session log).

        Args:
            message: Marker string (e.g., "=== LISTENER STARTED ===")
        """
        self._write_central( f"{self._timestamp()} [{self.session_id_hash}] {message}" )

    async def _handle_event( self, event_type, event_data ):
        """
        Handle a WebSocket event by filtering and buffering.

        Requires:
            - event_type is a string
            - event_data is a dict

        Ensures:
            - Only processes notification_queue_update events
            - Only buffers user_initiated_message notifications
            - Only buffers notifications whose job_id matches session_id_hash
            - Writes JSONL line to buffer file on match
            - Never raises exceptions (logging failure is non-fatal)

        Args:
            event_type: WebSocket event type string
            event_data: Full event payload dict
        """
        if event_type != "notification_queue_update":
            if self.verbose:
                self._log( f"{self.LOG_PREFIX} Ignoring event type: {event_type}" )
            return

        notification = event_data.get( "notification", {} )
        notif_type   = notification.get( "type" ) or notification.get( "notification_type", "" )
        job_id       = notification.get( "job_id", "" )

        if self.debug:
            self._log(
                f"{self.LOG_PREFIX} Notification: type={notif_type}, "
                f"job_id={job_id}, target={self.session_id_hash}"
            )

        # Action notifications: title-based routing (e.g., "action:set_session_topic")
        title = notification.get( "title", "" )
        if title.startswith( "action:" ) and job_id in self.accepted_ids:
            action = title[ len( "action:" ): ]
            self._handle_action( action, notification )
            return

        # Filter: must be user_initiated_message AND match our session
        if notif_type != "user_initiated_message":
            if self.debug:
                self._log( f"{self.LOG_PREFIX} Skipping: type={notif_type} (not user_initiated_message)" )
            return

        if job_id not in self.accepted_ids:
            if self.debug:
                self._log( f"{self.LOG_PREFIX} Skipping: job_id={job_id} not in {self.accepted_ids}" )
            return

        # Direction-aware routing (notification-native AI↔AI messaging, Phase 3 §6a of
        # src/rnd/v0.1.8/2026.06.13-cosa-voice-token-reduction/02-notification-native-aixai-design.md).
        # A peer DM (direction=ai_to_ai) must NOT receive the human-voice envelope or the
        # speakerphone rider — it routes to _handle_peer_dm, which injects a peer-DM envelope
        # plus a dm_send reply affordance verbatim (wrap=False). Everything else — human voice
        # (human_to_ai) or a legacy notification with no direction — keeps the existing path.
        if notification.get( "direction" ) == "ai_to_ai":
            self._deliver_peer_dm( notification )
            return

        # Match — inject directly into tmux prompt (skip buffer for idle injection)
        message_text = notification.get( "message", "" ).strip()
        if message_text:
            self._inject_via_tmux( message_text )
        self._send_gist_response( notification )

    def _deliver_peer_dm( self, notification ):
        """
        Idle-aware delivery for an inbound notification-native AI↔AI DM
        (direction=ai_to_ai), per §6 of
        src/rnd/v0.1.8/2026.06.13-cosa-voice-token-reduction/02-notification-native-aixai-design.md.

        Routes by the recipient session's liveness:
        - ACTIVE → _buffer_message: write to the voice buffer, drained by the
          next injecting hook (PreToolUse/PostToolUse/Stop) at a clean tool
          boundary and framed by format_voice_context's ai_to_ai branch. Clean,
          non-invasive — does NOT type into a live prompt mid-turn.
        - IDLE → _handle_peer_dm: inject via tmux to WAKE the idle pane (the only
          path that reaches a pane sitting at an idle prompt).

        Liveness is read from the existing heartbeat_events outcome store; on any
        read error we fall back to the tmux-wake path (degrades to the always-
        deliver behavior rather than risk a buffered DM sitting unseen).

        Ensures:
            - Active recipient → buffered; idle (or unknown-state) recipient → tmux
            - Never raises (both downstream paths are self-isolating)
        """
        if self._recipient_is_injectable():
            self._handle_peer_dm( notification )
        else:
            self._buffer_message( notification )

    def _recipient_is_injectable( self ):
        """
        Is this CC session safe to tmux-inject / wake an arriving peer DM into
        right now — i.e. is it PARKED AT AN IDLE PROMPT (not busy mid-turn, not
        sitting at a permission/AskUserQuestion dialog)?

        SOURCE OF TRUTH (bug d1bb1456, Mr. Radio ratified 2026-07-02): a bounded,
        fail-open tmux PANE-IDLE PROBE (`_pane_is_idle_at_prompt`) that OBSERVES
        the recipient pane's real state. This REPLACES the prior heartbeat-outcome
        heuristic, which read `last_emitted_outcome()` and returned False (→ buffer)
        for a parked pane whose last outcome was None (only `idle_prompt` beacons
        emitted, or a fresh session) or "poked". A parked pane so misclassified had
        its DM buffered for drain-at-next-tool-boundary — but a parked pane has NO
        next tool boundary and no UserPromptSubmit, so the DM never drained (the
        residual of baf5ea6d; see src/rnd/v0.1.9/2026.07.02-parked-worker-dm-wake-
        gap-triage.md). The probe reads the pane's ACTUAL state instead of inferring
        from a possibly-stale outcome log.

        Ensures:
            - Returns True iff the pane is OBSERVABLY parked at a normal idle prompt
              (delegates to `_pane_is_idle_at_prompt`).
            - Returns False when the pane is busy mid-turn, sitting at a dialog, or
              the probe cannot positively confirm idle (fail-open → buffer; the
              buffered DM still surfaces via the store reconcile on the next
              UserPromptSubmit, whereas a mis-injected running turn is unrecoverable).
            - Never raises.
        """
        return self._pane_is_idle_at_prompt()

    def _pane_is_idle_at_prompt( self ):
        """
        The pane-idle probe (bug d1bb1456). Captures the recipient tmux pane TWICE,
        ~PANE_PROBE_RECHECK_SECONDS apart, and returns True iff BOTH captures
        classify as a normal idle prompt (`_classify_capture_idle`).

        The double capture is the transition-race guard (Mr. Radio hardening #1): a
        turn that is STARTING may not have painted "esc to interrupt" yet, so a
        single capture could momentarily read idle; requiring two consistent reads
        closes that window.

        Ensures:
            - Returns False when the tmux session can't be resolved (can't probe →
              fail-open to buffer).
            - Returns True iff the first AND the (short-)later capture both classify
              idle; False otherwise. Never raises (capture is total).
        """
        tmux_session = self._resolve_tmux_session()
        if not tmux_session:
            # No pane to probe → can't confirm idle → fail-open to the buffer path.
            return False
        if not self._classify_capture_idle( self._capture_pane( tmux_session ) ):
            return False
        time.sleep( PANE_PROBE_RECHECK_SECONDS )
        return self._classify_capture_idle( self._capture_pane( tmux_session ) )

    def _capture_pane( self, tmux_session ):
        """
        Bounded, total `tmux capture-pane` of the recipient pane.

        Ensures:
            - Returns the captured pane text on a clean (rc==0), non-empty capture.
            - Returns None on any tmux error (timeout / missing binary / OSError),
              a non-zero return code, or an empty capture — the caller treats None
              as NOT-idle (fail-open → buffer). Never raises.
        """
        try:
            result = subprocess.run(
                [ "tmux", "capture-pane", "-p", "-t", tmux_session ],
                capture_output=True, text=True, timeout=2
            )
        except ( subprocess.TimeoutExpired, FileNotFoundError, OSError ) as e:
            self._log( f"{self.LOG_PREFIX} pane-idle probe capture failed (fail-open→buffer): {e}" )
            return None
        if result.returncode != 0:
            self._log( f"{self.LOG_PREFIX} pane-idle probe rc={result.returncode} (fail-open→buffer)" )
            return None
        captured = result.stdout or ""
        return captured if captured.strip() else None

    @staticmethod
    def _classify_capture_idle( captured ):
        """
        PURE classifier: does a captured pane show a NORMAL IDLE PROMPT — safe to
        tmux-inject a peer DM into?

        Fail-closed-toward-buffer (Mr. Radio hardening #1 & #2): idle requires a
        POSITIVE signal, never mere busy-sentinel absence. All must hold:
          - `captured` is a non-empty string (None ⇒ probe failed ⇒ NOT idle);
          - no BUSY_STATUS_SENTINELS  (a running turn ⇒ never inject);
          - no DIALOG_SENTINELS       (permission/AskUserQuestion modal ⇒ typing
                                        into it could select an option ⇒ never inject);
          - the IDLE_PROMPT_DIVIDER is present (the normal input-box chrome — the
                                        positive idle signal; an unknown/blank state
                                        lacks it ⇒ NOT idle ⇒ buffer).

        Ensures:
            - Returns True iff captured is non-empty AND busy-free AND dialog-free
              AND carries the idle-prompt divider; False otherwise. Never raises.
        """
        if not captured:
            return False
        if any( sentinel in captured for sentinel in BUSY_STATUS_SENTINELS ):
            return False
        if any( sentinel in captured for sentinel in DIALOG_SENTINELS ):
            return False
        return IDLE_PROMPT_DIVIDER in captured

    def _handle_peer_dm( self, notification ):
        """
        Inject a peer-DM envelope into an IDLE pane via tmux to wake it (the idle
        branch of _deliver_peer_dm).

        Per §6a of
        src/rnd/v0.1.8/2026.06.13-cosa-voice-token-reduction/02-notification-native-aixai-design.md:
        - A peer DM is NOT human voice. It must NOT receive the speakerphone_wrap
          voice rider ("the user spoke… call notify() to speak your reply aloud…
          TTS brevity… chorus") — that would hand an AI peer the human-voice
          contract, framed as if Rick spoke. Peers reply via dm_send, never TTS.
        - The body rides the push INLINE (notification["message"]) — no
          commons_read round-trip (the ~18x token win over the retired commons
          claim-check DM path).
        - The envelope (sender persona + icon + message_id + thread_id + dm_send
          reply affordance) is built by the SHARED build_peer_dm_reminder helper,
          so the idle (tmux) and active (buffer-drain) paths frame identically.
        - Injects via _inject_via_tmux( text, wrap=False ): the block is complete
          and must reach the model verbatim, with NO voice wrapping.

        Requires:
            - notification is a dict carrying at least "message"; sender_persona,
              sender_icon, id, and thread_id ride the WS dict via
              NotificationItem.to_dict().

        Ensures:
            - Injects a peer-framed <system-reminder> into the tmux pane
            - NEVER applies the speakerphone voice rider (wrap=False)
            - Skips (logs) when the inline body is empty
            - Never raises (T7 listener-injection isolation — failure logs + skips)
        """
        from lupin_cli.claude_code.hooks.lib.hook_common import build_peer_dm_reminder

        body = ( notification.get( "message" ) or "" ).strip()
        if not body:
            self._log( f"{self.LOG_PREFIX} peer DM missing body; skipping" )
            return

        wrapped = build_peer_dm_reminder(
            body,
            persona   = notification.get( "sender_persona" ),
            icon      = notification.get( "sender_icon" ),
            msg_id    = notification.get( "id" ),
            thread_id = notification.get( "thread_id" ),
        )
        try:
            self._inject_via_tmux( wrapped, wrap=False )
        except Exception as e:
            # T7 listener-injection isolation: failure logs + skips, doesn't crash listener
            self._log( f"{self.LOG_PREFIX} peer DM inject failed: {e}" )

    def _handle_action( self, action, notification ):
        """
        Handle action notifications routed by title prefix.

        Requires:
            - action is a string (the part after "action:" in title)
            - notification is a dict with at least a "message" key

        Ensures:
            - Routes to appropriate handler based on action name
            - Logs unknown actions without raising
        """
        if action == "set_session_topic":
            topic = notification.get( "message", "" ).strip()
            if topic:
                self._update_session_topic( topic )
        elif action == "disable_speakerphone":
            self._inject_exit_conversation_reminder()
        elif action == "broadcast_received":
            self._handle_broadcast_received( notification )
        else:
            self._log( f"{self.LOG_PREFIX} Unknown action: {action}" )

    def _handle_broadcast_received( self, notification ):
        """
        Handle an `action:broadcast_received` notification from the user-broadcast
        endpoint (Phase 2 step 6 — see
        src/rnd/v0.1.7/2026.05.09-inter-session-commons/03-phase2-user-broadcast-design.md AC6).

        Delegates to `lupin_mcp.broadcast_handler.handle_broadcast` which is the
        keystone orchestrator — pure-logic + 100% covered + identical contract
        whether invoked from this listener or from a future MCP tool path.

        The listener provides:
        - `inject_fn`: lambda wrapping `_inject_via_tmux(text, wrap=False)`
        - `store`: a fresh `CommonsStore` rooted at `<LUPIN_ROOT>/io/commons`
        - `local_persona`: pulled from `get_session_metadata().voice_persona`
        - `sender_session_id`: the local session id from bridge metadata
        - `persona_roster`: live persona names from the bridge scan, so the
          handler's directive discriminator only treats `@token:` runs as
          persona directives when the token resembles a real persona
        """
        import os
        try:
            from lupin_mcp.broadcast_handler import handle_broadcast
            from lupin_mcp.commons_store import CommonsStore
            from lupin_cli.claude_code.hooks.lib.session_bridge import (
                find_active_voice_persona_sessions,
                get_session_metadata,
            )
        except ImportError as e:
            self._log( f"{self.LOG_PREFIX} broadcast_handler import failed: {e}" )
            return

        meta = get_session_metadata()
        local_persona     = meta.get( "voice_persona" )
        sender_session_id = meta.get( "stable_session_id" ) or meta.get( "session_id" ) or "<unknown>"

        commons_root = os.environ.get( "LUPIN_ROOT" )
        if not commons_root:
            self._log( f"{self.LOG_PREFIX} LUPIN_ROOT unset — cannot post broadcast ack" )
            return

        try:
            store = CommonsStore( commons_root )
        except Exception as e:
            self._log( f"{self.LOG_PREFIX} CommonsStore init failed at {commons_root}: {e}" )
            return

        # Roster for directive discrimination: name + display_name of every live
        # persona session. An empty scan carries no roster signal (at minimum the
        # local session exists), so pass None — roster-blind legacy parse — rather
        # than an empty list, which would flag EVERY directive run as prose.
        persona_roster = [ ]
        for _bridge_path, _session_id, persona in find_active_voice_persona_sessions():
            for name_key in ( "name", "display_name" ):
                name_value = persona.get( name_key )
                if isinstance( name_value, str ) and name_value and name_value not in persona_roster:
                    persona_roster.append( name_value )

        handle_broadcast(
            notification      = notification,
            local_persona     = local_persona,
            inject_fn         = lambda text: self._inject_via_tmux( text, wrap=False ),
            store             = store,
            sender_session_id = sender_session_id,
            persona_roster    = persona_roster or None,
        )

    def _inject_exit_conversation_reminder( self ):
        """
        Inject the deactivation system-reminder into the CC session's tmux
        prompt. Triggered by an `action:disable_speakerphone` push from
        the speakerphone router when this session has been displaced by
        another session entering speakerphone mode (solo) or when this
        session toggled off itself (solo or chorus).

        The reminder body is generated by hook_common.speakerphone_exit_reminder
        so the wrapping format stays in lockstep with the entry-side helpers.
        Mode is read here so the body chooses the right framing (solo
        includes "displaced or toggled off"; chorus omits the displaced
        framing since chorus has no displacement).

        Bypasses _inject_via_tmux's bridge-gated wrap path — the reminder is
        already a complete <system-reminder> block and must be injected
        verbatim regardless of bridge state (which has, by this point,
        already flipped to speakerphone_on=false).

        Ensures:
            - Tmux pane receives the mode-appropriate reminder followed by Enter
            - Never raises (logging-only on injection failure)
        """
        try:
            from lupin_cli.claude_code.hooks.lib.hook_common import speakerphone_exit_reminder
            import cosa.utils.util as cu
            reminder = speakerphone_exit_reminder( cu.get_tts_interaction_mode() )
        except Exception as e:
            self._log( f"{self.LOG_PREFIX} speakerphone_exit_reminder import/build failed: {e}" )
            return
        self._inject_via_tmux( reminder, wrap=False )

    def _update_session_topic( self, topic ):
        """
        Write session_topic to session bridge file.

        Requires:
            - topic is a non-empty string

        Ensures:
            - Bridge file is updated with session_topic key
            - Logs success or failure without raising
        """
        try:
            from lupin_cli.claude_code.hooks.lib.session_bridge import get_session_metadata
            import json

            meta        = get_session_metadata()
            bridge_path = meta.get( "_bridge_path" )
            if not bridge_path:
                self._log( f"{self.LOG_PREFIX} No bridge path found, cannot set session topic" )
                return

            with open( bridge_path ) as f:
                data = json.load( f )
            data[ "session_topic" ] = topic
            with open( bridge_path, "w" ) as f:
                json.dump( data, f, indent=2 )
            self._log( f"{self.LOG_PREFIX} Session topic set: {topic}" )
        except Exception as e:
            self._log( f"{self.LOG_PREFIX} Failed to set session topic: {e}" )

    def _resolve_tmux_session( self ):
        """
        Resolve the tmux session name for this CC session.

        Priority: CLI arg override > cached value > session bridge file lookup.
        Caches the result after first successful resolution.

        Ensures:
            - Returns tmux session name string or None
            - Caches result for subsequent calls
            - Never raises exceptions

        Returns:
            str or None: tmux session name
        """
        if self._tmux_session is not None:
            return self._tmux_session

        if self._tmux_session_arg:
            self._tmux_session = self._tmux_session_arg
            return self._tmux_session

        try:
            from lupin_cli.claude_code.hooks.lib.session_bridge import find_session_by_id
            data = find_session_by_id( self.session_id_hash )
            if data:
                tmux = data.get( "tmux_session" )
                if tmux:
                    self._tmux_session = tmux
                    return self._tmux_session
        except Exception as e:
            self._log( f"{self.LOG_PREFIX} tmux session lookup failed: {e}" )

        return None

    def _inject_via_tmux( self, message_text, wrap=True ):
        """
        Type the voice message into the CC session's tmux pane, then press Enter.

        Uses tmux send-keys -l (literal) to avoid key interpretation of special
        characters. Sends Enter separately after a brief delay — tmux cannot
        reliably combine literal text + Enter in a single call.

        Requires:
            - message_text is a non-empty string
            - tmux session is resolvable
            - wrap is a bool — True (default) applies speakerphone_wrap, False
              injects the text verbatim. Set False when the caller has
              already produced a complete <system-reminder> block (e.g.
              the disable_speakerphone action handler) that must reach the
              model regardless of bridge state.

        Ensures:
            - Types message text into the CC prompt
            - Presses Enter after 250ms delay
            - CC receives a non-empty prompt and processes it
            - The text+Enter pair is atomic against any other lock-honoring
              injector on the same tmux session (F4 injection mutex — two
              racing injectors previously interleaved keystrokes into
              "text A, text B, Enter, Enter", silently corrupting delivery)
            - Never raises exceptions (injection failure is non-fatal)
        """
        tmux_session = self._resolve_tmux_session()
        if not tmux_session:
            self._log( f"{self.LOG_PREFIX} No tmux session found -- skipping injection" )
            return

        # Phase 5b — speakerphone rider: wrap voice input with the per-turn
        # rider. Content varies by (tts_interaction_mode, speakerphone_on);
        # rider fires on every turn (no on-state gating).
        # See: src/rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/14-phase5-hook-rider-design.md
        if wrap:
            try:
                from lupin_cli.claude_code.hooks.lib.hook_common import speakerphone_wrap
                message_text = speakerphone_wrap(
                    message_text,
                    source     = "voice",
                    session_id = self.session_id_hash
                )
            except Exception as e:
                # Wrap failure is non-fatal — fall through with raw text
                self._log( f"{self.LOG_PREFIX} speakerphone_wrap failed (passing through unwrapped): {e}" )

        # F4 injection mutex: serialize the 2-step send-keys sequence per tmux
        # session so concurrent injections cannot interleave. Fail-open — a
        # lock failure logs but never blocks injection.
        with tmux_injection_lock( tmux_session ) as lock_held:
            if not lock_held:
                self._log( f"{self.LOG_PREFIX} injection lock unavailable -- injecting unlocked" )

            try:
                # Step 1: Type the message text (literal mode — no key interpretation)
                subprocess.run(
                    [ "tmux", "send-keys", "-t", tmux_session, "-l", message_text ],
                    capture_output=True, timeout=2
                )

                # Step 2: Brief delay — tmux needs separation between text and Enter
                time.sleep( 0.25 )

                # Step 3: Press Enter separately
                subprocess.run(
                    [ "tmux", "send-keys", "-t", tmux_session, "Enter" ],
                    capture_output=True, timeout=2
                )

                self._log( f"{self.LOG_PREFIX} Injected message via tmux '{tmux_session}'" )

            except ( subprocess.TimeoutExpired, FileNotFoundError, OSError ) as e:
                self._log( f"{self.LOG_PREFIX} tmux injection failed: {e}" )

    def _send_gist_response( self, notification ):
        """
        Generate a 3-5 word gist and send it as an immediate auto-response
        notification back to the browser user. Renders in the session card UI.

        Requires:
            - notification dict contains "message" and "sender_id" keys
            - sender_id is a plain email address

        Ensures:
            - Uses sender_id as target email (reply-to sender)
            - Generates gist via Gister with session-title prompt
            - Sends low-priority notification to browser user
            - Falls back to first 5 words if Gister fails
            - Never raises exceptions (auto-response is non-fatal)
        """
        text = notification.get( "message", "" )
        if not text.strip():
            return

        # Target email is the sender_id (plain email, set by sendCCSessionMessage)
        target_email = notification.get( "sender_id", "" )
        if not target_email or "@" not in target_email:
            self._log( f"{self.LOG_PREFIX} No valid sender_id email — skipping gist response" )
            return

        try:
            from cosa.memory.gister import Gister
            gister = Gister( debug=False, verbose=False )
            gist   = gister.get_gist( text )
        except Exception as e:
            self._log( f"{self.LOG_PREFIX} Gister failed: {e}" )
            gist = None

        # Fallback: first 5 words.
        #
        # FAIL-LOUD (2026-07-27): this fallback is INDISTINGUISHABLE from a real gist at
        # the UI — "Received: <5 words>" reads as a short paraphrase, not as a failure —
        # so a broken Gister degrades silently and stays broken. It did: 526 consecutive
        # fallbacks between 2026-07-14 and 2026-07-27 (`LUPIN_CONFIG_MGR_CLI_ARGS` not
        # forwarded across the tmux pane boundary), during which the gist model was never
        # contacted and no vLLM-side error ever appeared to signal the outage. Mark the
        # degraded path explicitly so the next occurrence is greppable on sight.
        if not gist:
            gist = " ".join( text.split()[ :5 ] )
            self._log(
                f"{self.LOG_PREFIX} DEGRADED: gist unavailable — emitting 5-word prefix "
                f"fallback \"{gist}\". This is NOT a model-generated gist; the Gister "
                f"failure logged above is the cause."
            )

        try:
            from lupin_cli.notifications.notification_models import (
                AsyncNotificationRequest, NotificationType, NotificationPriority
            )
            from lupin_cli.notifications.notify_user_async import notify_user_async

            sender_id = build_sender_id_for_cc( session_id=self.session_id_hash ) or f"claude.code@lupin.deepily.ai#{self.session_id_hash}"

            request = AsyncNotificationRequest(
                message           = f"Received: {gist}",
                notification_type = NotificationType.PROGRESS,
                priority          = NotificationPriority.LOW,
                target_user       = target_email,
                sender_id         = sender_id,
                timeout           = NOTIFY_TRANSPORT_TIMEOUT_SECONDS
            )
            notify_user_async( request=request )
            self._log( f"{self.LOG_PREFIX} Gist response sent: \"{gist}\"" )

        except Exception as e:
            self._log( f"{self.LOG_PREFIX} Failed to send gist response: {e}" )

    def _buffer_message( self, notification ):
        """
        Append a notification to the JSONL buffer file.

        Requires:
            - notification is a dict with at least message and job_id keys

        Ensures:
            - Creates parent directory if needed
            - Appends one JSON line to buffer file
            - Flushes immediately for hook availability
            - Increments message counter
            - Never raises (failure is logged but non-fatal)

        Args:
            notification: Notification dict to buffer
        """
        try:
            self.buffer_path.parent.mkdir( parents=True, exist_ok=True )

            entry = {
                "message"       : notification.get( "message", "" ),
                "priority"      : notification.get( "priority", "normal" ),
                "job_id"        : notification.get( "job_id", "" ),
                "sender_id"     : notification.get( "sender_id", "" ),
                "notification_id" : notification.get( "id", "" ),
                "timestamp"     : notification.get( "timestamp", datetime.now( timezone.utc ).isoformat() ),
                "buffered_at"   : datetime.now( timezone.utc ).isoformat(),
                # Direction + DM provenance/threading (notification-native AI↔AI, §6a).
                # format_voice_context branches on `direction`: an ai_to_ai entry is
                # drained into a peer-DM envelope (persona/icon/ids) instead of a
                # "[Voice]:" line. Defaults keep voice entries shaped as before.
                "direction"      : notification.get( "direction", "human_to_ai" ),
                "sender_persona" : notification.get( "sender_persona" ),
                "sender_icon"    : notification.get( "sender_icon" ),
                "reply_to"       : notification.get( "reply_to" ),
                "thread_id"      : notification.get( "thread_id" ),
            }

            with open( self.buffer_path, "a" ) as f:
                f.write( json.dumps( entry ) + "\n" )
                f.flush()

            self._message_count += 1
            self._log(
                f"{self.LOG_PREFIX} Buffered message #{self._message_count}: "
                f'"{entry[ "message" ][:80]}"'
            )

        except Exception as e:
            self._log( f"{self.LOG_PREFIX} ERROR buffering message: {e}" )

    def _stamp_user_id_on_bridge( self ):
        """
        Phase 3 Option 2 — resolve the authenticated user_id and stamp it on
        this session's bridge file so the inter-session-commons broadcast
        surface can same-user-scope active sessions correctly.

        Per `src/rnd/v0.1.7/2026.05.13-broadcast-ui-no-active-sessions-bug.md`:
        - Posts to f"http://{host}:{port}/auth/login" with `email` + `password`
        - Extracts `user.id` from the response (canonical user UUID)
        - Calls `session_bridge.set_user_id(session_id_hash, user_id)` —
          set_user_id accepts the 8-char prefix via find_session_path_by_id
        - Best-effort: any failure (network, auth, parse, missing bridge) is
          debug-logged and swallowed. Option 1's graceful-degradation filter
          in `routers/commons.py::filter_and_project_sessions` covers the gap.

        Fires once at `run()` startup, not on each reconnect cycle.

        Ensures:
            - Never raises publicly. All errors caught + logged.
            - Bridge file is mutated only on full success.
        """
        try:
            import urllib.request
            import urllib.error
            from lupin_cli.claude_code.hooks.lib.session_bridge import set_user_id

            url = f"http://{self.host}:{self.port}/auth/login"
            body = json.dumps( { "email": self.email, "password": self.password } ).encode( "utf-8" )
            req  = urllib.request.Request(
                url,
                data    = body,
                headers = { "Content-Type": "application/json" },
                method  = "POST",
            )
            with urllib.request.urlopen( req, timeout=_SERVER_TRANSPORT_TIMEOUT_SECONDS ) as resp:
                payload = json.loads( resp.read().decode( "utf-8" ) )
            user_id = payload.get( "user", { } ).get( "id" )
            if not user_id:
                self._log( f"{self.LOG_PREFIX} user_id stamp skipped — no user.id in /auth/login response" )
                return
            ok = set_user_id( self.session_id_hash, user_id )
            if ok:
                self._log( f"{self.LOG_PREFIX} user_id stamped on bridge: {user_id}" )
            else:
                self._log( f"{self.LOG_PREFIX} user_id stamp skipped — bridge not found for session {self.session_id_hash}" )
        except ( urllib.error.URLError, json.JSONDecodeError, OSError, KeyError, ValueError ) as e:
            self._log( f"{self.LOG_PREFIX} user_id stamp failed (silent fallback): {e!r}" )
        except Exception as e:
            # Defense-in-depth: never let stamping kill the listener startup
            self._log( f"{self.LOG_PREFIX} user_id stamp unexpected error (silent fallback): {e!r}" )

    def _stamp_owner_user_id_on_bridge( self ):
        """
        Writer-side follow-up to the 2026-05-14 Option C design. Resolves
        the HUMAN OWNER's user_id via /auth/login using owner credentials
        from ~/.lupin/config[owner], then stamps it on the bridge via
        session_bridge.set_owner_user_id.

        Per `src/rnd/v0.1.7/2026.05.17-owner-user-id-stamper-writer-side/01-design.md`.

        Distinct from `_stamp_user_id_on_bridge`: that stamps the listener's
        OWN service-account identity (`claude.code@lupin.deepily.ai`); this
        stamps the HUMAN owner's identity, which is what the broadcast UI's
        same-user filter (`filter_and_project_sessions` in CoSA's
        `routers/commons.py`) actually compares against.

        Best-effort: any failure (creds missing, network, auth, parse,
        missing bridge) is logged and swallowed. CoSA-side graceful-
        degradation filter covers the gap until the stamp succeeds.

        Fires once at run() startup, immediately after _stamp_user_id_on_bridge.

        Ensures:
            - Never raises publicly. All errors caught + logged.
            - Bridge file is mutated only on full success.
        """
        try:
            import urllib.request
            import urllib.error
            from lupin_cli.claude_code.hooks.lib.hook_credentials import get_owner_credentials
            from lupin_cli.claude_code.hooks.lib.session_bridge import set_owner_user_id

            try:
                owner_email, owner_password = get_owner_credentials()
            except ( FileNotFoundError, ValueError ) as e:
                self._log( f"{self.LOG_PREFIX} owner_user_id stamp skipped — no owner credentials: {e}" )
                return

            url  = f"http://{self.host}:{self.port}/auth/login"
            body = json.dumps( { "email": owner_email, "password": owner_password } ).encode( "utf-8" )
            req  = urllib.request.Request(
                url,
                data    = body,
                headers = { "Content-Type": "application/json" },
                method  = "POST",
            )
            with urllib.request.urlopen( req, timeout=_SERVER_TRANSPORT_TIMEOUT_SECONDS ) as resp:
                payload = json.loads( resp.read().decode( "utf-8" ) )
            owner_user_id = payload.get( "user", { } ).get( "id" )
            if not owner_user_id:
                self._log( f"{self.LOG_PREFIX} owner_user_id stamp skipped — no user.id in /auth/login response" )
                return
            ok = set_owner_user_id( self.session_id_hash, owner_user_id )
            if ok:
                self._log( f"{self.LOG_PREFIX} owner_user_id stamped on bridge: {owner_user_id}" )
            else:
                self._log( f"{self.LOG_PREFIX} owner_user_id stamp skipped — bridge not found for session {self.session_id_hash}" )
        except ( urllib.error.URLError, json.JSONDecodeError, OSError, KeyError, ValueError ) as e:
            self._log( f"{self.LOG_PREFIX} owner_user_id stamp failed (silent fallback): {e!r}" )
        except Exception as e:
            # Defense-in-depth: never let stamping kill the listener startup
            self._log( f"{self.LOG_PREFIX} owner_user_id stamp unexpected error (silent fallback): {e!r}" )

    def _print_stats( self ):
        """Print session statistics on shutdown."""
        self._log( "" )
        self._log( f"  {self.LOG_PREFIX} Session Statistics" )
        self._log( f"  {'─' * 40}" )
        self._log( f"  Session hash  : {self.session_id_hash}" )
        self._log( f"  Buffer path   : {self.buffer_path}" )
        self._log( f"  Messages buffered : {self._message_count}" )
        buffer_exists = self.buffer_path.exists()
        if buffer_exists:
            lines = sum( 1 for _ in open( self.buffer_path ) )
            self._log( f"  Buffer lines  : {lines}" )
        else:
            self._log( f"  Buffer lines  : 0 (file does not exist)" )
        self._log( f"  {'─' * 40}" )
        self._log( "" )

    async def _watch_owner( self ):
        """
        Reap this listener once its owning Claude Code process dies.

        This is the ONLY cleanup path that survives an abrupt session death. The
        listener is setsid'd (start_new_session=True in register_session.py), so the
        SIGHUP tmux sends its panes never reaches it, and session_end.py — the only
        other reaper — runs only on a GRACEFUL exit. A tmux kill-server, a crash, or a
        SIGKILL therefore left the listener alive forever, reconnecting on a loop and
        still holding its WebSocket to the notifications UI.

        Requires:
            - self.owner_pid is a positive integer (no-op when None)

        Ensures:
            - Polls owner liveness every OWNER_WATCHDOG_INTERVAL_SECONDS
            - Calls self.stop() exactly once when the owner is gone, which unwinds the
              restart loop in run() the same way SIGTERM does
            - Returns immediately (watchdog disabled) when no owner_pid was supplied
        """
        if not self.owner_pid:
            self._log(
                f"{self.LOG_PREFIX} WARNING: no --owner-pid given; owner watchdog is "
                f"DISABLED. This listener will NOT self-reap if its session dies abruptly."
            )
            return

        self._log(
            f"{self.LOG_PREFIX} Owner watchdog armed: pid={self.owner_pid} "
            f"starttime={self._owner_starttime} interval={OWNER_WATCHDOG_INTERVAL_SECONDS}s"
        )

        while self._running:
            await asyncio.sleep( OWNER_WATCHDOG_INTERVAL_SECONDS )

            if not self._running:
                break

            if not owner_is_alive( self.owner_pid, self._owner_starttime ):
                self._log(
                    f"{self.LOG_PREFIX} Owner (pid {self.owner_pid}) is GONE — "
                    f"self-reaping to avoid stranding a listener on the notifications UI."
                )
                self._log_central(
                    f"=== LISTENER SELF-REAPED (owner pid {self.owner_pid} died) ==="
                )
                await self.stop()
                return

    async def _sample_memory( self ):
        """
        Opt-in RSS + tracemalloc sampler to catch the next listener memory leak.

        Off unless self.memory_trace is set (--memory-trace / LUPIN_CC_LISTENER_MEMTRACE).
        When on: starts tracemalloc, logs RSS every MEMORY_SAMPLE_INTERVAL_SECONDS, and
        when RSS has grown by MEMORY_GROWTH_DUMP_THRESHOLD_MB since the last dump, logs a
        tracemalloc top-N by allocation size — the allocation traceback the 2026-07-14
        post-mortem lacked because the leaking processes were reaped before profiling.

        Requires:
            - safe to call always; returns immediately when memory_trace is False

        Ensures:
            - Never raises into the run loop; tracemalloc is stopped on exit
            - Emits a growth dump at most once per threshold crossing
        """
        if not self.memory_trace:
            return

        tracemalloc.start( 25 )
        baseline = read_self_rss_mb()
        last_dump_rss = baseline or 0.0
        self._log(
            f"{self.LOG_PREFIX} Memory sampler armed: baseline RSS={baseline:.1f}MB "
            f"interval={MEMORY_SAMPLE_INTERVAL_SECONDS}s dump_threshold={MEMORY_GROWTH_DUMP_THRESHOLD_MB}MB"
        )

        try:
            while self._running:
                await asyncio.sleep( MEMORY_SAMPLE_INTERVAL_SECONDS )
                if not self._running:
                    break

                rss = read_self_rss_mb()
                if rss is None:
                    continue
                self._log( f"{self.LOG_PREFIX} [mem] RSS={rss:.1f}MB (baseline {baseline:.1f}MB)" )

                if rss - last_dump_rss >= MEMORY_GROWTH_DUMP_THRESHOLD_MB:
                    last_dump_rss = rss
                    self._dump_top_allocations( rss )
        finally:
            tracemalloc.stop()

    def _dump_top_allocations( self, rss ):
        """Log the tracemalloc top-N allocations — the traceback that names the leak."""
        snapshot = tracemalloc.take_snapshot()
        stats    = snapshot.statistics( "lineno" )
        self._log(
            f"{self.LOG_PREFIX} [mem] GROWTH DUMP at RSS={rss:.1f}MB — top "
            f"{MEMORY_TOP_ALLOCATIONS} allocations:"
        )
        for stat in stats[ :MEMORY_TOP_ALLOCATIONS ]:
            self._log( f"{self.LOG_PREFIX} [mem]   {stat}" )

    async def run( self ):
        """
        Start the listener with logging setup, shutdown stats, and infinite restart.

        Wraps super().run() in an outer restart loop: if the base listener
        exhausts its RECONNECT_MAX_ATTEMPTS (10), this method waits 60 seconds
        and restarts the connection cycle. This prevents voice input from being
        silently dropped when the Lupin server is temporarily down.

        The restart loop only exits on explicit shutdown (SIGTERM/SIGINT via
        self._running = False). It does NOT modify RECONNECT_MAX_ATTEMPTS
        (other proxy agents use it).

        Overrides base to add log file handling, statistics, and restart resilience.
        """
        self._setup_logging()

        self._log( f"{self.LOG_PREFIX} Starting CC Notification Listener" )
        self._log( f"{self.LOG_PREFIX} Session hash : {self.session_id_hash}" )
        self._log( f"{self.LOG_PREFIX} Buffer path  : {self.buffer_path}" )
        self._log( f"{self.LOG_PREFIX} Debug        : {self.debug}" )
        self._log( f"{self.LOG_PREFIX} Verbose      : {self.verbose}" )
        self._log_central( "=== LISTENER STARTED ===" )

        # Phase 3 Option 2 — stamp user_id on the bridge so inter-session-commons
        # active-sessions endpoint can same-user-scope correctly. Best-effort;
        # silent fallback on failure since Option 1's graceful filter covers
        # the gap. Fires once at startup, not on every reconnect cycle.
        # Per src/rnd/v0.1.7/2026.05.13-broadcast-ui-no-active-sessions-bug.md.
        self._stamp_user_id_on_bridge()

        # Writer-side follow-up — stamp the HUMAN OWNER's user_id on the
        # bridge. The broadcast UI's filter compares against the human
        # owner, not the listener's service account. Best-effort with
        # silent fallback; CoSA-side graceful-degradation covers the gap.
        # Per src/rnd/v0.1.7/2026.05.17-owner-user-id-stamper-writer-side/01-design.md
        self._stamp_owner_user_id_on_bridge()

        restart_cycle    = 0
        restart_cooldown = 60  # seconds
        self._running    = True

        # Arm the owner watchdog alongside the restart loop. It runs for the whole
        # life of the listener and is the thing that ends it when the session dies
        # without a graceful SessionEnd.
        watchdog = asyncio.ensure_future( self._watch_owner() )
        # Opt-in memory sampler (no-op unless --memory-trace). Same lifetime as the loop.
        mem_sampler = asyncio.ensure_future( self._sample_memory() )

        try:
            while self._running:
                restart_cycle += 1
                if restart_cycle > 1:
                    self._log(
                        f"{self.LOG_PREFIX} Restarting after reconnect exhaustion "
                        f"(cycle {restart_cycle})"
                    )

                # Reset the attempt counter so base listener gets a fresh set
                self._attempt  = 0
                self._connected = False

                await super().run()

                # If we're still running, super().run() returned because it
                # exhausted RECONNECT_MAX_ATTEMPTS — wait and retry
                if self._running:
                    self._log(
                        f"{self.LOG_PREFIX} Reconnects exhausted. "
                        f"Cooling down for {restart_cooldown}s before restart..."
                    )
                    await asyncio.sleep( restart_cooldown )

        finally:
            watchdog.cancel()
            mem_sampler.cancel()
            self._log_central( "=== LISTENER STOPPED ===" )
            self._print_stats()
            if self._centralized_log:
                self._centralized_log.close()
            if self._log_file:
                self._log_file.close()


# ── CLI Entry Point ───────────────────────────────────────────────────────────

def parse_args():
    """
    Parse command-line arguments for the CC Notification Listener.

    Ensures:
        - Returns parsed args with session_id, buffer_path, host, port,
          email, password, debug, verbose, log_file

    Returns:
        argparse.Namespace: Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description = "CC Notification Listener — buffers voice input for Claude Code sessions"
    )

    parser.add_argument(
        "--session-id",
        required = True,
        help     = "8-char CC session hash for filtering (e.g., 'abc12345')"
    )
    parser.add_argument(
        "--accepted-ids",
        default = None,
        help    = "Comma-separated 8-char hashes to accept (default: session-id only)"
    )
    parser.add_argument(
        "--buffer-path",
        default = None,
        help    = "Path to JSONL buffer file (default: ~/.claude/sessions/cc-buffer-{hash}.jsonl)"
    )
    parser.add_argument(
        "--tmux-session",
        default = None,
        help    = "Explicit tmux session name for Enter trigger (default: auto-resolve from session bridge)"
    )
    parser.add_argument(
        "--owner-pid",
        type    = int,
        default = None,
        help    = "PID of the owning Claude Code process. The listener self-reaps when it dies "
                  "(survives tmux kill-server / crash / SIGKILL, where SessionEnd cannot run)."
    )
    parser.add_argument(
        "--memory-trace",
        action  = "store_true",
        help    = "Arm the opt-in RSS + tracemalloc sampler (catches the listener memory leak "
                  "with an allocation traceback). Off by default; adds tracemalloc overhead."
    )
    parser.add_argument(
        "--host",
        default = DEFAULT_SERVER_HOST,
        help    = f"Server hostname (default: {DEFAULT_SERVER_HOST})"
    )
    parser.add_argument(
        "--port",
        type    = int,
        default = DEFAULT_SERVER_PORT,
        help    = f"Server port (default: {DEFAULT_SERVER_PORT})"
    )
    parser.add_argument(
        "--email",
        default = None,
        help    = "Login email (overrides INI file)"
    )
    parser.add_argument(
        "--password",
        default = None,
        help    = "Login password (overrides INI file)"
    )
    parser.add_argument(
        "--debug",
        action  = "store_true",
        help    = "Enable debug output"
    )
    parser.add_argument(
        "--verbose",
        action  = "store_true",
        help    = "Enable verbose output (implies debug)"
    )
    parser.add_argument(
        "--log-file",
        default = None,
        help    = "Path to log file (default: stdout only)"
    )
    parser.add_argument(
        "--centralized-log",
        default = None,
        help    = f"Path to centralized log file (default: {CENTRALIZED_LOG})"
    )

    return parser.parse_args()


def _resolve_credentials( args ):
    """
    Resolve credentials from CLI args or INI file.

    Requires:
        - Either CLI args provide email+password, or INI file has valid section

    Ensures:
        - Returns ( email, password ) tuple
        - CLI args take priority over INI file

    Args:
        args: Parsed argparse.Namespace

    Returns:
        Tuple[str, str]: ( email, password )
    """
    if args.email and args.password:
        return args.email, args.password

    try:
        from lupin_cli.claude_code.hooks.lib.hook_credentials import get_hook_credentials
        return get_hook_credentials()
    except ( FileNotFoundError, ValueError ) as e:
        print( f"[CC-Listener] Credential resolution failed: {e}" )
        sys.exit( 1 )


async def main():
    """
    Main async entry point for the CC Notification Listener.

    Ensures:
        - Resolves credentials
        - Creates and runs the listener
        - Handles SIGTERM for graceful shutdown
    """
    args = parse_args()

    if args.verbose:
        args.debug = True

    email, password = _resolve_credentials( args )

    # Parse accepted IDs from comma-separated string
    accepted_ids = None
    if args.accepted_ids:
        accepted_ids = set( h.strip() for h in args.accepted_ids.split( "," ) if h.strip() )

    listener = CCNotificationListener(
        email                = email,
        password             = password,
        session_id_hash      = args.session_id,
        buffer_path          = args.buffer_path,
        tmux_session         = args.tmux_session,
        accepted_ids         = accepted_ids,
        host                 = args.host,
        port                 = args.port,
        debug                = args.debug,
        verbose              = args.verbose,
        log_file_path        = args.log_file,
        centralized_log_path = args.centralized_log,
        owner_pid            = args.owner_pid,
        memory_trace         = args.memory_trace,
    )

    # Graceful shutdown on SIGTERM
    loop = asyncio.get_event_loop()

    def _handle_signal():
        print( f"\n{listener.LOG_PREFIX} Received shutdown signal" )
        asyncio.ensure_future( listener.stop() )

    for sig in ( signal.SIGTERM, signal.SIGINT ):
        loop.add_signal_handler( sig, _handle_signal )

    await listener.run()


if __name__ == "__main__":
    try:
        asyncio.run( main() )
    except KeyboardInterrupt:
        print( "\n[CC-Listener] Bye." )
