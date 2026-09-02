"""Integration test — the shipped v2 flow SERVES a CONFIRMED cached row (row 734bd1bf, AC-G3).

THE CLAIM, AND WHY IT IS NARROWER THAN THE ROUND TRIP NEXT DOOR. `test_v2_ask_roundtrip.py`
asks a cold question, waits for the queue to run it, and asks again — a cold→warm round trip.
That test is correct and its replay half is `xfail(strict=True)`, because on :8000 the
test-suite job IS the queue's monopolizer: anything the suite submits sits in `todo` until the
suite ends, so the first ask never runs and no row is ever written. Leave it as it is.

This file makes a DIFFERENT claim that the same box CAN show: **a row that is already on disk
and already confirmed is served as a replay.** It seeds the row itself, so it never needs the
queue to drain, never needs a second ask, and never needs a human at a microphone.

WHY THAT CLAIM WAS UNPROVEN UNTIL NOW. `_may_serve` (`v2/flow.py`, step 9b) is Rick's read
guard: a cached row is replayed only when `answer_is_correct is True`.
`src/tests/unit/test_9b_the_read_guard.py` drives that predicate in ISOLATION and passes. What
no test showed is that the SHIPPED flow reaches the guard holding the same row — that the
lookup, the guard and the replay exit compose over a real database and a real HTTP request.
That gap is why Rick's 2026-08-30 probe could not be read: his row WAS confirmed and no answer
came back, and "the guard refused it" and "it was served and lost in delivery" were
indistinguishable.

THE TWO ARMS ARE THE POINT — ONE ALONE PROVES NOTHING. The only difference between them is
`answer_is_correct`; everything else, including the seeding path, is identical.

    confirmed (True)   -> path="replay", route_reason="exact_hit", cache_hit=True
    unconfirmed (None) -> path="agent" — the guard refuses and the question is routed

Without the second arm a green in the first is not evidence the CONFIRMATION did anything: a
flow that replayed every exact hit regardless of the guard would pass the first arm exactly the
same way. The unconfirmed arm is what makes the pair discriminate, and it is also the direct
answer to the question row 734bd1bf could not settle.

THE SEED IS TWO WRITES, AND THAT IS WHY IT GOES THROUGH THE PRODUCTION WRITER. A snapshot row
ALONE is invisible to the exact tier: `_exact_probes` queries the CanonicalSynonym table and
gets back a snapshot_id, and only then is the snapshot itself marshalled. So the question text
lives on the synonym row while the human-confirmed mark lives on the snapshot row, and a seed
that writes only one of them looks correct and never matches (found by Tiffany and Mr. Radio
independently, each following the probe chain to its end). `V2Cache.write_back()` performs BOTH
writes in one call — `upsert_snapshot`, then `add_synonym` — and computes `question_normalized`
and `question_gist` with the same normalizers the request path uses, which is the other half of
the trap: those are STORED columns, not recomputed at read time, so a hand-typed value drifts
and the probe silently stops matching. Seeding through the real writer makes both mistakes
unavailable rather than merely documented.

WHY TIER 1 IS REACHED WITHOUT THE FIRST ASK EVER RUNNING. Tier 1 is plain equality on the
verbatim question via CanonicalSynonymRepository — "one indexed lookup, NO embedding"
(`v2/cache.py`). Embeddings are tier 2, and in phase 1 tier 2 does not trigger replay at all.
So a replay hit does not need the ANN index warm, which is exactly why this design escapes the
monopolize wall the round-trip test hits.

FACTS THIS TEST RELIES ON, EACH READ OFF THE CODE RATHER THAN ASSUMED:
  · `answer_is_correct` is stored as JSON text (`json.dumps` in `_snapshot_to_record`) and
    hydrated back with `json.loads` (`two_tier_question_search.py`), so a seeded `True`
    survives the round trip as `True` and satisfies the guard's `is True`.
  · The tier-1 lookup is NOT user-scoped (`find_exact_verbatim` filters on the question only),
    and the replay re-owns the row to the CALLER via `for_current_user()`. So the seeded row's
    `user_id` does not have to match the logged-in test user, and the replay job that lands in
    `todo` is owned by the caller — which is what lets teardown delete it.
  · A replay on the queued executor answers `status="waiting"` with a `job_id`, exactly like
    the agent path. `path`/`cache_hit` are what tell them apart, not `status`.
  · `agent_class_name="CalculatorAgent"` is the sole member of `CODELESS_AGENT_CLASSES`, so a
    row with no code is legally replayable. This matters only if a free consumer picks the job
    up before teardown drops it; under monopolize it never runs.
  · The seeded question carries real content words. A question made entirely of stopwords
    reduces to an empty gist, and the gist probe deliberately reports a miss rather than
    equality-matching every other blank-gist row.

Venue: :8000 (writes Postgres rows, spends embedding + routing inference). Submit via
POST /api/test-suite/submit on a verified-idle server — never side-doored.
Self-cleaning: both arms delete their snapshot + synonyms and take their queued job back out
of `todo` in a finally block.
"""

