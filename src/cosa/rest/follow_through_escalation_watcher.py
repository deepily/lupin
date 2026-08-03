"""
Follow-through accountability — the aged-escalation watcher (design §4.3 + §4.5).

The dead-manager BACKSTOP for the manager<->worker mutual-wait deadlock. The
unified task-store already carries the whole mechanism (REUSE, do not
re-architect — build plan §2):

  * "awaiting:manager" STALL    -> status="blocked" + blocked_by=[{kind:"persona",
                                    id:<accountable_manager>}] (the ->blocked
                                    transition already REQUIRES both)
  * "who must verify"           -> the first-class `accountable_manager` field
  * "awaited_since_ts"          -> the latest `*->blocked` event's ts (R3 audit log)
  * the repeating chase nudge   -> TaskChaseConsumer (the sibling daemon; re-arms
                                    next_chase_ts every pass)

This watcher is the ONE-SHOT complement to that repeating chase: when an
awaiting:manager item has aged past `T_escalate = live_arbiter_tick x multiplier`
(the manager-tick has effectively DIED — a normal manager acks within a tick or
two), it fires EXACTLY ONE escalation poke at the accountable manager and marks
the item escalated so the alarm never repeats. The interval is NEVER hardcoded —
it derives from the live `arbiter poll seconds` x the `follow through escalation
tick multiplier` INI key (build plan §3a).

**§4.5 escalation hygiene (the careful part)** — idempotent + self-clearing:

  * one-shot:        an aged item escalates at most ONCE per wait (the in-memory
                     `_escalated` set; mirrors the arbiter's `_manager_down_escalated`
                     escalate-once idiom — per-daemon-lifetime, resets on restart).
  * manager-ack clear: when the manager acts, the item leaves `blocked` and so
                     drops out of the awaiting:manager candidate set -> its marker
                     clears (the `_escalated &= live` intersect each pass).
  * worker-hold clear: a validly-parked worker (a fresh, reasoned `.heartbeat-hold-*.json`)
                     is a DOCUMENTED wait, NOT a silent stall — the watcher reads
                     the hold BEFORE declaring "blocking" and suppresses + clears.
                     *Founding evidence: the arbiter over-fired "blocking Maria" 2-3x
                     while Maria was validly parked — this guard is the fix.*

**Disabled by default.** Gated on the INI flag `follow through escalation enabled`
(default False, [Lupin: Baseline]) — defense-in-depth rollout gate, sibling to
TaskChaseConsumer's posture. With the flag off, `sweep_once` is a no-op and
`start` refuses to spawn the daemon. Wiring `start()` (or `sweep_once()` onto the
arbiter poll) is the deliberate activation step.

Time, DB access, the repo factory, the escalation sink, and the worker-hold
oracle are all injectable so the core is unit-testable with no live server, no
Postgres, no real clock, and no hold files.

Canonical design: planning-is-prompting -> src/rnd/2026.06.16-follow-through-accountability-design.md
Lupin build plan: src/rnd/v0.1.8/2026.06.16-follow-through-accountability-lupin-build.md
"""

import json
import threading
from pathlib import Path
from datetime import datetime, timezone

import cosa.utils.util as du
from cosa.rest.db.database import get_db
from cosa.rest.db.repositories.task_repository import TaskRepository
from lupin_mcp.persona_normalization import canonical_persona_key


ESCALATION_ACTOR = "follow-through-escalation-watcher"   # the system actor naming the escalation source


def is_awaiting_manager( item ) -> bool:
    """
    Is this item in the "awaiting:manager" STALL convention (build plan §2)?

    The convention is a NAMED reading over the existing store shape — no new
    field: a blocked item whose accountable_manager is set AND whose blocked_by
    carries a persona-ref pointing at that very manager.

    Requires:
        - item exposes .status, .accountable_manager, .blocked_by

    Ensures:
        - returns True iff status == "blocked" AND accountable_manager is truthy
          AND blocked_by contains a {kind:"persona", id:<accountable_manager>} ref
        - returns False for any other shape (never raises on a missing/odd ref)

    Returns:
        bool
    """
    if item.status != "blocked":
        return False
    manager = item.accountable_manager
    if not manager:
        return False
    for ref in ( item.blocked_by or [ ] ):
        if isinstance( ref, dict ) and ref.get( "kind" ) == "persona" and ref.get( "id" ) == manager:
            return True
    return False


