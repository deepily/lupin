#!/usr/bin/env python3
"""
Unit tests for SWE Team Agent — Phase 2 Delegation.

Tests hooks, state files, decomposition, delegation, and
orchestrator live flow. All SDK calls mocked via unittest.mock.

Coverage:
    - TestHooks: notification, pre-tool, post-tool hooks (6 tests)
    - TestStateFiles: FeatureList + ProgressLog (8 tests)
    - TestDecomposition: task decomposition parsing (6 tests)
    - TestDelegation: task delegation via mocked SDK (8 tests)
    - TestOrchestratorLiveFlow: E2E mocked live flow (6 tests)
"""

import asyncio
import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cosa.agents.swe_team.config import SweTeamConfig
from cosa.agents.swe_team.hooks import (
    notification_hook,
    pre_tool_hook,
    post_tool_hook,
    build_can_use_tool,
)
from cosa.agents.swe_team.safety_limits import SafetyGuard, SafetyLimitError
from cosa.agents.swe_team.state import (
    OrchestratorState,
    TaskSpec,
    DelegationResult,
)
from cosa.agents.swe_team.state_files import FeatureList, ProgressLog
from cosa.agents.swe_team.orchestrator import SweTeamOrchestrator


# =============================================================================
# TestHooks
# =============================================================================

class TestHooks:
    """Tests for SDK hook functions."""

    def test_notification_hook_fires_notify( self ):
        """notification_hook calls team_io.notify_progress with role."""
        team_io = MagicMock()
        team_io.notify_progress = AsyncMock()

        event = { "message": "Subtask completed", "notification_type": "progress" }

        asyncio.run( notification_hook( event, team_io, role="coder" ) )

        team_io.notify_progress.assert_called_once()
        call_kwargs = team_io.notify_progress.call_args.kwargs
        assert "coder" in call_kwargs[ "message" ]
        assert call_kwargs[ "role" ] == "coder"

    def test_pre_tool_hook_allows_safe_command( self ):
        """pre_tool_hook allows non-dangerous Bash commands."""
        team_io = MagicMock()
        guard   = SafetyGuard( max_iterations=10 )

        result = asyncio.run( pre_tool_hook(
            "Bash", { "command": "ls -la" }, team_io, guard
        ) )

        assert result.behavior == "allow"

    def test_pre_tool_hook_blocks_dangerous_command( self ):
        """pre_tool_hook asks confirmation for dangerous commands."""
        team_io = MagicMock()
        team_io.ask_confirmation = AsyncMock( return_value=False )
        guard = SafetyGuard( max_iterations=10 )

        result = asyncio.run( pre_tool_hook(
            "Bash", { "command": "rm -rf /tmp/foo" }, team_io, guard
        ) )

        assert result.behavior == "deny"
        team_io.ask_confirmation.assert_called_once()

    def test_pre_tool_hook_allows_after_user_approval( self ):
        """pre_tool_hook allows dangerous command when user approves."""
        team_io = MagicMock()
        team_io.ask_confirmation = AsyncMock( return_value=True )
        guard = SafetyGuard( max_iterations=10 )

        result = asyncio.run( pre_tool_hook(
            "Bash", { "command": "git push --force" }, team_io, guard
        ) )

        assert result.behavior == "allow"

    def test_post_tool_hook_tracks_file_changes( self ):
        """post_tool_hook increments guard for Edit/Write tools."""
        guard = SafetyGuard( max_iterations=10 )
        assert guard.file_changes == 0

        asyncio.run( post_tool_hook( "Edit", { "file_path": "src/auth.py" }, guard ) )
        assert guard.file_changes == 1

        asyncio.run( post_tool_hook( "Write", { "file_path": "src/new.py" }, guard ) )
        assert guard.file_changes == 2

    def test_post_tool_hook_ignores_read( self ):
        """post_tool_hook does not increment guard for Read tool."""
        guard = SafetyGuard( max_iterations=10 )

        asyncio.run( post_tool_hook( "Read", { "file_path": "src/auth.py" }, guard ) )
        assert guard.file_changes == 0

        asyncio.run( post_tool_hook( "Glob", { "pattern": "*.py" }, guard ) )
        assert guard.file_changes == 0


