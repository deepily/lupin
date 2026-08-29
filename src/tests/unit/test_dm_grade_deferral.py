"""
Row ec5cf83a — DM quality grading runs OFF the send path.

WHAT THIS FILE PINS. Accepting a DM used to include grading it: two live model
calls to the judge endpoint inside execute_dm_send, before it returned. A slow
grader made every fleet DM slow, and a dead one made it slower still. Rick ruled
on 2026-08-19 that the grade comes off the send path; the mechanism (a single
background worker fed by an in-process queue, which also writes the corpus row)
was picked in dm.py and is documented there.

THE ACCEPTANCE, in Mr Radio's words, is a MEASUREMENT and not an inspection:
"prove it with the endpoint DOWN — send latency must be indistinguishable from
the endpoint being up." TestTheEndpointBeingDownCostsTheSenderNothing below is
that measurement, and it carries its own live control: the same dead grader run
SYNCHRONOUSLY, in the same class, so a reader can see the cost the deferral
removes rather than take the green on faith.

INDISTINGUISHABLE IS A NUMBER HERE, NOT AN ADJECTIVE (Mr Radio's correction,
2026-08-19): the first draft asked only that the gap be "far below what the dead
endpoint costs", which a worker adding real latency could still pass. The test
compares MEDIANS over several sends per arm, and both measured numbers are
printed on failure so a reader never has to take the comparison on trust.

WHICH OUTAGE THE DENOMINATOR IS BUILT FROM, because since commit c5bac2b8 there
are two and they differ by three orders of magnitude (Mr Radio, 2026-08-19):
  · a COLD client on a dead port breaks immediately — ~0.00s, no retries
  · a client that answered once and THEN went dead keeps its full 3 attempts —
    ~3.00s, measured on row ec5cf83a
The warm-then-dead arm is the honest outage, so _DEAD_COST_S is 3.00s. Five
percent of that is generous, so the allowed gap is the TIGHTER of that 5% and
the per-send cap — the cap binds at 50ms, and the failure message says both.

WHAT THE NUMBER IS AND IS NOT (Mr Radio, 2026-08-19). The medians below are of
the SEND CODE PATH with every collaborator faked — no socket, no database, no
recipient. A median in the tenths of a millisecond is the proof of that, not an
end-to-end DM. That is the right cut for this question: it isolates the grader,
so the only thing that can move the number is where the grade runs. The revert
control is what turns it into evidence — the identical harness with grading back
inline reads three full seconds.

A DEAD ENDPOINT IS MODELLED, NOT DIALLED. A unit test may not open a routed
socket (row 7c84b8b8), so "the endpoint is down" is a grader that sleeps for the
outage and then raises ConnectionError. What the REAL judge costs against a dead
port is pinned by TestADeadPortDoesNotBuyRetries in test_dm_quality_judge_v2.py.
This file owns the other half: whatever the grader costs, the SENDER does not pay
it.
"""

import json
import os
import statistics
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import cosa.rest.dm_experiment as dm_experiment


# The in-window slots the experiment-path tests below use. Same shape as
# test_dm_experiment.py's, duplicated rather than imported: a test file that
# imports another test file's fixtures makes both harder to delete.
_SLOT_REJECTING = { "slot_id": "tue-09", "arm": "rejecting", "local_hour": 9,
                    "start_utc": "2026-08-04T13:00:00+00:00", "end_utc": "2026-08-04T14:00:00+00:00" }
_SLOT_BLIND     = { "slot_id": "tue-10", "arm": "blind", "local_hour": 10,
                    "start_utc": "2026-08-04T14:00:00+00:00", "end_utc": "2026-08-04T15:00:00+00:00" }
_IN_REJECTING   = datetime( 2026, 8, 4, 13, 30, tzinfo=timezone.utc )
_IN_BLIND       = datetime( 2026, 8, 4, 14, 30, tzinfo=timezone.utc )
_LONG_BODY      = " ".join( [ "word" ] * 160 )   # over the 150-word gate

