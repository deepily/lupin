#!/usr/bin/env python3
"""
A refused lineage claim on the test-suite job that holds the monopoly slot answers 403.

Every other refused claim stays the quiet drop that test_v2_parent_stamp_ownership.py pins. That drop is a
log line, a note in the trace, and a request that carries on without the stamp. The loud answer exists for
one case. A suite's own child with a refused claim would otherwise wait behind its own suite.
It would wait for the whole run, with one log line to say why.

Same construction as test_v2_parent_stamp_ownership.py, whose flow, queue stand-in and fixtures it reuses.
Stand-ins: the slot reader (`_active_suite_id`), the owner lookup, the switch.

Venue: :7999-eligible. In-process; dry_run, so nothing executes.
"""

import sys
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosa.rest import suite_run_token as srt
from cosa.rest.routers import v2_ask
from test_v2_parent_stamp_ownership import (   # noqa: F401  (the fixtures are used by name)
    OWNER_UID, PARENT, TEST_ACCOUNT, TS_COMMAND, _AskFlow, _client, _traces, _user, queue, world,
)


@pytest.fixture
def slot( monkeypatch ):
    """The suite holding the monopoly slot is the parent; `reads` counts the slot reads."""
    state = { "suite": PARENT, "reads": 0, "raises": None }
    def holder():
        state[ "reads" ] += 1
        if state[ "raises" ]: raise state[ "raises" ]
        return state[ "suite" ]
    monkeypatch.setattr( v2_ask, "_active_suite_id", holder )
    return state


def _post_submit( client, parent=PARENT, headers=None ):
    body = { "command": TS_COMMAND, "args": { "test_types": "unit", "dry_run": True }, "speak": False }
    if parent is not None: body[ "parent_id_hash" ] = parent
    return client.post( "/api/v2/submit", json=body, headers=headers or { } )


def _ask_client( user ):
    flow = _AskFlow()
    app  = FastAPI()
    app.include_router( v2_ask.router )
    app.dependency_overrides[ v2_ask.get_current_user ] = lambda: user
    app.dependency_overrides[ v2_ask.get_ask_flow ]     = lambda: flow
    return TestClient( app ), flow


def _post_ask( client, parent=PARENT, headers=None ):
    body = { "question": "hi" }
    if parent is not None: body[ "parent_id_hash" ] = parent
    return client.post( "/api/v2/ask", json=body, headers=headers or { } )


# ── the 403 ──────────────────────────────────────────────────────────────────

def test_submit_answers_403_for_a_strangers_claim_on_the_active_suite_and_pushes_nothing( queue, tmp_path, world, slot ):
    response = _post_submit( _client( queue, tmp_path, _user() ) )
    assert response.status_code == 403
    detail = response.json()[ "detail" ]
    assert detail[ "error" ] == "parent_id_hash_refused" and detail[ "reason" ] == "not_owner" and detail[ "parent_id_hash" ] == PARENT
    assert srt.TOKEN_HEADER in detail[ "message" ] and "not_owner" in detail[ "message" ]
    assert queue.pushed == [ ], "the refused request still ran"


def test_ask_answers_403_for_a_strangers_claim_on_the_active_suite_and_never_runs_the_flow( world, slot ):
    client, flow = _ask_client( _user() )
    response = _post_ask( client )
    assert response.status_code == 403
    assert response.json()[ "detail" ][ "reason" ] == "not_owner"
    assert flow.kwargs is None, "the refused ask still reached the flow"


def test_the_reason_is_owner_unknown_when_the_parent_has_no_job_history_row( world, slot ):
    world[ "owners" ].clear()
    response = _post_ask( _ask_client( _user() )[ 0 ] )
    assert response.status_code == 403 and response.json()[ "detail" ][ "reason" ] == "owner_unknown"


def test_a_refused_token_names_the_tokens_own_reason_in_the_403( world, slot, monkeypatch ):
    monkeypatch.setattr( v2_ask, "_suite_token_enabled", lambda: True )
    srt.clear()
    response = _post_ask( _ask_client( _user() )[ 0 ], headers={ srt.TOKEN_HEADER: "a-token-nobody-issued" } )
    assert response.status_code == 403
    assert response.json()[ "detail" ][ "reason" ] == "token_unknown"


def test_the_403_body_never_carries_the_presented_token( world, slot, monkeypatch ):
    monkeypatch.setattr( v2_ask, "_suite_token_enabled", lambda: True )
    srt.clear()
    response = _post_ask( _ask_client( _user() )[ 0 ], headers={ srt.TOKEN_HEADER: "SECRET-TOKEN-VALUE-1234" } )
    assert response.status_code == 403 and "SECRET-TOKEN-VALUE-1234" not in response.text


def test_the_log_line_says_refused_with_403_and_not_dropped( world, slot, capsys ):
    _post_ask( _ask_client( _user() )[ 0 ] )
    lines = [ l for l in capsys.readouterr().out.splitlines() if l.startswith( "[v2-lineage]" ) ]
    assert len( lines ) == 1 and "refused with 403" in lines[ 0 ] and "dropped" not in lines[ 0 ] and "not_owner" in lines[ 0 ]


# ── every other refusal stays the quiet drop ─────────────────────────────────

def test_a_claim_on_a_job_that_is_not_the_active_suite_is_still_dropped_quietly( queue, tmp_path, world, slot, capsys ):
    slot[ "suite" ] = "ts-some-other-suite"
    response = _post_submit( _client( queue, tmp_path, _user() ) )
    assert response.status_code == 200 and response.json()[ "status" ] == "waiting"
    assert [ r.get( "parent_id_hash_dropped" ) for r in _traces( tmp_path ) ] == [ "'ts-parentjob':not_owner" ]
    assert "dropped" in capsys.readouterr().out


