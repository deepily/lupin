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
import os
import threading
from typing import Any, Callable, Optional

from lupin_arbiter_app.health_watcher import SystemClock
from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob, _default_owed_work_fn, _default_known_owners_fn, _default_dm_activity_fn, _default_operator_gates_fn
from cosa.agents.heartbeat_arbiter.operator_gate_routing import DEFAULT_DIGEST_CADENCE_SECONDS
# 6929f4ac outward-twin backstop (§9.2): the per-session hold reader — defaulted
# real here so the :8001 service actually resurfaces a dark session's aged user-gate
# to Rick (without this wiring the seam stays None → the backstop is decorative).
from lupin_cli.claude_code.hooks.lib.heartbeat_hold import read_hold as _default_hold_reader
# REPORT-ONLY janitor (2026-07-16). NOT prune_stale_hold_files: hold files carry
# hand-written memento cargo (note_to_my_successor / the_lesson_that_should_outlive_
# this_session / board), and a measured 10 of them are ALREADY reapable by the
# existing rule the moment the sweep widens. Deletion stays disabled until the cargo
# has been triaged OUT — so the supervisor is wired to a function that structurally
# CANNOT delete, rather than to a destructive one behind a flag.
from lupin_cli.claude_code.hooks.lib.heartbeat_hold import report_hold_files as _default_hold_reporter
from lupin_cli.claude_code.hooks.lib.session_bridge import find_active_voice_persona_sessions as _find_active_voice_persona_sessions
from lupin_cli.claude_code.hooks.lib.session_bridge import find_active_sessions as _find_active_sessions
from lupin_mcp.persona_normalization import canonical_persona_key
from cosa.agents.heartbeat_arbiter.arbiter_journal import make_log_fn


ESCALATION_TOPIC = "fleet-escalations"


def _default_manager_bridge_mtimes():   # pragma: no cover - production bridge-scan IO boundary
    """
    bug 26dd3afb: scan the LIVE persona'd bridge files → { canonical_persona_key :
    freshest bridge-file mtime (epoch) } — the real reader wired into the MANAGER-
    STALE bridge-mtime veto on the :8001 deploy.

    Keyed by PERSONA (not session_id) so a re-spun twin's fresh bridge (a NEW
    session_id) still vetoes the superseded row's stale poke — the always-present
    analog of the sid-keyed union signal. Reuses find_active_voice_persona_sessions
    (PID-alive + persona-required projection) rather than hand-globbing. Exercised
    at the :8001 integration tier like the other _default_* IO boundaries; unit
    tests inject a fake, so this boundary is no-cover.

    Ensures:
        - returns { canonical_persona_key : max bridge mtime } across live persona'd
          bridges; a persona with several live sessions keeps the FRESHEST mtime
        - skips bridges with no persona name / unreadable mtime; never raises here
          (the arbiter's swallow-safe _read_manager_bridge_mtimes wraps it anyway)
    """
    result = { }
    for path, _sid, persona in _find_active_voice_persona_sessions():
        name = ( persona or { } ).get( "name" )
        if not name:
            continue
        key = canonical_persona_key( name )
        if not key:
            continue
        try:
            mtime = os.path.getmtime( path )
        except OSError:
            continue
        if key not in result or mtime > result[ key ]:
            result[ key ] = mtime
    return result


def _default_hold_roots():   # pragma: no cover - production project-root IO boundary
    """
    The root list the hold sweep is pointed at — the session's OWN project root.

    ⚠️ THIS IS NOT THE FLEET'S ROOT LIST, and it must not be mistaken for one.
    Where the janitor learns the fleet's roots is an OPEN, UNRULED design question,
    so this module REFUSES to invent an answer: the roots arrive as an injected
    seam, and this default only makes today's implicit reach EXPLICIT (the janitor
    was called with no base_dir → LUPIN_ROOT → one directory, non-recursively).

    Two verified traps for whoever rules that question:
      • the `external repo * path` config entries are CONTAINER paths
        (/var/external-projects/…) that DO NOT EXIST on the host — and the arbiter
        runs on the HOST. A config-derived root list resolves to nothing, reaching
        ZERO hold files while looking perfectly reasonable.
      • at least one hold-bearing project is not registered anywhere.
    A root list that reaches nothing is now VISIBLE (roots_swept + files_seen are
    emitted every tick, empty or not) rather than silent.

    Ensures:
        - returns [ project root ] — recursive within it, so the strays under
          src/migrations/versions/ and src/lupin-mobile/ are reached
    """
    import cosa.utils.util as cu
    return [ cu.get_project_root() ]


