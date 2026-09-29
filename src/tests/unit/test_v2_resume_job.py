"""
POST /api/v2/resume-job — resume a stalled job from its checkpoint (row 67a2a093).

It replaces two v1 doors with ONE body: door 6, `/api/jobs/{id_hash}/resume-from-checkpoint`
(the job id in the URL) and door 7, `/api/test-fix-expediter/resume-from` (free-form
`resume_from`). Rick, 2026-09-28: "Build v2 resume, then retire." This file carries what
`test_tfe_resume_endpoint.py` and the two resume classes in `test_queues_router_coverage.py`
used to pin — door 7's dispatch, its 404s and its `ambiguous` answer, door 6's overrides —
now on the door that survives, plus the one thing the merge added: how `resume_from` is
routed between the two behaviours.

The HTTP class enters the way a caller does, through the mounted router with only auth and
the queue swapped, so the route, the request model and the response model are the real ones.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from cosa.agents.test_fix_expediter.resume_resolver import ResumeTarget
from cosa.rest.auth import get_current_user
from cosa.rest.routers import v2_ask
from cosa.rest.routers.v2_ask import ( ResumeJobRequest, get_todo_queue, v2_resume_job )

RESOLVER = "cosa.agents.test_fix_expediter.resume_resolver.resolve_resume_target"
FACTORY  = "cosa.rest.agentic_job_factory.resume_job"
USER     = { "uid": "u1", "email": "u1@test.com" }


def _job( id_hash="tfe-new00001::u1@test.com", ordinal=3, name="proposing", count=1 ):
    job = MagicMock()
    job.id_hash            = id_hash
    job._resume_checkpoint = { "phase_ordinal": ordinal, "phase_name": name, "resume_count": count }
    return job


def _queue( size=4 ):
    q = MagicMock()
    q.size.return_value = size
    return q


async def _call( text, queue=None, user=USER, **overrides ):
    return await v2_resume_job( ResumeJobRequest( resume_from=text, **overrides ), current_user=user,
                                todo_queue=queue if queue is not None else _queue() )


# ── request model ────────────────────────────────────────────────────────────

def test_an_empty_resume_from_is_refused():
    with pytest.raises( ValidationError ):
        ResumeJobRequest( resume_from="" )


def test_a_thinking_effort_outside_the_ladder_is_refused():
    with pytest.raises( ValidationError ):
        ResumeJobRequest( resume_from="x", thinking_effort="ludicrous" )


def test_the_overrides_are_all_optional():
    r = ResumeJobRequest( resume_from="x" )
    assert ( r.lead_model_override, r.worker_model_override, r.thinking_effort ) == ( None, None, None )


# ── door 7's behaviour: the resolver path ────────────────────────────────────

@pytest.mark.asyncio
async def test_a_tfe_id_resolves_resumes_and_pushes():
    target = ResumeTarget( job_id="tfe-abc12345::u1@test.com", source_type="job_id", confidence=1.0, diagnostic="exact" )
    job    = _job()
    queue  = _queue( size=7 )
    with patch( RESOLVER, return_value=target ) as resolve, patch( FACTORY, return_value=job ):
        out = await _call( "tfe-abc12345", queue=queue )
    resolve.assert_called_once_with( "tfe-abc12345", "u1@test.com" )
    queue.push.assert_called_once_with( job )
    assert out.status == "resumed"
    assert out.resumed_job_id == "tfe-new00001::u1@test.com"
    assert out.original_job_id == "tfe-abc12345::u1@test.com"
    assert ( out.resume_from_phase, out.phase_name, out.resume_count ) == ( 3, "proposing", 1 )
    assert out.queue_position == 7, "the position is the queue's size right after the push"
    assert out.source_type == "job_id"
    assert out.confidence == 1.0


@pytest.mark.asyncio
async def test_a_plan_path_reports_the_matched_path():
    target = ResumeTarget( job_id="tfe-fromplan::u1@test.com", source_type="plan_path",
                           matched_path="io/swe-team/plans/foo-c1-plan.md", confidence=1.0 )
    with patch( RESOLVER, return_value=target ), patch( FACTORY, return_value=_job() ):
        out = await _call( "io/swe-team/plans/foo-c1-plan.md" )
    assert out.source_type == "plan_path"
    assert out.matched_path == "io/swe-team/plans/foo-c1-plan.md"


@pytest.mark.asyncio
async def test_not_found_is_a_404_carrying_the_resolvers_diagnostic_and_pushes_nothing():
    queue  = _queue()
    target = ResumeTarget( source_type="not_found", diagnostic="Job xyz not found or not stalled" )
    with patch( RESOLVER, return_value=target ), patch( FACTORY ) as factory:
        with pytest.raises( HTTPException ) as caught:
            await _call( "tfe-nonexistent", queue=queue )
    assert caught.value.status_code == 404
    assert "not found" in caught.value.detail.lower()
    factory.assert_not_called()
    queue.push.assert_not_called()


@pytest.mark.asyncio
async def test_several_matches_is_ambiguous_with_candidates_and_nothing_is_pushed():
    candidates = [ { "job_id": "tfe-a::u1", "summary": "visual" }, { "job_id": "tfe-b::u1", "summary": "auth" } ]
    target     = ResumeTarget( source_type="fuzzy", candidates=candidates, confidence=0.6, diagnostic="Multiple matches" )
    queue      = _queue()
    with patch( RESOLVER, return_value=target ), patch( FACTORY ) as factory:
        out = await _call( "something vague", queue=queue )
    assert out.status == "ambiguous"
    assert out.candidates == candidates
    assert out.diagnostic == "Multiple matches"
    assert out.resumed_job_id is None and out.queue_position is None
    factory.assert_not_called()
    queue.push.assert_not_called()


@pytest.mark.asyncio
async def test_resolved_but_unreconstructable_is_a_404_and_pushes_nothing():
    target = ResumeTarget( job_id="tfe-abc12345::u1@test.com", source_type="job_id", confidence=1.0 )
    queue  = _queue()
    with patch( RESOLVER, return_value=target ), patch( FACTORY, return_value=None ):
        with pytest.raises( HTTPException ) as caught:
            await _call( "tfe-abc12345", queue=queue )
    assert caught.value.status_code == 404
    assert "cannot be resumed" in caught.value.detail
    queue.push.assert_not_called()


# ── door 6's behaviour: the direct path ──────────────────────────────────────

@pytest.mark.asyncio
async def test_a_bare_job_id_hash_goes_straight_to_the_factory_without_the_resolver():
    """Door 6 never resolved anything: any job kind, the id handed over as given."""
    queue = _queue( size=2 )
    job   = _job( id_hash="bfe-99999999::u1@test.com", ordinal=2, name="plan", count=3 )
    with patch( RESOLVER ) as resolve, patch( FACTORY, return_value=job ) as factory:
        out = await _call( "bfe-1a2b3c4d::u1@test.com", queue=queue )
    resolve.assert_not_called()
    assert factory.call_args.args == ( "bfe-1a2b3c4d::u1@test.com", )
    queue.push.assert_called_once_with( job )
    assert out.source_type == "direct"
    assert out.original_job_id == "bfe-1a2b3c4d::u1@test.com"
    assert ( out.resume_from_phase, out.phase_name, out.resume_count ) == ( 2, "plan", 3 )
    assert out.matched_path is None and out.confidence is None


@pytest.mark.asyncio
async def test_a_direct_job_that_is_not_resumable_is_a_404():
    queue = _queue()
    with patch( FACTORY, return_value=None ):
        with pytest.raises( HTTPException ) as caught:
            await _call( "dr-1a2b3c4d", queue=queue )
    assert caught.value.status_code == 404
    queue.push.assert_not_called()


@pytest.mark.asyncio
async def test_a_tfe_id_is_resolved_not_sent_direct_even_though_it_looks_like_an_id_hash():
    """`tfe-` ids keep door 7's user-scoping (a bare id gets `::<email>` from the resolver)."""
    target = ResumeTarget( job_id="tfe-1a2b3c4d::u1@test.com", source_type="job_id", confidence=1.0 )
    with patch( RESOLVER, return_value=target ) as resolve, patch( FACTORY, return_value=_job() ):
        await _call( "tfe-1a2b3c4d" )
    resolve.assert_called_once()


