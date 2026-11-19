"""
The extractor's model-door probe and the factory command that submits it.

The model is a recorded double handed to model_transport.complete through its query_fn seam, so the real
call path runs. The live check is the scheduled :8000 run; these tests pin the probe's own behaviour.
"""

import asyncio
import concurrent.futures
import json

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

import cosa.agents.principle_learner.extractor_job as job_module
from cosa.agents.principle_learner.extractor_job import PrincipleExtractorJob
from cosa.repo.doc_lint import model_transport
from cosa.rest.agentic_job_factory import JOB_BUILDERS, create_agentic_job
from cosa.rest.job_state import JobState
from cosa.rest.v2.refusal import SubmitRefused

MODEL   = "claude-test-model"
COMMAND = "agent router go to principle extractor"


def _text_double( text ):
    """
    Build a query function that answers with one assistant message holding text.

    Ensures:
        - returns an async generator function in the shape model_transport.complete takes
    """
    async def query( prompt, options ):
        yield AssistantMessage( content=[ TextBlock( text=text ) ], model=MODEL )
        yield ResultMessage( subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id="s", result=text )
    return query


async def _error_double( prompt, options ):
    """
    Stand in for a model call that ends in an error result.

    Ensures:
        - yields one error result message
    """
    yield ResultMessage( subtype="error", duration_ms=1, duration_api_ms=1, is_error=True, num_turns=1, session_id="s", result="boom" )


def _probe( query_fn ):
    """
    Build a probe job over a model double.

    Ensures:
        - the job has no session factory, so any database use would raise
    """
    return PrincipleExtractorJob( "probe", "u-1", "o@example.com", query_fn=query_fn, model=MODEL, timeout_seconds=30, probe=True )


def _run( job ):
    """
    Run the job's async body and read its JSON.

    Ensures:
        - returns the parsed summary dict
    """
    return json.loads( asyncio.run( job._execute() ) )


def test_a_reply_inside_the_timeout_reads_probe_ok_and_names_the_door_facts():
    out = _run( _probe( _text_double( "ok" ) ) )
    assert out[ "status" ] == "probe_ok" and out[ "reply" ] == "ok"
    assert out[ "model" ] == MODEL and out[ "timeout" ] == 30 and out[ "loop_running" ] is True
    assert out[ "transport" ] == "claude" and out[ "cli_path" ] is None and out[ "seconds" ] >= 0


def test_the_probe_touches_no_database_and_no_embedding( monkeypatch ):
    def forbidden( *args, **kwargs ): raise AssertionError( "the probe must not open a session or embed" )
    monkeypatch.setattr( job_module, "default_session", forbidden )
    monkeypatch.setattr( job_module, "default_embed", forbidden )
    assert _run( _probe( _text_double( "ok" ) ) )[ "status" ] == "probe_ok"


@pytest.fixture
def no_budget():
    """
    Start and end a test with no call cap set in this process.

    Ensures:
        - model_transport has no cap and no ledger before the test and again after it
    """
    model_transport.set_budget( None, {} )
    yield
    model_transport.set_budget( None, {} )


def test_the_probe_reads_the_cap_for_the_model_as_a_literal_and_lists_every_cap( no_budget, tmp_path ):
    model_transport.set_budget( str( tmp_path / "calls.jsonl" ), { MODEL: 5, "other-model": 1 } )
    out = _run( _probe( _text_double( "ok" ) ) )
    assert out[ "budget_cap" ] == 5 and out[ "budget_caps" ] == { MODEL: 5, "other-model": 1 }
    assert model_transport.calls_used( MODEL ) == 1, "the probe's own call is charged against the cap"


def test_a_model_with_no_cap_reads_none_and_an_empty_cap_table( no_budget ):
    out = _run( _probe( _text_double( "ok" ) ) )
    assert out[ "budget_cap" ] is None and out[ "budget_caps" ] == {}


def test_a_failed_call_is_a_named_probe_error_not_an_exception():
    out = _run( _probe( _error_double ) )
    assert out[ "status" ] == "probe_error" and out[ "error_type" ] == "ModelCallError" and "boom" in out[ "error" ]
    assert "reply" not in out


def test_a_call_with_nothing_left_in_its_budget_is_a_named_probe_error( monkeypatch ):
    async def refused( *args, **kwargs ): raise model_transport.CallBudgetExceeded( "no calls left" )
    monkeypatch.setattr( model_transport, "complete", refused )
    out = _run( _probe( None ) )
    assert out[ "status" ] == "probe_error" and out[ "error_type" ] == "CallBudgetExceeded"


def test_an_error_that_is_not_a_model_call_error_reaches_the_queue( monkeypatch ):
    async def broken( *args, **kwargs ): raise RuntimeError( "a real bug" )
    monkeypatch.setattr( model_transport, "complete", broken )
    with pytest.raises( RuntimeError, match="a real bug" ): _run( _probe( None ) )


def test_do_all_runs_the_probe_on_a_pool_worker_thread_and_completes():
    job = _probe( _text_double( "ok" ) )
    with concurrent.futures.ThreadPoolExecutor( max_workers=1, thread_name_prefix="probe-pool" ) as pool:
        text = pool.submit( job.do_all ).result( timeout=30 )
    out = json.loads( text )
    assert out[ "status" ] == "probe_ok" and out[ "thread" ].startswith( "probe-pool" ) and job.state == JobState.COMPLETED


def test_the_factory_has_a_builder_for_the_command():
    assert COMMAND in JOB_BUILDERS


def test_the_factory_builds_a_probe_job_and_records_its_command_and_args():
    job = create_agentic_job( COMMAND, { "probe": "true" }, "u-1", "o@example.com", "s-1" )
    assert isinstance( job, PrincipleExtractorJob ) and job.probe is True
    assert job.routing_command == COMMAND and job.original_args == { "probe": "true" } and job.session_id == "principle-extractor"


def test_the_factory_builds_an_extraction_job_for_a_notification_id():
    job = create_agentic_job( COMMAND, { "notification_id": "00000000-0000-4000-8000-0000000000aa" }, "u-1", "o@example.com", "s-1" )
    assert job.probe is False and job.notification_id == "00000000-0000-4000-8000-0000000000aa"


def test_the_factory_refuses_a_submit_with_neither_a_notification_id_nor_probe():
    with pytest.raises( SubmitRefused, match="notification_id" ):
        create_agentic_job( COMMAND, {}, "u-1", "o@example.com", "s-1" )
    with pytest.raises( SubmitRefused, match="notification_id" ):
        create_agentic_job( COMMAND, { "probe": "no" }, "u-1", "o@example.com", "s-1" )
