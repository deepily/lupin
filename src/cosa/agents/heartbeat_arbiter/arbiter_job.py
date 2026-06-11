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
import json
import zoneinfo
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
    build_snapshot, carry_forward_lineage, frame_signature, prune_offline_rows,
    render_fleet_table, render_tick,
)
from cosa.rest.arbiter_snapshot_store import set_snapshot as _default_snapshot_sink
from lupin_cli.claude_code.hooks.lib.session_bridge import (
    get_bridge_mtime as _default_bridge_mtime_fn,
    find_active_voice_persona_sessions as _find_active_voice_persona_sessions,
    find_dead_sessions as _find_dead_sessions,
)
from cosa.agents.heartbeat_arbiter.manager_resolver import (
    resolve_manager as _default_resolve_manager,
    resolve_active_managers as _default_resolve_active_managers,
    list_manager_session_ids as _default_list_manager_session_ids,
)
# 2b-2 recipient routing — the ratified Part-6 tier model (pure leaf). CASE_TIERS
# is the RUNTIME contract: _route(case, …) dispatches by tier_for(case).
from cosa.agents.heartbeat_arbiter.arbiter_routing import (
    TIER_RICK_ONLY, TIER_RICK_AND_MANAGERS, TIER_OWNING_MANAGER,
    TIER_BLOCKER_AND_MANAGER, TIER_DROP, tier_for, CASE_AUTO_POKE_REAP_REC,
    CASE_MANAGER_STALE_ADVISORY, CASE_FLEET_DARK,
)


# Manager-surface topic + auto-ping message template
ROSTER_TOPIC          = "fleet-arbiter"
# v2.2 B3 D3 trigger: a reserved topic a worker/manager posts to when the fleet
# hits a decision IT can't make (scope / prod-logic / hard ambiguity). The
# arbiter TAILS it (read-only) and escalates each new post to Rick. Registered in
# planning-is-prompting → workflow/cross-session-communication.md reserved-topic table.
DECISION_TOPIC        = "fleet-decision-needed"
# 2b-2 Part-6 #4 rewrite: the ping goes to the BLOCKER (`awaited`), naming the
# blocked worker (`holder`) and the ASK — not the old vague "where are we?".
PING_MESSAGE_TEMPLATE = ( "You're blocking worker {holder} — they're waiting on you. "
                          "Post your status or unblock them." )
# build_graph edges are persona→persona; a richer "reason" is not well-sourced
# from the event stream (the holder's `awaiting` is just "peer:<awaited>",
# circular), so the throttle key uses a stable constant — one ping per
# (holder, awaited) blocker pair per backoff window.
PING_REASON           = "blocked"

# ── post-game constants (2026-06-11 missed-poke post-game — design src/rnd/
#    v0.1.8/2026.06.11-arbiter-missed-poke-postgame-and-outreach-logging.md) ──
# F1: full why-not-poked gate dump every N polls (hourly at the 60s default), so
# a long outreach silence is self-explaining even when no gate vector changes.
GATE_DUMP_INTERVAL_POLLS = 60
# F3 recovery arm: "the fleet JUST died" horizon — a boot straight into an empty
# published roster fires the fleet-dark advisory ONLY if some session still shows
# a signal younger than this (a cold morning boot over last evening's reaped
# roster has none → silent; the page-Rick-every-morning failure mode can't occur).
DARK_LOOKBACK_SECONDS    = 7200
# F1: arbiter_outreach carries a truncated message head, not the full body.
OUTREACH_SUMMARY_MAXLEN  = 160

# F1: routed-case → log `kind` vocabulary (the direct-send kinds — poke,
# manager_stale_poke, decision_cc, poll_error_escalation — are literals at their
# emission sites).
CASE_KINDS = {
    4                           : "ping",
    5                           : "deadlock",
    7                           : "tap",
    8                           : "orphan_worker",
    9                           : "manager_down",
    10                          : "decision",
    11                          : "stall",
    CASE_AUTO_POKE_REAP_REC     : "reap_rec",
    CASE_MANAGER_STALE_ADVISORY : "manager_stale_advisory",
    CASE_FLEET_DARK             : "fleet_dark",
}


def _default_log_fn( event, **fields ):
    """
    Structured JSON log line to stdout (flushed) — the F1 default log seam.

    Mirrors the lupin_arbiter_app loops' `_default_log_fn` shape so events from
    an in-pool arbiter land in the same greppable vocabulary; the :8001 factory
    injects the app's own log_fn instead (adding service/loop fields).

    Ensures:
        - prints one JSON object: { ts, service, event, **fields }
        - non-serializable field values are stringified (default=str)
    """
    line = {
        "ts"      : datetime.datetime.now( datetime.timezone.utc ).isoformat(),
        "service" : "heartbeat-arbiter",
        "event"   : event,
    }
    line.update( fields )
    print( json.dumps( line, default=str ), flush=True )


def _fmt_minutes( seconds ):
    """Compact whole-minutes age for Rick-facing text: 2700 → '45m'; None → 'unknown'."""
    if seconds is None:
        return "unknown"
    return f"{int( seconds ) // 60}m"


def _fmt_eastern( dt ):
    """
    Rick-facing wall-clock: aware datetime → 'HH:MM EDT/EST' (America/New_York).

    The journal + commons speak UTC; every human-facing advisory converts and
    LABELS the zone (project doctrine — bare-UTC times in Rick-facing text are
    a known footgun).

    Ensures:
        - returns the zone-labeled local time string; None / unusable input
          degrades to 'unknown'; never raises
    """
    if dt is None:
        return "unknown"
    try:
        return dt.astimezone( zoneinfo.ZoneInfo( "America/New_York" ) ).strftime( "%H:%M %Z" )
    except Exception:
        return "unknown"


def _default_bridge_discovery():
    """
    Discover live persona bridges → { session_id: persona_name|None }.

    The IMPURE integrator helper (arbiter liveness fix, Step 1.4): enumerates
    the live persona bridges out-of-band and reduces each to its session_id +
    persona name so the PURE `build_fleet_view` can fold them into the UNION
    roster WITHOUT doing IO itself. A bridge presence makes a session a roster
    member even with no events; its bridge mtime (read separately in
    `_publish_fleet_snapshot`) supplies the bridge_age liveness signal.

    Ensures:
        - returns { session_id: persona_name|None } for each live bridge
        - never raises — a discovery hiccup yields {} so the observer poll
          degrades safe (the §0 #2 invariant)
    """
    out = { }
    try:
        for _path, session_id, persona in _find_active_voice_persona_sessions(
                stale_threshold_seconds=43_200 ):
            if not session_id:
                continue
            out[ session_id ] = persona.get( "name" ) if isinstance( persona, dict ) \
                                else ( str( persona ) if persona else None )
    except Exception:
        return { }
    return out


