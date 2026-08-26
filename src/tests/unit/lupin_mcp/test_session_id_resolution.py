"""
Unit tests for cosa_voice_mcp's session-id resolution band: the watcher thread,
the hard-exit path, and the gate every ask/notify passes through.

WHY THIS BAND IS DELICATE
`SESSION_ID` / `SENDER_ID` decide which seat a notification is attributed to. Get
it wrong and a message lands under another persona's name; fail to resolve it and
the MCP server kills itself on purpose rather than send mis-attributed traffic.
None of those decisions had tests.

⚠️ TWO REAL HAZARDS, HANDLED EXPLICITLY

  1. `_die_no_session_id` calls `os._exit( 1 )`. That bypasses pytest, atexit and
     every finally block — an unpatched call would kill the test RUN, not fail a
     test. `os._exit` is replaced in every test that can reach it.

  2. `_session_watcher_thread`'s phase 2 is `while True`. It is driven here by a
     `time.sleep` that raises a sentinel after a set number of iterations, which
     is also what bounds the test. The module already starts a REAL watcher
     daemon at import, so every module global these tests touch — SESSION_ID,
     SENDER_ID, _session_failed, _session_ready — is restored by an autouse
     fixture, and `_session_ready` is swapped for a fresh Event so a test can
     never leave the live one in a state the running daemon did not set.

Venue: :7999-eligible — no server, no network, no new threads.
"""

import threading

import pytest

import lupin_mcp.cosa_voice_mcp as cv


class _StopLoop( BaseException ):
    """
    Sentinel used to break the watcher's `while True` from inside sleep.

    BaseException, NOT Exception, and that is load-bearing: the loop body ends in
    `except Exception`, so an Exception-derived sentinel is CAUGHT BY THE CODE
    UNDER TEST and the loop spins forever. Deriving from BaseException is what
    lets it escape the very handler this file also has to exercise.
    """


class _Exited( Exception ):
    """Stands in for os._exit so a test can observe the call instead of dying."""


@pytest.fixture( autouse=True )
def _isolate_session_globals( monkeypatch ):
    monkeypatch.setattr( cv, "SESSION_ID", "aaaaaaaa", raising=False )
    monkeypatch.setattr( cv, "SENDER_ID", "claude.code@lupin.deepily.ai#aaaaaaaa", raising=False )
    monkeypatch.setattr( cv, "_session_failed", False, raising=False )
    monkeypatch.setattr( cv, "_session_ready", threading.Event(), raising=False )


def _sleeper( iterations ):
    """A time.sleep that lets the loop run `iterations` times, then breaks it."""
    state = { "n": 0 }
    def _sleep( _seconds ):
        state[ "n" ] += 1
        if state[ "n" ] > iterations:
            raise _StopLoop
    return _sleep


def _run_watcher( monkeypatch, iterations=1 ):
    monkeypatch.setattr( cv.time, "sleep", _sleeper( iterations ) )
    with pytest.raises( _StopLoop ):
        cv._session_watcher_thread()


# ── phase 1: initial resolution ───────────────────────────────────────────────

