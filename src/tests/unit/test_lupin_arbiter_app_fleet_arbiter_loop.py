#!/usr/bin/env python3
"""
Unit tests for the fleet-arbiter loop — the standing fleet-stall arbiter + recycle supervisor (L3).

Venue: :7999-eligible (pure logic + fakes; the one real-thread test uses a blocking
fake job released deterministically by request_cancel — no real arbiter run, no
docker, no commons IO). Coverage target: 100% line+branch+function on fleet_arbiter_loop.py.
"""
import datetime
import json
import threading

from lupin_arbiter_app.fleet_arbiter_loop import (
    FleetArbiterLoop,
    build_fleet_arbiter_job_factory,
    make_escalation_notify_fn,
    make_warmup_notify_fn,
    _default_log_fn,
)
from lupin_arbiter_app.local_snapshot_store import LocalSnapshotStore


UTC = datetime.timezone.utc
T0  = datetime.datetime( 2026, 6, 7, 12, 0, 0, tzinfo=UTC )


class SettableClock:
    def __init__( self, t ): self.t = t
    def now( self ): return self.t


class FakeGateway:
    def __init__( self ): self.posts = [ ]; self.sends = [ ]
    def who( self, retention_hours=24 ): return [ ]
    def send_to( self, recipient, body, metadata=None ): self.sends.append( ( recipient, body ) )
    def post( self, topic, body ): self.posts.append( ( topic, body ) )
    def read( self, topic, since=None, limit=50 ): return [ ]


class Recorder:
    def __init__( self ): self.logs = [ ]
    def log( self, event, **fields ): self.logs.append( ( event, fields ) )


class FakeJob:
    """Stands in for ArbiterConsumerJob in runner tests (no real arbiter run)."""
    def __init__( self, result="hard-cap", raises=False, block=None, cancel_raises=False ):
        self.result = result; self.raises = raises; self.block = block
        self.cancel_raises = cancel_raises; self.cancelled = False
    def do_all( self ):
        if self.block is not None: self.block.wait( timeout=5 )
        if self.raises: raise RuntimeError( "job boom" )
        return self.result
    def request_cancel( self ):
        self.cancelled = True
        if self.cancel_raises: raise RuntimeError( "cancel boom" )
        if self.block is not None: self.block.set()


# ── escalation notify (ruling A) ────────────────────────────────────────────

def test_escalation_posts_durable():
    gw, rec = FakeGateway(), Recorder()
    make_escalation_notify_fn( gw, log_fn=rec.log )( "alert" )
    assert gw.posts == [ ( "fleet-escalations", "alert" ) ]


def test_escalation_post_error_swallowed():
    rec = Recorder()
    class BadGW( FakeGateway ):
        def post( self, topic, body ): raise RuntimeError( "commons down" )
    make_escalation_notify_fn( BadGW(), log_fn=rec.log )( "alert" )    # must not raise
    assert any( e == "escalation_post_error" for e, _ in rec.logs )


def test_escalation_best_effort_live_delivery():
    gw, rec, live = FakeGateway(), Recorder(), [ ]
    make_escalation_notify_fn( gw, live_notify_fn=live.append, log_fn=rec.log )( "a" )
    assert live == [ "a" ] and gw.posts == [ ( "fleet-escalations", "a" ) ]


def test_escalation_live_error_swallowed():
    gw, rec = FakeGateway(), Recorder()
    def boom( m ): raise RuntimeError( "live down" )
    make_escalation_notify_fn( gw, live_notify_fn=boom, log_fn=rec.log )( "b" )   # must not raise
    assert gw.posts == [ ( "fleet-escalations", "b" ) ]                # durable still landed
    assert any( e == "escalation_live_notify_error" for e, _ in rec.logs )


# ── warm-up suppressor (ruling B) ───────────────────────────────────────────

