#!/usr/bin/env python3
"""
The per-run suite token as a fourth holder of the lineage claim on both v2 doors.

A fresh random user is neither an admin, the test account, nor the parent's owner. With the INI
switch on and a valid token in the X-Lupin-Lineage-Token header, while the parent holds the
monopoly slot, the claim is honoured. In every other case it is dropped with a reason word, and
the token itself reaches no trace, log line, job argument or error body.

Same construction as test_v2_parent_stamp_ownership.py, whose real AskFlow, queue stand-in and
fixtures it reuses. Stand-ins: the switch, the slot reader, the owner lookup. The store is real.

Venue: :7999-eligible. In-process; dry_run, so nothing executes.
"""

import json
import os
import sys
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosa.rest import suite_run_token as srt
from cosa.rest.routers import v2_ask
from test_v2_parent_stamp_ownership import (   # noqa: F401  (the fixtures are used by name)
    PARENT, TS_COMMAND, OWNER_UID, TEST_ACCOUNT, _AskFlow, _client, _stamp, _traces, _user, queue, world,
)

HEADER = srt.TOKEN_HEADER


@pytest.fixture
def run( world, monkeypatch ):
    """A live token for the parent, the switch on and the slot held."""
    srt.clear()
    state = { "enabled": True, "active": PARENT, "token": srt.issue( PARENT, 100_000 ), "enabled_reads": 0, "slot_reads": 0 }
    def enabled():
        state[ "enabled_reads" ] += 1
        return state[ "enabled" ]
    def active():
        state[ "slot_reads" ] += 1
        return state[ "active" ]
    monkeypatch.setattr( v2_ask, "_suite_token_enabled", enabled )
    monkeypatch.setattr( v2_ask, "_active_monopolizer_id", active )
    yield state
    srt.clear()


def _submit_with( client, token, parent=PARENT ):
    body = { "command": TS_COMMAND, "args": { "test_types": "unit", "dry_run": True }, "speak": False, "parent_id_hash": parent }
    headers = { } if token is None else { HEADER: token }
    response = client.post( "/api/v2/submit", json=body, headers=headers )
    assert response.status_code == 200, response.text
    return response.json()


def _ask_with( user, token, parent=PARENT, body_extra=None ):
    flow = _AskFlow()
    app  = FastAPI()
    app.include_router( v2_ask.router )
    app.dependency_overrides[ v2_ask.get_current_user ] = lambda: user
    app.dependency_overrides[ v2_ask.get_ask_flow ]     = lambda: flow
    body = { "question": "hi", "parent_id_hash": parent, **( body_extra or { } ) }
    headers = { } if token is None else { HEADER: token }
    response = TestClient( app ).post( "/api/v2/ask", json=body, headers=headers )
    return response, flow.kwargs


def _dropped( tmp_path ):
    return [ r.get( "parent_id_hash_dropped" ) for r in _traces( tmp_path ) ]


# ── honoured ────────────────────────────────────────────────────────────────

def test_submit_honours_a_fresh_users_claim_when_the_token_is_live_and_the_run_holds_the_slot( queue, tmp_path, run ):
    _submit_with( _client( queue, tmp_path, _user() ), run[ "token" ] )
    assert _stamp( queue ) == PARENT
    assert _dropped( tmp_path ) == [ None ]


def test_ask_honours_the_same_claim( run ):
    response, kwargs = _ask_with( _user(), run[ "token" ] )
    assert response.status_code == 200
    assert kwargs[ "parent_id_hash" ] == PARENT and "parent_stamp_dropped" not in kwargs


def test_an_admin_and_the_test_account_never_touch_the_switch_the_store_or_the_slot( queue, tmp_path, run, monkeypatch ):
    consulted = [ ]
    monkeypatch.setattr( srt, "check", lambda *a, **k: consulted.append( a ) or ( False, "x" ) )
    _submit_with( _client( queue, tmp_path, _user( roles=[ "admin" ] ) ), run[ "token" ] )
    _submit_with( _client( queue, tmp_path, _user( email=TEST_ACCOUNT ) ), run[ "token" ] )
    assert consulted == [ ] and run[ "enabled_reads" ] == 0


# ── the INI switch is read before the check ─────────────────────────────────

def test_with_the_switch_off_a_valid_token_changes_nothing_and_the_store_is_not_consulted( queue, tmp_path, run, monkeypatch ):
    run[ "enabled" ] = False
    consulted = [ ]
    monkeypatch.setattr( srt, "check", lambda *a, **k: consulted.append( a ) or ( True, None ) )
    _submit_with( _client( queue, tmp_path, _user() ), run[ "token" ] )
    assert _stamp( queue ) is None
    assert _dropped( tmp_path ) == [ "'ts-parentjob':not_owner" ], "the reason is the existing one, not a token word"
    assert consulted == [ ] and run[ "enabled_reads" ] == 1


