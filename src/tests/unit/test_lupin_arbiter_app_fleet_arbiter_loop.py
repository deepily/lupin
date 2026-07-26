#!/usr/bin/env python3
"""
Unit tests for the fleet-arbiter loop — the standing fleet-stall arbiter + recycle supervisor (L3).

Venue: :7999-eligible (pure logic + fakes; the one real-thread test uses a blocking
fake job released deterministically by request_cancel — no real arbiter run, no
docker, no commons IO). Coverage target: 100% line+branch+function on fleet_arbiter_loop.py.
"""
import datetime
import json
import os
import subprocess
import threading
from pathlib import Path

from lupin_arbiter_app.fleet_arbiter_loop import (
    FleetArbiterLoop,
    build_fleet_arbiter_job_factory,
    make_escalation_notify_fn,
    make_warmup_notify_fn,
    _default_log_fn,
    _default_hold_roots,
    _default_live_session_ids,
    _default_manager_bridge_mtimes,
    _compute_hold_roots,
    _registry_container_paths,
    _derive_container_host_prefix,
    _translate_container_root,
    _scan_parent_for_repo_roots,
    _is_repo_root,
)
from lupin_arbiter_app.local_snapshot_store import LocalSnapshotStore


UTC = datetime.timezone.utc
T0  = datetime.datetime( 2026, 6, 7, 12, 0, 0, tzinfo=UTC )


def _report( files_found=0, roots_swept=( "/projects/lupin", ), prunable=0, keep=0,
             cargo_bearing=0, ttl_unusable=0, anchor_disagreement=0, kept_reasons=None,
             roots_unreachable=(), skipped=(), roots_requested=None ):
    """A report_hold_files-shaped result. The supervisor consumes the REPORT contract
    (classify + count), never a prune list — it cannot delete a hold file."""
    return {
        "roots_requested"         : list( roots_requested if roots_requested is not None else roots_swept ),
        "roots_swept"             : list( roots_swept ),
        "roots_unreachable"       : list( roots_unreachable ),
        "skipped_dirs_with_holds" : list( skipped ),
        "files_found"             : files_found,
        "files"                   : [ ],
        "counts"                  : { "prunable": prunable, "keep": keep,
                                      "cargo_bearing": cargo_bearing,
                                      "ttl_unusable": ttl_unusable,
                                      "anchor_disagreement": anchor_disagreement,
                                      "reachable_but_kept_reasons": kept_reasons or { } },
        "deleted"                 : 0,
    }


def _noop_report( **kwargs ):
    """Keeps the hold sweep out of the way of the recycle/threading tests."""
    return _report()


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
    def __init__( self, result="hard-cap", raises=False, block=None, cancel_raises=False,
                  started=None ):
        self.result = result; self.raises = raises; self.block = block
        self.cancel_raises = cancel_raises; self.cancelled = False
        self.started = started            # signalled on entry to do_all (start/stop race)
    def do_all( self ):
        if self.started is not None: self.started.set()
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


def test_orphan_bridge_sweep_inert_by_default():
    # Default (flag off) → the sweep seam is never wired → job._bridge_sweep_fn is None.
    gw, store, clock = FakeGateway(), LocalSnapshotStore(), SettableClock( T0 )
    factory = build_fleet_arbiter_job_factory( gw, store, clock=clock, log_fn=lambda *a, **k: None )
    assert factory()._bridge_sweep_fn is None


def test_orphan_bridge_sweep_wired_when_flag_on( monkeypatch ):
    # Flag on → a callable sweep seam is wired, bound to a per-job persistent
    # debounce-state dict. We stub reconcile_orphan_bridges to capture the call
    # (real sweep behavior is covered exhaustively in test_orphan_bridge_reaper).
    import cosa.agents.shared.orphan_bridge_reaper as reaper
    seen = { }
    def _stub( state, debounce_threshold=2 ):
        seen[ "call" ] = ( state, debounce_threshold )
        return { "reaped": [] }
    monkeypatch.setattr( reaper, "reconcile_orphan_bridges", _stub )
    gw, store, clock = FakeGateway(), LocalSnapshotStore(), SettableClock( T0 )
    factory = build_fleet_arbiter_job_factory(
        gw, store, clock=clock, log_fn=lambda *a, **k: None,
        orphan_bridge_sweep_enabled=True, orphan_bridge_sweep_debounce_polls=3,
    )
    sweep_fn = factory()._bridge_sweep_fn
    assert callable( sweep_fn )
    result = sweep_fn()
    assert result == { "reaped": [] }
    assert seen[ "call" ][ 1 ] == 3                      # debounce threshold threaded from the flag
    assert isinstance( seen[ "call" ][ 0 ], dict )       # a persistent state dict was bound


# ── FleetArbiterLoop recycle supervisor ─────────────────────────────────────

def test_runner_recycles_until_stop():
    rec = Recorder()
    runner = None
    n = { "c": 0 }
    def factory():
        n[ "c" ] += 1
        if n[ "c" ] >= 2: runner._stop.set()       # stop AT the 2nd job (after its do_all)
        return FakeJob( result="hard-cap" )
    runner = FleetArbiterLoop( factory, log_fn=rec.log, hold_janitor_fn=_noop_report )
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
    runner = FleetArbiterLoop( factory, log_fn=rec.log, hold_janitor_fn=_noop_report )
    runner.run()
    assert runner.cycles == 1
    assert any( e == "fleet_arbiter_job_error" for e, _ in rec.logs )


