#!/usr/bin/env python3
"""
Unit tests for Loop A — the dev/test health watch (L2).

Venue: :7999-eligible (pure logic on synthetic Status sequences; NO live docker,
NO network; the one real-thread test uses a fast fake clock that stops the loop
deterministically). Coverage target: 100% line+branch+function on health_watch.py
(the real `docker inspect` subprocess + SystemClock.sleep are the only
pragma-no-cover IO boundaries).
"""
import datetime
import json
import threading

import pytest

from lupin_arbiter_app.health_watch import (
    ContainerHealthTracker,
    HealthWatchLoop,
    SystemClock,
    _default_log_fn,
    _parse_inspect_result,
)
from lupin_arbiter_app.local_snapshot_store import LocalSnapshotStore


UTC = datetime.timezone.utc
T0  = datetime.datetime( 2026, 6, 7, 12, 0, 0, tzinfo=UTC )


def _at( seconds ):
    """Helper: an aware datetime `seconds` after T0."""
    return T0 + datetime.timedelta( seconds=seconds )


# ── seam helpers ────────────────────────────────────────────────────────────

class FakeClock:
    """
    Deterministic clock seam. now() advances by `step` each call (optionally
    raising on configured call indices); sleep() can set a stop event after N
    calls so a run()/thread loop exits without real waiting.
    """
    def __init__( self, step=1, raise_on_now=(), sleep_stops_after=None ):
        self._t                = T0
        self._step             = datetime.timedelta( seconds=step )
        self._now_calls        = 0
        self._raise_on         = set( raise_on_now )
        self._sleep_calls      = 0
        self._sleep_stops_after = sleep_stops_after
        self.stop_event        = None      # wired to the loop's _stop after construction

    def now( self ):
        self._now_calls += 1
        if self._now_calls in self._raise_on:
            raise RuntimeError( "boom-now" )
        t = self._t
        self._t = self._t + self._step
        return t

    def sleep( self, seconds ):
        self._sleep_calls += 1
        if ( self._sleep_stops_after is not None
             and self._sleep_calls >= self._sleep_stops_after
             and self.stop_event is not None ):
            self.stop_event.set()


class Recorder:
    """Records notify() messages + log() events."""
    def __init__( self ):
        self.notices = [ ]
        self.logs    = [ ]
    def notify( self, msg ):
        self.notices.append( msg )
    def log( self, event, **fields ):
        self.logs.append( ( event, fields ) )


# ── ContainerHealthTracker (pure) ───────────────────────────────────────────

def test_tracker_warmup_first_observation_is_baseline():
    tr = ContainerHealthTracker( 600, 3, flap_excluded=False )
    assert tr.observe( "healthy", T0 ) == [ ]        # baseline only
    assert tr.last_status == "healthy"
    assert tr.transitions_in_window() == 0


def test_tracker_enter_unhealthy_once_then_rearm():
    tr = ContainerHealthTracker( 600, 99, flap_excluded=False )   # high flap thresh → isolate unhealthy
    tr.observe( "healthy", _at( 0 ) )                             # baseline
    assert tr.observe( "unhealthy", _at( 1 ) ) == [ "enter_unhealthy" ]
    assert tr.observe( "unhealthy", _at( 2 ) ) == [ ]            # no change → no re-escalate
    assert tr.observe( "healthy",   _at( 3 ) ) == [ ]            # recovery (transition, not unhealthy)
    assert tr.observe( "unhealthy", _at( 4 ) ) == [ "enter_unhealthy" ]   # re-armed