_GRADE = {
    "length"     : { "emoji": "⭐", "weight":  2, "detail": "3 words, target ~60" },
    "directness" : { "emoji": "👍", "weight":  1, "detail": "leads with the result" },
    "tone"       : { "emoji": "😞", "weight": -2, "detail": "curt" },
    "overall"    : { "emoji": "👍", "weight":  1, "note": "ok" },
}


def _run_deferred_inline( job ):
    """Run the deferred job in the caller's thread and report it accepted."""
    job()
    return True


def _make_send_body( **overrides ):
    from cosa.rest.routers.dm import DmSendRequest
    fields = dict(
        sender_session_id = "asker-session-aaaa",
        sender_project    = "lupin",
        body              = "short body here.",
        recipient_persona = "mr radio",
        sender_persona    = "María",
        sender_icon       = "🌸",
    )
    fields.update( overrides )
    return DmSendRequest( **fields )


class _SendHarness( unittest.TestCase ):
    """execute_dm_send with every collaborator faked and the corpus redirected."""

    def setUp( self ):
        import cosa.rest.routers.dm as dm
        self.dm      = dm
        self.execute = dm.execute_dm_send
        self.queue   = MagicMock()
        self.persist = MagicMock( return_value="db-123" )
        self.spy     = MagicMock( side_effect=lambda sid, project=None: f"claude.code@{project}.deepily.ai#{sid}" )
        self.resolve = MagicMock( return_value={
            "http_status": 200, "session_id": "abcdef1234567890", "persona_name": "mr radio" } )
        self.corpus_path = os.path.join( tempfile.mkdtemp(), "dm_traffic.jsonl" )
        _cp = patch.object( dm, "_DM_TRAFFIC_JSONL", self.corpus_path )
        _cp.start(); self.addCleanup( _cp.stop )
        # The two-arm pilot forks on the arrival instant; pin it inactive so the
        # baseline tests here are independent of the wall clock.
        dm_experiment.set_policy( dm_experiment.make_inactive_policy() )
        self.addCleanup( dm_experiment.reset_policy )
        dm.reset_dm_grade_audit()
        self.addCleanup( dm.reset_dm_grade_audit )

    def _send( self, body=None, grader=lambda b: None, arrival=None, **kw ):
        if arrival is not None:
            kw[ "arrival_utc_fn" ] = lambda: arrival
        return self.execute(
            authenticated_user_id = "user-uuid-1",
            body                  = body if body is not None else _make_send_body(),
            notification_queue    = self.queue,
            resolve_recipient_fn  = self.resolve,
            build_sender_id       = self.spy,
            persist_fn            = self.persist,
            new_id_fn             = lambda: "fixed-msg-id",
            grade_quality_fn      = grader,
            **kw,
        )

    def _rows( self ):
        if not os.path.exists( self.corpus_path ):
            return []
        return [ json.loads( line ) for line in
                 open( self.corpus_path, encoding="utf-8" ).read().splitlines() ]


class TestTheInlineRunnerIsAnInstrument( unittest.TestCase ):
    """
    CONTROL — every assertion below that reads a grade depends on
    _run_deferred_inline actually running the job. A runner that silently did
    nothing would make "the row has no grade" pass against correct code.
    """

    def test_the_inline_runner_runs_the_job_and_reports_acceptance( self ):
        ran = []
        self.assertTrue( _run_deferred_inline( lambda: ran.append( 1 ) ) )
        self.assertEqual( ran, [ 1 ] )


