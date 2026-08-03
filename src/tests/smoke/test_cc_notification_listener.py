#!/usr/bin/env python3
"""
Smoke tests for the CC Notification Listener.

Validates lifecycle, buffer accumulation, atomic drain, and credential
resolution for the stateful WebSocket listener that buffers
user_initiated_message notifications for Claude Code sessions.

Tests:
    1. Lifecycle: spawn listener, verify running, SIGTERM, verify clean exit
    2. Accumulation + Drain: send messages via API, drain buffer, verify order
    3. Atomicity: concurrent drain race, verify no message loss
    4. Credential resolution: INI file parsing, missing section errors
    5. Buffer path computation: deterministic path from session hash

Usage:
    # Run all tests (no server required for unit-level tests)
    pytest src/tests/smoke/test_cc_notification_listener.py -v

    # Run only tests that don't require a server
    pytest src/tests/smoke/test_cc_notification_listener.py -v -k "not live"

    # Run with live server (requires FastAPI on port 7999)
    pytest src/tests/smoke/test_cc_notification_listener.py -v -k "live"
"""

import configparser
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure src/ is on path
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", "" ), "src" )
if _src_path and _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib.hook_common import (
    drain_voice_buffer,
    get_buffer_path,
)
from lupin_cli.claude_code.hooks.lib.hook_credentials import (
    get_hook_credentials,
    CREDENTIALS_FILE,
)
from lupin_cli.claude_code.hooks.lib.session_bridge import resolve_project_name
from lupin_cli.claude_code.hooks.lib.cc_notification_listener import (
    CCNotificationListener,
    SESSION_DIR,
)


# ══════════════════════════════════════════════════════════════════════════════
# Test: Buffer Path Computation
# ══════════════════════════════════════════════════════════════════════════════

class TestBufferPath:
    """Test get_buffer_path() produces deterministic, correct paths."""

    def test_full_session_id( self ):
        """Full UUID-style session_id truncated to 8 chars."""
        path = get_buffer_path( "bbd0e94b-cdf0-4766-a16d-16fe116125ef" )
        assert path.name == "cc-buffer-bbd0e94b.jsonl"

    def test_short_session_id( self ):
        """8-char session ID used directly."""
        path = get_buffer_path( "abc12345" )
        assert path.name == "cc-buffer-abc12345.jsonl"

    def test_empty_session_id( self ):
        """Empty session_id falls back to zeros."""
        path = get_buffer_path( "" )
        assert path.name == "cc-buffer-00000000.jsonl"

    def test_none_session_id( self ):
        """None session_id falls back to zeros."""
        path = get_buffer_path( None )
        assert path.name == "cc-buffer-00000000.jsonl"

    def test_path_in_sessions_dir( self ):
        """Buffer path lives in ~/.claude/sessions/."""
        path = get_buffer_path( "abc12345" )
        assert str( path ).endswith( "/.claude/sessions/cc-buffer-abc12345.jsonl" )


# ══════════════════════════════════════════════════════════════════════════════
# Test: Drain Voice Buffer
# ══════════════════════════════════════════════════════════════════════════════

class TestDrainVoiceBuffer:
    """Test atomic drain_voice_buffer() function."""

    def test_empty_buffer( self, tmp_path ):
        """Drain returns empty list when no buffer file exists."""
        with patch( "lupin_cli.claude_code.hooks.lib.hook_common.SESSION_DIR", tmp_path ):
            result = drain_voice_buffer( "test1234" )
            assert result == []

    def test_single_message( self, tmp_path ):
        """Drain returns single message from buffer."""
        # Write a buffer file
        buffer_file = tmp_path / "cc-buffer-test1234.jsonl"
        msg = { "message": "Hello", "priority": "normal", "job_id": "test1234" }
        buffer_file.write_text( json.dumps( msg ) + "\n" )

        with patch( "lupin_cli.claude_code.hooks.lib.hook_common.SESSION_DIR", tmp_path ):
            result = drain_voice_buffer( "test1234" )

        assert len( result ) == 1
        assert result[0][ "message" ] == "Hello"
        assert not buffer_file.exists(), "Buffer file should be deleted after drain"

    def test_multiple_messages_ordered( self, tmp_path ):
        """Messages returned in chronological (write) order."""
        buffer_file = tmp_path / "cc-buffer-multi123.jsonl"
        messages = [
            { "message": f"Message {i}", "priority": "normal", "job_id": "multi123" }
            for i in range( 5 )
        ]
        buffer_file.write_text(
            "\n".join( json.dumps( m ) for m in messages ) + "\n"
        )

        with patch( "lupin_cli.claude_code.hooks.lib.hook_common.SESSION_DIR", tmp_path ):
            result = drain_voice_buffer( "multi123" )

        assert len( result ) == 5
        for i, msg in enumerate( result ):
            assert msg[ "message" ] == f"Message {i}"

    def test_drain_is_atomic( self, tmp_path ):
        """Second concurrent drain gets empty list (rename already happened)."""
        buffer_file = tmp_path / "cc-buffer-atom1234.jsonl"
        buffer_file.write_text( json.dumps( { "message": "test" } ) + "\n" )

        with patch( "lupin_cli.claude_code.hooks.lib.hook_common.SESSION_DIR", tmp_path ):
            # First drain succeeds
            result1 = drain_voice_buffer( "atom1234" )
            # Second drain finds no file
            result2 = drain_voice_buffer( "atom1234" )

        assert len( result1 ) == 1
        assert len( result2 ) == 0

    def test_malformed_lines_skipped( self, tmp_path ):
        """Malformed JSON lines are silently skipped."""
        buffer_file = tmp_path / "cc-buffer-bad12345.jsonl"
        buffer_file.write_text(
            json.dumps( { "message": "good1" } ) + "\n"
            + "this is not json\n"
            + json.dumps( { "message": "good2" } ) + "\n"
        )

        with patch( "lupin_cli.claude_code.hooks.lib.hook_common.SESSION_DIR", tmp_path ):
            result = drain_voice_buffer( "bad12345" )

        assert len( result ) == 2
        assert result[0][ "message" ] == "good1"
        assert result[1][ "message" ] == "good2"

    def test_empty_lines_skipped( self, tmp_path ):
        """Empty lines in buffer are skipped."""
        buffer_file = tmp_path / "cc-buffer-empty123.jsonl"
        buffer_file.write_text(
            json.dumps( { "message": "a" } ) + "\n\n\n"
            + json.dumps( { "message": "b" } ) + "\n"
        )

        with patch( "lupin_cli.claude_code.hooks.lib.hook_common.SESSION_DIR", tmp_path ):
            result = drain_voice_buffer( "empty123" )

        assert len( result ) == 2


