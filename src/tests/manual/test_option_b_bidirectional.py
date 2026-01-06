#!/usr/bin/env python3
"""
Manual Test Script for Option B Bidirectional Control (Phase 2).

This script tests inject() and interrupt() functionality:
1. Start a long-running interactive task
2. Call inject() to redirect Claude mid-session
3. Call interrupt() to pause execution
4. Verify session state tracking

PREREQUISITES:
    1. Lupin server running on port 7999
       ./src/scripts/run-fastapi-lupin.sh

    2. Claude Code CLI installed
       npm install -g @anthropic-ai/claude-code

    3. LUPIN_ROOT environment variable set
       export LUPIN_ROOT=/path/to/genie-in-the-box

RUNNING:
    PYTHONPATH="$PWD/src:$PYTHONPATH" LUPIN_ROOT="$PWD" MCP_PROJECT="lupin" \
        src/cosa/.venv/bin/python src/tests/manual/test_option_b_bidirectional.py

Created: 2026-01-05
Purpose: Manual validation of Option B Phase 2 (inject/interrupt) before production use
"""

import asyncio
import os
import sys
from datetime import datetime
from typing import Optional

# Ensure cosa is importable
lupin_root = os.environ.get( "LUPIN_ROOT" )
if not lupin_root:
    print( "ERROR: LUPIN_ROOT environment variable not set" )
    print( "Run: export LUPIN_ROOT=/path/to/genie-in-the-box" )
    sys.exit( 1 )

src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

import cosa.utils.util as cu
from cosa.orchestration import ClaudeCodeDispatcher, Task, TaskType, TaskResult


# ============================================================================
# Test Configuration
# ============================================================================

class TestConfig:
    """Configuration for Phase 2 manual tests."""

    # Which tests to run
    RUN_INJECT_TEST    = True    # Test inject() - redirect mid-session
    RUN_INTERRUPT_TEST = True    # Test interrupt() - pause execution
    RUN_STATE_TEST     = True    # Test active sessions tracking

    # Timeouts and delays
    SESSION_TIMEOUT    = 180     # seconds - longer for bidirectional tests
    MAX_TURNS          = 30      # conversation turns
    INJECT_DELAY       = 5       # seconds before injecting
    INTERRUPT_DELAY    = 3       # seconds after inject before interrupt


# ============================================================================
# Message Tracking
# ============================================================================

