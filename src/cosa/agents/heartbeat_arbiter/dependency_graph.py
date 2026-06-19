#!/usr/bin/env python3
"""
Heartbeat Arbiter — dependency-graph cycle detection (pure).

The arbiter (doc 03 §4 / §6.4) assembles a who-waits-on-whom graph from each
session view's `holding_on: peer:X` edge and detects CYCLES = deadlocks
(A→B→A): a ring of sessions each blocked on the next, which no member can break
→ the arbiter escalates to the user (it never auto-breaks a deadlock).

Pure + never-raises. The consumer (Rachel's HeartbeatPokerJob arbiter) passes
the fleet_view (from fleet_data_model.build_fleet_view) and acts on the graph.

Design authority: lupin →
    src/rnd/v0.1.8/2026.06.04-heartbeat-hook/03-arbiter-design.md §4 / §6.4.
"""

PEER_PREFIX = "peer:"


def build_wait_edges( fleet_view ):
    """
    Extract holder→awaited-peer edges from the fleet view.

    Requires:
        - fleet_view is a dict { session_id: VIEW } (build_fleet_view output);
          each VIEW carries "persona" and "holding_on" (e.g. "peer:Sam",
          "user:Rick", "commons:foo", "none")

    Ensures:
        - Returns dict { holder_persona: awaited_persona } for ONLY peer:* edges
          with a non-empty holder AND a non-empty awaited persona
        - LAST edge wins if a holder appears twice (functional graph)
        - Non-dict views are skipped; never raises
    """
    edges = { }
    for view in fleet_view.values():
        if not isinstance( view, dict ):
            continue
        holder     = view.get( "persona" )
        holding_on = view.get( "holding_on" )
        if not holder or not isinstance( holding_on, str ) or not holding_on.startswith( PEER_PREFIX ):
            continue
        awaited = holding_on[ len( PEER_PREFIX ): ].strip()
        if awaited:
            edges[ holder ] = awaited
    return edges


def _canonicalize( cycle ):
    """Rotate a cycle so its lexicographically-smallest node is first (so the
    same ring is reported identically regardless of the walk's start)."""
    pivot = cycle.index( min( cycle ) )
    return cycle[ pivot: ] + cycle[ :pivot ]


def find_deadlock_cycles( wait_edges ):
    """
    Detect all deadlock cycles in the functional wait-graph.

    Each holder awaits AT MOST one peer (out-degree ≤ 1), so cycles are
    disjoint. Walk each unvisited node forward until the chain terminates (no
    outgoing edge), re-enters already-visited territory, or loops back into its
    own path (a NEW cycle).

    Requires:
        - wait_edges is a dict { holder: awaited }

    Ensures:
        - Returns a list of cycles; each is a list of personas in ring order,
          canonicalized (smallest persona first) for determinism
        - A→B→A → [["<min>", "<other>"]]; self-loop A→A → [["A"]]; acyclic → []
        - Never raises
    """
    visited = set( )
    cycles  = [ ]
    for start in wait_edges:
        if start in visited:
            continue
        path = [ ]
        pos  = { }
        node = start
        while node is not None and node not in visited:
            if node in pos:
                cycles.append( _canonicalize( path[ pos[ node ]: ] ) )
                break
            pos[ node ] = len( path )
            path.append( node )
            node = wait_edges.get( node )
        visited.update( path )
    return cycles


def build_graph( fleet_view ):
    """
    Build the dependency graph + deadlock cycles from the fleet view.

    Requires:
        - fleet_view is a dict { session_id: VIEW }

    Ensures:
        - Returns { "edges": {holder: awaited}, "cycles": [canonical cycles] }
        - Never raises
    """
    edges = build_wait_edges( fleet_view )
    return { "edges": edges, "cycles": find_deadlock_cycles( edges ) }


def quick_smoke_test():
    """Self-contained smoke test. Returns True or raises AssertionError."""
    fleet_view = {
        "s1": { "persona": "Ann", "holding_on": "peer:Bob" },
        "s2": { "persona": "Bob", "holding_on": "peer:Ann" },   # Ann↔Bob deadlock
        "s3": { "persona": "Cal", "holding_on": "user:Rick" },  # not a peer edge
        "s4": { "persona": "Dan", "holding_on": "peer:Eve" },   # Dan→Eve, no cycle
        "s5": "not-a-dict",                                     # skipped
    }
    graph = build_graph( fleet_view )
    assert graph[ "edges" ] == { "Ann": "Bob", "Bob": "Ann", "Dan": "Eve" }, graph[ "edges" ]
    assert graph[ "cycles" ] == [ [ "Ann", "Bob" ] ], graph[ "cycles" ]
    assert find_deadlock_cycles( { } ) == [ ]
    assert find_deadlock_cycles( { "X": "X" } ) == [ [ "X" ] ]   # self-deadlock
    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"dependency_graph smoke: {'PASS' if ok else 'FAIL'}" )