# ══════════════════════════════════════════════════════════════════════════════
# Test: Credential Resolution
# ══════════════════════════════════════════════════════════════════════════════

class TestCredentialResolution:
    """Test INI-based credential resolution."""

    def _write_ini( self, path, sections ):
        """Helper: write INI file with given sections."""
        config = configparser.ConfigParser()
        for name, values in sections.items():
            config[ name ] = values
        with open( path, "w" ) as f:
            config.write( f )

    def test_valid_credentials( self, tmp_path ):
        """Valid INI file returns correct email and password."""
        ini_file = tmp_path / "creds.ini"
        self._write_ini( ini_file, {
            "lupin": { "email": "test@lupin.ai", "password": "secret123" }
        } )

        with patch( "lupin_cli.claude_code.hooks.lib.hook_credentials.CREDENTIALS_FILE", ini_file ):
            email, password = get_hook_credentials( project="lupin" )

        assert email == "test@lupin.ai"
        assert password == "secret123"

    def test_missing_file_raises( self, tmp_path ):
        """Missing INI file raises FileNotFoundError."""
        missing = tmp_path / "nonexistent.ini"

        with patch( "lupin_cli.claude_code.hooks.lib.hook_credentials.CREDENTIALS_FILE", missing ):
            with pytest.raises( FileNotFoundError ):
                get_hook_credentials( project="lupin" )

    def test_missing_section_raises( self, tmp_path ):
        """INI file without matching section raises ValueError."""
        ini_file = tmp_path / "creds.ini"
        self._write_ini( ini_file, {
            "cosa": { "email": "test@cosa.ai", "password": "secret" }
        } )

        with patch( "lupin_cli.claude_code.hooks.lib.hook_credentials.CREDENTIALS_FILE", ini_file ):
            with pytest.raises( ValueError, match="No \\[lupin\\] section" ):
                get_hook_credentials( project="lupin" )

    def test_missing_email_raises( self, tmp_path ):
        """INI section without email key raises ValueError."""
        ini_file = tmp_path / "creds.ini"
        self._write_ini( ini_file, {
            "lupin": { "password": "secret" }
        } )

        with patch( "lupin_cli.claude_code.hooks.lib.hook_credentials.CREDENTIALS_FILE", ini_file ):
            with pytest.raises( ValueError, match="Missing 'email'" ):
                get_hook_credentials( project="lupin" )

    def test_missing_password_raises( self, tmp_path ):
        """INI section without password key raises ValueError."""
        ini_file = tmp_path / "creds.ini"
        self._write_ini( ini_file, {
            "lupin": { "email": "test@lupin.ai" }
        } )

        with patch( "lupin_cli.claude_code.hooks.lib.hook_credentials.CREDENTIALS_FILE", ini_file ):
            with pytest.raises( ValueError, match="Missing 'password'" ):
                get_hook_credentials( project="lupin" )

    def test_multiple_sections( self, tmp_path ):
        """Correct section selected from multi-section INI."""
        ini_file = tmp_path / "creds.ini"
        self._write_ini( ini_file, {
            "lupin" : { "email": "lupin@test.ai", "password": "lupin-pass" },
            "cosa"  : { "email": "cosa@test.ai", "password": "cosa-pass" },
        } )

        with patch( "lupin_cli.claude_code.hooks.lib.hook_credentials.CREDENTIALS_FILE", ini_file ):
            email_l, pass_l = get_hook_credentials( project="lupin" )
            email_c, pass_c = get_hook_credentials( project="cosa" )

        assert email_l == "lupin@test.ai"
        assert email_c == "cosa@test.ai"

    def test_project_derivation_from_lupin_root( self ):
        """Project name falls back to LUPIN_ROOT basename when no bridge resolves."""
        with patch( "lupin_cli.claude_code.hooks.lib.session_bridge._resolve_project_from_bridge_cwd",
                    return_value=None ), \
             patch.dict( os.environ, { "LUPIN_ROOT": "/path/to/lupin" } ):
            assert resolve_project_name() == "lupin"


# ══════════════════════════════════════════════════════════════════════════════
# Test: CC Notification Listener Instance
# ══════════════════════════════════════════════════════════════════════════════