def test_warmup_suppresses_then_passes():
    rec, calls = Recorder(), [ ]
    clock = SettableClock( T0 )
    nf = make_warmup_notify_fn( calls.append, T0, 120, clock, rec.log )
    clock.t = T0 + datetime.timedelta( seconds=10 )
    nf( "early" )                                                       # within window → suppressed
    assert calls == [ ]
    assert any( e == "escalation_suppressed_warmup" for e, _ in rec.logs )
    clock.t = T0 + datetime.timedelta( seconds=200 )
    nf( "late" )                                                        # past window → passes
    assert calls == [ "late" ]


# ── job factory (sink + warm-up + escalation wiring) ────────────────────────

def test_build_factory_wires_sink_and_warmup_escalation():
    gw, store, clock = FakeGateway(), LocalSnapshotStore(), SettableClock( T0 )
    factory = build_fleet_arbiter_job_factory( gw, store, clock=clock, log_fn=lambda *a, **k: None,
                                               start_period_seconds=120 )
    job = factory()
    # snapshot_sink writes the fleet_arbiter section of the shared store
    job._snapshot_sink( { "session_count": 2 } )
    assert store.get_section( "fleet_arbiter" ) == { "session_count": 2 }
    # notify within warm-up → suppressed (no durable post)
    clock.t = T0
    job._notify_fn( "early" )
    assert gw.posts == [ ]
    # notify past warm-up → durable post to fleet-escalations
    clock.t = T0 + datetime.timedelta( seconds=200 )
    job._notify_fn( "late" )
    assert gw.posts == [ ( "fleet-escalations", "late" ) ]


# ── FleetArbiterLoop recycle supervisor ─────────────────────────────────────

def test_runner_recycles_until_stop():
    rec = Recorder()
    runner = None
    n = { "c": 0 }
    def factory():
        n[ "c" ] += 1
        if n[ "c" ] >= 2: runner._stop.set()       # stop AT the 2nd job (after its do_all)
        return FakeJob( result="hard-cap" )
    runner = FleetArbiterLoop( factory, log_fn=rec.log, hold_janitor_fn=lambda: [ ] )
    runner.run()
    assert runner.cycles == 2
    assert len( [ e for e, _ in rec.logs if e == "fleet_arbiter_recycle" ] ) == 1     # one relaunch
    assert len( [ e for e, _ in rec.logs if e == "fleet_arbiter_job_start" ] ) == 2


def test_runner_swallows_job_error():
    rec = Recorder()
    runner = None
    def factory():
        runner._stop.set()                          # stop after this one job
        return FakeJob( raises=True )
    runner = FleetArbiterLoop( factory, log_fn=rec.log, hold_janitor_fn=lambda: [ ] )
    runner.run()
    assert runner.cycles == 1
    assert any( e == "fleet_arbiter_job_error" for e, _ in rec.logs )


def test_runner_start_stop_thread():
    rec = Recorder()
    ev  = threading.Event()
    job = FakeJob( block=ev )
    runner = FleetArbiterLoop( lambda: job, log_fn=rec.log, hold_janitor_fn=lambda: [ ] )
    runner.start()
    runner.stop()                                   # _stop + request_cancel → ev.set → do_all returns → break → join
    assert job.cancelled is True
    assert runner._thread is not None


def test_runner_janitor_logs_when_pruned():
    # b39562e4 pt2: janitor runs each cycle; a non-empty prune is logged with a count
    rec = Recorder()
    runner = None
    def factory():
        runner._stop.set()
        return FakeJob( result="hard-cap" )
    runner = FleetArbiterLoop( factory, log_fn=rec.log,
                               hold_janitor_fn=lambda: [ "/x/.heartbeat-hold-a.json",
                                                         "/x/.heartbeat-hold-b.json" ] )
    runner.run()
    janitor_logs = [ kw for e, kw in rec.logs if e == "fleet_arbiter_hold_janitor" ]
    assert janitor_logs and janitor_logs[ 0 ][ "pruned_count" ] == 2


def test_runner_janitor_exception_swallowed():
    # janitor blow-up must NOT kill the supervisor — logged + cycle proceeds
    rec = Recorder()
    runner = None
    def factory():
        runner._stop.set()
        return FakeJob( result="hard-cap" )
    def _boom():
        raise OSError( "janitor exploded" )
    runner = FleetArbiterLoop( factory, log_fn=rec.log, hold_janitor_fn=_boom )
    runner.run()
    assert runner.cycles == 1
    assert any( e == "fleet_arbiter_hold_janitor_error" for e, _ in rec.logs )


