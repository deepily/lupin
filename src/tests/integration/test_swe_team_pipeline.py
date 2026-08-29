#!/usr/bin/env python3
"""
Integration tests for SWE Team pipeline — end-to-end dry-run validation.

Submits catalog tasks via POST /api/v2/submit with dry_run=true, polls
for completion, and validates:
    1. CJ Flow lifecycle (todo → running → done)
    2. Proxy decisions are created with correct data_origin
    3. Classifications map to expected categories
    4. Decision metadata contains expected fields

Requires:
    - FastAPI server running on localhost:8000 (:8000 test venue; override via LUPIN_TEST_BASE_URL)
    - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and _PASSWORD set
    - PostgreSQL running with proxy_decisions table

Session 268: Work Item 2, Step 2.4.
"""

import math
import os
import time

import pytest
import requests

from tests.integration.v2_queued import assert_handed_off

# Server configuration
BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )


def _swe_submit_body( task_text, ws_session_id ):
    """
    Build the POST /api/v2/submit JSON body, threading the lineage token
    (bug 3a14292b) when present.

    When this suite runs INSIDE a monopolize test_suite sweep, that sweep exports
    its own id_hash as LUPIN_TEST_MONOPOLIZE_PARENT_ID. Echoing it back as
    parent_id_hash marks each swe_team child as the sweep's own lineage, so the
    consumer's Gate B admits it THROUGH the monopoly intake hold instead of
    starving it (the ts-ad4670ec deadlock). Absent the env var (a plain
    :7999/:8000 run with no monopolizing parent) no lineage is sent and behavior
    is unchanged.

    Requires:
        - task_text and ws_session_id are strings

    Ensures:
        - returns a dict with command/args/websocket_id
        - includes parent_id_hash iff LUPIN_TEST_MONOPOLIZE_PARENT_ID is set
    """
    # ONE DOOR NOW. The dedicated endpoint this used to post to is retired and answers 410
    # naming /api/v2/submit, which takes the routing command as a string and the agent's own
    # arguments in `args`. `websocket_id` and `parent_id_hash` stay TOP-LEVEL: they are
    # instructions about the request and the queue, not arguments to the agent, and `args`
    # is checked against the command's own argument contract, which neither of them is in.
    body = {
        "command"      : "agent router go to swe team",
        "args"         : { "task": task_text, "dry_run": True },
        "question"     : task_text,
        "websocket_id" : ws_session_id,
    }
    parent_id = os.environ.get( "LUPIN_TEST_MONOPOLIZE_PARENT_ID" )
    if parent_id:
        body[ "parent_id_hash" ] = parent_id
    return body


# --- Shared-agentic-pool wait budget (bug 67473d91) --------------------------
# The :8000 integration venue shares ONE agentic pool across ALL suites, and a
# post-bounce cold-start adds startup latency. 7 heavy SWE dry-run jobs serialize
# through that pool, so a flat 120s per-test budget structurally under-counts →
# false-red even though every job COMPLETES (jobs finish LATE, not failed). The
# budget is sized to the LIVE pool width so it survives a worker-count change.
# Pairs with the landing-run auto_fix_on_failure=False convention (facet 3), which
# removes the self-inflicted TestFixExpediter pool contention that worsened it.
_SWE_HEAVY_JOB_COUNT = 7    # heavy dry-run jobs contending for the pool this module
_PER_JOB_BUDGET_S    = 60   # generous per-heavy-job wall-clock (submit → done + proxy decisions)
_COLD_START_MARGIN_S = 90   # post-bounce fresh-container model/agent cold-start


def _agentic_pool_workers( auth_headers ):
    """
    Read max_agentic_workers from GET /api/queue/pool-status (JWT).

    FAIL-LOUD (Mr. Radio rider, bug 67473d91): a harness whose pool-status is
    unreachable must SCREAM, not silently guess a worker count — a wrong guess
    reintroduces the exact false-red this fixes. LUPIN_TEST_SWE_BUDGET_S is the
    explicit escape hatch (see swe_wait_budget_s), NOT a silent fallback here.

    Requires:
        - auth_headers carries a valid Bearer token

    Ensures:
        - returns a positive int max_agentic_workers

    Raises:
        - AssertionError if pool-status is unreachable / malformed
    """
    resp = requests.get( f"{BASE_URL}/api/queue/pool-status", headers=auth_headers, timeout=10 )
    assert resp.status_code == 200, (
        f"pool-status unreachable ({resp.status_code}) — cannot size the SWE wait "
        f"budget; set LUPIN_TEST_SWE_BUDGET_S to override"
    )
    workers = resp.json().get( "max_agentic_workers" )
    assert isinstance( workers, int ) and workers > 0, (
        f"pool-status returned invalid max_agentic_workers={workers!r}"
    )
    return workers