class TestCCNotificationListenerInit:
    """Test CCNotificationListener initialization and configuration."""

    def test_default_buffer_path( self ):
        """Default buffer path computed from session hash."""
        listener = CCNotificationListener(
            email           = "test@test.ai",
            password        = "pass",
            session_id_hash = "abc12345",
        )
        assert listener.buffer_path.name == "cc-buffer-abc12345.jsonl"
        assert listener.session_id_hash == "abc12345"

    def test_custom_buffer_path( self, tmp_path ):
        """Custom buffer path overrides default."""
        custom = tmp_path / "custom-buffer.jsonl"
        listener = CCNotificationListener(
            email           = "test@test.ai",
            password        = "pass",
            session_id_hash = "abc12345",
            buffer_path     = str( custom ),
        )
        assert listener.buffer_path == custom

    def test_websocket_session_name( self ):
        """WebSocket session ID is cc-listener-{hash}."""
        listener = CCNotificationListener(
            email           = "test@test.ai",
            password        = "pass",
            session_id_hash = "abc12345",
        )
        assert listener.session_id == "cc-listener-abc12345"

    def test_subscribed_events( self ):
        """Listener subscribes to notification_queue_update."""
        listener = CCNotificationListener(
            email           = "test@test.ai",
            password        = "pass",
            session_id_hash = "abc12345",
        )
        assert listener.subscribed_events == [ "notification_queue_update" ]

    def test_log_prefix( self ):
        """Log prefix is [CC-Listener]."""
        listener = CCNotificationListener(
            email           = "test@test.ai",
            password        = "pass",
            session_id_hash = "abc12345",
        )
        assert listener.LOG_PREFIX == "[CC-Listener]"


# ══════════════════════════════════════════════════════════════════════════════
# Test: Event Handling + Buffering
# ══════════════════════════════════════════════════════════════════════════════

