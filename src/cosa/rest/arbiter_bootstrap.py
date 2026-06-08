#!/usr/bin/env python3
"""
Heartbeat-Arbiter standing-cadence bootstrap (v2.2 closed-loop, lane B1).

The #1 missing piece of v2.1: the arbiter consumer was built + tested as a job
but never registered to run continuously. This module auto-submits ONE
`ArbiterConsumerJob` into CJ Flow at server startup so the fleet is observed on a
standing cadence — mirroring how other startup jobs are pushed in `main.py`'s
lifespan (the in-process agentic-pool path, per design D-A: NOT cron/out-of-
process — an in-process job dies WITH the server gracefully).

Two invariants this lane must honor (María's redlines):
  • **Additive-observer / degrade-safe:** the standing arbiter is NEVER a
    dependency of the local poke path. The dependency points ONE WAY — the
    arbiter READS the hook exhaust; no hook calls into the arbiter. If startup
    submission fails it is swallowed (broad except) so server boot + every local
    hook poke continue unaffected.
  • **Never-auto-assign:** this module only CONSTRUCTS + ENQUEUES the observer;
    it performs no spawn / assign / reassign / dismiss. (The job's own outbound
    verbs stay {who, send_to, post}.)

Single-instance guard (D-C): before submitting, scan the todo + run queues for
an existing `heartbeat_arbiter` job and no-op if one is present — so a restart
that restores a persisted arbiter job (or a double lifespan) never spawns a
duplicate observer.
"""
from typing import Any, Callable, Optional


def arbiter_already_present( todo_queue, run_queue ) -> bool:
    """
    Single-instance guard: is a heartbeat_arbiter job already queued or running?

    Requires:
        - todo_queue, run_queue expose a `queue_list` iterable of jobs (FifoQueue)

    Ensures:
        - returns True iff any job in either queue has
          JOB_TYPE == ArbiterConsumerJob.JOB_TYPE
        - tolerates jobs missing a JOB_TYPE attr (treated as non-arbiter)
        - never raises (a queue without queue_list → treated as empty)
    """
    from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob
    for queue in ( todo_queue, run_queue ):
        for job in list( getattr( queue, "queue_list", [ ] ) or [ ] ):
            if getattr( job, "JOB_TYPE", None ) == ArbiterConsumerJob.JOB_TYPE:
                return True
    return False


def build_arbiter_job( config_mgr ):   # pragma: no cover - production IO boundary
    """
    Construct the standing ArbiterConsumerJob from config + the real gateway.

    IO-boundary (marked no-cover, exercised at the :8000 integration tier, like
    LupinArbiterGateway.from_environment): wires the file-backed commons gateway
    and reads tuning params from lupin-app.ini. The guard + submit LOGIC around
    it is fully unit-tested via an injected job_builder.

    Ensures:
        - returns an ArbiterConsumerJob whose poll cadence + declared
          manager-on-duty fallback + thresholds come from config (with the
          v2.1 defaults when keys are absent)
        - manager_recipient here is the v2.1-era single fallback; v2.2 per-group
          routing (B6 resolve_manager) overrides it per stuck worker at tap time
    """
    from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob
    from cosa.agents.heartbeat_arbiter.arbiter_gateway import LupinArbiterGateway

    poll_seconds      = int( config_mgr.get( "arbiter poll seconds", default=60, return_type="int" ) )
    manager_on_duty   = config_mgr.get( "arbiter manager on duty", default="manager-on-duty" ) or "manager-on-duty"
    alive_threshold   = int( config_mgr.get( "arbiter alive threshold seconds", default=600, return_type="int" ) )
    quiet_threshold   = int( config_mgr.get( "arbiter quiet threshold seconds", default=300, return_type="int" ) )
    tap_min_interval  = int( config_mgr.get( "arbiter tap min interval seconds", default=300, return_type="int" ) )
    ack_window        = int( config_mgr.get( "arbiter manager ack window seconds", default=600, return_type="int" ) )
    stall_window      = int( config_mgr.get( "arbiter fleet stall window seconds", default=1800, return_type="int" ) )

    gateway = LupinArbiterGateway.from_environment( sender_session_id="heartbeat-arbiter" )
    return ArbiterConsumerJob(
        commons                    = gateway,
        poll_seconds               = poll_seconds,
        manager_recipient          = manager_on_duty,
        alive_threshold_seconds    = alive_threshold,
        quiet_threshold_seconds    = quiet_threshold,
        tap_min_interval_seconds   = tap_min_interval,
        manager_ack_window_seconds = ack_window,
        fleet_stall_window_seconds = stall_window,
        user_id                  = "system",
        user_email               = "system@lupin.deepily.ai",
        session_id               = "heartbeat-arbiter",
    )