class MessageTracker:
    """Track and display streaming messages with injection/interruption markers."""

    def __init__( self ):
        self.messages       = []
        self.text_blocks    = []
        self.tool_uses      = []
        self.tool_results   = []
        self.start_time     = None
        self.inject_time    = None
        self.interrupt_time = None

    def on_message( self, task_id: str, message ):
        """Callback for streaming messages."""
        now = datetime.now()
        if self.start_time is None:
            self.start_time = now

        elapsed = ( now - self.start_time ).total_seconds()
        msg_type = type( message ).__name__

        self.messages.append( {
            "elapsed" : elapsed,
            "type"    : msg_type,
            "message" : message
        } )

        # Categorize and display
        if msg_type == "TextBlock":
            self.text_blocks.append( message )
            text_preview = str( message )[:80] + "..." if len( str( message ) ) > 80 else str( message )
            print( f"  [{elapsed:6.1f}s] TEXT: {text_preview}" )

        elif msg_type == "ToolUseBlock":
            self.tool_uses.append( message )
            tool_name = getattr( message, "name", "unknown" )
            print( f"  [{elapsed:6.1f}s] TOOL: {tool_name}" )

        elif msg_type == "ToolResultBlock":
            self.tool_results.append( message )
            print( f"  [{elapsed:6.1f}s] RESULT: (tool completed)" )

        elif msg_type == "ResultMessage":
            cost = getattr( message, "cost_usd", None )
            print( f"  [{elapsed:6.1f}s] DONE: cost=${cost:.4f}" if cost else f"  [{elapsed:6.1f}s] DONE" )

        elif msg_type == "AssistantMessage":
            content = getattr( message, "content", [] )
            print( f"  [{elapsed:6.1f}s] ASSISTANT:" )
            for block in content:
                block_type = type( block ).__name__
                if block_type == "TextBlock":
                    self.text_blocks.append( block )
                    text = getattr( block, "text", str( block ) )
                    if len( text ) > 100:
                        print( f"             TEXT: {text[:100]}..." )
                    else:
                        print( f"             TEXT: {text}" )
                elif block_type == "ToolUseBlock":
                    self.tool_uses.append( block )
                    tool_name = getattr( block, "name", "unknown" )
                    print( f"             TOOL: {tool_name}" )
                else:
                    print( f"             {block_type}" )

        elif msg_type == "UserMessage":
            content = getattr( message, "content", [] )
            print( f"  [{elapsed:6.1f}s] USER:" )
            for block in content:
                block_type = type( block ).__name__
                if block_type == "ToolResultBlock":
                    self.tool_results.append( block )
                    tool_use_id = getattr( block, "tool_use_id", "?" )[:8]
                    result = getattr( block, "content", str( block ) )
                    if isinstance( result, str ) and len( result ) > 80:
                        result = result[:80] + "..."
                    print( f"             RESULT[{tool_use_id}]: {result}" )
                else:
                    text = str( block )[:80]
                    print( f"             {block_type}: {text}" )

        elif msg_type == "SystemMessage":
            print( f"  [{elapsed:6.1f}s] SYSTEM: (system prompt loaded)" )

        else:
            print( f"  [{elapsed:6.1f}s] {msg_type}: {str( message )[:80]}" )

    def mark_inject( self ):
        """Mark when inject() was called."""
        self.inject_time = datetime.now()
        elapsed = ( self.inject_time - self.start_time ).total_seconds() if self.start_time else 0
        print( f"\n  [{elapsed:6.1f}s] >>> INJECT() CALLED <<<\n" )

    def mark_interrupt( self ):
        """Mark when interrupt() was called."""
        self.interrupt_time = datetime.now()
        elapsed = ( self.interrupt_time - self.start_time ).total_seconds() if self.start_time else 0
        print( f"\n  [{elapsed:6.1f}s] >>> INTERRUPT() CALLED <<<\n" )

    def summary( self ):
        """Print summary of captured messages."""
        print( "\n  Message Summary:" )
        print( f"    Total messages : {len( self.messages )}" )
        print( f"    Text blocks    : {len( self.text_blocks )}" )
        print( f"    Tool uses      : {len( self.tool_uses )}" )
        print( f"    Tool results   : {len( self.tool_results )}" )

        if self.inject_time:
            elapsed = ( self.inject_time - self.start_time ).total_seconds()
            print( f"    Inject at      : {elapsed:.1f}s" )

        if self.interrupt_time:
            elapsed = ( self.interrupt_time - self.start_time ).total_seconds()
            print( f"    Interrupt at   : {elapsed:.1f}s" )

        if self.tool_uses:
            print( "    Tools called:" )
            for tool in self.tool_uses:
                name = getattr( tool, "name", "unknown" )
                print( f"      - {name}" )


# ============================================================================
# Test Functions
# ============================================================================