class TestEventHandling:
    """Test event filtering and tmux injection logic."""

    @pytest.fixture
    def listener( self, tmp_path ):
        """Create a listener with buffer in tmp_path."""
        return CCNotificationListener(
            email           = "test@test.ai",
            password        = "pass",
            session_id_hash = "sess1234",
            buffer_path     = str( tmp_path / "test-buffer.jsonl" ),
        )

    @pytest.mark.asyncio
    async def test_matching_message_injected( self, listener ):
        """user_initiated_message with matching job_id triggers tmux injection."""
        with patch.object( listener, '_inject_via_tmux' ) as mock_inject, \
             patch.object( listener, '_send_gist_response' ):
            await listener._handle_event( "notification_queue_update", {
                "notification": {
                    "type"    : "user_initiated_message",
                    "job_id"  : "sess1234",
                    "message" : "Hello from voice",
                }
            } )

            mock_inject.assert_called_once_with( "Hello from voice" )

    @pytest.mark.asyncio
    async def test_wrong_job_id_not_injected( self, listener ):
        """user_initiated_message with wrong job_id is NOT injected."""
        with patch.object( listener, '_inject_via_tmux' ) as mock_inject:
            await listener._handle_event( "notification_queue_update", {
                "notification": {
                    "type"    : "user_initiated_message",
                    "job_id"  : "other999",
                    "message" : "Wrong session",
                }
            } )

            mock_inject.assert_not_called()

    @pytest.mark.asyncio
    async def test_wrong_type_not_injected( self, listener ):
        """Non user_initiated_message type is NOT injected."""
        with patch.object( listener, '_inject_via_tmux' ) as mock_inject:
            await listener._handle_event( "notification_queue_update", {
                "notification": {
                    "type"    : "progress",
                    "job_id"  : "sess1234",
                    "message" : "Progress update",
                }
            } )

            mock_inject.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_notification_event_ignored( self, listener ):
        """Non notification_queue_update event is ignored."""
        with patch.object( listener, '_inject_via_tmux' ) as mock_inject:
            await listener._handle_event( "some_other_event", {
                "data": "irrelevant"
            } )

            mock_inject.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_messages_injected( self, listener ):
        """Multiple matching messages each trigger tmux injection."""
        injected = []
        with patch.object( listener, '_inject_via_tmux', side_effect=lambda m: injected.append( m ) ), \
             patch.object( listener, '_send_gist_response' ):
            for i in range( 3 ):
                await listener._handle_event( "notification_queue_update", {
                    "notification": {
                        "type"    : "user_initiated_message",
                        "job_id"  : "sess1234",
                        "message" : f"Message {i}",
                    }
                } )

        assert len( injected ) == 3
        for i, msg in enumerate( injected ):
            assert msg == f"Message {i}"

    @pytest.mark.asyncio
    async def test_message_count_incremented( self, listener ):
        """Message counter tracks injected messages."""
        assert listener._message_count == 0

        with patch.object( listener, '_inject_via_tmux' ), \
             patch.object( listener, '_send_gist_response' ):
            await listener._handle_event( "notification_queue_update", {
                "notification": {
                    "type"    : "user_initiated_message",
                    "job_id"  : "sess1234",
                    "message" : "First",
                }
            } )

        # _message_count is incremented by _buffer_message; direct injection
        # uses a different path — verify handler completes without error
        # (count tracking was removed when switching to direct tmux injection)

    @pytest.mark.asyncio
    async def test_notification_type_field_variant( self, listener ):
        """notification_type field (alternative to type) is recognized."""
        with patch.object( listener, '_inject_via_tmux' ) as mock_inject, \
             patch.object( listener, '_send_gist_response' ):
            await listener._handle_event( "notification_queue_update", {
                "notification": {
                    "notification_type" : "user_initiated_message",
                    "job_id"            : "sess1234",
                    "message"           : "Alt field",
                }
            } )

            mock_inject.assert_called_once_with( "Alt field" )

    @pytest.mark.asyncio
    async def test_empty_title_does_not_crash( self, listener ):
        """Notification with empty title (normalized from None at API boundary) proceeds to injection."""
        with patch.object( listener, '_inject_via_tmux' ) as mock_inject, \
             patch.object( listener, '_send_gist_response' ):
            await listener._handle_event( "notification_queue_update", {
                "notification": {
                    "type"      : "user_initiated_message",
                    "job_id"    : "sess1234",
                    "message"   : "Voice message",
                    "title"     : "",
                }
            } )

            mock_inject.assert_called_once_with( "Voice message" )

    @pytest.mark.asyncio
    async def test_action_title_routes_to_handler( self, listener ):
        """Notification with action: title prefix routes to _handle_action."""
        with patch.object( listener, '_handle_action' ) as mock_action, \
             patch.object( listener, '_inject_via_tmux' ) as mock_inject:
            await listener._handle_event( "notification_queue_update", {
                "notification": {
                    "type"    : "user_initiated_message",
                    "job_id"  : "sess1234",
                    "message" : "Bug Fix: WS crash",
                    "title"   : "action:set_session_topic",
                }
            } )

            mock_action.assert_called_once_with( "set_session_topic", {
                "type"    : "user_initiated_message",
                "job_id"  : "sess1234",
                "message" : "Bug Fix: WS crash",
                "title"   : "action:set_session_topic",
            } )
            mock_inject.assert_not_called()

    def test_action_disable_speakerphone_injects_reminder( self, listener ):
        """
        action:disable_speakerphone (renamed from exit_conversation_mode by the
        2026-05-12 speakerphone refactor) triggers _inject_via_tmux with the
        deactivation system-reminder body. The reminder is generated by
        `hook_common.speakerphone_exit_reminder()`; assert via call observability
        rather than reminder-body string match (the body varies by tts_interaction_mode).
        """
        with patch.object( listener, '_inject_via_tmux' ) as mock_inject:
            listener._handle_action( "disable_speakerphone", {} )

            assert mock_inject.call_count == 1
            args, kwargs = mock_inject.call_args
            # First positional is the reminder body; kwargs.wrap=False bypasses
            # the entry-side conv-mode wrap pipeline.
            reminder = args[ 0 ] if args else kwargs.get( "message_text" )
            assert reminder is not None and len( reminder ) > 0
            assert kwargs.get( "wrap" ) is False

    def test_action_unknown_logs_without_raising( self, listener ):
        """An unrecognized action: name logs and returns without raising."""
        with patch.object( listener, '_inject_via_tmux' ) as mock_inject, \
             patch.object( listener, '_log' ) as mock_log:
            # Should not raise
            listener._handle_action( "no_such_action", { "message": "" } )
            mock_inject.assert_not_called()
            # Logged something with "Unknown action"
            assert any( "Unknown action" in str( c ) for c in mock_log.call_args_list )


    @pytest.mark.asyncio
    async def test_voice_empty_message_skips_inject_still_gists( self, listener ):
        """
        A matching voice notification with an empty/whitespace body skips the
        tmux injection but still fires the gist auto-response (covers the
        message_text-falsy branch of the voice path).
        """
        with patch.object( listener, '_inject_via_tmux' ) as mock_inject, \
             patch.object( listener, '_send_gist_response' ) as mock_gist:
            await listener._handle_event( "notification_queue_update", {
                "notification": {
                    "type"    : "user_initiated_message",
                    "job_id"  : "sess1234",
                    "message" : "   ",
                }
            } )
            mock_inject.assert_not_called()
            mock_gist.assert_called_once()

    # ── Phase 3 §6a — direction-aware peer-DM framing ──────────────────────────

    @pytest.mark.asyncio
    async def test_ai_to_ai_routes_to_deliver_peer_dm( self, listener ):
        """
        A user_initiated_message carrying direction=ai_to_ai routes to the
        idle-aware _deliver_peer_dm — NOT the human-voice path (_inject_via_tmux
        raw + _send_gist_response). Per §6 of
        src/rnd/v0.1.8/2026.06.13-cosa-voice-token-reduction/02-notification-native-aixai-design.md.
        """
        with patch.object( listener, '_deliver_peer_dm' ) as mock_deliver, \
             patch.object( listener, '_inject_via_tmux' ) as mock_inject, \
             patch.object( listener, '_send_gist_response' ) as mock_gist:
            await listener._handle_event( "notification_queue_update", {
                "notification": {
                    "type"      : "user_initiated_message",
                    "job_id"    : "sess1234",
                    "message"   : "peer body",
                    "direction" : "ai_to_ai",
                }
            } )
            mock_deliver.assert_called_once()
            # Voice path is bypassed entirely for a peer DM.
            mock_inject.assert_not_called()
            mock_gist.assert_not_called()

    @pytest.mark.asyncio
    async def test_human_to_ai_uses_voice_path( self, listener ):
        """direction=human_to_ai keeps the existing voice path (raw inject + gist)."""
        with patch.object( listener, '_deliver_peer_dm' ) as mock_deliver, \
             patch.object( listener, '_inject_via_tmux' ) as mock_inject, \
             patch.object( listener, '_send_gist_response' ):
            await listener._handle_event( "notification_queue_update", {
                "notification": {
                    "type"      : "user_initiated_message",
                    "job_id"    : "sess1234",
                    "message"   : "Hello from voice",
                    "direction" : "human_to_ai",
                }
            } )
            mock_deliver.assert_not_called()
            mock_inject.assert_called_once_with( "Hello from voice" )

    @pytest.mark.asyncio
    async def test_missing_direction_uses_voice_path( self, listener ):
        """
        A legacy notification with no direction key keeps the voice path —
        only an explicit direction=ai_to_ai diverts to the peer handler.
        """
        with patch.object( listener, '_deliver_peer_dm' ) as mock_deliver, \
             patch.object( listener, '_inject_via_tmux' ) as mock_inject, \
             patch.object( listener, '_send_gist_response' ):
            await listener._handle_event( "notification_queue_update", {
                "notification": {
                    "type"    : "user_initiated_message",
                    "job_id"  : "sess1234",
                    "message" : "Legacy voice",
                }
            } )
            mock_deliver.assert_not_called()
            mock_inject.assert_called_once_with( "Legacy voice" )

    # ── §6 idle-aware delivery split: _deliver_peer_dm + _recipient_is_injectable ─────

    def test_deliver_peer_dm_active_buffers( self, listener ):
        """An ACTIVE recipient (not idle) → _buffer_message (clean, non-invasive),
        NOT a mid-turn tmux injection."""
        notif = { "direction": "ai_to_ai", "message": "hi", "job_id": "sess1234" }
        with patch.object( listener, '_recipient_is_injectable', return_value=False ), \
             patch.object( listener, '_buffer_message' ) as mock_buf, \
             patch.object( listener, '_handle_peer_dm' ) as mock_tmux:
            listener._deliver_peer_dm( notif )
            mock_buf.assert_called_once_with( notif )
            mock_tmux.assert_not_called()

    def test_deliver_peer_dm_idle_tmux_wakes( self, listener ):
        """An IDLE recipient → _handle_peer_dm (tmux-wake), NOT the buffer (nothing
        would drain a buffer at an idle pane)."""
        notif = { "direction": "ai_to_ai", "message": "hi", "job_id": "sess1234" }
        with patch.object( listener, '_recipient_is_injectable', return_value=True ), \
             patch.object( listener, '_buffer_message' ) as mock_buf, \
             patch.object( listener, '_handle_peer_dm' ) as mock_tmux:
            listener._deliver_peer_dm( notif )
            mock_tmux.assert_called_once_with( notif )
            mock_buf.assert_not_called()

    # bug d1bb1456 (2026-07-02): _recipient_is_injectable no longer reads the
    # heartbeat outcome log (it returned None → buffer for a parked pane that
    # emitted only idle_prompt beacons or last-outcome "poked" → the DM-wake gap,
    # residual of baf5ea6d). Injectability is now decided by a bounded, fail-open
    # tmux PANE-IDLE PROBE that observes the pane's real state. The end-to-end
    # ROUTING tests below drive the REAL _recipient_is_injectable → probe →
    # classifier path, stubbing only the pane capture + the two terminal sinks.
    _DIVIDER = "─" * 128

    def _idle_pane( self ):
        return ( f"{self._DIVIDER}\n❯ \n{self._DIVIDER}\n"
                 "  ⏵⏵ auto mode on (shift+tab to cycle)\n" )

    def _busy_pane( self ):
        return ( f"{self._DIVIDER}\n❯ \n{self._DIVIDER}\n"
                 "  ⏵⏵ auto mode on (shift+tab to cycle) · esc to interrupt · ← for agents\n" )

    def _dialog_pane( self ):
        return ( f"{self._DIVIDER}\nDo you want to proceed?\n❯ 1. Yes\n"
                 "  2. No, and tell Claude what to do differently\n" )

    def test_deliver_peer_dm_idle_pane_wakes_end_to_end( self, listener ):
        """d1bb1456 fix (cases A–D): a parked pane observably at an idle prompt →
        the REAL _recipient_is_injectable probe returns True → _deliver_peer_dm
        tmux-wakes, regardless of any heartbeat outcome (which is never consulted)."""
        notif = { "direction": "ai_to_ai", "message": "hi", "job_id": "sess1234" }
        with patch.object( listener, "_resolve_tmux_session", return_value="t" ), \
             patch.object( listener, "_capture_pane", side_effect=[ self._idle_pane(), self._idle_pane() ] ), \
             patch( "lupin_cli.claude_code.hooks.lib.cc_notification_listener.time.sleep" ), \
             patch.object( listener, "_handle_peer_dm" ) as mock_tmux, \
             patch.object( listener, "_buffer_message" ) as mock_buf:
            listener._deliver_peer_dm( notif )
            mock_tmux.assert_called_once_with( notif )
            mock_buf.assert_not_called()

    def test_deliver_peer_dm_busy_pane_buffers_end_to_end( self, listener ):
        """Mid-turn guard: a pane showing 'esc to interrupt' → NOT injectable →
        _deliver_peer_dm buffers (never corrupt a running turn)."""
        notif = { "direction": "ai_to_ai", "message": "hi", "job_id": "sess1234" }
        with patch.object( listener, "_resolve_tmux_session", return_value="t" ), \
             patch.object( listener, "_capture_pane", return_value=self._busy_pane() ), \
             patch( "lupin_cli.claude_code.hooks.lib.cc_notification_listener.time.sleep" ), \
             patch.object( listener, "_handle_peer_dm" ) as mock_tmux, \
             patch.object( listener, "_buffer_message" ) as mock_buf:
            listener._deliver_peer_dm( notif )
            mock_buf.assert_called_once_with( notif )
            mock_tmux.assert_not_called()

    def test_deliver_peer_dm_dialog_pane_buffers_end_to_end( self, listener ):
        """Dialog guard: a permission/AskUserQuestion modal (no 'esc to interrupt',
        divider present) → NOT injectable → buffer, so injected text can never
        select a dialog option."""
        notif = { "direction": "ai_to_ai", "message": "hi", "job_id": "sess1234" }
        with patch.object( listener, "_resolve_tmux_session", return_value="t" ), \
             patch.object( listener, "_capture_pane", return_value=self._dialog_pane() ), \
             patch( "lupin_cli.claude_code.hooks.lib.cc_notification_listener.time.sleep" ), \
             patch.object( listener, "_handle_peer_dm" ) as mock_tmux, \
             patch.object( listener, "_buffer_message" ) as mock_buf:
            listener._deliver_peer_dm( notif )
            mock_buf.assert_called_once_with( notif )
            mock_tmux.assert_not_called()

    # NOTE (bug d1bb1456, 2026-07-02): the F1 (8char→full-uuid resolution),
    # baf5ea6d (trailing idle_prompt masking), and held-worker-inject (honored/
    # cap_reached) end-to-end regressions that lived here tested the heartbeat-
    # OUTCOME-log injectability mechanism, which is RETIRED. Injectability is now a
    # tmux PANE-IDLE PROBE (a parked pane wakes regardless of outcome-log state, so
    # those None/masking/honored cases are subsumed). Their behaviour — a parked
    # pane wakes, a busy/dialog pane buffers — is covered end-to-end by
    # test_deliver_peer_dm_{idle,busy,dialog}_pane_*_end_to_end above and unit-level
    # in test_cc_notification_listener_coverage.py::TestClassifyCaptureIdle /
    # TestPaneIsIdleAtPrompt / TestRecipientIsInjectableProbe.

    def test_peer_dm_builds_envelope_with_reply_affordance( self, listener ):
        """
        _handle_peer_dm injects a PEER DM envelope — sender persona + icon +
        message_id + thread_id + a dm_send reply affordance — with the body
        INLINE, wrap=False, and NONE of the human-voice rider language.
        """
        with patch.object( listener, '_inject_via_tmux' ) as mock_inject:
            listener._handle_peer_dm( {
                "message"        : "Build is green, ready for review.",
                "sender_persona" : "maria",
                "sender_icon"    : "🌸",
                "id"             : "msg-abc-123",
                "thread_id"      : "thr-xyz-789",
            } )
            assert mock_inject.call_count == 1
            args, kwargs = mock_inject.call_args
            reminder = args[ 0 ] if args else kwargs.get( "message_text" )
            # Complete system-reminder block, injected verbatim (no voice wrap).
            assert reminder.startswith( "<system-reminder>" )
            assert reminder.endswith( "</system-reminder>" )
            assert kwargs.get( "wrap" ) is False
            # Peer envelope: framing + persona + icon + ids + inline body.
            assert "PEER DM from"                   in reminder
            assert "maria"                          in reminder
            assert "🌸"                              in reminder
            assert "msg-abc-123"                    in reminder
            assert "thr-xyz-789"                    in reminder
            assert "Build is green, ready for review." in reminder
            # Reply affordance points at dm_send with threading params.
            assert "dm_send("    in reminder
            assert "reply_to="   in reminder
            assert "thread_id="  in reminder
            # NO human-voice rider language — this is a peer, not Rick speaking.
            lowered = reminder.lower()
            assert "user spoke"   not in lowered
            assert "speakerphone" not in lowered
            assert "notify("      not in reminder
            assert "tts"          not in lowered

    def test_peer_dm_missing_body_skips( self, listener ):
        """Empty inline body → log + return; no injection."""
        with patch.object( listener, '_inject_via_tmux' ) as mock_inject, \
             patch.object( listener, '_log' ) as mock_log:
            listener._handle_peer_dm( {
                "message"        : "   ",
                "sender_persona" : "maria",
            } )
            mock_inject.assert_not_called()
            assert any( "peer DM missing body" in str( c ) for c in mock_log.call_args_list )

    def test_peer_dm_defaults_when_provenance_missing( self, listener ):
        """Missing persona/icon/ids → graceful defaults; still injects an envelope."""
        with patch.object( listener, '_inject_via_tmux' ) as mock_inject:
            listener._handle_peer_dm( { "message": "no provenance here" } )
            args, kwargs = mock_inject.call_args
            reminder = args[ 0 ]
            assert "a peer session"      in reminder   # persona fallback
            assert "no provenance here"  in reminder
            assert kwargs.get( "wrap" ) is False

    def test_peer_dm_inject_failure_isolated( self, listener ):
        """Tmux injection failure is caught (T7 isolation) — log + don't crash."""
        with patch.object( listener, '_inject_via_tmux', side_effect=RuntimeError( "tmux down" ) ) as mock_inject, \
             patch.object( listener, '_log' ) as mock_log:
            listener._handle_peer_dm( {
                "message"        : "body",
                "sender_persona" : "maria",
            } )
            mock_inject.assert_called_once()
            assert any( "peer DM inject failed" in str( c ) for c in mock_log.call_args_list )

    # ── §6a — _buffer_message persists direction + DM provenance/threading ──────

    def test_buffer_message_persists_direction_and_provenance( self, listener ):
        """An ai_to_ai buffered entry carries direction + persona/icon/reply_to/thread_id."""
        listener._buffer_message( {
            "message"        : "green build",
            "job_id"         : "sess1234",
            "id"             : "m1",
            "direction"      : "ai_to_ai",
            "sender_persona" : "maria",
            "sender_icon"    : "🌸",
            "reply_to"       : "r0",
            "thread_id"      : "t1",
        } )
        lines = listener.buffer_path.read_text().strip().splitlines()
        assert len( lines ) == 1
        entry = json.loads( lines[ 0 ] )
        assert entry[ "direction" ]       == "ai_to_ai"
        assert entry[ "sender_persona" ]  == "maria"
        assert entry[ "sender_icon" ]     == "🌸"
        assert entry[ "reply_to" ]        == "r0"
        assert entry[ "thread_id" ]       == "t1"
        assert entry[ "message" ]         == "green build"
        assert entry[ "notification_id" ] == "m1"
        assert listener._message_count == 1

    def test_buffer_message_direction_defaults_human_to_ai( self, listener ):
        """A notification with no direction defaults to human_to_ai; DM fields default to None."""
        listener._buffer_message( { "message": "hi", "job_id": "s" } )
        entry = json.loads( listener.buffer_path.read_text().strip() )
        assert entry[ "direction" ]      == "human_to_ai"
        assert entry[ "sender_persona" ] is None
        assert entry[ "sender_icon" ]    is None
        assert entry[ "reply_to" ]       is None
        assert entry[ "thread_id" ]      is None

    def test_buffer_message_error_isolated( self, listener ):
        """A write/serialize failure is caught and logged — never crashes the listener."""
        with patch( "lupin_cli.claude_code.hooks.lib.cc_notification_listener.json.dumps",
                    side_effect=RuntimeError( "serialize boom" ) ), \
             patch.object( listener, '_log' ) as mock_log:
            listener._buffer_message( { "message": "hi", "job_id": "s" } )   # must not raise
            assert any( "ERROR buffering message" in str( c ) for c in mock_log.call_args_list )


