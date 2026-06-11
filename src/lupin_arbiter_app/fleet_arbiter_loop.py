#!/usr/bin/env python3
"""
Fleet-arbiter loop — the standing fleet-stall arbiter (L3 of the :8001 lupin-arbiter-app service).

Reuses the v2.2 `ArbiterConsumerJob` AS-IS (zero logic edits → its invariants carry
by construction: never-auto-assign · additive-observer one-way · lineage-derived
routing). The standalone difference is purely WIRING + SUPERVISION:

  • RECYCLE-WRAPPER (FleetArbiterLoop): the job's `do_all()` returns after the 12h
    `max_duration` cap; a host-side thread that ran it ONCE would then sit silently
    dead while uvicorn keeps serving — and systemd's Restart=always only catches
    PROCESS exit, NOT a clean background-thread return. So FleetArbiterLoop RELAUNCHES a
    fresh job on every clean cap-exit. SEQUENTIAL by construction (do_all() returns
    before the next job starts) → exactly one job runs at a time = the :8001-side
    single-instance (the in-process arbiter is the SEPARATE mechanism, gated OFF by
    the R0 flag; never two).

  • OUT-OF-BAND (R4): the job's snapshot_sink is overridden to write the :8001-LOCAL
    store section "fleet_arbiter" (NOT the :7999 singleton). The DETECTION path is
    strictly :7999-free (events_tail / who / manager_resolver / sink are filesystem).

  • ESCALATION (ruling A): notify_fn ALWAYS posts to the durable `fleet-escalations`
    commons topic (degrade-safe — swallow+log) AND best-effort fires an injected,
    swallowed live_notify_fn (the ONLY place a :7999 notify may occur — escalation
    path only, never per-poll; default no-op so escalation never blocks detection).

  • WARM-UP (ruling B): each fresh job's notify_fn suppresses escalations while
    (now − job_start) < start_period_seconds — per-job-start, so cold boot / restart
    / recycle never false-fire.

All seams are injectable (job_factory / gateway / store / clock / log_fn /
live_notify_fn) → the recycle, escalation, and warm-up logic are 100% unit-tested
with fakes; only the literal external construction (gateway.from_environment) is
pragma'd, in app.create_production_app.
"""
import datetime
import json
import threading
from typing import Any, Callable, Optional

from lupin_arbiter_app.health_watcher import SystemClock
from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob


ESCALATION_TOPIC = "fleet-escalations"


def _default_log_fn( event: str, **fields: Any ) -> None:
    """Structured JSON line (loop:fleet_arbiter) to stdout → systemd journal (flushed)."""
    line : dict = {
        "ts"      : datetime.datetime.now( datetime.timezone.utc ).isoformat(),
        "service" : "lupin-arbiter-app",
        "loop"    : "fleet_arbiter",
        "event"   : event,
    }
    line.update( fields )
    print( json.dumps( line, default=str ), flush=True )


# ── escalation output sink (ruling A) ───────────────────────────────────────

def make_escalation_notify_fn(
    gateway       : Any,
    *,
    live_notify_fn : Optional[ Callable[ [ str ], None ] ] = None,
    log_fn         : Optional[ Callable ]                  = None,
    topic          : str                                   = ESCALATION_TOPIC,
) -> Callable[ [ str ], None ]:
    """
    Build the escalation-OUTPUT notify_fn: durable-primary + best-effort live.

    Ensures:
        - ALWAYS posts `message` to the durable commons `topic` via the bridge-less
          gateway; a write failure is swallowed+logged (the PRIMARY channel must
          not kill the loop any more than the best-effort one — note 3)
        - if live_notify_fn is provided, best-effort fires it (swallowed+logged on
          failure) — this is the ONLY :7999-capable hop, escalation-path only
        - never raises
    """
    log_fn = log_fn if log_fn is not None else _default_log_fn

    def notify_fn( message: str ) -> None:
        try:
            gateway.post( topic, message )
        except Exception as e:                       # durable post degrade-safe (note 3)
            log_fn( "escalation_post_error", error=str( e ) )
        if live_notify_fn is not None:
            try:
                live_notify_fn( message )
            except Exception as e:                   # best-effort live delivery, swallowed
                log_fn( "escalation_live_notify_error", error=str( e ) )

    return notify_fn


# ── warm-up suppressor (ruling B) ───────────────────────────────────────────

def make_warmup_notify_fn(
    inner                : Callable[ [ str ], None ],
    job_started_at       : datetime.datetime,
    start_period_seconds : int,
    clock                : Any,
    log_fn               : Callable,
) -> Callable[ [ str ], None ]:
    """
    Wrap an escalation notify_fn to SUPPRESS escalations during the warm-up window
    of a single job (keyed on that job's start time).

    Ensures:
        - while (clock.now() − job_started_at) < start_period_seconds → suppress
          (log `escalation_suppressed_warmup`, do NOT call inner)
        - at/after the window → pass through to inner
        - never raises
    """
    def notify_fn( message: str ) -> None:
        if ( clock.now() - job_started_at ).total_seconds() < start_period_seconds:
            log_fn( "escalation_suppressed_warmup", message=message )
            return
        inner( message )

    return notify_fn


# ── the standing-job factory ────────────────────────────────────────────────

