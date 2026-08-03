"""
Unit tests for the F1 singleton spawn guard in
src/lupin_cli/claude_code/hooks/register_session.py::_spawn_listener.

Root cause regression-tested here: the documented `--continue` double-fire
runs two concurrent SessionStart hooks; pre-fix BOTH spawned a listener
(no is-one-already-running check at the spawn site), producing the
duplicate-listener pair behind the 2026-06-06 broadcast miss.

Per src/rnd/v0.1.8/2026.06.10-broadcast-miss-duplicate-listener-root-cause.md §4
and src/rnd/v0.1.8/2026.06.11-broadcast-miss-f1-f4-implementation.md §2.2.
"""

import json
import threading
import time
from unittest.mock import MagicMock

import pytest

import lupin_cli.claude_code.hooks.lib.listener_processes as listener_processes
import lupin_cli.claude_code.hooks.register_session as register_session


SESSION_ID = "abc12345-6789-abcd-ef01-234567890abc"
SHORT_ID   = SESSION_ID[ :8 ]


@pytest.fixture
def lock_dir( tmp_path, monkeypatch ):
    """Isolate the spawn-lock files from the real ~/.claude/sessions."""
    # Row 8ccc20ab: the lock dir resolves through sessions_dir() at CALL time.
    monkeypatch.setenv( "LUPIN_HOOK_SESSIONS_DIR", str( tmp_path ) )
    return tmp_path


class TestSingletonGuardShortCircuit:

    def test_existing_listener_reused_no_spawn( self, lock_dir, tmp_path, monkeypatch ):
        """Guard finds a live listener → returns its PID, never Popens."""
        monkeypatch.setattr( register_session, "find_live_listener_pids",
                             MagicMock( return_value=[ 4242 ] ) )
        popen_mock = MagicMock()
        monkeypatch.setattr( register_session.subprocess, "Popen", popen_mock )

        session_file = tmp_path / "cc-999.json"
        session_data = { "session_id": SESSION_ID }

        result = register_session._spawn_listener( SESSION_ID, session_data, str( session_file ) )

        assert result == 4242
        popen_mock.assert_not_called()

    def test_existing_listener_pid_recorded_in_bridge( self, lock_dir, tmp_path, monkeypatch ):
        """Short-circuit still records the PID so SessionEnd can reap it."""
        monkeypatch.setattr( register_session, "find_live_listener_pids",
                             MagicMock( return_value=[ 4242, 5555 ] ) )
        session_file = tmp_path / "cc-999.json"
        session_data = { "session_id": SESSION_ID }

        register_session._spawn_listener( SESSION_ID, session_data, str( session_file ) )

        assert session_data[ "listener_pid" ] == 4242
        with open( session_file ) as f:
            assert json.load( f )[ "listener_pid" ] == 4242

    def test_empty_session_id_returns_none( self, lock_dir ):
        assert register_session._spawn_listener( "", { }, "x" ) is None

    def test_disabled_env_returns_none( self, lock_dir, monkeypatch ):
        monkeypatch.setenv( "LUPIN_CC_HOOK_LISTENER_ENABLED", "false" )
        find_mock = MagicMock( return_value=[ ] )
        monkeypatch.setattr( register_session, "find_live_listener_pids", find_mock )
        assert register_session._spawn_listener( SESSION_ID, { }, "x" ) is None
        find_mock.assert_not_called()

    def test_no_existing_listener_spawns( self, lock_dir, tmp_path, monkeypatch ):
        """Guard finds nothing → normal spawn path runs and records the PID."""
        monkeypatch.setattr( register_session, "find_live_listener_pids",
                             MagicMock( return_value=[ ] ) )
        proc          = MagicMock()
        proc.pid      = 7777
        popen_mock    = MagicMock( return_value=proc )
        monkeypatch.setattr( register_session.subprocess, "Popen", popen_mock )
        monkeypatch.setattr( register_session.os, "kill", MagicMock() )  # liveness probe passes
        monkeypatch.setattr( register_session.time, "sleep", MagicMock() )
        # Keep listener log/stderr files inside tmp
        monkeypatch.setattr( register_session.os.path, "expanduser",
                             lambda p: str( tmp_path ) )

        session_file = tmp_path / "cc-999.json"
        session_data = { "session_id": SESSION_ID }

        result = register_session._spawn_listener( SESSION_ID, session_data, str( session_file ) )

        assert result == 7777
        popen_mock.assert_called_once()
        assert session_data[ "listener_pid" ] == 7777


