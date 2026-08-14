"""Integration test — CJ Flow v2 write-back round-trip through the WIRED app.

Row b7ecfec7 (the open half of 41333974): the isolated cache control
(test_v2_cache.py, 92934eab) proves V2Cache composes with itself; it does NOT
prove the shipped app turns write-back ON and runs the path end to end. This is
that second claim — two POSTs to /api/v2/ask over HTTP against the running
server, proving a snapshotable answer is written back and the next identical
request replays it from cache.

Fail-first (approach A, intrinsic — no shared-config toggle): the FIRST call on a
unique cold question MUST be a MISS (cache_hit False, path agent). That miss
assertion is exactly what goes red if write-back is off — with the flag off the
SECOND call would also miss and the replay assertion would fail. A round-trip
that has never been red proves nothing, and the cold→warm contrast is red-able
within one run without editing the shared :8000 INI.

Venue: :8000 (mutates Postgres via write-back, spends real inference). Submit via
POST /api/test-suite/submit on a verified-idle server — never side-doored.
Self-cleaning: deletes the written-back snapshot + its synonyms in a finally
block (the embedding row is keyed by the unique question and cannot collide).
"""

import os
import uuid

import pytest
import requests


BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )

_EMAIL    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
_PASSWORD = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )

_ASK = f"{BASE_URL}/api/v2/ask"


pytestmark = pytest.mark.skipif(
    not ( _EMAIL and _PASSWORD ),
    reason = "Requires LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL + LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD env vars",
)


@pytest.fixture( scope="module" )
def auth_headers():
    """Login once → {"Authorization": "Bearer ..."}. /api/v2/ask is JWT-guarded."""
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


def _unique_math_question():
    """A clean arithmetic question, unique per run so the cache starts cold for it."""
    n     = uuid.uuid4().int
    a, b  = ( n % 900 ) + 100, ( ( n // 900 ) % 900 ) + 100   # two 3-digit operands
    return f"what is {a} plus {b}", a + b


def _cleanup_snapshot( snapshot_id ):
    """Best-effort teardown: drop the written-back snapshot + its synonyms.

    The embedding row (question_embeddings) has no delete API and is keyed by the
    unique question string, so it cannot collide with another test — left in place."""
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


def test_v2_ask_write_back_round_trip_replays_second_identical_request( auth_headers ):
    """First call routes + writes back (cold miss); second identical call replays it."""
    question, _expected_sum = _unique_math_question()
    body = { "question": question, "speak": False, "interactive": False }
    snapshot_id = None
    try:
        # ── first call: cold. Routes to an agent, runs, writes back. NOT a cache hit.
        r1 = requests.post( _ASK, json=body, headers=auth_headers, timeout=120 )
        assert r1.status_code == 200, f"first call: {r1.status_code} {r1.text}"
        first = r1.json()
        assert first[ "cache_hit" ] is False, f"cold question replayed on first call: {first}"
        assert first[ "path" ] == "agent", f"expected agent route on first call, got {first[ 'path' ]}: {first}"
        assert first[ "status" ] == "done", f"first call did not complete: {first}"
        snapshot_id = first[ "snapshot_id" ]
        assert snapshot_id, f"snapshotable+done but nothing written back — write-back is off: {first}"
        assert first[ "wrote_snapshot" ] is True, f"wrote_snapshot False despite a snapshot id: {first}"

        # ── second call: identical. MUST be a tier-1 exact replay from the write-back.
        r2 = requests.post( _ASK, json=body, headers=auth_headers, timeout=120 )
        assert r2.status_code == 200, f"second call: {r2.status_code} {r2.text}"
        second = r2.json()
        assert second[ "cache_hit" ] is True, f"second identical request did NOT replay — round-trip broken: {second}"
        assert second[ "path" ] == "replay", f"expected replay path on second call, got {second[ 'path' ]}: {second}"
        assert second[ "status" ] == "done", f"replay did not complete: {second}"
    finally:
        _cleanup_snapshot( snapshot_id )
