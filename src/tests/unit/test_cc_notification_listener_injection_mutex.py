"""
Unit tests for the F4 tmux injection mutex in
src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py::_inject_via_tmux.

The duplicate-listener failure mode: two listeners racing the two-step
injection ("type text" then "Enter") interleave keystrokes in one pane —
text A, text B, Enter, Enter — silently corrupting broadcast delivery.
The per-tmux-session flock keeps each text+Enter pair atomic.

Per src/rnd/v0.1.8/2026.06.11-broadcast-miss-f1-f4-implementation.md §2.5.
"""

import threading
import time
from unittest.mock import MagicMock

import pytest

import lupin_cli.claude_code.hooks.lib.cc_notification_listener as listener_module
import lupin_cli.claude_code.hooks.lib.listener_processes as listener_processes
from lupin_cli.claude_code.hooks.lib.cc_notification_listener import CCNotificationListener


def _make_listener( session_id_hash="abc12345", tmux_session="test tmux" ):
    """Listener with explicit tmux override — no bridge lookup, no WS connect."""
    return CCNotificationListener(
        email           = "service@lupin.deepily.ai",
        password        = "service-pass",
        session_id_hash = session_id_hash,
        tmux_session    = tmux_session,
        host            = "localhost",
        port            = 7999,
        debug           = False,
        verbose         = False,
    )


@pytest.fixture
def lock_dir( tmp_path, monkeypatch ):
    """Isolate the injection lock files from the real ~/.claude/sessions."""
    # Row 8ccc20ab: the lock dir resolves through sessions_dir() at CALL time.
    monkeypatch.setenv( "LUPIN_HOOK_SESSIONS_DIR", str( tmp_path ) )
    return tmp_path


class TestInjectionMutexSerialization:

    def test_concurrent_injections_do_not_interleave( self, lock_dir, monkeypatch ):
        """
        REGRESSION: two injectors racing one tmux session. Without the
        mutex the recorded keystroke stream interleaves (text, text,
        Enter, Enter); with it, each text is immediately followed by
        its own Enter.
        """
        events       = [ ]
        events_guard = threading.Lock()

        def fake_run( cmd, **kwargs ):
            kind = "enter" if cmd[ -1 ] == "Enter" else "text"
            with events_guard:
                events.append( kind )
            return MagicMock( returncode=0 )

        monkeypatch.setattr( listener_module.subprocess, "run", fake_run )
        real_sleep = time.sleep  # capture BEFORE patching — listener_module.time IS the global module
        monkeypatch.setattr( listener_module.time, "sleep", lambda s: real_sleep( 0.05 ) )

        listeners = [ _make_listener(), _make_listener() ]  # same tmux session
        threads   = [
            threading.Thread( target=l._inject_via_tmux, args=( f"msg-{i}", False ) )
            for i, l in enumerate( listeners )
        ]
        for t in threads: t.start()
        for t in threads: t.join( timeout=10 )

        assert events == [ "text", "enter", "text", "enter" ], (
            f"interleaved keystroke stream: {events}"
        )

    def test_different_tmux_sessions_do_not_serialize( self, lock_dir, monkeypatch ):
        """Locks are PER tmux session — distinct panes inject independently."""
        order = [ ]

        def fake_run( cmd, **kwargs ):
            order.append( ( cmd[ 3 ], "enter" if cmd[ -1 ] == "Enter" else "text" ) )
            return MagicMock( returncode=0 )

        monkeypatch.setattr( listener_module.subprocess, "run", fake_run )
        monkeypatch.setattr( listener_module.time, "sleep", MagicMock() )

        a = _make_listener( tmux_session="pane a" )
        b = _make_listener( tmux_session="pane b" )
        a._inject_via_tmux( "hello", wrap=False )
        b._inject_via_tmux( "world", wrap=False )

        assert ( lock_dir / "tmux-inject-pane_a.lock" ).exists()
        assert ( lock_dir / "tmux-inject-pane_b.lock" ).exists()
        assert len( order ) == 4


