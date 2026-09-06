#!/usr/bin/env python3
"""
THE ORPHAN SWEEPER, AND THE ONE PROPERTY IT MUST NOT LOSE (row bf4f65c3).

A response-required notification whose asking client WALKED AWAY is never marked
expired: the SSE generator is suspended at `await asyncio.wait_for( ... )`, a TCP
close raises `asyncio.CancelledError` there, and the only writer of
state='expired' sits in `except asyncio.TimeoutError`. The row stays 'delivered'
forever. Measured 2026-09-05 ~22:00 UTC against lupin_db_dev: 39 such rows,
oldest 2026-05-11, newest that same day. Positive control on the same scan:
3,125 'responded' and 1,551 'expired', so the instrument reaches the population
and 39 is a finding rather than a silence.

🔴 THE PROPERTY THESE TESTS EXIST FOR, AND IT IS NOT "DOES THE SWEEPER SWEEP".
`expires_at` IS NOT WHEN THE HUMAN STOPPED CARING. `/respond` accepts a late
answer against an 'expired' row for `notification grace period seconds`, and
against a 'delivered' row FOREVER. So a sweeper marking at `expires_at` would
convert a genuine keypress into a 400 — manufacturing a non-answer out of an
answer, the exact inverse of the e5f21fff defect this epic exists for.

  answers landing AFTER expires_at            58
  answers landing BEFORE it (CONTROL)      3,070
      <= 300s (inside grace)                  57   highest of them: 298s
      301-600s                                 0   <- the gap
      >  600s                                  1   notification 33311818,
                                                   source="ui", 1,109s late

⇒ EVERY TEST BELOW COMES IN A PAIR. "It sweeps" and "it sweeps ONLY what it
should" are different claims, and a sweeper that marked everything would satisfy
the first. The in-grace arm is the one that carries the finding.
"""
import os
import sys
import uuid
import unittest
from datetime import datetime, timedelta, timezone

# jwt_service.py raises AT IMPORT when JWT_SECRET_KEY is unset, and the repo-root
# .env that supplies it on this host is gitignored — PRESENT in the main checkout,
# ABSENT in every worktree. A fixture runs after the collection-time import that
# needs it, so it must be set at module scope. Throwaway: nothing here signs a token.
os.environ.setdefault( "JWT_SECRET_KEY", "test-only-orphan-sweeper-guard" )

from cosa.rest.notification_expiry_sweeper import _partition, find_sweepable_ids, sweep_once


class _Row:
    """
    A candidate row — the fields the partition rule reads, plus the `state` the
    scan-then-mark guard turns on.

    `state` defaults to "delivered" because that is the only state
    get_expired_notifications can return; a row carrying anything else is
    standing in for one a peer answered BETWEEN the scan and the mark.
    """
    def __init__( self, row_id, expires_at, state="delivered" ):
        self.id         = row_id
        self.expires_at = expires_at
        self.state      = state


class _Repo:
    """
    A repository stand-in that HONOURS its input rather than ignoring it.

    A fake returning a fixed list whatever it is asked would answer the same
    however the code behaves — this repo records every mark_expired call WITH
    its apply_default argument, so a wrong call yields a different observation.

    IT ALSO HONOURS expected_state, and that is not decoration. Without it the
    sweeper's refusal path is unreachable from this tier: a fake that accepts
    the argument and ignores it reports every attempt as a sweep, which is the
    exact number the guard exists to correct. The real refusal is a Postgres
    WHERE clause and is proven against a live database in
    src/tests/smoke/test_mark_expired_refuses_to_overwrite_a_live_answer.py —
    what THIS fake pins is that the sweeper ASKS for the guard and COUNTS the
    answer, which no database can tell you.
    """
    def __init__( self, rows ):
        self.rows  = rows
        self.marks = []

    def get_expired_notifications( self ):
        return self.rows

    def mark_expired( self, notification_id, apply_default=True, expected_state=None ):
        row = next( ( r for r in self.rows if str( r.id ) == str( notification_id ) ), None )

        if expected_state is not None and ( row is None or row.state != expected_state ):
            return None

        self.marks.append( ( str( notification_id ), apply_default ) )

        return row


def _now():
    return datetime( 2026, 9, 5, 22, 0, 0, tzinfo=timezone.utc )