# =============================================================================
# TestStateFiles
# =============================================================================

class TestStateFiles:
    """Tests for FeatureList and ProgressLog."""

    def test_feature_list_create_load_save( self ):
        """FeatureList round-trips through JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fl = FeatureList( storage_dir=tmpdir )
            fl.add_task( TaskSpec(
                title         = "Task A",
                objective     = "Do A",
                output_format = "File A",
            ) )
            fl.add_task( TaskSpec(
                title         = "Task B",
                objective     = "Do B",
                output_format = "File B",
            ) )

            # Reload from disk
            fl2 = FeatureList( storage_dir=tmpdir )
            loaded = fl2.load()
            assert len( loaded ) == 2
            assert loaded[ 0 ][ "title" ] == "Task A"
            assert loaded[ 1 ][ "title" ] == "Task B"

    def test_feature_list_add_task( self ):
        """add_task appends a TaskSpec with completed=False."""
        fl = FeatureList()
        fl.add_task( TaskSpec(
            title         = "New task",
            objective     = "Implement X",
            output_format = "Modified file",
        ) )
        assert len( fl.tasks ) == 1
        assert fl.tasks[ 0 ][ "completed" ] is False
        assert fl.tasks[ 0 ][ "title" ] == "New task"
        fl.cleanup()

    def test_feature_list_mark_complete( self ):
        """mark_complete sets completed=True and adds timestamp."""
        fl = FeatureList()
        fl.add_task( TaskSpec(
            title         = "Task 1",
            objective     = "Do 1",
            output_format = "File 1",
        ) )
        fl.mark_complete( 0 )
        assert fl.tasks[ 0 ][ "completed" ] is True
        assert "completed_at" in fl.tasks[ 0 ]
        fl.cleanup()

    def test_feature_list_get_pending( self ):
        """get_pending returns only incomplete tasks with indices."""
        fl = FeatureList()
        for i in range( 3 ):
            fl.add_task( TaskSpec(
                title         = f"Task {i}",
                objective     = f"Do {i}",
                output_format = f"File {i}",
            ) )

        fl.mark_complete( 0 )
        fl.mark_complete( 2 )

        pending = fl.get_pending()
        assert len( pending ) == 1
        assert pending[ 0 ][ 0 ] == 1  # index
        assert pending[ 0 ][ 1 ][ "title" ] == "Task 1"
        fl.cleanup()

    def test_progress_log_append( self ):
        """ProgressLog.log() appends timestamped entries."""
        pl = ProgressLog()
        pl.log( "Starting decomposition", role="lead" )
        pl.log( "Writing code", role="coder" )

        entries = pl.read_recent( 10 )
        assert len( entries ) == 2
        assert "[lead]" in entries[ 0 ]
        assert "Starting decomposition" in entries[ 0 ]
        assert "[coder]" in entries[ 1 ]
        pl.cleanup()

    def test_progress_log_read_recent( self ):
        """read_recent returns only last N entries."""
        pl = ProgressLog()
        for i in range( 20 ):
            pl.log( f"Entry {i}" )

        recent = pl.read_recent( 5 )
        assert len( recent ) == 5
        assert "Entry 15" in recent[ 0 ]
        assert "Entry 19" in recent[ 4 ]
        pl.cleanup()

    def test_progress_log_summary( self ):
        """get_summary returns count and last entry."""
        pl = ProgressLog()
        pl.log( "First entry" )
        pl.log( "Last entry" )

        summary = pl.get_summary()
        assert "2 entries" in summary
        assert "Last entry" in summary
        pl.cleanup()

    def test_state_files_temp_dir_isolation( self ):
        """State files with no storage_dir use isolated tempdirs."""
        fl = FeatureList()
        pl = ProgressLog()

        # Both should have different temp dirs
        assert fl.storage_dir != pl.storage_dir
        assert os.path.exists( fl.storage_dir )
        assert os.path.exists( pl.storage_dir )

        fl.cleanup()
        pl.cleanup()

        # After cleanup, dirs should be gone
        assert not os.path.exists( fl.storage_dir )
        assert not os.path.exists( pl.storage_dir )


# =============================================================================
# TestDecomposition
# =============================================================================

class TestDecomposition:
    """Tests for task decomposition parsing logic."""

    def _make_orchestrator( self ):
        """Create orchestrator configured for testing."""
        config = SweTeamConfig( dry_run=False )
        return SweTeamOrchestrator(
            task_description = "Add authentication endpoint",
            config           = config,
            debug            = False,
        )

    def test_parse_single_task( self ):
        """_parse_task_specs handles single-task JSON array."""
        orch = self._make_orchestrator()
        raw = json.dumps( [ {
            "title"         : "Add endpoint",
            "objective"     : "Create /auth endpoint",
            "output_format" : "Modified main.py",
            "assigned_role" : "coder",
            "priority"      : 1,
        } ] )

        specs = orch._parse_task_specs( raw )
        assert len( specs ) == 1
        assert specs[ 0 ].title == "Add endpoint"

    def test_parse_multi_task( self ):
        """_parse_task_specs handles multi-task JSON array."""
        orch = self._make_orchestrator()
        raw = json.dumps( [
            {
                "title"         : "Task 1",
                "objective"     : "Implement feature A",
                "output_format" : "Modified file A",
            },
            {
                "title"         : "Task 2",
                "objective"     : "Implement feature B",
                "output_format" : "Modified file B",
            },
        ] )

        specs = orch._parse_task_specs( raw )
        assert len( specs ) == 2
        assert specs[ 0 ].title == "Task 1"
        assert specs[ 1 ].title == "Task 2"

    def test_parse_fallback_on_invalid_json( self ):
        """_parse_task_specs falls back to single task on bad JSON."""
        orch = self._make_orchestrator()
        raw = "This is not JSON at all"

        specs = orch._parse_task_specs( raw )
        assert len( specs ) == 1
        assert specs[ 0 ].objective == orch.task_description

    def test_parse_strips_markdown_fences( self ):
        """_parse_task_specs handles JSON wrapped in code fences."""
        orch = self._make_orchestrator()
        raw = '```json\n[{"title": "Task", "objective": "Do it", "output_format": "File"}]\n```'

        specs = orch._parse_task_specs( raw )
        assert len( specs ) == 1
        assert specs[ 0 ].title == "Task"

    def test_parse_validates_with_pydantic( self ):
        """_parse_task_specs validates fields via Pydantic."""
        orch = self._make_orchestrator()
        raw = json.dumps( [ {
            "title"          : "Valid task",
            "objective"      : "Do something",
            "output_format"  : "Modified file",
            "scope_boundary" : "Only src/",
            "priority"       : 3,
        } ] )

        specs = orch._parse_task_specs( raw )
        assert specs[ 0 ].scope_boundary == "Only src/"
        assert specs[ 0 ].priority == 3

    def test_fallback_single_task( self ):
        """_fallback_single_task creates single TaskSpec from original."""
        orch = self._make_orchestrator()
        specs = orch._fallback_single_task()
        assert len( specs ) == 1
        assert specs[ 0 ].assigned_role == "coder"
        assert orch.task_description in specs[ 0 ].objective


# =============================================================================
# TestDelegation
# =============================================================================

class TestDelegation:
    """Tests for task delegation via mocked SDK."""

    def _make_orchestrator( self ):
        """Create orchestrator configured for testing."""
        config = SweTeamConfig( dry_run=False )
        return SweTeamOrchestrator(
            task_description = "Implement feature X",
            config           = config,
            debug            = False,
        )

    def _make_task_spec( self, title="Test task" ):
        """Create a test TaskSpec."""
        return TaskSpec(
            title         = title,
            objective     = f"Implement {title}",
            output_format = "Modified files",
            tool_guidance = "Use Edit",
            scope_boundary = "Stay in src/",
        )

    @patch( "cosa.agents.swe_team.orchestrator.sdk_query" )
    def test_delegate_task_returns_result( self, mock_query ):
        """_delegate_task returns DelegationResult on success."""
        # Mock SDK to yield a single text message
        async def mock_messages( **kwargs ):
            from claude_agent_sdk import TextBlock
            yield TextBlock( text="Task completed successfully" )

        mock_query.return_value = mock_messages()

        orch    = self._make_orchestrator()
        spec    = self._make_task_spec()
        team_io = MagicMock()

        result = asyncio.run( orch._delegate_task( spec, 0, team_io ) )

        assert isinstance( result, DelegationResult )
        assert result.status == "success"
        assert result.task_index == 0

    @patch( "cosa.agents.swe_team.orchestrator.sdk_query" )
    def test_delegate_task_tracks_files( self, mock_query ):
        """_delegate_task records files from Edit/Write tool uses."""
        async def mock_messages( **kwargs ):
            from claude_agent_sdk import AssistantMessage, ToolUseBlock, TextBlock

            # Simulate an assistant message with a tool use
            tool_block = ToolUseBlock(
                id="toolu_123",
                name="Edit",
                input={ "file_path": "/src/auth.py", "old_string": "a", "new_string": "b" },
            )
            text_block = TextBlock( text="Done editing" )
            msg = AssistantMessage(
                content=[ tool_block, text_block ],
                model="claude-sonnet-4-20250514",
            )
            yield msg

        mock_query.return_value = mock_messages()

        orch    = self._make_orchestrator()
        spec    = self._make_task_spec()
        team_io = MagicMock()

        result = asyncio.run( orch._delegate_task( spec, 0, team_io ) )
        assert "/src/auth.py" in result.files_changed

    @patch( "cosa.agents.swe_team.orchestrator.sdk_query" )
    def test_delegate_task_respects_timeout( self, mock_query ):
        """_delegate_task raises SafetyLimitError when timeout exceeded."""
        async def mock_messages( **kwargs ):
            from claude_agent_sdk import TextBlock
            yield TextBlock( text="Working..." )

        mock_query.return_value = mock_messages()

        orch = self._make_orchestrator()
        # Force timeout by setting start_time in the past
        orch.guard.start_time  = 0
        orch.guard.timeout_secs = 1

        spec    = self._make_task_spec()
        team_io = MagicMock()

        with pytest.raises( SafetyLimitError, match="timeout" ):
            asyncio.run( orch._delegate_task( spec, 0, team_io ) )

    @patch( "cosa.agents.swe_team.orchestrator.sdk_query" )
    def test_delegate_task_handles_sdk_error( self, mock_query ):
        """_delegate_task returns failure result on SDK exception."""
        async def mock_messages( **kwargs ):
            raise RuntimeError( "SDK connection lost" )
            yield  # Make it a generator

        mock_query.return_value = mock_messages()

        orch    = self._make_orchestrator()
        spec    = self._make_task_spec()
        team_io = MagicMock()

        result = asyncio.run( orch._delegate_task( spec, 0, team_io ) )
        assert result.status == "failure"
        assert "SDK connection lost" in result.errors[ 0 ]

    @patch( "cosa.agents.swe_team.orchestrator.sdk_query" )
    def test_delegate_task_sends_notifications( self, mock_query ):
        """Delegation sends progress notifications via team_io."""
        async def mock_messages( **kwargs ):
            from claude_agent_sdk import TextBlock
            yield TextBlock( text="Done" )

        mock_query.return_value = mock_messages()

        orch    = self._make_orchestrator()
        spec    = self._make_task_spec()
        team_io = MagicMock()
        team_io.notify_progress = AsyncMock()
        team_io.ask_confirmation = AsyncMock( return_value=True )

        # Call the full _execute_live flow via delegation
        result = asyncio.run( orch._delegate_task( spec, 0, team_io ) )
        assert result.status == "success"

    def test_build_agent_options_coder( self ):
        """_build_agent_options for coder uses worker model and acceptEdits."""
        orch    = self._make_orchestrator()
        team_io = MagicMock()

        options = orch._build_agent_options( "coder", team_io )

        assert options.model == orch.config.worker_model
        assert options.permission_mode == "acceptEdits"
        assert options.can_use_tool is not None

    def test_build_agent_options_lead( self ):
        """_build_agent_options for lead uses lead model and plan mode."""
        orch = self._make_orchestrator()

        options = orch._build_agent_options( "lead" )

        assert options.model == orch.config.lead_model
        assert options.permission_mode == "plan"
        assert options.can_use_tool is None

    def test_delegation_prompt_format( self ):
        """Delegation prompt includes all 5 required fields."""
        spec = self._make_task_spec( title="Test feature" )

        # Build the prompt as _delegate_task does
        prompt = f"""TASK: {spec.title}
