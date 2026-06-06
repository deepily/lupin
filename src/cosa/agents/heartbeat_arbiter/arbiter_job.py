#!/usr/bin/env python3
"""
Heartbeat Arbiter — the consumer job (Rachel's wiring lane).

The cross-fleet CONSUMER of the local Heartbeat Hook's event exhaust
(arbiter design `03`). Each poll it:

    1. tails ~/.claude/heartbeat-events/*.jsonl from tracked offsets (new only),
    2. accumulates a bounded per-session tail,
    3. asks the gateway who is active (commons_who),
    4. builds the fleet view (Tiffany's build_fleet_view leaf),
    5. builds the dependency graph + deadlock cycles (build_graph leaf),
    6. AUTO-PINGS blockers — throttled, per-edge backoff, global rate cap,
       clear-on-resume (§6.1),
    7. builds the HYBRID trust-labeled idle-roster (build_roster leaf),
    8. surfaces roster + blocked-graph + stuck + deadlocks to the MANAGER as a
       SENSOR + RECOMMENDER (§6.3 — the manager actuates reassignment; the
       arbiter never auto-assigns).

**Invariant (§0 #2):** the arbiter is an ADDITIVE OBSERVER of the Hook's
exhaust — never a dependency of any local poke. It reads files + posts commons
messages; it cannot corrupt a session's local state. Degrades safe: if the
arbiter is down, every Hook still pokes.

Testability: extends AgenticJobBase (CJ Flow agentic job, like HeartbeatPokerJob)
with the same injected seams — a `Clock` (FakeClock drives the poll/hard-cap
loop without real waiting) and an `ArbiterGateway` (FakeGateway records
who/send_to/post). Pure decision logic lives in the leaves; this composes them.

Lane: Rachel (wiring). Pure leaves: Tiffany. Design owner: María. Manager: Tiberius.
"""
import asyncio
import datetime
from typing import Callable, List, Optional, Protocol, runtime_checkable

from cosa.agents.agentic_job_base import AgenticJobBase
# Reuse the Hook-Poker's clock seam (DRY — same SystemClock / FakeClock pattern).
from cosa.agents.heartbeat_poker_job import Clock, SystemClock

from cosa.agents.heartbeat_arbiter.events_tail import tail_fleet_events
from cosa.agents.heartbeat_arbiter.arbiter_state import (
    FleetEventAccumulator, PingLedger, DEFAULT_TAIL_MAXLEN,
)
from cosa.agents.heartbeat_arbiter.fleet_data_model import build_fleet_view
from cosa.agents.heartbeat_arbiter.dependency_graph import build_graph
from cosa.agents.heartbeat_arbiter.idle_roster import build_roster
from cosa.agents.heartbeat_arbiter import ping_throttle
# v2.1 direct-state visibility (design 03 §10.2-§10.4): per-session liveness off
# the bridge-mtime clock, change-or-tick render, and the queryable snapshot push.
from cosa.agents.heartbeat_arbiter.fleet_render import (
    build_snapshot, frame_signature, render_fleet_table, render_tick,
)
from cosa.rest.arbiter_snapshot_store import set_snapshot as _default_snapshot_sink
from lupin_cli.claude_code.hooks.lib.session_bridge import (
    get_bridge_mtime as _default_bridge_mtime_fn,
)


# Manager-surface topic + auto-ping message template
ROSTER_TOPIC          = "fleet-arbiter"
PING_MESSAGE_TEMPLATE = "Session {holder} is holding on you — where are we?"
# build_graph edges are persona→persona; a richer "reason" is not well-sourced
# from the event stream (the holder's `awaiting` is just "peer:<awaited>",
# circular), so the throttle key uses a stable constant — one ping per
# (holder, awaited) blocker pair per backoff window.
PING_REASON           = "blocked"