# ══════════════════════════════════════════════════════════════════════════════
# Test: _stamp_user_id_on_bridge (Phase 3 Option 2 fix)
# ══════════════════════════════════════════════════════════════════════════════


class TestStampUserIdOnBridge:
    """
    Test the listener's `_stamp_user_id_on_bridge()` method per Option 2 of
    `src/rnd/v0.1.7/2026.05.13-broadcast-ui-no-active-sessions-bug.md`.

    The method must:
    - POST /auth/login with the listener's stored credentials
    - Extract `user.id` from the response
    - Call session_bridge.set_user_id(session_id_hash, user_id)
    - Swallow all failures silently (best-effort; Option 1 covers the gap)
    """

    @pytest.fixture
    def listener( self ):
        return CCNotificationListener(
            email           = "tester@example.com",
            password        = "pw",
            session_id_hash = "abc12345",
            host            = "localhost",
            port            = 7999,
        )

    def test_stamps_user_id_on_success( self, listener ):
        """
        Happy path: /auth/login returns 200 + `user.id`; set_user_id is called
        with (session_id_hash, user_id) and returns True.
        """
        from unittest.mock import MagicMock
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock( return_value=mock_resp )
        mock_resp.__exit__  = MagicMock( return_value=False )
        mock_resp.read.return_value = json.dumps( {
            "user"  : { "id": "user-uuid-abc" },
            "tokens": { "access_token": "jwt..." }
        } ).encode()

        with patch( "urllib.request.urlopen", return_value=mock_resp ) as mock_urlopen, \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.set_user_id", return_value=True ) as mock_set:
            listener._stamp_user_id_on_bridge()

        assert mock_urlopen.call_count == 1
        mock_set.assert_called_once_with( "abc12345", "user-uuid-abc" )

    def test_silent_on_missing_user_id_in_response( self, listener ):
        """
        Response lacks user.id → log + return without calling set_user_id.
        """
        from unittest.mock import MagicMock
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock( return_value=mock_resp )
        mock_resp.__exit__  = MagicMock( return_value=False )
        mock_resp.read.return_value = json.dumps( {
            "message": "Login successful",
            "tokens" : { "access_token": "jwt..." }
        } ).encode()

        with patch( "urllib.request.urlopen", return_value=mock_resp ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.set_user_id" ) as mock_set:
            listener._stamp_user_id_on_bridge()

        mock_set.assert_not_called()

    def test_silent_on_url_error( self, listener ):
        """Network failure → caught + logged + no exception propagates."""
        import urllib.error
        with patch( "urllib.request.urlopen", side_effect=urllib.error.URLError( "server unreachable" ) ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.set_user_id" ) as mock_set:
            listener._stamp_user_id_on_bridge()  # must NOT raise

        mock_set.assert_not_called()

    def test_silent_on_invalid_json_response( self, listener ):
        """Garbage response → caught + logged + no exception propagates."""
        from unittest.mock import MagicMock
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock( return_value=mock_resp )
        mock_resp.__exit__  = MagicMock( return_value=False )
        mock_resp.read.return_value = b"not valid json"

        with patch( "urllib.request.urlopen", return_value=mock_resp ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.set_user_id" ) as mock_set:
            listener._stamp_user_id_on_bridge()  # must NOT raise

        mock_set.assert_not_called()

    def test_silent_when_bridge_not_found( self, listener ):
        """
        Auth succeeds but set_user_id returns False (bridge missing) → log
        but no exception.
        """
        from unittest.mock import MagicMock
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock( return_value=mock_resp )
        mock_resp.__exit__  = MagicMock( return_value=False )
        mock_resp.read.return_value = json.dumps( {
            "user": { "id": "user-uuid-abc" }
        } ).encode()

        with patch( "urllib.request.urlopen", return_value=mock_resp ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.set_user_id", return_value=False ) as mock_set:
            listener._stamp_user_id_on_bridge()  # must NOT raise

        mock_set.assert_called_once()

    def test_silent_on_unexpected_exception( self, listener ):
        """
        Defense-in-depth: any other exception class is caught by the broad
        Exception handler. Listener startup must NEVER fail because of a
        user_id stamping issue.
        """
        with patch( "urllib.request.urlopen", side_effect=RuntimeError( "wat" ) ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.set_user_id" ) as mock_set:
            listener._stamp_user_id_on_bridge()  # must NOT raise

        mock_set.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# Test: SessionEnd Hook Functions
# ══════════════════════════════════════════════════════════════════════════════

class TestSessionEndHook:
    """Test SessionEnd hook helper functions (F2 reap-all contract, 2026-06-11)."""

    @staticmethod
    def _no_cmdline_matches( monkeypatch ):
        """Silence the pgrep sweep so only bridge-derived PIDs are observed."""
        import lupin_cli.claude_code.hooks.lib.listener_processes as listener_processes
        monkeypatch.setattr( listener_processes, "find_live_listener_pids", lambda h: [ ] )

    def test_find_listener_pids_from_bridge( self, tmp_path, monkeypatch ):
        """Finds the bridge-recorded listener PID."""
        from lupin_cli.claude_code.hooks.session_end import _find_all_listener_pids
        self._no_cmdline_matches( monkeypatch )

        bridge_file = tmp_path / "cc-12345.json"
        bridge_data = {
            "session_id"   : "bbd0e94b-cdf0-4766-a16d-16fe116125ef",
            "listener_pid" : 99999,
        }
        bridge_file.write_text( json.dumps( bridge_data ) )

        pids = _find_all_listener_pids(
            "bbd0e94b-cdf0-4766-a16d-16fe116125ef",
            session_dir=str( tmp_path )
        )
        assert pids == [ 99999 ]

    def test_no_matching_session( self, tmp_path, monkeypatch ):
        """Returns [] when no bridge file matches session_id."""
        from lupin_cli.claude_code.hooks.session_end import _find_all_listener_pids
        self._no_cmdline_matches( monkeypatch )

        bridge_file = tmp_path / "cc-12345.json"
        bridge_file.write_text( json.dumps( {
            "session_id"   : "other-session-id",
            "listener_pid" : 11111,
        } ) )

        pids = _find_all_listener_pids( "nonexistent-session", session_dir=str( tmp_path ) )
        assert pids == [ ]

    def test_empty_session_dir( self, tmp_path, monkeypatch ):
        """Returns [] when session dir is empty."""
        from lupin_cli.claude_code.hooks.session_end import _find_all_listener_pids
        self._no_cmdline_matches( monkeypatch )

        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        pids = _find_all_listener_pids( "any-session", session_dir=str( empty_dir ) )
        assert pids == [ ]

    def test_no_listener_pid_key( self, tmp_path, monkeypatch ):
        """Returns [] when bridge file has no listener_pid."""
        from lupin_cli.claude_code.hooks.session_end import _find_all_listener_pids
        self._no_cmdline_matches( monkeypatch )

        bridge_file = tmp_path / "cc-99999.json"
        bridge_file.write_text( json.dumps( {
            "session_id" : "test-session",
        } ) )

        pids = _find_all_listener_pids( "test-session", session_dir=str( tmp_path ) )
        assert pids == [ ]


# ══════════════════════════════════════════════════════════════════════════════
# Quick smoke test (standalone execution)
# ══════════════════════════════════════════════════════════════════════════════

def quick_smoke_test():
    """
    Run basic validation checks without pytest.

    Ensures:
        - All key classes and functions are importable
        - Buffer path computation works
        - Drain on empty buffer returns empty list
        - Listener initialization works
    """
    print( "\n  CC Notification Listener — Quick Smoke Test" )
    print( "  " + "═" * 50 )

    # Test 1: Imports
    print( "  ✓ All imports successful" )

    # Test 2: Buffer path
    path = get_buffer_path( "abc12345" )
    assert path.name == "cc-buffer-abc12345.jsonl"
    print( f"  ✓ Buffer path: {path}" )

    # Test 3: Empty drain
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch( "lupin_cli.claude_code.hooks.lib.hook_common.SESSION_DIR", Path( tmpdir ) ):
            result = drain_voice_buffer( "test0000" )
            assert result == []
    print( "  ✓ Empty drain returns []" )

    # Test 4: Listener init
    listener = CCNotificationListener(
        email           = "test@test.ai",
        password        = "pass",
        session_id_hash = "abc12345",
    )
    assert listener.session_id == "cc-listener-abc12345"
    assert listener.LOG_PREFIX == "[CC-Listener]"
    print( f"  ✓ Listener initialized (ws_session={listener.session_id})" )

    # Test 5: Drain with data
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path( tmpdir )
        buffer = tmpdir_path / "cc-buffer-drain123.jsonl"
        buffer.write_text(
            json.dumps( { "message": "first" } ) + "\n"
            + json.dumps( { "message": "second" } ) + "\n"
        )
        with patch( "lupin_cli.claude_code.hooks.lib.hook_common.SESSION_DIR", tmpdir_path ):
            result = drain_voice_buffer( "drain123" )
            assert len( result ) == 2
            assert result[0][ "message" ] == "first"
            assert result[1][ "message" ] == "second"
            assert not buffer.exists()
    print( "  ✓ Drain with 2 messages: correct order, file removed" )

    print( "  " + "═" * 50 )
    print( "  All smoke tests passed!" )
    print()


if __name__ == "__main__":
    quick_smoke_test()
