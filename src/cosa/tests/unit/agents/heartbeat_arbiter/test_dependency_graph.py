#!/usr/bin/env python3
"""
Unit tests for the Heartbeat Arbiter dependency-graph cycle detection.

Target: 100% line + branch + function coverage of
    cosa/agents/heartbeat_arbiter/dependency_graph.py
"""
from cosa.agents.heartbeat_arbiter import dependency_graph as d


# ── build_wait_edges ──────────────────────────────────────────────────────────

def test_build_wait_edges_filters():
    fv = {
        "s1": { "persona": "Ann", "holding_on": "peer:Bob" },     # kept
        "s2": { "persona": "Cal", "holding_on": "user:Rick" },    # not a peer edge
        "s3": { "persona": "Dan", "holding_on": "none" },         # not a peer edge
        "s4": { "holding_on": "peer:Eve" },                       # no holder
        "s5": { "persona": "Fay", "holding_on": "peer:   " },     # empty awaited after strip
        "s6": { "persona": "Gil", "holding_on": 123 },            # holding_on not a str
        "s7": "not-a-dict",                                      # skipped
    }
    assert d.build_wait_edges( fv ) == { "Ann": "Bob" }


# ── find_deadlock_cycles ──────────────────────────────────────────────────────

def test_empty_and_acyclic():
    assert d.find_deadlock_cycles( { } ) == [ ]
    assert d.find_deadlock_cycles( { "A": "B" } ) == [ ]          # B has no edge → chain ends


def test_two_cycle():
    assert d.find_deadlock_cycles( { "Ann": "Bob", "Bob": "Ann" } ) == [ [ "Ann", "Bob" ] ]


def test_self_loop():
    assert d.find_deadlock_cycles( { "X": "X" } ) == [ [ "X" ] ]


def test_three_cycle():
    assert d.find_deadlock_cycles( { "A": "B", "B": "C", "C": "A" } ) == [ [ "A", "B", "C" ] ]


def test_canonicalize_rotates():
    # cycle discovered as [B, A] (B inserted first) → canonicalized to [A, B]
    assert d.find_deadlock_cycles( { "B": "A", "A": "B" } ) == [ [ "A", "B" ] ]


def test_chain_into_cycle_and_visited_skip():
    # A→B→C→B : cycle [B,C]; A excluded; iterating B/C hits the `start in visited` continue
    assert d.find_deadlock_cycles( { "A": "B", "B": "C", "C": "B" } ) == [ [ "B", "C" ] ]


def test_two_disjoint_cycles():
    cy = d.find_deadlock_cycles( { "A": "B", "B": "A", "C": "D", "D": "C" } )
    assert sorted( cy ) == [ [ "A", "B" ], [ "C", "D" ] ]


# ── build_graph ───────────────────────────────────────────────────────────────

def test_build_graph():
    fv = { "s1": { "persona": "Ann", "holding_on": "peer:Bob" },
           "s2": { "persona": "Bob", "holding_on": "peer:Ann" } }
    g = d.build_graph( fv )
    assert g[ "edges" ] == { "Ann": "Bob", "Bob": "Ann" }
    assert g[ "cycles" ] == [ [ "Ann", "Bob" ] ]


def test_quick_smoke_test():
    assert d.quick_smoke_test() is True
