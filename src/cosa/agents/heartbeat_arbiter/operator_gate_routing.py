#!/usr/bin/env python3
"""
Operator-gate URGENCY routing (PURE) — proactive-manager A2 (fcb5dbc0, design D4).

The arbiter is the SINGLE pusher of operator gates (`gate_class='operator'` — the
store's fleet-wide "awaiting the human operator" queue). D4 routes each OPEN gate
by its `urgency` tier so the human is neither flooded nor starved:

    urgent → push immediately (interrupt)
    normal → batched into a periodic digest (cadence INI-configurable)
    low    → sits in the queue until the human PULLS it (never auto-pushed)

This module owns ONLY the pure routing DECISION — partition by tier + the digest
cadence debounce. It performs NO I/O and emits NO pushes: the arbiter
(`arbiter_job.py`) gathers the open operator gates, calls these transforms, then
does the actual interrupt / digest emission and stamps the digest clock. Keeping
the decision pure here (the `heartbeat_work_owed` discipline) makes it
exhaustively unit-testable and decouples it from the arbiter's push plumbing — the
thin arbiter wiring is the ONLY part that touches `arbiter_job.py` (deferred to the
post-Lane-B arbiter pass; this pure core carries zero collision risk).

The tier strings mirror `cosa.rest.task_store_rules.VALID_URGENCIES` (the store
enum, default "normal"); kept as literals here so the pure agent module takes no
dependency on the rest layer.

Design authority: planning-is-prompting ->
    src/rnd/2026.06.23-proactive-manager-doctrine-and-mechanism.md §D4.
"""

import datetime


# Urgency tiers (mirror task_store_rules.VALID_URGENCIES; "normal" is the default).
URGENCY_INTERRUPT = "urgent"
URGENCY_DIGEST    = "normal"
URGENCY_QUEUE     = "low"

# The digest cadence default (seconds): how often the batched NORMAL-urgency gates
# are emitted as one digest. INI-overridable (lupin-app.ini `arbiter operator gate
# digest cadence seconds`). 1800 = 30 min — normal gates are not time-critical, so
# a periodic sweep avoids both per-gate noise (urgent owns interrupts) and
# starvation (low is pull-only). The arbiter passes the runtime value in.
DEFAULT_DIGEST_CADENCE_SECONDS = 1800


def _parse_iso( value ):
    """
    Parse an ISO-8601 timestamp string -> aware datetime, or None. Never raises.

    Mirrors fleet_data_model._parse_iso (a trailing 'Z' normalized to +00:00, a
    naive datetime assumed UTC) so the routing clock agrees with the arbiter's.
    """
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


def _urgency_of( gate ):
    """
    The routing tier of one gate (defensive over foreign store/hold data).

    Ensures:
        - returns the gate's `urgency` when it is one of the three known tiers
        - returns URGENCY_DIGEST ("normal", the store default) for a missing /
          unknown / non-string urgency — a gate is NEVER dropped and NEVER
          spuriously escalated to an interrupt (urgent is strictly opt-in)
    """
    value = gate.get( "urgency" ) if isinstance( gate, dict ) else None
    if value in ( URGENCY_INTERRUPT, URGENCY_DIGEST, URGENCY_QUEUE ):
        return value
    return URGENCY_DIGEST


def partition_by_urgency( gates ):
    """
    Partition open operator gates into the three D4 routes (PURE).

    Requires:
        - gates is an iterable of gate-row dicts, or None

    Ensures:
        - returns { "interrupt": [...], "digest": [...], "queue": [...] } where
          each gate lands in exactly one bucket by its tier (urgent→interrupt,
          normal→digest, low→queue)
        - a non-dict entry is skipped; a gate with a missing/unknown urgency is
          routed to "digest" (the safe default tier — never dropped, never an
          interrupt)
        - input order is preserved within each bucket; PURE (no clock, no IO)
    """
    out = { "interrupt": [ ], "digest": [ ], "queue": [ ] }
    bucket = { URGENCY_INTERRUPT: "interrupt", URGENCY_DIGEST: "digest", URGENCY_QUEUE: "queue" }
    for gate in ( gates or [ ] ):
        if not isinstance( gate, dict ):
            continue
        out[ bucket[ _urgency_of( gate ) ] ].append( gate )
    return out


