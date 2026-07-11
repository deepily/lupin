#!/usr/bin/env python3
"""
Unit tests for the heartbeat-arbiter dependency graph (pure).

Covers the derived wait-edge / cycle detection AND the bug-436a366b
STORE-CORROBORATION helpers (build_store_wait_edges + cycle_is_store_backed)
that gate the deadlock escalation against an authoritative store dependency
ring instead of the self-reported holding_on edges.
"""
import os
import sys

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import datetime

import pytest

from cosa.agents.heartbeat_arbiter.dependency_graph import (
    build_wait_edges, find_deadlock_cycles, build_graph,
    build_store_wait_edges, build_store_blocked_item_index,
    cycle_is_store_backed, hold_is_stale, quick_smoke_test,
    hold_contradicts_peer_edge, session_is_stale,
    _parse_peer_target,
)


_NOW = datetime.datetime( 2026, 6, 23, 12, 0, 0, tzinfo=datetime.timezone.utc )


def _hold( seconds_ago_held=10, ttl=900, work_owed=True, **extra ):
    """A live, honored, work-owed hold by default; override per axis."""
    held_at = ( _NOW - datetime.timedelta( seconds=seconds_ago_held ) ).isoformat()
    h = { "held_at": held_at, "ttl_seconds": ttl, "work_owed": work_owed, "reason": "waiting" }
    h.update( extra )
    return h


# ── derived wait edges (holding_on: peer:X) ─────────────────────────────────────

class TestBuildWaitEdges:
    def test_peer_edges_only_with_skips_and_last_wins( self ):
        fleet = {
            "s1": { "persona": "Ann", "holding_on": "peer:Bob" },
            "s2": { "persona": "Cal", "holding_on": "user:Rick" },   # not a peer edge → skipped
            "s3": { "persona": "Dan", "holding_on": "peer:"    },    # empty awaited → skipped
            "s4": { "persona": "",    "holding_on": "peer:Bob" },    # no holder → skipped
            "s5": { "persona": "Eve", "holding_on": 123        },    # non-str holding_on → skipped
            "s6": "not-a-dict",                                      # non-dict view → skipped
            "s7": { "persona": "Ann", "holding_on": "peer:Zed" },    # last edge for Ann wins
        }
        assert build_wait_edges( fleet ) == { "Ann": "Zed" }

    def test_empty_view( self ):
        assert build_wait_edges( { } ) == { }

    def test_prose_and_list_awaiting_do_not_mint_garbage_edges( self ):
        # bug b39562e4: a free-form `awaiting` (prose tail / multi-peer list) used
        # to be swallowed whole into a garbage awaited-persona → phantom blocking
        # edge + 422 push_unavailable. Now only the FIRST canonical peer survives.
        fleet = {
            "s1": { "persona": "mr radio", "holding_on": "peer:krishna — Krishna's FOLLOW-ON SHA for the fix" },
            "s2": { "persona": "maria",    "holding_on": "peer:Krishna,peer:tiberius" },
            "s3": { "persona": "Sam",      "holding_on": "peer:cc-author-mr-radio-1" },   # bare hyphens kept
        }
        assert build_wait_edges( fleet ) == {
            "mr radio": "krishna",          # prose tail dropped
            "maria"   : "Krishna",          # only the first peer of the list
            "Sam"     : "cc-author-mr-radio-1",
        }

    def test_mis_prefixed_user_gate_target_mints_no_edge( self ):
        # task 70be69f2 fork-2(a): a `peer:`-prefixed holding whose parsed token is
        # itself a user/gate/commons scheme reference (a mis-prefix) has its TRUE
        # awaited target a user/gate — NOT a peer — so it mints ZERO blocking edge.
        # A legitimate multi-target peer wait ("peer:Tiberius,user:rick") is
        # UNAFFECTED: its first token is a genuine peer and its edge survives.
        fleet = {
            "s1": { "persona": "mr radio", "holding_on": "peer:user:rick" },        # user mis-prefix → dropped
            "s2": { "persona": "tiffany",  "holding_on": "peer:gate:operator" },    # gate mis-prefix → dropped
            "s3": { "persona": "krishna",  "holding_on": "peer:commons:fleet" },    # commons mis-prefix → dropped
            "s4": { "persona": "mr radio", "holding_on": "peer:Tiberius,user:rick" },  # legit peer KEPT
        }
        assert build_wait_edges( fleet ) == { "mr radio": "Tiberius" }


