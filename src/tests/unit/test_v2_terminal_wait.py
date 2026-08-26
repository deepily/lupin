"""
The falsifier for the span asymmetry (row a2e360f8, Mr Radio's catch in the since-deleted
v1_eval_arm.py:373).

v1 measures send -> observed COMPLETION. v2 measured send -> reply, which under
`v2 executor = queued` is the ENQUEUE ACK. The paired median-delta gate therefore compared
v1-at-completion against v2-at-enqueue, and every millisecond of v2's deferred work landed
in v1's column. `terminal_waiting_ask` makes v2's span end where v1's does.

WHAT THESE TESTS DELIBERATELY DO NOT CLAIM: nothing here measures how much work v2 defers.
That number does not exist and the two published estimates (~2400 ms, ~1909 ms) were
WITHDRAWN as cross-run subtractions. These tests prove the wrapper moves the measurement to
the right event; only a symmetric live run says what the corrected delta is.
"""

import os
import sys

import pytest


def _load():
    scripts = os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "scripts" )
    if scripts not in sys.path: sys.path.insert( 0, scripts )
    import v2_eval
    return v2_eval


ve = _load()


class _Clock:
    """A monotonic stub: each call returns the next scripted second."""
    def __init__( self, *ticks ): self.ticks = list( ticks ); self.i = 0
    def __call__( self ):
        v = self.ticks[ min( self.i, len( self.ticks ) - 1 ) ]; self.i += 1
        return v


def _waiting_reply( job_id="jid-1" ):
    return {
        "utterance"      : "u", "ok": True, "status_code": 200,
        "client_span_ms" : 583.0,
        "payload"        : { "status": ve.STATUS_WAITING, "job_id": job_id, "similarity": None },
    }


def _done_reply():
    return {
        "utterance"      : "u", "ok": True, "status_code": 200,
        "client_span_ms" : 3440.0,
        "payload"        : { "status": "done", "job_id": "jid-1", "similarity": 99.0 },
    }


def _frames( *states ):
    return [ { "to_state": s, "timestamp": "2026-08-25T21:00:00+00:00",
               "metadata": { "is_cache_hit": True } } for s in states ]


# ---------------------------------------------------------------------------
# The defect: a waiting reply's span must end at the terminal frame
# ---------------------------------------------------------------------------
def test_a_waiting_reply_is_remeasured_to_the_terminal_frame():
    seen = {}
    def ws( job_id ):
        seen[ "job_id" ] = job_id
        return _frames( "queued", "running", "completed" )
    wrapped = ve.terminal_waiting_ask( lambda q: _waiting_reply(), ws, clock=_Clock( 10.0, 14.5 ) )
    rec = wrapped( "u" )
    assert seen[ "job_id" ] == "jid-1", "the wrapper must wait on the job the reply named"
    assert rec[ "client_span_ms" ] == pytest.approx( 4500.0 ), (
        "span must be send->terminal (14.5 - 10.0 = 4.5s), not the 583ms enqueue ack"
    )
    assert rec[ "terminal_waited" ] is True
    assert rec[ "payload" ][ "status" ] == "completed"


def test_the_terminal_metadata_is_carried_onto_the_record():
    wrapped = ve.terminal_waiting_ask( lambda q: _waiting_reply(),
                                       lambda j: _frames( "queued", "completed" ),
                                       clock=_Clock( 0.0, 1.0 ) )
    rec = wrapped( "u" )
    assert rec[ "payload" ][ "terminal_meta" ] == { "is_cache_hit": True }, (
        "the outcome the arm could not see before is exactly what the gate needs"
    )


def test_a_failed_job_is_terminal_too_and_is_not_skipped():
    wrapped = ve.terminal_waiting_ask( lambda q: _waiting_reply(),
                                       lambda j: _frames( "queued", "running", "failed" ),
                                       clock=_Clock( 0.0, 2.0 ) )
    rec = wrapped( "u" )
    assert rec[ "payload" ][ "status" ] == "failed"
    assert rec[ "client_span_ms" ] == pytest.approx( 2000.0 )