def test_runner_start_stop_thread():
    rec     = Recorder()
    ev      = threading.Event()
    started = threading.Event()
    job     = FakeJob( block=ev, started=started )
    # ALL THREE sweep seams injected: the real hold_roots_fn / live_session_ids_fn do
    # genuine IO (project-root resolve + a PID-checked bridge scan) on the supervisor
    # thread BEFORE the first job is built. Harmless in production (once per ~12h
    # cycle) but it loses this start/stop race, so the sweep is stubbed out entirely.
    runner = FleetArbiterLoop( lambda: job, log_fn=rec.log, hold_janitor_fn=_noop_report,
                               hold_roots_fn=lambda: [ ], live_session_ids_fn=lambda: set() )
    runner.start()
    started.wait( timeout=5 )                       # the job is in do_all → _current_job is set
    runner.stop()                                   # _stop + request_cancel → ev.set → do_all returns → break → join
    assert job.cancelled is True
    assert runner._thread is not None


def _one_cycle( rec, **loop_kwargs ):
    """Run the supervisor for exactly one cycle and return it."""
    runner = None
    def factory():
        runner._stop.set()
        return FakeJob( result="hard-cap" )
    runner = FleetArbiterLoop( factory, log_fn=rec.log, **loop_kwargs )
    runner.run()
    return runner


def test_sweep_passes_BOTH_roots_and_live_session_ids():
    """The root-cause line: `self._hold_janitor_fn()` passed NOTHING. No base_dir ⇒
    LUPIN_ROOT ⇒ one directory, blind to every other tree. No live_session_ids ⇒
    `authoritative` always False ⇒ the janitor's entire positive-dead branch was
    UNREACHABLE in production — dead code that only ever ran in tests."""
    rec  = Recorder()
    seen = { }
    def _spy( **kwargs ):
        seen.update( kwargs )
        return _report()
    _one_cycle( rec, hold_janitor_fn=_spy,
                hold_roots_fn=lambda: [ "/projects/lupin", "/projects/pip" ],
                live_session_ids_fn=lambda: { "live-1", "live-2" } )
    assert seen[ "base_dirs" ]        == [ "/projects/lupin", "/projects/pip" ]
    assert seen[ "live_session_ids" ] == { "live-1", "live-2" }


def test_sweep_emits_UNCONDITIONALLY_even_when_nothing_is_prunable():
    """Rio's defect: the old line was `if pruned:` — it logged ONLY on a non-empty
    result. So a sweep that reached NOTHING and a sweep that found nothing to reap
    were both SILENT, and both identical to a healthy tick. This report IS the
    milestone's acceptance evidence; built on that line, the evidence for a
    total-failure sweep was an empty log. A check that cannot fail is not a check."""
    rec = Recorder()
    _one_cycle( rec, hold_janitor_fn=lambda **kw: _report( files_found=12, prunable=0, keep=12 ) )
    reports = [ kw for e, kw in rec.logs if e == "fleet_arbiter_hold_report" ]
    assert len( reports ) == 1                       # emitted despite prunable == 0
    assert reports[ 0 ][ "files_seen" ] == 12
    assert reports[ 0 ][ "prunable" ]   == 0
    assert reports[ 0 ][ "deleted" ]    == 0


def test_sweep_SWEPT_ZERO_ROOTS_fires_a_DISTINCT_event_from_found_zero_prunable():
    """'I reached no roots' and 'I reached everything and there was nothing to reap'
    are opposite facts. A lone zero cannot tell them apart — so the no-roots case
    gets its own event. This is the negative control on the multi-root fix itself:
    a janitor pointed at the wrong roots (the /var/external-projects container paths
    that do not exist on the host) produces an empty report, and THAT is how we
    learn the root list is wrong instead of reading it as success."""
    rec = Recorder()
    _one_cycle( rec, hold_janitor_fn=lambda **kw: _report(
        roots_swept=(), roots_requested=[ "/var/external-projects/skills-distillation" ],
        roots_unreachable=[ { "root": "/var/external-projects/skills-distillation",
                              "error": "not_a_directory" } ] ) )
    no_roots = [ kw for e, kw in rec.logs if e == "fleet_arbiter_hold_report_no_roots" ]
    assert len( no_roots ) == 1
    assert no_roots[ 0 ][ "roots_requested" ]   == [ "/var/external-projects/skills-distillation" ]
    assert no_roots[ 0 ][ "roots_unreachable" ][ 0 ][ "error" ] == "not_a_directory"
    # ...and the full report still lands too — the loud event ADDS, never replaces.
    assert len( [ kw for e, kw in rec.logs if e == "fleet_arbiter_hold_report" ] ) == 1


def test_sweep_healthy_roots_do_NOT_fire_the_no_roots_event():
    """PRESENCE-control on the test above: the no-roots alarm must be capable of
    staying quiet, or its firing proves nothing."""
    rec = Recorder()
    _one_cycle( rec, hold_janitor_fn=lambda **kw: _report( roots_swept=( "/projects/lupin", ) ) )
    assert not [ e for e, _ in rec.logs if e == "fleet_arbiter_hold_report_no_roots" ]


def test_sweep_report_carries_the_cargo_and_classification_tallies():
    rec = Recorder()
    _one_cycle( rec, hold_janitor_fn=lambda **kw: _report(
        files_found=45, prunable=20, keep=25, cargo_bearing=33, ttl_unusable=22,
        anchor_disagreement=1, kept_reasons={ "no_provable_age": 22 },
        skipped=[ { "dir": "/projects/lupin/.claude/worktrees", "hold_count": 1 } ] ) )
    r = [ kw for e, kw in rec.logs if e == "fleet_arbiter_hold_report" ][ 0 ]
    assert r[ "cargo_bearing" ]           == 33      # the population deletion must not touch
    assert r[ "ttl_unusable" ]            == 22
    assert r[ "anchor_disagreement" ]     == 1
    assert r[ "kept_reasons" ]            == { "no_provable_age": 22 }
    assert r[ "skipped_dirs_with_holds" ] == [ { "dir": "/projects/lupin/.claude/worktrees",
                                                 "hold_count": 1 } ]


