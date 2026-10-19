"""
Pins the wiring in POST /api/dm/send and POST /api/dm/respond.

execute_dm_send is replaced by a recorder, so these tests read what each route hands it.
That is the request model, the user, the queue, and the three seams.
The seams are then called to see what they do.
Nothing reaches a database or a session bridge.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest.routers import dm
from cosa.rest.routers.notifications import get_notification_queue

USER  = "11111111-2222-3333-4444-555555555555"
QUEUE = object()

SEND_JSON    = { "sender_session_id": "sid-a", "sender_project": "lupin", "body": "hello", "recipient_persona": "radio" }
RESPOND_JSON = { **SEND_JSON, "reply_to": "m-1", "thread_id": "t-1" }
ROUTES = [ ( "/api/dm/send", SEND_JSON, dm.DmSendRequest ), ( "/api/dm/respond", RESPOND_JSON, dm.DmRespondRequest ) ]


class Recorder:
    """Stands in for execute_dm_send; answers with the dict it was told to."""

    def __init__( self, answer ):
        self.answer = answer
        self.calls  = []

    def __call__( self, **kwargs ):
        self.calls.append( kwargs )
        return dict( self.answer )


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router( dm.router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: USER
    app.dependency_overrides[ get_notification_queue ] = lambda: QUEUE
    return TestClient( app )


def post( client, monkeypatch, path, payload, answer ):
    recorder = Recorder( answer )
    monkeypatch.setattr( dm, "execute_dm_send", recorder )
    return client.post( path, json=payload ), recorder


@pytest.mark.parametrize( "path, payload, model", ROUTES )
class TestRoute:

    def test_a_201_answer_is_returned_without_its_http_status_key( self, client, monkeypatch, path, payload, model ):
        resp, _ = post( client, monkeypatch, path, payload, { "http_status": 201, "message_id": "m", "thread_id": "t" } )
        assert resp.status_code == 201
        assert resp.json() == { "message_id": "m", "thread_id": "t" }

    @pytest.mark.parametrize( "status", [ 400, 404, 422, 500 ] )
    def test_an_error_status_becomes_an_http_exception_carrying_the_detail( self, client, monkeypatch, path, payload, model, status ):
        detail = { "error": "recipient_unresolved", "n": status }
        resp, _ = post( client, monkeypatch, path, payload, { "http_status": status, "detail": detail } )
        assert resp.status_code == status
        assert resp.json() == { "detail": detail }

    def test_a_status_under_400_is_a_json_response_with_that_status( self, client, monkeypatch, path, payload, model ):
        resp, _ = post( client, monkeypatch, path, payload, { "http_status": 202, "ok": True } )
        assert resp.status_code == 202 and resp.json() == { "ok": True }

    def test_execute_dm_send_is_called_once_with_the_user_queue_model_and_three_seams( self, client, monkeypatch, path, payload, model ):
        _, rec = post( client, monkeypatch, path, payload, { "http_status": 201 } )
        assert len( rec.calls ) == 1
        call = rec.calls[ 0 ]
        assert sorted( call ) == sorted( [ "authenticated_user_id", "body", "notification_queue", "resolve_recipient_fn", "build_sender_id", "persist_fn" ] )
        assert call[ "authenticated_user_id" ] == USER
        assert call[ "notification_queue" ] is QUEUE
        assert isinstance( call[ "body" ], model ) and call[ "body" ].body == "hello"
        assert call[ "persist_fn" ] is dm._persist_dm_send_sync

    def test_the_persist_seam_is_read_when_the_request_arrives( self, client, monkeypatch, path, payload, model ):
        sentinel = lambda **kw: "x"
        monkeypatch.setattr( dm, "_persist_dm_send_sync", sentinel )
        _, rec = post( client, monkeypatch, path, payload, { "http_status": 201 } )
        assert rec.calls[ 0 ][ "persist_fn" ] is sentinel

    def test_the_resolver_seam_asks_commons_with_null_persona_sessions_included( self, client, monkeypatch, path, payload, model ):
        from cosa.rest.routers import commons
        from lupin_cli.claude_code.hooks.lib import session_bridge
        seen = {}

        def fake_resolve( **kwargs ):
            seen.update( kwargs )
            return "RESOLVED"

        monkeypatch.setattr( commons, "_resolve_dm_recipient", fake_resolve )
        monkeypatch.setattr( commons, "_active_session_threshold_seconds", 123.5, raising=False )
        sessions_asked = []
        monkeypatch.setattr( session_bridge, "find_active_sessions", lambda **kw: sessions_asked.append( kw ) or [ "S" ] )
        _, rec = post( client, monkeypatch, path, payload, { "http_status": 201 } )

        answer = rec.calls[ 0 ][ "resolve_recipient_fn" ]( "sid-x", "persona-x", "user-x" )
        assert answer == "RESOLVED"
        assert seen[ "recipient_session_id" ] == "sid-x"
        assert seen[ "recipient_persona" ] == "persona-x"
        assert seen[ "authenticated_user_id" ] == "user-x"
        assert seen[ "bridge_loader" ] is commons._load_bridge_fields
        assert seen[ "active_session_threshold_seconds" ] == 123.5
        assert seen[ "raw_sessions_fn" ]() == [ "S" ]
        assert sessions_asked == [ { "require_persona": False } ]
        assert sorted( seen ) == sorted( [ "recipient_session_id", "recipient_persona", "authenticated_user_id",
                                           "raw_sessions_fn", "bridge_loader", "active_session_threshold_seconds" ] )

    def test_the_threshold_falls_back_to_600_seconds_when_commons_has_none( self, client, monkeypatch, path, payload, model ):
        from cosa.rest.routers import commons
        seen = {}
        monkeypatch.setattr( commons, "_resolve_dm_recipient", lambda **kw: seen.update( kw ) )
        monkeypatch.delattr( commons, "_active_session_threshold_seconds", raising=False )
        _, rec = post( client, monkeypatch, path, payload, { "http_status": 201 } )
        rec.calls[ 0 ][ "resolve_recipient_fn" ]( None, "p", USER )
        assert seen[ "active_session_threshold_seconds" ] == 600.0

    def test_the_sender_id_seam_uses_the_hosts_builder_unless_a_project_is_given( self, client, monkeypatch, path, payload, model ):
        from lupin_cli.claude_code.hooks.lib import session_bridge
        monkeypatch.setattr( session_bridge, "build_sender_id_for_cc", lambda session_id=None: f"host#{ session_id }" )
        _, rec = post( client, monkeypatch, path, payload, { "http_status": 201 } )
        build = rec.calls[ 0 ][ "build_sender_id" ]
        assert build( "abcdefgh1" ) == "host#abcdefgh1"
        assert build( "abcdefgh1", project="lupin" ) == "claude.code@lupin.deepily.ai#abcdefgh1"

    def test_the_handler_hands_the_core_to_asyncio_to_thread( self, client, monkeypatch, path, payload, model ):
        import asyncio
        handed = []
        real   = asyncio.to_thread

        async def spy( fn, *args, **kwargs ):
            handed.append( fn )
            return await real( fn, *args, **kwargs )

        monkeypatch.setattr( dm.asyncio, "to_thread", spy )
        rec = Recorder( { "http_status": 201 } )
        monkeypatch.setattr( dm, "execute_dm_send", rec )
        client.post( path, json=payload )
        assert handed == [ rec ]
