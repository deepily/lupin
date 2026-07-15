"""
AC3 — 100% lines/branches/functions on tests/smoke/utilities/killtrace_probe.py.

Pure finders + polling driven on real tmp files (no mocks); the subprocess
arms driven against REAL tmux on private -S sockets (the AC5/AC6 safety
recipe — -S overrides all env-based socket selection, fleet unreachable by
construction). The LIVE instrument end-to-end run lives in
src/tests/smoke/test_killtrace_observation_probe.py; here run_probe() is
exercised against an injected log so coverage never depends on the root
tracer being installed.

VENUE: :7999-eligible / AI-discretionary.
"""

import shutil

import pytest

from tests.smoke.utilities.killtrace_probe import (
    PROBE_SESSION_NAME,
    await_line,
    birth_throwaway_server,
    find_killer_line,
    find_self_sigterm_line,
    kill_throwaway_server,
    run_probe,
    stripped_env,
)


needs_tmux = pytest.mark.skipif( not shutil.which( "tmux" ), reason="tmux is not installed" )


# ---------------------------------------------------------------------------
# stripped_env
# ---------------------------------------------------------------------------

def test_stripped_env_removes_pane_context_and_tmpdir_copy_only():
    source = {
        "TMUX"        : "/tmp/tmux-1001/default,349437,0",
        "TMUX_PANE"   : "%7",
        "TMUX_TMPDIR" : "/tmp/prior",
        "PATH"        : "/usr/bin",
    }
    env = stripped_env( source )

    assert env == { "PATH": "/usr/bin" }
    assert source[ "TMUX" ] == "/tmp/tmux-1001/default,349437,0", "input mapping must be untouched"


def test_stripped_env_with_nothing_to_strip():
    assert stripped_env( { "PATH": "/usr/bin" } ) == { "PATH": "/usr/bin" }


# ---------------------------------------------------------------------------
# finders (pure)
# ---------------------------------------------------------------------------

def test_find_self_sigterm_line_returns_last_match():
    log = (
        "21:13:28 sig=15 target=349437 from=tmux: server pid=349437 uid=1001\n"
        "21:14:00 sig=28 target=349437 from=bash pid=1 uid=1001\n"
        "21:15:00 sig=15 target=349437 from=tmux: server pid=349437 uid=1001\n"
    )
    assert find_self_sigterm_line( log, 349437 ) == "21:15:00 sig=15 target=349437 from=tmux: server pid=349437 uid=1001"


def test_find_self_sigterm_line_rejects_wrong_pid_wrong_sender_and_empty():
    log = (
        "21:13:28 sig=15 target=999 from=tmux: server pid=999 uid=1001\n"
        "21:13:29 sig=15 target=349437 from=pkill pid=42 uid=1001\n"
    )
    assert find_self_sigterm_line( log, 349437 ) is None, "wrong pid / external sender must not match"
    assert find_self_sigterm_line( "", 349437 ) is None


def test_find_killer_line_returns_last_match_or_none():
    log = (
        "22:00:00 KILLER comm=bash pid=1 ppid=0 uid=1001 cmd=tmux kill-server\n"
        "22:00:01 KILLER comm=bash pid=2 ppid=0 uid=1001 cmd=tmux -L x kill-server\n"
        "22:00:02 KILLER comm=bash pid=3 ppid=0 uid=1001 cmd=tmux list-sessions\n"
    )
    assert find_killer_line( log ) == "22:00:01 KILLER comm=bash pid=2 ppid=0 uid=1001 cmd=tmux -L x kill-server"
    assert find_killer_line( "no such lines here" ) is None


# ---------------------------------------------------------------------------
# await_line (real tmp files, no mocks)
# ---------------------------------------------------------------------------

def test_await_line_finds_immediately( tmp_path ):
    log = tmp_path / "killtrace.log"
    log.write_text( "hit\n" )
    assert await_line( str( log ), lambda text: "hit" if "hit" in text else None, timeout_s=1.0 ) == "hit"


def test_await_line_times_out_to_none( tmp_path ):
    log = tmp_path / "killtrace.log"
    log.write_text( "nothing relevant\n" )
    assert await_line( str( log ), lambda text: None, timeout_s=0.3, poll_s=0.05 ) is None


def test_await_line_fails_loud_on_unreadable_log( tmp_path ):
    with pytest.raises( OSError ):
        await_line( str( tmp_path / "absent.log" ), lambda text: text, timeout_s=0.2 )


# ---------------------------------------------------------------------------
# subprocess arms (real tmux, private -S sockets only)
# ---------------------------------------------------------------------------

@needs_tmux
def test_birth_raises_loud_when_the_socket_path_is_a_directory( tmp_path ):
    """tmux fails CLIENT-side (rc=1 'Is a directory') — the birth branch."""
    with pytest.raises( RuntimeError, match="could not birth" ):
        birth_throwaway_server( tmp_path, stripped_env( {} ) )


@needs_tmux
def test_birth_raises_loud_when_the_socket_dir_does_not_exist( tmp_path ):
    """
    Measured tmux 3.2a quirk: new-session into a MISSING parent dir returns
    rc=0 (the forked server dies after the client detaches) — the failure
    only surfaces at the pid query. That is exactly why birth_throwaway_server
    carries the second guard.
    """
    with pytest.raises( RuntimeError, match="pid query failed" ):
        birth_throwaway_server( tmp_path / "no-such-dir" / "probe.sock", stripped_env( {} ) )


@needs_tmux
def test_birth_and_kill_on_a_private_socket( tmp_path, monkeypatch ):
    import os
    sock = tmp_path / "probe.sock"
    env  = stripped_env( dict( os.environ ) )

    pid = birth_throwaway_server( sock, env )
    assert pid > 0
    assert sock.exists()

    kill_throwaway_server( sock, env )
    kill_throwaway_server( sock, env )    # dead-already is fine (Ensures clause)


@needs_tmux
def test_run_probe_orchestration_against_an_injected_log( tmp_path ):
    """
    Drives the run_probe composition end-to-end with a REAL throwaway server
    but an injected log primed post-kill via the finder path — coverage of
    the orchestration must not depend on the root tracer being installed
    (that live proof is the smoke test's job).
    """
    import os
    sock = tmp_path / "probe.sock"
    log  = tmp_path / "killtrace.log"

    env = stripped_env( dict( os.environ ) )
    probe_pid = birth_throwaway_server( sock, env )
    kill_throwaway_server( sock, env )
    log.write_text( f"22:10:00 sig=15 target={probe_pid + 1} from=tmux: server pid={probe_pid + 1} uid=1001\n" )

    sock2 = tmp_path / "probe2.sock"
    server_pid, line = run_probe( sock2, dict( os.environ ), log_path=str( log ), timeout_s=0.3 )
    assert server_pid > 0
    assert line is None, "injected log names a DIFFERENT pid — probe must report not-observed"
