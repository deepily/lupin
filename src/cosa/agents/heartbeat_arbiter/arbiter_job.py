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
import uuid
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
from cosa.agents.heartbeat_arbiter.arbiter_journal import make_log_fn, DELIVERED_OUTCOMES
# Item B (§3.4/§3.5): the dm-topic slug (receipt polling reads the SAME board the
# durable send_to wrote to) + the restart-surviving Rick re-announce ledger.
from cosa.agents.heartbeat_arbiter.arbiter_gateway import LupinArbiterGateway
from cosa.agents.heartbeat_arbiter.outreach_ledger import (
    add_pending, read_pending, record_attempt, remove_pending,
)
# F-A (2026.06.11 lineage-persistence design): the restart-surviving carry file.
from cosa.agents.heartbeat_arbiter.lineage_carry import read_carry, write_carry
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
    CASE_MANAGER_AWAITING_USER, CASE_MANAGER_DONE_ADVISORY,
)
from lupin_mcp.persona_normalization import canonical_persona_key


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

# F1: routed-case → log `kind` vocabulary (the direct-send kinds — stuck_poke,
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
    CASE_MANAGER_AWAITING_USER  : "manager_awaiting_user",   # L1 (2026-06-17)
    CASE_MANAGER_DONE_ADVISORY  : "manager_done_advisory",   # L1 (2026-06-17)
}

# ── L1 store-classification constants (2026-06-17, arbiter detector gaps) ────
# Each tapped/owed-candidate manager is classified ONCE per poll from a
# swallow-safe store read (the injected owed_work_fn). The class drives whether
# the false-escalating detectors (D4 MANAGER-DOWN, D3 WHOLE-FLEET-STALL) suppress.
CLASS_BLOCKED_ON_USER = "blocked_on_user"   # every non-terminal owed item is Rick-gated → not down, not a stall
CLASS_DONE            = "done"              # zero non-terminal owed items → consider-reaping, not down
CLASS_ACTIVE          = "active"           # has ≥1 normal (non-Rick-gated) owed item → today's behavior
CLASS_UNKNOWN         = "unknown"          # store read failed / seam unwired → FAIL SAFE (today's behavior)

# The owed-classes that SUPPRESS a blocking escalation (lane 4, 2026-06-17): a
# session is "not owed" — not a stall, not down — iff its owed work is entirely
# Rick-gated (BLOCKED_ON_USER) or zero (DONE). ACTIVE / UNKNOWN never suppress
# (UNKNOWN is fail-SAFE: never silently swallow a real escalation).
NOT_OWED_CLASSES = ( CLASS_BLOCKED_ON_USER, CLASS_DONE )


def owed_class_suppresses( cls ):
    """
    The shared store-owed SUPPRESSION PREDICATE (lane 4, 2026-06-17).

    The single, named home for "does this owed-work classification mean DO-NOT-
    escalate?" — extracted so it is NOT re-inlined per caller. Consumed by the
    arbiter's three false-escalating detectors (#9 MANAGER-DOWN acks, #11
    WHOLE-FLEET-STALL, #F2 MANAGER-STALENESS) AND, once this unit lands, by Mr
    Radio's engagement-#7 follow-through-accountability watcher (its §4.5 "read
    the worker's declared not-owed state BEFORE firing a blocking-escalation").
    Reusing this one predicate keeps #7 from duplicating the decision and from
    contending over the poke path.

    Requires:
        - cls is a CLASS_* string (or any value; non-members → False)

    Ensures:
        - returns True iff cls in {CLASS_BLOCKED_ON_USER, CLASS_DONE}
        - ACTIVE / UNKNOWN / anything else → False (fail-SAFE); never raises
    """
    return cls in NOT_OWED_CLASSES


def _default_owed_work_fn( personas ):   # pragma: no cover - production store-read IO boundary
    """
    Default owed-work store reader — the arbiter is reader #2 of the
    one-store/three-readers design (see
    src/docs/fleet-liveness-and-task-store-architecture.md).

    Given the personas under evaluation this poll, return
    { persona: [ { id, status, gate_class, blocked_by }, ... ] } of each
    persona's NON-TERMINAL owed items (status not in {done, dropped}). ONE DB
    session per poll. Exercised at the :8000 integration tier like
    LupinArbiterGateway.from_environment; the classification LOGIC that consumes
    this dict is fully unit-tested via an injected fake (so this IO boundary is
    no-cover, mirroring build_arbiter_job).

    Requires:
        - personas is an iterable of persona-name strings

    Ensures:
        - returns the per-persona non-terminal owed-item dict (a persona with no
          owed work maps to an empty list)
        - raising is acceptable here — the caller (_classify_owed) swallows any
          exception into the fail-SAFE UNKNOWN path (observer invariant)
    """
    from cosa.rest.db.database import get_db
    from cosa.rest.db.repositories.task_repository import TaskRepository
    _TERMINAL = ( "done", "dropped" )
    out = { }
    with get_db() as session:
        repo = TaskRepository( session )
        for persona in personas:
            # Identity parity (Phase 2): this is a DIRECT repo query that bypasses
            # the /api/tasks router choke point, so it must canonicalize the
            # owner_persona itself — querying "María"/"Mr. Radio" raw matched ZERO
            # of the store's "maria"/"mr radio" rows (the 2026-06-18 false-idle).
            # The OUTPUT key stays the original `persona` so the caller's
            # roster-keyed lookups are unchanged.
            items = repo.query_tasks( owner_persona=canonical_persona_key( persona ) or persona )
            out[ persona ] = [
                { "id"         : str( it.id ),
                  "status"     : it.status,
                  "gate_class" : it.gate_class,
                  "blocked_by" : it.blocked_by }
                for it in items if it.status not in _TERMINAL
            ]
    return out


# DM-as-liveness window (2026-06-17): bound the SENT-DM scan to the verdict's
# stale ceiling — a DM older than this ages to "offline" anyway, so a 1h lookback
# is the natural, index-cheap bound (mirrors fleet_render.DEFAULT_STALE_SECONDS).
_DM_ACTIVITY_LOOKBACK_SECONDS = 3600


def _default_dm_activity_fn():   # pragma: no cover - production store-read IO boundary
    """
    Default SENT-DM activity reader — the DM-as-liveness store source (design §2).

    Returns { session_id: max(created_at) } over SENT ai_to_ai DM rows in the
    last ~1h. The session_id is parsed from the DM sender_id's '#'-suffix
    (build_sender_id format '<agent>@<project>.deepily.ai#<session_id>'); rows
    with no suffix are skipped (cannot be attributed to a session). SENT-only:
    the sender doing dm_send is the genuine sign of life — a dormant recipient
    does NOT wake on an inbound DM (reference_dm_send_does_not_wake_parked_workers),
    so RECEIVED-DM liveness over-reports (design §2; SENT∪RECEIVED kept as a
    future opt-in).

    The bounded scan filters direction='ai_to_ai' AND created_at >= since (the
    created_at index keeps it cheap). Exercised at the :8000 integration tier
    like _default_owed_work_fn / LupinArbiterGateway.from_environment; the
    GROUPING + freshest-age LOGIC that consumes this map is fully unit-tested via
    an injected fake, so this IO boundary is no-cover.

    NOTE (design §7 Q3, Tiberius): the exact group-by lives inline here for now
    (queries the model directly, no NotificationRepository edit) — if Tiberius
    prefers a named NotificationRepository method, this body moves there
    verbatim; the seam contract (no-arg → { session_id: ts }) is unchanged.

    Ensures:
        - returns { session_id: aware-datetime } of the latest SENT-DM per session
        - raising is acceptable — the caller swallows any exception into an inert
          empty map (observer invariant); the other 4 signals carry liveness
    """
    from cosa.rest.db.database import get_db
    from cosa.rest.postgres_models import Notification
    since = datetime.datetime.now( datetime.timezone.utc ) - datetime.timedelta( seconds=_DM_ACTIVITY_LOOKBACK_SECONDS )
    out   = { }
    with get_db() as session:
        rows = (
            session.query( Notification.sender_id, Notification.created_at )
            .filter( Notification.direction == "ai_to_ai",
                     Notification.created_at >= since )
            .all()
        )
    for sender_id, created_at in rows:
        if not sender_id or "#" not in sender_id or created_at is None:
            continue
        session_id = sender_id.split( "#", 1 )[ 1 ]
        if not session_id:
            continue
        prior = out.get( session_id )
        if prior is None or created_at > prior:
            out[ session_id ] = created_at
    return out