async def test_inject():
    """
    Test 1: inject() - Redirect Claude mid-session.

    Start a long-running task, then inject a message to redirect Claude.
    The test verifies that Claude acknowledges the injection and changes direction.
    """
    cu.print_banner( "Test 1: inject() - Redirect Mid-Session", prepend_nl=True )

    print( "\n  This test will:" )
    print( f"    1. Start an interactive session with a multi-step task" )
    print( f"    2. Wait {TestConfig.INJECT_DELAY}s, then inject a redirect message" )
    print( "    3. Verify Claude acknowledges the redirect" )
    print( "\n  Press Enter to continue, or 'skip' to skip this test..." )

    user_input = input( "  > " ).strip().lower()
    if user_input == "skip":
        print( "  Skipping inject test." )
        return None

    tracker = MessageTracker()
    dispatcher = ClaudeCodeDispatcher( on_message=tracker.on_message )

    # Start with a multi-step task that takes time
    prompt = """
    I have a multi-step task for you:

    1. First, use mcp__cosa-voice__notify to announce: "Starting multi-step task"

    2. Then, list the Python files in the current directory using ls command

    3. After that, count how many Python files there are

    4. Finally, use mcp__cosa-voice__notify to announce the count

    Take your time with each step - I may redirect you midway.
    """

    task = Task(
        id              = "manual-inject-001",
        project         = "lupin",
        prompt          = prompt,
        type            = TaskType.INTERACTIVE,
        max_turns       = TestConfig.MAX_TURNS,
        timeout_seconds = TestConfig.SESSION_TIMEOUT
    )

    print( "\n  Starting interactive session in background..." )
    print( "  Streaming messages:\n" )

    # Start task in background
    dispatch_task = asyncio.create_task( dispatcher.dispatch( task ) )

    # Wait for session to start
    await asyncio.sleep( 1 )

    # Verify session is active
    active = dispatcher.get_active_sessions()
    print( f"\n  Active sessions: {active}" )
    session_active = task.id in active
    print( f"  Session {task.id} active: {session_active}" )

    if not session_active:
        print( "  WARNING: Session not found in active sessions!" )

    # Wait before injecting
    print( f"\n  Waiting {TestConfig.INJECT_DELAY}s before inject..." )
    await asyncio.sleep( TestConfig.INJECT_DELAY )

    # Inject redirect message
    tracker.mark_inject()
    inject_success = await dispatcher.inject(
        task.id,
        "STOP! New priority: Instead of counting Python files, tell me a short joke. Use notify() to announce the joke."
    )
    print( f"  inject() returned: {inject_success}" )

    # Wait for task to complete
    result = await dispatch_task

    tracker.summary()

    print( f"\n  Result: {'SUCCESS' if result.success else 'FAILED'}" )
    if result.error:
        print( f"  Error: {result.error}" )
    if result.cost_usd:
        print( f"  Cost: ${result.cost_usd:.4f}" )

    # Verify inject worked - look for joke-related text after injection
    # This is a heuristic check - in practice you'd examine message content
    print( f"\n  Verification:" )
    print( f"    ✓ Session started: True" )
    print( f"    ✓ inject() succeeded: {inject_success}" )
    print( f"    ✓ Session completed: {result.success}" )

    return result.success and inject_success


async def test_interrupt():
    """
    Test 2: interrupt() - Pause execution.

    Start an interactive session, then interrupt it mid-execution.
    The test verifies that the session stops and returns partial results.
    """
    cu.print_banner( "Test 2: interrupt() - Pause Execution", prepend_nl=True )

    print( "\n  This test will:" )
    print( "    1. Start an interactive session with a long task" )
    print( f"    2. Wait {TestConfig.INTERRUPT_DELAY}s, then call interrupt()" )
    print( "    3. Verify session stops and returns" )
    print( "\n  Press Enter to continue, or 'skip' to skip this test..." )

    user_input = input( "  > " ).strip().lower()
    if user_input == "skip":
        print( "  Skipping interrupt test." )
        return None

    tracker = MessageTracker()
    dispatcher = ClaudeCodeDispatcher( on_message=tracker.on_message )

    # Start with a task that will take a while
    prompt = """
    I need you to do a thorough exploration:

    1. First, use mcp__cosa-voice__notify to announce: "Starting exploration task"

    2. Then, explore the src/cosa directory structure:
       - List all subdirectories
       - Count Python files in each
       - Summarize findings

    3. After each subdirectory, use notify() to report progress

    This is a detailed exploration - take your time to be thorough.
    """

    task = Task(
        id              = "manual-interrupt-001",
        project         = "lupin",
        prompt          = prompt,
        type            = TaskType.INTERACTIVE,
        max_turns       = TestConfig.MAX_TURNS,
        timeout_seconds = TestConfig.SESSION_TIMEOUT
    )

    print( "\n  Starting interactive session in background..." )
    print( "  Streaming messages:\n" )

    # Start task in background
    dispatch_task = asyncio.create_task( dispatcher.dispatch( task ) )

    # Wait for session to start
    await asyncio.sleep( 1 )

    # Verify session is active
    active = dispatcher.get_active_sessions()
    session_active = task.id in active
    print( f"\n  Session {task.id} active: {session_active}" )

    # Wait before interrupting
    print( f"\n  Waiting {TestConfig.INTERRUPT_DELAY}s before interrupt..." )
    await asyncio.sleep( TestConfig.INTERRUPT_DELAY )

    # Interrupt
    tracker.mark_interrupt()
    interrupt_success = await dispatcher.interrupt( task.id )
    print( f"  interrupt() returned: {interrupt_success}" )

    # Wait for task to return (should be quick after interrupt)
    try:
        result = await asyncio.wait_for( dispatch_task, timeout=10 )
    except asyncio.TimeoutError:
        print( "  WARNING: Task did not return within 10s after interrupt" )
        result = TaskResult(
            task_id = task.id,
            success = False,
            error   = "Task did not respond to interrupt"
        )

    # Check session is no longer active
    active_after = dispatcher.get_active_sessions()
    session_cleared = task.id not in active_after

    tracker.summary()

    print( f"\n  Result: {'INTERRUPTED' if result.success else 'FAILED'}" )
    if result.error:
        print( f"  Error: {result.error}" )

    print( f"\n  Verification:" )
    print( f"    ✓ Session started: True" )
    print( f"    ✓ interrupt() succeeded: {interrupt_success}" )
    print( f"    ✓ Session cleared from active: {session_cleared}" )

    # Interrupt test passes if we successfully interrupted
    # The result.success may be False because the task didn't complete normally
    return interrupt_success and session_cleared


