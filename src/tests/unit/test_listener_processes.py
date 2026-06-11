"""
Unit tests for src/lupin_cli/claude_code/hooks/lib/listener_processes.py —
the F1/F2/F4 shared primitives (pgrep discovery + exclusive flock).

Per src/rnd/v0.1.8/2026.06.11-broadcast-miss-f1-f4-implementation.md §2.1.

SAFETY: live-process tests spawn throwaway python children carrying the
listener marker + a uuid-unique FAKE hash in argv — they can never match
(or touch) a real session's listener.
"""

import fcntl
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import lupin_cli.claude_code.hooks.lib.listener_processes as listener_processes
from lupin_cli.claude_code.hooks.lib.listener_processes import (
    exclusive_flock, find_live_listener_pids, listener_spawn_lock, tmux_injection_lock
)


def _completed( returncode=0, stdout="" ):
    """Build a fake subprocess.CompletedProcess-alike for pgrep mocking."""
    fake            = MagicMock()
    fake.returncode = returncode
    fake.stdout     = stdout
    return fake


def _spawn_fake_listener( fake_hash ):
    """
    Spawn a real throwaway child whose cmdline matches the listener pattern
    for fake_hash. Extra argv tokens land in /proc cmdline, which is what
    pgrep -f matches against.
    """
    return subprocess.Popen(
        [ sys.executable, "-c", "import time; time.sleep( 30 )",
          "cc_notification_listener", "--session-id", fake_hash ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


# ═════════════════════════════════════════════════════════════════════════════
# find_live_listener_pids — mocked pgrep paths
# ═════════════════════════════════════════════════════════════════════════════

class TestFindLiveListenerPidsMocked:

    def test_empty_hash_returns_empty( self ):
        assert find_live_listener_pids( "" ) == [ ]

    def test_no_match_returncode_1_returns_empty( self, monkeypatch ):
        monkeypatch.setattr( listener_processes.subprocess, "run",
                             MagicMock( return_value=_completed( returncode=1 ) ) )
        assert find_live_listener_pids( "abc12345" ) == [ ]

    def test_pids_parsed_and_sorted( self, monkeypatch ):
        monkeypatch.setattr( listener_processes.subprocess, "run",
                             MagicMock( return_value=_completed( stdout="999\n111\n555\n" ) ) )
        assert find_live_listener_pids( "abc12345" ) == [ 111, 555, 999 ]

    def test_garbage_tokens_skipped( self, monkeypatch ):
        monkeypatch.setattr( listener_processes.subprocess, "run",
                             MagicMock( return_value=_completed( stdout="111\nnot-a-pid\n222\n" ) ) )
        assert find_live_listener_pids( "abc12345" ) == [ 111, 222 ]

    def test_own_pid_excluded( self, monkeypatch ):
        own = os.getpid()
        monkeypatch.setattr( listener_processes.subprocess, "run",
                             MagicMock( return_value=_completed( stdout=f"{own}\n333\n" ) ) )
        assert find_live_listener_pids( "abc12345" ) == [ 333 ]

    def test_pgrep_timeout_returns_empty( self, monkeypatch ):
        monkeypatch.setattr( listener_processes.subprocess, "run",
                             MagicMock( side_effect=subprocess.TimeoutExpired( "pgrep", 2 ) ) )
        assert find_live_listener_pids( "abc12345" ) == [ ]

    def test_pgrep_missing_returns_empty( self, monkeypatch ):
        monkeypatch.setattr( listener_processes.subprocess, "run",
                             MagicMock( side_effect=FileNotFoundError( "pgrep" ) ) )
        assert find_live_listener_pids( "abc12345" ) == [ ]

    def test_pgrep_oserror_returns_empty( self, monkeypatch ):
        monkeypatch.setattr( listener_processes.subprocess, "run",
                             MagicMock( side_effect=OSError( "boom" ) ) )
        assert find_live_listener_pids( "abc12345" ) == [ ]

    def test_pgrep_pattern_contains_module_name_and_hash( self, monkeypatch ):
        run_mock = MagicMock( return_value=_completed( returncode=1 ) )
        monkeypatch.setattr( listener_processes.subprocess, "run", run_mock )
        find_live_listener_pids( "feedc0de" )
        pattern = run_mock.call_args[ 0 ][ 0 ][ 2 ]
        assert "cc_notification_listener" in pattern
        assert "--session-id feedc0de" in pattern


# ═════════════════════════════════════════════════════════════════════════════
# find_live_listener_pids — live processes (real pgrep, fake hash)
# ═════════════════════════════════════════════════════════════════════════════

class TestFindLiveListenerPidsLive:

    def test_finds_both_duplicate_listeners( self ):
        """The 06-06 anomaly in miniature: TWO live listeners for ONE hash."""
        fake_hash = uuid.uuid4().hex[ :8 ]
        procs     = [ _spawn_fake_listener( fake_hash ), _spawn_fake_listener( fake_hash ) ]
        try:
            time.sleep( 0.2 )  # let /proc entries settle
            found = find_live_listener_pids( fake_hash )
            assert sorted( p.pid for p in procs ) == found
        finally:
            for p in procs:
                p.kill()
                p.wait( timeout=5 )

    def test_other_hash_not_matched( self ):
        fake_hash = uuid.uuid4().hex[ :8 ]
        proc      = _spawn_fake_listener( fake_hash )
        try:
            time.sleep( 0.2 )
            assert find_live_listener_pids( uuid.uuid4().hex[ :8 ] ) == [ ]
        finally:
            proc.kill()
            proc.wait( timeout=5 )


# ═════════════════════════════════════════════════════════════════════════════
# exclusive_flock
# ═════════════════════════════════════════════════════════════════════════════

class TestExclusiveFlock:

    def test_acquires_and_releases( self, tmp_path ):
        lock_path = tmp_path / "x.lock"
        with exclusive_flock( lock_path ) as held:
            assert held is True
            # A second NON-blocking attempt from another fd must fail while held
            other = open( lock_path, "w" )
            with pytest.raises( BlockingIOError ):
                fcntl.flock( other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB )
            other.close()
        # Released after the with-block — now acquirable
        other = open( lock_path, "w" )
        fcntl.flock( other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB )
        fcntl.flock( other.fileno(), fcntl.LOCK_UN )
        other.close()

    def test_creates_parent_dirs( self, tmp_path ):
        lock_path = tmp_path / "deep" / "nested" / "x.lock"
        with exclusive_flock( lock_path ) as held:
            assert held is True
        assert lock_path.exists()

    def test_fail_open_when_path_unopenable( self, tmp_path ):
        # A directory cannot be opened "w" → IsADirectoryError (an OSError)
        target = tmp_path / "as-dir"
        target.mkdir()
        with exclusive_flock( target ) as held:
            assert held is False  # fail-open: the block still ran

    def test_fail_open_when_flock_fails( self, tmp_path, monkeypatch ):
        calls = { "n": 0 }
        def _failing_flock( fd, op ):
            calls[ "n" ] += 1
            raise OSError( "flock refused" )
        monkeypatch.setattr( listener_processes.fcntl, "flock", _failing_flock )
        with exclusive_flock( tmp_path / "y.lock" ) as held:
            assert held is False
        assert calls[ "n" ] == 1  # only the acquire attempted; no unlock on fail-open

    def test_serializes_concurrent_holders( self, tmp_path ):
        """Two threads through one lock — critical sections must not overlap."""
        lock_path = tmp_path / "serial.lock"
        events    = [ ]
        def worker( name ):
            with exclusive_flock( lock_path ):
                events.append( ( name, "enter" ) )
                time.sleep( 0.15 )
                events.append( ( name, "exit" ) )
        threads = [ threading.Thread( target=worker, args=( n, ) ) for n in ( "a", "b" ) ]
        for t in threads: t.start()
        for t in threads: t.join( timeout=10 )
        # Serialized ⇒ enter/exit strictly alternate by holder: X-enter, X-exit, Y-enter, Y-exit
        assert [ e[ 1 ] for e in events ] == [ "enter", "exit", "enter", "exit" ]
        assert events[ 0 ][ 0 ] == events[ 1 ][ 0 ]
        assert events[ 2 ][ 0 ] == events[ 3 ][ 0 ]


# ═════════════════════════════════════════════════════════════════════════════
# Named lock wrappers
# ═════════════════════════════════════════════════════════════════════════════

class TestNamedLockWrappers:

    def test_listener_spawn_lock_path_convention( self, tmp_path, monkeypatch ):
        monkeypatch.setattr( listener_processes, "SESSION_DIR", tmp_path )
        with listener_spawn_lock( "abc12345" ) as held:
            assert held is True
        assert ( tmp_path / "cc-listener-abc12345.spawn-lock" ).exists()

    def test_tmux_injection_lock_path_convention( self, tmp_path, monkeypatch ):
        monkeypatch.setattr( listener_processes, "SESSION_DIR", tmp_path )
        with tmux_injection_lock( "wise penguin" ) as held:
            assert held is True
        assert ( tmp_path / "tmux-inject-wise_penguin.lock" ).exists()

    def test_tmux_injection_lock_sanitizes_hostile_names( self, tmp_path, monkeypatch ):
        monkeypatch.setattr( listener_processes, "SESSION_DIR", tmp_path )
        with tmux_injection_lock( "../../etc/passwd" ) as held:
            assert held is True
        # No traversal: everything non-filename-safe flattened (dots/dashes kept, slashes not)
        assert ( tmp_path / "tmux-inject-.._.._etc_passwd.lock" ).exists()