def test_runner_stop_cancel_error_swallowed():
    rec = Recorder()
    job = FakeJob( cancel_raises=True )
    runner = FleetArbiterLoop( lambda: job, log_fn=rec.log )
    runner._current_job = job                        # simulate an in-flight job
    runner.stop()                                    # request_cancel raises → swallowed+logged
    assert any( e == "fleet_arbiter_cancel_error" for e, _ in rec.logs )


def test_runner_stop_without_start_is_safe():
    FleetArbiterLoop( lambda: FakeJob(), log_fn=lambda *a, **k: None ).stop()   # no thread/job → no raise


def test_runner_already_stopped_runs_no_job():
    """_stop set before run() → the while condition exits immediately (no job built)."""
    rec    = Recorder()
    runner = FleetArbiterLoop( lambda: FakeJob(), log_fn=rec.log )
    runner._stop.set()
    runner.run()
    assert runner.cycles == 0
    assert rec.logs == [ ]


def test_default_log_fn_fleet_arbiter_emits_json( capsys ):
    _default_log_fn( "fleet_arbiter_job_start", cycle=1 )
    p = json.loads( capsys.readouterr().out.strip() )
    assert p[ "loop" ] == "fleet_arbiter" and p[ "event" ] == "fleet_arbiter_job_start" and p[ "cycle" ] == 1


def test_build_factory_passes_declared_managers_to_job():
    """COSA_VOICE_MANAGERS roster rides the factory into every recycled job."""
    gw, store = FakeGateway(), LocalSnapshotStore()
    factory = build_fleet_arbiter_job_factory(
        gw, store, log_fn=lambda *a, **k: None,
        manager_on_duty="dut", declared_managers=[ "Mr. Radio", "Tiberius" ] )
    job = factory()
    assert job.declared_managers == [ "Mr. Radio", "Tiberius" ]
    assert job.declared_fallback_manager == "Mr. Radio"          # roster head outranks INI dut


def test_build_factory_default_no_declared_managers():
    gw, store = FakeGateway(), LocalSnapshotStore()
    job = build_fleet_arbiter_job_factory( gw, store, log_fn=lambda *a, **k: None,
                                           manager_on_duty="dut" )()
    assert job.declared_managers == [ ]
    assert job.declared_fallback_manager == "dut"                # INI fallback unchanged


# ── 6929f4ac: the :8001 factory MUST wire the outward-twin hold reader ─────────
# Deploy-honesty regression guard (Rachel's catch): without this wiring the seam
# is None → the dark-session user-gate resurface + the open-gate→ACTIVE override
# are DECORATIVE on the actual :8001 deploy. This factory is the real deploy path
# (NOT arbiter_bootstrap, which is the default-OFF in-process path).

def test_build_factory_wires_real_hold_reader_by_default():
    """The :8001 factory defaults hold_reader_fn to the real read_hold so the
    outward-twin backstop is LIVE on deploy (regression guard against silent inertness)."""
    from lupin_cli.claude_code.hooks.lib.heartbeat_hold import read_hold
    gw, store = FakeGateway(), LocalSnapshotStore()
    job = build_fleet_arbiter_job_factory( gw, store, log_fn=lambda *a, **k: None )()
    assert job._hold_reader_fn is read_hold                       # non-None AND resolves to read_hold
    assert job.user_gate_resurface_seconds == 1800               # default ceiling threaded


def test_build_factory_threads_resurface_seconds_and_allows_fake_reader():
    """A custom ceiling is threaded; an injected fake hold reader overrides the default (test seam)."""
    gw, store = FakeGateway(), LocalSnapshotStore()
    fake = lambda sid: None
    job  = build_fleet_arbiter_job_factory(
        gw, store, log_fn=lambda *a, **k: None,
        hold_reader_fn=fake, user_gate_resurface_seconds=900 )()
    assert job._hold_reader_fn is fake
    assert job.user_gate_resurface_seconds == 900


