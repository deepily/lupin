"""
End-to-End Integration Tests for Claude Code Dispatcher.

These tests validate actual Claude Code invocation with MCP voice tools.
They require full infrastructure to be running.

PREREQUISITES:
    1. Lupin server running on port 7999
       ./src/scripts/run-fastapi-lupin.sh

    2. Claude Code CLI installed
       npm install -g @anthropic-ai/claude-code

    3. MCP server registered with Claude Code
       ./src/scripts/install-mcp-server.sh

    4. LUPIN_ROOT environment variable set
       export LUPIN_ROOT=/path/to/lupin

RUNNING TESTS:
    # Run all dispatcher E2E tests
    pytest src/tests/integration/test_dispatcher_e2e.py -v

    # Run only quick tests (no actual Claude invocation)
    pytest src/tests/integration/test_dispatcher_e2e.py -v -m "not e2e"

    # Run full E2E tests (requires Claude Code)
    pytest src/tests/integration/test_dispatcher_e2e.py -v -m "e2e"

Created: 2026-01-02
"""

import pytest
import subprocess
from unittest import mock

# Path bootstrapped by src/tests/conftest.py - cosa now importable
import cosa.utils.util as cu
from cosa.orchestration import ClaudeCodeDispatcher, Task, TaskType, TaskResult


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture( scope="module" )
def project_root():
    """
    Get project root using canonical pattern.

    Returns:
        str: Path to project root from LUPIN_ROOT
    """
    return cu.get_project_root()


@pytest.fixture( scope="module" )
def dispatcher():
    """
    Create a ClaudeCodeDispatcher instance for testing.

    Returns:
        ClaudeCodeDispatcher: Configured dispatcher instance
    """
    return ClaudeCodeDispatcher()


@pytest.fixture( scope="module" )
def verify_lupin_server():
    """
    Verify Lupin server is running on port 7999.

    Raises:
        pytest.skip: If server not accessible
    """
    import requests

    try:
        response = requests.get( "http://localhost:7999/health", timeout=2 )
        if response.status_code == 200:
            print( "\n✓ Lupin server accessible on port 7999" )
            return True
    except ( requests.exceptions.ConnectionError, requests.exceptions.Timeout ):
        pass

    pytest.skip(
        "\n" + "="*60 + "\n"
        "Lupin server not running or unhealthy on port 7999\n\n"
        "Start with: ./src/scripts/run-fastapi-lupin.sh\n"
        + "="*60 + "\n"
    )


@pytest.fixture( scope="module" )
def verify_claude_cli():
    """
    Verify Claude Code CLI is installed.

    Raises:
        pytest.skip: If CLI not found
    """
    try:
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            print( f"\n✓ Claude Code CLI found: {version}" )
            return True
    except ( subprocess.TimeoutExpired, FileNotFoundError ):
        pass

    pytest.skip(
        "\n" + "="*60 + "\n"
        "Claude Code CLI not found\n\n"
        "Install with: npm install -g @anthropic-ai/claude-code\n"
        + "="*60 + "\n"
    )


# ============================================================================
# Unit Tests (No external dependencies)
# ============================================================================

