#!/usr/bin/env python3
"""
Unit tests for cosa.agents.decision_proxy.user_presence.

The feed-failure rule lives in one small function so that the ruling on what
a broken connectivity feed means is a single constant. No I/O.
"""

import logging
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


def test_a_failed_feed_logs_one_line_that_names_the_feed_and_the_cause( caplog ):
    with caplog.at_level( logging.WARNING, logger=up.logger.name ):
        up.user_connected_or_default( MagicMock( side_effect=OSError( "connection refused" ) ) )
    lines = [ r for r in caplog.records if r.name == up.logger.name ]
    assert len( lines ) == 1
    assert "connectivity feed failed" in lines[ 0 ].getMessage()
    assert "connection refused" in lines[ 0 ].getMessage()
    assert lines[ 0 ].levelno == logging.WARNING


def test_each_failure_logs_its_own_line_and_a_working_feed_logs_nothing( caplog ):
    with caplog.at_level( logging.WARNING, logger=up.logger.name ):
        up.user_connected_or_default( lambda: True )
        up.user_connected_or_default( MagicMock( side_effect=OSError( "a" ) ) )
        up.user_connected_or_default( MagicMock( side_effect=OSError( "b" ) ) )
    assert len( [ r for r in caplog.records if r.name == up.logger.name ] ) == 2


def test_a_feed_failure_through_the_responder_still_lets_the_proxy_answer_and_logs( caplog ):
    from datetime import datetime
    from types import SimpleNamespace
    import asyncio
    from cosa.agents.decision_proxy.responder import DecisionResponder
    r = DecisionResponder( accepted_senders=[ "s@x" ], now_fn=lambda: datetime( 2026, 10, 8, 12, 0 ),
                           user_connected_fn=MagicMock( side_effect=OSError( "down" ) ) )
    r.submit_response   = MagicMock( return_value=True )
    r._persist_decision = MagicMock()
    r.set_domain_strategy( MagicMock( evaluate=MagicMock( return_value=SimpleNamespace(
        action="act", value="yes", category="c", confidence=0.9, trust_level=3, reason="r" ) ) ) )
    with caplog.at_level( logging.WARNING, logger=up.logger.name ):
        asyncio.run( r._handle_decision_event( { "response_requested": True, "id_hash": "nid-1", "message": "Do X?", "sender_id": "s@x" } ) )
    r.submit_response.assert_called_once_with( "nid-1", "yes" )
    assert any( "connectivity feed failed" in rec.getMessage() for rec in caplog.records )
