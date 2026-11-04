#!/usr/bin/env python3
"""
Row 8d4a5a59 — a caller's `parent_id_hash` lineage claim is honoured only for an admin, for the
configured test account, or for the parent job's owner; otherwise the stamp is dropped, logged and
traced, and the request carries on (never a 4xx).

Same construction as test_v2_submit_test_suite_through_path.py: a real AskFlow, the real factory,
the real QueuedExecutor and a real TestSuiteJob behind a real FastAPI route. Stand-ins: the todo
queue, the cache/router/expeditor/pending seams, the job_history owner lookup (a dict keyed by the
parent id, so asking about the wrong id answers None), and the configured test account.

Venue: :7999-eligible. In-process; dry_run, so nothing executes.
"""

import json
import os
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosa.rest.agentic_job_factory import create_agentic_job
from cosa.rest.routers             import v2_ask
from cosa.rest.v2.executor         import QueuedExecutor
from cosa.rest.v2.flow             import AskFlow

TS_COMMAND  = "agent router go to test suite"
PARENT      = "ts-parentjob"
TEST_ACCOUNT = "tester@example.test"          # stands in for the configured value; never read from code
OWNER_UID   = "owner-uid-0001"


# ────────────────────────────────────────────────── the four stand-ins (everything else is real)

class _Tracker:
    """The id-scoping tracker the queued executor calls before the push."""

    def register_scoped_job( self, base_hash, user_id, session_id ):
        # The real tracker's format (queue_extensions.register_scoped_job): base::user.
        # Spelled the same way here so an assertion about the id means what it means live.
        return f"{base_hash}::{user_id}"


class _Queue:
    """A todo queue that only records what was pushed onto it."""

    def __init__( self ):
        self.pushed            = [ ]
        self.user_job_tracker  = _Tracker()

    def push( self, job ):
        self.pushed.append( job )

    def size( self ):
        return len( self.pushed )


class _Cache:
    """`submit` never reads the cache — this is here so AskFlow can be constructed."""

    def lookup( self, question ):                                  # pragma: no cover - submit skips it
        return types.SimpleNamespace( is_replay_hit=False, snapshot=None, similarity=0.0,
                                      candidates=[ ], embed_cached=False )

    def normalize( self, q ): return q
    def gist( self, q ):      return q


class _Router:
    """`submit` names its own command — nothing routes."""

    def route( self, question ):                                   # pragma: no cover - submit skips it
        raise AssertionError( "submit must not route: the caller already named the command" )


class _Expeditor:
    """`submit` states its arguments — nothing is extracted."""

    def extract( self, command, raw_args, question, spec ):        # pragma: no cover - submit skips it
        raise AssertionError( "submit must not extract: the caller already stated the args" )


class _Pending:
    """A submit never parks (flow.submit's own rule), so nothing may be stored."""

    def put( self, **kwargs ):                                     # pragma: no cover - submit never parks
        raise AssertionError( "submit must never park a question" )

    def get( self, pending_id ):     return None                   # pragma: no cover - never resumed
    def set_status( self, *a, **kw ): return None                  # pragma: no cover - never resumed


class _Receptionist:
    """Stands in for the receptionist, so a degrade is observable without its stack."""

    def __init__( self, **kwargs ):
        self.kwargs          = kwargs
        self.routing_command = "agent router go to receptionist"
        # The queued executor scopes and pushes whatever agent it is given, keyed on id_hash.
        # A stub WITHOUT one made a degrade look like a failure here while production QUEUES a
        # real receptionist job and answers "waiting" (María, row a3c59f2d).
        self.id_hash         = "rec-stub"

    def run_prompt( self, **kwargs ):                              # pragma: no cover - executor is real, job never runs
        return "I do not understand"



@pytest.fixture
def queue():
    return _Queue()


@pytest.fixture
def world( monkeypatch ):
    """The two seams the verdict reads: the parent's owner (by id) and the configured test account."""
    state = { "owners": { PARENT: OWNER_UID }, "account": TEST_ACCOUNT, "asked": [] }
    def owner_of( id_hash ):
        state[ "asked" ].append( id_hash )
        return state[ "owners" ].get( id_hash )
    monkeypatch.setattr( v2_ask, "_job_owner_id", owner_of )
    monkeypatch.setattr( v2_ask, "_test_account_email", lambda: state[ "account" ] )
    return state


