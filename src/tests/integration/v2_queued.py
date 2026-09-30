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
`running_fifo_queue._handle_base_agent` saves the snapshot BEFORE it pushes the job onto
the done queue. So a job visible in the done queue has already had its write-back land,
and a second identical ask can be expected to replay. That ordering used to be read off
the source and believed; it is now driven and pinned by
`src/tests/unit/test_write_back_lands_before_the_job_is_done.py`.

🔴 AND THE DONE QUEUE CANNOT BE WATCHED FROM INSIDE A :8000 SUITE RUN — row `ce29cd20`.
The test-suite job is itself the queue's monopolizer, so while a suite is running the
consumer is busy with it and anything the suite submits sits in `todo` until the suite
ends. `wait_for_done` therefore waits on a queue that cannot advance until its own
watcher stops, and reports "still in the todo queue after N s" every time — which is what
it did at both gates, aea44d11 and 888754f1. Confirmed on the live box by maya against
pool-status, not inferred.

⇒ On :8000, assert the HAND-OFF and the job's presence in `todo` under the id the API
returned (`assert_handed_off`, `assert_queued_in_todo`). `wait_for_done` is kept for a box
whose consumer is free — a :7999 probe, or a future second server — and calling it from
inside a suite run is a test that cannot pass today. The drain half is pinned at unit tier
instead; the file named above says which claim moved and why.
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


DRAIN_UNOBSERVABLE = "done-queue drain unobservable under monopolize on :8000 (row ce29cd20)"

# A SECOND REASON, FOR THE ONE TEST THAT NEEDS A REPLAY RATHER THAN JUST A DRAIN.
#
# `DRAIN_UNOBSERVABLE` above is exactly right for a test whose only obstacle is the
# monopolized consumer — test_v2_resume_live.py's parked/resume test asserts
# `expect_path="agent"` throughout and needs nothing else, so it keeps that reason.
#
# The write-back round trip needs MORE than a free consumer, and saying only "drain" was
# a promise the test could not keep. Its second ask expects `path="replay"`, which
# `_may_serve` (v2/flow.py step 9b) serves only when `answer_is_correct is True` — and
# nothing in that test ever confirms the answer. So on a box whose consumer IS free, the
# first job would run, the row would be written UNCONFIRMED, the guard would refuse the
# second ask, and the test would fail on `path="agent"` rather than XPASS.
#
# Why that mattered enough to fix a string: a strict xfail's reason is what the next
# person reads before taking the mark off, and this one named the necessary half as if it
# were the whole condition. Tiffany found it, and asked that BOTH causes be named.
# Row 734bd1bf carries the measurement; the confirmed/unconfirmed pair in
# test_v2_ask_serves_a_confirmed_row.py is what established the second cause is real.
REPLAY_NEEDS_DRAIN_AND_CONFIRMATION = (
    "two blockers, both live: (1) done-queue drain unobservable under monopolize on :8000 "
    "(row ce29cd20), and (2) this test never confirms its answer, so the step-9b read guard "
    "refuses the replay even once a consumer is free (row 734bd1bf). A free consumer alone "
    "does NOT make this pass."
)

# The bodies behind that mark are xfail(strict=True), NOT skip — Cheech's ruling, and it is
# the difference between a claim that is parked and one that is abandoned. A strict xfail
# still RUNS, so the day the box gains a consumer that is not the test itself, it XPASSes
# and goes red, and somebody comes and removes the mark. A skip would stay quiet forever.
#
# But a body that runs every gate costs every gate, so the wait is bounded well below the
# 180s ladder: two tests, under a minute each, rather than a hang nobody budgeted for.
DRAIN_XFAIL_TIMEOUT = 25


