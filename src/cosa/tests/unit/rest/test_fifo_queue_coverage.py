#!/usr/bin/env python3
"""
Supplemental unit tests — `cosa.rest.fifo_queue.FifoQueue` coverage closure.

Complements `test_fifo_queue.py` (which owns init / push / pop / head /
get_by_id_hash / state / size / emission). This file closes the remaining gap:

    - `push` protocol-violation TypeError arm,
    - `get_push_counter`,
    - `pop_next_eligible` (paused-skip, scheduled future/past/tz/unparseable,
      stale-job pruning, empty),
    - `earliest_scheduled_at` (paused-skip, tz-normalize, unparseable-skip,
      earliest-selection, none),
    - `delete_by_id_hash` (found / not-found),
    - `has_changed`, `clear`,
    - `get_jobs_for_user` / `get_jobs_excluding_user` / `get_all_jobs`,
    - `_get_notification_job_id`, `_notify` (full email-resolution +
      abstract-promotion + debug + exception matrix).

Boundary-mock discipline: `notify_user_async` is patched (no real
notification dispatch); `user_job_tracker` is replaced per-instance with a
Mock (no real tracker state); jobs are lightweight fakes/Mocks. ZERO network,
ZERO DB, ZERO TTS.

Run: PYTHONPATH=src:src/cosa/tests/unit/infrastructure \
     src/cosa/.venv/bin/python -m pytest \
     src/cosa/tests/unit/rest/test_fifo_queue_coverage.py -v
"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from cosa.rest.fifo_queue import FifoQueue
from cosa.rest.job_state  import JobState


def _job( id_hash, state=JobState.QUEUED, scheduled_at=None, user_email="u@test.com" ):
    """Build a lightweight fake job carrying the attrs FifoQueue reads.

    artifacts defaults to an empty dict so `_notify`'s abstract auto-promotion
    reads a real (empty) mapping rather than an auto-vivified Mock attribute.
    """
    j              = Mock()
    j.id_hash      = id_hash
    j.state        = state
    j.scheduled_at = scheduled_at
    j.user_email   = user_email
    j.artifacts    = {}
    return j


class TestPushProtocolGuard( unittest.TestCase ):
    """
    Exercises the `push` QueueableJob-protocol boundary check.

    Ensures:
        - a non-conforming item raises TypeError naming the offending type
    """

    def test_push_rejects_non_queueable( self ):
        q = FifoQueue()
        # A bare object implements none of the protocol → is_queueable_job False
        with self.assertRaises( TypeError ) as ctx:
            q.push( object() )
        self.assertIn( "QueueableJob protocol", str( ctx.exception ) )

    def test_get_push_counter( self ):
        q = FifoQueue()
        self.assertEqual( q.get_push_counter(), 0 )
        q.push( _job( "h1" ) )
        self.assertEqual( q.get_push_counter(), 1 )


class TestPopNextEligible( unittest.TestCase ):
    """
    Exercises `pop_next_eligible` eligibility logic.

    Ensures:
        - empty queue returns None
        - paused jobs are skipped
        - immediate (scheduled_at None) jobs are eligible
        - future-scheduled jobs are skipped; past-scheduled are eligible
        - tz-aware scheduled_at is normalized before comparison
        - unparseable scheduled_at is treated as immediate
        - a stale queue_list entry (missing from queue_dict) is pruned
    """

    def setUp( self ):
        self.q = FifoQueue()

    def test_empty_returns_none( self ):
        self.assertIsNone( self.q.pop_next_eligible() )

    def test_paused_skipped( self ):
        self.q.push( _job( "paused", state=JobState.PAUSED ) )
        self.assertIsNone( self.q.pop_next_eligible() )
        # still in queue (skipped, not removed)
        self.assertEqual( self.q.size(), 1 )

    def test_immediate_eligible( self ):
        self.q.push( _job( "imm" ) )
        job = self.q.pop_next_eligible()
        self.assertEqual( job.id_hash, "imm" )
        self.assertEqual( self.q.size(), 0 )

    def test_future_scheduled_skipped( self ):
        future = ( datetime.now() + timedelta( hours=1 ) ).isoformat()
        self.q.push( _job( "future", scheduled_at=future ) )
        self.assertIsNone( self.q.pop_next_eligible() )
        self.assertEqual( self.q.size(), 1 )

    def test_past_scheduled_eligible( self ):
        past = ( datetime.now() - timedelta( hours=1 ) ).isoformat()
        self.q.push( _job( "past", scheduled_at=past ) )
        job = self.q.pop_next_eligible()
        self.assertEqual( job.id_hash, "past" )

    def test_tz_aware_scheduled_normalized( self ):
        # tz-aware UTC string in the past → normalized to naive-local, eligible
        past_utc = ( datetime.now( timezone.utc ) - timedelta( hours=2 ) ).isoformat()
        self.q.push( _job( "tzpast", scheduled_at=past_utc ) )
        job = self.q.pop_next_eligible()
        self.assertEqual( job.id_hash, "tzpast" )

    def test_unparseable_scheduled_treated_immediate( self ):
        self.q.push( _job( "bad", scheduled_at="not-a-date" ) )
        job = self.q.pop_next_eligible()
        self.assertEqual( job.id_hash, "bad" )

    def test_stale_queue_list_entry_pruned( self ):
        j = _job( "stale" )
        self.q.push( j )
        # Desync: remove from dict but leave in list → stale entry
        del self.q.queue_dict[ "stale" ]
        result = self.q.pop_next_eligible()
        self.assertIsNone( result )           # nothing eligible (stale pruned)
        self.assertEqual( len( self.q.queue_list ), 0 )

    def test_explicit_now_argument( self ):
        # Pass now explicitly; a job scheduled before it is eligible
        ref  = datetime( 2030, 1, 1, 12, 0, 0 )
        self.q.push( _job( "sched", scheduled_at="2030-01-01T11:00:00" ) )
        job  = self.q.pop_next_eligible( now=ref )
        self.assertEqual( job.id_hash, "sched" )


class TestEarliestScheduledAt( unittest.TestCase ):
    """
    Exercises `earliest_scheduled_at`.

    Ensures:
        - returns None when no scheduled non-paused jobs exist
        - paused jobs are ignored
        - tz-aware values are normalized
        - unparseable values are skipped
        - the minimum scheduled datetime is selected across candidates
    """

    def setUp( self ):
        self.q = FifoQueue()

    def test_none_when_all_immediate( self ):
        self.q.push( _job( "imm" ) )
        self.assertIsNone( self.q.earliest_scheduled_at() )

    def test_paused_ignored( self ):
        self.q.push( _job( "p", state=JobState.PAUSED, scheduled_at="2030-01-01T00:00:00" ) )
        self.assertIsNone( self.q.earliest_scheduled_at() )

    def test_unparseable_skipped( self ):
        self.q.push( _job( "bad", scheduled_at="nope" ) )
        self.assertIsNone( self.q.earliest_scheduled_at() )

    def test_selects_minimum( self ):
        # Push early FIRST so a subsequent later job exercises the
        # `scheduled_dt < earliest` FALSE arm (the 289->279 not-earlier path).
        self.q.push( _job( "early",  scheduled_at="2030-01-01T00:00:00" ) )
        self.q.push( _job( "late",   scheduled_at="2030-06-01T00:00:00" ) )
        self.q.push( _job( "latest", scheduled_at="2030-12-01T00:00:00" ) )
        earliest = self.q.earliest_scheduled_at()
        self.assertEqual( earliest, datetime( 2030, 1, 1, 0, 0, 0 ) )

    def test_tz_aware_normalized( self ):
        utc = datetime( 2030, 3, 1, 0, 0, 0, tzinfo=timezone.utc ).isoformat()
        self.q.push( _job( "tz", scheduled_at=utc ) )
        result = self.q.earliest_scheduled_at()
        self.assertIsNotNone( result )
        self.assertIsNone( result.tzinfo )    # normalized to naive


class TestDeleteByIdHash( unittest.TestCase ):
    """
    Exercises `delete_by_id_hash`.

    Ensures:
        - deleting a present item returns True and rebuilds queue_list
        - deleting an absent id_hash returns False
    """

    def test_delete_present( self ):
        q = FifoQueue()
        q.push( _job( "a" ) )
        q.push( _job( "b" ) )
        self.assertTrue( q.delete_by_id_hash( "a" ) )
        self.assertEqual( q.size(), 1 )
        self.assertNotIn( "a", q.queue_dict )
        self.assertEqual( q.queue_list[ 0 ].id_hash, "b" )

    def test_delete_absent_returns_false( self ):
        q = FifoQueue()
        q.push( _job( "a" ) )
        self.assertFalse( q.delete_by_id_hash( "missing" ) )
        self.assertEqual( q.size(), 1 )


class TestHasChangedAndClear( unittest.TestCase ):
    """
    Exercises `has_changed` and `clear`.

    Ensures:
        - has_changed returns True on first size change, False when unchanged
        - clear empties both structures and resets counters/flags
    """

    def test_has_changed_transitions( self ):
        q = FifoQueue()
        # initial last_queue_size 0, size 0 → unchanged
        self.assertFalse( q.has_changed() )
        q.push( _job( "a" ) )
        self.assertTrue( q.has_changed() )    # 0 → 1
        self.assertFalse( q.has_changed() )   # 1 → 1 unchanged

    def test_clear_resets_all( self ):
        q = FifoQueue()
        q.push( _job( "a" ) )
        q.push_blocking_object( "blk" )
        q.clear()
        self.assertEqual( q.size(), 0 )
        self.assertEqual( len( q.queue_dict ), 0 )
        self.assertEqual( q.push_counter, 0 )
        self.assertIsNone( q._blocking_object )
        self.assertTrue( q._accepting_jobs )


class TestUserJobAccessors( unittest.TestCase ):
    """
    Exercises `get_jobs_for_user`, `get_jobs_excluding_user`, `get_all_jobs`.

    Requires:
        - the per-instance user_job_tracker is mocked to return a fixed id set

    Ensures:
        - for-user returns only the user's jobs
        - excluding-user returns the complement
        - get_all_jobs returns a copy of the full queue_list
    """

    def setUp( self ):
        self.q = FifoQueue()
        self.ja = _job( "a" )
        self.jb = _job( "b" )
        self.jc = _job( "c" )
        for j in ( self.ja, self.jb, self.jc ):
            self.q.push( j )
        self.q.user_job_tracker = Mock()
        self.q.user_job_tracker.get_jobs_for_user.return_value = { "a", "c" }

    def test_get_jobs_for_user( self ):
        result = self.q.get_jobs_for_user( "u1" )
        self.assertEqual( { j.id_hash for j in result }, { "a", "c" } )

    def test_get_jobs_excluding_user( self ):
        result = self.q.get_jobs_excluding_user( "u1" )
        self.assertEqual( { j.id_hash for j in result }, { "b" } )

    def test_get_all_jobs_returns_copy( self ):
        result = self.q.get_all_jobs()
        self.assertEqual( len( result ), 3 )
        result.clear()                       # mutating copy must not affect queue
        self.assertEqual( self.q.size(), 3 )


class TestGetNotificationJobId( unittest.TestCase ):
    """
    Exercises `_get_notification_job_id`.

    Ensures:
        - None job → None
        - job with truthy id_hash → that id_hash
        - job without id_hash → None
    """

    def setUp( self ):
        self.q = FifoQueue()

    def test_none_job( self ):
        self.assertIsNone( self.q._get_notification_job_id( None ) )

    def test_job_with_id_hash( self ):
        self.assertEqual( self.q._get_notification_job_id( _job( "h9" ) ), "h9" )

    def test_job_without_id_hash( self ):
        # a plain object has no id_hash attribute → None
        self.assertIsNone( self.q._get_notification_job_id( object() ) )


class TestNotify( unittest.TestCase ):
    """
    Exercises `_notify` across its email-resolution / abstract-promotion matrix.

    Requires:
        - `notify_user_async` is patched (no real dispatch)

    Ensures:
        - explicit target_user is used
        - falls back to job.user_email, then LUPIN_DEV_EMAIL
        - skips (no dispatch) when no email is resolvable
        - explicit abstract overrides; otherwise auto-reads job.artifacts["abstract"]
        - debug branch prints when self.debug is set
        - a notify_user_async exception is swallowed
    """

    def setUp( self ):
        self.q = FifoQueue( queue_name="tq" )

    def _run( self, **kwargs ):
        with patch( "cosa.rest.fifo_queue.notify_user_async" ) as mk:
            self.q._notify( **kwargs )
        return mk

    def test_explicit_target_user( self ):
        mk = self._run( msg="hi", target_user="a@b.com" )
        mk.assert_called_once()
        req = mk.call_args.args[ 0 ]
        self.assertEqual( req.target_user, "a@b.com" )

    def test_resolves_from_job_email( self ):
        # job_id must satisfy AsyncNotificationRequest's hash-pattern validator
        job = _job( "dr-a1b2c3d4", user_email="job@x.com" )
        mk  = self._run( msg="hi", job=job )
        req = mk.call_args.args[ 0 ]
        self.assertEqual( req.target_user, "job@x.com" )
        self.assertEqual( req.job_id, "dr-a1b2c3d4" )

    def test_dev_email_fallback( self ):
        with patch.dict( "os.environ", { "LUPIN_DEV_EMAIL": "dev@x.com" } ):
            mk = self._run( msg="hi" )       # no target, no job
        mk.assert_called_once()
        self.assertEqual( mk.call_args.args[ 0 ].target_user, "dev@x.com" )

    def test_no_email_skips_dispatch( self ):
        with patch.dict( "os.environ", { "LUPIN_DEV_EMAIL": "" } ):
            mk = self._run( msg="hi" )       # no target, no job, empty dev email
        mk.assert_not_called()

    def test_job_present_but_empty_email_falls_to_dev( self ):
        job = _job( "dr-a1b2c3d4", user_email="" )    # job present, email falsy
        with patch.dict( "os.environ", { "LUPIN_DEV_EMAIL": "dev@x.com" } ):
            mk = self._run( msg="hi", job=job )
        self.assertEqual( mk.call_args.args[ 0 ].target_user, "dev@x.com" )

    def test_explicit_abstract_used( self ):
        mk  = self._run( msg="hi", target_user="a@b.com", abstract="EXPLICIT" )
        self.assertEqual( mk.call_args.args[ 0 ].abstract, "EXPLICIT" )

    def test_abstract_auto_from_job_artifacts( self ):
        job = _job( "dr-a1b2c3d4" )
        job.artifacts = { "abstract": "FROM_JOB" }
        mk  = self._run( msg="hi", job=job )
        self.assertEqual( mk.call_args.args[ 0 ].abstract, "FROM_JOB" )

    def test_abstract_none_when_artifacts_missing( self ):
        job = _job( "dr-a1b2c3d4" )
        job.artifacts = None                 # `or {}` → empty → .get returns None
        mk  = self._run( msg="hi", job=job )
        self.assertIsNone( mk.call_args.args[ 0 ].abstract )

    def test_debug_branch_prints( self ):
        self.q.debug = True
        mk = self._run( msg="hello world", target_user="a@b.com" )
        mk.assert_called_once()              # debug path is print-only; dispatch still happens

    def test_exception_swallowed( self ):
        with patch( "cosa.rest.fifo_queue.notify_user_async", side_effect=Exception( "boom" ) ):
            # must not raise
            self.q._notify( msg="hi", target_user="a@b.com" )


def isolated_unit_test():
    """
    Run this module's tests in isolation.

    Ensures:
        - returns True when all tests pass, False otherwise
    """
    import sys
    suite  = unittest.TestLoader().loadTestsFromModule( sys.modules[ __name__ ] )
    result = unittest.TextTestRunner( verbosity=2 ).run( suite )
    return result.wasSuccessful()


if __name__ == "__main__":
    isolated_unit_test()
