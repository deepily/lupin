"""
Unit tests for lupin_mcp.task_store_tools — the TRANSPORT layer behind the
task_create / task_transition / task_query MCP tools.

Spec of record: Lupin src/rnd/v0.1.8/2026.06.11-task-store-phase1/02-mcp-wrapper-spec.md.
The layer is transport-only: these tests pin the failure contract (spec §4)
and the wire shapes (spec §2.1–2.3) — structural rules are server-side and
deliberately NOT re-tested here.

Venue: :7999-eligible (pure unit, requests fully mocked, no server, no state).
"""

import inspect

import pytest
import requests

from lupin_mcp.task_store_tools import (
    TASK_STORE_TIMEOUT_SECONDS,
    task_store_request,
    task_create_impl,
    task_transition_impl,
    task_correlate_impl,
    task_reassign_impl,
    task_amend_impl,
    task_query_impl,
    task_get_impl,
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

    @pytest.mark.parametrize( "non_dict_body", [
        [ "upstream connect error" ],   # bare list — LB/proxy error shape
        "Bad Gateway",                  # bare str
        503,                            # bare int
    ] )
    def test_valid_json_non_dict_error_body_never_raises( self, capture_request, non_dict_body ):
        # F1 (review of 1ed3c0dc): json() succeeding with a NON-dict body used
        # to escape the ValueError handler and raise AttributeError on .get —
        # violating the never-raises contract. Pin all three body classes.
        capture_request( FakeResponse( 502, json_body=non_dict_body ) )
        result = task_store_request( "GET", "/api/tasks", BASE_URL, API_KEY )
        assert result == { "status": "error", "http_status": 502, "detail": non_dict_body }


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
            "urgency"             : "normal",
            "status"              : "queued",       # DEFAULT mint status (build 1b5483f4)
            "blocked_by"          : None,
            "next_chase_ts"       : None,
            "source_qid"          : None,
            "correlation_key"     : None,
        }

    def test_blocked_mint_fields_pass_through( self, capture_request ):
        # One-call blocked mint (Rick 2026-07-20): status/blocked_by/next_chase_ts
        # ride the payload verbatim — transport only, no client-side pre-validation.
        calls = capture_request( FakeResponse( 201, json_body={ } ) )
        task_create_impl(
            BASE_URL, API_KEY,
            created_by    = "mr radio 372f9dc9",
            item_class    = "task",
            title         = "held on tiberius",
            project       = "lupin",
            status        = "blocked",
            blocked_by    = [ { "kind": "persona", "id": "tiberius" } ],
            next_chase_ts = "2026-06-12T09:00:00+00:00",
        )
        sent = calls[ "json" ]
        assert sent[ "status" ]        == "blocked"
        assert sent[ "blocked_by" ]    == [ { "kind": "persona", "id": "tiberius" } ]
        assert sent[ "next_chase_ts" ] == "2026-06-12T09:00:00+00:00"

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
            gate_class          = "operator",
            priority            = "P1",
            source_qid          = "qid-123",
            correlation_key     = "corr-456",
            authority           = "manager_relay",
        )
        sent = calls[ "json" ]
        assert sent[ "body" ]                == "Options: A, B"
        assert sent[ "owner_persona" ]       == "tiberius"
        assert sent[ "accountable_manager" ] == "tiberius"
        assert sent[ "gate_class" ]          == "operator"
        assert sent[ "priority" ]            == "P1"
        assert sent[ "source_qid" ]          == "qid-123"
        assert sent[ "correlation_key" ]     == "corr-456"
        assert sent[ "authority" ]           == "manager_relay"

    def test_aliased_project_canonicalized_on_write( self, capture_request ):
        # Bug c6751cf8: the MCP write path stored the raw repo name while the
        # owed-work oracle queried the alias -> false-idle. The write seam now
        # canonicalizes, so an aliased repo's row is STORED under "plan".
        calls = capture_request( FakeResponse( 201, json_body={ } ) )
        task_create_impl(
            BASE_URL, API_KEY,
            created_by = "clayton 95cf676c",
            item_class = "task",
            title      = "Owe work in the PIP repo",
            project    = "planning-is-prompting",
        )
        assert calls[ "json" ][ "project" ] == "plan"

    def test_non_aliased_project_passes_through_on_write( self, capture_request ):
        # A repo with no alias entry is stored verbatim (canonicalize is a no-op).
        calls = capture_request( FakeResponse( 201, json_body={ } ) )
        task_create_impl(
            BASE_URL, API_KEY,
            created_by = "clayton 95cf676c",
            item_class = "task",
            title      = "Owe work in lupin",
            project    = "lupin",
        )
        assert calls[ "json" ][ "project" ] == "lupin"


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
            "reason"        : None,
            "park_reason"   : None,          # park wiring (f68bc520) — always in the payload
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

    def test_reason_passes_through( self, capture_request ):
        # Amendment 2026-06-12 (Phase-2 §1.11(B)): server-REQUIRED non-empty
        # for ->dropped once C12 lands; transport just carries it verbatim.
        calls = capture_request( FakeResponse( 200, json_body={ } ) )
        task_transition_impl(
            BASE_URL, API_KEY,
            actor     = "sam 01b3bf59",
            task_id   = "abc",
            to_status = "dropped",
            reason    = "superseded-by-rewrite",
        )
        assert calls[ "json" ][ "reason" ] == "superseded-by-rewrite"