def _client( queue, tmp_path, user ):
    flow = AskFlow(
        _Cache(), _Router(), _Expeditor(), QueuedExecutor( queue ), _Pending(),
        crud_enabled=False, similarity_floor=100.0, writeback_enabled=False,
        notifier=lambda request: None, agentic_factory=create_agentic_job,
        receptionist_factory=_Receptionist, trace_dir=str( tmp_path ),
    )
    app = FastAPI()
    app.include_router( v2_ask.router )
    app.dependency_overrides[ v2_ask.get_current_user ] = lambda: user
    app.dependency_overrides[ v2_ask.get_ask_flow ]     = lambda: flow
    return TestClient( app )


def _user( uid="caller-uid-9999", email="someone@example.test", roles=None ):
    return { "uid": uid, "email": email, "roles": roles or [ "user" ] }


def _submit( client, parent=PARENT ):
    body = { "command": TS_COMMAND, "args": { "test_types": "unit", "dry_run": True }, "speak": False }
    if parent is not None: body[ "parent_id_hash" ] = parent
    response = client.post( "/api/v2/submit", json=body )
    assert response.status_code == 200, response.text
    return response.json()


def _traces( tmp_path ):
    rows = []
    for name in sorted( os.listdir( tmp_path ) ):
        with open( tmp_path / name ) as handle: rows += [ json.loads( line ) for line in handle ]
    return rows


def _stamp( queue ):
    assert len( queue.pushed ) == 1
    return queue.pushed[ 0 ].spawned_by_id_hash if hasattr( queue.pushed[ 0 ], "spawned_by_id_hash" ) else None


# ── honoured ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize( "label, user", [
    ( "admin",        _user( roles=[ "admin" ] ) ),
    ( "test account", _user( email=TEST_ACCOUNT.upper() ) ),                 # case-insensitive
    ( "parent owner", _user( uid=OWNER_UID ) ),
] )
def test_a_claim_from_an_allowed_caller_is_stamped_on_the_job( label, user, queue, tmp_path, world ):
    _submit( _client( queue, tmp_path, user ) )
    assert _stamp( queue ) == PARENT, label
    assert [ r.get( "parent_id_hash_dropped" ) for r in _traces( tmp_path ) ] == [ None ]


def test_an_admin_or_the_test_account_is_honoured_without_a_job_history_read( queue, tmp_path, world ):
    _submit( _client( queue, tmp_path, _user( roles=[ "admin" ] ) ) )
    _submit( _client( queue, tmp_path, _user( email=TEST_ACCOUNT ) ) )
    assert world[ "asked" ] == [], "the cheap checks must come first"


# ── dropped ─────────────────────────────────────────────────────────────────

def test_a_stranger_claiming_a_real_parent_is_dropped_loudly_but_the_request_still_runs( queue, tmp_path, world, capsys ):
    body = _submit( _client( queue, tmp_path, _user() ) )

    assert body[ "status" ] == "waiting", "a dropped stamp is not a refusal"
    assert _stamp( queue ) is None
    assert [ r.get( "parent_id_hash_dropped" ) for r in _traces( tmp_path ) ] == [ "'ts-parentjob':not_owner" ]
    line = [ l for l in capsys.readouterr().out.splitlines() if l.startswith( "[v2-lineage]" ) ]
    assert len( line ) == 1
    assert "'someone@example.test'" in line[ 0 ] and "'caller-uid-9999'" in line[ 0 ] and "'ts-parentjob'" in line[ 0 ] and "not_owner" in line[ 0 ]


def test_a_claim_on_a_parent_with_no_job_history_row_is_dropped_as_owner_unknown( queue, tmp_path, world ):
    _submit( _client( queue, tmp_path, _user( uid=OWNER_UID ) ), parent="ts-never-persisted" )
    assert _stamp( queue ) is None
    assert [ r.get( "parent_id_hash_dropped" ) for r in _traces( tmp_path ) ] == [ "'ts-never-persisted':owner_unknown" ]
    assert world[ "asked" ] == [ "ts-never-persisted" ]


