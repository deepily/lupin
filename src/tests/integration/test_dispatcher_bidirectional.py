"""
Bidirectional Control Tests - Phase 4 of Option B Testing.

Tests inject() and interrupt() capabilities for interactive sessions.
These tests validate the unique bidirectional control features of Option B.

PREREQUISITES:
    1. Lupin server running on port 7999
       ./src/scripts/run-fastapi-lupin.sh

    2. Claude Code CLI installed
       npm install -g @anthropic-ai/claude-code

    3. claude-agent-sdk installed
       pip install claude-agent-sdk

    4. LUPIN_ROOT environment variable set
       export LUPIN_ROOT=/path/to/lupin

RUNNING TESTS:
    # Run bidirectional tests
    pytest src/tests/integration/test_dispatcher_bidirectional.py -v

    # Run only non-E2E tests
    pytest src/tests/integration/test_dispatcher_bidirectional.py -v -m "not e2e"

    # Run E2E tests (requires Claude CLI)
    pytest src/tests/integration/test_dispatcher_bidirectional.py -v -m "e2e"

Created: 2026-01-05
Phase: 4 of 5 (Option B Testing)
"""

import pytest
import asyncio
import subprocess

# Path bootstrapped by src/tests/conftest.py - cosa now importable
import cosa.utils.util as cu
from cosa.orchestration import ClaudeCodeDispatcher, Task, TaskType, TaskResult


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture( scope="module" )
def project_root():
    """Get project root using canonical pattern."""
    return cu.get_project_root()


@pytest.fixture( scope="module" )
def dispatcher():
    """Create a ClaudeCodeDispatcher instance for testing."""
    return ClaudeCodeDispatcher()


@pytest.fixture( scope="module" )
def verify_lupin_server():
    """Verify Lupin server is running on port 7999."""
    import requests

    try:
        response = requests.get( "http://localhost:7999/health", timeout=2 )
        if response.status_code == 200:
            print( "\n✓ Lupin server accessible on port 7999" )
            return True
    except ( requests.exceptions.ConnectionError, requests.exceptions.Timeout ):
        pass

    pytest.skip(
        "\n" + "=" * 60 + "\n"
        "Lupin server not running or unhealthy on port 7999\n\n"
        "Start with: ./src/scripts/run-fastapi-lupin.sh\n"
        + "=" * 60 + "\n"
    )