def test_tracker_flapping_edge_and_rearm_after_window_clears():
    tr = ContainerHealthTracker( flap_window_seconds=600, flap_threshold=3, flap_excluded=False )
    tr.observe( "healthy", _at( 0 ) )                            # baseline
    tr.observe( "unhealthy", _at( 1 ) )                          # transition 1 (enter_unhealthy)
    tr.observe( "healthy",   _at( 2 ) )                          # transition 2
    events = tr.observe( "unhealthy", _at( 3 ) )                 # transition 3 → flapping (+enter_unhealthy)
    assert "flapping" in events
    assert tr.is_flapping() is True
    # still flapping, no re-escalate while flag held
    assert "flapping" not in tr.observe( "healthy", _at( 4 ) )
    # advance well past the window so old transitions prune below threshold → re-arm
    tr.observe( "healthy", _at( 4 ) )                            # same status, prune-only path
    assert tr.observe( "unhealthy", _at( 1300 ) ) == [ "enter_unhealthy" ]   # window cleared; not flapping yet
    assert tr.is_flapping() is False


def test_tracker_flap_excluded_never_emits_flapping_but_still_unhealthy():
    tr = ContainerHealthTracker( 600, 3, flap_excluded=True )
    tr.observe( "healthy", _at( 0 ) )
    tr.observe( "unhealthy", _at( 1 ) )
    tr.observe( "healthy",   _at( 2 ) )
    events = tr.observe( "unhealthy", _at( 3 ) )                 # would-be flap, but excluded
    assert "flapping" not in events
    assert "enter_unhealthy" in events                          # enter-unhealthy still fires when excluded


def test_tracker_prune_drops_old_transitions():
    tr = ContainerHealthTracker( flap_window_seconds=100, flap_threshold=99, flap_excluded=False )
    tr.observe( "healthy", _at( 0 ) )
    tr.observe( "unhealthy", _at( 10 ) )
    tr.observe( "healthy",   _at( 20 ) )
    assert tr.transitions_in_window() == 2
    tr.observe( "unhealthy", _at( 200 ) )                       # now-200 prunes the _at(10),_at(20) entries
    assert tr.transitions_in_window() == 1


# ── HealthWatchLoop construction validation ─────────────────────────────────

@pytest.mark.parametrize( "kwargs", [
    { "containers": [ ] },
    { "containers": [ "c" ], "interval_seconds": 0 },
    { "containers": [ "c" ], "flap_window_seconds": 0 },
    { "containers": [ "c" ], "flap_threshold": 0 },
    { "containers": [ "c" ], "blind_threshold_polls": 0 },
] )
def test_loop_init_validation_raises( kwargs ):
    base = { "inspect_fn": lambda n: None, "notify_fn": lambda m: None }
    base.update( kwargs )
    with pytest.raises( ValueError ):
        HealthWatchLoop( **base )


# ── HealthWatchLoop.poll_once ───────────────────────────────────────────────

def _loop( inspect_fn, rec, **kw ):
    return HealthWatchLoop(
        containers = kw.pop( "containers", [ "c1" ] ),
        inspect_fn = inspect_fn,
        notify_fn  = rec.notify,
        clock      = FakeClock(),
        log_fn     = rec.log,
        **kw,
    )


def test_poll_enter_unhealthy_escalates():
    rec  = Recorder()
    seq  = iter( [ { "Status": "healthy" }, { "Status": "unhealthy" } ] )
    loop = _loop( lambda n: next( seq ), rec )
    loop.poll_once()                                            # baseline healthy
    loop.poll_once()                                            # → unhealthy
    assert any( "entered UNHEALTHY" in m for m in rec.notices )


def test_poll_health_unknown_status_none_and_string_none_are_skipped():
    rec  = Recorder()
    # None side of `Status or None`, then literal "none" string side
    seq  = iter( [ { "Status": None }, { "Status": "none" } ] )
    loop = _loop( lambda n: next( seq ), rec )
    assert loop.poll_once() is True                             # inspect succeeded (any_ok)
    assert loop.poll_once() is True
    assert rec.notices == [ ]                                   # never tracked, never paged
    assert any( ev == "health_unknown" for ev, _ in rec.logs )