def test_with_no_suite_holding_the_slot_a_refused_claim_is_dropped_quietly( world, slot ):
    slot[ "suite" ] = None
    client, flow = _ask_client( _user() )
    assert _post_ask( client ).status_code == 200
    assert flow.kwargs[ "parent_id_hash" ] is None and flow.kwargs[ "parent_stamp_dropped" ] == "'ts-parentjob':not_owner"


def test_a_slot_that_cannot_be_read_leaves_the_quiet_drop_and_never_a_500( world, slot, capsys ):
    slot[ "raises" ] = RuntimeError( "queue exploded" )
    client, flow = _ask_client( _user() )
    assert _post_ask( client ).status_code == 200
    assert flow.kwargs[ "parent_id_hash" ] is None
    assert "suite slot read failed, so the refusal stays a quiet drop: RuntimeError" in capsys.readouterr().out


@pytest.mark.parametrize( "label, user", [
    ( "admin",        _user( roles=[ "admin" ] ) ),
    ( "test account", _user( email=TEST_ACCOUNT ) ),
    ( "parent owner", _user( uid=OWNER_UID ) ),
] )
def test_an_honoured_caller_is_never_refused_and_never_makes_the_slot_read( label, user, world, slot ):
    client, flow = _ask_client( user )
    assert _post_ask( client ).status_code == 200, label
    assert flow.kwargs[ "parent_id_hash" ] == PARENT
    assert slot[ "reads" ] == 0, "an honoured claim must not consult the slot"


def test_a_valid_suite_token_is_honoured_and_not_refused( world, slot, monkeypatch ):
    monkeypatch.setattr( v2_ask, "_suite_token_enabled", lambda: True )
    monkeypatch.setattr( v2_ask, "_active_monopolizer_id", lambda: PARENT )
    srt.clear()
    token = srt.issue( PARENT, 100_000 )
    client, flow = _ask_client( _user() )
    assert _post_ask( client, headers={ srt.TOKEN_HEADER: token } ).status_code == 200
    assert flow.kwargs[ "parent_id_hash" ] == PARENT
    srt.clear()


def test_no_claim_neither_refuses_nor_reads_the_slot( world, slot ):
    client, flow = _ask_client( _user() )
    assert _post_ask( client, parent=None ).status_code == 200
    assert slot[ "reads" ] == 0


# ── the slot reader ──────────────────────────────────────────────────────────

class _Job:
    def __init__( self, job_type ): self.job_type = job_type


class _RunningQueue:
    """Only the two public accessors the reader may use; a private attribute would raise."""
    def __init__( self, holder, jobs ): self.holder, self.jobs = holder, jobs
    def get_pool_status( self ): return { "monopolize_id": self.holder }
    def get_by_id_hash( self, id_hash ): return self.jobs[ id_hash ]


def _with_queue( monkeypatch, running_queue ):
    main = types.ModuleType( "lupin_app.main" )
    main.jobs_run_queue = running_queue
    package = types.ModuleType( "lupin_app" )
    package.main = main
    monkeypatch.setitem( sys.modules, "lupin_app", package )
    monkeypatch.setitem( sys.modules, "lupin_app.main", main )


def test_the_slot_reader_returns_the_holder_only_when_it_is_a_test_suite_job( monkeypatch ):
    _with_queue( monkeypatch, _RunningQueue( "ts-live", { "ts-live": _Job( "test_suite" ) } ) )
    assert v2_ask._active_suite_id() == "ts-live"


@pytest.mark.parametrize( "make, why", [
    ( lambda: None,                                                        "the running queue is not initialised" ),
    ( lambda: _RunningQueue( None, { } ),                                  "no job holds the slot" ),
    ( lambda: _RunningQueue( "ts-gone", { } ),                             "the holder has left the queue" ),
    ( lambda: _RunningQueue( "dr-job", { "dr-job": _Job( "deep_research" ) } ), "the holder is not a test suite" ),
] )
def test_the_slot_reader_returns_none_when( monkeypatch, make, why ):
    _with_queue( monkeypatch, make() )
    assert v2_ask._active_suite_id() is None, why


def test_the_claim_check_is_true_only_for_the_active_suites_own_id( monkeypatch ):
    _with_queue( monkeypatch, _RunningQueue( "ts-live", { "ts-live": _Job( "test_suite" ) } ) )
    assert v2_ask._claims_the_active_suite( "ts-live" ) is True
    assert v2_ask._claims_the_active_suite( "ts-other" ) is False


# ── the contract is in the generated spec ────────────────────────────────────

@pytest.mark.parametrize( "path", [ "/api/v2/ask", "/api/v2/submit" ] )
def test_both_doors_list_the_403_in_the_openapi_spec( path ):
    app = FastAPI()
    app.include_router( v2_ask.router )
    responses = app.openapi()[ "paths" ][ path ][ "post" ][ "responses" ]
    assert "403" in responses and "monopoly slot" in responses[ "403" ][ "description" ]


def test_the_other_doors_do_not_list_a_403_they_never_send():
    app = FastAPI()
    app.include_router( v2_ask.router )
    for path in ( "/api/v2/ask-audio", "/api/v2/resume" ):
        assert "403" not in app.openapi()[ "paths" ][ path ][ "post" ][ "responses" ], path