class TestNoModelCallInTheSendersTimeline( _SendHarness ):
    """The send returns on the send: it queues the grade and does not run it."""

    def test_a_queued_grade_is_never_called_by_the_send( self ):
        called = []
        queued = []
        result = self._send( grader=lambda b: called.append( b ) or _GRADE,
                             defer_grade_fn=lambda job: queued.append( job ) or True )
        self.assertEqual( result[ "http_status" ], 201 )
        self.assertEqual( called, [] )          # the grader did not run here
        self.assertEqual( len( queued ), 1 )    # it was handed to the worker

    def test_a_queued_but_unrun_grade_leaves_no_row_YET( self ):
        """
        A message with no grade yet is a normal state (Mr Radio's ruling). The row
        and its grade arrive together, on the worker — so until the job runs there
        is nothing on disk, and that is not an error.
        """
        self._send( grader=lambda b: _GRADE, defer_grade_fn=lambda job: True )
        self.assertEqual( self._rows(), [] )

    def test_the_201_carries_no_quality_key( self ):
        result = self._send( grader=lambda b: _GRADE, defer_grade_fn=_run_deferred_inline )
        self.assertNotIn( "quality", result )

    def test_running_the_job_writes_exactly_one_row_carrying_the_grade( self ):
        self._send( grader=lambda b: _GRADE, defer_grade_fn=_run_deferred_inline )
        rows = self._rows()
        self.assertEqual( len( rows ), 1 )
        self.assertEqual( rows[ 0 ][ "len_grade" ],  2 )
        self.assertEqual( rows[ 0 ][ "directness" ], 1 )
        self.assertEqual( rows[ 0 ][ "tone" ],      -2 )
        self.assertEqual( rows[ 0 ][ "overall" ],    1 )

    def test_the_grader_sees_the_delivered_body( self ):
        seen = []
        self._send( body=_make_send_body( body="crisp verdict here." ),
                    grader=lambda b: seen.append( b ), defer_grade_fn=_run_deferred_inline )
        self.assertEqual( seen, [ "crisp verdict here." ] )   # no EDT "[...]" prefix

    def test_a_refused_deferral_still_writes_the_row_ungraded( self ):
        """
        Backlog full, or the pytest self-guard: the deferral is refused and the row
        is written HERE, without a grade. Losing a statistic is acceptable; losing
        the row is a lost measurement.
        """
        called = []
        self._send( grader=lambda b: called.append( b ) or _GRADE,
                    defer_grade_fn=lambda job: False )
        rows = self._rows()
        self.assertEqual( called, [] )
        self.assertEqual( len( rows ), 1 )
        self.assertIsNone( rows[ 0 ][ "len_grade" ] )
        self.assertIsNone( rows[ 0 ][ "overall" ] )