# Item A (2026.06.11 receipts design §2.3): the F1 default log seam now delegates
# to arbiter_journal.make_log_fn — the ONE owner of the line shape (ts + ts_local).
# In-pool arbiter events keep the historical "heartbeat-arbiter" service tag; the
# :8001 factory injects the app's own per-loop log_fn instead.
_default_log_fn = make_log_fn( service="heartbeat-arbiter" )


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
    def send_to( self, recipient: str, body: str, metadata: Optional[ dict ] = None ) -> None: ...
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
        declared_managers        : Optional[ list ] = None,
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
        manager_stale_poke_max_age_seconds : int        = 7200,   # corpse ceiling (~2h; must be > threshold)
        # Item B (2026.06.11 receipts design): the delivery-receipt seams. All
        # default None/inert so legacy in-pool construction is unchanged; the
        # :8001 factory wires the real hops.
        dm_push_fn               : Optional[ Callable ] = None,   # §3.3 manager wake hop (persona, thread_id, body) -> outcome
        tmux_push_fn             : Optional[ Callable ] = None,   # Thread C+D wake hop: host-side tmux inject (session_id, thread_id, body) -> outcome
        poke_wake_mechanism      : str                  = "tmux", # Thread C+D: "tmux" (direct host-side inject; wakes a dormant pane) | "dm" (dm/send only; buffered for a non-idle pane)
        live_retry_fn            : Optional[ Callable ] = None,   # §3.5 dedup-BYPASSING live transport for re-announce
        outreach_ack_window_seconds : int               = 900,    # §3.4 manager threaded-ack window
        reannounce_interval_seconds : int               = 300,    # §3.5 Rick re-announce cadence
        reannounce_ttl_seconds   : int                  = 86400,  # §3.5 re-announce give-up horizon
        pending_ledger_path      : Optional[ str ]      = None,   # §3.5 file-backed ledger (None → re-announce inert)
        lineage_carry_path       : Optional[ str ]      = None,   # F-A lineage-carry file (None → volatile, pre-fix behavior)
        clock                    : Optional[ Clock ]    = None,
        notify_fn                : Optional[ Callable ] = None,
        bridge_mtime_fn          : Optional[ Callable ] = None,
        owed_work_fn             : Optional[ Callable ] = None,   # L1: per-poll store read (None → inert; classify UNKNOWN → fail-safe)
        count_dm_as_liveness_fn  : Optional[ Callable ] = None,   # DM-toggle: per-poll INI re-read (None → lambda True; runtime-tunable)
        dm_activity_fn           : Optional[ Callable ] = None,   # DM-toggle: per-poll SENT-DM store read (None → inert; dm_ts None everywhere)
        bridge_discovery_fn      : Optional[ Callable ] = None,
        snapshot_sink            : Optional[ Callable ] = None,
        render_sink              : Optional[ Callable ] = None,
        resolve_manager_fn       : Optional[ Callable ] = None,
        resolve_active_managers_fn : Optional[ Callable ] = None,
        list_managers_fn         : Optional[ Callable ] = None,
        follow_through_watcher_factory : Optional[ Callable ] = None,   # eng#7: (job) -> watcher | None (chicken-egg resolver; None → inert)
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
        # corpse ceiling (2026-06-11): F2 means "this manager went dark RECENTLY",
        # not "a corpse exists" — the eligibility window is [threshold, max_age].
        # A ceiling at or below the threshold makes that window EMPTY and silently
        # config-deads the tier — fail fast, same bug-class guard as quiet < alive
        # above. Only enforced while the tier is enabled (threshold > 0).
        if manager_stale_poke_threshold_seconds > 0 and \
           manager_stale_poke_max_age_seconds <= manager_stale_poke_threshold_seconds:
            raise ValueError(
                f"manager_stale_poke_max_age_seconds ({manager_stale_poke_max_age_seconds}) "
                f"must be > manager_stale_poke_threshold_seconds "
                f"({manager_stale_poke_threshold_seconds}) — else the staleness "
                f"eligibility window is empty and the tier is config-dead"
            )
        # Item B: a zero/negative receipt knob silently config-deads its loop-closure
        # tier — same fail-fast bug-class guard as quiet < alive above.
        if outreach_ack_window_seconds <= 0:
            raise ValueError( f"outreach_ack_window_seconds must be positive, got {outreach_ack_window_seconds}" )
        if reannounce_interval_seconds <= 0:
            raise ValueError( f"reannounce_interval_seconds must be positive, got {reannounce_interval_seconds}" )
        if reannounce_ttl_seconds <= reannounce_interval_seconds:
            raise ValueError(
                f"reannounce_ttl_seconds ({reannounce_ttl_seconds}) must be > "
                f"reannounce_interval_seconds ({reannounce_interval_seconds}) — else a "
                f"pending advisory expires before its first retry (config-dead re-announce)"
            )
        if not manager_recipient:
            raise ValueError( "manager_recipient must be a non-empty string" )

        # --- config ---
        self.poll_seconds            = poll_seconds
        self.manager_recipient       = manager_recipient
        # Declared-manager roster (COSA_VOICE_MANAGERS__<PROJECT>, Rick
        # 2026-06-11): feeds (a) the Part-6 active-managers fanout via the
        # default resolver, (b) build_snapshot role badging, (c) the
        # per-worker declared fallback below. Role-only — never reserves
        # personas.
        self.declared_managers       = list( declared_managers ) if declared_managers else [ ]
        # The per-worker declared fallback stays a SINGLE recipient
        # (resolve_manager's contract): the roster head outranks the INI
        # manager-on-duty placeholder when a roster is declared.
        self.declared_fallback_manager = self.declared_managers[ 0 ] if self.declared_managers else manager_recipient
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
        # L1 (2026-06-17) store-awareness seam: per-poll owed-work reader (the
        # arbiter as reader #2 of the one-store/three-readers design). Default
        # None keeps the seam INERT — every manager classifies UNKNOWN → the two
        # false-escalating detectors preserve TODAY'S behavior (fail SAFE; never
        # silently suppress). The :8001 factory wires _default_owed_work_fn so the
        # suppression actually activates live; in-pool / unit-fake construction
        # stays inert unless a fake is injected. (Mirrors the Item B None-seam
        # pattern: a None seam is visibly inert, never a hidden behavior change.)
        self._owed_work_fn = owed_work_fn
        # DM-as-liveness toggle (2026-06-17): two seams. (1) the runtime-flag
        # re-read — None → `lambda: True` (inert-safe; reproduces the INI default
        # so in-pool / unit-fake construction needs no wiring; the :8001 factory
        # wires a per-poll mtime-gated INI read for no-bounce tunability). (2) the
        # SENT-DM store reader — None → INERT (no query; dm_ts None everywhere →
        # compute_liveness excludes dm_age → byte-identical to the 4-signal
        # behavior). Mirrors the owed_work_fn None-seam pattern: a None seam is
        # visibly inert, never a hidden behavior change.
        self._count_dm_as_liveness_fn = count_dm_as_liveness_fn if count_dm_as_liveness_fn is not None else ( lambda: True )
        self._dm_activity_fn          = dm_activity_fn
        # v1.4 integrator seam: bridge discovery → {sid: persona} folded into the
        # build_fleet_view UNION roster (impure IO lives here, not in the leaf).
        self._bridge_discovery_fn = bridge_discovery_fn if bridge_discovery_fn is not None else _default_bridge_discovery
        self._snapshot_sink   = snapshot_sink   if snapshot_sink   is not None else _default_snapshot_sink
        self._render_sink     = render_sink      if render_sink     is not None else print
        # v2.2 B2 manager-tap: per-worker manager routing (D5 lineage) seam.
        self._resolve_manager_fn = resolve_manager_fn if resolve_manager_fn is not None else _default_resolve_manager
        # 2b-2 Part-6 fanout: the active-managers-on-duty resolver seam (commons
        # candidate ∩ live-bridge PID guard — phantom-safe). Injectable for tests.
        # The production default folds the declared roster in here, keeping the
        # seam's (who_rows, bridge_sessions) signature stable for injected fakes.
        self._resolve_active_managers_fn = ( resolve_active_managers_fn
                                             if resolve_active_managers_fn is not None
                                             else lambda who_rows, bridge_sessions:
                                                 _default_resolve_active_managers(
                                                     who_rows, bridge_sessions,
                                                     declared_managers=self.declared_managers ) )
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
        # corpse ceiling (2026-06-11): ages beyond this are corpse rows resurfaced
        # by the include_offline detection snapshot (the 10:52 EDT boot-burst:
        # yesterday's dead manager session poked with a bogus 1134m age on every
        # process start), never a live manager going dark — NOT eligible.
        self.manager_stale_poke_max_age_seconds   = manager_stale_poke_max_age_seconds
        # post-game F1: the structured-log seam — every outreach + gate evaluation
        # lands in the journal so silence is diagnosable (Rick's verbatim ask).
        self._log_fn           = log_fn           if log_fn           is not None else _default_log_fn
        # post-game F2: manager-manifest role source, injectable for tests (was a
        # hardcoded _default_list_manager_session_ids inside _publish_fleet_snapshot).
        self._list_managers_fn = list_managers_fn if list_managers_fn is not None else _default_list_manager_session_ids
        # Item B (2026.06.11 receipts design): delivery-receipt seams + knobs.
        # None seams keep their tier inert (legacy in-pool / unit-fake construction);
        # an inert tier is VISIBLE per-outreach as outcome "disabled" (dm_push) or
        # by the absence of re-announce results (ledger path None).
        self._dm_push_fn                 = dm_push_fn
        # Thread C+D wake hop: the host-side tmux-inject seam + its mechanism
        # selector. "tmux" (default) wakes a dormant pane via the host-side
        # inject_qualifier_via_tmux primitive, BYPASSING the listener's
        # EVENT_IDLE buffer gate (the non-wake root cause — a stale/owed or an
        # idle-but-EVENT_IDLE-never-emitted session is buffered, never drained).
        # With the INTERNAL self-poke (stop.py decision:block) confirmed broken
        # (pokes log but never effect a continuation turn — filed separately,
        # P1), this EXTERNAL tmux-wake is the PRIMARY fleet liveness path, not a
        # fallback. "dm" keeps the dm/send-only path. A malformed value
        # coerces to the default "tmux" with a LOUD log — a typo must not
        # silently change wake behavior (mirrors arbiter_bootstrap's guard).
        self._tmux_push_fn               = tmux_push_fn
        _mechanism = str( poke_wake_mechanism ).strip().lower()
        if _mechanism not in ( "tmux", "dm" ):
            self._log_fn( "poke_wake_mechanism_coerced",
                          requested=poke_wake_mechanism, coerced_to="tmux" )
            _mechanism = "tmux"
        self._poke_wake_mechanism        = _mechanism
        self._live_retry_fn              = live_retry_fn
        self.outreach_ack_window_seconds = outreach_ack_window_seconds
        self.reannounce_interval_seconds = reannounce_interval_seconds
        self.reannounce_ttl_seconds      = reannounce_ttl_seconds
        self._pending_ledger_path        = pending_ledger_path

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
        # L1 (2026-06-17) store-aware advisory tracking: a tapped-but-quiet manager
        # classified BLOCKED_ON_USER / DONE is NOT escalated MANAGER-DOWN — instead
        # it gets at most ONE advisory per un-acked tap. These sets are the
        # escalate-once flags (siblings of _manager_down_escalated); all three clear
        # together when the manager shows liveness after its tap (re-arm).
        self._manager_blocked_advised = set()   # awaiting-Rick advisory already fired
        self._manager_done_advised    = set()   # consider-reaping advisory already fired
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
        # F-A (2026.06.11 lineage-persistence design): SEEDED from the carry file
        # when a path is wired, so the mapping survives restarts — the 4× :8001
        # bounces of 2026-06-11 each wiped the in-memory map and orphaned reaped
        # rows to "(Unmanaged)". None keeps the volatile pre-fix behavior
        # (in-pool / unit-fake construction).
        self._lineage_carry_path = lineage_carry_path
        self._manager_lineage    = read_carry( lineage_carry_path ) if lineage_carry_path else { }
        # post-game F2: manager-staleness EPISODE state (mirrors the stuck-tier
        # _poke_* trio): keyed by session_id; cleared when the manager freshens
        # below the threshold (or leaves the roster) → the cap + advisory re-arm.
        self._mgr_stale_since  = { }                               # sid -> episode-start datetime
        self._mgr_poke_count   = { }                               # sid -> staleness pokes this episode
        self._mgr_advised      = set()                             # sids whose Rick advisory fired this episode
        # L1 store-awareness (lane 4, 2026-06-17): sids whose case-14 staleness
        # poke was SUPPRESSED because the manager classified BLOCKED_ON_USER/DONE.
        # sid -> (CLASS_*, persona) so the re-arm can clear the SHARED case-16/17
        # advised flag when the manager freshens out of staleness eligibility.
        self._mgr_stale_suppressed = { }
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
        # Item B §3.4: manager-bound outreaches awaiting a threaded ack —
        # outreach_id -> { persona, kind, sent_at, resends, body }. In-memory by
        # design: the ack window (900s) is far inside the 12h recycle; only a
        # restart mid-window loses tracking (documented trade).
        self._awaiting_ack  = { }
        # Item B §3.4: terminal-unacked facts that ride the NEXT Rick-bound
        # advisory body (never a fresh escalation loop).
        self._unacked_notes = [ ]
        # eng#7 (2026-06-17, Mr Radio): the follow-through aged-escalation watcher
        # rides THIS poll loop (build-plan §3b). A FACTORY seam — not an instance —
        # resolves the chicken-egg: the watcher's §4.5 hold_check_fn IS
        # self.session_is_not_owed (the arbiter's already-built store-owed
        # suppression predicate, REUSED not re-implemented), which exists only once
        # self is built. None → INERT (in-pool / unit-fake / legacy construction):
        # the flag-gated sweep is simply never called. The :8001 factory wires a
        # real factory that builds FollowThroughEscalationWatcher( config_mgr,
        # escalate_fn=<directed manager poke>, hold_check_fn=self.session_is_not_owed ).
        # Mirrors the other None-seam patterns in this ctor: a None seam is visibly
        # inert, never a hidden behavior change.
        self._follow_through_watcher = (
            follow_through_watcher_factory( self )
            if follow_through_watcher_factory is not None else None
        )

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
        # DM-as-liveness toggle (2026-06-17): read the runtime flag ONCE this poll
        # (the seam re-reads the mtime-gated INI → runtime-tunable, no bounce). When
        # OFF, SKIP the SENT-DM store query ENTIRELY (zero added DB load) so the
        # poll is byte-identical to the prior 4-signal behavior — dm_ts is None
        # everywhere and compute_liveness excludes dm_age. The flag is threaded to
        # _publish_fleet_snapshot → build_snapshot so the verdict gate matches.
        count_dm        = self._count_dm_as_liveness_fn()
        # UNION source (e). Swallow-safe per the observer invariant + the
        # _default_dm_activity_fn contract (a raising reader degrades to NO dm
        # signal; the other 4 signals carry liveness) — mirrors the sibling
        # owed_work_fn seam's try/except→inert. WITHOUT this a raising reader
        # (e.g. a DB timeout) would propagate out of _poll_once, abort the WHOLE
        # poll, and surface as a false "arbiter down" loop-level escalation.
        dm_activity     = { }
        if count_dm and self._dm_activity_fn is not None:
            try:
                dm_activity = self._dm_activity_fn()
            except Exception:
                dm_activity = { }
        fleet_view      = build_fleet_view(
            self._acc.snapshot(), who_rows, now, self.alive_threshold_seconds,
            bridge_sessions=bridge_sessions, dm_activity=dm_activity,
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

        # L1 (2026-06-17): ONE swallow-safe store read per poll classifies every
        # persona under evaluation (tapped managers ∪ live-owed-candidate sessions)
        # into BLOCKED_ON_USER / DONE / ACTIVE / UNKNOWN; passed to BOTH false-
        # escalating detectors so neither re-reads (build-plan §3.0 "one read per
        # poll"). Seam unwired → all UNKNOWN → today's behavior (fail SAFE).
        eval_personas = (
            { v.get( "persona" ) for v in fleet_view.values()
              if isinstance( v, dict ) and v.get( "persona" ) }
            | set( self._last_tap_at.keys() )
        )
        owed_class = self._classify_owed( eval_personas, fleet_view )

        self._escalate_deadlocks( graph[ "cycles" ], active_managers )    # #5 Rick + all mgrs
        # REAPED/OFFLINE-PRUNE (lane 4, 2026-06-17): only auto-ping on behalf of an
        # ALIVE holder. A reaped/long-offline session whose stale `holding_on:
        # peer:X` lingers on its view row was generating phantom blocker pings (+
        # owning-manager cc's) every backoff window — a chunk of Mr Radio's token
        # burn. Deadlock detection (#5) keeps the full graph; only the outbound
        # ping feed is pruned. A re-activated holder re-enters next poll.
        alive_personas = {
            v.get( "persona" ) for v in fleet_view.values()
            if isinstance( v, dict ) and v.get( "alive" ) is True and v.get( "persona" )
        }
        live_edges  = { h: a for h, a in graph[ "edges" ].items() if h in alive_personas }
        pings_fired = self._auto_ping( live_edges, now, persona_to_sid )  # #4 blocker + cc mgr
        roster      = build_roster( fleet_view, now, self.quiet_threshold_seconds )
        # #6 roster broadcast DROPPED (Part-6 cut) — the fleet roster is PULL-state,
        # served by /state via the snapshot below; no per-tick commons post.
        taps_fired    = self._tap_managers( fleet_view, graph, roster, now, active_managers )  # #7 / #8
        managers_down = self._check_manager_acks( now, who_rows, fleet_view, active_managers, owed_class=owed_class )  # #9 (L1 store-aware)
        decisions     = self._check_decision_needed( now )          # #10 Rick (+owning mgr if known)
        stalled       = self._check_fleet_stall( fleet_view, now, active_managers, owed_class=owed_class )  # #11 (L1 store-aware)
        pokes_fired   = self._auto_poke( fleet_view, now, active_managers )          # 2b-3 auto-poke
        rendered      = self._publish_fleet_snapshot( fleet_view, now, count_dm )
        # post-game F2/F3 detectors read the FULL (include_offline=True) detection
        # snapshot + published count the publish step just stashed on the instance.
        manager_stale_pokes = self._check_manager_staleness( self._last_full_snapshot, now, active_managers, owed_class=owed_class )  # #F2 (L1 store-aware, lane 4)
        fleet_dark          = self._check_fleet_dark( self._last_full_snapshot, self._last_published_n, now )
        # post-game F1: why-not-poked gate evaluation — runs AFTER both poke tiers
        # so the emitted vectors reflect this poll's episode state.
        self._emit_poke_gates( fleet_view, self._last_full_snapshot, now )
        # Item B (2026.06.11): close the delivery loops — manager threaded-ack
        # receipts (§3.4) + Rick re-announce of pending advisories (§3.5).
        outreach_acks = self._check_outreach_receipts( now )
        reannounces   = self._check_pending_outreach( now )
        # eng#7 (2026-06-17): ONE follow-through aged-escalation sweep on the poll
        # path (build-plan §3b). Doubly inert — no watcher wired OR flag OFF — and
        # swallow-safe (the observer invariant); see _sweep_follow_through.
        ft_escalated  = self._sweep_follow_through()

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
            "outreach_acks"       : outreach_acks,
            "reannounces"         : reannounces,
            "ft_escalated"        : ft_escalated,            # eng#7 follow-through one-shot escalations this poll
            "rendered"            : rendered,
        }
        # post-game F1: promote the summary to the journal whenever ANY outreach
        # counter is nonzero — a poll that communicated is never invisible.
        if any( summary[ k ] for k in (
                "pings_fired", "taps_fired", "managers_down", "decisions",
                "stalled", "pokes_fired", "manager_stale_pokes", "fleet_dark", "cycles",
                "outreach_acks", "reannounces", "ft_escalated" ) ):
            self._log( "arbiter_poll_activity", **summary )
        return summary

    def _sweep_follow_through( self ):
        """
        eng#7 (2026-06-17): run ONE follow-through aged-escalation sweep on the
        arbiter poll path (build-plan §3b). Inert in TWO independent layers:

          (a) no watcher wired — `follow_through_watcher_factory` was None at
              construction (in-pool / unit-fake / legacy) → return 0, no work; AND
          (b) watcher wired but `follow through escalation enabled`=False → the
              watcher's own sweep_once() short-circuits (no DB access) and reports
              {enabled:False, escalated:0, …}.

        Swallow-safe per the observer invariant: a watcher / store hiccup is
        DEMOTED to a render-sink line and never kills the poll. (The watcher's own
        daemon `_loop` guards exceptions, but THIS direct-sweep path bypasses that
        loop, so the guard must live here.)

        Ensures:
            - no watcher → returns 0 (sweep_once never called)
            - watcher present → calls sweep_once() and returns its `escalated`
              count (0 when the flag is OFF); any exception is swallowed to a
              render-sink log and returns 0
            - never raises
        """
        if self._follow_through_watcher is None:
            return 0
        try:
            result = self._follow_through_watcher.sweep_once()
            return result.get( "escalated", 0 ) if isinstance( result, dict ) else 0
        except Exception as e:
            self._render_sink( f"follow-through sweep error (swallowed, observer invariant): {e!r}" )
            return 0

    def _publish_fleet_snapshot( self, fleet_view, now, count_dm=True ):
        """
        Build + render + push the v2.1 direct-state fleet snapshot (§10.2-§10.4).

        Requires:
            - fleet_view is the per-session view dict (build_fleet_view output)
            - now is an aware datetime
            - count_dm is the DM-as-liveness toggle (read once per poll in
              _poll_once), threaded to build_snapshot(count_dm_as_liveness=...):
              True ⇒ dm_age joins the freshest-of union; False ⇒ each row's
              liveness verdict is byte-identical to the prior 4-signal block

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
            resolve_manager_fn   = self._resolve_manager_fn,
            list_managers_fn     = self._list_managers_fn,
            process_dead         = process_dead,
            declared_managers    = self.declared_managers,
            include_offline      = True,        # FULL view for the post-game F2/F3 detectors
            count_dm_as_liveness = count_dm,    # DM-as-liveness toggle (read once in _poll_once)
        )
        # Fleet-Status offline-lineage carry (2026-06-10): a reaped worker loses both
        # lineage sources at once (bridge unlink + manifest drop), so its still-decaying
        # row would otherwise drop to "Unmanaged". Replay the last-known manager until
        # the row evicts. Pure + degrade-safe (never raises, never invents); manager is
        # orthogonal to frame_signature, so this never triggers a spurious re-render.
        # (Post-game note: the carry now runs on the FULL snapshot, so lineage is
        # retained until FULL-snapshot eviction — published rows are a subset and
        # receive identical fills, so the published view is unchanged.)
        prior_lineage = self._manager_lineage
        snapshot, self._manager_lineage = carry_forward_lineage( snapshot, self._manager_lineage )
        # F-A: persist the POST-prune mapping write-on-change — bounded by
        # construction (carry_forward_lineage prunes to the snapshot sids, so the
        # file tracks exactly the decay-window population). A write failure is
        # journaled, never raised (worst case = pre-fix volatility, not a dead poll).
        if self._lineage_carry_path and self._manager_lineage != prior_lineage:
            try:
                write_carry( self._lineage_carry_path, self._manager_lineage )
            except OSError as e:
                self._log( "lineage_carry_error", error=str( e ) )
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
                       case=None, tier=None, session_id=None, persona=None,
                       outreach_id=None ):
        """
        Emit the `arbiter_outreach` event — fired at EVERY outbound communication
        (Rick's verbatim ask: "a log so we can see when it's attempting to reach
        out and communicate").

        Accounting contract — RESTATED by the 2026.06.11 receipts design (the S3
        invariant's reality moved one level down): `recipients` is the PLANNED
        recipient set for this outreach; what actually happened on each hop lives
        in the per-recipient per-channel `arbiter_outreach_result` events and the
        terminal `arbiter_outreach_receipt` events, all chained on `outreach_id`.
        Pre-design this event claimed delivery it never verified (root-cause R4:
        "rick" journaled while the live push 404'd one line earlier).

        Ensures:
            - logs kind/via/recipients + a truncated message head (full bodies
              stay out of the journal); optional case/tier/session/persona/
              outreach_id fields attach when given; never raises
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
        if outreach_id:      fields[ "outreach_id" ] = outreach_id
        self._log( "arbiter_outreach", **fields )

    # ── Item B (2026.06.11): per-hop results + terminal receipts ────────────────

    def _log_outreach_result( self, outreach_id, kind, recipient, outcome, attempt=1 ):
        """
        Emit one `arbiter_outreach_result` event — the ATTEMPT-OUTCOME record for
        ONE (recipient, channel) hop of an outreach (§3.1: no hop may fail
        silently; tonight's swallowed 404 becomes this event).

        Requires:
            - outcome is a channel-outcome dict { channel, outcome, ... }

        Ensures:
            - logs outreach_id/kind/recipient/channel/outcome/attempt (+
              http_status/detail/connection_count when the outcome carries them);
              never raises
        """
        fields = {
            "outreach_id" : outreach_id,
            "kind"        : kind,
            "recipient"   : recipient,
            "channel"     : outcome.get( "channel" ),
            "outcome"     : outcome.get( "outcome" ),
            "attempt"     : attempt,
        }
        for key in ( "http_status", "detail", "connection_count" ):
            if key in outcome: fields[ key ] = outcome[ key ]
        self._log( "arbiter_outreach_result", **fields )

    def _log_outreach_receipt( self, outreach_id, kind, recipient, outcome, **extra ):
        """
        Emit one `arbiter_outreach_receipt` event — the per-recipient TERMINAL
        state of an outreach (§3.1): delivered / reannounced_delivered / expired
        (Rick) · acked / unacked (manager).

        Ensures:
            - logs outreach_id/kind/recipient/outcome + any extra fields
              (latency_s, attempts, resends, detail); never raises
        """
        self._log( "arbiter_outreach_receipt", outreach_id=outreach_id, kind=kind,
                   recipient=recipient, outcome=outcome, **extra )

    def _mint_outreach_id( self ):
        """Ensures: returns a fresh outreach id (uuid4 hex) — the dot-connect key."""
        return uuid.uuid4().hex

    @staticmethod
    def _normalize_notify_results( raw ):
        """
        Normalize the injected notify seam's return into a list of channel-outcome
        dicts — boundary normalization at the injection seam (the ONE place the
        outcome contract meets seams we don't construct: legacy in-pool defaults
        and test fakes may still return None).

        Ensures:
            - None → [{channel:"live", outcome:"legacy_notify"}] (a legacy seam's
              push is journaled as such, never claimed delivered)
            - a single outcome dict → wrapped in a list
            - a list/iterable of outcomes → list as-is; never raises
        """
        if raw is None:
            return [ { "channel": "live", "outcome": "legacy_notify" } ]
        if isinstance( raw, dict ):
            return [ raw ]
        return list( raw )

    def _emit_to_rick( self, outreach_id, kind, message, case=None ):
        """
        Emit one Rick-bound advisory through the notify seam and journal what
        ACTUALLY happened on every channel (§3.2), closing the Rick-side loop:
        delivered → receipt now; user_not_available → the pending ledger (§3.5
        re-announce-on-return — milestone-must-land).

        Ensures:
            - terminal-unacked manager facts (if any) ride THIS advisory's body
              (§3.4 — never a fresh escalation loop), then clear
            - every outcome the seam returns is journaled as one
              arbiter_outreach_result (a seam blow-up degrades to outcome
              http_error — journaled, never raised)
            - a DELIVERED live outcome journals receipt "delivered"; a
              user_not_available outcome enters the pending ledger (when a ledger
              path is wired); a ledger write failure is journaled
              (outreach_ledger_error) — visible, never silent
        """
        if self._unacked_notes:
            message = message + " [unacked prior outreach: " + "; ".join( self._unacked_notes ) + "]"
            self._unacked_notes = [ ]
        try:
            results = self._normalize_notify_results( self._notify_fn( message ) )
        except Exception as e:
            results = [ { "channel": "live", "outcome": "http_error", "detail": str( e )[ :160 ] } ]
        for outcome in results:
            self._log_outreach_result( outreach_id, kind, "rick", outcome )
        live = next( ( r for r in results if r.get( "channel" ) == "live" ), None )
        if live is None:
            return
        if live.get( "outcome" ) in DELIVERED_OUTCOMES:
            self._log_outreach_receipt( outreach_id, kind, "rick", "delivered" )
        elif live.get( "outcome" ) == "user_not_available" and self._pending_ledger_path:
            try:
                add_pending( self._pending_ledger_path, outreach_id,
                             message=message, kind=kind, case=case,
                             created_ts=self._clock.now_iso(),
                             last_outcome="user_not_available" )
            except OSError as e:
                self._log( "outreach_ledger_error", outreach_id=outreach_id, error=str( e ) )

    def _emit_dm( self, outreach_id, kind, persona, body, case=None,
                  session_id=None, expects_ack=False, attempt=1 ):
        """
        Emit one persona-bound DM: the durable dm-<persona> board write PLUS the
        best-effort wake push hop. Journals one result per channel.

        The wake push hop is mechanism-selected (Thread C+D, INI
        `arbiter poke wake mechanism`, default "tmux" — load-bearing, not a
        preference):
        - "tmux" + a tmux_push_fn + a session_id → host-side tmux injection
          (inject_qualifier_via_tmux) that WAKES a dormant pane, BYPASSING the
          listener's EVENT_IDLE buffer gate. This is the PRIMARY fleet liveness
          path now that the internal self-poke (stop.py decision:block) is
          confirmed broken (filed separately, P1). On a tmux/bridge-unavailable
          outcome it degrades to the dm_push_fn hop (rider a).
        - "dm" (or tmux selected with no tmux seam / no session_id) → the
          dm/send dm_push_fn hop (register-question-era §3.3 path).

        Ensures:
            - the board write stamps outreach_id + question_id metadata (the
              threading key a replying recipient names in in_reply_to) +
              expects_ack; a resend (attempt > 1) derives a fresh question_id
              "<outreach_id>-r<attempt>" so the push registration never 409s
            - the durable board write runs UNCONDITIONALLY, before the push-hop
              selection, so the poke is never lost regardless of mechanism/outcome
            - dm channel outcome: posted | post_error; dm_push channel outcome:
              the hop's own (dispatched / push_unavailable) or "disabled" when no
              hop is wired — every case journaled
            - expects_ack=True (manager-bound, first attempt) registers the
              outreach in the awaiting-ack tracker for §3.4 receipt polling
            - never raises
        """
        qid      = outreach_id if attempt == 1 else f"{outreach_id}-r{attempt}"
        metadata = { "kind": "arbiter-ping", "recipient_persona": persona,
                     "outreach_id": outreach_id, "question_id": qid,
                     "expects_ack": expects_ack }
        try:
            self._commons.send_to( persona, body, metadata=metadata )
            dm_outcome = { "channel": "dm", "outcome": "posted" }
        except Exception as e:
            dm_outcome = { "channel": "dm", "outcome": "post_error", "detail": str( e )[ :160 ] }
        self._log_outreach_result( outreach_id, kind, persona, dm_outcome, attempt=attempt )
        # Push hop — Thread C+D mechanism-selected, degrade-safe. The durable
        # board write above already ran UNCONDITIONALLY, so the poke is never
        # lost no matter which push channel is chosen or whether it lands.
        def _call_push( fn, *push_args ):
            try:
                return fn( *push_args )
            except Exception as e:
                return { "channel": "dm_push", "outcome": "push_unavailable",
                         "detail": str( e )[ :160 ] }
        push_outcome = None
        if self._poke_wake_mechanism == "tmux" and self._tmux_push_fn is not None and session_id:
            # PRIMARY wake path: host-side tmux inject (session_id, qid, body) —
            # bypasses the listener's EVENT_IDLE buffer gate, waking a dormant pane.
            push_outcome = _call_push( self._tmux_push_fn, session_id, qid, body )
            # Rider (a): tmux/bridge unavailable → degrade to the DM push hop.
            if push_outcome.get( "outcome" ) == "push_unavailable" and self._dm_push_fn is not None:
                push_outcome = _call_push( self._dm_push_fn, persona, qid, body )
        if push_outcome is None:
            # mechanism == "dm", OR tmux selected with no tmux seam / no session_id.
            push_outcome = ( _call_push( self._dm_push_fn, persona, qid, body )
                             if self._dm_push_fn is not None
                             else { "channel": "dm_push", "outcome": "disabled" } )
        self._log_outreach_result( outreach_id, kind, persona, push_outcome, attempt=attempt )
        if expects_ack:
            self._awaiting_ack[ outreach_id ] = {
                "persona" : persona,
                "kind"    : kind,
                "sent_at" : datetime.datetime.fromisoformat( self._clock.now_iso() ),
                "resends" : 0,
                "body"    : body,
            }

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
            - TIER_RICK_ONLY          → _emit_to_rick  (durable + live push + receipt/ledger)
            - TIER_RICK_AND_MANAGERS  → _emit_to_rick + _emit_dm each active manager (ack-tracked)
            - TIER_OWNING_MANAGER     → _emit_dm(owning_manager)  (if resolved; ack-tracked)
            - TIER_BLOCKER_AND_MANAGER→ _emit_dm(blocker, no ack owed) + _emit_dm(owning_manager,
                                        cc_message, ack-tracked)  (each when present)
            - TIER_DROP               → no push (pull-state; #6)
          (TIER_LOG_THEN_RICK #12 is handled by _on_poll_error's streak logic, not here.)

        Ensures (2026.06.11 receipts design — the R4 kill):
            - emits exactly the recipients its tier prescribes; absent optional
              recipients (no manager resolved, empty active set) degrade silently
            - ONE `arbiter_outreach` intent event (recipients = the PLANNED set,
              stamped with a fresh outreach_id), then one `arbiter_outreach_result`
              per (recipient, channel) hop recording what ACTUALLY happened, then
              terminal `arbiter_outreach_receipt` events as loops close — this
              event no longer claims delivery it didn't verify; a no-emission
              route (empty tier inputs / TIER_DROP) logs nothing
            - never raises (the emit helpers convert every hop failure into a
              journaled outcome)
        """
        tier       = tier_for( case )
        kind       = CASE_KINDS.get( case, f"case_{case}" )
        rick_bound = tier in ( TIER_RICK_ONLY, TIER_RICK_AND_MANAGERS )
        dm_targets = [ ]                          # ( persona, body, expects_ack )
        if tier == TIER_RICK_AND_MANAGERS:
            dm_targets = [ ( m, message, True ) for m in active_managers or [ ] ]
        elif tier == TIER_OWNING_MANAGER and owning_manager:
            dm_targets = [ ( owning_manager, message, True ) ]
        elif tier == TIER_BLOCKER_AND_MANAGER:
            if blocker:
                dm_targets.append( ( blocker, message, False ) )       # worker nudge — no ack owed
            if owning_manager and cc_message:
                dm_targets.append( ( owning_manager, cc_message, True ) )
        # TIER_DROP / empty tier inputs → intentional no-op (the #6 roster cut)
        if not rick_bound and not dm_targets:
            return
        outreach_id = self._mint_outreach_id()
        planned     = ( [ "rick" ] if rick_bound else [ ] ) + [ p for p, _b, _a in dm_targets ]
        self._log_outreach( kind, "route", planned, message,
                            case=case, tier=tier, outreach_id=outreach_id )
        if rick_bound:
            self._emit_to_rick( outreach_id, kind, message, case=case )
        for persona, body, expects_ack in dm_targets:
            self._emit_dm( outreach_id, kind, persona, body, case=case,
                           expects_ack=expects_ack )

    def _check_outreach_receipts( self, now ):
        """
        §3.4 manager-side receipt polling — the acked-ledger principle (the
        receipt is an explicit, OWNER-WRITTEN mark, never an inference): an
        awaited outreach is acked iff the recipient posted a threaded reply
        (metadata.in_reply_to naming the outreach's question_id) on the SAME
        dm-<persona> board the durable write landed on. Filesystem read via the
        gateway — detection-path-safe (R4-clean).

        Ensures:
            - an in_reply_to match (exact outreach_id or its "-rN" resend
              derivative) → receipt "acked" (+ latency_s) and the tracker clears
            - no ack past outreach_ack_window_seconds → exactly ONE re-send
              (attempt=2, fresh window), then — still nothing — terminal receipt
              "unacked" + the fact queued to ride the NEXT Rick-bound advisory
              (§3.4: never an escalation recursion; at most 2 sends total)
            - a gateway read hiccup degrades to "no ack seen this poll" (the
              window keeps governing); never raises
            - returns the count of acks confirmed this poll
        """
        acked = 0
        for outreach_id, state in list( self._awaiting_ack.items() ):
            topic = LupinArbiterGateway.dm_topic_for( state[ "persona" ] )
            # Timing note (Tiberius review nit, 2026-06-11): a resend resets
            # sent_at to NOW, so an ack posted in the instant between the
            # window-expiry evaluation and that reset falls before this `since`
            # and is missed for ONE cycle — it is still caught on the next poll
            # because the prefix match below accepts the ORIGINAL outreach_id
            # against any of its question_id derivatives. Correct, just non-obvious.
            since = ( state[ "sent_at" ] - datetime.timedelta( seconds=1 ) ).isoformat()
            try:
                entries = self._commons.read( topic, since=since ) or [ ]
            except Exception:
                entries = [ ]
            reply = next(
                ( e for e in entries
                  if isinstance( e, dict ) and isinstance( e.get( "metadata" ), dict )
                  and str( e[ "metadata" ].get( "in_reply_to" ) or "" ).startswith( outreach_id ) ),
                None,
            )
            if reply is not None:
                latency = ( now - state[ "sent_at" ] ).total_seconds()
                self._log_outreach_receipt( outreach_id, state[ "kind" ], state[ "persona" ],
                                            "acked", latency_s=int( latency ) )
                del self._awaiting_ack[ outreach_id ]
                acked += 1
                continue
            if ( now - state[ "sent_at" ] ).total_seconds() < self.outreach_ack_window_seconds:
                continue
            if state[ "resends" ] == 0:
                state[ "resends" ] = 1
                state[ "sent_at" ] = now
                self._emit_dm( outreach_id, state[ "kind" ], state[ "persona" ],
                               state[ "body" ], expects_ack=False, attempt=2 )
            else:
                self._log_outreach_receipt( outreach_id, state[ "kind" ], state[ "persona" ],
                                            "unacked", resends=state[ "resends" ] )
                self._unacked_notes.append(
                    f"{state[ 'kind' ]} {outreach_id[ :8 ]} to {state[ 'persona' ]}" )
                del self._awaiting_ack[ outreach_id ]
        return acked

    def _check_pending_outreach( self, now ):
        """
        §3.5 Rick-side re-announce-on-return — milestone-must-land, mechanized:
        every pending (user_not_available) advisory is re-pushed through the
        dedup-BYPASSING live transport at most once per reannounce interval
        until a DELIVERED outcome or TTL expiry. Escalation-path only (runs only
        while the ledger is non-empty — R4-clean); the ledger is file-backed so
        a recycle or restart never drops a pending advisory (S7-pinned).

        Ensures:
            - inert (returns 0) when no ledger path or no live_retry_fn is wired
            - TTL-expired entries → terminal receipt "expired" (+ attempts) + removal
            - malformed entries → the same terminal receipt with a detail + removal
              (visible, never a silent skip)
            - due entries (interval elapsed) re-push; every attempt journals an
              arbiter_outreach_result with attempt=N; a delivered outcome →
              receipt "reannounced_delivered" (+ attempts) + removal; otherwise
              the attempt is recorded back to the ledger
            - any ledger write failure is journaled (outreach_ledger_error);
              never raises; returns the count of re-announce attempts this poll
        """
        if not self._pending_ledger_path or self._live_retry_fn is None:
            return 0
        attempts_fired = 0
        for outreach_id, entry in list( read_pending( self._pending_ledger_path ).items() ):
            try:
                created = datetime.datetime.fromisoformat( str( entry[ "created_ts" ] ) )
                last    = datetime.datetime.fromisoformat( str( entry[ "last_attempt_ts" ] ) )
                kind    = str( entry.get( "kind" ) or "unknown" )
                message = entry[ "message" ]
                prior   = int( entry.get( "attempts", 1 ) )
            except Exception as e:
                self._log_outreach_receipt( outreach_id, "unknown", "rick", "expired",
                                            detail=f"malformed ledger entry: {e}" )
                try:
                    remove_pending( self._pending_ledger_path, outreach_id )
                except OSError as oe:
                    self._log( "outreach_ledger_error", outreach_id=outreach_id, error=str( oe ) )
                continue
            if ( now - created ).total_seconds() >= self.reannounce_ttl_seconds:
                self._log_outreach_receipt( outreach_id, kind, "rick", "expired", attempts=prior )
                try:
                    remove_pending( self._pending_ledger_path, outreach_id )
                except OSError as oe:
                    self._log( "outreach_ledger_error", outreach_id=outreach_id, error=str( oe ) )
                continue
            if ( now - last ).total_seconds() < self.reannounce_interval_seconds:
                continue
            try:
                outcome = self._live_retry_fn( message )
            except Exception as e:
                outcome = { "channel": "live", "outcome": "http_error", "detail": str( e )[ :160 ] }
            attempt = prior + 1
            self._log_outreach_result( outreach_id, kind, "rick", outcome, attempt=attempt )
            attempts_fired += 1
            if outcome.get( "outcome" ) in DELIVERED_OUTCOMES:
                self._log_outreach_receipt( outreach_id, kind, "rick",
                                            "reannounced_delivered", attempts=attempt )
                try:
                    remove_pending( self._pending_ledger_path, outreach_id )
                except OSError as oe:
                    self._log( "outreach_ledger_error", outreach_id=outreach_id, error=str( oe ) )
            else:
                try:
                    record_attempt( self._pending_ledger_path, outreach_id,
                                    attempt_ts=self._clock.now_iso(),
                                    outcome=str( outcome.get( "outcome" ) ) )
                except OSError as oe:
                    self._log( "outreach_ledger_error", outreach_id=outreach_id, error=str( oe ) )
        return attempts_fired

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
            res     = self._resolve_manager_fn( sid, declared_manager=self.declared_fallback_manager )
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

        REAPED/OFFLINE-PRUNE (lane 4, 2026-06-17): only ALIVE views qualify. A
        reaped tombstone (Rio, gone from the fleet) or a long-offline session
        whose STALE `holding_on: peer:X` still lingers on its view row was
        inflating the manager-tap roster ("N blocked / recommend cajole" listing
        reaped + non-blocked personas), and each re-tap re-invokes the manager
        session = full context reload = the token burn Mr Radio flagged. A dead
        worker's block is not actionable (the arbiter can't poke a session with no
        process); a re-activated worker re-enters the roster the very next poll.
        This also stabilizes `_tap_signature`, so the tap fires far less often.

        Ensures:
            - returns a list of ALIVE view dicts (stuck OR a blocked-edge holder by
              persona); reaped/offline views are excluded; never raises
        """
        holders = set( graph[ "edges" ].keys() )
        out     = [ ]
        for view in fleet_view.values():
            if not isinstance( view, dict ):
                continue
            if view.get( "alive" ) is not True:
                continue                                  # reaped/offline-prune (lane 4)
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
                                                declared_manager=self.declared_fallback_manager )
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

    def _manager_bridge_activity( self, manager, fleet_view ):
        """
        Freshest bridge-file mtime (as an aware-UTC datetime) across the
        session(s) whose persona is `manager`, or None.

        The bridge mtime is bumped UNCONDITIONALLY by every PreToolUse hook
        (touch_bridge_mtime — fires for ALL tools, MCP calls included), so a
        fresh mtime PROVES an actively-working manager is alive even when they
        post NOTHING to commons. This is the same wedge-resilient liveness clock
        the fleet render already trusts (_publish_fleet_snapshot via
        _bridge_mtime_fn); the manager-down detector consults it here so a
        hard-working-but-commons-silent manager is never falsely declared down
        (bug 9694fb11).

        Requires:
            - manager is a persona name (str)
            - fleet_view is the build_fleet_view dict { session_id: VIEW } or None

        Ensures:
            - returns the most-recent bridge mtime (aware-UTC datetime) among the
              manager's sessions, or None when fleet_view is None/empty, no view
              matches the persona, or no bridge resolves
            - NEVER raises (a single session's bridge-read hiccup is swallowed —
              the observer invariant)
        """
        best = None
        for view in ( fleet_view or { } ).values():
            if not isinstance( view, dict ) or view.get( "persona" ) != manager:
                continue
            sid   = view.get( "session_id" )
            mtime = self._bridge_mtime_fn( sid ) if sid else None
            if mtime is None:
                continue
            try:
                ts = datetime.datetime.fromtimestamp( mtime, tz=datetime.timezone.utc )
            except ( TypeError, ValueError, OSError, OverflowError ):
                ts = None
            if ts is not None and ( best is None or ts > best ):
                best = ts
        return best

    @staticmethod
    def _holding_on_by_persona( fleet_view ):
        """
        { persona: holding_on } for every view that carries a string holding_on.

        L1 degrade-safe corroboration source: when the store read is UNKNOWN, a
        holding_on starting "user:" is a best-effort HINT that a manager is parked
        on Rick — recorded for the advisory wording ONLY (never the sole basis for
        suppression; an UNKNOWN manager still escalates — fail SAFE).

        Ensures:
            - returns { persona: holding_on_str }; skips views without a persona or
              a non-string holding_on; never raises
        """
        out = { }
        for view in ( fleet_view or { } ).values():
            if isinstance( view, dict ) and view.get( "persona" ):
                holding = view.get( "holding_on" )
                if isinstance( holding, str ):
                    out[ view[ "persona" ] ] = holding
        return out

    @staticmethod
    def _item_is_user_gated( item ):
        """
        Is a single non-terminal owed item gated on Rick (the human)?

        TRUE iff gate_class == "ricks_court" OR (status == "blocked" AND blocked_by
        carries ≥1 typed ref {kind: "user"}). These are the two store encodings of
        "correctly waiting on the human" (build-plan §3.0).

        Ensures:
            - returns a bool; a non-dict / malformed item → False; never raises
        """
        if not isinstance( item, dict ):
            return False
        if item.get( "gate_class" ) == "ricks_court":
            return True
        if item.get( "status" ) == "blocked":
            for ref in ( item.get( "blocked_by" ) or [ ] ):
                if isinstance( ref, dict ) and ref.get( "kind" ) == "user":
                    return True
        return False

    def _classify_owed( self, personas, fleet_view ):
        """
        L1 (2026-06-17): classify each persona under evaluation this poll into
        BLOCKED_ON_USER / DONE / ACTIVE / UNKNOWN from a SINGLE swallow-safe store
        read — the crux of the detector-gap fix (build-plan §3.0).

        The injected owed_work_fn returns { persona: [ owed-item dicts ] } of each
        persona's NON-TERMINAL owed items. Classification per persona:
          - DONE             ⇔ zero non-terminal owed items
          - BLOCKED_ON_USER  ⇔ ≥1 owed item AND every owed item is Rick-gated
                               (_item_is_user_gated)
          - ACTIVE           ⇔ ≥1 owed item that is NOT Rick-gated
          - UNKNOWN          ⇔ the seam is unwired (owed_work_fn is None), the read
                               raised, or the persona is absent from the result →
                               FAIL SAFE: the detectors treat UNKNOWN exactly as
                               today (escalate), never silently suppressing.

        Observer invariant: ONE read per poll for the whole set; ANY exception from
        the seam is swallowed → the entire result is UNKNOWN (never crashes the
        poll, never silently suppresses a real escalation). The holding_on "user:"
        corroboration (consumed by the detectors) is best-effort wording only.

        Ensures:
            - returns { persona: CLASS_* } for each non-empty persona in `personas`
            - owed_work_fn is called AT MOST once (skipped when None or no personas)
            - never raises
        """
        names = sorted( { p for p in ( personas or [ ] ) if p } )
        owed  = None
        if self._owed_work_fn is not None and names:
            try:
                owed = self._owed_work_fn( names )
            except Exception:
                owed = None        # store hiccup → UNKNOWN → fail SAFE (observer invariant)
        result = { }
        for persona in names:
            if owed is None or persona not in owed:
                result[ persona ] = CLASS_UNKNOWN          # unwired / hiccup / absent → fail SAFE
                continue
            items = owed.get( persona ) or [ ]
            if not items:
                result[ persona ] = CLASS_DONE
            elif all( self._item_is_user_gated( it ) for it in items ):
                result[ persona ] = CLASS_BLOCKED_ON_USER
            else:
                result[ persona ] = CLASS_ACTIVE
        return result

    def session_is_not_owed( self, persona, fleet_view=None ):
        """
        Single-session reusable suppression seam (lane 4, 2026-06-17): True iff
        `persona`'s owed work means it is NOT a stall / NOT down — the canonical
        store-owed decision in ONE call, so a caller need not pre-compute the
        per-poll owed_class map.

        This is the named primitive Mr Radio's engagement-#7 follow-through
        watcher reuses (Tiberius, 2026-06-17): its §4.5 hygiene — "consult the
        worker's declared not-owed state BEFORE firing a blocking-escalation" — is
        EXACTLY this decision, so #7 calls this instead of re-implementing the
        store read + classification (no duplication, no poke-path contention). It
        composes `_classify_owed` (one swallow-safe store read) with the pure
        `owed_class_suppresses` predicate.

        Requires:
            - persona is a string; fleet_view is the per-poll view dict or None
              (only used for the holding_on "user:" best-effort corroboration)

        Ensures:
            - returns True iff persona classifies BLOCKED_ON_USER or DONE
            - ACTIVE / UNKNOWN (incl. unwired seam / store hiccup / absent) → False
              (fail-SAFE — never suppress a real escalation); one store read; never raises
        """
        cls = self._classify_owed( [ persona ], fleet_view or { } ).get( persona, CLASS_UNKNOWN )
        return owed_class_suppresses( cls )

    def _check_manager_acks( self, now, who_rows, fleet_view=None, active_managers=None, owed_class=None ):
        """
        B4/D4 manager-down detector via the liveness-proxy ACK.

        A manager tapped at T is treated as having "acked" (present-to-act) while
        their liveness is fresh AT/AFTER T. Liveness is the UNION of two aliveness
        sources: commons activity from who() AND a fresh bridge-mtime bump (the
        wedge-resilient clock every PreToolUse touches). If a TAPPED manager shows
        NO liveness from EITHER source since the tap AND ≥
        manager_ack_window_seconds have elapsed → MANAGER-DOWN → escalate to Rick
        (notify_fn) + HOLD.

        Why the bridge-mtime source (bug 9694fb11): there is NO deliverable
        tap-ACK path — a manager literally cannot DM the arbiter back. So the only
        honest ACK is a liveness proxy, and commons-activity ALONE under-counts: a
        manager working hard (edits/tools/MCP, all of which bump the bridge mtime)
        but posting nothing to commons looked "down" and false-escalated to Rick.
        Folding the bridge mtime in treats real work as the implicit ACK it is.

        IMPORTANT (semantics): the liveness-proxy proves ALIVENESS, not
        CONSUMPTION. That's correct for D4, whose trigger IS manager-DOWN —
        staleness detects exactly that. "Alive-but-ignoring-the-tap" is NOT a D4
        case (it's manager judgment, not down). Explicit-ack (proves consumption)
        is a logged V2 item.

        HOLD = escalate-ONLY: this path takes NO actuation (never auto-assign —
        acting-manager succession is V2). Escalates ONCE per un-acked tap (until
        the manager re-acks), not every poll.

        L1 STORE-AWARENESS (2026-06-17, build-plan §3.1/§3.2/§3.3): a manager that
        is tapped-but-quiet is NOT always down. Before escalating MANAGER-DOWN we
        consult the per-poll store classification (owed_class):
          - BLOCKED_ON_USER → the manager is CORRECTLY waiting on Rick (it makes no
            tool calls, so no bridge/commons liveness — exactly the false-fire). It
            is NOT down: emit at most ONE awaiting-Rick advisory (case 16), never
            the repeating MANAGER-DOWN loop.
          - DONE → the manager owes nothing (finished). Not down: emit at most ONE
            consider-reaping advisory (case 17). (Matches the stall path, which is
            already done-safe because an idle manager's state ∉ {working,stuck,
            holding}.)
          - ACTIVE / UNKNOWN → TODAY'S behavior: MANAGER-DOWN. UNKNOWN is the
            fail-SAFE class (seam unwired / store hiccup) — we never silently
            suppress; a holding_on starting "user:" only DECORATES the wording
            (best-effort corroboration, never suppresses).
        This honors §3.3 (tap-ACK window vs loop cadence) by OPTION (a): the
        window is irrelevant for a correctly-waiting manager because the class —
        not the clock — decides. Cross-ref memory
        reference_arbiter_staleness_threshold_loop_cadence (the mgr loop must stay
        below the staleness floor). The three escalate-once flags
        (_manager_down_escalated / _manager_blocked_advised / _manager_done_advised)
        all clear together on a re-ack so each fires at most once per un-acked tap.

        Ensures:
            - returns the count of NEW manager-down escalations this poll (advisories
              are NOT counted — they are not downs)
            - clears a manager's down/advisory flags once it shows activity (commons
              OR bridge) since its tap
            - BLOCKED_ON_USER / DONE managers never escalate MANAGER-DOWN
            - never raises
        """
        owed_class = owed_class or { }
        holding    = self._holding_on_by_persona( fleet_view )
        down = 0
        for manager, tapped_at in list( self._last_tap_at.items() ):
            commons_activity = self._manager_last_activity( manager, who_rows )
            bridge_activity  = self._manager_bridge_activity( manager, fleet_view )
            # Implicit tap-ACK from EITHER aliveness source (bug 9694fb11): the
            # most-recent of commons-post liveness and the bridge-mtime clock. A
            # fresh bridge bump means the manager is actively running tools right
            # now — alive, hence acked — even with zero commons posts.
            candidates    = [ t for t in ( commons_activity, bridge_activity ) if t is not None ]
            last_activity = max( candidates ) if candidates else None
            if last_activity is not None and last_activity >= tapped_at:
                self._manager_down_escalated.discard( manager )    # acked → clear (re-arm)
                self._manager_blocked_advised.discard( manager )
                self._manager_done_advised.discard( manager )
                continue
            if ( now - tapped_at ).total_seconds() < self.manager_ack_window_seconds:
                continue                                            # window not yet elapsed
            cls = owed_class.get( manager, CLASS_UNKNOWN )
            if cls == CLASS_BLOCKED_ON_USER:
                if manager not in self._manager_blocked_advised:    # L1 §3.1 advisory-once
                    self._manager_blocked_advised.add( manager )
                    self._route(
                        CASE_MANAGER_AWAITING_USER,
                        f"MANAGER-AWAITING-RICK (advisory, NOT manager-down): {manager} is "
                        f"correctly BLOCKED on Rick — every owed item is Rick-gated. No "
                        f"tap-ACK is expected while it waits; this is a one-time notice, "
                        f"not a repeating escalation.",
                        active_managers=active_managers
                    )
                continue
            if cls == CLASS_DONE:
                if manager not in self._manager_done_advised:       # L1 §3.2 advisory-once
                    self._manager_done_advised.add( manager )
                    self._route(
                        CASE_MANAGER_DONE_ADVISORY,
                        f"MANAGER-DONE (advisory, NOT manager-down): {manager} owes NO "
                        f"non-terminal work — it appears finished/idle. Consider reaping "
                        f"it (the arbiter never reaps — redline). One-time notice.",
                        active_managers=active_managers
                    )
                continue
            if manager not in self._manager_down_escalated:         # ACTIVE / UNKNOWN → today's MANAGER-DOWN
                self._manager_down_escalated.add( manager )
                note = ""
                if cls == CLASS_UNKNOWN and holding.get( manager, "" ).startswith( "user:" ):
                    note = ( f" (holding_on={holding[ manager ]} — possibly blocked on Rick, "
                             f"but the task-store could not confirm; escalating to be SAFE)" )
                self._route(                                   # Part-6 #9 manager-down
                    9,
                    f"MANAGER-DOWN: {manager} did not ack the arbiter tap within "
                    f"{self.manager_ack_window_seconds}s (no liveness since tap) — "
                    f"escalating to Rick + active managers + HOLDING (no auto-assign)"
                    f"{note}",
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
            outreach_id = self._mint_outreach_id()
            self._log_outreach( "decision_cc", "send_to", [ manager ], cc_body,
                                persona=manager, outreach_id=outreach_id )
            self._emit_dm( outreach_id, "decision_cc", manager, cc_body, expects_ack=True )

    @staticmethod
    def _fleet_progress_signature( fleet_view ):
        """
        A hashable signature over the fleet's SEMANTIC progress (per-session
        state / stuck / holding PLUS the last task-store-transition ts) — NOT
        liveness ages. When ANY session's semantic state advances OR a session
        records a NEW task-store WRITE, the signature changes ⇒ progress. Used by
        the stall detector (state≠liveness: stall keys on progress, never on
        liveness).

        TASK-TRANSITION PROGRESS (arbiter signs-of-life Fix 2, 2026-06-16): a
        manager actively creating/moving task items previously registered ALIVE
        but NOT progressing (commons chatter is liveness, never progress), tripping
        a false WHOLE-FLEET-STALL. Folding last_task_transition_ts in fixes that:
        a fresh task write advances the signature ⇒ progress ⇒ the stall timer
        re-arms. This is SAFE — a task write is unambiguous coordination work, and
        (unlike a DM) can never be idle "still blocked" chatter, so it does NOT
        re-open the chatty-but-stuck blind spot the signature deliberately guards:
        a LIVE-but-stuck fleet doing NO task writes still produces an UNCHANGED
        signature and STILL stalls (task writes are the ONLY new progress source —
        their ABSENCE is still "no progress"). The ts is stringified (isoformat)
        so the signature stays a clean, hashable, value-comparable tuple.
        """
        return tuple( sorted(
            ( v.get( "session_id" ), v.get( "state" ), bool( v.get( "stuck" ) ), v.get( "holding_on" ),
              v[ "last_task_transition_ts" ].isoformat() if v.get( "last_task_transition_ts" ) else None )
            for v in fleet_view.values() if isinstance( v, dict )
        ) )

    @staticmethod
    def _has_live_owed_work( fleet_view, owed_class=None ):
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

        L1 STORE-AWARENESS (2026-06-17, build-plan §3.1): a session whose persona
        classifies BLOCKED_ON_USER (every owed item Rick-gated) is EXCLUDED from
        the live-owed set — a fleet whose ONLY live owed work is parked on Rick is
        NOT a stall (the manager-in-`holding`-on-Rick false-fire). owed_class is
        the per-poll store classification; when it is None/empty (seam unwired,
        store UNKNOWN), NO session is excluded → TODAY'S behavior (fail SAFE).

        Ensures:
            - returns True iff some view is alive AND state ∈ {working, stuck,
              holding} AND its persona is NOT classified BLOCKED_ON_USER; never raises
        """
        owed_class = owed_class or { }
        for v in fleet_view.values():
            if not ( isinstance( v, dict ) and v.get( "alive" ) is True
                     and v.get( "state" ) in ( "working", "stuck", "holding" ) ):
                continue
            persona = v.get( "persona" )
            if persona is not None and owed_class.get( persona ) == CLASS_BLOCKED_ON_USER:
                continue                                # Rick-gated owed work is not a stall
            return True
        return False

    def _check_fleet_stall( self, fleet_view, now, active_managers=None, owed_class=None ):
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
            - a fleet whose only live owed work is BLOCKED_ON_USER never escalates
              (L1 §3.1; owed_class None/empty → today's behavior, fail SAFE)
            - returns 1 on a new escalation else 0; never raises
        """
        sig = self._fleet_progress_signature( fleet_view )
        if sig != self._last_progress_sig:
            self._last_progress_sig = sig
            self._last_progress_at  = now
            self._stall_escalated   = False
            return 0
        has_owed = self._has_live_owed_work( fleet_view, owed_class )
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
                recipient   = view.get( "persona" ) or sid
                body        = self._format_poke( view )
                # post-game F1 — kind "stuck_poke", never the bare four-letter literal
                # (the poked-rename one-name sweep bans quoted bare-poke literals on
                # production surfaces; also symmetric with "manager_stale_poke")
                outreach_id = self._mint_outreach_id()
                self._log_outreach( "stuck_poke", "send_to", [ recipient ], body,
                                    session_id=sid, persona=view.get( "persona" ),
                                    outreach_id=outreach_id )
                # no ack owed: a wake-nudge at a STUCK session would spam unacked
                # receipts by definition — the dm_push hop IS the wake mechanism
                self._emit_dm( outreach_id, "stuck_poke", recipient, body,
                               session_id=sid, expects_ack=False )
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

    def _check_manager_staleness( self, snapshot, now, active_managers, owed_class=None ):
        """
        F2: the SECOND, role-gated pokeable criterion — a MANAGER-role session
        whose freshest union signal is older than the threshold gets a bounded
        poke AND a Rick advisory, even with ZERO stuck workers (the 2026-06-10
        gap: stale 27m/34m/30m+ manager verdicts produced no outreach because the
        stuck-tier requires alive∧stuck and taps require attention workers).

        L1 STORE-AWARENESS (lane 4, 2026-06-17): this is the THIRD detector folded
        into the per-poll store classification (`owed_class`) — the one the L1
        store-aware pass (build-plan §3.1/§3.2) left out, so it kept false-firing
        MANAGER-STALE at an interactive, no-`/loop` manager that emits NONE of the
        5 liveness signals while CORRECTLY waiting on Rick (every owed item
        Rick-gated). The discriminator is NOT "is there a signal?" (there cannot be
        one while it idle-waits) but "does it OWE non-Rick-gated work?":
          - BLOCKED_ON_USER → silence IS the expected state → at most ONE case-16
            (MANAGER-AWAITING-USER) advisory, NEVER the repeating case-14 poke.
          - DONE → owes nothing (finished) → at most ONE case-17 (consider-reaping)
            advisory, never case-14.
          - ACTIVE / UNKNOWN → today's case-14 staleness poke. UNKNOWN is the
            fail-SAFE class (seam unwired / store hiccup): we never silently
            suppress a real escalation — this preserves the quota-freeze true
            positive (all-stale-UNKNOWN still escalates).
        The case-16/17 advised flags are SHARED with `_check_manager_acks` (#9),
        so a manager that is BOTH tapped and stale gets the advisory at most ONCE
        across both detectors (no Rick double-page). A suppressed manager that
        later freshens below threshold re-arms (see `_mgr_stale_suppressed`).

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
            - a row is eligible iff role == "manager" AND freshest_age_s is not
              None AND threshold <= freshest_age_s <= max_age. This FLIPS the
              original None-age choice (corpse-ceiling fix, 2026-06-11): None =
              no signal EVER = a corpse/malformed row → NOT eligible (was:
              None = maximally stale = eligible). The ceiling exists for the
              same reason — F2 means "this manager went dark RECENTLY", not "a
              corpse exists": the include_offline detection snapshot resurfaces
              yesterday's dead manager rows on every process start (the 10:52
              EDT boot-burst poked a 1134m-old corpse and advised Rick), and an
              age beyond max_age is a corpse, not a dark manager
            - ≤ poke_max_per_episode pokes + exactly ONE advisory per episode
            - returns the count of staleness pokes fired this poll; never raises
        """
        if self.manager_stale_poke_threshold_seconds <= 0:
            return 0

        owed_class = owed_class or { }
        eligible   = { }
        for row in ( snapshot or { } ).get( "sessions", [ ] ):
            if not isinstance( row, dict ) or row.get( "role" ) != "manager":
                continue
            sid = row.get( "session_id" )
            if not sid:
                continue
            liveness = row.get( "liveness" )
            age      = liveness.get( "freshest_age_s" ) if isinstance( liveness, dict ) else None
            # corpse ceiling: eligible iff the age lands inside [threshold, max_age];
            # None (no signal ever) is a corpse/malformed row, never a dark manager.
            if age is not None and \
               self.manager_stale_poke_threshold_seconds <= age <= self.manager_stale_poke_max_age_seconds:
                eligible[ sid ] = ( row, age )

        # episode end: a manager freshened (or left the roster) → clear state so
        # the cap + advisory re-arm for any future episode (mirrors _auto_poke).
        for sid in [ s for s in self._mgr_stale_since if s not in eligible ]:
            del self._mgr_stale_since[ sid ]
            self._mgr_poke_count.pop( sid, None )
            self._mgr_advised.discard( sid )

        # L1 store-awareness re-arm (lane 4): a previously-suppressed BLOCKED/DONE
        # manager that freshened below threshold (left `eligible`) clears its SHARED
        # case-16/17 advised flag so a FUTURE blocked/done episode re-notifies once.
        for sid in [ s for s in self._mgr_stale_suppressed if s not in eligible ]:
            kind, persona = self._mgr_stale_suppressed.pop( sid )
            if kind == CLASS_BLOCKED_ON_USER:
                self._manager_blocked_advised.discard( persona )
            else:
                self._manager_done_advised.discard( persona )

        fired = 0
        for sid, ( row, age ) in eligible.items():
            persona = row.get( "persona" ) or sid
            cls     = owed_class.get( persona, CLASS_UNKNOWN )
            # L1 store-awareness: a manager whose owed work is entirely Rick-gated
            # (BLOCKED_ON_USER) or zero (DONE) is NOT stale — its silence is the
            # CORRECT waiting/finished state. Suppress the repeating case-14 poke;
            # emit at most ONE case-16/17 advisory (SHARED advised-sets with
            # _check_manager_acks → cross-detector de-dupe, no Rick double-page).
            if cls == CLASS_BLOCKED_ON_USER:
                if persona not in self._manager_blocked_advised:
                    self._manager_blocked_advised.add( persona )
                    self._mgr_stale_suppressed[ sid ] = ( CLASS_BLOCKED_ON_USER, persona )
                    self._route(
                        CASE_MANAGER_AWAITING_USER,
                        f"MANAGER-AWAITING-RICK (advisory, NOT manager-stale): {persona} is "
                        f"silent {_fmt_minutes( age )} but correctly BLOCKED on Rick — every "
                        f"owed item is Rick-gated. The silence IS the expected state, not a "
                        f"stall; one-time notice, no poke.",
                        active_managers=active_managers,
                    )
                continue
            if cls == CLASS_DONE:
                if persona not in self._manager_done_advised:
                    self._manager_done_advised.add( persona )
                    self._mgr_stale_suppressed[ sid ] = ( CLASS_DONE, persona )
                    self._route(
                        CASE_MANAGER_DONE_ADVISORY,
                        f"MANAGER-DONE (advisory, NOT manager-stale): {persona} is silent "
                        f"{_fmt_minutes( age )} and owes NO non-terminal work — it appears "
                        f"finished/idle. Consider reaping it (the arbiter never reaps). "
                        f"One-time notice, no poke.",
                        active_managers=active_managers,
                    )
                continue
            # ACTIVE / UNKNOWN → today's case-14 poke + Rick advisory (UNKNOWN = fail-SAFE)
            if sid not in self._mgr_stale_since:
                self._mgr_stale_since[ sid ] = now                # episode start
                self._mgr_poke_count[ sid ]  = 0
            if sid not in self._mgr_advised:                      # Rick advisory: FIRST crossing, same poll as poke #1
                self._mgr_advised.add( sid )
                # age is never None here — the corpse-ceiling eligibility gate
                # excludes None-age rows, so last_seen is always computable.
                last_seen = now - datetime.timedelta( seconds=age )
                self._route(
                    CASE_MANAGER_STALE_ADVISORY,
                    f"MANAGER-STALE: {persona} silent {_fmt_minutes( age )} "
                    f"(last signal {_fmt_eastern( last_seen )}, threshold "
                    f"{self.manager_stale_poke_threshold_seconds}s) — poking (bounded, "
                    f"≤{self.poke_max_per_episode}/episode); outreach only, no action taken.",
                    active_managers=active_managers,
                )
            if self._mgr_poke_count[ sid ] < self.poke_max_per_episode:
                body        = self._format_manager_stale_poke( row, age )
                outreach_id = self._mint_outreach_id()
                self._log_outreach( "manager_stale_poke", "send_to", [ persona ], body,
                                    session_id=sid, persona=persona,
                                    outreach_id=outreach_id )
                # no ack owed: the poke targets a DARK session (it may have no
                # self-wake); the case-14 Rick advisory is the load-bearing output
                self._emit_dm( outreach_id, "manager_stale_poke", persona, body,
                               session_id=sid, expects_ack=False )
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
              preconditions from { tier_disabled, not_manager, no_signal,
                not_stale, beyond_max_age, mgr_capped }; never raises
            - corpse-ceiling fix (2026-06-11): a None age reads `no_signal`
              (corpse/malformed — flipped from eligible) and an age past the
              ceiling reads `beyond_max_age` (a corpse resurfaced by the
              include_offline snapshot, not a recently-dark manager)
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
        if age is None:
            return [ "no_signal" ]
        if age < self.manager_stale_poke_threshold_seconds:
            return [ "not_stale" ]
        if age > self.manager_stale_poke_max_age_seconds:
            return [ "beyond_max_age" ]
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
            outreach_id = self._mint_outreach_id()
            self._log_outreach( "poll_error_escalation", "notify", [ "rick" ], body,
                                outreach_id=outreach_id )   # post-game F1
            self._emit_to_rick( outreach_id, "poll_error_escalation", body )
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