def test_with_no_test_account_configured_only_admin_and_owner_pass( queue, tmp_path, world ):
    world[ "account" ] = None
    _submit( _client( queue, tmp_path, _user( email=TEST_ACCOUNT ) ) )
    assert _stamp( queue ) is None, "a blank key trusts nobody by email"


# ── nothing to vet ──────────────────────────────────────────────────────────

def test_no_claim_changes_nothing_and_reads_nothing( queue, tmp_path, world, capsys ):
    _submit( _client( queue, tmp_path, _user() ), parent=None )
    assert _stamp( queue ) is None
    assert world[ "asked" ] == []
    assert [ r.get( "parent_id_hash_dropped" ) for r in _traces( tmp_path ) ] == [ None ]
    assert "[v2-lineage]" not in capsys.readouterr().out


# ── /api/v2/ask carries the same rule ───────────────────────────────────────

class _AskFlow:
    def __init__( self ): self.kwargs = None
    def ask( self, **kwargs ):
        self.kwargs = kwargs
        return { "path": "agent", "status": "waiting", "route_reason": "args_none", "trace_id": "t" }


def _ask( user, parent=PARENT ):
    flow = _AskFlow()
    app  = FastAPI()
    app.include_router( v2_ask.router )
    app.dependency_overrides[ v2_ask.get_current_user ] = lambda: user
    app.dependency_overrides[ v2_ask.get_ask_flow ]     = lambda: flow
    body = { "question": "hi" }
    if parent is not None: body[ "parent_id_hash" ] = parent
    assert TestClient( app ).post( "/api/v2/ask", json=body ).status_code == 200
    return flow.kwargs


def test_ask_honours_an_owner_and_forwards_no_drop_note( world ):
    kwargs = _ask( _user( uid=OWNER_UID ) )
    assert kwargs[ "parent_id_hash" ] == PARENT and "parent_stamp_dropped" not in kwargs


def test_ask_drops_a_strangers_claim_and_names_it_for_the_trace( world ):
    kwargs = _ask( _user() )
    assert kwargs[ "parent_id_hash" ] is None
    assert kwargs[ "parent_stamp_dropped" ] == "'ts-parentjob':not_owner"


def test_ask_without_a_claim_sends_none_and_no_note( world ):
    kwargs = _ask( _user(), parent=None )
    assert kwargs[ "parent_id_hash" ] is None and "parent_stamp_dropped" not in kwargs


def test_ask_flow_records_the_drop_in_its_own_trace( tmp_path ):
    """The real AskFlow.ask path: the note lands in the trace row."""
    flow = AskFlow( _Cache(), _Router(), _Expeditor(), QueuedExecutor( _Queue() ), _Pending(),
                    crud_enabled=False, similarity_floor=100.0, writeback_enabled=False,
                    notifier=lambda request: None, agentic_factory=create_agentic_job,
                    receptionist_factory=_Receptionist, trace_dir=str( tmp_path ) )
    flow.ask( question="", user_id="u", user_email="u@x", session_id="s", websocket_id="s",
              parent_id_hash=None, parent_stamp_dropped="'ts-x':not_owner" )     # a blank question is rejected at the gate; the trace is still written
    assert [ r.get( "parent_id_hash_dropped" ) for r in _traces( tmp_path ) ] == [ "'ts-x':not_owner" ]


# ── the configured account ──────────────────────────────────────────────────

class _Mgr:
    value = None
    def __init__( self, env_var_name ): pass
    def get( self, key, default=None, return_type=None ):
        assert key == v2_ask.PARENT_STAMP_TEST_ACCOUNT_KEY
        return self.value


@pytest.fixture
def no_env_account( monkeypatch ):
    monkeypatch.delenv( v2_ask.PARENT_STAMP_TEST_ACCOUNT_ENV, raising=False )
    monkeypatch.setattr( v2_ask, "ConfigurationManager", _Mgr )


@pytest.mark.parametrize( "raw, expected", [ ( "  Tester@Example.Test ", "tester@example.test" ), ( "", None ), ( "   ", None ), ( None, None ) ] )
def test_the_ini_fallback_is_read_from_configuration_and_normalised( no_env_account, raw, expected ):
    _Mgr.value = raw
    assert v2_ask._test_account_email() == expected


