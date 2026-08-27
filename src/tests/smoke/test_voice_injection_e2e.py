#!/usr/bin/env python3
"""
Smoke test — end-to-end voice injection via UserPromptSubmit hook.

Tests the complete flow: write JSONL buffer -> pipe mock payload through
hook -> verify additionalContext output -> verify buffer consumed.

🔴 READ THIS BEFORE CHANGING THE PATCHES BELOW. What was found here on
2026-08-26 was a DEFECT, not a flaky test. The intermittent red was the symptom;
the defect was that this file had no isolation at all and was reaching into
production state every time it ran.

Everything here drives the REAL user_prompt_submit.main(), which resolves a
session id and then reads and writes that session's state. A made-up session id
is NOT isolation: resolve_stable_session_id() does not reject an unknown id, it
falls back to whatever live Claude Code session the bridge directory points at.
Measured — the id it returned belonged to a colleague's running seat, not to the
process invoking pytest. main() then called surface_dm_inbox() for that session,
which does a live GET /api/dm/list and ADVANCES that session's DM high-water
mark. Advancing it marks messages as already-shown, so a test run could consume
a real DM addressed to a real person, and nothing in the output would say so.
The two failures in twenty runs were simply the occasions when a DM happened to
land inside the window and made the damage visible.

So the fix is not "stop the red". Both e2e tests patch the session-id resolvers
on user_prompt_submit itself (not on session_bridge, where the patch never
reaches the copy main() actually calls), stub the two contributors that leave
this process, and then ASSERT the synthetic id was the one used. Keep that
assertion. It is the only thing standing between this file and a live
colleague's inbox, and it fails on every run rather than on unlucky ones.
"""
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )


def test_e2e_voice_injection():
    """Write buffer -> run hook -> verify context injection + buffer consumed."""
    from lupin_cli.claude_code.hooks import user_prompt_submit

    session_id = "e2etest1-fake-uuid-1234-567890abcdef"
    hash_part  = session_id[:8]

    with tempfile.TemporaryDirectory() as tmp_dir:
        sessions_dir = Path( tmp_dir ) / ".claude" / "sessions"
        sessions_dir.mkdir( parents=True, exist_ok=True )

        # Write JSONL buffer
        buffer_path = sessions_dir / f"cc-buffer-{hash_part}.jsonl"
        entries = [
            {
                "message"     : "show me git status",
                "priority"    : "normal",
                "job_id"      : hash_part,
                "sender_id"   : "user@example.com",
                "timestamp"   : "2026-03-06T10:00:00+00:00",
                "buffered_at" : "2026-03-06T10:00:00+00:00",
            },
            {
                "message"     : "also run the unit tests",
                "priority"    : "normal",
                "job_id"      : hash_part,
                "sender_id"   : "user@example.com",
                "timestamp"   : "2026-03-06T10:00:05+00:00",
                "buffered_at" : "2026-03-06T10:00:05+00:00",
            }
        ]
        with open( buffer_path, "w" ) as f:
            for entry in entries:
                f.write( json.dumps( entry ) + "\n" )

        assert buffer_path.exists(), "Buffer file should exist before hook"

        # Run hook
        payload  = { "session_id": session_id }
        captured = io.StringIO()

        # The voice buffer is only ONE of the four things main() concatenates into
        # additionalContext. The other three are the peer-DM inbox, the late-answer
        # catch-up, and the speakerphone rider. The first two reach OUT of this
        # process: surface_dm_inbox() does a live `GET /api/dm/list` against the
        # running server and reads/writes a high-water-mark file under the fleet
        # data root. Left unstubbed they make this test's output depend on whether
        # a colleague happened to send a DM while it ran. See the note on
        # test_e2e_empty_prompt_passthrough for the measurement.
        dm_stub     = MagicMock( return_value="" )
        answer_stub = MagicMock( return_value="" )

        with patch( "lupin_cli.claude_code.hooks.lib.hook_common.SESSION_DIR", sessions_dir ), \
             patch( "sys.stdin", io.StringIO( json.dumps( payload ) ) ), \
             patch( "sys.stdout", captured ), \
             patch( "lupin_cli.claude_code.hooks.lib.hook_common.log_payload" ), \
             patch( "lupin_cli.claude_code.hooks.user_prompt_submit.speakerphone_reminder_block",
                    return_value="" ), \
             patch( "lupin_cli.claude_code.hooks.user_prompt_submit.surface_dm_inbox", dm_stub ), \
             patch( "lupin_cli.claude_code.hooks.user_prompt_submit.surface_owed_answers", answer_stub ), \
             patch( "lupin_cli.claude_code.hooks.user_prompt_submit.resolve_stable_session_id",
                    return_value=session_id ), \
             patch( "lupin_cli.claude_code.hooks.user_prompt_submit.get_claude_session_id",
                    return_value=session_id ):
            try:
                user_prompt_submit.main()
            except SystemExit:
                pass

        # The hook must have run against the SYNTHETIC session, never the real one
        # this pytest process is nested inside. If the session-id patches above name
        # the wrong module, main() silently resolves the live session id instead and
        # every downstream read/write lands on a running colleague's state.
        assert dm_stub.call_count == 1, "main() should reconcile the DM inbox exactly once"
        assert dm_stub.call_args[ 0 ][ 0 ] == session_id, (
            f"hook ran against {dm_stub.call_args[ 0 ][ 0 ]!r}, not the synthetic "
            f"{session_id!r} — the session-id patch target is wrong"
        )

        # Parse output
        output = captured.getvalue().strip()
        assert output, "Hook should produce output"
        result = json.loads( output )

        # Verify additionalContext
        assert "hookSpecificOutput" in result, "Should have hookSpecificOutput"
        ctx = result[ "hookSpecificOutput" ][ "additionalContext" ]
        assert "[Voice]: show me git status" in ctx
        assert "[Voice]: also run the unit tests" in ctx
        assert "IMPORTANT:" in ctx

        # Verify buffer consumed
        assert not buffer_path.exists(), "Buffer file should be consumed after drain"

    print( "E2E voice injection test PASSED" )


