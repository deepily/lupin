#!/usr/bin/env python3
"""
Manual Test Script for Option B Phase B4: Inject/Interrupt Testing.

This script tests bidirectional control capabilities:
1. Message injection into active sessions
2. Session interruption
3. Active sessions tracking

PREREQUISITES:
    1. Lupin server running on port 7999
       ./src/scripts/run-fastapi-lupin.sh

    2. Claude Code CLI installed
       npm install -g @anthropic-ai/claude-code

    3. LUPIN_ROOT environment variable set
       export LUPIN_ROOT=/path/to/lupin

RUNNING:
    PYTHONPATH="$PWD/src:$PYTHONPATH" LUPIN_ROOT="$PWD" MCP_PROJECT="lupin" \
        src/cosa/.venv/bin/python src/tests/manual/test_option_b_inject_interrupt.py

Created: 2026-01-06
Purpose: Phase B4 validation - inject/interrupt for interactive sessions
"""

import asyncio
import os
import sys
from datetime import datetime

# Ensure cosa is importable
lupin_root = os.environ.get( "LUPIN_ROOT" )
if not lupin_root:
    print( "ERROR: LUPIN_ROOT environment variable not set" )
    print( "Run: export LUPIN_ROOT=/path/to/lupin" )
    sys.exit( 1 )

src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

import cosa.utils.util as cu
from cosa.orchestration import ClaudeCodeDispatcher, Task, TaskType


# ============================================================================
# Test Configuration
# ============================================================================

class TestConfig:
    """Configuration for Phase B4 tests."""

    # Which tests to run
    RUN_INJECT_TEST       = True    # Test message injection
    RUN_INTERRUPT_TEST    = True    # Test session interruption
    RUN_TRACKING_TEST     = True    # Test active sessions tracking

    # Timing
    INJECT_DELAY_SECONDS  = 3       # Wait before injecting
    SESSION_TIMEOUT       = 180     # seconds
    MAX_TURNS             = 30      # conversation turns


# ============================================================================
# Message Tracking (reused from Phase 1 tests)
# ============================================================================

class MessageTracker:
    """Track and display streaming messages."""

    def __init__( self ):
        self.messages      = []
        self.text_blocks   = []
        self.tool_uses     = []
        self.tool_results  = []
        self.start_time    = None

    def on_message( self, task_id: str, message ):
        """Callback for streaming messages."""
        now = datetime.now()
        if self.start_time is None:
            self.start_time = now

        elapsed = ( now - self.start_time ).total_seconds()
        msg_type = type( message ).__name__

        self.messages.append( {
            "elapsed"  : elapsed,
            "type"     : msg_type,
            "message"  : message
        } )

        # Categorize
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

    def summary( self ):
        """Print summary of captured messages."""
        print( "\n  Message Summary:" )
        print( f"    Total messages : {len( self.messages )}" )
        print( f"    Text blocks    : {len( self.text_blocks )}" )
        print( f"    Tool uses      : {len( self.tool_uses )}" )
        print( f"    Tool results   : {len( self.tool_results )}" )

        if self.tool_uses:
            print( "    Tools called:" )
            for tool in self.tool_uses:
                name = getattr( tool, "name", "unknown" )
                print( f"      - {name}" )


# ============================================================================
# Test Functions
# ============================================================================

