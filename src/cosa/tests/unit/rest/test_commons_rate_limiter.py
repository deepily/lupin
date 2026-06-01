"""
Unit tests for the commons broadcast rate limiter
(cosa.rest.commons_rate_limiter.CommonsBroadcastRateLimiter).

Covers construction validation, the atomic check-and-record sliding window
(first call, within-window rejection, post-window re-allow), the reset hook
(single-user + all-users), and the _peek inspector — to genuine 100% line +
branch + function.

time.monotonic is patched to drive the sliding window deterministically (no
real sleeps). Zero external dependencies.
"""

import unittest
from unittest.mock import patch

from cosa.rest.commons_rate_limiter import CommonsBroadcastRateLimiter


class TestConstruction( unittest.TestCase ):
    """
    Validate __init__ window-length guarding.

    Ensures:
        - A positive window is stored as a float
        - A zero or negative window raises ValueError
    """

    def test_positive_window_stored_as_float( self ):
        rl = CommonsBroadcastRateLimiter( window_seconds=5 )
        self.assertEqual( rl.window_seconds, 5.0 )
        self.assertIsInstance( rl.window_seconds, float )

    def test_zero_window_raises( self ):
        with self.assertRaises( ValueError ) as ctx:
            CommonsBroadcastRateLimiter( window_seconds=0 )
        self.assertIn( "window_seconds must be positive", str( ctx.exception ) )

    def test_negative_window_raises( self ):
        with self.assertRaises( ValueError ):
            CommonsBroadcastRateLimiter( window_seconds=-1 )


class TestCheckAndRecord( unittest.TestCase ):
    """
    Validate the atomic sliding-window check-and-record.

    Ensures:
        - First post for a user is allowed and records the time
        - A second post within the window is rejected with a retry_after
        - A post after the window elapses is allowed again (stale entry overwrite)
    """

    def test_first_post_allowed( self ):
        rl = CommonsBroadcastRateLimiter( window_seconds=10 )
        with patch( "cosa.rest.commons_rate_limiter.time.monotonic", return_value=100.0 ):
            allowed, retry_after = rl.check_and_record( "user-a" )
        self.assertTrue( allowed )
        self.assertIsNone( retry_after )
        self.assertEqual( rl._peek( "user-a" ), 100.0 )

    def test_second_post_within_window_rejected( self ):
        rl = CommonsBroadcastRateLimiter( window_seconds=10 )
        with patch( "cosa.rest.commons_rate_limiter.time.monotonic", side_effect=[ 100.0, 103.0 ] ):
            first_allowed, _ = rl.check_and_record( "user-a" )
            second_allowed, retry_after = rl.check_and_record( "user-a" )
        self.assertTrue( first_allowed )
        self.assertFalse( second_allowed )
        # 10s window, 3s elapsed → 7s remaining
        self.assertAlmostEqual( retry_after, 7.0 )
        # Rejected call must NOT overwrite the recorded timestamp
        self.assertEqual( rl._peek( "user-a" ), 100.0 )

    def test_post_after_window_allowed_again( self ):
        rl = CommonsBroadcastRateLimiter( window_seconds=10 )
        with patch( "cosa.rest.commons_rate_limiter.time.monotonic", side_effect=[ 100.0, 111.0 ] ):
            rl.check_and_record( "user-a" )
            allowed, retry_after = rl.check_and_record( "user-a" )
        # 11s elapsed > 10s window → allowed, and the timestamp is refreshed
        self.assertTrue( allowed )
        self.assertIsNone( retry_after )
        self.assertEqual( rl._peek( "user-a" ), 111.0 )

    def test_distinct_users_independent( self ):
        rl = CommonsBroadcastRateLimiter( window_seconds=10 )
        with patch( "cosa.rest.commons_rate_limiter.time.monotonic", return_value=50.0 ):
            a_allowed, _ = rl.check_and_record( "user-a" )
            b_allowed, _ = rl.check_and_record( "user-b" )
        self.assertTrue( a_allowed )
        self.assertTrue( b_allowed )


class TestResetAndPeek( unittest.TestCase ):
    """
    Validate the test-only reset hook and the _peek inspector.

    Ensures:
        - reset(user_id) clears a single user's entry only
        - reset(None) clears ALL state
        - _peek returns None for an unknown user
    """

    def test_reset_single_user( self ):
        rl = CommonsBroadcastRateLimiter( window_seconds=10 )
        with patch( "cosa.rest.commons_rate_limiter.time.monotonic", return_value=10.0 ):
            rl.check_and_record( "user-a" )
            rl.check_and_record( "user-b" )
        rl.reset( "user-a" )
        self.assertIsNone( rl._peek( "user-a" ) )
        self.assertEqual( rl._peek( "user-b" ), 10.0 )

    def test_reset_all_users( self ):
        rl = CommonsBroadcastRateLimiter( window_seconds=10 )
        with patch( "cosa.rest.commons_rate_limiter.time.monotonic", return_value=10.0 ):
            rl.check_and_record( "user-a" )
            rl.check_and_record( "user-b" )
        rl.reset()
        self.assertIsNone( rl._peek( "user-a" ) )
        self.assertIsNone( rl._peek( "user-b" ) )

    def test_peek_unknown_user_returns_none( self ):
        rl = CommonsBroadcastRateLimiter( window_seconds=10 )
        self.assertIsNone( rl._peek( "nobody" ) )


def isolated_unit_test():
    """
    Run the commons_rate_limiter unit tests in isolation.

    Ensures:
        - Returns (success, duration, message) for the smoke-runner harness
    """
    import time as _t
    start_time = _t.time()
    suite = unittest.TestLoader().loadTestsFromModule( __import__( __name__ ) )
    result = unittest.TextTestRunner( verbosity=2 ).run( suite )
    duration = _t.time() - start_time
    success = result.wasSuccessful()
    message = f"{result.testsRun} run, {len( result.failures )} failed, {len( result.errors )} errors"
    return success, duration, message


if __name__ == "__main__":
    ok, secs, msg = isolated_unit_test()
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} commons_rate_limiter tests in {secs:.3f}s — {msg}" )