def test_e2e_empty_prompt_passthrough():
    """
    Empty buffer -> hook emits {} -> normal prompt flow.

    Determinism fix, 2026-08-26. This test used to fail intermittently — measured
    2 failures in 20 consecutive runs, and the failure text contained REAL DMs
    from real colleagues, timestamped inside the test window. Two separate
    mistakes combined:

    1. It patched `session_bridge.get_claude_session_id`, but user_prompt_submit
       imports that name directly, so the patch never reached the copy main()
       actually calls. main() also calls `resolve_stable_session_id` FIRST, which
       was not patched at all.
    2. `resolve_stable_session_id( "nobuffe1-fake-uuid" )` does not reject an
       unknown id — measured, it returns the LIVE session id of whatever Claude
       Code process is running pytest. So the deliberately-fake id isolated
       nothing, and the hook ran against a real, running session.

    The consequence was worse than the red: `surface_dm_inbox()` then did a live
    `GET /api/dm/list` for that real session and advanced its high-water-mark
    file, which marks genuine DMs as already-shown. A test run could swallow a
    colleague's message.

    The fix patches the two resolvers on the module that actually calls them, and
    stubs the two contributors that reach outside this process. The assertions
    below check the isolation directly instead of hoping no DM arrives.
    """
    from lupin_cli.claude_code.hooks import user_prompt_submit

    session_id = "nobuffe1-fake-uuid"
    captured   = io.StringIO()

    dm_stub     = MagicMock( return_value="" )
    answer_stub = MagicMock( return_value="" )

    with tempfile.TemporaryDirectory() as tmp_dir:
        sessions_dir = Path( tmp_dir ) / ".claude" / "sessions"
        sessions_dir.mkdir( parents=True, exist_ok=True )

        payload = { "session_id": session_id }

        with patch( "lupin_cli.claude_code.hooks.lib.hook_common.SESSION_DIR", sessions_dir ), \
             patch( "sys.stdin", io.StringIO( json.dumps( payload ) ) ), \
             patch( "sys.stdout", captured ), \
             patch( "lupin_cli.claude_code.hooks.lib.hook_common.log_payload" ), \
             patch( "lupin_cli.claude_code.hooks.user_prompt_submit.speakerphone_reminder_block",
                    return_value="" ), \
             patch( "lupin_cli.claude_code.hooks.user_prompt_submit.surface_dm_inbox", dm_stub ), \
             patch( "lupin_cli.claude_code.hooks.user_prompt_submit.surface_owed_answers", answer_stub ), \
             patch( "lupin_cli.claude_code.hooks.user_prompt_submit.resolve_stable_session_id",
                    return_value=session_id ), \
             patch( "lupin_cli.claude_code.hooks.user_prompt_submit.get_claude_session_id",
                    return_value=session_id ):
            try:
                user_prompt_submit.main()
            except SystemExit:
                pass

    # The isolation guard. This is what makes the test deterministic: it asserts
    # the hook ran on the synthetic session rather than waiting to see whether a
    # real DM leaked into the output. Point either resolver patch at the wrong
    # module and this fails on every run, not on unlucky ones.
    assert dm_stub.call_count == 1, "main() should reconcile the DM inbox exactly once"
    assert dm_stub.call_args[ 0 ][ 0 ] == session_id, (
        f"hook ran against {dm_stub.call_args[ 0 ][ 0 ]!r}, not the synthetic "
        f"{session_id!r} — the session-id patch target is wrong, so this test was "
        f"reading and mutating a live session's DM inbox"
    )
    assert answer_stub.call_args[ 0 ][ 0 ] == session_id

    result = json.loads( captured.getvalue().strip() )
    assert result == {}, f"Expected empty dict, got: {result}"

    print( "E2E empty prompt passthrough test PASSED" )


def test_listener_tmux_inject_mocked():
    """Listener injects message text via tmux (literal + Enter, mocked subprocess)."""
    from lupin_cli.claude_code.hooks.lib.cc_notification_listener import CCNotificationListener

    listener = CCNotificationListener.__new__( CCNotificationListener )
    listener.session_id_hash   = "abc12345"
    listener._tmux_session_arg = "test-project"
    listener._tmux_session     = None
    listener.log_file_path     = None
    listener._log_file         = None
    listener._centralized_log  = None
    listener.LOG_PREFIX        = "[CC-Listener]"
    listener.verbose           = False
    listener.debug             = False

    with patch( "subprocess.run" ) as mock_run, \
         patch( "time.sleep" ) as mock_sleep:
        listener._inject_via_tmux( "run the tests", wrap=False )

    # Verify two subprocess calls: literal text then Enter
    assert mock_run.call_count == 2
    mock_run.assert_any_call(
        [ "tmux", "send-keys", "-t", "test-project", "-l", "run the tests" ],
        capture_output=True, timeout=2
    )
    mock_run.assert_any_call(
        [ "tmux", "send-keys", "-t", "test-project", "Enter" ],
        capture_output=True, timeout=2
    )
    mock_sleep.assert_called_once_with( 0.25 )

    print( "Listener tmux inject test PASSED" )


if __name__ == "__main__":
    test_e2e_voice_injection()
    test_e2e_empty_prompt_passthrough()
    test_listener_tmux_inject_mocked()
    print( "\nAll voice injection E2E smoke tests PASSED" )
