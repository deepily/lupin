#!/usr/bin/env python3
"""
Unit tests for cosa.agents.decision_proxy.smart_router.

SmartRouter decides whether a decision should be deferred to the user based
on (1) configured active hours (normal + overnight wrap-around) and (2)
WebSocket connectivity. datetime is supplied via the `now` parameter for
determinism; the now=None default path (zoneinfo) and its ImportError
fallback are exercised explicitly.
"""

import sys
from datetime import datetime
from unittest.mock import patch

from cosa.agents.decision_proxy.smart_router import SmartRouter


def _at( hour ):
    return datetime( 2026, 1, 15, hour, 0, 0 )


# ----------------------------------------------------------------------------
# __init__
# ----------------------------------------------------------------------------
def test_init_stores_config():
    r = SmartRouter( active_hours_start=8, active_hours_end=20, timezone="UTC", debug=True )
    assert r.active_hours_start == 8
    assert r.active_hours_end == 20
    assert r.timezone == "UTC"
    assert r.debug is True


# ----------------------------------------------------------------------------
# is_active_hours — normal window (start <= end)
# ----------------------------------------------------------------------------
def test_active_hours_normal_inside():
    assert SmartRouter( 9, 22 ).is_active_hours( _at( 12 ) ) is True


def test_active_hours_normal_before_start():
    assert SmartRouter( 9, 22 ).is_active_hours( _at( 3 ) ) is False


def test_active_hours_normal_end_is_exclusive():
    assert SmartRouter( 9, 22 ).is_active_hours( _at( 22 ) ) is False
    assert SmartRouter( 9, 22 ).is_active_hours( _at( 9 ) ) is True


# ----------------------------------------------------------------------------
# is_active_hours — overnight wrap-around (start > end)
# ----------------------------------------------------------------------------
def test_active_hours_overnight_evening():
    assert SmartRouter( 22, 6 ).is_active_hours( _at( 23 ) ) is True


def test_active_hours_overnight_morning():
    assert SmartRouter( 22, 6 ).is_active_hours( _at( 3 ) ) is True


def test_active_hours_overnight_daytime_inactive():
    assert SmartRouter( 22, 6 ).is_active_hours( _at( 12 ) ) is False


# ----------------------------------------------------------------------------
# is_active_hours — now=None default resolution
# ----------------------------------------------------------------------------
def test_active_hours_now_none_uses_zoneinfo():
    """Ensures: now=None resolves the clock via zoneinfo and returns a bool."""
    r = SmartRouter( 0, 23, timezone="America/Chicago" )
    assert isinstance( r.is_active_hours(), bool )


def test_active_hours_now_none_zoneinfo_importerror_fallback():
    """
    Ensures: when `import zoneinfo` fails, the except-ImportError arm falls
    back to datetime.now() (genuinely covered, not pragma'd).
    """
    r = SmartRouter( 0, 23 )
    with patch.dict( sys.modules, { "zoneinfo": None } ):
        result = r.is_active_hours()
    assert isinstance( result, bool )


# ----------------------------------------------------------------------------
# should_defer_to_user
# ----------------------------------------------------------------------------
def test_defer_false_outside_hours_debug( capsys ):
    r = SmartRouter( 9, 22, debug=True )
    assert r.should_defer_to_user( _at( 2 ), user_connected=True ) is False
    assert "Outside active hours" in capsys.readouterr().out


def test_defer_false_not_connected_debug( capsys ):
    r = SmartRouter( 9, 22, debug=True )
    assert r.should_defer_to_user( _at( 12 ), user_connected=False ) is False
    assert "not connected" in capsys.readouterr().out


def test_defer_true_active_and_connected_debug( capsys ):
    r = SmartRouter( 9, 22, debug=True )
    assert r.should_defer_to_user( _at( 12 ), user_connected=True ) is True
    assert "defer to user" in capsys.readouterr().out


def test_defer_quiet_paths_emit_no_output( capsys ):
    """Exercises the debug=False arm of all three branches (no printing)."""
    r = SmartRouter( 9, 22, debug=False )
    assert r.should_defer_to_user( _at( 2 ), user_connected=True ) is False    # outside hours
    assert r.should_defer_to_user( _at( 12 ), user_connected=False ) is False  # not connected
    assert r.should_defer_to_user( _at( 12 ), user_connected=True ) is True    # defer
    assert capsys.readouterr().out == ""