def _default_live_session_ids():   # pragma: no cover - production bridge-scan IO boundary
    """
    The AUTHORITATIVE live-session set for the hold sweep — the belt-and-suspenders
    that stops a live session's hold from ever being read as positive-dead.

    ⚠️ `find_active_voice_persona_sessions` is imported one line up, it is the
    obvious choice, and it is the WRONG one. It delegates to
    find_active_sessions( require_persona=True ) — persona'd sessions ONLY. A LIVE
    but persona-LESS session (one that booted when the persona pool was exhausted,
    or whose allocation raced/failed — bug d57dbfea's black hole) would be ABSENT
    from that set, read as POSITIVE-DEAD, and have its hold reaped at TTL with NO
    grace. That is the forbidden relaxation of bias-to-keep, and it names its
    victim: a pool-exhausted worker's live hold.

    require_persona=False is the honest liveness set — d57dbfea's own lesson,
    applied one layer over.

    Ensures:
        - returns the set of live session ids INCLUDING persona-less sessions
        - degrade-safe: any scan failure yields None (NO authoritative set) rather
          than a PARTIAL one — a half-enumerated live-set is worse than none, since
          absence from it is what licenses the no-grace prune
    """
    try:
        return { sid for _path, sid, _persona in _find_active_sessions( require_persona=False ) }
    except Exception:
        return None


# Item A (2026.06.11 receipts design §2.3): the line shape has ONE owner —
# arbiter_journal.make_log_fn (ts + ts_local).
_default_log_fn = make_log_fn( loop="fleet_arbiter" )


# ── escalation output sink (ruling A) ───────────────────────────────────────

def make_escalation_notify_fn(
    gateway       : Any,
    *,
    live_notify_fn : Optional[ Callable[ [ str ], dict ] ] = None,
    log_fn         : Optional[ Callable ]                  = None,
    topic          : str                                   = ESCALATION_TOPIC,
) -> Callable[ [ str ], list ]:
    """
    Build the escalation-OUTPUT notify_fn: durable-primary + best-effort live —
    OUTCOME-RETURNING since the 2026.06.11 receipts design (§3.2: pre-design
    this swallowed every failure into a lone log line one journal entry before
    `arbiter_outreach` claimed Rick was reached — root-cause R3/R4).

    Ensures:
        - ALWAYS posts `message` to the durable commons `topic` via the bridge-less
          gateway; returns [{channel:"durable", outcome:"posted"}] on success,
          outcome "post_error" (+ detail) on failure — still logged, still
          non-fatal (the PRIMARY channel must not kill the loop — note 3)
        - if live_notify_fn is provided, appends its live-channel outcome dict
          (a blow-up degrades to outcome "http_error" — logged, never raised);
          if ABSENT, appends {channel:"live", outcome:"disabled"} — a disabled
          live hop is a VISIBLE per-outreach fact, not a silent gap (§3.6)
        - never raises; the caller journals one arbiter_outreach_result per
          returned outcome under the outreach_id
    """
    log_fn = log_fn if log_fn is not None else _default_log_fn

    def notify_fn( message: str ) -> list:
        results = [ ]
        try:
            gateway.post( topic, message )
            results.append( { "channel": "durable", "outcome": "posted" } )
        except Exception as e:                       # durable post degrade-safe (note 3)
            log_fn( "escalation_post_error", error=str( e ) )
            results.append( { "channel": "durable", "outcome": "post_error",
                              "detail": str( e )[ :160 ] } )
        if live_notify_fn is not None:
            try:
                results.append( live_notify_fn( message ) )
            except Exception as e:                   # best-effort live delivery, degraded to an outcome
                log_fn( "escalation_live_notify_error", error=str( e ) )
                results.append( { "channel": "live", "outcome": "http_error",
                                  "detail": str( e )[ :160 ] } )
        else:
            results.append( { "channel": "live", "outcome": "disabled" } )
        return results

    return notify_fn