def swe_wait_budget_s( auth_headers ):
    """
    Per-test wait budget (seconds) for a heavy SWE dry-run job, sized to the LIVE
    agentic-pool width (bug 67473d91):

        budget = COLD_START_MARGIN + ceil( N_SWE_HEAVY_JOBS / workers ) * PER_JOB_BUDGET

    LUPIN_TEST_SWE_BUDGET_S (int seconds), when set, is the explicit escape hatch:
    it short-circuits the pool-status query entirely.

    Requires:
        - auth_headers carries a valid Bearer token (unless the env override is set)

    Ensures:
        - returns a positive int budget in seconds
    """
    override = os.environ.get( "LUPIN_TEST_SWE_BUDGET_S" )
    if override is not None:
        return int( override )
    workers = _agentic_pool_workers( auth_headers )
    waves   = math.ceil( _SWE_HEAVY_JOB_COUNT / workers )
    return _COLD_START_MARGIN_S + waves * _PER_JOB_BUDGET_S


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture( scope="module" )
def auth_headers():
    """
    Authenticate and return headers with Bearer token.

    Requires:
        - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and _PASSWORD env vars set
        - Server running on BASE_URL
    """
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )

    if not email or not password:
        pytest.skip( "Test credentials not set (LUPIN_TEST_INTERACTIVE_MOCK_JOBS_*)" )

    resp = requests.post(
        f"{BASE_URL}/auth/login",
        json={ "email": email, "password": password },
        timeout=30
    )
    if resp.status_code != 200:
        pytest.skip( f"Login failed: {resp.status_code}" )

    token = resp.json()[ "tokens" ][ "access_token" ]
    return { "Authorization": f"Bearer {token}" }