# ── overrides ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_overrides_reach_the_factory_and_none_ones_are_dropped():
    with patch( FACTORY, return_value=_job() ) as factory:
        await _call( "bfe-1a2b3c4d", thinking_effort="high" )
    assert factory.call_args.kwargs[ "args_overrides" ] == { "thinking_effort": "high" }


@pytest.mark.asyncio
async def test_all_three_overrides_are_forwarded_together():
    with patch( FACTORY, return_value=_job() ) as factory:
        await _call( "bfe-1a2b3c4d", lead_model_override="claude-opus-4-7",
                     worker_model_override="claude-sonnet-4-6", thinking_effort="max" )
    assert factory.call_args.kwargs[ "args_overrides" ] == {
        "lead_model_override": "claude-opus-4-7", "worker_model_override": "claude-sonnet-4-6",
        "thinking_effort": "max" }


@pytest.mark.asyncio
async def test_no_overrides_means_the_factory_gets_none_not_an_empty_dict():
    with patch( FACTORY, return_value=_job() ) as factory:
        await _call( "bfe-1a2b3c4d" )
    assert factory.call_args.kwargs[ "args_overrides" ] is None


# ── identity ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_token_without_an_email_is_a_401():
    with pytest.raises( HTTPException ) as caught:
        await _call( "tfe-abc12345", user={ "uid": "u1" } )
    assert caught.value.status_code == 401