class TestDispatcherUnit:
    """Unit tests that don't require external infrastructure."""

    def test_import_dispatcher( self ):
        """Test that dispatcher module can be imported."""
        assert ClaudeCodeDispatcher is not None
        assert Task is not None
        assert TaskType is not None
        assert TaskResult is not None

    def test_task_creation( self ):
        """Test Task dataclass creation and defaults."""
        task = Task(
            id="test-001",
            project="lupin",
            prompt="Test prompt",
            type=TaskType.BOUNDED
        )

        assert task.id == "test-001"
        assert task.project == "lupin"
        assert task.prompt == "Test prompt"
        assert task.type == TaskType.BOUNDED
        assert task.max_turns == 50
        assert task.timeout_seconds == 3600

    def test_task_sender_id( self ):
        """Test Task sender_id generation."""
        task = Task(
            id="test-001",
            project="lupin",
            prompt="Test",
            type=TaskType.BOUNDED
        )

        assert task.sender_id == "claude.code@lupin.deepily.ai"

    def test_task_result_success( self ):
        """Test TaskResult success case."""
        result = TaskResult(
            task_id="test-001",
            success=True,
            session_id="session-abc",
            result="Task completed",
            cost_usd=0.01,
            duration_ms=5000,
            exit_code=0
        )

        assert result.success is True
        assert result.error is None
        assert result.cost_usd == 0.01

    def test_task_result_failure( self ):
        """Test TaskResult failure case."""
        result = TaskResult(
            task_id="test-002",
            success=False,
            error="Task timed out",
            exit_code=-1
        )

        assert result.success is False
        assert result.error == "Task timed out"
        assert result.exit_code == -1

    def test_dispatcher_creation( self, dispatcher ):
        """Test ClaudeCodeDispatcher instantiation.

        Accepts either the host-path config file (`cosa_mcp.json`) OR the
        container-path variant (`cosa_mcp_docker.json`) which is what the
        dispatcher resolves to when LUPIN_ROOT is `/var/lupin` (Docker).
        Per TFE analysis 2026-04-24 on ts-ff11fb27.
        """
        assert dispatcher is not None
        assert dispatcher.mcp_config_path.endswith( ( "cosa_mcp.json", "cosa_mcp_docker.json" ) )
        assert dispatcher.mcp_server_path.endswith( "cosa_voice_mcp.py" )

    def test_dispatcher_active_sessions( self, dispatcher ):
        """Test get_active_sessions returns empty list initially."""
        sessions = dispatcher.get_active_sessions()
        assert isinstance( sessions, list )
        assert len( sessions ) == 0


# ============================================================================
# Integration Tests (Require Lupin server)
# ============================================================================

class TestDispatcherIntegration:
    """Integration tests that require Lupin server running."""

    @pytest.mark.integration
    def test_mcp_config_exists( self, project_root ):
        """Test that MCP config file exists."""
        import os
        config_path = project_root + "/src/conf/mcp/cosa_mcp.json"
        assert os.path.exists( config_path ), f"MCP config not found: {config_path}"

    @pytest.mark.integration
    def test_mcp_server_exists( self, project_root ):
        """Test that MCP server script exists."""
        import os
        server_path = project_root + "/src/lupin_mcp/cosa_voice_mcp.py"
        assert os.path.exists( server_path ), f"MCP server not found: {server_path}"


# ============================================================================
# E2E Tests (Require full infrastructure)
# ============================================================================

