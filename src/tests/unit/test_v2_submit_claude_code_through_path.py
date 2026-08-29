#!/usr/bin/env python3
"""
A bounded Claude Code job goes through POST /api/v2/submit and lands on the queue.

RICK'S RULING, 2026-08-21: *"A Claude code job should absolutely be upgraded and updated
to use the front door submit under V2. Under no circumstances should we allow it to die
on the vine."* The two `/api/claude-code/*` doors become tombstones in the same change,
so this file is the proof that what they did is still possible — before they stop doing
it.

WHAT IS REAL HERE, AND WHY THAT IS THE POINT. The flow is a real `AskFlow`, the factory
is the real `create_agentic_job`, the executor is the real `QueuedExecutor`, and the job
that comes out the far end is a real `ClaudeCodeJob`. Only the four things that need a
server are stand-ins: the queue it is pushed onto, the id-scoping tracker, the cache and
the router (neither of which `submit` reaches — it names its command). A test that mocked
the factory would prove the door forwards a dict; it could not prove the dict BUILDS the
job the retiring door built, which is the whole claim the tombstone rests on.

WHY `scheduled_at` GETS ITS OWN ASSERTION. It is what the off-peak scheduling rule in
CLAUDE.md is made of, and it is not an argument to the agent — it is a directive to the
queue, carried as a top-level field on SubmitRequest and stamped on the job by the
factory. A cutover that queued the work but ran it immediately would look green in every
other assertion here and would put batch jobs back into Rick's interactive window.

Venue: :7999-eligible. Pure in-process — no server, no network, no LLM, no Claude CLI
(`dry_run=True` never leaves the constructor in this test; nothing is executed).
"""

import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosa.agents.claude_code.job     import ClaudeCodeJob
from cosa.rest.agentic_job_factory   import create_agentic_job
from cosa.rest.routers               import v2_ask
from cosa.rest.v2.executor           import QueuedExecutor
from cosa.rest.v2.flow               import AskFlow

CC_COMMAND   = "agent router go to claude code"
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
        "command"      : CC_COMMAND,
        "args"         : { "prompt"    : "Run the unit suite and report the failures",
                           "project"   : "lupin",
                           "task_type" : "BOUNDED",
                           "max_turns" : 7,
                           "dry_run"   : True },
        "question"     : "run the unit suite",
        "scheduled_at" : SCHEDULED_AT,
        "speak"        : False,
    }
    body.update( overrides )
    return client.post( "/api/v2/submit", json=body )


# ────────────────────────────────────────────────────────────────────── the through path

def test_a_bounded_claude_code_submit_is_accepted( client ):
    """The door answers, and it answers `waiting` — the queued executor's success."""
    response = _submit( client )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body[ "path"   ] == "agent",   body
    assert body[ "status" ] == "waiting", body
    assert body[ "job_id" ], body


def test_the_job_that_lands_on_the_queue_is_a_real_claude_code_job( client, queue ):
    """
    Not "a job was pushed" — the RIGHT job. The retiring door built a ClaudeCodeJob with
    the caller's five fields on it, and that is what has to come out of the new one.
    """
    _submit( client )
    assert len( queue.pushed ) == 1, queue.pushed
    job = queue.pushed[ 0 ]
    assert isinstance( job, ClaudeCodeJob ), type( job )
    assert job.routing_command == CC_COMMAND
    assert job.prompt    == "Run the unit suite and report the failures"
    assert job.project   == "lupin"
    assert job.task_type == "BOUNDED"
    assert job.max_turns == 7
    assert job.dry_run   is True


def test_scheduled_at_reaches_the_job( client, queue ):
    """
    The off-peak scheduling rule is built on this field. It is a queue directive, not an
    agent argument, so it travels as a top-level SubmitRequest field and is stamped on
    the job by the factory.

    RED ON REVERT: drop the `scheduled_at` stamp in `create_agentic_job` and this fails
    while every other assertion in this file stays green — the work still queues, it just
    runs at the wrong time.
    """
    _submit( client )
    assert queue.pushed[ 0 ].scheduled_at == SCHEDULED_AT


