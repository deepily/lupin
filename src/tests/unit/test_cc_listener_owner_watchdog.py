"""
Unit tests for the CC-listener OWNER WATCHDOG — the self-reap that ends the
stranded-listener bug (2026-07-14).

WHY THIS EXISTS

The listener is spawned with `start_new_session=True` (register_session.py), i.e.
setsid'd to PPID 1. That deliberately detaches it from its pane — so the SIGHUP tmux
sends every pane when the tmux SERVER dies never reaches it. Its only other reaper was
`session_end.py`, which sends SIGTERM and runs ONLY on a graceful SessionEnd. And its
run loop is `while self._running:` — reconnect forever, restart forever, never once
asking whether the session that owns it still exists.

So any ABRUPT death (tmux kill-server, crash, SIGKILL) orphaned the listener
permanently: still authenticated, still holding a WebSocket to the notifications UI.
On 2026-07-14 the tmux server died twice (14:12 and 14:55, whole cohorts at once) and
left THIRTEEN immortal listeners holding 1.8 GB.

The watchdog closes this by polling the owner's PID and calling stop() when it's gone —
the same lever SIGTERM pulls. It is death-mode agnostic, which is the whole point: it
does not care WHY the session died, only that it did.

THE PID-REUSE TRAP (and why start-time is load-bearing)

A bare `os.kill(pid, 0)` is NOT sufficient. If the owner dies and the kernel recycles
its PID onto an unrelated process, that check reports "alive" forever and the listener
never reaps itself — reintroducing the exact bug, in the one scenario nobody tests.
`owner_is_alive` therefore pins the owner's /proc start-time at boot and compares it on
every poll. `test_recycled_pid_reads_as_dead` is the test that can come out otherwise.
"""

import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import lupin_cli.claude_code.hooks.lib.listener_processes as listener_processes
import lupin_cli.claude_code.hooks.register_session as register_session
from lupin_cli.claude_code.hooks.lib.cc_notification_listener import (
    CCNotificationListener,
    MEMORY_GROWTH_DUMP_THRESHOLD_MB,
    OWNER_WATCHDOG_INTERVAL_SECONDS,
    owner_is_alive,
    read_proc_starttime,
    read_self_rss_mb,
)
from lupin_cli.claude_code.hooks.register_session import _resolve_owner_pid


LISTENER_MOD = "lupin_cli.claude_code.hooks.lib.cc_notification_listener"
SESSION_ID   = "abc12345-6789-abcd-ef01-234567890abc"


@pytest.fixture
def lock_dir( tmp_path, monkeypatch ):
    """Isolate the spawn-lock files from the real ~/.claude/sessions."""
    monkeypatch.setattr( listener_processes, "SESSION_DIR", tmp_path )
    return tmp_path


@pytest.fixture
def spawn_rig( lock_dir, tmp_path, monkeypatch ):
    """Drive the REAL _spawn_listener with Popen captured, and hand back the argv it built."""
    monkeypatch.setattr( register_session, "find_live_listener_pids", MagicMock( return_value=[ ] ) )
    proc       = MagicMock()
    proc.pid   = 7777
    popen_mock = MagicMock( return_value=proc )
    monkeypatch.setattr( register_session.subprocess, "Popen", popen_mock )
    monkeypatch.setattr( register_session.os, "kill", MagicMock() )
    monkeypatch.setattr( register_session.time, "sleep", MagicMock() )
    monkeypatch.setattr( register_session.os.path, "expanduser", lambda p: str( tmp_path ) )
    return popen_mock, tmp_path


# ═════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════════

def _make_listener( owner_pid=None, memory_trace=False ):
    """A listener with logging stubbed — we assert on behaviour, not on stdout."""
    listener = CCNotificationListener(
        email           = "service@lupin.deepily.ai",
        password        = "service-pass",
        session_id_hash = "abc12345",
        owner_pid       = owner_pid,
        memory_trace    = memory_trace,
    )
    listener._log         = MagicMock()
    listener._log_central = MagicMock()
    return listener


