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

STORE-CORROBORATION (bug 436a366b, 2026-06-23): the `holding_on: peer:X` edges
above are SELF-REPORTED / view-derived — a fresh, legitimately-PROGRESSING
sequencing wait (e.g. Krishna awaiting Mr Radio's merge+build) self-reports a
ring that is NOT a deadlock and false-escalated every poll. The escalation is
now GATED on an AUTHORITATIVE store dependency ring (build_store_wait_edges +
cycle_is_store_backed): a derived persona-ring fires ONLY when it is corroborated
by real store `blocked_by` edges (owner→owner). Scope limit (v1, ratified by Mr
Radio): a PURE-coordination ring — two managers mutually awaiting with ZERO store
rows — is out of scope; it is rare, a human breaks it anyway, and the correct fix
is managers expressing real waits as store `blocked_by` (this gate is a hygiene
forcing-function, a feature not a gap).
"""
from lupin_mcp.persona_normalization import canonical_persona_key

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


def build_store_wait_edges( owed_by_persona ):
    """
    Build AUTHORITATIVE owner→owner wait edges from store `blocked_by` refs.

    The store source of truth for "who is really blocked on whom" — the
    counterpart to the self-reported build_wait_edges. Consumed by
    cycle_is_store_backed to corroborate a derived deadlock ring before the
    arbiter escalates it (bug 436a366b).

    Requires:
        - owed_by_persona is the arbiter's per-poll non-terminal owed read,
          { persona: [ { id, status, gate_class, blocked_by }, ... ] } (the
          _default_owed_work_fn / _classify_owed shape), or None

    `blocked_by` is a list of typed refs { "kind": "item"|"persona"|"user",
    "id": ... }:
        - persona-kind → a DIRECT owner edge holder→canonical(id).
        - item-kind    → resolved to the OWNER of that task-id via an id→owner
          map built from the SAME owed read. A blocking task that is terminal or
          owned by a persona outside this poll's read is UNRESOLVABLE → that edge
          is omitted, biasing toward NOT firing (the documented v1 scope limit).
        - user-kind / malformed / non-dict ref → ignored (a user gate is a
          human-wait, never a peer deadlock).

    Ensures:
        - returns { canonical_holder: set(canonical_awaited) }; personas are
          canonical_persona_key-normalized so the edges match the (same-spelling)
          derived cycle nodes
        - self-edges (a holder blocked on its own item) are dropped — a session
          cannot peer-deadlock on itself
        - None / malformed input → {}; never raises
    """
    owed = owed_by_persona or { }
    if not isinstance( owed, dict ):
        return { }
    # id → canonical owner, across the whole poll read (resolves item-kind refs).
    id_to_owner = { }
    for persona, items in owed.items():
        if not isinstance( items, list ):
            continue
        owner = canonical_persona_key( persona ) or persona
        for it in items:
            if isinstance( it, dict ) and it.get( "id" ) is not None:
                id_to_owner[ str( it.get( "id" ) ) ] = owner
    edges = { }
    for persona, items in owed.items():
        if not isinstance( items, list ):
            continue
        holder = canonical_persona_key( persona ) or persona
        for it in items:
            if not isinstance( it, dict ):
                continue
            for ref in ( it.get( "blocked_by" ) or [ ] ):
                if not isinstance( ref, dict ):
                    continue
                kind    = ref.get( "kind" )
                rid     = ref.get( "id" )
                awaited = None
                if kind == "persona" and isinstance( rid, str ):
                    awaited = canonical_persona_key( rid ) or rid
                elif kind == "item" and rid is not None:
                    awaited = id_to_owner.get( str( rid ) )      # None if unresolvable → edge omitted
                if awaited and awaited != holder:
                    edges.setdefault( holder, set() ).add( awaited )
    return edges


def cycle_is_store_backed( cycle, store_edges ):
    """
    True iff EVERY consecutive holder→awaited edge of a derived persona ring is
    corroborated by an authoritative store owner-edge (build_store_wait_edges).

    Requires:
        - cycle is a list of personas in ring order (find_deadlock_cycles output);
          ring edge i = cycle[i] → cycle[(i+1) % len(cycle)]
        - store_edges is build_store_wait_edges output { holder: set(awaited) }

    Ensures:
        - returns True only when all ring edges exist in store_edges (personas
          compared canonically — both sides share the view-persona spelling, so
          this is consistent)
        - a self-cycle [X] needs X→X, which build_store_wait_edges never emits
          (self-edges dropped) → a self-deadlock is never store-backed (correct:
          no real cross-owner dependency)
        - empty / malformed cycle → False; never raises
    """
    if not cycle or not isinstance( cycle, list ):
        return False
    n = len( cycle )
    for i in range( n ):
        holder  = canonical_persona_key( cycle[ i ] )             or cycle[ i ]
        awaited = canonical_persona_key( cycle[ ( i + 1 ) % n ] ) or cycle[ ( i + 1 ) % n ]
        if awaited not in store_edges.get( holder, set() ):
            return False
    return True


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

    # store-corroboration (bug 436a366b): item-kind blocked_by resolved to owners.
    owed = {
        "Ann": [ { "id": "t1", "status": "blocked", "blocked_by": [ { "kind": "item", "id": "t2" } ] } ],
        "Bob": [ { "id": "t2", "status": "blocked", "blocked_by": [ { "kind": "item", "id": "t1" } ] } ],
        "Cal": [ { "id": "t3", "status": "running", "blocked_by": [ ] } ],   # no edge
    }
    store = build_store_wait_edges( owed )
    assert store == { "ann": { "bob" }, "bob": { "ann" } }, store
    assert cycle_is_store_backed( [ "Ann", "Bob" ], store ) is True       # corroborated ring fires
    assert cycle_is_store_backed( [ "Dan", "Eve" ], store ) is False      # NOT in store → suppressed
    assert cycle_is_store_backed( [ "X" ], store )          is False      # self-cycle never store-backed
    # persona-kind ref → direct edge; unresolvable item ref → omitted.
    owed2 = {
        "Sam": [ { "id": "s1", "blocked_by": [ { "kind": "persona", "id": "Dot" },
                                               { "kind": "item",    "id": "missing" },
                                               { "kind": "user",    "id": "Rick" } ] } ],
    }
    assert build_store_wait_edges( owed2 ) == { "sam": { "dot" } }
    assert build_store_wait_edges( None ) == { } and build_store_wait_edges( "x" ) == { }
    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"dependency_graph smoke: {'PASS' if ok else 'FAIL'}" )
