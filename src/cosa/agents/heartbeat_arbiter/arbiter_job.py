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
import os
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
from cosa.agents.heartbeat_arbiter.dependency_graph import (
    build_graph, build_store_wait_edges, cycle_is_store_backed, hold_is_stale,
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
from lupin_cli.claude_code.hooks.lib.heartbeat_user_gates import open_gates, aged_open_gates
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


def _default_known_owners_fn():   # pragma: no cover - production store-read IO boundary
    """
    Default KNOWN-OWNER store reader (262c59f6 option A — the known-persona
    fail-safe belt). Return the DISTINCT set of `owner_persona` values across ALL
    store rows (any status) — the personas the store recognizes as real owners of
    work. Feeds `_classify_owed`'s DONE→UNKNOWN downgrade: a would-be-DONE persona
    whose canonical label is NOT in this set is a likely re-spin / label-contamination
    false DONE (an empty read from a mismatched label), not genuine completion.

    ALL statuses (not just non-terminal) BY DESIGN: a genuinely-finished persona
    ('mr radio' with only terminal rows) MUST remain a known owner so its real
    completion still classifies DONE — only a persona that never owned ANY row (the
    spurious canonicalized key) is treated as contamination. ONE DB session per poll.
    The classification LOGIC that consumes this is fully unit-tested via an injected
    fake, so this IO boundary is no-cover (mirrors _default_owed_work_fn).

    Ensures:
        - returns an iterable of owner_persona strings (canonicalization happens in
          the caller `_read_known_owners`)
        - raising is acceptable — `_read_known_owners` swallows any exception into
          None (fail-SAFE: the downgrade goes inert, never mass-UNKNOWNs the fleet)
    """
    from cosa.rest.db.database import get_db
    from cosa.rest.db.repositories.task_repository import TaskRepository
    with get_db() as session:
        repo = TaskRepository( session )
        return { it.owner_persona for it in repo.query_tasks() if it.owner_persona }


def _default_operator_gates_fn():   # pragma: no cover - production store-read IO boundary
    """
    Default OPEN-operator-gate store reader (proactive-manager A2/A3, fcb5dbc0).

    The arbiter as the SINGLE pusher of operator gates: return EVERY open
    (non-terminal) `gate_class='operator'` item, FLEET-WIDE — one DB session per
    poll. Because the read is by gate_class (NOT per-session/per-persona), it sees
    a gate regardless of whether the owning session is alive or DARK — that is what
    extends the case-18 dark-only resurface to ALL open operator gates. The routing
    LOGIC that consumes this list (operator_gate_routing.route_operator_gates) is
    fully unit-tested via an injected fake, so this IO boundary is no-cover
    (mirrors _default_owed_work_fn / build_arbiter_job).

    Ensures:
        - returns a list of { id, title, status, gate_class, urgency, owner_persona }
          for each open operator gate (urgency drives the D4 routing tier)
        - raising is acceptable — the caller (_route_operator_gates) swallows any
          exception into an empty read (observer invariant: never crash the poll)
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


def _default_hold_mtime_fn( session_id ):   # pragma: no cover - production hold-file mtime IO boundary
    """
    Default hold-file mtime reader — the hold-as-liveness store source (task 70be69f2).

    Returns the epoch-seconds mtime of the session's `.heartbeat-hold-<sid>.json`
    artifact (project-root scoped via heartbeat_hold.hold_path), or None when no
    hold file exists / the stat fails. The mtime bumps every time the session
    re-stamps its hold (each Stop refreshes held_at → the file is rewritten), so a
    fresh mtime is an unambiguous sign the session's process is ALIVE — the fix for
    the MANAGER-STALE false-positive at an interactive, no-`/loop` manager that
    refreshes its hold but posts nothing to commons (Tiberius's sess 6ec69a8c).

    Mirrors session_bridge.get_bridge_mtime: a per-session epoch-float reader the
    arbiter calls out-of-band (in _publish_fleet_snapshot) so compute_liveness
    stays pure. Exercised at the :8000 integration tier like _default_bridge_mtime_fn;
    the LOGIC that folds the mtime into the verdict is fully unit-tested via an
    injected fake, so this IO boundary is no-cover (mirrors _default_dm_activity_fn).

    Ensures:
        - returns the hold-file mtime (epoch float) or None (no file / stat error)
        - never raises — a missing hold or stat hiccup degrades to None (the other
          5 signals carry liveness; ADDITIVE + fail-safe per the observer invariant)
    """
    try:
        return os.path.getmtime( hold_path( session_id ) )
    except OSError:
        return None


def _default_transcript_mtime_fn( session_id ):   # pragma: no cover - production transcript-file mtime IO boundary
    """
    Default transcript-file mtime reader — the transcript-as-liveness store
    source (bug fb332fcd, the 7th liveness signal).

    Resolves the session's bridge dict via session_bridge.find_session_by_id
    (full-uuid or 8-char-prefix match, dead-PID-aware) and returns the
    epoch-seconds mtime of its `transcript_path` `.jsonl` artifact. The harness
    appends a turn to that file on every assistant/tool event, so a fresh mtime
    is an unambiguous sign the session's process is ALIVE — including mid-plan,
    when no `Stop` fires and the other six signals (bridge/event/commons/
    idle_prompt/dm/hold) all age past STALE → the MANAGER-STALE false-positive
    at a manager deep in an approved plan (the fb332fcd live hit, 2026-06-30).

    Mirrors _default_hold_mtime_fn: a per-session epoch-float reader the arbiter
    calls out-of-band (in _publish_fleet_snapshot) so compute_liveness stays
    pure. Exercised at the :8000 integration tier like the other mtime readers;
    the LOGIC that folds the mtime into the verdict is fully unit-tested via an
    injected fake, so this IO boundary is no-cover (mirrors _default_hold_mtime_fn).

    FAIL-SAFE (fb332fcd non-negotiable #1): a missing bridge, an absent/empty
    transcript_path, or a stat failure all degrade to None — NO signal, never a
    spurious-fresh mtime. A genuinely-dark session (transcript stops appending,
    or the path is gone) therefore STILL ages to STALE; the other 6 signals
    carry liveness (ADDITIVE + fail-safe per the observer invariant).

    Ensures:
        - returns the transcript-file mtime (epoch float) when resolvable
        - returns None on any failure (no bridge / no transcript_path / stat error)
        - never raises
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
        deadlock_dwell_seconds     : int                = 300,    # store-backed ring must PERSIST this long before escalating (progressing-wait belt; 0 → fire on first corroborated sight)
        fleet_stall_window_seconds : int                = 1800,
        poll_error_escalate_threshold : int             = 3,
        auto_poke_enabled        : bool                 = True,
        poke_stall_threshold_seconds : int              = 720,    # ~12 min
        poke_max_per_episode     : int                  = 3,
        manager_stale_poke_threshold_seconds : int      = 2700,   # post-game F2 (~45 min; 0 disables)
        manager_stale_poke_max_age_seconds : int        = 7200,   # corpse ceiling (~2h; must be > threshold)
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
        worktree_janitor_fn      : Optional[ Callable ] = None,   # §4b janitor: per-poll abandoned-worktree reconcile (None → INERT, no sweep; the :8001 factory wires worktree_reaper.reconcile_worktrees)
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
        self._offsets       = { }                                  # sid -> byte offset
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
        pings_fired = self._auto_ping( ping_edges, now, persona_to_sid )  # #4 blocker + cc mgr (store-backed only)
        roster      = build_roster( fleet_view, now, self.quiet_threshold_seconds,
                                     alive_threshold_seconds=self.alive_threshold_seconds )  # free-count fix: live-idle only (session_is_stale gate)
        # #6 roster broadcast DROPPED (Part-6 cut) — the fleet roster is PULL-state,
        # served by /state via the snapshot below; no per-tick commons post.
        taps_fired    = self._tap_managers( fleet_view, graph, roster, now, active_managers )  # #7 / #8
        managers_down = self._check_manager_acks( now, who_rows, fleet_view, active_managers, owed_class=owed_class, count_dm=count_dm, owed_items=owed_items, store_read_degraded=store_degraded )  # #9 (L1 store-aware, 5-signal ACK; owed_items → de3c5b87/33949e83 diagnostics; store gate)
        decisions     = self._check_decision_needed( now )          # #10 Rick (+owning mgr if known)
        stalled       = self._check_fleet_stall( fleet_view, now, active_managers, owed_class=owed_class )  # #11 (L1 store-aware)
        pokes_fired   = self._auto_poke( fleet_view, now, active_managers, owed_class=owed_class )  # 2b-3 auto-poke (262c59f6 store-aware)
        rendered      = self._publish_fleet_snapshot( fleet_view, now, count_dm )
        # post-game F2/F3 detectors read the FULL (include_offline=True) detection
        # snapshot + published count the publish step just stashed on the instance.
        manager_stale_pokes = self._check_manager_staleness( self._last_full_snapshot, now, active_managers, owed_class=owed_class, store_read_degraded=store_degraded )  # #F2 (L1 store-aware, lane 4; 33949e83 store gate)
        fleet_dark          = self._check_fleet_dark( self._last_full_snapshot, self._last_published_n, now )
        # 6929f4ac outward-twin backstop: resurface a dark session's aged user-gate
        # to Rick (case 18). Reads the FULL snapshot (offline rows included) so a
        # gone-dark session's buried gate is still seen. The production factories wire
        # hold_reader_fn (read_hold) so this is LIVE on :8001; unit-fake construction
        # leaves it None → inert.
        gates_resurfaced    = self._check_user_gate_resurface( self._last_full_snapshot, now )
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
        outreach_acks = self._check_outreach_receipts( now, offline_personas=self._confirmed_offline_personas() )
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
                worktrees_swept = len( jr.get( "swept", [] ) ) if isinstance( jr, dict ) else 0
            except Exception:
                worktrees_swept = 0

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
              clock, §10.1) AND hold-file mtime (task 70be69f2 hold-as-liveness)
              via the injected readers and builds the snapshot with STATE and
              LIVENESS kept as orthogonal columns (C4)
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
        for key in ( "http_status", "detail", "connection_count",
                     "window_count", "last_sent_local" ):   # Item C: throttle observability
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

    def _stamp( self, message ):
        """
        Prefix a human-facing outreach message with Rick's timestamp (Item B,
        2026-06-24): "[YYYY.MM.DD at HH:MM:SS] <message>", rendered in the configured
        outreach tz from the SAME injectable poll clock (self._clock).

        Applied at message CONSTRUCTION — `_route` (the routed choke point, covering
        message + cc_message) and the four DIRECT-send literals that bypass `_route`
        (decision_cc, stuck_poke, manager_stale_poke, poll_error_escalation). Because
        the stamp lands at construction, a resend (_check_outreach_receipts reuses the
        stored body) and a re-announce (the pending ledger reuses the stored message)
        carry the ORIGINAL stamp and are never double-stamped.

        Requires:
            - message is a string

        Ensures:
            - returns "[<stamp>] <message>" with <stamp> = now() (self._clock, the
              injectable seam → deterministic under a fake clock) rendered via
              format_outreach_ts in self._outreach_tz
            - never raises (clock + tz are construction-validated)
        """
        now = datetime.datetime.fromisoformat( self._clock.now_iso() )
        return f"[{format_outreach_ts( now, self._outreach_tz )}] {message}"

    def _outreach_throttle_allows( self, recipient ):
        """
        Item C: per-recipient trailing-window throttle decision for a ROUTINE
        persona-bound outreach DM (N messages / Y minutes). Consumer-side state
        (`self._outreach_sent_ts`) + the PURE ping_throttle predicates.

        DISABLED (max <= 0 or window <= 0) ⇒ always allowed, NO state kept
        (fail-safe: never suppress, zero overhead). When ENABLED, the recipient's
        send-history is pruned to the trailing window; on an ALLOWED decision `now`
        is appended (so the NEXT call counts this send); a SUPPRESSED decision does
        NOT append (it was not sent).

        Ensures:
            - returns ( allowed:bool, count_in_window:int, last_sent:datetime|None )
              where count_in_window is the post-decision window count and last_sent
              is the most-recent PRIOR send (None if none) — both for the journal
            - never raises (the clock is construction-validated)
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
                  session_id=None, expects_ack=False, attempt=1, throttleable=False ):
        """
        Emit one persona-bound DM: the durable dm-<persona> board write PLUS the
        best-effort wake push hop. Journals one result per channel.

        Item C (2026-06-24): when `throttleable=True` — set ONLY for the routine taps in
        THROTTLEABLE_CASES (case 4 blocker ping, case 7 manager tap) — the per-recipient
        trailing-window throttle (N msgs / Y min) gates the send: once N have been sent
        to this recipient in the trailing window the DM is SUPPRESSED — no board write,
        no push, no ack registration — and journaled as outcome `throttle_suppressed`
        (carrying the window count + the last-sent EDT stamp). EVERYTHING ELSE passes the
        default `throttleable=False` → TRACKED-but-never-suppressed: Rick-bound
        escalations (deadlock/manager-down/decision) AND the direct-send pokes
        (stuck_poke / manager_stale_poke — which carry their OWN per-episode caps, so the
        trailing-window cap would double-throttle + skew those counters) AND resends.

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
                blocker=None, cc_message=None, exclude_persona=None ):
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

        Requires:
            - exclude_persona is None OR a persona name (bug b9911943): a manager
              advisory that NAMES a specific subject (the stale/blocked/done manager
              itself — cases 14/16/17) must NOT fan out to that subject, only to its
              PEER managers + Rick. When truthy, the subject is dropped from the
              TIER_RICK_AND_MANAGERS active-managers fan-out, matched by canonical
              persona key (so "Mr. Radio" == "mr radio" == "mr_radio"). A falsy
              exclude_persona (None / empty) excludes nothing — byte-identical to
              every pre-existing caller. ONLY the TIER_RICK_AND_MANAGERS fan-out is
              filtered; Rick (rick_bound), owning_manager, blocker and cc targets
              are NEVER touched by this filter.

        Ensures (2026.06.11 receipts design — the R4 kill):
            - emits exactly the recipients its tier prescribes (minus exclude_persona
              from the TIER_RICK_AND_MANAGERS fan-out when supplied); absent optional
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
        Ping-storm Fix 3: the personas whose session is POSITIVELY offline this
        poll, read from the published full snapshot's liveness verdicts. A
        confirmed-offline target won't ACK, so its one-shot outreach resend
        (_check_outreach_receipts) is suppressed — no wasted -r2 to a dead pane.

        STRICT positive reading + persona-collapse-safe (bias toward delivery):
          - a persona qualifies ONLY if it appears in the snapshot AND EVERY row
            for it has liveness verdict "offline" — a persona with ANY non-offline
            row (a live twin session that could still read the dm-board) is EXCLUDED
          - an absent / unknown persona is never included
          - inert before the first publish (snapshot None / non-dict → empty set)

        Ensures:
            - returns the SET of personas all of whose published rows are "offline"
            - empty when no snapshot has been published yet; never raises
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

    def _check_outreach_receipts( self, now, offline_personas=None ):
        """
        §3.4 manager-side receipt polling — the acked-ledger principle (the
        receipt is an explicit, OWNER-WRITTEN mark, never an inference): an
        awaited outreach is acked iff the recipient posted a threaded reply
        (metadata.in_reply_to naming the outreach's question_id) on the SAME
        dm-<persona> board the durable write landed on. Filesystem read via the
        gateway — detection-path-safe (R4-clean).

        Requires:
            - now is an aware datetime
            - offline_personas is a set/collection of CONFIRMED-offline personas
              (ping-storm Fix 3) or None — the resend is SUPPRESSED for a target in
              this set (no wasted -r2 to a dead pane); None ⇒ empty ⇒ no suppression,
              byte-identical to the prior behavior

        Ensures:
            - an in_reply_to match (exact outreach_id or its "-rN" resend
              derivative) → receipt "acked" (+ latency_s) and the tracker clears
              (an ACK always wins — checked BEFORE the resend/suppress gate)
            - no ack past outreach_ack_window_seconds → exactly ONE re-send
              (attempt=2, fresh window), then — still nothing — terminal receipt
              "unacked" + the fact queued to ride the NEXT Rick-bound advisory
              (§3.4: never an escalation recursion; at most 2 sends total)
            - Fix 3: when the target persona is CONFIRMED offline, the one-shot
              resend is SKIPPED and the loop closes terminal-unacked (resends=0) —
              the un-ACK'd fact still queues for Rick (milestone-must-land), but no
              -r2 ping is wasted on a dead pane. Bias toward delivery: only a
              positively-offline target is suppressed (absent/unknown/alive → resend)
            - a gateway read hiccup degrades to "no ack seen this poll" (the
              window keeps governing); never raises
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

    def _escalate_deadlocks( self, cycles, store_edges, now, active_managers=None ):
        """
        Escalate deadlock cycles — NEVER auto-break (§4). Part-6 #5: Rick + ALL
        active managers (a human/manager breaks the cycle).

        STORE-CORROBORATED + DWELL + DE-DUP (bug 436a366b): the derived
        `holding_on: peer:X` cycles are SELF-REPORTED — a fresh, legitimately
        PROGRESSING sequencing wait (Krishna awaiting Mr Radio's merge+build)
        self-reported a ring and false-escalated to Rick every poll all session.
        Three gates now stand between a derived cycle and an escalation:
          1. STORE-CORROBORATION (Mr Radio's single-source-of-truth mandate): a
             cycle fires ONLY when EVERY ring edge is backed by an authoritative
             store `blocked_by` owner-edge (cycle_is_store_backed over
             build_store_wait_edges). A pure-coordination ring with ZERO store
             rows is OUT OF SCOPE v1 (rare, human-broken, and the right fix is
             managers expressing real waits as store blocked_by — a hygiene
             forcing-function). When the owed read is unwired/hiccupped,
             store_edges is empty → NOTHING fires: deadlock detection
             fail-SUPPRESSES (the opposite bias from the stall/manager-down
             detectors, BY DESIGN — over-escalation is THIS bug).
          2. DWELL / PROGRESSING-WAIT BELT: a store-backed ring must PERSIST for
             deadlock_dwell_seconds before it escalates. A fresh ring is recorded
             (first-seen) and given the grace window to self-resolve — a
             progressing wait clears within it and never fires. dwell=0 ⇒ fire on
             first corroborated sight.
          3. DE-DUP: each persisting store-backed ring escalates ONCE (not every
             poll). Both trackers PRUNE a signature the moment its ring is no
             longer present (resolved) so a genuine recurrence re-arms.

        Requires:
            - cycles is a list of canonical peer cycles (build_graph output)
            - store_edges is build_store_wait_edges output { holder: set(awaited) }
            - now is an aware datetime (poll clock)
            - active_managers is the resolved on-duty manager set (or None)

        Ensures:
            - fires ONE escalation per poll listing the rings NEWLY crossing the
              dwell this poll — to Rick (notify_fn) + each active manager
              (send_to); no-op when no store-backed ring has persisted past dwell
            - never raises
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

        LIVE-PEER EXCLUSION (bug bbce7e2f, 2026-06-30): a non-stuck holder whose
        awaited peer is ITSELF alive is a LEGITIMATE in-flight dependency (e.g. a
        worker awaiting a peer that is actively building), NOT a stall — it is
        EXCLUDED from the attention roster. Without this, the manager-tap emitted
        a spurious "N blocked / cajole the blockers" advisory for a healthy
        sequencing wait (mr radio→peer:rio, Cheech→peer:rio while Rio builds);
        that advisory is `expects_ack=True`, so when the busy manager doesn't ACK
        it the receipt poller re-sends it ONCE as a stale-timestamped `-r2` — the
        observed duplicate. The exclusion is NARROW so no real stall is hidden:
        a holder still in a deadlock CYCLE is KEPT (mutual stall — the `:1018`
        store-backed escalation still owns it byte-identically), and a holder
        awaiting a NON-alive / absent peer is KEPT (a genuine block on a
        dead/unknown blocker). Fail-safe: an awaited peer absent from the fleet
        is treated as NOT alive → the holder is kept (never hide a live block).

        Ensures:
            - returns a list of ALIVE view dicts: every stuck session, plus every
              blocked-edge holder whose awaited peer is NOT alive OR that sits in
              a deadlock cycle; reaped/offline views and holders waiting only on a
              live peer are excluded; never raises
        """
        holders        = set( graph[ "edges" ].keys() )
        alive_personas = { v.get( "persona" ) for v in fleet_view.values()
                           if isinstance( v, dict ) and v.get( "alive" ) is True and v.get( "persona" ) }
        cycle_personas = { p for cycle in graph[ "cycles" ] for p in cycle }
        out            = [ ]
        for view in fleet_view.values():
            if not isinstance( view, dict ):
                continue
            if view.get( "alive" ) is not True:
                continue                                  # reaped/offline-prune (lane 4)
            if view.get( "stuck" ):
                out.append( view )                        # a stuck session always needs attention
                continue
            persona = view.get( "persona" )
            if persona not in holders:
                continue                                  # neither stuck nor a blocked-edge holder
            # blocked-edge holder: KEEP only on a real stall — the holder is in a
            # deadlock cycle, OR its awaited peer is not alive. A wait on a LIVE
            # peer is a legit in-flight dependency → EXCLUDE (bug bbce7e2f).
            if persona in cycle_personas or graph[ "edges" ].get( persona ) not in alive_personas:
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

    def _should_tap( self, manager, sig, now, at_map=None, sig_map=None ):
        """
        Tap iff the crew-summary CHANGED since the last tap AND (first-ever tap OR
        ≥ tap_min_interval_seconds elapsed). NEVER tap on no-change (anti-storm).

        `at_map`/`sig_map` select the throttle-state store: None → the crew-tap dicts
        (_last_tap_at / _last_tap_sig); the stuck-manager-subject path passes its
        DEDICATED dicts so its "stuck-mgr:<persona>" throttle key never pollutes the
        clean-persona _last_tap_at (de3c5b87/33949e83 root fix).
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
            "blockers — and if there's unassigned work or idle capacity, spawn/assign "
            "THIS tick. Task a worker; NEVER absorb the work yourself — reap+replace a "
            "dark worker, don't take their lane. (Recommendation only — I do not assign.)"
        )
        return "\n".join( lines )

    def _subject_is_manager( self, view ):
        """
        ff91cff4: is the escalation SUBJECT itself a declared manager?

        A stuck/dead MANAGER's escalation is Rick's to actuate (reap/replace/
        re-staff), never a peer manager's — a manager can't own itself, so the
        case-7 "owning manager" resolver and the case-13 Rick+managers fan-out
        both mis-route it to the OTHER declared manager. This predicate gates the
        Rick-only redirect at both sites. It mirrors build_snapshot's `is_declared`
        role assignment (canonical persona key vs the declared-manager roster) —
        used here because the raw fleet_view rows carry no `role` yet (that is
        added later in build_snapshot, AFTER _tap_managers / _auto_poke run).

        Requires:
            - view is a dict (foreign data) or anything (defensive)

        Ensures:
            - returns True iff view is a dict with a persona whose canonical key is
              in the declared-manager set; False for non-dict / missing persona /
              empty declared roster; never raises
        """
        if not isinstance( view, dict ):
            return False
        persona = view.get( "persona" )
        if not persona:
            return False
        return canonical_persona_key( str( persona ) ) in self._declared_manager_keys

    def _format_stuck_manager_advisory( self, view, free_n ):
        """
        ff91cff4: the RICK-ONLY advisory body for a stuck/dead MANAGER subject —
        the case-7 tap's manager-subject twin. Names the manager and frames the
        actuation as Rick's (reap/replace/re-staff), NOT a peer manager's.
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
        Freshest liveness DATETIME for `manager` via the AUTHORITATIVE 5-signal
        union (fleet_render.compute_liveness) across that manager's session
        view row(s), or None.

        SINGLE SOURCE OF TRUTH (bug e8f40042): the tap-ACK now consumes EXACTLY
        the same liveness inputs as the general fleet-render verdict path —
        bridge_age + event_age + commons_age + idle_prompt_age + dm_age (dm gated
        by `count_dm`, the `arbiter count dm as liveness` toggle). The OLD tap-ACK
        looked at only {commons, bridge}, so it was STRICTLY NARROWER than the
        verdict: a manager whose only sign of life was a sent DM (coordination-
        only, no Read/Edit/Bash to bump the bridge) or a fresh stop-event read
        `down` and false-escalated MANAGER-DOWN to Rick every
        manager_ack_window_seconds while it was demonstrably LIVE. Reusing
        compute_liveness means the ACK can never drift narrower than the verdict
        again.

        Persona→view matching goes through canonical_persona_key (THE F-B
        persona-equivalence normalizer the allocation/DM path uses) so a fresh
        row whose persona spelling differs from the tap key is NOT missed — this
        also closes the secondary _manager_bridge_activity association miss
        (exact `==` left bridge_activity None even on a fresh bridge file).

        compute_liveness's thresholds only colour the verdict LABEL; the ACK
        decision uses `freshest_age_s` alone, so the render-layer defaults are
        fine. The freshest age (int seconds) is converted back to an absolute
        datetime (`now - age`) so the caller's `last_activity >= tapped_at`
        comparison stays unchanged.

        Requires:
            - manager is a persona name (str)
            - fleet_view is the build_fleet_view dict { session_id: VIEW } or None
            - now is an aware datetime; count_dm is a bool

        Ensures:
            - returns the freshest liveness datetime among the manager's session
              rows, or None when fleet_view is None/empty, no view's
              canonical persona matches, or NO signal is present on any match
            - NEVER raises (the observer invariant — a per-row hiccup is swallowed
              by compute_liveness, which is itself never-raises)
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

        TRUE iff gate_class == "operator" OR (status == "blocked" AND blocked_by
        carries ≥1 typed ref {kind: "user"}). These are the two store encodings of
        "correctly waiting on the human" (build-plan §3.0).

        Ensures:
            - returns a bool; a non-dict / malformed item → False; never raises
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

    def _read_owed( self, personas ):
        """
        ONE swallow-safe non-terminal owed read for `personas` →
        { persona: [ item-dicts ] } or None.

        The SINGLE per-poll store read shared by BOTH consumers of owed work:
        _classify_owed (→ CLASS_* labels) AND build_store_wait_edges (→ the
        authoritative deadlock-corroboration owner-ring). Extracted so the poll
        keeps its one-read-per-poll discipline (the observer invariant) instead of
        querying the store twice.

        Ensures:
            - returns the injected owed_work_fn's result, or None when the seam is
              unwired (owed_work_fn is None), there are no personas, or the read
              RAISED (swallowed → None = fail-SAFE for the classifier / suppress
              for the deadlock gate); never raises
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
        262c59f6 (A): ONE swallow-safe read of the store's KNOWN owner personas →
        a set of CANONICAL persona keys, or None when the seam is unwired / the read
        raised. Feeds `_classify_owed`'s known-persona fail-safe (a would-be-DONE
        persona whose canonical key is not a known owner is a likely label-contamination
        false DONE → UNKNOWN).

        Ensures:
            - returns None when the seam is unwired (known_owners_fn is None) or the
              read RAISED (swallowed → None = fail-SAFE: the downgrade goes inert,
              never mass-UNKNOWNs the fleet)
            - otherwise returns the set of canonical owner keys (falsy owners
              filtered); an empty store → empty set (also inert downstream); never raises
        """
        if self._known_owners_fn is None:
            return None
        try:
            owners = self._known_owners_fn()
        except Exception:
            return None        # store hiccup → None → fail SAFE (observer invariant)
        return { canonical_persona_key( o ) for o in ( owners or ( ) ) if o }

    def _store_read_degraded( self, owed_items, personas ):
        """
        33949e83 store-health gate: True iff the per-poll owed store read was EXPECTED
        to return data (the seam is WIRED and ≥1 persona was under evaluation) but
        returned None — i.e. it RAISED / timed out, a self-observed arbiter-side infra
        outage (the 2026-07-01 :7999 bog that swallowed tap-acks and false-DOWNed BOTH
        live managers in 1s). When True, the liveness-derived "no tap-ACK" reading is
        untrustworthy, so the MANAGER-DOWN / MANAGER-STALE escalations SUPPRESS (treat
        as UNKNOWN-INFRA, not dark) and re-arm only after a clean read window.

        Distinguishes an OUTAGE from the two innocent None cases: the seam UNWIRED
        (owed_work_fn None — inert config, not a failure) and an EMPTY roster (no
        persona to read). Neither is degradation → never manufactures a fleet-wide
        escalation freeze from a benign None.

        Ensures:
            - returns False when the owed seam is unwired OR no persona was under
              evaluation; True iff a wired read over ≥1 persona yielded None; never raises
        """
        if self._owed_work_fn is None:
            return False
        if not any( p for p in ( personas or [ ] ) ):
            return False
        return owed_items is None

    def _classify_owed( self, personas, fleet_view, owed=_UNREAD, known_owners=None ):
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

        `owed` (bug 436a366b): the caller MAY thread in a pre-read owed dict so the
        per-poll read is SHARED with build_store_wait_edges (deadlock
        corroboration) — one store read feeds both. Default `_UNREAD` ⇒ do our own
        read via _read_owed (the single-persona session_is_not_owed path). A passed
        value (including None) is used verbatim — None ⇒ all UNKNOWN, as if the read
        had failed.

        Ensures:
            - returns { persona: CLASS_* } for each non-empty persona in `personas`
            - owed_work_fn is called AT MOST once, and NOT AT ALL when `owed` is
              threaded in (the read already happened upstream)
            - never raises
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
            - 262c59f6 (A): threads the known-persona fail-safe so a re-spin /
              label-contamination would-be-DONE persona (∉ known owners → UNKNOWN) is
              NOT falsely suppressed here either — consistent with the case-17 path
              (inert when known_owners_fn is unwired → today's behavior)
        """
        cls = self._classify_owed(
            [ persona ], fleet_view or { }, known_owners=self._read_known_owners()
        ).get( persona, CLASS_UNKNOWN )
        return owed_class_suppresses( cls )

    def _stale_hold_holders( self, fleet_view, now ):
        """
        Personas whose `holding_on: peer:X` edge must contribute ZERO inferred edges
        this poll, killing the phantom "X is blocking worker Y" advisory + cc.

        THREE subtraction axes (OR'd); the first two read the authoritative HOLD
        artifact, the third reads the per-session liveness ts already on the view:
          - DEAD hold (bug bc1bc373) — `hold_is_stale`: an expired / not-work-owed /
            past-next-chase hold whose lingering `awaiting` drove a phantom edge
            (Tiffany's empty store board produced no real blocked_by, yet a dead
            hold drove the edge).
          - FRESH hold that CONTRADICTS the edge (bug 7f9a8ee2) —
            `hold_contradicts_peer_edge`: a holder whose CURRENT hold is fresh +
            honored with `awaiting="none"` (or a DIFFERENT peer) while its
            `holding_on` edge was minted from a STALE `last_activity.awaiting=peer:X`
            (the activity record out-lived the wait). `hold_is_stale` does NOT fire
            (the hold is fresh), so this complementary axis reconciles the hold's
            AUTHORITATIVE declared `awaiting` against the stale activity-derived edge.
          - STALE SESSION (ping-storm durable Fix 2, 2026-06-24) — `session_is_stale`:
            a holder WITH a readable hold whose hold is FRESH and CORROBORATING (both
            axes above say keep) but whose SESSION is beyond the alive threshold
            (last_activity_ts age > alive_threshold_seconds) contributes ZERO edges.
            ADDITIVE defense-in-depth behind build_graph's own per-session gate
            (8a450183) — kept INSIDE the `hold is not None` guard so the method's
            contract is preserved (a session with NO readable hold is never added
            here; build_graph drops a no-hold dead session). Fail-SAFE identical to
            the bridge-edge gate: a missing / unparseable last_activity_ts → NOT
            stale → no extra subtraction (never hide a live block).

        IO seam: reads the hold artifact via the wired `_hold_reader_fn`
        (heartbeat_hold.read_hold on :8001). The pure verdicts are
        dependency_graph.hold_is_stale / hold_contradicts_peer_edge. Only PEER-edge
        holders are read (an edge is only inferred from a `peer:` holding_on, so
        reading other holds is wasted IO). The returned set feeds ONLY the FILTERED
        advisory graph (build_graph @ _poll_once); the deadlock ESCALATION reads the
        UNFILTERED build_wait_edges feed and is deliberately NOT touched here
        (María's CHANGES-REQUESTED design — a real store-backed ring must still
        escalate; the phantom is rejected there by cycle_is_store_backed).

        Requires:
            - fleet_view is the per-poll view dict; now is an aware datetime

        Ensures:
            - returns the SET of holder personas whose readable hold is DEAD OR is
              FRESH-but-contradicts its derived peer edge OR whose SESSION is stale
              (last_activity_ts beyond alive_threshold_seconds — Fix 2)
            - INERT when the reader seam is unwired (None → empty set → today's
              behavior, every existing test + the deployed deadlock path unchanged)
            - a session with NO readable hold is NOT added (absence ≠ deadness — the
              filter only SUBTRACTS an edge for a readable hold; never over-filters)
            - swallow-safe: a raising reader degrades that session to "not stale"
              (its edge survives — fail toward the prior behavior); never raises
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
        de3c5b87 + 33949e83 (re-scoped observability): at every MANAGER-DONE (case-17)
        and MANAGER-DOWN (case-9) EMISSION, log the exact ground-truth inputs so the
        true root of a false-fire is captured DETERMINISTICALLY on the next occurrence
        (ground-truth-before-fix — Cheech's live /state capture DISPROVED the
        session-suffix-contamination premise, so we instrument rather than guess). ONE
        instrument serves BOTH open bugs:
          - de3c5b87 (false MANAGER-DONE): fed_label + canonical(fed_label) +
            label_is_canonical + owed_class + owed_read_ok + store_row_count +
            hold_work_owed → distinguishes a label→canonical mismatch (the disproven
            premise) from a genuine empty read from a 25ba173e hold-override
            (work_owed=false) from a degraded/raised store read.
          - 33949e83 (false MANAGER-DOWN during the :7999 bog): owed_read_ok
            (store-read health) + last_activity vs tapped_at → confirms whether the
            reads were degraded when both managers false-DOWNed.

        PURE telemetry via the swallow-safe `_log` seam — it reads only (never mutates)
        and has NO control-flow effect (a diagnostic blow-up is swallowed by `_log`).

        Requires:
            - manager is the fed persona label; cls is its owed_class; owed_items is
              the per-poll { persona: [items] } dict or None (None ⇒ the store read
              was unwired / raised); tapped_at is an aware datetime; last_activity is
              an aware datetime or None
        Ensures:
            - emits exactly one `arbiter_manager_ack_diagnostic` line; never raises
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
        B4/D4 manager-down detector via the liveness-proxy ACK.

        A manager tapped at T is treated as having "acked" (present-to-act) while
        their liveness is fresh AT/AFTER T. Liveness is the AUTHORITATIVE 5-signal
        union — the SAME inputs as the general fleet-render verdict
        (fleet_render.compute_liveness): bridge-mtime + stop-event + commons +
        idle_prompt + sent-DM (dm gated by `count_dm`). If a TAPPED manager shows
        NO fresh signal since the tap AND ≥ manager_ack_window_seconds have
        elapsed → MANAGER-DOWN → escalate to Rick (notify_fn) + HOLD.

        Why a liveness proxy (bug 9694fb11): there is NO deliverable tap-ACK path
        — a manager literally cannot DM the arbiter back. So the only honest ACK
        is a liveness proxy.

        Why the FULL union (bug e8f40042): the ACK formerly looked at only
        {commons, bridge}, making it STRICTLY NARROWER than the verdict path that
        consumes all five. A manager whose only sign of life was a sent DM
        (coordination-only — no Read/Edit/Bash to bump the bridge, nothing to
        commons) or a fresh stop-event read `down` and false-escalated
        MANAGER-DOWN to Rick every window while demonstrably LIVE. Routing the ACK
        through compute_liveness (via _manager_liveness_activity) makes the ACK a
        strict SUPERSET of the verdict's life signals — it can never drift
        narrower again. The who()-sourced commons activity is retained as a belt
        (the view's commons_ts is phantom-nulled when the bridge is absent).

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
                    self._log_manager_ack_diagnostic( "manager_done", manager, cls,   # de3c5b87 ground-truth capture
                                                      owed_items, fleet_view, now, tapped_at, last_activity )
                    self._route(
                        CASE_MANAGER_DONE_ADVISORY,
                        f"MANAGER-DONE (advisory, NOT manager-down): {manager} owes NO "
                        f"non-terminal work — it appears finished/idle. Consider reaping "
                        f"it (the arbiter never reaps — redline). One-time notice.",
                        active_managers=active_managers
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
            cc_body = self._stamp(                                  # Item B: direct-send site (bypasses _route)
                f"Heartbeat arbiter (cc): your crew posted a decision-needed — "
                f"{entry.get( 'body', '' )}. Rick has it; weigh in if it's yours." )
            outreach_id = self._mint_outreach_id()
            self._log_outreach( "decision_cc", "send_to", [ manager ], cc_body,
                                persona=manager, outreach_id=outreach_id )
            # decision_cc is part of a DECISION escalation → NOT throttled (carve-out)
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

        L1 STORE-AWARENESS (2026-06-17, build-plan §3.1): a session whose persona's
        owed work is "not owed" — entirely Rick-gated (BLOCKED_ON_USER) OR zero
        (DONE) — is EXCLUDED from the live-owed set. A fleet whose ONLY live owed
        work is parked on Rick is NOT a stall (the manager-in-`holding`-on-Rick
        false-fire); a fleet that is DONE-but-alive-and-frozen owes NOTHING, so it
        is NOT a stall either (bug d2a4c040 false-positive). The exclusion routes
        through the shared `owed_class_suppresses` predicate (NOT_OWED_CLASSES) —
        the SAME suppression set #9 (acks) and #F2 (staleness) honor and the
        sibling `session_is_not_owed` seam composes — so the hand-roll, the
        predicate, and its docstring no longer drift. owed_class is the per-poll
        store classification; when it is None/empty (seam unwired) or a persona
        classifies UNKNOWN (store hiccup), the predicate does NOT suppress → NO
        session is excluded → TODAY'S behavior (fail SAFE — never silence a real
        stall).

        Ensures:
            - returns True iff some view is alive AND state ∈ {working, stuck,
              holding} AND its persona's owed-class does NOT suppress (i.e. is
              neither BLOCKED_ON_USER nor DONE); never raises
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
        Facet-2 of bug 423f04a5: does ANY alive session show recent BUILD / DM /
        HOLD-REFRESH activity within the stall window? — the liveness the frozen
        progress signature deliberately cannot see.

        The whole-fleet-stall signature keys ONLY on the semantic state + the last
        task-transition ts (Fix 2), so an actively-BUILDING fleet holding its
        commits (Read/Edit/Bash bumping the bridge-mtime, DMs coordinating, holds
        re-stamped every Stop — but ZERO task-store writes in the window) reads as
        "no progress" and false-escalates WHOLE-FLEET-STALL to Rick (the 2026-07-01
        13:46 false-fire: Mr Radio's mux-parity crew was demonstrably building/DMing).
        This gate credits exactly the three NON-chatter liveness signals the bug
        names — bridge (build), dm (coordination), hold (defended-quiescence
        refresh) — as fleet progress BEFORE declaring a stall.

        DELIBERATELY NARROWER than compute_liveness's freshest-of union: it reads
        ONLY bridge_age_s / dm_age_s / hold_age_s and EXCLUDES commons_age_s +
        idle_prompt_age_s + event_age_s. Commons chatter is liveness, not progress
        (the arbiter's own per-poll posts surface in who()), so crediting it would
        RE-OPEN the chatty-but-stuck blind spot — a LIVE fleet posting "still
        blocked" while nothing builds MUST still stall. dm_age_s is read from the
        always-present auditable column, so it is credited regardless of the
        `arbiter count dm as liveness` toggle (a sent DM is coordination work here).

        Requires:
            - fleet_view is the build_fleet_view dict { session_id: VIEW } or None
            - now is an aware datetime

        Ensures:
            - returns True iff some ALIVE view with a session_id has a bridge/dm/hold
              age that is present AND ≤ fleet_stall_window_seconds (recent build /
              DM / hold-refresh)
            - a dead/offline session's stale-or-fresh mtime never credits (the alive
              gate blocks it); a session without a session_id is skipped
            - reads bridge/hold mtime via the injected never-raise seams and folds
              them through compute_liveness (itself never-raises); never raises
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
            - a fleet whose only live owed work is "not owed" — BLOCKED_ON_USER
              (Rick-gated) or DONE (zero owed) — never escalates (L1 §3.1 +
              d2a4c040; owed_class None/empty/UNKNOWN → today's behavior, fail SAFE)
            - a session on a DEFENDED awaiting-user hold is excluded from the owed
              set — it is correctly PARKED on Rick, not stalled (423f04a5 facet-1)
            - an actively-BUILDING fleet (recent bridge/DM/hold-refresh liveness) is
              PROGRESSING → never escalates, even with a frozen signature (423f04a5
              facet-2); commons/idle_prompt chatter still does NOT credit progress
            - returns 1 on a new escalation else 0; never raises
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

    def _append_goal_line( self, body, role ):
        """
        Append the role-selected north-star goal echo (role-goals Phase 2-3) to a
        poke body. role=="manager" → the Manager line; any other non-empty role →
        the Worker line. The goal strings are injected at construction (the :8001
        factory reads the `heartbeat <role> goal line` INI keys); when the selected
        line is None/"" the body is byte-identical to the pre-role-goals output.
        Canonical text: planning-is-prompting -> workflow/role-goals.md.
        """
        is_manager = ( role or "" ).strip().lower() == "manager"
        line       = self.manager_goal_line if is_manager else self.worker_goal_line
        if line:
            return body + "\n\n" + line
        return body

    def _format_poke( self, view ):
        """The non-destructive wake-nudge body sent to a stuck LIVE session.

        ROLE-SELECTED (MANAGE-not-BUILD revision 2026-06-29): the closing clause
        forks on view["role"]. A stuck WORKER is still told to "resume" the work
        itself; a stuck MANAGER is told to tap/assign its crew (staff up if it has
        more tasks than workers) and NOT resume the work itself.
        """
        who        = view.get( "persona" ) or view.get( "session_id" )
        is_manager = ( view.get( "role" ) or "" ).strip().lower() == "manager"
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
        """The reap-RECOMMENDATION body — a recommendation to a HUMAN/manager; the
        arbiter NEVER executes the reap (redline)."""
        who = view.get( "persona" ) or view.get( "session_id" )
        return (
            f"REAP-RECOMMENDATION (advisory — I recommend, you decide; I do NOT reap): "
            f"session {who} stayed STUCK through {pokes} bounded auto-poke(s) with no "
            f"recovery. Recommend a human/manager reap-and-replace it. The arbiter "
            f"takes NO destructive action."
        )

    def _session_awaiting_user( self, session_id, now ):
        """
        c9575068: is this session in the MANAGER-AWAITING-RICK state the stuck-poke
        must NOT treat as wedged? True iff the session carries a FRESH HONORED hold
        that EITHER declares `awaiting: user:...` OR holds ≥1 OPEN pending_user_gate
        (all pending gates awaiting the user). Either signal means the session is
        correctly parked on Rick with a defended quiescence — advisory, not stuck.

        Mirrors the other three detectors' not-owed suppression (`_has_live_owed_work`
        / `_check_manager_acks` / `_check_manager_staleness`), but keys on the HOLD
        rather than owed_class: the 6929f4ac open-gate override reclassifies an
        awaiting-user session as CLASS_ACTIVE in owed_class (it owes Rick a RE-ASK,
        so it must keep re-asking, not go dark), so the store classification CANNOT
        see this state — the awaiting-user truth lives ONLY in the hold artifact.
        Suppressing the arbiter's harsh stuck-poke here does NOT stop the Stop-hook's
        own bounded re-ask channel (poke_cap=3, by design — reference memory
        reference_user_gate_poke_overrides_honored_hold); it only silences the
        inappropriate "you appear STUCK — wedged?" escalation on top of it.

        Requires:
            - session_id is a string; now is an aware datetime

        Ensures:
            - returns False when the hold-reader seam is unwired (None), the read
              raises, or the hold is absent / not-honored — INERT / fail-SAFE
              (today's poke behavior preserved; never silences a real stuck-poke)
            - returns True iff is_honored( hold, now ) AND ( awaiting starts "user:"
              OR open_gates( pending_user_gates ) is non-empty ); never raises
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

    def _session_awaiting_peer( self, session_id, now ):
        """
        262c59f6 (H2): is this session correctly MANAGER-AWAITING-PEER — a delegating
        manager parked on LIVE WORKERS — a state the stuck-poke must NOT treat as
        wedged? True iff the session carries a FRESH HONORED hold that BOTH declares
        `work_owed=true` AND names `awaiting: peer:...`. A manager that has correctly
        delegated its owed work shows NO self-transition BY DESIGN (the workers make
        the progress, not the manager), so the activity-tail stuck oracle misreads
        "no progress + work owed" as wedged — exactly wrong for a delegating manager.
        The honored work_owed=true peer-hold is the defended-quiescence artifact the
        store classification cannot express (a delegated ACTIVE persona looks the same
        as a self-owned wedged one in owed_class).

        Sibling of `_session_awaiting_user` (c9575068 covered awaiting-USER; this
        covers awaiting-PEER). TIGHTER than the user path: it additionally REQUIRES
        `work_owed` to be explicitly True — a manager awaiting a peer while owing
        nothing is not the MANAGE-not-BUILD posture, so it stays pokeable. Same inert
        / fail-SAFE seam discipline: an unwired reader, a raised read, an absent /
        not-honored hold, or a work_owed that is not explicitly True → False (never
        silences a real stuck-poke).

        Requires:
            - session_id is a string; now is an aware datetime

        Ensures:
            - returns False when the hold-reader seam is unwired (None), the read
              raises, the hold is absent / not-honored, or work_owed is not
              explicitly True — INERT / fail-SAFE (today's poke behavior preserved)
            - returns True iff is_honored( hold, now ) AND declared_work_owed( hold )
              is True AND awaiting is a str starting "peer:"; never raises
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

    def _auto_poke( self, fleet_view, now, active_managers, owed_class=None ):
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

        Suppression (262c59f6): a stuck session is DROPPED from the pokeable set —
        no harsh "you appear STUCK — wedged?" poke — when it is DEFENDED by any of
        awaiting-USER hold / awaiting-PEER work_owed hold / a store `owed_class` of
        DONE|BLOCKED_ON_USER (see the suppression block). `owed_class` unifies the
        stuck path onto the SAME store authority the three other detectors read, so
        the activity-tail and store oracles can no longer contradict within one poll.

        Requires:
            - owed_class is the per-poll { persona: CLASS_* } map (or None/empty →
              the store cross-check is inert → today's activity-tail-only behavior)

        Ensures:
            - no-op when auto_poke_enabled is False (the make-before-break flag)
            - pokes ≤ poke_max_per_episode times per session per episode, then
              escalates exactly once, then silent
            - an awaiting-user / awaiting-peer / store-not-owed session is never poked
            - returns the count of pokes fired this poll; never raises
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
        # Dropping a session from `pokeable` ends any in-flight poke episode via the
        # clear-on-resume loop below (the cap re-arms), exactly as a recovery would.
        pokeable = { sid: v for sid, v in pokeable.items()
                     if not self._session_awaiting_user( sid, now )
                     and not self._session_awaiting_peer( sid, now )
                     and not owed_class_suppresses( owed_class.get( v.get( "persona" ) ) ) }

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
                fired += 1
            elif sid not in self._poke_escalated:
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
        """The bounded, non-destructive staleness nudge sent to a dark MANAGER session."""
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

    def _check_manager_staleness( self, snapshot, now, active_managers, owed_class=None, store_read_degraded=False ):
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
            if persona and fa is not None and fa < self.manager_stale_poke_threshold_seconds:
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
                        exclude_persona=persona,                     # b9911943: not to the subject itself
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
                        exclude_persona=persona,                     # b9911943: not to the subject itself
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
                    exclude_persona=persona,                         # b9911943: not to the subject itself
                )
            if self._mgr_poke_count[ sid ] < self.poke_max_per_episode:
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

    def _check_user_gate_resurface( self, snapshot, now ):
        """
        6929f4ac OUTWARD-twin backstop (§9.2): a session that went DARK while still
        holding an OPEN, AGED direct user-gate (it stopped re-asking) → surface the
        buried question to RICK on the session's behalf (case 18, Rick-only), so a
        dead/silent session's owed gate still reaches him even when it can no longer
        re-ask. The primary mechanism is the Stop-hook self-poke (Parts 1-3); this
        is the external backstop for when self-regulation has gone dark.

        Inert in TWO layers: (a) no hold-reader wired (None seam) → return 0, no
        work, byte-identical to today; (b) wired but no session is both dark AND
        holding an aged open gate. Swallow-safe per the observer invariant: a
        hold-read hiccup degrades that session to "no gate seen", never kills the poll.

        Darkness = the row's liveness verdict is "offline" OR its freshest signal
        age is unknown / older than user_gate_resurface_seconds (it is not actively
        alive). Aged gate = an OPEN gate whose last_asked_ts is older than the same
        ceiling (the session has clearly stopped re-asking). Escalate-once per
        (session, gate); a gate that clears (answered/removed) or a session that
        freshens leaves the eligible set → its key re-arms for a future episode.

        Requires:
            - snapshot is the FULL (include_offline=True) detection snapshot
            - now is an aware datetime

        Ensures:
            - returns 0 when the hold-reader seam is unwired (inert)
            - resurfaces each newly-eligible aged gate exactly once (case 18 → Rick)
            - returns the count resurfaced this poll; never raises
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
            for gate in aged_open_gates( get_pending_user_gates( hold ), now_epoch, ceiling ):
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
        A2/A3 (fcb5dbc0): the arbiter as the SINGLE pusher of STORE operator gates,
        routed by D4 urgency — the thin consumer of the PURE router
        (operator_gate_routing.route_operator_gates).

        Each poll reads EVERY open operator gate FLEET-WIDE via the store seam (by
        gate_class, NOT per-session — so it sees a gate whether the owning session is
        alive or DARK; that is the case-18 dark-only resurface EXTENDED to ALL open
        operator gates), then routes by urgency:
          - URGENT → interrupt Rick immediately, escalate-once per gate (the de-dup is
            re-armed to the present urgent set, so a cleared-then-reopened or re-tiered
            gate re-fires)
          - NORMAL → batched into ONE digest emitted at most every
            operator_digest_cadence_seconds; the digest clock is stamped on emission
            (route_operator_gates returns an empty digest until the cadence elapses)
          - LOW    → pull-only; never auto-pushed

        Inert TWO ways: (a) seam unwired (operator_gates_fn None) → return 0,
        byte-identical to today; (b) wired but no open operator gate. Swallow-safe per
        the observer invariant: a store-read hiccup degrades to "no gates seen", never
        kills the poll.

        Requires:
            - now is an aware datetime (the poll clock)

        Ensures:
            - returns the count of arbiter emissions this poll (urgent interrupts +
              at most one digest); never raises
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