def digest_due( last_digest_ts, now, cadence_seconds=DEFAULT_DIGEST_CADENCE_SECONDS ):
    """
    Has the NORMAL-urgency digest cadence elapsed? The pure debounce predicate.

    Requires:
        - last_digest_ts is the arbiter's most-recent digest-emission stamp
          (ISO-8601 str) or None (never emitted)
        - now is an aware datetime (the arbiter's injected clock)
        - cadence_seconds is the digest window (positive number)

    Ensures:
        - returns True when there is no datable prior digest (None / unparseable
          ⇒ bias-to-emit a first digest) OR the age >= cadence_seconds
        - Boundary: age EXACTLY == cadence is due (>=)
        - a future stamp (clock skew) reads NOT due (age < cadence); never raises
        - PURE: no clock read, no IO
    """
    parsed = _parse_iso( last_digest_ts )
    if parsed is None:
        return True
    try:
        age = ( now - parsed ).total_seconds()
    except ( TypeError, AttributeError ):
        return True
    return age >= cadence_seconds


def route_operator_gates( gates, last_digest_ts, now,
                          cadence_seconds=DEFAULT_DIGEST_CADENCE_SECONDS ):
    """
    The actionable D4 routing verdict the arbiter consumes (PURE).

    Combines partition_by_urgency + digest_due into one verdict so the arbiter's
    single-pusher loop is a thin consumer: interrupt every gate in `interrupt`;
    emit `digest` as ONE batch + stamp the digest clock ONLY when `digest_due` is
    True AND `digest` is non-empty; `queue` is never auto-pushed (surfaced only
    when the human pulls it via task_query(gate_class=operator, urgency=low)).

    Requires:
        - gates is an iterable of open operator-gate dicts, or None
        - last_digest_ts / now / cadence_seconds as for digest_due

    Ensures:
        - returns {
            "interrupt": [urgent gates],         # push each immediately
            "digest":    [normal gates] if due else [ ],  # emit as one batch when due
            "digest_due": bool,                  # whether the cadence elapsed
            "queue":     [low gates],            # pull-only, never auto-pushed
          }
        - `digest` is the EMPTY list when the cadence has not elapsed (the normal
          gates wait for the next due sweep) — so the arbiter emits a digest iff
          `digest` is truthy
        - PURE: no clock read, no IO; never raises on well-formed dict input
    """
    parts = partition_by_urgency( gates )
    due   = digest_due( last_digest_ts, now, cadence_seconds )
    return {
        "interrupt"  : parts[ "interrupt" ],
        "digest"     : parts[ "digest" ] if due else [ ],
        "digest_due" : due,
        "queue"      : parts[ "queue" ],
    }


def quick_smoke_test():
    """
    Self-contained smoke test of the pure routing transforms.

    Ensures:
        - Returns True if partition / digest_due / route behave as designed;
          raises AssertionError otherwise.
    """
    now = datetime.datetime( 2026, 6, 23, 12, 0, 0, tzinfo=datetime.timezone.utc )

    def ago( s ):
        return ( now - datetime.timedelta( seconds=s ) ).isoformat()

    gates = [
        { "id": "u1", "urgency": "urgent" },
        { "id": "n1", "urgency": "normal" },
        { "id": "l1", "urgency": "low" },
        { "id": "x1" },                       # missing urgency → digest (default tier)
        { "id": "x2", "urgency": "bogus" },   # unknown → digest
        "junk",                                # non-dict → skipped
    ]
    parts = partition_by_urgency( gates )
    assert [ g[ "id" ] for g in parts[ "interrupt" ] ] == [ "u1" ]
    assert [ g[ "id" ] for g in parts[ "digest" ] ]    == [ "n1", "x1", "x2" ]
    assert [ g[ "id" ] for g in parts[ "queue" ] ]     == [ "l1" ]

    # digest_due: never emitted ⇒ due; fresh ⇒ not due; stale ⇒ due; boundary ⇒ due
    assert digest_due( None, now ) is True
    assert digest_due( ago( 60 ), now ) is False
    assert digest_due( ago( 1801 ), now ) is True
    assert digest_due( ago( DEFAULT_DIGEST_CADENCE_SECONDS ), now ) is True
    assert digest_due( "not-a-ts", now ) is True                       # unparseable ⇒ bias-to-emit

    # route: urgent always interrupts; digest only when due; queue always present
    due_verdict = route_operator_gates( gates, None, now )
    assert [ g[ "id" ] for g in due_verdict[ "interrupt" ] ] == [ "u1" ]
    assert [ g[ "id" ] for g in due_verdict[ "digest" ] ]    == [ "n1", "x1", "x2" ]
    assert due_verdict[ "digest_due" ] is True
    assert [ g[ "id" ] for g in due_verdict[ "queue" ] ]     == [ "l1" ]

    not_due = route_operator_gates( gates, ago( 60 ), now )
    assert not_due[ "digest" ] == [ ] and not_due[ "digest_due" ] is False   # normals wait
    assert [ g[ "id" ] for g in not_due[ "interrupt" ] ] == [ "u1" ]         # urgent still interrupts

    print( "✓ operator_gate_routing smoke passed" )
    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"operator_gate_routing smoke: {'PASS' if ok else 'FAIL'}" )