def test_with_the_switch_off_ask_drops_the_claim_the_same_way( run ):
    run[ "enabled" ] = False
    _, kwargs = _ask_with( _user(), run[ "token" ] )
    assert kwargs[ "parent_id_hash" ] is None and kwargs[ "parent_stamp_dropped" ] == "'ts-parentjob':not_owner"


def test_without_a_header_the_switch_is_not_even_read_and_the_reason_is_the_existing_one( queue, tmp_path, run ):
    _submit_with( _client( queue, tmp_path, _user() ), None )
    assert _stamp( queue ) is None
    assert _dropped( tmp_path ) == [ "'ts-parentjob':not_owner" ]
    assert run[ "enabled_reads" ] == 0 and run[ "slot_reads" ] == 0


# ── every refusal names its reason in the existing trace field ──────────────

@pytest.mark.parametrize( "case, token_for, reason", [
    ( "wrong token",        lambda run: "not-the-token",   "token_mismatch" ),
    ( "empty token",        lambda run: "",                "token_mismatch" ),
    ( "oversized token",    lambda run: "x" * 5000,        "token_mismatch" ),
] )
def test_a_bad_token_is_dropped_with_its_reason_never_a_4xx( case, token_for, reason, queue, tmp_path, run ):
    _submit_with( _client( queue, tmp_path, _user() ), token_for( run ) )
    assert _stamp( queue ) is None, case
    assert _dropped( tmp_path ) == [ f"'ts-parentjob':{reason}" ], case


def test_a_parent_with_no_token_issued_is_token_unknown_as_after_a_restart( queue, tmp_path, run ):
    srt.clear()
    _submit_with( _client( queue, tmp_path, _user() ), run[ "token" ] )
    assert _dropped( tmp_path ) == [ "'ts-parentjob':token_unknown" ]


def test_an_expired_token_is_token_expired( queue, tmp_path, run ):
    srt.clear()
    token = srt.issue( PARENT, 100, now=-1000 )
    _submit_with( _client( queue, tmp_path, _user() ), token )
    assert _dropped( tmp_path ) == [ "'ts-parentjob':token_expired" ]


def test_a_run_that_no_longer_holds_the_slot_is_not_active_monopolizer( queue, tmp_path, run ):
    run[ "active" ] = None
    _submit_with( _client( queue, tmp_path, _user() ), run[ "token" ] )
    assert _stamp( queue ) is None
    assert _dropped( tmp_path ) == [ "'ts-parentjob':not_active_monopolizer" ]


def test_ask_reports_the_same_reason_word_to_the_flow( run ):
    _, kwargs = _ask_with( _user(), "wrong" )
    assert kwargs[ "parent_id_hash" ] is None and kwargs[ "parent_stamp_dropped" ] == "'ts-parentjob':token_mismatch"


def test_the_token_for_one_parent_does_not_vouch_for_another( queue, tmp_path, run ):
    _submit_with( _client( queue, tmp_path, _user() ), run[ "token" ], parent="ts-someone-elses" )
    assert _stamp( queue ) is None
    assert _dropped( tmp_path ) == [ "'ts-someone-elses':token_unknown" ]


def test_an_owner_who_presents_a_bad_token_is_still_honoured_as_the_owner( queue, tmp_path, run ):
    _submit_with( _client( queue, tmp_path, _user( uid=OWNER_UID ) ), "wrong" )
    assert _stamp( queue ) == PARENT and _dropped( tmp_path ) == [ None ]


def test_a_slot_reader_that_raises_drops_the_token_but_still_runs_the_owner_check( queue, tmp_path, run, monkeypatch, capsys ):
    def broken(): raise RuntimeError( "queue gone" )
    monkeypatch.setattr( v2_ask, "_active_monopolizer_id", broken )
    _submit_with( _client( queue, tmp_path, _user() ), run[ "token" ] )
    assert _stamp( queue ) is None
    assert _dropped( tmp_path ) == [ "'ts-parentjob':token_check_failed" ]
    assert "suite token check failed: RuntimeError" in capsys.readouterr().out
    _submit_with( _client( queue, tmp_path, _user( uid=OWNER_UID ) ), run[ "token" ] )
    assert queue.pushed[ -1 ].spawned_by_id_hash == PARENT, "the owner is honoured even when the reader is broken"


def test_a_switch_that_cannot_be_read_fails_closed_to_the_owner_check( queue, tmp_path, run, monkeypatch, capsys ):
    def unreadable(): raise OSError( "ini unreadable" )
    monkeypatch.setattr( v2_ask, "_suite_token_enabled", unreadable )
    _submit_with( _client( queue, tmp_path, _user() ), run[ "token" ] )
    assert _stamp( queue ) is None
    assert _dropped( tmp_path ) == [ "'ts-parentjob':token_check_failed" ]
    assert "suite token check failed: OSError" in capsys.readouterr().out
    _submit_with( _client( queue, tmp_path, _user( uid=OWNER_UID ) ), run[ "token" ] )
    assert queue.pushed[ -1 ].spawned_by_id_hash == PARENT


