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
# query_owed — Spine Step-2 store-count owed reader, O3 connection-reuse path
# (_open_owed_connection + _count_on_connection + query_owed) — 100% L/B/F
# ═════════════════════════════════════════════════════════════════════════════

# The OWED status tuple was DELETED here on 2026-07-19 (PARKED-STATUS). `query_owed`
# no longer takes a `statuses` argument — the owed set is defined SERVER-side behind
# `owed_only=true`. Deleted rather than left unused: a stale constant is the thing the
# next reader re-wires a test to, and this one had already forked into four copies
# across stop.py / task_store_drain.py / here.


class FakeHTTPResponse:
    """Minimal http.client response stand-in — only .status + .read()."""

    def __init__( self, status, body ):
        self.status = status
        self._body  = body

    def read( self ):
        return self._body.encode( "utf-8" )


@pytest.fixture
def conn_seq( monkeypatch ):
    """
    http.client connection stand-in for the O3 reuse path. Serves a QUEUE of
    per-request outcomes (one per status query); an Exception outcome is RAISED
    from .request() (transport failure), otherwise it's the .getresponse() body.
    Records every constructed connection (host/port/timeout/scheme), every
    request path, and the close() count — so a test can prove ONE reused socket
    across N statuses (the O3 win) and that it is always released.
    """
    state = {
        "ctor"     : [ ],   # one dict per connection constructed
        "requests" : [ ],   # ( method, path, headers ) per .request()
        "outcomes" : [ ],   # FakeHTTPResponse | Exception, popped per request
        "closed"   : 0,     # .close() call count
    }

    class _FakeConn:
        def __init__( self, host, port, timeout=None, scheme="http" ):
            state[ "ctor" ].append( { "host": host, "port": port, "timeout": timeout, "scheme": scheme } )
            self._resp = None

        def request( self, method, path, headers=None ):
            state[ "requests" ].append( ( method, path, headers ) )
            outcome = state[ "outcomes" ].pop( 0 )
            if isinstance( outcome, Exception ):
                raise outcome
            self._resp = outcome

        def getresponse( self ):
            return self._resp

        def close( self ):
            state[ "closed" ] += 1

    def _http_ctor( host, port, timeout=None ):
        return _FakeConn( host, port, timeout=timeout, scheme="http" )

    def _https_ctor( host, port, timeout=None ):
        return _FakeConn( host, port, timeout=timeout, scheme="https" )

    monkeypatch.setattr( tc.http.client, "HTTPConnection", _http_ctor )
    monkeypatch.setattr( tc.http.client, "HTTPSConnection", _https_ctor )
    return state


def _count_resp( count ):
    return FakeHTTPResponse( 200, json.dumps( { "count": count } ) )