import os
import uuid

import pytest
import requests

from tests.integration.v2_queued import assert_handed_off, drop_from_todo


BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )

_EMAIL    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
_PASSWORD = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )

_ASK = f"{BASE_URL}/api/v2/ask"

# The owner stamped on a seeded row. It is deliberately a marker rather than the logged-in
# user's id: the tier-1 lookup does not filter on owner and the replay re-owns the row to the
# caller, so making them match would imply a scoping this path does not have.
_SEED_USER_ID = "integration-test-seeded-row"

_ROUTING_COMMAND = "agent router go to calculator"


pytestmark = pytest.mark.skipif(
    not ( _EMAIL and _PASSWORD ),
    reason = "Requires LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL + LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD env vars",
)


@pytest.fixture( scope="module" )
def auth_headers():
    """Login once -> {"Authorization": "Bearer ..."}. /api/v2/ask is JWT-guarded.

    DELIBERATELY SHADOWS THE conftest FIXTURE OF THE SAME NAME, which is not a duplication
    to be tidied away. `conftest.auth_headers` chains through `create_test_user` ->
    `clean_test_db`, and clean_test_db TRUNCATES the test database — which would delete the
    snapshot this file seeds. This module needs a plain login as the standing test user and
    nothing else, which is the same reason test_v2_ask_roundtrip.py defines its own.
    """
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