# ── warm-up suppressor (ruling B) ───────────────────────────────────────────

def make_warmup_notify_fn(
    inner                : Callable[ [ str ], list ],
    job_started_at       : datetime.datetime,
    start_period_seconds : int,
    clock                : Any,
    log_fn               : Callable,
) -> Callable[ [ str ], list ]:
    """
    Wrap an escalation notify_fn to SUPPRESS escalations during the warm-up window
    of a single job (keyed on that job's start time) — outcome-returning (§3.2).

    Ensures:
        - while (clock.now() − job_started_at) < start_period_seconds → suppress
          (log `escalation_suppressed_warmup`, do NOT call inner) and return
          [{channel:"all", outcome:"suppressed_warmup"}] — pre-design this
          returned None and the caller journaled "rick" as reached anyway (the
          §1.3 L3 leg of the journal-lies bug)
        - at/after the window → pass through to inner and return its outcomes
        - never raises
    """
    def notify_fn( message: str ) -> list:
        if ( clock.now() - job_started_at ).total_seconds() < start_period_seconds:
            log_fn( "escalation_suppressed_warmup", message=message )
            return [ { "channel": "all", "outcome": "suppressed_warmup" } ]
        return inner( message )

    return notify_fn


# ── eng#7 follow-through watcher factory (build-plan §3b) ───────────────────