def test_monopolize_reaches_the_job( client, queue ):
    """The other directive the retiring door carried, and set on the job by hand."""
    _submit( client, monopolize=True )
    assert queue.pushed[ 0 ].monopolize is True


def test_the_queued_id_is_the_scoped_one_and_it_is_what_the_caller_is_told( client, queue ):
    """
    v1 scoped the id BEFORE the push so a filtering read never saw an unscoped row, and
    returned that same id as `job_id`. Both halves still hold.
    """
    body = _submit( client ).json()
    job  = queue.pushed[ 0 ]
    assert job.id_hash.startswith( "cc-" ) and job.id_hash.endswith( "::u1234567890" ), job.id_hash
    assert body[ "job_id" ] == job.id_hash


def test_a_submit_with_no_prompt_is_refused_and_queues_nothing( client, queue ):
    """
    `prompt` is the command's one required argument. A submit missing it comes back
    `needs_input` naming what is missing — and, because there is no human behind a
    submit, is NOT parked and NOT queued.
    """
    body = _submit( client, args={ "project": "lupin" } ).json()
    assert body[ "status"       ] == "needs_input", body
    assert body[ "args_missing" ] == [ "prompt" ],  body
    assert body[ "pending_id"   ] is None,          body
    assert queue.pushed == [ ]


# ─────────────────────────────────────── the guard the retiring door held, and this one must

def test_an_unknown_task_type_is_refused_and_queues_nothing( client, queue ):
    """
    THE ONE THING THE OLD DOOR DID THAT THE SHAPE ALONE DOES NOT CARRY.
    `/api/claude-code/submit` upper-cased `task_type` and answered 400 for anything that
    was not BOUNDED or INTERACTIVE. `/api/v2/submit` is generic — it validates `args`
    against the command's argument contract, and that contract says nothing about which
    VALUES `task_type` may take.

    Left unguarded, "BOUNDEDD" reaches ClaudeCodeJob, which stores it and then tests it
    with `== "BOUNDED"` at every branch (job.py:264, :354) — so a typo does not fail, it
    silently runs an INTERACTIVE task that waits for a human who is not there. A
    fire-and-forget batch job becoming an interactive one is not a smaller version of the
    job the caller asked for.

    The guard belongs to the JOB, not to the door: the job's own docstring already
    promises `task_type is "BOUNDED" or "INTERACTIVE"`, and putting it there covers the
    voice path and the in-process callers too, not just this one endpoint.

    RED BEFORE THE FIX: this failed with the job queued and `task_type == "BOUNDEDD"`.
    """
    args = { "prompt": "Run the unit suite", "project": "lupin", "task_type": "BOUNDEDD" }
    body = _submit( client, args=args ).json()
    assert queue.pushed == [ ], (
        f"a job with task_type=BOUNDEDD was queued: {getattr( queue.pushed[ 0 ], 'task_type', None )!r}"
    )
    assert body[ "path" ] == "receptionist", body
    assert "BOUNDEDD" in ( body[ "error" ] or "" ), body[ "error" ]


def test_task_type_is_still_case_insensitive( client, queue ):
    """
    The old door upper-cased before validating, so "bounded" was always legal. The guard
    must not turn a case difference into a refusal — that would break a caller the
    retiring door served.
    """
    args = { "prompt": "Run the unit suite", "project": "lupin", "task_type": "bounded" }
    _submit( client, args=args )
    assert queue.pushed[ 0 ].task_type == "BOUNDED"


def test_an_interactive_claude_code_submit_still_works( client, queue ):
    """The other legal value — the guard must admit both, not just the default."""
    args = { "prompt": "Pair with me on the parser", "project": "lupin", "task_type": "INTERACTIVE" }
    _submit( client, args=args )
    assert queue.pushed[ 0 ].task_type == "INTERACTIVE"