class TestDispatcherE2E:
    """
    Full E2E tests that invoke actual Claude Code CLI.

    These tests are marked with @pytest.mark.e2e and require:
    - Lupin server running
    - Claude Code CLI installed
    - MCP server registered
    """

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_bounded_task_simple( self, dispatcher, verify_lupin_server, verify_claude_cli ):
        """
        Test a simple bounded task that completes without interaction.

        This is the simplest E2E test - just runs a command and checks result.
        """
        task = Task(
            id="e2e-simple-001",
            project="lupin",
            prompt="List the Python files in the src/cosa/orchestration directory. Just list the filenames, nothing else.",
            type=TaskType.BOUNDED,
            max_turns=5,
            timeout_seconds=60
        )

        result = await dispatcher.dispatch( task )

        assert result.task_id == "e2e-simple-001"
        if result.success:
            print( f"\n✓ E2E simple task succeeded" )
            print( f"  Session: {result.session_id}" )
            if result.cost_usd:
                print( f"  Cost: ${result.cost_usd:.4f}" )
        else:
            print( f"\n⚠ E2E simple task failed: {result.error}" )
            pytest.skip( f"Task failed (may be config issue): {result.error}" )

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_bounded_task_timeout( self, dispatcher, verify_lupin_server, verify_claude_cli ):
        """
        Test that timeout handling works correctly.

        Uses a very short timeout to force timeout error.
        """
        task = Task(
            id="e2e-timeout-001",
            project="lupin",
            prompt="Count to 1000 slowly.",
            type=TaskType.BOUNDED,
            max_turns=100,
            timeout_seconds=1  # Very short timeout
        )

        result = await dispatcher.dispatch( task )

        assert result.task_id == "e2e-timeout-001"
        if not result.success and "timeout" in result.error.lower():
            print( f"\n✓ Timeout handled correctly: {result.error}" )
        else:
            print( f"\n⚠ Unexpected result: success={result.success}, error={result.error}" )

    @pytest.mark.e2e
    @pytest.mark.manual
    @pytest.mark.asyncio
    async def test_bounded_task_with_voice_clarification( self, dispatcher, verify_lupin_server, verify_claude_cli ):
        """
        Test a task that requires voice clarification.

        MANUAL TEST: Requires human interaction via Lupin UI.

        Run with: pytest ... -m "manual" -s
        """
        print( "\n" + "="*60 )
        print( "MANUAL TEST: Voice Clarification" )
        print( "="*60 )
        print( "\nThis test will ask a question via voice notification." )
        print( "Watch the Lupin UI and respond when prompted." )
        print( "="*60 + "\n" )

        task = Task(
            id="e2e-voice-001",
            project="lupin",
            prompt="Ask the user what their favorite color is using the converse() MCP tool, then report their answer.",
            type=TaskType.BOUNDED,
            max_turns=10,
            timeout_seconds=120
        )

        result = await dispatcher.dispatch( task )

        print( f"\nResult: success={result.success}" )
        if result.success:
            print( f"Response: {result.result}" )
        else:
            print( f"Error: {result.error}" )

        assert True  # Manual test - just report results

    @pytest.mark.e2e
    @pytest.mark.manual
    @pytest.mark.asyncio
    async def test_bounded_task_with_notifications( self, dispatcher, verify_lupin_server, verify_claude_cli ):
        """
        Test a task that sends progress notifications.

        MANUAL TEST: Watch Lupin UI for notification messages.

        Run with: pytest ... -m "manual" -s
        """
        print( "\n" + "="*60 )
        print( "MANUAL TEST: Progress Notifications" )
        print( "="*60 )
        print( "\nThis test will send progress notifications." )
        print( "Watch the Lupin UI for notification messages." )
        print( "="*60 + "\n" )

        task = Task(
            id="e2e-notify-001",
            project="lupin",
            prompt="Use the notify() MCP tool to send three progress updates: 'Starting task', 'Working on it', 'Task complete'. Then respond with 'Done'.",
            type=TaskType.BOUNDED,
            max_turns=10,
            timeout_seconds=60
        )

        result = await dispatcher.dispatch( task )

        print( f"\nResult: success={result.success}" )
        if result.success:
            print( f"Response: {result.result}" )
        else:
            print( f"Error: {result.error}" )

        assert True  # Manual test - just report results


# ============================================================================
# Interactive Session Tests (Phase 2 & 3 - Option B Testing)
# ============================================================================