def _unique_arithmetic_question():
    """A clean arithmetic question, unique per run so it can only match the row we seed.

    Uniqueness is load-bearing twice over: it keeps the seeded row from colliding with an
    earlier run's, and it makes the exact hit provably OURS — a question nobody has asked
    before cannot match a pre-existing row by accident.
    """
    n    = uuid.uuid4().int
    a, b = ( n % 900 ) + 100, ( ( n // 900 ) % 900 ) + 100      # two 3-digit operands
    return f"what is {a} plus {b}", str( a + b )


def _seed_row( question, answer, answer_is_correct ):
    """Write one snapshot through the PRODUCTION write path and return its id_hash.

    Requires:
        - question is a non-empty string not already present in the cache
        - answer_is_correct is True or None — the one variable the two arms differ on

    Ensures:
        - BOTH writes land: the snapshot row is upserted AND its canonical-synonym row is
          registered, so a tier-1 verbatim lookup finds it
        - question_normalized and question_gist are computed by the same normalizers the
          request path uses, never typed by hand
        - returns the row's id_hash

    `answer_is_correct` is set on the snapshot BEFORE write_back, because write_back marshals
    the whole object in one pass — setting it afterwards would leave the stored column reading
    `null` while the in-memory object looked confirmed.
    """
    from cosa.rest.v2.cache import V2Cache

    cache    = V2Cache()
    snapshot = cache.snapshot_from_result(
        question              = question,
        answer                = answer,
        answer_conversational = f"The answer is {answer}",
        routing_command       = _ROUTING_COMMAND,
        user_id               = _SEED_USER_ID,
        agent_class_name      = "CalculatorAgent",
    )
    snapshot.answer_is_correct = answer_is_correct
    return cache.write_back( snapshot )


def _cleanup_snapshot( snapshot_id ):
    """Best-effort teardown: drop the seeded snapshot + its synonyms.

    The embedding row (question_embeddings) has no delete API and is keyed by the unique
    question string, so it cannot collide with another test — left in place, same as the
    round-trip test does.
    """
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


def test_a_confirmed_cached_row_is_served_as_a_replay( auth_headers ):
    """A seeded row with answer_is_correct=True is replayed on the first ask of its question.

    THE OBSERVABLE AC-G3 ASKS FOR, reached without a queue drain: path="replay" with
    route_reason="exact_hit". Both are already in the §8 response body — the gap was never
    instrumentation, it was that the probe was run through the web Q&A UI, which does not
    surface them.

    `replayed_snapshot_id` is asserted too, and it is the assertion that makes this test about
    OUR row rather than about replay in general: it is the id_hash of the row the flow actually
    read. A flow that replayed some other row, or that reported a hit it did not serve, passes
    the first three assertions and fails this one.

    RED ON REVERT: take the confirmation off the seeded row and this goes to path="agent" —
    which is the second test below, run deliberately rather than left to be imagined.
    """
    question, answer = _unique_arithmetic_question()
    snapshot_id      = _seed_row( question, answer, answer_is_correct=True )
    assert snapshot_id, "the seed did not return an id_hash — write-back is off or it failed"

    job_id = None
    try:
        resp = requests.post(
            _ASK,
            json    = { "question": question, "speak": False, "interactive": False },
            headers = auth_headers,
            timeout = 120,
        )
        assert resp.status_code == 200, f"ask: {resp.status_code} {resp.text}"
        body = resp.json()

        job_id = assert_handed_off( body, expect_cache_hit=True, expect_path="replay" )
        assert body[ "route_reason" ] == "exact_hit", (
            f"a tier-1 exact hit must say so — got route_reason={body[ 'route_reason' ]!r}. "
            f"A replay on any other reason is a different branch of the flow: {body}"
        )
        assert body[ "replayed_snapshot_id" ] == snapshot_id, (
            f"the flow replayed {body[ 'replayed_snapshot_id' ]!r}, not the row this test "
            f"seeded ({snapshot_id!r}) — the cache hit was real but it was not ours: {body}"
        )
    finally:
        drop_from_todo( BASE_URL, job_id, auth_headers )
        _cleanup_snapshot( snapshot_id )


def test_an_unconfirmed_cached_row_is_refused_and_the_question_is_routed( auth_headers ):
    """The SAME seed with answer_is_correct=None is NOT replayed — the read guard refuses it.

    THE CONTROL THAT MAKES THE TEST ABOVE MEAN SOMETHING. Its green says a confirmed row is
    served; on its own that is equally consistent with a flow that serves every exact hit and
    never consults the guard at all. This arm is the same row, seeded the same way, differing
    in exactly one field — so a pass here is what establishes that the CONFIRMATION is doing
    the work.

    It also settles the question row 734bd1bf could not: a refusal is observable from the
    outside as path="agent" on a question the cache demonstrably holds. "The guard refused it"
    and "the cache is broken" are no longer indistinguishable, and neither needs the trace.

    `cache_hit` is False here even though the row IS in the cache — deliberately, and it is
    worth saying out loud because it looks wrong. `cache_hit` reports whether this request was
    SERVED from cache, not whether a matching row exists. The guard refuses before the replay
    exit, so the flow falls through to routing and answers on the agent path.
    """
    question, answer = _unique_arithmetic_question()
    snapshot_id      = _seed_row( question, answer, answer_is_correct=None )
    assert snapshot_id, "the seed did not return an id_hash — write-back is off or it failed"

    job_id = None
    try:
        resp = requests.post(
            _ASK,
            json    = { "question": question, "speak": False, "interactive": False },
            headers = auth_headers,
            timeout = 120,
        )
        assert resp.status_code == 200, f"ask: {resp.status_code} {resp.text}"
        body = resp.json()

        job_id = assert_handed_off( body, expect_cache_hit=False, expect_path="agent" )
        assert body[ "replayed_snapshot_id" ] is None, (
            f"nothing may be reported as replayed when the guard refused: {body}"
        )
    finally:
        drop_from_todo( BASE_URL, job_id, auth_headers )
        _cleanup_snapshot( snapshot_id )
