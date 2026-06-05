#!/usr/bin/env python3
"""
Heartbeat Arbiter — idle-roster assembly + trust labeling (pure).

The arbiter (doc 03 §6.2, Rick's HYBRID ruling) surfaces the fleet's idle /
nothing-owed sessions to the manager, each entry TRUST-LABELED so the manager
can weight reassignment confidence:
    - declared-available — the session emitted a genuine-idle beacon
      (heartbeat_events EVENT_IDLE; sticky-until-superseded → its LAST emitted
      outcome is "idle"). Authoritative.
    - quiet (inferred) — no beacon, but the session is ALIVE AND QUIET (no
      activity — events OR commons — past the idle threshold). Heuristic
      ("quiet" can be a long tool-run).

HYBRID = declared ∪ inferred. Pure: the consumer feeds the fleet_view (from
fleet_data_model, which already merged events + commons_who into
last_activity_ts + alive); this returns the trust-labeled roster. Never raises.

Design authority: lupin →
    src/rnd/v0.1.8/2026.06.04-heartbeat-hook/03-arbiter-design.md §6.2.
"""
import datetime

from lupin_cli.claude_code.hooks.lib.heartbeat_events import EVENT_IDLE


IDLE_SOURCE_DECLARED  = "declared"
IDLE_SOURCE_INFERENCE = "inference"

TRUST_DECLARED = "declared-available"
TRUST_INFERRED = "quiet (inferred)"

# Sortable sentinel for a missing last-activity ts (sorts last in desc order).
_MIN_TS = datetime.datetime.min.replace( tzinfo=datetime.timezone.utc )


def _quiet_for_seconds( ts, now ):
    """Seconds since ts (how long quiet), or None if unusable. Never raises."""
    if ts is None:
        return None
    try:
        return ( now - ts ).total_seconds()
    except ( TypeError, AttributeError ):
        return None


def classify_idle( view, now, idle_threshold_seconds ):
    """
    Trust-classify a session view's idle status, or None if it is NOT idle.

    Requires:
        - view is a fleet_data_model VIEW dict
        - now is an aware datetime
        - idle_threshold_seconds is a positive number (the "quiet" window)

    Ensures:
        - last_outcome == EVENT_IDLE → (IDLE_SOURCE_DECLARED, TRUST_DECLARED)
          — the sticky beacon wins outright
        - else, ALIVE AND quiet (now - last_activity_ts >= idle_threshold) →
          (IDLE_SOURCE_INFERENCE, TRUST_INFERRED)
        - otherwise → None (working / not-yet-quiet / dead / unknown ts)
        - Never raises
    """
    if view.get( "last_outcome" ) == EVENT_IDLE:
        return ( IDLE_SOURCE_DECLARED, TRUST_DECLARED )
    if not view.get( "alive" ):
        return None
    quiet_for = _quiet_for_seconds( view.get( "last_activity_ts" ), now )
    if quiet_for is not None and quiet_for >= idle_threshold_seconds:
        return ( IDLE_SOURCE_INFERENCE, TRUST_INFERRED )
    return None


def build_roster( fleet_view, now, idle_threshold_seconds ):
    """
    Build the trust-labeled fleet idle-roster (HYBRID: declared ∪ inferred).

    Requires:
        - fleet_view is a dict { session_id: VIEW } (build_fleet_view output)
        - now is an aware datetime
        - idle_threshold_seconds is a positive number

    Ensures:
        - Returns a list of { session_id, persona, idle_source, trust_label,
          last_activity_ts } for ONLY the idle sessions (classify_idle non-None)
        - Sorted by last_activity_ts descending (most-recent first; missing last)
        - Non-dict views are skipped; never raises
    """
    roster = [ ]
    for view in fleet_view.values():
        if not isinstance( view, dict ):
            continue
        classified = classify_idle( view, now, idle_threshold_seconds )
        if classified is None:
            continue
        source, label = classified
        roster.append( {
            "session_id"       : view.get( "session_id" ),
            "persona"          : view.get( "persona" ),
            "idle_source"      : source,
            "trust_label"      : label,
            "last_activity_ts" : view.get( "last_activity_ts" ),
        } )
    roster.sort( key=lambda e: e[ "last_activity_ts" ] or _MIN_TS, reverse=True )
    return roster


def quick_smoke_test():
    """Self-contained smoke test. Returns True or raises AssertionError."""
    now    = datetime.datetime( 2026, 6, 5, 12, 0, 0, tzinfo=datetime.timezone.utc )
    quiet  = now - datetime.timedelta( seconds=600 )    # 10 min quiet
    active = now - datetime.timedelta( seconds=10 )

    fleet_view = {
        "s1": { "session_id": "s1", "persona": "Ann", "last_outcome": "idle",
                "alive": True, "last_activity_ts": quiet },                 # declared
        "s2": { "session_id": "s2", "persona": "Bob", "last_outcome": "poke",
                "alive": True, "last_activity_ts": quiet },                 # inferred (alive+quiet)
        "s3": { "session_id": "s3", "persona": "Cal", "last_outcome": "poke",
                "alive": True, "last_activity_ts": active },                # working (not quiet)
        "s4": { "session_id": "s4", "persona": "Dan", "last_outcome": "honored",
                "alive": False, "last_activity_ts": quiet },                # dead → excluded
        "s5": "not-a-dict",
    }
    roster = build_roster( fleet_view, now, idle_threshold_seconds=300 )
    by_sid = { e[ "session_id" ]: e for e in roster }
    assert set( by_sid ) == { "s1", "s2" }, set( by_sid )
    assert by_sid[ "s1" ][ "trust_label" ] == TRUST_DECLARED
    assert by_sid[ "s2" ][ "trust_label" ] == TRUST_INFERRED
    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"idle_roster smoke: {'PASS' if ok else 'FAIL'}" )
