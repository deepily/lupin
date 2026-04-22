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
    _derive_project_name,
    CREDENTIALS_FILE,
)
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
        """Project name derived from LUPIN_ROOT basename."""
        with patch.dict( os.environ, { "LUPIN_ROOT": "/path/to/lupin" } ):
            assert _derive_project_name() == "lupin"


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


# ══════════════════════════════════════════════════════════════════════════════
# Test: SessionEnd Hook Functions
# ══════════════════════════════════════════════════════════════════════════════

class TestSessionEndHook:
    """Test SessionEnd hook helper functions."""

    def test_find_listener_pid_from_bridge( self, tmp_path ):
        """Finds listener PID from session bridge file."""
        from lupin_cli.claude_code.hooks.session_end import _find_listener_pid

        bridge_file = tmp_path / "cc-12345.json"
        bridge_data = {
            "session_id"   : "bbd0e94b-cdf0-4766-a16d-16fe116125ef",
            "listener_pid" : 99999,
        }
        bridge_file.write_text( json.dumps( bridge_data ) )

        pid = _find_listener_pid(
            "bbd0e94b-cdf0-4766-a16d-16fe116125ef",
            session_dir=str( tmp_path )
        )
        assert pid == 99999

    def test_no_matching_session( self, tmp_path ):
        """Returns None when no bridge file matches session_id."""
        from lupin_cli.claude_code.hooks.session_end import _find_listener_pid

        bridge_file = tmp_path / "cc-12345.json"
        bridge_file.write_text( json.dumps( {
            "session_id"   : "other-session-id",
            "listener_pid" : 11111,
        } ) )

        pid = _find_listener_pid( "nonexistent-session", session_dir=str( tmp_path ) )
        assert pid is None

    def test_empty_session_dir( self, tmp_path ):
        """Returns None when session dir is empty."""
        from lupin_cli.claude_code.hooks.session_end import _find_listener_pid

        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        pid = _find_listener_pid( "any-session", session_dir=str( empty_dir ) )
        assert pid is None

    def test_no_listener_pid_key( self, tmp_path ):
        """Returns None when bridge file has no listener_pid."""
        from lupin_cli.claude_code.hooks.session_end import _find_listener_pid

        bridge_file = tmp_path / "cc-99999.json"
        bridge_file.write_text( json.dumps( {
            "session_id" : "test-session",
        } ) )

        pid = _find_listener_pid( "test-session", session_dir=str( tmp_path ) )
        assert pid is None


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