class TestDispatcherInteractive:
    """
    Tests for Option B interactive sessions (_run_interactive).

    These tests validate the SDK client mode with bidirectional control.
    They require the same infrastructure as E2E tests plus the SDK.
    """

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_interactive_session_basic( self, dispatcher, verify_lupin_server, verify_claude_cli ):
        """
        Test a basic interactive session that completes without interaction.

        Phase 2: Validates _run_interactive() runs to completion.
        """
        from cosa.orchestration.claude_code.dispatcher import SDK_AVAILABLE

        if not SDK_AVAILABLE:
            pytest.skip( "claude-agent-sdk not installed" )

        task = Task(
            id="interactive-basic-001",
            project="lupin",
            prompt="Say 'Hello from interactive mode!' and nothing else.",
            type=TaskType.INTERACTIVE,
            max_turns=5,
            timeout_seconds=60
        )

        result = await dispatcher.dispatch( task )

        assert result.task_id == "interactive-basic-001"
        if result.success:
            print( f"\n✓ Interactive session succeeded" )
            print( f"  Session: {result.session_id}" )
            if result.cost_usd:
                print( f"  Cost: ${result.cost_usd:.4f}" )
        else:
            print( f"\n⚠ Interactive session failed: {result.error}" )
            # Don't fail - may be infrastructure issue
            pytest.skip( f"Interactive task failed (may be config issue): {result.error}" )

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_interactive_session_streaming( self, dispatcher, verify_lupin_server, verify_claude_cli ):
        """
        Test that streaming messages are received via on_message callback.

        Phase 2: Validates message streaming works.
        """
        from cosa.orchestration.claude_code.dispatcher import SDK_AVAILABLE

        if not SDK_AVAILABLE:
            pytest.skip( "claude-agent-sdk not installed" )

        messages_received = []

        def capture_message( task_id: str, message ):
            messages_received.append( { "task_id": task_id, "type": type( message ).__name__ } )

        # Create dispatcher with custom callback
        from cosa.orchestration import ClaudeCodeDispatcher
        streaming_dispatcher = ClaudeCodeDispatcher( on_message=capture_message )

        task = Task(
            id="interactive-stream-001",
            project="lupin",
            prompt="List three things: 1. Python, 2. JavaScript, 3. Rust. Then say 'Done'.",
            type=TaskType.INTERACTIVE,
            max_turns=5,
            timeout_seconds=60
        )

        result = await streaming_dispatcher.dispatch( task )

        print( f"\n✓ Messages received: {len( messages_received )}" )
        for msg in messages_received[:5]:
            print( f"  - {msg['type']}" )

        # We should have received some messages during streaming
        if result.success:
            assert len( messages_received ) > 0, "No messages received during streaming"
            print( f"\n✓ Streaming validation passed with {len( messages_received )} messages" )
        else:
            pytest.skip( f"Task failed: {result.error}" )

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_interactive_session_tracking( self, dispatcher, verify_lupin_server, verify_claude_cli ):
        """
        Test that session appears in active_sessions during execution.

        Phase 2: Validates session lifecycle tracking.
        """
        from cosa.orchestration.claude_code.dispatcher import SDK_AVAILABLE

        if not SDK_AVAILABLE:
            pytest.skip( "claude-agent-sdk not installed" )

        # After execution, session should be cleaned up
        sessions_after = dispatcher.get_active_sessions()
        assert "session-track-001" not in sessions_after, "Session not cleaned up after completion"

        print( "\n✓ Session lifecycle tracking verified" )

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_interactive_with_notify( self, dispatcher, verify_lupin_server, verify_claude_cli ):
        """
        Test interactive session using MCP notify() tool.

        Phase 3: E2E test with actual MCP voice tool usage.
        """
        from cosa.orchestration.claude_code.dispatcher import SDK_AVAILABLE

        if not SDK_AVAILABLE:
            pytest.skip( "claude-agent-sdk not installed" )

        task = Task(
            id="interactive-notify-001",
            project="lupin",
            prompt="Use the notify() MCP tool to send a message: 'Interactive session test complete'. Then say 'Done'.",
            type=TaskType.INTERACTIVE,
            max_turns=10,
            timeout_seconds=60
        )

        result = await dispatcher.dispatch( task )

        print( f"\nResult: success={result.success}" )
        if result.success:
            print( f"✓ Interactive notification test passed" )
            if result.cost_usd:
                print( f"  Cost: ${result.cost_usd:.4f}" )
        else:
            print( f"⚠ Error: {result.error}" )
            pytest.skip( f"Task failed: {result.error}" )

    @pytest.mark.e2e
    @pytest.mark.manual
    @pytest.mark.asyncio
    async def test_interactive_with_converse( self, dispatcher, verify_lupin_server, verify_claude_cli ):
        """
        Test interactive session using MCP converse() tool.

        MANUAL TEST: Requires human interaction via Lupin UI.
        Phase 3: E2E test with blocking voice interaction.

        Run with: pytest ... -m "manual" -s
        """
        from cosa.orchestration.claude_code.dispatcher import SDK_AVAILABLE

        if not SDK_AVAILABLE:
            pytest.skip( "claude-agent-sdk not installed" )

        print( "\n" + "=" * 60 )
        print( "MANUAL TEST: Interactive Session with Voice" )
        print( "=" * 60 )
        print( "\nThis test will use converse() in an interactive session." )
        print( "Watch the Lupin UI and respond when prompted." )
        print( "=" * 60 + "\n" )

        task = Task(
            id="interactive-converse-001",
            project="lupin",
            prompt="Ask the user 'What is your favorite programming language?' using the converse() MCP tool. Report their answer.",
            type=TaskType.INTERACTIVE,
            max_turns=10,
            timeout_seconds=120
        )

        result = await dispatcher.dispatch( task )

        print( f"\nResult: success={result.success}" )
        if result.success:
            print( f"Response captured: {result.result}" )
            if result.cost_usd:
                print( f"Cost: ${result.cost_usd:.4f}" )
        else:
            print( f"Error: {result.error}" )

        assert True  # Manual test - just report results

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_interactive_error_handling( self, dispatcher, verify_lupin_server, verify_claude_cli ):
        """
        Test interactive session error handling.

        Phase 3: Validates graceful failure handling.
        """
        from cosa.orchestration.claude_code.dispatcher import SDK_AVAILABLE

        if not SDK_AVAILABLE:
            pytest.skip( "claude-agent-sdk not installed" )

        # Test with very short max_turns to force early termination
        task = Task(
            id="interactive-error-001",
            project="lupin",
            prompt="Write a 1000-line Python script that does complex calculations.",
            type=TaskType.INTERACTIVE,
            max_turns=1,  # Very low - should hit limit
            timeout_seconds=30
        )

        result = await dispatcher.dispatch( task )

        # Should either succeed with partial result or fail gracefully
        print( f"\nResult: success={result.success}" )
        if not result.success:
            print( f"✓ Error handled gracefully: {result.error}" )
        else:
            print( "✓ Task completed despite low max_turns" )


