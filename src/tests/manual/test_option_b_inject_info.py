#!/usr/bin/env python3
"""
Manual Test Script for Option B: Information Injection Testing.

This script tests the interrupt-then-inject pattern where Claude is given
incomplete information initially, then the missing data is injected mid-stream.

PREREQUISITES:
    1. Lupin server running on port 7999
       ./src/scripts/run-fastapi-lupin.sh

    2. Claude Code CLI installed
       npm install -g @anthropic-ai/claude-code

    3. LUPIN_ROOT environment variable set
       export LUPIN_ROOT=/path/to/lupin

RUNNING:
    PYTHONPATH="$PWD/src:$PYTHONPATH" LUPIN_ROOT="$PWD" MCP_PROJECT="lupin" \
        src/cosa/.venv/bin/python src/tests/manual/test_option_b_inject_info.py

Created: 2026-01-06
Purpose: Validate interrupt-then-inject pattern for providing late-arriving data
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
    """Configuration for information injection tests."""

    # Which tests to run
    RUN_CALCULATION_TEST  = True    # Test: inject price for calculation
    RUN_DIRECTION_TEST    = True    # Test: inject new direction mid-task
    RUN_CORRECTION_TEST   = True    # Test: inject correction

    # Timing
    INJECT_DELAY_SECONDS  = 3       # Wait before injecting
    SESSION_TIMEOUT       = 120     # seconds
    MAX_TURNS             = 20      # conversation turns


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
        self.all_text      = ""  # Concatenated text for verification

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

        # Categorize and extract text
        if msg_type == "TextBlock":
            self.text_blocks.append( message )
            text = getattr( message, "text", str( message ) )
            self.all_text += text + " "
            text_preview = text[:80] + "..." if len( text ) > 80 else text
            print( f"  [{elapsed:6.1f}s] TEXT: {text_preview}" )

        elif msg_type == "ToolUseBlock":
            self.tool_uses.append( message )
            tool_name = getattr( message, "name", "unknown" )
            print( f"  [{elapsed:6.1f}s] TOOL: {tool_name}" )
            # Display notify() message content for visibility
            if "notify" in tool_name.lower():
                tool_input = getattr( message, "input", {} )
                notify_msg = tool_input.get( "message", "" )
                if notify_msg:
                    preview = notify_msg[:80] + "..." if len( notify_msg ) > 80 else notify_msg
                    print( f"             → message: \"{preview}\"" )

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
                    self.all_text += text + " "
                    if len( text ) > 100:
                        print( f"             TEXT: {text[:100]}..." )
                    else:
                        print( f"             TEXT: {text}" )
                elif block_type == "ToolUseBlock":
                    self.tool_uses.append( block )
                    tool_name = getattr( block, "name", "unknown" )
                    print( f"             TOOL: {tool_name}" )
                    # Display notify() message content for visibility
                    if "notify" in tool_name.lower():
                        tool_input = getattr( block, "input", {} )
                        notify_msg = tool_input.get( "message", "" )
                        if notify_msg:
                            preview = notify_msg[:80] + "..." if len( notify_msg ) > 80 else notify_msg
                            print( f"                  → message: \"{preview}\"" )
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

    def contains( self, *keywords ):
        """Check if any keywords appear in captured text."""
        text_lower = self.all_text.lower()
        for keyword in keywords:
            if keyword.lower() in text_lower:
                return True
        return False

    def contains_notify_with( self, *keywords ):
        """
        Check if any notify() tool call contains the keywords.

        Requires:
            - keywords are strings to search for (case-insensitive)

        Ensures:
            - Returns True if a notify() tool call was made AND its 'message'
              parameter contains at least one of the provided keywords
            - Returns False if no matching notify() call found

        This provides stronger verification than contains() because it checks
        the tool call parameters, not just text output.
        """
        for tool_use in self.tool_uses:
            tool_name = getattr( tool_use, "name", "" )
            if "notify" in tool_name.lower():
                # Get the 'input' dict containing tool parameters
                tool_input = getattr( tool_use, "input", {} )
                message = tool_input.get( "message", "" ).lower()
                for keyword in keywords:
                    if keyword.lower() in message:
                        return True
        return False


# ============================================================================
# Test Functions
# ============================================================================

async def test_calculation_injection():
    """
    Test 1: Information Injection - Calculation.

    Start Claude with incomplete info (needs price), then inject the missing price.
    Verify Claude uses the injected price in its calculation.
    """
    cu.print_banner( "Test 1: Calculation Info Injection", prepend_nl=True )

    print( "\n  Scenario:" )
    print( "    1. Ask Claude to calculate cost of 5 items (price unknown)" )
    print( "    2. After 3s, inject: 'The price per item is $12.50'" )
    print( "    3. Verify: Claude calculates 5 × $12.50 = $62.50" )
    print( "\n  Press Enter to continue, or 'skip' to skip this test..." )

    user_input = input( "  > " ).strip().lower()
    if user_input == "skip":
        print( "  Skipping calculation test." )
        return None

    tracker = MessageTracker()
    dispatcher = ClaudeCodeDispatcher( on_message=tracker.on_message )

    # Initial prompt with missing information
    prompt = """
    I need you to calculate the total cost of purchasing 5 items.
    I don't have the price per item yet - I'll provide it shortly.

    While you wait, please:
    1. Use notify() to say "Waiting for price information..."
    2. Explain how you'll calculate the total once you have the price
    3. Wait for me to provide the price before calculating

    Do NOT make up a price. Wait for me to give you the actual price.
    """

    task = Task(
        id          = "calc-inject-001",
        project     = "lupin",
        prompt      = prompt,
        type        = TaskType.INTERACTIVE,
        max_turns   = TestConfig.MAX_TURNS,
        timeout_seconds = TestConfig.SESSION_TIMEOUT
    )

    print( "\n  Starting interactive session..." )
    print( f"  Will inject price after {TestConfig.INJECT_DELAY_SECONDS} seconds" )
    print( "\n  Streaming messages:" )

    # Start the task in background
    task_future = asyncio.create_task( dispatcher.dispatch( task ) )

    # Wait, then inject the missing information
    await asyncio.sleep( TestConfig.INJECT_DELAY_SECONDS )

    print( f"\n  >>> INJECTING PRICE INFO at {TestConfig.INJECT_DELAY_SECONDS}s <<<" )

    injection_message = """
    Here's the price: $12.50 per item.

    BEFORE you calculate, use notify() to summarize what you remember from our
    earlier conversation:
    - How many items did I ask about?
    - What information was I going to provide later?

    Example: "Session 1 context: User asked about [X] items and said they
    would provide the [missing info]"

    THEN calculate the total cost and use notify() to announce the result.
    """

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

    # Verify injected information was used
    has_correct_answer = tracker.contains( "62.50", "62.5", "$62.50" )
    has_price = tracker.contains( "12.50", "$12.50" )

    # Verify Session 1 context via notify() call (stronger than text matching)
    # Claude should call notify() with BOTH: "5 items" AND "price" was missing
    remembers_quantity = tracker.contains_notify_with( "5 item", "five item", "5" )
    remembers_missing  = tracker.contains_notify_with( "price" )

    print( f"\n  ✓ Injection delivered: {inject_success}" )
    print( f"  ✓ Price ($12.50) mentioned: {has_price}" )
    print( f"  ✓ Correct answer ($62.50) calculated: {has_correct_answer}" )
    print( f"  ✓ Session 1 memory - quantity (notify with '5 items'): {remembers_quantity}" )
    print( f"  ✓ Session 1 memory - missing info (notify with 'price'): {remembers_missing}" )

    return inject_success and has_correct_answer and remembers_quantity and remembers_missing


async def test_direction_change():
    """
    Test 2: Direction Change - Switch task mid-stream.

    Start Claude on one topic, then inject new instructions to switch.
    """
    cu.print_banner( "Test 2: Direction Change Injection", prepend_nl=True )

    print( "\n  Scenario:" )
    print( "    1. Ask Claude to list facts about dogs" )
    print( "    2. After 3s, inject: 'Actually, tell me about cats instead'" )
    print( "    3. Verify: Claude switches to talking about cats" )
    print( "\n  Press Enter to continue, or 'skip' to skip this test..." )

    user_input = input( "  > " ).strip().lower()
    if user_input == "skip":
        print( "  Skipping direction change test." )
        return None

    tracker = MessageTracker()
    dispatcher = ClaudeCodeDispatcher( on_message=tracker.on_message )

    # Initial prompt
    prompt = """
    Please tell me 5 interesting facts about dogs.
    Take your time with each fact - explain each one thoroughly.
    Use notify() to announce when you start.
    """

    task = Task(
        id          = "direction-inject-001",
        project     = "lupin",
        prompt      = prompt,
        type        = TaskType.INTERACTIVE,
        max_turns   = TestConfig.MAX_TURNS,
        timeout_seconds = TestConfig.SESSION_TIMEOUT
    )

    print( "\n  Starting interactive session..." )
    print( f"  Will inject direction change after {TestConfig.INJECT_DELAY_SECONDS} seconds" )
    print( "\n  Streaming messages:" )

    # Start the task in background
    task_future = asyncio.create_task( dispatcher.dispatch( task ) )

    # Wait, then inject direction change
    await asyncio.sleep( TestConfig.INJECT_DELAY_SECONDS )

    print( f"\n  >>> INJECTING DIRECTION CHANGE at {TestConfig.INJECT_DELAY_SECONDS}s <<<" )

    injection_message = """
    STOP talking about dogs!

    FIRST: Use notify() to summarize what you remember from our earlier conversation:
    - What animal did I originally ask about?
    - What type of information did I want? (e.g., facts, history, care tips)

    Example: "Session 1 context: User asked for [type of info] about [animal]"

    THEN: Tell me 3 interesting facts about CATS instead.
    When done, use notify() to say "Direction change complete".
    """

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

    # Verify direction change was followed
    has_cats = tracker.contains( "cat", "cats", "feline" )

    # Verify Session 1 context via notify() call (stronger than text matching)
    # Claude should call notify() with BOTH: "dogs" AND "facts" (the info type)
    remembers_animal   = tracker.contains_notify_with( "dog", "dogs", "canine" )
    remembers_request  = tracker.contains_notify_with( "fact", "facts", "interesting" )

    print( f"\n  ✓ Injection delivered: {inject_success}" )
    print( f"  ✓ Cats mentioned after injection: {has_cats}" )
    print( f"  ✓ Session 1 memory - animal (notify with 'dogs'): {remembers_animal}" )
    print( f"  ✓ Session 1 memory - request type (notify with 'facts'): {remembers_request}" )

    return inject_success and has_cats and remembers_animal and remembers_request


async def test_correction_injection():
    """
    Test 3: Correction Injection - Fix a mistake mid-stream.

    Start Claude with incorrect info, then inject a correction.
    """
    cu.print_banner( "Test 3: Correction Injection", prepend_nl=True )

    print( "\n  Scenario:" )
    print( "    1. Tell Claude the capital of France is Berlin (wrong!)" )
    print( "    2. After 3s, inject: 'Wait, I made a mistake. It's Paris.'" )
    print( "    3. Verify: Claude acknowledges the correction" )
    print( "\n  Press Enter to continue, or 'skip' to skip this test..." )

    user_input = input( "  > " ).strip().lower()
    if user_input == "skip":
        print( "  Skipping correction test." )
        return None

    tracker = MessageTracker()
    dispatcher = ClaudeCodeDispatcher( on_message=tracker.on_message )

    # Initial prompt with WRONG information
    prompt = """
    I'm studying for a geography test. Please help me remember:
    The capital of France is Berlin.

    Use notify() to start, then help me create a mnemonic to remember this.
    Take your time explaining the mnemonic.
    """

    task = Task(
        id          = "correct-inject-001",
        project     = "lupin",
        prompt      = prompt,
        type        = TaskType.INTERACTIVE,
        max_turns   = TestConfig.MAX_TURNS,
        timeout_seconds = TestConfig.SESSION_TIMEOUT
    )

    print( "\n  Starting interactive session..." )
    print( f"  Will inject correction after {TestConfig.INJECT_DELAY_SECONDS} seconds" )
    print( "\n  Streaming messages:" )

    # Start the task in background
    task_future = asyncio.create_task( dispatcher.dispatch( task ) )

    # Wait, then inject correction
    await asyncio.sleep( TestConfig.INJECT_DELAY_SECONDS )

    print( f"\n  >>> INJECTING CORRECTION at {TestConfig.INJECT_DELAY_SECONDS}s <<<" )

    injection_message = """
    WAIT! I made a mistake!

    FIRST: Use notify() to summarize what you remember from our earlier conversation:
    - What INCORRECT city did I claim was the capital?
    - What country was I asking about?

    Example: "Session 1 context: User incorrectly said [city] was the capital of [country]"

    THEN: Correct me - the capital of France is PARIS, not what I said before.
    Create a new mnemonic to help me remember Paris is the correct capital.
    When done, use notify() to say "Correction complete".
    """

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

    # Verify correction was acknowledged
    has_paris = tracker.contains( "paris" )
    has_correction = tracker.contains( "correct", "mistake", "actually", "sorry" )

    # Verify Session 1 context via notify() call (stronger than text matching)
    # Claude should call notify() with BOTH: "Berlin" AND "France"
    remembers_wrong_city = tracker.contains_notify_with( "berlin" )
    remembers_country    = tracker.contains_notify_with( "france" )

    print( f"\n  ✓ Injection delivered: {inject_success}" )
    print( f"  ✓ Paris mentioned: {has_paris}" )
    print( f"  ✓ Correction acknowledged: {has_correction}" )
    print( f"  ✓ Session 1 memory - wrong city (notify with 'Berlin'): {remembers_wrong_city}" )
    print( f"  ✓ Session 1 memory - country (notify with 'France'): {remembers_country}" )

    return inject_success and has_paris and remembers_wrong_city and remembers_country


# ============================================================================
# Main
# ============================================================================

async def main():
    """Run information injection tests."""

    cu.print_banner( "Option B: Information Injection Testing", prepend_nl=True )

    print( "\n  This script tests the interrupt-then-inject pattern:" )
    print( "    1. Calculation - Inject missing price data" )
    print( "    2. Direction   - Inject task change mid-stream" )
    print( "    3. Correction  - Inject correction of wrong info" )
    print( "\n  Prerequisites:" )
    print( "    • Lupin server running on port 7999" )
    print( "    • Claude Code CLI installed" )
    print( "    • claude-agent-sdk installed" )

    results = {}

    # Test 1: Calculation injection
    if TestConfig.RUN_CALCULATION_TEST:
        try:
            results[ "calculation" ] = await test_calculation_injection()
        except Exception as e:
            print( f"\n  ✗ calculation test failed with exception: {e}" )
            import traceback
            traceback.print_exc()
            results[ "calculation" ] = False

    # Test 2: Direction change
    if TestConfig.RUN_DIRECTION_TEST:
        try:
            results[ "direction" ] = await test_direction_change()
        except Exception as e:
            print( f"\n  ✗ direction test failed with exception: {e}" )
            import traceback
            traceback.print_exc()
            results[ "direction" ] = False

    # Test 3: Correction injection
    if TestConfig.RUN_CORRECTION_TEST:
        try:
            results[ "correction" ] = await test_correction_injection()
        except Exception as e:
            print( f"\n  ✗ correction test failed with exception: {e}" )
            import traceback
            traceback.print_exc()
            results[ "correction" ] = False

    # Final summary
    cu.print_banner( "Information Injection Test Results", prepend_nl=True )

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
