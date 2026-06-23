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

STALENESS-FILTER (bug bc1bc373, 2026-06-23): the `holding_on: peer:X` edge is
SELF-REPORTED from the most-recent heartbeat `awaiting` field. When the declaring
session's HOLD goes DEAD (expired / work_owed=false / past next_chase), the
lingering `awaiting` still produced a phantom peer edge that fed the
manager-blocking advisory ("mr radio blocking Tiffany") and any other edge
consumer with NO store `blocked_by` backing. `hold_is_stale` is the PURE predicate
(three staleness axes); `build_wait_edges`/`build_graph` accept an OPTIONAL
`stale_holders` set whose members contribute ZERO edges. This is ADDITIVE and
UPSTREAM of all edge inference — the deployed deadlock LOGIC (build_store_wait_edges
+ cycle_is_store_backed + the escalation) is byte-identical; a dead holder removed
from `edges` is simply also absent from `cycles` (it was never store-backed
anyway). The hold READ lives in the arbiter orchestrator seam
(ArbiterConsumerJob._stale_hold_holders); this leaf stays pure.
"""
import datetime

from lupin_mcp.persona_normalization import canonical_persona_key
# Staleness primitives REUSED (no reinvention) — the single source of truth for
# the hold freshness window (held_at + ttl_seconds) and the declared work_owed flag.
from lupin_cli.claude_code.hooks.lib.heartbeat_hold import is_fresh, declared_work_owed

PEER_PREFIX = "peer:"


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


def hold_is_stale( hold, now ):
    """
    Is this declared hold DEAD for edge-inference purposes (bug bc1bc373)?

    A DEAD hold must contribute ZERO inferred edges — its `holding_on: peer:X`
    wait-edge is a phantom (the session has expired/finished/handed-off its wait).
    A hold is STALE on ANY of three axes:
      - EXPIRED         : not is_fresh( hold, now ) — now − held_at ≥ ttl_seconds
                          (also fires on an uncredible held_at / non-numeric ttl,
                          a hold that cannot prove freshness → bias-to-suppress,
                          matching the deadlock detector's documented fail-SUPPRESS)
      - NOT-WORK-OWED   : declared_work_owed( hold ) is False (explicit False ⇒ the
                          session is done ⇒ never a real wait; None/absent ≠ stale)
      - PAST-NEXT-CHASE : an optional `next_chase` ISO ts is present, parseable, and
                          ≤ now (forward-compatible — holds don't emit it today)

    Requires:
        - hold is a dict or None; now is an aware datetime

    Ensures:
        - returns False for a missing / non-dict hold (absence of a hold is NOT
          evidence of a dead hold — never over-filter a session that simply has no
          hold; the filter only SUBTRACTS edges for a readable DEAD hold)
        - returns True iff the hold is EXPIRED, explicitly NOT-WORK-OWED, or
          PAST-NEXT-CHASE; otherwise False
        - never raises
    """
    if not hold or not isinstance( hold, dict ):
        return False
    if not is_fresh( hold, now=now ):
        return True
    if declared_work_owed( hold ) is False:
        return True
    next_chase = _parse_iso( hold.get( "next_chase" ) )
    if next_chase is not None and next_chase <= now:
        return True
    return False


def build_wait_edges( fleet_view, stale_holders=None ):
    """
    Extract holder→awaited-peer edges from the fleet view.

    Requires:
        - fleet_view is a dict { session_id: VIEW } (build_fleet_view output);
          each VIEW carries "persona" and "holding_on" (e.g. "peer:Sam",
          "user:Rick", "commons:foo", "none")
        - stale_holders is a set/collection of holder PERSONAS whose hold is DEAD
          (bug bc1bc373) — their peer edge is dropped at ingestion — or None
          (⇒ no filtering, byte-identical to the prior behavior)

    Ensures:
        - Returns dict { holder_persona: awaited_persona } for ONLY peer:* edges
          with a non-empty holder AND a non-empty awaited persona
        - a holder in `stale_holders` contributes ZERO edges (its dead hold's
          phantom wait-edge is filtered out UPSTREAM of all edge inference)
        - LAST edge wins if a holder appears twice (functional graph)
        - Non-dict views are skipped; never raises
    """
    stale = stale_holders or set()
    edges = { }
    for view in fleet_view.values():
        if not isinstance( view, dict ):
            continue
        holder     = view.get( "persona" )
        holding_on = view.get( "holding_on" )
        if not holder or not isinstance( holding_on, str ) or not holding_on.startswith( PEER_PREFIX ):
            continue
        if holder in stale:                                  # bc1bc373: dead hold → zero edges
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


def build_graph( fleet_view, stale_holders=None ):
    """
    Build the dependency graph + deadlock cycles from the fleet view.

    Requires:
        - fleet_view is a dict { session_id: VIEW }
        - stale_holders is a set of dead-hold holder personas (bug bc1bc373) whose
          peer edge is dropped, or None (⇒ no filtering)

    Ensures:
        - Returns { "edges": {holder: awaited}, "cycles": [canonical cycles] }
        - a holder in `stale_holders` is absent from BOTH edges and cycles (the
          dead hold contributes ZERO inferred edges to every consumer); the
          deadlock LOGIC downstream is unchanged — it simply sees fewer rings
        - Never raises
    """
    edges = build_wait_edges( fleet_view, stale_holders=stale_holders )
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

    # staleness-filter (bug bc1bc373): a dead holder contributes ZERO edges.
    now_dt = datetime.datetime( 2026, 6, 23, 12, 0, 0, tzinfo=datetime.timezone.utc )
    fresh_held = ( now_dt - datetime.timedelta( seconds=10 ) ).isoformat()
    expired_held = ( now_dt - datetime.timedelta( seconds=10_000 ) ).isoformat()
    live_hold = { "held_at": fresh_held, "ttl_seconds": 900, "work_owed": True, "reason": "waiting" }
    assert hold_is_stale( None, now_dt ) is False and hold_is_stale( "x", now_dt ) is False
    assert hold_is_stale( live_hold, now_dt ) is False
    assert hold_is_stale( { **live_hold, "held_at": expired_held }, now_dt ) is True       # EXPIRED
    assert hold_is_stale( { **live_hold, "work_owed": False }, now_dt ) is True             # NOT-WORK-OWED
    assert hold_is_stale( { **live_hold, "next_chase": fresh_held }, now_dt ) is True       # PAST-NEXT-CHASE
    # edge filter: Ann's dead hold drops her edge; Bob's live edge stays.
    fv2 = { "a": { "persona": "Ann", "holding_on": "peer:Bob" },
            "b": { "persona": "Bob", "holding_on": "peer:Ann" } }
    assert build_wait_edges( fv2, stale_holders={ "Ann" } ) == { "Bob": "Ann" }
    assert build_graph( fv2, stale_holders={ "Ann", "Bob" } )[ "cycles" ] == [ ]
    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"dependency_graph smoke: {'PASS' if ok else 'FAIL'}" )
