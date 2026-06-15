"""
Task-store chase consumer (Phase 2.1, Item E — the `next_chase_ts` consumer).

Operationalizes design I3 ("blocked items carry next_chase_ts — no 'pending X'
graves; STALL != QUIET"): a daemon that periodically finds blocked items whose
chase time has arrived, emits a chase signal (a nudge to the accountable
manager), re-arms next_chase_ts with a backoff, and stamps a 'chased' audit
event. It NEVER auto-transitions — chasing is a nudge, not a decision.

**Disabled by default.** Gated on the INI flag `task store chase enabled`
(default False, [Lupin: Baseline]). With the flag off, `sweep_once` is a no-op
and `start` refuses to spawn the daemon — so this module is inert in every
environment until explicitly opted in (the rollout gate, mirroring the
task-store mirror flag's posture). Wiring `start()` into server boot is the
deliberate activation step, also behind the flag.

Mirrors the ghost-job-sweeper daemon idiom on RunningFifoQueue (Event.wait
loop so shutdown interrupts the nap immediately). Time, DB access, the repo
factory, and the signal sink are all injectable so the core is unit-testable
with no live server, no Postgres, and no clock.

Canonical design: planning-is-prompting -> src/rnd/2026.06.11-unified-task-store-design.md
(I3 chase semantics); build plan src/rnd/v0.1.8/2026.06.15-task-store-phase2.1/01-build-plan.md (Item E).
"""

import threading
from datetime import datetime, timedelta, timezone

import cosa.utils.util as du
from cosa.rest.db.database import get_db
from cosa.rest.db.repositories.task_repository import TaskRepository


CHASE_ACTOR = "task-chase-consumer"   # the system actor stamped on 'chased' events


class TaskChaseConsumer:
    """
    Daemon that chases overdue blocked items (re-arm + audit + signal), never
    auto-transitioning. Inert unless `task store chase enabled` is True.
    """

    def __init__(
        self,
        config_mgr,
        get_db_fn    = get_db,
        repo_factory = TaskRepository,
        signal_fn    = None,
        now_fn       = None,
    ):
        """
        Initialize the chase consumer.

        Requires:
            - config_mgr exposes .get( key, default=, return_type= )
            - get_db_fn is a context-manager factory yielding a DB session
            - repo_factory( session ) -> a TaskRepository-like object exposing
              query_chase_due / apply_chase
            - signal_fn( item ) -> None emits the chase nudge (default: a
              structured banner log); injected so tests assert it fired
            - now_fn() -> tz-aware datetime (default: datetime.now(utc));
              injected so tests pin the clock

        Ensures:
            - no thread is started at construction (call start() explicitly)
        """
        self._config_mgr   = config_mgr
        self._get_db_fn    = get_db_fn
        self._repo_factory = repo_factory
        self._signal_fn    = signal_fn if signal_fn is not None else self._default_signal
        self._now_fn       = now_fn if now_fn is not None else ( lambda: datetime.now( timezone.utc ) )
        self._stop_event   = threading.Event()
        self._thread       = None

    # -- config accessors -----------------------------------------------------

    def _enabled( self ) -> bool:
        return self._config_mgr.get( "task store chase enabled", default=False, return_type="boolean" )

    def _interval_seconds( self ) -> int:
        return self._config_mgr.get( "task store chase interval seconds", default=300, return_type="int" )

    def _backoff_seconds( self ) -> int:
        return self._config_mgr.get( "task store chase backoff seconds", default=1800, return_type="int" )

    # -- core (unit-testable, no thread) --------------------------------------

    def sweep_once( self ) -> dict:
        """
        Run one chase pass: signal + re-arm every overdue blocked item.

        Ensures:
            - flag OFF  -> no DB access at all; returns {enabled:False, chased:0}
            - flag ON   -> for each query_chase_due(now) item: signal_fn(item),
              then apply_chase(re-armed next_chase_ts = now + backoff); status
              is NEVER touched; returns {enabled:True, chased:<n>}
            - one get_db() transaction wraps the whole pass (atomic commit)

        Returns:
            dict summary { "enabled": bool, "chased": int }
        """
        if not self._enabled():
            return { "enabled": False, "chased": 0 }

        now     = self._now_fn()
        re_arm  = now + timedelta( seconds=self._backoff_seconds() )
        chased  = 0
        with self._get_db_fn() as session:
            repo = self._repo_factory( session )
            for item in repo.query_chase_due( now ):
                self._signal_fn( item )
                repo.apply_chase( item, actor=CHASE_ACTOR, authority="standing", next_chase_ts=re_arm )
                chased += 1
        return { "enabled": True, "chased": chased }

    def stall_report( self ) -> list:
        """
        Read-only surfacing of overdue blocked items (the store-derived I4
        signal: stalls that are visible IN the store). NEVER mutates, NEVER
        gated — a manager/operator can always ask "what's overdue?".

        Note: the hook-side I4 (sessions that should-write-but-don't) lives in
        the hook lane's flag-once markers (Phase 2) — that surface is a
        documented follow-on; this report covers store-internal stalls only.

        Returns:
            list of { id, owner_persona, accountable_manager, title,
            next_chase_ts } dicts for every currently-overdue blocked item
        """
        now = self._now_fn()
        with self._get_db_fn() as session:
            repo = self._repo_factory( session )
            return [
                {
                    "id"                  : str( item.id ),
                    "owner_persona"       : item.owner_persona,
                    "accountable_manager" : item.accountable_manager,
                    "title"               : item.title,
                    "next_chase_ts"       : item.next_chase_ts.isoformat() if item.next_chase_ts is not None else None,
                }
                for item in repo.query_chase_due( now )
            ]

    def _default_signal( self, item ) -> None:
        """Default chase sink: a structured banner naming who owes/chases what."""
        du.print_banner(
            f"[task-chase] overdue blocked item {item.id} "
            f"owner={item.owner_persona} manager={item.accountable_manager} title={item.title!r}",
            prepend_nl=True,
        )

    # -- daemon lifecycle -----------------------------------------------------

    def _loop( self ) -> None:
        """
        Daemon loop until stop(); Event.wait(timeout) so shutdown interrupts the
        nap immediately. Each sweep is exception-guarded so a transient DB error
        never kills the daemon.
        """
        while not self._stop_event.is_set():
            try:
                self.sweep_once()
            except Exception as e:
                du.print_banner( f"Task-chase consumer loop caught exception (continuing): {e!r}", prepend_nl=True )
            self._stop_event.wait( timeout=self._interval_seconds() )

    def start( self ) -> bool:
        """
        Spawn the daemon thread — ONLY if the flag is enabled and no thread is
        already running. Returns True if a thread was started, else False (the
        no-op rollout gate: a disabled consumer never spawns).
        """
        if not self._enabled():
            return False
        if self._thread is not None and self._thread.is_alive():
            return False
        self._stop_event.clear()
        self._thread = threading.Thread( target=self._loop, daemon=True, name="TaskChaseConsumer" )
        self._thread.start()
        return True

    def stop( self, timeout: float = 5.0 ) -> None:
        """Signal the daemon to exit and join it (idempotent — safe if never started)."""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join( timeout=timeout )