def build_fleet_arbiter_job_factory(
    gateway              : Any,
    store                : Any,
    *,
    clock                : Optional[ Any ]      = None,
    log_fn               : Optional[ Callable ] = None,
    live_notify_fn       : Optional[ Callable ] = None,
    poll_seconds         : int                  = 60,
    manager_on_duty      : str                  = "manager-on-duty",
    declared_managers    : Optional[ list ]     = None,
    alive_threshold      : int                  = 600,
    quiet_threshold      : int                  = 300,
    tap_min_interval     : int                  = 300,
    ack_window           : int                  = 600,
    stall_window         : int                  = 1800,
    poll_error_escalate_threshold : int         = 3,
    auto_poke_enabled    : bool                 = True,
    poke_stall_threshold : int                  = 720,
    poke_max_per_episode : int                  = 3,
    manager_stale_poke_threshold : int          = 2700,
    manager_stale_poke_max_age : int            = 7200,
    start_period_seconds : int                  = 120,
) -> Callable[ [ ], ArbiterConsumerJob ]:
    """
    Build the recycle factory: each call returns a FRESH ArbiterConsumerJob wired
    bridge-less to the :8001-local store + the warm-up-wrapped escalation sink.

    Ensures:
        - returned factory() builds an ArbiterConsumerJob whose snapshot_sink writes
          store section "fleet_arbiter", whose notify_fn = warm-up(escalation(durable
          + best-effort live)), keyed on a fresh per-call job-start (warm-up resets
          on each recycle)
        - construction is pure in-memory (no IO until the job runs) — fully
          testable with a fake gateway
    """
    clock  = clock  if clock  is not None else SystemClock()
    log_fn = log_fn if log_fn is not None else _default_log_fn
    escalation_notify = make_escalation_notify_fn( gateway, live_notify_fn=live_notify_fn, log_fn=log_fn )

    def factory() -> ArbiterConsumerJob:
        job_start     = clock.now()
        warmup_notify = make_warmup_notify_fn( escalation_notify, job_start, start_period_seconds, clock, log_fn )
        return ArbiterConsumerJob(
            commons                    = gateway,
            poll_seconds               = poll_seconds,
            manager_recipient          = manager_on_duty,
            declared_managers          = declared_managers,
            alive_threshold_seconds    = alive_threshold,
            quiet_threshold_seconds    = quiet_threshold,
            tap_min_interval_seconds   = tap_min_interval,
            manager_ack_window_seconds = ack_window,
            fleet_stall_window_seconds = stall_window,
            poll_error_escalate_threshold = poll_error_escalate_threshold,
            auto_poke_enabled            = auto_poke_enabled,
            poke_stall_threshold_seconds = poke_stall_threshold,
            poke_max_per_episode         = poke_max_per_episode,
            manager_stale_poke_threshold_seconds = manager_stale_poke_threshold,   # post-game F2
            manager_stale_poke_max_age_seconds   = manager_stale_poke_max_age,     # corpse ceiling
            snapshot_sink              = lambda snap: store.set_section( "fleet_arbiter", snap ),
            render_sink                = lambda line: log_fn( "fleet_arbiter_render", line=line ),
            notify_fn                  = warmup_notify,
            log_fn                     = log_fn,                                   # post-game F1: outreach + gate events → journal
            user_id                    = "system",
            user_email                 = "system@lupin.deepily.ai",
            session_id                 = "lupin-arbiter-app-8001",
        )

    return factory


# ── recycle supervisor ──────────────────────────────────────────────────────

class FleetArbiterLoop:
    """
    The :8001-side fleet-arbiter supervisor: runs one ArbiterConsumerJob at a time on a
    background thread, RELAUNCHING a fresh job on each clean cap-exit (12h
    self-perpetuation fix). Single-instance by construction (sequential recycle).
    """

    def __init__(
        self,
        job_factory : Callable[ [ ], ArbiterConsumerJob ],
        *,
        log_fn      : Optional[ Callable ] = None,
    ) -> None:
        self._job_factory = job_factory
        self._log_fn      = log_fn if log_fn is not None else _default_log_fn
        self._stop        = threading.Event()
        self._current_job = None
        self._thread      = None
        self.cycles       = 0

    def run( self ) -> None:
        """
        Poll-supervisor loop: build a job, run it to its cap/cancel, relaunch.

        Ensures:
            - relaunches a fresh job after each clean cap-exit until stop()
            - a job blow-up is swallowed+logged (the supervisor outlives one bad job)
            - exits promptly when stop() has been signalled
            - never raises
        """
        while not self._stop.is_set():
            job = self._job_factory()
            self._current_job = job
            self.cycles += 1
            self._log_fn( "fleet_arbiter_job_start", cycle=self.cycles )
            try:
                summary = job.do_all()
            except Exception as e:                   # a job blow-up must not kill the supervisor
                self._log_fn( "fleet_arbiter_job_error", error=str( e ) )
                summary = None
            if self._stop.is_set():
                break
            self._log_fn( "fleet_arbiter_recycle", reason="clean cap-exit — relaunching", summary=summary )

    def start( self ) -> None:
        """Spawn the daemon supervisor thread."""
        self._thread = threading.Thread( target=self.run, name="fleet-arbiter-loop", daemon=True )
        self._thread.start()

    def stop( self ) -> None:
        """Signal stop, cancel the in-flight job, and join the thread."""
        self._stop.set()
        if self._current_job is not None:
            try:
                self._current_job.request_cancel()
            except Exception as e:                   # cancel must never raise out of stop()
                self._log_fn( "fleet_arbiter_cancel_error", error=str( e ) )
        if self._thread is not None:
            self._thread.join( timeout=5 )
