"""
The "MCP VALIDATION FAILED" alert is sent at most once per project per 6 hours.

Venue: :7999-eligible. `notify_user_async` is stubbed and the state file lives in tmp_path, so no
socket is opened and the real ~/.lupin is never touched.
"""
import json
import os
from types import SimpleNamespace

import pytest

import lupin_mcp.cosa_voice_mcp as cv
import lupin_mcp.validation_alert_throttle as throttle

HOUR = 3600


@pytest.fixture
def state( monkeypatch, tmp_path ):
    path = tmp_path / ".lupin" / "mcp-validation-alerts.json"      # parent does not exist yet
    monkeypatch.setattr( throttle, "STATE_PATH", path )
    return path


@pytest.fixture
def clock( monkeypatch ):
    """A fake clock: clock.now moves only when the test says so."""
    c = SimpleNamespace( now=1_000_000.0 )
    monkeypatch.setattr( throttle.time, "time", lambda: c.now )
    return c


@pytest.fixture
def sends( monkeypatch ):
    """Stub the notifier: records every request and reports delivery per `sends.success`."""
    s = SimpleNamespace( requests=[], success=True )
    def _notify( request, debug ):
        s.requests.append( request )
        return SimpleNamespace( success=s.success )
    monkeypatch.setattr( cv, "notify_user_async", _notify )
    return s


# ── the four behaviours the row requires ──────────────────────────────────────

def test_ten_rapid_calls_for_one_project_send_once( state, clock, sends ):
    for _ in range( 10 ):
        cv._send_validation_error( "no account", "lupin" )
    assert len( sends.requests ) == 1
    assert sends.requests[ 0 ].priority.value == "urgent"          # the first alert stays urgent


def test_it_sends_again_after_the_cooldown( state, clock, sends ):
    cv._send_validation_error( "no account", "lupin" )
    clock.now += 6 * HOUR - 1
    cv._send_validation_error( "no account", "lupin" )
    assert len( sends.requests ) == 1                                # one second short: still suppressed
    clock.now += 1
    cv._send_validation_error( "no account", "lupin" )
    assert len( sends.requests ) == 2                                # exactly 6h: sends again


def test_a_different_project_is_unaffected( state, clock, sends ):
    cv._send_validation_error( "no account", "lupin" )
    cv._send_validation_error( "no account", "cosa-voice" )
    cv._send_validation_error( "no account", "lupin" )
    assert len( sends.requests ) == 2


def test_a_corrupt_state_file_still_sends( state, clock, sends ):
    state.parent.mkdir( parents=True )
    state.write_text( "{this is not json" )
    cv._send_validation_error( "no account", "lupin" )
    assert len( sends.requests ) == 1
    assert json.loads( state.read_text() ) == { "lupin": clock.now }   # and it repaired the file


# ── the suppressed repeat logs a line instead of notifying ────────────────────

def test_a_suppressed_repeat_logs_and_does_not_notify( state, clock, sends, caplog ):
    cv._send_validation_error( "first", "lupin" )
    with caplog.at_level( "DEBUG", logger=cv.logger.name ):
        cv._send_validation_error( "second", "lupin" )
    assert len( sends.requests ) == 1
    assert "not re-sent" in caplog.text and "'lupin'" in caplog.text and "6h" in caplog.text
    assert "second" in caplog.text                                   # CRITICAL is still logged: the floor


# ── fail open, and only a DELIVERED alert is recorded ─────────────────────────

def test_an_undelivered_alert_is_not_recorded_so_the_next_start_retries( state, clock, sends ):
    sends.success = False
    cv._send_validation_error( "server down", "lupin" )
    assert not state.exists()
    sends.success = True
    cv._send_validation_error( "server down", "lupin" )
    assert len( sends.requests ) == 2                                # the first never reached anyone
    assert state.exists()


def test_a_notifier_that_raises_records_nothing_and_never_propagates( state, clock, monkeypatch ):
    def boom( request, debug ): raise RuntimeError( "unreachable" )
    monkeypatch.setattr( cv, "notify_user_async", boom )
    cv._send_validation_error( "x", "lupin" )
    assert not state.exists()


@pytest.mark.parametrize( "content", [ "[]", '"a string"', '{"lupin": "yesterday"}', '{"lupin": true}',
                                       '{"lupin": null}', "" ] )
def test_malformed_state_means_send( state, clock, sends, content ):
    state.parent.mkdir( parents=True )
    state.write_text( content )
    cv._send_validation_error( "x", "lupin" )
    assert len( sends.requests ) == 1


