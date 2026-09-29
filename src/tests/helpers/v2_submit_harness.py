"""
A real AskFlow behind POST /api/v2/submit with only the queue, tracker, cache, router,
expeditor and receptionist stubbed (rows a3c59f2d / 4e8f348e). Shared by the guards that used
to reach the test-suite door through its handler and now reach it through the v2 door.

`make_client( queue, trace_dir )` returns a TestClient; `submit_test_suite( client, **args )`
posts the test-suite command with those args and returns the response.
"""

import types

from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosa.rest.agentic_job_factory import create_agentic_job
from cosa.rest.routers               import v2_ask
from cosa.rest.v2.executor           import QueuedExecutor
from cosa.rest.v2.flow               import AskFlow

TS_COMMAND = "agent router go to test suite"


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




class Queue( _Queue ):
    """The recording queue, public name."""


def make_client( queue, trace_dir ):
    flow = AskFlow(
        _Cache(), _Router(), _Expeditor(), QueuedExecutor( queue ), _Pending(),
        crud_enabled=False, similarity_floor=100.0, writeback_enabled=False,
        notifier=lambda request: None, agentic_factory=create_agentic_job,
        receptionist_factory=_Receptionist,
        trace_dir=str( trace_dir ),
    )
    app = FastAPI()
    app.include_router( v2_ask.router )
    app.dependency_overrides[ v2_ask.get_current_user ] = lambda: { "uid": "u1234567890", "email": "t@t.com" }
    app.dependency_overrides[ v2_ask.get_ask_flow ]     = lambda: flow
    return TestClient( app )


def submit_test_suite( client, scheduled_at=None, **args ):
    """POST the test-suite command with `args`; return the response."""
    body = { "command": TS_COMMAND, "args": args, "speak": False }
    if scheduled_at: body[ "scheduled_at" ] = scheduled_at
    return client.post( "/api/v2/submit", json=body )
