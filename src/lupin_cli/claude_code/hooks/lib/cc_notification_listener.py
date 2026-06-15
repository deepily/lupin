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
from lupin_cli.claude_code.hooks.lib.listener_processes import tmux_injection_lock


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
        if self._recipient_is_idle():
            self._handle_peer_dm( notification )
        else:
            self._buffer_message( notification )

    def _recipient_is_idle( self ):
        """
        Is this CC session sitting at an idle prompt right now?

        Reads the most recent heartbeat outcome for this session: a last outcome
        of EVENT_IDLE ("idle") means the session went idle and is waiting at a
        prompt. Any other outcome (poked/honored/cap_reached/…) or None (no
        heartbeat history yet — e.g. a freshly-started session) is treated as
        ACTIVE, so a peer DM buffers cleanly rather than interrupting.

        Ensures:
            - Returns True iff last_emitted_outcome(<full stable uuid>) == EVENT_IDLE
            - Returns True when the full id can't be resolved, or on any
              read/import error (fail toward tmux-wake so a DM is never silently
              lost to a buffer that nothing drains)
        """
        try:
            from lupin_cli.claude_code.hooks.lib.session_bridge import find_session_by_id
            from lupin_cli.claude_code.hooks.lib.heartbeat_events import (
                last_emitted_outcome, EVENT_IDLE
            )
            # heartbeat events are keyed by the FULL stable UUID — the file is
            # <full_uuid>.jsonl, read by EXACT match (no prefix glob), and stop.py
            # writes via resolve_stable_session_id (full UUID). self.session_id_hash
            # is the 8-char form, so we MUST resolve the full id via the bridge
            # first; passing the 8-char hash straight through always misses the
            # file → None → "active" → the idle→tmux-wake branch was DEAD in prod
            # (F1, Cheech 2026-06-15). Fix at the source (the listener holds the
            # wrong-form id), not by loosening the store's exact-match contract.
            data    = find_session_by_id( self.session_id_hash )
            full_id = ( data.get( "stable_session_id" ) or data.get( "session_id" ) ) if data else None
            if not full_id:
                # No live bridge → can't resolve the full id → fail toward tmux-wake.
                return True
            return last_emitted_outcome( full_id ) == EVENT_IDLE
        except Exception as e:
            self._log( f"{self.LOG_PREFIX} idle-state read failed (assuming idle/tmux-wake): {e}" )
            return True

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
        elif action == "commons_answer_received":
            self._handle_commons_answer_received( notification )
        elif action == "commons_question_received":
            self._handle_commons_question_received( notification )
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

    def _handle_commons_answer_received( self, notification ):
        """
        Handle an `action:commons_answer_received` notification from the
        server-side `CommonsQuestionWatcher` (Phase 3 step 8).

        Per AC4 + Q3 of
        src/rnd/v0.1.7/2026.05.09-inter-session-commons/04-phase3-push-mode-and-llm-fallback-design.md:
        - Reads `persona_name` from the STAMPED notification payload (F9-fit
          immutability — never a live lookup; the answerer's persona at
          answer-write time is the authoritative attribution).
        - Builds the `<system-reminder>` body using the Q3 framing:
              "COMMONS PEER REPLY (question_id X, from @PersonaName):
                  [body]"
          PEER ≠ USER (intra-AI principle), REPLY ≠ BROADCAST.
        - Injects via `_inject_via_tmux(text, wrap=False)` — the body
          is already a complete <system-reminder> block.
        """
        payload      = notification.get( "payload" ) or { }
        question_id  = payload.get( "question_id" )
        body         = payload.get( "body", "" )
        persona_name = payload.get( "persona_name" ) or "unknown"

        if not question_id:
            self._log( f"{self.LOG_PREFIX} commons_answer_received missing question_id; skipping" )
            return

        # Q3 framing — persona attribution preserves provenance; question_id
        # lets the LLM correlate to the original ask_async call.
        reminder_body = (
            f"COMMONS PEER REPLY (question_id {question_id}, from @{persona_name}):\n\n"
            f"{body}"
        )
        wrapped = f"<system-reminder>\n{reminder_body}\n</system-reminder>"
        self._inject_via_tmux( wrapped, wrap=False )

    def _handle_commons_question_received( self, notification ):
        """
        Handle an `action:commons_question_received` notification — an inter-
        session directed DM addressed to this CC session.

        Per AC6 + Phase 0 Q5-rev framing of
        src/rnd/v0.1.7/2026.05.15-inter-session-direct-messaging-design.md:
        - Reads payload fields stamped at register-question dispatch time by
          the endpoint's `_dispatch_commons_question_received` helper (the
          sender's persona is NOT stamped here today — the listener can read
          it from the topic entry if needed). For v1, the sender is identified
          via the asker_session_id field; future enhancement adds the sender's
          persona to the dispatch payload.
        - Builds the `<system-reminder>` body using the Q5-rev framing
          (parallel to Phase 3's COMMONS PEER REPLY):
              "COMMONS PEER MESSAGE (question_id X, topic Y, from session Z):
                  <body to be read from the commons topic>"
          For v1, the body is not in the dispatch payload (the entry sits in
          the commons topic) — the listener injects the framing with a
          pointer to the topic + question_id so the recipient AI can call
          commons_read() to retrieve the actual body and any subsequent
          context. v1.1 enhancement: include body in dispatch payload to
          avoid the read round-trip.
        - Injects via `_inject_via_tmux(text, wrap=False)` — body is a
          complete <system-reminder> block.
        """
        payload          = notification.get( "payload" ) or { }
        question_id      = payload.get( "question_id" )
        topic            = payload.get( "topic" )
        asker_session    = payload.get( "asker_session" ) or "unknown"

        if not question_id:
            self._log( f"{self.LOG_PREFIX} commons_question_received missing question_id; skipping" )
            return
        if not topic:
            self._log( f"{self.LOG_PREFIX} commons_question_received missing topic; skipping" )
            return

        reminder_body = (
            f"COMMONS PEER MESSAGE (question_id {question_id}, topic {topic}, from session {asker_session[:8]}):\n\n"
            f"A peer CC session has addressed a directed DM to you on topic '{topic}' with question_id '{question_id}'.\n"
            f"Read the message body via commons_read(topic='{topic}', limit=10) and look for the entry whose "
            f"metadata.question_id == '{question_id}'. To reply, call commons_post(topic='{topic}', body='<your reply>', "
            f"metadata={{'in_reply_to': '{question_id}'}}) — the original asker's watcher will push your reply back "
            f"to their tmux session via Phase 3 commons_answer_received."
        )
        wrapped = f"<system-reminder>\n{reminder_body}\n</system-reminder>"
        try:
            self._inject_via_tmux( wrapped, wrap=False )
        except Exception as e:
            # T7 listener-injection isolation: failure logs + skips, doesn't crash listener
            self._log( f"{self.LOG_PREFIX} commons_question_received inject failed: {e}" )

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
            with urllib.request.urlopen( req, timeout=10.0 ) as resp:
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
            with urllib.request.urlopen( req, timeout=10.0 ) as resp:
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