def test_the_last_terminal_frame_wins_when_several_arrive():
    wrapped = ve.terminal_waiting_ask( lambda q: _waiting_reply(),
                                       lambda j: _frames( "completed", "interrupted" ),
                                       clock=_Clock( 0.0, 1.0 ) )
    assert wrapped( "u" )[ "payload" ][ "status" ] == "interrupted"


# ---------------------------------------------------------------------------
# THE THIRD STATE — named, counted, and it must NOT kill the pass
#
# This block asserted the OPPOSITE until 2026-08-25 21:39, when Mr Radio ruled. The
# reasoning it replaces was "mirror v1, let the timeout propagate". The asymmetry is
# deliberate and is the whole reason these two arms differ here: v1 can afford to raise
# because it has ALREADY DUMPED its artifact; a v2 kill loses the entire run and produces
# no artifact at all — precisely the failure the poll exists to end.
# ---------------------------------------------------------------------------
def test_a_timed_out_wait_does_not_kill_the_pass():
    def ws( job_id ): raise RuntimeError( "v2 WS collect timed out for job 'jid-1'" )
    wrapped = ve.terminal_waiting_ask( lambda q: _waiting_reply(), ws, clock=_Clock( 0.0, 1.0 ) )
    rec = wrapped( "u" )                      # must RETURN, not raise
    assert rec[ "wait_timed_out" ] is True
    assert rec[ "terminal_waited" ] is False, "it is not observed — the harness gave up"
    assert "collect timed out" in rec[ "wait_timeout_detail" ], (
        "the row must NAME what it caught, so a non-timeout RuntimeError cannot be counted "
        "as a timeout anonymously"
    )


def test_a_timed_out_wait_keeps_the_enqueue_span_and_is_kept_out_of_the_gate():
    """
    The span stays honest in the raw record AND unusable to the paired gate. Leaving it in
    would reintroduce the exact enqueue-vs-completion bias this row exists to remove, this
    time through the timeout path.
    """
    def ws( job_id ): raise RuntimeError( "collect timed out" )
    wrapped = ve.terminal_waiting_ask( lambda q: _waiting_reply(), ws, clock=_Clock( 0.0, 9.0 ) )
    rec = wrapped( "u" )
    rec[ "expected_command" ] = "agent router go to weather"
    assert rec[ "client_span_ms" ] == 583.0, "the enqueue span is kept, flagged — not rewritten"

    metrics = ve.compute_metrics( [ rec ] )
    assert metrics[ "waits_timed_out_n" ] == 1
    assert metrics[ "spans_by_utterance" ] == {}, "a timed-out row must not reach the paired gate"
    assert metrics[ "client_p50_ms" ] is None


def test_a_timed_out_wait_is_counted_apart_from_observed_and_from_waiting():
    """Three rows, three states — the count is what stops the third being read as another."""
    def ws_ok( job_id ):   return _frames( "queued", "completed" )
    def ws_slow( job_id ): raise RuntimeError( "collect timed out" )

    observed = ve.terminal_waiting_ask( lambda q: _waiting_reply( "jid-obs" ), ws_ok,
                                        clock=_Clock( 0.0, 2.0 ) )( "u-observed" )
    timed_out = ve.terminal_waiting_ask( lambda q: _waiting_reply( "jid-slow" ), ws_slow,
                                         clock=_Clock( 0.0, 2.0 ) )( "u-timeout" )
    still_waiting = _waiting_reply( "jid-wait" )       # never wrapped: no one looked at all
    still_waiting[ "utterance" ] = "u-waiting"
    observed[ "utterance" ]  = "u-observed"
    timed_out[ "utterance" ] = "u-timeout"
    for r in ( observed, timed_out, still_waiting ): r[ "expected_command" ] = "agent router go to weather"

    metrics = ve.compute_metrics( [ observed, timed_out, still_waiting ] )
    assert metrics[ "waits_timed_out_n" ]  == 1, "the timed-out row is counted on its own"
    assert metrics[ "cache_observed_n" ]   == 1, "only the completed row is observed"
    assert metrics[ "cache_unobserved_n" ] == 2, (
        "both non-observed rows are still unobserved — the new count SPLITS them, it does "
        "not remove either from the honest total"
    )