# ═════════════════════════════════════════════════════════════════════════════
# read_proc_starttime
# ═════════════════════════════════════════════════════════════════════════════

class TestReadProcStarttime:

    def test_live_process_yields_a_numeric_starttime( self ):
        """POSITIVE CONTROL. If this ever fails, every 'dead' verdict below is worthless."""
        import os
        starttime = read_proc_starttime( os.getpid() )
        assert starttime is not None
        assert starttime.isdigit()

    def test_dead_pid_yields_none( self ):
        assert read_proc_starttime( 999_999 ) is None

    def test_unreadable_proc_yields_none( self ):
        with patch( "builtins.open", side_effect=PermissionError( "nope" ) ):
            assert read_proc_starttime( 1 ) is None

    def test_oserror_yields_none( self ):
        with patch( "builtins.open", side_effect=OSError( "io" ) ):
            assert read_proc_starttime( 1 ) is None

    def test_stat_without_close_paren_yields_none( self ):
        """A malformed /proc line must not raise — it must read as 'unknown'."""
        mock_file = MagicMock()
        mock_file.read.return_value = "123 claude-with-no-paren 0 0"
        with patch( "builtins.open", MagicMock( return_value=MagicMock(
            __enter__=MagicMock( return_value=mock_file ), __exit__=MagicMock() ) ) ):
            assert read_proc_starttime( 123 ) is None

    def test_truncated_stat_yields_none( self ):
        """Fewer than 20 post-comm fields means field 22 isn't there. Do not IndexError."""
        mock_file = MagicMock()
        mock_file.read.return_value = "123 (claude) S 1 2 3"
        with patch( "builtins.open", MagicMock( return_value=MagicMock(
            __enter__=MagicMock( return_value=mock_file ), __exit__=MagicMock() ) ) ):
            assert read_proc_starttime( 123 ) is None

    def test_comm_containing_spaces_and_parens_still_parses( self ):
        """
        The tmux server's comm is literally 'tmux: server' — spaces. Others embed ')'.
        Splitting on whitespace from the left would mis-index; we split after the LAST ')'.
        """
        fields = " ".join( str( i ) for i in range( 3, 25 ) )   # state..., 22 fields
        mock_file = MagicMock()
        mock_file.read.return_value = f"123 (weird (comm) here) {fields}"
        with patch( "builtins.open", MagicMock( return_value=MagicMock(
            __enter__=MagicMock( return_value=mock_file ), __exit__=MagicMock() ) ) ):
            # fields_after_comm[0] == "3" (state), so index 19 == "22"
            assert read_proc_starttime( 123 ) == "22"


# ═════════════════════════════════════════════════════════════════════════════
# owner_is_alive — the PID-reuse guard
# ═════════════════════════════════════════════════════════════════════════════

class TestOwnerIsAlive:

    def test_live_owner_with_matching_starttime_is_alive( self ):
        import os
        me = os.getpid()
        assert owner_is_alive( me, read_proc_starttime( me ) ) is True

    def test_dead_owner_is_dead( self ):
        assert owner_is_alive( 999_999, "12345" ) is False

    def test_recycled_pid_reads_as_dead( self ):
        """
        🔴 THE ONE THAT MATTERS. The PID exists, but it is NOT our owner — the kernel
        recycled it onto something else. A bare os.kill(pid, 0) says "alive" here and
        the listener never reaps itself. Start-time is what makes this come out DEAD.
        """
        import os
        me = os.getpid()
        assert read_proc_starttime( me ) != "1"          # guard the fixture's premise
        assert owner_is_alive( me, "1" ) is False

    def test_unpinned_starttime_falls_back_to_bare_existence( self ):
        """Couldn't read /proc at boot: weaker check, but strictly better than never checking."""
        import os
        assert owner_is_alive( os.getpid(), None ) is True
        assert owner_is_alive( 999_999, None ) is False


# ═════════════════════════════════════════════════════════════════════════════
# _watch_owner — the reap itself
# ═════════════════════════════════════════════════════════════════════════════

