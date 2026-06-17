"""
Unit tests for the DM-verb MCP tool cores in lupin_mcp.cosa_voice_mcp:
_dm_respond_impl / _dm_get_impl / _dm_list_impl — to 100% line + branch + function.

HTTP is injected via post_fn / get_fn, so these tests need no live server
(mirrors test_dm_send.py).

Design: src/rnd/v0.1.8/2026.06.16-dm-api-namespace-design.md §5
"""

from lupin_mcp.cosa_voice_mcp import _dm_respond_impl, _dm_get_impl, _dm_list_impl


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


# ─────────────────────────────────────────────────────────────────────────────
# _dm_respond_impl
# ─────────────────────────────────────────────────────────────────────────────

def _respond( post_fn, api_key="k-123", recipient="tiberius", recipient_session_id=None ):
    return _dm_respond_impl(
        recipient            = recipient,
        body                 = "yes — commit f4e0370",
        reply_to             = "m-7",
        thread_id            = "th-7",
        recipient_session_id = recipient_session_id,
        session_id           = "asker-sess-1",
        sender_persona       = "Clayton",
        sender_icon          = "😎",
        api_base_url         = "http://localhost:7999",
        api_key              = api_key,
        post_fn              = post_fn,
    )


def test_respond_missing_api_key_short_circuits():
    calls = []
    out = _respond( lambda *a, **k: calls.append( k ) or _Resp( 201, {} ), api_key=None )
    assert out[ "status" ] == "error"
    assert out[ "reason" ] == "missing_auth_header"
    assert calls == []


def test_respond_201_targets_respond_endpoint_with_threading():
    captured = {}
    def post_fn( url, json=None, headers=None, timeout=None ):
        captured.update( url=url, json=json, headers=headers )
        return _Resp( 201, { "message_id": "m1", "thread_id": "th-7" } )
    out = _respond( post_fn )
    assert out[ "status" ] == "sent"
    assert out[ "message_id" ] == "m1"
    assert captured[ "url" ].endswith( "/api/dm/respond" )
    assert captured[ "json" ][ "reply_to" ] == "m-7"
    assert captured[ "json" ][ "thread_id" ] == "th-7"
    assert captured[ "json" ][ "recipient_persona" ] == "tiberius"
    assert captured[ "headers" ] == { "X-API-Key": "k-123" }


def test_respond_recipient_session_id_takes_precedence():
    captured = {}
    def post_fn( url, json=None, headers=None, timeout=None ):
        captured.update( json=json )
        return _Resp( 201, {} )
    _respond( post_fn, recipient="tiberius", recipient_session_id="sess-9999" )
    assert captured[ "json" ][ "recipient_session_id" ] == "sess-9999"
    assert "recipient_persona" not in captured[ "json" ]


def test_respond_422_maps_to_recipient_unresolved():
    out = _respond( lambda *a, **k: _Resp( 422, { "detail": { "error": "recipient_not_found" } } ) )
    assert out[ "reason" ] == "recipient_unresolved"
    assert out[ "detail" ][ "error" ] == "recipient_not_found"


def test_respond_422_non_json_falls_back_to_text():
    out = _respond( lambda *a, **k: _Resp( 422, json_data=None, text="boom-text" ) )
    assert out[ "reason" ] == "recipient_unresolved"
    assert out[ "detail" ] == "boom-text"


def test_respond_other_status_maps_to_http_reason():
    out = _respond( lambda *a, **k: _Resp( 500, text="kaboom" ) )
    assert out[ "reason" ] == "http_500"
    assert out[ "detail" ] == "kaboom"


def test_respond_transport_exception():
    def post_fn( *a, **k ):
        raise ConnectionError( "refused" )
    out = _respond( post_fn )
    assert out[ "reason" ] == "request_failed"
    assert "refused" in out[ "detail" ]


# ─────────────────────────────────────────────────────────────────────────────
# _dm_get_impl
# ─────────────────────────────────────────────────────────────────────────────

def _get( get_fn, api_key="k-123" ):
    return _dm_get_impl(
        message_id   = "33333333-3333-3333-3333-333333333333",
        api_base_url = "http://localhost:7999",
        api_key      = api_key,
        get_fn       = get_fn,
    )