def _default_dead_session_ids( fleet_view ):
    """
    Confirmed-dead session-ids among the fleet view → set[str] (the §kill-0 source).

    The IMPURE death probe for `_publish_fleet_snapshot`: delegates to
    session_bridge.find_dead_sessions (unfiltered bridge scan + kill -0), which is
    itself host-PID-trust gated + bias-to-alive. Wrapped degrade-safe so a probe
    hiccup yields an empty set — the snapshot then falls back to staleness exactly
    as before (the §0 #2 observer invariant).

    Ensures:
        - returns a set[str] subset of fleet_view's session-ids (empty on any error,
          in a container, or when nothing is positively dead)
        - never raises
    """
    try:
        return _find_dead_sessions( fleet_view.keys() )
    except Exception:
        return set()


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
    # v2.2 B3: tail a reserved topic (e.g. fleet-decision-needed). READ is pure
    # OBSERVATION — side-effect-free, redline-safe (NOT actuation). Verb set is
    # now {who, send_to, post, read}: all sense/recommend/escalate, zero actuate.
    def read( self, topic: str, since: Optional[ str ] = None, limit: int = 50 ) -> List[ dict ]: ...


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
        tap_min_interval_seconds : int                  = 300,
        manager_ack_window_seconds : int                = 600,
        fleet_stall_window_seconds : int                = 1800,
        poll_error_escalate_threshold : int             = 3,
        auto_poke_enabled        : bool                 = True,
        poke_stall_threshold_seconds : int              = 720,    # ~12 min
        poke_max_per_episode     : int                  = 3,
        manager_stale_poke_threshold_seconds : int      = 2700,   # post-game F2 (~45 min; 0 disables)
        clock                    : Optional[ Clock ]    = None,
        notify_fn                : Optional[ Callable ] = None,
        bridge_mtime_fn          : Optional[ Callable ] = None,
        bridge_discovery_fn      : Optional[ Callable ] = None,
        snapshot_sink            : Optional[ Callable ] = None,
        render_sink              : Optional[ Callable ] = None,
        resolve_manager_fn       : Optional[ Callable ] = None,
        resolve_active_managers_fn : Optional[ Callable ] = None,
        list_managers_fn         : Optional[ Callable ] = None,
        log_fn                   : Optional[ Callable ] = None,
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
        if poll_error_escalate_threshold < 1:
            raise ValueError( f"poll_error_escalate_threshold must be >= 1, got {poll_error_escalate_threshold}" )
        if poke_stall_threshold_seconds < 0:
            raise ValueError( f"poke_stall_threshold_seconds must be >= 0, got {poke_stall_threshold_seconds}" )
        if poke_max_per_episode < 1:
            raise ValueError( f"poke_max_per_episode must be >= 1, got {poke_max_per_episode}" )
        # post-game F2: 0 disables the manager-staleness tier; negative is a config bug.
        if manager_stale_poke_threshold_seconds < 0:
            raise ValueError( f"manager_stale_poke_threshold_seconds must be >= 0, "
                              f"got {manager_stale_poke_threshold_seconds}" )
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
        # v1.4 integrator seam: bridge discovery → {sid: persona} folded into the
        # build_fleet_view UNION roster (impure IO lives here, not in the leaf).
        self._bridge_discovery_fn = bridge_discovery_fn if bridge_discovery_fn is not None else _default_bridge_discovery
        self._snapshot_sink   = snapshot_sink   if snapshot_sink   is not None else _default_snapshot_sink
        self._render_sink     = render_sink      if render_sink     is not None else print
        # v2.2 B2 manager-tap: per-worker manager routing (D5 lineage) seam.
        self._resolve_manager_fn = resolve_manager_fn if resolve_manager_fn is not None else _default_resolve_manager
        # 2b-2 Part-6 fanout: the active-managers-on-duty resolver seam (commons
        # candidate ∩ live-bridge PID guard — phantom-safe). Injectable for tests.
        self._resolve_active_managers_fn = ( resolve_active_managers_fn
                                             if resolve_active_managers_fn is not None
                                             else _default_resolve_active_managers )
        self.tap_min_interval_seconds      = tap_min_interval_seconds
        self.manager_ack_window_seconds    = manager_ack_window_seconds
        self.fleet_stall_window_seconds    = fleet_stall_window_seconds
        self.poll_error_escalate_threshold = poll_error_escalate_threshold
        # 2b-3 auto-poke (Rick redline-narrowing confirmed): bounded, non-destructive
        # wake-nudge at genuinely-stuck LIVE sessions, then a reap-RECOMMENDATION.
        self.auto_poke_enabled             = auto_poke_enabled
        self.poke_stall_threshold_seconds  = poke_stall_threshold_seconds
        self.poke_max_per_episode          = poke_max_per_episode
        # post-game F2: the SECOND, role-gated pokeable criterion — a MANAGER-role
        # session whose freshest union signal is older than this is poked + Rick-
        # advised even with zero stuck workers (the 2026-06-10 gap). 0 disables.
        self.manager_stale_poke_threshold_seconds = manager_stale_poke_threshold_seconds
        # post-game F1: the structured-log seam — every outreach + gate evaluation
        # lands in the journal so silence is diagnosable (Rick's verbatim ask).
        self._log_fn           = log_fn           if log_fn           is not None else _default_log_fn
        # post-game F2: manager-manifest role source, injectable for tests (was a
        # hardcoded _default_list_manager_session_ids inside _publish_fleet_snapshot).
        self._list_managers_fn = list_managers_fn if list_managers_fn is not None else _default_list_manager_session_ids

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
        # v2.2 B2 manager-tap throttle state (per manager persona): last tapped
        # crew-summary signature + when, so a manager is tapped only on CHANGE +
        # min-interval (never tap on no-change).
        self._last_tap_sig = { }
        self._last_tap_at  = { }
        # v2.2 B4/D4 manager-ack tracking: managers already escalated as down for
        # their current (un-acked) tap — so manager-down escalates ONCE, not every
        # poll, until the manager re-acks (shows liveness after the tap).
        self._manager_down_escalated = set()
        # v2.2 B3 state: decision-needed tail cursor (ISO ts; baselined on first
        # poll so a pre-arbiter backlog isn't re-escalated) + whole-fleet-stall
        # progress tracking (last PROGRESS signature + when it last advanced +
        # whether the current stall was already escalated).
        self._decision_since   = None
        self._last_progress_sig = None
        self._last_progress_at  = None
        self._stall_escalated   = False
        # 2b-2 Part-6 #12: poll-error is DEMOTED to a log; escalate to Rick only
        # when PERSISTENT (≥ threshold consecutive failures = arbiter effectively
        # down). Streak resets on any clean poll; escalate-once per persistent run.
        self._poll_error_streak    = 0
        self._poll_error_escalated = False
        # 2b-3 auto-poke per-STALL-EPISODE state (anti-storm FM-20: PERSISTS across
        # ticks, NOT per-poll). Keyed by session_id; cleared when a session leaves
        # the pokeable set (its episode ends → the cap re-arms for a future episode).
        self._poke_stuck_since = { }                               # sid -> episode-start datetime
        self._poke_count       = { }                               # sid -> pokes fired this episode
        self._poke_escalated   = set()                             # sids whose reap-rec already fired
        # Fleet-Status offline-lineage carry (2026-06-10): last poll's resolved
        # { session_id -> manager_persona }. A reaped worker loses BOTH lineage
        # sources at once (bridge unlink + manifest drop), so without this its
        # still-decaying row would wrongly drop to "Unmanaged". Threaded through
        # carry_forward_lineage each poll; pruned to the published sids (eviction).
        self._manager_lineage  = { }                               # sid -> manager_persona (last-known)
        # post-game F2: manager-staleness EPISODE state (mirrors the stuck-tier
        # _poke_* trio): keyed by session_id; cleared when the manager freshens
        # below the threshold (or leaves the roster) → the cap + advisory re-arm.
        self._mgr_stale_since  = { }                               # sid -> episode-start datetime
        self._mgr_poke_count   = { }                               # sid -> staleness pokes this episode
        self._mgr_advised      = set()                             # sids whose Rick advisory fired this episode
        # post-game F3: fleet-dark hybrid trigger state. The edge (prev>0 → 0) is
        # primary; the recovery arm (boot straight into 0 with recent corpses) only
        # runs while NO nonzero roster has been seen this process.
        self._published_count_prev = None                          # last poll's PUBLISHED row count
        self._fleet_dark_escalated = False                         # once per dark episode
        self._saw_nonzero_roster   = False                         # gates the recovery arm OFF after any live poll
        self._last_manager_seen    = None                          # { persona, at: datetime } freshest manager signal observed
        # post-game F1: per-session why-not-poked gate signatures (emit-on-change).
        self._gate_state           = { }                           # sid -> (stuck_why tuple, stale_why tuple)
        # post-game: the FULL (include_offline=True) detection snapshot + published
        # row count of the current poll — set by _publish_fleet_snapshot, consumed
        # by the F2/F3 detectors in the same _poll_once pass.
        self._last_full_snapshot   = None
        self._last_published_n     = 0

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

        who_rows        = self._commons.who()
        bridge_sessions = self._bridge_discovery_fn()              # impure discovery → UNION source (a)
        fleet_view      = build_fleet_view(
            self._acc.snapshot(), who_rows, now, self.alive_threshold_seconds,
            bridge_sessions=bridge_sessions,
        )
        graph = build_graph( fleet_view )

        # 2b-2 Part-6 fanout inputs: the active-managers-on-duty set (phantom-
        # guarded) for the Rick+managers tier, and a persona→session_id map (off
        # the fleet view) so #4 can cc the blocker's owning manager.
        active_managers = self._active_managers( who_rows, bridge_sessions )
        persona_to_sid  = {
            v.get( "persona" ): v.get( "session_id" )
            for v in fleet_view.values()
            if isinstance( v, dict ) and v.get( "persona" )
        }

        self._escalate_deadlocks( graph[ "cycles" ], active_managers )    # #5 Rick + all mgrs
        pings_fired = self._auto_ping( graph[ "edges" ], now, persona_to_sid )  # #4 blocker + cc mgr
        roster      = build_roster( fleet_view, now, self.quiet_threshold_seconds )
        # #6 roster broadcast DROPPED (Part-6 cut) — the fleet roster is PULL-state,
        # served by /state via the snapshot below; no per-tick commons post.
        taps_fired    = self._tap_managers( fleet_view, graph, roster, now, active_managers )  # #7 / #8
        managers_down = self._check_manager_acks( now, who_rows, active_managers )  # #9 Rick + all mgrs
        decisions     = self._check_decision_needed( now )          # #10 Rick (+owning mgr if known)
        stalled       = self._check_fleet_stall( fleet_view, now, active_managers )  # #11 Rick + all mgrs
        pokes_fired   = self._auto_poke( fleet_view, now, active_managers )          # 2b-3 auto-poke
        rendered      = self._publish_fleet_snapshot( fleet_view, now )
        # post-game F2/F3 detectors read the FULL (include_offline=True) detection
        # snapshot + published count the publish step just stashed on the instance.
        manager_stale_pokes = self._check_manager_staleness( self._last_full_snapshot, now, active_managers )
        fleet_dark          = self._check_fleet_dark( self._last_full_snapshot, self._last_published_n, now )
        # post-game F1: why-not-poked gate evaluation — runs AFTER both poke tiers
        # so the emitted vectors reflect this poll's episode state.
        self._emit_poke_gates( fleet_view, self._last_full_snapshot, now )

        self._poll_count += 1
        summary = {
            "sessions"            : len( fleet_view ),
            "edges"               : len( graph[ "edges" ] ),
            "cycles"              : len( graph[ "cycles" ] ),
            "pings_fired"         : pings_fired,
            "roster"              : len( roster ),
            "taps_fired"          : taps_fired,
            "managers_down"       : managers_down,
            "decisions"           : decisions,
            "stalled"             : stalled,
            "pokes_fired"         : pokes_fired,
            "manager_stale_pokes" : manager_stale_pokes,
            "fleet_dark"          : fleet_dark,
            "rendered"            : rendered,
        }
        # post-game F1: promote the summary to the journal whenever ANY outreach
        # counter is nonzero — a poll that communicated is never invisible.
        if any( summary[ k ] for k in (
                "pings_fired", "taps_fired", "managers_down", "decisions",
                "stalled", "pokes_fired", "manager_stale_pokes", "fleet_dark", "cycles" ) ):
            self._log( "arbiter_poll_activity", **summary )
        return summary

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
            - post-game split (2026-06-11): builds ONE FULL snapshot
              (include_offline=True) and stashes it on self._last_full_snapshot
              for the F2/F3 detectors, then derives the PUBLISHED live-only view
              via prune_offline_rows — render, frame signature, and sink payload
              ride the PUBLISHED view, so the D6/§5.2 published contract is
              unchanged; self._last_published_n carries its row count
            - renders the FULL table when the semantic frame changed (or on the
              first poll), else a one-line tick with the duration-since-change
              (§10.3 / D1) — to the injected render sink (greppable log)
            - pushes the published snapshot to the injected sink (the in-pool
              arbiter's server singleton, surfaced by GET /api/arbiter/fleet-snapshot)
            - returns "table" or "tick" (for the poll summary)
        """
        bridge_mtimes = { sid: self._bridge_mtime_fn( sid ) for sid in fleet_view }
        # PID fast-death (kill-0): confirmed-dead sessions among the fleet view, so
        # a /exit'd worker is forced "offline" in ~1 poll instead of aging out over
        # ~1h. Host-PID-trust gated + bias-to-alive inside find_dead_sessions (empty
        # set in a container, on any error, or when no pid is positively dead).
        process_dead  = _default_dead_session_ids( fleet_view )
        # Fleet-Status P1 (design §4): enrich each row with role + manager via the
        # already-injected resolver seam + the manager-manifest lister. Both are
        # degrade-safe inside build_snapshot (never raises), so a brittle hop can
        # only flatten the hierarchy — never crash the poll or mis-parent a worker.
        snapshot      = build_snapshot(
            fleet_view, bridge_mtimes, now,
            resolve_manager_fn = self._resolve_manager_fn,
            list_managers_fn   = self._list_managers_fn,
            process_dead       = process_dead,
            include_offline    = True,        # FULL view for the post-game F2/F3 detectors
        )
        # Fleet-Status offline-lineage carry (2026-06-10): a reaped worker loses both
        # lineage sources at once (bridge unlink + manifest drop), so its still-decaying
        # row would otherwise drop to "Unmanaged". Replay the last-known manager until
        # the row evicts. Pure + degrade-safe (never raises, never invents); manager is
        # orthogonal to frame_signature, so this never triggers a spurious re-render.
        # (Post-game note: the carry now runs on the FULL snapshot, so lineage is
        # retained until FULL-snapshot eviction — published rows are a subset and
        # receive identical fills, so the published view is unchanged.)
        snapshot, self._manager_lineage = carry_forward_lineage( snapshot, self._manager_lineage )
        self._last_full_snapshot = snapshot
        published                = prune_offline_rows( snapshot )   # the D6/§5.2 published contract
        self._last_published_n   = published[ "session_count" ]

        sig = frame_signature( published )
        if sig != self._last_frame_sig:
            self._last_frame_sig = sig
            self._last_change_at = now
            self._render_sink( render_fleet_table( published ) )
            rendered = "table"
        else:
            self._render_sink( render_tick( now, self._last_change_at, published[ "session_count" ] ) )
            rendered = "tick"

        self._snapshot_sink( published )
        return rendered

    # ── post-game F1: structured outreach + gate logging ────────────────────────

    def _log( self, event, **fields ):
        """
        Emit one structured log event via the injected log seam.

        Ensures:
            - calls self._log_fn( event, **fields )
            - a log_fn blow-up is swallowed (observer invariant — telemetry must
              never kill a poll); never raises
        """
        try:
            self._log_fn( event, **fields )
        except Exception:
            pass

    def _log_outreach( self, kind, via, recipients, message,
                       case=None, tier=None, session_id=None, persona=None ):
        """
        Emit the `arbiter_outreach` event — fired at EVERY outbound communication
        (Rick's verbatim ask: "a log so we can see when it's attempting to reach
        out and communicate").

        Accounting contract (the S3 invariant): `recipients` lists ONE entry per
        actual emission — "rick" for a notify_fn push, the persona name for each
        send_to — so the journal's recipient total equals the gateway+notify total.

        Ensures:
            - logs kind/via/recipients + a truncated message head (full bodies
              stay out of the journal); optional case/tier/session/persona fields
              attach when given; never raises
        """
        fields = {
            "kind"       : kind,
            "via"        : via,
            "recipients" : list( recipients ),
            "summary"    : ( message or "" )[ :OUTREACH_SUMMARY_MAXLEN ],
        }
        if case is not None: fields[ "case" ] = case
        if tier is not None: fields[ "tier" ] = tier
        if session_id:       fields[ "session_id" ] = session_id
        if persona:          fields[ "persona" ]    = persona
        self._log( "arbiter_outreach", **fields )

    # ── 2b-2 Part-6 recipient routing ───────────────────────────────────────────

    def _active_managers( self, who_rows, bridge_sessions ):
        """
        Resolve the active-managers-on-duty set for the Rick+managers fanout tier.

        Delegates to the injected resolver (commons candidate ∩ live-bridge PID
        guard — phantom-safe; a reaped manager whose commons last-post lingers is
        EXCLUDED). Swallows any resolver hiccup → [] (observer invariant: a
        resolver failure degrades the fanout to Rick-only, never crashes the poll).

        Ensures:
            - returns a list of active-manager personas (possibly empty); never raises
        """
        try:
            return self._resolve_active_managers_fn( who_rows, bridge_sessions ) or [ ]
        except Exception:
            return [ ]

    def _route( self, case, message, *, active_managers=None, owning_manager=None,
                blocker=None, cc_message=None ):
        """
        Dispatch an arbiter output to its Part-6 recipient tier — CASE_TIERS
        (arbiter_routing) is the contract; `tier_for(case)` selects the tier.

        Invariant: calls ONLY {notify_fn, send_to} — NO actuation (redline). The
        redline test (test_arbiter_redline) guards this structurally.

        Tier behaviors:
            - TIER_RICK_ONLY          → notify_fn(message)  (Rick: durable + live push)
            - TIER_RICK_AND_MANAGERS  → notify_fn(message) + send_to each active manager
            - TIER_OWNING_MANAGER     → send_to(owning_manager, message)  (if resolved)
            - TIER_BLOCKER_AND_MANAGER→ send_to(blocker, message) + send_to(owning_manager,
                                        cc_message)  (each when present)
            - TIER_DROP               → no push (pull-state; #6)
          (TIER_LOG_THEN_RICK #12 is handled by _on_poll_error's streak logic, not here.)

        Ensures:
            - emits exactly the recipients its tier prescribes; absent optional
              recipients (no manager resolved, empty active set) degrade silently
            - post-game F1: every routed emission is journaled as ONE
              `arbiter_outreach` event whose `recipients` lists each actual push
              ("rick" = notify_fn, persona = send_to); a no-emission route (empty
              tier inputs / TIER_DROP) logs nothing — the journal mirrors reality
            - never raises out (gateway send hiccups propagate to the caller's guard)
        """
        tier       = tier_for( case )
        recipients = [ ]
        if tier == TIER_RICK_ONLY:
            self._notify_fn( message )
            recipients.append( "rick" )
        elif tier == TIER_RICK_AND_MANAGERS:
            self._notify_fn( message )
            recipients.append( "rick" )
            for manager in active_managers or [ ]:
                self._commons.send_to( manager, message )
                recipients.append( manager )
        elif tier == TIER_OWNING_MANAGER:
            if owning_manager:
                self._commons.send_to( owning_manager, message )
                recipients.append( owning_manager )
        elif tier == TIER_BLOCKER_AND_MANAGER:
            if blocker:
                self._commons.send_to( blocker, message )
                recipients.append( blocker )
            if owning_manager and cc_message:
                self._commons.send_to( owning_manager, cc_message )
                recipients.append( owning_manager )
        # TIER_DROP → intentional no-op (the #6 roster broadcast is cut)
        if recipients:
            self._log_outreach( CASE_KINDS.get( case, f"case_{case}" ), "route",
                                recipients, message, case=case, tier=tier )

    def _auto_ping( self, edges, now, persona_to_sid=None ):
        """
        Auto-ping each blocker, throttled + per-edge backoff + global cap, then
        clear-on-resume (§6.1). Part-6 #4: DM the blocker AND cc its owning manager.

        Requires:
            - edges is {holder: awaited} (build_graph output — persona→persona;
              `holder` is the BLOCKED worker waiting on `awaited`, the BLOCKER)
            - now is an aware datetime
            - persona_to_sid maps persona → session_id (for the manager cc) or None

        Ensures:
            - pings at most one DM per (holder, awaited) edge per backoff window,
              and never more than ping_global_cap within the cap window
            - the DM goes to the BLOCKER (awaited), naming the blocked worker
              (holder) + the ask (Part-6 #4 rewrite), AND cc's the blocker's owning
              manager (resolved via lineage) when resolvable — so the manager chases
              if the blocker stays silent
            - records each ping in the ledger + attempt counter
            - drops ledger + attempt state for edges no longer active (resume)
            - returns the count of pings fired this poll
        """
        self._prune_recent_pings( now )
        persona_to_sid = persona_to_sid or { }
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
                manager, cc_msg = self._blocker_manager_cc( awaited, holder, persona_to_sid )
                self._route( 4, PING_MESSAGE_TEMPLATE.format( holder=holder ),   # Part-6 #4
                             blocker=awaited, owning_manager=manager, cc_message=cc_msg )
                self._ledger.record_ping( key, now )
                self._ping_attempts[ key ] = attempt + 1
                self._recent_pings.append( now )
                fired += 1

        # clear-on-resume: forget edges no longer present
        self._ledger.clear_resolved( active_keys )
        for stale in [ k for k in self._ping_attempts if k not in active_keys ]:
            del self._ping_attempts[ stale ]
        return fired

    def _blocker_manager_cc( self, blocker, blocked_worker, persona_to_sid ):
        """
        Part-6 #4 helper: resolve the BLOCKER's owning manager + build the cc note
        so the manager chases if the blocker stays silent.

        Ensures:
            - returns (manager_persona, cc_message) when a DM-able owning manager
              (≠ the blocker) resolves from spawn-lineage; else (None, None)
            - never raises (a resolver hiccup degrades to (None, None) → Rick/blocker
              still nudged, just no cc)
        """
        sid = persona_to_sid.get( blocker )
        if not sid:
            return None, None
        try:
            res     = self._resolve_manager_fn( sid, declared_manager=self.manager_recipient )
            manager = res.get( "manager_persona" ) if isinstance( res, dict ) else None
        except Exception:
            manager = None
        if not manager or manager == blocker:
            return None, None
        cc = ( f"Heartbeat arbiter (cc): {blocker} is blocking worker {blocked_worker}. "
               f"I've nudged {blocker} directly — chase if they stay silent." )
        return manager, cc

    def _escalate_deadlocks( self, cycles, active_managers=None ):
        """
        Escalate deadlock cycles — NEVER auto-break (§4). Part-6 #5: Rick + ALL
        active managers (a human/manager breaks the cycle).

        Requires:
            - cycles is a list of canonical peer cycles (build_graph output)
            - active_managers is the resolved on-duty manager set (or None)

        Ensures:
            - fires ONE escalation per poll when any cycle exists — to Rick
              (notify_fn) + each active manager (send_to) — the arbiter surfaces
              deadlocks; a human/manager decides the break
            - no-op when there are no cycles
        """
        if cycles:
            rendered = "; ".join( " → ".join( c ) for c in cycles )
            self._route( 5, f"DEADLOCK detected (no autonomous break) — escalating: {rendered}",
                         active_managers=active_managers )

    def _prune_recent_pings( self, now ):
        """Drop recorded pings older than the global-cap window (rolling cap)."""
        cutoff = self.ping_cap_window_seconds
        self._recent_pings = [
            ts for ts in self._recent_pings
            if ( now - ts ).total_seconds() < cutoff
        ]

    # NOTE (2b-2 Part-6 #6): the per-tick roster broadcast (formerly
    # `_surface_to_manager` → post(ROSTER_TOPIC)) is DROPPED. A roster is PULL
    # state: it is served by /state via `_publish_fleet_snapshot` (the snapshot
    # sink), not spammed to a commons topic nobody polls every ~60s. ROSTER_TOPIC
    # is retained only as the historical topic constant; nothing posts to it now.

    # ── v2.2 B2: active manager-tap (DM-push, per-group, throttled) ─────────────

    def _attention_workers( self, fleet_view, graph ):
        """
        The workers needing a manager's attention: STUCK sessions ∪ holders
        blocked on a peer (the §4 blocked-edge holders).

        Ensures:
            - returns a list of view dicts (stuck OR a blocked-edge holder by
              persona); never raises
        """
        holders = set( graph[ "edges" ].keys() )
        out     = [ ]
        for view in fleet_view.values():
            if not isinstance( view, dict ):
                continue
            if view.get( "stuck" ) or view.get( "persona" ) in holders:
                out.append( view )
        return out

    def _tap_signature( self, members, graph ):
        """
        Hashable signature over a manager-crew's SEMANTIC state (NOT liveness
        ages) — so the tap fires on a real change, not on the clock ticking.
        """
        crew = tuple( sorted(
            ( v.get( "session_id" ), v.get( "persona" ), v.get( "state" ),
              bool( v.get( "stuck" ) ), v.get( "holding_on" ) )
            for v in members
        ) )
        return ( crew, len( graph[ "cycles" ] ) )

    def _should_tap( self, manager, sig, now ):
        """
        Tap iff the crew-summary CHANGED since the last tap AND (first-ever tap OR
        ≥ tap_min_interval_seconds elapsed). NEVER tap on no-change (anti-storm).
        """
        if self._last_tap_sig.get( manager ) == sig:
            return False                              # no change → never tap
        last_at = self._last_tap_at.get( manager )
        if last_at is None:
            return True                               # first tap for this manager
        return ( now - last_at ).total_seconds() >= self.tap_min_interval_seconds

    def _format_manager_tap( self, manager, members, graph, free_n ):
        """
        Build the ADVISORY tap body (D5/§6.3): "I observe … / I recommend …" —
        the manager ACTUATES; the arbiter NEVER assigns. No hardcoded persona.
        """
        stuck   = [ ( v.get( "persona" ) or v.get( "session_id" ) ) for v in members if v.get( "stuck" ) ]
        blocked = [ ( v.get( "persona" ) or v.get( "session_id" ) ) for v in members if not v.get( "stuck" ) ]
        k       = len( graph[ "cycles" ] )
        lines = [
            "Heartbeat arbiter (advisory — I observe + recommend; you actuate).",
            f"I observe: {len( stuck )} stuck/dead · {len( blocked )} blocked · "
            f"{free_n} free fleet-wide · {k} deadlock cycle(s).",
        ]
        if stuck:
            lines.append( "Stuck: " + ", ".join( stuck ) )
        if blocked:
            lines.append( "Blocked: " + ", ".join( blocked ) )
        lines.append(
            "I recommend: pull a free worker to unblock the stuck, or cajole the "
            "blockers. (Recommendation only — I do not assign.)"
        )
        return "\n".join( lines )

    def _tap_managers( self, fleet_view, graph, roster, now, active_managers=None ):
        """
        Actively TAP each manager-on-duty with their crew's actionable ADVISORY
        summary (DM-push), throttled tap-on-change + min-interval (B2 / D1).

        Routing (Part-6 #7/#8): each attention-needing worker → resolve_manager →
        grouped by manager persona (#7, the owning-manager DM); an UNRESOLVED
        manager → ORPHAN worker → escalate to Rick + ALL active managers (#8 — any
        manager could adopt it), never a wrong-manager DM.

        Invariant: this method calls ONLY {send_to} + notify_fn — NO actuation
        (never-auto-assign).

        Ensures:
            - taps a manager only when their crew-summary signature changed since
              the last tap AND ≥ tap_min_interval_seconds elapsed (anti-storm)
            - unresolved-manager (orphan) workers escalate to Rick + all active
              managers
            - returns the count of manager DMs fired this poll; never raises
        """
        attention = self._attention_workers( fleet_view, graph )
        if not attention:
            return 0

        groups = { }                                 # manager_persona -> [view, ...]
        for view in attention:
            res     = self._resolve_manager_fn( view.get( "session_id" ),
                                                declared_manager=self.manager_recipient )
            persona = res.get( "manager_persona" ) if isinstance( res, dict ) else None
            if not persona:
                self._route(                                   # Part-6 #8 orphan worker
                    8,
                    f"Unresolved manager for attention-needing worker "
                    f"{view.get( 'persona' ) or view.get( 'session_id' )} — escalating to "
                    f"Rick + active managers (orphan — any manager could adopt)",
                    active_managers=active_managers
                )
                continue
            groups.setdefault( persona, [ ] ).append( view )

        fired  = 0
        free_n = len( roster )
        for manager, members in groups.items():
            sig = self._tap_signature( members, graph )
            if self._should_tap( manager, sig, now ):
                self._route( 7, self._format_manager_tap( manager, members, graph, free_n ),  # Part-6 #7
                             owning_manager=manager )
                self._last_tap_sig[ manager ] = sig
                self._last_tap_at[ manager ]  = now
                fired += 1
        return fired

    # ── v2.2 B4 / D4: manager-ack tracking → manager-down → escalate + HOLD ─────

    @staticmethod
    def _manager_last_activity( manager, who_rows ):
        """Most-recent commons activity ts for a manager persona (who row), or None."""
        best = None
        for row in who_rows or [ ]:
            if not isinstance( row, dict ) or row.get( "persona_name" ) != manager:
                continue
            raw = row.get( "last_post_ts" )
            try:
                ts = datetime.datetime.fromisoformat( raw ) if raw else None
            except ( TypeError, ValueError ):
                ts = None
            if ts is not None and ( best is None or ts > best ):
                best = ts
        return best

    def _check_manager_acks( self, now, who_rows, active_managers=None ):
        """
        B4/D4 manager-down detector via the liveness-proxy ACK.

        A manager tapped at T is treated as having "acked" (present-to-act) while
        their liveness (commons activity from who()) is fresh AT/AFTER T. If a
        TAPPED manager shows NO activity since the tap AND ≥
        manager_ack_window_seconds have elapsed → MANAGER-DOWN → escalate to Rick
        (notify_fn) + HOLD.

        IMPORTANT (semantics): the liveness-proxy proves ALIVENESS, not
        CONSUMPTION. That's correct for D4, whose trigger IS manager-DOWN —
        staleness detects exactly that. "Alive-but-ignoring-the-tap" is NOT a D4
        case (it's manager judgment, not down). Explicit-ack (proves consumption)
        is a logged V2 item.

        HOLD = escalate-ONLY: this path takes NO actuation (never auto-assign —
        acting-manager succession is V2). Escalates ONCE per un-acked tap (until
        the manager re-acks), not every poll.

        Ensures:
            - returns the count of NEW manager-down escalations this poll
            - clears a manager's down-flag once it shows activity since its tap
            - never raises
        """
        down = 0
        for manager, tapped_at in list( self._last_tap_at.items() ):
            last_activity = self._manager_last_activity( manager, who_rows )
            if last_activity is not None and last_activity >= tapped_at:
                self._manager_down_escalated.discard( manager )   # acked → clear
                continue
            if ( now - tapped_at ).total_seconds() >= self.manager_ack_window_seconds \
               and manager not in self._manager_down_escalated:
                self._manager_down_escalated.add( manager )
                self._route(                                   # Part-6 #9 manager-down
                    9,
                    f"MANAGER-DOWN: {manager} did not ack the arbiter tap within "
                    f"{self.manager_ack_window_seconds}s (no liveness since tap) — "
                    f"escalating to Rick + active managers + HOLDING (no auto-assign)",
                    active_managers=active_managers
                )
                down += 1
        return down

    # ── v2.2 B3: D3 escalation detectors (decision-needed + whole-fleet-stall) ──

    def _check_decision_needed( self, now ):
        """
        D3 trigger: a worker/manager posted a decision the FLEET can't make to the
        reserved `fleet-decision-needed` topic → escalate each NEW one to Rick
        (genuine trigger, NOT a digest).

        READ is pure observation (side-effect-free; never-auto-assign safe). The
        cursor is baselined on the FIRST poll to `now` so a pre-arbiter backlog
        isn't re-escalated; subsequent polls read strictly newer entries.

        Ensures:
            - returns the count of NEW decision-needed posts escalated this poll
            - advances the tail cursor to the latest entry ts seen
            - never raises (a read hiccup is swallowed — observer invariant)
        """
        if self._decision_since is None:
            self._decision_since = now.isoformat()       # baseline: ignore backlog
            return 0
        try:
            entries = self._commons.read( DECISION_TOPIC, since=self._decision_since )
        except Exception:
            return 0
        fired = 0
        for entry in entries or [ ]:
            if not isinstance( entry, dict ):
                continue
            ts      = entry.get( "ts" )
            body    = entry.get( "body", "" )
            who     = entry.get( "persona_name" ) or entry.get( "sender_session_id" ) or "a session"
            self._route( 10, f"DECISION-NEEDED (escalating to Rick) — {who}: {body}" )    # Part-6 #10 Rick
            self._cc_decision_manager( entry )                                           # +owning mgr if known
            fired += 1
            if ts and ( self._decision_since is None or ts > self._decision_since ):
                self._decision_since = ts
        return fired

    def _cc_decision_manager( self, entry ):
        """
        Part-6 #10: cc the owning manager of a decision-needed post WHEN KNOWN.

        Decisions are Rick-primary; the owning manager is looped in only if the
        post carries a `sender_session_id` that resolves (via lineage) to a DM-able
        manager. No session / no resolution → Rick-only (no-op). Calls ONLY
        send_to (redline-safe).

        Ensures:
            - send_to( manager, cc-note ) exactly when a DM-able owning manager
              resolves from the post's sender; else no-op; never raises
        """
        sid = entry.get( "sender_session_id" )
        if not sid:
            return
        try:
            res     = self._resolve_manager_fn( sid, declared_manager=None )
            manager = res.get( "manager_persona" ) if isinstance( res, dict ) else None
        except Exception:
            manager = None
        if manager:
            cc_body = ( f"Heartbeat arbiter (cc): your crew posted a decision-needed — "
                        f"{entry.get( 'body', '' )}. Rick has it; weigh in if it's yours." )
            self._commons.send_to( manager, cc_body )
            self._log_outreach( "decision_cc", "send_to", [ manager ], cc_body, persona=manager )

    @staticmethod
    def _fleet_progress_signature( fleet_view ):
        """
        A hashable signature over the fleet's SEMANTIC progress (per-session
        state / stuck / holding) — NOT liveness ages. When ANY session's semantic
        state advances, the signature changes ⇒ progress. Used by the stall
        detector (state≠liveness: stall keys on progress, never on liveness).
        """
        return tuple( sorted(
            ( v.get( "session_id" ), v.get( "state" ), bool( v.get( "stuck" ) ), v.get( "holding_on" ) )
            for v in fleet_view.values() if isinstance( v, dict )
        ) )

    @staticmethod
    def _has_live_owed_work( fleet_view ):
        """
        Calibration GATE (2b-1): is there ≥1 session that is BOTH alive AND owes
        work? — the liveness precondition the whole-fleet-stall trigger evaluates.

        The documented false-fire (Part 3 / Part 7) was a roster of DEAD/offline
        sessions — frozen owed-work `state`, no live bridge, every `alive` False —
        reading as "no progress" → escalate. The old trigger keyed on owed-work
        ALONE (it never consulted `alive`), so a dead roster tripped it. Requiring
        a LIVE owed-work session means a dead/empty roster can NEVER stall-escalate.

        Liveness here is the Round-1 union signal (`alive` = bridge ∪ commons ∪
        idle_prompt ∪ stop-event recency, set by build_fleet_view) — NOT a
        re-derivation. It gates EVALUATION only; PROGRESS itself stays keyed on
        work-advancement (the semantic signature), so a chatty-but-stuck LIVE
        fleet — alive sessions posting "still blocked" while nothing advances —
        is a REAL stall and STILL fires (commons chatter is liveness, not
        progress; it never reaches the signature).

        Ensures:
            - returns True iff some view is alive is True AND state ∈
              {working, stuck, holding}; never raises
        """
        return any(
            isinstance( v, dict ) and v.get( "alive" ) is True
            and v.get( "state" ) in ( "working", "stuck", "holding" )
            for v in fleet_view.values()
        )

    def _check_fleet_stall( self, fleet_view, now, active_managers=None ):
        """
        D3 catch-all: no FLEET PROGRESS for ≥ fleet_stall_window_seconds while
        LIVE work is owed → escalate to Rick + ALL active managers (Part-6 #11).

        LOAD-BEARING (María): PROGRESS keys on the semantic signature (state /
        stuck / holding), NOT on liveness — so it FIRES EVEN WHEN A MANAGER'S
        BRIDGE-MTIME IS FRESH. That catches the "manager alive-but-IGNORING the
        tap" failure mode, OUTSIDE D4's manager-DOWN scope. The two triggers
        compose: D4 = manager GONE; D3-stall = manager PRESENT-but-not-acting.
        Escalate-only (no actuation; never auto-assign).

        CALIBRATION (2b-1, Tiberius's framing): liveness GATES whether to evaluate
        a stall at all — `_has_live_owed_work` requires the owed work to sit on a
        session the Round-1 union marks ALIVE. A dead/offline roster (the Part-3
        false-fire) no longer escalates; a chatty-but-stuck LIVE fleet still does
        (progress ≠ aliveness). The progress SIGNATURE is deliberately UNCHANGED —
        commons chatter must never read as work-advancement (else the arbiter's own
        per-poll posts, which surface in who(), would mask every stall).

        Ensures:
            - resets the stall timer whenever the progress signature changes
            - escalates ONCE per stall episode when the signature is unchanged for
              ≥ the window AND a LIVE session owes work; re-arms on the next
              progress
            - a dead/offline roster (no LIVE owed work) never escalates
            - returns 1 on a new escalation else 0; never raises
        """
        sig = self._fleet_progress_signature( fleet_view )
        if sig != self._last_progress_sig:
            self._last_progress_sig = sig
            self._last_progress_at  = now
            self._stall_escalated   = False
            return 0
        has_owed = self._has_live_owed_work( fleet_view )
        if ( has_owed and self._last_progress_at is not None
             and ( now - self._last_progress_at ).total_seconds() >= self.fleet_stall_window_seconds
             and not self._stall_escalated ):
            self._stall_escalated = True
            self._route(                                   # Part-6 #11 Rick + all mgrs
                11,
                f"WHOLE-FLEET-STALL: no fleet progress for ≥{self.fleet_stall_window_seconds}s "
                f"with work owed — escalating to Rick (manager present-but-not-acting?)",
                active_managers=active_managers
            )
            return 1
        return 0

    # ── 2b-3: bounded, non-destructive auto-poke + reap-recommendation ──────────

    @staticmethod
    def _pokeable_sessions( fleet_view ):
        """
        The genuinely-stuck LIVE sessions eligible for an auto-poke this poll.

        POKEABLE iff BOTH (STALL≠QUIET, María's doctrine + the 2b-1 calibration):
          • `alive is True`  — the Round-1 union liveness (the SAME gate the stall
            detector uses); a dead/offline session is NEVER poked (poking a corpse
            is waste), AND
          • `stuck is True`  — repeated cap_reached + work owed = "owed work + NO
            progress". A busy/working, declared-holding, or idle session is NOT
            stuck → NOT poked (quiet ≠ stall; don't poke a heads-down live worker).

        Ensures:
            - returns { session_id: view } for each LIVE+stuck session; never raises
        """
        return {
            v[ "session_id" ]: v
            for v in fleet_view.values()
            if isinstance( v, dict ) and v.get( "session_id" )
            and v.get( "alive" ) is True and v.get( "stuck" ) is True
        }

    def _format_poke( self, view ):
        """The non-destructive wake-nudge body sent to a stuck LIVE session."""
        who = view.get( "persona" ) or view.get( "session_id" )
        return (
            f"Heartbeat arbiter (auto-poke): {who}, you appear STUCK — repeated "
            f"cap-reached with work owed and no progress. Are you blocked or wedged? "
            f"Post your status, ask for help, or resume. (Non-destructive nudge.)"
        )

    def _format_reap_recommendation( self, view, pokes ):
        """The reap-RECOMMENDATION body — a recommendation to a HUMAN/manager; the
        arbiter NEVER executes the reap (redline)."""
        who = view.get( "persona" ) or view.get( "session_id" )
        return (
            f"REAP-RECOMMENDATION (advisory — I recommend, you decide; I do NOT reap): "
            f"session {who} stayed STUCK through {pokes} bounded auto-poke(s) with no "
            f"recovery. Recommend a human/manager reap-and-replace it. The arbiter "
            f"takes NO destructive action."
        )

    def _auto_poke( self, fleet_view, now, active_managers ):
        """
        2b-3 auto-poke: fire a BOUNDED, TARGETED, NON-DESTRUCTIVE wake-nudge at each
        genuinely-stuck LIVE session; after ≤N pokes with no recovery, emit ONE
        reap-RECOMMENDATION (to Rick + active managers) and fall silent. The arbiter
        NEVER reaps — the redline holds (this method calls ONLY send_to + _route,
        both non-destructive; the structural redline test enforces it).

        Anti-storm (FM-20): the cap + escalated-flag PERSIST per STALL-EPISODE
        (state on self, keyed by session_id), NOT per-poll. A persistently-stuck
        session therefore gets ≤ poke_max_per_episode pokes TOTAL → ONE
        reap-recommendation → silence — never a per-tick re-poke storm. When a
        session leaves the pokeable set (recovered / died / no longer stuck) its
        episode ENDS: state is cleared and the cap re-arms for any future episode.

        Threshold: a session must be continuously LIVE+stuck for ≥
        poke_stall_threshold_seconds (observed by the arbiter) before its FIRST
        poke — a brief stick that self-resolves is never poked.

        Ensures:
            - no-op when auto_poke_enabled is False (the make-before-break flag)
            - pokes ≤ poke_max_per_episode times per session per episode, then
              escalates exactly once, then silent
            - returns the count of pokes fired this poll; never raises
        """
        if not self.auto_poke_enabled:
            return 0

        pokeable = self._pokeable_sessions( fleet_view )

        # episode bookkeeping: a session no longer pokeable ended its episode →
        # clear its state so the cap re-arms (clear-on-resume, mirrors _auto_ping).
        for sid in [ s for s in self._poke_stuck_since if s not in pokeable ]:
            del self._poke_stuck_since[ sid ]
            self._poke_count.pop( sid, None )
            self._poke_escalated.discard( sid )

        fired = 0
        for sid, view in pokeable.items():
            if sid not in self._poke_stuck_since:
                self._poke_stuck_since[ sid ] = now               # episode start (no poke yet)
                self._poke_count[ sid ]       = 0
            if ( now - self._poke_stuck_since[ sid ] ).total_seconds() < self.poke_stall_threshold_seconds:
                continue                                          # not stuck long enough yet
            if self._poke_count[ sid ] < self.poke_max_per_episode:
                recipient = view.get( "persona" ) or sid
                body      = self._format_poke( view )
                self._commons.send_to( recipient, body )
                self._log_outreach( "poke", "send_to", [ recipient ], body,    # post-game F1
                                    session_id=sid, persona=view.get( "persona" ) )
                self._poke_count[ sid ] += 1
                fired += 1
            elif sid not in self._poke_escalated:
                self._poke_escalated.add( sid )
                self._route( CASE_AUTO_POKE_REAP_REC,             # → Rick + active managers
                             self._format_reap_recommendation( view, self._poke_count[ sid ] ),
                             active_managers=active_managers )
            # else: capped AND already escalated → silence (anti-storm)
        return fired

    # ── post-game F2: manager-staleness poke tier (2026-06-11) ──────────────────

    def _format_manager_stale_poke( self, row, age ):
        """The bounded, non-destructive staleness nudge sent to a dark MANAGER session."""
        who = row.get( "persona" ) or row.get( "session_id" )
        return (
            f"Heartbeat arbiter (manager-staleness poke): {who}, no signal from your "
            f"session for {_fmt_minutes( age )} (threshold "
            f"{self.manager_stale_poke_threshold_seconds}s). Are you wedged or idle-dark? "
            f"Post your status or resume. Rick has been advised. (Non-destructive nudge.)"
        )

    def _check_manager_staleness( self, snapshot, now, active_managers ):
        """
        F2: the SECOND, role-gated pokeable criterion — a MANAGER-role session
        whose freshest union signal is older than the threshold gets a bounded
        poke AND a Rick advisory, even with ZERO stuck workers (the 2026-06-10
        gap: stale 27m/34m/30m+ manager verdicts produced no outreach because the
        stuck-tier requires alive∧stuck and taps require attention workers).

        Workers are UNTOUCHED — the gate is role == "manager" (manager-manifest
        via the injected list_managers_fn, surfaced on the snapshot row), so
        María's quiet≠stall doctrine for heads-down workers is preserved intact.

        The Rick advisory (case 14, Rick + active managers) fires on the FIRST
        threshold crossing — the SAME poll as poke #1, NOT after poke exhaustion:
        pokes at a dark session are best-effort (it may have no self-wake); the
        advisory is the load-bearing output. Pokes continue bounded
        (≤ poke_max_per_episode); episode state clears when the manager freshens
        below the threshold (or leaves the roster) → cap + advisory re-arm.

        Requires:
            - snapshot is the FULL (include_offline=True) detection snapshot
            - now is an aware datetime; active_managers a list or None

        Ensures:
            - no-op (returns 0) when the threshold is 0 (tier disabled)
            - a row is eligible iff role == "manager" AND (freshest_age_s is None
              OR >= threshold) — None = no signal at all = maximally stale; an
              offline-verdict manager STAYS eligible (offline is maximal
              staleness, not an exit)
            - ≤ poke_max_per_episode pokes + exactly ONE advisory per episode
            - returns the count of staleness pokes fired this poll; never raises
        """
        if self.manager_stale_poke_threshold_seconds <= 0:
            return 0

        eligible = { }
        for row in ( snapshot or { } ).get( "sessions", [ ] ):
            if not isinstance( row, dict ) or row.get( "role" ) != "manager":
                continue
            sid = row.get( "session_id" )
            if not sid:
                continue
            liveness = row.get( "liveness" )
            age      = liveness.get( "freshest_age_s" ) if isinstance( liveness, dict ) else None
            if age is None or age >= self.manager_stale_poke_threshold_seconds:
                eligible[ sid ] = ( row, age )

        # episode end: a manager freshened (or left the roster) → clear state so
        # the cap + advisory re-arm for any future episode (mirrors _auto_poke).
        for sid in [ s for s in self._mgr_stale_since if s not in eligible ]:
            del self._mgr_stale_since[ sid ]
            self._mgr_poke_count.pop( sid, None )
            self._mgr_advised.discard( sid )

        fired = 0
        for sid, ( row, age ) in eligible.items():
            persona = row.get( "persona" ) or sid
            if sid not in self._mgr_stale_since:
                self._mgr_stale_since[ sid ] = now                # episode start
                self._mgr_poke_count[ sid ]  = 0
            if sid not in self._mgr_advised:                      # Rick advisory: FIRST crossing, same poll as poke #1
                self._mgr_advised.add( sid )
                last_seen = now - datetime.timedelta( seconds=age ) if age is not None else None
                self._route(
                    CASE_MANAGER_STALE_ADVISORY,
                    f"MANAGER-STALE: {persona} silent {_fmt_minutes( age )} "
                    f"(last signal {_fmt_eastern( last_seen )}, threshold "
                    f"{self.manager_stale_poke_threshold_seconds}s) — poking (bounded, "
                    f"≤{self.poke_max_per_episode}/episode); outreach only, no action taken.",
                    active_managers=active_managers,
                )
            if self._mgr_poke_count[ sid ] < self.poke_max_per_episode:
                body = self._format_manager_stale_poke( row, age )
                self._commons.send_to( persona, body )
                self._log_outreach( "manager_stale_poke", "send_to", [ persona ], body,
                                    session_id=sid, persona=persona )
                self._mgr_poke_count[ sid ] += 1
                fired += 1
            # else: poke-capped — the advisory already fired; silence (anti-storm)
        return fired

    # ── post-game F3: fleet-dark advisory (hybrid trigger, 2026-06-11) ──────────

    def _check_fleet_dark( self, snapshot, published_count, now ):
        """
        F3: the published roster decayed to ZERO → ONE Rick advisory per dark
        episode (case 15, Rick-only — no managers remain by definition). The
        2026-06-10 failure: 4→3→2→1→0 then 6+ hours of "no changes · 0 session(s)"
        ticks with zero outreach — full-fleet death was silence BY DESIGN
        (_has_live_owed_work requires live owed work; a dead/empty roster can
        never stall-escalate).

        HYBRID trigger (Tiberius review NIT-1): a pure >0→0 edge loses its state
        on a service restart (LocalSnapshotStore is in-memory — it dies with the
        process). So:
          - PRIMARY (edge): previous published count > 0 and current == 0.
          - RECOVERY (state; evaluated only while NO nonzero roster has been seen
            this process — i.e. a boot/recycle straight into darkness): fire iff
            some session in the FULL snapshot still shows a signal younger than
            DARK_LOOKBACK_SECONDS ("the fleet JUST died" leaves recent corpses).
            A cold morning boot over a roster reaped the previous evening has no
            signal that fresh → silent (no daily page).

        Ensures:
            - tracks the freshest MANAGER signal ever observed (persona + wall
              time) for the advisory body, EDT-labeled
            - fires at most once per dark episode (flag re-arms on count > 0);
              a mid-dark restart re-fires at most once per process
            - returns 1 on a new advisory else 0; never raises
        """
        rows = ( snapshot or { } ).get( "sessions", [ ] )
        # harvest the freshest manager signal observed (for the advisory body)
        for row in rows:
            if not isinstance( row, dict ) or row.get( "role" ) != "manager":
                continue
            liveness = row.get( "liveness" )
            age      = liveness.get( "freshest_age_s" ) if isinstance( liveness, dict ) else None
            if age is None:
                continue
            at = now - datetime.timedelta( seconds=age )
            if self._last_manager_seen is None or at > self._last_manager_seen[ "at" ]:
                self._last_manager_seen = { "persona": row.get( "persona" ) or row.get( "session_id" ),
                                            "at"     : at }

        prev = self._published_count_prev
        self._published_count_prev = published_count

        if published_count > 0:
            self._saw_nonzero_roster   = True
            self._fleet_dark_escalated = False                    # re-arm for the next dark episode
            return 0
        if self._fleet_dark_escalated:
            return 0

        edge     = prev is not None and prev > 0
        recovery = ( not self._saw_nonzero_roster ) and any(
            isinstance( r, dict ) and isinstance( r.get( "liveness" ), dict )
            and r[ "liveness" ].get( "freshest_age_s" ) is not None
            and r[ "liveness" ][ "freshest_age_s" ] <= DARK_LOOKBACK_SECONDS
            for r in rows
        )
        if not ( edge or recovery ):
            return 0

        self._fleet_dark_escalated = True
        seen  = self._last_manager_seen
        last  = f"{seen[ 'persona' ]} at {_fmt_eastern( seen[ 'at' ] )}" if seen else "unknown"
        decay = f"{prev}→0" if edge else "0 at startup (recent signals within lookback)"
        self._route(
            CASE_FLEET_DARK,
            f"FLEET-DARK: published roster {decay}; last manager signal {last}. "
            f"The arbiter keeps watching; this fires once per dark episode.",
        )
        return 1

    # ── post-game F1: why-not-poked gate evaluation (2026-06-11) ────────────────

    def _stuck_gate_why_not( self, sid, view, now ):
        """
        The stuck-tier gate vector for one session: which precondition blocks a
        wake-nudge THIS poll. Runs after _auto_poke, so episode state is current.

        Ensures:
            - returns [] iff a stuck-tier poke would fire; else the failed
              preconditions in evaluation order, from
              { disabled, not_alive, not_stuck, below_threshold, capped,
                already_escalated }; never raises
        """
        why = [ ]
        if not self.auto_poke_enabled:
            why.append( "disabled" )
        if not isinstance( view, dict ) or view.get( "alive" ) is not True:
            why.append( "not_alive" )
        if not isinstance( view, dict ) or view.get( "stuck" ) is not True:
            why.append( "not_stuck" )
        if why:
            return why
        since = self._poke_stuck_since.get( sid )
        if since is not None and ( now - since ).total_seconds() < self.poke_stall_threshold_seconds:
            return [ "below_threshold" ]
        if self._poke_count.get( sid, 0 ) >= self.poke_max_per_episode:
            return [ "already_escalated" ] if sid in self._poke_escalated else [ "capped" ]
        return [ ]

    def _stale_gate_why_not( self, sid, row ):
        """
        The manager-staleness-tier gate vector for one session (off its FULL-
        snapshot row, which carries role + freshest_age_s).

        Ensures:
            - returns [] iff a staleness poke would fire; else the failed
              preconditions from { tier_disabled, not_manager, not_stale,
                mgr_capped }; never raises
        """
        why = [ ]
        if self.manager_stale_poke_threshold_seconds <= 0:
            why.append( "tier_disabled" )
        if not isinstance( row, dict ) or row.get( "role" ) != "manager":
            why.append( "not_manager" )
        if why:
            return why
        liveness = row.get( "liveness" )
        age      = liveness.get( "freshest_age_s" ) if isinstance( liveness, dict ) else None
        if age is not None and age < self.manager_stale_poke_threshold_seconds:
            return [ "not_stale" ]
        if self._mgr_poke_count.get( sid, 0 ) >= self.poke_max_per_episode:
            return [ "mgr_capped" ]
        return [ ]

    def _emit_poke_gates( self, fleet_view, snapshot, now ):
        """
        F1 gate-evaluation visibility: journal WHY each session was (not) poked,
        on CHANGE of its gate vector + a full dump every GATE_DUMP_INTERVAL_POLLS
        polls — so an outreach silence is always diagnosable ("evaluated and
        correctly declined" vs "never evaluated" vs "fired and delivery failed").

        Ensures:
            - emits `arbiter_poke_gate` per session whose (stuck_why, stale_why)
              signature changed since its last emission, or unconditionally on a
              dump poll (poll 0 = the baseline dump)
            - a session leaving the fleet view emits ONE { evicted: True } event
              and drops its signature
            - never raises (the _log seam swallows)
        """
        rows_by_sid = {
            r.get( "session_id" ): r
            for r in ( snapshot or { } ).get( "sessions", [ ] )
            if isinstance( r, dict ) and r.get( "session_id" )
        }
        dump    = ( self._poll_count % GATE_DUMP_INTERVAL_POLLS == 0 )
        current = set()
        for sid, view in ( fleet_view or { } ).items():
            if not isinstance( view, dict ):
                continue
            current.add( sid )
            row       = rows_by_sid.get( sid, { } )
            stuck_why = self._stuck_gate_why_not( sid, view, now )
            stale_why = self._stale_gate_why_not( sid, row )
            sig       = ( tuple( stuck_why ), tuple( stale_why ) )
            if dump or self._gate_state.get( sid ) != sig:
                self._gate_state[ sid ] = sig
                self._log(
                    "arbiter_poke_gate",
                    session_id       = sid,
                    persona          = view.get( "persona" ),
                    role             = row.get( "role", "worker" ),
                    stuck_pokeable   = not stuck_why,
                    stuck_why_not    = stuck_why,
                    stale_pokeable   = not stale_why,
                    stale_why_not    = stale_why,
                    stuck_poke_count = self._poke_count.get( sid, 0 ),
                    mgr_poke_count   = self._mgr_poke_count.get( sid, 0 ),
                )
        for sid in [ s for s in self._gate_state if s not in current ]:
            del self._gate_state[ sid ]
            self._log( "arbiter_poke_gate", session_id=sid, evicted=True )

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def _execute( self ):
        """
        Poll loop: poll → sleep, until cancel or hard-cap.

        Ensures:
            - exits on self._cancel_requested or elapsed >= max_duration_seconds
            - a per-poll exception is SWALLOWED (the observer invariant — one bad
              poll never kills the arbiter) and DEMOTED to a render-sink log
              (Part-6 #12); it escalates to Rick (notify_fn) ONLY when PERSISTENT
              (≥ poll_error_escalate_threshold consecutive failures), once per run;
              a clean poll resets the streak
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
                self._poll_error_streak    = 0          # clean poll → reset the streak
                self._poll_error_escalated = False
            except Exception as e:                      # observer invariant — never die on one poll
                self._on_poll_error( e )

            await self._clock.sleep( self.poll_seconds )

    def _on_poll_error( self, error ):
        """
        Part-6 #12: handle a swallowed per-poll exception — LOG (transient), escalate
        to Rick ONLY when PERSISTENT.

        Ensures:
            - increments the consecutive-error streak
            - at/after poll_error_escalate_threshold consecutive failures, escalates
              ONCE to Rick (notify_fn — "arbiter effectively down"); below it, logs a
              transient line to the render sink (no Rick spam on a one-off hiccup)
            - never raises
        """
        self._poll_error_streak += 1
        if ( self._poll_error_streak >= self.poll_error_escalate_threshold
             and not self._poll_error_escalated ):
            self._poll_error_escalated = True
            body = ( f"ARBITER POLL-ERROR persistent: {self._poll_error_streak} consecutive poll "
                     f"failures (≥{self.poll_error_escalate_threshold}) — escalating to Rick "
                     f"(arbiter effectively down): {error}" )
            self._notify_fn( body )
            self._log_outreach( "poll_error_escalation", "notify", [ "rick" ], body )   # post-game F1
        else:
            self._render_sink(
                f"arbiter poll-error (transient, streak {self._poll_error_streak}/"
                f"{self.poll_error_escalate_threshold}): {error}"
            )

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
