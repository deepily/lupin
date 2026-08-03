#!/usr/bin/env python3
"""
Heartbeat Arbiter — fleet data-model transform (pure).

The arbiter (doc 03 §4) rebuilds a per-session "fleet view" each poll from the
heartbeat-events exhaust + a `commons_who` snapshot. THIS is the pure transform:
an accumulated per-session record tail (+ who rows + now) → a flat per-session
view dict the other arbiter leaves (dependency_graph, idle_roster) and the
consumer's behaviors consume.

Liveness is **event-file-ts PRIMARY, commons_who SECONDARY** (doc 03 N3): the
event-file ts is `:7999`-free (local read), so liveness degrades gracefully
when `:7999` saturates; commons_who only enriches it. `last_activity_ts` is the
most-recent of either signal — used for both alive (broad window) and quiet
(narrow window, idle_roster). The commons_who secondary signal is matched by
**session_id** (persona can be borrowed/duplicated — Rachel's catch) and is
PHANTOM-GUARDED by live-bridge presence (Fleet-Status §5.2(b), 2026-06-09): a
commons echo from a session absent from the live-bridge discovery is retention
residue of a reaped process, not liveness — it is nulled so the session reads
offline and the publish-prune evicts it (mirrors the manager-roster guard in
manager_resolver.resolve_active_managers).

Input contract (Rachel's wiring): `events_by_session` is the ACCUMULATED tail
per session (oldest→newest, ~50 records) — `[-1]` is the current state; the
list is scanned for REPEATED cap_reached (the §4 "stuck" signal).

Pure + never-raises.

Design authority: lupin →
    src/rnd/v0.1.8/2026.06.04-heartbeat-hook/03-arbiter-design.md §4 / N3.
"""
import datetime

# Outcome vocabulary referenced from the emitting side (one-name-everywhere:
# the hook's constants are the single source of truth for outcome VALUES, so
# value renames — e.g. poke→poked, 2026-06-09 — ride through for free).
from lupin_cli.claude_code.hooks.lib.heartbeat_decision import (
    OUTCOME_POKE, OUTCOME_HONORED, OUTCOME_CAP_REACHED,
)
from lupin_cli.claude_code.hooks.lib.heartbeat_events import (
    EVENT_IDLE, EVENT_KIND_REAPED, EVENT_KIND_TASK_TRANSITION,
)


# last-outcome → coarse session state (doc 03 §4)
_STATE_BY_OUTCOME = {
    OUTCOME_POKE        : "working",
    OUTCOME_HONORED     : "holding",
    OUTCOME_CAP_REACHED : "stuck",
    EVENT_IDLE          : "idle",
}

# "stuck = REPEATED cap_reached + work_owed" (§4): ≥ this many cap_reached+owed
# episodes in the accumulated tail. A single cap-reach isn't yet "stuck".
STUCK_REPEAT_THRESHOLD = 2

# bug 52b8ed6b: the RECOVERY CLASS — the outcomes that CONSUME prior cap_reached
# evidence. MEMBERSHIP RULE (Mr. Radio's ruling, 2026-07-12 — apply it to classify any
# future addition to the outcome vocabulary): a recovery outcome is a liveness beacon
# THE SESSION ITSELF EMITS, asserting it is not wedged.
#   • honored — a fresh declared hold: defended quiescence (the original 5a1f17f8 rule).
#   • idle    — the explicit "nothing owed" beacon (work_owed=false), written only on the
#               TRANSITION into idle. ADDED here: without it, a session that recovered by
#               going idle consumed NOTHING and stayed flagged `stuck` FOREVER (sam, live:
#               announced LIVE STUCK at 21:49 EDT while idle, owing nothing, bridge 0s
#               fresh — from caps he had recovered from 8 hours earlier).
# EXCLUDED, deliberately: `poked` (owed + under cap — the session is still IN the wedge);
# `not_owed` (dead vocabulary — never written; the writer emits `idle` instead, see
# heartbeat_events.py:441); `suppressed_stale_declared_owed` (an ARBITER-side suppression
# marker, not a session-emitted beacon — it fails the membership rule).
RECOVERY_OUTCOMES = frozenset( { OUTCOME_HONORED, EVENT_IDLE } )


