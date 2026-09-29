#!/usr/bin/env python3
"""
The mock-job command goes through POST /api/v2/submit and reproduces BOTH modes of the
retired door 14 (`/api/mock-job/submit`, row 432511fd).

Same construction as test_v2_submit_test_suite_through_path.py: a real AskFlow, the real
factory, the real QueuedExecutor, the real MockAgenticJob / TestSuiteJob; only the queue,
the tracker, the cache, the router and the RuntimeArgumentExpeditor's LLM/notification call
are stand-ins.

Venue: :7999-eligible. Pure in-process; nothing executes.
"""

import types
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosa.agents.test_harness.mock_job import MockAgenticJob
from cosa.agents.test_suite.job        import TestSuiteJob
from cosa.rest.agentic_job_factory     import create_agentic_job
from cosa.rest.routers                 import v2_ask
from cosa.rest.v2.executor             import QueuedExecutor
from cosa.rest.v2.flow                 import AskFlow

MOCK_COMMAND = "agent router go to mock job"
SCHEDULED_AT = "2026-08-22T11:00:00-04:00"


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


def _submit( client, args=None, headers=None, **overrides ):
    body = { "command": MOCK_COMMAND, "args": args if args is not None else { }, "speak": False }
    body.update( overrides )
    return client.post( "/api/v2/submit", json=body, headers=headers or { } )


class _FakeExpeditor:
    """Stands in for RuntimeArgumentExpeditor: records the call, answers what it is told to."""
    instances = [ ]

    def __init__( self, *a, **kw ):
        self.calls = [ ]
        _FakeExpeditor.instances.append( self )

    answer = { "test_types": "unit" }
    status = "answered"

    def expedite( self, **kwargs ):
        self.calls.append( kwargs )
        kwargs[ "context" ].notification_status = _FakeExpeditor.status
        return dict( _FakeExpeditor.answer ) if _FakeExpeditor.answer is not None else None


@pytest.fixture
def expeditor():
    """Patch the expeditor + config manager the builder imports lazily; reset the fake."""
    _FakeExpeditor.instances = [ ]
    _FakeExpeditor.answer    = { "test_types": "unit" }
    _FakeExpeditor.status    = "answered"
    with patch( "cosa.agents.runtime_argument_expeditor.expeditor.RuntimeArgumentExpeditor", _FakeExpeditor ), \
         patch( "cosa.config.configuration_manager.ConfigurationManager", return_value=MagicMock() ):
        yield _FakeExpeditor


# ── PLAIN mode ───────────────────────────────────────────────────────────────

def test_a_plain_mock_submit_queues_a_real_mock_job_and_reports_it( client, queue ):
    response = _submit( client, args={ "fixed_iterations": 4, "fixed_sleep": 0.1, "description": "hi" } )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body[ "path" ] == "agent" and body[ "status" ] == "waiting", body
    assert body[ "job_id" ].startswith( "mock-" ), body
    assert body[ "queue_position" ] == 1, body
    assert len( queue.pushed ) == 1 and isinstance( queue.pushed[ 0 ], MockAgenticJob )
    config = body[ "submit_details" ][ "config" ]
    assert config[ "iterations" ] == 4 and config[ "sleep_seconds" ] == 0.1
    assert config[ "will_fail" ] is False and config[ "fail_at_iteration" ] is None
    assert config[ "estimated_duration" ] == "0.4s"


def test_a_plain_mock_job_records_the_mock_command_as_its_own( client, queue ):
    _submit( client )
    assert queue.pushed[ 0 ].routing_command == MOCK_COMMAND


def test_a_certain_failure_reports_the_iteration_it_fails_at( client ):
    config = _submit( client, args={ "failure_probability": 1.0 } ).json()[ "submit_details" ][ "config" ]
    assert config[ "will_fail" ] is True and isinstance( config[ "fail_at_iteration" ], int )


def test_scheduled_at_and_monopolize_travel_top_level_and_reach_the_job( client, queue ):
    _submit( client, scheduled_at=SCHEDULED_AT, monopolize=True )
    job = queue.pushed[ 0 ]
    assert job.scheduled_at == SCHEDULED_AT and job.monopolize is True


def test_an_inverted_range_queues_nothing_and_reports_no_details( client, queue ):
    body = _submit( client, args={ "iterations_min": 8, "iterations_max": 3 } ).json()
    assert queue.pushed == [ ]
    assert body[ "queue_position" ] is None and body.get( "submit_details" ) is None, body