def test_sweep_roots_fn_returning_none_is_tolerated():
    rec = Recorder()
    seen = { }
    def _spy( **kwargs ):
        seen.update( kwargs )
        return _report()
    _one_cycle( rec, hold_janitor_fn=_spy, hold_roots_fn=lambda: None )
    assert seen[ "base_dirs" ] == [ ]


def test_sweep_exception_swallowed():
    # sweep blow-up must NOT kill the supervisor — logged + cycle proceeds
    rec = Recorder()
    def _boom( **kwargs ):
        raise OSError( "janitor exploded" )
    runner = _one_cycle( rec, hold_janitor_fn=_boom )
    assert runner.cycles == 1
    assert any( e == "fleet_arbiter_hold_janitor_error" for e, _ in rec.logs )


def test_sweep_roots_fn_exception_swallowed():
    rec = Recorder()
    def _boom():
        raise OSError( "root resolution exploded" )
    runner = _one_cycle( rec, hold_janitor_fn=_noop_report, hold_roots_fn=_boom )
    assert runner.cycles == 1
    assert any( e == "fleet_arbiter_hold_janitor_error" for e, _ in rec.logs )


def test_supervisor_deletes_NOTHING_unless_deletion_is_explicitly_opted_IN( tmp_path ):
    """SUCCESSOR to `test_supervisor_CANNOT_delete_a_hold_file` (11461241, 2026-07-26).

    THE OLD TEST STAYED GREEN WHILE THE INVARIANT IT NAMED BECAME FALSE, and that is
    why it was replaced rather than edited. It asserted two things:

      1. no literal `.unlink` attribute in six function sources, via an AST scan
      2. `_hold_janitor_fn is report_hold_files` on a default-constructed loop

    When reclamation was wired, BOTH still passed. (2) passed because the deleter went
    on a NEW seam, `_hold_deleter_fn`, which the assertion never looked at — it kept
    checking that the old seam still pointed at the reporter, which was true and had
    become beside the point. (1) passed because the sweep now reaches `unlink` through
    an injected CALLABLE one frame down, and a shallow attribute scan cannot see that.
    Its failure message said "REACHABLE unlink"; its implementation meant "no literal
    `.unlink` token in these six sources." The word `reachable` was doing work the
    code did not do. Found by Mr Radio 🦉 running the suite against a PREDICTION that
    it would go red — a review would not have caught it, because reading the old test
    makes it look like it covers this.

    ⇒ So this successor is BEHAVIOURAL. It puts real files on disk and asks what
    survives, which is the only formulation that cannot be fooled by where the call
    lives or how many frames down the unlink sits.
    """
    import json, time
    from lupin_cli.claude_code.hooks.lib import heartbeat_hold as hh

    def _write_hold( name, age_seconds, **extra ):
        p = tmp_path / f".heartbeat-hold-{name}.json"
        held = datetime.datetime.now( datetime.timezone.utc ) - datetime.timedelta( seconds=age_seconds )
        body = { "session_id": name, "held_at": held.isoformat(), "ttl_seconds": 60 }
        body.update( extra )
        p.write_text( json.dumps( body ) )
        old = time.time() - age_seconds
        os.utime( p, ( old, old ) )              # mtime anchor must agree with held_at
        return p

    ancient = _write_hold( "plainold", 86400 )
    cargo   = _write_hold( "precious", 86400, note_to_my_successor="the only copy of this" )

    # ── DEFAULT CONSTRUCTION: deletion is OPT-IN, so BOTH files must survive ──
    loop = FleetArbiterLoop( lambda: None, log_fn=lambda *a, **k: None,
                             hold_roots_fn=lambda: [ str( tmp_path ) ],
                             live_session_ids_fn=lambda: set() )
    loop._sweep_hold_files()
    assert ancient.exists(), "default-constructed supervisor DELETED — omission must be the safe state (A0)"
    assert cargo.exists()

    # ── OPTED IN: the plain file goes, the CARGO file still does not ──
    loop = FleetArbiterLoop( lambda: None, log_fn=lambda *a, **k: None,
                             hold_roots_fn=lambda: [ str( tmp_path ) ],
                             live_session_ids_fn=lambda: set(),
                             enable_hold_deletion=True )
    loop._sweep_hold_files()
    assert not ancient.exists(), "POSITIVE CONTROL FAILED: opted-in sweep deleted nothing — the test proves nothing"
    assert cargo.exists(), "CARGO FILE DELETED — the structural guard did not hold"

    # The destructive fn is still the one on the deleter seam (a rename must not silently unwire it).
    assert FleetArbiterLoop( lambda: None )._hold_deleter_fn is hh.prune_stale_hold_files


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


# ── bug 26dd3afb: the :8001 factory MUST wire the real bridge-mtime veto reader ─
# Same deploy-honesty guard as the hold-reader test above — without factory
# wiring the veto seam is None → the MANAGER-STALE bridge-mtime veto is DECORATIVE
# on the real :8001 deploy and Tiberius-class false positives recur.

