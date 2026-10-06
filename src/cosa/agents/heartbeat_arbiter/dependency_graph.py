#!/usr/bin/env python3
"""
Heartbeat Arbiter dependency-graph cycle detection (pure).

The arbiter builds a who-waits-on-whom graph from each session view's `holding_on: peer:X`
edge and detects cycles, which are deadlocks (A→B→A). A deadlock is a ring of sessions each
blocked on the next, which no member can break. The arbiter escalates it to the user and never
breaks one itself.

Pure and never raises. The consumer passes the fleet_view (from
fleet_data_model.build_fleet_view) and acts on the graph.

Design: src/rnd/v0.1.8/2026.06.04-heartbeat-hook/03-arbiter-design.md (arbiter design, cycle detection).

Store corroboration: the `holding_on: peer:X` edges are self-reported and view-derived. A fresh,
progressing sequencing wait (one session awaiting another's merge and build) reports a ring that
is not a deadlock. That ring false-escalated on every poll. So escalation is gated on an
authoritative store dependency ring (build_store_wait_edges and cycle_is_store_backed). A derived
persona ring fires only when real store `blocked_by` edges (owner to owner) back it. A
pure-coordination ring is out of scope: two managers awaiting each other with zero store rows.
It is rare and a human breaks it anyway. The fix is for managers to express real waits as store
`blocked_by`, so the gate is a hygiene forcing function, not a gap.

Staleness filter: the `holding_on: peer:X` edge comes from the most recent heartbeat `awaiting`
field. When the declaring session's hold goes dead (expired, work_owed false, or past
next_chase), the lingering `awaiting` still produced a phantom peer edge. That edge fed the
manager-blocking advisory and any other edge consumer, with no store `blocked_by` backing.
`hold_is_stale` is the pure predicate, over three staleness axes. `build_wait_edges` and
`build_graph` accept an optional `stale_holders` set whose members contribute zero edges. The
filter is additive and sits upstream of all edge inference, so the deadlock logic
(build_store_wait_edges, cycle_is_store_backed, the escalation) is unchanged. A dead holder
removed from `edges` is also absent from `cycles`; it was never store-backed anyway. The hold
read lives in the arbiter orchestrator seam (ArbiterConsumerJob._stale_hold_holders), so this
leaf stays pure.
"""
import datetime
import re

from lupin_mcp.persona_normalization import canonical_persona_key
# Staleness primitives REUSED (no reinvention) — the single source of truth for
# the hold freshness window (held_at + ttl_seconds) and the declared work_owed flag.
from lupin_cli.claude_code.hooks.lib.heartbeat_hold import is_fresh, declared_work_owed

PEER_PREFIX = "peer:"

# A peer reference is "peer:<persona>". The <persona> token may legitimately carry
# single internal spaces ("mr radio") and hyphens-without-spaces ("cc-author-mr-radio-1"),
# but a heartbeat `awaiting` field is FREE-FORM and routinely carries either a
# MULTI-peer list ("peer:Krishna,peer:maria") or a PROSE tail
# ("peer:krishna — Krishna's FOLLOW-ON SHA ..."). Only the FIRST canonical persona
# token may mint a wait-edge; the list tail and prose MUST be dropped. Splitting on
# a comma / semicolon / open-paren / space-delimited dash isolates the first token
# while preserving a persona's own internal spaces and bare hyphens.
_PEER_PROSE_DELIMITERS = re.compile( r"[,;(]|\s[—–-]\s" )

# task 70be69f2 (b39562e4 follow-on): a MIS-PREFIXED awaiting like "peer:user:rick"
# leaves a NON-peer scheme prefix on the first parsed token — its TRUE awaited
# target is a user / gate / commons-topic, NOT a peer persona, so it must mint ZERO
# blocking edge (else the arbiter pings a non-existent "user:rick" peer → a phantom
# "X blocking Y" advisory + a 422 push_unavailable). NARROW by design (Tiberius's
# fork-2 ruling): only a token that is ITSELF a non-peer scheme is dropped — a
# legitimate MULTI-target peer wait ("peer:Tiberius,user:rick") still parses to its
# genuine first peer (Tiberius) and keeps its edge. Schema schemes per
# heartbeat_hold.awaiting: "user:" / "gate:" / "commons:".
_NON_PEER_SCHEME_PREFIXES = ( "user:", "gate:", "commons:" )


