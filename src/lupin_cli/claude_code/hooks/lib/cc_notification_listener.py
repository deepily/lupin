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
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from cosa.agents.utils.proxy_agents.base_listener import BaseWebSocketListener
from cosa.agents.utils.proxy_agents.base_config import (
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
)
from lupin_cli.claude_code.hooks.lib.session_bridge import build_sender_id_for_cc


# ── Constants ─────────────────────────────────────────────────────────────────

SESSION_DIR       = Path.home() / ".claude" / "sessions"
CENTRALIZED_LOG   = SESSION_DIR / "cc-listeners.log"
SUBSCRIBED_EVENTS = [ "notification_queue_update" ]


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

        # Match — inject directly into tmux prompt (skip buffer for idle injection)
        message_text = notification.get( "message", "" ).strip()
        if message_text:
            self._inject_via_tmux( message_text )
        self._send_gist_response( notification )

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
        else:
            self._log( f"{self.LOG_PREFIX} Unknown action: {action}" )

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

    def _inject_via_tmux( self, message_text ):
        """
        Type the voice message into the CC session's tmux pane, then press Enter.

        Uses tmux send-keys -l (literal) to avoid key interpretation of special
        characters. Sends Enter separately after a brief delay — tmux cannot
        reliably combine literal text + Enter in a single call.

        Requires:
            - message_text is a non-empty string
            - tmux session is resolvable

        Ensures:
            - Types message text into the CC prompt
            - Presses Enter after 250ms delay
            - CC receives a non-empty prompt and processes it
            - Never raises exceptions (injection failure is non-fatal)
        """
        tmux_session = self._resolve_tmux_session()
        if not tmux_session:
            self._log( f"{self.LOG_PREFIX} No tmux session found -- skipping injection" )
            return

        # Phase 2 — Layer 1 threading: wrap with conv-mode envelope when active.
        # See: src/rnd/v0.1.7/2026.04.30-conv-mode-three-layer-enforcement/01-design.md
        # Pass-through (unwrapped) when conv mode is off — gate is in conv_mode_wrap.
        try:
            from lupin_cli.claude_code.hooks.lib.hook_common import conv_mode_wrap
            message_text = conv_mode_wrap(
                message_text,
                source     = "voice",
                session_id = self.session_id_hash
            )
        except Exception as e:
            # Wrap failure is non-fatal — fall through with raw text
            self._log( f"{self.LOG_PREFIX} conv_mode_wrap failed (passing through unwrapped): {e}" )

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

        # Fallback: first 5 words
        if not gist:
            gist = " ".join( text.split()[ :5 ] )

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
                timeout           = 3
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

        restart_cycle    = 0
        restart_cooldown = 60  # seconds
        self._running    = True

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
