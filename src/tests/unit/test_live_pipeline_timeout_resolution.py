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
    SUBMIT_ENDPOINT = "/api/push"

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