def _parse_iso( value ):
    """Parse an ISO-8601 timestamp → aware datetime, or None. Never raises."""
    if not value or not isinstance( value, str ):
        return None
    text = value.strip()
    if text.endswith( "Z" ):
        text = text[ :-1 ] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat( text )
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace( tzinfo=datetime.timezone.utc )
    return parsed


def _age_seconds( ts, now ):
    """Seconds since ts (negative if ts is in the future), or None if unusable."""
    if ts is None:
        return None
    try:
        return ( now - ts ).total_seconds()
    except ( TypeError, AttributeError ):
        return None


def _is_recent( ts, now, window_seconds ):
    """True iff ts is non-None and within `window_seconds` of now (future ts ⇒ recent)."""
    age = _age_seconds( ts, now )
    return age is not None and age <= window_seconds


def _newer( a, b ):
    """The more-recent of two datetimes (either may be None)."""
    if a is None:
        return b
    if b is None:
        return a
    return a if a >= b else b


def _who_matches( row_sid, sid ):
    """
    Does a commons_who row's session_id refer to this session? Prefix-tolerant
    because commons_who returns BOTH full-uuid and short rows (and event files
    are keyed by the short id).
    """
    if not row_sid or not sid:
        return False
    return row_sid == sid or row_sid.startswith( sid ) or sid.startswith( row_sid )


def _commons_ts_for_session( who_rows, sid ):
    """Most-recent commons_who ts for this session_id (prefix-matched), or None."""
    best = None
    for row in who_rows or [ ]:
        if not isinstance( row, dict ) or not _who_matches( row.get( "session_id" ), sid ):
            continue
        ts = _parse_iso( row.get( "last_post_ts" ) )
        if ts is not None and ( best is None or ts > best ):
            best = ts
    return best


def _dm_ts_for_session( dm_activity, sid ):
    """
    Most-recent SENT-DM ts for this session_id (prefix-matched), or None.

    The DM-as-liveness mirror of `_commons_ts_for_session`: `dm_activity` is the
    arbiter's per-poll { session_id: max(created_at) } map of SENT ai_to_ai DM
    activity (the IMPURE store read lives in the orchestrator seam, NOT here).
    Prefix-tolerant on the session-id (short 8-char vs full-uuid forms) so a map
    keyed by one form matches a canonical view id of the other.

    Requires:
        - dm_activity is { session_id: datetime } (aware) or None; sid is a
          canonical session-id string

    Ensures:
        - returns the MAX datetime among prefix-matching map entries, or None
          (no match / empty / None map); never raises
    """
    best = None
    for row_sid, ts in ( dm_activity or { } ).items():
        if not _who_matches( row_sid, sid ) or ts is None:
            continue
        if best is None or ts > best:
            best = ts
    return best


