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


# ═════════════════════════════════════════════════════════════════════════════
# query_owed — Spine Step-2 store-count owed reader (100% L/B/F)
# ═════════════════════════════════════════════════════════════════════════════

OWED = ( "queued", "in_progress" )


@pytest.fixture
def capture_seq( monkeypatch ):
    """
    urlopen stand-in that serves a QUEUE of outcomes (one per query_owed call)
    and records EVERY Request + timeout. An outcome that is an Exception is
    raised (transport/HTTP failure); otherwise it's returned. Running past the
    queue is a test bug surfaced loudly (IndexError), proving call-count.
    """
    state = { "requests": [ ], "timeouts": [ ], "outcomes": [ ] }

    def fake_urlopen( request, timeout=None ):
        state[ "requests" ].append( request )
        state[ "timeouts" ].append( timeout )
        outcome = state[ "outcomes" ].pop( 0 )
        if isinstance( outcome, Exception ):
            raise outcome
        return outcome

    monkeypatch.setattr( tc.urllib.request, "urlopen", fake_urlopen )
    return state


def _rows( count ):
    return FakeResponse( 200, json.dumps( { "tasks": [ ], "count": count } ) )


class TestQueryOwed:

    def test_sums_counts_across_statuses( self, capture_seq ):
        capture_seq[ "outcomes" ] = [ _rows( 2 ), _rows( 3 ) ]
        ok, count = tc.query_owed( SETTINGS, "k", "krishna", OWED, project="lupin" )
        assert ( ok, count ) == ( True, 5 )
        # one GET per owed status, owner + status + project all wired
        assert len( capture_seq[ "requests" ] ) == 2
        urls = [ r.full_url for r in capture_seq[ "requests" ] ]
        assert all( u.startswith( "http://test:7999/api/tasks?" ) for u in urls )
        assert "owner_persona=krishna" in urls[ 0 ] and "status=queued" in urls[ 0 ] and "project=lupin" in urls[ 0 ]
        assert "status=in_progress" in urls[ 1 ]
        assert capture_seq[ "requests" ][ 0 ].get_method() == "GET"

    def test_store_up_zero_rows_is_ok_zero( self, capture_seq ):
        capture_seq[ "outcomes" ] = [ _rows( 0 ), _rows( 0 ) ]
        assert tc.query_owed( SETTINGS, "k", "p", OWED ) == ( True, 0 )

    def test_count_only_true_on_every_owed_query( self, capture_seq ):
        # O2 / §G: each owed query rides count_only=true so the server returns a
        # true COUNT(*), never a page-length saturating at the endpoint's limit.
        capture_seq[ "outcomes" ] = [ _rows( 250 ), _rows( 175 ) ]
        ok, count = tc.query_owed( SETTINGS, "k", "p", OWED )
        assert ( ok, count ) == ( True, 425 )                 # >100 counted exactly, no saturation
        urls = [ r.full_url for r in capture_seq[ "requests" ] ]
        assert all( "count_only=true" in u for u in urls )

    def test_transport_failure_short_circuits( self, capture_seq ):
        # first status raises (refused) → return immediately, second never attempted
        capture_seq[ "outcomes" ] = [ ConnectionRefusedError( "refused" ), _rows( 9 ) ]
        assert tc.query_owed( SETTINGS, "k", "p", OWED ) == ( False, 0 )
        assert len( capture_seq[ "requests" ] ) == 1          # short-circuit proven

    def test_timeout_is_not_ok( self, capture_seq ):
        capture_seq[ "outcomes" ] = [ TimeoutError( "slow store" ) ]
        assert tc.query_owed( SETTINGS, "k", "p", OWED ) == ( False, 0 )

    def test_http_error_is_not_ok( self, capture_seq ):
        capture_seq[ "outcomes" ] = [ http_error( 500, '{"detail": "boom"}' ) ]
        assert tc.query_owed( SETTINGS, "k", "p", OWED ) == ( False, 0 )

    def test_malformed_missing_count( self, capture_seq ):
        capture_seq[ "outcomes" ] = [ FakeResponse( 200, '{"tasks": []}' ) ]
        assert tc.query_owed( SETTINGS, "k", "p", OWED ) == ( False, 0 )

    def test_malformed_non_int_count( self, capture_seq ):
        capture_seq[ "outcomes" ] = [ FakeResponse( 200, '{"count": "5"}' ) ]
        assert tc.query_owed( SETTINGS, "k", "p", OWED ) == ( False, 0 )

    def test_malformed_bool_count_rejected( self, capture_seq ):
        # JSON `true` is a bool (an int subclass) — must NOT slip through as 1
        capture_seq[ "outcomes" ] = [ FakeResponse( 200, '{"count": true}' ) ]
        assert tc.query_owed( SETTINGS, "k", "p", OWED ) == ( False, 0 )

    def test_empty_statuses_is_ok_zero_no_calls( self, capture_seq ):
        capture_seq[ "outcomes" ] = [ ]
        assert tc.query_owed( SETTINGS, "k", "p", () ) == ( True, 0 )
        assert capture_seq[ "requests" ] == [ ]

    def test_project_omitted_when_none( self, capture_seq ):
        capture_seq[ "outcomes" ] = [ _rows( 1 ) ]
        tc.query_owed( SETTINGS, "k", "p", ( "queued", ) )            # no project
        assert "project=" not in capture_seq[ "requests" ][ 0 ].full_url

    def test_uses_bounded_default_timeout( self, capture_seq ):
        capture_seq[ "outcomes" ] = [ _rows( 0 ) ]
        tc.query_owed( SETTINGS, "k", "p", ( "queued", ) )
        # §C/§J6: the Stop-hot-path read is bounded by an aggressive default
        assert capture_seq[ "timeouts" ][ 0 ] == tc.DEFAULT_OWED_TIMEOUT_SECONDS
        assert tc.DEFAULT_OWED_TIMEOUT_SECONDS <= 2.0                 # never stalls turn-end

    def test_timeout_override_passed_through( self, capture_seq ):
        capture_seq[ "outcomes" ] = [ _rows( 0 ) ]
        tc.query_owed( SETTINGS, "k", "p", ( "queued", ), timeout=0.5 )
        assert capture_seq[ "timeouts" ][ 0 ] == 0.5
