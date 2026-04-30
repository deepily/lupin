"""
Unit tests for Phase 4 Stop-hook auto-narrate logic + bridge dedup helpers.

Per src/rnd/v0.1.7/2026.04.30-conv-mode-three-layer-enforcement/01-design.md §Phase 4.

Coverage:
- `_read_last_assistant_message`: missing file, empty file, malformed JSON
  lines skipped, multi-message → last wins, no assistant → None.
- `_turn_has_notify_call`: ToolUseBlock with mcp__cosa-voice__notify name
  present, absent, malformed content shape.
- `_extract_narratable_text`: concatenates text blocks, strips fenced code,
  empty content → empty.
- `_try_auto_narrate`: skip on no transcript_path, no assistant, claude
  self-narrated, dedup match; fires send_tts + stamps turn id when valid.
- `get_last_autonarrated_turn_id` / `set_last_autonarrated_turn_id` round-trip
  + per-session isolation.
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ── _read_last_assistant_message ──────────────────────────────────────────────

class TestReadLastAssistantMessage:

    def test_missing_file_returns_none( self ):
        from lupin_cli.claude_code.hooks.stop import _read_last_assistant_message
        assert _read_last_assistant_message( "/nonexistent/path.jsonl" ) is None

    def test_empty_path_returns_none( self ):
        from lupin_cli.claude_code.hooks.stop import _read_last_assistant_message
        assert _read_last_assistant_message( "" ) is None

    def test_empty_file_returns_none( self, tmp_path ):
        from lupin_cli.claude_code.hooks.stop import _read_last_assistant_message
        f = tmp_path / "empty.jsonl"
        f.write_text( "" )
        assert _read_last_assistant_message( str( f ) ) is None

    def test_no_assistant_messages_returns_none( self, tmp_path ):
        from lupin_cli.claude_code.hooks.stop import _read_last_assistant_message
        f = tmp_path / "user_only.jsonl"
        f.write_text( json.dumps( { "type": "user", "content": "hi" } ) + "\n" )
        assert _read_last_assistant_message( str( f ) ) is None

    def test_malformed_lines_skipped( self, tmp_path ):
        from lupin_cli.claude_code.hooks.stop import _read_last_assistant_message
        f = tmp_path / "mixed.jsonl"
        lines = [
            "not valid json",
            json.dumps( { "type": "assistant", "uuid": "msg1", "message": { "content": [ ] } } ),
            "{also-malformed}",
        ]
        f.write_text( "\n".join( lines ) + "\n" )
        result = _read_last_assistant_message( str( f ) )
        assert result is not None
        assert result.get( "uuid" ) == "msg1"

    def test_multiple_assistants_returns_last( self, tmp_path ):
        from lupin_cli.claude_code.hooks.stop import _read_last_assistant_message
        f = tmp_path / "multi.jsonl"
        lines = [
            json.dumps( { "type": "assistant", "uuid": "msg1", "message": { "content": [ ] } } ),
            json.dumps( { "type": "user", "content": "next" } ),
            json.dumps( { "type": "assistant", "uuid": "msg2", "message": { "content": [ ] } } ),
            json.dumps( { "type": "assistant", "uuid": "msg3", "message": { "content": [ ] } } ),
        ]
        f.write_text( "\n".join( lines ) + "\n" )
        result = _read_last_assistant_message( str( f ) )
        assert result.get( "uuid" ) == "msg3"


# ── _turn_has_notify_call ─────────────────────────────────────────────────────

class TestTurnHasNotifyCall:

    def test_returns_true_with_notify_tool_use( self ):
        from lupin_cli.claude_code.hooks.stop import _turn_has_notify_call
        msg = {
            "message": {
                "content": [
                    { "type": "text", "text": "Hello" },
                    { "type": "tool_use", "name": "mcp__cosa-voice__notify", "input": { } },
                ]
            }
        }
        assert _turn_has_notify_call( msg ) is True

    def test_returns_false_with_other_tool_use( self ):
        from lupin_cli.claude_code.hooks.stop import _turn_has_notify_call
        msg = {
            "message": {
                "content": [
                    { "type": "text", "text": "Hello" },
                    { "type": "tool_use", "name": "Bash", "input": { "command": "ls" } },
                ]
            }
        }
        assert _turn_has_notify_call( msg ) is False

    def test_returns_false_with_no_content( self ):
        from lupin_cli.claude_code.hooks.stop import _turn_has_notify_call
        assert _turn_has_notify_call( { } ) is False
        assert _turn_has_notify_call( { "message": { } } ) is False
        assert _turn_has_notify_call( { "message": { "content": [ ] } } ) is False

    def test_returns_false_with_text_only( self ):
        from lupin_cli.claude_code.hooks.stop import _turn_has_notify_call
        msg = {
            "message": {
                "content": [
                    { "type": "text", "text": "Just text" },
                ]
            }
        }
        assert _turn_has_notify_call( msg ) is False


# ── _extract_narratable_text ──────────────────────────────────────────────────

class TestExtractNarratableText:

    def test_concatenates_text_blocks( self ):
        from lupin_cli.claude_code.hooks.stop import _extract_narratable_text
        msg = {
            "message": {
                "content": [
                    { "type": "text", "text": "First sentence." },
                    { "type": "tool_use", "name": "Bash", "input": { "command": "ls" } },
                    { "type": "text", "text": "Second sentence." },
                ]
            }
        }
        result = _extract_narratable_text( msg )
        assert "First sentence." in result
        assert "Second sentence." in result
        # Tool-use block should NOT be included
        assert "Bash" not in result

    def test_strips_fenced_code( self ):
        from lupin_cli.claude_code.hooks.stop import _extract_narratable_text
        msg = {
            "message": {
                "content": [
                    { "type": "text", "text": "Result:\n```python\nx=1\n```\nDone." },
                ]
            }
        }
        result = _extract_narratable_text( msg )
        assert "x=1" not in result
        assert "Done." in result

    def test_empty_content_returns_empty( self ):
        from lupin_cli.claude_code.hooks.stop import _extract_narratable_text
        assert _extract_narratable_text( { "message": { "content": [ ] } } ) == ""
        assert _extract_narratable_text( { } ) == ""


# ── _try_auto_narrate ─────────────────────────────────────────────────────────

class TestTryAutoNarrate:

    def test_skips_when_no_transcript_path_in_payload_or_bridge( self, tmp_path ):
        from lupin_cli.claude_code.hooks import stop

        with patch.object( stop, "get_session_metadata", return_value={ } ), \
             patch.object( stop, "send_tts" ) as mock_tts:
            stop._try_auto_narrate( "abc12345", { } )
            mock_tts.assert_not_called()

    def test_skips_when_transcript_missing( self, tmp_path ):
        from lupin_cli.claude_code.hooks import stop

        with patch.object( stop, "send_tts" ) as mock_tts:
            stop._try_auto_narrate(
                "abc12345",
                { "transcript_path": "/nonexistent/x.jsonl" }
            )
            mock_tts.assert_not_called()

    def test_skips_when_claude_self_narrated( self, tmp_path ):
        from lupin_cli.claude_code.hooks import stop

        f = tmp_path / "transcript.jsonl"
        f.write_text( json.dumps( {
            "type": "assistant",
            "uuid": "msg-self-narrated",
            "message": {
                "content": [
                    { "type": "text", "text": "Hello" },
                    { "type": "tool_use", "name": "mcp__cosa-voice__notify", "input": { } },
                ]
            }
        } ) + "\n" )

        with patch.object( stop, "send_tts" ) as mock_tts, \
             patch.object( stop, "set_last_autonarrated_turn_id" ) as mock_stamp:
            stop._try_auto_narrate(
                "abc12345",
                { "transcript_path": str( f ) }
            )
            mock_tts.assert_not_called()
            mock_stamp.assert_not_called()

    def test_skips_when_already_auto_narrated_dedup( self, tmp_path ):
        from lupin_cli.claude_code.hooks import stop

        f = tmp_path / "transcript.jsonl"
        f.write_text( json.dumps( {
            "type": "assistant",
            "uuid": "turn-42",
            "message": {
                "content": [
                    { "type": "text", "text": "Hello" },
                ]
            }
        } ) + "\n" )

        with patch.object( stop, "get_last_autonarrated_turn_id", return_value="turn-42" ), \
             patch.object( stop, "send_tts" ) as mock_tts, \
             patch.object( stop, "set_last_autonarrated_turn_id" ) as mock_stamp:
            stop._try_auto_narrate(
                "abc12345",
                { "transcript_path": str( f ) }
            )
            mock_tts.assert_not_called()
            mock_stamp.assert_not_called()

    def test_fires_send_tts_when_valid( self, tmp_path ):
        from lupin_cli.claude_code.hooks import stop

        f = tmp_path / "transcript.jsonl"
        f.write_text( json.dumps( {
            "type": "assistant",
            "uuid": "turn-100",
            "message": {
                "content": [
                    { "type": "text", "text": "Console-only response." },
                ]
            }
        } ) + "\n" )

        with patch.object( stop, "get_last_autonarrated_turn_id", return_value=None ), \
             patch.object( stop, "send_tts" ) as mock_tts, \
             patch.object( stop, "set_last_autonarrated_turn_id" ) as mock_stamp:
            stop._try_auto_narrate(
                "abc12345",
                { "transcript_path": str( f ) }
            )

            # send_tts called once with conv-mode params
            mock_tts.assert_called_once()
            args, kwargs = mock_tts.call_args
            assert kwargs.get( "priority" ) == "high"
            assert kwargs.get( "suppress_ding" ) is True
            # Narration text is positional arg 0
            assert "Console-only response." in args[ 0 ]

            # Turn id stamped
            mock_stamp.assert_called_once_with( "abc12345", "turn-100" )

    def test_skips_when_no_narratable_text( self, tmp_path ):
        from lupin_cli.claude_code.hooks import stop

        # Assistant message with only tool-use blocks (no text)
        f = tmp_path / "transcript.jsonl"
        f.write_text( json.dumps( {
            "type": "assistant",
            "uuid": "turn-nottext",
            "message": {
                "content": [
                    { "type": "tool_use", "name": "Bash", "input": { "command": "ls" } },
                ]
            }
        } ) + "\n" )

        with patch.object( stop, "get_last_autonarrated_turn_id", return_value=None ), \
             patch.object( stop, "send_tts" ) as mock_tts:
            stop._try_auto_narrate(
                "abc12345",
                { "transcript_path": str( f ) }
            )
            mock_tts.assert_not_called()


# ── bridge round-trip for last_autonarrated_turn_id ───────────────────────────

class TestLastAutonarratedTurnIdBridge:

    def test_round_trip( self, tmp_path, monkeypatch ):
        from lupin_cli.claude_code.hooks.lib import session_bridge

        # Bridge file structure: cc-{PPID}.json with a session_id field
        bridge_path = tmp_path / "cc-12345.json"
        bridge_path.write_text( json.dumps( {
            "session_id"                : "abc12345-uuid-here",
            "conversation_mode_active" : True
        } ) )

        # Patch the SESSION_DIR to our tmp_path so find_session_path_by_id sees it.
        # Also disable host-PID gating so the cc-{PID}.json filename's PID isn't
        # checked for liveness (12345 likely isn't a real process).
        monkeypatch.setattr( session_bridge, "SESSION_DIR", tmp_path )
        monkeypatch.setattr( session_bridge, "_can_trust_host_pids", lambda: False )

        # Initially absent
        assert session_bridge.get_last_autonarrated_turn_id( "abc12345" ) is None

        # Set + read back
        ok = session_bridge.set_last_autonarrated_turn_id( "abc12345", "turn-xyz" )
        assert ok is True
        assert session_bridge.get_last_autonarrated_turn_id( "abc12345" ) == "turn-xyz"

        # Other fields preserved
        with open( bridge_path ) as fp:
            data = json.load( fp )
        assert data.get( "conversation_mode_active" ) is True
        assert data.get( "session_id" ) == "abc12345-uuid-here"

    def test_set_returns_false_on_missing_bridge( self, tmp_path, monkeypatch ):
        from lupin_cli.claude_code.hooks.lib import session_bridge
        monkeypatch.setattr( session_bridge, "SESSION_DIR", tmp_path )
        monkeypatch.setattr( session_bridge, "_can_trust_host_pids", lambda: False )
        # No bridge file exists
        assert session_bridge.set_last_autonarrated_turn_id( "missing-sid", "turn-x" ) is False

    def test_get_returns_none_on_missing_bridge( self, tmp_path, monkeypatch ):
        from lupin_cli.claude_code.hooks.lib import session_bridge
        monkeypatch.setattr( session_bridge, "SESSION_DIR", tmp_path )
        monkeypatch.setattr( session_bridge, "_can_trust_host_pids", lambda: False )
        assert session_bridge.get_last_autonarrated_turn_id( "missing-sid" ) is None

    def test_per_session_isolation( self, tmp_path, monkeypatch ):
        from lupin_cli.claude_code.hooks.lib import session_bridge
        monkeypatch.setattr( session_bridge, "SESSION_DIR", tmp_path )
        monkeypatch.setattr( session_bridge, "_can_trust_host_pids", lambda: False )

        # Two bridges
        ( tmp_path / "cc-1.json" ).write_text( json.dumps( { "session_id": "sess-A" } ) )
        ( tmp_path / "cc-2.json" ).write_text( json.dumps( { "session_id": "sess-B" } ) )

        session_bridge.set_last_autonarrated_turn_id( "sess-A", "turn-a1" )
        session_bridge.set_last_autonarrated_turn_id( "sess-B", "turn-b1" )

        assert session_bridge.get_last_autonarrated_turn_id( "sess-A" ) == "turn-a1"
        assert session_bridge.get_last_autonarrated_turn_id( "sess-B" ) == "turn-b1"