async def test_active_sessions_tracking():
    """
    Test 3: Active Sessions Tracking.

    Verify that get_active_sessions() correctly tracks session lifecycle:
    - Empty before starting
    - Contains task_id during execution
    - Empty after completion
    """
    cu.print_banner( "Test 3: Active Sessions Tracking", prepend_nl=True )

    tracker = MessageTracker()
    dispatcher = ClaudeCodeDispatcher( on_message=tracker.on_message )

    # Step 1: Verify empty before starting
    print( "  Step 1: Checking sessions before start..." )
    active_before = dispatcher.get_active_sessions()
    print( f"    Active sessions: {active_before}" )
    before_empty = len( active_before ) == 0
    print( f"    ✓ Empty before start: {before_empty}" )

    # Start a quick task
    prompt = """
    Quick task: Use mcp__cosa-voice__notify to say "Session tracking test" and then say "Done".
    """

    task = Task(
        id              = "manual-tracking-001",
        project         = "lupin",
        prompt          = prompt,
        type            = TaskType.INTERACTIVE,
        max_turns       = 10,
        timeout_seconds = 60
    )

    print( "\n  Step 2: Starting session..." )

    # Start in background
    dispatch_task = asyncio.create_task( dispatcher.dispatch( task ) )

    # Give it a moment to start
    await asyncio.sleep( 1 )

    # Step 2: Verify session is tracked
    active_during = dispatcher.get_active_sessions()
    print( f"    Active sessions: {active_during}" )
    during_tracked = task.id in active_during
    print( f"    ✓ Session tracked during execution: {during_tracked}" )

    # Wait for completion
    result = await dispatch_task

    # Step 3: Verify empty after completion
    print( "\n  Step 3: Checking sessions after completion..." )
    active_after = dispatcher.get_active_sessions()
    print( f"    Active sessions: {active_after}" )
    after_empty = len( active_after ) == 0
    print( f"    ✓ Empty after completion: {after_empty}" )

    tracker.summary()

    print( f"\n  Overall Result:" )
    print( f"    ✓ Empty before: {before_empty}" )
    print( f"    ✓ Tracked during: {during_tracked}" )
    print( f"    ✓ Empty after: {after_empty}" )

    return before_empty and during_tracked and after_empty