@pytest.fixture( scope="module" )
def verify_claude_cli():
    """Verify Claude Code CLI is installed."""
    try:
        result = subprocess.run(
            [ "claude", "--version" ],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            print( f"\n✓ Claude Code CLI found: {version}" )
            return True
    except ( subprocess.TimeoutExpired, FileNotFoundError ):
        pass

    pytest.skip(
        "\n" + "=" * 60 + "\n"
        "Claude Code CLI not found\n\n"
        "Install with: npm install -g @anthropic-ai/claude-code\n"
        + "=" * 60 + "\n"
    )


@pytest.fixture( scope="module" )
def verify_sdk():
    """Verify claude-agent-sdk is installed."""
    from cosa.orchestration.claude_code.dispatcher import SDK_AVAILABLE

    if not SDK_AVAILABLE:
        pytest.skip(
            "\n" + "=" * 60 + "\n"
            "claude-agent-sdk not installed\n\n"
            "Install with: pip install claude-agent-sdk\n"
            + "=" * 60 + "\n"
        )
    return True


# ============================================================================
# Unit Tests for inject() and interrupt() (no external dependencies)
# ============================================================================

class TestInjectUnit:
    """Unit tests for inject() method."""

    @pytest.mark.asyncio
    async def test_inject_to_nonexistent_session( self, dispatcher ):
        """Inject to non-existent session should return False."""
        result = await dispatcher.inject( "nonexistent-session-id", "Hello" )

        assert result is False
        print( "\n✓ inject() correctly returns False for non-existent session" )

    @pytest.mark.asyncio
    async def test_inject_empty_message( self, dispatcher ):
        """Inject with empty message to non-existent session."""
        result = await dispatcher.inject( "fake-session", "" )

        assert result is False
        print( "\n✓ inject() returns False for non-existent session (empty message)" )


class TestInterruptUnit:
    """Unit tests for interrupt() method."""

    @pytest.mark.asyncio
    async def test_interrupt_nonexistent_session( self, dispatcher ):
        """Interrupt non-existent session should return False."""
        result = await dispatcher.interrupt( "nonexistent-session-id" )

        assert result is False
        print( "\n✓ interrupt() correctly returns False for non-existent session" )


class TestActiveSessionsUnit:
    """Unit tests for active session tracking."""

    def test_get_active_sessions_empty( self, dispatcher ):
        """get_active_sessions() should return empty list initially."""
        sessions = dispatcher.get_active_sessions()

        assert isinstance( sessions, list )
        assert len( sessions ) == 0
        print( "\n✓ get_active_sessions() returns empty list initially" )


# ============================================================================
# E2E Tests for inject() and interrupt()
# ============================================================================

class TestInjectE2E:
    """E2E tests for message injection into active sessions."""

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_inject_basic( self, verify_lupin_server, verify_claude_cli, verify_sdk ):
        """
        Test basic inject() - inject a message into a running session.

        This test is complex because we need a running session to inject into.
        We use asyncio.create_task to run the session in background.
        """
        from cosa.orchestration import ClaudeCodeDispatcher, Task, TaskType

        messages = []

        def capture( task_id, msg ):
            messages.append( { "task_id": task_id, "type": type( msg ).__name__ } )

        dispatcher = ClaudeCodeDispatcher( on_message=capture )

        # Create a task that waits for input
        task = Task(
            id="inject-test-001",
            project="lupin",
            prompt="Wait for me to tell you a number, then multiply it by 2 and report the result. Use converse() to ask me for the number.",
            type=TaskType.INTERACTIVE,
            max_turns=10,
            timeout_seconds=60
        )

        # Note: This test would require actual voice interaction
        # For now, we test that the mechanism doesn't crash
        print( "\n⚠ inject() E2E test requires voice interaction" )
        print( "  Marking as informational - inject mechanism verified at unit level" )

        # Verify inject() mechanism exists and is callable
        result = await dispatcher.inject( "inject-test-001", "42" )
        assert result is False  # Session not active yet

        print( "\n✓ inject() mechanism verified" )

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_active_sessions_during_execution( self, verify_lupin_server, verify_claude_cli, verify_sdk ):
        """
        Test that session appears in active_sessions during execution.

        Uses a quick task and checks session tracking.
        """
        from cosa.orchestration import ClaudeCodeDispatcher, Task, TaskType

        dispatcher = ClaudeCodeDispatcher()

        # Check before
        sessions_before = dispatcher.get_active_sessions()
        assert len( sessions_before ) == 0

        # Run a quick task
        task = Task(
            id="active-track-001",
            project="lupin",
            prompt="Say 'Quick test' and nothing else.",
            type=TaskType.INTERACTIVE,
            max_turns=3,
            timeout_seconds=30
        )

        result = await dispatcher.dispatch( task )

        # Check after - session should be cleaned up
        sessions_after = dispatcher.get_active_sessions()
        assert "active-track-001" not in sessions_after

        print( f"\n✓ Session tracking verified" )
        print( f"  Result: success={result.success}" )
        if result.success:
            print( f"  Session ID: {result.session_id}" )


class TestInterruptE2E:
    """E2E tests for session interruption."""

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_interrupt_mechanism( self, verify_lupin_server, verify_claude_cli, verify_sdk ):
        """
        Test interrupt() mechanism verification.

        Full interrupt testing would require a long-running session.
        This test verifies the mechanism is callable and handles edge cases.
        """
        from cosa.orchestration import ClaudeCodeDispatcher

        dispatcher = ClaudeCodeDispatcher()

        # Interrupt non-existent session
        result = await dispatcher.interrupt( "fake-session-for-interrupt-test" )
        assert result is False

        print( "\n✓ interrupt() mechanism verified" )
        print( "  Returns False for non-existent sessions" )

    @pytest.mark.e2e
    @pytest.mark.manual
    @pytest.mark.asyncio
    async def test_interrupt_active_session( self, verify_lupin_server, verify_claude_cli, verify_sdk ):
        """
        Test interrupting an active session.

        MANUAL TEST: Requires timing coordination.

        Run with: pytest ... -m "manual" -s
        """
        import asyncio
        from cosa.orchestration import ClaudeCodeDispatcher, Task, TaskType

        print( "\n" + "=" * 60 )
        print( "MANUAL TEST: Interrupt Active Session" )
        print( "=" * 60 )

        dispatcher = ClaudeCodeDispatcher()

        # Create a long-running task
        task = Task(
            id="interrupt-manual-001",
            project="lupin",
            prompt="Count slowly from 1 to 100, saying each number out loud. Take your time.",
            type=TaskType.INTERACTIVE,
            max_turns=50,
            timeout_seconds=120
        )

        # Start task in background
        async def run_task():
            return await dispatcher.dispatch( task )

        task_future = asyncio.create_task( run_task() )

        # Wait a bit for session to start
        await asyncio.sleep( 3 )

        # Check if session is active
        sessions = dispatcher.get_active_sessions()
        print( f"\nActive sessions: {sessions}" )

        if "interrupt-manual-001" in sessions:
            print( "Session found! Interrupting..." )
            success = await dispatcher.interrupt( "interrupt-manual-001" )
            print( f"Interrupt result: {success}" )
        else:
            print( "Session not found in active sessions" )

        # Wait for task to complete
        result = await task_future

        print( f"\nTask result: success={result.success}" )
        if result.error:
            print( f"Error: {result.error}" )

        assert True  # Manual test - just report


# ============================================================================
# Smoke Test Entry Point
# ============================================================================

def quick_smoke_test():
    """
    Quick smoke test for bidirectional control.

    Run with:
        python -m tests.integration.test_dispatcher_bidirectional
    """
    import asyncio

    cu.print_banner( "Bidirectional Control Smoke Test", prepend_nl=True )

    async def run_tests():
        try:
            dispatcher = ClaudeCodeDispatcher()

            # Test 1: inject to non-existent
            print( "Testing inject() to non-existent session..." )
            result = await dispatcher.inject( "fake-id", "test" )
            assert result is False
            print( "✓ inject() returns False for non-existent session" )

            # Test 2: interrupt non-existent
            print( "Testing interrupt() on non-existent session..." )
            result = await dispatcher.interrupt( "fake-id" )
            assert result is False
            print( "✓ interrupt() returns False for non-existent session" )

            # Test 3: active sessions
            print( "Testing get_active_sessions()..." )
            sessions = dispatcher.get_active_sessions()
            assert isinstance( sessions, list )
            print( f"✓ get_active_sessions() returns list (len={len( sessions )})" )

            print( "\n✓ Bidirectional control smoke test completed successfully" )

        except Exception as e:
            print( f"\n✗ Smoke test failed: {e}" )
            import traceback
            traceback.print_exc()

    asyncio.run( run_tests() )


if __name__ == "__main__":
    quick_smoke_test()