class TestWatchOwner:

    @pytest.mark.asyncio
    async def test_no_owner_pid_disables_watchdog_LOUDLY( self ):
        """
        A silently-disabled watchdog is the bug wearing a fix's clothes. If we can't
        watch the owner, SAY SO — don't return quietly and let the listener go immortal.
        """
        listener = _make_listener( owner_pid=None )

        await listener._watch_owner()

        logged = " ".join( str( c ) for c in listener._log.call_args_list )
        assert "DISABLED" in logged
        assert "WARNING"  in logged

    @pytest.mark.asyncio
    async def test_dead_owner_triggers_self_reap( self ):
        """The whole point: owner gone -> stop() -> the run loop unwinds like it got SIGTERM."""
        listener          = _make_listener( owner_pid=4242 )
        listener._running = True
        listener.stop     = AsyncMock()

        with patch( f"{LISTENER_MOD}.asyncio.sleep", new=AsyncMock() ), \
             patch( f"{LISTENER_MOD}.owner_is_alive", return_value=False ):
            await listener._watch_owner()

        listener.stop.assert_awaited_once()
        assert "SELF-REAPED" in " ".join( str( c ) for c in listener._log_central.call_args_list )

    @pytest.mark.asyncio
    async def test_live_owner_does_not_reap( self ):
        """A living session must never be reaped by its own watchdog. False positives are fatal."""
        listener          = _make_listener( owner_pid=4242 )
        listener._running = True
        listener.stop     = AsyncMock()

        calls = { "n": 0 }

        async def _sleep( _ ):
            # Let the loop turn 3 times against a LIVE owner, then release it.
            calls[ "n" ] += 1
            if calls[ "n" ] >= 3:
                listener._running = False

        with patch( f"{LISTENER_MOD}.asyncio.sleep", new=_sleep ), \
             patch( f"{LISTENER_MOD}.owner_is_alive", return_value=True ):
            await listener._watch_owner()

        listener.stop.assert_not_awaited()
        assert calls[ "n" ] == 3

    @pytest.mark.asyncio
    async def test_shutdown_between_sleep_and_poll_exits_without_reaping( self ):
        """
        Graceful SIGTERM lands while we're asleep. On wake, _running is already False —
        we must fall out of the loop, not fire a redundant stop() on a shutting-down listener.
        """
        listener          = _make_listener( owner_pid=4242 )
        listener._running = True
        listener.stop     = AsyncMock()

        async def _sleep( _ ):
            listener._running = False   # SIGTERM landed mid-sleep

        with patch( f"{LISTENER_MOD}.asyncio.sleep", new=_sleep ), \
             patch( f"{LISTENER_MOD}.owner_is_alive", return_value=False ) as alive:
            await listener._watch_owner()

        listener.stop.assert_not_awaited()
        alive.assert_not_called()       # we broke BEFORE polling

    @pytest.mark.asyncio
    async def test_armed_watchdog_announces_its_pin( self ):
        listener          = _make_listener( owner_pid=4242 )
        listener._running = False       # arm, log, then fall straight out
        await listener._watch_owner()

        logged = " ".join( str( c ) for c in listener._log.call_args_list )
        assert "watchdog armed" in logged.lower()
        assert "4242" in logged


# ═════════════════════════════════════════════════════════════════════════════
# Construction + CLI wiring
# ═════════════════════════════════════════════════════════════════════════════