def test_the_reason_word_stays_in_the_trace_and_out_of_the_http_body( queue, tmp_path, run ):
    body = _submit_with( _client( queue, tmp_path, _user() ), "wrong" )
    assert "token_" not in json.dumps( body )
    response, _ = _ask_with( _user(), "wrong" )
    assert "token_" not in response.text


# ── the token reaches no trace, log line, job argument or error body ────────

def _everything_written( queue, tmp_path, capsys ):
    out   = capsys.readouterr()
    jobs  = " ".join( repr( vars( job ) ) for job in queue.pushed )
    files = " ".join( open( tmp_path / name ).read() for name in os.listdir( tmp_path ) )
    return out.out + out.err + jobs + files


@pytest.mark.parametrize( "presented", [ "live", "wrong" ] )
def test_the_token_is_in_no_trace_log_line_or_built_job( presented, queue, tmp_path, run, capsys ):
    token = run[ "token" ] if presented == "live" else "DISTINCTIVE-WRONG-TOKEN-0123456789"
    _submit_with( _client( queue, tmp_path, _user() ), token )
    written = _everything_written( queue, tmp_path, capsys )
    assert token not in written
    assert len( written ) > 100, "the capture must hold something for the absence to mean anything"


def test_a_dropped_line_names_the_reason_and_not_the_token( queue, tmp_path, run, capsys ):
    _submit_with( _client( queue, tmp_path, _user() ), "DISTINCTIVE-WRONG-TOKEN-0123456789" )
    lines = [ l for l in capsys.readouterr().out.splitlines() if l.startswith( "[v2-lineage]" ) ]
    assert len( lines ) == 1 and "token_mismatch" in lines[ 0 ] and "DISTINCTIVE" not in lines[ 0 ]


def test_ask_never_forwards_the_token_to_the_flow( run ):
    _, kwargs = _ask_with( _user(), run[ "token" ] )
    assert run[ "token" ] not in repr( kwargs )


def test_a_422_for_a_missing_question_does_not_echo_the_token( run ):
    response, _ = _ask_with( _user(), run[ "token" ], body_extra={ "question": None } )
    assert response.status_code == 422
    assert run[ "token" ] not in response.text


def test_an_oversized_header_is_a_dropped_claim_not_a_422( run ):
    response, kwargs = _ask_with( _user(), "x" * 5000 )
    assert response.status_code == 200
    assert kwargs[ "parent_stamp_dropped" ] == "'ts-parentjob':token_mismatch"


# ── the two readers the vet uses ────────────────────────────────────────────

def test_the_vet_switch_is_the_modules_switch( monkeypatch ):
    monkeypatch.setattr( srt, "token_enabled", lambda: "sentinel" )
    assert v2_ask._suite_token_enabled() == "sentinel"


def _fake_main( monkeypatch, queue ):
    monkeypatch.setitem( sys.modules, "lupin_app.main", types.SimpleNamespace( jobs_run_queue=queue ) )


class _PoolOnly:
    """A queue that offers the accessor and nothing else, so a read of the private slot raises."""
    def __init__( self, monopolize_id ): self._mid = monopolize_id
    def get_pool_status( self ): return { "monopolize_id": self._mid, "inflight_agentic_jobs": 0 }


def test_the_slot_is_read_through_the_pool_status_accessor_only( monkeypatch ):
    _fake_main( monkeypatch, _PoolOnly( "ts-holder" ) )
    assert v2_ask._active_monopolizer_id() == "ts-holder"
    _fake_main( monkeypatch, _PoolOnly( None ) )
    assert v2_ask._active_monopolizer_id() is None


def test_a_running_queue_not_yet_initialised_holds_no_slot( monkeypatch ):
    _fake_main( monkeypatch, None )
    assert v2_ask._active_monopolizer_id() is None


# ── the switch is in the shipped INI where Rick approved it, and only there ─

def _ini_sections( name ):
    sections, current = { }, None
    path = os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "conf", name )
    for raw in open( path ).read().splitlines():
        line = raw.strip()
        if line.startswith( "[" ) and line.endswith( "]" ):
            current = line[ 1:-1 ]; sections[ current ] = { }; continue
        if current is not None and "=" in line and not line.startswith( "#" ):
            key, value = line.split( "=", 1 )
            sections[ current ][ key.strip() ] = value.strip()
    return sections


def test_the_switch_is_true_in_development_and_testing_and_absent_in_baseline_and_production():
    sections = _ini_sections( "lupin-app.ini" )
    key      = srt.TOKEN_ENABLED_KEY
    assert len( sections ) >= 5, f"too few sections to trust a negative: {sorted( sections )}"
    assert sections[ "Lupin: Development" ][ key ] == "true" and sections[ "Lupin: Testing" ][ key ] == "true"
    assert key not in sections[ "Lupin: Baseline" ] and key not in sections[ "Lupin: Production" ]


def test_the_splainer_explains_the_switch():
    text = open( os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "conf", "lupin-app-splainer.ini" ) ).read()
    assert f"\n{srt.TOKEN_ENABLED_KEY} = " in text
