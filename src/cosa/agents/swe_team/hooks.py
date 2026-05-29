#!/usr/bin/env python3
"""
SDK Hook Functions for COSA SWE Team Agent.

Extracted from orchestrator for clean separation. These hooks wire
into ClaudeAgentOptions.can_use_tool and notification callbacks to
integrate the SWE Team with COSA's safety and notification systems.

Hook Types:
    - notification_hook: Fires notify_progress() on SDK notification events
    - pre_tool_hook: Gates dangerous commands via ask_confirmation()
    - post_tool_hook: Tracks file changes via guard.record_file_change()

Pattern source: ClaudeCodeDispatcher (dispatcher.py) on_message() callbacks,
adapted for the can_use_tool / hooks interface in claude-agent-sdk >= 0.1.35.
"""

import asyncio
import logging
from typing import Any

from .safety_limits import SafetyGuard, is_dangerous_command

logger = logging.getLogger( __name__ )


# =============================================================================
# Notification Hook
# =============================================================================

async def notification_hook( event, team_io, role="lead", progress_group_id=None ):
    """
    Fire notify_progress() on SDK notification events.

    Maps SDK notification event data to cosa_interface calls
    with a role-aware sender ID.

    Requires:
        - event is a dict-like with "message" key
        - team_io is the cosa_interface module
        - role is a valid SWE Team role name

    Ensures:
        - Calls team_io.notify_progress() with the event message
        - Passes progress_group_id for in-place DOM updates when provided
        - Logs warning on failure (never raises)

    Args:
        event: SDK notification event (NotificationHookInput)
        team_io: cosa_interface module for notifications
        role: Agent role name for sender ID construction
        progress_group_id: Optional progress group ID (pg-{8 hex chars}) for in-place DOM updates
    """
    try:
        message = event.get( "message", "" )
        if not message:
            return

        await team_io.notify_progress(
            message           = f"[{role}] {message}",
            role              = role,
            priority          = "low",
            progress_group_id = progress_group_id,
        )

    except Exception as e:
        logger.warning( f"notification_hook failed: {e}" )


# =============================================================================
# Pre-Tool Hook (via can_use_tool callback)
# =============================================================================

async def pre_tool_hook( tool_name, tool_input, team_io, guard, role="coder" ):
    """
    Gate dangerous commands via ask_confirmation().

    Called by ClaudeAgentOptions.can_use_tool before each tool execution.
    Returns PermissionResultAllow or PermissionResultDeny.

    Requires:
        - tool_name is a string (e.g., "Bash", "Edit", "Write")
        - tool_input is a dict with tool-specific keys
        - team_io is the cosa_interface module
        - guard is a SafetyGuard instance

    Ensures:
        - Returns PermissionResultAllow for safe commands
        - Returns PermissionResultDeny for dangerous commands rejected by user
        - Allows dangerous commands when user approves
        - Always allows non-Bash tools

    Args:
        tool_name: SDK tool name
        tool_input: Tool input parameters
        team_io: cosa_interface module for confirmations
        guard: SafetyGuard instance for tracking
        role: Agent role for notification context

    Returns:
        PermissionResultAllow or PermissionResultDeny
    """
    from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

    # Only gate Bash commands for danger
    if tool_name != "Bash":
        return PermissionResultAllow( behavior="allow" )

    command = tool_input.get( "command", "" )

    if not is_dangerous_command( command ):
        return PermissionResultAllow( behavior="allow" )

    # Dangerous command detected — ask user
    logger.warning( f"Dangerous command detected: {command[ :200 ]}" )

    try:
        approved = await team_io.ask_confirmation(
            question = f"SWE Team {role} wants to run a potentially dangerous command:\n\n`{command[ :300 ]}`\n\nAllow this command?",
            role     = role,
            default  = "no",
            timeout  = 60,
            abstract = f"**Tool**: Bash\n**Command**: `{command[ :500 ]}`\n**Detected pattern**: dangerous command",
        )

        if approved:
            logger.info( f"User approved dangerous command: {command[ :100 ]}" )
            return PermissionResultAllow( behavior="allow" )
        else:
            logger.info( f"User rejected dangerous command: {command[ :100 ]}" )
            return PermissionResultDeny(
                behavior = "deny",
                message  = "Command rejected by user: potentially dangerous operation",
                interrupt = False,
            )

    except Exception as e:
        logger.warning( f"pre_tool_hook confirmation failed: {e}, denying command" )
        return PermissionResultDeny(
            behavior  = "deny",
            message   = f"Could not confirm dangerous command: {e}",
            interrupt = False,
        )


# =============================================================================
# Post-Tool Hook
# =============================================================================

