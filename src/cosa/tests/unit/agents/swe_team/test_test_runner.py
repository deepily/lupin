"""
Unit tests for swe_team/test_runner.py — orchestrator-level pytest helper:
  - _parse_pytest_summary : regex extraction of passed/failed/error counts
  - run_pytest            : async subprocess wrapper (success / timeout / exception)

asyncio.create_subprocess_exec is fully boundary-mocked — NO real pytest subprocess
is ever spawned (zero spend, zero fs/process side effects).

Created 2026-05-31 by Extra 1 🪨 (CoSA coverage campaign, swe_team lane, mid tier).
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import cosa.agents.swe_team.test_runner as tr


def _run( coro ):
    return asyncio.run( coro )


class TestParsePytestSummary( unittest.TestCase ):

    def test_passed_only( self ):
        c = tr._parse_pytest_summary( "===== 5 passed in 0.3s =====" )
        self.assertEqual( c, { "passed_count": 5, "failed_count": 0, "error_count": 0 } )

    def test_mixed_counts( self ):
        c = tr._parse_pytest_summary( "3 passed, 2 failed, 1 error in 1.5s" )
        self.assertEqual( c[ "passed_count" ], 3 )
        self.assertEqual( c[ "failed_count" ], 2 )
        self.assertEqual( c[ "error_count" ], 1 )

    def test_no_results_all_zero( self ):
        c = tr._parse_pytest_summary( "no tests ran" )
        self.assertEqual( c, { "passed_count": 0, "failed_count": 0, "error_count": 0 } )


def _fake_proc( stdout_bytes ):
    """A stand-in for the asyncio subprocess with an awaitable communicate()."""
    proc = MagicMock()
    proc.communicate = AsyncMock( return_value=( stdout_bytes, None ) )
    proc.wait        = AsyncMock( return_value=0 )
    proc.kill        = MagicMock()
    return proc


class TestRunPytest( unittest.TestCase ):

    def test_success_all_passed( self ):
        proc = _fake_proc( b"===== 4 passed in 0.2s =====" )
        with patch.object( tr.asyncio, "create_subprocess_exec", AsyncMock( return_value=proc ) ):
            result = _run( tr.run_pytest( "tests/", timeout_secs=30 ) )
        self.assertTrue( result.passed )
        self.assertEqual( result.passed_count, 4 )
        self.assertEqual( result.total_tests, 4 )
        self.assertFalse( result.timed_out )

    def test_failure_when_tests_fail( self ):
        proc = _fake_proc( b"2 passed, 1 failed in 0.5s" )
        with patch.object( tr.asyncio, "create_subprocess_exec", AsyncMock( return_value=proc ) ):
            result = _run( tr.run_pytest( "tests/" ) )
        self.assertFalse( result.passed )           # failed_count > 0
        self.assertEqual( result.failed_count, 1 )
        self.assertEqual( result.total_tests, 3 )

    def test_failure_when_zero_passed( self ):
        proc = _fake_proc( b"no tests ran" )
        with patch.object( tr.asyncio, "create_subprocess_exec", AsyncMock( return_value=proc ) ):
            result = _run( tr.run_pytest( "tests/" ) )
        self.assertFalse( result.passed )           # passed_count == 0 → not passed
        self.assertEqual( result.total_tests, 0 )

    def test_output_truncation( self ):
        big = b"x" * 5000 + b"\n10 passed"
        proc = _fake_proc( big )
        with patch.object( tr.asyncio, "create_subprocess_exec", AsyncMock( return_value=proc ) ):
            result = _run( tr.run_pytest( "tests/", max_output=100 ) )
        self.assertIn( "truncated", result.output )
        self.assertTrue( result.passed )

    def test_no_truncation_when_short( self ):
        proc = _fake_proc( b"1 passed" )
        with patch.object( tr.asyncio, "create_subprocess_exec", AsyncMock( return_value=proc ) ):
            result = _run( tr.run_pytest( "tests/", max_output=4000 ) )
        self.assertNotIn( "truncated", result.output )

    def test_timeout_kills_proc_and_flags_timed_out( self ):
        proc = _fake_proc( b"" )
        proc.communicate = AsyncMock( side_effect=asyncio.TimeoutError() )
        with patch.object( tr.asyncio, "create_subprocess_exec", AsyncMock( return_value=proc ) ):
            result = _run( tr.run_pytest( "tests/", timeout_secs=1 ) )
        self.assertTrue( result.timed_out )
        self.assertFalse( result.passed )
        proc.kill.assert_called_once()
        proc.wait.assert_awaited_once()
        self.assertIn( "timed out", result.output )

    def test_exception_returns_failure_result( self ):
        with patch.object( tr.asyncio, "create_subprocess_exec",
                           AsyncMock( side_effect=OSError( "no python" ) ) ):
            result = _run( tr.run_pytest( "tests/" ) )
        self.assertFalse( result.passed )
        self.assertEqual( result.error_count, 1 )
        self.assertIn( "run_pytest error", result.output )


class TestTestRunResultDataclass( unittest.TestCase ):

    def test_construction( self ):
        r = tr.TestRunResult(
            passed=True, total_tests=1, passed_count=1, failed_count=0,
            error_count=0, output="ok", duration_secs=0.1, timed_out=False,
        )
        self.assertTrue( r.passed )
        self.assertEqual( r.total_tests, 1 )


if __name__ == "__main__":
    unittest.main()
