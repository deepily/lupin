"""
The SessionStart listener-spawn liveness check must see a child that has
already exited.

🔴 THE INCIDENT (2026-09-04). A worktree seat's listener exited 1 during
credential resolution roughly 0.1s after Popen. The hook's check —
`os.kill( listener_pid, 0 )` at +0.3s — reported it ALIVE, wrote the dead PID
into the session bridge, and returned success. The seat then ran DEAF while
the roster reported it healthy. The centralized listener log carried 32 such
startup deaths, almost all worktree seats.

The mechanism is not subtle and is not about credentials: `_spawn_listener_locked`
never `wait()`s its child, so an exited child is a ZOMBIE, and `os.kill( pid, 0 )`
succeeds on a zombie. `proc.poll()` reaps it and reports the exit code.

WHAT THIS FILE ENTERS AT. The incident entered at `_spawn_listener_locked` —
spawn, check, record — so that is the function driven here. Only the argv is
stood down (a `/bin/true` / `/bin/sleep` child via a patched Popen); the
liveness check, the bridge write and the return value are the real ones. A test
that called `poll()` itself would confirm CPython and say nothing about the hook.

THREE ARMS, and the second is why the first means anything:
    1. child exits immediately  -> returns None, bridge carries NO listener_pid
    2. child stays alive        -> returns the pid, bridge carries it
    3. the mechanism itself     -> os.kill( pid, 0 ) succeeds on the zombie that
                                   poll() reports, so the old check COULD NOT have
                                   caught arm 1
Revert the fix to `os.kill( listener_pid, 0 )` and arm 1 reddens while arms 2
and 3 stay green — the discrimination, not merely a failure.
"""

import json
import os
import subprocess
import time

import pytest

from lupin_cli.claude_code.hooks import register_session


def _bridge( tmp_path ):
    """A minimal bridge dict + file, as Phase 2 would have written them."""
    session_file = tmp_path / "cc-4242.json"
    session_data = {
        "session_id"        : "abcd1234-0000-0000-0000-000000000000",
        "stable_session_id" : "abcd1234-0000-0000-0000-000000000000",
        "cwd"               : str( tmp_path ),
        "cc_pid"            : os.getpid(),
    }
    session_file.write_text( json.dumps( session_data ) )
    return session_data, str( session_file )


@pytest.fixture
def sessions_seam( tmp_path, monkeypatch ):
    """Redirect the bridge directory away from the operator's live one (row 8ccc20ab)."""
    monkeypatch.setenv( "LUPIN_HOOK_SESSIONS_DIR", str( tmp_path ) )
    return tmp_path


def _patch_popen_with( monkeypatch, argv ):
    """
    Replace the module's Popen with one that runs `argv` instead of the listener.

    The child is REAL — really forked, really exits, really becomes a zombie
    because nothing wait()s it. Only what it executes is stood down.
    """
    real_popen = subprocess.Popen

    def fake_popen( cmd, **kwargs ):
        kwargs.pop( "env", None )
        return real_popen( argv, **kwargs )

    monkeypatch.setattr( register_session.subprocess, "Popen", fake_popen )


def test_a_listener_that_exits_immediately_is_not_recorded_as_live( tmp_path, sessions_seam, monkeypatch, capsys ):
    session_data, session_file = _bridge( tmp_path )
    _patch_popen_with( monkeypatch, [ "/bin/true" ] )

    result = register_session._spawn_listener_locked(
        session_data[ "stable_session_id" ], session_data, session_file, None )

    assert result is None, "a dead-on-arrival listener must not be reported as spawned"
    assert "listener_pid" not in session_data, "a dead PID must never reach the bridge dict"
    assert "listener_pid" not in json.loads( open( session_file ).read() ), \
        "a dead PID must never reach the bridge FILE — that is what the roster reads"
    assert "died immediately" in capsys.readouterr().err


def test_a_listener_that_stays_up_is_still_recorded( tmp_path, sessions_seam, monkeypatch ):
    """
    The positive control. Without it, an always-refusing check would satisfy the
    test above — 'the alarm fires' and 'the alarm fires when it should' are
    different claims.
    """
    session_data, session_file = _bridge( tmp_path )
    _patch_popen_with( monkeypatch, [ "/bin/sleep", "5" ] )

    result = register_session._spawn_listener_locked(
        session_data[ "stable_session_id" ], session_data, session_file, None )

    try:
        assert isinstance( result, int ) and result > 0
        assert session_data[ "listener_pid" ] == result
        assert json.loads( open( session_file ).read() )[ "listener_pid" ] == result
    finally:
        try:
            os.kill( result, 9 )
        except ( ProcessLookupError, TypeError ):
            pass


def test_os_kill_sig0_cannot_see_the_zombie_that_poll_reports():
    """
    The mechanism, pinned independently of the hook.

    This is what makes the first test's failure mode legible rather than
    mysterious: the replaced check is not merely weaker, it is INCAPABLE of
    observing the state the incident produced.
    """
    proc = subprocess.Popen( [ "/bin/true" ], start_new_session=True )
    time.sleep( 0.3 )

    os.kill( proc.pid, 0 )                      # raises if the old check could have caught it

    assert proc.poll() == 0, "poll() must report the exit the signal-0 probe cannot see"
