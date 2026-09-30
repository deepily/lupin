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
    """A REFUSED submit (unbalanced quoting here) queues nothing, so there is no position."""
    body = _submit( client, args={ "test_types": "integration", "pytest_args": '-k "unbalanced' } ).json()
    assert body[ "queue_position" ] is None, body
    assert queue.pushed == []


def test_positive_control_an_unknown_command_DOES_queue_a_receptionist_and_says_waiting( client, queue ):
    """
    The control the refusal tests stand on. An unknown COMMAND is not a refusal: the flow
    degrades it to the receptionist, the queued executor pushes a real receptionist job, and
    the answer is status "waiting" with a position. If the harness could not show that, a
    green "queues nothing" over a refusal would mean nothing (María, row a3c59f2d: the first
    cut of these tests passed because the receptionist STUB lacked an id_hash and so failed
    where production queues).
    """
    body = _submit( client, command="agent router go to nowhere at all", args={} ).json()
    assert body[ "status" ] == "waiting" and body[ "queue_position" ] == 1, body
    assert len( queue.pushed ) == 1 and queue.pushed[ 0 ].routing_command == "agent router go to receptionist"


# ── what door 18 did that v2 answers differently — pinned so nobody assumes ──

def test_malformed_pytest_args_are_not_a_400_on_v2_and_queue_nothing( client, queue ):
    """
    DOOR 18 ANSWERED 400 for `-k "unbalanced`. The v2 door answers HTTP 200 with a TERMINAL
    `failed` (route_reason `submit_refused`, the cause in `error`) and queues nothing — the
    zero-test run the 400 exists to prevent still cannot happen — so a caller that keyed on
    HTTP 400 must key on `status` / `error` instead.

    NOT "waiting": the first cut let the builder's ValueError degrade to the receptionist,
    and the queued executor then pushed a receptionist job and reported status "waiting" with
    a job id for a submit that was refused (María's review). The builder now raises
    SubmitRefused, which the flow reports as failed.
    """
    response = _submit( client, args={ "test_types": "integration", "pytest_args": '-k "unbalanced' } )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body[ "status" ] == "failed" and body[ "route_reason" ] == "submit_refused", body
    assert body[ "path" ] == "agent", body      # not "receptionist": nothing was handed to a fallback
    assert body[ "job_id" ] is None, body
    assert "Malformed pytest_args" in ( body[ "error" ] or "" ), body
    assert queue.pushed == []
    assert body[ "queue_position" ] is None


def test_a_contradictory_timeout_is_refused_the_same_way( client, queue ):
    body = _submit( client, args={ "test_types": "integration",
                                   "pytest_args": "--timeout 5400 src/tests/integration/x.py" } ).json()
    assert body[ "status" ] == "failed" and body[ "route_reason" ] == "submit_refused", body
    assert queue.pushed == []