# ---------------------------------------------------------------------------
# NEGATIVE CONTROLS — the wrapper must be inert on every path it is not for
# ---------------------------------------------------------------------------
def test_a_non_waiting_reply_is_returned_untouched():
    """An inline-executor run must be bit-identical, wrapper or not."""
    def ws( job_id ): raise AssertionError( "must not wait on an already-terminal reply" )
    wrapped = ve.terminal_waiting_ask( lambda q: _done_reply(), ws, clock=_Clock( 0.0, 99.0 ) )
    rec = wrapped( "u" )
    assert rec[ "client_span_ms" ] == 3440.0, "an inline reply's span must not be rewritten"
    assert "terminal_waited" not in rec


def test_an_http_error_is_returned_untouched():
    err = { "utterance": "u", "ok": False, "status_code": 500,
            "client_span_ms": 12.0, "payload": {} }
    def ws( job_id ): raise AssertionError( "must not wait on an error reply" )
    wrapped = ve.terminal_waiting_ask( lambda q: err, ws, clock=_Clock( 0.0, 99.0 ) )
    assert wrapped( "u" )[ "client_span_ms" ] == 12.0


def test_a_waiting_reply_with_no_job_id_is_marked_rather_than_silently_short():
    reply = _waiting_reply(); reply[ "payload" ].pop( "job_id" )
    def ws( job_id ): raise AssertionError( "nothing to wait on" )
    wrapped = ve.terminal_waiting_ask( lambda q: reply, ws, clock=_Clock( 0.0, 99.0 ) )
    rec = wrapped( "u" )
    assert rec[ "client_span_ms" ] == 583.0
    assert rec[ "terminal_waited" ] is False, (
        "an unwaitable row must be visible; a silently-short span is the defect this fixes"
    )


def test_the_two_arms_agree_on_what_terminal_means():
    """If these sets ever diverge the gate compares two different events under one name."""
    scripts = os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "scripts" )
    if scripts not in sys.path: sys.path.insert( 0, scripts )
    # v1_eval_arm is DELETED (row e2099400 §2). The set it used to own moved to
    # ws_job_listener with the listener; the property is unchanged — the two must agree on
    # what "finished" means, or the terminal wait is watching for a different event.
    import ws_job_listener
    assert ve.V2_TERMINAL_STATES == ws_job_listener._TERMINAL_STATES


def test_frames_with_no_terminal_state_still_remeasure_but_do_not_invent_a_status():
    """
    The listener's contract says it only returns once a frame is terminal, so this is the
    seam-violated path. It is covered rather than pragma'd because the SAFE behaviour is
    not obvious: the span is still send->when-we-stopped-waiting (honest), but the status
    is left exactly as the server reported it. Inventing a terminal status here would be
    the harness asserting an outcome nobody observed - the whole defect this row is about.
    """
    wrapped = ve.terminal_waiting_ask( lambda q: _waiting_reply(),
                                       lambda j: _frames( "queued", "running" ),
                                       clock=_Clock( 0.0, 3.0 ) )
    rec = wrapped( "u" )
    assert rec[ "client_span_ms" ] == pytest.approx( 3000.0 )
    assert rec[ "terminal_waited" ] is True
    assert rec[ "payload" ][ "status" ] == ve.STATUS_WAITING, "no invented outcome"
    assert "terminal_meta" not in rec[ "payload" ]
