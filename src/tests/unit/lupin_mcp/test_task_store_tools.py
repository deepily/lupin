"""
Unit tests for lupin_mcp.task_store_tools — the TRANSPORT layer behind the
task_create / task_transition / task_query MCP tools.

Spec of record: Lupin src/rnd/v0.1.8/2026.06.11-task-store-phase1/02-mcp-wrapper-spec.md.
The layer is transport-only: these tests pin the failure contract (spec §4)
and the wire shapes (spec §2.1–2.3) — structural rules are server-side and
deliberately NOT re-tested here.

Venue: :7999-eligible (pure unit, requests fully mocked, no server, no state).
"""

import pytest
import requests

from lupin_mcp.task_store_tools import (
    TASK_STORE_TIMEOUT_SECONDS,
    task_store_request,
    task_create_impl,
    task_transition_impl,
    task_query_impl,
)

BASE_URL = "http://localhost:7999"
API_KEY  = "ck_live_test_key"


class FakeResponse:
    """Minimal stand-in for requests.Response — json() raises ValueError on non-JSON."""

    def __init__( self, status_code, json_body=None, text="" ):
        self.status_code = status_code
        self._json_body  = json_body
        self.text        = text

    def json( self ):
        if self._json_body is None:
            raise ValueError( "no JSON" )
        return self._json_body


@pytest.fixture
def capture_request( monkeypatch ):
    """Patch requests.request to capture the call and return a canned response."""
    calls = { }

    def install( response ):
        def _fake_request( method, url, headers=None, json=None, params=None, timeout=None ):
            calls.update( method=method, url=url, headers=headers, json=json, params=params, timeout=timeout )
            if isinstance( response, Exception ):
                raise response
            return response
        monkeypatch.setattr( requests, "request", _fake_request )
        return calls

    return install


class TestTaskStoreRequest:

    def test_missing_api_key_short_circuits( self, capture_request ):
        # No HTTP attempt at all — the canned response would explode if called.
        calls  = capture_request( RuntimeError( "must not be called" ) )
        result = task_store_request( "GET", "/api/tasks", BASE_URL, api_key=None )
        assert result[ "status" ] == "error"
        assert result[ "reason" ] == "missing_auth_header"
        assert calls == { }

    def test_connection_error_returns_unreachable( self, capture_request ):
        capture_request( requests.exceptions.ConnectionError( "refused" ) )
        result = task_store_request( "GET", "/api/tasks", BASE_URL, API_KEY )
        assert result[ "status" ] == "error"
        assert result[ "reason" ] == "server_unreachable"
        assert "ConnectionError" in result[ "detail" ]

    def test_timeout_returns_unreachable( self, capture_request ):
        capture_request( requests.exceptions.Timeout( "slow store" ) )
        result = task_store_request( "POST", "/api/tasks", BASE_URL, API_KEY )
        assert result[ "status" ] == "error"
        assert result[ "reason" ] == "server_unreachable"
        assert "Timeout" in result[ "detail" ]

    def test_2xx_returns_body_verbatim( self, capture_request ):
        body  = { "id": "abc", "status": "queued" }
        calls = capture_request( FakeResponse( 201, json_body=body ) )
        result = task_store_request( "POST", "/api/tasks", BASE_URL, API_KEY, json_body={ "title": "t" } )
        assert result == body
        assert calls[ "method" ]  == "POST"
        assert calls[ "url" ]     == f"{BASE_URL}/api/tasks"
        assert calls[ "headers" ] == { "X-API-Key": API_KEY }
        assert calls[ "json" ]    == { "title": "t" }
        assert calls[ "timeout" ] == TASK_STORE_TIMEOUT_SECONDS

    def test_422_rules_shape_surfaces_errors_verbatim( self, capture_request ):
        # The no-confabulation rule (spec §2.2): server's words, unedited.
        server_errors = [ "->done requires receipt_refs", "receipt key 'vibes' not whitelisted" ]
        capture_request( FakeResponse( 422, json_body={ "detail": { "errors": server_errors } } ) )
        result = task_store_request( "POST", "/api/tasks/x/transition", BASE_URL, API_KEY )
        assert result == { "status": "error", "http_status": 422, "errors": server_errors }

    def test_422_non_rules_shape_surfaces_detail_verbatim( self, capture_request ):
        # FastAPI request-validation 422s carry detail as a LIST, not the rules dict.
        fastapi_detail = [ { "loc": [ "body", "title" ], "msg": "field required" } ]
        capture_request( FakeResponse( 422, json_body={ "detail": fastapi_detail } ) )
        result = task_store_request( "POST", "/api/tasks", BASE_URL, API_KEY )
        assert result == { "status": "error", "http_status": 422, "detail": fastapi_detail }

    def test_404_surfaces_detail_verbatim( self, capture_request ):
        capture_request( FakeResponse( 404, json_body={ "detail": "task abc not found" } ) )
        result = task_store_request( "GET", "/api/tasks/abc", BASE_URL, API_KEY )
        assert result == { "status": "error", "http_status": 404, "detail": "task abc not found" }

    def test_non_json_error_body_falls_back_to_text( self, capture_request ):
        capture_request( FakeResponse( 500, json_body=None, text="Internal Server Error" ) )
        result = task_store_request( "GET", "/api/tasks", BASE_URL, API_KEY )
        assert result == { "status": "error", "http_status": 500, "detail": "Internal Server Error" }