def _parse_peer_target( holding_on ):
    """
    Extract the single canonical awaited persona from a `peer:` holding string.

    Without this, a prose or list tail would be swallowed whole into a garbage awaited persona.
    That mints a phantom blocking edge and a 422 push_unavailable.

    Requires:
        - holding_on is a string beginning with PEER_PREFIX

    Ensures:
        - returns the first canonical persona token — internal single spaces and
          bare hyphens preserved ("mr radio", "cc-author-mr-radio-1") — with any
          multi-peer list tail (after a comma/semicolon) and any prose tail (after
          an open-paren or a space-delimited em/en/hyphen dash) stripped
        - returns None when no non-empty persona remains (pure prose / empty body)
        - returns None when the first token is itself a non-peer scheme reference
          (a mis-prefixed "peer:user:rick" / "peer:gate:x" /
          "peer:commons:t" — case-insensitive — names a user/gate/commons target,
          not a peer persona, so it mints no blocking edge). A legitimate
          multi-target peer wait ("peer:Tiberius,user:rick") is unaffected — its
          first token "Tiberius" is a genuine peer and its edge survives.
        - never raises (pure string op)

    Known limit: a holder awaiting multiple peers ("peer:A,peer:B") mints an edge only for the
    first peer. That is a strict improvement over the earlier garbage edge. It is enough because
    the deadlock escalation is separately gated on store `blocked_by`. Modelling every peer of
    a multi-await holder is a possible follow-on.
    """
    body  = holding_on[ len( PEER_PREFIX ): ]
    first = _PEER_PROSE_DELIMITERS.split( body, maxsplit=1 )[ 0 ].strip()
    if not first:
        return None
    if first.lower().startswith( _NON_PEER_SCHEME_PREFIXES ):   # task 70be69f2: user/gate/commons target → no peer edge
        return None
    return first


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
    Return True when a declared hold is dead and must contribute no inferred edges.

    A dead hold's `holding_on: peer:X` wait edge is a phantom, because the session has expired,
    finished or handed off its wait. The three staleness axes are listed under Ensures.

    Requires:
        - hold is a dict or None; now is an aware datetime

    Ensures:
        - returns False for a missing / non-dict hold (absence of a hold is not
          evidence of a dead hold — never over-filter a session that simply has no
          hold; the filter only subtracts edges for a readable dead hold)
        - returns True iff the hold is expired, explicitly not-work-owed, or
          past-next-chase; otherwise False
        - expired: not is_fresh( hold, now ), meaning now - held_at >= ttl_seconds. It also
          fires on an uncredible held_at or non-numeric ttl: a hold that cannot prove
          freshness is suppressed, matching the deadlock detector's documented fail-suppress bias
        - not-work-owed: declared_work_owed( hold ) is False. An explicit False means the
          session is done, so never a real wait; None or absent is not stale
        - past-next-chase: an optional `next_chase` ISO timestamp is present, parseable and
          <= now (forward-compatible; holds do not emit it today)
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


def hold_contradicts_peer_edge( hold, holding_on, now ):
    """
    Return True when a fresh hold's declared `awaiting` contradicts the derived peer edge.

    Complement to `hold_is_stale`: that drops a dead-hold holder, this drops a fresh holder
    whose hold contradicts the edge. The arbiter merges both into one subtraction set.
    Additive and fail-safe.

    Requires:
        - hold is a dict or None; holding_on is the view's holding_on (any type);
          now is an aware datetime

    Ensures:
        - returns True iff all hold:
            * hold is a readable dict, and
            * holding_on is a `peer:` string naming a parseable peer (the only edge
              kind that mints a wait-edge), and
            * the hold is fresh (is_fresh — only a fresh hold's `awaiting` is
              authoritative; a dead hold is hold_is_stale's axis, never double-
              classified here), and
            * the hold carries an explicit string `awaiting` field, and
            * that `awaiting` does not (canonically) name the same peer as
              holding_on — i.e. it is "none", a non-peer scheme, or a different peer
        - returns False otherwise — in particular fail-safe (keep the edge) for a
          missing/non-dict hold, a non-peer/unparseable holding_on, a non-fresh
          hold, an absent/non-string `awaiting` (no authoritative declaration), or
          an `awaiting` that canonically matches the edge peer (a genuine wait)
        - the phantom it removes: a holder whose current hold is fresh and honored with
          `awaiting="none"` (or a different peer), while its `holding_on` edge came from a stale
          `last_activity.awaiting="peer:X"`. That heartbeat record outlived the wait it described.
          `hold_is_stale` does not fire on a fresh hold, so the edge would stay and the arbiter
          would loop-fire a phantom "X is blocking worker Y". The hold's declared `awaiting` is
          authoritative over the stale record, so such a holder contributes zero edges
        - never raises (pure)
    """
    if not hold or not isinstance( hold, dict ):
        return False
    if not isinstance( holding_on, str ) or not holding_on.startswith( PEER_PREFIX ):
        return False
    edge_peer = _parse_peer_target( holding_on )
    if edge_peer is None:
        return False                                         # unparseable peer → no edge minted anyway
    if not is_fresh( hold, now=now ):
        return False                                         # only a FRESH hold's awaiting is authoritative
    awaiting = hold.get( "awaiting" )
    if not isinstance( awaiting, str ):
        return False                                         # no authoritative declaration → fail-SAFE keep
    declared = _parse_peer_target( awaiting ) if awaiting.startswith( PEER_PREFIX ) else None
    if declared is not None and ( canonical_persona_key( declared ) or declared ) == ( canonical_persona_key( edge_peer ) or edge_peer ):
        return False                                         # hold corroborates the edge → genuine wait
    return True                                              # hold declares it is NOT awaiting edge_peer → phantom


