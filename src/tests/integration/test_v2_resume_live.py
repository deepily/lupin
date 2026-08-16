"""Integration test — CJ Flow v2 ask→park→resume drives to a terminal result over HTTP.

Row 91ca6384 shipped POST /api/v2/resume: a parked flow is resumed synchronously
and driven to done. The unit tier (test_v2_flow.py:538) proves resume closes the
loop against the REAL in-process PendingRequests, but with a FAKE executor/router —
it never proves the SHIPPED app routes a live question, parks it, and resumes it to
a real agent answer end to end. This is that second claim: two POSTs to the running
server — /api/v2/ask (interactive) parks a location-less weather question, then
/api/v2/resume folds the answer and returns a terminal `done`.

Fail-first: the ask MUST park (status='parked', a pending_id, 'location' missing) —
if the live router stops routing this to the weather command, or fills location
without asking, that assertion goes red, which is the point. The resume MUST reach
status='done' with route_reason='resumed' — a parked flow that never terminates is
exactly the DoD-4 failure this test is the live guard against.

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


def test_v2_ask_parks_then_resume_reaches_terminal_done( auth_headers ):
    """A location-less weather question parks; resuming with a city drives to a terminal done."""
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

        # ── resume: fold the answer. MUST drive to a terminal done, synchronously.
        r2 = requests.post(
            _RESUME,
            json    = { "pending_id": pending_id, "answer": "Boston", "speak": False },
            headers = auth_headers,
            timeout = 120,
        )
        assert r2.status_code == 200, f"resume: {r2.status_code} {r2.text}"
        res = r2.json()
        snapshot_id = res.get( "snapshot_id" )
        assert res[ "status" ] == "done", f"resume did not reach a terminal done — parked flow never terminated: {res}"
        assert res[ "route_reason" ] == "resumed", f"expected route_reason='resumed', got {res[ 'route_reason' ]}: {res}"
        assert res[ "path" ] == "agent", f"expected agent path on resume, got {res[ 'path' ]}: {res}"
        assert res[ "answer" ], f"resume completed with no answer: {res}"
    finally:
        _cleanup_snapshot( snapshot_id )
