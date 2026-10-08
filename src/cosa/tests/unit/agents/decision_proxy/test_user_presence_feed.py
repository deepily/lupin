#!/usr/bin/env python3
"""
Unit tests for the connectivity feed and the responder wiring.

They cover the feed and the wiring function of user_presence. The feed asks the server which sessions are live (GET /api/websocket-sessions)
and answers whether the human has one that is not the proxy's own. All HTTP
and time are doubles.
"""

from unittest.mock import MagicMock

import cosa.agents.decision_proxy.user_presence as up

HUMAN = "human-1"
OWN   = "decision-proxy-session"


def _payload( *pairs ):
    return { "sessions": [ { "session_id": sid, "user_id": uid } for sid, uid in pairs ] }


def _feed( payload, ttl=10.0, clock=None, human=HUMAN, authorization_fn=lambda: "Bearer t-1" ):
    fetch = MagicMock( return_value=payload )
    feed  = up.sessions_feed( "h", 7999, authorization_fn, human, OWN, ttl_seconds=ttl, fetch_fn=fetch,
                              clock=clock if clock is not None else ( lambda: 0.0 ) )
    return feed, fetch


def test_the_human_with_a_session_of_their_own_is_connected():
    feed, _ = _feed( _payload( ( "web-1", HUMAN ) ) )
    assert feed() is True


def test_the_proxys_own_session_does_not_count_even_under_the_humans_id():
    feed, _ = _feed( _payload( ( OWN, HUMAN ) ) )
    assert feed() is False


def test_other_users_do_not_count():
    feed, _ = _feed( _payload( ( "web-9", "someone-else" ), ( "web-2", None ) ) )
    assert feed() is False


def test_no_sessions_means_not_connected():
    feed, _ = _feed( { "sessions": [] } )
    assert feed() is False


def test_no_human_configured_means_not_connected_and_no_request():
    feed, fetch = _feed( _payload( ( "web-1", HUMAN ) ), human="" )
    assert feed() is False
    fetch.assert_not_called()


def test_the_request_goes_to_the_sessions_door_with_the_current_authorization():
    tokens = iter( [ "Bearer t-1", "Bearer t-2" ] )
    now    = [ 0.0 ]
    feed, fetch = _feed( _payload( ( "web-1", HUMAN ) ), clock=lambda: now[ 0 ], authorization_fn=lambda: next( tokens ) )
    feed()
    now[ 0 ] = 100.0
    feed()
    assert fetch.call_args_list[ 0 ].args == ( "http://h:7999/api/websocket-sessions", { "Authorization": "Bearer t-1" } )
    assert fetch.call_args_list[ 1 ].args == ( "http://h:7999/api/websocket-sessions", { "Authorization": "Bearer t-2" } )


def test_an_answer_is_reused_inside_the_ttl_and_refetched_after_it():
    now = [ 0.0 ]
    feed, fetch = _feed( _payload( ( "web-1", HUMAN ) ), ttl=10.0, clock=lambda: now[ 0 ] )
    feed(); now[ 0 ] = 9.9; feed()
    assert fetch.call_count == 1
    now[ 0 ] = 10.0; feed()
    assert fetch.call_count == 2


def test_a_failed_fetch_raises_and_is_not_cached():
    fetch = MagicMock( side_effect=[ OSError( "down" ), _payload( ( "web-1", HUMAN ) ) ] )
    feed  = up.sessions_feed( "h", 7999, lambda: None, HUMAN, OWN, fetch_fn=fetch, clock=lambda: 0.0 )
    try:
        feed()
        raised = False
    except OSError:
        raised = True
    assert raised and feed() is True


def test_the_default_fetch_is_a_timed_get_that_raises_on_http_errors(monkeypatch):
    response = MagicMock()
    response.json.return_value = { "sessions": [] }
    get = MagicMock( return_value=response )
    monkeypatch.setattr( up.requests, "get", get )
    assert up.fetch_sessions( "http://x/api/websocket-sessions", { "Authorization": "Bearer t" } ) == { "sessions": [] }
    assert get.call_args.kwargs[ "headers" ] == { "Authorization": "Bearer t" }
    assert get.call_args.kwargs[ "timeout" ] == up.SESSIONS_TIMEOUT_SECONDS and up.SESSIONS_TIMEOUT_SECONDS > 0
    response.raise_for_status.assert_called_once_with()


def test_a_request_without_a_token_sends_no_authorization_header():
    feed, fetch = _feed( _payload(), authorization_fn=lambda: None )
    feed()
    assert fetch.call_args.args[ 1 ] == {}


def _config( values ):
    mgr = MagicMock()
    mgr.get.side_effect = lambda key, default=None, return_type=None: values.get( key, default )
    return mgr


def test_the_wiring_reads_the_ini_values_and_returns_the_responder_arguments():
    mgr = _config( { "decision proxy active hours start": 7, "decision proxy active hours end": 18,
                     "decision proxy timezone": "UTC", "decision proxy human user id": HUMAN } )
    out = up.responder_presence_kwargs( mgr, "h", 7999, lambda: "Bearer t", OWN )
    assert ( out[ "active_hours_start" ], out[ "active_hours_end" ], out[ "timezone" ] ) == ( 7, 18, "UTC" )
    assert set( out ) == { "active_hours_start", "active_hours_end", "timezone", "user_connected_fn" }
    assert callable( out[ "user_connected_fn" ] )


def test_the_wiring_asks_for_the_hours_as_integers():
    mgr = _config( {} )
    up.responder_presence_kwargs( mgr, "h", 7999, lambda: None, OWN )
    asked = { c.args[ 0 ]: c.kwargs.get( "return_type" ) for c in mgr.get.call_args_list }
    assert asked[ "decision proxy active hours start" ] == "int" and asked[ "decision proxy active hours end" ] == "int"


def test_the_wired_feed_uses_the_configured_human_and_the_hosts_port():
    mgr = _config( { "decision proxy human user id": HUMAN } )
    out = up.responder_presence_kwargs( mgr, "srv", 8123, lambda: "Bearer t", OWN, fetch_fn=MagicMock( return_value=_payload( ( "web-1", HUMAN ) ) ) )
    assert out[ "user_connected_fn" ]() is True


def test_with_no_human_id_in_the_ini_the_wired_feed_is_never_connected():
    mgr = _config( {} )
    fetch = MagicMock( return_value=_payload( ( "web-1", HUMAN ) ) )
    out = up.responder_presence_kwargs( mgr, "h", 7999, lambda: None, OWN, fetch_fn=fetch )
    assert out[ "user_connected_fn" ]() is False
    fetch.assert_not_called()


def test_the_ini_and_its_splainer_both_carry_the_human_user_id_key():
    import cosa.utils.util as cu
    root = cu.get_project_root()
    for name in ( "lupin-app.ini", "lupin-app-splainer.ini" ):
        text  = open( f"{root}/src/conf/{name}" ).read()
        lines = [ l for l in text.splitlines() if l.startswith( "decision proxy human user id" ) ]
        assert len( lines ) == 1, name
    ini = [ l for l in open( f"{root}/src/conf/lupin-app.ini" ).read().splitlines() if l.startswith( "decision proxy human user id" ) ][ 0 ]
    assert ini.split( "=", 1 )[ 1 ].strip() == ""          # shipped empty: the proxy answers as before