def _count_stuck_episodes( events ):
    """Count LIVE cap_reached+owed records in the accumulated tail — those NOT
    consumed by a later recovery.

    5a1f17f8 (a): a cap_reached is CONSUMED when a RECOVERY outcome appears LATER in
    the ordered (oldest→newest) tail — the session moved to defended quiescence (or
    resumed), so that prior wedge no longer stands. Only cap_reached+owed AFTER the
    last recovery count as live stuck evidence.

    bug 52b8ed6b: the recovery class is `RECOVERY_OUTCOMES` = { honored, idle }, NOT
    `honored` alone. An `idle` recovery (the session's explicit "nothing owed" beacon)
    previously consumed NOTHING, so a recovered session stayed flagged `stuck` until the
    events tail rolled off — PERMANENT LIVE-STUCK (sam: still announced stuck at 21:49
    EDT while idle, owing nothing, bridge 0s fresh, from caps recovered 8h earlier).

    MONOTONE + SAFE: broadening the recovery class can only CONSUME MORE caps, so the
    derived `stuck` flag can only flip True→False, NEVER False→True. No consumer of the
    flag (attention roster · poke gate · /state snapshot · terminal render · UI table)
    can ever see a NEW stuck session — only fewer.

    TRUE POSITIVE PRESERVED BY CONSTRUCTION: a genuinely wedged session OWES work
    (`work_owed: True`) and therefore can NEVER emit `idle` (which is written only when
    work_owed is false) — its caps are never consumed, it stays stuck, and it is still
    poked and still announced. Recovery consumes the PAST; it grants no immunity — a
    session that recovers and then wedges again re-arms on its new caps.

    Why: the offset-reset replay (a :8001 restart re-reads the events file from byte 0,
    bug 5a1f17f8 root cause) re-surfaces HISTORICAL cap_reached as if fresh. In the real
    streams those are followed by `honored` recoveries (Mr Radio's 2026-07-02 fixture:
    one cap_reached at 21:27Z + FIVE honored after it, yet replayed as fresh STUCK on
    two restarts). Gating on a later honored makes the `stuck` signal robust to replay
    WITHOUT a now/threshold knob — deterministic, order-respecting. A genuinely wedged
    session emits repeated cap_reached with NO intervening honored → last_recovery stays
    behind them → they all count → the true-positive is preserved. This composes with
    the durable-offset fix (b): (a) is the belt for any replayed/lingering record, (b)
    stops the re-read at the source.
    """
    last_recovery = -1
    for i, e in enumerate( events ):
        if isinstance( e, dict ) and e.get( "outcome" ) in RECOVERY_OUTCOMES:   # 52b8ed6b: { honored, idle }
            last_recovery = i
    return sum(
        1 for i, e in enumerate( events )
        if i > last_recovery
        and isinstance( e, dict )
        and e.get( "outcome" ) == OUTCOME_CAP_REACHED
        and e.get( "work_owed" ) is True
    )


# heartbeat-event `kind` discriminator (Step 1.3): records carrying this kind are
# the passive idle_prompt recency beacon — they feed `idle_prompt_ts` ONLY and
# are FILTERED OUT of the ACTIVITY axis (last/state/stuck/stop-event), per N2.
KIND_IDLE_PROMPT = "idle_prompt"


def _canonicalize_ids( all_ids ):
    """
    Collapse heterogeneous session-id forms (short 8-char vs full uuid) to one
    canonical id each, reusing the prefix-match logic (review N3).

    The four union sources key sessions differently — event files use SHORT
    8-char ids, commons_who returns BOTH short + full, bridges/commons use full
    uuids. A naive set-union would double-count a session present as a short-id
    event AND a full-uuid bridge. We group ids that prefix-match (`_who_matches`)
    and elect the LONGEST id of each group as canonical (full uuid wins).

    Requires:
        - all_ids is an iterable of session-id strings (falsy entries ignored)

    Ensures:
        - returns { raw_id: canonical_id } where canonical_id is the longest id
          in raw_id's prefix-group (raw_id itself when it has no longer match)
        - never raises
    """
    ids   = [ i for i in all_ids if i ]
    canon = { }
    for i in ids:
        best = i
        for j in ids:
            if j != i and _who_matches( i, j ) and len( j ) > len( best ):
                best = j
        canon[ i ] = best
    return canon