class TestWiring:

    def test_owner_starttime_is_pinned_at_construction( self ):
        """Pin while the owner is CERTAINLY alive — that's what makes the compare meaningful."""
        import os
        listener = _make_listener( owner_pid=os.getpid() )
        assert listener.owner_pid        == os.getpid()
        assert listener._owner_starttime == read_proc_starttime( os.getpid() )

    def test_no_owner_pid_pins_nothing( self ):
        listener = _make_listener( owner_pid=None )
        assert listener.owner_pid        is None
        assert listener._owner_starttime is None

    def test_cli_parses_owner_pid( self ):
        from lupin_cli.claude_code.hooks.lib.cc_notification_listener import parse_args
        with patch( "sys.argv", [ "prog", "--session-id", "abc12345", "--owner-pid", "4242" ] ):
            assert parse_args().owner_pid == 4242

    def test_cli_owner_pid_defaults_to_none( self ):
        from lupin_cli.claude_code.hooks.lib.cc_notification_listener import parse_args
        with patch( "sys.argv", [ "prog", "--session-id", "abc12345" ] ):
            assert parse_args().owner_pid is None

    def test_cli_memory_trace_flag( self ):
        from lupin_cli.claude_code.hooks.lib.cc_notification_listener import parse_args
        with patch( "sys.argv", [ "prog", "--session-id", "abc12345", "--memory-trace" ] ):
            assert parse_args().memory_trace is True

    def test_cli_memory_trace_defaults_off( self ):
        from lupin_cli.claude_code.hooks.lib.cc_notification_listener import parse_args
        with patch( "sys.argv", [ "prog", "--session-id", "abc12345" ] ):
            assert parse_args().memory_trace is False

    def test_memory_trace_stored_on_listener( self ):
        assert _make_listener( memory_trace=True ).memory_trace  is True
        assert _make_listener( memory_trace=False ).memory_trace is False

    def test_poll_interval_is_sane( self ):
        """Tight enough that a strand is measured in seconds; loose enough to be free."""
        assert 5 <= OWNER_WATCHDOG_INTERVAL_SECONDS <= 60


# ═════════════════════════════════════════════════════════════════════════════
# register_session._resolve_owner_pid — the spawn-side contract
# ═════════════════════════════════════════════════════════════════════════════

class TestResolveOwnerPid:

    def test_reads_cc_pid_from_session_data( self ):
        assert _resolve_owner_pid( { "cc_pid": 212845 }, None ) == 212845

    def test_falls_back_to_the_bridge_file( self, tmp_path ):
        """
        _spawn_listener is called with `session_data if session_id else None`. On that
        branch the dict is absent — and WITHOUT this fallback the listener would spawn
        with no watchdog, silently preserving the strand on the path nobody looks at.
        """
        bridge = tmp_path / "cc-212845.json"
        bridge.write_text( json.dumps( { "cc_pid": 212845, "session_id": "abc" } ) )

        assert _resolve_owner_pid( None, str( bridge ) ) == 212845

    def test_session_data_without_cc_pid_falls_back_to_file( self, tmp_path ):
        bridge = tmp_path / "cc-9.json"
        bridge.write_text( json.dumps( { "cc_pid": 9 } ) )

        assert _resolve_owner_pid( {}, str( bridge ) ) == 9

    def test_no_sources_yields_none( self ):
        assert _resolve_owner_pid( None, None ) is None

    def test_missing_bridge_file_yields_none( self, tmp_path ):
        assert _resolve_owner_pid( None, str( tmp_path / "nope.json" ) ) is None

    def test_malformed_bridge_file_yields_none( self, tmp_path ):
        bridge = tmp_path / "bad.json"
        bridge.write_text( "{ not json" )

        assert _resolve_owner_pid( None, str( bridge ) ) is None

    def test_bridge_without_cc_pid_yields_none( self, tmp_path ):
        bridge = tmp_path / "nopid.json"
        bridge.write_text( json.dumps( { "session_id": "abc" } ) )

        assert _resolve_owner_pid( None, str( bridge ) ) is None


# ═════════════════════════════════════════════════════════════════════════════
# read_self_rss_mb
# ═════════════════════════════════════════════════════════════════════════════

class TestReadSelfRss:

    def test_returns_positive_mb_for_this_process( self ):
        rss = read_self_rss_mb()
        assert rss is not None and rss > 0

    def test_unreadable_status_yields_none( self ):
        with patch( "builtins.open", side_effect=OSError( "io" ) ):
            assert read_self_rss_mb() is None

    def test_status_without_vmrss_yields_none( self ):
        mock_file = MagicMock()
        mock_file.__iter__.return_value = iter( [ "Name:\tx\n", "State:\tR\n" ] )
        with patch( "builtins.open", MagicMock( return_value=MagicMock(
            __enter__=MagicMock( return_value=mock_file ), __exit__=MagicMock() ) ) ):
            assert read_self_rss_mb() is None


