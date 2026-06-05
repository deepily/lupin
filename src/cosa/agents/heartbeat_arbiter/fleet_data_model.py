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


def build_fleet_view( events_by_session, who_rows, now, alive_threshold_seconds ):
    """
    Build the per-session fleet view from an accumulated record tail + who rows.

    Requires:
        - events_by_session is a dict { session_id: list[event-record-dict] }
          — the ACCUMULATED tail per session (oldest→newest)
        - who_rows is a list of commons_who rows (dicts) or None
        - now is an aware datetime
        - alive_threshold_seconds is a positive number (the "alive" window)

    Ensures:
        - Returns dict { session_id: VIEW } for each session with ≥1 valid event
        - VIEW (flat dict): session_id · persona · last_outcome ·
          last_event_ts(datetime|None) · last_activity_ts(datetime|None;
          max of last event ts + matching commons ts) · alive(bool) ·
          state(working|holding|stuck|idle|unknown) · holding_on(str, "none"
          default) · stuck(bool; ≥ STUCK_REPEAT_THRESHOLD cap_reached+owed) ·
          poke_count · cap
        - Sessions with no/invalid events are skipped (not trackable)
        - liveness: alive = last_activity_ts within alive_threshold (event-ts
          PRIMARY, commons_who SECONDARY matched by session_id)
        - Never raises
    """
    view = { }
    for sid, events in ( events_by_session or { } ).items():
        if not isinstance( events, list ) or not events:
            continue
        last = events[ -1 ]
        if not isinstance( last, dict ):
            continue

        persona       = last.get( "persona" )
        last_event_ts = _parse_iso( last.get( "ts" ) )
        last_outcome  = last.get( "outcome" )
        activity_ts   = _newer( last_event_ts, _commons_ts_for_session( who_rows, sid ) )

        view[ sid ] = {
            "session_id"       : sid,
            "persona"          : persona,
            "last_outcome"     : last_outcome,
            "last_event_ts"    : last_event_ts,
            "last_activity_ts" : activity_ts,
            "alive"            : _is_recent( activity_ts, now, alive_threshold_seconds ),
            "state"            : _STATE_BY_OUTCOME.get( last_outcome, "unknown" ),
            "holding_on"       : last.get( "awaiting" ) or "none",
            "stuck"            : _count_stuck_episodes( events ) >= STUCK_REPEAT_THRESHOLD,
            "poke_count"       : last.get( "poke_count" ),
            "cap"              : last.get( "cap" ),
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

    events_by_session = {
        "s1": [ ev( "poke", recent, awaiting="peer:Bob", poke_count=1 ) ],
        # two cap_reached+owed episodes ⇒ REPEATED ⇒ stuck
        "s2": [ ev( "cap_reached", old, work_owed=True, poke_count=3 ),
                ev( "cap_reached", recent, work_owed=True, poke_count=3 ) ],
        "s3": [ ev( "idle", old ) ],          # old event, but session active on commons
        "s4": [ ],                            # no events → skipped
    }
    who_rows = [ { "session_id": "s3", "persona_name": "Cal", "last_post_ts": recent } ]

    view = build_fleet_view( events_by_session, who_rows, now, alive_threshold_seconds=3600 )
    assert set( view ) == { "s1", "s2", "s3" }, set( view )
    assert view[ "s1" ][ "state" ] == "working" and view[ "s1" ][ "holding_on" ] == "peer:Bob"
    assert view[ "s2" ][ "stuck" ] is True and view[ "s2" ][ "state" ] == "stuck"
    # s3: old event ts but recent commons ts (matched by session_id) ⇒ alive
    assert view[ "s3" ][ "alive" ] is True and view[ "s3" ][ "last_outcome" ] == "idle"
    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"fleet_data_model smoke: {'PASS' if ok else 'FAIL'}" )