async def post_tool_hook( tool_name, tool_input, guard ):
    """
    Track file changes via guard.record_file_change() when
    Edit or Write tools are used.

    Requires:
        - tool_name is a string
        - tool_input is a dict with tool-specific keys
        - guard is a SafetyGuard instance

    Ensures:
        - Calls guard.record_file_change() for Edit and Write tools
        - Does nothing for Read, Glob, Grep, Bash, and other tools
        - Logs the file path being tracked

    Args:
        tool_name: SDK tool name
        tool_input: Tool input parameters
        guard: SafetyGuard instance for file change tracking
    """
    if tool_name not in ( "Edit", "Write" ):
        return

    file_path = tool_input.get( "file_path", "unknown" )
    logger.info( f"File change tracked: {tool_name} → {file_path}" )
    guard.record_file_change()


# =============================================================================
# Hook Wiring Helpers
# =============================================================================

def build_can_use_tool( team_io, guard, role="coder" ):
    """
    Build a can_use_tool callback for ClaudeAgentOptions.

    Returns an async callable with the signature expected by the SDK:
        async (tool_name, tool_input, context) -> PermissionResultAllow | PermissionResultDeny

    Requires:
        - team_io is the cosa_interface module
        - guard is a SafetyGuard instance

    Ensures:
        - Returns a closure that delegates to pre_tool_hook
        - Closure matches SDK can_use_tool signature

    Args:
        team_io: cosa_interface module
        guard: SafetyGuard instance
        role: Agent role name

    Returns:
        Async callable for ClaudeAgentOptions.can_use_tool
    """
    async def _can_use_tool( tool_name, tool_input, context ):
        return await pre_tool_hook( tool_name, tool_input, team_io, guard, role )

    return _can_use_tool


# =============================================================================
# Streaming-mode prompt wrapper (Bug 15 workaround)
# =============================================================================

async def wrap_prompt_for_streaming( prompt, session_id=None ):
    """
    Wrap a string prompt as the single-message AsyncIterable shape that
    `claude-agent-sdk >= 0.1.36` requires whenever `options.can_use_tool` is set.

    WORKAROUND for an upstream Python-SDK design gap: the SDK raises
    `ValueError( "can_use_tool callback requires streaming mode. Please
    provide prompt as an AsyncIterable instead of a string." )` if a plain
    string is passed while `can_use_tool` is configured. The TypeScript SDK
    has no such restriction — this is Python-only.

    Upstream tracker (unresolved as of 2026-04-17):
        https://github.com/anthropics/claude-code/issues/18735

    **Remove this helper and revert every call site** once upstream lands
    stream persistence for `can_use_tool` and the string path works again.

    Requires:
        - prompt is a non-empty string
        - session_id is None or a string (auto-generated UUID4 if None)

    Ensures:
        - Returns an async generator yielding exactly one SDK-format message dict
        - Shape matches what the SDK's `query()` path builds internally
          (see https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/client.py)
    """
    import uuid
    effective_session_id = session_id or str( uuid.uuid4() )
    yield {
        "type"               : "user",
        "message"            : { "role": "user", "content": prompt },
        "parent_tool_use_id" : None,
        "session_id"         : effective_session_id,
    }


def quick_smoke_test():
    """Quick smoke test for hooks module."""
    import cosa.utils.util as cu

    cu.print_banner( "SWE Team Hooks Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import validation
        print( "Testing imports..." )
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
        assert PermissionResultAllow is not None
        assert PermissionResultDeny is not None
        print( "✓ SDK imports available" )

        # Test 2: notification_hook is async
        print( "Testing notification_hook signature..." )
        import inspect
        assert inspect.iscoroutinefunction( notification_hook )
        print( "✓ notification_hook is async" )

        # Test 3: pre_tool_hook is async
        print( "Testing pre_tool_hook signature..." )
        assert inspect.iscoroutinefunction( pre_tool_hook )
        print( "✓ pre_tool_hook is async" )

        # Test 4: post_tool_hook is async
        print( "Testing post_tool_hook signature..." )
        assert inspect.iscoroutinefunction( post_tool_hook )
        print( "✓ post_tool_hook is async" )

        # Test 5: build_can_use_tool returns callable
        print( "Testing build_can_use_tool..." )
        guard = SafetyGuard( max_iterations=5 )

        # Use a simple mock for team_io
        class MockTeamIO:
            async def notify_progress( self, **kwargs ): pass
            async def ask_confirmation( self, **kwargs ): return False

        callback = build_can_use_tool( MockTeamIO(), guard )
        assert callable( callback )
        print( "✓ build_can_use_tool returns callable" )

        # Test 6: post_tool_hook tracks changes
        print( "Testing post_tool_hook file tracking..." )

        async def test_post():
            guard2 = SafetyGuard( max_iterations=5 )
            await post_tool_hook( "Edit", { "file_path": "test.py" }, guard2 )
            assert guard2.file_changes == 1
            await post_tool_hook( "Read", { "file_path": "test.py" }, guard2 )
            assert guard2.file_changes == 1  # Read doesn't increment
            await post_tool_hook( "Write", { "file_path": "test2.py" }, guard2 )
            assert guard2.file_changes == 2

        asyncio.run( test_post() )
        print( "✓ post_tool_hook tracks Edit/Write, ignores Read" )

        print( "\n✓ SWE Team Hooks smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