class TestTheEndpointBeingDownCostsTheSenderNothing( _SendHarness ):
    """
    THE ACCEPTANCE MEASUREMENT. Send latency with a dead grader must be
    INDISTINGUISHABLE from send latency with a live one — held to a number, not an
    adjective — and the same class measures what that grader costs when it is NOT
    deferred, so the green is reported next to the cost it removed.
    """

    # The WARM-THEN-DEAD outage: a judge client that answered once and then lost its
    # endpoint keeps its full 3-attempt budget, measured at ~3.00s on row ec5cf83a
    # (before c5bac2b8 a cold client paid this too; after it, a cold one breaks at
    # ~0.00s). The warm number is the honest one to size a latency bar against.
    _DEAD_COST_S = 3.00
    _SEND_CAP_S  = 0.05      # what one SEND is allowed to cost, either way
    _SAMPLES     = 5         # sends per arm; medians compared, so one stall cannot decide

    @property
    def _max_gap_s( self ):
        """The TIGHTER of 5% of the outage and the per-send cap. At a 3s outage the
        5% figure is 150ms — generous enough that a real leak could hide under it —
        so the cap binds instead."""
        return min( self._DEAD_COST_S * 0.05, self._SEND_CAP_S )

    def _dead_grader( self, body_text ):
        """The endpoint is down: the judge burns its retry budget and then fails."""
        time.sleep( self._DEAD_COST_S )
        raise ConnectionError( "192.168.1.21:3001 refused" )

    def _slow_grader( self, body_text ):
        """The endpoint is SLOW rather than dead — same wall-clock cost, and it
        returns, so the synchronous control below measures latency without the
        exception semantics getting in the way of the number."""
        time.sleep( self._DEAD_COST_S )
        return _GRADE

    def _live_grader( self, body_text ):
        return _GRADE

    def _timed_send( self, grader, defer_grade_fn ):
        started = time.monotonic()
        result  = self._send( grader=grader, defer_grade_fn=defer_grade_fn )
        return result, time.monotonic() - started

    def _median_send_s( self, grader, defer_grade_fn ):
        samples = []
        for _ in range( self._SAMPLES ):
            result, elapsed = self._timed_send( grader, defer_grade_fn )
            self.assertEqual( result[ "http_status" ], 201 )
            samples.append( elapsed )
        return statistics.median( samples )

    def test_a_dead_grader_and_a_live_one_cost_the_send_the_same( self ):
        queued = []
        take   = lambda job: queued.append( job ) or True
        live_s = self._median_send_s( self._live_grader, take )
        dead_s = self._median_send_s( self._dead_grader, take )
        gap    = abs( dead_s - live_s )
        # Every number is in the failure message: a reader who does not believe the
        # green can read what was actually measured instead of re-deriving it.
        detail = ( f"median send with the endpoint UP={live_s*1000:.2f}ms, "
                   f"DOWN={dead_s*1000:.2f}ms, gap={gap*1000:.2f}ms, "
                   f"allowed gap={self._max_gap_s*1000:.2f}ms, "
                   f"per-send cap={self._SEND_CAP_S*1000:.2f}ms, "
                   f"the warm-then-dead endpoint itself costs {self._DEAD_COST_S*1000:.2f}ms" )
        self.assertLess( live_s, self._SEND_CAP_S, detail )
        self.assertLess( dead_s, self._SEND_CAP_S, detail )
        self.assertLessEqual( gap, self._max_gap_s, detail )
        self.assertEqual( len( queued ), self._SAMPLES * 2 )   # every grade was queued

    def test_THE_CONTROL_the_same_dead_grader_run_inline_costs_the_send_everything( self ):
        """
        The cost is real and this instrument can see it. Run the identical grader
        on the send's own thread — which is what the code did before this row — and
        the send pays the whole outage. If this test ever goes green under the cap,
        the measurement above is measuring nothing.
        """
        result, elapsed = self._timed_send( self._slow_grader, _run_deferred_inline )
        self.assertEqual( result[ "http_status" ], 201 )
        self.assertGreaterEqual( elapsed, self._DEAD_COST_S )
        self.assertGreater( elapsed, self._SEND_CAP_S )

    def test_a_grader_that_raises_is_invisible_to_the_sender_and_still_leaves_a_row( self ):
        """
        Run the raising grader THROUGH the deferred job (inline, so the assertion
        does not race it). The send is 201, no exception reaches the caller, and the
        row is still on disk — ungraded. Losing the grade to a broken grader is
        acceptable; losing the row is not, because the row cannot be recomputed.
        """
        result = self._send( grader=self._dead_grader, defer_grade_fn=_run_deferred_inline )
        self.assertEqual( result[ "http_status" ], 201 )
        rows = self._rows()
        self.assertEqual( len( rows ), 1 )
        self.assertIsNone( rows[ 0 ][ "overall" ] )
        self.assertEqual( rows[ 0 ][ "body" ], "short body here." )