class TestWatcherInitialResolution:

    def test_a_resolved_id_upgrades_both_the_session_and_the_sender( self, monkeypatch, caplog ):
        monkeypatch.setattr( cv, "wait_for_session_id", lambda **k: "bbbbbbbb-1111-2222" )
        monkeypatch.setattr( cv, "_get_cc_metadata", lambda: { "source": "session_file" } )
        monkeypatch.setattr( cv, "CANONICAL_PROJECT", "lupin", raising=False )
        monkeypatch.setattr( cv.time, "sleep", _sleeper( 0 ) )

        with caplog.at_level( "INFO", logger=cv.logger.name ), pytest.raises( _StopLoop ):
            cv._session_watcher_thread()

        assert cv.SESSION_ID == "bbbbbbbb"
        assert cv.SENDER_ID  == "claude.code@lupin.deepily.ai#bbbbbbbb"
        assert "Session ID upgraded" in caplog.text
        assert cv._session_ready.is_set()

    def test_a_fallback_source_warns_that_no_bridge_was_found( self, monkeypatch, caplog ):
        """
        A fallback sender_id is STABLE but not this seat's — messages sent under
        it are attributed to a project rather than a session. The warning is the
        only signal that the roster will not show this seat.
        """
        monkeypatch.setattr( cv, "wait_for_session_id", lambda **k: "aaaaaaaa-x" )
        monkeypatch.setattr( cv, "_get_cc_metadata", lambda: { "source": "fallback" } )
        monkeypatch.setattr( cv.time, "sleep", _sleeper( 0 ) )

        with caplog.at_level( "WARNING", logger=cv.logger.name ), pytest.raises( _StopLoop ):
            cv._session_watcher_thread()

        assert "No session bridge file found" in caplog.text
        assert "stable fallback sender_id" in caplog.text

    def test_a_failed_resolution_sets_the_failure_flag_and_still_opens_the_gate( self, monkeypatch, caplog ):
        """
        `_session_ready` is set in a `finally`, so callers blocked on the gate are
        released even when resolution failed. They then read `_session_failed` and
        take the exit path — waiting forever would be the worse outcome.
        """
        def boom( **k ):
            raise RuntimeError( "no bridge ever appeared" )
        monkeypatch.setattr( cv, "wait_for_session_id", boom )
        monkeypatch.setattr( cv.time, "sleep", _sleeper( 0 ) )

        with caplog.at_level( "CRITICAL", logger=cv.logger.name ), pytest.raises( _StopLoop ):
            cv._session_watcher_thread()

        assert cv._session_failed is True
        assert cv._session_ready.is_set()
        assert "Session ID resolution failed" in caplog.text


# ── phase 2: the persistent bridge watcher ────────────────────────────────────

class TestWatcherMonitoringLoop:

    def _phase1_ok( self, monkeypatch ):
        monkeypatch.setattr( cv, "wait_for_session_id", lambda **k: "aaaaaaaa-x" )
        monkeypatch.setattr( cv, "_get_cc_metadata", lambda: { "source": "session_file" } )
        monkeypatch.setattr( cv, "clear_cached_session_id", lambda: None )
        monkeypatch.setattr( cv, "CANONICAL_PROJECT", "lupin", raising=False )

    def test_a_changed_bridge_id_is_picked_up_as_a_context_clear( self, monkeypatch, tmp_path, caplog ):
        self._phase1_ok( monkeypatch )
        bridge = tmp_path / "cc-bridge.json"
        bridge.write_text( "{}" )
        monkeypatch.setattr( cv, "_find_session_file", lambda: ( bridge, "session_file" ) )
        monkeypatch.setattr( cv, "_read_session_file", lambda p: "cccccccc-9999" )

        with caplog.at_level( "INFO", logger=cv.logger.name ):
            _run_watcher( monkeypatch, iterations=1 )

        assert cv.SESSION_ID == "cccccccc"
        assert cv.SENDER_ID  == "claude.code@lupin.deepily.ai#cccccccc"
        assert "context clear detected" in caplog.text

    def test_no_bridge_file_is_skipped_rather_than_treated_as_a_change( self, monkeypatch ):
        self._phase1_ok( monkeypatch )
        monkeypatch.setattr( cv, "_find_session_file", lambda: None )

        _run_watcher( monkeypatch, iterations=2 )

        assert cv.SESSION_ID == "aaaaaaaa"                 # untouched

    def test_an_unstattable_bridge_is_skipped_not_fatal( self, monkeypatch, tmp_path ):
        # The bridge can vanish between the lookup and the stat — a live fleet
        # rewrites these files constantly.
        self._phase1_ok( monkeypatch )
        missing = tmp_path / "gone.json"
        monkeypatch.setattr( cv, "_find_session_file", lambda: ( missing, "session_file" ) )

        _run_watcher( monkeypatch, iterations=2 )

        assert cv.SESSION_ID == "aaaaaaaa"

    def test_an_unreadable_or_empty_bridge_is_skipped( self, monkeypatch, tmp_path ):
        self._phase1_ok( monkeypatch )
        bridge = tmp_path / "cc-bridge.json"
        bridge.write_text( "{}" )
        monkeypatch.setattr( cv, "_find_session_file", lambda: ( bridge, "session_file" ) )
        monkeypatch.setattr( cv, "_read_session_file", lambda p: None )

        _run_watcher( monkeypatch, iterations=1 )

        assert cv.SESSION_ID == "aaaaaaaa"

    def test_an_unexpected_error_is_logged_and_the_loop_survives_it( self, monkeypatch, caplog ):
        """
        This is a daemon with no supervisor. If an iteration could kill it, a
        single transient error would silently end context-clear detection for the
        rest of the process's life.
        """
        self._phase1_ok( monkeypatch )
        def boom():
            raise RuntimeError( "lookup exploded" )
        monkeypatch.setattr( cv, "_find_session_file", boom )

        with caplog.at_level( "ERROR", logger=cv.logger.name ):
            _run_watcher( monkeypatch, iterations=2 )      # ran twice, survived both

        assert "Session watcher error" in caplog.text


