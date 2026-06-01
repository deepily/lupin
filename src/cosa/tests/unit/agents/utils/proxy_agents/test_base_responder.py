"""
Unit tests for cosa/agents/utils/proxy_agents/base_responder.py.

BaseResponder is abstract; a minimal concrete subclass exercises the shared
strategy-chain + submit + stats logic. The REST seam (submit_notification_response)
is boundary-mocked. ZERO API spend.
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

import cosa.agents.utils.proxy_agents.base_responder as mod
from cosa.agents.utils.proxy_agents.base_responder import BaseResponder


class _Responder( BaseResponder ):
    async def handle_event( self, event_type, event_data ):
        # delegate to the abstract base body once ( covers the `...` contract line )
        return await super().handle_event( event_type, event_data )


def _strategy( name, available=True, can_handle=True, answer="ans", coro=False ):
    s = MagicMock()
    s.name      = name
    s.available = available
    s.can_handle.return_value = can_handle
    if coro:
        async def _async_respond( item ):
            return answer
        s.respond.side_effect = _async_respond
    else:
        s.respond.return_value = answer
    return s


def _run( coro ):
    return asyncio.run( coro )


# =========================================================================== #
# __init__
# =========================================================================== #
def test_init_stores_params_and_stats():
    r = _Responder( host="h", port=1234, dry_run=True, debug=True, verbose=True )
    assert ( r.host, r.port, r.dry_run, r.debug, r.verbose ) == ( "h", 1234, True, True, True )
    assert r.stats == { "events_received": 0, "responses_sent": 0, "skipped": 0, "errors": 0 }


def test_abstract_handle_event_body_is_noop():
    # subclass delegates to super().handle_event → the abstract `...` body runs, returns None
    assert _run( _Responder().handle_event( "evt", {} ) ) is None


# =========================================================================== #
# route_to_strategies  ( sync )
# =========================================================================== #
def test_route_sync_skips_unavailable_then_matches():
    unavailable = _strategy( "off", available=False )
    matcher     = _strategy( "hit", answer="42" )
    answer, name = _Responder().route_to_strategies( { "x": 1 }, [ unavailable, matcher ] )
    assert ( answer, name ) == ( "42", "hit" )
    unavailable.can_handle.assert_not_called()


def test_route_sync_skips_non_handling_strategy():
    nope = _strategy( "nope", can_handle=False )
    answer, name = _Responder().route_to_strategies( {}, [ nope ] )
    assert ( answer, name ) == ( None, None )


def test_route_sync_handler_returns_none_falls_through():
    none_answer = _strategy( "n", answer=None )
    answer, name = _Responder().route_to_strategies( {}, [ none_answer ] )
    assert ( answer, name ) == ( None, None )


# =========================================================================== #
# route_to_strategies_async
# =========================================================================== #
def test_route_async_with_coroutine_respond():
    s = _strategy( "async-hit", answer="async-ans", coro=True )
    answer, name = _run( _Responder().route_to_strategies_async( {}, [ s ] ) )
    assert ( answer, name ) == ( "async-ans", "async-hit" )


def test_route_async_with_sync_respond():
    s = _strategy( "sync-hit", answer="sync-ans", coro=False )
    answer, name = _run( _Responder().route_to_strategies_async( {}, [ s ] ) )
    assert ( answer, name ) == ( "sync-ans", "sync-hit" )


def test_route_async_skips_unavailable_and_non_handling():
    off  = _strategy( "off", available=False )
    nope = _strategy( "nope", can_handle=False )
    answer, name = _run( _Responder().route_to_strategies_async( {}, [ off, nope ] ) )
    assert ( answer, name ) == ( None, None )


def test_route_async_none_answer_falls_through():
    s = _strategy( "n", answer=None )
    answer, name = _run( _Responder().route_to_strategies_async( {}, [ s ] ) )
    assert ( answer, name ) == ( None, None )


# =========================================================================== #
# submit_response
# =========================================================================== #
def test_submit_response_delegates_to_rest_submitter():
    r = _Responder( host="h", port=99, debug=True, verbose=True )
    with patch.object( mod, "submit_notification_response", return_value=True ) as m:
        assert r.submit_response( "nid", "val" ) is True
    m.assert_called_once_with(
        notification_id="nid", response_value="val", host="h", port=99, debug=True, verbose=True
    )


# =========================================================================== #
# print_stats
# =========================================================================== #
def test_print_stats_emits_all_keys( capsys ):
    r = _Responder()
    r.stats[ "events_received" ] = 3
    r.print_stats()
    out = capsys.readouterr().out
    assert "Proxy Agent Statistics" in out
    assert "Events Received" in out
    assert "3" in out
