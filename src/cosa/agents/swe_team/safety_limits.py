#!/usr/bin/env python3
"""
Safety Limits for COSA SWE Team Agent.

Defines hard limits, dangerous command patterns, and guard functions
to prevent runaway execution and unauthorized operations.

Source: Architecture design doc Section 7.2
"""

import time
import logging
from typing import Optional

logger = logging.getLogger( __name__ )


# =============================================================================
# Hard Safety Limits
# =============================================================================

SAFETY_LIMITS = {
    "max_iterations_per_task"   : 10,
    "max_tokens_per_session"    : 500_000,
    "wall_clock_timeout_secs"   : 1800,
    "max_consecutive_failures"  : 3,
    "max_file_changes_per_task" : 20,
    "require_test_pass"         : True,
}


# =============================================================================
# Dangerous Command Patterns
# =============================================================================

DANGEROUS_COMMANDS = frozenset( {
    "rm ",
    "rm -rf",
    "git push",
    "git push --force",
    "git reset --hard",
    "docker rm",
    "docker rmi",
    "DROP TABLE",
    "DELETE FROM",
    "TRUNCATE",
    "kill -9",
    "pkill",
    "shutdown",
    "reboot",
    "chmod 777",
    "chown",
} )


def is_dangerous_command( command: str ) -> bool:
    """
    Check if a command matches any dangerous command pattern.

    Requires:
        - command is a string

    Ensures:
        - Returns True if command contains any dangerous pattern
        - Returns False otherwise
        - Case-insensitive matching for SQL commands

    Args:
        command: The shell command to check

    Returns:
        bool: True if command is potentially dangerous
    """
    if not command:
        return False

    cmd_lower = command.lower()
    for pattern in DANGEROUS_COMMANDS:
        if pattern.lower() in cmd_lower:
            return True

    return False


# =============================================================================
# Guard Functions
# =============================================================================

class SafetyGuard:
    """
    Runtime safety guard that tracks and enforces execution limits.

    Requires:
        - max_iterations, max_failures are positive integers
        - timeout_secs is a positive integer

    Ensures:
        - check_iteration() raises when iteration limit exceeded
        - check_timeout() raises when wall-clock limit exceeded
        - record_failure() tracks consecutive failures and raises at threshold
        - record_success() resets failure counter
    """

    def __init__(
        self,
        max_iterations : int = SAFETY_LIMITS[ "max_iterations_per_task" ],
        max_failures   : int = SAFETY_LIMITS[ "max_consecutive_failures" ],
        timeout_secs   : int = SAFETY_LIMITS[ "wall_clock_timeout_secs" ],
    ):
        self.max_iterations      = max_iterations
        self.max_failures        = max_failures
        self.timeout_secs        = timeout_secs

        self.iteration_count     = 0
        self.failure_count       = 0
        self.start_time          = time.time()
        self.file_changes        = 0

    def check_iteration( self ) -> None:
        """
        Increment and check iteration count.

        Raises:
            SafetyLimitError: If max iterations exceeded
        """
        self.iteration_count += 1
        if self.iteration_count > self.max_iterations:
            raise SafetyLimitError(
                f"Max iterations exceeded: {self.iteration_count}/{self.max_iterations}"
            )

    def check_timeout( self ) -> None:
        """
        Check wall-clock timeout.

        Raises:
            SafetyLimitError: If timeout exceeded
        """
        elapsed = time.time() - self.start_time
        if elapsed > self.timeout_secs:
            raise SafetyLimitError(
                f"Wall-clock timeout exceeded: {elapsed:.0f}s/{self.timeout_secs}s"
            )

    def record_failure( self, reason: str = "" ) -> None:
        """
        Record a consecutive failure.

        Requires:
            - reason is a string describing the failure

        Raises:
            SafetyLimitError: If max consecutive failures reached
        """
        self.failure_count += 1
        logger.warning(
            f"Failure #{self.failure_count}/{self.max_failures}: {reason}"
        )
        if self.failure_count >= self.max_failures:
            raise SafetyLimitError(
                f"Max consecutive failures reached: {self.failure_count}/{self.max_failures}. "
                f"Last failure: {reason}"
            )

    def record_success( self ) -> None:
        """Reset consecutive failure counter on success."""
        self.failure_count = 0

    def record_file_change( self, max_changes: int = SAFETY_LIMITS[ "max_file_changes_per_task" ] ) -> None:
        """
        Record a file change and check limit.

        Raises:
            SafetyLimitError: If max file changes exceeded
        """
        self.file_changes += 1
        if self.file_changes > max_changes:
            raise SafetyLimitError(
                f"Max file changes exceeded: {self.file_changes}/{max_changes}"
            )

    def get_status( self ) -> dict:
        """
        Get current guard status.

        Returns:
            dict: Current iteration, failure, timeout, and file change status
        """
        elapsed = time.time() - self.start_time
        return {
            "iterations"       : f"{self.iteration_count}/{self.max_iterations}",
            "failures"         : f"{self.failure_count}/{self.max_failures}",
            "elapsed_secs"     : f"{elapsed:.0f}/{self.timeout_secs}",
            "file_changes"     : f"{self.file_changes}/{SAFETY_LIMITS[ 'max_file_changes_per_task' ]}",
            "within_limits"    : (
                self.iteration_count <= self.max_iterations
                and self.failure_count < self.max_failures
                and elapsed <= self.timeout_secs
            ),
        }


