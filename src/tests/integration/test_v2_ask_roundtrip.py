"""Integration test — CJ Flow v2 write-back round-trip through the WIRED app.

Row b7ecfec7 (the open half of 41333974): the isolated cache control
(test_v2_cache.py, 92934eab) proves V2Cache composes with itself; it does NOT
prove the shipped app turns write-back ON and runs the path end to end. This is
that second claim — two POSTs to /api/v2/ask over HTTP against the running
server, proving a snapshotable answer is written back and the next identical
request replays it from cache.

🔴 WHAT THIS FILE CAN AND CANNOT SHOW ON :8000 — row `ce29cd20`. The cold→warm
round trip needs the first job to RUN, and on :8000 it cannot: the test-suite job
is itself the queue's monopolizer, so anything the suite submits waits in `todo`
until the suite ends. Both halves of the old test failed at both gates (aea44d11
and 888754f1) with the same message — the job "was still in the todo queue after
N s" — and no amount of waiting would have changed it. Confirmed on the live box
by maya against pool-status.

So the live test keeps what the box can show: the ask is a cold MISS handed off to
the queue, and the queue actually has it under the id the API returned. The drain
and the replay are marked xfail(strict=True) here by name and pinned a tier down —
`src/tests/unit/test_write_back_lands_before_the_job_is_done.py` drives the
ordering the round trip rested on. This is a real loss of coverage, not a
relabelling: nothing on :8000 now proves the shipped app replays a row it wrote.
Restoring it needs a consumer that is not the test itself.

Fail-first (approach A, intrinsic — no shared-config toggle): the FIRST call on a
unique cold question MUST be a MISS (cache_hit False, path agent). With write-back
off that assertion still stands, so the surviving test is a hand-off guard rather
than a write-back guard — stated plainly rather than left for a reader to notice.

Venue: :8000 (mutates Postgres via write-back, spends real inference). Submit via
POST /api/test-suite/submit on a verified-idle server — never side-doored.
Self-cleaning: deletes the written-back snapshot + its synonyms in a finally
block (the embedding row is keyed by the unique question and cannot collide).
"""

import os
import uuid

import pytest
import requests

from tests.integration.v2_queued import (
    DRAIN_UNOBSERVABLE, DRAIN_XFAIL_TIMEOUT, assert_handed_off, assert_queued_in_todo,
    drop_from_todo, snapshot_id_for_question, wait_for_done,
)


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


def test_v2_ask_hands_a_cold_question_to_the_queue( auth_headers ):
    """A cold, unique question misses the cache and is handed to the queue as a real job.

    THE HALF THE BOX CAN SHOW. The response says `waiting` with a job_id, claims no cache
    hit, and says it wrote nothing — and the queue then actually holds that id. The two
    together are the queued contract's front end: the flow decided, and the board received.

    RED ON REVERT: put the inline executor back and the hand-off assertion fails; break the
    enqueue and the job never appears on the board, which the old test could not tell apart
    from a slow consumer.
    """
    question, _expected_sum = _unique_math_question()
    body   = { "question": question, "speak": False, "interactive": False }
    job_id = None
    try:
        r1 = requests.post( _ASK, json=body, headers=auth_headers, timeout=120 )
        assert r1.status_code == 200, f"first call: {r1.status_code} {r1.text}"
        first = r1.json()
        job_id = assert_handed_off( first, expect_cache_hit=False, expect_path="agent" )
        assert first[ "wrote_snapshot" ] is False, (
            f"a queued hand-off wrote a snapshot before the job ran — the row would carry "
            f"no answer: {first}"
        )

        queued = assert_queued_in_todo( BASE_URL, job_id, auth_headers )
        assert queued, f"the queue reported the job with no metadata: {queued}"
    finally:
        # Row ff4166d9: the job this test queued will NOT drain while the suite holds the
        # consumer, so leaving it behind means it runs hours later and pads the board for
        # everyone after. Take it back out.
        drop_from_todo( BASE_URL, job_id, auth_headers )
        # Under monopolize the job never ran, so there is normally nothing written. The
        # cleanup stays because on a box with a free consumer it WILL have run by now.
        _cleanup_snapshot( snapshot_id_for_question( question ) )


@pytest.mark.xfail( reason=DRAIN_UNOBSERVABLE, strict=True )
def test_v2_ask_write_back_round_trip_replays_second_identical_request( auth_headers ):
    """First ask queues, runs and writes back (cold miss); the second identical ask replays it.

    🔴 STRICT XFAIL, NOT SKIP, AND NOT DELETED. This is the only end-to-end proof that the
    shipped app writes a row and then serves it; nothing else covers it. Strict xfail keeps
    it RUNNING: the day the box gains a consumer which is not the test itself — a :7999
    probe, a second server, a suite that does not monopolize — it XPASSes and the gate goes
    RED, and somebody comes and takes the mark off. A skip would sit quiet forever, which is
    how a blocked claim turns into an unmade one without anybody deciding to drop it.

    Its waits are bounded well under the usual ladder (DRAIN_XFAIL_TIMEOUT) — a body that
    runs every gate costs every gate. Everything else below is the original test, unchanged.
    """
    question, _expected_sum = _unique_math_question()
    body       = { "question": question, "speak": False, "interactive": False }
    queued_ids = [ ]
    try:
        # ── first ask: cold. Routed, then HANDED OFF — not run on this thread.
        r1 = requests.post( _ASK, json=body, headers=auth_headers, timeout=120 )
        assert r1.status_code == 200, f"first call: {r1.status_code} {r1.text}"
        first = r1.json()
        queued_ids.append( assert_handed_off( first, expect_cache_hit=False, expect_path="agent" ) )
        assert first[ "wrote_snapshot" ] is False, (
            f"a queued hand-off wrote a snapshot before the job ran — the row would carry "
            f"no answer: {first}"
        )

        # ── the queue runs it. Landing in the done queue means the write-back has landed.
        done = wait_for_done( BASE_URL, first[ "job_id" ], auth_headers, timeout=DRAIN_XFAIL_TIMEOUT )
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
        queued_ids.append( assert_handed_off( second, expect_cache_hit=True, expect_path="replay" ) )

        # ── and the replay itself reaches a terminal answer, which is the point of a cache.
        replayed = wait_for_done( BASE_URL, second[ "job_id" ], auth_headers, timeout=DRAIN_XFAIL_TIMEOUT )
        assert replayed.get( "response_text" ) or replayed.get( "answer" ), (
            f"the replay completed with no answer — a cache hit that serves nothing is a "
            f"miss with extra steps: {replayed}"
        )
    finally:
        for queued_id in queued_ids:
            drop_from_todo( BASE_URL, queued_id, auth_headers )
        _cleanup_snapshot( snapshot_id_for_question( question ) )
