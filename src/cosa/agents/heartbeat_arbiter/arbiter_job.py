#!/usr/bin/env python3
"""
Heartbeat Arbiter — the consumer job (Rachel's wiring lane).

The cross-fleet consumer of the local Heartbeat Hook's event exhaust
(arbiter design `03`). Each poll it:

    1. tails ~/.claude/heartbeat-events/*.jsonl from tracked offsets (new only),
    2. accumulates a bounded per-session tail,
    3. asks the gateway who is active (commons_who),
    4. builds the fleet view (the build_fleet_view leaf),
    5. builds the dependency graph + deadlock cycles (build_graph leaf),
    6. auto-pings blockers: throttled, per-edge backoff, global rate cap,
       clear-on-resume,
    7. builds the hybrid trust-labeled idle-roster (build_roster leaf),
    8. surfaces roster + blocked-graph + stuck + deadlocks to the manager as a
       sensor and recommender (the manager actuates reassignment; the
       arbiter never auto-assigns).

**Invariant:** the arbiter is an additive observer of the Hook's
exhaust and never a dependency of any local poke. It reads files and posts
commons messages, so it cannot corrupt a session's local state. It degrades
safe: if the arbiter is down, every Hook still pokes.

Testability: extends AgenticJobBase (CJ Flow agentic job, like HeartbeatPokerJob).
It takes the same injected seams. One is a `Clock` (FakeClock drives the
poll/hard-cap loop without real waiting). The other is an `ArbiterGateway`
(FakeGateway records who/send_to/post). Pure decision logic lives in the leaves; this composes them.
"""
import asyncio
import datetime
import json
import os
import uuid
import zoneinfo
from typing import Callable, List, Optional, Protocol, runtime_checkable

from cosa.agents.agentic_job_base import AgenticJobBase
# Reuse the Hook-Poker's clock seam (DRY — same SystemClock / FakeClock pattern).
from cosa.agents.heartbeat_poker_job import Clock, SystemClock

from cosa.agents.heartbeat_arbiter.events_tail import tail_fleet_events, load_offsets, save_offsets
from cosa.agents.heartbeat_arbiter.arbiter_state import (
    FleetEventAccumulator, PingLedger, DEFAULT_TAIL_MAXLEN,
)
from cosa.agents.heartbeat_arbiter.fleet_data_model import build_fleet_view
from cosa.agents.heartbeat_arbiter.dependency_graph import (
    build_graph, build_store_wait_edges, build_store_blocked_item_index,
    cycle_is_store_backed, hold_is_stale,
    hold_contradicts_peer_edge, build_wait_edges, find_deadlock_cycles, session_is_stale,
    edge_is_store_backed,
)
from cosa.agents.heartbeat_arbiter.idle_roster import build_roster
from cosa.agents.heartbeat_arbiter import ping_throttle
# v2.1 direct-state visibility (design 03 §10.2-§10.4): per-session liveness off
# the bridge-mtime clock, change-or-tick render, and the queryable snapshot push.
from cosa.agents.heartbeat_arbiter.fleet_render import (
    build_snapshot, carry_forward_lineage, compute_liveness, frame_signature,
    prune_offline_rows, render_fleet_table, render_tick,
)
from cosa.agents.heartbeat_arbiter.arbiter_journal import (
    make_log_fn, DELIVERED_OUTCOMES, resolve_tz, format_outreach_ts,
)
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
    find_session_by_id as _find_session_by_id,
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
    CASE_USER_GATE_RESURFACE, CASE_OPERATOR_GATE,
    CASE_STUCK_MANAGER_RICK_ONLY,
)
from lupin_mcp.persona_normalization import canonical_persona_key
# 6929f4ac outward-twin backstop (§9.2): the pure hold/gate readers reused so the
# arbiter resurfaces a dark session's aged user-gate to Rick.
from lupin_cli.claude_code.hooks.lib.heartbeat_hold import get_pending_user_gates, hold_path, declared_work_owed, is_honored
from lupin_cli.claude_code.hooks.lib.heartbeat_user_gates import open_gates, aged_open_gates, derive_user_chase_until
# b33c8e96: cross-package SINGLE source of truth for the arbiter-poke sentinel. Both
# poke bodies below DERIVE their prefix from this constant so the emitter (here) and
# the Stop-hook matcher (is_heartbeat_poke_prompt) cannot drift — a wrapped arbiter
# poke must NOT reset the recipient's Stop-hook poke-cap (user_prompt_submit.py:86).
from lupin_cli.claude_code.hooks.lib.heartbeat_work_owed import ARBITER_POKE_SENTINEL
# Proactive-manager A2/A3 (fcb5dbc0): the PURE D4 operator-gate urgency router — the
# arbiter is its single thin consumer (interrupt urgent / digest normal / queue low).
from cosa.agents.heartbeat_arbiter.operator_gate_routing import (
    route_operator_gates, DEFAULT_DIGEST_CADENCE_SECONDS,
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

# A2/A3 (fcb5dbc0): cap on the number of gate titles listed inline in the operator-
# gate NORMAL digest message; overflow folds into "+N more" (keeps the Rick-bound
# advisory readable when many normal gates are pending).
OPERATOR_DIGEST_LIST_CAP = 8

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
    CASE_USER_GATE_RESURFACE    : "user_gate_resurface",     # 6929f4ac (2026-06-22)
    CASE_OPERATOR_GATE          : "operator_gate",           # A2/A3 (fcb5dbc0)
}

# Item C (2026.06.24) — the ROUTINE persona-bound shoulder-taps subject to the
# trailing-window outreach throttle (the noise Rick is targeting: the phantom-prone
# blocker-ping storm + the manager-tap cadence). DELIBERATELY EXCLUDES every
# Rick-bound escalation (deadlock #5, manager-down #9, decision #10, orphan #8,
# stall #11, fleet-dark, manager-stale-advisory, reap-rec, operator-gate): those are
# TRACKED-but-NEVER-SUPPRESSED — capping a real alert to save noise is the failure we
# must avoid (Rick-ratification-pending safety carve-out, Mr Radio 2026-06-24). The
# DIRECT-send pokes (stuck_poke, manager_stale_poke) are EXCLUDED too — they carry
# their OWN per-episode caps (poke_max_per_episode / mgr poke caps), so layering the
# trailing-window cap there would double-throttle AND skew the episode counters.
THROTTLEABLE_CASES = frozenset( { 4, 7 } )   # 4 = blocker ping · 7 = manager tap

# ── L1 store-classification constants (2026-06-17, arbiter detector gaps) ────
# Each tapped/owed-candidate manager is classified ONCE per poll from a
# swallow-safe store read (the injected owed_work_fn). The class drives whether
# the false-escalating detectors (D4 MANAGER-DOWN, D3 WHOLE-FLEET-STALL) suppress.
CLASS_BLOCKED_ON_USER = "blocked_on_user"   # every non-terminal owed item is Rick-gated → not down, not a stall
CLASS_DONE            = "done"              # zero non-terminal owed items → consider-reaping, not down
CLASS_ACTIVE          = "active"           # has ≥1 normal (non-Rick-gated) owed item → today's behavior
CLASS_UNKNOWN         = "unknown"          # store read failed / seam unwired → FAIL SAFE (today's behavior)

# ── audience-scoped poke gating (2026-07-19, Rick via María) ─────────────────
# The arbiter's outreach has THREE audiences, each independently silenceable
# under the `auto_poke_enabled` master. Audience is derived from the TARGET's
# `role` (see AutoPokeMixin.audience_for_role) for the two session-directed
# tiers; OPERATOR names the Rick-directed advisory stream the poke tiers emit.
AUDIENCE_WORKER   = "worker"     # stuck-tier poke at a non-manager session
AUDIENCE_MANAGER  = "manager"    # stuck-tier poke at a manager + the manager-staleness tier
AUDIENCE_OPERATOR = "operator"   # the poke subsystem's Rick-directed advisories (case 14 + reap-recommendation)

# Sentinel: distinguishes "_classify_owed must do its own owed read" (default)
# from "a pre-read owed dict (possibly None) was threaded in by the caller" — so
# the per-poll one-read can be SHARED with the deadlock corroboration source
# (build_store_wait_edges) without re-querying the store.
_UNREAD = object()

# The owed-classes that SUPPRESS a blocking escalation (lane 4, 2026-06-17): a
# session is "not owed" — not a stall, not down — iff its owed work is entirely
# Rick-gated (BLOCKED_ON_USER) or zero (DONE). ACTIVE / UNKNOWN never suppress
# (UNKNOWN is fail-SAFE: never silently swallow a real escalation).
NOT_OWED_CLASSES = ( CLASS_BLOCKED_ON_USER, CLASS_DONE )


def owed_class_suppresses( cls ):
    """
    Say whether an owed-work classification means "do not escalate".

    The single named home for that decision, so callers never re-inline it.

    Requires:
        - cls is a CLASS_* string (or any value; non-members → False)

    Ensures:
        - returns True iff cls in {CLASS_BLOCKED_ON_USER, CLASS_DONE}
        - `ACTIVE` / `UNKNOWN` / anything else → False (fail-SAFE); never raises
        - the manager-down ack, whole-fleet-stall and manager-staleness detectors
          share this one predicate, and so does the follow-through watcher, which
          reads the worker's declared not-owed state before firing a blocking
          escalation; one predicate keeps the watcher from duplicating the
          decision or contending over the poke path
    """
    return cls in NOT_OWED_CLASSES


def _default_owed_work_fn( personas ):   # pragma: no cover - production store-read IO boundary
    """
    Read each persona's non-terminal owed items from the task store.

    Returns { persona: [ { id, status, gate_class, blocked_by }, ... ] } of the
    items whose status is not in {done, dropped}. It uses one DB session per poll.
    See src/docs/fleet-liveness-and-task-store-architecture.md.

    Requires:
        - personas is an iterable of persona-name strings

    Ensures:
        - returns the per-persona non-terminal owed-item dict (a persona with no
          owed work maps to an empty list)
        - raising is acceptable here — the caller (_classify_owed) swallows any
          exception into the fail-SAFE `UNKNOWN` path (observer invariant)
        - this IO boundary is exercised at the :8000 integration tier; the
          classification logic that consumes the dict is unit-tested with an
          injected fake
    """
    from datetime import datetime, timezone
    from cosa.rest.db.database import get_db
    from cosa.rest.db.repositories.task_repository import TaskRepository
    _TERMINAL = ( "done", "dropped" )
    # PARKED-STATUS (2026-07-19): ONE clock for the whole poll. A per-persona
    # clock read could classify two personas against different instants and
    # straddle a park-expiry boundary mid-poll — reader #2 and reader #3 would
    # then disagree about a row for reasons no test could reproduce.
    now = datetime.now( timezone.utc )
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
            #
            # hide_parked=True (NOT owed_only): this reader selects ALL non-terminal
            # rows, which ALREADY contains parked ones, so SUPPRESSION alone is both
            # sufficient and correct — owed_only would wrongly narrow the arbiter to
            # queued/in_progress and drop the blocked rows its deadlock-corroboration
            # ring is built from. Expired-parked rows stay VISIBLE here: they have
            # rejoined, and the arbiter must see what the Stop hook is being poked about.
            items = repo.query_tasks(
                owner_persona = canonical_persona_key( persona ) or persona,
                hide_parked   = True,
                now           = now,
            )
            out[ persona ] = [
                { "id"            : str( it.id ),
                  "status"        : it.status,
                  "gate_class"    : it.gate_class,
                  "blocked_by"    : it.blocked_by,
                  # be56bff8: the per-USER gate-deferral source. The resurface leg
                  # derives user_chase_until from the blocked_by:[{kind:user}] rows'
                  # future chase, so a gate the seat deferred in the store stops the
                  # arbiter re-surfacing it too. Additive on a read that already runs.
                  "next_chase_ts" : it.next_chase_ts.isoformat() if it.next_chase_ts else None }
                for it in items if it.status not in _TERMINAL
            ]
    return out


def _default_known_owners_fn():   # pragma: no cover - production store-read IO boundary
    """
    Read the distinct owner_persona values across all store rows, any status.

    These are the personas the store knows as real owners of work, using one DB
    session per poll. They feed the `DONE` to `UNKNOWN` downgrade in
    `_classify_owed`; the logic that consumes them is unit-tested with a fake.

    Ensures:
        - returns an iterable of owner_persona strings (canonicalization happens in
          the caller `_read_known_owners`)
        - raising is acceptable — `_read_known_owners` swallows any exception into
          None (fail-SAFE: the downgrade goes inert, never mass-UNKNOWNs the fleet)
        - every status is read, not only non-terminal rows, because a finished
          persona with only terminal rows must stay a known owner so its
          completion still classifies as `DONE`; a would-be-`DONE` persona missing
          from this set is likely a re-spin or label mismatch, not completion
    """
    from cosa.rest.db.database import get_db
    from cosa.rest.db.repositories.task_repository import TaskRepository
    with get_db() as session:
        repo = TaskRepository( session )
        # unscoped_audit=True: this is a DELIBERATE full-store sweep — the arbiter's
        # known-owner fail-safe MUST see every owner, so it passes the guard's escape
        # (Rick's operational mandate, verbatim: "make sure the arbiter passes that
        # unscoped_audit flag in as true … the last thing we want is for the arbiter
        # to break"). include_terminal=True: a genuinely-finished persona (only
        # terminal rows) MUST remain a known owner so its real completion still
        # classifies DONE — so the ALL-status read is preserved (decision-5, verified).
        return {
            it.owner_persona
            for it in repo.query_tasks( unscoped_audit=True, include_terminal=True )
            if it.owner_persona
        }


def _default_operator_gates_fn():   # pragma: no cover - production store-read IO boundary
    """
    Read every open (non-terminal) `gate_class='operator'` item, fleet-wide.

    The arbiter is the single pusher of operator gates, using one DB session per
    poll. The read is by gate_class, not by session or persona, so it sees a gate
    whether the owning session is alive or dark.

    Ensures:
        - returns a list of { id, title, status, gate_class, urgency, owner_persona }
          for each open operator gate (urgency drives the routing tier)
        - raising is acceptable — the caller (_route_operator_gates) swallows any
          exception into an empty read (observer invariant: never crash the poll)
        - the routing logic that consumes the list
          (operator_gate_routing.route_operator_gates) is unit-tested with an
          injected fake
    """
    from cosa.rest.db.database import get_db
    from cosa.rest.db.repositories.task_repository import TaskRepository
    _TERMINAL = ( "done", "dropped" )
    with get_db() as session:
        repo  = TaskRepository( session )
        items = repo.query_tasks( gate_class="operator" )
        return [
            { "id"            : str( it.id ),
              "title"         : it.title,
              "status"        : it.status,
              "gate_class"    : it.gate_class,
              "urgency"       : it.urgency,
              "owner_persona" : it.owner_persona }
            for it in items if it.status not in _TERMINAL
        ]


# DM-as-liveness window (2026-06-17): bound the SENT-DM scan to the verdict's
# stale ceiling — a DM older than this ages to "offline" anyway, so a 1h lookback
# is the natural, index-cheap bound (mirrors fleet_render.DEFAULT_STALE_SECONDS).
_DM_ACTIVITY_LOOKBACK_SECONDS = 3600


def _default_dm_activity_fn():   # pragma: no cover - production store-read IO boundary
    """
    Read the latest sent-DM time per session, as DM-based liveness evidence.

    Returns { session_id: max(created_at) } over sent ai_to_ai DM rows in the
    last hour. The session_id is parsed from the DM sender_id's '#' suffix
    (format '<agent>@<project>.deepily.ai#<session_id>').

    Ensures:
        - returns { session_id: aware-datetime } of the latest SENT-DM per session
        - raising is acceptable — the caller swallows any exception into an inert
          empty map (observer invariant); the other 4 signals carry liveness
        - rows with no '#' suffix are skipped because they cannot be attributed
          to a session
        - only sent DMs count: a dormant recipient does not wake on an inbound
          DM, so received-DM liveness would over-report
        - the scan filters direction='ai_to_ai' and created_at >= since, and the
          created_at index keeps it cheap; the group-by lives inline, querying
          the model directly; the logic that consumes the map is unit-tested
          with an injected fake
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


def _default_hold_mtime_fn( session_id ):   # pragma: no cover - production hold-file mtime IO boundary
    """
    Read the mtime of a session's hold file, as hold-based liveness evidence.

    Returns the epoch-seconds mtime of the session's `.heartbeat-hold-<sid>.json`
    file (located via heartbeat_hold.hold_path), or None when no hold file
    exists or the stat fails.

    Ensures:
        - returns the hold-file mtime (epoch float) or None (no file / stat error)
        - never raises — a missing hold or stat hiccup degrades to None (the other
          5 signals carry liveness; additive and fail-safe per the observer invariant)
        - each Stop rewrites the file, so a fresh mtime shows the process is
          alive, which avoids a false manager-stale verdict at an interactive
          manager that refreshes its hold but posts nothing to commons
        - the arbiter calls this out-of-band in _publish_fleet_snapshot so
          compute_liveness stays pure; the logic that folds the mtime into the
          verdict is unit-tested with an injected fake
    """
    try:
        return os.path.getmtime( hold_path( session_id ) )
    except OSError:
        return None


def _default_transcript_mtime_fn( session_id ):   # pragma: no cover - production transcript-file mtime IO boundary
    """
    Read the mtime of a session's transcript file, as transcript-based liveness.

    Resolves the session's bridge dict via session_bridge.find_session_by_id
    (full-uuid or 8-char-prefix match, dead-PID-aware) and returns the
    epoch-seconds mtime of its `transcript_path` `.jsonl` file.

    Ensures:
        - returns the transcript-file mtime (epoch float) when resolvable
        - returns None on any failure (no bridge / no transcript_path / stat error)
        - never raises
        - the harness appends to that file on every assistant or tool event, so a
          fresh mtime shows the process is alive, even mid-plan when no Stop
          fires and the other six signals (bridge/event/commons/idle_prompt/dm/
          hold) have all aged past stale
        - a failure yields no signal, never a spurious fresh mtime, so a truly
          dark session still ages to stale
        - the arbiter calls this out-of-band in _publish_fleet_snapshot so
          compute_liveness stays pure; the logic that folds the mtime into the
          verdict is unit-tested with an injected fake
    """
    try:
        data = _find_session_by_id( session_id )
        transcript_path = data.get( "transcript_path" ) if isinstance( data, dict ) else None
        if not transcript_path:
            return None
        return os.path.getmtime( transcript_path )
    except OSError:
        return None


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

    The journal and commons speak UTC, so every human-facing advisory converts
    and labels the zone; a bare UTC time in text for the owner misleads.

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

    The impure integrator helper: reduces each live bridge to its session_id
    and persona name. The pure `build_fleet_view` then folds them into the
    union roster without doing IO.

    Ensures:
        - returns { session_id: persona_name|None } for each live bridge
        - never raises — a discovery hiccup yields {} so the observer poll
          degrades safe (the observer invariant)
        - a bridge makes a session a roster member even with no events; its
          bridge mtime (read separately in `_publish_fleet_snapshot`) supplies
          the bridge_age liveness signal
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
    Return the confirmed-dead session-ids among the fleet view, as a set[str].

    The impure death probe for `_publish_fleet_snapshot`: delegates to
    session_bridge.find_dead_sessions (unfiltered bridge scan plus kill -0).
    That helper trusts a host PID only when valid and leans toward alive.

    Ensures:
        - returns a set[str] subset of fleet_view's session-ids (empty on any error,
          in a container, or when nothing is positively dead)
        - never raises
        - a probe hiccup yields an empty set, and the snapshot then falls back to
          staleness (the observer invariant)
    """
    try:
        return _find_dead_sessions( fleet_view.keys() )
    except Exception:
        return set()


