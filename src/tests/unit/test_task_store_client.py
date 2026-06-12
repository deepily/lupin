#!/usr/bin/env python3
"""
Unit tests — task-store hook-side REST client (Phase 2).

Venue: :7999-eligible / local — urllib fully mocked, key file under tmp_path.
Covers read_api_key / _request / create_task / transition_task /
correlate_task / query_by_correlation_key to 100% lines/branches/functions.
The module contract under test: uniform ( ok, status, body ) and NEVER raises.
"""
import io
import json
import os
import sys
import urllib.error

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib import task_store_client as tc

SETTINGS = { "api_base_url": "http://test:7999", "timeout_seconds": 3.0 }


class FakeResponse:
    """Minimal context-manager stand-in for urlopen's response."""

    def __init__( self, status, body ):
        self.status = status
        self._body  = body

    def read( self ):
        return self._body.encode( "utf-8" )

    def __enter__( self ):
        return self

    def __exit__( self, *args ):
        return False


def http_error( code, body ):
    return urllib.error.HTTPError( "http://test", code, "err", {}, io.BytesIO( body.encode( "utf-8" ) ) )


@pytest.fixture
def capture( monkeypatch ):
    """Patch urlopen; capture the Request; let the test choose the outcome."""
    state = { "request": None, "outcome": FakeResponse( 200, "{}" ) }

    def fake_urlopen( request, timeout=None ):
        state[ "request" ] = request
        state[ "timeout" ] = timeout
        outcome = state[ "outcome" ]
        if isinstance( outcome, Exception ):
            raise outcome
        return outcome

    monkeypatch.setattr( tc.urllib.request, "urlopen", fake_urlopen )
    return state


class TestReadApiKey:

    def test_reads_and_strips_key( self, tmp_path ):
        key_file = tmp_path / tc.KEY_FILE_RELATIVE
        key_file.parent.mkdir( parents=True )
        key_file.write_text( "  secret-key \n" )
        assert tc.read_api_key( { "LUPIN_ROOT": str( tmp_path ) } ) == "secret-key"

    def test_unset_root_is_empty( self ):
        assert tc.read_api_key( { } ) == ""

    def test_missing_file_is_empty( self, tmp_path ):
        assert tc.read_api_key( { "LUPIN_ROOT": str( tmp_path ) } ) == ""

    def test_environ_none_uses_os_environ( self, monkeypatch, tmp_path ):
        key_file = tmp_path / tc.KEY_FILE_RELATIVE
        key_file.parent.mkdir( parents=True )
        key_file.write_text( "k" )
        monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )
        assert tc.read_api_key() == "k"


class TestRequestOutcomes:

    def test_success_parses_json( self, capture ):
        capture[ "outcome" ] = FakeResponse( 201, '{"id": "u1"}' )
        ok, status, body = tc.create_task( SETTINGS, "k", { "title": "t" } )
        assert ( ok, status, body ) == ( True, 201, { "id": "u1" } )

    def test_http_error_returns_parsed_detail( self, capture ):
        capture[ "outcome" ] = http_error( 422, '{"detail": {"errors": ["bad"]}}' )
        ok, status, body = tc.create_task( SETTINGS, "k", { } )
        assert ( ok, status ) == ( False, 422 )
        assert body[ "detail" ][ "errors" ] == [ "bad" ]

    def test_http_error_with_unparseable_body( self, capture ):
        capture[ "outcome" ] = http_error( 500, "<html>oops</html>" )
        ok, status, body = tc.create_task( SETTINGS, "k", { } )
        assert ( ok, status ) == ( False, 500 )
        assert "error" in body

    def test_http_error_with_non_dict_json_body( self, capture ):
        capture[ "outcome" ] = http_error( 400, '["a", "b"]' )
        ok, status, body = tc.create_task( SETTINGS, "k", { } )
        assert ( ok, status ) == ( False, 400 )
        assert body == { "error": [ "a", "b" ] }

    def test_transport_failure_status_is_none( self, capture ):
        capture[ "outcome" ] = ConnectionRefusedError( "refused" )
        ok, status, body = tc.create_task( SETTINGS, "k", { } )
        assert ( ok, status ) == ( False, None )
        assert "ConnectionRefusedError" in body[ "error" ]

    def test_timeout_is_transport_failure( self, capture ):
        capture[ "outcome" ] = TimeoutError( "timed out" )
        ok, status, body = tc.create_task( SETTINGS, "k", { } )
        assert ( ok, status ) == ( False, None )

    def test_unparseable_success_body_not_ok( self, capture ):
        capture[ "outcome" ] = FakeResponse( 200, "not json" )
        ok, status, body = tc.create_task( SETTINGS, "k", { } )
        assert ( ok, status ) == ( False, 200 )
        assert "unparseable" in body[ "error" ]

    def test_non_object_success_body_not_ok( self, capture ):
        capture[ "outcome" ] = FakeResponse( 200, "[1]" )
        ok, status, body = tc.create_task( SETTINGS, "k", { } )
        assert ( ok, status ) == ( False, 200 )
        assert "non-object" in body[ "error" ]


class TestWireShape:

    def test_create_posts_payload_with_key_header( self, capture ):
        tc.create_task( SETTINGS, "the-key", { "title": "t" } )
        req = capture[ "request" ]
        assert req.full_url == "http://test:7999/api/tasks"
        assert req.get_method() == "POST"
        assert req.get_header( "X-api-key" ) == "the-key"
        assert json.loads( req.data.decode() ) == { "title": "t" }
        assert capture[ "timeout" ] == 3.0

    def test_transition_url_embeds_item_id( self, capture ):
        tc.transition_task( SETTINGS, "k", "uuid-1", { "to_status": "review" } )
        assert capture[ "request" ].full_url == "http://test:7999/api/tasks/uuid-1/transition"

    def test_correlate_url_embeds_item_id( self, capture ):
        tc.correlate_task( SETTINGS, "k", "uuid-2", { "correlation_key": "ck" } )
        assert capture[ "request" ].full_url == "http://test:7999/api/tasks/uuid-2/correlate"

    def test_query_encodes_correlation_key( self, capture ):
        capture[ "outcome" ] = FakeResponse( 200, '{"tasks": [], "count": 0}' )
        ok, status, body = tc.query_by_correlation_key( SETTINGS, "k", "cc-task:sid:1" )
        req = capture[ "request" ]
        assert req.get_method() == "GET"
        assert req.data is None
        assert req.full_url == "http://test:7999/api/tasks?correlation_key=cc-task%3Asid%3A1"
        assert ok is True