@runtime_checkable
class ArbiterGateway( Protocol ):
    """
    Injectable commons seam for the arbiter (server-side, in-process).

    Distinct from the Hook-Poker's CommonsGateway: the arbiter additionally
    needs `who()` (list active sessions for the liveness SECONDARY signal +
    the roster) and `post()` (the manager surface). All I/O behind this seam →
    100% unit-testable with a FakeGateway.
    """
    def who( self, retention_hours: int = 24 ) -> List[ dict ]: ...
    def send_to( self, recipient: str, body: str ) -> None: ...
    def post( self, topic: str, body: str ) -> None: ...


class ArbiterConsumerJob( AgenticJobBase ):
    """
    The fleet Heartbeat-Arbiter consumer (CJ Flow Layer-1 agentic job).

    Exit disposition mirrors HeartbeatPokerJob: cancelled / hard-cap RETURN
    normally → queue marks `done`; only an unexpected exception → `dead`. A
    single poll's failure is swallowed (observer invariant) and never exits the
    loop.
    """

    JOB_TYPE   = "heartbeat_arbiter"
    JOB_PREFIX = "ha"

    def __init__(
        self,
        commons                  : ArbiterGateway,
        poll_seconds             : int,
        manager_recipient        : str,
        alive_threshold_seconds  : int                  = 600,
        quiet_threshold_seconds  : int                  = 300,
        ping_global_cap          : int                  = 10,
        ping_cap_window_seconds  : int                  = 3600,
        max_duration_seconds     : int                  = 43_200,   # 12h
        events_dir               : Optional[ str ]      = None,     # None → fleet dir
        tail_maxlen              : int                  = DEFAULT_TAIL_MAXLEN,
        clock                    : Optional[ Clock ]    = None,
        notify_fn                : Optional[ Callable ] = None,
        bridge_mtime_fn          : Optional[ Callable ] = None,
        snapshot_sink            : Optional[ Callable ] = None,
        render_sink              : Optional[ Callable ] = None,
        user_id      : str  = None,
        user_email   : str  = None,
        session_id   : str  = None,
        scheduled_at : str  = None,
        monopolize   : bool = False,
        debug        : bool = False,
        verbose      : bool = False,
    ) -> None:
        """
        Construct the arbiter consumer job.

        Requires:
            - commons satisfies the ArbiterGateway protocol
            - poll_seconds, alive/quiet_threshold_seconds, ping_cap_window_seconds,
              max_duration_seconds, tail_maxlen are positive ints
            - quiet_threshold_seconds < alive_threshold_seconds (F3 invariant —
              else the inference idle-window is empty)
            - ping_global_cap is an int >= 1
            - manager_recipient is a non-empty string

        Ensures:
            - parent AgenticJobBase state initialised
            - config stored; injected seams resolved (clock → SystemClock)
            - any invariant violation raises ValueError with context
        """
        super().__init__(
            user_id      = user_id,
            user_email   = user_email,
            session_id   = session_id,
            scheduled_at = scheduled_at,
            monopolize   = monopolize,
            debug        = debug,
            verbose      = verbose,
        )

        if poll_seconds <= 0:
            raise ValueError( f"poll_seconds must be positive, got {poll_seconds}" )
        if max_duration_seconds <= 0:
            raise ValueError( f"max_duration_seconds must be positive, got {max_duration_seconds}" )
        if alive_threshold_seconds <= 0:
            raise ValueError( f"alive_threshold_seconds must be positive, got {alive_threshold_seconds}" )
        if quiet_threshold_seconds <= 0:
            raise ValueError( f"quiet_threshold_seconds must be positive, got {quiet_threshold_seconds}" )
        # F3 invariant (design §6.2): the inference idle-window is [quiet, alive];
        # it is non-empty ONLY when quiet < alive. quiet >= alive silently
        # config-deads the inference half → the hybrid roster degrades to
        # declared-only (Mr. Radio's integration finding). Fail fast so the
        # bug-class can never reship.
        if quiet_threshold_seconds >= alive_threshold_seconds:
            raise ValueError(
                f"quiet_threshold_seconds ({quiet_threshold_seconds}) must be < "
                f"alive_threshold_seconds ({alive_threshold_seconds}) — else the "
                f"inference idle-window is empty (design §6.2 F3)"
            )
        # Heuristic caveat (§6.2, María 2026-06-05): with quiet=300 a long single
        # tool-run (>5min between Stops) can read as "quiet (inferred)" though
        # actually working — mitigated by the trust-label (the manager weighs an
        # inferred entry before reassigning) + tunability (widen toward 600/1200
        # if prod is noisy). The numbers are tunable config; the invariant above
        # is the real guard against the config-dead bug-class.
        if ping_global_cap < 1:
            raise ValueError( f"ping_global_cap must be >= 1, got {ping_global_cap}" )
        if ping_cap_window_seconds <= 0:
            raise ValueError( f"ping_cap_window_seconds must be positive, got {ping_cap_window_seconds}" )
        if tail_maxlen <= 0:
            raise ValueError( f"tail_maxlen must be positive, got {tail_maxlen}" )
        if not manager_recipient:
            raise ValueError( "manager_recipient must be a non-empty string" )

        # --- config ---
        self.poll_seconds            = poll_seconds
        self.manager_recipient       = manager_recipient
        self.alive_threshold_seconds = alive_threshold_seconds
        self.quiet_threshold_seconds = quiet_threshold_seconds
        self.ping_global_cap         = ping_global_cap
        self.ping_cap_window_seconds = ping_cap_window_seconds
        self.max_duration_seconds    = max_duration_seconds
        self.events_dir              = events_dir

        # --- injected seams ---
        self._commons   = commons
        self._clock     = clock if clock is not None else SystemClock()
        self._notify_fn = notify_fn if notify_fn is not None else self.notify_progress
        # v2.1 seams: bridge-mtime liveness reader, snapshot sink (in-pool →
        # server singleton), and the render sink (greppable log; default stdout,
        # captured by the container log). All injectable for 100% unit testing.
        self._bridge_mtime_fn = bridge_mtime_fn if bridge_mtime_fn is not None else _default_bridge_mtime_fn
        self._snapshot_sink   = snapshot_sink   if snapshot_sink   is not None else _default_snapshot_sink
        self._render_sink     = render_sink      if render_sink     is not None else print

        # --- consumer state (carried across polls) ---
        self._offsets       = { }                                  # sid -> byte offset
        self._acc           = FleetEventAccumulator( maxlen=tail_maxlen )
        self._ledger        = PingLedger()
        self._ping_attempts = { }                                  # edge_key -> attempt count
        self._recent_pings  = [ ]                                  # list of ping datetimes (global-cap window)
        self._poll_count    = 0
        # v2.1 render state (§10.3 change-or-tick): the last rendered SEMANTIC
        # frame signature + when it last changed (for the tick's since-duration).
        self._last_frame_sig = None
        self._last_change_at = None

    def last_question_asked( self ) -> str:
        """Human-readable display string for the queue UI (QueueableJob protocol)."""
        return ( f"Heartbeat arbiter — manager {self.manager_recipient} @ "
                 f"{self.poll_seconds}s poll" )

    # ── one poll cycle ────────────────────────────────────────────────────────

    def _poll_once( self ):
        """
        Run ONE arbiter poll: tail → view → graph → ping → roster → surface.

        Ensures:
            - reads new events, updates the fleet view, fires throttled pings,
              and posts the recommender surface to the manager
            - returns a small summary dict (for tests / logging)
            - never raises (a leaf/gateway hiccup is swallowed per the observer
              invariant) — see _execute's per-poll guard
        """
        now = datetime.datetime.fromisoformat( self._clock.now_iso() )

        new_events, self._offsets = tail_fleet_events( self.events_dir, self._offsets )
        self._acc.update( new_events )

        who_rows   = self._commons.who()
        fleet_view = build_fleet_view(
            self._acc.snapshot(), who_rows, now, self.alive_threshold_seconds
        )
        graph = build_graph( fleet_view )

        self._escalate_deadlocks( graph[ "cycles" ] )
        pings_fired = self._auto_ping( graph[ "edges" ], now )
        roster      = build_roster( fleet_view, now, self.quiet_threshold_seconds )
        self._surface_to_manager( fleet_view, graph, roster )
        rendered    = self._publish_fleet_snapshot( fleet_view, now )

        self._poll_count += 1
        return {
            "sessions"    : len( fleet_view ),
            "edges"       : len( graph[ "edges" ] ),
            "cycles"      : len( graph[ "cycles" ] ),
            "pings_fired" : pings_fired,
            "roster"      : len( roster ),
            "rendered"    : rendered,
        }

    def _publish_fleet_snapshot( self, fleet_view, now ):
        """
        Build + render + push the v2.1 direct-state fleet snapshot (§10.2-§10.4).

        Requires:
            - fleet_view is the per-session view dict (build_fleet_view output)
            - now is an aware datetime

        Ensures:
            - reads each session's bridge-mtime (the wedge-resilient liveness
              clock, §10.1) via the injected reader and builds the snapshot with
              STATE and LIVENESS kept as orthogonal columns (C4)
            - renders the FULL table when the semantic frame changed (or on the
              first poll), else a one-line tick with the duration-since-change
              (§10.3 / D1) — to the injected render sink (greppable log)
            - pushes the snapshot to the injected sink (the in-pool arbiter's
              server singleton, surfaced by GET /api/arbiter/fleet-snapshot)
            - returns "table" or "tick" (for the poll summary)
        """
        bridge_mtimes = { sid: self._bridge_mtime_fn( sid ) for sid in fleet_view }
        snapshot      = build_snapshot( fleet_view, bridge_mtimes, now )

        sig = frame_signature( snapshot )
        if sig != self._last_frame_sig:
            self._last_frame_sig = sig
            self._last_change_at = now
            self._render_sink( render_fleet_table( snapshot ) )
            rendered = "table"
        else:
            self._render_sink( render_tick( now, self._last_change_at, snapshot[ "session_count" ] ) )
            rendered = "tick"

        self._snapshot_sink( snapshot )
        return rendered

    def _auto_ping( self, edges, now ):
        """
        Auto-ping each blocker, throttled + per-edge backoff + global cap, then
        clear-on-resume (§6.1).

        Requires:
            - edges is {holder: awaited} (build_graph output — persona→persona)
            - now is an aware datetime

        Ensures:
            - pings at most one DM per (holder, awaited) edge per backoff window,
              and never more than ping_global_cap within the cap window
            - the DM names the holder + goes to the awaited peer
            - records each ping in the ledger + attempt counter
            - drops ledger + attempt state for edges no longer active (resume)
            - returns the count of pings fired this poll
        """
        self._prune_recent_pings( now )
        fired       = 0
        active_keys = set()

        for holder, awaited in edges.items():
            key = ping_throttle.edge_key( holder, awaited, PING_REASON )
            active_keys.add( key )

            attempt   = self._ping_attempts.get( key, 0 )
            # `attempt` is the count of pings ALREADY fired for this edge, so the
            # gap BEFORE the next ping is backoff_for_attempt(attempt-1): the
            # first gated gap (after 1 ping) = schedule[0]=60, then 300/900/3600.
            # (attempt=0 → backoff_for_attempt(-1) clamps to schedule[0], unused
            # because should_ping(None,…) short-circuits the immediate first ping.)
            backoff   = ping_throttle.backoff_for_attempt( attempt - 1 )
            under_cap = ping_throttle.under_global_cap( len( self._recent_pings ), self.ping_global_cap )
            if under_cap and ping_throttle.should_ping( self._ledger.get_last( key ), now, backoff ):
                self._commons.send_to( awaited, PING_MESSAGE_TEMPLATE.format( holder=holder ) )
                self._ledger.record_ping( key, now )
                self._ping_attempts[ key ] = attempt + 1
                self._recent_pings.append( now )
                fired += 1

        # clear-on-resume: forget edges no longer present
        self._ledger.clear_resolved( active_keys )
        for stale in [ k for k in self._ping_attempts if k not in active_keys ]:
            del self._ping_attempts[ stale ]
        return fired

    def _escalate_deadlocks( self, cycles ):
        """
        Escalate deadlock cycles to the user/manager — NEVER auto-break (§4).

        Requires:
            - cycles is a list of canonical peer cycles (build_graph output)

        Ensures:
            - fires ONE notify_fn escalation per poll when any cycle exists
              (the arbiter surfaces deadlocks; a human decides the break)
            - no-op when there are no cycles
        """
        if cycles:
            rendered = "; ".join( " → ".join( c ) for c in cycles )
            self._notify_fn( f"DEADLOCK detected (no autonomous break) — escalating: {rendered}" )

    def _prune_recent_pings( self, now ):
        """Drop recorded pings older than the global-cap window (rolling cap)."""
        cutoff = self.ping_cap_window_seconds
        self._recent_pings = [
            ts for ts in self._recent_pings
            if ( now - ts ).total_seconds() < cutoff
        ]

    def _surface_to_manager( self, fleet_view, graph, roster ):
        """
        Post the sensor+recommender surface to the manager (§6.3 — never auto-assign).

        Ensures:
            - posts a single structured message to ROSTER_TOPIC summarising the
              idle-roster, blocked edges, deadlock cycles, and stuck sessions
            - deadlock cycles are flagged for manager escalation (the arbiter
              never breaks a cycle autonomously)
        """
        stuck = [ v.get( "session_id" ) for v in fleet_view.values()
                  if isinstance( v, dict ) and v.get( "stuck" ) ]
        lines = [
            f"Fleet arbiter — {len( fleet_view )} session(s).",
            f"Idle-roster ({len( roster )}): " + ", ".join(
                f"{r['persona'] or r['session_id']} [{r['trust_label']}]" for r in roster
            ) if roster else "Idle-roster: (none)",
            f"Blocked edges ({len( graph['edges'] )}): " + ", ".join(
                f"{h}→{a}" for h, a in graph[ "edges" ].items()
            ) if graph[ "edges" ] else "Blocked edges: (none)",
        ]
        if graph[ "cycles" ]:
            lines.append( "⚠️ DEADLOCK cycle(s) — manager escalation: " +
                          "; ".join( " → ".join( c ) for c in graph[ "cycles" ] ) )
        if stuck:
            lines.append( "Stuck (≥2 cap-reached, work owed): " + ", ".join( stuck ) )
        self._commons.post( ROSTER_TOPIC, "\n".join( lines ) )

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def _execute( self ):
        """
        Poll loop: poll → sleep, until cancel or hard-cap.

        Ensures:
            - exits on self._cancel_requested or elapsed >= max_duration_seconds
            - a per-poll exception is logged via notify_fn and SWALLOWED (the
              observer invariant — one bad poll never kills the arbiter)
            - returns an exit-summary string
        """
        start = self._clock.monotonic()
        while True:
            if self._cancel_requested:
                return self._exit_summary( "cancelled" )
            if ( self._clock.monotonic() - start ) >= self.max_duration_seconds:
                return self._exit_summary( "hard-cap" )

            try:
                self._poll_once()
            except Exception as e:                      # observer invariant — never die on one poll
                self._notify_fn( f"arbiter poll error (continuing): {e}" )

            await self._clock.sleep( self.poll_seconds )

    def _exit_summary( self, reason ):
        """Ensures: returns a human-readable exit summary + stores it on the job."""
        summary = f"Heartbeat arbiter exited ({reason}) after {self._poll_count} poll(s)."
        self.answer_conversational = summary
        return summary

    def do_all( self ):
        """
        Sync entry point (CJ Flow agentic-pool dispatch). Bridges async _execute.

        Ensures:
            - runs the poll loop to completion; stamps started_at/completed_at
            - returns the exit-summary string
        """
        self.started_at = self._clock.now_iso()
        try:
            summary = asyncio.run( self._execute() )
        finally:
            self.completed_at = self._clock.now_iso()
        return summary