# ── the door, entered over HTTP ──────────────────────────────────────────────

@pytest.fixture
def client_and_queue():
    app   = FastAPI()
    queue = _queue( size=5 )
    app.include_router( v2_ask.router )
    app.dependency_overrides[ get_current_user ] = lambda: USER
    app.dependency_overrides[ get_todo_queue ]   = lambda: queue
    return TestClient( app ), queue


def test_the_route_is_mounted_at_the_path_the_tombstones_name():
    from cosa.rest.routers._retired_doors import V2_RESUME_JOB
    assert V2_RESUME_JOB == "/api/v2/resume-job"
    assert V2_RESUME_JOB in { r.path for r in v2_ask.router.routes }


def test_a_door_6_shaped_request_resumes_over_http_and_says_where_it_is_queued( client_and_queue ):
    client, queue = client_and_queue
    with patch( FACTORY, return_value=_job( id_hash="bfe-99999999::u1@test.com" ) ):
        r = client.post( "/api/v2/resume-job", json={ "resume_from": "bfe-1a2b3c4d::u1@test.com", "thinking_effort": "high" } )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body[ "status" ] == "resumed"
    assert body[ "resumed_job_id" ] == "bfe-99999999::u1@test.com"
    assert body[ "queue_position" ] == 5
    assert body[ "source_type" ] == "direct"
    queue.push.assert_called_once()


def test_a_door_7_shaped_request_resumes_over_http( client_and_queue ):
    client, queue = client_and_queue
    target = ResumeTarget( job_id="tfe-abc12345::u1@test.com", source_type="job_id", confidence=1.0 )
    with patch( RESOLVER, return_value=target ), patch( FACTORY, return_value=_job() ):
        r = client.post( "/api/v2/resume-job", json={ "resume_from": "tfe-abc12345" } )
    assert r.status_code == 200, r.text
    assert r.json()[ "source_type" ] == "job_id"


def test_an_empty_body_field_is_a_422_over_http( client_and_queue ):
    client, _ = client_and_queue
    assert client.post( "/api/v2/resume-job", json={ "resume_from": "" } ).status_code == 422


def test_the_default_queue_dependency_reads_the_main_module( monkeypatch ):
    import sys, types
    fake = types.ModuleType( "lupin_app.main" )
    fake.jobs_todo_queue = "the-queue"
    monkeypatch.setitem( sys.modules, "lupin_app.main", fake )
    monkeypatch.setitem( sys.modules, "lupin_app", types.ModuleType( "lupin_app" ) )
    sys.modules[ "lupin_app" ].main = fake
    assert get_todo_queue() == "the-queue"