class SafetyLimitError( Exception ):
    """Raised when a safety limit is exceeded."""
    pass


def quick_smoke_test():
    """Quick smoke test for safety_limits module."""
    import cosa.utils.util as cu

    cu.print_banner( "SWE Team Safety Limits Smoke Test", prepend_nl=True )

    try:
        # Test 1: SAFETY_LIMITS dict
        print( "Testing SAFETY_LIMITS dict..." )
        assert SAFETY_LIMITS[ "max_iterations_per_task" ] == 10
        assert SAFETY_LIMITS[ "max_tokens_per_session" ] == 500_000
        assert SAFETY_LIMITS[ "wall_clock_timeout_secs" ] == 1800
        assert SAFETY_LIMITS[ "max_consecutive_failures" ] == 3
        assert SAFETY_LIMITS[ "max_file_changes_per_task" ] == 20
        assert SAFETY_LIMITS[ "require_test_pass" ] is True
        print( "✓ SAFETY_LIMITS has correct values" )

        # Test 2: Dangerous command detection
        print( "Testing dangerous command detection..." )
        assert is_dangerous_command( "rm -rf /tmp/foo" ) is True
        assert is_dangerous_command( "git push --force origin main" ) is True
        assert is_dangerous_command( "DROP TABLE users" ) is True
        assert is_dangerous_command( "DELETE FROM sessions" ) is True
        assert is_dangerous_command( "ls -la" ) is False
        assert is_dangerous_command( "git status" ) is False
        assert is_dangerous_command( "pytest src/tests/" ) is False
        assert is_dangerous_command( "" ) is False
        print( "✓ Dangerous command detection works" )

        # Test 3: SafetyGuard iteration limit
        print( "Testing SafetyGuard iteration limit..." )
        guard = SafetyGuard( max_iterations=3 )
        guard.check_iteration()  # 1
        guard.check_iteration()  # 2
        guard.check_iteration()  # 3
        try:
            guard.check_iteration()  # 4 — should raise
            assert False, "Should have raised SafetyLimitError"
        except SafetyLimitError:
            pass
        print( "✓ Iteration limit enforced" )

        # Test 4: SafetyGuard failure tracking
        print( "Testing SafetyGuard failure tracking..." )
        guard = SafetyGuard( max_failures=2 )
        guard.record_failure( "test error 1" )
        try:
            guard.record_failure( "test error 2" )  # Should raise at 2
            assert False, "Should have raised SafetyLimitError"
        except SafetyLimitError:
            pass
        print( "✓ Failure limit enforced" )

        # Test 5: SafetyGuard success resets failures
        print( "Testing failure reset on success..." )
        guard = SafetyGuard( max_failures=3 )
        guard.record_failure( "fail 1" )
        guard.record_success()
        assert guard.failure_count == 0
        print( "✓ Success resets failure counter" )

        # Test 6: SafetyGuard file change limit
        print( "Testing file change limit..." )
        guard = SafetyGuard()
        for _ in range( 20 ):
            guard.record_file_change()
        try:
            guard.record_file_change()  # 21 — should raise
            assert False, "Should have raised SafetyLimitError"
        except SafetyLimitError:
            pass
        print( "✓ File change limit enforced" )

        # Test 7: get_status
        print( "Testing get_status..." )
        guard = SafetyGuard( max_iterations=10, max_failures=3, timeout_secs=1800 )
        guard.check_iteration()
        status = guard.get_status()
        assert "iterations" in status
        assert "failures" in status
        assert "within_limits" in status
        assert status[ "within_limits" ] is True
        print( "✓ get_status returns valid dict" )

        print( "\n✓ Safety Limits smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
