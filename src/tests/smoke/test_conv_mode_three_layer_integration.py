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

    def test_layer1_wraps_voice_message( self ):
        """
        Refreshed 2026-08-26. Two things moved under this test:

        1. `conv_mode_wrap` was renamed `speakerphone_wrap` when conversation
           mode became speakerphone, and the flag reader it patched
           (`session_bridge.get_conversation_mode`) is `get_speakerphone` now —
           the old name does not exist, so this died on AttributeError before
           asserting anything.
        2. The wrap no longer READS the flag at all. Per
           src/rnd/v0.1.9/2026.06.27-cosa-voice-rider-slim.md (Rick-approved
           2026-06-27) the rider is UNCONDITIONAL — the stored flag proved
           unreliable, so speakerphone is assumed on and only the input modality
           is dynamic. There is therefore nothing left to mock, and the old
           "Conversation mode is active" sentence is gone from the body; the
           rider now leads with a `[turn-state] input=` line.
        """
        from lupin_cli.claude_code.hooks.lib.hook_common import speakerphone_wrap

        wrapped = speakerphone_wrap(
            "What is the build status?",
            source     = "voice",
            session_id = "abc12345"
        )
        # Voice envelope present
        assert '<voice-message from-distance="true"' in wrapped
        assert "What is the build status?" in wrapped
        # System reminder appended, carrying the slim per-turn rider
        assert "<system-reminder>" in wrapped
        assert "[turn-state] input=voice(distance)" in wrapped
        assert "TTS contract ACTIVE" in wrapped

    def test_layer1_rider_is_unconditional_and_marks_typed_input( self ):
        """
        The rider fires for a non-voice source too, with no voice envelope and
        the modality reported as typed. Added 2026-08-26 alongside the rename
        above: the old test only covered the voice path because the wrap used to
        be gated on a flag, and the unconditional behaviour is the thing worth
        pinning now.
        """
        from lupin_cli.claude_code.hooks.lib.hook_common import speakerphone_wrap

        wrapped = speakerphone_wrap(
            "What is the build status?",
            source     = "terminal-typed",
            session_id = "abc12345"
        )
        assert "<voice-message"                 not in wrapped
        assert "[turn-state] input=typed"           in wrapped
        assert "TTS contract ACTIVE"                in wrapped

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
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.get_speakerphone" ) as mock_get:

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

        # `get_tts_interaction_mode` pinned to "solo" 2026-08-26. The inversion
        # became MODE-CONDITIONAL in the solo/chorus refactor (Phase 4, shipped in
        # 26898e1e, cosa_voice_mcp.py ~line 1402): it fires in SOLO only, where a
        # single session holds speakerphone and a silent TTS from a phone-mode
        # session is a leak symptom. In CHORUS, siblings legitimately notify with
        # suppress_ding=True, so the value passes through untouched. This test read
        # the AMBIENT config, which is chorus on this box, so it asserted the solo
        # behaviour while exercising the chorus path and failed on
        # `assert True == False`. The mode is now stated by the test rather than
        # inherited from whatever the box happens to be set to.
        with patch( "lupin_mcp.cosa_voice_mcp.notify_user_async", side_effect=_fake_notify ), \
             patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata" ) as mock_meta, \
             patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id" ) as mock_sender, \
             patch( "cosa.utils.util.get_tts_interaction_mode", return_value="solo" ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.get_speakerphone" ) as mock_get:

            mock_meta.return_value   = { "stable_session_id": "displaced-sid" }
            mock_sender.return_value = "claude.code@lupin.deepily.ai#displaced-sid"
            mock_get.return_value    = False   # Bridge says: speakerphone OFF

            # Claude (in displaced session) still cached active=True from session start
            # and calls notify with speakerphone shape:
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

    def test_chorus_passes_suppress_ding_through_untouched( self ):
        """
        The chorus half of the same branch, added 2026-08-26. In chorus mode a
        sibling session calling notify with suppress_ding=True is normal, not a
        leak, so the inversion must NOT fire. Without this, pinning the test above
        to solo would leave the mode check itself unasserted — the bug that let the
        original test pass for months on a box that was solo and then fail on one
        that is chorus.
        """
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
             patch( "cosa.utils.util.get_tts_interaction_mode", return_value="chorus" ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.get_speakerphone" ) as mock_get:

            mock_meta.return_value   = { "stable_session_id": "displaced-sid" }
            mock_sender.return_value = "claude.code@lupin.deepily.ai#displaced-sid"
            mock_get.return_value    = False

            _notify_impl(
                message       = "Continuing the refactor as you asked...",
                priority      = "high",
                suppress_ding = True
            )

        req = captured[ "request" ]
        assert req.suppress_ding == True, "chorus must not invert the caller's suppress_ding"
        assert req.priority.value == "high"