def make_follow_through_watcher_factory(
    config_mgr,
    gateway,
    *,
    log_fn : Optional[ Callable ] = None,
) -> Callable[ [ Any ], Any ]:
    """
    Build the eng#7 follow-through-watcher FACTORY: a `(job) -> FollowThroughEscalationWatcher`
    callable the ArbiterConsumerJob invokes ONCE at construction.

    The factory (not a bare instance) is what resolves the chicken-egg in the job
    ctor: the watcher's §4.5 hold_check_fn IS `job.session_is_not_owed` — the
    arbiter's already-built store-owed suppression predicate (Clayton's lane-4
    primitive). REUSING it means #7 never duplicates the store-read + classification
    and never contends on the poke path. The escalate_fn fires ONE directed poke at
    the accountable manager via the bridge-less gateway when an awaiting:manager item
    has aged past T_escalate.

    Gating lives in the watcher: `follow through escalation enabled` (default False)
    makes sweep_once() a no-op, so wiring this factory in changes ZERO runtime
    behavior until a deliberate post-soak flip.

    Requires:
        - config_mgr exposes .get( key, default=, return_type= ) (the watcher reads
          the enable flag, tick multiplier, and live `arbiter poll seconds`)
        - gateway exposes send_to( recipient, body ) (the directed manager poke)

    Ensures:
        - returns factory( job ) -> a FollowThroughEscalationWatcher wired with
          config_mgr, the directed-manager-poke escalate_fn, and
          hold_check_fn = job.session_is_not_owed
        - the escalate_fn is degrade-safe: a gateway.send_to blow-up is logged
          (follow_through_escalation_error), never raised — escalation must never
          kill a poll (observer invariant)
        - construction is pure in-memory (no DB / clock / hold-file IO until the
          flag is flipped AND sweep_once runs); fully testable with a fake gateway
          + fake cfg + a stub job exposing session_is_not_owed
    """
    log_fn = log_fn if log_fn is not None else _default_log_fn

    def _escalate_fn( item, manager, worker, awaited_since ):
        body = ( f"FOLLOW-THROUGH ESCALATION — you ({manager}) owe verification on an aged "
                 f"awaiting-manager item: '{item.title}' (worker {worker}, awaiting since "
                 f"{awaited_since.isoformat()}). Ack it or verify the work." )
        try:
            gateway.send_to( manager, body )
            log_fn( "follow_through_escalation", item=str( item.id ), manager=manager,
                    worker=worker, awaited_since=awaited_since.isoformat() )
        except Exception as e:                       # escalation degrade-safe (observer invariant)
            log_fn( "follow_through_escalation_error", item=str( item.id ), error=str( e ) )

    def factory( job ) -> Any:
        from cosa.rest.follow_through_escalation_watcher import FollowThroughEscalationWatcher
        return FollowThroughEscalationWatcher(
            config_mgr,
            escalate_fn   = _escalate_fn,
            hold_check_fn = job.session_is_not_owed,   # §4.5: reuse the store-owed predicate
        )

    return factory


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
    stuck_poke_min_interval_seconds : int       = 0,            # bug 5a1f17f8 (c) fire-throttle (0 → disabled)
    manager_stale_poke_threshold : int          = 2700,
    manager_stale_poke_max_age : int            = 7200,
    # role-goals Phase 2-3: role-selected north-star goal echoes appended to the
    # stuck-poke + manager-staleness poke bodies. "" → inert (poke body unchanged).
    manager_goal_line    : str                  = "",
    worker_goal_line     : str                  = "",
    start_period_seconds : int                  = 120,
    # Item B (2026.06.11 receipts design): the delivery-receipt seams + knobs,
    # threaded verbatim to the job. None seams keep their tier inert.
    dm_push_fn           : Optional[ Callable ] = None,
    tmux_push_fn         : Optional[ Callable ] = None,   # Thread C+D host-side tmux wake hop
    poke_wake_mechanism  : str                  = "tmux", # Thread C+D wake-surface selector (default tmux)
    live_retry_fn        : Optional[ Callable ] = None,
    outreach_ack_window  : int                  = 900,
    reannounce_interval  : int                  = 300,
    reannounce_ttl       : int                  = 86400,
    pending_ledger_path  : Optional[ str ]      = None,
    # F-A (2026.06.11 lineage-persistence design): the restart-surviving carry file.
    lineage_carry_path   : Optional[ str ]      = None,
    offsets_state_path   : Optional[ str ]      = None,          # bug 5a1f17f8 (b): durable event-offset store; None → in-memory (replay on restart)
    # L1 (2026-06-17 arbiter detector gaps): the per-poll owed-work store reader
    # (arbiter = reader #2). Defaults to the real DB reader so the :8001 service
    # activates the store-aware suppression of the false-escalating detectors;
    # injectable for tests (construction is pure — the reader is never CALLED here).
    owed_work_fn         : Optional[ Callable ] = None,
    # 262c59f6 (A): the fleet-wide known-owner-persona reader (distinct owner_persona
    # over all store rows). Defaults to the real DB reader so the :8001 service arms
    # the known-persona fail-safe (a re-spin/label-contamination would-be-DONE persona
    # ∉ known owners → UNKNOWN, never a false MANAGER-DONE); injectable for tests.
    known_owners_fn      : Optional[ Callable ] = None,
    # 6929f4ac (outward-twin backstop): the per-session hold reader + the aged-gate
    # resurface ceiling. hold_reader_fn defaults to the real read_hold so the :8001
    # service resurfaces a DARK session's open, aged user-gate to Rick (None →
    # decorative); injectable for tests (never CALLED at construction).
    hold_reader_fn       : Optional[ Callable ] = None,
    user_gate_resurface_seconds : int           = 1800,
    # A2/A3 (fcb5dbc0): the fleet-wide open-operator-gate store reader + the NORMAL-
    # urgency digest cadence. operator_gates_fn defaults to the real DB reader so the
    # :8001 service activates the operator-gate urgency routing (urgent interrupt /
    # normal digest / low pull-only); injectable for tests (never CALLED here).
    operator_gates_fn    : Optional[ Callable ] = None,
    operator_digest_cadence_seconds : int       = DEFAULT_DIGEST_CADENCE_SECONDS,
    # DM-as-liveness toggle (2026-06-17): (1) the per-poll runtime-flag re-read
    # (None → the job defaults to `lambda: True`; app.py wires a per-poll
    # mtime-gated INI read so the flag is runtime-tunable with no bounce). (2) the
    # SENT-DM store reader — defaults to the real DB reader so the :8001 service
    # activates the 5th signal; injectable for tests (never CALLED at construction).
    count_dm_as_liveness_fn : Optional[ Callable ] = None,
    dm_activity_fn          : Optional[ Callable ] = None,
    # bug 26dd3afb: the MANAGER-STALE bridge-mtime veto reader. Defaulted REAL here
    # (like hold_reader_fn) so the veto is LIVE on the :8001 deploy — without this
    # wiring the seam stays None → the veto is decorative and Tiberius-class false
    # positives recur. A fake overrides it for tests.
    bridge_mtimes_fn        : Optional[ Callable ] = None,
    # eng#7 (2026-06-17): the follow-through aged-escalation watcher factory
    # ((job) -> watcher). None keeps it INERT (no watcher wired); app.py builds the
    # real one (make_follow_through_watcher_factory) so the :8001 job rides it. Even
    # wired, the `follow through escalation enabled`=False flag keeps sweep_once a
    # no-op until a deliberate flip — zero runtime behavior change on wiring-in.
    follow_through_watcher_factory : Optional[ Callable ] = None,
    # ee59d5ed orphan-bridge janitor: default-OFF because it CHANGES fleet-wide reap
    # semantics (every reaped session now durably drops off the operator focus bar).
    # Off → the sweep seam is never wired (None → INERT), zero runtime change on
    # merge; Rick flips `arbiter orphan bridge sweep enabled`=True to activate.
    orphan_bridge_sweep_enabled       : bool = False,
    orphan_bridge_sweep_debounce_polls : int = 2,   # N consecutive dead polls before a reap (safety debounce)
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
    # L1: wire the real DB owed-work reader by default so the :8001 service gets
    # store-aware detector suppression; an injected fake overrides it for tests.
    owed_work_fn = owed_work_fn if owed_work_fn is not None else _default_owed_work_fn
    # 262c59f6 (A): wire the real known-owner reader by default so the :8001 service
    # arms the known-persona fail-safe against re-spin/label-contamination false
    # MANAGER-DONE; an injected fake overrides it for tests.
    known_owners_fn = known_owners_fn if known_owners_fn is not None else _default_known_owners_fn
    # DM-as-liveness: wire the real SENT-DM reader by default so the :8001 service
    # activates the 5th signal; an injected fake overrides it for tests. The
    # runtime-flag re-read is wired by app.py (cfg-closed lambda); None here lets
    # the job default to `lambda: True` (feature ON, the INI default).
    dm_activity_fn = dm_activity_fn if dm_activity_fn is not None else _default_dm_activity_fn
    # 6929f4ac: wire the real hold reader by default so the :8001 service activates
    # the outward-twin backstop (open-gate→ACTIVE classify override + dark-session
    # gate resurface); an injected fake overrides it for tests.
    hold_reader_fn = hold_reader_fn if hold_reader_fn is not None else _default_hold_reader
    # A2/A3 (fcb5dbc0): wire the real fleet-wide operator-gate reader by default so the
    # :8001 service activates the operator-gate urgency routing; a fake overrides it.
    operator_gates_fn = operator_gates_fn if operator_gates_fn is not None else _default_operator_gates_fn
    # bug 26dd3afb: wire the real persona→bridge-mtime reader by default so the :8001
    # service arms the MANAGER-STALE bridge-mtime veto; an injected fake overrides it.
    bridge_mtimes_fn = bridge_mtimes_fn if bridge_mtimes_fn is not None else _default_manager_bridge_mtimes
    escalation_notify = make_escalation_notify_fn( gateway, live_notify_fn=live_notify_fn, log_fn=log_fn )

    def factory() -> ArbiterConsumerJob:
        job_start     = clock.now()
        warmup_notify = make_warmup_notify_fn( escalation_notify, job_start, start_period_seconds, clock, log_fn )
        # ee59d5ed orphan-bridge sweep seam. The debounce-state dict is created ONCE
        # per job here and captured by the closure, so the {session_id: consecutive-
        # dead-polls} counter PERSISTS across this job's polls (a recycle resets it —
        # the accepted trade for all arbiter cross-poll state). None when the flag is
        # off → the poll-loop seam stays inert.
        bridge_sweep_fn = None
        if orphan_bridge_sweep_enabled:
            from cosa.agents.shared.orphan_bridge_reaper import reconcile_orphan_bridges
            bridge_dead_polls: dict = { }
            bridge_sweep_fn = lambda: reconcile_orphan_bridges(
                bridge_dead_polls, debounce_threshold=orphan_bridge_sweep_debounce_polls
            )
        return ArbiterConsumerJob(
            commons                    = gateway,
            bridge_sweep_fn            = bridge_sweep_fn,                           # ee59d5ed orphan-bridge janitor (default-off flag)
            owed_work_fn               = owed_work_fn,                              # L1 store-aware seam
            known_owners_fn            = known_owners_fn,                           # 262c59f6 (A) known-persona fail-safe seam
            hold_reader_fn             = hold_reader_fn,                            # 6929f4ac outward-twin backstop
            user_gate_resurface_seconds = user_gate_resurface_seconds,             # 6929f4ac aged-gate ceiling
            operator_gates_fn          = operator_gates_fn,                         # A2/A3 operator-gate store reader
            operator_digest_cadence_seconds = operator_digest_cadence_seconds,      # A2/A3 normal-digest cadence
            count_dm_as_liveness_fn    = count_dm_as_liveness_fn,                   # DM-toggle runtime flag (app.py wires cfg read)
            dm_activity_fn             = dm_activity_fn,                            # DM-toggle SENT-DM store reader
            bridge_mtimes_fn           = bridge_mtimes_fn,                          # bug 26dd3afb MANAGER-STALE bridge-mtime veto reader
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
            stuck_poke_min_interval_seconds = stuck_poke_min_interval_seconds,      # bug 5a1f17f8 (c) fire-throttle
            manager_stale_poke_threshold_seconds = manager_stale_poke_threshold,   # post-game F2
            manager_stale_poke_max_age_seconds   = manager_stale_poke_max_age,     # corpse ceiling
            manager_goal_line          = manager_goal_line,                        # role-goals Phase 2-3
            worker_goal_line           = worker_goal_line,                         # role-goals Phase 2-3
            dm_push_fn                  = dm_push_fn,                              # Item B §3.3
            tmux_push_fn                = tmux_push_fn,                            # Thread C+D host-side tmux wake
            poke_wake_mechanism         = poke_wake_mechanism,                     # Thread C+D wake selector
            lineage_carry_path          = lineage_carry_path,                      # F-A lineage carry
            offsets_state_path          = offsets_state_path,                       # bug 5a1f17f8 (b) durable event offsets
            live_retry_fn               = live_retry_fn,                           # Item B §3.5
            outreach_ack_window_seconds = outreach_ack_window,
            reannounce_interval_seconds = reannounce_interval,
            reannounce_ttl_seconds      = reannounce_ttl,
            pending_ledger_path         = pending_ledger_path,
            follow_through_watcher_factory = follow_through_watcher_factory,        # eng#7 §3b
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
        job_factory          : Callable[ [ ], ArbiterConsumerJob ],
        *,
        log_fn               : Optional[ Callable ] = None,
        hold_janitor_fn      : Optional[ Callable ] = None,
        hold_roots_fn        : Optional[ Callable ] = None,
        live_session_ids_fn  : Optional[ Callable ] = None,
    ) -> None:
        self._job_factory    = job_factory
        self._log_fn         = log_fn if log_fn is not None else _default_log_fn
        # b39562e4 pt2 → 2026-07-16: the hold sweep, REPORT-ONLY. Runs once per
        # supervisor cycle (each arbiter start + ~12h recycle). All three seams are
        # injectable so tests never touch the real project root, and so the two
        # UNRULED questions (which roots? which live-set?) are answered by the
        # caller rather than assumed here.
        self._hold_janitor_fn     = hold_janitor_fn if hold_janitor_fn is not None else _default_hold_reporter
        self._hold_roots_fn       = hold_roots_fn if hold_roots_fn is not None else _default_hold_roots
        self._live_session_ids_fn = live_session_ids_fn if live_session_ids_fn is not None else _default_live_session_ids
        self._stop           = threading.Event()
        self._current_job    = None
        self._thread         = None
        self.cycles          = 0

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
            self._sweep_hold_files()             # b39562e4 pt2: hold janitor — REPORT-ONLY (deletes nothing)
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

    def _sweep_hold_files( self ) -> None:
        """
        REACH and CLASSIFY every `.heartbeat-hold-*` file, and DELETE NOTHING.

        Renamed from `_reap_stale_holds`: it no longer reaps, and a method whose
        name promises deletion while its body reports is exactly the kind of false
        claim that becomes the next reader's ground truth.

        Two defects this method used to embody, both fixed here:

        1. **It passed NOTHING.** `self._hold_janitor_fn()` — no base_dir (⇒
           LUPIN_ROOT ⇒ one directory, non-recursively, blind to every other tree)
           and no live_session_ids (⇒ `authoritative` always False ⇒ the entire
           positive-dead branch of the janitor was UNREACHABLE in production —
           dead code that only ever ran in tests).

        2. **`if pruned:` made failure look like success.** It logged ONLY on a
           non-empty result, so "I swept zero roots and reached nothing" and "I
           swept everything and there was nothing to reap" were both SILENT and
           both indistinguishable from a healthy tick. The sweep report is this
           milestone's acceptance evidence; built on that line, the evidence for a
           total-failure sweep was an empty log. A check that cannot fail is not a
           check. **The emit is now UNCONDITIONAL.**

        Ensures:
            - calls the injected report fn with BOTH the injected roots AND the
              injected live-set; emits `fleet_arbiter_hold_report` EVERY tick with
              roots_swept / files_seen / the classification tallies — empty or not
            - emits `fleet_arbiter_hold_report_no_roots` (distinctly!) when the
              sweep reached ZERO roots — "swept nothing" is the opposite fact from
              "found nothing", and a lone zero cannot tell them apart
            - surfaces skipped-but-hold-bearing dirs + unreachable roots rather
              than silently omitting them
            - deletes nothing; swallows + logs any exception (the janitor must
              never kill the supervisor)
        """
        try:
            roots  = list( self._hold_roots_fn() or [ ] )
            live   = self._live_session_ids_fn()
            report = self._hold_janitor_fn( base_dirs=roots, live_session_ids=live )
            counts = report[ "counts" ]
            if not report[ "roots_swept" ]:
                # LOUD: reached no roots at all. Not the same fact as "nothing to reap".
                self._log_fn( "fleet_arbiter_hold_report_no_roots",
                              roots_requested   = report[ "roots_requested" ],
                              roots_unreachable = report[ "roots_unreachable" ] )
            self._log_fn( "fleet_arbiter_hold_report",
                          roots_swept             = report[ "roots_swept" ],
                          roots_unreachable       = report[ "roots_unreachable" ],
                          files_seen              = report[ "files_found" ],
                          prunable                = counts[ "prunable" ],
                          kept                    = counts[ "keep" ],
                          cargo_bearing           = counts[ "cargo_bearing" ],
                          ttl_unusable            = counts[ "ttl_unusable" ],
                          anchor_disagreement     = counts[ "anchor_disagreement" ],
                          kept_reasons            = counts[ "reachable_but_kept_reasons" ],
                          skipped_dirs_with_holds = report[ "skipped_dirs_with_holds" ],
                          deleted                 = report[ "deleted" ] )
        except Exception as e:                   # janitor must never kill the supervisor
            self._log_fn( "fleet_arbiter_hold_janitor_error", error=str( e ) )

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