class TestTaskCorrelateImpl:

    def test_payload_and_route( self, capture_request ):
        body  = { "item": { "id": "abc" }, "event": { "transition": "re-correlated" } }
        calls = capture_request( FakeResponse( 200, json_body=body ) )
        result = task_correlate_impl(
            BASE_URL, API_KEY,
            actor           = "krishna a38ee857",
            task_id         = "abc-def",
            correlation_key = "cc-task:newsid:harness-7",
        )
        assert result == body
        assert calls[ "method" ] == "POST"
        assert calls[ "url" ]    == f"{BASE_URL}/api/tasks/abc-def/correlate"
        assert calls[ "json" ]   == {
            "correlation_key" : "cc-task:newsid:harness-7",
            "actor"           : "krishna a38ee857",
            "authority"       : "standing",
        }

    def test_authority_passes_through( self, capture_request ):
        calls = capture_request( FakeResponse( 200, json_body={ } ) )
        task_correlate_impl(
            BASE_URL, API_KEY,
            actor           = "krishna a38ee857",
            task_id         = "abc",
            correlation_key = "corr-9",
            authority       = "manager_relay",
        )
        assert calls[ "json" ][ "authority" ] == "manager_relay"

    def test_422_terminal_item_surfaces_detail_verbatim( self, capture_request ):
        # No re-keying closed history: the terminal-item reject is the SERVER's
        # 422 (one rules home) — transport carries its words unedited.
        detail = "cannot re-correlate a terminal item (status=done)"
        capture_request( FakeResponse( 422, json_body={ "detail": detail } ) )
        result = task_correlate_impl(
            BASE_URL, API_KEY,
            actor           = "krishna a38ee857",
            task_id         = "abc",
            correlation_key = "corr-9",
        )
        assert result == { "status": "error", "http_status": 422, "detail": detail }