class TestTheGradingWorker( unittest.TestCase ):
    """_submit_deferred_grade itself — the production default."""

    def setUp( self ):
        import cosa.rest.routers.dm as dm
        self.dm = dm
        dm.reset_dm_grade_audit()
        self.addCleanup( dm.reset_dm_grade_audit )
        self.addCleanup( self._shutdown_worker )

    def _shutdown_worker( self ):
        if self.dm._dm_grade_executor is not None:
            self.dm._dm_grade_executor.shutdown( wait=True )
            self.dm._dm_grade_executor = None

    def test_under_pytest_the_deferral_is_refused_and_no_worker_is_started( self ):
        """
        THE SELF-GUARD, and the defect it exists for. Grading asynchronously broke
        the toggle pins the send-path tests rely on: the background call landed
        after the patch context had exited and dialled the live endpoint for real
        (observed 2026-08-19). Refusing under pytest means no unit test can reach
        the grader through the default, and no grading thread can outlive its test.
        """
        ran = []
        self.assertFalse( self.dm._submit_deferred_grade( lambda: ran.append( 1 ) ) )
        self.assertEqual( ran, [] )
        self.assertIsNone( self.dm._dm_grade_executor )
        self.assertEqual( self.dm.get_dm_grade_audit()[ "refused_under_pytest" ], 1 )
        self.assertEqual( self.dm.get_dm_grade_audit()[ "accepted" ], 0 )

    def test_outside_pytest_the_job_runs_on_a_worker_thread( self ):
        done   = threading.Event()
        where  = {}
        def job():
            where[ "thread" ] = threading.current_thread().name
            done.set()
        with patch.object( self.dm, "_running_under_pytest", lambda: False ):
            self.assertTrue( self.dm._submit_deferred_grade( job ) )
        self.assertTrue( done.wait( timeout=5 ) )
        self.assertNotEqual( where[ "thread" ], threading.current_thread().name )
        self.assertTrue( where[ "thread" ].startswith( "dm-grade" ) )
        self._shutdown_worker()
        audit = self.dm.get_dm_grade_audit()
        self.assertEqual( audit[ "accepted" ], 1 )
        self.assertEqual( audit[ "pending" ],  0 )
        self.assertEqual( audit[ "failed" ],   0 )

    def test_the_worker_is_built_once_and_reused( self ):
        with patch.object( self.dm, "_running_under_pytest", lambda: False ):
            first  = self.dm._get_dm_grade_executor()
            second = self.dm._get_dm_grade_executor()
        self.assertIs( first, second )

    def test_a_full_backlog_refuses_the_deferral( self ):
        ran = []
        with patch.object( self.dm, "_running_under_pytest", lambda: False ):
            self.dm._dm_grade_audit[ "pending" ] = self.dm._DM_GRADE_MAX_PENDING
            try:
                self.assertFalse( self.dm._submit_deferred_grade( lambda: ran.append( 1 ) ) )
            finally:
                self.dm._dm_grade_audit[ "pending" ] = 0
        self.assertEqual( ran, [] )
        self.assertEqual( self.dm.get_dm_grade_audit()[ "refused" ], 1 )
        self.assertIsNone( self.dm._dm_grade_executor )

    def test_a_job_that_raises_is_counted_and_the_worker_survives( self ):
        """A worker thread that dies takes every LATER grade with it — a silent
        stop. The raise is caught, counted, and the next job still runs."""
        second_ran = threading.Event()
        def boom():
            raise RuntimeError( "grader exploded" )
        with patch.object( self.dm, "_running_under_pytest", lambda: False ):
            self.assertTrue( self.dm._submit_deferred_grade( boom ) )
            self.assertTrue( self.dm._submit_deferred_grade( second_ran.set ) )
        self.assertTrue( second_ran.wait( timeout=5 ) )
        self._shutdown_worker()
        audit = self.dm.get_dm_grade_audit()
        self.assertEqual( audit[ "failed" ],   1 )
        self.assertEqual( audit[ "accepted" ], 2 )
        self.assertEqual( audit[ "pending" ],  0 )

    def test_the_audit_snapshot_is_a_copy_and_reset_zeroes_it( self ):
        snapshot = self.dm.get_dm_grade_audit()
        snapshot[ "accepted" ] = 99
        self.assertEqual( self.dm.get_dm_grade_audit()[ "accepted" ], 0 )
        self.dm._submit_deferred_grade( lambda: None )              # counts a refusal
        self.assertEqual( self.dm.get_dm_grade_audit()[ "refused_under_pytest" ], 1 )
        self.dm.reset_dm_grade_audit()
        self.assertEqual( self.dm.get_dm_grade_audit()[ "refused_under_pytest" ], 0 )