# ═════════════════════════════════════════════════════════════════════════════
# _sample_memory — the opt-in leak sampler
# ═════════════════════════════════════════════════════════════════════════════

class TestMemorySampler:

    @pytest.mark.asyncio
    async def test_disabled_by_default_is_a_noop( self ):
        """OFF must mean zero tracemalloc cost and zero log noise — it's the default path."""
        listener = _make_listener( memory_trace=False )
        with patch( f"{LISTENER_MOD}.tracemalloc.start" ) as start:
            await listener._sample_memory()
        start.assert_not_called()
        listener._log.assert_not_called()

    @pytest.mark.asyncio
    async def test_enabled_logs_rss_each_tick_without_growth( self ):
        """Steady RSS: heartbeat each tick, but never a top-N dump."""
        listener          = _make_listener( memory_trace=True )
        listener._running = True

        ticks = { "n": 0 }
        async def _sleep( _ ):
            ticks[ "n" ] += 1
            if ticks[ "n" ] >= 2:
                listener._running = False

        with patch( f"{LISTENER_MOD}.tracemalloc.start" ), \
             patch( f"{LISTENER_MOD}.tracemalloc.stop" ) as stop, \
             patch( f"{LISTENER_MOD}.asyncio.sleep", new=_sleep ), \
             patch( f"{LISTENER_MOD}.read_self_rss_mb", return_value=40.0 ), \
             patch.object( listener, "_dump_top_allocations" ) as dump:
            await listener._sample_memory()

        dump.assert_not_called()
        stop.assert_called_once()   # tracemalloc always torn down
        assert any( "[mem] RSS=" in str( c ) for c in listener._log.call_args_list )

    @pytest.mark.asyncio
    async def test_growth_past_threshold_triggers_one_dump( self ):
        """
        🔴 THE POINT. RSS jumps past the threshold → exactly one allocation dump, so the
        NEXT leak lands with a traceback instead of being reaped into the dark like 07ed283c.
        """
        listener          = _make_listener( memory_trace=True )
        listener._running = True

        # baseline 40, then a jump well past the threshold, then release.
        rss_seq = iter( [ 40.0, 40.0 + MEMORY_GROWTH_DUMP_THRESHOLD_MB + 5 ] )
        async def _sleep( _ ):
            listener._running = True   # keep going until the sequence is exhausted

        def _next_rss():
            try:
                return next( rss_seq )
            except StopIteration:
                listener._running = False
                return 40.0 + MEMORY_GROWTH_DUMP_THRESHOLD_MB + 5

        with patch( f"{LISTENER_MOD}.tracemalloc.start" ), \
             patch( f"{LISTENER_MOD}.tracemalloc.stop" ), \
             patch( f"{LISTENER_MOD}.asyncio.sleep", new=_sleep ), \
             patch( f"{LISTENER_MOD}.read_self_rss_mb", side_effect=_next_rss ), \
             patch.object( listener, "_dump_top_allocations" ) as dump:
            await listener._sample_memory()

        assert dump.call_count == 1

    @pytest.mark.asyncio
    async def test_none_rss_reading_is_skipped_not_crashed( self ):
        """
        A transient /proc read failure must be SKIPPED (continue), not crash the sampler.
        The loop has to actually run one full body with rss=None to exercise the continue,
        so _sleep keeps _running True on the first wake and only stops on the second.
        """
        listener          = _make_listener( memory_trace=True )
        listener._running = True

        wakes = { "n": 0 }
        async def _sleep( _ ):
            wakes[ "n" ] += 1
            if wakes[ "n" ] >= 2:
                listener._running = False   # stop only after the None body has run once

        # baseline=40.0, then the in-loop read returns None -> continue.
        with patch( f"{LISTENER_MOD}.tracemalloc.start" ), \
             patch( f"{LISTENER_MOD}.tracemalloc.stop" ), \
             patch( f"{LISTENER_MOD}.asyncio.sleep", new=_sleep ), \
             patch( f"{LISTENER_MOD}.read_self_rss_mb", side_effect=[ 40.0, None ] ), \
             patch.object( listener, "_dump_top_allocations" ) as dump:
            await listener._sample_memory()

        dump.assert_not_called()
        # It logged the baseline arm line but NO "[mem] RSS=" heartbeat (the None was skipped).
        assert not any( "[mem] RSS=" in str( c ) for c in listener._log.call_args_list )

    @pytest.mark.asyncio
    async def test_shutdown_during_sleep_exits_cleanly( self ):
        listener          = _make_listener( memory_trace=True )
        listener._running = True

        async def _sleep( _ ):
            listener._running = False

        with patch( f"{LISTENER_MOD}.tracemalloc.start" ), \
             patch( f"{LISTENER_MOD}.tracemalloc.stop" ) as stop, \
             patch( f"{LISTENER_MOD}.asyncio.sleep", new=_sleep ), \
             patch( f"{LISTENER_MOD}.read_self_rss_mb", return_value=40.0 ) as rss, \
             patch.object( listener, "_dump_top_allocations" ) as dump:
            await listener._sample_memory()

        # Baseline read fires once BEFORE the loop; then we wake to _running False and
        # break BEFORE the in-loop sample — so exactly one read, and no dump.
        rss.assert_called_once()
        dump.assert_not_called()
        stop.assert_called_once()

    def test_dump_top_allocations_logs_a_snapshot( self ):
        """The dump names allocations; assert it takes a snapshot and logs the header + rows."""
        import tracemalloc
        listener = _make_listener( memory_trace=True )
        tracemalloc.start()
        try:
            listener._dump_top_allocations( 555.0 )
        finally:
            tracemalloc.stop()
        logged = " ".join( str( c ) for c in listener._log.call_args_list )
        assert "GROWTH DUMP" in logged
        assert "555" in logged