# ── peer-target parse (bug b39562e4) ────────────────────────────────────────────

class TestParsePeerTarget:
    @pytest.mark.parametrize( "holding_on, expected", [
        ( "peer:krishna",                               "krishna" ),                # plain
        ( "peer:mr radio",                              "mr radio" ),               # internal space preserved
        ( "peer:cc-author-mr-radio-1",                  "cc-author-mr-radio-1" ),   # bare hyphens preserved
        ( "peer:Krishna,peer:maria",                    "Krishna" ),                # comma list → first
        ( "peer:a;peer:b",                              "a" ),                      # semicolon list → first
        ( "peer:maria (Lane B handoff)",               "maria" ),                  # paren prose dropped
        ( "peer:krishna — long em-dash prose tail",     "krishna" ),                # em-dash prose dropped
        ( "peer:rio – en-dash prose",                   "rio" ),                    # en-dash prose dropped
        ( "peer:bob - hyphen-with-spaces prose",        "bob" ),                    # spaced hyphen = prose
        ( "peer:  spacey  ",                            "spacey" ),                 # surrounding ws stripped
        ( "peer:",                                      None ),                     # empty body
        ( "peer: — pure prose",                         None ),                     # nothing before delimiter
        # task 70be69f2 fork-2(a): a MIS-PREFIXED token that is itself a non-peer
        # scheme (user/gate/commons) names a user/gate target, NOT a peer persona
        # → no edge (else the arbiter pings a phantom "user:rick" peer + 422s).
        ( "peer:user:rick",                             None ),                     # user mis-prefix dropped
        ( "peer:gate:ricks-court",                      None ),                     # gate mis-prefix dropped
        ( "peer:commons:fleet-arbiter",                 None ),                     # commons mis-prefix dropped
        ( "peer:USER:Rick",                             None ),                     # scheme match is case-insensitive
        ( "peer:user:rick,peer:bob",                    None ),                     # mis-prefix is the FIRST token → dropped before the list tail
        # NON-REGRESSION (the narrow ruling): a LEGIT multi-target peer wait keeps
        # its genuine first peer — the user-tail is dropped by the list split, not
        # the scheme guard, so the peer edge survives.
        ( "peer:Tiberius,user:rick",                    "Tiberius" ),               # legit peer kept (user tail dropped)
        ( "peer:user",                                  "user" ),                   # bare "user" w/o colon is a (odd) persona, NOT a scheme → kept
    ] )
    def test_first_canonical_token_only( self, holding_on, expected ):
        assert _parse_peer_target( holding_on ) == expected


# ── cycle detection ─────────────────────────────────────────────────────────────

class TestFindDeadlockCycles:
    def test_two_cycle_canonicalized_and_visited_skip( self ):
        # Walk may start at "B"; the cycle is canonicalized to start at min ("A"),
        # and the second loop iteration (start="A") is already visited → skipped.
        cycles = find_deadlock_cycles( { "B": "A", "A": "B" } )
        assert cycles == [ [ "A", "B" ] ]

    def test_self_loop_and_acyclic_and_empty( self ):
        assert find_deadlock_cycles( { "X": "X" } )        == [ [ "X" ] ]   # self-deadlock
        assert find_deadlock_cycles( { "P": "Q" } )        == [ ]           # acyclic chain (Q has no edge)
        assert find_deadlock_cycles( { } )                 == [ ]

    def test_build_graph_round_trip( self ):
        fleet = { "s1": { "persona": "Ann", "holding_on": "peer:Bob" },
                  "s2": { "persona": "Bob", "holding_on": "peer:Ann" } }
        graph = build_graph( fleet )
        assert graph == { "edges": { "Ann": "Bob", "Bob": "Ann" }, "cycles": [ [ "Ann", "Bob" ] ] }


# ── STORE-CORROBORATION: owner-ring edges from blocked_by (bug 436a366b) ─────────