class TestTaskCreateImpl:

    def test_payload_and_route( self, capture_request ):
        body  = { "id": "new-item" }
        calls = capture_request( FakeResponse( 201, json_body=body ) )
        result = task_create_impl(
            BASE_URL, API_KEY,
            created_by = "sam 01b3bf59",
            item_class = "task",
            title      = "Build the wrapper",
            project    = "lupin",
        )
        assert result == body
        assert calls[ "method" ] == "POST"
        assert calls[ "url" ]    == f"{BASE_URL}/api/tasks"
        assert calls[ "json" ]   == {
            "item_class"          : "task",
            "title"               : "Build the wrapper",
            "project"             : "lupin",
            "created_by"          : "sam 01b3bf59",
            "authority"           : "standing",
            "body"                : None,
            "owner_persona"       : None,
            "accountable_manager" : None,
            "gate_class"          : "none",
            "priority"            : "P2",
            "source_qid"          : None,
            "correlation_key"     : None,
        }

    def test_all_optionals_pass_through( self, capture_request ):
        calls = capture_request( FakeResponse( 201, json_body={ } ) )
        task_create_impl(
            BASE_URL, API_KEY,
            created_by          = "sam 01b3bf59",
            item_class          = "decision",
            title               = "Pick a deploy window",
            project             = "lupin",
            body                = "Options: A, B",
            owner_persona       = "tiberius",
            accountable_manager = "tiberius",
            gate_class          = "ricks_court",
            priority            = "P1",
            source_qid          = "qid-123",
            correlation_key     = "corr-456",
            authority           = "manager_relay",
        )
        sent = calls[ "json" ]
        assert sent[ "body" ]                == "Options: A, B"
        assert sent[ "owner_persona" ]       == "tiberius"
        assert sent[ "accountable_manager" ] == "tiberius"
        assert sent[ "gate_class" ]          == "ricks_court"
        assert sent[ "priority" ]            == "P1"
        assert sent[ "source_qid" ]          == "qid-123"
        assert sent[ "correlation_key" ]     == "corr-456"
        assert sent[ "authority" ]           == "manager_relay"


class TestTaskTransitionImpl:

    def test_payload_and_route( self, capture_request ):
        body  = { "item": { "id": "abc" }, "event": { "transition": "queued->in_progress" } }
        calls = capture_request( FakeResponse( 200, json_body=body ) )
        result = task_transition_impl(
            BASE_URL, API_KEY,
            actor     = "sam 01b3bf59",
            task_id   = "abc-def",
            to_status = "in_progress",
        )
        assert result == body
        assert calls[ "url" ]  == f"{BASE_URL}/api/tasks/abc-def/transition"
        assert calls[ "json" ] == {
            "to_status"     : "in_progress",
            "actor"         : "sam 01b3bf59",
            "authority"     : "standing",
            "receipt_refs"  : None,
            "next_chase_ts" : None,
            "blocked_by"    : None,
        }

    def test_blocked_fields_pass_through( self, capture_request ):
        calls = capture_request( FakeResponse( 200, json_body={ } ) )
        task_transition_impl(
            BASE_URL, API_KEY,
            actor         = "sam 01b3bf59",
            task_id       = "abc",
            to_status     = "blocked",
            receipt_refs  = { "commit": "f4e0370" },
            next_chase_ts = "2026-06-13T09:00:00-04:00",
            blocked_by    = [ { "kind": "persona", "id": "tiffany" } ],
            authority     = "user_direct",
        )
        sent = calls[ "json" ]
        assert sent[ "receipt_refs" ]  == { "commit": "f4e0370" }
        assert sent[ "next_chase_ts" ] == "2026-06-13T09:00:00-04:00"
        assert sent[ "blocked_by" ]    == [ { "kind": "persona", "id": "tiffany" } ]
        assert sent[ "authority" ]     == "user_direct"


class TestTaskQueryImpl:

    def test_no_args_sends_no_params( self, capture_request ):
        # The manager board glance: everything, newest first — server defaults.
        body  = { "tasks": [ ], "count": 0 }
        calls = capture_request( FakeResponse( 200, json_body=body ) )
        result = task_query_impl( BASE_URL, API_KEY )
        assert result == body
        assert calls[ "method" ] == "GET"
        assert calls[ "url" ]    == f"{BASE_URL}/api/tasks"
        assert calls[ "params" ] == { }
        assert calls[ "json" ]   is None

    def test_set_filters_sent_unset_omitted( self, capture_request ):
        calls = capture_request( FakeResponse( 200, json_body={ "tasks": [ ], "count": 0 } ) )
        task_query_impl(
            BASE_URL, API_KEY,
            owner_persona = "sam",
            status        = "in_progress",
            limit         = 10,
        )
        assert calls[ "params" ] == { "owner_persona": "sam", "status": "in_progress", "limit": 10 }

    def test_all_filters_pass_through( self, capture_request ):
        calls = capture_request( FakeResponse( 200, json_body={ "tasks": [ ], "count": 0 } ) )
        task_query_impl(
            BASE_URL, API_KEY,
            owner_persona       = "sam",
            status              = "queued",
            gate_class          = "ricks_court",
            accountable_manager = "tiberius",
            project             = "lupin",
            item_class          = "decision",
            limit               = 5,
            offset              = 20,
        )
        assert calls[ "params" ] == {
            "owner_persona"       : "sam",
            "status"              : "queued",
            "gate_class"          : "ricks_court",
            "accountable_manager" : "tiberius",
            "project"             : "lupin",
            "item_class"          : "decision",
            "limit"               : 5,
            "offset"              : 20,
        }

    def test_offset_zero_is_sent_not_dropped( self, capture_request ):
        # 0 is falsy but IS a set value — the is-not-None filter must keep it.
        calls = capture_request( FakeResponse( 200, json_body={ "tasks": [ ], "count": 0 } ) )
        task_query_impl( BASE_URL, API_KEY, limit=0, offset=0 )
        assert calls[ "params" ] == { "limit": 0, "offset": 0 }