@pytest.fixture( scope="module" )
def ws_session_id( auth_headers ):
    """Get a WebSocket session ID for notifications."""
    try:
        resp = requests.get(
            f"{BASE_URL}/api/ws/session",
            headers=auth_headers,
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json().get( "session_id", "test-pipeline" )
    except Exception:
        pass
    return "test-pipeline"


def submit_and_wait( task_text, auth_headers, ws_session_id, timeout=None ):
    """
    Submit a dry-run SWE team task and poll until done.

    timeout=None (default) sizes the wait budget to the live agentic-pool width
    via swe_wait_budget_s() — see bug 67473d91.

    Returns:
        ( job_id, job_data ) on success, or pytest.fail on error
    """
    if timeout is None:
        timeout = swe_wait_budget_s( auth_headers )

    resp = requests.post(
        f"{BASE_URL}/api/v2/submit",
        json=_swe_submit_body( task_text, ws_session_id ),
        headers=auth_headers,
        timeout=60
    )
    assert resp.status_code == 200, f"Submit failed: {resp.status_code} {resp.text[ :200 ]}"

    data   = resp.json()
    job_id = data[ "job_id" ]
    assert job_id, "No job_id in response"

    # Poll done queue
    elapsed = 0
    while elapsed < timeout:
        done_resp = requests.get(
            f"{BASE_URL}/api/get-queue/done",
            headers=auth_headers,
            timeout=30
        )
        if done_resp.status_code == 200:
            for job in done_resp.json().get( "done_jobs_metadata", [] ):
                if job.get( "job_id" ) == job_id:
                    return job_id, job

        time.sleep( 2 )
        elapsed += 2

    pytest.fail( f"Timeout after {timeout}s waiting for job_id={job_id}" )


def get_decisions_for_job( job_id ):
    """
    Query PostgreSQL for proxy decisions created by a specific job.

    Returns:
        list of decision row dicts
    """
    from cosa.rest.db.database import get_db
    from sqlalchemy import text

    with get_db() as session:
        result = session.execute(
            text( """
                SELECT id, category, question, action, decision_value,
                       confidence, trust_level, data_origin, metadata_json,
                       created_at
                FROM proxy_decisions
                WHERE metadata_json->>'job_id' = :job_id
                ORDER BY created_at ASC
            """ ),
            { "job_id": job_id }
        )
        return [ dict( row._mapping ) for row in result ]


# =============================================================================
# Tests
# =============================================================================

class TestSweTeamDryRunPipeline:
    """End-to-end tests for SWE team dry-run pipeline with proxy decisions."""

    def test_dry_run_completes_successfully( self, auth_headers, ws_session_id ):
        """A dry-run task should complete and appear in the done queue."""
        job_id, job_data = submit_and_wait(
            "Add a health check endpoint",
            auth_headers, ws_session_id
        )

        assert job_data is not None
        assert job_data.get( "agent_type" ) == "swe_team"

    def test_dry_run_produces_proxy_decisions( self, auth_headers, ws_session_id ):
        """Dry-run should generate proxy decisions via the real classifier pipeline."""
        job_id, job_data = submit_and_wait(
            "Run the pytest test suite before merging changes",
            auth_headers, ws_session_id
        )

        decisions = get_decisions_for_job( job_id )
        assert len( decisions ) > 0, "Expected at least 1 proxy decision from dry-run"

    def test_dry_run_decisions_have_synthetic_generated_origin( self, auth_headers, ws_session_id ):
        """All dry-run proxy decisions should have data_origin='synthetic_generated'."""
        job_id, job_data = submit_and_wait(
            "Deploy the authentication service to staging",
            auth_headers, ws_session_id
        )

        decisions = get_decisions_for_job( job_id )
        assert len( decisions ) > 0

        for dec in decisions:
            assert dec[ "data_origin" ] == "synthetic_generated", \
                f"Expected synthetic_generated, got {dec[ 'data_origin' ]} for {dec[ 'category' ]}"

    def test_dry_run_decisions_have_classified_metadata( self, auth_headers, ws_session_id ):
        """Decisions should have metadata indicating they were classified by the pipeline."""
        job_id, job_data = submit_and_wait(
            "Refactor the notification module using the observer pattern",
            auth_headers, ws_session_id
        )

        decisions = get_decisions_for_job( job_id )
        assert len( decisions ) > 0

        for dec in decisions:
            meta = dec[ "metadata_json" ]
            assert meta is not None
            assert meta.get( "dry_run" ) is True
            assert meta.get( "job_id" ) == job_id
            assert meta.get( "classified" ) is True
            assert "phase" in meta

    def test_dry_run_decisions_span_multiple_categories( self, auth_headers, ws_session_id ):
        """Dry-run should produce decisions across at least 2 different categories."""
        job_id, job_data = submit_and_wait(
            "Add input validation and deploy to staging",
            auth_headers, ws_session_id
        )

        decisions = get_decisions_for_job( job_id )
        categories = set( dec[ "category" ] for dec in decisions )

        # The phase questions exercise testing, deployment, architecture, deps, destructive
        assert len( categories ) >= 2, \
            f"Expected at least 2 categories, got {categories}"

    def test_dry_run_cj_flow_lifecycle( self, auth_headers, ws_session_id ):
        """Job should go through CJ Flow: submit returns queued, poll returns done."""
        # Submit
        resp = requests.post(
            f"{BASE_URL}/api/v2/submit",
            json=_swe_submit_body( "Fix the pagination off-by-one error", ws_session_id ),
            headers=auth_headers,
            timeout=60
        )
        assert resp.status_code == 200

        # The v2 hand-off status is "waiting", not "queued" — AskResponse.status is
        # done | waiting | parked | needs_input | expired | failed (v2_ask.py:91), and
        # AskResponse carries no queue_position at all. Both assertions predate the
        # move of this door to v2 in 4f1501a2. assert_handed_off() is the shared check
        # every other v2 caller uses, and it explains itself on failure.
        job_id = assert_handed_off( resp.json() )
        assert job_id.startswith( "swe-" )

        # Poll until complete (shared-pool-aware budget — bug 67473d91)
        budget  = swe_wait_budget_s( auth_headers )
        elapsed = 0
        while elapsed < budget:
            done_resp = requests.get(
                f"{BASE_URL}/api/get-queue/done",
                headers=auth_headers,
                timeout=30
            )
            if done_resp.status_code == 200:
                for job in done_resp.json().get( "done_jobs_metadata", [] ):
                    if job.get( "job_id" ) == job_id:
                        return  # Success — job appeared in done queue

            time.sleep( 2 )
            elapsed += 2

        pytest.fail( f"Job {job_id} never appeared in done queue within {budget}s" )

    def test_dry_run_confidence_values_are_valid( self, auth_headers, ws_session_id ):
        """All proxy decision confidence values should be between 0.0 and 1.0."""
        job_id, job_data = submit_and_wait(
            "Upgrade the requests package to the latest version",
            auth_headers, ws_session_id
        )

        decisions = get_decisions_for_job( job_id )
        assert len( decisions ) > 0

        for dec in decisions:
            conf = dec[ "confidence" ]
            assert 0.0 <= conf <= 1.0, \
                f"Confidence {conf} out of range for {dec[ 'category' ]}"