def test_a_future_timestamp_does_not_silence_the_alert( state, clock, sends ):
    state.parent.mkdir( parents=True )
    state.write_text( json.dumps( { "lupin": clock.now + 10 * HOUR } ) )    # the clock went backwards
    cv._send_validation_error( "x", "lupin" )
    assert len( sends.requests ) == 1


def test_an_unwritable_state_location_still_sends_every_time( state, clock, sends, monkeypatch ):
    state.parent.parent.mkdir( parents=True, exist_ok=True )
    state.parent.write_text( "i am a file, not a directory" )               # mkdir under it will fail
    cv._send_validation_error( "x", "lupin" )
    cv._send_validation_error( "x", "lupin" )
    assert len( sends.requests ) == 2                                       # nothing recorded, nothing silenced


# ── the write is atomic ───────────────────────────────────────────────────────

def test_the_write_leaves_valid_json_and_no_temp_file( state, clock ):
    assert throttle.record_sent( "lupin" ) is True
    assert throttle.record_sent( "cosa-voice" ) is True
    assert json.loads( state.read_text() ) == { "lupin": clock.now, "cosa-voice": clock.now }
    assert [ p.name for p in state.parent.iterdir() ] == [ state.name ]


def test_the_write_goes_through_a_temp_file_and_os_replace( state, clock, monkeypatch ):
    calls = []
    real  = os.replace
    def _spy( src, dst ):
        calls.append( ( os.path.basename( src ), os.path.basename( dst ) ) )
        real( src, dst )
    monkeypatch.setattr( throttle.os, "replace", _spy )
    throttle.record_sent( "lupin" )
    assert len( calls ) == 1
    tmp, dst = calls[ 0 ]
    assert dst == state.name and tmp != dst and tmp.startswith( state.name + "." ) and tmp.endswith( ".tmp" )


def test_a_failed_replace_cleans_up_its_temp_file_and_leaves_the_old_state( state, clock, monkeypatch ):
    throttle.record_sent( "lupin" )
    before = state.read_text()
    def _fail( src, dst ): raise OSError( "disk full" )
    monkeypatch.setattr( throttle.os, "replace", _fail )
    assert throttle.record_sent( "cosa-voice" ) is False
    assert state.read_text() == before                                       # the old file is intact
    assert [ p.name for p in state.parent.iterdir() ] == [ state.name ]      # and no .tmp left behind


def test_a_failed_replace_whose_cleanup_also_fails_still_does_not_raise( state, clock, monkeypatch ):
    def _fail( src, dst ): raise OSError( "disk full" )
    def _no_unlink( p ): raise OSError( "cannot remove" )
    monkeypatch.setattr( throttle.os, "replace", _fail )
    monkeypatch.setattr( throttle.os, "unlink", _no_unlink )
    assert throttle.record_sent( "lupin" ) is False


def test_the_default_path_is_the_one_in_dot_lupin_and_the_cooldown_is_six_hours():
    assert throttle.COOLDOWN_SECONDS == 6 * HOUR
    assert throttle.STATE_PATH.name == "mcp-validation-alerts.json" and throttle.STATE_PATH.parent.name == ".lupin"


# ── the call sites pass the project, so the cooldown is really per project ────

@pytest.mark.parametrize( "setup,expected_fragment", [
    ( "no_creds",    "No credentials for project 'alpha'" ),
    ( "login_401",   "Login failed for" ),
    ( "unreachable", "Cannot reach Lupin server" ),
] )
def test_each_validation_failure_passes_its_project_name( monkeypatch, state, setup, expected_fragment ):
    import lupin_cli.claude_code.hooks.lib.hook_credentials as hc
    import requests
    seen = []
    monkeypatch.setattr( cv, "_send_validation_error", lambda detail, project: seen.append( ( project, detail ) ) )
    if setup == "no_creds":
        monkeypatch.setattr( hc, "get_hook_credentials", lambda p: ( _ for _ in () ).throw( FileNotFoundError( "none" ) ) )
    else:
        monkeypatch.setattr( hc, "get_hook_credentials", lambda p: ( "claude.code@alpha.deepily.ai", "pw" ) )
        if setup == "login_401":
            monkeypatch.setattr( cv.requests, "post", lambda *a, **k: SimpleNamespace( status_code=401 ) )
        else:
            def _refused( *a, **k ): raise requests.ConnectionError( "refused" )
            monkeypatch.setattr( cv.requests, "post", _refused )
    cv._validate_repo_account( "alpha" )
    assert len( seen ) == 1 and seen[ 0 ][ 0 ] == "alpha" and expected_fragment in seen[ 0 ][ 1 ]
