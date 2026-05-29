#!/usr/bin/env python3
"""
Pytest Runner for COSA SWE Team Agent.

Orchestrator-level pytest validation helper. NOT an MCP tool — the
orchestrator calls this after the tester agent finishes to independently
confirm test results via subprocess execution.

Parses pytest summary output to produce a structured TestRunResult.
Never raises on errors — returns a failure result instead.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass

logger = logging.getLogger( __name__ )


@dataclass
class TestRunResult:
    """
    Structured result from a pytest execution.

    Requires:
        - output is a string (may be truncated)
        - counts are non-negative integers

    Ensures:
        - passed is True only when failed_count == 0 and error_count == 0 and passed_count > 0
        - output is truncated to max_output chars
    """

    passed        : bool
    total_tests   : int
    passed_count  : int
    failed_count  : int
    error_count   : int
    output        : str
    duration_secs : float
    timed_out     : bool


def _parse_pytest_summary( output: str ) -> dict:
    """
    Parse pytest summary line to extract test counts.

    Handles common pytest summary formats:
        - "5 passed"
        - "3 passed, 2 failed"
        - "1 passed, 1 failed, 1 error"
        - "no tests ran"

    Requires:
        - output is a string containing pytest output

    Ensures:
        - Returns dict with passed_count, failed_count, error_count keys
        - Returns zeros if summary line cannot be parsed

    Args:
        output: Raw pytest stdout/stderr output

    Returns:
        dict: Parsed test counts
    """
    result = {
        "passed_count" : 0,
        "failed_count" : 0,
        "error_count"  : 0,
    }

    # Match patterns like "5 passed", "3 failed", "1 error"
    passed_match = re.search( r"(\d+)\s+passed", output )
    failed_match = re.search( r"(\d+)\s+failed", output )
    error_match  = re.search( r"(\d+)\s+error", output )

    if passed_match:
        result[ "passed_count" ] = int( passed_match.group( 1 ) )
    if failed_match:
        result[ "failed_count" ] = int( failed_match.group( 1 ) )
    if error_match:
        result[ "error_count" ] = int( error_match.group( 1 ) )

    return result


async def run_pytest(
    test_path    : str,
    timeout_secs : int = 120,
    max_output   : int = 4000,
) -> TestRunResult:
    """
    Run pytest on the given path and return structured results.

    Uses asyncio.create_subprocess_exec with timeout to prevent
    runaway test execution. Parses pytest summary output for
    pass/fail counts.

    Requires:
        - test_path is a valid file or directory path
        - timeout_secs is a positive integer
        - max_output is a positive integer

    Ensures:
        - Never raises — returns failure TestRunResult on any error
        - Output is truncated to max_output characters
        - timed_out is True if execution exceeded timeout_secs
        - passed is True only when all tests pass and none fail/error

    Args:
        test_path: Path to test file or directory
        timeout_secs: Maximum execution time in seconds
        max_output: Maximum output characters to retain

    Returns:
        TestRunResult: Structured test execution result
    """
    start = time.time()

    try:
        proc = await asyncio.create_subprocess_exec(
            "python", "-m", "pytest", test_path, "-v", "--tb=short", "--no-header",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        try:
            stdout, _ = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_secs,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            elapsed = time.time() - start
            return TestRunResult(
                passed        = False,
                total_tests   = 0,
                passed_count  = 0,
                failed_count  = 0,
                error_count   = 0,
                output        = f"pytest timed out after {timeout_secs}s",
                duration_secs = elapsed,
                timed_out     = True,
            )

        elapsed = time.time() - start
        raw_output = stdout.decode( "utf-8", errors="replace" )

        # Truncate output
        output = raw_output[ :max_output ]
        if len( raw_output ) > max_output:
            output += f"\n... [truncated {len( raw_output ) - max_output} chars]"

        # Parse counts
        counts  = _parse_pytest_summary( raw_output )
        total   = counts[ "passed_count" ] + counts[ "failed_count" ] + counts[ "error_count" ]
        passed  = (
            counts[ "failed_count" ] == 0
            and counts[ "error_count" ] == 0
            and counts[ "passed_count" ] > 0
        )

        return TestRunResult(
            passed        = passed,
            total_tests   = total,
            passed_count  = counts[ "passed_count" ],
            failed_count  = counts[ "failed_count" ],
            error_count   = counts[ "error_count" ],
            output        = output,
            duration_secs = elapsed,
            timed_out     = False,
        )

    except Exception as e:
        elapsed = time.time() - start
        logger.error( f"run_pytest failed for '{test_path}': {e}" )
        return TestRunResult(
            passed        = False,
            total_tests   = 0,
            passed_count  = 0,
            failed_count  = 0,
            error_count   = 1,
            output        = f"run_pytest error: {e}",
            duration_secs = elapsed,
            timed_out     = False,
        )


def quick_smoke_test():
    """Quick smoke test for test_runner module."""
    import cosa.utils.util as cu

    cu.print_banner( "SWE Team Test Runner Smoke Test", prepend_nl=True )

    try:
        # Test 1: TestRunResult creation
        print( "Testing TestRunResult creation..." )
        result = TestRunResult(
            passed        = True,
            total_tests   = 5,
            passed_count  = 5,
            failed_count  = 0,
            error_count   = 0,
            output        = "5 passed",
            duration_secs = 1.2,
            timed_out     = False,
        )
        assert result.passed is True
        assert result.total_tests == 5
        assert result.timed_out is False
        print( "✓ TestRunResult created" )

        # Test 2: _parse_pytest_summary with passed
        print( "Testing _parse_pytest_summary (passed)..." )
        counts = _parse_pytest_summary( "====== 5 passed in 0.3s ======" )
        assert counts[ "passed_count" ] == 5
        assert counts[ "failed_count" ] == 0
        assert counts[ "error_count" ] == 0
        print( "✓ Parsed '5 passed' correctly" )

        # Test 3: _parse_pytest_summary with failures
        print( "Testing _parse_pytest_summary (mixed)..." )
        counts = _parse_pytest_summary( "3 passed, 2 failed, 1 error in 1.5s" )
        assert counts[ "passed_count" ] == 3
        assert counts[ "failed_count" ] == 2
        assert counts[ "error_count" ] == 1
        print( "✓ Parsed mixed results correctly" )

        # Test 4: _parse_pytest_summary with no results
        print( "Testing _parse_pytest_summary (no results)..." )
        counts = _parse_pytest_summary( "no tests ran" )
        assert counts[ "passed_count" ] == 0
        assert counts[ "failed_count" ] == 0
        print( "✓ No results parsed as zeros" )

        print( "\n✓ Test Runner smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
