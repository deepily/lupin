#!/usr/bin/env python3
"""
Unit tests for LivePipelineTestBase timeout-state resolution (bug e5473a72).

THE BUG: the smoke harness polled ONLY the done queue and, on timeout, reported a
bare "Timeout after Ns" — so a job that SUCCEEDED just past the poll window, a job
that DIED, and a job still RUNNING all read as the same false failure. On
2026-08-03 it reported FAIL for job pr-bf7ac6f5, which had produced a 15-slide deck.

THE FIX (live_pipeline_base._submit_and_wait): poll done AND dead each iteration,
and on timeout ASK the server the job's real state and report THAT with the job id.

RED-PROOF (the brief's requirement): force a timeout against a job KNOWN to be
healthy (still in the run queue) and confirm the message says "STILL RUNNING", not
"failed". These tests mock the HTTP layer, so they need no server and burn no
tokens (:7999/recorded-data rule).
"""

from unittest.mock import MagicMock, patch

import tests.smoke.utilities.live_pipeline_base as lpb
from tests.smoke.utilities.live_pipeline_base import LivePipelineTestBase


class _Harness( LivePipelineTestBase ):
    """Minimal concrete subclass — skips the heavy base __init__ for unit isolation."""
    BASE_URL        = "http://test-server"
    POLL_INTERVAL   = 1
    REQUEST_TIMEOUT = 5
    # /api/push retired 2026-08-21. These tests drive the POLLING arm, which the
    # base class still takes for any response that is not terminal.
    SUBMIT_ENDPOINT = "/api/v2/ask"

    def __init__( self ):
        pass  # deliberately skip base setup (login/config) — we test polling only

    def get_submit_payload( self, scenario, ws_id ):
        return { "q": scenario.get( "query", "x" ) }

    def get_submit_headers( self, headers, ws_id ):
        return headers


def _resp( status, body ):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body
    return r


def _queue_getter( contents ):
    """requests.get side_effect: /get-queue/<name> → { '<name>_jobs_metadata': rows }."""
    def _get( url, headers=None, timeout=None ):
        for name in ( "done", "dead", "run", "todo" ):
            if f"/get-queue/{name}" in url:
                return _resp( 200, { f"{name}_jobs_metadata": contents.get( name, [] ) } )
        return _resp( 404, {} )
    return _get


HEADERS = { "Authorization": "Bearer t" }
SCENARIO = { "query": "x" }
JOB = { "job_id": "pr-x", "response_text": "deck built", "error": None }


# ───────────────────────── _find_job_in_queue ─────────────────────────

def test_find_job_in_queue_hit():
    h = _Harness()
    with patch.object( lpb.requests, "get", side_effect=_queue_getter( { "done": [ JOB ] } ) ):
        assert h._find_job_in_queue( "pr-x", "done", HEADERS ) == JOB

def test_find_job_in_queue_absent():
    h = _Harness()
    with patch.object( lpb.requests, "get", side_effect=_queue_getter( { "done": [] } ) ):
        assert h._find_job_in_queue( "pr-x", "done", HEADERS ) is None

def test_find_job_in_queue_non_200_returns_none():
    h = _Harness()
    with patch.object( lpb.requests, "get", return_value=_resp( 500, {} ) ):
        assert h._find_job_in_queue( "pr-x", "done", HEADERS ) is None


# ───────────────────────── _resolve_job_state ─────────────────────────

def test_resolve_prefers_done_then_dead_then_run():
    h = _Harness()
    with patch.object( lpb.requests, "get", side_effect=_queue_getter( { "run": [ JOB ] } ) ):
        assert h._resolve_job_state( "pr-x", HEADERS ) == ( "run", JOB )

def test_resolve_absent_returns_none_none():
    h = _Harness()
    with patch.object( lpb.requests, "get", side_effect=_queue_getter( {} ) ):
        assert h._resolve_job_state( "pr-x", HEADERS ) == ( None, None )


# ───────────────────────── _submit_and_wait timeout paths ─────────────

def _run_submit_and_wait( queue_contents, timeout=2 ):
    h = _Harness()
    with patch.object( lpb.requests, "post", return_value=_resp( 200, { "job_id": "pr-x" } ) ), \
         patch.object( lpb.requests, "get", side_effect=_queue_getter( queue_contents ) ), \
         patch.object( lpb.time, "sleep" ):
        return h._submit_and_wait( SCENARIO, HEADERS, "ws1", timeout=timeout )

def test_done_during_poll_returns_job():
    job, err = _run_submit_and_wait( { "done": [ JOB ] } )
    assert job == JOB and err is None

def test_dead_during_poll_reports_failure_not_timeout():
    job, err = _run_submit_and_wait( { "dead": [ { "job_id": "pr-x", "error": "gate unreachable" } ] } )
    assert job is None
    assert "FAILED (dead queue)" in err and "gate unreachable" in err

def test_timeout_still_running_reports_running_not_failed():
    """RED-PROOF: healthy job still in run at timeout → 'STILL RUNNING', never 'failed'."""
    job, err = _run_submit_and_wait( { "run": [ JOB ] }, timeout=2 )
    assert job is None
    assert "STILL RUNNING after 2s" in err
    assert "did NOT fail" in err
    assert "FAILED" not in err

def test_resolve_prefers_done_over_run():
    """A completed job must be found as 'done' even if a stale 'run' row lingers —
    done-first ordering is what turns the false-fail back into a PASS."""
    h = _Harness()
    with patch.object( lpb.requests, "get", side_effect=_queue_getter( { "done": [ JOB ], "run": [ JOB ] } ) ):
        assert h._resolve_job_state( "pr-x", HEADERS ) == ( "done", JOB )

