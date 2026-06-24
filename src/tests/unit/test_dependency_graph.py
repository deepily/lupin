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
    build_store_wait_edges, cycle_is_store_backed, hold_is_stale, quick_smoke_test,
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


def test_module_smoke_passes():
    assert quick_smoke_test() is True