def test_build_factory_wires_real_bridge_mtimes_by_default():
    """The :8001 factory defaults bridge_mtimes_fn to the real persona→bridge-mtime
    reader so the MANAGER-STALE veto is LIVE on deploy (not inert)."""
    from lupin_arbiter_app.fleet_arbiter_loop import _default_manager_bridge_mtimes
    gw, store = FakeGateway(), LocalSnapshotStore()
    job = build_fleet_arbiter_job_factory( gw, store, log_fn=lambda *a, **k: None )()
    assert job._bridge_mtimes_fn is _default_manager_bridge_mtimes


def test_build_factory_allows_fake_bridge_mtimes_reader():
    """An injected fake bridge-mtime reader overrides the default (test seam)."""
    gw, store = FakeGateway(), LocalSnapshotStore()
    fake = lambda: { "tiberius": 1.0 }
    job  = build_fleet_arbiter_job_factory(
        gw, store, log_fn=lambda *a, **k: None, bridge_mtimes_fn=fake )()
    assert job._bridge_mtimes_fn is fake


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


# ─────────────────────────────────────────────────────────────────────────────
# Q1 ROOT SOURCE — "config + host-path translation + parent scan" (Rick, 2026-07-16)
#
# NO TEST HERE ASSERTS A CENSUS COUNT. The hold corpus is LIVE — it measured
# 41 → 43 → 44 → 45 across five honest measurements with zero errors anywhere,
# because sessions write holds while you are counting them. Every assertion below
# is on a PROPERTY.
# ─────────────────────────────────────────────────────────────────────────────

class FakeConfigMgr:
    """A ConfigurationManager-shaped stub: only .get( key, default, return_type )."""

    def __init__( self, repos=(), paths=None ):
        self._repos = list( repos )
        self._paths = dict( paths or { } )

    def get( self, key, default=None, return_type=None ):
        if key == "external repos":
            return list( self._repos )
        if key.startswith( "external repo " ) and key.endswith( " path" ):
            return self._paths.get( key[ len( "external repo " ) : -len( " path" ) ], default )
        return default


def _git( *args, cwd ):
    """Run a git command in cwd, quietly. Raises on failure — a broken fixture must be LOUD."""
    subprocess.run( [ "git", *args ], cwd=str( cwd ), check=True,
                    capture_output=True, text=True, timeout=30 )


def _git_common_dir( path ):
    """The REPO identity of a tree — what the refuted dedupe rule would have keyed on."""
    out = subprocess.run( [ "git", "-C", str( path ), "rev-parse",
                            "--path-format=absolute", "--git-common-dir" ],
                          capture_output=True, text=True, timeout=30 )
    return os.path.realpath( out.stdout.strip() )


def _git_init_with_worktree( main, worktree ):
    """
    A REAL main repo + a REAL linked worktree — two distinct trees that genuinely
    share one git-common-dir. Hand-faking a `.git` file does not reproduce this.
    """
    main.mkdir( parents=True )
    _git( "init", "-q", cwd=main )
    _git( "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
          "--allow-empty", "-m", "seed", cwd=main )
    _git( "worktree", "add", "-q", "--detach", str( worktree ), cwd=main )


def _make_projects_tree( tmp_path ):
    """
    A miniature of the real host layout: a projects parent holding registered repos,
    a NON-repo grouping dir (google/), and an UNREGISTERED repo one level under it —
    which is `google/harvey-labs`, the case the parent scan exists for.
    """
    projects = tmp_path / "projects"
    for rel in ( "lupin", "planning-is-prompting", "google/skills-distillation",
                 "google/harvey-labs" ):
        ( projects / rel / ".git" ).mkdir( parents=True )
    ( projects / "not-a-repo" ).mkdir()                          # no .git → not a root
    return projects


# ---- the negative control: the bug the ruling exists to fix ----------------

def test_NEGATIVE_CONTROL_untranslated_container_paths_reach_nothing( tmp_path ):
    """
    THE BUG, PINNED. Rick's first ruling — "just reuse the registered-project
    config" — hands back CONTAINER paths (/var/external-projects/…) while the
    arbiter runs on the HOST, where they do not exist. The root list looks
    perfectly reasonable and reaches ZERO holds.

    This test asserts the FAILURE is LOUD: every untranslated root must be
    REPORTED (emitted verbatim → roots_unreachable downstream), never silently
    skipped. It is the control that MUST fail — delete the translation and
    `test_translation_is_what_reaches_the_holds` goes RED while this one stays
    green, which is exactly how you tell "swept 0 roots" from "found 0 prunable".

    ⚠️ Bug 7c2e889e — this control used to hard-code the REAL container literals
    (/var/external-projects/…) and assert `not is_dir()` on them as "host truth".
    That is not a truth, it is an accident of what happens to be mounted: those
    paths genuinely exist inside lupin-rest-test (the multi-repo doc-viewer bind),
    so the control went RED in the venue CLOSEST to where the arbiter's translation
    problem actually lives, and was green on the host only because nothing was
    mounted there. A control whose falsity is venue-dependent is not a control, and
    every mount added makes it worse — silently, had it not already been red.

    So absence is now a property of THIS fixture rather than of the venue: the
    container-shaped roots live under `tmp_path`, which pytest makes unique per test
    and which is never created. The claims about the REAL literals are kept, but
    stated as claims about `_translate_container_root` — which never touches the
    filesystem — so they hold identically on the host and in any container.
    """
    projects = _make_projects_tree( tmp_path )

    # Container-SHAPED, absent BY CONSTRUCTION — never created, unique per test.
    absent_mount = tmp_path / "absent-mount" / "external-projects"
    container    = [ str( absent_mount / "lupin" ),
                     str( absent_mount / "google" / "skills-distillation" ) ]

    for raw in container:
        assert not Path( raw ).is_dir()                          # true in EVERY venue
        # …and no anchor can be derived against a host root, so nothing translates:
        assert _translate_container_root( raw, None ) is None

    # The real container literals, asserted where it is safe to assert them: with no
    # anchor, translation short-circuits before any filesystem access, so this pins
    # the actual bug shape without depending on what is mounted.
    for raw in [ "/var/external-projects/lupin", "/var/external-projects/google/skills-distillation" ]:
        assert _translate_container_root( raw, None ) is None

    # The whole point: a config-derived list, untranslated, reaches nothing.
    # `cosa-voice` cannot anchor against a host root named `lupin`, so it is emitted
    # VERBATIM. Asserting the exact root list is stronger than the old is_dir() filter
    # AND owes nothing to the filesystem: scan_fn is empty, so this is fully determined.
    unreachable = str( absent_mount / "cosa-voice" )
    roots = _compute_hold_roots( FakeConfigMgr( repos=[ "cosa-voice" ],
                                                paths={ "cosa-voice": unreachable } ),
                                 host_root=str( projects / "lupin" ),
                                 scan_fn=lambda: [ ] )
    assert roots == [ str( projects / "lupin" ), unreachable ]    # PASSED THROUGH, not dropped
    #     ^ emitted on purpose so the sweep reports it in roots_unreachable:
    #       the gap stays a NUMBER instead of a silence.