class TestInjectionMutexFailOpen:

    def test_lock_unavailable_still_injects( self, lock_dir, monkeypatch ):
        """Fail-open: a broken lock layer must never block delivery."""
        run_mock = MagicMock( return_value=MagicMock( returncode=0 ) )
        monkeypatch.setattr( listener_module.subprocess, "run", run_mock )
        monkeypatch.setattr( listener_module.time, "sleep", MagicMock() )

        # Force acquisition failure: the seam points at a FILE, so the
        # lock-file open fails (NotADirectoryError ⊂ OSError) → held=False.
        blocker = lock_dir / "blocker"
        blocker.write_text( "x" )
        monkeypatch.setenv( "LUPIN_HOOK_SESSIONS_DIR", str( blocker ) )

        logged = [ ]
        l = _make_listener()
        monkeypatch.setattr( l, "_log", logged.append )

        l._inject_via_tmux( "still delivered", wrap=False )

        assert run_mock.call_count == 2  # text + Enter both sent
        assert any( "injection lock unavailable" in m for m in logged )

    def test_injection_failure_logged_not_raised( self, lock_dir, monkeypatch ):
        monkeypatch.setattr( listener_module.subprocess, "run",
                             MagicMock( side_effect=FileNotFoundError( "tmux" ) ) )
        logged = [ ]
        l = _make_listener()
        monkeypatch.setattr( l, "_log", logged.append )

        l._inject_via_tmux( "boom", wrap=False )  # must not raise

        assert any( "tmux injection failed" in m for m in logged )


class TestInjectionPreLockPaths:
    """The pre-mutex paths of _inject_via_tmux — tmux resolution + wrap."""

    def test_no_tmux_session_skips_injection( self, lock_dir, monkeypatch ):
        run_mock = MagicMock()
        monkeypatch.setattr( listener_module.subprocess, "run", run_mock )
        logged = [ ]
        l = _make_listener( tmux_session=None )
        monkeypatch.setattr( l, "_resolve_tmux_session", lambda: None )
        monkeypatch.setattr( l, "_log", logged.append )

        l._inject_via_tmux( "nowhere to go" )

        run_mock.assert_not_called()
        assert any( "No tmux session found" in m for m in logged )

    def test_wrap_true_applies_speakerphone_wrap( self, lock_dir, monkeypatch ):
        import lupin_cli.claude_code.hooks.lib.hook_common as hook_common
        monkeypatch.setattr( hook_common, "speakerphone_wrap",
                             lambda text, source, session_id: f"<wrapped>{text}</wrapped>" )
        sent = [ ]
        def fake_run( cmd, **kwargs ):
            sent.append( cmd )
            return MagicMock( returncode=0 )
        monkeypatch.setattr( listener_module.subprocess, "run", fake_run )
        monkeypatch.setattr( listener_module.time, "sleep", MagicMock() )

        l = _make_listener()
        l._inject_via_tmux( "voice msg", wrap=True )

        assert sent[ 0 ][ -1 ] == "<wrapped>voice msg</wrapped>"

    def test_wrap_failure_falls_through_unwrapped( self, lock_dir, monkeypatch ):
        import lupin_cli.claude_code.hooks.lib.hook_common as hook_common
        def _exploding_wrap( text, source, session_id ):
            raise RuntimeError( "bridge unreadable" )
        monkeypatch.setattr( hook_common, "speakerphone_wrap", _exploding_wrap )
        sent = [ ]
        def fake_run( cmd, **kwargs ):
            sent.append( cmd )
            return MagicMock( returncode=0 )
        monkeypatch.setattr( listener_module.subprocess, "run", fake_run )
        monkeypatch.setattr( listener_module.time, "sleep", MagicMock() )
        logged = [ ]
        l = _make_listener()
        monkeypatch.setattr( l, "_log", logged.append )

        l._inject_via_tmux( "raw msg", wrap=True )

        assert sent[ 0 ][ -1 ] == "raw msg"
        assert any( "speakerphone_wrap failed" in m for m in logged )