async def test_message_injection():
    """
    Test 1: Message Injection.

    Start a long-running task, then inject a message mid-stream
    to redirect Claude's work.
    """
    cu.print_banner( "Test 1: Message Injection", prepend_nl=True )

    print( "\n  This test will:" )
    print( "    1. Start a task that takes several steps" )
    print( "    2. After 3 seconds, inject a new instruction" )
    print( "    3. Verify Claude receives and processes the injection" )
    print( "\n  Press Enter to continue, or 'skip' to skip this test..." )

    user_input = input( "  > " ).strip().lower()
    if user_input == "skip":
        print( "  Skipping injection test." )
        return None

    tracker = MessageTracker()
    dispatcher = ClaudeCodeDispatcher( on_message=tracker.on_message )

    # Start with a multi-step task
    prompt = """
    I want you to do the following steps. Take your time with each step:

    1. First, use notify() to say "Starting step 1"
    2. Then, list 3 interesting facts about the Python programming language
    3. Then, use notify() to say "Starting step 2"
    4. Then, list 3 interesting facts about JavaScript

    Wait for further instructions before proceeding.
    """

    task = Task(
        id          = "inject-test-001",
        project     = "lupin",
        prompt      = prompt,
        type        = TaskType.INTERACTIVE,
        max_turns   = TestConfig.MAX_TURNS,
        timeout_seconds = TestConfig.SESSION_TIMEOUT
    )

    print( "\n  Starting interactive session..." )
    print( f"  Will inject message after {TestConfig.INJECT_DELAY_SECONDS} seconds" )
    print( "\n  Streaming messages:" )

    # Start the task in background
    task_future = asyncio.create_task( dispatcher.dispatch( task ) )

    # Wait a bit, then inject
    await asyncio.sleep( TestConfig.INJECT_DELAY_SECONDS )

    print( f"\n  >>> INJECTING MESSAGE at {TestConfig.INJECT_DELAY_SECONDS}s <<<" )

    injection_message = """
    STOP what you're doing. Instead of JavaScript facts, I want you to:
    1. Use notify() to say "Received injection! Changing course."
    2. Tell me ONE fun fact about cats
    3. Then say "Injection test complete" and finish.
    """

    # Verify session is active before injecting
    active_before = dispatcher.get_active_sessions()
    print( f"  Active sessions before inject: {active_before}" )

    inject_success = await dispatcher.inject( task.id, injection_message )
    print( f"  Injection result: {'SUCCESS' if inject_success else 'FAILED'}" )

    # Wait for task to complete
    result = await task_future

    tracker.summary()

    print( f"\n  Result: {'SUCCESS' if result.success else 'FAILED'}" )
    if result.error:
        print( f"  Error: {result.error}" )
    if result.cost_usd:
        print( f"  Cost: ${result.cost_usd:.4f}" )

    # Verify injection was processed
    # Look for "cats" or "cat" in text blocks (from injected instruction)
    cat_mentioned = any(
        "cat" in str( getattr( t, "text", str( t ) ) ).lower()
        for t in tracker.text_blocks
    )

    print( f"\n  ✓ Injection delivered: {inject_success}" )
    print( f"  ✓ New topic (cats) mentioned: {cat_mentioned}" )

    return result.success and inject_success


async def test_session_interruption():
    """
    Test 2: Session Interruption.

    Start a long-running task, then interrupt it before completion.
    Verify partial results are available.
    """
    cu.print_banner( "Test 2: Session Interruption", prepend_nl=True )

    print( "\n  This test will:" )
    print( "    1. Start a task that would take a long time" )
    print( "    2. Interrupt it after 5 seconds" )
    print( "    3. Verify session is interrupted cleanly" )
    print( "\n  Press Enter to continue, or 'skip' to skip this test..." )

    user_input = input( "  > " ).strip().lower()
    if user_input == "skip":
        print( "  Skipping interruption test." )
        return None

    tracker = MessageTracker()
    dispatcher = ClaudeCodeDispatcher( on_message=tracker.on_message )

    # Start with a task that would take many turns
    prompt = """
    I want you to count from 1 to 100, but between each number:
    1. Use notify() to announce the current number
    2. Explain why that number is interesting

    Take your time. Start counting now.
    """

    task = Task(
        id          = "interrupt-test-001",
        project     = "lupin",
        prompt      = prompt,
        type        = TaskType.INTERACTIVE,
        max_turns   = TestConfig.MAX_TURNS,
        timeout_seconds = TestConfig.SESSION_TIMEOUT
    )

    print( "\n  Starting interactive session..." )
    print( "  Will interrupt after 5 seconds" )
    print( "\n  Streaming messages:" )

    # Start the task in background
    task_future = asyncio.create_task( dispatcher.dispatch( task ) )

    # Wait a bit, then interrupt
    await asyncio.sleep( 5 )

    print( "\n  >>> INTERRUPTING SESSION <<<" )

    # Verify session is active before interrupting
    active_before = dispatcher.get_active_sessions()
    print( f"  Active sessions before interrupt: {active_before}" )

    interrupt_success = await dispatcher.interrupt( task.id )
    print( f"  Interrupt result: {'SUCCESS' if interrupt_success else 'FAILED'}" )

    # Wait for task to complete (should be quick after interrupt)
    try:
        result = await asyncio.wait_for( task_future, timeout=10 )
    except asyncio.TimeoutError:
        print( "  Warning: Task didn't complete within 10s after interrupt" )
        result = None

    tracker.summary()

    if result:
        print( f"\n  Result: {'SUCCESS' if result.success else 'FAILED'}" )
        if result.error:
            print( f"  Error: {result.error}" )
    else:
        print( "\n  Result: TIMEOUT (task didn't complete after interrupt)" )

    # Check session was removed from active list
    active_after = dispatcher.get_active_sessions()
    session_cleaned = task.id not in active_after

    print( f"\n  ✓ Interrupt delivered: {interrupt_success}" )
    print( f"  ✓ Session cleaned up: {session_cleaned}" )
    print( f"  ✓ Messages captured before interrupt: {len( tracker.messages )}" )

    return interrupt_success


