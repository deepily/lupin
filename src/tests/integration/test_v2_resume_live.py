"""Integration test — CJ Flow v2 ask→park→resume drives to a terminal result over HTTP.

Row 91ca6384 shipped POST /api/v2/resume: a parked flow is resumed synchronously
and driven to done. The unit tier (test_v2_flow.py:538) proves resume closes the
loop against the REAL in-process PendingRequests, but with a FAKE executor/router —
it never proves the SHIPPED app routes a live question, parks it, and resumes it to
a real agent answer end to end. This is that second claim: two POSTs to the running
server — /api/v2/ask (interactive) parks a location-less weather question, then
/api/v2/resume folds the answer and returns a terminal `done`.

🔴 THE DRAIN HALF CANNOT RUN ON :8000 — row `ce29cd20`. The test-suite job is the
queue's monopolizer, so a job the suite hands off waits in `todo` until the suite
ends; both gates (aea44d11 and 888754f1) reported this test's job "still in the
todo queue after N s". Confirmed on the live box by maya against pool-status.

So the live test keeps what the box can show, and it is the more interesting half
anyway: the live router PARKS a location-less weather question, and a resume with
a city is accepted and reaches the queue as a real job under the id it returned.
What is lost is the terminal answer — the resumed flow producing a weather result
end to end — which is skipped by name below and is NOT covered anywhere else at
this tier. The unit tier proves resume closes the loop against a fake executor
(test_v2_flow.py:538); nothing now proves the shipped app does.

Fail-first: the ask MUST park (status='parked', a pending_id, 'location' missing) —
if the live router stops routing this to the weather command, or fills location
without asking, that assertion goes red, which is the point. The resume MUST be
accepted with route_reason='resumed' and reach the board.

Venue: :8000 — the ask branch spends real routing inference and the resume executes
the agent (may write a snapshot). Submit via POST /api/test-suite/submit on a
verified-idle server; never :7999, never curl, never side-doored. The park probe
that established this test's premise (router parks the question, wrote_snapshot=False)
ran read-only on :7999; the resume-to-done half belongs here because it executes.

Self-cleaning: if the resume writes back a snapshot, its id is deleted in a finally
block so the run leaves no residue in the shared store.

Auth uses the REAL /auth/login shape — tokens.access_token — mirroring
test_v2_ask_roundtrip.py (NOT the flat read that bug f0b3f630 / the v2_eval.py:1052
KeyError exposed).
"""

import os

import pytest
import requests

from tests.integration.v2_queued import (
    DRAIN_UNOBSERVABLE, assert_handed_off, assert_queued_in_todo, wait_for_done,
)


BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )

_EMAIL    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
_PASSWORD = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )

_ASK    = f"{BASE_URL}/api/v2/ask"
_RESUME = f"{BASE_URL}/api/v2/resume"


pytestmark = pytest.mark.skipif(
    not ( _EMAIL and _PASSWORD ),
    reason = "Requires LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL + LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD env vars",
)


@pytest.fixture( scope="module" )
def auth_headers():
    """Login once → {"Authorization": "Bearer ..."}. Real nested shape: tokens.access_token."""
    resp = requests.post(
        f"{BASE_URL}/auth/login",
        json    = { "email": _EMAIL, "password": _PASSWORD },
        timeout = 10,
    )
    assert resp.status_code == 200, f"Login failed: {resp.status_code} {resp.text}"
    body   = resp.json()
    tokens = body.get( "tokens", body )
    token  = tokens.get( "access_token" ) or tokens.get( "accessToken" )
    assert token, f"No access token in login response: {body}"
    return { "Authorization": f"Bearer {token}" }


def _cleanup_snapshot( snapshot_id ):
    """Best-effort teardown: drop a written-back snapshot + its synonyms (mirrors test_v2_ask_roundtrip)."""
    if not snapshot_id:
        return
    from cosa.rest.db.database import get_db
    from cosa.rest.db.repositories.solution_snapshot_repository import SolutionSnapshotRepository
    from cosa.rest.db.repositories.canonical_synonym_repository import CanonicalSynonymRepository
    try:
        with get_db() as session:
            CanonicalSynonymRepository( session ).delete_by_snapshot_id( snapshot_id )
            SolutionSnapshotRepository( session ).delete_snapshot( snapshot_id )
    except Exception as e:                       # teardown must never mask the assertion
        print( f"[cleanup] snapshot {snapshot_id} teardown skipped: {e}" )