# ── the hard-exit path ────────────────────────────────────────────────────────

class TestDieNoSessionId:

    def test_alerts_from_the_mcp_error_sender_then_exits_nonzero( self, monkeypatch ):
        sent = {}
        monkeypatch.setattr( cv, "notify_user_async",
                             lambda request, debug: sent.update( req=request ) )
        monkeypatch.setattr( cv.os, "_exit", lambda code: ( _ for _ in () ).throw( _Exited( code ) ) )

        with pytest.raises( _Exited ) as ei:
            cv._die_no_session_id()

        assert ei.value.args[ 0 ] == 1
        assert sent[ "req" ].sender_id.endswith( "#mcp-error" )
        assert sent[ "req" ].priority.value == "high"
        assert "Restart Claude Code" in sent[ "req" ].message

    def test_it_exits_even_when_the_alert_cannot_be_sent( self, monkeypatch, caplog ):
        # The exit is the point. A server that cannot be told is still a server
        # that must not keep sending mis-attributed traffic.
        def boom( request, debug ):
            raise RuntimeError( "server down" )
        monkeypatch.setattr( cv, "notify_user_async", boom )
        monkeypatch.setattr( cv.os, "_exit", lambda code: ( _ for _ in () ).throw( _Exited( code ) ) )

        with caplog.at_level( "ERROR", logger=cv.logger.name ), pytest.raises( _Exited ):
            cv._die_no_session_id()

        assert "Failed to send error notification" in caplog.text


# ── the gate every ask and notify passes through ──────────────────────────────

class TestWaitForSenderId:

    def test_returns_the_sender_id_once_resolution_has_completed( self ):
        cv._session_ready.set()
        assert cv._wait_for_sender_id( timeout=0.1 ) == cv.SENDER_ID

    def test_a_gate_that_never_opens_takes_the_exit_path( self, monkeypatch ):
        called = []
        monkeypatch.setattr( cv, "_die_no_session_id", lambda: called.append( True ) )
        cv._wait_for_sender_id( timeout=0.01 )             # event never set
        assert called == [ True ]

    def test_a_resolution_that_failed_takes_the_exit_path_even_though_the_gate_opened( self, monkeypatch ):
        # The gate opens in a `finally` regardless of outcome, so "opened" alone
        # does not mean "resolved". The flag is the real verdict.
        called = []
        monkeypatch.setattr( cv, "_die_no_session_id", lambda: called.append( True ) )
        monkeypatch.setattr( cv, "_session_failed", True, raising=False )
        cv._session_ready.set()

        cv._wait_for_sender_id( timeout=0.1 )
        assert called == [ True ]