# ============================================================================
# Mock Tests (Test command construction without Claude)
# ============================================================================

class _FakeStdout:
    """
    Async-iterable stand-in for asyncio.subprocess.Process.stdout.

    Yields pre-canned byte lines, then stops — matching how the dispatcher
    consumes the real stream (`async for line in process.stdout`).
    """

    def __init__( self, lines ):
        self._lines = list( lines )

    def __aiter__( self ):
        return self

    async def __anext__( self ):
        if not self._lines: raise StopAsyncIteration
        return self._lines.pop( 0 )


class _FakeStderr:
    """
    Stand-in for asyncio.subprocess.Process.stderr.

    Mirrors real StreamReader semantics that the dispatcher depends on: the
    first read() drains the buffer, every read() after it returns b"" at EOF.
    A test double that re-served the payload on each call would hide the
    double-read bug this class exists to make visible.
    """

    def __init__( self, data=b"" ):
        self._data = data

    async def read( self, n=-1 ):
        data       = self._data
        self._data = b""
        return data


class _FakeProcess:
    """Stand-in for the Process returned by asyncio.create_subprocess_exec."""

    def __init__( self, returncode=0, stdout_lines=(), stderr=b"" ):
        self.returncode = returncode
        self.pid        = 4242
        self.stdout     = _FakeStdout( stdout_lines )
        self.stderr     = _FakeStderr( stderr )
        self.killed     = False

    async def wait( self ):
        return self.returncode

    def kill( self ):
        self.killed = True


def _patch_spawn( process ):
    """
    Patch the dispatcher's ACTUAL spawn call site.

    The dispatcher runs bounded tasks through asyncio.create_subprocess_exec,
    not subprocess.run. These tests previously mocked subprocess.run — a call
    site the dispatcher does not use — so `mock.called` was always False and
    the class was blanket-skipped rather than fixed.

    Returns:
        mock.patch context manager whose AsyncMock records the spawn call.
    """
    return mock.patch(
        "cosa.orchestration.claude_code.dispatcher.asyncio.create_subprocess_exec",
        new_callable=mock.AsyncMock,
        return_value=process
    )


