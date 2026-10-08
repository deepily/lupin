#!/usr/bin/env python3
"""
Unit test that main() builds the responder with the active-hours settings and the feed.

main() is driven end to end with every outside part doubled. The doubled parts are the
arguments, the login, the INI, the profile loader, the listener, the notifier and the
sessions request. What is checked is the responder it builds.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import cosa.agents.decision_proxy.__main__ as dm
import cosa.agents.decision_proxy.user_presence as up

INI = {
    "decision proxy enabled"            : True,
    "decision proxy active hours start" : 7,
    "decision proxy active hours end"   : 18,
    "decision proxy timezone"           : "UTC",
    "decision proxy human user id"      : "human-1",
}


def _drive_main( monkeypatch, fetch ):
    """Run main() with doubles; return ( the responder it built, the listener double )."""
    built    = []
    listener = MagicMock( authorization="Bearer late", run=AsyncMock(), stop=AsyncMock() )
    args     = SimpleNamespace( verbose=False, debug=False, dry_run=False, email=None, password=None,
                                host="srv", port=8123, session_id="proxy-own", profile=dm.DEFAULT_PROFILE,
                                trust_mode="shadow" )
    cfg      = MagicMock()
    cfg.get.side_effect = lambda key, default=None, return_type=None: INI.get( key, default )

    def loader( responder, debug=False ):
        built.append( responder )
        return True

    monkeypatch.setattr( dm, "parse_args", lambda: args )
    monkeypatch.setattr( dm, "get_credentials", lambda e, p: ( "e@x", "pw" ) )
    monkeypatch.setattr( "cosa.config.configuration_manager.ConfigurationManager", lambda **kw: cfg )
    monkeypatch.setattr( dm, dm.AVAILABLE_PROFILES[ dm.DEFAULT_PROFILE ][ "loader" ], loader )
    monkeypatch.setattr( dm, "DecisionListener", lambda **kw: listener )
    monkeypatch.setattr( dm, "notify", MagicMock() )
    monkeypatch.setattr( up, "fetch_sessions", fetch )
    asyncio.run( dm.main() )
    return built[ 0 ], listener


def test_main_builds_the_responder_with_the_ini_hours_and_timezone( monkeypatch ):
    responder, _ = _drive_main( monkeypatch, MagicMock() )
    router = responder.smart_router
    assert ( router.active_hours_start, router.active_hours_end, router.timezone ) == ( 7, 18, "UTC" )


def test_main_gives_the_responder_a_feed_that_asks_the_server_with_the_listeners_token( monkeypatch ):
    fetch = MagicMock( return_value={ "sessions": [ { "session_id": "web-1", "user_id": "human-1" } ] } )
    responder, listener = _drive_main( monkeypatch, fetch )
    listener.authorization = "Bearer renewed"             # read at each request, not at build time
    assert responder.user_connected_fn() is True
    fetch.assert_called_once_with( "http://srv:8123/api/websocket-sessions", { "Authorization": "Bearer renewed" } )


def test_main_excludes_the_proxys_own_session_from_the_feed( monkeypatch ):
    fetch = MagicMock( return_value={ "sessions": [ { "session_id": "proxy-own", "user_id": "human-1" } ] } )
    responder, _ = _drive_main( monkeypatch, fetch )
    assert responder.user_connected_fn() is False
