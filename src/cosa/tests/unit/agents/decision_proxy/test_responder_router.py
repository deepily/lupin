#!/usr/bin/env python3
"""
Unit tests for the SmartRouter wiring in DecisionResponder.

Before the strategy's auto-answer is posted, the responder asks the router
whether the human is available. Inside active hours and connected, it defers:
nothing is posted and the decision is recorded as a defer. Plan:
io/tmp/2026.10.08-john-smartrouter-wiring-plan.md. No I/O: the answer door,
the database and the connectivity feed are all doubles.
"""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from cosa.agents.decision_proxy.responder import DecisionResponder

NOON  = datetime( 2026, 10, 8, 12, 0 )
NIGHT = datetime( 2026, 10, 8, 3, 0 )


def _result( action="act", value="yes", category="testing" ):
    return SimpleNamespace( action=action, value=value, category=category,
                            confidence=0.9, trust_level=3, reason="strategy reason" )


def _event():
    return { "response_requested": True, "id_hash": "nid-1", "message": "Do X?", "sender_id": "s@x" }


def _responder( result, connected=None, now=NOON, **kwargs ):
    """A responder with a strategy double, a feed double and a clock double."""
    feed = MagicMock( return_value=connected ) if not isinstance( connected, Exception ) else MagicMock( side_effect=connected )
    r    = DecisionResponder( accepted_senders=[ "s@x" ], user_connected_fn=feed, now_fn=lambda: now, **kwargs )
    r.submit_response    = MagicMock( return_value=True )
    r._persist_decision  = MagicMock()
    strategy             = MagicMock()
    strategy.evaluate    = MagicMock( return_value=result )
    r.set_domain_strategy( strategy )
    return r, feed


def _run( r ):
    asyncio.run( r._handle_decision_event( _event() ) )


def test_act_inside_hours_with_the_user_connected_defers_and_posts_nothing():
    r, _ = _responder( _result(), connected=True )
    _run( r )
    r.submit_response.assert_not_called()
    assert r.stats[ "decisions_deferred_to_user" ] == 1
    assert r.stats[ "decisions_acted" ] == 0 and r.stats[ "responses_sent" ] == 0
    assert r.stats[ "decisions_deferred" ] == 0


def test_a_router_defer_is_persisted_as_a_defer_that_keeps_the_proxys_answer_and_says_why():
    r, _ = _responder( _result( category="cat-9" ), connected=True )
    _run( r )
    ( nid, persisted, question ), _kw = r._persist_decision.call_args
    assert nid == "nid-1" and question == "Do X?"
    assert persisted.action == "defer" and persisted.category == "cat-9" and persisted.value == "yes"
    assert "user available" in persisted.reason


def test_act_outside_active_hours_still_posts_even_if_the_user_is_connected():
    r, _ = _responder( _result(), connected=True, now=NIGHT )
    _run( r )
    r.submit_response.assert_called_once_with( "nid-1", "yes" )
    assert r.stats[ "decisions_acted" ] == 1 and r.stats[ "decisions_deferred_to_user" ] == 0


def test_act_inside_hours_with_the_user_away_still_posts():
    r, _ = _responder( _result(), connected=False )
    _run( r )
    r.submit_response.assert_called_once_with( "nid-1", "yes" )
    assert r.stats[ "decisions_deferred_to_user" ] == 0


def test_a_responder_with_no_feed_behaves_as_before_at_any_hour():
    r = DecisionResponder( accepted_senders=[ "s@x" ], now_fn=lambda: NOON )
    r.submit_response   = MagicMock( return_value=True )
    r._persist_decision = MagicMock()
    r.set_domain_strategy( MagicMock( evaluate=MagicMock( return_value=_result() ) ) )
    _run( r )
    r.submit_response.assert_called_once_with( "nid-1", "yes" )


def test_a_feed_that_raises_is_read_through_the_failure_rule_not_propagated():
    r, feed = _responder( _result(), connected=RuntimeError( "server down" ) )
    _run( r )
    feed.assert_called_once()
    r.submit_response.assert_called_once_with( "nid-1", "yes" )   # failure rule: not connected


def test_the_router_is_consulted_only_when_the_proxy_is_about_to_answer():
    for action, value in ( ( "shadow", None ), ( "suggest", "maybe" ), ( "defer", None ), ( "act", None ) ):
        r, feed = _responder( _result( action=action, value=value ), connected=True )
        _run( r )
        feed.assert_not_called()


def test_dry_run_and_a_disabled_proxy_never_reach_the_router():
    for kwargs in ( { "dry_run": True }, { "enabled": False } ):
        r, feed = _responder( _result(), connected=True, **kwargs )
        _run( r )
        feed.assert_not_called()


def test_the_active_hours_and_timezone_settings_reach_the_router():
    r = DecisionResponder( active_hours_start=7, active_hours_end=18, timezone="UTC" )
    assert ( r.smart_router.active_hours_start, r.smart_router.active_hours_end, r.smart_router.timezone ) == ( 7, 18, "UTC" )


def test_the_configured_window_decides_not_the_defaults():
    # 20:00 is outside 7..18 but inside the default 9..22
    r, _ = _responder( _result(), connected=True, now=datetime( 2026, 10, 8, 20, 0 ), active_hours_start=7, active_hours_end=18 )
    _run( r )
    r.submit_response.assert_called_once_with( "nid-1", "yes" )