class TestRecordListenerPid:

    def test_records_and_persists( self, tmp_path ):
        session_file = tmp_path / "b.json"
        session_data = { "session_id": SESSION_ID }
        register_session._record_listener_pid( session_data, str( session_file ), 123 )
        with open( session_file ) as f:
            assert json.load( f ) == { "session_id": SESSION_ID, "listener_pid": 123 }

    def test_noop_without_session_data( self, tmp_path ):
        register_session._record_listener_pid( None, str( tmp_path / "b.json" ), 123 )
        assert not ( tmp_path / "b.json" ).exists()

    def test_noop_without_session_file( self ):
        session_data = { }
        register_session._record_listener_pid( session_data, None, 123 )
        assert session_data == { }  # no file ⇒ no record (original contract preserved)

    def test_write_failure_swallowed( self, tmp_path ):
        unwritable = tmp_path / "no-such-dir" / "b.json"
        register_session._record_listener_pid( { }, str( unwritable ), 123 )  # must not raise


class TestSpawnListenerLocked:
    """The relocated spawn body — flags, env wiring, and crash diagnostics."""

    @pytest.fixture
    def spawn_env( self, tmp_path, monkeypatch ):
        """Common patches: tmp session dir, instant sleep, captured Popen."""
        captured = { }
        proc     = MagicMock()
        proc.pid = 7777
        def fake_popen( cmd, **kwargs ):
            captured[ "cmd" ]    = cmd
            captured[ "kwargs" ] = kwargs
            return proc
        monkeypatch.setattr( register_session.subprocess, "Popen", fake_popen )
        monkeypatch.setattr( register_session.os, "kill", MagicMock() )
        monkeypatch.setattr( register_session.time, "sleep", MagicMock() )
        monkeypatch.setattr( register_session.os.path, "expanduser", lambda p: str( tmp_path ) )
        # Deterministic flag state — the developer shell exports these as True
        monkeypatch.delenv( "LUPIN_CC_HOOK_LISTENER_DEBUG", raising=False )
        monkeypatch.delenv( "LUPIN_CC_HOOK_LISTENER_VERBOSE", raising=False )
        return captured

    def test_accepted_ids_and_debug_verbose_flags_forwarded( self, spawn_env, monkeypatch ):
        monkeypatch.setenv( "LUPIN_CC_HOOK_LISTENER_DEBUG", "true" )
        monkeypatch.setenv( "LUPIN_CC_HOOK_LISTENER_VERBOSE", "true" )
        result = register_session._spawn_listener_locked(
            SESSION_ID, None, None, accepted_ids="abc12345,def67890"
        )
        assert result == 7777
        cmd = spawn_env[ "cmd" ]
        assert [ "--accepted-ids", "abc12345,def67890" ] == cmd[ cmd.index( "--accepted-ids" ): cmd.index( "--accepted-ids" ) + 2 ]
        assert "--debug" in cmd and "--verbose" in cmd

    def test_flags_absent_when_env_unset( self, spawn_env ):
        register_session._spawn_listener_locked( SESSION_ID, None, None, None )
        cmd = spawn_env[ "cmd" ]
        assert "--debug" not in cmd and "--verbose" not in cmd and "--accepted-ids" not in cmd

    def test_pythonpath_prefixed_when_missing_src( self, spawn_env, monkeypatch ):
        monkeypatch.setenv( "LUPIN_ROOT", "/fake/lupin" )
        monkeypatch.setenv( "PYTHONPATH", "/elsewhere" )
        register_session._spawn_listener_locked( SESSION_ID, None, None, None )
        assert spawn_env[ "kwargs" ][ "env" ][ "PYTHONPATH" ].startswith( "/fake/lupin/src:" )

    def test_immediate_death_with_stderr_diagnostics( self, tmp_path, monkeypatch, capsys ):
        def fake_popen( cmd, **kwargs ):
            kwargs[ "stderr" ].write( "Traceback: missing credentials" )
            kwargs[ "stderr" ].flush()
            proc     = MagicMock()
            proc.pid = 7777
            return proc
        monkeypatch.setattr( register_session.subprocess, "Popen", fake_popen )
        monkeypatch.setattr( register_session.os, "kill",
                             MagicMock( side_effect=ProcessLookupError ) )
        monkeypatch.setattr( register_session.time, "sleep", MagicMock() )
        monkeypatch.setattr( register_session.os.path, "expanduser", lambda p: str( tmp_path ) )

        assert register_session._spawn_listener_locked( SESSION_ID, None, None, None ) is None
        assert "missing credentials" in capsys.readouterr().err

    def test_immediate_death_without_stderr( self, spawn_env, monkeypatch, capsys ):
        monkeypatch.setattr( register_session.os, "kill",
                             MagicMock( side_effect=ProcessLookupError ) )
        assert register_session._spawn_listener_locked( SESSION_ID, None, None, None ) is None
        assert "died immediately with no stderr output" in capsys.readouterr().err

    def test_immediate_death_stderr_unreadable( self, tmp_path, monkeypatch, capsys ):
        def fake_popen( cmd, **kwargs ):
            # Remove the stderr file mid-spawn so the diagnostic re-open fails
            import os as _os
            _os.remove( tmp_path / f"cc-listener-{SHORT_ID}.stderr" )
            proc     = MagicMock()
            proc.pid = 7777
            return proc
        monkeypatch.setattr( register_session.subprocess, "Popen", fake_popen )
        monkeypatch.setattr( register_session.os, "kill",
                             MagicMock( side_effect=ProcessLookupError ) )
        monkeypatch.setattr( register_session.time, "sleep", MagicMock() )
        monkeypatch.setattr( register_session.os.path, "expanduser", lambda p: str( tmp_path ) )

        assert register_session._spawn_listener_locked( SESSION_ID, None, None, None ) is None
        assert "could not read stderr" in capsys.readouterr().err

    def test_popen_failure_returns_none( self, tmp_path, monkeypatch ):
        monkeypatch.setattr( register_session.subprocess, "Popen",
                             MagicMock( side_effect=RuntimeError( "spawn refused" ) ) )
        monkeypatch.setattr( register_session.os.path, "expanduser", lambda p: str( tmp_path ) )
        assert register_session._spawn_listener_locked( SESSION_ID, None, None, None ) is None