class TestQueryOwed:
    """
    PARKED-STATUS REWRITE (2026-07-19, Rachel 🕊️ seat 3).

    `query_owed` no longer takes a `statuses` tuple. The owed set moved SERVER-side
    behind a single `owed_only=true` flag, so this class pins the ONE-CALL shape.

    THREE TESTS WERE DELETED RATHER THAN RE-POINTED, deliberately:

      · test_sums_counts_across_statuses      — pinned the per-status LOOP + SUM
      · test_connection_reused_across_statuses — pinned socket reuse ACROSS the loop
      · test_empty_statuses_is_ok_zero_no_socket — pinned the empty-tuple short-circuit

    All three tested a MECHANISM THAT NO LONGER EXISTS. Re-pointing them at the new
    shape would have preserved the appearance of coverage while asserting nothing:
    there is no loop to sum, no second status to reuse a socket across, and no tuple
    to be empty. Per Mr. Radio's ruling, a test whose subject died should die with it
    rather than be quietly re-aimed. Their surviving VALUE — one socket, closed once,
    exactly one request — is asserted by test_single_request_one_socket_closed_once.

    ⚠️ The old `OWED` tuple was also passed POSITIONALLY as the 4th argument in most
    of these tests. Under the new signature that slot is `project`, so those calls
    were silently sending a tuple as the project filter and passing for the wrong
    reason. All call sites now use keyword arguments.
    """

    def test_single_request_owed_only_no_status_enumeration( self, conn_seq ):
        """
        THE SHAPE PIN. Exactly ONE request, carrying owed_only=true and NO status
        parameter.

        Asserted on the SHAPE, not just the answer: a re-introduced per-status loop
        can return a correct total on a board with no parked rows and still be
        broken the moment one expires. Shape divergence is silent; this makes it loud.
        """
        conn_seq[ "outcomes" ] = [ _count_resp( 5 ) ]
        ok, count = tc.query_owed( SETTINGS, "k", "krishna", project="lupin" )
        assert ( ok, count ) == ( True, 5 )

        assert len( conn_seq[ "requests" ] ) == 1, "more than one request — the per-status loop is back"
        method, path, headers = conn_seq[ "requests" ][ 0 ]
        assert path.startswith( "/api/tasks?" )
        assert "owed_only=true" in path
        assert "status=" not in path, "a status filter leaked back into the owed count"
        assert "owner_persona=krishna" in path and "project=lupin" in path
        assert method == "GET" and headers == { "X-API-Key": "k" }

    def test_expired_park_cannot_double_count( self, conn_seq ):
        """
        🔴 THE DOUBLE-COUNT GUARD at the transport seam (Krishna 🦚's defect #4).

        The retired loop fired one count per status and SUMMED. With server-side
        admission an expired-parked row would be admitted on the `queued` pass AND
        the `in_progress` pass — counted TWICE, making a parked board look BUSIER
        than an unparked one.

        One request means the server's number is returned VERBATIM. Asserted as an
        exact equality against a single seeded response: if any summation is ever
        reintroduced, the returned value diverges from the response the store gave.
        """
        conn_seq[ "outcomes" ] = [ _count_resp( 7 ) ]
        ok, count = tc.query_owed( SETTINGS, "k", "p", project="lupin" )
        assert ( ok, count ) == ( True, 7 ), "count is not the server's number verbatim — summation reintroduced?"
        assert len( conn_seq[ "requests" ] ) == 1

    def test_single_request_one_socket_closed_once( self, conn_seq ):
        """
        O3, carried forward from the deleted reuse test: one socket, one request,
        closed exactly once. The reuse WIN is gone with the loop; the release
        DISCIPLINE is not.
        """
        conn_seq[ "outcomes" ] = [ _count_resp( 1 ) ]
        tc.query_owed( SETTINGS, "k", "p" )
        assert len( conn_seq[ "ctor" ] ) == 1
        assert len( conn_seq[ "requests" ] ) == 1
        assert conn_seq[ "closed" ] == 1

    def test_owner_field_defaults_to_owner_persona( self, conn_seq ):
        # Default owner_field preserves the owed-count behavior (filters owner_persona).
        conn_seq[ "outcomes" ] = [ _count_resp( 1 ) ]
        tc.query_owed( SETTINGS, "k", "krishna", project="lupin" )
        _method, path, _headers = conn_seq[ "requests" ][ 0 ]
        assert "owner_persona=krishna" in path and "accountable_manager" not in path

    def test_owner_field_accountable_manager_filters_chase_list( self, conn_seq ):
        # Face A (proactive-manager A1): owner_field="accountable_manager" counts a
        # manager's chase-list instead of its own owned rows.
        conn_seq[ "outcomes" ] = [ _count_resp( 6 ) ]
        ok, count = tc.query_owed( SETTINGS, "k", "mr radio", project="lupin",
                                   owner_field="accountable_manager" )
        assert ( ok, count ) == ( True, 6 )
        _method, path, _headers = conn_seq[ "requests" ][ 0 ]
        assert "accountable_manager=mr+radio" in path and "owner_persona" not in path

    def test_store_up_zero_rows_is_ok_zero( self, conn_seq ):
        conn_seq[ "outcomes" ] = [ _count_resp( 0 ) ]
        assert tc.query_owed( SETTINGS, "k", "p" ) == ( True, 0 )

    def test_count_only_true_on_the_owed_query( self, conn_seq ):
        # O2 / §G: the owed query rides count_only=true so the server returns a true
        # COUNT(*), never a page-length saturating at the endpoint's limit.
        conn_seq[ "outcomes" ] = [ _count_resp( 425 ) ]
        ok, count = tc.query_owed( SETTINGS, "k", "p" )
        assert ( ok, count ) == ( True, 425 )                 # >100 counted exactly, no saturation
        _method, path, _headers = conn_seq[ "requests" ][ 0 ]
        assert "count_only=true" in path

    def test_transport_failure_is_not_ok_and_closes( self, conn_seq ):
        # The request raises (refused) → fail safe, and the connection is STILL
        # closed (finally). The old "short-circuit" half died with the loop.
        conn_seq[ "outcomes" ] = [ ConnectionRefusedError( "refused" ) ]
        assert tc.query_owed( SETTINGS, "k", "p" ) == ( False, 0 )
        assert conn_seq[ "closed" ] == 1                      # released even on failure

    def test_timeout_is_not_ok( self, conn_seq ):
        conn_seq[ "outcomes" ] = [ TimeoutError( "slow store" ) ]
        assert tc.query_owed( SETTINGS, "k", "p" ) == ( False, 0 )

    def test_http_error_is_not_ok( self, conn_seq ):
        conn_seq[ "outcomes" ] = [ FakeHTTPResponse( 500, '{"detail": "boom"}' ) ]
        assert tc.query_owed( SETTINGS, "k", "p" ) == ( False, 0 )

    def test_malformed_unparseable_body( self, conn_seq ):
        conn_seq[ "outcomes" ] = [ FakeHTTPResponse( 200, "not json" ) ]
        assert tc.query_owed( SETTINGS, "k", "p" ) == ( False, 0 )

    def test_malformed_non_dict_body( self, conn_seq ):
        conn_seq[ "outcomes" ] = [ FakeHTTPResponse( 200, "[1]" ) ]
        assert tc.query_owed( SETTINGS, "k", "p" ) == ( False, 0 )

    def test_malformed_missing_count( self, conn_seq ):
        conn_seq[ "outcomes" ] = [ FakeHTTPResponse( 200, '{"tasks": []}' ) ]
        assert tc.query_owed( SETTINGS, "k", "p" ) == ( False, 0 )

    def test_malformed_non_int_count( self, conn_seq ):
        conn_seq[ "outcomes" ] = [ FakeHTTPResponse( 200, '{"count": "5"}' ) ]
        assert tc.query_owed( SETTINGS, "k", "p" ) == ( False, 0 )

    def test_malformed_bool_count_rejected( self, conn_seq ):
        # JSON `true` is a bool (an int subclass) — must NOT slip through as 1
        conn_seq[ "outcomes" ] = [ FakeHTTPResponse( 200, '{"count": true}' ) ]
        assert tc.query_owed( SETTINGS, "k", "p" ) == ( False, 0 )

    def test_project_omitted_when_none( self, conn_seq ):
        conn_seq[ "outcomes" ] = [ _count_resp( 1 ) ]
        tc.query_owed( SETTINGS, "k", "p" )                           # no project
        _method, path, _headers = conn_seq[ "requests" ][ 0 ]
        assert "project=" not in path

    def test_uses_bounded_default_timeout( self, conn_seq ):
        conn_seq[ "outcomes" ] = [ _count_resp( 0 ) ]
        tc.query_owed( SETTINGS, "k", "p" )
        # §C/§J6: the Stop-hot-path read is bounded by an aggressive default,
        # applied as the connection's per-operation socket timeout.
        assert conn_seq[ "ctor" ][ 0 ][ "timeout" ] == tc.DEFAULT_OWED_TIMEOUT_SECONDS
        assert tc.DEFAULT_OWED_TIMEOUT_SECONDS <= 2.0                 # never stalls turn-end

    def test_timeout_override_passed_through( self, conn_seq ):
        conn_seq[ "outcomes" ] = [ _count_resp( 0 ) ]
        tc.query_owed( SETTINGS, "k", "p", timeout=0.5 )
        assert conn_seq[ "ctor" ][ 0 ][ "timeout" ] == 0.5

    def test_http_scheme_uses_http_connection( self, conn_seq ):
        conn_seq[ "outcomes" ] = [ _count_resp( 0 ) ]
        tc.query_owed( SETTINGS, "k", "p" )                           # SETTINGS is http://
        assert conn_seq[ "ctor" ][ 0 ][ "scheme" ] == "http"
        assert conn_seq[ "ctor" ][ 0 ][ "host" ] == "test" and conn_seq[ "ctor" ][ 0 ][ "port" ] == 7999

    def test_https_scheme_uses_https_connection( self, conn_seq ):
        conn_seq[ "outcomes" ] = [ _count_resp( 4 ) ]
        https_settings = { "api_base_url": "https://secure-store:8443", "timeout_seconds": 3.0 }
        ok, count = tc.query_owed( https_settings, "k", "p", ( "queued", ) )
        assert ( ok, count ) == ( True, 4 )
        assert conn_seq[ "ctor" ][ 0 ][ "scheme" ] == "https"
        assert conn_seq[ "ctor" ][ 0 ][ "port" ] == 8443

    def test_bad_base_url_fails_safe_no_request( self, conn_seq ):
        # A non-numeric port makes urlsplit.port raise ValueError → _open_owed_connection
        # returns None → fail safe ( False, 0 ), and NO request is ever issued.
        conn_seq[ "outcomes" ] = [ _count_resp( 9 ) ]
        bad_settings = { "api_base_url": "http://host:notaport", "timeout_seconds": 3.0 }
        assert tc.query_owed( bad_settings, "k", "p" ) == ( False, 0 )
        assert conn_seq[ "requests" ] == [ ] and conn_seq[ "closed" ] == 0