def submit_arbiter_if_absent(
    todo_queue,
    run_queue,
    config_mgr,
    *,
    job_builder : Callable = build_arbiter_job,
    log         : Callable = print,
) -> Optional[ Any ]:
    """
    Standing-cadence startup submission (B1) — guarded + degrade-safe.

    Requires:
        - todo_queue / run_queue are the CJ Flow queues (expose queue_list + push)
        - config_mgr is the ConfigurationManager
        - job_builder( config_mgr ) -> a job (injected for unit testing)

    Ensures:
        - if a heartbeat_arbiter job is already present (todo or run) → no-op,
          returns None (single-instance guard, D-C)
        - else builds the arbiter job and pushes it to the todo queue, returns it
        - NEVER raises: any failure is swallowed + logged so server startup and
          every local hook poke continue unaffected (additive-observer redline)
    """
    try:
        if arbiter_already_present( todo_queue, run_queue ):
            log( "[ARBITER] standing instance already present — skip submit" )
            return None
        job = job_builder( config_mgr )
        todo_queue.push( job )
        log( "[ARBITER] standing arbiter submitted to CJ Flow (B1 standing cadence)" )
        return job
    except Exception as e:
        # Degrade-safe: the arbiter is an additive observer; if it can't start,
        # the server + local hook pokes must be unaffected.
        log( f"[ARBITER] standing-cadence submission failed (degrade-safe; hooks unaffected): {e}" )
        return None


def submit_arbiter_if_enabled(
    todo_queue,
    run_queue,
    config_mgr,
    *,
    submit_fn : Callable = submit_arbiter_if_absent,
    log       : Callable = print,
) -> Optional[ Any ]:
    """
    R0 gate (deploy-arch R0 / `2026.06.07-arbiter-r0-inprocess-decommission-spec.md`):
    submit the IN-PROCESS standing arbiter only when the INI flag
    `arbiter in-process bootstrap enabled` is True.

    Never-two across BOTH mechanisms: this is the in-process mechanism. The
    standalone :8001 service runs Loop B via its own single LoopBRunner thread (the
    :8001-side single-instance). This flag gates the in-process side OFF so only ONE
    path ever actuates; `arbiter_already_present` (inside submit_fn) remains the belt
    against a double in-process submission. Cutover is break-before-make (flag False
    → bounce → enable :8001) — a brief zero-arbiter window is acceptable, never two.

    Requires:
        - todo_queue / run_queue are the CJ Flow queues
        - config_mgr exposes .get( key, default, return_type )
        - submit_fn( todo, run, cfg, log=... ) -> job|None (injected for testing)

    Ensures:
        - reads the flag ONCE (read-once contract — no mid-run re-read)
        - flag True (or absent → default True) → returns submit_fn(...)
        - flag False → skips submission, logs a greppable DISABLED line, returns None
        - a MALFORMED (present-but-not-clean-bool) value → coerced to False
          (in-process OFF — never-two-safe in both regimes) with a LOUD WARNING
          (a typo must not silently change fleet vigilance), then returns None
        - mirrors ConfigurationManager's boolean coercion (str(value).lower() == "true")
    """
    raw        = str( config_mgr.get( "arbiter in-process bootstrap enabled", default="true", return_type="string" ) )
    normalized = raw.strip().lower()
    enabled    = normalized == "true"
    if normalized not in ( "true", "false" ):
        log( f"[ARBITER] WARNING: 'arbiter in-process bootstrap enabled'={raw!r} is not a clean "
             f"bool -> coerced to False (in-process arbiter DISABLED) — a typo must not silently "
             f"disable fleet vigilance; set it explicitly to true or false" )
    if not enabled:
        log( "[ARBITER] in-process bootstrap DISABLED by config — standalone :8001 owns the loop" )
        return None
    return submit_fn( todo_queue, run_queue, config_mgr, log=log )


def quick_smoke_test():
    """Self-contained smoke test with fake queues. Returns True or raises."""
    class _Job:
        JOB_TYPE = "heartbeat_arbiter"
    class _Q:
        def __init__( self, jobs=None ):
            self.queue_list = list( jobs or [ ] )
        def push( self, job ):
            self.queue_list.append( job )

    # absent → submits
    todo, run = _Q(), _Q()
    logs = [ ]
    job = submit_arbiter_if_absent( todo, run, object(),
                                    job_builder=lambda cfg: _Job(), log=logs.append )
    assert job is not None and len( todo.queue_list ) == 1

    # present → no-op (guard)
    job2 = submit_arbiter_if_absent( todo, run, object(),
                                     job_builder=lambda cfg: _Job(), log=logs.append )
    assert job2 is None and len( todo.queue_list ) == 1

    # builder raises → swallowed (degrade-safe)
    def _boom( cfg ):
        raise RuntimeError( "no config" )
    fresh = _Q()
    assert submit_arbiter_if_absent( fresh, _Q(), object(), job_builder=_boom, log=logs.append ) is None
    assert len( fresh.queue_list ) == 0
    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"arbiter_bootstrap smoke: {'PASS' if ok else 'FAIL'}" )