def test_poll_inspect_failure_and_blind_escalation_then_rearm():
    rec   = Recorder()
    state = { "fail": True }
    def inspect( n ):
        return None if state[ "fail" ] else { "Status": "healthy" }
    loop = _loop( inspect, rec, blind_threshold_polls=2 )
    assert loop.poll_once() is False                            # fail #1
    assert loop.poll_once() is False                            # fail #2 → BLIND
    blind_msgs = [ m for m in rec.notices if "BLIND" in m ]
    assert len( blind_msgs ) == 1
    loop.poll_once()                                            # fail #3 → no re-escalate
    assert len( [ m for m in rec.notices if "BLIND" in m ] ) == 1
    state[ "fail" ] = False
    assert loop.poll_once() is True                            # recovery → re-arm blind


def test_poll_inspect_raises_is_swallowed():
    rec  = Recorder()
    def inspect( n ):
        raise RuntimeError( "docker gone" )
    loop = _loop( inspect, rec )
    assert loop.poll_once() is False
    assert any( ev == "inspect_error" for ev, _ in rec.logs )


def test_poll_notify_raises_is_swallowed():
    rec  = Recorder()
    seq  = iter( [ { "Status": "healthy" }, { "Status": "unhealthy" } ] )
    def boom_notify( msg ):
        raise RuntimeError( "notify down" )
    loop = HealthWatchLoop( containers=[ "c1" ], inspect_fn=lambda n: next( seq ),
                            notify_fn=boom_notify, clock=FakeClock(), log_fn=rec.log )
    loop.poll_once()
    loop.poll_once()                                            # escalation fires → notify raises → swallowed
    assert any( ev == "notify_error" for ev, _ in rec.logs )


def test_poll_writes_loop_a_section_to_store():
    rec   = Recorder()
    store = LocalSnapshotStore()
    loop  = _loop( lambda n: { "Status": "healthy" }, rec, store=store, containers=[ "c1", "c2" ] )
    loop.poll_once()
    section = store.get_section( "loop_a" )
    assert set( section[ "containers" ].keys() ) == { "c1", "c2" }
    assert section[ "containers" ][ "c1" ][ "status" ] == "healthy"
    assert section[ "blind" ] is False
    assert "updated_at" in section


def test_poll_without_store_is_noop():
    rec  = Recorder()
    loop = _loop( lambda n: { "Status": "healthy" }, rec, store=None )
    loop.poll_once()                                            # must not raise


def test_write_state_marks_flapping_and_exclusion():
    rec   = Recorder()
    store = LocalSnapshotStore()
    loop  = HealthWatchLoop( containers=[ "dev", "other" ], inspect_fn=lambda n: { "Status": "healthy" },
                             notify_fn=rec.notify, clock=FakeClock(), log_fn=rec.log, store=store,
                             flap_threshold=2, flap_exclude=[ "dev" ] )
    # drive both containers through transitions to flap "other" (and would-be "dev")
    seq = { "dev": iter( [ "healthy", "unhealthy", "healthy" ] ),
            "other": iter( [ "healthy", "unhealthy", "healthy" ] ) }
    loop._inspect_fn = lambda n: { "Status": next( seq[ n ] ) }
    loop.poll_once(); loop.poll_once(); loop.poll_once()
    section = store.get_section( "loop_a" )
    assert section[ "containers" ][ "dev" ][ "flap_excluded" ] is True
    assert section[ "containers" ][ "dev" ][ "flapping" ] is False      # excluded → never flapping in the view
    assert section[ "containers" ][ "other" ][ "flapping" ] is True     # not excluded, ≥2 transitions


# ── _format_escalation (all arms incl. defensive fallback) ──────────────────

def test_format_escalation_all_events():
    f = HealthWatchLoop._format_escalation
    assert "UNHEALTHY" in f( "enter_unhealthy", "c", "unhealthy" )
    assert "FLAPPING"  in f( "flapping", "c", "unhealthy" )
    assert "BLIND"     in f( "blind", None, None )
    assert "weird"     in f( "weird", "c", "x" )                # defensive fallback