@runtime_checkable
class ArbiterGateway( Protocol ):
    """
    Injectable commons seam for the arbiter (server-side, in-process).

    Distinct from the Hook-Poker's CommonsGateway. The arbiter also needs
    `who()` (list active sessions for the secondary liveness signal and the
    roster) and `post()` (the manager surface). All I/O sits behind it.
    That makes it fully unit-testable with a FakeGateway.
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

    Exit disposition mirrors HeartbeatPokerJob: cancelled / hard-cap return
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
        offsets_state_path       : Optional[ str ]      = None,     # bug 5a1f17f8 (b): durable event offsets across restarts; None → in-memory only (today's behavior)
        tail_maxlen              : int                  = DEFAULT_TAIL_MAXLEN,
        tap_min_interval_seconds : int                  = 300,
        manager_ack_window_seconds : int                = 600,
        deadlock_dwell_seconds     : int                = 300,    # store-backed ring must PERSIST this long before escalating (progressing-wait belt; 0 → fire on first corroborated sight)
        fleet_stall_window_seconds : int                = 1800,
        poll_error_escalate_threshold : int             = 3,
        auto_poke_enabled        : bool                 = True,
        # AUDIENCE SCALPEL (2026-07-19, Rick via María): three audience-scoped gates
        # UNDER the `auto_poke_enabled` master. Master off ⇒ all silent (the panic
        # button); master on ⇒ each audience is independently silenceable (the
        # scalpel). All default True ⇒ behavior-neutral when unconfigured.
        poke_workers_enabled     : bool                 = True,
        poke_managers_enabled    : bool                 = True,
        poke_operator_enabled    : bool                 = True,
        poke_stall_threshold_seconds : int              = 720,    # ~12 min
        poke_max_per_episode     : int                  = 3,
        stuck_poke_min_interval_seconds : int           = 0,      # bug 5a1f17f8 (c): min seconds between consecutive stuck-pokes to one session; 0 → disabled (poll-cadence, today's behavior)
        manager_stale_poke_threshold_seconds : int      = 2700,   # post-game F2 (~45 min; 0 disables)
        manager_stale_poke_max_age_seconds : int        = 7200,   # corpse ceiling (~2h; must be > threshold)
        manager_stale_velocity_suppress_streak : int    = 2,      # item 285c0343 Lever B: >= N consecutive episodes whose last-signal ADVANCED ⇒ alive-on-a-cadence ⇒ suppress the staleness poke; 0 disables. Ctor default (NOT INI day-one — a tunable, not a safety switch; INI promotion is the follow-on IF live tuning is wanted).
        manager_advisory_cooldown_seconds : int          = None,   # bug 58660c64: min seconds between case-16/17 advisories for the SAME (family, persona), independent of the flappy shared advised flag — kills the cross-detector ping-pong loop-fire. None → default to manager_stale_poke_threshold_seconds (one advisory per blocked-episode window). 0 disables the cooldown (legacy per-tick behavior). Ctor default, INI-promotable.
        # Role-goal poke echoes (role-goals Phase 2-3, 2026-06-24). The role-selected
        # north-star goal lines APPENDED to the stuck-poke + manager-staleness poke
        # bodies. Default None = inert (legacy in-pool construction unchanged); the
        # :8001 factory reads the `heartbeat manager/worker goal line` INI keys and
        # passes them. Canonical text: planning-is-prompting -> workflow/role-goals.md.
        manager_goal_line        : Optional[ str ]      = None,
        worker_goal_line         : Optional[ str ]      = None,
        # Item B (2026.06.24): outreach-timestamp tz. The stamp '[YYYY.MM.DD at HH:MM:SS]'
        # prefixed to every human-facing outreach message is rendered in this tz
        # (REUSES arbiter_journal.resolve_tz + the INI key `arbiter journal local
        # timezone`; None → America/New_York, DST-aware EDT/EST, degrade-safe to UTC).
        local_timezone_name      : Optional[ str ]      = None,
        # Item C (2026.06.24): trailing-window outreach-DM throttle (N msgs / Y min),
        # PER-RECIPIENT. Both default 0 → DISABLED (fail-safe: never suppress); the
        # :8001 factory reads the two runtime-tunable INI keys. SAFETY carve-out:
        # only routine persona-bound shoulder-taps are suppressed — Rick-bound
        # deadlock/manager-down/decision escalations are TRACKED but NEVER suppressed.
        outreach_throttle_max_messages   : int          = 0,      # N (0 → throttle disabled)
        outreach_throttle_window_minutes : int          = 0,      # Y (0 → throttle disabled)
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
        hold_mtime_fn            : Optional[ Callable ] = None,   # task 70be69f2: per-session hold-file mtime reader (None → real reader; hold-as-liveness)
        transcript_mtime_fn      : Optional[ Callable ] = None,   # bug fb332fcd: per-session transcript-file mtime reader (None → real reader; transcript-as-liveness, 7th signal)
        owed_work_fn             : Optional[ Callable ] = None,   # L1: per-poll store read (None → inert; classify UNKNOWN → fail-safe)
        known_owners_fn          : Optional[ Callable ] = None,   # 262c59f6 (A): fleet-wide known-owner-persona read () -> [canonical keys] (None → inert; DONE→UNKNOWN fail-safe never fires)
        hold_reader_fn           : Optional[ Callable ] = None,   # 6929f4ac: per-session hold reader (session_id) -> hold|None (None → inert: classify-override + resurface tier never fire)
        user_gate_resurface_seconds : int               = 1800,  # 6929f4ac: aged-gate ceiling (30 min) — resurface a DARK session's open gate older than this to Rick
        operator_gates_fn        : Optional[ Callable ] = None,   # A2/A3 (fcb5dbc0): fleet-wide open-operator-gate store read () -> [gate-dict] (None → inert: operator-gate routing never fires)
        operator_digest_cadence_seconds : int           = DEFAULT_DIGEST_CADENCE_SECONDS,  # A2/A3: NORMAL-urgency operator-gate digest cadence (30 min)
        worktree_janitor_fn      : Optional[ Callable ] = None,   # §4b janitor: per-poll abandoned-worktree reconcile (None → INERT, no sweep). The :8001 factory wires fleet_arbiter_loop.make_worktree_janitor_fn when `arbiter worktree janitor enabled` — since 2026-09-14 (row 033538f6); before that this comment claimed it did and it did not
        bridge_sweep_fn          : Optional[ Callable ] = None,   # ee59d5ed: per-poll orphan-bridge reconcile () -> {reaped:[...]} (None → INERT; the :8001 factory wires orphan_bridge_reaper.reconcile_orphan_bridges bound to a persistent debounce-state dict)
        count_dm_as_liveness_fn  : Optional[ Callable ] = None,   # DM-toggle: per-poll INI re-read (None → lambda True; runtime-tunable)
        dm_activity_fn           : Optional[ Callable ] = None,   # DM-toggle: per-poll SENT-DM store read (None → inert; dm_ts None everywhere)
        bridge_mtimes_fn         : Optional[ Callable ] = None,   # bug 26dd3afb: () -> {canonical_persona_key: freshest bridge mtime}; None → MANAGER-STALE veto INERT (fail-safe, today's behavior)
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
            - quiet_threshold_seconds < alive_threshold_seconds (otherwise
              the inference idle-window is empty)
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
        if stuck_poke_min_interval_seconds < 0:
            raise ValueError( f"stuck_poke_min_interval_seconds must be >= 0, got {stuck_poke_min_interval_seconds}" )
        # post-game F2: 0 disables the manager-staleness tier; negative is a config bug.
        if manager_stale_poke_threshold_seconds < 0:
            raise ValueError( f"manager_stale_poke_threshold_seconds must be >= 0, "
                              f"got {manager_stale_poke_threshold_seconds}" )
        # item 285c0343 Lever B: 0 disables the velocity suppression; negative is a config bug.
        if manager_stale_velocity_suppress_streak < 0:
            raise ValueError( f"manager_stale_velocity_suppress_streak must be >= 0, "
                              f"got {manager_stale_velocity_suppress_streak}" )
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
        # 6929f4ac: a zero/negative resurface ceiling would config-dead the outward-
        # twin backstop (an aged-gate window with no floor) — fail fast, same guard
        # bug-class as quiet < alive above.
        if user_gate_resurface_seconds <= 0:
            raise ValueError( f"user_gate_resurface_seconds must be positive, got {user_gate_resurface_seconds}" )
        # A2/A3 (fcb5dbc0): a zero/negative digest cadence would config-dead the
        # NORMAL-urgency digest debounce (same fail-fast bug-class as above).
        if operator_digest_cadence_seconds <= 0:
            raise ValueError( f"operator_digest_cadence_seconds must be positive, got {operator_digest_cadence_seconds}" )

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
        # ff91cff4: the canonical-key set of declared managers — the authority the
        # manager-subject routing guard (`_subject_is_manager`) keys on, MIRRORING
        # build_snapshot's `is_declared` role assignment (canonical persona key vs
        # the declared roster). Precomputed once; the raw fleet_view rows passed to
        # _tap_managers / _auto_poke carry no `role` (added later in build_snapshot),
        # so the guard resolves manager-ness from the persona against THIS set.
        self._declared_manager_keys  = { canonical_persona_key( str( m ) )
                                         for m in self.declared_managers
                                         if canonical_persona_key( str( m ) ) }
        self.alive_threshold_seconds = alive_threshold_seconds
        self.quiet_threshold_seconds = quiet_threshold_seconds
        self.ping_global_cap         = ping_global_cap
        self.ping_cap_window_seconds = ping_cap_window_seconds
        self.max_duration_seconds    = max_duration_seconds
        self.events_dir              = events_dir
        self._offsets_state_path     = offsets_state_path          # bug 5a1f17f8 (b): durable-offset store path (None → inert)

        # --- injected seams ---
        self._commons   = commons
        self._clock     = clock if clock is not None else SystemClock()
        self._notify_fn = notify_fn if notify_fn is not None else self.notify_progress
        # v2.1 seams: bridge-mtime liveness reader, snapshot sink (in-pool →
        # server singleton), and the render sink (greppable log; default stdout,
        # captured by the container log). All injectable for 100% unit testing.
        self._bridge_mtime_fn = bridge_mtime_fn if bridge_mtime_fn is not None else _default_bridge_mtime_fn
        # task 70be69f2 hold-as-liveness seam: per-session hold-file mtime reader.
        # Defaults to the REAL reader (like bridge_mtime_fn, NOT None-inert) — a fresh
        # hold mtime is an unconditional fail-safe sign of life that can only ADD
        # liveness, never suppress a dark session, so it is safe live-by-default and
        # needs no factory wiring. A non-existent hold (unit fake-id sessions) stats
        # to None, so unit/in-pool construction stays clean without injection.
        self._hold_mtime_fn   = hold_mtime_fn if hold_mtime_fn is not None else _default_hold_mtime_fn
        self._transcript_mtime_fn = transcript_mtime_fn if transcript_mtime_fn is not None else _default_transcript_mtime_fn
        # bug 26dd3afb MANAGER-STALE bridge-mtime veto seam: () -> {canonical_persona_key:
        # freshest bridge-file mtime}. UNLIKE the mtime readers above this defaults to
        # None-INERT (NOT a real reader) — the veto is a NEW suppressor, so an unwired
        # seam must degrade to TODAY'S behavior (never silently suppress a genuine dark
        # manager). The :8001 factory wires the real persona-scan reader.
        self._bridge_mtimes_fn = bridge_mtimes_fn
        # L1 (2026-06-17) store-awareness seam: per-poll owed-work reader (the
        # arbiter as reader #2 of the one-store/three-readers design). Default
        # None keeps the seam INERT — every manager classifies UNKNOWN → the two
        # false-escalating detectors preserve TODAY'S behavior (fail SAFE; never
        # silently suppress). The :8001 factory wires _default_owed_work_fn so the
        # suppression actually activates live; in-pool / unit-fake construction
        # stays inert unless a fake is injected. (Mirrors the Item B None-seam
        # pattern: a None seam is visibly inert, never a hidden behavior change.)
        self._owed_work_fn = owed_work_fn
        # 262c59f6 (A) known-persona fail-safe seam: the fleet-wide KNOWN-OWNER read
        # (distinct owner_persona over all store rows → canonical keys). None keeps it
        # INERT — the _classify_owed DONE→UNKNOWN downgrade never fires, so unit-fake
        # construction needs no wiring (byte-identical to today). The production paths
        # WIRE _default_known_owners_fn so the belt against re-spin/label-contamination
        # false MANAGER-DONE activates live. Mirrors the owed_work_fn None-seam pattern.
        self._known_owners_fn = known_owners_fn
        # 6929f4ac outward-twin backstop (§9.2): the per-session hold reader. None
        # keeps the seam INERT — the _classify_owed open-gate→ACTIVE override and the
        # user-gate resurface detector both no-op — so unit-fake construction needs no
        # wiring. The production paths WIRE heartbeat_hold.read_hold (project-root
        # scoped): the :8001 fleet-arbiter factory (lupin_arbiter_app/fleet_arbiter_loop.py),
        # the in-process bootstrap (cosa/rest/arbiter_bootstrap.py), and the dev runner
        # (scripts/run-heartbeat-arbiter.py). Mirrors the owed_work_fn seam pattern.
        self._hold_reader_fn            = hold_reader_fn
        self.user_gate_resurface_seconds = user_gate_resurface_seconds
        # A2/A3 (fcb5dbc0) operator-gate routing seam: the fleet-wide open-operator-
        # gate store read. None keeps it INERT (the routing never fires → unit-fake
        # construction needs no wiring; byte-identical to today). The :8001 factory +
        # in-process bootstrap WIRE _default_operator_gates_fn so it activates live.
        # Mirrors the owed_work_fn / hold_reader_fn None-seam pattern.
        self._operator_gates_fn          = operator_gates_fn
        self.operator_digest_cadence_seconds = operator_digest_cadence_seconds
        # Per-arbiter routing state: the NORMAL-digest cadence clock (ISO str, None =
        # never emitted ⇒ first digest is due) + the escalate-once de-dup of URGENT
        # gates already interrupted (re-armed each poll to the present urgent set).
        self._last_operator_digest_ts    = None
        self._routed_operator_gates      = set()
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
        # §4b worktree janitor seam (Worktree Lifecycle Contract): None → INERT
        # (no reconcile, byte-identical to today). The :8001 factory wires
        # worktree_reaper.reconcile_worktrees (drain-then-remove of abandoned
        # sandbox worktrees; preserves WIP + keeps branches; never pushes). A
        # None seam is visibly inert, never a hidden behavior change.
        self._worktree_janitor_fn     = worktree_janitor_fn
        # ee59d5ed orphan-bridge janitor: per-poll lineage-independent reap of
        # CONFIRMED-dead orphan bridges (dual-confirm + debounce inside the seam).
        # None → visibly inert (today's behavior); the :8001 factory wires it.
        self._bridge_sweep_fn         = bridge_sweep_fn
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
        self.deadlock_dwell_seconds        = deadlock_dwell_seconds
        self.fleet_stall_window_seconds    = fleet_stall_window_seconds
        self.poll_error_escalate_threshold = poll_error_escalate_threshold
        # 2b-3 auto-poke (Rick redline-narrowing confirmed): bounded, non-destructive
        # wake-nudge at genuinely-stuck LIVE sessions, then a reap-RECOMMENDATION.
        self.auto_poke_enabled             = auto_poke_enabled
        # audience scalpel (2026-07-19): AND-gated UNDER auto_poke_enabled
        self.poke_workers_enabled          = poke_workers_enabled
        self.poke_managers_enabled         = poke_managers_enabled
        self.poke_operator_enabled         = poke_operator_enabled
        self.poke_stall_threshold_seconds  = poke_stall_threshold_seconds
        self.poke_max_per_episode          = poke_max_per_episode
        self.stuck_poke_min_interval_seconds = stuck_poke_min_interval_seconds     # bug 5a1f17f8 (c) fire-throttle
        # post-game F2: the SECOND, role-gated pokeable criterion — a MANAGER-role
        # session whose freshest union signal is older than this is poked + Rick-
        # advised even with zero stuck workers (the 2026-06-10 gap). 0 disables.
        self.manager_stale_poke_threshold_seconds = manager_stale_poke_threshold_seconds
        # corpse ceiling (2026-06-11): ages beyond this are corpse rows resurfaced
        # by the include_offline detection snapshot (the 10:52 EDT boot-burst:
        # yesterday's dead manager session poked with a bogus 1134m age on every
        # process start), never a live manager going dark — NOT eligible.
        self.manager_stale_poke_max_age_seconds   = manager_stale_poke_max_age_seconds
        # item 285c0343 Lever B: consecutive-advancing-episode streak at/above which the
        # manager-staleness poke is suppressed as alive-on-a-cadence (0 disables).
        self.manager_stale_velocity_suppress_streak = manager_stale_velocity_suppress_streak
        # bug 58660c64: case-16/17 advisory cooldown. None → tie to the staleness
        # threshold (one advisory per blocked-episode window). The cooldown is the
        # hard ceiling the cross-detector flag ping-pong cannot bypass (the acks-path
        # liveness re-arm discards the shared advised flag, but NOT this cooldown).
        self.manager_advisory_cooldown_seconds = (
            manager_advisory_cooldown_seconds if manager_advisory_cooldown_seconds is not None
            else manager_stale_poke_threshold_seconds
        )
        # Role-goal poke echoes (role-goals Phase 2-3): the role-selected north-star
        # goal lines appended to the stuck-poke (_format_poke, via view["role"]) and
        # the manager-staleness poke (_format_manager_stale_poke, always Manager).
        # None/"" ⇒ nothing appended (legacy body unchanged). Canonical text:
        # planning-is-prompting -> workflow/role-goals.md.
        self.manager_goal_line = manager_goal_line or ""
        self.worker_goal_line  = worker_goal_line  or ""
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
        # Item B (2026.06.24): resolve the outreach-stamp tz ONCE (REUSE
        # arbiter_journal.resolve_tz + the INI key `arbiter journal local timezone`;
        # None → America/New_York, DST-aware). resolve_tz is degrade-safe (invalid
        # name → UTC + an error string); we journal that error ONCE so a tz typo is
        # visible, never a silent UTC fallback.
        self._outreach_tz, _tz_err = resolve_tz( local_timezone_name )
        if _tz_err is not None:
            self._log_fn( "outreach_tz_invalid", detail=_tz_err )
        # Item C (2026.06.24): trailing-window outreach throttle config (N msgs / Y
        # min, PER-RECIPIENT). max <= 0 OR window <= 0 ⇒ DISABLED (fail-safe: never
        # suppress). Window stored in seconds (Y minutes → seconds).
        self._outreach_throttle_max            = outreach_throttle_max_messages
        self._outreach_throttle_window_seconds = outreach_throttle_window_minutes * 60

        # --- consumer state (carried across polls) ---
        # bug 5a1f17f8 (b): resume from the durable offset store on (re)start so a
        # :8001 bounce does NOT re-read every events file from byte 0 (the STUCK-poke
        # replay root cause). None path → {} = today's fresh-start behavior.
        self._offsets       = load_offsets( self._offsets_state_path ) if self._offsets_state_path else { }   # sid -> byte offset
        self._acc           = FleetEventAccumulator( maxlen=tail_maxlen )
        self._ledger        = PingLedger()
        self._ping_attempts = { }                                  # edge_key -> attempt count
        self._recent_pings  = [ ]                                  # list of ping datetimes (global-cap window)
        # Item C (2026.06.24) per-recipient outreach-DM throttle state: recipient
        # persona -> [ sent datetime, ... ] (trailing-window; pruned to the window on
        # each send). In-memory across polls (a restart resets the window — acceptable,
        # mirrors _awaiting_ack / _recent_pings). Feeds ping_throttle.trailing_window_allows.
        self._outreach_sent_ts = { }                               # recipient -> list[datetime]
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
        # de3c5b87/33949e83 ROOT FIX: the stuck-MANAGER-subject advisory (ff91cff4,
        # Rick-only case-20) throttles on a "stuck-mgr:<persona>" key. That key MUST
        # live in DEDICATED state — NOT _last_tap_at — because _last_tap_at feeds
        # eval_personas + the owed-read + _check_manager_acks as CLEAN manager personas.
        # A "stuck-mgr:Tiberius" key there canonicalizes to "stuckmgrtiberius" ≠ the
        # store owner "tiberius" → 0-row read → UNKNOWN (→ false MANAGER-DOWN) / DONE
        # (→ false MANAGER-DONE). Same throttle semantics, isolated key space.
        self._last_stuck_tap_sig = { }
        self._last_stuck_tap_at  = { }
        # v2.2 B4/D4 manager-ack tracking: managers already escalated as down for
        # their current (un-acked) tap — so manager-down escalates ONCE, not every
        # poll, until the manager re-acks (shows liveness after the tap).
        self._manager_down_escalated = set()
        # bug 436a366b deadlock state (store-corroborated rings only): per
        # ring-signature first-seen datetime (dwell/progressing-wait belt) + the
        # set of signatures already escalated (de-dup: fire ONCE per store-backed
        # ring). Both prune when a ring disappears (resolved → re-arm).
        self._deadlock_first_seen = { }
        self._deadlock_escalated  = set()
        # 6929f4ac: keys "<session_id>:<gate_id>" already resurfaced to Rick this
        # dark episode — escalate-once; re-arms when the gate clears or the session
        # freshens out of the eligible set (mirrors the _mgr_* episode trackers).
        self._resurfaced_gates = set()
        # L1 (2026-06-17) store-aware advisory tracking: a tapped-but-quiet manager
        # classified BLOCKED_ON_USER / DONE is NOT escalated MANAGER-DOWN — instead
        # it gets at most ONE advisory per un-acked tap. These sets are the
        # escalate-once flags (siblings of _manager_down_escalated); all three clear
        # together when the manager shows liveness after its tap (re-arm).
        self._manager_blocked_advised = set()   # awaiting-Rick advisory already fired
        self._manager_done_advised    = set()   # consider-reaping advisory already fired
        # bug 58660c64: per-(family, persona) advisory cooldown state (in-memory, NO
        # persistence — a single extra advisory after an :8001 restart is acceptable).
        # `_until` gates re-fire; `_suppressed` is the running suppression count fed to
        # the arbiter_advisory_suppressed_cooldown journal event (observability rider).
        self._advisory_cooldown_until     = { }   # (family, persona) -> datetime the cooldown expires
        self._advisory_suppressed_count   = { }   # (family, persona) -> count of re-fires suppressed this window
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
        self._poke_last_at     = { }                               # bug 5a1f17f8 (c): sid -> last stuck-poke datetime (fire-throttle)
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
        # item 285c0343 Lever B: cross-episode last-signal VELOCITY state. Keyed by
        # PERSONA (not sid) so it PERSISTS across the per-sid episode clear above (a
        # freshen wipes _mgr_stale_since/_mgr_poke_count but the cadence memory must
        # survive to compare episode N against N-1) and across re-spins. A manager
        # whose last-signal advances each episode is alive-on-a-cadence, not stale.
        self._mgr_last_signal_seen = { }                           # persona -> last-signal datetime captured at the prior episode start
        self._mgr_velocity_streak  = { }                           # persona -> count of consecutive episodes whose last-signal ADVANCED
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
        Run one arbiter poll: tail → view → graph → ping → roster → surface.

        Ensures:
            - reads new events, updates the fleet view, fires throttled pings,
              and posts the recommender surface to the manager
            - returns a small summary dict (for tests / logging)
            - never raises (a leaf/gateway hiccup is swallowed per the observer
              invariant) — see _execute's per-poll guard
        """
        now = datetime.datetime.fromisoformat( self._clock.now_iso() )

        new_events, self._offsets = tail_fleet_events( self.events_dir, self._offsets )
        # bug 5a1f17f8 (b): persist the advanced offsets so a restart resumes here,
        # not at byte 0. Swallow-safe (never raises) → a store hiccup degrades to the
        # in-memory path, never crashes the poll. Inert when no path is configured.
        if self._offsets_state_path:
            save_offsets( self._offsets_state_path, self._offsets )
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
        # bc1bc373 STALENESS-FILTER: drop a DEAD-hold holder's phantom peer edge
        # UPSTREAM of all edge inference (blocked-edge, deadlock cycles, the
        # manager-blocking advisory). Inert when the hold-reader seam is unwired
        # (None → empty set → today's behavior); the deadlock LOGIC is untouched.
        stale_holders = self._stale_hold_holders( fleet_view, now )
        # 8a450183 PERSONA-COLLAPSE filter: gate peer-edge inference on each HOLDER
        # SESSION's OWN freshness (per session-id, NOT persona) so a DEAD session's
        # stale `holding_on: peer:X` edge cannot ride a LIVE same-persona session's
        # liveness into the advisory/ping graph. Threaded ONLY here (the FILTERED
        # path); the UNFILTERED :1018 escalation feed below passes neither now nor
        # the threshold, so it stays BYTE-IDENTICAL (a real store-backed ring with a
        # dead participant must still escalate — Krishna A2).
        graph = build_graph( fleet_view, stale_holders=stale_holders,
                             now=now, alive_threshold_seconds=self.alive_threshold_seconds )

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
        owed_items  = self._read_owed( eval_personas )                    # ONE per-poll owed read, shared below
        known_owners = self._read_known_owners()                          # 262c59f6 (A): known store-owner set (None/empty → downgrade inert)
        store_degraded = self._store_read_degraded( owed_items, eval_personas )  # 33949e83: self-observed store outage → gate MANAGER-DOWN/STALE
        manager_bridge_mtimes = self._read_manager_bridge_mtimes()        # bug 26dd3afb: persona→bridge-mtime map for the MANAGER-STALE veto (None → inert)
        owed_class  = self._classify_owed( eval_personas, fleet_view, owed=owed_items, known_owners=known_owners )
        # bug 436a366b: the AUTHORITATIVE store dependency ring — the deadlock
        # escalation is corroborated against THIS, never the derived holding_on
        # edges alone. Built from the SAME owed read (one query per poll).
        store_edges = build_store_wait_edges( owed_items )

        # María review of bc1bc373/c88a7431 (CHANGES-REQUESTED): the deadlock
        # ESCALATION reads the UNFILTERED peer graph — NOT graph["cycles"] (which is
        # built with stale_holders and so is FILTERED). The bc1bc373 staleness-filter
        # correctly drops a dead-hold holder's phantom edge from the ADVISORY graph
        # ("X blocking Y"), but _stale_hold_holders is hold-FILE-only (zero store-
        # awareness): an alive-but-slow X with an EXPIRED hold AND a REAL store-backed
        # cycle (X→Y→X in the store's blocked_by) would have its peer edge filtered, the
        # cycle would drop out of graph["cycles"], and a GENUINE store-backed deadlock
        # would go UNESCALATED. cycle_is_store_backed (inside _escalate_deadlocks) stays
        # the gate — non-store phantoms still never escalate — and the ADVISORY path
        # keeps the filtered graph above; only this escalation feed is un-filtered.
        escalation_cycles = find_deadlock_cycles( build_wait_edges( fleet_view ) )
        self._escalate_deadlocks( escalation_cycles, store_edges, now, active_managers )  # #5 Rick + all mgrs (store-corroborated, UNFILTERED cycles)
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
        # B3 BACKING-OBLIGATION GATE (bug d44b7068): the "You're blocking worker Y"
        # ping is minted from the WAITER's self-reported `holding_on: peer:X` with NO
        # check that X actually OWES Y. A holder whose wait is already discharged (the
        # awaited peer delivered / owes nothing) re-pinged the innocent peer every
        # poll (Maria/Tiberius 2026-06-27; Krishna/Mr-Radio in the post-mortem). Gate
        # the ping on the AUTHORITATIVE store `blocked_by` graph (the single-edge
        # analog of the deadlock cycle_is_store_backed): fire ONLY when Y's store item
        # is really blocked_by X. FAIL-SAFE: when the owed read FAILED/unwired
        # (owed_items is None → store-backing UNKNOWN) keep today's behavior so a
        # store outage never silences a genuine blocker; a SUCCESSFUL read with no
        # backing edge SUPPRESSES the phantom. Mirrors the deadlock gate's
        # fail-SUPPRESS-on-no-backing / observer-invariant discipline.
        if owed_items is None:
            ping_edges = live_edges                                       # store UNKNOWN → fail-SAFE (today's behavior)
        else:
            ping_edges = { h: a for h, a in live_edges.items()
                           if edge_is_store_backed( h, a, store_edges ) }
        # bug ce13b134: the blocked-ITEM leg of the blocker-cc idempotency key —
        # { (canonical_holder, canonical_awaited): frozenset(item_ids) } from the SAME
        # per-poll owed read (empty when the store read failed → the cc dedup falls
        # back to a persona-only key + clear-on-resume).
        edge_items  = build_store_blocked_item_index( owed_items )
        pings_fired = self._auto_ping( ping_edges, now, persona_to_sid, edge_items )  # #4 blocker + cc mgr (store-backed only)
        roster      = build_roster( fleet_view, now, self.quiet_threshold_seconds,
                                     alive_threshold_seconds=self.alive_threshold_seconds )  # free-count fix: live-idle only (session_is_stale gate)
        # #6 roster broadcast DROPPED (Part-6 cut) — the fleet roster is PULL-state,
        # served by /state via the snapshot below; no per-tick commons post.
        designed_holds = self._designed_hold_personas( owed_items )  # cec10ef9: store-backed review-gate-hold suppression (reuses the per-poll owed read @ :1236)
        # bug 1ff7be20: the blocked-edge ROSTER leg gets the same store corroboration the
        # PING leg already has (d44b7068 @ :1285) — the SAME per-poll store wait-graph, no
        # re-query. owed_items None ⇒ the read FAILED/is unwired ⇒ backing UNKNOWN ⇒ pass
        # None ⇒ NO filtering (FAIL-SAFE to ROSTER: a store outage never silences a real
        # block). Mirrors ping_edges' fail-safe branch exactly.
        tap_store_edges = None if owed_items is None else store_edges
        taps_fired    = self._tap_managers( fleet_view, graph, roster, now, active_managers, bridge_mtimes=manager_bridge_mtimes, designed_hold_personas=designed_holds, store_edges=tap_store_edges )  # #7 / #8 (bug bf8c5cbb: bridge-fresh peers count alive in the blocked-roster; cec10ef9 designed-hold suppression; 1ff7be20 store-corroborated blocked-edge roster)
        managers_down = self._check_manager_acks( now, who_rows, fleet_view, active_managers, owed_class=owed_class, count_dm=count_dm, owed_items=owed_items, store_read_degraded=store_degraded )  # #9 (L1 store-aware, 5-signal ACK; owed_items → de3c5b87/33949e83 diagnostics; store gate)
        decisions     = self._check_decision_needed( now )          # #10 Rick (+owning mgr if known)
        stalled       = self._check_fleet_stall( fleet_view, now, active_managers, owed_class=owed_class )  # #11 (L1 store-aware)
        pokes_fired   = self._auto_poke( fleet_view, now, active_managers, owed_class=owed_class, bridge_mtimes=manager_bridge_mtimes )  # 2b-3 auto-poke (262c59f6 store-aware; bug 92c7ab1d bridge-mtime sign-of-life veto)
        rendered      = self._publish_fleet_snapshot( fleet_view, now, count_dm )
        # post-game F2/F3 detectors read the FULL (include_offline=True) detection
        # snapshot + published count the publish step just stashed on the instance.
        manager_stale_pokes = self._check_manager_staleness( self._last_full_snapshot, now, active_managers, owed_class=owed_class, store_read_degraded=store_degraded, bridge_mtimes=manager_bridge_mtimes )  # #F2 (L1 store-aware, lane 4; 33949e83 store gate; bug 26dd3afb bridge-mtime veto)
        fleet_dark          = self._check_fleet_dark( self._last_full_snapshot, self._last_published_n, now )
        # 6929f4ac outward-twin backstop: resurface a dark session's aged user-gate
        # to Rick (case 18). Reads the FULL snapshot (offline rows included) so a
        # gone-dark session's buried gate is still seen. The production factories wire
        # hold_reader_fn (read_hold) so this is LIVE on :8001; unit-fake construction
        # leaves it None → inert.
        gates_resurfaced    = self._check_user_gate_resurface( self._last_full_snapshot, now, owed_items=owed_items )
        # A2/A3 (fcb5dbc0): the arbiter's single-pusher operator-gate routing — read
        # ALL open operator gates (store, fleet-wide → covers dark + alive), route by
        # D4 urgency (urgent interrupt / normal digest / low pull-only). Inert until
        # the operator_gates_fn seam is wired (the :8001 factory + bootstrap wire it).
        operator_gates_routed = self._route_operator_gates( now )
        # post-game F1: why-not-poked gate evaluation — runs AFTER both poke tiers
        # so the emitted vectors reflect this poll's episode state.
        self._emit_poke_gates( fleet_view, self._last_full_snapshot, now )
        # Item B (2026.06.11): close the delivery loops — manager threaded-ack
        # receipts (§3.4) + Rick re-announce of pending advisories (§3.5).
        outreach_acks = self._check_outreach_receipts( now, offline_personas=self._confirmed_offline_personas(), bridge_mtimes=manager_bridge_mtimes )  # item 285c0343 Lever C: recipient bridge-activity since delivery = implicit ACK
        reannounces   = self._check_pending_outreach( now )
        # eng#7 (2026-06-17): ONE follow-through aged-escalation sweep on the poll
        # path (build-plan §3b). Doubly inert — no watcher wired OR flag OFF — and
        # swallow-safe (the observer invariant); see _sweep_follow_through.
        ft_escalated  = self._sweep_follow_through()
        # §4b worktree janitor (Worktree Lifecycle Contract): reconcile abandoned
        # sandbox worktrees (drain-then-remove; preserves WIP + keeps branches;
        # never pushes). Doubly inert — None seam → no work — and swallow-safe per
        # the observer invariant: a reconcile hiccup is demoted, never kills the
        # poll. Returns the count swept this poll for the summary/journal.
        worktrees_swept = 0
        if self._worktree_janitor_fn is not None:
            try:
                jr = self._worktree_janitor_fn()
                # Count REMOVALS, not attempts: a refused drain also lands in "swept" (the
                # refusal ledger reads it there), and counting it made the journal read
                # "worktrees_swept: 17" every poll while nothing left disk (2026-09-29).
                worktrees_swept = sum( 1 for e in jr.get( "swept", [] )
                                       if isinstance( e, dict ) and ( e.get( "result" ) or {} ).get( "removed" ) ) if isinstance( jr, dict ) else 0
            except Exception:
                worktrees_swept = 0

        # ee59d5ed orphan-bridge janitor: reap CONFIRMED-dead orphan bridges whose
        # dead spawner left them unreachable by any dismiss (lineage-independent).
        # The seam owns dual-confirm (PID-dead AND tmux-gone) + the N-poll debounce
        # + all reap emits; here we only invoke + count. Doubly inert (None seam →
        # no work) and swallow-safe per the observer invariant — a sweep hiccup is
        # demoted, never kills the poll.
        bridges_reaped = 0
        if self._bridge_sweep_fn is not None:
            try:
                br = self._bridge_sweep_fn()
                bridges_reaped = len( br.get( "reaped", [] ) ) if isinstance( br, dict ) else 0
            except Exception:
                bridges_reaped = 0

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
            "gates_resurfaced"    : gates_resurfaced,         # 6929f4ac outward-twin backstop
            "bridges_reaped"      : bridges_reaped,            # ee59d5ed orphan-bridge janitor
            "operator_gates_routed" : operator_gates_routed,  # A2/A3 operator-gate urgency routing (fcb5dbc0)
            "outreach_acks"       : outreach_acks,
            "reannounces"         : reannounces,
            "ft_escalated"        : ft_escalated,            # eng#7 follow-through one-shot escalations this poll
            "worktrees_swept"     : worktrees_swept,         # §4b janitor: abandoned sandbox worktrees retired this poll
            "rendered"            : rendered,
        }
        # post-game F1: promote the summary to the journal whenever ANY outreach
        # counter is nonzero — a poll that communicated is never invisible.
        if any( summary[ k ] for k in (
                "pings_fired", "taps_fired", "managers_down", "decisions",
                "stalled", "pokes_fired", "manager_stale_pokes", "fleet_dark", "cycles",
                "gates_resurfaced", "operator_gates_routed", "outreach_acks", "reannounces",
                "ft_escalated", "worktrees_swept" ) ):
            self._log( "arbiter_poll_activity", **summary )
        return summary

    def _sweep_follow_through( self ):
        """
        Run one follow-through aged-escalation sweep on the arbiter poll path.

        Inert in two layers. One is no watcher wired (`follow_through_watcher_factory`
        was None). The other is a watcher wired with `follow through escalation
        enabled` False, where its own sweep_once() short-circuits with no DB access.

        Ensures:
            - no watcher → returns 0 (sweep_once never called)
            - watcher present → calls sweep_once() and returns its `escalated`
              count (0 when the flag is off, where sweep_once reports
              {enabled:False, escalated:0, …}); any exception is swallowed to a
              render-sink log and returns 0
            - never raises
            - a watcher or store hiccup is demoted to a render-sink line and never
              kills the poll; the watcher's own daemon `_loop` guards exceptions,
              but this direct sweep bypasses that loop, so the guard lives here
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
        Build, render and push the direct-state fleet snapshot.

        Requires:
            - fleet_view is the per-session view dict (build_fleet_view output)
            - now is an aware datetime
            - count_dm is the DM-as-liveness toggle (read once per poll in
              _poll_once), threaded to build_snapshot(count_dm_as_liveness=...):
              when True, dm_age joins the freshest-of union; when False, each row's
              liveness verdict is byte-identical to the prior 4-signal block

        Ensures:
            - reads each session's bridge-mtime (the wedge-resilient liveness
              clock) and hold-file mtime (hold-as-liveness) via the injected
              readers and builds the snapshot with state and liveness kept as
              orthogonal columns
            - builds one full snapshot (include_offline=True) and stashes it on
              self._last_full_snapshot for the manager-staleness and fleet-dark
              detectors, then derives the
              published live-only view via prune_offline_rows; render, frame
              signature and sink payload ride the published view, so the
              published contract is unchanged; self._last_published_n carries
              its row count
            - renders the full table when the semantic frame changed (or on the
              first poll), else a one-line tick with the duration-since-change,
              to the injected render sink (greppable log)
            - pushes the published snapshot to the injected sink (the in-pool
              arbiter's server singleton, surfaced by GET /api/arbiter/fleet-snapshot)
            - returns "table" or "tick" (for the poll summary)
        """
        bridge_mtimes = { sid: self._bridge_mtime_fn( sid ) for sid in fleet_view }
        # task 70be69f2 hold-as-liveness: each session's hold-file mtime (out-of-band
        # IO here, so compute_liveness stays pure). A fresh hold mtime folds into the
        # freshest-of union → an interactive manager that only Stop-refreshes its hold
        # reads LIVE, not MANAGER-STALE. Per-session reader degrades to None (no file).
        hold_mtimes   = { sid: self._hold_mtime_fn( sid ) for sid in fleet_view }
        # bug fb332fcd transcript-as-liveness: each session's transcript .jsonl
        # mtime (out-of-band IO here, so compute_liveness stays pure). A fresh
        # transcript mtime folds into the freshest-of union → a manager mid-plan
        # (appending its transcript every tool call but emitting no Stop) reads
        # LIVE, not MANAGER-STALE. Per-session reader degrades to None (no bridge
        # / no transcript_path / stat error) — fail-safe, never masks a dark one.
        transcript_mtimes = { sid: self._transcript_mtime_fn( sid ) for sid in fleet_view }
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
            hold_mtimes          = hold_mtimes, # task 70be69f2 hold-as-liveness (unconditional fail-safe signal)
            transcript_mtimes    = transcript_mtimes, # bug fb332fcd transcript-as-liveness (7th unconditional fail-safe signal)
            alive_threshold_seconds = self.alive_threshold_seconds,  # bug 65d1247f: same threshold the peer-EDGE gate uses (:1029-30) → display agrees with edge logic
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
        Journal an `arbiter_outreach` event at every outbound communication.

        `recipients` is the planned recipient set, not a delivery claim.

        Ensures:
            - logs kind/via/recipients + a truncated message head (full bodies
              stay out of the journal); optional case/tier/session/persona/
              outreach_id fields attach when given; never raises
            - what happened on each hop lives in the per-recipient, per-channel
              `arbiter_outreach_result` events and the terminal
              `arbiter_outreach_receipt` events, all chained on `outreach_id`;
              this event never claims a delivery it did not verify, because a
              recipient could be journaled while the live push failed
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
        Journal one `arbiter_outreach_result` event for a (recipient, channel) hop.

        It records the attempt outcome of that single hop, so no hop fails
        silently; a swallowed 404 becomes this event.

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
        for key in ( "http_status", "detail", "connection_count",
                     "window_count", "last_sent_local" ):   # Item C: throttle observability
            if key in outcome: fields[ key ] = outcome[ key ]
        self._log( "arbiter_outreach_result", **fields )

    def _log_outreach_receipt( self, outreach_id, kind, recipient, outcome, **extra ):
        """
        Journal one `arbiter_outreach_receipt` event: a recipient's final state.

        The states are delivered, reannounced_delivered or expired for the owner,
        and acked or unacked for a manager.

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
        Normalize the injected notify seam's return into channel-outcome dicts.

        This is the one place the outcome contract meets seams we do not
        construct: legacy in-pool defaults and test fakes may still return None.

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

    def _stamp( self, message ):
        """
        Prefix an outreach message with "[YYYY.MM.DD at HH:MM:SS] <message>".

        The time comes from the injectable poll clock (self._clock), rendered in
        the configured outreach tz.

        Requires:
            - message is a string

        Ensures:
            - returns "[<stamp>] <message>" with <stamp> = now() (self._clock, the
              injectable seam → deterministic under a fake clock) rendered via
              format_outreach_ts in self._outreach_tz
            - never raises (clock + tz are construction-validated)
            - it is applied at message construction, in `_route` (the choke point,
              covering message and cc_message) and in the four direct-send literals
              that bypass it (decision_cc, stuck_poke, manager_stale_poke,
              poll_error_escalation); so a resend (_check_outreach_receipts reuses
              the stored body) and a re-announce (the pending ledger reuses the
              stored message) carry the original stamp and are never double-stamped
        """
        now = datetime.datetime.fromisoformat( self._clock.now_iso() )
        return f"[{format_outreach_ts( now, self._outreach_tz )}] {message}"

    def _outreach_throttle_allows( self, recipient ):
        """
        Decide, per recipient, whether a routine persona-bound outreach DM may go.

        The limit is N messages per Y minutes in a trailing window, kept in
        consumer-side state (`self._outreach_sent_ts`) with the pure ping_throttle
        predicates.

        Ensures:
            - returns ( allowed:bool, count_in_window:int, last_sent:datetime|None )
              where count_in_window is the post-decision window count and last_sent
              is the most-recent prior send (None if none) — both for the journal
            - never raises (the clock is construction-validated)
            - when disabled (max <= 0 or window <= 0) it always allows and keeps no
              state, so it never suppresses
            - when enabled, the recipient's send history is pruned to the trailing
              window; an allowed decision appends `now` so the next call counts
              this send, and a suppressed decision does not append because nothing
              was sent
        """
        if self._outreach_throttle_max <= 0 or self._outreach_throttle_window_seconds <= 0:
            return True, 0, None
        now    = datetime.datetime.fromisoformat( self._clock.now_iso() )
        window = self._outreach_throttle_window_seconds
        kept   = ping_throttle.in_window( self._outreach_sent_ts.get( recipient, [ ] ), now, window )
        last_sent = kept[ -1 ] if kept else None
        allowed   = ping_throttle.trailing_window_allows( kept, now, self._outreach_throttle_max, window )
        if allowed:
            kept = kept + [ now ]
        self._outreach_sent_ts[ recipient ] = kept
        return allowed, len( kept ), last_sent

    def _emit_to_rick( self, outreach_id, kind, message, case=None ):
        """
        Send one advisory to the owner via the notify seam and journal each channel.

        This closes the owner-side loop. A delivered advisory gets its receipt now.
        A user_not_available one enters the pending ledger to be re-announced when
        the owner returns, so a milestone always lands.

        Ensures:
            - terminal-unacked manager facts (if any) ride this advisory's body
              (never a fresh escalation loop), then clear
            - every outcome the seam returns is journaled as one
              arbiter_outreach_result (a seam blow-up degrades to outcome
              http_error — journaled, never raised)
            - a delivered live outcome journals receipt "delivered"; a
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
                  session_id=None, expects_ack=False, attempt=1, throttleable=False ):
        """
        Emit one persona-bound DM: a durable board write plus a best-effort wake push.

        Journals one result per channel. The board write always runs first. The wake push hop follows, chosen by
        the INI key `arbiter poke wake mechanism`, whose default is "tmux".

        Ensures:
            - the board write stamps outreach_id + question_id metadata (the threading key a replying recipient
              names in in_reply_to) + expects_ack; a resend (attempt > 1) derives a fresh question_id
              "<outreach_id>-r<attempt>" so the push registration never 409s
            - the durable board write runs unconditionally, before the push-hop selection, so the poke is never
              lost regardless of mechanism or outcome
            - dm channel outcome: posted | post_error; dm_push channel outcome: the hop's own (dispatched /
              push_unavailable) or "disabled" when no hop is wired; every case is journaled
            - expects_ack=True (manager-bound, first attempt) registers the outreach in the awaiting-ack tracker
              for receipt polling
            - never raises
            - with mechanism "tmux", a tmux_push_fn and a session_id, a host-side tmux injection wakes a dormant
              pane and bypasses the listener's idle buffer gate. It is the primary fleet liveness path, since the
              internal self-poke in the stop hook cannot be relied on. If tmux or the bridge is unavailable it
              falls back to the dm_push_fn hop; with "dm", or with no tmux seam or session_id, only that hop runs
            - throttleable=True (set only for the routine taps in THROTTLEABLE_CASES: the case 4 blocker ping and
              the case 7 manager tap) applies the per-recipient trailing-window throttle. Once N messages went to
              that recipient in the window, the DM is suppressed (no board write, no push, no ack registration)
              and journaled as outcome throttle_suppressed with the window count and the last-sent local stamp
            - throttleable=False is tracked but never suppressed: escalations to the owner, the direct-send pokes
              (stuck_poke and manager_stale_poke carry their own per-episode caps, so a window cap would throttle
              them twice and skew those counters) and resends
        """
        # Item C: routine-tap trailing-window throttle (persona-bound, per-recipient).
        # Suppression short-circuits BEFORE the board write / push / ack registration
        # so a suppressed tap costs nothing downstream; escalations (throttleable=False)
        # never reach this branch (the carve-out).
        if throttleable:
            allowed, count, last_sent = self._outreach_throttle_allows( persona )
            if not allowed:
                # On suppression `last_sent` is provably non-None: suppression requires
                # >= max >= 1 prior in-window sends, so a last-sent stamp always exists.
                self._log_outreach_result(
                    outreach_id, kind, persona,
                    { "channel": "dm", "outcome": "throttle_suppressed",
                      "window_count": count,
                      "last_sent_local": format_outreach_ts( last_sent, self._outreach_tz ) },
                    attempt=attempt )
                return
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
        Resolve the active managers on duty for the owner-plus-managers fanout tier.

        Delegates to the injected resolver, which intersects the commons candidates with a live-bridge PID guard.
        A reaped manager whose last commons post lingers is excluded. A resolver failure returns an empty list,
        which degrades the fanout to the owner only and never crashes the poll.

        Ensures:
            - returns a list of active-manager personas (possibly empty); never raises
        """
        try:
            return self._resolve_active_managers_fn( who_rows, bridge_sessions ) or [ ]
        except Exception:
            return [ ]

    def _route( self, case, message, *, active_managers=None, owning_manager=None,
                blocker=None, cc_message=None, exclude_persona=None ):
        """
        Dispatch an arbiter output to the recipient tier that CASE_TIERS assigns to the case.

        `tier_for( case )` selects the tier. This method calls only notify_fn and send_to and never actuates
        anything; test_arbiter_redline guards that structurally.

        Requires:
            - exclude_persona is None or a persona name: a manager advisory that names a specific subject (the
              stale, blocked or done manager itself, cases 14, 16 and 17) must not fan out to that subject, only to
              its peer managers and the owner. When truthy, the subject is dropped from the TIER_RICK_AND_MANAGERS
              active-managers fan-out, matched by canonical persona key
              ("Mr. Radio" == "mr radio" == "mr_radio"). A falsy exclude_persona (None or empty) excludes nothing, so every caller that omits it behaves as before. Only the
              TIER_RICK_AND_MANAGERS fan-out is filtered; the owner, owning_manager, blocker and cc targets are
              never touched by this filter

        Ensures:
            - emits the recipients its tier prescribes and no others (minus exclude_persona from the
              TIER_RICK_AND_MANAGERS fan-out when supplied); absent optional recipients (no manager resolved,
              empty active set) degrade silently
            - one `arbiter_outreach` intent event (recipients = the planned set, stamped with a fresh
              outreach_id), then one `arbiter_outreach_result` per (recipient, channel) hop recording what
              actually happened, then terminal `arbiter_outreach_receipt` events as loops close; the intent event
              no longer claims delivery it did not verify; a no-emission route (empty tier inputs or TIER_DROP)
              logs nothing
            - never raises (the emit helpers convert every hop failure into a journaled outcome)
            - tiers: TIER_RICK_ONLY goes to the owner (durable write, live push, receipt and ledger);
              TIER_RICK_AND_MANAGERS goes to the owner plus an ack-tracked DM to each active manager;
              TIER_OWNING_MANAGER sends an ack-tracked DM to owning_manager when one resolved;
              TIER_BLOCKER_AND_MANAGER sends a DM to the blocker (no ack owed) and an ack-tracked DM of cc_message
              to owning_manager, each when present; TIER_DROP pushes nothing; TIER_LOG_THEN_RICK is handled by the
              streak logic of _on_poll_error, not here
        """
        tier       = tier_for( case )
        kind       = CASE_KINDS.get( case, f"case_{case}" )
        message    = self._stamp( message )                          # Item B: timestamp prefix (BEFORE dm_targets build)
        if cc_message is not None:
            cc_message = self._stamp( cc_message )
        rick_bound = tier in ( TIER_RICK_ONLY, TIER_RICK_AND_MANAGERS )
        dm_targets = [ ]                          # ( persona, body, expects_ack )
        if tier == TIER_RICK_AND_MANAGERS:
            # bug b9911943: drop the named subject from its OWN advisory fan-out
            # (a stale/blocked/done manager must not be told about itself). Matched
            # by canonical persona key; falsy exclude_persona / falsy key → no drop.
            excluded_key = canonical_persona_key( exclude_persona ) if exclude_persona else None
            dm_targets   = [ ( m, message, True ) for m in active_managers or [ ]
                             if not ( excluded_key and canonical_persona_key( m ) == excluded_key ) ]
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
        throttleable = case in THROTTLEABLE_CASES                    # Item C: only routine taps (4 ping / 7 tap)
        for persona, body, expects_ack in dm_targets:
            self._emit_dm( outreach_id, kind, persona, body, case=case,
                           expects_ack=expects_ack, throttleable=throttleable )

    def _confirmed_offline_personas( self ):
        """
        Return the personas whose every published session row has liveness verdict "offline".

        Reads the full snapshot published this poll. A confirmed-offline target will not ack, so its one-shot
        outreach resend in _check_outreach_receipts is suppressed and no resend goes to a dead pane.

        Ensures:
            - returns the set of personas all of whose published rows are "offline"; the reading is strictly
              positive and biased toward delivery: a persona with any non-offline row (a live twin session could
              still read the dm board) is excluded, and an absent or unknown persona is never included
            - empty when no snapshot has been published yet (snapshot None or not a dict); never raises
        """
        snapshot = self._last_full_snapshot
        if not isinstance( snapshot, dict ):
            return set()
        all_offline = { }                                    # persona -> (every row so far is offline)
        for row in snapshot.get( "sessions", [ ] ):
            if not isinstance( row, dict ):
                continue
            persona = row.get( "persona" )
            if not persona:
                continue
            liveness = row.get( "liveness" ) if isinstance( row.get( "liveness" ), dict ) else { }
            is_off   = liveness.get( "verdict" ) == "offline"
            all_offline[ persona ] = is_off if persona not in all_offline else ( all_offline[ persona ] and is_off )
        return { p for p, off in all_offline.items() if off }

    def _check_outreach_receipts( self, now, offline_personas=None, bridge_mtimes=None ):
        """
        Ack or resend each awaited manager outreach, closing the loop on a threaded reply.

        The receipt is an explicit mark written by the recipient, never an inference. An outreach is acked only
        if the recipient posted a threaded reply on the same dm board the durable write landed on. The reply's
        metadata.in_reply_to names the question_id. The read goes through the gateway, so it is detection-path-safe.

        Requires:
            - now is an aware datetime
            - offline_personas is a set/collection of confirmed-offline personas or None; the resend is suppressed
              for a target in this set (no wasted second send to a dead pane); None means empty, so there is no
              suppression

        Ensures:
            - an in_reply_to match (exact outreach_id or its "-rN" resend derivative) gives receipt "acked"
              (+ latency_s) and clears the tracker; an ack always wins, checked before the resend/suppress gate
            - no ack past outreach_ack_window_seconds gives exactly one re-send (attempt=2, fresh window); still
              nothing after that gives terminal receipt "unacked", and the fact is queued to ride the next
              owner-bound advisory (never an escalation recursion; at most 2 sends total)
            - when the target persona is confirmed offline, the one-shot resend is skipped and the loop closes
              terminal-unacked (resends=0); the un-acked fact still queues for the owner (a milestone must land), but no second ping is
              wasted on a dead pane. Only a positively-offline target is suppressed (absent, unknown or alive
              targets are resent)
            - recipient activity since delivery counts as an implicit ack: a bridge mtime between sent_at and now,
              checked after the ack window and before the resend gate, gives receipt "acked_by_activity"; it is
              inert when bridge_mtimes is None
            - a gateway read hiccup degrades to "no ack seen this poll" (the window keeps governing); never raises
            - returns the count of acks confirmed this poll
        """
        offline = offline_personas or set()
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
            # item 285c0343 Lever C: demonstrable recipient ACTIVITY since delivery counts
            # as an IMPLICIT ACK — an active peer manager (fresh bridge mtime in
            # [sent_at, now]) has not gone dark and needs no duplicate advisory. Checked
            # AFTER the ack window (so it only pre-empts the -r2, never the explicit
            # threaded-reply ACK above) and BEFORE the resend gate. Distinct receipt
            # outcome ("acked_by_activity") for María's audit; the resend MECHANISM, the
            # Fix-3 offline suppression, and the milestone-must-land Rick note are all
            # UNTOUCHED. Inert when bridge_mtimes is None (seam unwired) → today's behavior.
            if self._recipient_active_since( state[ "persona" ], state[ "sent_at" ], now, bridge_mtimes ):
                latency = ( now - state[ "sent_at" ] ).total_seconds()
                self._log_outreach_receipt( outreach_id, state[ "kind" ], state[ "persona" ],
                                            "acked_by_activity", latency_s=int( latency ) )
                del self._awaiting_ack[ outreach_id ]
                acked += 1
                continue
            # Fix 3 (ping-storm durable): suppress the one-shot resend when the
            # target is CONFIRMED offline — a -r2 to a dead pane is the doubling Rick
            # flagged. Otherwise resend exactly once (the intentional non-ACK retry).
            if state[ "resends" ] == 0 and state[ "persona" ] not in offline:
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
        Re-announce each pending owner advisory on an interval until delivered or expired.

        Each pending (user_not_available) advisory is re-pushed through the live transport that bypasses dedup.
        That happens at most once per reannounce interval, until a delivered outcome or TTL expiry. It runs only
        while the ledger is non-empty. The ledger is file-backed, so a restart never drops a pending advisory.

        Ensures:
            - inert (returns 0) when no ledger path or no live_retry_fn is wired
            - TTL-expired entries get terminal receipt "expired" (+ attempts) and are removed
            - malformed entries get the same terminal receipt with a detail and are removed (visible, never a
              silent skip)
            - due entries (interval elapsed) re-push; every attempt journals an arbiter_outreach_result with
              attempt=N; a delivered outcome gives receipt "reannounced_delivered" (+ attempts) and removal;
              otherwise the attempt is recorded back to the ledger
            - any ledger write failure is journaled (outreach_ledger_error); never raises; returns the count of
              re-announce attempts this poll
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

    @staticmethod
    def _blocker_cc_key( holder, awaited, edge_items ):
        """
        Build the manager-cc idempotency key: canonical awaited, canonical holder, item signature.

        The owning manager follows from the blocker's lineage, so the (blocker, blocked item) pair carries it.
        The item_sig part is the sorted, plus-joined blocked task ids for this edge. It is empty when the store read was
        unknown. The key then degrades to a persona-only pair, and clear-on-resume tells sequential blocks apart.

        Ensures:
            - returns a stable str key; personas canonicalized so it matches across view-persona spelling variants;
              never raises
        """
        ch  = canonical_persona_key( holder )  or holder
        ca  = canonical_persona_key( awaited ) or awaited
        sig = "+".join( sorted( ( edge_items or { } ).get( ( ch, ca ), () ) ) )
        return f"{ca}|{ch}|{sig}"

    def _auto_ping( self, edges, now, persona_to_sid=None, edge_items=None ):
        """
        Ping each blocker under backoff and a global cap, cc its manager, clear resumed edges.

        The DM goes to the blocker and a cc goes to its owning manager (case 4 routing).

        Requires:
            - edges is {holder: awaited} (build_graph output, persona to persona; `holder` is the blocked worker
              waiting on `awaited`, the blocker)
            - now is an aware datetime
            - persona_to_sid maps persona to session_id (for the manager cc) or None
            - edge_items is build_store_blocked_item_index output { (canonical_holder, canonical_awaited):
              frozenset(item_ids) } or None; it supplies the blocked_item part of the cc idempotency key

        Ensures:
            - pings at most one DM per (holder, awaited) edge per backoff window, and never more than
              ping_global_cap within the cap window
            - the DM goes to the blocker (awaited), naming the blocked worker (holder) and the ask, and cc's the
              blocker's owning manager (resolved via lineage) when resolvable, so the manager chases if the
              blocker stays silent
            - the manager cc is idempotency-gated: the blocker ping re-fires on its escalating backoff, but a cc on
              every ping would flood the manager with identical advisories. The manager is cc'd at most once per
              manager_advisory_cooldown_seconds window per (blocker, blocked_item, recipient) key; a new block
              (different item) re-cc's exactly once; the cooldown clears on edge-resume; cooldown 0 restores a cc
              on every ping
            - records each ping in the ledger + attempt counter
            - drops ledger + attempt state (and the blocker-cc cooldown) for edges no longer active (resume)
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
                # bug ce13b134: the blocker PING re-fires on its escalating backoff
                # (a silent blocker SHOULD keep being nudged), but the owning-manager
                # cc must NOT re-fire every ping — that flooded the manager with
                # identical "X is blocking worker Y" DMs (3 in 6 min, each a fresh
                # thread). Gate the cc on the (blocker, blocked_item, recipient)
                # cooldown, reusing the 58660c64 advisory-cooldown machinery; the
                # blocker ping itself is untouched.
                if cc_msg is not None:
                    cc_key = self._blocker_cc_key( holder, awaited, edge_items )
                    if self._advisory_cooldown_blocks( "blocker-cc", cc_key, now ):
                        cc_msg = None                                     # suppress cc; blocker ping still fires
                    else:
                        self._stamp_advisory_cooldown( "blocker-cc", cc_key, now )
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
        # bug ce13b134: also drop the blocker-cc cooldown for edges no longer active
        # so a genuinely-new block on the same edge re-cc's the manager at once
        # (mirrors the ping clear-on-resume; the 58660c64 _clear_advisory_cooldown
        # intent). A resolved-then-reformed edge whose blocked_item changed already
        # keys differently; this also covers the same-item reform after a real gap.
        active_cc_keys = { self._blocker_cc_key( h, a, edge_items ) for h, a in edges.items() }
        for stale in [ k for k in self._advisory_cooldown_until
                       if k[ 0 ] == "blocker-cc" and k[ 1 ] not in active_cc_keys ]:
            self._clear_advisory_cooldown( "blocker-cc", stale[ 1 ] )
        return fired

    def _blocker_manager_cc( self, blocker, blocked_worker, persona_to_sid ):
        """
        Resolve the blocker's owning manager and build the cc note asking it to chase.

        The manager chases if the blocker stays silent after the direct nudge.

        Ensures:
            - returns (manager_persona, cc_message) when a DM-able owning manager (other than the blocker)
              resolves from spawn-lineage; else (None, None)
            - never raises (a resolver hiccup degrades to (None, None), so the owner and blocker are still nudged,
              just with no cc)
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
        # e8eee4c4 (family-close): derive the "Heartbeat arbiter (" prefix from the shared
        # ARBITER_POKE_SENTINEL (b33c8e96 one-source-of-truth) so every arbiter body has a
        # single source for that opening clause — no drift-prone literal.
        cc = ( f"{ARBITER_POKE_SENTINEL}cc): {blocker} is blocking worker {blocked_worker}. "
               f"I've nudged {blocker} directly — chase if they stay silent." )
        return manager, cc

    def _escalate_deadlocks( self, cycles, store_edges, now, active_managers=None ):
        """
        Escalate store-backed deadlock cycles that outlast the dwell; never auto-break them.

        A human or manager breaks the cycle, so the escalation goes to the owner and every active manager.
        Three gates stand between a derived cycle and an escalation: store corroboration, dwell and de-dup.

        Requires:
            - cycles is a list of canonical peer cycles (build_graph output)
            - store_edges is build_store_wait_edges output { holder: set(awaited) }
            - now is an aware datetime (poll clock)
            - active_managers is the resolved on-duty manager set (or None)

        Ensures:
            - fires one escalation per poll listing the rings newly crossing the dwell this poll, to the owner
              (notify_fn) and each active manager (send_to); no-op when no store-backed ring has persisted past dwell
            - never raises
            - store corroboration: derived `holding_on: peer:X` cycles are self-reported, so a progressing
              sequencing wait can look like a ring and falsely escalate every poll. A cycle fires only when every
              ring edge is backed by a store `blocked_by` owner-edge (cycle_is_store_backed). A ring with zero
              store rows is out of scope, because such rings are rare and human-broken and managers should
              express real waits as store blocked_by. When the owed read is unwired or failed, store_edges is empty and nothing
              fires: deadlock detection fails suppressed, the opposite bias from the stall and manager-down
              detectors, because over-escalation is the defect here
            - dwell: a store-backed ring must persist for deadlock_dwell_seconds before it escalates; a fresh ring
              is recorded as first-seen and given the grace window to self-resolve; dwell=0 fires on first sight
            - de-dup: each persisting ring escalates once, not every poll; both trackers prune a signature as soon
              as its ring is gone, so a genuine recurrence re-arms
        """
        backed  = [ c for c in ( cycles or [ ] ) if cycle_is_store_backed( c, store_edges ) ]
        present = { tuple( c ) for c in backed }
        # prune resolved rings (re-arm): drop first-seen + escalated for any sig
        # whose ring is gone this poll.
        self._deadlock_first_seen = { s: t for s, t in self._deadlock_first_seen.items() if s in present }
        self._deadlock_escalated  = self._deadlock_escalated & present
        firing = [ ]
        for c in backed:
            sig   = tuple( c )
            first = self._deadlock_first_seen.setdefault( sig, now )      # record fresh ring → dwell grace
            if ( now - first ).total_seconds() < self.deadlock_dwell_seconds:
                continue                                                  # still progressing-wait window → suppress
            if sig in self._deadlock_escalated:
                continue                                                  # de-dup: fire ONCE per store-backed ring
            firing.append( c )
            self._deadlock_escalated.add( sig )
        if firing:
            rendered = "; ".join( " → ".join( c ) for c in firing )
            self._route( 5, f"DEADLOCK detected (store-corroborated, no autonomous break) — escalating: {rendered}",
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

    def _attention_workers( self, fleet_view, graph, now=None, bridge_mtimes=None, designed_hold_personas=None,
                            store_edges=None ):
        """
        Pick the workers needing a manager's attention: stuck sessions plus blocked-edge holders.

        Only alive views qualify, and a holder is rostered only on a real stall. The reasons are in the Ensures items.

        Requires:
            - store_edges is build_store_wait_edges output { canonical_holder: set(canonical_awaited) } from this
              poll's authoritative owed read, or None when that read failed or is unwired (backing unknown)

        Ensures:
            - returns a list of alive view dicts: every stuck session, plus every blocked-edge holder whose awaited
              peer is not alive or that sits in a deadlock cycle; reaped or offline views and holders waiting only
              on a live peer are excluded; a blocked-edge holder whose edge is not store-backed (when store_edges
              is an authoritative read) is excluded; a stuck session whose session bridge is fresh (demonstrably
              taking turns) is excluded unless it sits in a deadlock cycle; never raises
            - only alive views qualify: a reaped tombstone or long-offline session can keep a stale
              `holding_on: peer:X` on its view row, which inflated the roster, and every re-tap reloads the
              manager's whole context. A dead worker's block is not actionable (no process to poke), and a
              re-activated worker re-enters on the next poll. This also keeps _tap_signature stable
            - live-peer exclusion: a non-stuck holder whose awaited peer is alive is a legitimate in-flight
              dependency, and rostering it sends a spurious "blocked" advisory for a healthy wait; that advisory
              expects an ack, so a busy manager's missing ack would make the receipt poller send a duplicate. The
              exclusion is narrow: a deadlock-cycle member is kept (the store-backed deadlock escalation owns it),
              and an awaited peer that is non-alive or absent from the fleet keeps the holder, so a live block is
              never hidden
            - store corroboration: the derived `holding_on: peer:X` edge comes from the latest heartbeat `awaiting`
              field, which is sticky until a later activity record overwrites it, so an active worker can carry an
              hours-stale wait that bridge freshness does not age out. The ping leg is already store-corroborated
              (edge_is_store_backed); the roster leg consults the same per-poll store wait graph, so an edge with
              no store `blocked_by` backing does not roster its holder
            - fail-safe toward rostering in every uncertain direction: store_edges None means no filtering, a
              deadlock-cycle member is always kept, and personas are canonicalized on both sides so a spelling
              difference never fakes an unbacked edge. The stuck leg is not store-gated, since a stuck session is
              rostered on its own axis (the activity-derived stuck flag) and gating it would hide a wedged worker
            - a fresh bridge vetoes a stuck entry only on positive liveness evidence; an unwired seam, absent
              persona, stale or future-skewed bridge, or now=None never vetoes. Without it the arbiter could refuse
              to poke a session because it is taking turns and still tell its manager it is wedged
            - a worker whose owed work is entirely a store-backed hold blocked_by a peer operator is holding by
              design, not stalled, while at least one such operator is alive: it is excluded from both legs unless
              it sits in a deadlock cycle; designed_hold_personas None or empty means no suppression
        """
        holders        = set( graph[ "edges" ].keys() )
        alive_personas = { v.get( "persona" ) for v in fleet_view.values()
                           if isinstance( v, dict ) and v.get( "alive" ) is True and v.get( "persona" ) }
        # bug bf8c5cbb: a comms-silent (view.alive False) but BRIDGE-FRESH persona is
        # demonstrably ALIVE — count it for the live-peer exclusion, the same stale-
        # liveness gap 26dd3afb fixed for MANAGER-STALE, applied to the blocked-roster.
        # Reuses the per-poll bridge_mtimes map (persona→freshest bridge mtime, canonical-
        # keyed). Fail-safe: bridge_mtimes None / now None ⇒ no augmentation ⇒ today's
        # behavior (a genuine dead-peer block is never hidden).
        if bridge_mtimes and now is not None:
            now_epoch = now.timestamp()
            for v in fleet_view.values():
                if not isinstance( v, dict ):
                    continue
                p  = v.get( "persona" )
                mt = bridge_mtimes.get( canonical_persona_key( p ) ) if p else None
                # 0 <= age lower bound (bug 097778b8): a FUTURE mtime (clock
                # skew/corruption ⇒ negative age) is NOT ground-truth liveness →
                # do not count it alive; fail toward rostering (the safe direction).
                if mt is not None and 0 <= ( now_epoch - mt ) <= self.manager_stale_poke_threshold_seconds:
                    alive_personas.add( p )
        cycle_personas = { p for cycle in graph[ "cycles" ] for p in cycle }
        # bug cec10ef9: the UNIFORM designed-review-gate-hold suppression seam. A worker
        # whose owed work is entirely a store-backed hold blocked_by a peer OPERATOR,
        # when ≥1 operator is ALIVE, is holding BY DESIGN — not a stall — so it is
        # excluded from the attention roster on BOTH announce legs (the stuck
        # short-circuit AND the blocked-edge path; Mr. Radio ruling Q1, 2026-07-11).
        # designed_hold_personas is { canonical_persona_key: frozenset(canonical operator
        # keys) } (from _designed_hold_personas over the per-poll authoritative owed read);
        # None → {} → no suppression = today's behavior (FAIL-SAFE, store hiccup/unwired).
        # alive_keys canonicalizes the alive set (incl. the bridge-fresh augmentation) so
        # the operator-liveness test is case/spacing-robust vs the store's persona ids.
        alive_keys     = { canonical_persona_key( p ) for p in alive_personas if p }
        dhp            = designed_hold_personas or { }
        out            = [ ]
        for view in fleet_view.values():
            if not isinstance( view, dict ):
                continue
            if view.get( "alive" ) is not True:
                continue                                  # reaped/offline-prune (lane 4)
            persona = view.get( "persona" )
            # cec10ef9 suppression: a designed hold on a LIVE operator, EXCEPT a deadlock
            # cycle member (a mutual stall stays load-bearing) — a dead operator leaves
            # `operators & alive_keys` empty → NOT suppressed → rostered (real stall).
            if persona and persona not in cycle_personas:
                operators = dhp.get( canonical_persona_key( persona ) )
                if operators and ( operators & alive_keys ):
                    self._log( "arbiter_designed_hold_suppressed", persona=persona,
                               operators=sorted( operators & alive_keys ) )
                    continue
            if view.get( "stuck" ):
                # bug 3287ee1e: the WORKER-subject stuck advisory gets the SAME bridge-fresh
                # veto the POKE leg (92c7ab1d, :4005) and the MANAGER-subject advisory leg
                # (e5e33795, :2627) already have — worker subjects were simply never covered.
                # Live 2026-07-11 21:12:20 EDT, ONE poll emitted BOTH:
                #   arbiter_stuck_bridge_veto persona=sam bridge_age_s=8.6   ("don't poke — alive")
                #   tap → manager: "1 stuck/dead"                            ("sam is STUCK")
                # i.e. the arbiter refused to poke sam BECAUSE he was demonstrably taking turns,
                # then told his manager he was wedged anyway. `_session_bridge_fresh` only ever
                # suppresses on POSITIVE liveness evidence, so this is FAIL-SAFE to ROSTER:
                # unwired seam / absent persona / STALE or future-skewed bridge / now=None →
                # no veto → still announced. A genuinely wedged session stops emitting hook
                # stamps (at cap the self-poke nudge halts), so its bridge goes stale and the
                # true positive is preserved. A deadlock-cycle member is exempt (mutual stall
                # stays load-bearing). NOTE the `stuck` FLAG itself is untouched here — its
                # cap-consumption semantics are a SHARED signal (render/poke/snapshot/UI) and
                # are tracked separately (Mr. Radio's board, split from this bug).
                if ( persona and now is not None and persona not in cycle_personas
                     and self._session_bridge_fresh( persona, now, bridge_mtimes ) ):
                    continue
                out.append( view )                        # a stuck session always needs attention
                continue
            if persona not in holders:
                continue                                  # neither stuck nor a blocked-edge holder
            # blocked-edge holder: KEEP only on a real stall — the holder is in a
            # deadlock cycle, OR its awaited peer is not alive. A wait on a LIVE
            # peer is a legit in-flight dependency → EXCLUDE (bug bbce7e2f).
            if persona in cycle_personas or graph[ "edges" ].get( persona ) not in alive_personas:
                # bug 1ff7be20: STORE-CORROBORATION of the blocked-edge roster — the
                # sibling of the ping leg's d44b7068 gate (:1285). A cycle member is
                # exempt (mutual stall stays load-bearing); store_edges None ⇒ backing
                # UNKNOWN ⇒ no filtering (FAIL-SAFE to ROSTER).
                awaited = graph[ "edges" ].get( persona )
                if ( store_edges is not None and persona not in cycle_personas
                     and not edge_is_store_backed( persona, awaited, store_edges ) ):
                    self._log( "arbiter_unbacked_edge_suppressed", persona=persona, awaited=awaited )
                    continue
                out.append( view )
        return out

    def _tap_signature( self, members, graph ):
        """
        Hashable signature over a manager crew's semantic state, not its liveness ages.

        The tap therefore fires on a real change, not on the clock ticking.
        """
        crew = tuple( sorted(
            ( v.get( "session_id" ), v.get( "persona" ), v.get( "state" ),
              bool( v.get( "stuck" ) ), v.get( "holding_on" ) )
            for v in members
        ) )
        return ( crew, len( graph[ "cycles" ] ) )

    def _should_tap( self, manager, sig, now, at_map=None, sig_map=None ):
        """
        Decide whether to tap a manager: the crew summary changed and the tap interval has passed.

        Taps only when the crew summary changed since the last tap and either no tap was ever sent or at least
        tap_min_interval_seconds elapsed. It never taps on no change (anti-storm).

        The `at_map` and `sig_map` arguments select the throttle-state store. None means the crew-tap dicts
        (_last_tap_at and _last_tap_sig). The stuck-manager path passes its own dicts.
        The _last_tap_at dict feeds the manager-ack checks as clean persona names. A "stuck-mgr:<persona>" key
        there would read as a nonexistent manager.
        """
        at_map  = self._last_tap_at  if at_map  is None else at_map
        sig_map = self._last_tap_sig if sig_map is None else sig_map
        if sig_map.get( manager ) == sig:
            return False                              # no change → never tap
        last_at = at_map.get( manager )
        if last_at is None:
            return True                               # first tap for this manager
        return ( now - last_at ).total_seconds() >= self.tap_min_interval_seconds

    def _format_manager_tap( self, manager, members, graph, free_n ):
        """
        Build the advisory tap body: what the arbiter observes and what it recommends.

        The manager actuates; the arbiter never assigns work. No persona name is hardcoded.
        """
        stuck   = [ ( v.get( "persona" ) or v.get( "session_id" ) ) for v in members if v.get( "stuck" ) ]
        blocked = [ ( v.get( "persona" ) or v.get( "session_id" ) ) for v in members if not v.get( "stuck" ) ]
        k       = len( graph[ "cycles" ] )
        # ff91cff4 F1 nit (sibling of d34efe7a): derive the "Heartbeat arbiter (" prefix
        # from the shared ARBITER_POKE_SENTINEL (b33c8e96 one-source-of-truth) so every
        # arbiter body has a single source for that opening clause — no drift-prone literal.
        lines = [
            f"{ARBITER_POKE_SENTINEL}advisory — I observe + recommend; you actuate).",
            f"I observe: {len( stuck )} stuck/dead · {len( blocked )} blocked · "
            f"{free_n} free fleet-wide · {k} deadlock cycle(s).",
        ]
        if stuck:
            lines.append( "Stuck: " + ", ".join( stuck ) )
        if blocked:
            lines.append( "Blocked: " + ", ".join( blocked ) )
        lines.append(
            "I recommend: pull a free worker to unblock the stuck, or cajole the "
            "blockers — and if there's unassigned work or idle capacity, spawn/assign "
            "THIS tick. Task a worker; NEVER absorb the work yourself — reap+replace a "
            "dark worker, don't take their lane. (Recommendation only — I do not assign.)"
        )
        return "\n".join( lines )

    def _subject_is_manager( self, view ):
        """
        Say whether the escalation subject is itself a declared manager.

        A stuck or dead manager's escalation is the owner's to actuate, never a peer manager's. A manager cannot own
        itself, so the case 7 owning-manager resolver and the case 13 fan-out would both misroute it to the other manager.

        Requires:
            - view is a dict (foreign data) or an arbitrary value (defensive)

        Ensures:
            - returns True iff view is a dict with a persona whose canonical key is in the declared-manager set;
              False for non-dict / missing persona / empty declared roster; never raises
            - gates the owner-only redirect at both sites, and mirrors build_snapshot's `is_declared` role assignment
              (canonical persona key against the declared-manager roster), because raw fleet_view rows carry no
              `role` until build_snapshot adds it, after _tap_managers and _auto_poke have run
        """
        if not isinstance( view, dict ):
            return False
        persona = view.get( "persona" )
        if not persona:
            return False
        return canonical_persona_key( str( persona ) ) in self._declared_manager_keys

    def _format_stuck_manager_advisory( self, view, free_n ):
        """
        Build the owner-only advisory body for a stuck or dead manager subject.

        It is the case 7 tap's twin for manager subjects. It names the manager and frames the actuation (reap,
        replace, re-staff) as the owner's, not a peer manager's.
        """
        who = view.get( "persona" ) or view.get( "session_id" )
        # ff91cff4 F1 nit: derive the "Heartbeat arbiter (" prefix from the shared
        # ARBITER_POKE_SENTINEL (b33c8e96 one-source-of-truth) so every arbiter body
        # has a single source for that opening clause — no drift-prone literal.
        return (
            f"{ARBITER_POKE_SENTINEL}advisory — I observe + recommend; you actuate). "
            f"MANAGER {who} appears STUCK/DEAD — a manager's escalation is yours to "
            f"actuate (reap/replace/re-staff), not a peer manager's. {free_n} free "
            f"worker(s) fleet-wide. (Recommendation only — I do not reap.)"
        )

    def _tap_managers( self, fleet_view, graph, roster, now, active_managers=None, bridge_mtimes=None, designed_hold_personas=None,
                       store_edges=None ):
        """
        Tap each manager on duty with a DM-push advisory about their crew, throttled.

        Each attention-needing worker is grouped under its resolved manager (case 7). This method calls only
        send_to and notify_fn, never actuates and never auto-assigns.

        Ensures:
            - taps a manager only when their crew-summary signature changed since the last tap and at least
              tap_min_interval_seconds elapsed (anti-storm)
            - unresolved-manager (orphan) workers escalate to the owner and all active managers (case 8), because
              any manager could adopt one; never a wrong-manager DM
            - returns the count of manager DMs fired this poll; never raises
            - a stuck or dead session that is itself a declared manager escalates to the owner only (case 20), never
              grouped under a peer manager: a manager cannot own itself, so the resolver would tap the other manager.
              That advisory is throttled on a distinct key ("stuck-mgr:<persona>") in dedicated state, not
              _last_tap_at, which feeds the manager-ack checks as clean persona names; a prefixed key there
              canonicalizes to a nonexistent persona and causes a false manager-down
            - the bridge-fresh veto for stuck subjects lives in _attention_workers, which covers every subject, so a
              bridge-fresh stuck session never reaches this loop; a second copy here would be two owners for one rule
        """
        attention = self._attention_workers( fleet_view, graph, now=now, bridge_mtimes=bridge_mtimes, designed_hold_personas=designed_hold_personas,
                                             store_edges=store_edges )   # bug bf8c5cbb: bridge-fresh peers count alive; cec10ef9: designed-hold suppression; 1ff7be20: store-corroborated blocked-edge roster
        if not attention:
            return 0

        free_n = len( roster )
        fired  = 0

        # ff91cff4: split OUT manager-subjects — a stuck/dead session that is ITSELF
        # a declared manager escalates RICK-ONLY (case 20), never grouped under a
        # peer/owning manager (a manager can't own itself → the resolver would tap
        # the OTHER declared manager). Worker-subjects keep the case-7 owning-manager
        # grouping below, byte-identical. The Rick-only advisory is throttled on a
        # DISTINCT tap key ("stuck-mgr:<persona>") in DEDICATED throttle state — NOT
        # _last_tap_at (de3c5b87/33949e83 root fix): _last_tap_at feeds eval_personas +
        # the owed-read + _check_manager_acks as clean manager personas, so a prefixed
        # key there canonicalizes to a non-persona ("stuckmgrtiberius") → 0-row read →
        # false MANAGER-DOWN/DONE. The dedicated dicts preserve the identical anti-storm
        # throttle without touching the tap-ACK manager-identity space.
        groups = { }                                 # manager_persona -> [view, ...]
        for view in attention:
            if self._subject_is_manager( view ):
                # bug e5e33795's manager-SUBJECT bridge-fresh veto USED to sit here. It is
                # now SUBSUMED, byte-for-byte in outcome, by the same veto applied ONE LAYER
                # UP in `_attention_workers`' stuck leg (bug 3287ee1e) — which covers EVERY
                # subject, manager and worker alike, so a bridge-fresh stuck session never
                # reaches this loop at all. Keeping a second copy here would be two owners
                # for one rule. The e5e33795 SEMANTICS are unchanged (same veto, same
                # arbiter_stuck_bridge_veto journal event, same fail-safe); only its WORKER-
                # exclusion is retired — that exclusion WAS the 3287ee1e defect, and it left
                # the advisory path disagreeing with the POKE path, which has always vetoed
                # every role (see _auto_poke's `pokeable` filter).
                subject = view.get( "persona" ) or view.get( "session_id" )
                tap_key = "stuck-mgr:" + str( subject )
                sig     = ( "stuck_manager", subject )
                if self._should_tap( tap_key, sig, now,
                                     at_map=self._last_stuck_tap_at, sig_map=self._last_stuck_tap_sig ):
                    self._route( CASE_STUCK_MANAGER_RICK_ONLY,        # → Rick only (no peer manager)
                                 self._format_stuck_manager_advisory( view, free_n ) )
                    self._last_stuck_tap_sig[ tap_key ] = sig
                    self._last_stuck_tap_at[ tap_key ]  = now
                    fired += 1
                continue
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

    def _manager_liveness_activity( self, manager, fleet_view, now, count_dm ):
        """
        Freshest liveness datetime for a manager from the five-signal union over its session rows.

        The tap-ack consumes the same five signals as the fleet-render verdict, through fleet_render.compute_liveness:
        bridge, event, commons, idle-prompt and dm age. The dm signal is gated by `count_dm`, the
        `arbiter count dm as liveness` toggle.

        Requires:
            - manager is a persona name (str)
            - fleet_view is the build_fleet_view dict { session_id: view } or None
            - now is an aware datetime; count_dm is a bool

        Ensures:
            - returns the freshest liveness datetime among the manager's session rows, or None when fleet_view is
              None or empty, no view's canonical persona matches, or no signal is present on any match
            - never raises (the observer invariant: a per-row hiccup is swallowed by compute_liveness, which never raises)
            - single source: reusing compute_liveness keeps the ack from drifting narrower than the verdict. Looking
              only at commons and bridge made a manager whose only sign of life was a sent DM (coordination-only work
              that never bumps the bridge) or a fresh stop event read down, so manager-down was falsely escalated
              every manager_ack_window_seconds while it was live
            - persona-to-view matching uses canonical_persona_key, the persona-equivalence normalizer of the
              allocation and DM path, so a fresh row whose persona spelling differs from the tap key is not missed
            - only `freshest_age_s` decides the ack (compute_liveness thresholds colour only the verdict label); the
              age is converted back to an absolute datetime (now - age), so the caller's `last_activity >= tapped_at`
              comparison is unchanged
        """
        target = canonical_persona_key( manager ) or manager
        best   = None
        for view in ( fleet_view or { } ).values():
            if not isinstance( view, dict ):
                continue
            vp = view.get( "persona" )
            if ( canonical_persona_key( vp ) or vp ) != target:
                continue
            sid      = view.get( "session_id" )
            mtime    = self._bridge_mtime_fn( sid ) if sid else None
            liveness = compute_liveness( view, mtime, now, count_dm=count_dm )
            age      = liveness[ "freshest_age_s" ]
            if age is None:
                continue
            ts = now - datetime.timedelta( seconds=age )
            if best is None or ts > best:
                best = ts
        return best

    @staticmethod
    def _holding_on_by_persona( fleet_view ):
        """
        Map each persona to its holding_on string, for every view that carries one.

        A degrade-safe corroboration source. When the store read is unknown, a holding_on that starts with "user:"
        is a best-effort hint that a manager is parked on the owner. It shapes the advisory wording only and is never
        the sole basis for suppression; an unknown manager still escalates (fail safe).

        Ensures:
            - returns { persona: holding_on_str }; skips views without a persona or a non-string holding_on; never raises
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
        Say whether one non-terminal owed item is gated on the owner (the human).

        True when gate_class is "operator", or when status is "blocked" and blocked_by carries at least one typed ref
        {kind: "user"}. These are the two store encodings of correctly waiting on the human.

        Ensures:
            - returns a bool; a non-dict / malformed item gives False; never raises
        """
        if not isinstance( item, dict ):
            return False
        if item.get( "gate_class" ) == "operator":
            return True
        if item.get( "status" ) == "blocked":
            for ref in ( item.get( "blocked_by" ) or [ ] ):
                if isinstance( ref, dict ) and ref.get( "kind" ) == "user":
                    return True
        return False

    @staticmethod
    def _item_is_review_gate_hold( item ):
        """
        Say whether one owed item is a designed review-gate hold on a peer operator.

        A worker legitimately blocked on a peer operator (reviewer or tester) is holding for double-green. True when
        status is "blocked" and blocked_by carries at least one typed ref {kind: "persona"}.

        Ensures:
            - returns a bool; a non-dict / malformed item / non-"blocked" status / no persona-kind blocked_by ref
              gives False; never raises
            - the predicate is narrow and separate from _item_is_user_gated, the owner-gate predicate: a peer
              review-gate hold is not a human gate, and conflating the two would let this suppression reach into the
              human-domain routing
        """
        if not isinstance( item, dict ):
            return False
        if item.get( "status" ) != "blocked":
            return False
        for ref in ( item.get( "blocked_by" ) or [ ] ):
            if isinstance( ref, dict ) and ref.get( "kind" ) == "persona":
                return True
        return False

    @staticmethod
    def _designed_hold_personas( owed_items ):
        """
        Map personas whose owed work is entirely review-gate holds to their operator keys.

        The result is { canonical_persona_key : frozenset( canonical operator keys ) }. A persona qualifies only if it
        has at least one non-terminal owed item and every such item is a review-gate hold (_item_is_review_gate_hold).

        Ensures:
            - returns { canonical_persona_key : frozenset( canonical operator keys ) } for every all-holds persona
              with at least one known operator; {} when owed_items is falsy or no persona qualifies; never raises
            - a persona with any non-hold owed item is excluded, so a real stall on that other work is never hidden
              (the same every-owed-item idiom as _classify_owed)
            - the operator keys are the union of all persona-kind blocked_by ids across the persona's hold items.
              _attention_workers checks their liveness before suppressing, so a dead operator means a real stall and
              the persona stays rostered; a hold item with no operator id adds no key, and a persona with only id-less
              holds is omitted (no operator to check, so fail safe to roster)
            - fail-safe: owed_items None (store read failed or seam unwired) or empty gives {}, meaning no
              suppression, so a failed read never manufactures one
        """
        out = { }
        for persona, items in ( owed_items or { } ).items():
            if not items:
                continue
            if not all( ArbiterConsumerJob._item_is_review_gate_hold( it ) for it in items ):
                continue
            operators = set()
            for it in items:
                for ref in ( it.get( "blocked_by" ) or [ ] ):
                    if isinstance( ref, dict ) and ref.get( "kind" ) == "persona" and ref.get( "id" ):
                        operators.add( canonical_persona_key( str( ref[ "id" ] ) ) )
            if operators:
                out[ canonical_persona_key( str( persona ) ) ] = frozenset( operators )
        return out

    def _read_owed( self, personas ):
        """
        One swallow-safe read of non-terminal owed items for the given personas.

        Returns { persona: [ item-dicts ] } or None. It is the single per-poll store read shared by _classify_owed
        (class labels) and build_store_wait_edges (the store-backed deadlock owner ring). The poll therefore
        keeps one read per poll instead of querying the store twice.

        Ensures:
            - returns the injected owed_work_fn's result, or None when the seam is unwired (owed_work_fn is None),
              there are no personas, or the read raised; a swallowed read gives None, which fails safe for the
              classifier and suppresses for the deadlock gate; never raises
        """
        names = sorted( { p for p in ( personas or [ ] ) if p } )
        if self._owed_work_fn is None or not names:
            return None
        try:
            return self._owed_work_fn( names )
        except Exception:
            return None        # store hiccup → None → fail SAFE (observer invariant)

    def _read_known_owners( self ):
        """
        One swallow-safe read of the store's known owner personas, as canonical keys.

        Returns a set of canonical persona keys, or None when the seam is unwired or the read raised. It feeds the
        known-persona fail-safe of `_classify_owed`. A would-be-done persona whose canonical key is not a known
        owner is likely a label-contamination false done, so it is classed unknown.

        Ensures:
            - returns None when the seam is unwired (known_owners_fn is None) or the read raised (swallowed, so None
              fails safe: the downgrade goes inert and never marks the whole fleet unknown)
            - otherwise returns the set of canonical owner keys (falsy owners filtered); an empty store gives an
              empty set (also inert downstream); never raises
        """
        if self._known_owners_fn is None:
            return None
        try:
            owners = self._known_owners_fn()
        except Exception:
            return None        # store hiccup → None → fail SAFE (observer invariant)
        return { canonical_persona_key( o ) for o in ( owners or ( ) ) if o }

    def _read_manager_bridge_mtimes( self ):
        """
        One swallow-safe read of the live persona bridge files: persona key to freshest mtime.

        Returns { canonical_persona_key : freshest bridge-file mtime (epoch) }, or None when the seam is unwired or
        the read raised. It feeds the manager-stale bridge-mtime veto. A fresh bridge is ground-truth liveness
        that the union `freshest_age_s` can miss (a gap in session-id to bridge resolution, or a re-spun twin).

        Ensures:
            - returns None when the seam is unwired (bridge_mtimes_fn is None) or the read raised (swallowed, so
              None fails safe: the veto goes inert, which is the behavior without it, and never silently suppresses
              a genuine dark-manager escalation)
            - otherwise returns the persona-to-mtime map from the injected reader; never raises
        """
        if self._bridge_mtimes_fn is None:
            return None
        try:
            return self._bridge_mtimes_fn()
        except Exception:
            return None        # bridge-scan hiccup → None → fail SAFE (observer invariant)

    def _store_read_degraded( self, owed_items, personas ):
        """
        Say whether the per-poll owed store read failed when it was expected to return data.

        True when the seam is wired and at least one persona was under evaluation, yet the read returned None
        because it raised or timed out. The no-tap-ack reading is then untrustworthy, so manager-down and
        manager-stale escalations are suppressed (treated as unknown infra, not dark) and re-arm after a clean read.

        Ensures:
            - returns False when the owed seam is unwired or no persona was under evaluation; True iff a wired read
              over at least one persona yielded None; never raises
            - an outage is told apart from the two harmless None cases, an unwired seam (inert config, not a
              failure) and an empty roster (no persona to read); neither counts as degradation, so a benign None
              never freezes escalation fleet-wide
        """
        if self._owed_work_fn is None:
            return False
        if not any( p for p in ( personas or [ ] ) ):
            return False
        return owed_items is None

    def _classify_owed( self, personas, fleet_view, owed=_UNREAD, known_owners=None ):
        """
        Classify each persona under evaluation as blocked on user, done, active or unknown.

        The classes come from one swallow-safe store read. The injected owed_work_fn returns each persona's
        non-terminal owed items as a dict of lists.

        Ensures:
            - returns { persona: CLASS_* } for each non-empty persona in `personas`
            - owed_work_fn is called at most once, and not at all when `owed` is threaded in (the read already
              happened upstream)
            - never raises
            - classes: done when the persona has zero non-terminal owed items; blocked_on_user when it has at least
              one owed item and every owed item is owner-gated (_item_is_user_gated); active when it has at least
              one owed item that is not owner-gated; unknown when the seam is unwired, the read raised, or the
              persona is absent from the result
            - fail-safe: detectors treat unknown as they always did (escalate). An exception from the seam is
              swallowed and makes the whole result unknown, so a real escalation is never silently suppressed. The
              holding_on "user:" corroboration used by the detectors is best-effort wording only
            - `owed` lets the caller pass the per-poll owed dict so one store read feeds this method and
              build_store_wait_edges (deadlock corroboration). The default `_UNREAD` means read for itself via
              _read_owed (the single-persona session_is_not_owed path); a passed value, None included, is used as
              given, and None makes every persona unknown, as if the read had failed
            - known-persona fail-safe: a store-derived done whose canonical label is not a known store owner is
              likely a re-spin or label contamination (a label with a session suffix canonicalizes to a key no real
              persona owns), not real completion, so it becomes unknown and escalates instead of a false
              manager-done. Only the store-derived done is guarded, and the guard is inert when known_owners is
              empty or None
            - hold overrides apply only when the hold-reader seam is wired. A hold that declares work_owed=false
              makes the persona done, whatever a lingering store row says; declared_work_owed gives a bool only for
              a present boolean field, so an absent or non-bool field gives no override. This runs before the next
              rule: an open owner gate in the hold makes the persona active, because it owes the owner a re-ask and
              must not be treated as correctly parked, even if it sloppily set work_owed=false
        """
        names = sorted( { p for p in ( personas or [ ] ) if p } )
        if owed is _UNREAD:                # default: do our own one read (single-persona callers)
            owed = self._read_owed( names )
        # 262c59f6 (A) known-persona fail-safe: canonicalize the known-owner set ONCE.
        # Non-empty ⇒ arm the DONE→UNKNOWN downgrade below; empty / None ⇒ inert
        # (degenerate roster / unwired seam → today's behavior, NEVER mass-UNKNOWN).
        known_canon = { canonical_persona_key( o ) for o in ( known_owners or ( ) ) if o }
        result = { }
        for persona in names:
            if owed is None or persona not in owed:
                result[ persona ] = CLASS_UNKNOWN          # unwired / hiccup / absent → fail SAFE
                continue
            items = owed.get( persona ) or [ ]
            if not items:
                # 262c59f6 (A): a STORE-derived DONE (zero non-terminal rows) whose
                # canonical label is NOT a known store owner is a likely re-spin /
                # label-contamination false DONE — the empty read came from a label
                # that canonicalizes to a key no real persona owns ('tiberius eb4b105f'
                # ≠ 'tiberius'), NOT genuine completion. Fail-SAFE to UNKNOWN (escalate,
                # never a false MANAGER-DONE). Only the STORE DONE is guarded here; a
                # hold-declared work_owed=false DONE (below) stays authoritative. Inert
                # when known_canon is empty (the literal idempotence assert was rejected —
                # every legit display label is non-idempotent by design).
                if known_canon and canonical_persona_key( persona ) not in known_canon:
                    result[ persona ] = CLASS_UNKNOWN
                else:
                    result[ persona ] = CLASS_DONE
            elif all( self._item_is_user_gated( it ) for it in items ):
                result[ persona ] = CLASS_BLOCKED_ON_USER
            else:
                result[ persona ] = CLASS_ACTIVE

        # 6929f4ac OUTWARD-twin override (§9.2): a persona whose owning session
        # holds an OPEN user-gate owes a RE-ASK to Rick — that is ACTIVE work, NOT a
        # suppressible BLOCKED_ON_USER / DONE state (the §9 inversion: a user-gated
        # session must keep re-asking, not be treated as "correctly parked"). The
        # gate lives in the hold artifact, not the store, so reading the hold is the
        # ONLY way to see it. Override only when the hold-reader seam is wired
        # (None → inert → today's store-only behavior, all existing tests unchanged).
        if self._hold_reader_fn is not None and names:
            persona_to_sid = {
                v.get( "persona" ): k
                for k, v in ( fleet_view or { } ).items()
                if isinstance( v, dict ) and v.get( "persona" )
            }
            for persona in names:
                sid = persona_to_sid.get( persona )
                if not sid:
                    continue
                try:
                    hold = self._hold_reader_fn( sid )
                except Exception:
                    hold = None
                # 25ba173e (2026-06-29): a hold that SELF-DECLARES work_owed=false is
                # DONE-equivalent — a finished session owes nothing, regardless of any
                # lingering non-terminal STORE row (or an UNKNOWN store read). This is
                # the work_owed axis of the consolidated signal-of-life direction; like
                # the open-gate override it reads the hold (the ONLY place the flag
                # lives), and like it, it is INERT when the seam is unwired (None →
                # today's store-only behavior). declared_work_owed returns the bool ONLY
                # for a present boolean field; an absent / non-bool field → None (NOT
                # False) → no override → never silences a real escalation (fail-SAFE).
                # ORDER MATTERS: apply work_owed=false → DONE BEFORE the open-gate →
                # ACTIVE override, so a session that owes Rick a re-ask (open user-gate)
                # is re-promoted to ACTIVE and still escalates (6929f4ac preserved), even
                # if it sloppily set work_owed=false.
                if declared_work_owed( hold ) is False:
                    result[ persona ] = CLASS_DONE
                if open_gates( get_pending_user_gates( hold ) ):
                    result[ persona ] = CLASS_ACTIVE
        return result

    def session_is_not_owed( self, persona, fleet_view=None ):
        """
        Say whether a persona's owed work means it is not stalled and not down.

        True iff the persona classifies blocked_on_user or done. It is the canonical store-owed decision in one call,
        so a caller need not pre-compute the per-poll owed_class map or re-implement the store read. It composes
        `_classify_owed` (one swallow-safe store read) with the pure `owed_class_suppresses` predicate.

        Requires:
            - persona is a string; fleet_view is the per-poll view dict or None (only used to map the persona to its
              session for the hold-reader overrides in _classify_owed)

        Ensures:
            - returns True iff persona classifies blocked_on_user or done
            - active and unknown (including an unwired seam, a store hiccup or an absent persona) give False
              (fail-safe, never suppressing a real escalation); one store read; never raises
            - threads the known-persona fail-safe, so a re-spin or label-contamination would-be-done persona (not in
              the known owners, so unknown) is not falsely suppressed here either, consistent with the case 17 path
              (inert when known_owners_fn is unwired)
        """
        cls = self._classify_owed(
            [ persona ], fleet_view or { }, known_owners=self._read_known_owners()
        ).get( persona, CLASS_UNKNOWN )
        return owed_class_suppresses( cls )

    def _stale_hold_holders( self, fleet_view, now ):
        """
        Personas whose `holding_on: peer:X` edge must add no inferred edge this poll.

        This kills the phantom "X is blocking worker Y" advisory and cc. Three subtraction axes are or-ed. The first
        two read the authoritative hold artifact; the third reads the session liveness timestamp on the view.

        Requires:
            - fleet_view is the per-poll view dict; now is an aware datetime

        Ensures:
            - returns the set of holder personas whose readable hold is dead, or is fresh but contradicts its derived
              peer edge, or whose session is stale (last_activity_ts beyond alive_threshold_seconds)
            - inert when the reader seam is unwired (None gives an empty set, so behavior is unchanged for every caller)
            - a session with no readable hold is not added (absence is not deadness; the filter only subtracts an
              edge for a readable hold and never over-filters)
            - swallow-safe: a raising reader degrades that session to "not stale" (its edge survives); never raises
            - dead hold (`hold_is_stale`): an expired, not-work-owed or past-next-chase hold whose lingering
              `awaiting` drove a phantom edge although the store held no real blocked_by
            - fresh hold that contradicts the edge (`hold_contradicts_peer_edge`): the current hold is fresh and
              honored with awaiting "none" or a different peer, while the `holding_on` edge was minted from a stale
              `last_activity.awaiting=peer:X` that out-lived the wait. `hold_is_stale` does not fire for a fresh
              hold, so this axis reconciles the hold's declared awaiting against the activity-derived edge
            - stale session (`session_is_stale`): a holder with a readable, fresh, corroborating hold whose session
              is beyond the alive threshold adds zero edges. It is extra defense behind build_graph's own per-session
              gate and sits inside the `hold is not None` guard. A missing or unparseable last_activity_ts counts as
              not stale, so a live block is never hidden
            - the hold is read through the wired `_hold_reader_fn`, only for peer-edge holders (an edge is inferred
              only from a `peer:` holding_on). The result feeds only the filtered advisory graph; the deadlock
              escalation reads the unfiltered build_wait_edges feed, because a real store-backed ring must still
              escalate and the phantom is rejected there by cycle_is_store_backed
        """
        if self._hold_reader_fn is None:
            return set()
        stale = set()
        for view in ( fleet_view or { } ).values():
            if not isinstance( view, dict ):
                continue
            persona    = view.get( "persona" )
            sid        = view.get( "session_id" )
            holding_on = view.get( "holding_on" )
            if not persona or not sid or not isinstance( holding_on, str ) or not holding_on.startswith( "peer:" ):
                continue
            try:
                hold = self._hold_reader_fn( sid )
            except Exception:
                hold = None
            if hold is not None and ( hold_is_stale( hold, now )
                                      or hold_contradicts_peer_edge( hold, holding_on, now )
                                      or session_is_stale( view, now, self.alive_threshold_seconds ) ):
                stale.add( persona )
        return stale

    def _log_manager_ack_diagnostic( self, verdict, manager, cls, owed_items, fleet_view, now, tapped_at, last_activity ):
        """
        Log the exact ground-truth inputs at a manager-done or manager-down emission.

        At every manager-done (case 17) and manager-down (case 9) emission the inputs are logged.
        The true cause of a false fire can then be captured deterministically on the next occurrence.

        Requires:
            - manager is the fed persona label; cls is its owed_class; owed_items is the per-poll
              { persona: [items] } dict or None (None means the store read was unwired or raised); tapped_at is an
              aware datetime; last_activity is an aware datetime or None

        Ensures:
            - emits exactly one `arbiter_manager_ack_diagnostic` line; never raises
            - the fields (owed_class among them) tell a label-to-canonical mismatch (fed_label, canonical_label, label_is_canonical) from a
              genuine empty read, from a hold override with work_owed false (hold_work_owed) and from a degraded or
              raised store read (owed_read_ok, store_row_count); last_activity against tapped_at shows whether reads
              were degraded when a manager was falsely marked down
            - pure telemetry through the swallow-safe `_log` seam: it only reads, never mutates, and has no
              control-flow effect
        """
        canon     = canonical_persona_key( manager )
        read_ok   = owed_items is not None
        row_count = None if owed_items is None else len( owed_items.get( manager ) or [ ] )
        sid       = None
        for v in ( fleet_view or { } ).values():
            if isinstance( v, dict ) and v.get( "persona" ) == manager:
                sid = v.get( "session_id" )
                break
        work_owed = None
        if self._hold_reader_fn is not None and sid:
            try:
                work_owed = declared_work_owed( self._hold_reader_fn( sid ) )
            except Exception:
                work_owed = None                                # telemetry never crashes the poll
        self._log(
            "arbiter_manager_ack_diagnostic",
            verdict             = verdict,
            fed_label           = manager,
            canonical_label     = canon,
            label_is_canonical  = ( canon == manager ),
            owed_class          = cls,
            owed_read_ok        = read_ok,
            store_row_count     = row_count,
            hold_work_owed      = work_owed,
            session_id          = sid,
            tapped_at           = tapped_at.isoformat(),
            last_activity       = last_activity.isoformat() if last_activity is not None else None,
            secs_since_activity = ( now - last_activity ).total_seconds() if last_activity is not None else None,
            ack_window_secs     = self.manager_ack_window_seconds,
        )

    def _check_manager_acks( self, now, who_rows, fleet_view=None, active_managers=None, owed_class=None, count_dm=True, owed_items=None, store_read_degraded=False ):
        """
        Escalates a tapped manager that shows no sign of life since the tap.

        Liveness is the five-signal union the fleet render uses: bridge mtime, stop event,
        commons, idle prompt and sent DM (DMs gated by `count_dm`). It proves the manager is
        alive, not that it read the tap. A manager that is alive but ignores a tap is not down.

        Ensures:
            - returns the count of new manager-down escalations this poll (advisories are not counted, they are not downs)
            - clears a manager's down/advisory flags once it shows activity (commons or bridge) since its tap
            - `BLOCKED_ON_USER` and `DONE` managers never escalate `MANAGER-DOWN`
            - never raises
            - escalates only after manager_ack_window_seconds have passed with no activity since the tap, once per un-acked tap, and only notifies (never auto-assigns)
            - a `BLOCKED_ON_USER` manager gets at most one awaiting-owner advisory and a `DONE` manager at most one consider-reaping advisory; the three escalate-once flags clear together on a re-ack
            - the owed class decides, not the clock: a manager correctly waiting on Rick makes no tool calls, so it has no bridge or commons liveness and must not be reported down; the manager loop must stay below the staleness floor
            - `ACTIVE` and `UNKNOWN` classes escalate `MANAGER-DOWN`; `UNKNOWN` is the fail-safe class, so nothing is silently suppressed and a hold starting "user:" only changes the wording
            - a degraded owed read this poll suppresses the escalation without setting the once flag, so it re-arms on the next clean read
            - the ack uses the full liveness union (plus who() commons activity) because a narrower set false-escalated a live manager whose only sign was a sent DM or stop event; a manager cannot DM the arbiter back, so liveness is the only possible ack
            - who() commons activity stays in the union because the view's commons_ts is set to None when the bridge is absent; a DM-only manager is coordination-only, with no Read, Edit or Bash to bump the bridge and nothing to commons
        """
        owed_class = owed_class or { }
        holding    = self._holding_on_by_persona( fleet_view )
        down = 0
        for manager, tapped_at in list( self._last_tap_at.items() ):
            # Implicit tap-ACK from the AUTHORITATIVE 5-signal liveness union
            # (bug e8f40042 — was {commons, bridge}-only, strictly narrower than
            # the verdict, so a DM-only / coordination manager false-DOWNed every
            # window). commons_activity from who_rows is KEPT as a belt: the view
            # path's commons_ts is phantom-nulled when the bridge is absent, so a
            # bridge-less-but-commons-posting manager would otherwise lose that
            # ACK — max() of both makes the new path a strict SUPERSET of the old.
            commons_activity = self._manager_last_activity( manager, who_rows )
            view_activity    = self._manager_liveness_activity( manager, fleet_view, now, count_dm )
            candidates       = [ t for t in ( commons_activity, view_activity ) if t is not None ]
            last_activity    = max( candidates ) if candidates else None
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
                    if not self._advisory_cooldown_blocks( "blocked", manager, now ):   # bug 58660c64 ping-pong guard
                        self._stamp_advisory_cooldown( "blocked", manager, now )
                        self._route(
                            CASE_MANAGER_AWAITING_USER,                 # f48f089d: → Rick only (mirror case 20)
                            f"MANAGER-AWAITING-RICK (advisory, NOT manager-down): {manager} is "
                            f"correctly BLOCKED on Rick — every owed item is Rick-gated. No "
                            f"tap-ACK is expected while it waits; this is a one-time notice, "
                            f"not a repeating escalation."
                        )
                continue
            if cls == CLASS_DONE:
                if manager not in self._manager_done_advised:       # L1 §3.2 advisory-once
                    self._manager_done_advised.add( manager )
                    if not self._advisory_cooldown_blocks( "done", manager, now ):      # bug 58660c64 ping-pong guard
                        self._stamp_advisory_cooldown( "done", manager, now )
                        self._log_manager_ack_diagnostic( "manager_done", manager, cls,   # de3c5b87 ground-truth capture
                                                          owed_items, fleet_view, now, tapped_at, last_activity )
                        self._route(
                            CASE_MANAGER_DONE_ADVISORY,                # f48f089d: → Rick only (mirror case 20)
                            f"MANAGER-DONE (advisory, NOT manager-down): {manager} owes NO "
                            f"non-terminal work — it appears finished/idle. Consider reaping "
                            f"it (the arbiter never reaps — redline). One-time notice.",
                        )
                continue
            # 33949e83 STORE-HEALTH GATE: when the arbiter's OWN owed read is degraded
            # this poll (raised/timed out), the missing tap-ACK liveness is an infra
            # artifact, NOT manager darkness (the 2026-07-01 :7999 bog false-DOWNed
            # BOTH managers in 1s). SUPPRESS the escalation (UNKNOWN-INFRA) and do NOT
            # set the escalate-once flag → it re-arms on the next CLEAN read window. The
            # diagnostic still records the suppression (verifies the gate on a real outage).
            if store_read_degraded:
                self._log_manager_ack_diagnostic( "manager_down_suppressed_infra", manager, cls,
                                                  owed_items, fleet_view, now, tapped_at, last_activity )
                continue
            if manager not in self._manager_down_escalated:         # ACTIVE / UNKNOWN → today's MANAGER-DOWN
                self._manager_down_escalated.add( manager )
                self._log_manager_ack_diagnostic( "manager_down", manager, cls,       # 33949e83 ground-truth capture
                                                  owed_items, fleet_view, now, tapped_at, last_activity )
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
        Escalates each new post of a decision the fleet cannot make to Rick.

        Reading is pure observation, with no side effects. The first poll sets the cursor to
        `now`, so a backlog from before the arbiter started is not escalated again.

        Ensures:
            - returns the count of new decision-needed posts escalated this poll
            - later polls read only entries strictly newer than the cursor
            - advances the tail cursor to the latest entry ts seen
            - never raises (a read hiccup is swallowed because the observer must not fail)
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
        Copies the owning manager on a decision-needed post when that manager is known.

        Decisions go to Rick first. The manager is added only if the post carries a
        `sender_session_id` that resolves through lineage to a manager that can take a DM.
        Otherwise nothing happens. Only send_to is called.

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
            # e8eee4c4 (family-close): opening clause derived from ARBITER_POKE_SENTINEL
            # (b33c8e96 one-source-of-truth) — no drift-prone literal.
            cc_body = self._stamp(                                  # Item B: direct-send site (bypasses _route)
                f"{ARBITER_POKE_SENTINEL}cc): your crew posted a decision-needed — "
                f"{entry.get( 'body', '' )}. Rick has it; weigh in if it's yours." )
            outreach_id = self._mint_outreach_id()
            self._log_outreach( "decision_cc", "send_to", [ manager ], cc_body,
                                persona=manager, outreach_id=outreach_id )
            # decision_cc is part of a DECISION escalation → NOT throttled (carve-out)
            self._emit_dm( outreach_id, "decision_cc", manager, cc_body, expects_ack=True )

    @staticmethod
    def _fleet_progress_signature( fleet_view ):
        """
        Returns a hashable signature of the fleet's work progress, ignoring liveness ages.

        The signature covers each session's state, stuck flag, holding_on and last task-store transition time.

        Ensures:
            - changes when any session's state advances or a session records a new task-store write, and not when only liveness ages move (the stall detector keys on progress, not liveness)
            - a task write counts as progress because a manager creating or moving task items was alive but not progressing (commons chatter is liveness only), which tripped a false whole-fleet stall
            - a task write is unambiguous coordination work and, unlike a DM, can never be idle "still blocked" chatter, so a live fleet making no task writes keeps an unchanged signature and still stalls
            - the transition time is stringified with isoformat so the signature stays a hashable, value-comparable tuple
        """
        return tuple( sorted(
            ( v.get( "session_id" ), v.get( "state" ), bool( v.get( "stuck" ) ), v.get( "holding_on" ),
              v[ "last_task_transition_ts" ].isoformat() if v.get( "last_task_transition_ts" ) else None )
            for v in fleet_view.values() if isinstance( v, dict )
        ) )

    @staticmethod
    def _has_live_owed_work( fleet_view, owed_class=None ):
        """
        Returns whether any session is both alive and owes work that is not parked.

        This is the liveness precondition the whole-fleet-stall trigger evaluates. `alive` is the union signal set by build_fleet_view (bridge, commons, idle prompt, stop event), not a re-derivation.

        Ensures:
            - returns True iff some view is alive and state ∈ {working, stuck,
              holding} and its persona's owed-class does not suppress (i.e. is
              neither BLOCKED_ON_USER nor `DONE`); never raises
            - a dead or empty roster can never stall-escalate: offline sessions with frozen owed-work state and no live bridge would otherwise read as no progress
            - the gate limits evaluation only; progress stays keyed on the semantic signature, so alive sessions posting "still blocked" while nothing advances are still a real stall
            - a session owing only Rick-gated work (BLOCKED_ON_USER) or nothing (`DONE`) is excluded through the shared `owed_class_suppresses` predicate, the same suppression set the ack and staleness checks use
            - when owed_class is None or empty, or a persona classifies as `UNKNOWN`, nothing is excluded (fail safe: a real stall is never silenced)
        """
        owed_class = owed_class or { }
        for v in fleet_view.values():
            if not ( isinstance( v, dict ) and v.get( "alive" ) is True
                     and v.get( "state" ) in ( "working", "stuck", "holding" ) ):
                continue
            persona = v.get( "persona" )
            if persona is not None and owed_class_suppresses( owed_class.get( persona ) ):
                continue                                # not-owed (Rick-gated OR done) is not a stall
            return True
        return False

    def _fleet_has_recent_build_liveness( self, fleet_view, now ):
        """
        Returns whether any alive session shows recent build, DM or hold-refresh activity.

        The frozen progress signature cannot see this. A fleet that builds but holds its commits makes no task-store writes in the window. It would read as no progress and false-escalate a whole-fleet stall. The three signals credited here are bridge (build), dm (coordination) and hold (refresh).

        Requires:
            - fleet_view is the build_fleet_view dict { session_id: view } or None
            - now is an aware datetime

        Ensures:
            - returns True iff some alive view with a session_id has a bridge/dm/hold
              age that is present and ≤ fleet_stall_window_seconds (recent build /
              DM / hold-refresh)
            - a dead/offline session's stale-or-fresh mtime never credits (the alive
              gate blocks it); a session without a session_id is skipped
            - reads bridge/hold mtime via the injected never-raise seams and folds
              them through compute_liveness (itself never-raises); never raises
            - only bridge_age_s, dm_age_s and hold_age_s are read; commons, idle prompt and event ages are excluded because commons chatter is liveness, not progress (the arbiter's own posts surface in who()), and crediting it would hide a live fleet posting "still blocked" while nothing builds
            - dm_age_s comes from the always-present auditable column, so a sent DM counts here whatever the `arbiter count dm as liveness` toggle says
        """
        window = self.fleet_stall_window_seconds
        for view in ( fleet_view or { } ).values():
            if not ( isinstance( view, dict ) and view.get( "alive" ) is True ):
                continue
            sid = view.get( "session_id" )
            if not sid:
                continue
            bridge_mtime = self._bridge_mtime_fn( sid )
            hold_mtime   = self._hold_mtime_fn( sid )
            liveness     = compute_liveness( view, bridge_mtime, now, hold_mtime=hold_mtime )
            for age in ( liveness[ "bridge_age_s" ], liveness[ "dm_age_s" ], liveness[ "hold_age_s" ] ):
                if age is not None and age <= window:
                    return True                                 # recent build/DM/hold-refresh = progress
        return False

    def _check_fleet_stall( self, fleet_view, now, active_managers=None, owed_class=None ):
        """
        Escalates when the fleet makes no progress for the stall window while live work is owed.

        The alert goes to Rick and all active managers; it only escalates and never auto-assigns.
        Progress keys on the semantic signature (state, stuck, holding), not on liveness, so this
        fires even when a manager's bridge mtime is fresh.

        Ensures:
            - resets the stall timer whenever the progress signature changes
            - escalates once per stall episode when the signature is unchanged for
              ≥ the window and a live session owes work; re-arms on the next progress
            - a dead/offline roster (no live owed work) never escalates
            - a fleet whose only live owed work is "not owed", BLOCKED_ON_USER (Rick-gated) or `DONE` (zero owed), never escalates; owed_class None, empty or `UNKNOWN` gives today's behavior (fail safe)
            - a session on a defended awaiting-user hold is excluded from the owed set; it is correctly parked on Rick, not stalled
            - an actively building fleet (recent bridge/DM/hold-refresh liveness) is progressing, so it never escalates even with a frozen signature; commons/idle_prompt chatter still does not credit progress
            - returns 1 on a new escalation else 0; never raises
            - this catches a manager that is alive but ignoring the tap, which the manager-down check does not cover: manager-down means gone, this means present but not acting
            - liveness only gates whether a stall is evaluated (the owed work must sit on a session marked alive), so a dead roster no longer escalates while a chatty but stuck live fleet still does
            - the signature never counts commons chatter, because the arbiter's own per-poll posts surface in who() and would mask every stall
            - the hold decides the awaiting-user exclusion, not the store class: the open-gate override reclassifies such a session as active in owed_class, so the store cannot see it; with the hold-reader seam unwired nothing is excluded
        """
        sig = self._fleet_progress_signature( fleet_view )
        if sig != self._last_progress_sig:
            self._last_progress_sig = sig
            self._last_progress_at  = now
            self._stall_escalated   = False
            return 0
        # 423f04a5 facet-1: a session on a DEFENDED awaiting-user hold is correctly
        # PARKED on Rick, NOT stalled — exclude it from the owed/stalled set. This
        # mirrors the not-owed suppression #9/#F2/_has_live_owed_work already apply,
        # but keys on the HOLD: the 6929f4ac open-gate override reclassifies an
        # awaiting-user session as CLASS_ACTIVE in owed_class (it owes Rick a RE-ASK),
        # so the store classification CANNOT see this state — the truth lives only in
        # the hold artifact. Inert when the hold-reader seam is unwired (returns False
        # → owed_view == fleet_view → today's behavior). _session_awaiting_user is
        # never-raise and None-sid-safe, so malformed views degrade to NOT-excluded.
        owed_view = { sid: v for sid, v in fleet_view.items()
                      if not ( isinstance( v, dict )
                               and self._session_awaiting_user( v.get( "session_id" ), now ) ) }
        has_owed = self._has_live_owed_work( owed_view, owed_class )
        if ( has_owed and self._last_progress_at is not None
             and ( now - self._last_progress_at ).total_seconds() >= self.fleet_stall_window_seconds
             and not self._stall_escalated
             # 423f04a5 facet-2: don't escalate while the fleet is demonstrably
             # BUILDING — recent bridge(build)/DM/hold-refresh liveness IS progress
             # the frozen semantic signature can't see (commons chatter excluded, so
             # the chatty-but-stuck blind spot stays closed).
             and not self._fleet_has_recent_build_liveness( fleet_view, now ) ):
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
        Returns the live, stuck sessions eligible for an auto-poke this poll.

        A session is pokeable only when `alive is True` and `stuck is True`.

        Ensures:
            - returns { session_id: view } for each live+stuck session; never raises
            - a dead or offline session is never poked, since poking a corpse is waste; alive is the same union-liveness gate the stall detector uses
            - stuck means repeated cap_reached with work owed and no progress; a busy, declared-holding or idle session is not stuck, so it is not poked (quiet is not a stall, and a heads-down live worker is left alone)
        """
        return {
            v[ "session_id" ]: v
            for v in fleet_view.values()
            if isinstance( v, dict ) and v.get( "session_id" )
            and v.get( "alive" ) is True and v.get( "stuck" ) is True
        }

    # ── audience scalpel (2026-07-19): the poke-routing predicate ───────────────

    @staticmethod
    def audience_for_role( role ):
        """
        Returns the poke audience (worker or manager) for a target session's role.

        Every audience gate takes its answer from here, from the `role` field of the fleet view row.

        Ensures:
            - returns AUDIENCE_MANAGER iff role case/space-insensitively == "manager"
            - every other value (incl. None / "" / "worker" / junk) maps to AUDIENCE_WORKER,
              matching _append_goal_line's manager-or-else fork; never raises
            - the role field is the single source because _format_poke, _append_goal_line, _stale_gate_why_not and _maybe_poke_stale_managers already key on it; deriving the audience from the bridge or elsewhere would add a second source for a question the row answers, free to diverge from the role that shaped the poke text
        """
        is_manager = ( role or "" ).strip().lower() == "manager"
        return AUDIENCE_MANAGER if is_manager else AUDIENCE_WORKER

    def _poke_audience_enabled( self, audience ):
        """
        Returns whether the arbiter may emit to `audience` this poll.

        The master `auto_poke_enabled` gates all three audiences. With the master off every audience is silent.
        Each audience can also be silenced on its own.

        Requires:
            - audience is one of AUDIENCE_WORKER | AUDIENCE_MANAGER | AUDIENCE_OPERATOR

        Ensures:
            - returns False when the master is off, regardless of audience flags
            - else returns the audience's own flag
            - an unknown audience returns False (fail-silent, not fail-loud: an
              unrecognized audience must never become an unscoped poke channel);
              never raises
        """
        if not self.auto_poke_enabled:
            return False
        return {
            AUDIENCE_WORKER   : self.poke_workers_enabled,
            AUDIENCE_MANAGER  : self.poke_managers_enabled,
            AUDIENCE_OPERATOR : self.poke_operator_enabled,
        }.get( audience, False )

    def _append_goal_line( self, body, role ):
        """
        Appends the role-selected north-star goal line to a poke body.

        A manager role gets the manager line and any other role the worker line. The goal strings are
        injected at construction (the :8001 factory reads the `heartbeat <role> goal line` INI keys).
        When the selected line is None or empty, the body is returned unchanged.
        Canonical text: planning-is-prompting -> workflow/role-goals.md.
        """
        is_manager = ( role or "" ).strip().lower() == "manager"
        line       = self.manager_goal_line if is_manager else self.worker_goal_line
        if line:
            return body + "\n\n" + line
        return body

    def _format_poke( self, view ):
        """
        Builds the non-destructive wake-nudge body sent to a stuck live session.

        The closing clause forks on the role. A stuck worker is told to resume the work.
        A stuck manager is told to tap or assign its crew, and to staff up if it has more tasks than workers.
        It is not told to resume the work itself. A manager serving under another manager cannot tap a crew,
        so it gets the worker wording; that case is view["manager"] set from lineage, never guessed.
        Only the wording changes and `role` is untouched.
        """
        who        = view.get( "persona" ) or view.get( "session_id" )
        # A declared manager currently serving UNDER someone (view["manager"] set —
        # lineage-only, never guessed) cannot tap a crew or staff up, so it gets the
        # WORKER wording. Wording only: `role` is untouched, so audience routing and
        # the manager-staleness tier keep exactly the population they have today.
        is_manager = ( ( view.get( "role" ) or "" ).strip().lower() == "manager"
                       and not ( view.get( "manager" ) or "" ) )
        prefix     = (
            f"{ARBITER_POKE_SENTINEL}auto-poke): {who}, you appear STUCK — repeated "
            f"cap-reached with work owed and no progress. Are you blocked or wedged? "
            f"Post your status, ask for help, "
        )
        if is_manager:
            body = prefix + (
                "or — if you manage a crew — tap/assign your crew (staff up if you "
                "have more tasks than workers); don't resume the work yourself. "
                "(Non-destructive nudge.)"
            )
        else:
            body = prefix + "or resume. (Non-destructive nudge.)"
        # role-goals Phase 2-3: append the role-selected goal echo (view["role"] is
        # "manager" | "worker", set by fleet_render); inert when unconfigured.
        return self._append_goal_line( body, view.get( "role" ) )

    def _format_reap_recommendation( self, view, pokes ):
        """
        Builds the advisory recommending a human or manager reap a session that stayed stuck.

        The arbiter never executes the reap; the text only recommends it and takes no destructive action.
        """
        who = view.get( "persona" ) or view.get( "session_id" )
        return (
            f"REAP-RECOMMENDATION (advisory — I recommend, you decide; I do NOT reap): "
            f"session {who} stayed STUCK through {pokes} bounded auto-poke(s) with no "
            f"recovery. Recommend a human/manager reap-and-replace it. The arbiter "
            f"takes NO destructive action."
        )

    def _session_awaiting_user( self, session_id, now ):
        """
        Returns whether the session sits on a fresh honored awaiting-user hold.

        Such a session is correctly parked on Rick, so the stuck-poke must not treat it as wedged.

        Requires:
            - session_id is a string; now is an aware datetime

        Ensures:
            - returns False when the hold-reader seam is unwired (None), the read
              raises, or the hold is absent / not-honored: inert and fail-safe
              (today's poke behavior preserved; never silences a real stuck-poke)
            - returns True iff is_honored( hold, now ) and ( awaiting starts "user:"
              or open_gates( pending_user_gates ) is non-empty ); never raises
            - it mirrors the not-owed suppression in `_has_live_owed_work`, `_check_manager_acks` and `_check_manager_staleness`, but keys on the hold instead of owed_class: the open-gate override classifies an awaiting-user session as CLASS_ACTIVE (it owes Rick a re-ask and must keep re-asking), so the store classification cannot see this state
            - suppressing the arbiter's stuck-poke does not stop the Stop-hook's own bounded re-ask channel (poke_cap=3); it only silences the "you appear stuck, wedged?" escalation on top of it
        """
        if self._hold_reader_fn is None:
            return False                                        # inert seam → today's behavior
        try:
            hold = self._hold_reader_fn( session_id )
        except Exception:
            return False                                        # store hiccup → fail SAFE (observer invariant)
        if not is_honored( hold, now ):
            return False                                        # no fresh, reasoned hold → not defended
        awaiting = hold.get( "awaiting" )
        if isinstance( awaiting, str ) and awaiting.startswith( "user:" ):
            return True
        return bool( open_gates( get_pending_user_gates( hold ) ) )

    def _awaiting_user_hold_facets( self, session_id ):
        """
        Returns the hold's `awaiting` string and the soonest open-gate `next_chase_ts`.

        Feeds the log row for a manager-stale suppression on an awaiting-user hold, in one best-effort read.
        It runs only after `_session_awaiting_user` returned True and serves observability, never control flow.

        Ensures:
            - returns {} when the seam is unwired (None), the read raises, or the hold
              is not a dict: the suppression still fires, the log row just omits facets
            - otherwise returns a dict with `awaiting` (when a non-empty str) and
              `soonest_next_chase_ts` (when ≥1 open gate carries one), the soonest
              chosen by parsed chronological order (offset-aware), falling back to the
              first stamp on any parse hiccup; never raises
        """
        if self._hold_reader_fn is None:
            return { }
        try:
            hold = self._hold_reader_fn( session_id )
        except Exception:
            return { }
        if not isinstance( hold, dict ):
            return { }
        facets   = { }
        awaiting = hold.get( "awaiting" )
        if isinstance( awaiting, str ) and awaiting:
            facets[ "awaiting" ] = awaiting
        chase_stamps = [ g.get( "next_chase_ts" )
                         for g in open_gates( get_pending_user_gates( hold ) )
                         if isinstance( g, dict ) and g.get( "next_chase_ts" ) ]
        if chase_stamps:
            try:
                facets[ "soonest_next_chase_ts" ] = min(
                    chase_stamps, key=lambda s: datetime.datetime.fromisoformat( s ) )
            except Exception:
                facets[ "soonest_next_chase_ts" ] = chase_stamps[ 0 ]
        return facets

    def _recipient_active_since( self, persona, sent_at, now, bridge_mtimes ):
        """
        Returns whether the outreach recipient showed activity after the message was delivered.

        A fresh session-bridge mtime in [sent_at, now] means the peer took a turn after delivery. That is
        an implicit ack, so the one-shot `-r2` resend would be redundant noise to an active peer.

        Requires:
            - persona is a persona name; sent_at, now are aware datetimes;
              bridge_mtimes is {canonical_persona_key: epoch} or None

        Ensures:
            - returns False when bridge_mtimes is None/empty (seam unwired), persona is
              falsy, or the persona has no mtime: today's resend behavior (fail toward
              delivery, never drop a genuine escalation)
            - returns True iff sent_at <= bridge_mtime <= now; a future-skewed mtime
              (> now) is rejected, failing toward the resend; never raises
            - any hook fire counts as a turn (a DM, task_transition or hold write each rides one)
            - this is the same persona-keyed bridge-mtime signal the manager-stale veto uses; every ack-tracked recipient is a manager (every expects_ack=True route targets one), so the manager-only bridge map covers them
        """
        if not bridge_mtimes or not persona:
            return False
        mt = bridge_mtimes.get( canonical_persona_key( persona ) )
        if mt is None:
            return False
        return sent_at.timestamp() <= mt <= now.timestamp()

    def _session_awaiting_peer( self, session_id, now ):
        """
        Returns whether the session is a manager correctly awaiting live peer workers.

        True iff it carries a fresh honored hold that declares `work_owed=true` and names `awaiting: peer:...`.

        Requires:
            - session_id is a string; now is an aware datetime

        Ensures:
            - returns False when the hold-reader seam is unwired (None), the read
              raises, the hold is absent / not-honored, or work_owed is not
              explicitly True: inert and fail-safe (today's poke behavior preserved)
            - returns True iff is_honored( hold, now ) and declared_work_owed( hold )
              is True and awaiting is a str starting "peer:"; never raises
            - a manager that delegated its owed work shows no self-transition, since the workers make the progress; the activity-tail stuck oracle would misread "no progress + work owed" as wedged
            - the honored work_owed=true peer hold is the defended-quiescence artifact the store classification cannot express (a delegated active persona looks the same as a self-owned wedged one in owed_class)
            - sibling of `_session_awaiting_user` and tighter: it also requires work_owed to be explicitly True, since a manager awaiting a peer while owing nothing is not the manage-not-build posture and stays pokeable
        """
        if self._hold_reader_fn is None:
            return False                                        # inert seam → today's behavior
        try:
            hold = self._hold_reader_fn( session_id )
        except Exception:
            return False                                        # store hiccup → fail SAFE (observer invariant)
        if not is_honored( hold, now ):
            return False                                        # no fresh, reasoned hold → not defended
        if declared_work_owed( hold ) is not True:
            return False                                        # not a delegating-with-work posture → still pokeable
        awaiting = hold.get( "awaiting" )
        return isinstance( awaiting, str ) and awaiting.startswith( "peer:" )

    def _session_bridge_fresh( self, persona, now, bridge_mtimes ):
        """
        Returns whether a stuck-flagged session took a turn recently, per its bridge mtime.

        A fresh persona session-bridge mtime means the session is active, so the stuck-poke is vetoed.
        The key is canonical_persona_key( persona ); the freshness window is manager_stale_poke_threshold_seconds.

        Requires:
            - persona is a persona name or None; now is an aware datetime;
              bridge_mtimes is { canonical_persona_key: epoch-mtime } or None

        Ensures:
            - returns False when bridge_mtimes is falsy, persona is None, the persona
              has no bridge entry, or the bridge age is negative / beyond the window
            - returns True iff 0 <= (now - bridge_mtime) <= manager_stale_poke_threshold_seconds;
              logs one arbiter_stuck_bridge_veto event when it vetoes; never raises
            - the stuck flag derives from the accumulated cap_reached tail (maxlen 50, no recency bound) and cap_reached fires on every turn a session ends while owed and at poke-cap, so a busy manager with a full board stays flagged stuck from stale history; none of the three owed-work suppressors (awaiting-user, awaiting-peer, owed_class) catches that case
            - owed_class `ACTIVE` is fail-safe and never silences a real stuck poke, which is why it does not catch the false positive above
            - the bridge is keyed by persona because that key is always present (the session-id keyed activity signal is not) and it also catches a re-spun twin under a new session id
            - every hook fire touches the bridge, the same signal the manager-stale bridge veto reads, so a fresh bridge means a real turn and the session is not wedged
            - at poke-cap the self-poke nudge stops, so a truly wedged or parked session takes no further turns, its bridge goes stale and it is still poked
            - the veto suppresses only on positive liveness evidence and never hides a real stall: a falsy bridge_mtimes (seam unwired, read raised, empty), a persona with no entry and a future mtime (clock skew) all return False, failing toward poking
        """
        if not bridge_mtimes or persona is None:
            return False
        bridge_mtime = bridge_mtimes.get( canonical_persona_key( persona ) )
        if bridge_mtime is None:
            return False
        age = now.timestamp() - bridge_mtime
        if 0 <= age <= self.manager_stale_poke_threshold_seconds:
            self._log( "arbiter_stuck_bridge_veto", persona=persona, bridge_age_s=age )
            return True
        return False

    def _auto_poke( self, fleet_view, now, active_managers, owed_class=None, bridge_mtimes=None ):
        """
        Pokes each stuck live session a bounded number of times, then recommends a reap once.

        After at most poke_max_per_episode pokes with no recovery it sends one reap recommendation and
        falls silent. The arbiter never reaps.

        Requires:
            - owed_class is the per-poll { persona: CLASS_* } map (or None/empty, so
              the store cross-check is inert: today's activity-tail-only behavior)

        Ensures:
            - no-op when auto_poke_enabled is False (the make-before-break flag)
            - pokes ≤ poke_max_per_episode times per session per episode, then
              escalates exactly once, then silent
            - an awaiting-user / awaiting-peer / store-not-owed session is never poked
            - returns the count of pokes fired this poll; never raises
            - the method only sends DMs and routes messages, never reaps; the structural redline test enforces this
            - the cap and escalated flag persist per stall episode (state on self, keyed by session_id), not per poll, so a stuck session gets at most poke_max_per_episode pokes in total, then one reap recommendation, then silence, never a re-poke storm every tick
            - a session that leaves the pokeable set (recovered, died, no longer stuck, suppressed, or its audience silenced) ends its episode: its state is cleared and the cap re-arms
            - a session must be continuously live and stuck for at least poke_stall_threshold_seconds before its first poke, so a brief stick that resolves itself is never poked
            - stuck_poke_min_interval_seconds (0 disables it) sets a minimum gap between pokes to one session; a poke skipped for being too soon does not use up the per-episode budget
            - a stuck session is dropped from the pokeable set when an awaiting-user hold, an awaiting-peer work_owed hold, a store owed_class of `DONE` or BLOCKED_ON_USER, or a fresh session bridge defends it; owed_class puts the stuck path on the same store authority the other detectors read, so the activity-tail and store oracles cannot contradict within one poll
            - the reap recommendation is sent only while the operator audience is enabled; for a manager subject it goes to Rick only (managers answer to Rick, not each other), for a worker it goes to Rick plus the active managers
        """
        if not self.auto_poke_enabled:
            return 0

        owed_class = owed_class or { }

        pokeable = self._pokeable_sessions( fleet_view )

        # SUPPRESS the harsh stuck-poke for a session that is DEFENDED — across BOTH
        # owed-work oracles the two detectors disagreed on in bug 262c59f6:
        #   (a) c9575068 awaiting-USER — a fresh honored hold declaring awaiting:user
        #       (or an open user-gate): correctly MANAGER-AWAITING-RICK, advisory
        #       (the case-16 path emits its one-time notice), NOT wedged; OR
        #   (b) 262c59f6 H2 awaiting-PEER — a fresh honored work_owed=true hold
        #       declaring awaiting:peer: a delegating manager parked on live workers,
        #       proper MANAGE-not-BUILD with NO self-transition to show BY DESIGN; OR
        #   (c) 262c59f6 UNIFY — the STORE owed_class says the persona owes nothing
        #       pokeable (DONE / BLOCKED_ON_USER). Cross-check the SAME store authority
        #       the other three detectors read (owed_class_suppresses), so the
        #       activity-tail oracle and the store oracle can no longer contradict
        #       within one poll. ACTIVE / UNKNOWN / unclassified → today's behavior
        #       (fail-SAFE — never silence a real stuck-poke).
        #   (d) 92c7ab1d bridge-fresh — the session's persona'd session-bridge was
        #       touched within the freshness window: ground-truth "took a real turn
        #       recently" liveness (the SAME signal the 26dd3afb MANAGER-STALE veto
        #       reads). `stuck` comes from the ACCUMULATED cap_reached tail with no
        #       recency bound, so a busy manager owning a full board (cap_reached every
        #       turn) stays flagged wedged from stale cap-history while demonstrably
        #       active — owed_class ACTIVE cannot suppress it (fail-SAFE). A fresh
        #       bridge is the missing sign-of-life. INERT when bridge_mtimes is
        #       None/unwired; suppresses ONLY on positive liveness evidence.
        # Dropping a session from `pokeable` ends any in-flight poke episode via the
        # clear-on-resume loop below (the cap re-arms), exactly as a recovery would.
        pokeable = { sid: v for sid, v in pokeable.items()
                     if not self._session_awaiting_user( sid, now )
                     and not self._session_awaiting_peer( sid, now )
                     and not owed_class_suppresses( owed_class.get( v.get( "persona" ) ) )
                     and not self._session_bridge_fresh( v.get( "persona" ), now, bridge_mtimes ) }

        # AUDIENCE SCALPEL (2026-07-19): drop sessions whose audience is silenced.
        # Placed with the other suppressors so a silenced session's episode state is
        # cleared by the loop below exactly like any other de-pokeable session — the
        # cap re-arms cleanly if its audience is re-enabled mid-episode.
        pokeable = { sid: v for sid, v in pokeable.items()
                     if self._poke_audience_enabled( self.audience_for_role( v.get( "role" ) ) ) }

        # episode bookkeeping: a session no longer pokeable ended its episode →
        # clear its state so the cap re-arms (clear-on-resume, mirrors _auto_ping).
        for sid in [ s for s in self._poke_stuck_since if s not in pokeable ]:
            del self._poke_stuck_since[ sid ]
            self._poke_count.pop( sid, None )
            self._poke_escalated.discard( sid )
            self._poke_last_at.pop( sid, None )                   # bug 5a1f17f8 (c): re-arm the throttle on episode end

        fired = 0
        for sid, view in pokeable.items():
            if sid not in self._poke_stuck_since:
                self._poke_stuck_since[ sid ] = now               # episode start (no poke yet)
                self._poke_count[ sid ]       = 0
            if ( now - self._poke_stuck_since[ sid ] ).total_seconds() < self.poke_stall_threshold_seconds:
                continue                                          # not stuck long enough yet
            if self._poke_count[ sid ] < self.poke_max_per_episode:
                # bug 5a1f17f8 (c) fire-throttle: enforce a minimum interval between
                # consecutive stuck-pokes to the SAME session (0 → disabled). The cap
                # bounds pokes PER EPISODE; the throttle bounds their RATE — belt for
                # any residual storm (poll cadence is ~60s; without this the ≤N pokes
                # can all land within N polls). Inert by default; skips this poll's
                # poke WITHOUT consuming the per-episode budget when too soon.
                last_at = self._poke_last_at.get( sid )
                if ( self.stuck_poke_min_interval_seconds > 0 and last_at is not None
                     and ( now - last_at ).total_seconds() < self.stuck_poke_min_interval_seconds ):
                    continue
                recipient   = view.get( "persona" ) or sid
                body        = self._stamp( self._format_poke( view ) )   # Item B: direct-send site (bypasses _route)
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
                self._poke_last_at[ sid ] = now                   # bug 5a1f17f8 (c): stamp for the fire-throttle
                fired += 1
            # OPERATOR audience (2026-07-19): the reap-RECOMMENDATION is Rick-directed
            # (case 13 fans to peer managers too, but Rick is the decider on every
            # tier). Gated on operator so a crew-silenced fleet still surfaces "this
            # session stayed stuck through N pokes" to the human who decides the reap.
            elif sid not in self._poke_escalated and self._poke_audience_enabled( AUDIENCE_OPERATOR ):
                self._poke_escalated.add( sid )
                # ff91cff4: a stuck/dead MANAGER subject escalates its reap-rec to
                # RICK ONLY (case 20) — never fanned to peer managers (managers
                # answer to Rick, not each other). A worker subject keeps the case-13
                # Rick + active-managers fan-out, byte-identical.
                if self._subject_is_manager( view ):
                    self._route( CASE_STUCK_MANAGER_RICK_ONLY,   # → Rick only
                                 self._format_reap_recommendation( view, self._poke_count[ sid ] ) )
                else:
                    self._route( CASE_AUTO_POKE_REAP_REC,             # → Rick + active managers
                                 self._format_reap_recommendation( view, self._poke_count[ sid ] ),
                                 active_managers=active_managers )
            # else: capped AND already escalated → silence (anti-storm)
        return fired

    # ── post-game F2: manager-staleness poke tier (2026-06-11) ──────────────────

    def _format_manager_stale_poke( self, row, age ):
        """
        Builds the bounded, non-destructive staleness nudge sent to a dark manager session.
        """
        who  = row.get( "persona" ) or row.get( "session_id" )
        body = (
            f"{ARBITER_POKE_SENTINEL}manager-staleness poke): {who}, no signal from your "
            f"session for {_fmt_minutes( age )} (threshold "
            f"{self.manager_stale_poke_threshold_seconds}s). Are you wedged or idle-dark? "
            f"Post your status, or — you manage a crew — tap/assign your crew (staff up if "
            f"more tasks than workers); don't resume the work yourself. Rick has been advised. "
            f"(Non-destructive nudge.)"
        )
        # role-goals Phase 2-3: this tier is manager-gated by construction → always
        # the Manager goal echo (inert when unconfigured).
        return self._append_goal_line( body, "manager" )

    def _advisory_cooldown_blocks( self, family, persona, now ):
        """
        Returns True when an advisory for (family, persona) is still inside its cooldown window.

        This is the cross-detector ping-pong guard. A cooldown of 0 disables it. On suppression it logs
        the arbiter_advisory_suppressed_cooldown journal event carrying a running suppressed_count.

        Requires:
            - family is "blocked" / "done" (case-16/17 manager advisories) or
              "blocker-cc" (the blocker-to-manager cc, keyed on the
              (blocker, blocked_item, recipient) string); persona is the subject
              (for "blocker-cc", the blocker-cc key string); now is tz-aware

        Ensures:
            - returns True (and logs) when the (family, persona) cooldown has not
              yet expired; False otherwise (or when the cooldown is disabled)
            - never raises
        """
        if self.manager_advisory_cooldown_seconds <= 0:
            return False
        key   = ( family, persona )
        until = self._advisory_cooldown_until.get( key )
        if until is not None and now < until:
            count = self._advisory_suppressed_count.get( key, 0 ) + 1
            self._advisory_suppressed_count[ key ] = count
            self._log( "arbiter_advisory_suppressed_cooldown",
                       persona=persona, family=family, suppressed_count=count,
                       cooldown_until=until.isoformat() )
            return True
        return False

    def _stamp_advisory_cooldown( self, family, persona, now ):
        """
        Arms the (family, persona) advisory cooldown from `now` and resets its suppression count.

        It does nothing when the cooldown is disabled (0).
        """
        if self.manager_advisory_cooldown_seconds <= 0:
            return
        key = ( family, persona )
        self._advisory_cooldown_until[ key ]   = now + datetime.timedelta( seconds=self.manager_advisory_cooldown_seconds )
        self._advisory_suppressed_count[ key ] = 0

    def _clear_advisory_cooldown( self, family, persona ):
        """
        Clears the (family, persona) advisory cooldown when a real episode ends.

        Called on the staleness freshen re-arm, so a new blocked or done episode re-advises at once.
        It is not called on the acks-path liveness discard: that discard is the ping-pong the cooldown absorbs.
        """
        self._advisory_cooldown_until.pop( ( family, persona ), None )
        self._advisory_suppressed_count.pop( ( family, persona ), None )

    def _check_manager_staleness( self, snapshot, now, active_managers, owed_class=None, store_read_degraded=False, bridge_mtimes=None ):
        """
        Pokes and advises on a manager-role session whose freshest liveness signal is too old.

        Such a manager gets a bounded poke and a Rick advisory, even with no stuck workers.
        Workers are untouched: the gate is role == "manager", taken from the injected list_managers_fn
        and surfaced on the snapshot row. A quiet heads-down worker is not a stalled one.

        Requires:
            - snapshot is the full (include_offline=True) detection snapshot
            - now is an aware datetime; active_managers a list or None

        Ensures:
            - no-op (returns 0) when the threshold is 0 (tier disabled)
            - a row is eligible iff role == "manager" and freshest_age_s is not None and threshold <= freshest_age_s <= max_age; None means no signal ever, a corpse or malformed row, so it is not eligible; the ceiling means this manager went dark recently, not that a corpse exists, because the offline snapshot resurfaces dead manager rows on every process start and an age beyond max_age is a corpse, not a dark manager
            - ≤ poke_max_per_episode pokes + exactly one advisory per episode
            - returns the count of staleness pokes fired this poll; never raises
            - the advisory fires on the first threshold crossing, the same poll as poke 1, not after the pokes run out: a poke at a dark session is best effort (it may have no self-wake), so the advisory is the main output; episode state clears when the manager freshens or leaves the roster, which re-arms the cap and the advisory
            - the master auto_poke_enabled gates the whole tier but the manager audience does not: the poke is gated by the manager audience and the advisory by the operator audience, each at its own emission, so silencing the crew never hides a dark manager from Rick
            - the store class decides first: a `BLOCKED_ON_USER` manager gets at most one awaiting-Rick advisory and a `DONE` manager at most one consider-reaping advisory, never the repeating poke; the advised flags are shared with `_check_manager_acks`, so a manager both tapped and stale is advised once across both detectors, and a suppressed manager that freshens re-arms; `ACTIVE` and `UNKNOWN` classes get the poke (`UNKNOWN` is fail-safe, so an all-stale quota freeze still escalates)
            - the test for a `MANAGER-STALE` advisory is whether the manager owes work that is not gated on Rick, not whether a signal exists, because there can be no signal while it idles and waits
            - a fresh honored awaiting-user hold (or an open user gate) is defended quiescence, not staleness: the open-gate override makes the store report such a manager as active, so the hold is read directly; it gets one advisory and no poke, and this check runs before the velocity lever
            - a stale row whose persona has a fresh row on another session id is a superseded ghost and is skipped, because the poke is persona-addressed and would reach the live twin; a future (negative-age) mtime never counts as live
            - a fresh persona bridge mtime vetoes the poke, since the union age can read stale while the manager is alive; a degraded owed read this poll suppresses the escalation and starts no episode
            - velocity lever: when a persona's last-signal time has advanced across manager_stale_velocity_suppress_streak consecutive episodes (0 disables it) it is alive on a slow cadence, so that episode's advisory and poke are suppressed and logged; a frozen last signal resets the streak, so a wedged manager still gets poked
        """
        if self.manager_stale_poke_threshold_seconds <= 0:
            return 0

        # MASTER-GATE HOLE, closed 2026-07-19 (Mr. Radio). This tier read ONLY its
        # own threshold — `auto_poke_enabled = false` silenced the STUCK tier while
        # manager-staleness pokes kept firing, so the documented "auto-poke master
        # gate" was never actually master. Checking the master here makes Job 1's
        # panic button absolute as advertised.
        #
        # The MASTER only — deliberately NOT the manager audience. This tier emits to
        # TWO audiences: the manager-directed poke (AUDIENCE_MANAGER, gated at its
        # emission below) and Rick's MANAGER-STALE advisory (AUDIENCE_OPERATOR, gated
        # at its own emission). Returning early on managers-off would silence Rick's
        # "your manager went dark" advisory too — precisely the signal he asked to
        # KEEP while silencing the crew. Audience gating belongs at each emission.
        if not self.auto_poke_enabled:
            return 0

        owed_class = owed_class or { }

        # PERSONA-TWIN SUPPRESSION (Tiberius 2026-06-27, bug 7c931b3a — the INVERSE
        # sibling of 8a450183's persona-collapse filter). A RE-SPUN manager keeps its
        # OLD (reaped/superseded) session row in the include_offline detection
        # snapshot until that row ages past the corpse ceiling. For the whole ~45-min
        # span between "went dark" and "aged out", the ghost row's freshest_age_s
        # climbs ~1/poll and lands inside [threshold, max_age] — so this tier flags
        # it. But the poke is PERSONA-ADDRESSED (_emit_dm targets the persona, not the
        # session_id), so a dead incarnation's "silent 47m" nudge is delivered to the
        # LIVE twin (a NEW session_id, same persona) that is actively working — false
        # MANAGER-STALE spam + a Rick advisory per episode (the 2026-06-27 mr radio
        # cd637762/54622550 case: the render table showed 'mr radio LIVE 3s/1m' on the
        # SAME poll the poke fired for the dead 54622550 row). The discriminator: the
        # persona is demonstrably ALIVE on a DIFFERENT session_id. Build the set of
        # personas with ≥1 FRESH (sub-threshold) row and suppress a stale row whose
        # persona is live elsewhere — the row is a superseded ghost, never a dark
        # manager. A persona with NO live incarnation anywhere is UNTOUCHED (the
        # genuine-darkness true-positive — incl. the all-stale quota-freeze — is
        # preserved). 8a450183 gates by SESSION-id freshness for peer-EDGE inference;
        # this is the outreach-side dual: a live twin under any session_id mutes the
        # ghost's persona-addressed poke.
        live_personas = set()
        for row in ( snapshot or { } ).get( "sessions", [ ] ):
            if not isinstance( row, dict ):
                continue
            persona  = row.get( "persona" )
            liveness = row.get( "liveness" )
            fa       = liveness.get( "freshest_age_s" ) if isinstance( liveness, dict ) else None
            # 0 <= fa lower bound (bug 46eb7b98, sibling of 097778b8): a FUTURE /
            # corrupt union mtime (clock skew ⇒ negative freshest_age_s) is NOT
            # ground-truth liveness → do not count it live, else it would shield a
            # genuinely-stale twin of the same persona from its warranted poke.
            # Fail toward action (poke), never toward silent suppression. (The
            # eligibility gate below already excludes negatives via threshold>0.)
            if persona and fa is not None and 0 <= fa < self.manager_stale_poke_threshold_seconds:
                live_personas.add( persona )

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
            # Checked BEFORE the twin guard so a FRESH twin row (age < threshold)
            # falls through silently — only an otherwise-pokeable row is suppressed.
            if age is None or not (
               self.manager_stale_poke_threshold_seconds <= age <= self.manager_stale_poke_max_age_seconds ):
                continue
            # persona-twin guard: this stale row's persona is LIVE on another
            # incarnation → superseded ghost; poking it persona-addresses the live
            # twin. Skip + log (so the suppression is auditable on the next re-spin).
            persona = row.get( "persona" )
            if persona is not None and persona in live_personas:
                self._log( "arbiter_manager_stale_twin_suppressed",
                           session_id=sid, persona=persona, freshest_age_s=age )
                continue
            # BRIDGE-MTIME VETO (bug 26dd3afb): the union freshest_age_s can read
            # stale even while the manager is demonstrably alive — its hooks-driven
            # session-bridge file was touched seconds ago but that mtime never
            # reached the union (sid→bridge resolution gap; or a re-spun twin whose
            # LIVE bridge is under a different session_id the live_personas guard
            # above didn't catch — the 2026-07-02 Tiberius false-positive). A fresh
            # bridge is ground-truth liveness → this manager is NOT stale. Keyed by
            # PERSONA (the always-present analog of the sid-keyed union signal; also
            # catches the twin case). bridge_mtimes None → seam unwired / read failed
            # → INERT (today's behavior). Placed AFTER the twin guard so a live-in-
            # snapshot twin logs the more-specific twin suppression.
            if bridge_mtimes and persona is not None:
                bridge_mtime = bridge_mtimes.get( canonical_persona_key( persona ) )
                # 0 <= age lower bound (bug 097778b8): a FUTURE bridge mtime (clock
                # skew/corruption ⇒ negative age) is NOT ground-truth liveness → do
                # not veto; fail toward poking (the safe direction).
                if bridge_mtime is not None and 0 <= ( now.timestamp() - bridge_mtime ) <= self.manager_stale_poke_threshold_seconds:
                    self._log( "arbiter_manager_stale_bridge_veto",
                               session_id=sid, persona=persona, freshest_age_s=age,
                               bridge_age_s=( now.timestamp() - bridge_mtime ) )
                    continue
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
                self._clear_advisory_cooldown( "blocked", persona )   # bug 58660c64: genuine episode end re-arms the cooldown too
            else:
                self._manager_done_advised.discard( persona )
                self._clear_advisory_cooldown( "done", persona )

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
                    if not self._advisory_cooldown_blocks( "blocked", persona, now ):   # bug 58660c64 ping-pong guard
                        self._stamp_advisory_cooldown( "blocked", persona, now )
                        self._route(
                            CASE_MANAGER_AWAITING_USER,               # f48f089d: → Rick only (mirror case 20)
                            f"MANAGER-AWAITING-RICK (advisory, NOT manager-stale): {persona} is "
                            f"silent {_fmt_minutes( age )} but correctly BLOCKED on Rick — every "
                            f"owed item is Rick-gated. The silence IS the expected state, not a "
                            f"stall; one-time notice, no poke."
                        )
                continue
            if cls == CLASS_DONE:
                if persona not in self._manager_done_advised:
                    self._manager_done_advised.add( persona )
                    self._mgr_stale_suppressed[ sid ] = ( CLASS_DONE, persona )
                    if not self._advisory_cooldown_blocks( "done", persona, now ):      # bug 58660c64 ping-pong guard
                        self._stamp_advisory_cooldown( "done", persona, now )
                        self._route(
                            CASE_MANAGER_DONE_ADVISORY,               # f48f089d: → Rick only (mirror case 20)
                            f"MANAGER-DONE (advisory, NOT manager-stale): {persona} is silent "
                            f"{_fmt_minutes( age )} and owes NO non-terminal work — it appears "
                            f"finished/idle. Consider reaping it (the arbiter never reaps). "
                            f"One-time notice, no poke.",
                        )
                continue
            # item 285c0343 Lever A — HOLD-GATING (the hold-side dual of the owed_class
            # BLOCKED_ON_USER branch above). owed_class reads the STORE, where the
            # 6929f4ac open-gate override reclassifies an awaiting-user session as
            # CLASS_ACTIVE (it owes Rick a re-ask) — so a manager PARKED awaiting Rick's
            # gate answer reaches HERE classed ACTIVE and would draw the case-14 poke
            # (the 2026-07-07 episode-2 false positive). The awaiting-user truth lives
            # ONLY in the hold artifact; read it. A FRESH HONORED hold declaring
            # awaiting:user:* (or holding ≥1 OPEN user-gate — which already covers a
            # defer_to_chase gate carrying a future next_chase_ts) is defended
            # quiescence, NOT staleness → suppress the repeating case-14 poke, emit AT
            # MOST ONE case-16 advisory via the SHARED _manager_blocked_advised set
            # (cross-detector de-dupe with #9, no Rick double-page; re-arm reuses the
            # _mgr_stale_suppressed loop). Placed BEFORE the store-health gate and the
            # velocity lever so a defended hold (ground truth from the artifact) wins.
            # Inert when the hold-reader seam is unwired (_session_awaiting_user → False)
            # → today's escalation preserved. Layered pair with Lever B: an EXPIRED hold
            # (is_honored=False) falls THROUGH here to the velocity check below.
            if self._session_awaiting_user( sid, now ):
                _facets = self._awaiting_user_hold_facets( sid )     # Q1 rider: awaiting + soonest next_chase_ts for María's audit
                self._log( "arbiter_manager_stale_suppressed_awaiting_user_hold",
                           session_id=sid, persona=persona, freshest_age_s=age,
                           awaiting=_facets.get( "awaiting" ),
                           soonest_next_chase_ts=_facets.get( "soonest_next_chase_ts" ) )
                if persona not in self._manager_blocked_advised:
                    self._manager_blocked_advised.add( persona )
                    self._mgr_stale_suppressed[ sid ] = ( CLASS_BLOCKED_ON_USER, persona )
                    if not self._advisory_cooldown_blocks( "blocked", persona, now ):   # bug 58660c64 ping-pong guard
                        self._stamp_advisory_cooldown( "blocked", persona, now )
                        self._route(
                            CASE_MANAGER_AWAITING_USER,               # f48f089d: → Rick only (mirror case 20)
                            f"MANAGER-AWAITING-RICK (advisory, NOT manager-stale): {persona} is "
                            f"silent {_fmt_minutes( age )} but its honored hold declares it PARKED "
                            f"awaiting Rick — defended quiescence, not a stall. One-time notice, no poke."
                        )
                continue
            # ACTIVE / UNKNOWN → today's case-14 poke + Rick advisory (UNKNOWN = fail-SAFE)
            # 33949e83 STORE-HEALTH GATE: a self-observed degraded owed read this poll
            # means the manager's "silence" is an infra outage artifact, not darkness →
            # SUPPRESS the case-14 escalation (UNKNOWN-INFRA) and do NOT start an episode
            # → re-arms on the next CLEAN read window. Mirrors the MANAGER-DOWN gate.
            if store_read_degraded:
                self._log( "arbiter_manager_stale_suppressed_infra",
                           session_id=sid, persona=persona, freshest_age_s=age )
                continue
            if sid not in self._mgr_stale_since:
                self._mgr_stale_since[ sid ] = now                # episode start
                self._mgr_poke_count[ sid ]  = 0
                # item 285c0343 Lever B — LAST-SIGNAL VELOCITY (updated ONCE per episode,
                # here at episode start). A manager whose last-signal ADVANCED since the
                # prior episode is alive on a wake-tick-park rhythm SLOWER than the 45m
                # threshold (mr radio 13:08→13:59→14:59→15:59, four false episodes, all
                # advancing) — definitionally NOT stale. Track the streak of consecutive
                # advancing episodes; a NON-advancing (frozen) last-signal RESETS it, so a
                # genuinely-wedged manager (last-signal stuck) still pokes — the real-stall
                # true positive Tiberius requires. Persona-keyed state survives the per-sid
                # episode clear + re-spins.
                last_seen = now - datetime.timedelta( seconds=age )
                prior     = self._mgr_last_signal_seen.get( persona )
                if prior is not None and last_seen > prior:
                    self._mgr_velocity_streak[ persona ] = self._mgr_velocity_streak.get( persona, 0 ) + 1
                else:
                    self._mgr_velocity_streak[ persona ] = 0
                self._mgr_last_signal_seen[ persona ] = last_seen
            # Lever B suppress guard (streak is stable within an episode): at/above the
            # configured advancing-streak threshold ⇒ alive-on-a-cadence ⇒ suppress this
            # episode's advisory + poke (the episode counter above is still opened so the
            # re-arm on freshen stays symmetric). 0 disables the lever. Distinct log
            # outcome for María's audit — never silent.
            if ( self.manager_stale_velocity_suppress_streak > 0
                 and self._mgr_velocity_streak.get( persona, 0 ) >= self.manager_stale_velocity_suppress_streak ):
                self._log( "arbiter_manager_stale_suppressed_velocity",
                           session_id=sid, persona=persona, freshest_age_s=age,
                           advancing_streak=self._mgr_velocity_streak.get( persona, 0 ) )
                continue
            # Rick advisory: FIRST crossing, same poll as poke #1. OPERATOR audience
            # (2026-07-19) — survives `poke managers enabled = false`, so silencing
            # the crew never blinds Rick to a manager going dark.
            if sid not in self._mgr_advised and self._poke_audience_enabled( AUDIENCE_OPERATOR ):
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
                    exclude_persona=persona,                         # b9911943: not to the subject itself
                )
            # MANAGER audience (2026-07-19): the manager-DIRECTED half of this tier.
            # Silenced independently of the Rick advisory above.
            if ( self._mgr_poke_count[ sid ] < self.poke_max_per_episode
                 and self._poke_audience_enabled( AUDIENCE_MANAGER ) ):
                # observability (Mr Radio's handoff ask): log the FULL per-component
                # liveness breakdown of every row we actually poke, so a future
                # false-positive is self-diagnosing (the dead component is visible
                # without re-deriving it from raw event logs).
                _liv = row.get( "liveness" ) if isinstance( row.get( "liveness" ), dict ) else { }
                self._log( "arbiter_manager_stale_poke_components",
                           session_id=sid, persona=persona, age_s=age,
                           bridge_age_s=_liv.get( "bridge_age_s" ),
                           event_age_s=_liv.get( "event_age_s" ),
                           commons_age_s=_liv.get( "commons_age_s" ),
                           idle_prompt_age_s=_liv.get( "idle_prompt_age_s" ),
                           dm_age_s=_liv.get( "dm_age_s" ),
                           hold_age_s=_liv.get( "hold_age_s" ) )
                body        = self._stamp( self._format_manager_stale_poke( row, age ) )   # Item B: direct-send site
                outreach_id = self._mint_outreach_id()
                self._log_outreach( "manager_stale_poke", "send_to", [ persona ], body,
                                    session_id=sid, persona=persona,
                                    outreach_id=outreach_id )
                # no ack owed: the poke targets a DARK session (it may have no
                # self-wake); the case-14 Rick advisory is the load-bearing output
                self._emit_dm( outreach_id, "manager_stale_poke", persona, body, session_id=sid, expects_ack=False )
                self._mgr_poke_count[ sid ] += 1
                fired += 1
            # else: poke-capped — the advisory already fired; silence (anti-storm)
        return fired

    # ── 6929f4ac: outward-twin user-gate resurface (dark session → Rick) ────────

    def _check_user_gate_resurface( self, snapshot, now, owed_items=None ):
        """
        Resurfaces an aged open user gate to Rick when its session has gone dark.

        A dark session has stopped re-asking, so the arbiter surfaces the buried question to Rick on its
        behalf (case 18, Rick-only). The primary mechanism is the Stop-hook self-poke; this is the external
        backstop for when that self-regulation has gone dark.

        Requires:
            - snapshot is the full (include_offline=True) detection snapshot
            - now is an aware datetime

        Ensures:
            - returns 0 when the hold-reader seam is unwired (inert)
            - resurfaces each newly-eligible aged gate exactly once (case 18 to Rick)
            - returns the count resurfaced this poll; never raises
            - inert in two layers: an unwired hold reader returns 0 with no work, and a wired one does nothing when no session is both dark and holding an aged open gate; a hold-read error degrades that session to "no gate seen" and never kills the poll
            - a session is dark when its liveness verdict is "offline" or its freshest signal age is unknown or at least user_gate_resurface_seconds; an aged gate is an open gate whose last_asked_ts is older than that same ceiling
            - escalates once per (session, gate); a gate that clears or a session that freshens leaves the eligible set, so its key re-arms for a future episode
            - a persona whose owed read shows a future per-user chase deferral is not nagged: the arbiter reads the same hold file as the seat, so it must honor the same deferral or fixing the seat would only move the nag; with no owed read nothing is suppressed, so an open decision is never buried
        """
        if self._hold_reader_fn is None:
            return 0
        ceiling   = self.user_gate_resurface_seconds
        now_epoch = now.timestamp()
        eligible  = { }    # "<sid>:<gate_id>" -> ( sid, persona, gate )
        for row in ( snapshot or { } ).get( "sessions", [ ] ):
            if not isinstance( row, dict ):
                continue
            sid = row.get( "session_id" )
            if not sid:
                continue
            liveness = row.get( "liveness" ) if isinstance( row.get( "liveness" ), dict ) else { }
            age      = liveness.get( "freshest_age_s" )
            is_dark  = ( liveness.get( "verdict" ) == "offline" ) or age is None or age >= ceiling
            if not is_dark:
                continue
            try:
                hold = self._hold_reader_fn( sid )
            except Exception:
                hold = None
            persona = row.get( "persona" ) or sid
            # be56bff8 per-USER deferral: the arbiter reads the SAME hold file as the
            # seat, so it must honor the same store deferral — else fixing the seat
            # but not the arbiter just MOVES the nag. Derive this persona's per-user
            # chase from the per-poll owed read (blocked_by:[{kind:user}] future
            # chase); a deferred user ⇒ aged_open_gates returns nothing to resurface.
            # owed_items None (store read failed / seam unwired) ⇒ None ⇒ no
            # suppression (fail-safe toward liveness — never bury an open decision).
            user_chase = derive_user_chase_until(
                ( owed_items or { } ).get( persona ), now_epoch ) if owed_items else None
            for gate in aged_open_gates( get_pending_user_gates( hold ), now_epoch, ceiling,
                                         user_chase_until_epoch=user_chase ):
                eligible[ f"{sid}:{gate.get( 'id' )}" ] = ( sid, persona, gate )
        # re-arm: drop already-resurfaced keys no longer eligible (gate cleared /
        # session freshened) so a future dark episode re-surfaces.
        self._resurfaced_gates &= set( eligible )
        fired = 0
        for key, ( sid, persona, gate ) in eligible.items():
            if key in self._resurfaced_gates:
                continue
            self._resurfaced_gates.add( key )
            question = gate.get( "question" ) or "(question text unavailable)"
            ask_kind = gate.get( "ask_kind" ) or "unknown"
            self._route(
                CASE_USER_GATE_RESURFACE,
                f"USER-GATE RESURFACED (on behalf of a dark session): {persona} "
                f"({sid[ :8 ]}) went silent still awaiting your answer to a direct "
                f"gate and has stopped re-asking it — surfacing it so it reaches "
                f"you. Question: \"{question}\" (ask kind: {ask_kind}).",
            )
            fired += 1
        return fired

    def _route_operator_gates( self, now ):
        """
        Pushes open store operator gates to Rick, routed by urgency.

        The arbiter is the single pusher of operator gates. It is a thin consumer of the pure router
        operator_gate_routing.route_operator_gates.

        Requires:
            - now is an aware datetime (the poll clock)

        Ensures:
            - returns the count of arbiter emissions this poll (urgent interrupts +
              at most one digest); never raises
            - urgent gates interrupt Rick at once, escalating once per gate; the de-dup is re-armed to the present urgent set, so a cleared-then-reopened or re-tiered gate fires again
            - normal gates are batched into one digest emitted at most every operator_digest_cadence_seconds; the digest clock is stamped only on emission, and route_operator_gates returns an empty digest until the cadence elapses
            - each poll reads every open operator gate fleet-wide through the store seam (by gate_class, not per session), so a gate is seen whether its owning session is alive or dark
            - low gates are pull-only and never auto-pushed
            - returns 0 when the seam is unwired (operator_gates_fn None); a store-read error degrades to "no gates seen" and never kills the poll
        """
        if self._operator_gates_fn is None:
            return 0
        try:
            gates = self._operator_gates_fn()
        except Exception:
            gates = None
        gates   = [ g for g in ( gates or [ ] ) if isinstance( g, dict ) ]
        verdict = route_operator_gates(
            gates, self._last_operator_digest_ts, now, self.operator_digest_cadence_seconds )

        fired = 0
        # URGENT — interrupt each, escalate-once. Re-arm to the present urgent set so a
        # gate that cleared (answered / re-tiered / removed) re-fires if it re-opens.
        present_urgent = { g.get( "id" ) for g in verdict[ "interrupt" ] }
        self._routed_operator_gates &= present_urgent
        for gate in verdict[ "interrupt" ]:
            gid = gate.get( "id" )
            if gid in self._routed_operator_gates:
                continue
            self._routed_operator_gates.add( gid )
            title = gate.get( "title" ) or "(untitled)"
            owner = gate.get( "owner_persona" ) or "a session"
            self._route(
                CASE_OPERATOR_GATE,
                f"URGENT operator gate awaiting your decision (from {owner}): "
                f"\"{title}\". Marked urgent — it needs you now.",
            )
            fired += 1

        # NORMAL — one batched digest when the cadence is due (route returns [] until
        # then). Stamp the clock ONLY on an actual emission so a due-but-empty poll
        # keeps the window open for the next normal gate.
        digest = verdict[ "digest" ]
        if digest:
            titles = [ ( g.get( "title" ) or "(untitled)" ) for g in digest ]
            head   = "; ".join( titles[ :OPERATOR_DIGEST_LIST_CAP ] )
            more   = len( titles ) - OPERATOR_DIGEST_LIST_CAP
            if more > 0:
                head += f"; +{more} more"
            self._route(
                CASE_OPERATOR_GATE,
                f"Operator-gate digest: {len( titles )} normal-urgency gate(s) awaiting "
                f"your decision — {head}. (Urgent gates interrupt separately; low-urgency "
                f"gates wait in the queue until you pull them.)",
            )
            self._last_operator_digest_ts = now.isoformat()
            fired += 1

        return fired

    # ── post-game F3: fleet-dark advisory (hybrid trigger, 2026-06-11) ──────────

    def _check_fleet_dark( self, snapshot, published_count, now ):
        """
        Advises Rick once per dark episode when the published fleet roster drops to zero.

        The advisory (case 15) goes to Rick only, since no managers remain. Without it a full-fleet death was
        silent: the stall check needs live owed work, so an empty roster never stall-escalates.

        Ensures:
            - tracks the freshest manager signal ever observed (persona + wall
              time) for the advisory body, labeled in EDT
            - fires at most once per dark episode (flag re-arms on count > 0);
              a mid-dark restart re-fires at most once per process
            - returns 1 on a new advisory else 0; never raises
            - the trigger is hybrid: a pure edge (previous published count > 0 and current == 0) loses its state on a service restart, because the snapshot store is in memory and dies with the process; so a recovery path also fires, evaluated only while no nonzero roster has been seen this process (a boot straight into darkness), when some session in the full snapshot still shows a signal younger than DARK_LOOKBACK_SECONDS
            - a cold boot over a roster reaped the previous evening has no signal that fresh, so it stays silent and sends no daily page
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
        Returns the preconditions that blocked a stuck-tier wake-nudge for one session this poll.

        It runs after _auto_poke, so episode state is current.

        Ensures:
            - returns [] iff a stuck-tier poke would fire; else the failed
              preconditions in evaluation order, from
              { disabled, audience_disabled, not_alive, not_stuck, below_threshold,
                capped, already_escalated }; never raises
            - `disabled` is the master gate; `audience_disabled` is this session's audience (worker|manager) being silenced under a live master, kept distinct so an outreach silence names which knob caused it
        """
        why = [ ]
        if not self.auto_poke_enabled:
            why.append( "disabled" )
        elif not self._poke_audience_enabled(
                self.audience_for_role( view.get( "role" ) if isinstance( view, dict ) else None ) ):
            why.append( "audience_disabled" )
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
        Returns the preconditions that blocked a manager-staleness poke for one session.

        It reads the full-snapshot row, which carries role and freshest_age_s.

        Ensures:
            - returns [] iff a staleness poke would fire; else the failed
              preconditions from { tier_disabled, disabled, audience_disabled,
                not_manager, no_signal, not_stale, beyond_max_age, mgr_capped };
              never raises
            - `disabled` (master) and `audience_disabled` (manager audience) report the audience gates; this vector describes the manager-directed poke, which is the half those knobs silence, while Rick's case-14 advisory rides the operator audience and can still fire when this reads audience_disabled
            - a None age reads `no_signal` (a corpse or malformed row) and an age past the ceiling reads `beyond_max_age` (a corpse resurfaced by the include_offline snapshot, not a recently-dark manager)
        """
        why = [ ]
        if self.manager_stale_poke_threshold_seconds <= 0:
            why.append( "tier_disabled" )
        if not self.auto_poke_enabled:
            why.append( "disabled" )
        elif not self._poke_audience_enabled( AUDIENCE_MANAGER ):
            why.append( "audience_disabled" )
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
        Journals why each session was or was not poked, on change and in periodic full dumps.

        An outreach silence stays diagnosable this way: "evaluated and correctly declined" versus "never
        evaluated" versus "fired and delivery failed".

        Ensures:
            - emits `arbiter_poke_gate` per session whose (stuck_why, stale_why)
              signature changed since its last emission, or unconditionally on a
              dump poll (every GATE_DUMP_INTERVAL_POLLS polls; poll 0 = the baseline dump)
            - a session leaving the fleet view emits one { evicted: True } event
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
        Runs the poll loop, poll then sleep, until cancel or the hard cap.

        Ensures:
            - exits on self._cancel_requested or elapsed >= max_duration_seconds
            - a per-poll exception is swallowed (the observer invariant: one bad
              poll never kills the arbiter) and demoted to a render-sink log; it
              escalates to Rick (notify_fn) only when persistent
              (≥ poll_error_escalate_threshold consecutive failures), once per failure streak;
              a clean poll resets the streak and re-arms the escalation
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
        Handles a swallowed per-poll exception, escalating to Rick only when it persists.

        Ensures:
            - increments the consecutive-error streak
            - at/after poll_error_escalate_threshold consecutive failures, escalates
              once to Rick (notify_fn, "arbiter effectively down"); below it, logs a
              transient line to the render sink (no Rick spam on a one-off hiccup)
            - never raises
        """
        self._poll_error_streak += 1
        if ( self._poll_error_streak >= self.poll_error_escalate_threshold
             and not self._poll_error_escalated ):
            self._poll_error_escalated = True
            body = self._stamp(                                     # Item B: direct-send site (bypasses _route)
                f"ARBITER POLL-ERROR persistent: {self._poll_error_streak} consecutive poll "
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
