#!/usr/bin/env python3
"""
Unit tests for cosa.agents.decision_proxy.user_presence.

The feed-failure rule lives in one small function so that the ruling on what
a broken connectivity feed means is a single constant. No I/O.
"""

from unittest.mock import MagicMock

import cosa.agents.decision_proxy.user_presence as up


def test_a_working_feed_is_returned_as_a_bool():
    assert up.user_connected_or_default( lambda: True ) is True
    assert up.user_connected_or_default( lambda: False ) is False
    assert up.user_connected_or_default( lambda: 1 ) is True


def test_a_feed_that_raises_returns_the_failure_value():
    feed = MagicMock( side_effect=OSError( "refused" ) )
    assert up.user_connected_or_default( feed ) is up.FEED_FAILURE_MEANS_CONNECTED


def test_the_failure_value_is_not_connected_until_rick_rules_otherwise():
    assert up.FEED_FAILURE_MEANS_CONNECTED is False


def test_the_failure_value_is_what_the_function_returns_when_it_is_changed(monkeypatch):
    monkeypatch.setattr( up, "FEED_FAILURE_MEANS_CONNECTED", True )
    assert up.user_connected_or_default( MagicMock( side_effect=OSError() ) ) is True
