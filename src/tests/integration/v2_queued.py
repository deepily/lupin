"""Helpers for integration tests that go through /api/v2/ask under the QUEUED executor.

WHY THESE EXIST. `/api/v2/ask` used to answer with the finished result, because the
inline executor ran the agent on the request thread. The product's executor is the
queued one (`v2 executor = queued`, the shipped design since steps 2+3): the flow hands
the job to the FIFO queue and answers `status="waiting"` with a `job_id`, and the queue
consumer produces the answer behind the response. A test that asserts `"done"` from one
POST is asserting the old executor, not the product (row ce29cd20).

So the queued contract is two steps, and these helpers are the second one: hand-off,
then observe completion the way the product delivers it — the done queue, which is what
`live_pipeline_base._submit_and_wait` polls and what the UI reads.

MATCH ON THE EXACT job_id THE API RETURNED (maya, who runs the gate). Not a count of
rows, not a websocket, and no user filtering: the id the response carries is already
the scoped one the queue registered, so comparing it to each row's "job_id" key is
immune to another test's traffic arriving in the same queue. The DEAD queue is polled
in the same loop on purpose — a job that dies is reported as dead immediately rather
than as a timeout after the full wait — and every failure names the job id AND where
the job actually was.

ORDERING THIS RELIES ON, stated because a round-trip test depends on it:
`running_fifo_queue` saves the snapshot BEFORE it pushes the job onto the done queue.
So a job visible in the done queue has already had its write-back land, and a second
identical ask can be expected to replay.
"""

import time

import requests


DEFAULT_TIMEOUT = 180
POLL_INTERVAL   = 2


def assert_handed_off( response_body, expect_cache_hit=None, expect_path=None ):
    """Assert one /api/v2/ask response is a queued HAND-OFF, and return its job_id.

    Requires:
        - response_body is the decoded JSON of a 200 from /api/v2/ask or /api/v2/resume

    Ensures:
        - returns the job_id the queue accepted
        - raises AssertionError naming the whole body when the status is not "waiting"
          or no job_id came back — a hand-off with no id cannot be observed, which is
          indistinguishable from work that was never queued
    """
    assert response_body[ "status" ] == "waiting", (
        f"expected a queued hand-off (status='waiting'); got {response_body[ 'status' ]!r}. "
        f"An ask that answers 'done' means the INLINE executor ran it — check "
        f"`v2 executor` in the INI rather than relaxing this assertion: {response_body}"
    )
    job_id = response_body.get( "job_id" )
    assert job_id, f"handed off with no job_id — nothing to observe: {response_body}"
    if expect_cache_hit is not None:
        assert response_body[ "cache_hit" ] is expect_cache_hit, (
            f"expected cache_hit={expect_cache_hit}: {response_body}"
        )
    if expect_path is not None:
        assert response_body[ "path" ] == expect_path, (
            f"expected path={expect_path!r}, got {response_body[ 'path' ]!r}: {response_body}"
        )
    return job_id


def wait_for_done( base_url, job_id, headers, timeout=DEFAULT_TIMEOUT ):
    """Poll until `job_id` lands in the done queue; return its metadata dict.

    Ensures:
        - returns the done-queue metadata for the job, matched on the exact job_id
        - raises AssertionError carrying the job id and its ACTUAL whereabouts on
          failure — dead, still running, or absent from every queue. "I stopped
          waiting" and "it failed" are different facts, and a message that conflates
          them sends the reader hunting the wrong thing.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        done = _find_in_queue( base_url, job_id, "done", headers )
        if done is not None:
            return done
        dead = _find_in_queue( base_url, job_id, "dead", headers )
        if dead is not None:
            raise AssertionError(
                f"job {job_id} landed in the DEAD queue: "
                f"{dead.get( 'error' ) or dead.get( 'response_text' ) or '(no error detail)'}"
            )
        time.sleep( POLL_INTERVAL )

    for queue_name in ( "done", "dead", "run", "todo" ):
        found = _find_in_queue( base_url, job_id, queue_name, headers )
        if found is None:
            continue
        if queue_name == "done":
            return found                           # it finished inside the last interval
        if queue_name == "dead":
            # The sweep has to say the same thing the loop says. A job found DEAD here
            # is a job that failed, and reporting it as "the test stopped waiting" would
            # send the reader to look for a slow queue instead of the error the job
            # already carries (Pocholo).
            raise AssertionError(
                f"job {job_id} landed in the DEAD queue: "
                f"{found.get( 'error' ) or found.get( 'response_text' ) or '(no error detail)'}"
            )
        raise AssertionError(
            f"job {job_id} was still in the '{queue_name}' queue after {timeout}s — "
            f"it did not fail, the test stopped waiting"
        )
    raise AssertionError(
        f"job {job_id} is in NO queue (done/dead/run/todo) after {timeout}s — state "
        f"indeterminate; check the server log for this job id"
    )


def _find_in_queue( base_url, job_id, queue_name, headers ):
    """The job's metadata from one queue, or None when it is absent or unreadable."""
    resp = requests.get( f"{base_url}/api/get-queue/{queue_name}", headers=headers, timeout=30 )
    if resp.status_code != 200:
        return None
    for job in resp.json().get( f"{queue_name}_jobs_metadata", [] ):
        if job.get( "job_id" ) == job_id:
            return job
    return None


def snapshot_id_for_question( question ):
    """The snapshot the write-back filed under `question`, or None.

    Teardown cannot read the id off the ask response any more: a waiting hand-off has
    written nothing yet, and the row appears later under an id the QUEUE chose. Asking
    the synonym table what the verbatim question resolves to finds it however it was
    scoped.
    """
    from cosa.rest.db.database import get_db
    from cosa.rest.db.repositories.canonical_synonym_repository import CanonicalSynonymRepository
    try:
        with get_db() as session:
            return CanonicalSynonymRepository( session ).find_exact_verbatim( question )
    except Exception as e:                          # teardown must never mask an assertion
        print( f"[cleanup] could not resolve a snapshot for {question!r}: {e}" )
        return None