# ── run() / start() / stop() lifecycle ──────────────────────────────────────

def test_run_swallows_poll_error_then_stops():
    rec   = Recorder()
    clock = FakeClock( raise_on_now=( 1, ), sleep_stops_after=1 )   # 1st now() raises → poll_once raises
    loop  = HealthWatchLoop( containers=[ "c1" ], inspect_fn=lambda n: { "Status": "healthy" },
                             notify_fn=rec.notify, clock=clock, log_fn=rec.log )
    clock.stop_event = loop._stop
    loop.run()                                                  # poll raises → per-poll guard → sleep stops it
    assert any( ev == "poll_error" for ev, _ in rec.logs )


def test_run_normal_then_stops():
    rec   = Recorder()
    clock = FakeClock( sleep_stops_after=1 )
    loop  = HealthWatchLoop( containers=[ "c1" ], inspect_fn=lambda n: { "Status": "healthy" },
                             notify_fn=rec.notify, clock=clock, log_fn=rec.log )
    clock.stop_event = loop._stop
    loop.run()                                                  # one clean poll, then stop
    assert any( ev == "health_obs" for ev, _ in rec.logs )


def test_start_stop_thread_lifecycle():
    rec   = Recorder()
    clock = FakeClock( sleep_stops_after=1 )
    loop  = HealthWatchLoop( containers=[ "c1" ], inspect_fn=lambda n: { "Status": "healthy" },
                             notify_fn=rec.notify, clock=clock, log_fn=rec.log )
    clock.stop_event = loop._stop
    loop.start()
    loop._thread.join( timeout=5 )                              # thread self-stops via the fake clock
    loop.stop()                                                 # idempotent join (thread already done)
    assert loop._thread is not None


def test_stop_without_start_is_safe():
    rec  = Recorder()
    loop = _loop( lambda n: { "Status": "healthy" }, rec )
    loop.stop()                                                 # never started → no thread to join


# ── default seams ───────────────────────────────────────────────────────────

def test_loop_default_seams_smoke():
    """Construct with default clock + default log_fn (covers the else-branches)."""
    store = LocalSnapshotStore()
    loop  = HealthWatchLoop( containers=[ "c1" ], inspect_fn=lambda n: { "Status": "healthy" },
                             notify_fn=lambda m: None, store=store )
    loop.poll_once()                                            # uses SystemClock + _default_log_fn
    assert store.get_section( "loop_a" )[ "containers" ][ "c1" ][ "status" ] == "healthy"


def test_parse_inspect_result_all_arms():
    """The 4 parse/error arms extracted from docker_inspect_health (SOFT→REQUIRED)."""
    f = _parse_inspect_result
    assert f( 1, '{"Status":"healthy"}' ) is None            # non-zero returncode → failure
    assert f( 0, "" ) == { "Status": None }                  # empty stdout → no healthcheck
    assert f( 0, "  null  " ) == { "Status": None }          # "null" → no healthcheck
    assert f( 0, None ) == { "Status": None }                # None stdout → (stdout or "") branch
    assert f( 0, '{"Status": "healthy", "FailingStreak": 0}' )[ "Status" ] == "healthy"   # valid JSON
    assert f( 0, "not json {" ) is None                      # unparseable → None


def test_system_clock_now_is_aware_utc():
    ts = SystemClock().now()
    assert ts.tzinfo is not None
    assert ts.utcoffset() == datetime.timedelta( 0 )


def test_default_log_fn_emits_json_line( capsys ):
    _default_log_fn( "health_obs", container="c1", status="healthy" )
    out = capsys.readouterr().out.strip()
    parsed = json.loads( out )
    assert parsed[ "event" ] == "health_obs"
    assert parsed[ "container" ] == "c1"
    assert parsed[ "loop" ] == "A"
    assert parsed[ "service" ] == "lupin-arbiter-app"
