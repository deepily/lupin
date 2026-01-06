#!/usr/bin/env python3
"""
Manual Test Script for Option B Interactive Sessions.

This script tests all interaction modalities:
1. Interactive session creation
2. Streaming message callbacks
3. MCP notify() - fire-and-forget announcements
4. MCP converse() - blocking voice I/O

PREREQUISITES:
    1. Lupin server running on port 7999
       ./src/scripts/run-fastapi-lupin.sh

    2. Claude Code CLI installed
       npm install -g @anthropic-ai/claude-code

    3. LUPIN_ROOT environment variable set
       export LUPIN_ROOT=/path/to/lupin

RUNNING:
    PYTHONPATH="$PWD/src:$PYTHONPATH" LUPIN_ROOT="$PWD" MCP_PROJECT="lupin" \
        src/cosa/.venv/bin/python src/tests/manual/test_option_b_interactive.py

Created: 2026-01-05
Purpose: Manual validation of Option B before production use
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
    """Configuration for manual tests."""

    # Which tests to run
    RUN_NOTIFY_TEST   = True    # Test notify() - fire-and-forget
    RUN_CONVERSE_TEST = True    # Test converse() - blocking voice I/O
    RUN_COMBINED_TEST = True    # Test both in one session

    # Timeouts
    SESSION_TIMEOUT   = 120     # seconds
    MAX_TURNS         = 20      # conversation turns


# ============================================================================
# Message Tracking
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
            # Show content blocks from assistant
            content = getattr( message, "content", [] )
            print( f"  [{elapsed:6.1f}s] ASSISTANT:" )
            for block in content:
                block_type = type( block ).__name__
                if block_type == "TextBlock":
                    self.text_blocks.append( block )  # Count nested blocks
                    text = getattr( block, "text", str( block ) )
                    # Wrap long text
                    if len( text ) > 100:
                        print( f"             TEXT: {text[:100]}..." )
                    else:
                        print( f"             TEXT: {text}" )
                elif block_type == "ToolUseBlock":
                    self.tool_uses.append( block )  # Count nested blocks
                    tool_name = getattr( block, "name", "unknown" )
                    print( f"             TOOL: {tool_name}" )
                else:
                    print( f"             {block_type}" )

        elif msg_type == "UserMessage":
            # Show user message content (tool results or injected messages)
            content = getattr( message, "content", [] )
            print( f"  [{elapsed:6.1f}s] USER:" )
            for block in content:
                block_type = type( block ).__name__
                if block_type == "ToolResultBlock":
                    self.tool_results.append( block )  # Count nested blocks
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

        # List tools used
        if self.tool_uses:
            print( "    Tools called:" )
            for tool in self.tool_uses:
                name = getattr( tool, "name", "unknown" )
                print( f"      - {name}" )


# ============================================================================
# Test Functions
# ============================================================================

async def test_notify_only():
    """
    Test 1: notify() - Fire-and-forget announcement.

    Claude should use mcp__cosa-voice__notify to send an announcement.
    This should NOT block - Claude continues immediately.
    """
    cu.print_banner( "Test 1: notify() - Fire-and-Forget", prepend_nl=True )

    tracker = MessageTracker()
    dispatcher = ClaudeCodeDispatcher( on_message=tracker.on_message )

    prompt = """
    Use the mcp__cosa-voice__notify tool to announce: "Hello! This is a test of the notification system."

    After sending the notification, say "Notification sent successfully" and stop.

    Do NOT use converse or ask_yes_no - only use notify.
    """

    task = Task(
        id          = "manual-notify-001",
        project     = "lupin",
        prompt      = prompt,
        type        = TaskType.INTERACTIVE,
        max_turns   = TestConfig.MAX_TURNS,
        timeout_seconds = TestConfig.SESSION_TIMEOUT
    )

    print( "\n  Starting interactive session..." )
    print( "  Prompt: Use notify() to send announcement" )
    print( "\n  Streaming messages:" )

    result = await dispatcher.dispatch( task )

    tracker.summary()

    print( f"\n  Result: {'SUCCESS' if result.success else 'FAILED'}" )
    if result.error:
        print( f"  Error: {result.error}" )
    if result.cost_usd:
        print( f"  Cost: ${result.cost_usd:.4f}" )

    # Check if notify was used
    notify_used = any(
        getattr( t, "name", "" ) == "mcp__cosa-voice__notify"
        for t in tracker.tool_uses
    )
    print( f"\n  ✓ notify() was called: {notify_used}" )

    return result.success and notify_used


async def test_converse_only():
    """
    Test 2: converse() - Blocking voice I/O.

    Claude should use mcp__cosa-voice__converse to ask a question
    and WAIT for the user's voice response.
    """
    cu.print_banner( "Test 2: converse() - Blocking Voice I/O", prepend_nl=True )

    print( "\n  ⚠️  This test requires voice interaction!" )
    print( "  When Claude asks a question, respond via voice or the Lupin UI." )
    print( "  Press Enter to continue, or 'skip' to skip this test..." )

    user_input = input( "  > " ).strip().lower()
    if user_input == "skip":
        print( "  Skipping converse test." )
        return None

    tracker = MessageTracker()
    dispatcher = ClaudeCodeDispatcher( on_message=tracker.on_message )

    prompt = """
    Use the mcp__cosa-voice__converse tool to ask me: "What is your favorite color?"

    Wait for my response, then say "Thank you! You said your favorite color is [their answer]."

    Do NOT use notify - use converse which waits for a response.
    """

    task = Task(
        id          = "manual-converse-001",
        project     = "lupin",
        prompt      = prompt,
        type        = TaskType.INTERACTIVE,
        max_turns   = TestConfig.MAX_TURNS,
        timeout_seconds = TestConfig.SESSION_TIMEOUT
    )

    print( "\n  Starting interactive session..." )
    print( "  Prompt: Use converse() to ask about favorite color" )
    print( "\n  Streaming messages:" )

    result = await dispatcher.dispatch( task )

    tracker.summary()

    print( f"\n  Result: {'SUCCESS' if result.success else 'FAILED'}" )
    if result.error:
        print( f"  Error: {result.error}" )
    if result.cost_usd:
        print( f"  Cost: ${result.cost_usd:.4f}" )

    # Check if converse was used
    converse_used = any(
        getattr( t, "name", "" ) == "mcp__cosa-voice__converse"
        for t in tracker.tool_uses
    )
    print( f"\n  ✓ converse() was called: {converse_used}" )

    return result.success and converse_used


async def test_combined_interaction():
    """
    Test 3: Combined - notify + converse in one session.

    Claude should:
    1. Use notify() to announce start
    2. Use converse() to ask a question
    3. Use notify() to announce completion
    """
    cu.print_banner( "Test 3: Combined Interaction", prepend_nl=True )

    print( "\n  ⚠️  This test requires voice interaction!" )
    print( "  Claude will notify, then ask a question via voice." )
    print( "  Press Enter to continue, or 'skip' to skip this test..." )

    user_input = input( "  > " ).strip().lower()
    if user_input == "skip":
        print( "  Skipping combined test." )
        return None

    tracker = MessageTracker()
    dispatcher = ClaudeCodeDispatcher( on_message=tracker.on_message )

    prompt = """
    Perform this sequence:

    1. Use mcp__cosa-voice__notify to announce: "Starting the combined interaction test."

    2. Use mcp__cosa-voice__converse to ask: "What should I call you?"

    3. After receiving the response, use mcp__cosa-voice__notify to announce:
       "Test complete! Nice to meet you, [their name]."

    4. Then say "Combined test finished successfully" and stop.
    """

    task = Task(
        id          = "manual-combined-001",
        project     = "lupin",
        prompt      = prompt,
        type        = TaskType.INTERACTIVE,
        max_turns   = TestConfig.MAX_TURNS,
        timeout_seconds = TestConfig.SESSION_TIMEOUT
    )

    print( "\n  Starting interactive session..." )
    print( "  Prompt: notify → converse → notify sequence" )
    print( "\n  Streaming messages:" )

    result = await dispatcher.dispatch( task )

    tracker.summary()

    print( f"\n  Result: {'SUCCESS' if result.success else 'FAILED'}" )
    if result.error:
        print( f"  Error: {result.error}" )
    if result.cost_usd:
        print( f"  Cost: ${result.cost_usd:.4f}" )

    # Check tools used
    notify_count = sum(
        1 for t in tracker.tool_uses
        if getattr( t, "name", "" ) == "mcp__cosa-voice__notify"
    )
    converse_count = sum(
        1 for t in tracker.tool_uses
        if getattr( t, "name", "" ) == "mcp__cosa-voice__converse"
    )

    print( f"\n  ✓ notify() calls: {notify_count} (expected 2)" )
    print( f"  ✓ converse() calls: {converse_count} (expected 1)" )

    return result.success and notify_count >= 2 and converse_count >= 1


# ============================================================================
# Main
# ============================================================================

async def main():
    """Run manual tests for Option B interactive sessions."""

    cu.print_banner( "Option B Interactive Sessions - Manual Test", prepend_nl=True )

    print( "\n  This script tests all interaction modalities:" )
    print( "    1. notify()   - Fire-and-forget announcements" )
    print( "    2. converse() - Blocking voice I/O" )
    print( "    3. Combined   - Both in sequence" )
    print( "\n  Prerequisites:" )
    print( "    • Lupin server running on port 7999" )
    print( "    • Claude Code CLI installed" )
    print( "    • Voice notification system accessible" )

    results = {}

    # Test 1: notify
    if TestConfig.RUN_NOTIFY_TEST:
        try:
            results[ "notify" ] = await test_notify_only()
        except Exception as e:
            print( f"\n  ✗ notify test failed with exception: {e}" )
            results[ "notify" ] = False

    # Test 2: converse
    if TestConfig.RUN_CONVERSE_TEST:
        try:
            results[ "converse" ] = await test_converse_only()
        except Exception as e:
            print( f"\n  ✗ converse test failed with exception: {e}" )
            results[ "converse" ] = False

    # Test 3: combined
    if TestConfig.RUN_COMBINED_TEST:
        try:
            results[ "combined" ] = await test_combined_interaction()
        except Exception as e:
            print( f"\n  ✗ combined test failed with exception: {e}" )
            results[ "combined" ] = False

    # Final summary
    cu.print_banner( "Test Results Summary", prepend_nl=True )

    for test_name, passed in results.items():
        if passed is None:
            status = "SKIPPED"
        elif passed:
            status = "✓ PASSED"
        else:
            status = "✗ FAILED"
        print( f"  {test_name:12} : {status}" )

    all_passed = all( v is True for v in results.values() if v is not None )
    print( f"\n  Overall: {'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}" )

    return all_passed


if __name__ == "__main__":
    success = asyncio.run( main() )
    sys.exit( 0 if success else 1 )