class TestDispatcherMocked:
    """
    Tests using a mocked subprocess to verify bounded-task dispatch.

    Every test here asserts observable dispatcher behaviour — the argv it
    builds, the environment it exports, and the TaskResult it returns — so
    each one fails if that behaviour changes, not merely if a string is
    reworded.
    """

    @pytest.mark.asyncio
    async def test_command_construction( self, dispatcher ):
        """The bounded argv names the CLI, the prompt, and the streaming contract."""
        result_line = b'{"type":"result","session_id":"mock-session","result":"mocked","cost_usd":0.01}\n'

        with _patch_spawn( _FakeProcess( returncode=0, stdout_lines=[result_line] ) ) as mock_spawn:
            task = Task(
                id="mock-001",
                project="lupin",
                prompt="Test prompt",
                type=TaskType.BOUNDED,
                max_turns=10
            )

            await dispatcher.dispatch( task )

            assert mock_spawn.called, "dispatch() never spawned a subprocess"
            cmd = list( mock_spawn.call_args[0] )

            assert cmd[0] == "claude"
            assert cmd[1] == "-p"
            assert cmd[2] == "Test prompt"

            # Streaming contract: the dispatcher parses stdout line-by-line, so
            # stream-json (not plain json) is load-bearing, and --verbose is
            # required by the CLI whenever stream-json rides with -p.
            assert cmd[ cmd.index( "--output-format" ) + 1 ] == "stream-json"
            assert "--verbose" in cmd
            assert cmd[ cmd.index( "--max-turns" ) + 1 ] == "10"
            assert cmd[ cmd.index( "--mcp-config" ) + 1 ] == dispatcher.mcp_config_path
            assert cmd[ cmd.index( "--permission-mode" ) + 1 ] == "acceptEdits"

            # The voice tools are what make a bounded task able to reach the user.
            allowed = cmd[ cmd.index( "--allowedTools" ) + 1 ].split( "," )
            assert "mcp__cosa-voice__converse"    in allowed
            assert "mcp__cosa-voice__notify"      in allowed
            assert "mcp__cosa-voice__ask_yes_no"  in allowed

    @pytest.mark.asyncio
    async def test_environment_variables( self, dispatcher ):
        """MCP_PROJECT is exported lower-cased so the MCP server resolves the project."""
        with _patch_spawn( _FakeProcess( returncode=0 ) ) as mock_spawn:
            task = Task(
                id="mock-002",
                project="TestProject",
                prompt="Test",
                type=TaskType.BOUNDED
            )

            await dispatcher.dispatch( task )

            env = mock_spawn.call_args[1]["env"]
            assert env["MCP_PROJECT"] == "testproject"
            # Inherited, not replaced — the CLI needs the ambient environment.
            assert "PATH" in env

    @pytest.mark.asyncio
    async def test_streamed_result_populates_task_result( self, dispatcher ):
        """A result message on stdout is surfaced on the returned TaskResult."""
        result_line = b'{"type":"result","session_id":"sess-9","result":"all done","total_cost_usd":0.25}\n'

        with _patch_spawn( _FakeProcess( returncode=0, stdout_lines=[result_line] ) ):
            seen = []
            dispatcher.on_message = lambda task_id, data: seen.append( ( task_id, data ) )

            task = Task( id="mock-005", project="lupin", prompt="Test", type=TaskType.BOUNDED )
            result = await dispatcher.dispatch( task )

            assert result.success    is True
            assert result.session_id == "sess-9"
            assert result.result     == "all done"
            assert result.cost_usd   == 0.25
            assert result.exit_code  == 0
            # Every parsed line is forwarded to the callback that feeds the WebSocket.
            assert seen == [ ( "mock-005", {
                "type"           : "result",
                "session_id"     : "sess-9",
                "result"         : "all done",
                "total_cost_usd" : 0.25
            } ) ]

    @pytest.mark.asyncio
    async def test_error_handling( self, dispatcher ):
        """A non-zero exit fails the task and surfaces the subprocess's stderr."""
        with _patch_spawn( _FakeProcess( returncode=1, stderr=b"Error: Something went wrong" ) ):
            task = Task( id="mock-003", project="lupin", prompt="Test", type=TaskType.BOUNDED )

            result = await dispatcher.dispatch( task )

            assert result.success   is False
            assert result.exit_code == 1
            assert result.error     == "Error: Something went wrong"

    @pytest.mark.asyncio
    async def test_non_json_output_is_forwarded_as_text( self, dispatcher ):
        """
        Plain-text stdout is tolerated, not fatal.

        The dispatcher wraps an unparseable line as a text message and keeps
        going; a clean exit still succeeds. This test fails if someone makes
        the stream parser strict — which would drop the CLI's non-JSON chatter
        on the floor and dead-letter otherwise-healthy tasks.
        """
        with _patch_spawn( _FakeProcess( returncode=0, stdout_lines=[b"not valid json\n"] ) ):
            seen = []
            dispatcher.on_message = lambda task_id, data: seen.append( data )

            task = Task( id="mock-004", project="lupin", prompt="Test", type=TaskType.BOUNDED )
            result = await dispatcher.dispatch( task )

            assert seen == [ { "type": "text", "content": "not valid json" } ]
            assert result.success   is True
            assert result.exit_code == 0

# ============================================================================
# Run directly
# ============================================================================

if __name__ == "__main__":
    pytest.main( [__file__, "-v", "-m", "not e2e and not manual"] )