def test_translation_is_what_reaches_the_holds( tmp_path ):
    """
    THE POSITIVE CONTROL, paired with the negative one above — proving the check
    is non-vacuous. Same config, same host tree; the ONLY difference is that an
    anchor exists, so translation happens. Measured on the real corpus, this is
    the difference between reaching 4 holds and reaching 44.
    """
    projects = _make_projects_tree( tmp_path )
    cfg      = FakeConfigMgr(
        repos=[ "lupin", "skills-distillation" ],
        paths={ "lupin"               : "/var/external-projects/lupin",
                "skills-distillation" : "/var/external-projects/google/skills-distillation" } )

    roots = _compute_hold_roots( cfg, host_root=str( projects / "lupin" ), scan_fn=lambda: [ ] )

    assert str( projects / "google" / "skills-distillation" ) in roots   # container → host
    assert all( not r.startswith( "/var/" ) for r in roots )             # nothing left untranslated
    assert all( Path( r ).is_dir() for r in roots )                      # every root REACHES


# ---- anchor derivation ------------------------------------------------------

def test_anchor_pair_derives_the_prefix_map_without_a_hardcoded_swap():
    pair = _derive_container_host_prefix( [ "/var/external-projects/lupin" ], "/mnt/DATA01/projects/lupin" )
    assert pair == ( "/var/external-projects", "/mnt/DATA01/projects" )


def test_anchor_self_calibrates_when_the_mount_moves():
    """Re-mount the tree and the mapping follows — no edit to the module."""
    pair = _derive_container_host_prefix( [ "/somewhere/else/lupin" ], "/new/host/root/lupin" )
    assert pair == ( "/somewhere/else", "/new/host/root" )


def test_no_anchor_when_no_config_entry_matches_this_project():
    assert _derive_container_host_prefix( [ "/var/external-projects/other" ], "/host/lupin" ) is None


def test_no_anchor_from_a_bare_root_level_path():
    """A path with no prefix to strip is not an anchor (would map "/" → everything)."""
    assert _derive_container_host_prefix( [ "/lupin" ], "/host/lupin" ) is None


def test_anchorless_config_translates_nothing_but_stays_loud( tmp_path ):
    """No anchor ⇒ every config root passes through untranslated ⇒ all reported."""
    cfg   = FakeConfigMgr( repos=[ "a" ], paths={ "a": "/var/external-projects/a" } )
    roots = _compute_hold_roots( cfg, host_root=str( tmp_path ), scan_fn=lambda: [ ] )
    assert "/var/external-projects/a" in roots                   # untranslated → reported downstream


# ---- translation ------------------------------------------------------------

def test_translate_rejects_a_path_outside_the_mapped_mount( tmp_path ):
    """`/var/lupin/src/lupin-mobile` shares no prefix with `/var/external-projects`."""
    assert _translate_container_root( "/var/lupin/src/lupin-mobile",
                                      ( "/var/external-projects", str( tmp_path ) ) ) is None


def test_translate_rejects_a_prefix_that_only_looks_like_a_match( tmp_path ):
    """`/var/external-projects-backup` must NOT match the `/var/external-projects` mount."""
    assert _translate_container_root( "/var/external-projects-backup/x",
                                      ( "/var/external-projects", str( tmp_path ) ) ) is None


def test_translate_rejects_a_translation_that_does_not_exist( tmp_path ):
    """Selection is a hypothesis; EXISTENCE is the verification."""
    assert _translate_container_root( "/var/external-projects/ghost",
                                      ( "/var/external-projects", str( tmp_path ) ) ) is None


def test_translate_of_the_mount_root_itself( tmp_path ):
    assert _translate_container_root( "/var/external-projects",
                                      ( "/var/external-projects", str( tmp_path ) ) ) == str( tmp_path )


def test_translate_survives_an_oserror( monkeypatch, tmp_path ):
    def boom( self ):
        raise OSError( "stat exploded" )
    monkeypatch.setattr( Path, "is_dir", boom )
    assert _translate_container_root( "/var/external-projects/x",
                                      ( "/var/external-projects", str( tmp_path ) ) ) is None


def test_translate_without_an_anchor_is_none():
    assert _translate_container_root( "/var/external-projects/x", None ) is None