class FollowThroughEscalationWatcher:
    """
    One-shot aged-escalation backstop for awaiting:manager items. Inert unless
    `follow through escalation enabled` is True.
    """

    def __init__(
        self,
        config_mgr,
        get_db_fn     = get_db,
        repo_factory  = TaskRepository,
        escalate_fn   = None,
        hold_check_fn = None,
        now_fn        = None,
        hold_base_dir = None,
    ):
        """
        Initialize the escalation watcher.

        Requires:
            - config_mgr exposes .get( key, default=, return_type= )
            - get_db_fn is a context-manager factory yielding a DB session
            - repo_factory( session ) -> a TaskRepository-like object exposing
              query_tasks / get_events
            - escalate_fn( item, manager, worker, awaited_since ) -> None fires the
              ONE manager poke (default: a structured banner log); injected so
              production supplies the real arbiter/dm poke and tests assert it fired
            - hold_check_fn( persona ) -> bool answers "does this persona hold a
              valid (fresh, reasoned) park right now?" (default: glob
              .heartbeat-hold-*.json); injected for §4.5 worker-hold hygiene
            - now_fn() -> tz-aware datetime (default: datetime.now(utc)); injected
              so tests pin the clock
            - hold_base_dir is the directory holding .heartbeat-hold-*.json (default:
              the project root); injected so the default hold-check is testable

        Ensures:
            - no thread is started at construction (call start() explicitly)
            - the one-shot `_escalated` marker set starts empty
        """
        self._config_mgr    = config_mgr
        self._get_db_fn     = get_db_fn
        self._repo_factory  = repo_factory
        self._escalate_fn   = escalate_fn   if escalate_fn   is not None else self._default_escalation_signal
        self._hold_check_fn = hold_check_fn if hold_check_fn is not None else self._default_hold_check
        self._now_fn        = now_fn        if now_fn        is not None else ( lambda: datetime.now( timezone.utc ) )
        self._hold_base_dir = hold_base_dir
        self._escalated     = set()                    # item-ids escalated once (one-shot; per-daemon-lifetime)
        self._stop_event    = threading.Event()
        self._thread        = None

    # -- config accessors -----------------------------------------------------

    def _enabled( self ) -> bool:
        return self._config_mgr.get( "follow through escalation enabled", default=False, return_type="boolean" )

    def _multiplier( self ) -> int:
        return self._config_mgr.get( "follow through escalation tick multiplier", default=2, return_type="int" )

    def _tick_seconds( self ) -> int:
        # the LIVE arbiter tick — the same key the :8001 fleet-arbiter loop polls on.
        return self._config_mgr.get( "arbiter poll seconds", default=60, return_type="int" )

    def _t_escalate( self ) -> int:
        # NEVER a literal interval — live tick x the rider multiplier (build plan §3a).
        return self._tick_seconds() * self._multiplier()

    # -- core (unit-testable, no thread) --------------------------------------

    def sweep_once( self ) -> dict:
        """
        Run one escalation pass over the awaiting:manager candidates.

        Ensures:
            - flag OFF -> no DB access at all; returns {enabled:False, escalated:0,
              candidates:0}
            - flag ON  -> for each blocked item in the awaiting:manager convention:
                * a validly-parked worker (hold_check_fn True) is SKIPPED (§4.5(b) —
                  documented wait, not a silent stall)
                * an item aged past T_escalate that has NOT already escalated fires
                  ONE escalate_fn(...) and is marked escalated (one-shot)
                * an already-escalated aged item fires nothing (never re-fire)
            - after the pass, `_escalated` is intersected with the live candidate
              set so markers clear on manager-ack (item left blocked) OR worker-hold
              (skipped above) — one-shot-THEN-cleared (§4.5(a)/(b))
            - one get_db() transaction (read-only) wraps the whole pass

        Returns:
            dict summary { "enabled": bool, "escalated": int, "candidates": int }
        """
        if not self._enabled():
            return { "enabled": False, "escalated": 0, "candidates": 0 }

        now        = self._now_fn()
        t_escalate = self._t_escalate()
        escalated  = 0
        candidates = 0
        live       = set()                             # awaiting:manager ids that are NOT validly-parked this pass
        with self._get_db_fn() as session:
            repo = self._repo_factory( session )
            for item in repo.query_tasks( status="blocked", limit=500 ):
                if not is_awaiting_manager( item ):
                    continue
                candidates += 1
                worker  = item.owner_persona
                manager = item.accountable_manager
                # §4.5(b): a validly-parked worker is a DOCUMENTED wait — read the
                # hold BEFORE declaring "blocking"; suppress + let the marker clear.
                if self._hold_check_fn( worker ):
                    continue
                live.add( item.id )
                awaited_since = self._awaited_since( repo, item )
                if awaited_since is None:
                    continue                           # no ->blocked event to age against (defensive)
                if ( now - awaited_since ).total_seconds() <= t_escalate:
                    continue                           # not yet aged
                if item.id in self._escalated:
                    continue                           # one-shot — already fired this wait
                self._escalate_fn( item, manager, worker, awaited_since )
                self._escalated.add( item.id )
                escalated += 1

        # §4.5(a) manager-ack clear + (b) hold clear: an id no longer a live
        # awaiting:manager candidate (acked -> left blocked -> absent; parked ->
        # skipped -> absent) drops its one-shot marker.
        self._escalated &= live
        return { "enabled": True, "escalated": escalated, "candidates": candidates }

    def _awaited_since( self, repo, item ):
        """
        Derive awaited_since_ts: the ts of the LATEST `*->blocked` transition event
        (build plan §2 — derived from the R3 audit log, not a new column).

        Requires:
            - repo exposes get_events( item_id ) -> events ordered by id ascending
            - item exposes .id

        Ensures:
            - returns the most-recent ->blocked event's ts (tz-aware; a naive ts is
              coerced to UTC defensively), or None when there is no ->blocked event
              (or its ts is missing)
            - never mutates

        Returns:
            tz-aware datetime or None
        """
        blocked_events = [ e for e in repo.get_events( item.id ) if str( e.transition ).endswith( "->blocked" ) ]
        if not blocked_events:
            return None
        ts = blocked_events[ -1 ].ts                   # id-asc order -> last is the most recent block
        if ts is None:
            return None
        if ts.tzinfo is None:
            ts = ts.replace( tzinfo=timezone.utc )
        return ts

    def _default_escalation_signal( self, item, manager, worker, awaited_since ) -> None:
        """Default escalation sink: a structured banner naming the aged stall + who owes the verification."""
        du.print_banner(
            f"[follow-through] aged awaiting:manager item {item.id} worker={worker} "
            f"manager={manager} awaited_since={awaited_since.isoformat()} "
            f"title={item.title!r} — escalating ONCE to {manager}",
            prepend_nl=True,
        )

    def _default_hold_check( self, persona ) -> bool:
        """
        Default §4.5 worker-hold oracle: is `persona` validly parked right now?

        Globs `.heartbeat-hold-*.json` in the hold base dir and returns True iff
        one belongs to `persona` (normalized match) and is HONORED (fresh +
        reasoned, per heartbeat_hold.is_honored). A documented park is not a
        silent stall.

        Requires:
            - persona is a string (the store owner_persona) or None

        Ensures:
            - empty/None persona -> False (nothing to match)
            - True iff some honored hold file's persona normalizes to `persona`
            - unreadable / malformed / non-object / `.tmp` hold files are skipped
            - never raises

        Returns:
            bool
        """
        # Identity parity (Phase 2): retired the private _norm_persona (which
        # DROPPED spaces -> "mrradio") for the one canonical_persona_key root
        # (keep-spaces -> "mr radio"), so the hold-file persona matches the store
        # owner_persona by the SAME key. Both compare sides moved in lockstep.
        target = canonical_persona_key( persona )
        if not target:
            return False

        from lupin_cli.claude_code.hooks.lib import heartbeat_hold as hh
        base = self._hold_base_dir
        if base is None:
            import cosa.utils.util as cu
            base = cu.get_project_root()

        now     = self._now_fn()
        # the `*.json` pattern already excludes atomic-write `.json.tmp` artifacts.
        pattern = hh.HOLD_FILENAME_TEMPLATE.format( session_id="*" )
        for path in Path( base ).glob( pattern ):
            try:
                hold = json.loads( path.read_text() )
            except ( OSError, ValueError ):
                continue
            if not isinstance( hold, dict ):
                continue
            if canonical_persona_key( hold.get( "persona" ) ) != target:
                continue
            if hh.is_honored( hold, now=now ):
                return True
        return False

    # -- daemon lifecycle -----------------------------------------------------

    def _loop( self ) -> None:
        """
        Daemon loop until stop(); Event.wait(timeout) so shutdown interrupts the
        nap immediately. Each sweep is exception-guarded so a transient DB error
        never kills the daemon. Naps the LIVE arbiter tick (sweeps every tick).
        """
        while not self._stop_event.is_set():
            try:
                self.sweep_once()
            except Exception as e:
                du.print_banner( f"Follow-through escalation watcher loop caught exception (continuing): {e!r}", prepend_nl=True )
            self._stop_event.wait( timeout=self._tick_seconds() )

    def start( self ) -> bool:
        """
        Spawn the daemon thread — ONLY if the flag is enabled and no thread is
        already running. Returns True if a thread was started, else False (the
        no-op rollout gate: a disabled watcher never spawns).
        """
        if not self._enabled():
            return False
        if self._thread is not None and self._thread.is_alive():
            return False
        self._stop_event.clear()
        self._thread = threading.Thread( target=self._loop, daemon=True, name="FollowThroughEscalationWatcher" )
        self._thread.start()
        return True

    def stop( self, timeout: float = 5.0 ) -> None:
        """Signal the daemon to exit and join it (idempotent — safe if never started)."""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join( timeout=timeout )