# ═════════════════════════════════════════════════════════════════════════════
# _spawn_listener → the production argv actually carries --owner-pid
# ═════════════════════════════════════════════════════════════════════════════

class TestSpawnArgvWiring:

    def test_spawned_argv_carries_owner_pid( self, spawn_rig ):
        """
        The line that arms the watchdog in production. A helper that returns the right PID
        is worthless if the spawn site never forwards it, so assert on the REAL argv.
        """
        popen_mock, tmp_path = spawn_rig
        session_file = tmp_path / "cc-999.json"
        session_data = { "session_id": SESSION_ID, "cc_pid": 212845 }

        register_session._spawn_listener( SESSION_ID, session_data, str( session_file ) )

        argv = popen_mock.call_args.args[ 0 ]
        assert "--owner-pid" in argv
        assert argv[ argv.index( "--owner-pid" ) + 1 ] == "212845"

    def test_spawned_argv_omits_owner_pid_when_unresolvable( self, spawn_rig ):
        """No cc_pid anywhere → no flag (the listener then logs the DISABLED warning itself)."""
        popen_mock, tmp_path = spawn_rig
        session_file = tmp_path / "cc-none.json"     # never created

        register_session._spawn_listener( SESSION_ID, { }, str( session_file ) )

        assert "--owner-pid" not in popen_mock.call_args.args[ 0 ]

    def test_memtrace_env_forwards_the_flag( self, spawn_rig, monkeypatch ):
        popen_mock, tmp_path = spawn_rig
        monkeypatch.setenv( "LUPIN_CC_LISTENER_MEMTRACE", "true" )

        register_session._spawn_listener( SESSION_ID, { "cc_pid": 5 }, str( tmp_path / "cc-5.json" ) )

        assert "--memory-trace" in popen_mock.call_args.args[ 0 ]

    def test_memtrace_absent_by_default( self, spawn_rig, monkeypatch ):
        popen_mock, tmp_path = spawn_rig
        monkeypatch.delenv( "LUPIN_CC_LISTENER_MEMTRACE", raising=False )

        register_session._spawn_listener( SESSION_ID, { "cc_pid": 5 }, str( tmp_path / "cc-5.json" ) )

        assert "--memory-trace" not in popen_mock.call_args.args[ 0 ]
