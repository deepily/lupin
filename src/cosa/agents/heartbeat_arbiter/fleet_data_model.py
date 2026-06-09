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
**session_id** (persona can be borrowed/duplicated — Rachel's catch).

Input contract (Rachel's wiring): `events_by_session` is the ACCUMULATED tail
per session (oldest→newest, ~50 records) — `[-1]` is the current state; the
list is scanned for REPEATED cap_reached (the §4 "stuck" signal).

Pure + never-raises.

Design authority: lupin →
    src/rnd/v0.1.8/2026.06.04-heartbeat-hook/03-arbiter-design.md §4 / N3.
"""
import datetime


# last-outcome → coarse session state (doc 03 §4)
_STATE_BY_OUTCOME = {
    "poke"        : "working",
    "honored"     : "holding",
    "cap_reached" : "stuck",
    "idle"        : "idle",
}

# "stuck = REPEATED cap_reached + work_owed" (§4): ≥ this many cap_reached+owed
# episodes in the accumulated tail. A single cap-reach isn't yet "stuck".
STUCK_REPEAT_THRESHOLD = 2


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


def _count_stuck_episodes( events ):
    """Count cap_reached records with work_owed True in the accumulated tail."""
    return sum(
        1 for e in events
        if isinstance( e, dict ) and e.get( "outcome" ) == "cap_reached" and e.get( "work_owed" ) is True
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


def build_fleet_view( events_by_session, who_rows, now, alive_threshold_seconds, bridge_sessions=None ):
    """
    Build the per-session fleet view as the UNION of all liveness signals.

    The roster is the UNION of FOUR sources (arbiter liveness fix, Part 7 /
    Step 1.4) — a session enters the view if it appears in ANY of:
        (a) bridge-discovered   — `bridge_sessions` (the arbiter passes this IN;
            it does the IO via find_active_voice_persona_sessions — the leaf
            stays pure),
        (b) commons-active      — `who_rows`,
        (c) idle_prompt-recent  — kind=idle_prompt records in events_by_session,
        (d) stop-event sessions — the prior event-sourced members.
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

    Ensures:
        - Returns dict { canonical_session_id: VIEW } for every session with ≥1
          REAL signal (an event record, an idle_prompt record, a commons match,
          or a bridge presence); a bare empty event list with no other signal is
          NOT a member (preserves the old "skip empty/untrackable" behavior)
        - VIEW (flat dict): session_id · persona · last_outcome ·
          last_event_ts(datetime|None — STOP/non-idle_prompt) ·
          commons_ts(datetime|None) · idle_prompt_ts(datetime|None) ·
          last_activity_ts(datetime|None; max of the three) · alive(bool) ·
          state · holding_on · stuck · poke_count · cap
        - the three distinct ts fields stay SEPARATE so the verdict seam
          (fleet_render.compute_liveness) can derive four distinct ages
        - persona prefers the bridge-discovered name, then the last activity
          record, then the idle_prompt record
        - Never raises
    """
    events_by_session = events_by_session or { }
    bridge_sessions   = bridge_sessions or { }

    # 1. Gather every candidate session id across the four sources, then
    #    canonicalize the heterogeneous id forms before dedup (N3).
    candidate_ids = set()
    candidate_ids.update( k for k in events_by_session.keys() if k )
    candidate_ids.update( k for k in bridge_sessions.keys() if k )
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

        activity_recs   = [ r for r in records if r.get( "kind" ) != KIND_IDLE_PROMPT ]
        idleprompt_recs = [ r for r in records if r.get( "kind" ) == KIND_IDLE_PROMPT ]

        last_activity = activity_recs[ -1 ]   if activity_recs   else None
        last_idle     = idleprompt_recs[ -1 ] if idleprompt_recs else None

        commons_ts = _commons_ts_for_session( who_rows, cid )

        # Bridge presence + persona (source a). A raw id may be the bridge key.
        bridge_persona = None
        bridge_present = False
        for raw in raw_ids:
            if raw in bridge_sessions:
                bridge_present = True
                if bridge_sessions[ raw ] and bridge_persona is None:
                    bridge_persona = bridge_sessions[ raw ]

        # Membership: a session is a member iff it has a REAL signal. An empty
        # event list with no commons/idle/bridge signal is NOT trackable.
        has_signal = bool( activity_recs ) or bool( idleprompt_recs ) \
                     or commons_ts is not None or bridge_present
        if not has_signal:
            continue

        last_event_ts  = _parse_iso( last_activity.get( "ts" ) ) if last_activity else None
        last_outcome   = last_activity.get( "outcome" ) if last_activity else None
        idle_prompt_ts = _parse_iso( last_idle.get( "ts" ) ) if last_idle else None
        activity_ts    = _newer( _newer( last_event_ts, commons_ts ), idle_prompt_ts )

        persona = bridge_persona
        if persona is None and last_activity is not None:
            persona = last_activity.get( "persona" )
        if persona is None and last_idle is not None:
            persona = last_idle.get( "persona" )

        view[ cid ] = {
            "session_id"       : cid,
            "persona"          : persona,
            "last_outcome"     : last_outcome,
            "last_event_ts"    : last_event_ts,
            "commons_ts"       : commons_ts,
            "idle_prompt_ts"   : idle_prompt_ts,
            "last_activity_ts" : activity_ts,
            "alive"            : _is_recent( activity_ts, now, alive_threshold_seconds ),
            "state"            : _STATE_BY_OUTCOME.get( last_outcome, "unknown" ),
            "holding_on"       : ( last_activity.get( "awaiting" ) or "none" ) if last_activity else "none",
            "stuck"            : _count_stuck_episodes( activity_recs ) >= STUCK_REPEAT_THRESHOLD,
            "poke_count"       : last_activity.get( "poke_count" ) if last_activity else None,
            "cap"              : last_activity.get( "cap" ) if last_activity else None,
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
        "s1": [ ev( "poke", recent, awaiting="peer:Bob", poke_count=1 ) ],
        # two cap_reached+owed episodes ⇒ REPEATED ⇒ stuck
        "s2": [ ev( "cap_reached", old, work_owed=True, poke_count=3 ),
                ev( "cap_reached", recent, work_owed=True, poke_count=3 ) ],
        "s3": [ ev( "idle", old ) ],          # old event, but session active on commons
        "s4": [ ],                            # empty + no other signal → skipped
        # idle_prompt-ONLY session: kind-tagged, NO outcome → enters the roster
        # via the idle_prompt signal but stays OFF the activity axis (N2)
        "ip": [ { "session_id": "ip", "persona": "Dot", "kind": "idle_prompt", "ts": recent } ],
        # canonicalization (N3): a SHORT event id that prefixes the full bridge uuid
        "abcd1234": [ ev( "poke", recent, persona="Eve", poke_count=2 ) ],
    }
    who_rows = [ { "session_id": "s3", "persona_name": "Cal", "last_post_ts": recent } ]
    bridge_sessions = {
        full_uuid                : "Eve",     # SAME session as short event id "abcd1234"
        "bridgeonly-no-events"   : "Fred",    # bridge-only member (no events at all)
    }

    view = build_fleet_view(
        events_by_session, who_rows, now, alive_threshold_seconds=3600, bridge_sessions=bridge_sessions
    )

    # UNION membership: stop-event (s1/s2/s3) ∪ idle_prompt (ip) ∪ canonical
    # bridge⊕event (full_uuid) ∪ bridge-only (bridgeonly) — s4 (no signal) skipped
    assert set( view ) == { "s1", "s2", "s3", "ip", full_uuid, "bridgeonly-no-events" }, set( view )
    assert view[ "s1" ][ "state" ] == "working" and view[ "s1" ][ "holding_on" ] == "peer:Bob"
    assert view[ "s2" ][ "stuck" ] is True and view[ "s2" ][ "state" ] == "stuck"
    # s3: old event ts but recent commons ts (matched by session_id) ⇒ alive
    assert view[ "s3" ][ "alive" ] is True and view[ "s3" ][ "last_outcome" ] == "idle"

    # idle_prompt-only: kind filter keeps it OFF the activity axis, ON idle_prompt_ts
    ipv = view[ "ip" ]
    assert ipv[ "state" ] == "unknown" and ipv[ "last_outcome" ] is None
    assert ipv[ "last_event_ts" ] is None and ipv[ "idle_prompt_ts" ] is not None
    assert ipv[ "persona" ] == "Dot"

    # canonicalization: short "abcd1234" event ⊕ full-uuid bridge ⇒ ONE view under the full uuid
    assert "abcd1234" not in view
    cv = view[ full_uuid ]
    assert cv[ "state" ] == "working" and cv[ "persona" ] == "Eve"   # bridge persona preferred

    # bridge-only member: present + named, but no activity ⇒ state unknown, no stop-event ts
    bov = view[ "bridgeonly-no-events" ]
    assert bov[ "persona" ] == "Fred" and bov[ "state" ] == "unknown" and bov[ "last_event_ts" ] is None
    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"fleet_data_model smoke: {'PASS' if ok else 'FAIL'}" )