def test_the_env_var_wins_over_the_ini_and_is_read_at_call_time( monkeypatch, no_env_account ):
    """Risk 2: the suite's tests log in as the env var, so reading it here cannot drift from them."""
    _Mgr.value = "ini-account@example.test"
    monkeypatch.setenv( v2_ask.PARENT_STAMP_TEST_ACCOUNT_ENV, "  Env-Account@Example.Test " )
    assert v2_ask._test_account_email() == "env-account@example.test"
    monkeypatch.setenv( v2_ask.PARENT_STAMP_TEST_ACCOUNT_ENV, "second@example.test" )
    assert v2_ask._test_account_email() == "second@example.test", "read per call, not cached at import"


@pytest.mark.parametrize( "blank", [ "", "   " ] )
def test_a_blank_env_var_falls_back_to_the_ini( monkeypatch, no_env_account, blank ):
    _Mgr.value = "ini-account@example.test"
    monkeypatch.setenv( v2_ask.PARENT_STAMP_TEST_ACCOUNT_ENV, blank )
    assert v2_ask._test_account_email() == "ini-account@example.test"


def test_a_caller_logged_in_as_the_env_account_is_honoured_even_when_the_ini_names_another( monkeypatch, queue, tmp_path ):
    """The drift case end to end: INI says A, the container's env says B, the suite logs in as B."""
    monkeypatch.setattr( v2_ask, "_job_owner_id", lambda id_hash: None )
    monkeypatch.setattr( v2_ask, "ConfigurationManager", _Mgr )
    _Mgr.value = "ini-account@example.test"
    monkeypatch.setenv( v2_ask.PARENT_STAMP_TEST_ACCOUNT_ENV, "env-account@example.test" )
    _submit( _client( queue, tmp_path, _user( email="env-account@example.test" ) ) )
    assert _stamp( queue ) == PARENT


def _ini_sections():
    """{section: set of keys} read straight from the shipped INI text (first-word headers, no interpolation)."""
    sections, current = {}, None
    path = os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "conf", "lupin-app.ini" )
    for raw in open( path ).read().splitlines():
        line = raw.strip()
        if line.startswith( "[" ) and line.endswith( "]" ):
            current = line[ 1:-1 ]; sections[ current ] = set(); continue
        if current is not None and "=" in line and not line.startswith( "#" ):
            sections[ current ].add( line.split( "=", 1 )[ 0 ].strip() )
    return sections


def test_the_ini_key_is_in_development_and_testing_and_not_in_baseline_or_production():
    """Risk 3: Baseline is inherited by Production; no tester address may be trusted there."""
    sections = _ini_sections()
    key      = v2_ask.PARENT_STAMP_TEST_ACCOUNT_KEY
    assert len( sections ) >= 5, f"the INI reader found too few sections to trust a negative: {sorted( sections )}"
    assert key in sections[ "Lupin: Development" ] and key in sections[ "Lupin: Testing" ]
    assert key not in sections[ "Lupin: Baseline" ] and key not in sections[ "Lupin: Production" ]


# ── the logged and traced value is bounded and escaped ──────────────────────

def test_a_hostile_parent_id_cannot_forge_a_log_line_or_flood_it( queue, tmp_path, world, capsys ):
    hostile = "ts-x\n[v2-lineage] parent_id_hash dropped: caller='admin' " + "A" * 500
    _submit( _client( queue, tmp_path, _user() ), parent=hostile )

    lines = [ l for l in capsys.readouterr().out.splitlines() if l.startswith( "[v2-lineage]" ) ]
    assert len( lines ) == 1, "the newline in the id must not start a second log line"
    assert len( lines[ 0 ] ) < 400, f"the logged value was not capped: {len( lines[ 0 ] )} chars"
    note = [ r.get( "parent_id_hash_dropped" ) for r in _traces( tmp_path ) ][ 0 ]
    assert "\n" not in note and len( note ) < 120, note
    assert "..." in note and note.endswith( ":owner_unknown" ), note


@pytest.mark.parametrize( "value, expected", [ ( "short", "'short'" ), ( "x" * 80, repr( "x" * 80 ) ), ( "x" * 81, repr( "x" * 80 ) + "..." ) ] )
def test_loggable_caps_at_eighty_characters_and_marks_the_cut( value, expected ):
    assert v2_ask._loggable( value ) == expected