def session_is_stale( view, now, alive_threshold_seconds ):
    """
    Return True when a holder session's last activity is older than the alive threshold.

    Complement to `hold_is_stale` and `hold_contradicts_peer_edge`. Those read the per-session
    hold artifact; this reads the per-session last-activity timestamp the view already carries.
    All three only subtract edges, and are additive and fail-safe.

    Requires:
        - view is a fleet-view row dict (any type tolerated); now is an aware
          datetime; alive_threshold_seconds is a positive number
        - `view['last_activity_ts']` (when present) is the session's most-recent
          liveness ts (a datetime, or an ISO string — tolerated/parsed)

    Ensures:
        - returns True iff the view's `last_activity_ts` is present, parseable, and
          its age (now − ts) is strictly greater than alive_threshold_seconds
        - returns False — fail-safe, keep the edge — for a non-dict view, a missing
          now / alive_threshold (the additive default: no gate when un-threaded), a
          missing / None / unparseable `last_activity_ts` (absence of a usable ts is
          not evidence of deadness — never over-filter), or a future/within-window ts
        - decided explicitly from the ts (not `view['alive']`, which reads False for
          an unparseable ts and would over-filter)
        - the phantom it closes: a dead session's lingering `holding_on: peer:X` edge survives
          the consumer's per-persona `alive` filter, because a live session sharing the persona
          keeps that persona alive, so the dead session's wait is attributed to the live persona.
          The gate therefore uses the holder session's own freshness, decided per session id and
          never collapsed to persona liveness
        - never raises (pure)
    """
    if not isinstance( view, dict ) or now is None or alive_threshold_seconds is None:
        return False
    ts = view.get( "last_activity_ts" )
    if isinstance( ts, str ):
        ts = _parse_iso( ts )
    if not isinstance( ts, datetime.datetime ):
        return False                                         # no usable ts → fail-SAFE keep
    try:
        age = ( now - ts ).total_seconds()
    except ( TypeError, AttributeError ):
        return False                                         # unusable now/ts → fail-SAFE keep
    return age > alive_threshold_seconds


