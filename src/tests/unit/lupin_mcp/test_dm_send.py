"""
Unit tests for `_dm_send_impl` — the testable core of the `dm_send` MCP tool.

`dm_send` is the notification-native peer-DM tool (POST /api/notify-peer, body
inline) that replaces the deprecated commons claim-check DM path. HTTP is
injected via `post_fn`, so these tests need no live server.

Design: src/rnd/v0.1.8/2026.06.13-cosa-voice-token-reduction/02-notification-native-aixai-design.md
"""

from lupin_mcp.cosa_voice_mcp import _dm_send_impl


class _Resp:
    """Minimal stand-in for a requests.Response."""
    def __init__( self, status_code, json_data=None, text="" ):
        self.status_code = status_code
        self._json       = json_data
        self.text        = text

    def json( self ):
        if self._json is None:
            raise ValueError( "no json body" )
        return self._json


def _call( post_fn, api_key="k-123", recipient="tiberius", recipient_session_id=None,
           reply_to=None, thread_id=None ):
    return _dm_send_impl(
        recipient            = recipient,
        body                 = "ready for review",
        reply_to             = reply_to,
        thread_id            = thread_id,
        recipient_session_id = recipient_session_id,
        session_id           = "asker-sess-1",
        sender_persona       = "Mr. Radio",
        sender_icon          = "🦉",
        api_base_url         = "http://localhost:7999",
        api_key              = api_key,
        post_fn              = post_fn,
    )


def test_missing_api_key_short_circuits():
    """No outbound key → no HTTP attempt, explicit auth error."""
    calls = []
    out = _call( lambda *a, **k: calls.append( k ) or _Resp( 201, {} ), api_key=None )
    assert out[ "status" ] == "error"
    assert out[ "reason" ] == "missing_auth_header"
    assert calls == []   # post_fn never invoked


def test_201_returns_sent_and_merges_body():
    captured = {}
    def post_fn( url, json=None, headers=None, timeout=None ):
        captured.update( url=url, json=json, headers=headers )
        return _Resp( 201, { "message_id": "m1", "thread_id": "t1",
                             "recipient_session": "abcdef12", "recipient_persona": "Tiberius",
                             "dispatched": True } )
    out = _call( post_fn )
    assert out[ "status" ] == "sent"
    assert out[ "message_id" ] == "m1"
    assert out[ "thread_id" ] == "t1"
    # endpoint + payload shape
    assert captured[ "url" ].endswith( "/api/notify-peer" )
    assert captured[ "headers" ] == { "X-API-Key": "k-123" }
    assert captured[ "json" ][ "asker_session_id" ] == "asker-sess-1"
    assert captured[ "json" ][ "recipient_persona" ] == "tiberius"
    assert captured[ "json" ][ "sender_persona" ] == "Mr. Radio"
    assert captured[ "json" ][ "sender_icon" ] == "🦉"


def test_recipient_session_id_takes_precedence_over_persona():
    captured = {}
    def post_fn( url, json=None, headers=None, timeout=None ):
        captured.update( json=json )
        return _Resp( 201, {} )
    _call( post_fn, recipient="tiberius", recipient_session_id="sess-9999" )
    assert captured[ "json" ][ "recipient_session_id" ] == "sess-9999"
    assert "recipient_persona" not in captured[ "json" ]


def test_reply_to_and_thread_id_threaded_into_payload():
    captured = {}
    def post_fn( url, json=None, headers=None, timeout=None ):
        captured.update( json=json )
        return _Resp( 201, {} )
    _call( post_fn, reply_to="m-7", thread_id="th-7" )
    assert captured[ "json" ][ "reply_to" ] == "m-7"
    assert captured[ "json" ][ "thread_id" ] == "th-7"


def test_422_maps_to_recipient_unresolved():
    out = _call( lambda *a, **k: _Resp( 422, { "detail": { "error": "recipient_not_found" } } ) )
    assert out[ "status" ] == "error"
    assert out[ "reason" ] == "recipient_unresolved"
    assert out[ "detail" ][ "error" ] == "recipient_not_found"


def test_other_status_maps_to_http_reason():
    out = _call( lambda *a, **k: _Resp( 500, text="boom" ) )
    assert out[ "status" ] == "error"
    assert out[ "reason" ] == "http_500"
    assert out[ "detail" ] == "boom"


def test_transport_exception_maps_to_request_failed():
    def post_fn( *a, **k ):
        raise ConnectionError( "refused" )
    out = _call( post_fn )
    assert out[ "status" ] == "error"
    assert out[ "reason" ] == "request_failed"
    assert "refused" in out[ "detail" ]