class TestBuildStoreWaitEdges:
    def test_item_kind_resolved_to_owner_ring( self ):
        owed = {
            "Ann": [ { "id": "t1", "blocked_by": [ { "kind": "item", "id": "t2" } ] } ],
            "Bob": [ { "id": "t2", "blocked_by": [ { "kind": "item", "id": "t1" } ] } ],
        }
        assert build_store_wait_edges( owed ) == { "ann": { "bob" }, "bob": { "ann" } }

    def test_persona_kind_direct_user_ignored_unresolvable_item_omitted( self ):
        owed = {
            "Sam": [ { "id": "s1", "blocked_by": [
                { "kind": "persona", "id": "Dot" },        # direct owner edge
                { "kind": "persona", "id": 999 },          # non-str persona id → ignored
                { "kind": "item",    "id": "missing" },    # unresolvable item → omitted
                { "kind": "item",    "id": None },         # item id None → skipped
                { "kind": "user",    "id": "Rick" },       # user gate → ignored
                "not-a-dict",                              # malformed ref → skipped
            ] } ],
        }
        assert build_store_wait_edges( owed ) == { "sam": { "dot" } }

    def test_self_edge_dropped_and_non_list_non_dict_skipped( self ):
        owed = {
            "Ann": [ { "id": "t1", "blocked_by": [ { "kind": "item", "id": "t1" } ] } ],  # own item → self-edge dropped
            "Bob": "not-a-list",                                                          # non-list items → skipped
            "Cal": [ "not-a-dict", { "id": None } ],                                      # non-dict item + id None
        }
        assert build_store_wait_edges( owed ) == { }

    def test_none_and_non_dict_input( self ):
        assert build_store_wait_edges( None ) == { }
        assert build_store_wait_edges( "x" )  == { }
        assert build_store_wait_edges( { } )  == { }

    def test_item_without_blocked_by_makes_no_edge( self ):
        owed = { "Ann": [ { "id": "t1", "status": "running" } ] }   # no blocked_by key → no edge
        assert build_store_wait_edges( owed ) == { }


# ── STORE ITEM INDEX: per-edge blocked task-ids (bug ce13b134 blocker-cc key) ────

class TestBuildStoreBlockedItemIndex:
    def test_persona_kind_edge_carries_holder_item_id( self ):
        owed = {
            "Rio": [ { "id": "99399723", "blocked_by": [ { "kind": "persona", "id": "Sam" } ] } ],
        }
        assert build_store_blocked_item_index( owed ) == {
            ( "rio", "sam" ): frozenset( { "99399723" } ) }

    def test_item_kind_resolved_to_owner_edge_keeps_item_id( self ):
        owed = {
            "Ann": [ { "id": "t1", "blocked_by": [ { "kind": "item", "id": "t2" } ] } ],
            "Bob": [ { "id": "t2", "blocked_by": [ ] } ],
        }
        assert build_store_blocked_item_index( owed ) == {
            ( "ann", "bob" ): frozenset( { "t1" } ) }

    def test_two_items_same_edge_union_of_ids( self ):
        owed = {
            "Rio": [
                { "id": "A", "blocked_by": [ { "kind": "persona", "id": "Sam" } ] },
                { "id": "B", "blocked_by": [ { "kind": "persona", "id": "Sam" } ] },
            ],
        }
        assert build_store_blocked_item_index( owed ) == {
            ( "rio", "sam" ): frozenset( { "A", "B" } ) }

    def test_malformed_refs_user_and_unresolvable_omitted( self ):
        owed = {
            "Sam": [ { "id": "s1", "blocked_by": [
                { "kind": "persona", "id": "Dot" },        # kept
                { "kind": "persona", "id": 999 },          # non-str persona id → ignored
                { "kind": "item",    "id": "missing" },    # unresolvable item → omitted
                { "kind": "item",    "id": None },         # item id None → skipped
                { "kind": "user",    "id": "Rick" },       # user gate → ignored
                "not-a-dict",                              # malformed ref → skipped
            ] } ],
        }
        assert build_store_blocked_item_index( owed ) == {
            ( "sam", "dot" ): frozenset( { "s1" } ) }

    def test_self_edge_and_non_list_non_dict_and_idless_skipped( self ):
        owed = {
            "Ann": [ { "id": "t1", "blocked_by": [ { "kind": "item", "id": "t1" } ] } ],  # own item → self-edge dropped
            "Bob": "not-a-list",                                                          # non-list → skipped
            "Cal": [ "not-a-dict", { "id": None, "blocked_by": [ { "kind": "persona", "id": "Sam" } ] } ],  # non-dict + id None (no item id → skipped)
        }
        assert build_store_blocked_item_index( owed ) == { }

    def test_none_and_non_dict_input( self ):
        assert build_store_blocked_item_index( None ) == { }
        assert build_store_blocked_item_index( "x" )  == { }
        assert build_store_blocked_item_index( { } )  == { }


