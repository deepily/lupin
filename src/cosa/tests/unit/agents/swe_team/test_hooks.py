"""
Unit tests for swe_team/hooks.py — SDK hook functions:
  - notification_hook  : fires team_io.notify_progress on SDK notification events
  - pre_tool_hook      : gates dangerous Bash commands via ask_confirmation
  - post_tool_hook     : tracks Edit/Write file changes via guard.record_file_change
  - build_can_use_tool : closure factory delegating to pre_tool_hook
  - wrap_prompt_for_streaming : single-message AsyncIterable wrapper (SDK workaround)

team_io is an AsyncMock; SafetyGuard is real (pure in-memory). The real
PermissionResultAllow/Deny come from claude_agent_sdk (pre-warmed by run-sdk-cov.sh).
No real SDK/network/LLM calls.

Created 2026-05-31 by Extra 1 🪨 (CoSA coverage campaign, swe_team lane, mid tier).
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

import cosa.agents.swe_team.hooks as hooks
from cosa.agents.swe_team.safety_limits import SafetyGuard


def _run( coro ):
    return asyncio.run( coro )


class TestNotificationHook( unittest.TestCase ):

    def test_fires_notify_progress_on_message( self ):
        team_io = MagicMock()
        team_io.notify_progress = AsyncMock()
        event = { "message": "build started" }
        _run( hooks.notification_hook( event, team_io, role="coder", progress_group_id="pg-1" ) )
        team_io.notify_progress.assert_awaited_once()
        kwargs = team_io.notify_progress.await_args.kwargs
        self.assertEqual( kwargs[ "message" ], "[coder] build started" )
        self.assertEqual( kwargs[ "progress_group_id" ], "pg-1" )

    def test_empty_message_short_circuits( self ):
        team_io = MagicMock()
        team_io.notify_progress = AsyncMock()
        _run( hooks.notification_hook( { "message": "" }, team_io ) )
        team_io.notify_progress.assert_not_awaited()

    def test_exception_is_swallowed_and_logged( self ):
        team_io = MagicMock()
        team_io.notify_progress = AsyncMock( side_effect=RuntimeError( "boom" ) )
        # Must not raise.
        _run( hooks.notification_hook( { "message": "x" }, team_io ) )


class TestPreToolHook( unittest.TestCase ):

    def test_non_bash_tool_always_allowed( self ):
        team_io = MagicMock()
        guard = SafetyGuard()
        res = _run( hooks.pre_tool_hook( "Edit", { "file_path": "a.py" }, team_io, guard ) )
        self.assertEqual( res.behavior, "allow" )

    def test_safe_bash_command_allowed( self ):
        team_io = MagicMock()
        guard = SafetyGuard()
        res = _run( hooks.pre_tool_hook( "Bash", { "command": "ls -la" }, team_io, guard ) )
        self.assertEqual( res.behavior, "allow" )

    def test_dangerous_bash_approved_allows( self ):
        team_io = MagicMock()
        team_io.ask_confirmation = AsyncMock( return_value=True )
        guard = SafetyGuard()
        res = _run( hooks.pre_tool_hook( "Bash", { "command": "rm -rf /tmp/x" }, team_io, guard, role="coder" ) )
        self.assertEqual( res.behavior, "allow" )
        team_io.ask_confirmation.assert_awaited_once()

    def test_dangerous_bash_rejected_denies( self ):
        team_io = MagicMock()
        team_io.ask_confirmation = AsyncMock( return_value=False )
        guard = SafetyGuard()
        res = _run( hooks.pre_tool_hook( "Bash", { "command": "git push --force" }, team_io, guard ) )
        self.assertEqual( res.behavior, "deny" )
        self.assertIn( "rejected by user", res.message )

    def test_dangerous_bash_confirmation_exception_denies( self ):
        team_io = MagicMock()
        team_io.ask_confirmation = AsyncMock( side_effect=RuntimeError( "timeout" ) )
        guard = SafetyGuard()
        res = _run( hooks.pre_tool_hook( "Bash", { "command": "DROP TABLE users" }, team_io, guard ) )
        self.assertEqual( res.behavior, "deny" )
        self.assertIn( "Could not confirm", res.message )


class TestPostToolHook( unittest.TestCase ):

    def test_edit_records_file_change( self ):
        guard = SafetyGuard()
        _run( hooks.post_tool_hook( "Edit", { "file_path": "a.py" }, guard ) )
        self.assertEqual( guard.file_changes, 1 )

    def test_write_records_file_change( self ):
        guard = SafetyGuard()
        _run( hooks.post_tool_hook( "Write", { "file_path": "b.py" }, guard ) )
        self.assertEqual( guard.file_changes, 1 )

    def test_read_does_not_record( self ):
        guard = SafetyGuard()
        _run( hooks.post_tool_hook( "Read", { "file_path": "a.py" }, guard ) )
        self.assertEqual( guard.file_changes, 0 )

    def test_edit_missing_file_path_uses_unknown( self ):
        guard = SafetyGuard()
        _run( hooks.post_tool_hook( "Edit", {}, guard ) )  # file_path absent → "unknown"
        self.assertEqual( guard.file_changes, 1 )


class TestBuildCanUseTool( unittest.TestCase ):

    def test_returns_async_closure_delegating_to_pre_tool_hook( self ):
        team_io = MagicMock()
        guard = SafetyGuard()
        cb = hooks.build_can_use_tool( team_io, guard, role="tester" )
        self.assertTrue( callable( cb ) )
        # Non-Bash tool → the closure delegates to pre_tool_hook → Allow.
        res = _run( cb( "Read", { "file_path": "x" }, context=None ) )
        self.assertEqual( res.behavior, "allow" )


class TestWrapPromptForStreaming( unittest.TestCase ):

    def test_yields_single_message_with_given_session_id( self ):
        async def collect():
            return [ m async for m in hooks.wrap_prompt_for_streaming( "do it", session_id="sess-1" ) ]
        msgs = _run( collect() )
        self.assertEqual( len( msgs ), 1 )
        self.assertEqual( msgs[ 0 ][ "session_id" ], "sess-1" )
        self.assertEqual( msgs[ 0 ][ "message" ][ "content" ], "do it" )
        self.assertEqual( msgs[ 0 ][ "type" ], "user" )

    def test_generates_uuid_session_id_when_none( self ):
        async def collect():
            return [ m async for m in hooks.wrap_prompt_for_streaming( "go" ) ]
        msgs = _run( collect() )
        self.assertEqual( len( msgs ), 1 )
        self.assertTrue( len( msgs[ 0 ][ "session_id" ] ) > 0 )  # uuid4 fallback


if __name__ == "__main__":
    unittest.main()
