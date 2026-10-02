"""
Row 4cbd4858 — POST /api/v2/ask can carry `parent_id_hash`, so a monopolizing suite job's own asks
are admitted through its intake hold instead of sitting out the 120 s collect timeout.

Four seams, one chain: the request field -> flow.ask -> the trace -> QueuedExecutor stamps
`spawned_by_id_hash` -> v2_eval's client sends it. Every test also pins the ABSENT case, because
the field must change nothing when it is not sent.

Venue: :7999 (unit, no server).
"""

import asyncio
import os
import sys

import pytest

import cosa.utils.util as cu
from cosa.rest.routers import v2_ask
from cosa.rest.v2.executor import QueuedExecutor, Work
from cosa.rest.v2.trace import StageTrace

_scripts = os.path.join( cu.get_project_root(), "src", "scripts" )
if _scripts not in sys.path: sys.path.insert( 0, _scripts )
import v2_eval as ve   # noqa: E402

USER = { "uid": "u1234567890", "email": "u@x.com" }


class _Job:
    """A job with no lineage attribute, like AgentBase / SolutionSnapshot."""
    def __init__( self ): self.id_hash = "base"; self.user_id = "x"; self.user_email = "x"


class _Queue:
    def __init__( self ):
        self.user_job_tracker = self
        self.pushed           = []
    def register_scoped_job( self, base, user_id, session_id=None ): return f"{base}::{user_id}"
    def push( self, job ): self.pushed.append( job )
    def size( self ): return len( self.pushed )


def _submit( trace ):
    job   = _Job()
    queue = _Queue()
    work  = Work( "agent", job, "u-1", "u@x.com", "s-1", snapshotable=True )
    out   = QueuedExecutor( queue ).submit( work, trace )
    assert out.status == "waiting" and queue.pushed == [ job ]
    return job


# ---- executor: the stamp -------------------------------------------------------------------
def test_a_parent_on_the_trace_is_stamped_on_the_queued_job():
    trace = StageTrace( trace_dir="/tmp/unused" )
    trace.set( "parent_id_hash", "suite-job-hash" )
    assert _submit( trace ).spawned_by_id_hash == "suite-job-hash"


@pytest.mark.parametrize( "value", [ None, "" ] )
def test_no_parent_leaves_the_job_untouched_and_foreign( value ):
    trace = StageTrace( trace_dir="/tmp/unused" )
    if value is not None: trace.set( "parent_id_hash", value )
    assert not hasattr( _submit( trace ), "spawned_by_id_hash" )


# ---- the request model and the route -------------------------------------------------------
def test_the_request_field_is_optional_and_defaults_to_none():
    assert v2_ask.AskRequest( question="hi" ).parent_id_hash is None
    assert v2_ask.AskRequest( question="hi", parent_id_hash="abc" ).parent_id_hash == "abc"


class _Flow:
    def __init__( self ): self.kwargs = None
    def ask( self, **kwargs ):
        self.kwargs = kwargs
        return { "path": "agent", "status": "waiting", "route_reason": "args_none", "trace_id": "t" }


@pytest.mark.parametrize( "sent, expected", [ ( "suite-job-hash", "suite-job-hash" ), ( None, None ) ] )
def test_the_route_passes_the_parent_to_flow_ask( sent, expected ):
    flow = _Flow()
    asyncio.run( v2_ask.v2_ask( v2_ask.AskRequest( question="hi", parent_id_hash=sent ),
                                current_user=USER, flow=flow ) )
    assert flow.kwargs[ "parent_id_hash" ] == expected


# ---- the eval client -----------------------------------------------------------------------
class _Reply:
    status_code = 200
    def json( self ): return { "path": "agent" }


def _body_sent( **client_kwargs ):
    seen = []
    def post_fn( url, json, headers, timeout ):
        seen.append( json )
        return _Reply()
    ve.HttpAskClient( "http://localhost:8000", bearer="j", post_fn=post_fn, **client_kwargs ).ask( "q" )
    return seen[ 0 ]


def test_the_eval_client_sends_the_parent_when_it_has_one():
    assert _body_sent( parent_id_hash="suite-job-hash" )[ "parent_id_hash" ] == "suite-job-hash"


def test_the_eval_client_body_is_unchanged_without_one():
    assert "parent_id_hash" not in _body_sent()


@pytest.mark.parametrize( "env, expected", [ ( "suite-job-hash", "suite-job-hash" ), ( None, None ), ( "", None ) ] )
def test_the_default_factory_reads_the_suite_lineage_env( monkeypatch, env, expected ):
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", "a@b.c" )
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD", "pw" )
    if env is None: monkeypatch.delenv( "LUPIN_TEST_MONOPOLIZE_PARENT_ID", raising=False )
    else:           monkeypatch.setenv( "LUPIN_TEST_MONOPOLIZE_PARENT_ID", env )

    class _Login:
        def raise_for_status( self ): return None
        def json( self ): return { "tokens": { "access_token": "jwt" } }
    class _Requests:
        @staticmethod
        def post( url, json, timeout ): return _Login()
    monkeypatch.setitem( sys.modules, "requests", _Requests )

    assert ve._default_client_factory( "http://localhost:8000" ).parent_id_hash == expected