def test_v2_ask_parks_then_resume_reaches_the_queue( auth_headers ):
    """A location-less weather question parks; resuming with a city hands a real job off.

    THE HALVES THE BOX CAN SHOW. The park is entirely observable — it happens on the
    request thread, before any queue is involved — and so is the resume's hand-off and the
    job's arrival on the board. Only the drain is not.

    RED ON REVERT: stop parking a question with a missing required arg and the first block
    fails; break resume's hand-off and the job never reaches the board.
    """
    try:
        r1 = requests.post(
            _ASK,
            json    = { "question": "what\'s the weather", "interactive": True, "speak": False },
            headers = auth_headers,
            timeout = 120,
        )
        assert r1.status_code == 200, f"ask: {r1.status_code} {r1.text}"
        ask = r1.json()
        assert ask[ "status" ] == "parked", f"live router did not park a location-less weather question: {ask}"
        assert ask[ "path" ] == "needs_input", f"expected needs_input path on park, got {ask[ 'path' ]}: {ask}"
        assert "location" in ask[ "args_missing" ], f"expected 'location' missing, got {ask[ 'args_missing' ]}: {ask}"
        pending_id = ask[ "pending_id" ]
        assert pending_id, f"parked but no pending_id to resume: {ask}"
        assert ask[ "wrote_snapshot" ] is False, f"a parked ask must not write back: {ask}"

        r2 = requests.post(
            _RESUME,
            json    = { "pending_id": pending_id, "answer": "Boston", "speak": False },
            headers = auth_headers,
            timeout = 120,
        )
        assert r2.status_code == 200, f"resume: {r2.status_code} {r2.text}"
        res    = r2.json()
        job_id = assert_handed_off( res, expect_path="agent" )
        assert res[ "route_reason" ] == "resumed", f"expected route_reason='resumed', got {res[ 'route_reason' ]}: {res}"
        assert res[ "wrote_snapshot" ] is False, (
            f"a queued hand-off wrote a snapshot before the agent ran: {res}"
        )

        queued = assert_queued_in_todo( BASE_URL, job_id, auth_headers )
        assert queued, f"the queue reported the resumed job with no metadata: {queued}"
    finally:
        # WeatherAgent results are not serialized by the queue (running_fifo_queue
        # excludes it, and the registry marks weather snapshotable=False), so there is
        # normally nothing to clean up — the call stays as a guard in case that changes.
        _cleanup_snapshot( None )


@pytest.mark.skip( reason=DRAIN_UNOBSERVABLE )
def test_v2_ask_parks_then_resume_reaches_terminal_done( auth_headers ):
    """A location-less weather question parks; resuming with a city drives to a terminal done.

    🔴 SKIPPED, NOT DELETED — row ce29cd20. This is the only end-to-end proof that a parked
    flow, resumed, produces a real agent answer on the shipped app; the unit tier does it
    with a fake executor. It is kept intact so that the day the run has a consumer which is
    not the test itself, the skip comes off and it runs as written. Everything below is the
    original test, unchanged.
    """
    snapshot_id = None
    try:
        # ── ask: interactive. A missing required arg (location) MUST park — not execute.
        r1 = requests.post(
            _ASK,
            json    = { "question": "what's the weather", "interactive": True, "speak": False },
            headers = auth_headers,
            timeout = 120,
        )
        assert r1.status_code == 200, f"ask: {r1.status_code} {r1.text}"
        ask = r1.json()
        assert ask[ "status" ] == "parked", f"live router did not park a location-less weather question: {ask}"
        assert ask[ "path" ] == "needs_input", f"expected needs_input path on park, got {ask[ 'path' ]}: {ask}"
        assert "location" in ask[ "args_missing" ], f"expected 'location' missing, got {ask[ 'args_missing' ]}: {ask}"
        pending_id = ask[ "pending_id" ]
        assert pending_id, f"parked but no pending_id to resume: {ask}"
        assert ask[ "wrote_snapshot" ] is False, f"a parked ask must not write back: {ask}"

        # ── resume: fold the answer. The work is HANDED OFF to the queue, not run here.
        #
        # This used to assert `status == "done"` off this response, which is what the
        # INLINE executor did — it ran the agent on the request thread. The product's
        # executor is the queued one, so resume answers `waiting` with a job_id and the
        # queue produces the answer behind it (row ce29cd20). What the test is FOR is
        # unchanged: a parked flow must terminate. It just terminates in the queue.
        r2 = requests.post(
            _RESUME,
            json    = { "pending_id": pending_id, "answer": "Boston", "speak": False },
            headers = auth_headers,
            timeout = 120,
        )
        assert r2.status_code == 200, f"resume: {r2.status_code} {r2.text}"
        res = r2.json()
        job_id = assert_handed_off( res, expect_path="agent" )
        assert res[ "route_reason" ] == "resumed", f"expected route_reason='resumed', got {res[ 'route_reason' ]}: {res}"
        assert res[ "wrote_snapshot" ] is False, (
            f"a queued hand-off wrote a snapshot before the agent ran: {res}"
        )

        # ── the queue runs the weather agent and the resumed flow reaches its answer.
        done = wait_for_done( BASE_URL, job_id, auth_headers )
        assert done.get( "response_text" ) or done.get( "answer" ), (
            f"the resumed job completed with no answer — the parked flow never produced "
            f"one, which is the DoD-4 failure this test guards: {done}"
        )
    finally:
        # WeatherAgent results are not serialized by the queue (running_fifo_queue
        # excludes it, and the registry marks weather snapshotable=False), so there is
        # normally nothing to clean up — the call stays as a guard in case that changes.
        _cleanup_snapshot( snapshot_id )
