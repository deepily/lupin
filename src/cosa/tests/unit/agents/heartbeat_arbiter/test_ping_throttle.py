#!/usr/bin/env python3
"""
Unit tests for the Heartbeat Arbiter ping-throttle leaf.

Target: 100% line + branch + function coverage of
    cosa/agents/heartbeat_arbiter/ping_throttle.py
"""
import datetime

from cosa.agents.heartbeat_arbiter import ping_throttle as p


UTC = datetime.timezone.utc
NOW = datetime.datetime( 2026, 6, 5, 12, 0, 0, tzinfo=UTC )


def test_edge_key():
    assert p.edge_key( "Ann", "Bob", "blocked" ) == "Ann|Bob|blocked"
    assert p.edge_key( None, None, None ) == "||"


def test_backoff_for_attempt():
    assert p.backoff_for_attempt( 0 ) == 60
    assert p.backoff_for_attempt( 1 ) == 300
    assert p.backoff_for_attempt( 3 ) == 3600
    assert p.backoff_for_attempt( 99 ) == 3600     # clamped to widest
    assert p.backoff_for_attempt( -1 ) == 60       # negative → first window


def test_should_ping():
    assert p.should_ping( None, NOW, 60 ) is True                                    # never pinged
    assert p.should_ping( NOW - datetime.timedelta( seconds=120 ), NOW, 60 ) is True  # window elapsed
    assert p.should_ping( NOW - datetime.timedelta( seconds=30 ),  NOW, 60 ) is False # within window
    assert p.should_ping( "bad-ts", NOW, 60 ) is False                                # unusable ts


def test_under_global_cap():
    assert p.under_global_cap( 4, 5 ) is True
    assert p.under_global_cap( 5, 5 ) is False


# ── Item C (2026-06-24): trailing-window throttle primitives ────────────────────

def test_in_window():
    recent = [ NOW - datetime.timedelta( seconds=10 ), NOW - datetime.timedelta( seconds=59 ) ]
    old    = NOW - datetime.timedelta( seconds=10_000 )
    future = NOW + datetime.timedelta( seconds=5 )
    assert p.in_window( recent, NOW, 60 )          == recent            # both within 60s
    assert p.in_window( recent + [ old ], NOW, 60 ) == recent           # old pruned
    assert p.in_window( [ future ], NOW, 60 )      == [ ]              # future ts dropped (fail-safe)
    assert p.in_window( [ "bad-ts" ], NOW, 60 )    == [ ]              # unusable entry dropped
    assert p.in_window( None, NOW, 60 )            == [ ]              # None → []
    assert p.in_window( [ ], NOW, 60 )             == [ ]              # empty → []
    # boundary: age exactly == window is INSIDE
    assert p.in_window( [ NOW - datetime.timedelta( seconds=60 ) ], NOW, 60 ) == [ NOW - datetime.timedelta( seconds=60 ) ]


def test_trailing_window_allows():
    two = [ NOW - datetime.timedelta( seconds=10 ), NOW - datetime.timedelta( seconds=20 ) ]
    assert p.trailing_window_allows( two, NOW, 3, 60 ) is True          # 2 < 3 → room
    assert p.trailing_window_allows( two, NOW, 2, 60 ) is False         # 2 >= 2 → full
    assert p.trailing_window_allows( [ ], NOW, 1, 60 ) is True          # none sent → room
    # old sends drop out of the window → room again
    old = two + [ NOW - datetime.timedelta( seconds=10_000 ) ]
    assert p.trailing_window_allows( old, NOW, 3, 60 ) is True          # only 2 in window < 3
    # DISABLED (fail-safe): max<=0 or window<=0 → always allowed
    assert p.trailing_window_allows( two, NOW, 0, 60 )  is True
    assert p.trailing_window_allows( two, NOW, -1, 60 ) is True
    assert p.trailing_window_allows( two, NOW, 2, 0 )   is True
    assert p.trailing_window_allows( two, NOW, 2, -5 )  is True


def test_quick_smoke_test():
    assert p.quick_smoke_test() is True