def build_fleet_view( events_by_session, who_rows, now, alive_threshold_seconds, bridge_sessions=None, dm_activity=None ):
    """
    Build the per-session fleet view as the UNION of all liveness signals.

    The roster is the UNION of FIVE sources (arbiter liveness fix, Part 7 /
    Step 1.4 + DM-as-liveness toggle, 2026-06-17) — a session enters the view if
    it appears in ANY of:
        (a) bridge-discovered   — `bridge_sessions` (the arbiter passes this IN;
            it does the IO via find_active_voice_persona_sessions — the leaf
            stays pure),
        (b) commons-active      — `who_rows`,
        (c) idle_prompt-recent  — kind=idle_prompt records in events_by_session,
        (d) stop-event sessions — the prior event-sourced members,
        (e) dm-active           — `dm_activity` (per-session SENT ai_to_ai DM ts;
            the arbiter passes this IN — the store read is in the orchestrator
            seam, the leaf stays pure).
    The old code iterated (d) ONLY and could merely ANNOTATE — so live workers
    with no stop-event were invisible (the false WHOLE-FLEET-STALL bug). Now we
    ADD union members.

    The ACTIVITY axis (last_outcome/state/stuck/holding/stop-event ts) is built
    from NON-idle_prompt records only (kind filter, N2): an idle_prompt record
    must NEVER become `state` and must NEVER feed the stop-event age. It feeds
    `idle_prompt_ts` ONLY.

    Heterogeneous id forms (short 8-char event ids vs full-uuid bridge/commons
    ids) are canonicalized BEFORE dedup (`_canonicalize_ids`, N3) so a session
    present under both forms yields ONE view keyed by its canonical (longest) id.

    Requires:
        - events_by_session is a dict { session_id: list[event-record-dict] }
          (the ACCUMULATED tail per session, oldest→newest) or None
        - who_rows is a list of commons_who rows (dicts) or None
        - now is an aware datetime; alive_threshold_seconds is a positive number
        - bridge_sessions is { session_id: persona_name|None } (the arbiter's
          bridge discovery) or None — membership + naming source (a)
        - dm_activity is { session_id: datetime(aware) } (the arbiter's per-poll
          SENT ai_to_ai DM-activity map) or None — membership + liveness source
          (e). None / empty ⇒ the prior 4-source behavior (no dm_ts anywhere)

    Ensures:
        - Returns dict { canonical_session_id: VIEW } for every session with ≥1
          REAL signal (an event record, an idle_prompt record, a commons match,
          a bridge presence, or a SENT-DM ts); a bare empty event list with no
          other signal is NOT a member (preserves the old "skip empty/untrackable"
          behavior)
        - PHANTOM GUARD (Fleet-Status §5.2(b)): a session ABSENT from
          bridge_sessions has its commons_ts NULLED — the commons echo of a
          reaped/dead process (commons_who retention) must not count as
          liveness, so such a session's verdict rests on its event/idle_prompt
          ages alone and reads "offline" once those age out (a commons-ONLY
          bridge-absent member is offline immediately). Membership is judged on
          the RAW signal, so the phantom remains an auditable (offline) roster
          row. Bridge-present sessions keep commons as a secondary signal —
          unchanged. Mirrors manager_resolver.resolve_active_managers.
        - VIEW (flat dict): session_id · persona · last_outcome ·
          last_event_ts(datetime|None — STOP/non-idle_prompt) ·
          commons_ts(datetime|None; None when bridge-absent, see guard) ·
          idle_prompt_ts(datetime|None) ·
          dm_ts(datetime|None — SENT ai_to_ai DM ts; NOT phantom-guarded) ·
          last_task_transition_ts(datetime|None) ·
          last_activity_ts(datetime|None; max of the LIVENESS ts) · alive(bool) ·
          state · holding_on · stuck · poke_count · cap · reaped(bool)
        - reaped is True iff a kind="reaped" tombstone is present (the host-side
          reaper appended it); kept OFF the activity axis (never `state` / never
          feeds last_event_ts), it makes the session a member so its row can be
          force-offlined + pruned (fleet_render.build_snapshot)
        - last_task_transition_ts is the ts of the latest kind="task_transition"
          PROGRESS beacon (arbiter signs-of-life Fix 2) — a task-store WRITE.
          Kept OFF the activity axis (never `state`, never feeds last_event_ts /
          last_activity_ts / `alive`): it is a PROGRESS-only signal, consumed
          exclusively by _fleet_progress_signature, so liveness and progress stay
          orthogonal. A task_transition record DOES confer membership.
        - dm_ts is the per-session MAX SENT ai_to_ai DM ts (DM-as-liveness
          toggle). UNLIKE commons_ts it is NOT phantom-guarded by bridge presence
          — the coverage hole it closes IS the bridge-absent coordination-only
          manager (only activity is dm_send → bridge-mtime never bumps), so
          guarding it on bridge presence would defeat the feature. Kept OFF the
          activity axis (never `state`/last_event_ts/last_activity_ts/`alive`): a
          LIFE signal consumed ONLY by the verdict seam (compute_liveness, where
          the `arbiter count dm as liveness` toggle gates whether it drives the
          verdict). A SENT-DM ts DOES confer membership.
        - the LIVENESS ts fields (last_event_ts/commons_ts/idle_prompt_ts/dm_ts)
          stay SEPARATE so the verdict seam (fleet_render.compute_liveness) can
          derive its distinct ages; last_task_transition_ts is orthogonal
          (progress)
        - persona prefers the bridge-discovered name, then the last activity
          record, then the idle_prompt record, then the reaped tombstone, then
          the task_transition record
        - Never raises
    """
    events_by_session = events_by_session or { }
    bridge_sessions   = bridge_sessions or { }
    dm_activity       = dm_activity or { }

    # 1. Gather every candidate session id across the FIVE sources, then
    #    canonicalize the heterogeneous id forms before dedup (N3). dm_activity
    #    (DM-as-liveness toggle) is the 5th membership source: a session whose
    #    ONLY signal is a SENT DM enters the roster (union doctrine).
    candidate_ids = set()
    candidate_ids.update( k for k in events_by_session.keys() if k )
    candidate_ids.update( k for k in bridge_sessions.keys() if k )
    candidate_ids.update( k for k in dm_activity.keys() if k )
    for row in who_rows or [ ]:
        if isinstance( row, dict ) and row.get( "session_id" ):
            candidate_ids.add( row.get( "session_id" ) )

    canon = _canonicalize_ids( candidate_ids )

    # raw_id → canonical inverse: canonical → [raw ids]
    groups = { }
    for raw, cid in canon.items():
        groups.setdefault( cid, [ ] ).append( raw )

    view = { }
    for cid, raw_ids in groups.items():
        # Concatenate event records across all raw forms of this session, then
        # split by the kind discriminator: idle_prompt feeds idle_prompt_ts ONLY.
        records = [ ]
        for raw in raw_ids:
            recs = events_by_session.get( raw )
            if isinstance( recs, list ):
                records.extend( r for r in recs if isinstance( r, dict ) )

        # The activity axis excludes ALL THREE off-axis kinds (idle_prompt
        # recency, the reaped tombstone, AND the task_transition progress beacon):
        # none may become `state` or feed the stop-event age. The reaped tombstone
        # is a membership + verdict signal ONLY; the task_transition record is a
        # PROGRESS signal ONLY (arbiter signs-of-life Fix 2) — it feeds
        # last_task_transition_ts (folded into the progress signature) and must
        # NEVER map through _STATE_BY_OUTCOME (it carries no `outcome` key anyway).
        activity_recs    = [ r for r in records if r.get( "kind" ) not in ( KIND_IDLE_PROMPT, EVENT_KIND_REAPED, EVENT_KIND_TASK_TRANSITION ) ]
        idleprompt_recs  = [ r for r in records if r.get( "kind" ) == KIND_IDLE_PROMPT ]
        reaped_recs      = [ r for r in records if r.get( "kind" ) == EVENT_KIND_REAPED ]
        tasktrans_recs   = [ r for r in records if r.get( "kind" ) == EVENT_KIND_TASK_TRANSITION ]

        last_activity = activity_recs[ -1 ]   if activity_recs   else None
        last_idle     = idleprompt_recs[ -1 ] if idleprompt_recs else None
        last_reaped   = reaped_recs[ -1 ]     if reaped_recs     else None
        last_tasktrans = tasktrans_recs[ -1 ] if tasktrans_recs  else None

        commons_ts = _commons_ts_for_session( who_rows, cid )
        # DM-as-liveness (toggle, 2026-06-17): the per-session SENT-DM ts. A pure
        # lookup into the orchestrator-supplied map — kept OFF the activity axis
        # (never state / last_event_ts / last_activity_ts / `alive`) and
        # deliberately NOT phantom-guarded by bridge presence: the coverage hole
        # this closes IS the bridge-absent coordination-only manager, so guarding
        # dm_ts on bridge presence would defeat the feature. It feeds the verdict
        # seam (fleet_render.compute_liveness, flag-gated) ONLY.
        dm_ts = _dm_ts_for_session( dm_activity, cid )

        # Bridge presence + persona (source a). A raw id may be the bridge key.
        bridge_persona = None
        bridge_present = False
        for raw in raw_ids:
            if raw in bridge_sessions:
                bridge_present = True
                if bridge_sessions[ raw ] and bridge_persona is None:
                    bridge_persona = bridge_sessions[ raw ]

        # Membership: a session is a member iff it has a REAL signal. An empty
        # event list with no commons/idle/bridge/dm signal is NOT trackable.
        # Judged on the RAW commons signal (pre-guard) so a phantom stays an
        # auditable roster row instead of vanishing without trace. dm_ts confers
        # membership (a DMing-only session enters the roster) — union doctrine.
        has_signal = bool( activity_recs ) or bool( idleprompt_recs ) or bool( reaped_recs ) \
                     or bool( tasktrans_recs ) or commons_ts is not None or bridge_present \
                     or dm_ts is not None
        if not has_signal:
            continue

        # PHANTOM GUARD (worker-roster mirror of manager_resolver.
        # resolve_active_managers): a commons echo from a session ABSENT from the
        # live-bridge discovery is retention residue of a reaped/dead process,
        # NOT liveness — a reap deletes the bridge file, but commons_who keeps
        # listing the session for its retention window, which pinned reaped
        # workers at "quiet" on the roster. Null the echo so the verdict seam
        # (fleet_render.compute_liveness) sees no commons age and the §5.2
        # publish-prune (build_snapshot include_offline=False) evicts the row as
        # soon as its real signals age out. A LIVE bridge keeps commons as a
        # legitimate secondary signal (the Part-7 union doctrine is unchanged
        # for bridge-present sessions); event/idle_prompt signals still count
        # either way (degrade-safe: a bridge-discovery hiccup can only mute the
        # commons echo, never kill event-based liveness).
        if not bridge_present:
            commons_ts = None

        last_event_ts       = _parse_iso( last_activity.get( "ts" ) ) if last_activity else None
        last_outcome        = last_activity.get( "outcome" ) if last_activity else None
        idle_prompt_ts      = _parse_iso( last_idle.get( "ts" ) ) if last_idle else None
        # PROGRESS-ONLY (arbiter signs-of-life Fix 2): deliberately NOT folded into
        # activity_ts / `alive`. Liveness is already broad (PreToolUse + PostToolUse
        # bridge-mtime stamps cover a task-writing session); this ts feeds the
        # PROGRESS signature ONLY, keeping liveness and progress orthogonal.
        task_transition_ts  = _parse_iso( last_tasktrans.get( "ts" ) ) if last_tasktrans else None
        activity_ts         = _newer( _newer( last_event_ts, commons_ts ), idle_prompt_ts )

        persona = bridge_persona
        if persona is None and last_activity is not None:
            persona = last_activity.get( "persona" )
        if persona is None and last_idle is not None:
            persona = last_idle.get( "persona" )
        if persona is None and last_reaped is not None:
            persona = last_reaped.get( "persona" )
        if persona is None and last_tasktrans is not None:
            persona = last_tasktrans.get( "persona" )

        view[ cid ] = {
            "session_id"       : cid,
            "persona"          : persona,
            "last_outcome"     : last_outcome,
            "last_event_ts"    : last_event_ts,
            "commons_ts"       : commons_ts,
            "idle_prompt_ts"   : idle_prompt_ts,
            "dm_ts"            : dm_ts,
            "last_task_transition_ts" : task_transition_ts,
            "last_activity_ts" : activity_ts,
            "alive"            : _is_recent( activity_ts, now, alive_threshold_seconds ),
            "state"            : _STATE_BY_OUTCOME.get( last_outcome, "unknown" ),
            "holding_on"       : ( last_activity.get( "awaiting" ) or "none" ) if last_activity else "none",
            "stuck"            : _count_stuck_episodes( activity_recs ) >= STUCK_REPEAT_THRESHOLD,
            "poke_count"       : last_activity.get( "poke_count" ) if last_activity else None,
            "cap"              : last_activity.get( "cap" ) if last_activity else None,
            "reaped"           : bool( reaped_recs ),
        }
    return view


