#!/usr/bin/env python3
"""
Heartbeat Arbiter — consumer wiring state (Rachel's lane).

Pure state objects the ArbiterConsumerJob carries ACROSS polls. They hold no
decision logic (that lives in Tiffany's leaves) and do no I/O — just the
bookkeeping the poll loop needs:

    - FleetEventAccumulator: the glob/tail returns only NEW records per poll;
      this accumulates a BOUNDED per-session tail (oldest→newest) so
      `build_fleet_view` sees each session's current state ([-1]) plus a window
      for "repeated cap_reached" stuck-detection (§4). Bounded by maxlen.

    - PingLedger: per-edge last-ping timestamp + clear-on-resume. The throttle
      DECISION is the `ping_throttle` leaf's job (should_ping / backoff); this
      only remembers when we last pinged each (holder→awaited→reason) edge and
      forgets edges that are no longer active (the holder resumed or re-held
      elsewhere ⇒ the §6.1 "clear the edge on resume" rule).

Both are pure + deterministic (no clock, no I/O) — 100%-testable in isolation.
"""
from collections import deque


DEFAULT_TAIL_MAXLEN = 50      # per-session accumulated-tail cap (ample for repeated-cap detection)


class FleetEventAccumulator:
    """
    Bounded per-session accumulation of heartbeat event records across polls.

    Requires:
        - maxlen is a positive int (per-session record cap)

    Ensures:
        - update(events_by_session) appends each session's NEW records to its
          bounded tail (oldest→newest), dropping the oldest beyond maxlen
        - snapshot() returns {session_id: list(records)} for build_fleet_view
        - never raises on well-formed {sid: list} input
    """

    def __init__( self, maxlen=DEFAULT_TAIL_MAXLEN ):
        self._maxlen      = maxlen
        self._by_session  = { }     # sid -> deque(maxlen)

    def update( self, events_by_session ):
        """
        Append new records to each session's bounded tail.

        Requires:
            - events_by_session is {session_id: [record dict, ...]} (the
              glob/tail output for THIS poll — new records only)

        Ensures:
            - each session's tail grows by its new records, capped at maxlen
            - a session seen for the first time gets a fresh bounded deque
        """
        for sid, records in events_by_session.items():
            tail = self._by_session.get( sid )
            if tail is None:
                tail = deque( maxlen=self._maxlen )
                self._by_session[ sid ] = tail
            tail.extend( records )

    def snapshot( self ):
        """
        Ensures:
            - Returns {session_id: list(records oldest→newest)} — the input
              shape build_fleet_view consumes (uses [-1] for current state)
        """
        return { sid: list( tail ) for sid, tail in self._by_session.items() }

    def sessions( self ):
        """Ensures: returns the set of session_ids seen so far."""
        return set( self._by_session.keys() )


class PingLedger:
    """
    Per-edge last-ping bookkeeping + clear-on-resume (§6.1).

    An "edge" is a (holder→awaited→reason) blocker relationship, keyed by a
    string the `ping_throttle.edge_key` leaf produces. This ledger does NOT
    decide whether to ping (that is the throttle leaf, given the last-ping ts);
    it only REMEMBERS the last ping per edge and forgets edges that are no
    longer active.

    Ensures:
        - get_last(edge_key) → the recorded last-ping value or None
        - record_ping(edge_key, ts) → store ts for the edge
        - clear_resolved(active_edge_keys) → drop every edge NOT in the active
          set (resumed/re-held elsewhere) and return the dropped keys
        - never raises
    """

    def __init__( self ):
        self._last_ping = { }       # edge_key -> ts

    def get_last( self, edge_key ):
        """Ensures: returns the last-ping ts for the edge, or None if never pinged."""
        return self._last_ping.get( edge_key )

    def record_ping( self, edge_key, ts ):
        """Ensures: records ts as the last-ping for the edge."""
        self._last_ping[ edge_key ] = ts

    def clear_resolved( self, active_edge_keys ):
        """
        Drop ledger entries for edges that are no longer active (§6.1 clear-on-resume).

        Requires:
            - active_edge_keys is an iterable of currently-active edge keys

        Ensures:
            - removes every tracked edge NOT in active_edge_keys
            - returns the set of dropped edge keys
        """
        active  = set( active_edge_keys )
        dropped = { k for k in self._last_ping if k not in active }
        for k in dropped:
            del self._last_ping[ k ]
        return dropped

    def tracked_edges( self ):
        """Ensures: returns the set of edge keys currently in the ledger."""
        return set( self._last_ping.keys() )


def quick_smoke_test():
    """
    Self-contained smoke test of the accumulator + ping ledger.

    Ensures:
        - Returns True if accumulate/cap/snapshot + record/clear-on-resume
          behave as designed; raises AssertionError otherwise.
    """
    # Accumulator — cap + incremental
    acc = FleetEventAccumulator( maxlen=3 )
    acc.update( { "s1": [ { "n": 1 }, { "n": 2 } ] } )
    acc.update( { "s1": [ { "n": 3 }, { "n": 4 } ], "s2": [ { "n": 1 } ] } )
    snap = acc.snapshot()
    assert [ r[ "n" ] for r in snap[ "s1" ] ] == [ 2, 3, 4 ], snap          # capped at 3, oldest dropped
    assert [ r[ "n" ] for r in snap[ "s2" ] ] == [ 1 ]
    assert acc.sessions() == { "s1", "s2" }

    # PingLedger — record + clear-on-resume
    led = PingLedger()
    assert led.get_last( "eA" ) is None
    led.record_ping( "eA", "t1" )
    led.record_ping( "eB", "t2" )
    assert led.get_last( "eA" ) == "t1"
    dropped = led.clear_resolved( { "eA" } )          # eB no longer active → dropped
    assert dropped == { "eB" }
    assert led.tracked_edges() == { "eA" }
    assert led.get_last( "eB" ) is None

    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"arbiter_state smoke: {'PASS' if ok else 'FAIL'}" )
