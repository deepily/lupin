#!/usr/bin/env python3
"""
Unit tests for the v2.1 direct-state liveness primitives in session_bridge:

    - touch_bridge_mtime()  — the PostToolUse / hook-side bare os.utime stamp
                              (arbiter design `03` §10.1, redline C1)
    - get_bridge_mtime()    — the arbiter-side liveness reader (§10.1/§10.2)

100% line + branch coverage of both functions (the SWE-team hard gate).
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import lupin_cli.claude_code.hooks.lib.session_bridge as sb
from lupin_cli.claude_code.hooks.lib.session_bridge import (
    touch_bridge_mtime, get_bridge_mtime, get_bridge_touch_failure_count,
)


@pytest.fixture( autouse=True )
def _reset_failure_observability():
    """Reset the process-global liveness-stamp failure counter/log flag per test."""
    sb._bridge_touch_failure_count  = 0
    sb._bridge_touch_failure_logged = False
    yield
    sb._bridge_touch_failure_count  = 0
    sb._bridge_touch_failure_logged = False


# ── Helpers ──────────────────────────────────────────────────────────────────

def _write_session_file( sessions_dir, pid, session_id ):
    """Write a minimal session bridge file cc-{pid}.json and return its Path."""
    path = sessions_dir / f"cc-{pid}.json"
    data = {
        "session_id"        : session_id,
        "stable_session_id" : session_id,
        "cwd"               : "/tmp",
        "cc_pid"            : os.getpid(),
    }
    with open( path, "w" ) as f:
        json.dump( data, f )
    return path


# ── touch_bridge_mtime ───────────────────────────────────────────────────────

class TestTouchBridgeMtime:

    def test_touches_resolved_bridge_via_ppid( self ):
        """Real-resolution path: cc-{ppid}.json is found and its mtime bumped."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            # _find_session_file() resolves cc-{os.getppid()}.json first (PPID hit).
            path = _write_session_file( sessions_dir, os.getppid(), "sid-aaa" )

            # Age the file 1 hour into the past so the bump is unambiguous.
            old = time.time() - 3600
            os.utime( path, ( old, old ) )

            with patch.object( sb, "SESSION_DIR", sessions_dir ):
                result = touch_bridge_mtime()

            assert result is True
            # mtime moved forward to ~now (well past the aged value).
            assert path.stat().st_mtime > old + 1000

    def test_metadata_only_no_content_write( self ):
        """REDLINE C1: the stamp must NOT alter file content (JSON-corruption gate)."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            path   = _write_session_file( sessions_dir, os.getppid(), "sid-bbb" )
            before = path.read_bytes()

            with patch.object( sb, "SESSION_DIR", sessions_dir ):
                touch_bridge_mtime()

            assert path.read_bytes() == before   # byte-identical → no write occurred

    def test_returns_false_when_no_bridge_resolves( self ):
        """No bridge file found → False, no raise (and not counted as a failure)."""
        with patch.object( sb, "_find_session_file", return_value=None ):
            assert touch_bridge_mtime() is False
        # "no bridge yet" is a normal pre-SessionStart state, NOT a fault.
        assert get_bridge_touch_failure_count() == 0

    # ── Fault injection (María Steward gate #1): prove never-raises under the
    #    real LIVE filesystem failure modes, not just well-formed input. ────────

    def test_fault_missing_bridge_dir( self ):
        """(a) Missing ~/.claude/sessions dir → swallowed no-op."""
        with tempfile.TemporaryDirectory() as tmp:
            gone = Path( tmp ) / "does-not-exist"          # never created
            with patch.object( sb, "SESSION_DIR", gone ):
                assert touch_bridge_mtime() is False        # _find_session_file → None

    def test_fault_permission_denied_eperm( self ):
        """(b) EPERM on os.utime (permission flip on the bridge) → swallowed."""
        fake = ( Path( "/locked/cc-1.json" ), "ppid" )
        with patch.object( sb, "_find_session_file", return_value=fake ), \
             patch.object( sb.os, "utime", side_effect=PermissionError( 13, "EPERM" ) ):
            assert touch_bridge_mtime() is False
        assert get_bridge_touch_failure_count() == 1

    def test_fault_enoent_path_unlinked( self ):
        """(c) ENOENT on os.utime (bridge unlinked) → swallowed."""
        fake = ( Path( "/tmp/cc-vanished.json" ), "ppid" )
        with patch.object( sb, "_find_session_file", return_value=fake ), \
             patch.object( sb.os, "utime", side_effect=FileNotFoundError( 2, "ENOENT" ) ):
            assert touch_bridge_mtime() is False
        assert get_bridge_touch_failure_count() == 1

    def test_fault_fs_race_getcwd_fails( self ):
        """(d) FS race: cwd deleted mid-resolution (os.getcwd → FileNotFoundError) → swallowed."""
        with patch.object( sb, "_find_session_file", side_effect=FileNotFoundError( 2, "cwd gone" ) ):
            assert touch_bridge_mtime() is False
        assert get_bridge_touch_failure_count() == 1

    def test_fault_non_oserror_never_propagates( self ):
        """Fail-safe (§10.6): even a NON-OSError never escapes a tool call."""
        with patch.object( sb, "_find_session_file", side_effect=RuntimeError( "unexpected" ) ):
            assert touch_bridge_mtime() is False
        assert get_bridge_touch_failure_count() == 1


# ── Observability rider (María Steward gate #2) ───────────────────────────────

class TestTouchFailureObservability:

    def test_counter_accumulates_across_failures( self ):
        """The in-memory counter increments on each swallowed failure."""
        with patch.object( sb, "_find_session_file", side_effect=OSError( "x" ) ):
            touch_bridge_mtime(); touch_bridge_mtime(); touch_bridge_mtime()
        assert get_bridge_touch_failure_count() == 3

    def test_stderr_logged_once_only( self ):
        """A one-shot stderr line fires on the FIRST failure only (no per-call spam)."""
        writes = [ ]
        fake_stderr = type( "S", (), { "write": lambda self, s: writes.append( s ) } )()
        with patch.object( sb, "_find_session_file", side_effect=OSError( "x" ) ), \
             patch.object( sb, "sys" ) as mock_sys:
            mock_sys.stderr = fake_stderr
            touch_bridge_mtime(); touch_bridge_mtime()
        assert len( writes ) == 1                    # logged once despite two failures
        assert "liveness stamp dropped" in writes[ 0 ]
        assert get_bridge_touch_failure_count() == 2  # but BOTH counted

    def test_stderr_write_failure_is_swallowed( self ):
        """If stderr.write itself raises, the recorder still never raises."""
        class _BoomStderr:
            def write( self, s ):
                raise OSError( "stderr closed" )
        with patch.object( sb, "_find_session_file", side_effect=OSError( "x" ) ), \
             patch.object( sb, "sys" ) as mock_sys:
            mock_sys.stderr = _BoomStderr()
            assert touch_bridge_mtime() is False     # no raise despite stderr failure
        assert get_bridge_touch_failure_count() == 1


# ── get_bridge_mtime ─────────────────────────────────────────────────────────

class TestGetBridgeMtime:

    def test_returns_mtime_for_matched_session( self ):
        """A resolvable session_id yields its bridge file's epoch mtime."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            path = _write_session_file( sessions_dir, os.getpid(), "abc12345-full-uuid" )
            stamp = time.time() - 120
            os.utime( path, ( stamp, stamp ) )

            with patch.object( sb, "SESSION_DIR", sessions_dir ):
                mtime = get_bridge_mtime( "abc12345-full-uuid" )

            assert mtime == pytest.approx( stamp, abs=1 )

    def test_returns_none_when_no_match( self ):
        """No bridge matches the id → None."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            _write_session_file( sessions_dir, os.getpid(), "present-session" )

            with patch.object( sb, "SESSION_DIR", sessions_dir ):
                assert get_bridge_mtime( "absent-session" ) is None

    def test_returns_none_on_empty_session_id( self ):
        """Empty id resolves to no path → None (find_session_path_by_id guard)."""
        assert get_bridge_mtime( "" ) is None

    def test_returns_none_and_swallows_stat_oserror( self ):
        """stat() raising OSError is swallowed → None."""
        class _BadPath:
            def stat( self ):
                raise OSError( "stat failed" )
        with patch.object( sb, "find_session_path_by_id", return_value=_BadPath() ):
            assert get_bridge_mtime( "any" ) is None

    def test_returns_none_and_swallows_any_exception( self ):
        """Fail-safe: a NON-OSError during resolution never breaks the arbiter poll."""
        with patch.object( sb, "find_session_path_by_id", side_effect=RuntimeError( "boom" ) ):
            assert get_bridge_mtime( "any" ) is None


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