# ── STORE-CORROBORATION: ring corroboration predicate ───────────────────────────

class TestCycleIsStoreBacked:
    STORE = { "ann": { "bob" }, "bob": { "ann" } }

    def test_corroborated_ring_true( self ):
        assert cycle_is_store_backed( [ "Ann", "Bob" ], self.STORE ) is True

    def test_uncorroborated_ring_false( self ):
        assert cycle_is_store_backed( [ "Dan", "Eve" ], self.STORE ) is False      # neither edge in store
        assert cycle_is_store_backed( [ "Ann", "Zed" ], self.STORE ) is False      # one edge missing

    def test_self_cycle_never_store_backed_in_practice( self ):
        # build_store_wait_edges NEVER emits a self-edge, so a derived self-cycle
        # is never corroborated by a REAL store ring → a session can't peer-deadlock
        # on itself.
        owed  = { "X": [ { "id": "t1", "blocked_by": [ { "kind": "item", "id": "t1" } ] } ] }
        store = build_store_wait_edges( owed )                                      # self-edge dropped → {}
        assert store == { }
        assert cycle_is_store_backed( [ "X" ], store ) is False

    def test_empty_and_malformed_cycle_false( self ):
        assert cycle_is_store_backed( [ ], self.STORE )   is False
        assert cycle_is_store_backed( None, self.STORE )  is False
        assert cycle_is_store_backed( "AB", self.STORE )  is False                 # non-list

    def test_three_party_ring( self ):
        store = { "a": { "b" }, "b": { "c" }, "c": { "a" } }
        assert cycle_is_store_backed( [ "a", "b", "c" ], store ) is True
        store_broken = { "a": { "b" }, "b": { "c" } }                              # c→a missing
        assert cycle_is_store_backed( [ "a", "b", "c" ], store_broken ) is False


# ── STALENESS-FILTER: hold_is_stale predicate (bug bc1bc373) ─────────────────────

class TestHoldIsStale:
    def test_missing_or_non_dict_hold_not_stale( self ):
        # absence of a hold is NOT evidence of a dead hold → never over-filter
        assert hold_is_stale( None, _NOW )  is False
        assert hold_is_stale( "x", _NOW )   is False
        assert hold_is_stale( { }, _NOW )   is False     # falsy empty dict → guarded before is_fresh
        assert hold_is_stale( 0, _NOW )     is False

    def test_live_honored_work_owed_hold_kept( self ):           # AC B.2
        assert hold_is_stale( _hold(), _NOW ) is False

    def test_expired_axis( self ):                                # AC B.1 — EXPIRED
        assert hold_is_stale( _hold( seconds_ago_held=10_000, ttl=900 ), _NOW ) is True

    def test_expired_axis_uncredible_held_at_or_ttl( self ):
        # a hold that cannot prove freshness reads stale (bias-to-suppress)
        assert hold_is_stale( _hold( held_at="not-a-date" ), _NOW ) is True   # unparseable held_at
        assert hold_is_stale( _hold( ttl="lots" ), _NOW )           is True   # non-numeric ttl
        assert hold_is_stale( _hold( ttl=True ), _NOW )             is True   # bool ttl rejected by is_fresh

    def test_not_work_owed_axis( self ):                          # AC B.1 — NOT-WORK-OWED
        assert hold_is_stale( _hold( work_owed=False ), _NOW ) is True

    def test_work_owed_none_or_absent_not_stale_on_that_axis( self ):
        # explicit False ⇒ stale; None/absent ⇒ that axis does NOT fire (still live here)
        assert hold_is_stale( _hold( work_owed=None ), _NOW ) is False
        h = _hold(); del h[ "work_owed" ]
        assert hold_is_stale( h, _NOW ) is False

    def test_past_next_chase_axis( self ):                        # AC B.1 — PAST-NEXT-CHASE
        past = ( _NOW - datetime.timedelta( seconds=5 ) ).isoformat()
        assert hold_is_stale( _hold( next_chase=past ), _NOW ) is True

    def test_future_next_chase_kept( self ):
        future = ( _NOW + datetime.timedelta( seconds=600 ) ).isoformat()
        assert hold_is_stale( _hold( next_chase=future ), _NOW ) is False

    def test_next_chase_at_now_is_stale_boundary( self ):
        assert hold_is_stale( _hold( next_chase=_NOW.isoformat() ), _NOW ) is True   # <= now

    def test_next_chase_unparseable_skips_axis( self ):
        assert hold_is_stale( _hold( next_chase="garbage" ), _NOW ) is False         # parse None → axis off

    def test_next_chase_zulu_and_naive_forms_parse( self ):
        # "Z" suffix normalized; a naive ts assumed UTC — both compare against now
        past_z     = ( _NOW - datetime.timedelta( seconds=5 ) ).isoformat().replace( "+00:00", "Z" )
        past_naive = ( _NOW - datetime.timedelta( seconds=5 ) ).replace( tzinfo=None ).isoformat()
        assert hold_is_stale( _hold( next_chase=past_z ),     _NOW ) is True
        assert hold_is_stale( _hold( next_chase=past_naive ), _NOW ) is True

    def test_next_chase_non_string_skips_axis( self ):
        assert hold_is_stale( _hold( next_chase=12345 ), _NOW ) is False             # non-str → parse None