class TestTaskReassignImpl:

    def test_payload_and_route_omits_manager_when_absent( self, capture_request ):
        # No new_manager -> accountable_manager NOT in the body, so the server's
        # exclude_unset model_dump leaves the chasing manager UNCHANGED (Q6).
        # Default authority is the manager-relay handoff lane.
        body  = { "item": { "id": "abc" }, "event": { "transition": "patched" } }
        calls = capture_request( FakeResponse( 200, json_body=body ) )
        result = task_reassign_impl(
            BASE_URL, API_KEY,
            actor             = "tiberius d9e65cd8",
            task_id           = "abc-def",
            new_owner_persona = "marcus",
            reason            = "Tiffany pulled onto the P0 arbiter fix",
        )
        assert result == body
        assert calls[ "method" ] == "PATCH"
        assert calls[ "url" ]    == f"{BASE_URL}/api/tasks/abc-def"
        assert calls[ "json" ]   == {
            "owner_persona" : "marcus",
            "reason"        : "Tiffany pulled onto the P0 arbiter fix",
            "actor"         : "tiberius d9e65cd8",
            "authority"     : "manager_relay",
        }
        assert "accountable_manager" not in calls[ "json" ]

    def test_new_manager_included_when_supplied( self, capture_request ):
        # An explicit new_manager re-homes the chasing manager too.
        calls = capture_request( FakeResponse( 200, json_body={ } ) )
        task_reassign_impl(
            BASE_URL, API_KEY,
            actor             = "tiberius d9e65cd8",
            task_id           = "abc",
            new_owner_persona = "marcus",
            reason            = "lane handoff",
            new_manager       = "tiberius",
        )
        assert calls[ "json" ][ "accountable_manager" ] == "tiberius"

    def test_authority_override_passes_through( self, capture_request ):
        calls = capture_request( FakeResponse( 200, json_body={ } ) )
        task_reassign_impl(
            BASE_URL, API_KEY,
            actor             = "rick (multiplexer)",
            task_id           = "abc",
            new_owner_persona = "marcus",
            reason            = "human edit",
            authority         = "user_direct",
        )
        assert calls[ "json" ][ "authority" ] == "user_direct"

    def test_404_surfaces_detail_verbatim( self, capture_request ):
        # A bad task id is the server's 404 to report — transport carries it raw.
        capture_request( FakeResponse( 404, json_body={ "detail": "task abc not found" } ) )
        result = task_reassign_impl(
            BASE_URL, API_KEY,
            actor             = "tiberius d9e65cd8",
            task_id           = "abc",
            new_owner_persona = "marcus",
            reason            = "whatever",
        )
        assert result == { "status": "error", "http_status": 404, "detail": "task abc not found" }


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
            gate_class          = "operator",
            accountable_manager = "tiberius",
            project             = "lupin",
            item_class          = "decision",
            correlation_key     = "todo:abc123",
            limit               = 5,
            offset              = 20,
        )
        assert calls[ "params" ] == {
            "owner_persona"       : "sam",
            "status"              : "queued",
            "gate_class"          : "operator",
            "accountable_manager" : "tiberius",
            "project"             : "lupin",
            "item_class"          : "decision",
            "correlation_key"     : "todo:abc123",
            "limit"               : 5,
            "offset"              : 20,
        }

    def test_offset_zero_is_sent_not_dropped( self, capture_request ):
        # 0 is falsy but IS a set value — the is-not-None filter must keep it.
        calls = capture_request( FakeResponse( 200, json_body={ "tasks": [ ], "count": 0 } ) )
        task_query_impl( BASE_URL, API_KEY, limit=0, offset=0 )
        assert calls[ "params" ] == { "limit": 0, "offset": 0 }

    def test_terse_default_omits_param( self, capture_request ):
        # §G: terse defaults False → the param is NOT sent (full-row contract
        # unchanged for every existing caller).
        calls = capture_request( FakeResponse( 200, json_body={ "tasks": [ ], "count": 0 } ) )
        task_query_impl( BASE_URL, API_KEY, owner_persona="sam" )
        assert "terse" not in calls[ "params" ]

    def test_terse_true_sends_canonical_lowercase_true( self, capture_request ):
        # §G token win: terse=True rides the wire as the canonical lowercase
        # "true" alongside the filters (a pre-§G server ignores the unknown param).
        calls = capture_request( FakeResponse( 200, json_body={ "tasks": [ ], "count": 0 } ) )
        task_query_impl( BASE_URL, API_KEY, owner_persona="sam", status="queued", terse=True )
        assert calls[ "params" ] == { "owner_persona": "sam", "status": "queued", "terse": "true" }

    def test_aliased_project_canonicalized_on_query( self, capture_request ):
        # Mirror of the write seam: an agent querying by the RAW repo name still
        # matches the canonically-stored rows (read == write, bug c6751cf8).
        calls = capture_request( FakeResponse( 200, json_body={ "tasks": [ ], "count": 0 } ) )
        task_query_impl( BASE_URL, API_KEY, project="planning-is-prompting" )
        assert calls[ "params" ] == { "project": "plan" }

    def test_guard_params_default_omitted( self, capture_request ):
        # include_terminal / unscoped_audit default False → NOT sent (the guarded,
        # terminal-excluding common path; contract unchanged for existing callers).
        calls = capture_request( FakeResponse( 200, json_body={ "tasks": [ ], "count": 0 } ) )
        task_query_impl( BASE_URL, API_KEY, owner_persona="sam" )
        assert "include_terminal" not in calls[ "params" ]
        assert "unscoped_audit" not in calls[ "params" ]

    def test_guard_params_true_send_canonical_lowercase_true( self, capture_request ):
        # The deliberate-audit escape (the arbiter + UI board cards): both ride the
        # wire as the canonical lowercase "true" (mirror of terse).
        calls = capture_request( FakeResponse( 200, json_body={ "tasks": [ ], "count": 0 } ) )
        task_query_impl( BASE_URL, API_KEY, unscoped_audit=True, include_terminal=True )
        assert calls[ "params" ] == { "unscoped_audit": "true", "include_terminal": "true" }