def assert_queued_in_todo( base_url, job_id, headers, timeout=30 ):
    """Assert `job_id` is visible in the TODO queue, and return its metadata.

    THE HALF OF THE QUEUED CONTRACT A :8000 SUITE CAN ACTUALLY SHOW. The hand-off says the
    API accepted the work; this says the QUEUE did — the job exists, under the exact id the
    caller was given, on the server's own board. What it deliberately does not claim is
    that the job ever runs: under monopolize it will not, until the suite that is asking
    finishes.

    It polls rather than reading once, because "accepted" and "enqueued" are not the same
    instant, and a single read that lands between them would fail for a reason that has
    nothing to do with the contract.
    """
    deadline    = time.time() + timeout
    last_status = { }
    while time.time() < deadline:
        todo, last_status[ "todo" ] = _find_in_queue( base_url, job_id, "todo", headers )
        if todo is not None:
            return todo
        for queue_name in ( "run", "done", "dead" ):
            found, last_status[ queue_name ] = _find_in_queue( base_url, job_id, queue_name, headers )
            if found is not None:
                # A free consumer picked it up already — the contract is satisfied MORE
                # strongly than asked, so this is a pass, not a surprise. Reported so a
                # reader of the log can tell which box they were on.
                print( f"[v2_queued] job {job_id} was already in the '{queue_name}' queue — "
                       f"this consumer is not monopolized" )
                return found
        time.sleep( POLL_INTERVAL )

    unreadable = { name: status for name, status in last_status.items() if status != 200 }
    if unreadable:
        raise AssertionError(
            f"job {job_id} could not be looked for: these queue reads did not return 200 "
            f"{unreadable}. This says nothing about the hand-off — check auth and the "
            f"server before looking at the flow."
        )
    raise AssertionError(
        f"job {job_id} never appeared in ANY queue within {timeout}s, and every queue read "
        f"returned 200 — so it was genuinely absent, not unreadable. The ask returned a "
        f"job_id, so the flow believes it handed the work off; a board that never shows it "
        f"means the hand-off did not reach the queue."
    )


def drop_from_todo( base_url, job_id, headers ):
    """Teardown: remove a job this test handed off, if it is still waiting in TODO.

    ROW ff4166d9, CLOSED HERE. Under monopolize a job a test hands off never drains — the
    suite holds the consumer for its whole run — so it simply STAYS in todo after the
    suite reports. Nothing swept them, and they accumulated: 193 rows at the time this was
    written, each one real work that eventually runs long after the run that created it,
    spending real inference nobody is watching, and each one skewing any later reading of
    queue depth. A test that creates a row and leaves it is the thing that has to change.

    ONLY `todo`, DELIBERATELY, and only via the same door a person would use
    (`DELETE /api/queue/todo/{job_id}`, which is ownership-checked server-side). A job that
    has moved on is a job that is running or has run, and deleting one of those is a
    different and much worse act than tidying up after yourself — so a 404 here is the
    expected, quiet outcome, not a problem.

    Never raises: teardown that can fail is teardown that masks the assertion it follows.
    A `job_id` of None is the ordinary case where the test failed BEFORE it queued
    anything — there is nothing to take back, and turning that into a request for
    `/api/queue/todo/None` would replace a real assertion failure with a teardown error.
    """
    if not job_id:
        return
    try:
        resp = requests.delete( f"{base_url}/api/queue/todo/{job_id}", headers=headers, timeout=30 )
    except requests.RequestException as e:
        print( f"[v2_queued] could not drop {job_id} from todo: {e.__class__.__name__}" )
        return
    if resp.status_code == 404:
        print( f"[v2_queued] {job_id} was no longer in todo — it moved on, nothing to drop" )
    elif resp.status_code != 200:
        print( f"[v2_queued] dropping {job_id} from todo returned {resp.status_code}: {resp.text[ :200 ]}" )


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
        done, _status = _find_in_queue( base_url, job_id, "done", headers )
        if done is not None:
            return done
        dead, _status = _find_in_queue( base_url, job_id, "dead", headers )
        if dead is not None:
            raise AssertionError(
                f"job {job_id} landed in the DEAD queue: "
                f"{dead.get( 'error' ) or dead.get( 'response_text' ) or '(no error detail)'}"
            )
        time.sleep( POLL_INTERVAL )

    for queue_name in ( "done", "dead", "run", "todo" ):
        found, _status = _find_in_queue( base_url, job_id, queue_name, headers )
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
    """`( job_metadata_or_None, status )` — and the two Nones are told apart.

    `status` is the HTTP status the queue read returned, or the string "read-failed" if
    the request itself blew up. It exists because this used to collapse "the job is not
    in this queue" and "I could not read this queue" into one None (Pocholo). A bad token
    or a 500 then made every poll return None, burned the caller's whole timeout, and
    produced an assertion blaming the hand-off — a red with a confidently wrong cause,
    which costs more of a reader's evening than a red with none.
    """
    try:
        resp = requests.get( f"{base_url}/api/get-queue/{queue_name}", headers=headers, timeout=30 )
    except requests.RequestException as e:
        return None, f"read-failed ({e.__class__.__name__})"
    if resp.status_code != 200:
        return None, resp.status_code
    for job in resp.json().get( f"{queue_name}_jobs_metadata", [] ):
        if job.get( "job_id" ) == job_id:
            return job, resp.status_code
    return None, resp.status_code


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