# ── RECONCILIATION: fresh hold awaiting vs derived holding_on edge (bug 7f9a8ee2) ─
#
# The PRIMARY phantom: a holder whose CURRENT hold is fresh+honored with
# awaiting="none" (or naming a DIFFERENT peer) but whose holding_on edge was minted
# from a STALE last_activity.awaiting="peer:X". hold_is_stale does NOT fire (the hold
# is fresh), so the edge survived → phantom "X is blocking worker Y". The hold's
# declared awaiting is AUTHORITATIVE over the stale activity record → the edge dies.

class TestHoldContradictsPeerEdge:
    def test_missing_or_non_dict_hold_not_contradiction( self ):
        assert hold_contradicts_peer_edge( None, "peer:maria", _NOW ) is False
        assert hold_contradicts_peer_edge( { },  "peer:maria", _NOW ) is False   # falsy empty dict guarded
        assert hold_contradicts_peer_edge( "x",  "peer:maria", _NOW ) is False   # non-dict truthy

    def test_non_peer_or_non_string_holding_on_not_contradiction( self ):
        assert hold_contradicts_peer_edge( _hold( awaiting="none" ), None,        _NOW ) is False
        assert hold_contradicts_peer_edge( _hold( awaiting="none" ), "user:rick", _NOW ) is False

    def test_unparseable_edge_peer_not_contradiction( self ):
        # "peer:" → empty token; "peer:user:rick" → non-peer scheme → _parse → None
        assert hold_contradicts_peer_edge( _hold( awaiting="none" ), "peer:",           _NOW ) is False
        assert hold_contradicts_peer_edge( _hold( awaiting="none" ), "peer:user:rick",  _NOW ) is False

    def test_expired_hold_deferred_to_staleness_axis( self ):
        # only a FRESH hold's awaiting is authoritative; a dead hold is hold_is_stale's
        # job (fail-SAFE — this predicate does not double-classify the staleness axes)
        dead = _hold( seconds_ago_held=10_000, ttl=900, awaiting="none" )
        assert hold_contradicts_peer_edge( dead, "peer:maria", _NOW ) is False

    def test_awaiting_absent_or_non_string_not_contradiction( self ):
        # no authoritative declaration → fail-SAFE keep the edge
        assert hold_contradicts_peer_edge( _hold(),                "peer:maria", _NOW ) is False  # no awaiting key
        assert hold_contradicts_peer_edge( _hold( awaiting=None ), "peer:maria", _NOW ) is False

    def test_awaiting_matches_edge_peer_no_contradiction( self ):
        # genuine wait — the hold corroborates the edge → it survives
        assert hold_contradicts_peer_edge( _hold( awaiting="peer:maria" ), "peer:maria", _NOW ) is False

    def test_awaiting_matches_case_insensitively( self ):
        # canonical comparison: a spelling/case difference still corroborates
        assert hold_contradicts_peer_edge( _hold( awaiting="peer:maria" ), "peer:Maria", _NOW ) is False

    def test_awaiting_none_contradicts_peer_edge( self ):           # THE phantom (7f9a8ee2)
        assert hold_contradicts_peer_edge( _hold( awaiting="none" ), "peer:maria", _NOW ) is True

    def test_awaiting_different_peer_contradicts( self ):
        assert hold_contradicts_peer_edge( _hold( awaiting="peer:bob" ), "peer:maria", _NOW ) is True

    def test_falsy_canonical_token_falls_back_to_raw_on_both_sides( self ):
        # canonical_persona_key("🌸") == "" (falsy: no [a-z0-9 ] chars) → the
        # ( canonical_persona_key(x) or x ) short-circuit must FALL BACK to the raw
        # token on BOTH the declared AND edge_peer sides — drives the else-arm of the
        # `or` that the maria/bob cases never reach (genuine branch coverage, not just
        # line). Equal raw emoji tokens corroborate; different raw tokens contradict.
        assert hold_contradicts_peer_edge( _hold( awaiting="peer:🌸" ), "peer:🌸", _NOW ) is False
        assert hold_contradicts_peer_edge( _hold( awaiting="peer:🌸" ), "peer:🌹", _NOW ) is True


