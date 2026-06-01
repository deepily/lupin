"""
Unit tests for the auth rate limiter (cosa.rest.rate_limiter).

Covers record_failed_login, check_account_lockout (locked / expired-lock /
no-recent-attempts / under-threshold / error), clear_failed_attempts,
cleanup_old_attempts (>=1 day / <1 day / error), and get_failed_attempts_count
(success / error) — to genuine 100% line + branch + function.

All DB access is boundary-mocked: get_db (context manager) +
FailedLoginAttemptRepository + the module-level config_mgr are patched. ZERO DB,
ZERO config-file reads at test time.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timedelta, timezone

from cosa.rest import rate_limiter


def _config_get( key, default=None, return_type=None ):
    """Stand-in for config_mgr.get covering the two keys the limiter reads."""
    return { "auth max failed attempts": 5, "auth lockout duration minutes": 15 }.get( key, default )


class _RateLimiterTestBase( unittest.TestCase ):
    """
    Shared harness: patch get_db (CM), the repository class, and config_mgr.

    Ensures:
        - self.repo is the mock FailedLoginAttemptRepository used by the SUT
        - No real database or configuration access occurs
    """

    def setUp( self ):
        self.repo = Mock()
        self._p_getdb = patch( "cosa.rest.rate_limiter.get_db" )
        self._p_repo  = patch( "cosa.rest.rate_limiter.FailedLoginAttemptRepository", return_value=self.repo )
        self._p_cfg   = patch.object( rate_limiter, "config_mgr" )
        mock_getdb = self._p_getdb.start()
        # `with get_db() as session:` → session is a throwaway MagicMock
        mock_getdb.return_value = MagicMock()
        self._p_repo.start()
        mock_cfg = self._p_cfg.start()
        mock_cfg.get.side_effect = _config_get

    def tearDown( self ):
        self._p_getdb.stop()
        self._p_repo.stop()
        self._p_cfg.stop()


class TestRecordFailedLogin( _RateLimiterTestBase ):
    def test_with_ip( self ):
        rate_limiter.record_failed_login( "u@e.com", "1.2.3.4" )
        self.repo.record_attempt.assert_called_once_with( "u@e.com", "1.2.3.4" )

    def test_without_ip_defaults( self ):
        rate_limiter.record_failed_login( "u@e.com" )
        self.repo.record_attempt.assert_called_once_with( "u@e.com", "0.0.0.0" )

    def test_exception_swallowed( self ):
        self.repo.record_attempt.side_effect = Exception( "db down" )
        with patch( "builtins.print" ) as mp:
            rate_limiter.record_failed_login( "u@e.com" )   # must not raise
        self.assertTrue( any( "Failed to record failed login" in str( c ) for c in mp.call_args_list ) )


class TestCheckAccountLockout( _RateLimiterTestBase ):
    def test_locked_when_recent_and_within_window( self ):
        self.repo.count_recent_by_email.return_value = 5   # >= max(5)
        attempt = Mock()
        attempt.attempt_time = datetime.now( timezone.utc )   # unlock = +15min > now → locked
        self.repo.get_recent_attempts_by_email.return_value = [ attempt ]

        is_locked, unlock_time = rate_limiter.check_account_lockout( "u@e.com" )
        self.assertTrue( is_locked )
        self.assertIsInstance( unlock_time, str )   # ISO string

    def test_not_locked_when_window_expired( self ):
        self.repo.count_recent_by_email.return_value = 6
        attempt = Mock()
        attempt.attempt_time = datetime.now( timezone.utc ) - timedelta( minutes=60 )  # unlock past
        self.repo.get_recent_attempts_by_email.return_value = [ attempt ]

        is_locked, unlock_time = rate_limiter.check_account_lockout( "u@e.com" )
        self.assertFalse( is_locked )
        self.assertIsNone( unlock_time )

    def test_over_threshold_but_no_recent_attempts( self ):
        self.repo.count_recent_by_email.return_value = 5
        self.repo.get_recent_attempts_by_email.return_value = []   # empty → falls through
        is_locked, unlock_time = rate_limiter.check_account_lockout( "u@e.com" )
        self.assertFalse( is_locked )
        self.assertIsNone( unlock_time )

    def test_under_threshold( self ):
        self.repo.count_recent_by_email.return_value = 2   # < max(5)
        is_locked, unlock_time = rate_limiter.check_account_lockout( "u@e.com" )
        self.assertFalse( is_locked )
        self.assertIsNone( unlock_time )

    def test_exception_returns_unlocked( self ):
        self.repo.count_recent_by_email.side_effect = Exception( "db down" )
        with patch( "builtins.print" ) as mp:
            is_locked, unlock_time = rate_limiter.check_account_lockout( "u@e.com" )
        self.assertFalse( is_locked )
        self.assertIsNone( unlock_time )
        self.assertTrue( any( "Failed to check account lockout" in str( c ) for c in mp.call_args_list ) )


class TestClearFailedAttempts( _RateLimiterTestBase ):
    def test_clears( self ):
        rate_limiter.clear_failed_attempts( "u@e.com" )
        self.repo.delete_by_email.assert_called_once_with( "u@e.com" )

    def test_exception_swallowed( self ):
        self.repo.delete_by_email.side_effect = Exception( "db down" )
        with patch( "builtins.print" ) as mp:
            rate_limiter.clear_failed_attempts( "u@e.com" )
        self.assertTrue( any( "Failed to clear failed attempts" in str( c ) for c in mp.call_args_list ) )


class TestCleanupOldAttempts( _RateLimiterTestBase ):
    def test_hours_ge_one_day( self ):
        self.repo.cleanup_old.return_value = 7
        deleted = rate_limiter.cleanup_old_attempts( hours=48 )   # 2.0 days → int(2)
        self.assertEqual( deleted, 7 )
        self.repo.cleanup_old.assert_called_once_with( days_old=2 )

    def test_hours_under_one_day_floors_to_one( self ):
        self.repo.cleanup_old.return_value = 3
        deleted = rate_limiter.cleanup_old_attempts( hours=12 )   # 0.5 days → < 1 → 1
        self.assertEqual( deleted, 3 )
        self.repo.cleanup_old.assert_called_once_with( days_old=1 )

    def test_exception_returns_zero( self ):
        self.repo.cleanup_old.side_effect = Exception( "db down" )
        with patch( "builtins.print" ) as mp:
            deleted = rate_limiter.cleanup_old_attempts( hours=24 )
        self.assertEqual( deleted, 0 )
        self.assertTrue( any( "Failed to cleanup old attempts" in str( c ) for c in mp.call_args_list ) )


class TestGetFailedAttemptsCount( _RateLimiterTestBase ):
    def test_count( self ):
        self.repo.count_recent_by_email.return_value = 4
        self.assertEqual( rate_limiter.get_failed_attempts_count( "u@e.com", minutes=15 ), 4 )

    def test_exception_returns_zero( self ):
        self.repo.count_recent_by_email.side_effect = Exception( "db down" )
        with patch( "builtins.print" ) as mp:
            self.assertEqual( rate_limiter.get_failed_attempts_count( "u@e.com" ), 0 )
        self.assertTrue( any( "Failed to get failed attempts count" in str( c ) for c in mp.call_args_list ) )


def isolated_unit_test():
    """
    Run the rate_limiter unit tests in isolation.

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
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} rate_limiter tests in {secs:.3f}s — {msg}" )
