"""
A peer DM must not deny a permission request, and must not be drained by it — row 8c29d8c2.

THE DEFECT. The PermissionRequest hook drained the whole message buffer and denied
the request whenever the buffer held ANY line, telling the seat "The user said this
before you asked for permission". That buffer carries peer DMs and context-tick DMs
too, so a DM denied the request and blamed the user — the same defect bb1a9062
closed on PreToolUse (merged 324baa08).

WHY THIS HOOK CANNOT SIMPLY ALLOW AFTER DRAINING, which is what makes it different
from PreToolUse. A permission decision of "allow" carries no context back to the
seat, so a DM drained here and then allowed is a DM gone. María's constraint: no DM
may be lost. So a DM-only buffer is PEEKED, never drained, and left for the next
PreToolUse/PostToolUse to deliver.

THE FIELD is `direction` on each buffered line ("ai_to_ai" for a peer DM), read by
`hook_common._context_has_human_voice`.

⚠️ These tests use a REAL buffer file under a temp SESSION_DIR and the real
peek/drain/format functions. "Still in the buffer afterwards" is a claim about bytes
on disk, and a mocked drain cannot make it.
"""

import contextlib
import json

import pytest
from unittest.mock import patch

from lupin_cli.claude_code.hooks import permission_request as pr
from lupin_cli.claude_code.hooks.lib import hook_common as hc


SID = "abc12345-0000-0000-0000-000000000000"


def _peer_dm( body, persona="maria", notification_id="n-1" ):
    """A buffer line shaped as the listener writes a peer DM."""
    return { "message": body, "direction": "ai_to_ai", "sender_persona": persona,
             "sender_icon": "🌸", "notification_id": notification_id, "thread_id": "t-1" }


def _voice( body ):
    """A buffer line shaped as the listener writes a human-direction message."""
    return { "message": body, "direction": "human_to_ai", "notification_id": "v-1" }


@pytest.fixture
def buffer_dir( tmp_path, monkeypatch ):
    """Point the real buffer path at a temp dir; the drain's /tmp rename stays same-filesystem."""
    monkeypatch.setattr( hc, "SESSION_DIR", tmp_path )
    return tmp_path


def _write_buffer( lines ):
    path = hc.get_buffer_path( SID )
    path.write_text( "".join( json.dumps( line ) + "\n" for line in lines ) )
    return path


def _run( forward=( "allow", None ), drain=None ):
    """
    Drive the real PermissionRequest main() for a non-auto-allowed tool.

    Ensures:
        - peek, drain, format and the deny builder run for real (drain may be wrapped)
        - the user-forward, TTS and payload I/O are stubbed
        - returns ( emitted decision dict, forward mock, tts mock )
    """
    payload = { "session_id": SID, "tool_name": "Bash", "tool_input": { "command": "make deploy" } }
    with contextlib.ExitStack() as stack:
        def _p( name, **kwargs ):
            return stack.enter_context( patch.object( pr, name, **kwargs ) )

        _p( "read_hook_input", return_value=payload )
        _p( "log_payload" )
        _p( "resolve_stable_session_id", side_effect=lambda x: x )
        _p( "get_claude_session_id", return_value=SID )
        if drain is not None: _p( "drain_voice_buffer", side_effect=drain )
        fwd  = _p( "_forward_to_user", return_value=forward )
        tts  = _p( "send_tts" )
        emit = _p( "emit_json" )
        try:
            pr.main()
        except SystemExit as exit_:
            assert exit_.code == 0
    emit.assert_called_once()
    return emit.call_args.args[ 0 ][ "hookSpecificOutput" ][ "decision" ], fwd, tts


