"""
Stop-hook arms no earlier test reached.

Covers the idle-waiter spawn, the muted-stop beacon failure and the auto-narration failures.
Popen, the notifier and the TTS call are stand-ins, so nothing is spawned or sent.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from lupin_cli.claude_code.hooks import stop


class _FakeProc:
    pid = 31337


@pytest.fixture
def arm( monkeypatch, tmp_path ):
    """Stub what `_arm_idle_waiter` consults; return the Popen stand-in and the log recorder."""
    monkeypatch.setenv( "LUPIN_HOOK_SESSIONS_DIR", str( tmp_path ) )
    monkeypatch.delenv( "LUPIN_IDLE_WAITER_TEST_SLEEP_SECS", raising=False )
    monkeypatch.setattr( stop, "_shared_summarize_task", lambda msg: "gist" )
    monkeypatch.setattr( stop, "get_idle_detection", lambda sid: { "backoff_index": 2 } )
    monkeypatch.setattr( stop, "get_session_metadata", lambda: { "cc_pid": 12345 } )
    monkeypatch.setattr( stop, "kill_idle_waiter", lambda sid: None )
    monkeypatch.setattr( stop, "set_idle_detection_field", lambda sid, **kw: None )
    log   = MagicMock()
    monkeypatch.setattr( stop, "log_to_stream", log )
    popen = MagicMock( return_value=_FakeProc() )
    monkeypatch.setattr( "subprocess.Popen", popen )
    return popen, log


class TestArmIdleWaiter:

    def test_the_test_sleep_env_var_is_forwarded_as_a_flag( self, arm, monkeypatch ):
        popen, _ = arm
        monkeypatch.setenv( "LUPIN_IDLE_WAITER_TEST_SLEEP_SECS", "7" )
        stop._arm_idle_waiter( "deadbeef-session", "last", "/some/cwd" )
        cmd = popen.call_args.args[ 0 ]
        assert cmd[ cmd.index( "--sleep-secs" ) + 1 ] == "7"
        assert cmd[ cmd.index( "--backoff-index" ) + 1 ] == "2"

    def test_without_the_env_var_no_sleep_flag_is_passed( self, arm ):
        popen, _ = arm
        stop._arm_idle_waiter( "deadbeef-session", "last", "/some/cwd" )
        assert "--sleep-secs" not in popen.call_args.args[ 0 ]

    def test_a_bare_pythonpath_gets_the_source_path_prepended( self, arm, monkeypatch ):
        popen, _ = arm
        monkeypatch.delenv( "PYTHONPATH", raising=False )
        stop._arm_idle_waiter( "deadbeef-session", "last", "/some/cwd" )
        assert popen.call_args.kwargs[ "env" ][ "PYTHONPATH" ] == stop._src_path + ":"

    def test_the_cwd_is_handed_to_the_waiter_only_when_there_is_one( self, arm, monkeypatch ):
        popen, _ = arm
        monkeypatch.delenv( "CC_HOOK_CWD", raising=False )
        stop._arm_idle_waiter( "deadbeef-session", "last", "/some/cwd" )
        assert popen.call_args.kwargs[ "env" ][ "CC_HOOK_CWD" ] == "/some/cwd"
        popen.reset_mock()
        stop._arm_idle_waiter( "deadbeef-session", "last", None )
        assert "CC_HOOK_CWD" not in popen.call_args.kwargs[ "env" ]

    def test_a_failed_spawn_returns_none_and_logs_the_reason( self, arm ):
        popen, log = arm
        popen.side_effect = OSError( "no fork" )
        assert stop._arm_idle_waiter( "deadbeef-session", "last", "/some/cwd" ) is None
        extra = log.call_args.kwargs[ "extra" ]
        assert ( extra[ "phase" ], extra[ "error" ] ) == ( "idle_waiter_spawn_failed", "no fork" )

    def test_a_good_spawn_returns_the_pid_and_logs_it_armed( self, arm ):
        _, log = arm
        assert stop._arm_idle_waiter( "deadbeef-session", "last", "/some/cwd" ) == _FakeProc.pid
        extra = log.call_args.kwargs[ "extra" ]
        assert ( extra[ "phase" ], extra[ "waiter_pid" ], extra[ "backoff_index" ] ) == ( "idle_waiter_armed", 31337, 2 )


class TestAnnounceMuted:

    def test_a_notifier_failure_is_logged_not_raised( self ):
        with patch.object( stop, "build_sender_id_for_cc", return_value="claude.code@lupin.deepily.ai#47a835e8" ), \
             patch.object( stop, "notify_user_async", side_effect=RuntimeError( "server down" ) ), \
             patch.object( stop, "log_to_stream" ) as log:
            stop._announce_muted( "abc12345", "Mr. Radio", "stand by" )
        extra = log.call_args.kwargs[ "extra" ]
        assert ( extra[ "phase" ], extra[ "session_id" ], extra[ "error" ] ) == ( "muted_announce_error", "abc12345", "server down" )

    def test_the_beacon_names_the_persona_and_carries_the_mute_text_verbatim( self ):
        sent = [ ]
        with patch.object( stop, "build_sender_id_for_cc", return_value="claude.code@lupin.deepily.ai#47a835e8" ), \
             patch.object( stop, "notify_user_async", side_effect=sent.append ):
            stop._announce_muted( "abc12345", "Mr. Radio", "stand by" )
        assert sent[ 0 ].message == "Mr. Radio stopped — pokes muted, default message injected."
        assert sent[ 0 ].abstract.endswith( "stand by" )


def _transcript( tmp_path, **entry_extra ):
    f = tmp_path / "t.jsonl"
    f.write_text( json.dumps( { "type": "assistant",
                                "message": { "content": [ { "type": "text", "text": "Console-only reply." } ] },
                                **entry_extra } ) + "\n" )
    return str( f )


class TestAutoNarrateArms:

    def test_an_unreadable_bridge_reads_as_no_transcript_and_nothing_is_spoken( self ):
        with patch.object( stop, "get_session_metadata", side_effect=RuntimeError( "bridge gone" ) ), \
             patch.object( stop, "send_tts" ) as tts:
            stop._try_auto_narrate( "abc12345", { } )
        tts.assert_not_called()

    def test_a_turn_with_no_id_is_spoken_but_cannot_be_stamped( self, tmp_path ):
        with patch.object( stop, "get_last_autonarrated_turn_id", return_value=None ), \
             patch.object( stop, "send_tts" ) as tts, \
             patch.object( stop, "set_last_autonarrated_turn_id" ) as stamp:
            stop._try_auto_narrate( "abc12345", { "transcript_path": _transcript( tmp_path ) } )
        tts.assert_called_once()
        stamp.assert_not_called()

    def test_a_tts_failure_is_logged_and_the_turn_is_not_stamped( self, tmp_path ):
        with patch.object( stop, "get_last_autonarrated_turn_id", return_value=None ), \
             patch.object( stop, "send_tts", side_effect=RuntimeError( "tts down" ) ), \
             patch.object( stop, "set_last_autonarrated_turn_id" ) as stamp, \
             patch.object( stop, "log_to_stream" ) as log:
            stop._try_auto_narrate( "abc12345", { "transcript_path": _transcript( tmp_path, uuid="turn-9" ) } )
        stamp.assert_not_called()
        extra = log.call_args.kwargs[ "extra" ]
        assert ( extra[ "phase" ], extra[ "error" ] ) == ( "auto_narrate_error", "tts down" )
