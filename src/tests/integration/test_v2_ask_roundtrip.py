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

from tests.integration.v2_queued import assert_handed_off, snapshot_id_for_question, wait_for_done


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
    """First ask queues, runs and writes back (cold miss); the second identical ask replays it.

    THE ROUND TRIP IS UNCHANGED; WHERE THE ANSWER ARRIVES IS NOT. This used to assert
    `status == "done"` from a single POST, which is what the INLINE executor did. The
    product's executor is the queued one: the flow hands the job to the FIFO queue and
    answers `waiting` with a job_id, and the queue produces the answer behind the
    response (row ce29cd20). The old assertion was pinning the executor the product
    stopped using — so the test follows the product rather than the INI being flipped
    back to inline to keep it green.

    The write-back still happens; it is the QUEUE that does it, before the job reaches
    the done queue. That ordering is what makes the second ask a fair test: by the time
    the first job is observable as done, its row is already in the table.
    """
    question, _expected_sum = _unique_math_question()
    body = { "question": question, "speak": False, "interactive": False }
    try:
        # ── first ask: cold. Routed, then HANDED OFF — not run on this thread.
        r1 = requests.post( _ASK, json=body, headers=auth_headers, timeout=120 )
        assert r1.status_code == 200, f"first call: {r1.status_code} {r1.text}"
        first = r1.json()
        assert_handed_off( first, expect_cache_hit=False, expect_path="agent" )
        assert first[ "wrote_snapshot" ] is False, (
            f"a queued hand-off wrote a snapshot before the job ran — the row would carry "
            f"no answer: {first}"
        )

        # ── the queue runs it. Landing in the done queue means the write-back has landed.
        done = wait_for_done( BASE_URL, first[ "job_id" ], auth_headers )
        assert done, f"first job completed with no metadata: {done}"

        snapshot_id = snapshot_id_for_question( question )
        assert snapshot_id, (
            f"the job finished but nothing was filed under {question!r} — write-back is off, "
            f"or the row was written under a key `ask` cannot look up"
        )

        # ── second ask: identical. MUST be a tier-1 exact replay of that row.
        r2 = requests.post( _ASK, json=body, headers=auth_headers, timeout=120 )
        assert r2.status_code == 200, f"second call: {r2.status_code} {r2.text}"
        second = r2.json()
        assert_handed_off( second, expect_cache_hit=True, expect_path="replay" )

        # ── and the replay itself reaches a terminal answer, which is the point of a cache.
        replayed = wait_for_done( BASE_URL, second[ "job_id" ], auth_headers )
        assert replayed.get( "response_text" ) or replayed.get( "answer" ), (
            f"the replay completed with no answer — a cache hit that serves nothing is a "
            f"miss with extra steps: {replayed}"
        )
    finally:
        _cleanup_snapshot( snapshot_id_for_question( question ) )
