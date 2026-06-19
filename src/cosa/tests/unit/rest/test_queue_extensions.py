"""
Unit tests for the user-scoped job tracker (cosa.rest.queue_extensions.UserJobTracker).

Covers the thread-safe singleton lifecycle (fresh creation + re-init guard +
return-existing), register_scoped_job, associate_job_with_user, get_jobs_for_user
(copy semantics + unknown user), generate_user_scoped_hash (scoped + double-scope
strip), and remove_job (present / absent / empty-list cleanup) — to genuine 100%
line + branch + function.

The module-level singleton is snapshotted in setUp and restored in tearDown so
each test starts from a clean, isolated tracker without leaking into the shared
process-wide instance.
"""

import unittest

from cosa.rest import queue_extensions
from cosa.rest.queue_extensions import UserJobTracker


class TestUserJobTracker( unittest.TestCase ):
    """
    Validate UserJobTracker's singleton + indexing behavior in isolation.

    Requires:
        - The class-level _instance is reset per test for deterministic state

    Ensures:
        - Each test runs against a fresh tracker; the original singleton is
          restored afterward
    """

    def setUp( self ):
        # Snapshot the shared singleton, then force a fresh instance for this test.
        self._saved_instance = UserJobTracker._instance
        UserJobTracker._instance = None
        self.tracker = UserJobTracker()   # exercises the __new__ create branch + __init__

    def tearDown( self ):
        # Restore the original process-wide singleton.
        UserJobTracker._instance = self._saved_instance

    def test_singleton_returns_same_instance( self ):
        # Second construction returns the existing instance (return-existing branch
        # in __new__ + the _initialized early-return guard in __init__).
        again = UserJobTracker()
        self.assertIs( again, self.tracker )

    def test_module_global_is_a_tracker( self ):
        self.assertIsInstance( queue_extensions.user_job_tracker, UserJobTracker )

    def test_generate_user_scoped_hash_basic( self ):
        self.assertEqual( self.tracker.generate_user_scoped_hash( "abc", "user1" ), "abc::user1" )

    def test_generate_user_scoped_hash_strips_existing_scope( self ):
        # Double-scoping guard: an already-scoped hash is stripped before re-scoping.
        self.assertEqual(
            self.tracker.generate_user_scoped_hash( "abc::olduser", "user2" ),
            "abc::user2"
        )

    def test_register_scoped_job_indexes_and_returns_scoped_id( self ):
        scoped = self.tracker.register_scoped_job( "qhash", "user1" )
        self.assertEqual( scoped, "qhash::user1" )
        self.assertEqual( self.tracker.get_jobs_for_user( "user1" ), [ "qhash::user1" ] )
        self.assertEqual( self.tracker.job_to_user[ "qhash::user1" ], "user1" )

    def test_register_scoped_job_appends_for_existing_user( self ):
        self.tracker.register_scoped_job( "q1", "user1" )
        self.tracker.register_scoped_job( "q2", "user1" )
        self.assertEqual(
            self.tracker.get_jobs_for_user( "user1" ),
            [ "q1::user1", "q2::user1" ]
        )

    def test_associate_job_with_user_new_and_existing( self ):
        self.tracker.associate_job_with_user( "job-a", "user1" )   # new user branch
        self.tracker.associate_job_with_user( "job-b", "user1" )   # existing user branch
        self.assertEqual( self.tracker.get_jobs_for_user( "user1" ), [ "job-a", "job-b" ] )

    def test_get_jobs_for_user_unknown_returns_empty( self ):
        self.assertEqual( self.tracker.get_jobs_for_user( "nobody" ), [] )

    def test_get_jobs_for_user_returns_copy( self ):
        self.tracker.associate_job_with_user( "job-a", "user1" )
        snapshot = self.tracker.get_jobs_for_user( "user1" )
        snapshot.append( "tampered" )
        # External mutation of the returned list must not affect internal state.
        self.assertEqual( self.tracker.get_jobs_for_user( "user1" ), [ "job-a" ] )

    def test_remove_job_present_cleans_up_empty_user_list( self ):
        self.tracker.associate_job_with_user( "job-a", "user1" )
        self.tracker.remove_job( "job-a" )
        self.assertNotIn( "job-a", self.tracker.job_to_user )
        # Last job removed → the user's now-empty list is deleted entirely.
        self.assertNotIn( "user1", self.tracker.user_jobs )

    def test_remove_job_present_keeps_nonempty_user_list( self ):
        self.tracker.associate_job_with_user( "job-a", "user1" )
        self.tracker.associate_job_with_user( "job-b", "user1" )
        self.tracker.remove_job( "job-a" )
        # User still has job-b → list retained.
        self.assertEqual( self.tracker.get_jobs_for_user( "user1" ), [ "job-b" ] )

    def test_remove_job_absent_is_noop( self ):
        # Removing an unknown job hits the `if job_id in self.job_to_user` False arm.
        self.tracker.remove_job( "ghost" )   # must not raise
        self.assertEqual( self.tracker.job_to_user, {} )

    def test_remove_job_inconsistent_state_skips_user_jobs_cleanup( self ):
        # Defensive branch: job present in job_to_user but its user absent from
        # user_jobs (inconsistent index). remove_job must tolerate it — the
        # `if user_id in self.user_jobs` False arm is exercised here.
        self.tracker.job_to_user[ "orphan" ] = "ghost-user"
        self.tracker.remove_job( "orphan" )   # must not raise
        self.assertNotIn( "orphan", self.tracker.job_to_user )


def isolated_unit_test():
    """
    Run the queue_extensions unit tests in isolation.

    Ensures:
        - Returns (success, duration, message) for the smoke-runner harness
    """
    import time
    start_time = time.time()
    suite = unittest.TestLoader().loadTestsFromModule( __import__( __name__ ) )
    result = unittest.TextTestRunner( verbosity=2 ).run( suite )
    duration = time.time() - start_time
    success = result.wasSuccessful()
    message = f"{result.testsRun} run, {len( result.failures )} failed, {len( result.errors )} errors"
    return success, duration, message


if __name__ == "__main__":
    ok, secs, msg = isolated_unit_test()
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} queue_extensions tests in {secs:.3f}s — {msg}" )
