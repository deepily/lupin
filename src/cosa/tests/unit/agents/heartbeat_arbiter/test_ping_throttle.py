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


def test_quick_smoke_test():
    assert p.quick_smoke_test() is True