class TestTheExperimentPathDefersToo( _SendHarness ):
    """
    In-window sends grade for the corpus and the audit tally, never for the sender.
    That is unchanged; WHEN the grade runs is not.
    """

    def _set_policy( self, **kw ):
        kw.setdefault( "slots", [ _SLOT_REJECTING, _SLOT_BLIND ] )
        dm_experiment.set_policy( dm_experiment.make_policy( **kw ) )

    def test_a_delivered_in_window_send_defers_its_grade( self ):
        self._set_policy()
        called = []
        queued = []
        result = self._send( arrival=_IN_BLIND,
                             grader=lambda b: called.append( b ) or _GRADE,
                             defer_grade_fn=lambda job: queued.append( job ) or True )
        self.assertEqual( result[ "http_status" ], 201 )
        self.assertEqual( called, [] )            # not in the sender's timeline
        self.assertEqual( len( queued ), 1 )
        queued[ 0 ]()                             # now run what the worker would
        rows = self._rows()
        self.assertEqual( len( rows ), 1 )
        self.assertEqual( rows[ 0 ][ "overall" ],       1 )
        self.assertEqual( rows[ 0 ][ "effective_arm" ], "blind" )

    def test_a_413_refusal_writes_its_row_inline_and_never_grades( self ):
        """
        The crash-honest `delivery_outcome` contract is untouched: an outcome that
        never delivered never had a grade to defer, so its row is written on the
        spot rather than queued behind a grader.
        """
        self._set_policy()
        queued = []
        result = self._send( body=_make_send_body( body=_LONG_BODY ), arrival=_IN_REJECTING,
                             grader=lambda b: _GRADE,
                             defer_grade_fn=lambda job: queued.append( job ) or True )
        self.assertEqual( result[ "http_status" ], 413 )
        self.assertEqual( queued, [] )
        rows = self._rows()
        self.assertEqual( len( rows ), 1 )
        self.assertEqual( rows[ 0 ][ "delivery_outcome" ], "not_attempted" )
        self.assertIsNone( rows[ 0 ][ "overall" ] )

    def test_a_failed_delivery_writes_its_row_inline_and_never_grades( self ):
        self._set_policy()
        queued = []
        self.persist.side_effect = RuntimeError( "db down" )
        with self.assertRaises( RuntimeError ):
            self._send( arrival=_IN_BLIND, grader=lambda b: _GRADE,
                        defer_grade_fn=lambda job: queued.append( job ) or True )
        self.assertEqual( queued, [] )
        rows = self._rows()
        self.assertEqual( len( rows ), 1 )
        self.assertEqual( rows[ 0 ][ "delivery_outcome" ], "failed" )
        self.assertIsNone( rows[ 0 ][ "overall" ] )