def quick_smoke_test():
    """Self-contained smoke test. Returns True or raises AssertionError."""
    now = datetime.datetime( 2026, 6, 5, 12, 0, 0, tzinfo=datetime.timezone.utc )

    def ev( outcome, ts, **kw ):
        rec = { "session_id": "s", "persona": "Ann", "outcome": outcome, "ts": ts,
                "poke_count": 0, "cap": 3, "work_owed": False, "awaiting": None }
        rec.update( kw )
        return rec

    recent = ( now - datetime.timedelta( seconds=30 ) ).isoformat()
    old    = ( now - datetime.timedelta( seconds=9000 ) ).isoformat()

    full_uuid = "abcd1234-aaaa-bbbb-cccc-dddddddddddd"
    events_by_session = {
        "s1": [ ev( OUTCOME_POKE, recent, awaiting="peer:Bob", poke_count=1 ) ],
        # two cap_reached+owed episodes ⇒ REPEATED ⇒ stuck
        "s2": [ ev( OUTCOME_CAP_REACHED, old, work_owed=True, poke_count=3 ),
                ev( OUTCOME_CAP_REACHED, recent, work_owed=True, poke_count=3 ) ],
        "s3": [ ev( EVENT_IDLE, old ) ],      # old event, but session active on commons (live bridge)
        "s4": [ ],                            # empty + no other signal → skipped
        # idle_prompt-ONLY session: kind-tagged, NO outcome → enters the roster
        # via the idle_prompt signal but stays OFF the activity axis (N2)
        "ip": [ { "session_id": "ip", "persona": "Dot", "kind": "idle_prompt", "ts": recent } ],
        # reaped-ONLY session: a kind=reaped tombstone (NO outcome) → enters the
        # roster as a member but stays OFF the activity axis; reaped flag set so
        # the verdict seam force-offlines it.
        "rp": [ { "session_id": "rp", "persona": "Hal", "kind": "reaped", "ts": recent } ],
        # canonicalization (N3): a SHORT event id that prefixes the full bridge uuid
        "abcd1234": [ ev( OUTCOME_POKE, recent, persona="Eve", poke_count=2 ) ],
    }
    who_rows = [
        { "session_id": "s3", "persona_name": "Cal", "last_post_ts": recent },
        # PHANTOM: reaped worker — commons echo recent, but NO live bridge
        { "session_id": "ph", "persona_name": "Gus", "last_post_ts": recent },
    ]
    bridge_sessions = {
        full_uuid                : "Eve",     # SAME session as short event id "abcd1234"
        "bridgeonly-no-events"   : "Fred",    # bridge-only member (no events at all)
        "s3"                     : "Cal",     # s3 has a LIVE bridge ⇒ commons counts
    }

    view = build_fleet_view(
        events_by_session, who_rows, now, alive_threshold_seconds=3600, bridge_sessions=bridge_sessions
    )

    # UNION membership: stop-event (s1/s2/s3) ∪ idle_prompt (ip) ∪ canonical
    # bridge⊕event (full_uuid) ∪ bridge-only (bridgeonly) ∪ commons phantom (ph)
    # — s4 (no signal) skipped
    assert set( view ) == { "s1", "s2", "s3", "ip", "rp", full_uuid, "bridgeonly-no-events", "ph" }, set( view )
    assert view[ "s1" ][ "state" ] == "working" and view[ "s1" ][ "holding_on" ] == "peer:Bob"
    assert view[ "s2" ][ "stuck" ] is True and view[ "s2" ][ "state" ] == "stuck"
    # s3: old event ts but recent commons ts + LIVE bridge ⇒ commons counts ⇒ alive
    assert view[ "s3" ][ "alive" ] is True and view[ "s3" ][ "last_outcome" ] == EVENT_IDLE

    # PHANTOM GUARD (§5.2(b)): ph is commons-recent but bridge-ABSENT — a reaped
    # worker's retention echo. Still a roster member (auditable), but its commons
    # echo is nulled ⇒ no liveness signal at all ⇒ alive False (and the verdict
    # seam reads it "offline", so the publish-prune evicts it).
    phv = view[ "ph" ]
    assert phv[ "commons_ts" ] is None and phv[ "alive" ] is False
    assert phv[ "last_activity_ts" ] is None and phv[ "state" ] == "unknown"

    # idle_prompt-only: kind filter keeps it OFF the activity axis, ON idle_prompt_ts
    ipv = view[ "ip" ]
    assert ipv[ "state" ] == "unknown" and ipv[ "last_outcome" ] is None
    assert ipv[ "last_event_ts" ] is None and ipv[ "idle_prompt_ts" ] is not None
    assert ipv[ "persona" ] == "Dot"

    # reaped-only: kind=reaped tombstone keeps it OFF the activity axis, sets the
    # reaped flag (verdict seam force-offlines it), still a member with persona.
    rpv = view[ "rp" ]
    assert rpv[ "reaped" ] is True and rpv[ "state" ] == "unknown"
    assert rpv[ "last_outcome" ] is None and rpv[ "last_event_ts" ] is None
    assert rpv[ "idle_prompt_ts" ] is None and rpv[ "persona" ] == "Hal"
    # every non-reaped row carries reaped=False (additive flag, default off)
    assert view[ "s1" ][ "reaped" ] is False and view[ "ip" ][ "reaped" ] is False

    # canonicalization: short "abcd1234" event ⊕ full-uuid bridge ⇒ ONE view under the full uuid
    assert "abcd1234" not in view
    cv = view[ full_uuid ]
    assert cv[ "state" ] == "working" and cv[ "persona" ] == "Eve"   # bridge persona preferred

    # bridge-only member: present + named, but no activity ⇒ state unknown, no stop-event ts
    bov = view[ "bridgeonly-no-events" ]
    assert bov[ "persona" ] == "Fred" and bov[ "state" ] == "unknown" and bov[ "last_event_ts" ] is None

    # DM-as-liveness toggle (2026-06-17): with NO dm_activity passed, every view
    # carries dm_ts=None (additive field, default off) — no spurious members.
    assert all( v[ "dm_ts" ] is None for v in view.values() )

    # With a dm_activity map: a DM-only session ("dm1") enters the roster (source
    # e), dm_ts is set, and it stays OFF the activity axis (state unknown, no
    # last_event_ts, last_activity_ts None, alive False — the verdict seam, not
    # build_fleet_view, turns dm_ts into a LIVE verdict). dm_ts is NOT phantom-
    # guarded: dm1 has NO bridge yet still carries its dm_ts (the coverage hole).
    dm_recent   = now - datetime.timedelta( seconds=12 )
    dm_activity = { "dm1": dm_recent, "s1": now - datetime.timedelta( seconds=5 ) }
    dview = build_fleet_view(
        events_by_session, who_rows, now, alive_threshold_seconds=3600,
        bridge_sessions=bridge_sessions, dm_activity=dm_activity,
    )
    assert "dm1" in dview                                         # source (e) confers membership
    dm1 = dview[ "dm1" ]
    assert dm1[ "dm_ts" ] == dm_recent                           # set, NOT bridge-guarded
    assert dm1[ "last_event_ts" ] is None and dm1[ "commons_ts" ] is None
    assert dm1[ "last_activity_ts" ] is None and dm1[ "alive" ] is False   # off the activity axis
    assert dm1[ "state" ] == "unknown"
    # s1 (a stop-event session) ALSO gets its dm_ts folded in (prefix-matched),
    # but its state/last_event_ts are unchanged by dm (liveness ≠ activity).
    assert dview[ "s1" ][ "dm_ts" ] == dm_activity[ "s1" ]
    assert dview[ "s1" ][ "state" ] == "working" and dview[ "s1" ][ "last_event_ts" ] is not None
    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"fleet_data_model smoke: {'PASS' if ok else 'FAIL'}" )