# ── STALENESS-FILTER: edge contribution (bug bc1bc373) ───────────────────────────

class TestStalenessEdgeFilter:
    FLEET = {
        "a": { "persona": "Ann", "holding_on": "peer:Bob" },
        "b": { "persona": "Bob", "holding_on": "peer:Ann" },
    }

    def test_stale_holder_contributes_zero_edges( self ):        # AC B.1
        assert build_wait_edges( self.FLEET, stale_holders={ "Ann" } ) == { "Bob": "Ann" }

    def test_live_holder_keeps_edge_no_overfilter( self ):       # AC B.2
        assert build_wait_edges( self.FLEET, stale_holders=set() )  == { "Ann": "Bob", "Bob": "Ann" }
        assert build_wait_edges( self.FLEET, stale_holders=None )   == { "Ann": "Bob", "Bob": "Ann" }

    def test_build_graph_threads_stale_holders_into_cycles( self ):
        # dropping ONE ring member dissolves the cycle (zero inferred edges from it)
        g = build_graph( self.FLEET, stale_holders={ "Ann" } )
        assert g[ "edges" ]  == { "Bob": "Ann" }
        assert g[ "cycles" ] == [ ]

    def test_filter_does_not_disturb_unrelated_live_ring( self ):  # AC B.3-adjacent (pure leaf)
        # a ring of all-LIVE holders (none stale) still forms — the filter only
        # subtracts dead holders; a store-backed live ring is unaffected.
        g = build_graph( self.FLEET, stale_holders={ "Zed" } )      # Zed not in fleet → no-op
        assert g[ "cycles" ] == [ [ "Ann", "Bob" ] ]


# ── SESSION-FRESHNESS GATE: dead SESSION → zero edges (bug 8a450183) ──────────────
#
# The PERSONA-COLLAPSE phantom: a DEAD session's stale `holding_on: peer:X` edge
# survives the per-PERSONA alive filter because a LIVE same-persona session keeps
# the persona "alive". The fix gates peer-edge inference on the HOLDER SESSION's
# OWN freshness — decided per session-id (the view), NEVER collapsed to persona —
# additive + fail-SAFE (missing/unparseable ts → KEEP the edge; never view['alive']).