class TestTheSenderStillGetsItsGrade( _SendHarness ):
    """
    Mr Radio's ruling, 2026-08-19: taking the grade out of the 201 must not take it
    away from the sender. That feedback IS the live intervention (arm `signal_only`
    — grade shown, nothing refused), so the worker pushes it back. Two constraints
    came with the ruling and each has a test: it NAMES the message it grades, and it
    is best-effort and silent when the sender seat is gone.
    """

    def _pushed( self ):
        return [ call.kwargs for call in self.queue.push_notification.call_args_list ]

    def test_the_grade_is_pushed_back_to_the_sending_session( self ):
        self._send( grader=lambda b: _GRADE, defer_grade_fn=_run_deferred_inline )
        grades = [ p for p in self._pushed() if p[ "sender_persona" ] == "DM Quality Judge" ]
        self.assertEqual( len( grades ), 1 )
        # Routed to the SENDER's seat, not the recipient's — the DM itself went to
        # "abcdef12"; the grade comes back to "asker-se".
        self.assertEqual( grades[ 0 ][ "job_id" ], "asker-se" )
        self.assertTrue( grades[ 0 ][ "suppress_ding" ] )

    def test_the_notice_names_the_message_it_grades( self ):
        """
        A late grade with no anchor is the same confusion arriving slower. The anchor
        is the id the SENDER was handed in its 201 — which is the db id when the row
        persisted, not the pre-persist message id, so the sender can match the two
        without knowing that distinction exists.
        """
        result = self._send( grader=lambda b: _GRADE, defer_grade_fn=_run_deferred_inline )
        grades = [ p for p in self._pushed() if p[ "sender_persona" ] == "DM Quality Judge" ]
        self.assertIn( result[ "message_id" ], grades[ 0 ][ "message" ] )
        self.assertIn( "overall", grades[ 0 ][ "message" ] )

    def test_a_withheld_dimension_reads_as_withheld_not_as_zero( self ):
        from cosa.rest.routers.dm import format_dm_grade_notice
        length_only = dict( _GRADE )
        length_only[ "directness" ] = { "emoji": "♾️", "weight": None }
        length_only[ "tone" ]       = { "emoji": "♾️", "weight": None }
        notice = format_dm_grade_notice( "msg-1", length_only )
        self.assertIn( "directness —", notice )
        self.assertIn( "tone —", notice )
        self.assertNotIn( "directness ♾️ +0", notice )

    def test_a_gone_seat_is_silent_not_an_error( self ):
        """
        A reaped worker is a normal outcome. The push raising must not reach the send,
        must not lose the corpus row, and must not kill the grading worker — which
        would take every LATER grade with it.
        """
        self.queue.push_notification.side_effect = [ None, RuntimeError( "no such session" ) ]
        result = self._send( grader=lambda b: _GRADE, defer_grade_fn=_run_deferred_inline )
        self.assertEqual( result[ "http_status" ], 201 )
        rows = self._rows()
        self.assertEqual( len( rows ), 1 )
        self.assertEqual( rows[ 0 ][ "overall" ], 1 )      # the row kept its grade

    def test_no_grade_means_no_notice( self ):
        self._send( grader=lambda b: None, defer_grade_fn=_run_deferred_inline )
        grades = [ p for p in self._pushed() if p[ "sender_persona" ] == "DM Quality Judge" ]
        self.assertEqual( grades, [] )

    def test_a_refused_deferral_delivers_nothing( self ):
        self._send( grader=lambda b: _GRADE, defer_grade_fn=lambda job: False )
        grades = [ p for p in self._pushed() if p[ "sender_persona" ] == "DM Quality Judge" ]
        self.assertEqual( grades, [] )

    def test_a_delivery_hook_that_raises_is_caught_by_the_job( self ):
        """The hook catches its own failures; this proves the job catches them too, so
        a future delivery path cannot kill the worker by forgetting to."""
        def boom( quality ):
            raise RuntimeError( "delivery exploded" )
        result = self._send( grader=lambda b: _GRADE, defer_grade_fn=_run_deferred_inline,
                             deliver_grade_fn=boom )
        self.assertEqual( result[ "http_status" ], 201 )
        self.assertEqual( len( self._rows() ), 1 )

    def test_an_in_window_send_pushes_NO_grade_to_its_sender( self ):
        """
        The blind arm stays blind. Pushing the grade in-window would hand the sender
        exactly the signal the arm exists to withhold — the same reason the in-window
        201 carries no `quality` key in either arm.
        """
        dm_experiment.set_policy( dm_experiment.make_policy( slots=[ _SLOT_REJECTING, _SLOT_BLIND ] ) )
        queued = []
        self._send( arrival=_IN_BLIND, grader=lambda b: _GRADE,
                    defer_grade_fn=lambda job: queued.append( job ) or True )
        queued[ 0 ]()
        grades = [ p for p in self._pushed() if p[ "sender_persona" ] == "DM Quality Judge" ]
        self.assertEqual( grades, [] )


if __name__ == "__main__":
    unittest.main()