def test_timeout_done_missed_by_poll_returns_job_as_pass():
    """The exact 2026-08-03 false-fail, reproduced end-to-end: the job completes
    just PAST the poll window. The loop sees empty done/dead every iteration and
    times out; the job lands in 'done' only on the final wait, so ONLY the
    post-timeout resolver finds it — and returns it as a PASS, not a timeout FAIL.

    Stateful mock: time.sleep flips 'done' to contain the job on its LAST call,
    after the loop's final poll read — so the loop genuinely misses it."""
    h = _Harness()
    contents = { "done": [] }
    calls = { "n": 0 }

    def _sleep( *a, **k ):
        calls[ "n" ] += 1
        if calls[ "n" ] == 2:            # timeout=2, POLL_INTERVAL=1 → 2 sleeps, then loop exits
            contents[ "done" ] = [ JOB ]

    with patch.object( lpb.requests, "post", return_value=_resp( 200, { "job_id": "pr-x" } ) ), \
         patch.object( lpb.requests, "get", side_effect=_queue_getter( contents ) ), \
         patch.object( lpb.time, "sleep", side_effect=_sleep ):
        job, err = h._submit_and_wait( SCENARIO, HEADERS, "ws1", timeout=2 )

    assert job == JOB and err is None, f"slow-but-done job must PASS, got ({job!r}, {err!r})"

def test_timeout_absent_reports_not_found():
    job, err = _run_submit_and_wait( {}, timeout=2 )
    assert job is None
    assert "NOT FOUND in any queue" in err


# ══════════════════════════════════════════════════════════════════════════════
# The v2 cutover — BOTH ARMS (2026-08-21)
#
# `/api/push` queued the work and answered `{status: "queued", job_id}`, so the harness
# submitted and polled. `/api/v2/ask` does not queue: with `v2 executor = inline` the
# agent runs on the request thread and the response IS the terminal result. Polling such
# a job waits out the whole timeout and then reports a job that finished before the first
# poll.
#
# The branch is on the RESPONSE, not the endpoint, and both arms are pinned here. Once
# the queued executor lands, an agentic job comes back "waiting" with a job_id through
# the SAME door and must still be polled — an endpoint-only branch would be correct
# today and wrong the moment that merges. That is the case the second half covers.
# ══════════════════════════════════════════════════════════════════════════════

def test_a_terminal_v2_answer_is_the_result_and_nothing_is_polled():
    h = _Harness()
    body = { "status": "done", "path": "agent", "answer": "the answer", "trace_id": "t1" }
    with patch.object( lpb.requests, "post", return_value=_resp( 200, body ) ), \
         patch.object( lpb.requests, "get", side_effect=AssertionError( "must not poll a finished job" ) ):
        job, err = h._submit_and_wait( SCENARIO, HEADERS, "ws-1", timeout=1 )

    assert err is None
    # Mapped onto the key every validator already reads, so no scenario file changes.
    assert job[ "response_text" ] == "the answer"


def test_a_waiting_v2_response_still_polls_the_done_queue():
    """
    The arm that keeps this honest after Krishna's queued executor merges. Same door,
    same harness — a job that went to a queue answers "waiting" with a job_id, and the
    old submit-then-poll path has to run for it.
    """
    h = _Harness()
    body = { "status": "waiting", "job_id": "pr-x", "trace_id": "t2" }
    with patch.object( lpb.requests, "post", return_value=_resp( 200, body ) ), \
         patch.object( lpb.requests, "get", side_effect=_queue_getter( { "done": [ JOB ] } ) ):
        job, err = h._submit_and_wait( SCENARIO, HEADERS, "ws-1", timeout=5 )

    assert err is None
    assert job == JOB, "a waiting response must be resolved by polling, not read as an answer"


def test_a_failed_v2_flow_is_reported_as_a_failure_not_an_empty_answer():
    h = _Harness()
    body = { "status": "failed", "error": "router exploded", "trace_id": "t3" }
    with patch.object( lpb.requests, "post", return_value=_resp( 200, body ) ):
        job, err = h._submit_and_wait( SCENARIO, HEADERS, "ws-1", timeout=1 )

    assert job is None
    assert "router exploded" in err


def test_a_flow_that_stops_to_ask_is_a_failure_not_a_pass():
    """
    A scenario that parks never ran to an answer. Reporting it as a pass with an empty
    answer would be worse than reporting a failure — the validators keyword-match on
    `response_text`, and an empty string quietly matches nothing while the run reads green
    for anything with no expected keywords.
    """
    h = _Harness()
    body = { "status": "needs_input", "args_missing": [ "date" ], "trace_id": "t4" }
    with patch.object( lpb.requests, "post", return_value=_resp( 200, body ) ):
        job, err = h._submit_and_wait( SCENARIO, HEADERS, "ws-1", timeout=1 )

    assert job is None
    assert "needs_input" in err and "date" in err


def test_an_old_style_queued_response_is_untouched():
    """
    The legacy shape carries no `status` this branch recognises, so it falls straight
    through to polling — which is what every pre-cutover caller and the pinned v1 eval
    server still produce.
    """
    h = _Harness()
    body = { "status": "queued", "job_id": "pr-x", "websocket_id": "ws-1" }
    with patch.object( lpb.requests, "post", return_value=_resp( 200, body ) ), \
         patch.object( lpb.requests, "get", side_effect=_queue_getter( { "done": [ JOB ] } ) ):
        job, err = h._submit_and_wait( SCENARIO, HEADERS, "ws-1", timeout=5 )

    assert err is None
    assert job == JOB
