"""
The three background loops in `lupin_app/main.py`, exercised in-process.

WHY THIS FILE EXISTS. Row `e2099400` §3c. `src/lupin_app/main.py` carried 367 missing
statements when this was written, and the received explanation was that its runtime is
the `:8000` integration and e2e tiers, so unit tests should not be expected to reach it.
That is TRUE OF THE LIFESPAN FUNCTION and false of a good deal else. Measured at sha
ef63aed9 with an isolated coverage data file, the 367 break down as:

    lifespan                              274      needs a booting server
    clock_loop                             32   ┐
    websocket_cleanup_loop                 15   ├─ 61 statements: three `while True`
    websocket_heartbeat_loop               14   ┘  loops with injectable collaborators
    _managed_bounce_all_clear_blocking     12      already covered by an existing test
    _emit_managed_bounce                    5   ┐
    load_stt_model                          5   ├─ 11 statements: thin wrappers over
    _log_vram                               4   │  module globals
    _managed_bounce_server_label            2   ┘
    _run_managed_bounce_all_clear           2
    import guards                           2

The three loops need no server at all. They need a fake websocket manager and a sleep
that stops the loop — which is what this file supplies.

HOW EACH LOOP IS STOPPED. Every one of them is `while True` around a body whose last
statement is `await asyncio.sleep(...)`, wrapped in `except asyncio.CancelledError: break`.
So the sleep IS the seam: a stub that raises CancelledError on the Nth call runs the body
exactly N times and then leaves through the loop's own shutdown path. Nothing here reaches
a real clock, and no test in this file takes longer than the work it does.

⚠️ ONE ASYMMETRY WORTH KNOWING, and it is the code's, not the harness's. Each loop's
`except Exception` arm ends in its own `await asyncio.sleep(...)`, and that sleep sits
OUTSIDE the try — so a cancel arriving while the loop is backing off from an error
PROPAGATES out of the loop instead of being caught by the `except asyncio.CancelledError`
arm above it. In production that is harmless (the task is being cancelled anyway), but it
means the error-arm tests below assert a raise where the happy-path tests assert a return.

⚠️ NO REAL `record_server_available`. clock_loop hands that to a worker thread, and it
writes to the job database. `asyncio.to_thread` is stubbed for the same reason the sleep
is: a unit test that touches the real database is not a unit test.

Venue: :7999-eligible — in-process, no server, no network, no persistent-state mutation.
"""

import asyncio
import types
import unittest

from unittest import mock

from lupin_app import main


# ── the sleep stub, which is also the loop's off-switch ──────────────────────

def run_body_times( iterations, *, to_thread=None ):
    """
    A stand-in for the `asyncio` module as `main.py` sees it, whose `sleep` stops the loop.

    ⚠️ PATCH `main.asyncio`, NEVER the real `asyncio.sleep`. The first draft of this file
    patched the global and pytest died with an INTERNALERROR rather than a test failure:
    `IsolatedAsyncioTestCase` shuts its own event loop down through `asyncio.sleep`, so a
    stub that raises CancelledError on the Nth call poisons the harness's teardown, not
    just the code under test. Replacing the NAME main.py reaches through keeps the blast
    radius inside main.py.

    Requires:
        - iterations is a positive int — the number of times the loop BODY should run
        - to_thread, when supplied, is an async callable standing in for asyncio.to_thread

    Ensures:
        - the loop body runs exactly `iterations` times: the Nth sleep raises the REAL
          asyncio.CancelledError after recording its delay
        - a cancel raised inside a loop's `except Exception` arm PROPAGATES, because that
          arm's sleep is outside the try — the tests for those arms expect it
        - `.CancelledError` on the shim is the real class, so main.py's own except arm
          still matches
        - returns ( shim, calls ) where `calls` accumulates the delays asked for, so a
          test can assert WHAT the loop tried to sleep for and not merely that it slept
    """
    calls = []

    async def stub( delay ):
        # Record FIRST, then decide. The delay the loop asks for on the pass that gets
        # cancelled is still a delay it asked for, and it is the one worth asserting —
        # the error arms reach their sleep only on the pass that fails.
        calls.append( delay )
        if len( calls ) >= iterations: raise asyncio.CancelledError()
        return None

    shim = types.SimpleNamespace(
        sleep           = stub,
        to_thread       = to_thread if to_thread is not None else mock.AsyncMock( return_value=None ),
        CancelledError  = asyncio.CancelledError,
    )
    return shim, calls