async def test_active_sessions_tracking():
    """
    Test 3: Active Sessions Tracking.

    Start multiple sessions, verify they're tracked, then clean up.
    """
    cu.print_banner( "Test 3: Active Sessions Tracking", prepend_nl=True )

    print( "\n  This test will:" )
    print( "    1. Verify empty active sessions list initially" )
    print( "    2. Start a session and verify it appears in list" )
    print( "    3. Complete session and verify it's removed" )
    print( "\n  Press Enter to continue, or 'skip' to skip this test..." )

    user_input = input( "  > " ).strip().lower()
    if user_input == "skip":
        print( "  Skipping tracking test." )
        return None

    tracker = MessageTracker()
    dispatcher = ClaudeCodeDispatcher( on_message=tracker.on_message )

    # Check initial state
    initial_sessions = dispatcher.get_active_sessions()
    print( f"\n  Initial active sessions: {initial_sessions}" )
    initial_empty = len( initial_sessions ) == 0

    # Quick task
    prompt = """
    Use notify() to say "Quick test" and then say "Done" and stop immediately.
    """

    task = Task(
        id          = "tracking-test-001",
        project     = "lupin",
        prompt      = prompt,
        type        = TaskType.INTERACTIVE,
        max_turns   = 10,
        timeout_seconds = 30
    )

    print( "\n  Starting quick session..." )
    print( "\n  Streaming messages:" )

    # We need to check active sessions DURING execution
    # This is tricky - we'll use a callback to check

    sessions_during = []

    original_on_message = tracker.on_message
    def tracking_callback( task_id, message ):
        # Check active sessions on first message
        if len( sessions_during ) == 0:
            current = dispatcher.get_active_sessions()
            sessions_during.extend( current )
            print( f"  [TRACKING] Active sessions during task: {current}" )
        original_on_message( task_id, message )

    dispatcher.on_message = tracking_callback

    result = await dispatcher.dispatch( task )

    # Check final state
    final_sessions = dispatcher.get_active_sessions()
    print( f"\n  Final active sessions: {final_sessions}" )
    final_empty = len( final_sessions ) == 0

    # Was session tracked during execution?
    session_tracked = task.id in sessions_during

    print( f"\n  ✓ Initial sessions empty: {initial_empty}" )
    print( f"  ✓ Session tracked during execution: {session_tracked}" )
    print( f"  ✓ Session removed after completion: {final_empty}" )

    return initial_empty and final_empty


# ============================================================================
# Main
# ============================================================================

async def main():
    """Run Phase B4 manual tests for inject/interrupt capabilities."""

    cu.print_banner( "Option B Phase B4: Inject/Interrupt Testing", prepend_nl=True )

    print( "\n  This script tests bidirectional control:" )
    print( "    1. inject()   - Send message to active session" )
    print( "    2. interrupt() - Stop active session" )
    print( "    3. Tracking   - Monitor active sessions" )
    print( "\n  Prerequisites:" )
    print( "    • Lupin server running on port 7999" )
    print( "    • Claude Code CLI installed" )
    print( "    • claude-agent-sdk installed" )

    results = {}

    # Test 1: Message Injection
    if TestConfig.RUN_INJECT_TEST:
        try:
            results[ "inject" ] = await test_message_injection()
        except Exception as e:
            print( f"\n  ✗ inject test failed with exception: {e}" )
            import traceback
            traceback.print_exc()
            results[ "inject" ] = False

    # Test 2: Session Interruption
    if TestConfig.RUN_INTERRUPT_TEST:
        try:
            results[ "interrupt" ] = await test_session_interruption()
        except Exception as e:
            print( f"\n  ✗ interrupt test failed with exception: {e}" )
            import traceback
            traceback.print_exc()
            results[ "interrupt" ] = False

    # Test 3: Active Sessions Tracking
    if TestConfig.RUN_TRACKING_TEST:
        try:
            results[ "tracking" ] = await test_active_sessions_tracking()
        except Exception as e:
            print( f"\n  ✗ tracking test failed with exception: {e}" )
            import traceback
            traceback.print_exc()
            results[ "tracking" ] = False

    # Final summary
    cu.print_banner( "Phase B4 Test Results", prepend_nl=True )

    for test_name, passed in results.items():
        if passed is None:
            status = "SKIPPED"
        elif passed:
            status = "✓ PASSED"
        else:
            status = "✗ FAILED"
        print( f"  {test_name:12} : {status}" )

    all_passed = all( v is True for v in results.values() if v is not None )
    some_ran = any( v is not None for v in results.values() )

    if some_ran:
        print( f"\n  Overall: {'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}" )
    else:
        print( "\n  Overall: ALL TESTS SKIPPED" )

    return all_passed


if __name__ == "__main__":
    success = asyncio.run( main() )
    sys.exit( 0 if success else 1 )