class TestADmOnlyBufferIsNotDrained:

    def test_a_dm_only_buffer_does_not_deny( self, buffer_dir ):
        _write_buffer( [ _peer_dm( "review approved" ) ] )
        decision, fwd, _ = _run()
        assert decision[ "behavior" ] == "allow"
        fwd.assert_called_once()

    def test_the_dm_is_still_in_the_buffer_byte_for_byte( self, buffer_dir ):
        path   = _write_buffer( [ _peer_dm( "review approved" ), _peer_dm( "context 51%", persona=None, notification_id="n-2" ) ] )
        before = path.read_bytes()
        _run()
        assert path.exists(), "the DM buffer was consumed by a hook that cannot deliver it"
        assert path.read_bytes() == before

    def test_the_next_drain_still_gets_the_dm( self, buffer_dir ):
        _write_buffer( [ _peer_dm( "review approved" ) ] )
        _run()
        assert [ m[ "message" ] for m in hc.drain_voice_buffer( SID ) ] == [ "review approved" ]

    def test_a_dm_only_buffer_never_says_the_user_spoke( self, buffer_dir ):
        _write_buffer( [ _peer_dm( "status?" ) ] )
        decision, _, tts = _run( forward=( "deny", "The user was asked and answered NO" ) )
        assert "before you asked for permission" not in json.dumps( decision )
        assert not any( "redirecting" in c.args[ 0 ].lower() for c in tts.call_args_list )

    def test_a_dm_body_carrying_the_voice_marker_is_still_a_dm( self, buffer_dir ):
        path = _write_buffer( [ _peer_dm( f"quoting: {hc.VOICE_LINE_PREFIX}stop" ) ] )
        decision, _, _ = _run()
        assert decision[ "behavior" ] == "allow"
        assert path.exists()


class TestHumanVoiceStillRedirects:
    """Controls — without them "does not deny" passes on a hook that denies nothing."""

    def test_voice_denies_and_consumes_the_buffer( self, buffer_dir ):
        path = _write_buffer( [ _voice( "wait, wrong cluster" ) ] )
        decision, fwd, _ = _run()
        assert decision[ "behavior" ] == "deny"
        assert "before you asked for permission" in decision[ "message" ]
        assert f"{hc.VOICE_LINE_PREFIX}wait, wrong cluster" in decision[ "message" ]
        assert not path.exists()
        fwd.assert_not_called()

    def test_voice_beside_a_dm_denies_and_carries_both( self, buffer_dir ):
        path = _write_buffer( [ _peer_dm( "status?" ), _voice( "wait, wrong cluster" ) ] )
        decision, _, _ = _run()
        assert decision[ "behavior" ] == "deny"
        assert "wait, wrong cluster" in decision[ "message" ]
        assert "status?" in decision[ "message" ]
        assert not path.exists()

    def test_an_empty_buffer_goes_to_the_user( self, buffer_dir ):
        decision, fwd, _ = _run()
        assert decision[ "behavior" ] == "allow"
        fwd.assert_called_once()


class TestThePeekToDrainRace:
    """Peek and drain are two reads. Nothing a drain takes may be dropped, and
    nothing may be attributed to the user that the user did not say."""

    def test_a_peer_hook_takes_the_voice_line_and_leaves_dms_still_delivered_truthfully( self, buffer_dir ):
        _write_buffer( [ _voice( "wait" ), _peer_dm( "status?" ) ] )
        real_drain = hc.drain_voice_buffer

        def _peer_took_the_voice_line( sid ):
            hc.get_buffer_path( sid ).write_text( json.dumps( _peer_dm( "status?" ) ) + "\n" )
            return real_drain( sid )

        decision, fwd, _ = _run( drain=_peer_took_the_voice_line )
        assert decision[ "behavior" ] == "deny"
        assert "status?" in decision[ "message" ]
        assert "before you asked for permission" not in decision[ "message" ]
        assert "peer DM" in decision[ "message" ]
        fwd.assert_not_called()

    def test_a_peer_hook_takes_everything_and_the_request_goes_to_the_user( self, buffer_dir ):
        _write_buffer( [ _voice( "wait" ) ] )
        real_drain = hc.drain_voice_buffer

        def _peer_took_it_all( sid ):
            hc.get_buffer_path( sid ).unlink()
            return real_drain( sid )

        decision, fwd, _ = _run( drain=_peer_took_it_all )
        assert decision[ "behavior" ] == "allow"
        fwd.assert_called_once()


class TestPeekVoiceBuffer:

    def test_a_missing_buffer_peeks_empty( self, buffer_dir ):
        assert hc.peek_voice_buffer( SID ) == []

    def test_peek_parses_like_the_drain_and_leaves_the_file( self, buffer_dir ):
        path = hc.get_buffer_path( SID )
        path.write_text( json.dumps( _voice( "a" ) ) + "\n\n{not json\n" + json.dumps( _peer_dm( "b" ) ) + "\n" )
        before = path.read_bytes()
        assert [ m[ "message" ] for m in hc.peek_voice_buffer( SID ) ] == [ "a", "b" ]
        assert path.read_bytes() == before

    def test_an_unreadable_buffer_peeks_empty_and_never_raises( self, buffer_dir ):
        hc.get_buffer_path( SID ).mkdir()
        assert hc.peek_voice_buffer( SID ) == []