# ── eng#7: follow-through watcher factory (build-plan §3b) ───────────────────

import types

from lupin_arbiter_app.fleet_arbiter_loop import make_follow_through_watcher_factory


class _StubJob:
    """Stands in for ArbiterConsumerJob — exposes only session_is_not_owed."""
    def session_is_not_owed( self, persona, fleet_view=None ):
        return False


class _FakeCfg:
    def __init__( self, values=None ): self._v = values or { }
    def get( self, key, default=None, return_type=None ): return self._v.get( key, default )


def _item( id="i-1", title="Verify lane 4" ):
    return types.SimpleNamespace( id=id, title=title )


def test_follow_through_factory_builds_watcher_with_bound_hold_check():
    from cosa.rest.follow_through_escalation_watcher import FollowThroughEscalationWatcher
    cfg, gw, job = _FakeCfg(), FakeGateway(), _StubJob()
    factory = make_follow_through_watcher_factory( cfg, gw, log_fn=lambda *a, **k: None )
    watcher = factory( job )
    assert isinstance( watcher, FollowThroughEscalationWatcher )
    assert watcher._config_mgr is cfg
    # §4.5: hold_check IS the job's store-owed predicate (REUSED, not re-implemented)
    assert watcher._hold_check_fn == job.session_is_not_owed


def test_follow_through_escalate_fn_pokes_accountable_manager():
    gw, rec = FakeGateway(), Recorder()
    watcher = make_follow_through_watcher_factory( _FakeCfg(), gw, log_fn=rec.log )( _StubJob() )
    awaited = T0
    watcher._escalate_fn( _item( id="i-9", title="Aged item" ), "Mr. Radio", "Rachel", awaited )
    assert len( gw.sends ) == 1
    recipient, body = gw.sends[ 0 ]
    assert recipient == "Mr. Radio"
    assert "Aged item" in body and "Rachel" in body              # names the item + the waiting worker
    ev = [ f for e, f in rec.logs if e == "follow_through_escalation" ]
    assert ev and ev[ 0 ][ "item" ] == "i-9" and ev[ 0 ][ "manager" ] == "Mr. Radio"


def test_follow_through_escalate_fn_error_swallowed():
    rec = Recorder()
    class BadGW( FakeGateway ):
        def send_to( self, recipient, body, metadata=None ): raise RuntimeError( "commons down" )
    watcher = make_follow_through_watcher_factory( _FakeCfg(), BadGW(), log_fn=rec.log )( _StubJob() )
    watcher._escalate_fn( _item(), "Mr. Radio", "Rachel", T0 )   # must NOT raise
    assert any( e == "follow_through_escalation_error" for e, _ in rec.logs )


def test_follow_through_factory_default_log_fn( capsys ):
    # No log_fn → the module default (_default_log_fn) is used (else-branch cover).
    watcher = make_follow_through_watcher_factory( _FakeCfg(), FakeGateway() )( _StubJob() )
    watcher._escalate_fn( _item( id="i-d" ), "Mgr", "Wkr", T0 )
    p = json.loads( capsys.readouterr().out.strip() )
    assert p[ "event" ] == "follow_through_escalation" and p[ "item" ] == "i-d"


def test_build_factory_threads_follow_through_watcher_factory():
    gw, store = FakeGateway(), LocalSnapshotStore()
    sentinel = object()
    seen     = [ ]
    def fac( job ):
        seen.append( job )
        return sentinel
    job = build_fleet_arbiter_job_factory(
        gw, store, log_fn=lambda *a, **k: None,
        follow_through_watcher_factory=fac )()
    assert job._follow_through_watcher is sentinel               # threaded → wired into the job
    assert seen == [ job ]                                       # factory called once, with the job


def test_build_factory_default_no_follow_through_watcher():
    gw, store = FakeGateway(), LocalSnapshotStore()
    job = build_fleet_arbiter_job_factory( gw, store, log_fn=lambda *a, **k: None )()
    assert job._follow_through_watcher is None                   # default → inert
