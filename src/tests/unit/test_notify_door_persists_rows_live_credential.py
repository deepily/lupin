"""
The two row-writing /api/notify integration tests send a credential the door can read (row c46ba7c0).

They used to put `api_key` in the query string; `require_api_key_or_jwt` reads headers, so both arrived
unauthenticated and answered 401 "Missing auth". They now log in and send a Bearer header. This file
drives the two tests against a RECORDING fake of requests.post, so nothing touches a server and no row
is written. The fake answers the login and the notify call from what it was actually sent.

Venue: :7999-eligible (no network, no state).
"""
import importlib.util
import os

import pytest

import cosa.utils.util as cu

PATH = os.path.join( cu.get_project_root(), "src/tests/integration/test_notify_door_persists_rows_live.py" )


class _Resp:
    def __init__( self, status, body, content_type="application/json" ):
        self.status_code = status
        self.headers     = { "content-type": content_type }
        self._body       = body
        self.text        = str( body )
    def json( self ): return self._body


@pytest.fixture
def mod( monkeypatch ):
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", "t@example.com" )
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD", "pw" )
    spec = importlib.util.spec_from_file_location( "notify_door_live", PATH )
    m    = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( m )
    m.calls = []

    def fake_post( url, **kw ):
        m.calls.append( ( url, kw ) )
        if url.endswith( "/auth/login" ):
            return _Resp( 200, { "tokens": { "access_token": "JWT-1" } } )
        auth = kw.get( "headers", { } ).get( "Authorization" )
        if auth != "Bearer JWT-1":
            return _Resp( 401, { "detail": "Missing auth. Provide X-API-Key or Authorization: Bearer <jwt>" } )
        if kw[ "params" ].get( "response_requested" ):
            return _Resp( 200, { "status": "offline", "response": "no", "default_used": "no" } )
        return _Resp( 200, { "status": "queued" } )

    monkeypatch.setattr( m.requests, "post", fake_post )
    return m


def _notify_calls( m ): return [ c for c in m.calls if c[ 0 ].endswith( "/api/notify" ) ]


def test_fire_and_forget_sends_the_bearer_header_and_no_query_key( mod ):
    mod.test_fire_and_forget_mode()
    ( _, kw ), = _notify_calls( mod )
    assert kw[ "headers" ] == { "Authorization": "Bearer JWT-1" }
    assert "api_key" not in kw[ "params" ]


def test_offline_with_default_sends_the_bearer_header_and_no_query_key( mod ):
    mod.test_offline_with_default()
    ( _, kw ), = _notify_calls( mod )
    assert kw[ "headers" ] == { "Authorization": "Bearer JWT-1" }
    assert "api_key" not in kw[ "params" ]
    assert kw[ "params" ][ "response_default" ] == "no"


def test_login_happens_once_for_both_tests( mod ):
    mod.test_fire_and_forget_mode()
    mod.test_offline_with_default()
    assert len( [ c for c in mod.calls if c[ 0 ].endswith( "/auth/login" ) ] ) == 1


def test_a_request_without_the_header_would_have_been_the_401_the_row_describes( mod ):
    """Control: the fake really refuses an unauthenticated call, so the passes above mean something."""
    r = mod.requests.post( f"{mod.BASE_URL}/api/notify", params={ "api_key": "x" } )
    assert r.status_code == 401 and r.text.startswith( "{'detail': 'Missing auth" )


def test_missing_credentials_name_the_env_vars( mod, monkeypatch ):
    monkeypatch.delenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    with pytest.raises( ValueError, match="LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" ):
        mod._bearer_headers()


def test_a_failed_login_is_named_as_a_harness_failure( mod, monkeypatch ):
    monkeypatch.setattr( mod.requests, "post", lambda url, **kw: _Resp( 401, { "detail": "bad" } ) )
    with pytest.raises( AssertionError, match="LOGIN FAILED with 401" ):
        mod._bearer_headers()