class ClockLoopTest( unittest.IsolatedAsyncioTestCase ):
    """`clock_loop` — the once-a-minute time broadcast."""

    def _wire( self, *, sessions=None, emit_raises=None, heartbeat_raises=None ):
        """Build the fake websocket manager the loop talks to."""
        sessions = { } if sessions is None else sessions
        manager  = mock.MagicMock()
        manager.async_emit           = mock.AsyncMock( side_effect=emit_raises )
        manager.get_connection_count = mock.MagicMock( return_value=len( sessions ) )
        manager.active_connections   = sessions
        manager.session_to_user      = { }
        return manager

    async def test_one_pass_emits_the_time_and_sleeps_a_minute( self ):
        """The straight-line body: emit, heartbeat, sleep 60."""
        manager  = self._wire()
        shim, naps = run_body_times( 1 )

        with mock.patch.object( main, "websocket_manager", manager ), \
             mock.patch.object( main, "app_debug", False ), \
             mock.patch.object( main.du, "get_current_time", return_value="2026-08-26 @ 20:00" ), \
             mock.patch.object( main, "asyncio", shim ):
            await main.clock_loop()

        self.assertEqual( naps, [ 60 ], "the clock loop must ask for exactly 60 seconds" )
        manager.async_emit.assert_awaited_once()
        event, payload = manager.async_emit.await_args.args
        self.assertEqual( event, "sys_time_update" )
        self.assertEqual( payload[ "date" ], "2026-08-26 @ 20:00" )
        shim.to_thread.assert_awaited_once_with( main.record_server_available )

    async def test_the_environment_label_says_TEST_only_for_a_test_environment( self ):
        """
        The label the whole fleet sees in its clock. It is read ONCE before the loop, so
        a wrong reading here is wrong for the life of the process — which is the same
        shape as bug 652271f3, where the test container announced itself as the dev one.
        """
        seen = { }

        for env_value, expected in [ ( "test", "TEST" ), ( "testing", "TEST" ),
                                     ( "development", "DEVELOPMENT" ), ( "", "DEVELOPMENT" ) ]:
            manager  = self._wire()
            shim, _  = run_body_times( 1 )
            with mock.patch.dict( main.os.environ, { "LUPIN_ENV": env_value } ), \
                 mock.patch.object( main, "websocket_manager", manager ), \
                 mock.patch.object( main, "app_debug", False ), \
                 mock.patch.object( main.du, "get_current_time", return_value="t" ), \
                 mock.patch.object( main, "asyncio", shim ):
                await main.clock_loop()
            seen[ env_value ] = manager.async_emit.await_args.args[ 1 ][ "env_label" ]

        self.assertEqual( seen, { "test": "TEST", "testing": "TEST",
                                  "development": "DEVELOPMENT", "": "DEVELOPMENT" } )

    async def test_verbose_debug_prints_the_session_and_user_mapping( self ):
        """The chatty branch — only reachable with BOTH debug and verbose on."""
        manager  = self._wire( sessions={ "wise penguin": object(), "clever dolphin": object() } )
        manager.session_to_user = { "wise penguin": "rick@example.com" }
        shim, _  = run_body_times( 1 )

        with mock.patch.object( main, "websocket_manager", manager ), \
             mock.patch.object( main, "app_debug", True ), \
             mock.patch.object( main, "app_verbose", True ), \
             mock.patch.object( main.du, "get_current_time", return_value="t" ), \
             mock.patch.object( main, "asyncio", shim ):
            await main.clock_loop()

        manager.get_connection_count.assert_called_once()

    async def test_verbose_debug_with_no_connections_skips_the_session_listing( self ):
        """The other side of the `if all_sessions` branch — nobody connected."""
        manager  = self._wire( sessions={ } )
        shim, _ = run_body_times( 1 )

        with mock.patch.object( main, "websocket_manager", manager ), \
             mock.patch.object( main, "app_debug", True ), \
             mock.patch.object( main, "app_verbose", True ), \
             mock.patch.object( main.du, "get_current_time", return_value="t" ), \
             mock.patch.object( main, "asyncio", shim ):
            await main.clock_loop()

        manager.get_connection_count.assert_called_once()

    async def test_a_failing_server_available_heartbeat_does_not_stop_the_clock( self ):
        """
        The database write is best-effort. If it throws, the clock must still emit next
        minute — the time broadcast is not allowed to die because a heartbeat row failed.
        """
        manager  = self._wire()
        shim, naps = run_body_times( 2, to_thread=mock.AsyncMock( side_effect=RuntimeError( "db is down" ) ) )

        with mock.patch.object( main, "websocket_manager", manager ), \
             mock.patch.object( main, "app_debug", True ), \
             mock.patch.object( main, "app_verbose", False ), \
             mock.patch.object( main.du, "get_current_time", return_value="t" ), \
             mock.patch.object( main, "asyncio", shim ):
            await main.clock_loop()

        self.assertEqual( manager.async_emit.await_count, 2, "the clock kept ticking through the failure" )
        self.assertEqual( naps, [ 60, 60 ] )

    async def test_an_emit_failure_backs_off_a_minute_and_tries_again( self ):
        """
        The outer `except Exception` arm. A broken emit must not spin: the loop sleeps a
        full minute before retrying, which is what stops a failing broadcast from
        becoming a busy loop.
        """
        manager  = self._wire( emit_raises=RuntimeError( "socket layer exploded" ) )
        shim, naps = run_body_times( 1 )

        with mock.patch.object( main, "websocket_manager", manager ), \
             mock.patch.object( main, "app_debug", False ), \
             mock.patch.object( main.du, "get_current_time", return_value="t" ), \
             mock.patch.object( main, "asyncio", shim ):
            with self.assertRaises( asyncio.CancelledError ):
                await main.clock_loop()

        self.assertEqual( naps, [ 60 ], "the error arm must back off, not retry immediately" )