class TheGraceWindowIsHonoured( unittest.TestCase ):

    def test_a_row_past_expires_at_but_INSIDE_grace_is_not_swept( self ):
        """
        THE FINDING. Row 33311818 answered 1,109s late with source="ui" is why
        this arm exists: a sweeper that closed a row the moment expires_at
        passed would have refused that keypress with a 400.
        """
        now  = _now()
        rows = [ _Row( "inside", now - timedelta( seconds=120 ) ) ]

        sweepable, in_grace = _partition( rows, grace_seconds=300, now=now )

        self.assertEqual( sweepable, [] )
        self.assertEqual( in_grace, 1 )

    def test_a_row_past_expires_at_AND_past_grace_IS_swept( self ):
        """
        THE POSITIVE CONTROL. Without it, the arm above is indistinguishable
        from a partition that can never return anything at all.
        """
        now  = _now()
        rows = [ _Row( "outside", now - timedelta( seconds=400 ) ) ]

        sweepable, in_grace = _partition( rows, grace_seconds=300, now=now )

        self.assertEqual( sweepable, [ "outside" ] )
        self.assertEqual( in_grace, 0 )

    def test_the_boundary_is_inclusive_at_exactly_grace( self ):
        """A row exactly `grace` seconds past expiry is swept, not held."""
        now  = _now()
        rows = [ _Row( "exact", now - timedelta( seconds=300 ) ) ]

        sweepable, _ = _partition( rows, grace_seconds=300, now=now )

        self.assertEqual( sweepable, [ "exact" ] )

    def test_one_call_separates_a_mixed_batch_both_ways( self ):
        """
        Both populations in ONE call, so the result cannot be satisfied by a
        rule that always sweeps or always holds.
        """
        now  = _now()
        rows = [
            _Row( "old",    now - timedelta( days=30 ) ),
            _Row( "recent", now - timedelta( seconds=10 ) ),
            _Row( "past",   now - timedelta( seconds=901 ) ),
        ]

        sweepable, in_grace = _partition( rows, grace_seconds=300, now=now )

        self.assertEqual( sorted( sweepable ), [ "old", "past" ] )
        self.assertEqual( in_grace, 1 )

    def test_find_sweepable_ids_applies_the_same_rule_through_a_repo( self ):
        now  = _now()
        repo = _Repo( [
            _Row( "held",  now - timedelta( seconds=1 ) ),
            _Row( "ready", now - timedelta( seconds=3600 ) ),
        ] )

        self.assertEqual( find_sweepable_ids( repo, grace_seconds=300, now=now ), [ "ready" ] )


class ANaiveExpiresAtIsRefusedRatherThanCompared( unittest.TestCase ):

    def test_a_naive_expires_at_raises_instead_of_comparing_wrong( self ):
        """
        Row 3b4002fe was exactly this comparison going unnoticed: naive on both
        sides cancelled out under one session and did not across two, and an
        expired row was simply never swept. A refusal beats a wrong answer.
        """
        now  = _now()
        rows = [ _Row( "naive", datetime( 2026, 1, 1, 0, 0, 0 ) ) ]

        with self.assertRaises( TypeError ) as ctx:
            _partition( rows, grace_seconds=300, now=now )

        self.assertIn( "NAIVE", str( ctx.exception ) )

    def test_an_AWARE_expires_at_is_accepted_CONTROL( self ):
        """Without this, the refusal above could be a partition that always raises."""
        now  = _now()
        rows = [ _Row( "aware", datetime( 2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc ) ) ]

        self.assertEqual( _partition( rows, grace_seconds=300, now=now )[ 0 ], [ "aware" ] )


class TheSweeperNeverStampsAnAnswerNobodyGave( unittest.TestCase ):
    """
    On the TIMEOUT path a response_default is genuinely returned to a waiter, so
    recording it is true. On the SWEEP path nobody is waiting and nothing
    consumes it, so stamping one would assert an answer was supplied when none
    ever reached anyone.
    """

    def _run( self, rows, grace_seconds=300, batch_limit=200 ):
        repo = _Repo( rows )

        class _Session:
            def __enter__( self ):  return self
            def __exit__( self, *a ): return False

        import cosa.rest.notification_expiry_sweeper as mod
        real_repo_cls = None
        import cosa.rest.db.repositories.notification_repository as repo_mod
        real_repo_cls = repo_mod.NotificationRepository
        repo_mod.NotificationRepository = lambda session: repo
        try:
            result = sweep_once( _Session, grace_seconds, batch_limit, now=_now() )
        finally:
            repo_mod.NotificationRepository = real_repo_cls
        return repo, result

    def test_every_sweep_passes_apply_default_False( self ):
        # A REAL uuid: sweep_once parses the id with uuid.UUID, so a tidy
        # hand-written "a" would be a fixture better-formed than the rows the
        # repository actually returns.
        row_id       = str( uuid.uuid4() )
        repo, result = self._run( [ _Row( row_id, _now() - timedelta( days=1 ) ) ] )

        self.assertEqual( repo.marks, [ ( row_id, False ) ] )
        self.assertEqual( result[ "swept" ], 1 )

    def test_a_row_inside_grace_is_never_marked_at_all( self ):
        """The absence is load-bearing because the arm above shows a mark landing."""
        repo, result = self._run( [ _Row( str( uuid.uuid4() ), _now() - timedelta( seconds=30 ) ) ] )

        self.assertEqual( repo.marks, [] )
        self.assertEqual( result, { "scanned": 1, "swept": 0, "refused": 0, "skipped_in_grace": 1 } )

    def test_the_batch_limit_caps_one_pass_without_dropping_the_rest( self ):
        rows = [ _Row( str( uuid.uuid4() ), _now() - timedelta( days=1 ) ) for _ in range( 5 ) ]

        repo, result = self._run( rows, batch_limit=2 )

        self.assertEqual( len( repo.marks ), 2 )
        self.assertEqual( result, { "scanned": 5, "swept": 2, "refused": 0, "skipped_in_grace": 0 } )