# ---- the parent scan (the safety net) --------------------------------------

def test_parent_scan_finds_the_UNREGISTERED_repo_the_config_forgot( tmp_path ):
    """
    google/harvey-labs: a real repo, holding a real hold, with ZERO config mentions.
    Without this scan it is unreachable forever — a registry cannot report what was
    never written into it.
    """
    projects = _make_projects_tree( tmp_path )
    found    = _scan_parent_for_repo_roots( projects )
    assert str( projects / "google" / "harvey-labs" ) in found   # depth 2, under a non-repo dir
    assert str( projects / "lupin" ) in found                    # depth 1
    assert str( projects / "not-a-repo" ) not in found           # no .git → not a root
    assert str( projects / "google" ) not in found               # grouping dir → descended, not a root


def test_parent_scan_stops_at_a_repo_and_does_not_descend_into_it( tmp_path ):
    """A repo IS a root — the hold sweep recurses inside it; walking in here duplicates work."""
    projects = _make_projects_tree( tmp_path )
    ( projects / "lupin" / "nested" / ".git" ).mkdir( parents=True )
    found = _scan_parent_for_repo_roots( projects, max_depth=3 )
    assert str( projects / "lupin" ) in found
    assert str( projects / "lupin" / "nested" ) not in found     # not descended into


def test_parent_scan_respects_max_depth( tmp_path ):
    projects = _make_projects_tree( tmp_path )
    assert str( projects / "google" / "harvey-labs" ) not in _scan_parent_for_repo_roots( projects, max_depth=1 )


def test_parent_scan_ignores_files_and_unreadable_dirs( tmp_path ):
    projects = _make_projects_tree( tmp_path )
    ( projects / "a-file.txt" ).write_text( "not a dir" )
    assert _scan_parent_for_repo_roots( projects )               # still finds the repos
    assert _scan_parent_for_repo_roots( tmp_path / "does-not-exist" ) == [ ]   # OSError → []


def test_parent_scan_skips_an_entry_whose_type_cannot_be_read( tmp_path, monkeypatch ):
    projects = _make_projects_tree( tmp_path )
    real_scandir = os.scandir

    class Exploding:
        def __init__( self, entry ): self.path = entry.path; self.name = entry.name
        def is_dir( self, follow_symlinks=True ): raise OSError( "type unreadable" )

    monkeypatch.setattr( os, "scandir",
                         lambda p: [ Exploding( e ) for e in real_scandir( p ) ] )
    assert _scan_parent_for_repo_roots( projects ) == [ ]        # every entry skipped, no raise


def test_is_repo_root_survives_an_oserror( monkeypatch, tmp_path ):
    def boom( self ):
        raise OSError( "stat exploded" )
    monkeypatch.setattr( Path, "exists", boom )
    assert _is_repo_root( tmp_path ) is False


# ---- the union + realpath dedupe -------------------------------------------

def test_union_covers_both_halves_blind_spots( tmp_path ):
    """Config names what the scan's depth misses; the scan catches what config forgot."""
    projects = _make_projects_tree( tmp_path )
    deep     = projects / "a" / "b" / "c" / "registered-but-deep"
    ( deep / ".git" ).mkdir( parents=True )
    cfg = FakeConfigMgr( repos=[ "lupin", "deep" ],
                         paths={ "lupin": "/var/external-projects/lupin",
                                 "deep" : "/var/external-projects/a/b/c/registered-but-deep" } )

    roots = _compute_hold_roots( cfg, host_root=str( projects / "lupin" ) )   # REAL scan

    assert str( deep ) in roots                                  # config half: too deep to scan
    assert str( projects / "google" / "harvey-labs" ) in roots   # scan half: unregistered


def test_dedupe_is_on_realpath_so_the_same_tree_is_swept_once( tmp_path ):
    """A symlinked spelling of a root is the SAME TREE — sweep it once."""
    projects = _make_projects_tree( tmp_path )
    link     = tmp_path / "lupin-link"
    link.symlink_to( projects / "lupin" )
    cfg = FakeConfigMgr( repos=[ "lupin" ], paths={ "lupin": "/var/external-projects/lupin" } )

    roots = _compute_hold_roots( cfg, host_root=str( projects / "lupin" ),
                                 scan_fn=lambda: [ str( link ) ] )

    identities = [ os.path.realpath( r ) for r in roots ]
    assert len( identities ) == len( set( identities ) )         # no tree swept twice
    assert str( link ) not in roots                              # the dupe spelling dropped


def test_dedupe_does_NOT_collapse_a_worktree_into_its_main_repo( tmp_path ):
    """
    🔴 THE REFUTED INSTRUCTION, PINNED AS A TEST — on a REAL git worktree.

    Deduping on `git --git-common-dir` would treat a worktree and its main repo as
    ONE identity and DROP a root that demonstrably holds a hold today
    (lupin/.claude/worktrees/cheech-orphan-bridge). git-common-dir is the identity
    of a REPO; these are two TREES with different files.

    ⚠️ THE FIXTURE IS THE TEST. A hand-faked `.git` text file does NOT work here:
    `git rev-parse` errors on it and falls back to realpath, so the test passes
    under BOTH dedupe rules and pins NOTHING. It has to be a real worktree, or this
    is decoration. (It was decoration when first written — a faithful
    git-common-dir mutant survived it. Verified dead only after this rewrite.)
    """
    projects = _make_projects_tree( tmp_path )
    main     = projects / "real-repo"
    worktree = projects / "real-worktree"
    _git_init_with_worktree( main, worktree )

    # The fixture's own precondition: the two trees DO share a git-common-dir.
    # If this ever stops holding, the test below is vacuous again and must be fixed.
    assert _git_common_dir( main ) == _git_common_dir( worktree )

    roots = _compute_hold_roots( FakeConfigMgr(), host_root=str( projects / "lupin" ),
                                 scan_fn=lambda: [ str( main ), str( worktree ) ] )

    assert str( main ) in roots
    assert str( worktree ) in roots                              # SAME repo, DIFFERENT tree → kept