class WebsocketHeartbeatLoopTest( unittest.IsolatedAsyncioTestCase ):
    """`websocket_heartbeat_loop` — drops connections that stopped answering."""

    def _wire( self, *, interval=30, dead=0, raises=None ):
        manager = mock.MagicMock()
        manager.config_mgr.get = mock.MagicMock( return_value=interval )
        manager.heartbeat_check = mock.AsyncMock( return_value=dead, side_effect=raises )
        return manager

    async def test_the_configured_interval_is_the_one_it_sleeps( self ):
        """A hard-coded 30 would look identical on a default config — so use a value nobody defaults to."""
        manager  = self._wire( interval=7 )
        shim, naps = run_body_times( 2 )

        with mock.patch.object( main, "websocket_manager", manager ), \
             mock.patch.object( main, "app_debug", False ), \
             mock.patch.object( main, "asyncio", shim ):
            await main.websocket_heartbeat_loop()

        self.assertEqual( naps, [ 7, 7 ] )
        manager.config_mgr.get.assert_called_once_with(
            "websocket heartbeat interval seconds", default=30, return_type="int"
        )

    async def test_dead_connections_are_reported_only_when_verbose_and_only_when_nonzero( self ):
        """Both halves of the reporting guard, in one pass each."""
        for dead in ( 0, 3 ):
            manager  = self._wire( interval=5, dead=dead )
            shim, _ = run_body_times( 1 )
            with mock.patch.object( main, "websocket_manager", manager ), \
                 mock.patch.object( main, "app_debug", True ), \
                 mock.patch.object( main, "app_verbose", True ), \
                 mock.patch.object( main, "asyncio", shim ):
                await main.websocket_heartbeat_loop()
            manager.heartbeat_check.assert_awaited_once()

    async def test_a_failing_heartbeat_check_backs_off_by_the_same_interval( self ):
        """The error arm must reuse the configured interval, not a hard-coded one."""
        manager  = self._wire( interval=11, raises=RuntimeError( "check blew up" ) )
        shim, naps = run_body_times( 1 )

        with mock.patch.object( main, "websocket_manager", manager ), \
             mock.patch.object( main, "app_debug", False ), \
             mock.patch.object( main, "asyncio", shim ):
            with self.assertRaises( asyncio.CancelledError ):
                await main.websocket_heartbeat_loop()

        self.assertEqual( naps, [ 11 ] )


class WebsocketCleanupLoopTest( unittest.IsolatedAsyncioTestCase ):
    """`websocket_cleanup_loop` — drops sessions that outlived their welcome."""

    def _wire( self, *, hours=1, cleaned=0, raises=None ):
        manager = mock.MagicMock()
        manager.config_mgr.get = mock.MagicMock( return_value=hours )
        manager.auto_cleanup = mock.AsyncMock( return_value=cleaned, side_effect=raises )
        return manager

    async def test_the_interval_is_configured_in_hours_and_slept_in_seconds( self ):
        """
        The unit conversion is the whole risk in this function. Two hours must become
        7200 seconds; getting it wrong by a factor of 3600 either never cleans up or
        cleans up constantly, and neither shows as an error.
        """
        manager  = self._wire( hours=2 )
        shim, naps = run_body_times( 2 )

        with mock.patch.object( main, "websocket_manager", manager ), \
             mock.patch.object( main, "app_debug", False ), \
             mock.patch.object( main, "asyncio", shim ):
            await main.websocket_cleanup_loop()

        self.assertEqual( naps, [ 7200, 7200 ] )
        manager.config_mgr.get.assert_called_once_with(
            "websocket cleanup interval hours", default=1, return_type="int"
        )

    async def test_cleaned_sessions_are_reported_only_when_verbose_and_nonzero( self ):
        for cleaned in ( 0, 4 ):
            manager  = self._wire( hours=1, cleaned=cleaned )
            shim, _ = run_body_times( 1 )
            with mock.patch.object( main, "websocket_manager", manager ), \
                 mock.patch.object( main, "app_debug", True ), \
                 mock.patch.object( main, "app_verbose", True ), \
                 mock.patch.object( main, "asyncio", shim ):
                await main.websocket_cleanup_loop()
            manager.auto_cleanup.assert_awaited_once()

    async def test_a_failing_cleanup_backs_off_by_the_converted_interval( self ):
        """The error arm sleeps SECONDS too — a bug here would back off for 3 hours or 3 seconds."""
        manager  = self._wire( hours=3, raises=RuntimeError( "cleanup blew up" ) )
        shim, naps = run_body_times( 1 )

        with mock.patch.object( main, "websocket_manager", manager ), \
             mock.patch.object( main, "app_debug", False ), \
             mock.patch.object( main, "asyncio", shim ):
            with self.assertRaises( asyncio.CancelledError ):
                await main.websocket_cleanup_loop()

        self.assertEqual( naps, [ 10800 ] )