class TheSweeperAsksForTheGuardAndCountsTheRefusal( unittest.TestCase ):
    """
    The sweeper->repository seam, which the grace-window arms above cannot see.

    Those arms pass whether or not the sweeper asks for the state guard at all,
    because a fake that ignores the argument marks every row anyway. These two
    turn on it: one proves the argument is SENT with the right value, the other
    proves a refusal lands in `refused` rather than being reported as a sweep.
    """

    def _run( self, repo, grace_seconds=300, batch_limit=200 ):
        """Drive the real sweep_once against a stand-in repository."""
        class _Session:
            def __enter__( self ):    return self
            def __exit__( self, *a ): return False

        import cosa.rest.db.repositories.notification_repository as repo_mod
        real_repo_cls = repo_mod.NotificationRepository
        repo_mod.NotificationRepository = lambda session: repo
        try:
            result = sweep_once( _Session, grace_seconds, batch_limit, now=_now() )
        finally:
            repo_mod.NotificationRepository = real_repo_cls

        return result

    def test_every_sweep_guards_on_delivered( self ):
        """
        The VALUE, not merely the presence of the argument. A sweeper passing
        expected_state=None compiles, runs, sweeps, and IS the unguarded code.
        """
        seen = []

        class _RecordingRepo( _Repo ):
            def mark_expired( self, notification_id, apply_default=True, expected_state=None ):
                seen.append( expected_state )
                return super().mark_expired( notification_id, apply_default, expected_state )

        repo   = _RecordingRepo( [ _Row( str( uuid.uuid4() ), _now() - timedelta( days=1 ) ) ] )
        result = self._run( repo )

        self.assertEqual( seen, [ "delivered" ] )
        self.assertEqual( result[ "swept" ], 1 )

    def test_a_row_answered_between_the_scan_and_the_mark_is_refused_not_swept( self ):
        """
        THE WHOLE POINT OF THE COUNT. Reporting len( targets ) would call this a
        sweep — and that is the one number that would tell us the race is live.
        """
        answered = _Row( str( uuid.uuid4() ), _now() - timedelta( days=1 ), state="responded" )
        clean    = _Row( str( uuid.uuid4() ), _now() - timedelta( days=1 ) )

        repo   = _Repo( [ answered, clean ] )
        result = self._run( repo )

        self.assertEqual( repo.marks, [ ( str( clean.id ), False ) ] )
        self.assertEqual(
            result, { "scanned": 2, "swept": 1, "refused": 1, "skipped_in_grace": 0 }
        )


class TheRepositoryHonoursApplyDefaultBothWays( unittest.TestCase ):

    def _notification( self ):
        class _N:
            def __init__( self ):
                self.state            = "delivered"
                self.response_default = "yes"
                self.response_value   = None
        return _N()

    def _repo_with( self, notification ):
        from cosa.rest.db.repositories.notification_repository import NotificationRepository

        repo             = NotificationRepository.__new__( NotificationRepository )
        repo.get_by_id   = lambda _id: notification
        class _S:
            def flush( self ): pass
        repo.session = _S()
        return repo

    def test_apply_default_False_leaves_response_value_untouched( self ):
        n    = self._notification()
        repo = self._repo_with( n )

        repo.mark_expired( uuid.uuid4(), apply_default=False )

        self.assertEqual( n.state, "expired" )
        self.assertIsNone( n.response_value )

    def test_the_default_TRUE_still_stamps_it_CONTROL( self ):
        """
        Every pre-existing caller relies on this. Without the control, the arm
        above could pass against a mark_expired that never stamps anything.
        """
        n    = self._notification()
        repo = self._repo_with( n )

        repo.mark_expired( uuid.uuid4() )

        self.assertEqual( n.state, "expired" )
        self.assertEqual( n.response_value, { "value": "yes", "source": "timeout_default" } )


if __name__ == "__main__":
    unittest.main()