def test_an_out_of_bounds_argument_queues_nothing( client, queue ):
    _submit( client, args={ "iterations_max": 99 } )
    assert queue.pushed == [ ]


def test_an_inverted_sleep_range_queues_nothing( client, queue ):
    _submit( client, args={ "sleep_min": 5.0, "sleep_max": 1.0 } )
    assert queue.pushed == [ ]


# ── EXPEDITOR TEST mode ──────────────────────────────────────────────────────

def test_a_voice_command_builds_a_dry_run_job_of_the_matched_command( client, queue, expeditor ):
    body = _submit( client, args={ "voice_command": "please run the test suite" } ).json()
    assert body[ "status" ] == "waiting" and body[ "job_id" ].startswith( "ts-" ), body
    job = queue.pushed[ 0 ]
    assert isinstance( job, TestSuiteJob ) and job.dry_run is True
    config = body[ "submit_details" ][ "config" ]
    assert config[ "command" ] == "agent router go to test suite"
    assert config[ "voice_command" ] == "please run the test suite"
    assert config[ "dry_run" ] is True and config[ "force_failure_mode" ] is None
    assert "user_id" not in config[ "args_resolved" ] and "user_email" not in config[ "args_resolved" ]


def test_the_expeditor_job_keeps_the_matched_commands_identity_not_the_mock_commands( client, queue, expeditor ):
    """`_finish` must NOT run over it: job_history has to describe the job that actually runs."""
    _submit( client, args={ "voice_command": "please run the test suite" } )
    assert queue.pushed[ 0 ].routing_command == "agent router go to test suite"


def test_the_callers_bearer_token_reaches_the_expeditor_through_the_threadpool( client, expeditor ):
    """The ContextVar set in v2_submit must survive run_in_threadpool into the builder."""
    _submit( client, args={ "voice_command": "run the test suite" }, headers={ "Authorization": "Bearer tok-123" } )
    assert expeditor.instances[ 0 ].calls[ 0 ][ "bearer_token" ] == "tok-123"


def test_no_authorization_header_means_no_token_and_a_later_request_does_not_inherit_one( client, expeditor ):
    _submit( client, args={ "voice_command": "run the test suite" }, headers={ "Authorization": "Bearer tok-123" } )
    _submit( client, args={ "voice_command": "run the test suite" } )
    _submit( client, args={ "voice_command": "run the test suite" }, headers={ "Authorization": "Basic abc" } )
    tokens = [ i.calls[ 0 ][ "bearer_token" ] for i in expeditor.instances ]
    assert tokens == [ "tok-123", None, None ], tokens


def test_force_failure_mode_is_reported_and_reaches_the_resolved_args( client, expeditor ):
    body = _submit( client, args={ "voice_command": "run the test suite", "force_failure_mode": "rate_limit" } ).json()
    config = body[ "submit_details" ][ "config" ]
    assert config[ "force_failure_mode" ] == "rate_limit"
    assert "force_failure_mode=rate_limit" in body[ "submit_details" ][ "message" ]
    assert "rate_limit" in config[ "args_resolved" ].get( "force_failure_mode", "" )


def test_a_cancelled_interview_is_a_failed_result_with_the_reason_and_the_notification_status( client, queue, expeditor ):
    expeditor.answer = None
    expeditor.status = "no_response"
    body = _submit( client, args={ "voice_command": "run the test suite" } ).json()
    assert body[ "status" ] == "failed" and body[ "route_reason" ] == "expeditor_cancelled", body
    assert body[ "submit_details" ][ "config" ][ "notification_status" ] == "no_response"
    assert body[ "submit_details" ][ "config" ][ "result" ] == "cancelled_or_timeout"
    assert queue.pushed == [ ]


def test_a_voice_command_that_matches_nothing_queues_nothing_and_names_the_choices( client, queue, expeditor ):
    body = _submit( client, args={ "voice_command": "tell me a joke" } ).json()
    assert queue.pushed == [ ] and body[ "queue_position" ] is None, body


def test_the_matcher_never_picks_the_mock_command_itself( client, queue, expeditor ):
    """'mock job' contains both keywords of the mock command; it must not match itself."""
    _submit( client, args={ "voice_command": "run the mock job" } )
    assert queue.pushed == [ ]