class TestSessionFreshnessGate:
    _OLD   = _NOW - datetime.timedelta( hours=12 )      # far beyond a 600s threshold
    _FRESH = _NOW - datetime.timedelta( seconds=30 )

    def test_predicate_beyond_threshold_is_stale( self ):           # A: parseable + beyond → True
        assert session_is_stale( { "last_activity_ts": self._OLD }, _NOW, 600 ) is True

    def test_predicate_fresh_is_not_stale( self ):                  # A3: fresh session kept
        assert session_is_stale( { "last_activity_ts": self._FRESH }, _NOW, 600 ) is False

    def test_predicate_iso_string_ts_parsed( self ):               # tolerate a string ts (fail-safe parse)
        assert session_is_stale( { "last_activity_ts": self._OLD.isoformat() }, _NOW, 600 ) is True
        assert session_is_stale( { "last_activity_ts": self._FRESH.isoformat() }, _NOW, 600 ) is False

    def test_predicate_missing_or_unparseable_ts_keeps_edge( self ):  # A3 fail-SAFE: missing → KEEP
        assert session_is_stale( { }, _NOW, 600 )                              is False  # no ts key
        assert session_is_stale( { "last_activity_ts": None }, _NOW, 600 )     is False  # explicit None
        assert session_is_stale( { "last_activity_ts": "garbage" }, _NOW, 600 ) is False  # unparseable
        assert session_is_stale( { "last_activity_ts": 12345 }, _NOW, 600 )    is False  # non-str/non-dt

    def test_predicate_inert_without_now_or_threshold( self ):      # additive: defaults None → no gate
        assert session_is_stale( { "last_activity_ts": self._OLD }, None, 600 )  is False
        assert session_is_stale( { "last_activity_ts": self._OLD }, _NOW, None ) is False

    def test_predicate_non_dict_view( self ):                       # fail-SAFE: junk view
        assert session_is_stale( "not-a-dict", _NOW, 600 ) is False
        assert session_is_stale( None, _NOW, 600 )         is False

    def test_predicate_unusable_now_keeps_edge( self ):            # fail-SAFE: now non-datetime → except → keep
        # a truthy-but-non-datetime `now` makes (now - ts) raise TypeError → KEEP edge
        assert session_is_stale( { "last_activity_ts": self._OLD }, "not-a-datetime", 600 ) is False

    def test_predicate_future_ts_is_not_stale( self ):             # negative age → recent → keep
        future = _NOW + datetime.timedelta( hours=1 )
        assert session_is_stale( { "last_activity_ts": future }, _NOW, 600 ) is False

    # ── the PERSONA-COLLAPSE scenario at the pure leaf ──────────────────────────
    # Two views, SAME persona "mr radio": a DEAD session (old ts, awaiting peer:maria)
    # and a LIVE session (fresh, awaiting none). The dead session's edge must NOT
    # survive when the session-freshness gate is engaged.
    DUAL = {
        "s_dead": { "persona": "mr radio", "holding_on": "peer:maria", "last_activity_ts": _OLD },
        "s_live": { "persona": "mr radio", "holding_on": "none",       "last_activity_ts": _FRESH },
    }

    def test_dead_session_edge_dropped_with_gate( self ):           # A1: filtered path → no phantom
        edges = build_wait_edges( self.DUAL, now=_NOW, alive_threshold_seconds=600 )
        assert edges == { }                                        # dead "mr radio"→"maria" gone
        g = build_graph( self.DUAL, now=_NOW, alive_threshold_seconds=600 )
        assert g[ "edges" ] == { } and g[ "cycles" ] == [ ]

    def test_dead_session_edge_survives_without_gate( self ):       # A2: :1018 unfiltered feed unchanged
        # the UNFILTERED escalation feed passes NO now/threshold → byte-identical to
        # the prior behavior: the dead session's edge is STILL present (the store gate
        # downstream is what suppresses a non-store phantom, NOT this leaf).
        assert build_wait_edges( self.DUAL ) == { "mr radio": "maria" }

    def test_gate_composes_with_stale_holders( self ):             # both axes OR'd, no interference
        # a LIVE-but-stale-hold holder (persona path) AND a dead session (session path)
        fv = {
            "s_dead": { "persona": "mr radio", "holding_on": "peer:maria", "last_activity_ts": self._OLD },
            "s_live": { "persona": "Ann",      "holding_on": "peer:Bob",   "last_activity_ts": self._FRESH },
        }
        # session gate drops s_dead; stale_holders drops Ann → zero edges
        assert build_wait_edges( fv, stale_holders={ "Ann" },
                                 now=_NOW, alive_threshold_seconds=600 ) == { }
        # without stale_holders, Ann's live edge survives; only the dead session drops
        assert build_wait_edges( fv, now=_NOW, alive_threshold_seconds=600 ) == { "Ann": "Bob" }


def test_module_smoke_passes():
    assert quick_smoke_test() is True
