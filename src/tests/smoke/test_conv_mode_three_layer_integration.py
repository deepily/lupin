"""
Cross-layer integration smoke test for the conv-mode three-layer
enforcement plan (Phase 5).

Exercises the three layers in sequence via mocks to verify they compose
correctly:
  - Layer 1 (conv_mode_wrap): wraps voice text when bridge active
  - Layer 2 (_notify_impl bidirectional gate): forces conv-mode params
    when active, audible cue when displaced
  - Layer 3 (Stop-hook auto-narrate): synthesizes notify() if turn ended
    silent

Per src/rnd/v0.1.7/2026.04.30-conv-mode-three-layer-enforcement/01-design.md
Phase 5.

These tests are mock-driven (no live server) so they're :7999-friendly
under the AI-discretionary venue rule. The full multi-session live E2E
is Phase 6 (user-gated).
"""

import json
from unittest.mock import patch, MagicMock

import pytest


# ── End-to-end happy path: conv mode on, voice → wrap → notify → no auto-narrate

class TestConvModeOnHappyPath:
    """
    When conv mode is active and Claude self-narrates via notify():
      - Layer 1 wraps the voice message
      - Layer 2 forces conv-mode params
      - Layer 3 detects self-narration and skips
    """

    @patch( "lupin_cli.claude_code.hooks.lib.session_bridge.get_conversation_mode" )
    def test_layer1_wraps_voice_message_when_active( self, mock_get ):
        from lupin_cli.claude_code.hooks.lib.hook_common import conv_mode_wrap

        mock_get.return_value = True
        wrapped = conv_mode_wrap(
            "What is the build status?",
            source     = "voice",
            session_id = "abc12345"
        )
        # Voice envelope present
        assert '<voice-message from-distance="true"' in wrapped
        assert "What is the build status?" in wrapped
        # System reminder appended
        assert "<system-reminder>" in wrapped
        assert "Conversation mode is active" in wrapped

    def test_layer2_gate_forces_conv_mode_params_when_active( self ):
        from lupin_mcp.cosa_voice_mcp import _notify_impl

        captured = { }

        def _fake_notify( request, debug=False ):
            captured[ "request" ] = request
            r = MagicMock()
            r.success = True
            r.status  = "ok"
            return r

        with patch( "lupin_mcp.cosa_voice_mcp.notify_user_async", side_effect=_fake_notify ), \
             patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata" ) as mock_meta, \
             patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id" ) as mock_sender, \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.get_conversation_mode" ) as mock_get:

            mock_meta.return_value   = { "stable_session_id": "abc12345" }
            mock_sender.return_value = "claude.code@lupin.deepily.ai#abc12345"
            mock_get.return_value    = True

            _notify_impl(
                message       = "Build complete.\n```python\nprint(1)\n```",
                priority      = "low",
                suppress_ding = False
            )

        req = captured[ "request" ]
        assert req.priority.value == "high"
        assert req.suppress_ding == True
        # Code block stripped
        assert "print(1)" not in req.message
        # Text content preserved
        assert "Build complete." in req.message

    def test_layer3_skips_when_turn_has_notify_call( self, tmp_path ):
        from lupin_cli.claude_code.hooks import stop

        f = tmp_path / "transcript.jsonl"
        f.write_text( json.dumps( {
            "type": "assistant",
            "uuid": "turn-narrated",
            "message": {
                "content": [
                    { "type": "text",      "text": "All done." },
                    { "type": "tool_use",  "name": "mcp__cosa-voice__notify", "input": { } },
                ]
            }
        } ) + "\n" )

        with patch.object( stop, "send_tts" ) as mock_tts, \
             patch.object( stop, "set_last_autonarrated_turn_id" ) as mock_stamp:
            stop._try_auto_narrate(
                "abc12345",
                { "transcript_path": str( f ) }
            )
            # Layer 3 detected self-narration; auto-narrate skipped
            mock_tts.assert_not_called()
            mock_stamp.assert_not_called()


# ── Failure-mode B: console-only turn, Layer 3 catches it

class TestConsoleOnlySalvage:
    """
    When conv mode is active but Claude wrote a console-only response
    (didn't call notify), Layer 3 must synthesize a notify().
    """

    def test_layer3_synthesizes_notify_with_conv_mode_params( self, tmp_path ):
        from lupin_cli.claude_code.hooks import stop

        f = tmp_path / "transcript.jsonl"
        f.write_text( json.dumps( {
            "type": "assistant",
            "uuid": "turn-silent",
            "message": {
                "content": [
                    { "type": "text", "text": "I think we should refactor the database layer next." },
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

            mock_tts.assert_called_once()
            args, kwargs = mock_tts.call_args
            assert kwargs.get( "priority" ) == "high"
            assert kwargs.get( "suppress_ding" ) is True
            assert "refactor the database layer" in args[ 0 ]
            mock_stamp.assert_called_once_with( "abc12345", "turn-silent" )


# ── Cross-talk symptom (the ORIGINAL bug): Layer 2 cue intervention

class TestCrossTalkCue:
    """
    When a CC session that THINKS it's in conv mode (cached belief) calls
    notify() with conv-mode params after being displaced, Layer 2's
    bridge=false branch inverts suppress_ding so the user hears an
    audible cue. This is the core fix for the originally-reported symptom.
    """

    def test_displaced_session_gets_audible_ding( self ):
        from lupin_mcp.cosa_voice_mcp import _notify_impl

        captured = { }

        def _fake_notify( request, debug=False ):
            captured[ "request" ] = request
            r = MagicMock()
            r.success = True
            r.status  = "ok"
            return r

        with patch( "lupin_mcp.cosa_voice_mcp.notify_user_async", side_effect=_fake_notify ), \
             patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata" ) as mock_meta, \
             patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id" ) as mock_sender, \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.get_conversation_mode" ) as mock_get:

            mock_meta.return_value   = { "stable_session_id": "displaced-sid" }
            mock_sender.return_value = "claude.code@lupin.deepily.ai#displaced-sid"
            mock_get.return_value    = False   # Bridge says: NOT in conv mode

            # Claude (in displaced session) still cached active=True from session start
            # and calls notify with conv-mode shape:
            _notify_impl(
                message       = "Continuing the refactor as you asked...",
                priority      = "high",
                suppress_ding = True
            )

        req = captured[ "request" ]
        # Cue: ding turned ON despite caller's suppress_ding=True
        assert req.suppress_ding == False
        # Priority pass-through (legitimate alerts survive)
        assert req.priority.value == "high"