def test_get_missing_api_key_short_circuits():
    calls = []
    out = _get( lambda *a, **k: calls.append( k ) or _Resp( 200, {} ), api_key=None )
    assert out[ "reason" ] == "missing_auth_header"
    assert calls == []


def test_get_200_returns_ok_and_merges_dm():
    captured = {}
    def get_fn( url, params=None, headers=None, timeout=None ):
        captured.update( url=url, params=params )
        return _Resp( 200, { "message_id": "m1", "body": "hi" } )
    out = _get( get_fn )
    assert out[ "status" ] == "ok"
    assert out[ "body" ] == "hi"
    assert captured[ "url" ].endswith( "/api/dm/get" )
    assert captured[ "params" ] == { "message_id": "33333333-3333-3333-3333-333333333333" }


def test_get_404_maps_to_not_found():
    out = _get( lambda *a, **k: _Resp( 404, text="DM not found" ) )
    assert out[ "reason" ] == "not_found"
    assert out[ "detail" ] == "DM not found"


def test_get_400_maps_to_bad_request():
    out = _get( lambda *a, **k: _Resp( 400, text="invalid message_id" ) )
    assert out[ "reason" ] == "bad_request"


def test_get_other_status_maps_to_http_reason():
    out = _get( lambda *a, **k: _Resp( 503, text="down" ) )
    assert out[ "reason" ] == "http_503"


def test_get_transport_exception():
    def get_fn( *a, **k ):
        raise ConnectionError( "refused" )
    out = _get( get_fn )
    assert out[ "reason" ] == "request_failed"
    assert "refused" in out[ "detail" ]


# ─────────────────────────────────────────────────────────────────────────────
# _dm_list_impl
# ─────────────────────────────────────────────────────────────────────────────

def _list( get_fn, api_key="k-123", thread_id=None, since=None, limit=50 ):
    return _dm_list_impl(
        thread_id    = thread_id,
        since        = since,
        limit        = limit,
        api_base_url = "http://localhost:7999",
        api_key      = api_key,
        get_fn       = get_fn,
    )


def test_list_missing_api_key_short_circuits():
    calls = []
    out = _list( lambda *a, **k: calls.append( k ) or _Resp( 200, {} ), api_key=None )
    assert out[ "reason" ] == "missing_auth_header"
    assert calls == []


def test_list_200_inbox_sends_only_limit():
    captured = {}
    def get_fn( url, params=None, headers=None, timeout=None ):
        captured.update( url=url, params=params )
        return _Resp( 200, { "count": 0, "messages": [] } )
    out = _list( get_fn )
    assert out[ "status" ] == "ok"
    assert out[ "count" ] == 0
    assert captured[ "url" ].endswith( "/api/dm/list" )
    assert captured[ "params" ] == { "limit": 50 }   # no thread_id / since


def test_list_200_thread_and_since_in_params():
    captured = {}
    def get_fn( url, params=None, headers=None, timeout=None ):
        captured.update( params=params )
        return _Resp( 200, { "count": 1, "messages": [ { "body": "x" } ] } )
    out = _list( get_fn, thread_id="th-9", since="2026-06-17T00:00:00+00:00", limit=25 )
    assert out[ "status" ] == "ok"
    assert captured[ "params" ] == {
        "limit"     : 25,
        "thread_id" : "th-9",
        "since"     : "2026-06-17T00:00:00+00:00",
    }


def test_list_400_maps_to_bad_request():
    out = _list( lambda *a, **k: _Resp( 400, text="invalid 'since'" ) )
    assert out[ "reason" ] == "bad_request"


def test_list_other_status_maps_to_http_reason():
    out = _list( lambda *a, **k: _Resp( 500, text="oops" ) )
    assert out[ "reason" ] == "http_500"


def test_list_transport_exception():
    def get_fn( *a, **k ):
        raise TimeoutError( "slow" )
    out = _list( get_fn )
    assert out[ "reason" ] == "request_failed"
    assert "slow" in out[ "detail" ]


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