def test_host_root_is_always_present_even_with_an_empty_config( tmp_path ):
    roots = _compute_hold_roots( FakeConfigMgr(), host_root=str( tmp_path ), scan_fn=lambda: [ ] )
    assert roots == [ str( tmp_path ) ]


def test_config_order_first_then_scan_order( tmp_path ):
    projects = _make_projects_tree( tmp_path )
    cfg      = FakeConfigMgr( repos=[ "lupin", "pip" ],
                              paths={ "lupin": "/var/external-projects/lupin",          # the anchor
                                      "pip"  : "/var/external-projects/planning-is-prompting" } )
    roots    = _compute_hold_roots( cfg, host_root=str( projects / "lupin" ),
                                    scan_fn=lambda: [ str( projects / "google" / "harvey-labs" ) ] )
    assert roots == [ str( projects / "lupin" ),                 # host_root first (config's lupin dedupes)
                      str( projects / "planning-is-prompting" ),  # …then config order
                      str( projects / "google" / "harvey-labs" ) ]   # …then scan order


# ---- the raw config read ----------------------------------------------------

def test_registry_container_paths_reads_raw_untranslated_values():
    cfg = FakeConfigMgr( repos=[ "a", "b" ],
                         paths={ "a": "/var/external-projects/a", "b": "/var/lupin/src/b" } )
    assert _registry_container_paths( cfg ) == [ "/var/external-projects/a", "/var/lupin/src/b" ]


def test_registry_container_paths_drops_blank_and_missing_entries():
    cfg = FakeConfigMgr( repos=[ "a", "  ", "no-path", "blank" ],
                         paths={ "a": "  /var/x/a  ", "blank": "   " } )
    assert _registry_container_paths( cfg ) == [ "/var/x/a" ]    # stripped; blanks/missing dropped


def test_registry_container_paths_of_an_empty_registry():
    assert _registry_container_paths( FakeConfigMgr() ) == [ ]


# ---- F-C: the pragmas come OFF — these functions are REACHABLE -------------

def test_default_hold_roots_executes_the_real_production_path():
    """
    F-C: this carried `# pragma: no cover - production project-root IO boundary`.
    It RUNS — so the pragma was invalid under the 100% mandate. Properties only;
    the fleet's root list is live and unassertable as a count.
    """
    roots = _default_hold_roots()
    assert isinstance( roots, list ) and roots
    assert all( isinstance( r, str ) for r in roots )
    import cosa.utils.util as cu
    assert cu.get_project_root() in roots                        # own project always reachable
    identities = [ os.path.realpath( r ) for r in roots ]
    assert len( identities ) == len( set( identities ) )         # deduped on tree identity


def test_default_live_session_ids_executes_and_includes_persona_less_sessions():
    """F-C: also pragma'd, also reachable — it returns the live set in ~0.00s."""
    live = _default_live_session_ids()
    assert live is None or isinstance( live, set )


def test_default_live_session_ids_uses_require_persona_FALSE():
    """
    F-B, pinned. `find_active_voice_persona_sessions` is imported one line up and is
    the WRONG source: persona'd sessions ONLY ⇒ a live but persona-LESS session
    (pool-exhausted — bug d57dbfea) reads as POSITIVE-DEAD and loses its hold at TTL
    with no grace. That is the forbidden relaxation of bias-to-keep.
    """
    seen = { }

    def fake_find( require_persona=True ):
        seen[ "require_persona" ] = require_persona
        return [ ( "/p/a", "sid-persona'd", { "name": "rio" } ),
                 ( "/p/b", "sid-persona-LESS", None ) ]

    live = _default_live_session_ids( find_fn=fake_find )
    assert seen[ "require_persona" ] is False
    assert live == { "sid-persona'd", "sid-persona-LESS" }        # the persona-less one SURVIVES


def test_default_live_session_ids_degrades_to_None_not_a_partial_set():
    """A half-enumerated live-set is WORSE than none — absence licenses the no-grace prune."""
    def boom( require_persona=True ):
        raise RuntimeError( "bridge scan exploded" )
    assert _default_live_session_ids( find_fn=boom ) is None      # NO authoritative set


# ---- F-C third instance (bug 3cd0d4c1): the last pragma comes OFF ----------

def test_default_manager_bridge_mtimes_executes_the_real_production_path():
    """
    F-C #3. This carried `# pragma: no cover - production bridge-scan IO boundary`
    and the claim "unit tests inject a fake, so this boundary is no-cover". It RUNS
    (~0.00s) — so the pragma was invalid. A pragma'd function is EXEMPT FROM THE
    INSTRUMENT: coverage reports green over code nobody has proven runs.
    Properties only — the live fleet's persona set is not assertable as a count.
    """
    mtimes = _default_manager_bridge_mtimes()
    assert isinstance( mtimes, dict )
    assert all( isinstance( k, str ) and isinstance( v, float ) for k, v in mtimes.items() )