def build_wait_edges( fleet_view, stale_holders=None, now=None, alive_threshold_seconds=None ):
    """
    Extract holder→awaited-peer edges from the fleet view.

    Requires:
        - fleet_view is a dict { session_id: view } (build_fleet_view output);
          each view carries "persona", "holding_on" (e.g. "peer:Sam", "user:Rick",
          "commons:foo", "none") and "last_activity_ts"
        - stale_holders is a set/collection of holder personas whose hold is dead
          — their peer edge is dropped at ingestion — or None
          (meaning no persona filtering, byte-identical to the prior behavior)
        - now / alive_threshold_seconds gate the per-session freshness filter: both
          None (the default) means no session-freshness gate, byte-identical to the prior
          behavior — this keeps the unfiltered escalation feed
          `find_deadlock_cycles( build_wait_edges( fleet_view ) )`
          untouched (it passes neither, so no session is dropped)

    Ensures:
        - Returns dict { holder_persona: awaited_persona } for only peer:* edges
          with a non-empty holder and a non-empty awaited persona
        - the awaited persona is the first canonical token from the peer string
          (`_parse_peer_target`): a multi-peer list tail or free
          prose after the first persona is dropped, so a free-form `awaiting`
          field can no longer mint a garbage/phantom edge
        - a beyond-threshold session (`session_is_stale`) contributes zero edges —
          dropped per session-id at ingestion, before the holder→persona collapse,
          so a dead session never poisons a live same-persona session
        - a holder in `stale_holders` contributes zero edges (its dead hold's
          phantom wait-edge is filtered out upstream of all edge inference)
        - last edge wins if a holder appears twice (functional graph)
        - Non-dict views are skipped; never raises
    """
    stale = stale_holders or set()
    edges = { }
    for view in fleet_view.values():
        if not isinstance( view, dict ):
            continue
        if session_is_stale( view, now, alive_threshold_seconds ):   # 8a450183: dead SESSION → zero edges (per session-id, pre-collapse)
            continue
        holder     = view.get( "persona" )
        holding_on = view.get( "holding_on" )
        if not holder or not isinstance( holding_on, str ) or not holding_on.startswith( PEER_PREFIX ):
            continue
        if holder in stale:                                  # bc1bc373: dead hold → zero edges
            continue
        awaited = _parse_peer_target( holding_on )           # b39562e4: first canonical peer only (drop list/prose tail)
        if awaited:
            edges[ holder ] = awaited
    return edges


def _canonicalize( cycle ):
    """
    Rotate a cycle so its lexicographically smallest node comes first.

    The same ring is then reported identically whatever node the walk started from.
    """
    pivot = cycle.index( min( cycle ) )
    return cycle[ pivot: ] + cycle[ :pivot ]


def find_deadlock_cycles( wait_edges ):
    """
    Detect all deadlock cycles in the functional wait-graph.

    Each holder awaits at most one peer (out-degree ≤ 1), so cycles are disjoint. Walk each
    unvisited node forward until the chain ends, re-enters visited territory, or loops into
    its own path (a new cycle).

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


def build_graph( fleet_view, stale_holders=None, now=None, alive_threshold_seconds=None ):
    """
    Build the dependency graph + deadlock cycles from the fleet view.

    Requires:
        - fleet_view is a dict { session_id: view }
        - stale_holders is a set of dead-hold holder personas whose
          peer edge is dropped, or None (meaning no persona filtering)
        - now / alive_threshold_seconds gate the per-session freshness filter —
          passed straight through to build_wait_edges; both None
          (the default) means no session-freshness gate (byte-identical prior behavior)

    Ensures:
        - Returns { "edges": {holder: awaited}, "cycles": [canonical cycles] }
        - a holder in `stale_holders`, and a beyond-threshold session when
          now/threshold are supplied, are absent from both edges and cycles (each
          contributes zero inferred edges to every consumer of this filtered graph);
          the deadlock logic downstream is unchanged — it simply sees fewer rings
        - Never raises
    """
    edges = build_wait_edges( fleet_view, stale_holders=stale_holders,
                              now=now, alive_threshold_seconds=alive_threshold_seconds )
    return { "edges": edges, "cycles": find_deadlock_cycles( edges ) }


def build_store_wait_edges( owed_by_persona ):
    """
    Build authoritative owner→owner wait edges from store `blocked_by` refs.

    The store's answer to "who is really blocked on whom". It is the counterpart to the
    self-reported build_wait_edges. cycle_is_store_backed uses it to corroborate a derived
    deadlock ring before the arbiter escalates it.

    Requires:
        - owed_by_persona is the arbiter's per-poll non-terminal owed read,
          { persona: [ { id, status, gate_class, blocked_by }, ... ] } (the
          _default_owed_work_fn / _classify_owed shape), or None

    `blocked_by` is a list of typed refs { "kind": "item"|"persona"|"user",
    "id": ... }:
        - persona-kind → a direct owner edge holder→canonical(id).
        - item-kind    → resolved to the owner of that task-id via an id→owner
          map built from the same owed read. A blocking task that is terminal or
          owned by a persona outside this poll's read is unresolvable → that edge
          is omitted, biasing toward not firing (the documented v1 scope limit).
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


