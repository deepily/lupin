"""
Smoke test for the idle_waiter detached-subprocess flow.

Spawns a real idle_waiter.py subprocess with a 5-second sleep override
(via env var LUPIN_IDLE_WAITER_TEST_SLEEP_SECS), verifies the bridge state
transitions through the expected sequence:
  1. Pre-spawn: no waiter_pid in bridge
  2. Mid-sleep: waiter_pid is set to the subprocess PID
  3. Post-fire: waiter_pid is cleared (or replaced by successor)

Per `feedback_tests_parameterize_base_url` and the project testing-patterns
SKILL: this smoke targets `LUPIN_API_URL` (default `http://localhost:7999`).
The waiter's REST call goes to whatever URL the env points at. For pre-merge
runs without a live server, we point `LUPIN_API_URL` at an unreachable host
so the waiter's REST call fails fast — we're testing the spawn/sleep/wake
plumbing, not the response-parse path (that's covered in test_idle_waiter.py).

Design: src/rnd/v0.1.7/2026.04.29-idle-aware-stop-hook/01-design.md
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


# Per-test BASE_URL — `LUPIN_API_URL` env wins, falling back to a non-routable
# port that fails fast so the waiter's REST call dies in <2s. The smoke verifies
# state transitions, not response handling.
BASE_URL = os.environ.get( "LUPIN_API_URL", "http://localhost:1" ).rstrip( "/" )


@pytest.fixture
def isolated_bridge( tmp_path, monkeypatch ):
    """
    Stand up an isolated ~/.claude/sessions directory under tmp_path so we
    can drop a fake bridge file without polluting real session bridges.

    The waiter's session_bridge.find_session_path_by_id resolves bridges
    by scanning ~/.claude/sessions/ — we override HOME so the scan finds
    only our test file.
    """
    fake_home = tmp_path / "fake-home"
    sessions  = fake_home / ".claude" / "sessions"
    sessions.mkdir( parents=True )

    # File MUST be named after a live PID — session_bridge's PID-alive
    # filter discards bridges whose filename PID is dead. Use the test
    # process's own PID so the file is "owned" by something alive.
    live_pid    = os.getpid()
    bridge_path = sessions / f"cc-{live_pid}.json"
    bridge_path.write_text( json.dumps( {
        "session_id"        : "smoketestid",
        "stable_session_id" : "smoketestid",
        "ppid"              : live_pid,
        "idle_detection"    : {
            "last_interaction_at" : "2026-04-29T10:00:00-04:00",
            "backoff_index"       : 0,
            "waiter_pid"          : None,
        },
    }, indent=2 ) )

    monkeypatch.setenv( "HOME", str( fake_home ) )
    return bridge_path


def _read_bridge( bridge_path: Path ) -> dict:
    return json.loads( bridge_path.read_text() )


@pytest.mark.timeout( 30 )
def test_waiter_lifecycle_state_transitions( isolated_bridge ):
    """
    Spawn idle_waiter.py with 2-second sleep + unreachable API URL.
    Verify: waiter_pid set during sleep → cleared after exit.
    """
    bridge_path = isolated_bridge
    lupin_root  = os.environ.get( "LUPIN_ROOT", os.getcwd() )
    src_path    = os.path.join( lupin_root, "src" )

    env = os.environ.copy()
    env[ "PYTHONPATH" ]                       = src_path + ":" + env.get( "PYTHONPATH", "" )
    env[ "LUPIN_IDLE_WAITER_TEST_SLEEP_SECS" ] = "2"
    env[ "LUPIN_API_URL" ]                    = BASE_URL  # unreachable for this test
    env[ "HOME" ]                             = str( bridge_path.parents[ 2 ] )

    cmd = [
        sys.executable, "-m", "lupin_cli.claude_code.hooks.lib.idle_waiter",
        "--session-id"   , "smoketestid",
        "--ppid"         , str( os.getpid() ),
        "--backoff-index", "0",
    ]

    proc = subprocess.Popen(
        cmd,
        stdout = subprocess.PIPE,
        stderr = subprocess.PIPE,
        env    = env,
    )

    # Phase 1: mid-sleep — waiter should have claimed the slot
    # Give it ~0.5s to write its PID to the bridge
    time.sleep( 0.5 )
    state = _read_bridge( bridge_path ).get( "idle_detection", { } )
    assert state.get( "waiter_pid" ) == proc.pid, \
        f"expected waiter_pid={proc.pid} mid-sleep, got {state.get( 'waiter_pid' )}"

    # waiter_started_at should be ISO timestamp
    started_at = state.get( "waiter_started_at" )
    assert started_at, "waiter should have set waiter_started_at"

    # Phase 2: wait for subprocess to finish (sleeps 2s + REST fail)
    try:
        out, err = proc.communicate( timeout=15 )
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait( timeout=5 )
        pytest.fail( "waiter did not exit in 15s — possible hang in REST call or sleep" )

    # Phase 3: post-exit — slot cleared (no successor since fire failed with error)
    state = _read_bridge( bridge_path ).get( "idle_detection", { } )
    assert state.get( "waiter_pid" ) is None, \
        f"slot should be cleared after waiter exits with error, got waiter_pid={state.get( 'waiter_pid' )}"


@pytest.mark.timeout( 30 )
def test_waiter_exits_silently_on_dead_ppid( isolated_bridge ):
    """
    Spawn waiter pointing at a PPID that's definitely dead (PID 1 won't be us;
    we use a fake high-numbered PID instead). Waiter should detect dead PPID
    during its first sleep chunk and exit fast.
    """
    bridge_path = isolated_bridge
    lupin_root  = os.environ.get( "LUPIN_ROOT", os.getcwd() )
    src_path    = os.path.join( lupin_root, "src" )

    env = os.environ.copy()
    env[ "PYTHONPATH" ]                       = src_path + ":" + env.get( "PYTHONPATH", "" )
    env[ "LUPIN_IDLE_WAITER_TEST_SLEEP_SECS" ] = "2"   # short sleep so dead-PPID branch fires in ~2s
    env[ "LUPIN_API_URL" ]                    = BASE_URL
    env[ "HOME" ]                             = str( bridge_path.parents[ 2 ] )

    # Use a likely-dead high PID
    fake_dead_ppid = 999999

    cmd = [
        sys.executable, "-m", "lupin_cli.claude_code.hooks.lib.idle_waiter",
        "--session-id"   , "smoketestid",
        "--ppid"         , str( fake_dead_ppid ),
        "--backoff-index", "0",
    ]

    proc = subprocess.Popen( cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env )

    # The waiter does sleep(2) in one chunk, then checks _is_pid_alive — finds
    # the fake_dead_ppid is dead, exits. Should complete in ~2-3s.
    try:
        out, err = proc.communicate( timeout=15 )
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait( timeout=5 )
        pytest.fail( "waiter did not exit on dead PPID within 15s" )

    state = _read_bridge( bridge_path ).get( "idle_detection", { } )
    assert state.get( "waiter_pid" ) is None
