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

from cosa.agents.heartbeat_arbiter.dependency_graph import (
    build_wait_edges, find_deadlock_cycles, build_graph,
    build_store_wait_edges, cycle_is_store_backed, quick_smoke_test,
)


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


def test_module_smoke_passes():
    assert quick_smoke_test() is True