class TestProjectAliasRoundTrip:
    """
    The bug-c6751cf8 regression: an aliased-repo session writes via task_create
    and the owed-work read query finds it because BOTH seams canonicalize through
    the ONE shared alias map. The oracle (stop.py) resolves the same alias via
    resolve_project_name(); here we pin that the write seam and the agent-facing
    read seam land on the SAME stored project key, so write == read.
    """

    def test_write_then_read_land_on_same_project_key( self, capture_request ):
        # WRITE: an aliased-repo session creates an item.
        write_calls = capture_request( FakeResponse( 201, json_body={ } ) )
        task_create_impl(
            BASE_URL, API_KEY,
            created_by = "clayton 95cf676c",
            item_class = "task",
            title      = "Owe work in the PIP repo",
            project    = "planning-is-prompting",
        )
        stored_project = write_calls[ "json" ][ "project" ]

        # READ: the same aliased repo name queried back.
        read_calls = capture_request( FakeResponse( 200, json_body={ "tasks": [ ], "count": 0 } ) )
        task_query_impl( BASE_URL, API_KEY, project="planning-is-prompting" )
        queried_project = read_calls[ "params" ][ "project" ]

        # The crux: the key written is the key queried -> no false-idle.
        assert stored_project == queried_project == "plan"


class TestTaskAmendImpl:

    def test_payload_and_route( self, capture_request ):
        body  = { "item": { "id": "abc" }, "event": { "transition": "amended" } }
        calls = capture_request( FakeResponse( 200, json_body=body ) )
        result = task_amend_impl(
            BASE_URL, API_KEY,
            actor   = "arnold 8b7225c4",
            task_id = "abc-def",
            note    = "SCOPE REFRAME: subscriber path.",
            reason  = "manager ruling",
        )
        assert result == body
        assert calls[ "method" ] == "POST"
        assert calls[ "url" ]    == f"{BASE_URL}/api/tasks/abc-def/amend"
        assert calls[ "json" ]   == {
            "note"      : "SCOPE REFRAME: subscriber path.",
            "reason"    : "manager ruling",
            "actor"     : "arnold 8b7225c4",
            "authority" : "standing",
        }

    def test_reason_defaults_none_and_authority_passes_through( self, capture_request ):
        calls = capture_request( FakeResponse( 200, json_body={ } ) )
        task_amend_impl(
            BASE_URL, API_KEY,
            actor     = "arnold 8b7225c4",
            task_id   = "abc",
            note      = "n",
            authority = "manager_relay",
        )
        assert calls[ "json" ][ "reason" ]    is None
        assert calls[ "json" ][ "authority" ] == "manager_relay"

    def test_422_terminal_item_surfaces_detail_verbatim( self, capture_request ):
        # No amending closed history: the terminal reject is the SERVER's 422
        # (one rules home) — transport carries its words unedited.
        detail = "item is terminal ('done') — no amendments to closed history"
        capture_request( FakeResponse( 422, json_body={ "detail": detail } ) )
        result = task_amend_impl(
            BASE_URL, API_KEY,
            actor   = "arnold 8b7225c4",
            task_id = "abc",
            note    = "n",
        )
        assert result == { "status": "error", "http_status": 422, "detail": detail }


