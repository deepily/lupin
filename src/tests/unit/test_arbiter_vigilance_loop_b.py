#!/usr/bin/env python3
"""
Unit tests for Loop B — the standing fleet-stall arbiter + recycle supervisor (L3).

Venue: :7999-eligible (pure logic + fakes; the one real-thread test uses a blocking
fake job released deterministically by request_cancel — no real arbiter run, no
docker, no commons IO). Coverage target: 100% line+branch+function on loop_b.py.
"""
import datetime
import json
import threading

from arbiter_vigilance.loop_b import (
    LoopBRunner,
    build_loop_b_job_factory,
    make_escalation_notify_fn,
    make_warmup_notify_fn,
    _default_log_fn,
)
from arbiter_vigilance.local_snapshot_store import LocalSnapshotStore


UTC = datetime.timezone.utc
T0  = datetime.datetime( 2026, 6, 7, 12, 0, 0, tzinfo=UTC )


class SettableClock:
    def __init__( self, t ): self.t = t
    def now( self ): return self.t


class FakeGateway:
    def __init__( self ): self.posts = [ ]; self.sends = [ ]
    def who( self, retention_hours=24 ): return [ ]
    def send_to( self, recipient, body ): self.sends.append( ( recipient, body ) )
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
    factory = build_loop_b_job_factory( gw, store, clock=clock, log_fn=lambda *a, **k: None,
                                        start_period_seconds=120 )
    job = factory()
    # snapshot_sink writes the loop_b_fleet section of the shared store
    job._snapshot_sink( { "session_count": 2 } )
    assert store.get_section( "loop_b_fleet" ) == { "session_count": 2 }
    # notify within warm-up → suppressed (no durable post)
    clock.t = T0
    job._notify_fn( "early" )
    assert gw.posts == [ ]
    # notify past warm-up → durable post to fleet-escalations
    clock.t = T0 + datetime.timedelta( seconds=200 )
    job._notify_fn( "late" )
    assert gw.posts == [ ( "fleet-escalations", "late" ) ]


# ── LoopBRunner recycle supervisor ──────────────────────────────────────────

def test_runner_recycles_until_stop():
    rec = Recorder()
    runner = None
    n = { "c": 0 }
    def factory():
        n[ "c" ] += 1
        if n[ "c" ] >= 2: runner._stop.set()       # stop AT the 2nd job (after its do_all)
        return FakeJob( result="hard-cap" )
    runner = LoopBRunner( factory, log_fn=rec.log )
    runner.run()
    assert runner.cycles == 2
    assert len( [ e for e, _ in rec.logs if e == "loop_b_recycle" ] ) == 1     # one relaunch
    assert len( [ e for e, _ in rec.logs if e == "loop_b_job_start" ] ) == 2


def test_runner_swallows_job_error():
    rec = Recorder()
    runner = None
    def factory():
        runner._stop.set()                          # stop after this one job
        return FakeJob( raises=True )
    runner = LoopBRunner( factory, log_fn=rec.log )
    runner.run()
    assert runner.cycles == 1
    assert any( e == "loop_b_job_error" for e, _ in rec.logs )


def test_runner_start_stop_thread():
    rec = Recorder()
    ev  = threading.Event()
    job = FakeJob( block=ev )
    runner = LoopBRunner( lambda: job, log_fn=rec.log )
    runner.start()
    runner.stop()                                   # _stop + request_cancel → ev.set → do_all returns → break → join
    assert job.cancelled is True
    assert runner._thread is not None


def test_runner_stop_cancel_error_swallowed():
    rec = Recorder()
    job = FakeJob( cancel_raises=True )
    runner = LoopBRunner( lambda: job, log_fn=rec.log )
    runner._current_job = job                        # simulate an in-flight job
    runner.stop()                                    # request_cancel raises → swallowed+logged
    assert any( e == "loop_b_cancel_error" for e, _ in rec.logs )


def test_runner_stop_without_start_is_safe():
    LoopBRunner( lambda: FakeJob(), log_fn=lambda *a, **k: None ).stop()   # no thread/job → no raise


def test_runner_already_stopped_runs_no_job():
    """_stop set before run() → the while condition exits immediately (no job built)."""
    rec    = Recorder()
    runner = LoopBRunner( lambda: FakeJob(), log_fn=rec.log )
    runner._stop.set()
    runner.run()
    assert runner.cycles == 0
    assert rec.logs == [ ]


def test_default_log_fn_b_emits_json( capsys ):
    _default_log_fn( "loop_b_job_start", cycle=1 )
    p = json.loads( capsys.readouterr().out.strip() )
    assert p[ "loop" ] == "B" and p[ "event" ] == "loop_b_job_start" and p[ "cycle" ] == 1