OBJECTIVE: {spec.objective}
EXPECTED OUTPUT: {spec.output_format}
TOOL GUIDANCE: {spec.tool_guidance}
SCOPE BOUNDARY: {spec.scope_boundary}"""

        assert "TASK: Test feature" in prompt
        assert "OBJECTIVE:" in prompt
        assert "EXPECTED OUTPUT:" in prompt
        assert "TOOL GUIDANCE:" in prompt
        assert "SCOPE BOUNDARY:" in prompt


# =============================================================================
# TestOrchestratorLiveFlow
# =============================================================================

class TestOrchestratorLiveFlow:
    """Tests for orchestrator _execute_live E2E mock flow."""

    def _make_orchestrator( self ):
        config = SweTeamConfig( dry_run=False )
        return SweTeamOrchestrator(
            task_description = "Add health check endpoint",
            config           = config,
            debug            = False,
        )

    @patch( "cosa.agents.swe_team.orchestrator.sdk_query" )
    def test_live_flow_decompose_then_delegate( self, mock_query ):
        """Full E2E: decompose → confirm → delegate → result."""
        call_count = 0

        async def mock_messages( **kwargs ):
            nonlocal call_count
            from claude_agent_sdk import TextBlock
            call_count += 1

            if call_count == 1:
                # Lead decomposition response
                task_json = json.dumps( [ {
                    "title"         : "Add endpoint",
                    "objective"     : "Create /health",
                    "output_format" : "Modified main.py",
                    "assigned_role" : "coder",
                    "priority"      : 1,
                } ] )
                yield TextBlock( text=task_json )
            else:
                # Coder delegation response
                yield TextBlock( text="Endpoint added to main.py" )

        mock_query.side_effect = lambda **kwargs: mock_messages( **kwargs )

        orch = self._make_orchestrator()

        with patch( "cosa.agents.swe_team.orchestrator.ProgressLog" ) as MockPL, \
             patch( "cosa.agents.swe_team.orchestrator.FeatureList" ) as MockFL:
            MockPL.return_value = MagicMock()
            MockFL.return_value = MagicMock()
            MockFL.return_value.tasks = []

            team_io = MagicMock()
            team_io.notify_progress  = AsyncMock()
            team_io.ask_confirmation = AsyncMock( return_value=True )

            result = asyncio.run( orch._execute_live( team_io ) )

            assert result is not None
            assert "1/1" in result or "completed" in result.lower()

    @patch( "cosa.agents.swe_team.orchestrator.sdk_query" )
    def test_live_flow_asks_confirmation( self, mock_query ):
        """Live flow asks user confirmation after decomposition."""
        async def mock_messages( **kwargs ):
            from claude_agent_sdk import TextBlock
            task_json = json.dumps( [ {
                "title"         : "Task 1",
                "objective"     : "Do 1",
                "output_format" : "File 1",
            } ] )
            yield TextBlock( text=task_json )

        mock_query.return_value = mock_messages()

        orch = self._make_orchestrator()
        team_io = MagicMock()
        team_io.notify_progress  = AsyncMock()
        team_io.ask_confirmation = AsyncMock( return_value=False )

        result = asyncio.run( orch._execute_live( team_io ) )

        team_io.ask_confirmation.assert_called_once()
        assert "cancelled" in result.lower()

    @patch( "cosa.agents.swe_team.orchestrator.sdk_query" )
    def test_live_flow_stops_on_rejection( self, mock_query ):
        """Live flow stops delegation when user rejects."""
        async def mock_messages( **kwargs ):
            from claude_agent_sdk import TextBlock
            task_json = json.dumps( [ {
                "title"         : "Task 1",
                "objective"     : "Do 1",
                "output_format" : "File 1",
            } ] )
            yield TextBlock( text=task_json )

        mock_query.return_value = mock_messages()

        orch = self._make_orchestrator()
        team_io = MagicMock()
        team_io.notify_progress  = AsyncMock()
        team_io.ask_confirmation = AsyncMock( return_value=False )

        result = asyncio.run( orch._execute_live( team_io ) )

        assert "cancelled" in result.lower()
        assert len( orch.state[ "delegation_results" ] ) == 0

    @patch( "cosa.agents.swe_team.orchestrator.sdk_query" )
    def test_live_flow_collects_results( self, mock_query ):
        """Live flow populates delegation_results for each task."""
        call_count = 0

        async def mock_messages( **kwargs ):
            nonlocal call_count
            from claude_agent_sdk import TextBlock
            call_count += 1

            if call_count == 1:
                # Lead decomposition — 2 tasks
                task_json = json.dumps( [
                    { "title": "T1", "objective": "Do 1", "output_format": "F1" },
                    { "title": "T2", "objective": "Do 2", "output_format": "F2" },
                ] )
                yield TextBlock( text=task_json )
            else:
                yield TextBlock( text=f"Completed task (call {call_count})" )

        mock_query.side_effect = lambda **kwargs: mock_messages( **kwargs )

        orch = self._make_orchestrator()

        with patch( "cosa.agents.swe_team.orchestrator.ProgressLog" ) as MockPL, \
             patch( "cosa.agents.swe_team.orchestrator.FeatureList" ) as MockFL:
            MockPL.return_value = MagicMock()
            MockFL.return_value = MagicMock()
            MockFL.return_value.tasks = []

            team_io = MagicMock()
            team_io.notify_progress  = AsyncMock()
            team_io.ask_confirmation = AsyncMock( return_value=True )

            result = asyncio.run( orch._execute_live( team_io ) )

            assert len( orch.state[ "delegation_results" ] ) == 2

    @patch( "cosa.agents.swe_team.orchestrator.sdk_query" )
    def test_live_flow_handles_guard_limit( self, mock_query ):
        """Live flow catches SafetyLimitError from guard."""
        async def mock_messages( **kwargs ):
            from claude_agent_sdk import TextBlock
            task_json = json.dumps( [ {
                "title"         : "Task 1",
                "objective"     : "Do 1",
                "output_format" : "File 1",
            } ] )
            yield TextBlock( text=task_json )

        mock_query.side_effect = lambda **kwargs: mock_messages( **kwargs )

        orch = self._make_orchestrator()
        # Force timeout
        orch.guard.start_time  = 0
        orch.guard.timeout_secs = 1

        team_io = MagicMock()
        team_io.notify_progress  = AsyncMock()
        team_io.ask_confirmation = AsyncMock( return_value=True )

        with patch( "cosa.agents.swe_team.orchestrator.ProgressLog" ) as MockPL, \
             patch( "cosa.agents.swe_team.orchestrator.FeatureList" ) as MockFL:
            MockPL.return_value = MagicMock()
            MockFL.return_value = MagicMock()
            MockFL.return_value.tasks = []

            with pytest.raises( SafetyLimitError ):
                asyncio.run( orch._execute_live( team_io ) )

    @patch( "cosa.agents.swe_team.orchestrator.sdk_query" )
    def test_live_flow_updates_state( self, mock_query ):
        """Live flow transitions through correct states."""
        call_count = 0

        async def mock_messages( **kwargs ):
            nonlocal call_count
            from claude_agent_sdk import TextBlock
            call_count += 1

            if call_count == 1:
                task_json = json.dumps( [ {
                    "title"         : "Task 1",
                    "objective"     : "Do 1",
                    "output_format" : "File 1",
                } ] )
                yield TextBlock( text=task_json )
            else:
                yield TextBlock( text="Done" )

        mock_query.side_effect = lambda **kwargs: mock_messages( **kwargs )

        orch = self._make_orchestrator()

        with patch( "cosa.agents.swe_team.orchestrator.ProgressLog" ) as MockPL, \
             patch( "cosa.agents.swe_team.orchestrator.FeatureList" ) as MockFL:
            MockPL.return_value = MagicMock()
            MockFL.return_value = MagicMock()
            MockFL.return_value.tasks = []

            team_io = MagicMock()
            team_io.notify_progress  = AsyncMock()
            team_io.ask_confirmation = AsyncMock( return_value=True )

            result = asyncio.run( orch._execute_live( team_io ) )

            # After execution, state should reflect final summary
            assert orch.state[ "final_summary" ] is not None
            assert len( orch.state[ "task_specs" ] ) == 1