class TestTaskGetImpl:
    """
    task_get (4288dd53) — the single-row fetch-by-id transport. Thin proxy over
    GET /api/tasks/{task_id}; no server change (AC7). Transport only, so the
    error contract is inherited from task_store_request and re-pinned here at
    the by-id route.
    """

    def test_route_is_the_single_row_get( self, capture_request ):
        # AC1: a valid id → the FULL serialized item verbatim, via a GET to the
        # by-id route (no body, no params — nothing to shape).
        item  = { "id": "4288dd53-6779-460a-88bd-a7365fb734b2", "body": "x" * 8395 }
        calls = capture_request( FakeResponse( 200, json_body=item ) )
        result = task_get_impl( BASE_URL, API_KEY, "4288dd53-6779-460a-88bd-a7365fb734b2" )
        assert result == item                                          # full row, body included
        assert calls[ "method" ] == "GET"
        assert calls[ "url" ]     == f"{BASE_URL}/api/tasks/4288dd53-6779-460a-88bd-a7365fb734b2"
        assert calls[ "json" ]    is None                              # no request body
        assert calls[ "params" ]  is None                              # no query params
        assert calls[ "headers" ] == { "X-API-Key": API_KEY }

    def test_404_absent_row_is_error_dict_not_empty_success( self, capture_request ):
        # AC2: an absent row → error dict carrying the server's detail verbatim.
        # NEVER an empty success, NEVER None — a silent nothing is the confusion
        # this verb exists to kill.
        detail = "task 00000000-0000-0000-0000-000000000000 not found"
        capture_request( FakeResponse( 404, json_body={ "detail": detail } ) )
        result = task_get_impl( BASE_URL, API_KEY, "00000000-0000-0000-0000-000000000000" )
        assert result == { "status": "error", "http_status": 404, "detail": detail }
        assert result is not None and result != { }                   # not a silent nothing

    def test_malformed_uuid_surfaces_server_422_not_client_raise( self, capture_request ):
        # AC3: a malformed id is the SERVER's 422 to report — never pre-checked
        # or raised client-side (transport only, no rule duplication).
        fastapi_detail = [ { "loc": [ "path", "task_id" ], "msg": "value is not a valid uuid" } ]
        capture_request( FakeResponse( 422, json_body={ "detail": fastapi_detail } ) )
        result = task_get_impl( BASE_URL, API_KEY, "not-a-uuid" )
        assert result == { "status": "error", "http_status": 422, "detail": fastapi_detail }

    def test_missing_auth_is_error_dict_not_exception( self, capture_request ):
        # AC4: auth failure surfaces as an error dict; no HTTP attempt is made.
        calls  = capture_request( RuntimeError( "must not be called" ) )
        result = task_get_impl( BASE_URL, api_key=None, task_id="abc" )
        assert result == {
            "status" : "error",
            "reason" : "missing_auth_header",
            "detail" : result[ "detail" ],                            # exact text pinned in TestTaskStoreRequest
        }
        assert calls == { }                                           # never reached the wire

    def test_server_unreachable_is_error_dict_never_raises( self, capture_request ):
        # AC4 (transport arm): a hung/refused store surfaces as an error dict.
        capture_request( requests.exceptions.ConnectionError( "refused" ) )
        result = task_get_impl( BASE_URL, API_KEY, "abc" )
        assert result[ "status" ] == "error" and result[ "reason" ] == "server_unreachable"


class TestFetchByIdNegativeControl:
    """
    🔴 AC5 — THE NEGATIVE CONTROL. Prove the PRE-CHANGE MCP surface CANNOT fetch
    a row by id, so `task_get` is shown to close a real gap rather than merely
    pass a test that would pass anyway.

    The pre-change read surface was `task_query_impl` ALONE. The gap is
    structural and asserted on the SPECIFIC mechanism, not on mere absence
    (Plan-1 AC8a lesson: a control must name the exact wrong shape): the query
    verb has no id parameter, and its route is the LIST endpoint, so "give me
    row X" is not expressible — you can only ask a filter and scan a page, and a
    page's silence is not an answer.
    """

    def test_pre_change_query_verb_has_no_id_parameter( self ):
        # The concrete gap: task_query_impl accepts filters, NONE of which is an
        # id. A caller literally cannot pass the row's id to the pre-change verb.
        params = inspect.signature( task_query_impl ).parameters
        assert "task_id" not in params and "id" not in params and "ids" not in params, (
            "the pre-change query verb grew an id parameter — fetch-by-id belongs "
            "in task_get, not folded into the list query (plan §5 option (a))" )

    def test_pre_change_query_verb_hits_the_LIST_route_never_a_by_id_route( self, capture_request ):
        # Even fully specified, task_query_impl issues a GET to the LIST endpoint
        # (/api/tasks) and returns a {tasks, count} envelope — never /api/tasks/{id}.
        # So the only pre-change way to "find row X" is to scan a page, which is
        # exactly the failure (an absence in a page read as a fact about the world).
        calls  = capture_request( FakeResponse( 200, json_body={ "tasks": [ ], "count": 0 } ) )
        result = task_query_impl( BASE_URL, API_KEY, owner_persona="sam" )
        assert calls[ "url" ] == f"{BASE_URL}/api/tasks"                       # the LIST route, exactly
        assert not calls[ "url" ].startswith( f"{BASE_URL}/api/tasks/" )       # NOT a by-id route
        assert set( result.keys() ) == { "tasks", "count" }                   # a LIST envelope, never one row

    def test_task_get_closes_the_gap_it_names( self, capture_request ):
        # The positive contrast, on the SAME axis the control measures: task_get
        # DOES take an id and DOES hit the by-id route. The gap is real and this
        # is what closes it.
        get_params = inspect.signature( task_get_impl ).parameters
        assert "task_id" in get_params
        calls = capture_request( FakeResponse( 200, json_body={ "id": "abc" } ) )
        task_get_impl( BASE_URL, API_KEY, "abc" )
        assert calls[ "url" ] == f"{BASE_URL}/api/tasks/abc"                   # the by-id route