def test_manager_bridge_mtimes_keeps_the_FRESHEST_mtime_per_persona( tmp_path ):
    """One persona, several live sessions → the freshest bridge wins (the re-spun twin)."""
    stale, fresh = tmp_path / "stale.json", tmp_path / "fresh.json"
    stale.write_text( "{}" ); fresh.write_text( "{}" )
    os.utime( stale, ( 1000, 1000 ) )
    os.utime( fresh, ( 9000, 9000 ) )

    def fake_find():
        return [ ( str( stale ), "sid-old", { "name": "rio" } ),
                 ( str( fresh ), "sid-new", { "name": "rio" } ) ]

    assert _default_manager_bridge_mtimes( find_fn=fake_find ) == { "rio": 9000.0 }


def test_manager_bridge_mtimes_freshest_wins_regardless_of_scan_order( tmp_path ):
    """The max must not depend on which bridge the scan happens to yield first."""
    stale, fresh = tmp_path / "stale.json", tmp_path / "fresh.json"
    stale.write_text( "{}" ); fresh.write_text( "{}" )
    os.utime( stale, ( 1000, 1000 ) )
    os.utime( fresh, ( 9000, 9000 ) )
    reversed_order = lambda: [ ( str( fresh ), "s1", { "name": "rio" } ),
                               ( str( stale ), "s2", { "name": "rio" } ) ]
    assert _default_manager_bridge_mtimes( find_fn=reversed_order ) == { "rio": 9000.0 }


def test_manager_bridge_mtimes_skips_nameless_unkeyable_and_unreadable( tmp_path ):
    """
    Every skip branch: no persona · blank name · unkeyable name · unreadable mtime.

    ⚠️ EACH ENTRY IS ISOLATED ON A REAL, READABLE FILE — that is load-bearing. A first
    draft pointed the nameless/unkeyable entries at MISSING paths, so the OSError skip
    MASKED the name skips: those entries died on the missing file no matter what any
    name guard did. The branches were 100% COVERED and still pinned NOTHING. Coverage
    is not discrimination — it says the line RAN, not that this test would NOTICE if
    it were WRONG.

    WHAT THIS TEST PINS, precisely — and no more. Each verified KILLED by a runtime
    mutant on a harness whose canary died first (so the injection is proven to land):
      • `if not key: continue` — drop it and the nameless/blank/unkeyable entries land
        under a "" key ⇒ the equality assert goes RED.
      • the freshest-mtime rule — take-first or flip `>` to `<` ⇒ RED.
      • the OSError skip — remove it and the missing-file entry lands ⇒ RED.

    ⛔ WHAT NO TEST CAN PIN — stated here because the honest limit belongs in the
    record, not a claim nobody can cash: there is NO independent blank-name guard to
    pin, BY DESIGN. `canonical_persona_key` DECLARES `Requires: name is a string or
    None` and GUARANTEES `None / non-string / empty / whitespace-only -> ""`, so the
    single key guard covers every nameless case BY CONTRACT. The redundant
    `if not name: continue` that used to precede it was an EQUIVALENT MUTANT —
    deleting it was behavior-preserving, so NOTHING could ever kill it. It is now
    deleted rather than described. (An earlier version of this docstring claimed
    "dropping any name guard ⇒ RED". That was FALSE for the blank-name guard, and it
    was the one sentence a future seat would trust instead of re-deriving.)
    """
    named, blank, unkeyable, nameless = ( tmp_path / f"{n}.json"
                                          for n in ( "named", "blank", "unkeyable", "nameless" ) )
    for f in ( named, blank, unkeyable, nameless ):
        f.write_text( "{}" )
        os.utime( f, ( 5000, 5000 ) )                   # ALL readable → only the name guards can skip them

    def fake_find():
        return [ ( str( nameless ),   "s1", None ),                 # no persona dict
                 ( str( blank ),      "s2", { "name": "" } ),       # blank name
                 ( str( unkeyable ),  "s3", { "name": "!!!" } ),    # unkeyable → canonical key falsy
                 ( "/nope/gone.json", "s4", { "name": "rio" } ),    # name OK, file MISSING → OSError
                 ( str( named ),      "s5", { "name": "sam" } ) ]   # the only survivor

    assert _default_manager_bridge_mtimes( find_fn=fake_find ) == { "sam": 5000.0 }


def test_manager_bridge_mtimes_of_an_empty_fleet():
    assert _default_manager_bridge_mtimes( find_fn=lambda: [ ] ) == { }


# ---- the invariant that outranks all of the above ---------------------------

def test_the_ruled_root_source_still_CANNOT_delete_anything():
    """
    The sweep got ~10× wider tonight. Width is exactly what makes a deletion bug
    catastrophic — so the no-unlink invariant is re-asserted against the NEW root
    source, not assumed to have survived it.
    """
    import ast, inspect
    import lupin_arbiter_app.fleet_arbiter_loop as mod

    tree     = ast.parse( inspect.getsource( mod ) )
    unlinks  = [ n for n in ast.walk( tree )
                 if isinstance( n, ast.Attribute ) and n.attr in ( "unlink", "rmtree", "remove", "rmdir" ) ]
    assert unlinks == [ ]                                        # not one deletion call in the module

    # POSITIVE CONTROL — the AST check is non-vacuous: it DOES find an unlink when
    # one is there. (A guard that cannot fail is the exact defect this milestone is
    # about; my predecessor wrote one INSIDE the fix for it — his grep matched the
    # word "unlink" in a DOCSTRING.)
    import lupin_cli.claude_code.hooks.lib.heartbeat_hold as hold_mod
    hold_tree = ast.parse( inspect.getsource( hold_mod ) )
    assert [ n for n in ast.walk( hold_tree )
             if isinstance( n, ast.Attribute ) and n.attr == "unlink" ]   # prune_stale_hold_files has one