class TestDoubleFireRegression:
    """
    REGRESSION: two concurrent SessionStart hooks (the `--continue`
    double-fire) race _spawn_listener for the same session hash. Pre-fix:
    two listeners. Post-fix: the flock serializes check-then-spawn, the
    loser sees the winner's listener, exactly ONE Popen happens and both
    callers return the SAME PID.
    """

    def test_concurrent_spawns_yield_one_listener( self, lock_dir, tmp_path, monkeypatch ):
        spawned = [ ]          # PIDs visible to "pgrep" — append-on-spawn
        results = { }

        def fake_find( session_hash ):
            return sorted( spawned )

        def fake_popen( *args, **kwargs ):
            time.sleep( 0.1 )  # widen the race window pre-fix code would lose
            proc     = MagicMock()
            proc.pid = 9000 + len( spawned )
            spawned.append( proc.pid )
            return proc

        monkeypatch.setattr( register_session, "find_live_listener_pids", fake_find )
        monkeypatch.setattr( register_session.subprocess, "Popen", fake_popen )
        monkeypatch.setattr( register_session.os, "kill", MagicMock() )
        monkeypatch.setattr( register_session.time, "sleep", MagicMock() )
        monkeypatch.setattr( register_session.os.path, "expanduser",
                             lambda p: str( tmp_path ) )

        def hook_fire( name ):
            session_file = tmp_path / f"cc-{name}.json"
            results[ name ] = register_session._spawn_listener(
                SESSION_ID, { "session_id": SESSION_ID }, str( session_file )
            )

        threads = [ threading.Thread( target=hook_fire, args=( n, ) ) for n in ( "a", "b" ) ]
        for t in threads: t.start()
        for t in threads: t.join( timeout=10 )

        assert len( spawned ) == 1, f"double-fire spawned {len( spawned )} listeners: {spawned}"
        assert results[ "a" ] == results[ "b" ] == spawned[ 0 ]
