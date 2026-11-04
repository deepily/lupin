#!/usr/bin/env python3
"""
Heartbeat arbiter idle-roster assembly with trust labels (pure).

The arbiter surfaces the fleet's idle or nothing-owed sessions to the manager.
Each entry carries a trust label, so the manager can weight reassignment confidence:
    - declared-available: the session emitted an idle beacon (heartbeat_events
      EVENT_IDLE, sticky until superseded, so its last emitted outcome is
      "idle"). Authoritative.
    - quiet (inferred): no beacon, but the session is alive and quiet. It has no
      activity, from events or commons, past the idle threshold. This is a
      heuristic, since "quiet" can be a long tool-run.

The roster is hybrid: declared ∪ inferred. The consumer feeds the fleet_view from
fleet_data_model, which has already merged events and commons_who into
last_activity_ts and alive. This module returns the trust-labeled roster and
never raises.

Design authority: lupin →
    src/rnd/v0.1.8/2026.06.04-heartbeat-hook/03-arbiter-design.md §6.2.
"""
import datetime

from lupin_cli.claude_code.hooks.lib.heartbeat_decision import OUTCOME_POKE, OUTCOME_HONORED
from lupin_cli.claude_code.hooks.lib.heartbeat_events import EVENT_IDLE
from cosa.agents.heartbeat_arbiter.dependency_graph import session_is_stale


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


def classify_idle( view, now, quiet_threshold_seconds ):
    """
    Trust-classify a session view's idle status, or None if it is not idle.

    Requires:
        - view is a fleet_data_model view dict
        - now is an aware datetime
        - quiet_threshold_seconds is a positive number (the "quiet" window)

    Ensures:
        - last_outcome == EVENT_IDLE → (IDLE_SOURCE_DECLARED, TRUST_DECLARED)
          — the sticky beacon wins outright
        - else, alive and quiet (now - last_activity_ts >= idle_threshold) →
          (IDLE_SOURCE_INFERENCE, TRUST_INFERRED)
        - otherwise → None (working / not-yet-quiet / dead / unknown ts)
        - Never raises
    """
    if view.get( "last_outcome" ) == EVENT_IDLE:
        return ( IDLE_SOURCE_DECLARED, TRUST_DECLARED )
    if not view.get( "alive" ):
        return None
    quiet_for = _quiet_for_seconds( view.get( "last_activity_ts" ), now )
    if quiet_for is not None and quiet_for >= quiet_threshold_seconds:
        return ( IDLE_SOURCE_INFERENCE, TRUST_INFERRED )
    return None


def build_roster( fleet_view, now, quiet_threshold_seconds, alive_threshold_seconds=None ):
    """
    Build the trust-labeled fleet idle-roster (hybrid: declared ∪ inferred).

    Requires:
        - fleet_view is a dict { session_id: view } (build_fleet_view output)
        - now is an aware datetime
        - quiet_threshold_seconds is a positive number
        - alive_threshold_seconds is a positive number (the staleness window) or
          None (the additive default → no staleness gate, byte-identical to the
          pre-filter behavior; existing 3-arg callers/tests are unaffected)

    Ensures:
        - Returns a list of { session_id, persona, idle_source, trust_label,
          last_activity_ts } for only the idle sessions (classify_idle non-None)
          that are also not stale: an idle/quiet entry is dropped when
          dependency_graph.session_is_stale (the same predicate the peer-edge and
          ping-storm fixes use, so there is one source of truth) judges its
          session beyond alive_threshold_seconds. The filter applies uniformly to
          declared and inferred entries, so a dead session's sticky EVENT_IDLE
          beacon no longer inflates the "free fleet-wide" count.
        - Fail-safe: session_is_stale returns False (keep) for a missing/None/
          unparseable last_activity_ts or an un-threaded alive_threshold_seconds
          (None), so the count never under-reports live capacity.
        - Sorted by last_activity_ts descending (most-recent first; missing last)
        - Non-dict views are skipped; never raises
    """
    roster = [ ]
    for view in fleet_view.values():
        if not isinstance( view, dict ):
            continue
        classified = classify_idle( view, now, quiet_threshold_seconds )
        if classified is None:
            continue
        if session_is_stale( view, now, alive_threshold_seconds ):       # free-count fix: live-idle only
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
        "s1": { "session_id": "s1", "persona": "Ann", "last_outcome": EVENT_IDLE,
                "alive": True, "last_activity_ts": quiet },                 # declared
        "s2": { "session_id": "s2", "persona": "Bob", "last_outcome": OUTCOME_POKE,
                "alive": True, "last_activity_ts": quiet },                 # inferred (alive+quiet)
        "s3": { "session_id": "s3", "persona": "Cal", "last_outcome": OUTCOME_POKE,
                "alive": True, "last_activity_ts": active },                # working (not quiet)
        "s4": { "session_id": "s4", "persona": "Dan", "last_outcome": OUTCOME_HONORED,
                "alive": False, "last_activity_ts": quiet },                # dead → excluded
        "s5": "not-a-dict",
    }
    roster = build_roster( fleet_view, now, quiet_threshold_seconds=300 )
    by_sid = { e[ "session_id" ]: e for e in roster }
    assert set( by_sid ) == { "s1", "s2" }, set( by_sid )
    assert by_sid[ "s1" ][ "trust_label" ] == TRUST_DECLARED
    assert by_sid[ "s2" ][ "trust_label" ] == TRUST_INFERRED
    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"idle_roster smoke: {'PASS' if ok else 'FAIL'}" )