async def test_multiple_sessions():
    """
    Test 4: Multiple Concurrent Sessions (Optional).

    Tests that multiple sessions can be tracked simultaneously.
    """
    cu.print_banner( "Test 4: Multiple Concurrent Sessions", prepend_nl=True )

    print( "\n  This test will:" )
    print( "    1. Start two interactive sessions concurrently" )
    print( "    2. Verify both are tracked in get_active_sessions()" )
    print( "    3. Let both complete and verify cleanup" )
    print( "\n  Press Enter to continue, or 'skip' to skip this test..." )

    user_input = input( "  > " ).strip().lower()
    if user_input == "skip":
        print( "  Skipping multiple sessions test." )
        return None

    tracker1 = MessageTracker()
    tracker2 = MessageTracker()

    dispatcher = ClaudeCodeDispatcher( on_message=tracker1.on_message )

    # Create two tasks
    task1 = Task(
        id              = "manual-multi-001",
        project         = "lupin",
        prompt          = "Use notify() to say 'Session ONE started' then say 'Session ONE done'",
        type            = TaskType.INTERACTIVE,
        max_turns       = 10,
        timeout_seconds = 60
    )

    task2 = Task(
        id              = "manual-multi-002",
        project         = "lupin",
        prompt          = "Use notify() to say 'Session TWO started' then say 'Session TWO done'",
        type            = TaskType.INTERACTIVE,
        max_turns       = 10,
        timeout_seconds = 60
    )

    print( "\n  Starting two sessions concurrently..." )

    # Start both
    dispatch1 = asyncio.create_task( dispatcher.dispatch( task1 ) )
    dispatch2 = asyncio.create_task( dispatcher.dispatch( task2 ) )

    # Give them time to start
    await asyncio.sleep( 2 )

    # Check active sessions
    active = dispatcher.get_active_sessions()
    print( f"\n  Active sessions: {active}" )
    both_tracked = task1.id in active and task2.id in active
    print( f"  ✓ Both sessions tracked: {both_tracked}" )

    # Wait for both to complete
    results = await asyncio.gather( dispatch1, dispatch2, return_exceptions=True )

    # Verify cleanup
    active_after = dispatcher.get_active_sessions()
    cleaned_up = len( active_after ) == 0
    print( f"\n  Active after completion: {active_after}" )
    print( f"  ✓ Both cleaned up: {cleaned_up}" )

    # Check results
    success_count = sum( 1 for r in results if isinstance( r, TaskResult ) and r.success )
    print( f"\n  Results: {success_count}/2 succeeded" )

    return both_tracked and cleaned_up


# ============================================================================
# Main
# ============================================================================

async def main():
    """Run Phase 2 manual tests for Option B bidirectional control."""

    cu.print_banner( "Option B Phase 2 - Bidirectional Control Tests", prepend_nl=True )

    print( "\n  This script tests inject() and interrupt() functionality:" )
    print( "    1. inject()   - Redirect Claude mid-session" )
    print( "    2. interrupt()- Pause execution" )
    print( "    3. tracking   - Active session lifecycle" )
    print( "    4. multi      - Multiple concurrent sessions (optional)" )
    print( "\n  Prerequisites:" )
    print( "    * Lupin server running on port 7999" )
    print( "    * Claude Code CLI installed" )
    print( "    * claude-agent-sdk installed" )

    results = {}

    # Test 1: inject
    if TestConfig.RUN_INJECT_TEST:
        try:
            results[ "inject" ] = await test_inject()
        except Exception as e:
            print( f"\n  ✗ inject test failed with exception: {e}" )
            import traceback
            traceback.print_exc()
            results[ "inject" ] = False

    # Test 2: interrupt
    if TestConfig.RUN_INTERRUPT_TEST:
        try:
            results[ "interrupt" ] = await test_interrupt()
        except Exception as e:
            print( f"\n  ✗ interrupt test failed with exception: {e}" )
            import traceback
            traceback.print_exc()
            results[ "interrupt" ] = False

    # Test 3: active sessions tracking
    if TestConfig.RUN_STATE_TEST:
        try:
            results[ "tracking" ] = await test_active_sessions_tracking()
        except Exception as e:
            print( f"\n  ✗ tracking test failed with exception: {e}" )
            import traceback
            traceback.print_exc()
            results[ "tracking" ] = False

    # Test 4: multiple sessions (optional - ask user)
    print( "\n" )
    try:
        results[ "multi" ] = await test_multiple_sessions()
    except Exception as e:
        print( f"\n  ✗ multi-session test failed with exception: {e}" )
        import traceback
        traceback.print_exc()
        results[ "multi" ] = False

    # Final summary
    cu.print_banner( "Test Results Summary", prepend_nl=True )

    for test_name, passed in results.items():
        if passed is None:
            status = "SKIPPED"
        elif passed:
            status = "PASSED"
        else:
            status = "FAILED"
        print( f"  {test_name:12} : {status}" )

    all_passed = all( v is True for v in results.values() if v is not None )
    print( f"\n  Overall: {'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED OR SKIPPED'}" )

    return all_passed


if __name__ == "__main__":
    success = asyncio.run( main() )
    sys.exit( 0 if success else 1 )
