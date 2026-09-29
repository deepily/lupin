#!/usr/bin/env python3
"""
A test-suite job goes through POST /api/v2/submit, lands on the queue, and says WHERE
(row a3c59f2d — door 18, `/api/test-suite/submit`).

RICK'S RULING, 2026-09-29 (answered, not defaulted): *"Retire after v2 gap"* — door 18
retires to 410 once v2 covers `queue_position`, which is the ONE thing the v1 door returned
that `/api/v2/submit` did not. The v1 door answered `todo_queue.size()` taken right after
its push; `AskResponse.queue_position` is now that same number, set by the queued executor.

This file is the proof that the v2 door can do what door 18 did for a test-suite job — build
the real `TestSuiteJob` from the same argument spellings (comma-string `test_types`,
quote-aware `pytest_args`, `dry_run`, `auto_fix_on_failure`, `env_vars`), stamp
`scheduled_at`, keep `monopolize` (forced by the job's own constructor, on both paths), and
report the position. Same construction as test_v2_submit_claude_code_through_path.py: a real
AskFlow, the real factory, the real QueuedExecutor, a real job; only the queue, the tracker,
the cache and the router are stand-ins.

Venue: :7999-eligible. Pure in-process; dry_run means nothing is ever executed.
"""

import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosa.agents.test_suite.job      import TestSuiteJob
from cosa.rest.agentic_job_factory   import create_agentic_job
from cosa.rest.routers               import v2_ask
from cosa.rest.v2.executor           import QueuedExecutor
from cosa.rest.v2.flow               import AskFlow

TS_COMMAND   = "agent router go to test suite"
SCHEDULED_AT = "2026-08-22T11:00:00-04:00"   # inside the 10 AM – 1 PM window CLAUDE.md prefers


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

    def run_prompt( self, **kwargs ):                              # pragma: no cover - executor is real, job never runs
        return "I do not understand"


@pytest.fixture
def queue():
    return _Queue()


@pytest.fixture
def client( queue, tmp_path ):
    flow = AskFlow(
        _Cache(), _Router(), _Expeditor(), QueuedExecutor( queue ), _Pending(),
        crud_enabled=False, similarity_floor=100.0, writeback_enabled=False,
        notifier=lambda request: None, agentic_factory=create_agentic_job,
        receptionist_factory=_Receptionist,
        trace_dir=str( tmp_path ),
    )
    app = FastAPI()
    app.include_router( v2_ask.router )
    app.dependency_overrides[ v2_ask.get_current_user ] = lambda: { "uid": "u1234567890", "email": "t@t.com" }
    app.dependency_overrides[ v2_ask.get_ask_flow ]     = lambda: flow
    return TestClient( app )


def _submit( client, **overrides ):
    body = {
        "command"      : TS_COMMAND,
        "args"         : { "test_types"          : "integration",
                           "pytest_args"         : "-k \"a or b\" -v",
                           "dry_run"             : True,
                           "auto_fix_on_failure" : False,
                           "env_vars"            : { "TFE_RESUME_E2E_LIVE": "1" } },
        "scheduled_at" : SCHEDULED_AT,
        "speak"        : False,
    }
    body.update( overrides )
    return client.post( "/api/v2/submit", json=body )



# ────────────────────────────────────────────────────────────────────── the through path

def test_a_test_suite_submit_is_accepted_and_waiting( client ):
    response = _submit( client )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body[ "path" ] == "agent", body
    assert body[ "status" ] == "waiting", body
    assert body[ "job_id" ].startswith( "ts-" ), body


def test_the_job_on_the_queue_is_the_real_test_suite_job_built_from_door_18s_spellings( client, queue ):
    _submit( client )
    assert len( queue.pushed ) == 1
    job = queue.pushed[ 0 ]
    assert isinstance( job, TestSuiteJob ), type( job )
    assert job.test_types == [ "integration" ]
    assert job.pytest_args[ :2 ] == [ "-k", "a or b" ], job.pytest_args     # ONE -k value: quote-aware split survives
    assert job.dry_run is True
    assert job.auto_fix_on_failure is False
    assert job.env_vars == { "TFE_RESUME_E2E_LIVE": "1" }


def test_monopolize_is_forced_by_the_job_itself_without_the_caller_asking( client, queue ):
    """Door 18 said 'always monopolize'; on v2 it is the constructor that says it."""
    _submit( client )
    assert queue.pushed[ 0 ].monopolize is True


def test_scheduled_at_reaches_the_job( client, queue ):
    _submit( client )
    assert queue.pushed[ 0 ].scheduled_at == SCHEDULED_AT


# ── the gap this row closes ──────────────────────────────────────────────────

def test_queue_position_is_the_queue_size_right_after_the_push( client, queue ):
    """The number door 18 returned: with two jobs already waiting, this one is the third."""
    queue.pushed.extend( [ object(), object() ] )
    body = _submit( client ).json()
    assert body[ "queue_position" ] == 3, body


def test_an_empty_queue_puts_the_job_at_one( client ):
    assert _submit( client ).json()[ "queue_position" ] == 1


def test_queue_position_is_null_when_nothing_was_queued( client, queue ):
    """A refusal (a missing required argument would do it; here an unknown command) queues nothing."""
    body = _submit( client, command="agent router go to nowhere at all", args={} ).json()
    assert body[ "queue_position" ] is None, body
    assert queue.pushed == []


# ── what door 18 did that v2 answers differently — pinned so nobody assumes ──

def test_malformed_pytest_args_are_not_a_400_on_v2_and_queue_nothing( client, queue ):
    """
    DOOR 18 ANSWERED 400 for `-k "unbalanced`. The v2 door does not: the factory raises and
    the flow degrades to the receptionist (status failed / path receptionist) with the cause
    in `error`. Nothing is queued, which is what matters — the zero-test run the 400 exists
    to prevent still cannot happen — but a caller that keyed on HTTP 400 must key on
    `status` / `error` instead.
    """
    response = _submit( client, args={ "test_types": "integration", "pytest_args": '-k "unbalanced' } )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body[ "status" ] != "waiting", body
    assert "Malformed pytest_args" in ( body[ "error" ] or "" ), body
    assert queue.pushed == []
    assert body[ "queue_position" ] is None