def build_store_blocked_item_index( owed_by_persona ):
    """
    Map each owner→owner wait edge to the set of the holder's blocked task ids.

    Companion to build_store_wait_edges: it keeps which task items are blocked, which that
    function drops. The Ensures list says why the blocker-cc idempotency key needs them.

    Requires:
        - owed_by_persona is the arbiter's per-poll non-terminal owed read,
          { persona: [ { id, status, gate_class, blocked_by }, ... ] }, or None
          (same shape build_store_wait_edges consumes)

    Ensures:
        - returns { ( canonical_holder, canonical_awaited ): frozenset( item_ids ) }
          where item_ids are str ids of the holder's items whose blocked_by
          resolves to `awaited` (item-kind refs resolved to owner via the same
          id→owner map; unresolvable/terminal-owner refs omitted, mirroring
          build_store_wait_edges' v1 scope limit)
        - self-edges dropped (a holder blocked on its own item is not a peer edge)
        - personas are canonical_persona_key-normalized so lookups match the
          (canonicalized) ping-edge keys
        - why the items are kept: build_store_wait_edges collapses each (holder, awaited) edge
          to a bare persona pair. The blocker-cc idempotency key (blocker, blocked_item,
          recipient) needs the blocked_item leg. Two sequential blocks with the same
          (blocker, blocked_worker, recipient) but different blocked items are distinct
          announcements, and each must go out once rather than be suppressed as a duplicate
        - None / malformed input → {}; never raises (pure)
    """
    owed = owed_by_persona or { }
    if not isinstance( owed, dict ):
        return { }
    id_to_owner = { }
    for persona, items in owed.items():
        if not isinstance( items, list ):
            continue
        owner = canonical_persona_key( persona ) or persona
        for it in items:
            if isinstance( it, dict ) and it.get( "id" ) is not None:
                id_to_owner[ str( it.get( "id" ) ) ] = owner
    index = { }
    for persona, items in owed.items():
        if not isinstance( items, list ):
            continue
        holder = canonical_persona_key( persona ) or persona
        for it in items:
            if not isinstance( it, dict ) or it.get( "id" ) is None:
                continue
            item_id = str( it.get( "id" ) )
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
                    index.setdefault( ( holder, awaited ), set() ).add( item_id )
    return { edge: frozenset( ids ) for edge, ids in index.items() }


def cycle_is_store_backed( cycle, store_edges ):
    """
    Return True iff every ring edge of a derived persona cycle is backed by the store.

    Each consecutive holder→awaited edge must match an authoritative store owner-edge
    (build_store_wait_edges).

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


def edge_is_store_backed( holder, awaited, store_edges ):
    """
    Return True iff a single derived holder→awaited edge is backed by the store.

    The single-edge analog of `cycle_is_store_backed`. It gates the blocking-obligation
    advisory on authoritative store backing.

    Requires:
        - holder / awaited are view-persona strings (any type tolerated)
        - store_edges is build_store_wait_edges output { holder: set(awaited) }

    Ensures:
        - returns True iff canonical(awaited) is in store_edges[ canonical(holder) ]
          (personas compared canonically, mirroring cycle_is_store_backed — both
          sides share the view-persona spelling, so this is consistent)
        - returns False for a falsy holder/awaited or a non-dict store_edges
          (fail-suppress: no authoritative backing means not a real blocker). The
          caller decides separately what to do when the store is unknown (the read
          failed); it only consults this gate when it has an authoritative store read
        - why the gate exists: the "You're blocking worker Y" advisory is minted from the
          waiter's self-reported `holding_on: peer:X`. It asserts "X is blocking Y" purely
          because Y says it awaits X, with no check that X owes Y anything. A holder whose
          wait is already discharged (the awaited peer delivered, or owes nothing) would keep
          pinging the innocent peer every poll. The store `blocked_by` graph is the
          authoritative record of who owes whom, so gating on it fires only when Y's store
          item is really blocked_by X
        - never raises (pure)
    """
    if not holder or not awaited or not isinstance( store_edges, dict ):
        return False
    h = canonical_persona_key( holder )  or holder
    a = canonical_persona_key( awaited ) or awaited
    return a in store_edges.get( h, set() )


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
    # B3 backing-obligation gate (d44b7068): single-edge store corroboration.
    assert edge_is_store_backed( "Ann", "Bob", store ) is True            # canonical match → real blocker
    assert edge_is_store_backed( "Ann", "Eve", store ) is False           # not backed → phantom
    assert edge_is_store_backed( "",    "Bob", store ) is False           # falsy holder
    assert edge_is_store_backed( "Ann", "Bob", None )  is False           # non-dict store_edges
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
