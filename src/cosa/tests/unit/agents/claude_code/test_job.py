"""
Unit tests for cosa.agents.claude_code.job (ClaudeCodeJob).

NEW FILE 2026-05-31 by Extra 2 🪨 (CoSA coverage campaign, claude_code lane — finale).
ClaudeCodeJob is the AgenticJobBase subclass bridging do_all() → async _execute() via
asyncio.run(), with BOUNDED/INTERACTIVE task types and BOUNDED/INTERACTIVE dry-run
simulations. The ClaudeCodeDispatcher / Task / TaskType, cosa_interface.notify_progress,
and asyncio.sleep are boundary-mocked → ZERO real SDK / subprocess / network / sleep.
MessageHistory (interactive dry-run) is the real pure in-process type.

SCOUT: do_all + _execute + both dry-run paths read carefully — NO prod bug (defensive
throughout; success/failure artifacts + the cost/duration/output ternaries all correct).

Must run via run-sdk-cov.sh (job imports the SDK chain).
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from cosa.agents.claude_code.job import ClaudeCodeJob
from cosa.rest.job_state import JobState
import cosa.agents.claude_code.cosa_interface as ci_mod


def make_job( **over ):
    defaults = dict(
        prompt="Run the tests", project="lupin", user_id="u1",
        user_email="e@x.com", session_id="s1", task_type="BOUNDED", debug=False,
    )
    defaults.update( over )
    return ClaudeCodeJob( **defaults )


def make_result( success=True, cost_usd=0.05, result="the output", session_id="sess",
                 duration_ms=1500, error=None, exit_code=0 ):
    return SimpleNamespace(
        success=success, cost_usd=cost_usd, result=result, session_id=session_id,
        duration_ms=duration_ms, error=error, exit_code=exit_code,
    )


class TestConfigDefaults( unittest.TestCase ):
    """
    BUG #3 (FIXED 2026-05-31): job.py:84 imported `cosa.app.configuration_manager`,
    which does NOT exist (real module: cosa.config.configuration_manager). The import
    raised ModuleNotFoundError on every call, swallowed by the bare `except Exception:
    pass`, so the INI keys `claude code job max turns default` / `claude code job
    timeout seconds default` were never read — the job silently used hardcoded 50/3600.
    Tiberius fixed the import (cosa.app → cosa.config); :85-87 are now reachable. The
    xfail tripwire is removed; the fallback test now triggers the except via a raising
    ConfigurationManager.
    """

    def tearDown( self ):
        ClaudeCodeJob._config_defaults_loaded = False
        ClaudeCodeJob._default_max_turns = 50
        ClaudeCodeJob._default_timeout = 3600

    def test_config_load_exception_falls_back_to_hardcoded( self ):
        # If ConfigurationManager construction/read raises, the bare except swallows it
        # and the hardcoded defaults stand. Covers the (now-valid) import + the
        # try/except fallback at job.py:84-90.
        ClaudeCodeJob._config_defaults_loaded = False
        ClaudeCodeJob._default_max_turns = 50
        with patch( "cosa.config.configuration_manager.ConfigurationManager", side_effect=RuntimeError( "config unavailable" ) ):
            ClaudeCodeJob._load_config_defaults()
        self.assertTrue( ClaudeCodeJob._config_defaults_loaded )
        self.assertEqual( ClaudeCodeJob._default_max_turns, 50 )   # except → defaults unchanged

    def test_already_loaded_early_return( self ):
        ClaudeCodeJob._config_defaults_loaded = True
        ClaudeCodeJob._default_max_turns = 42
        ClaudeCodeJob._load_config_defaults()                       # early return, no reload
        self.assertEqual( ClaudeCodeJob._default_max_turns, 42 )

    def test_config_defaults_loaded_from_ini( self ):
        # Defaults are read from ConfigurationManager and override the hardcoded values.
        # Was an armed xfail-strict TRIPWIRE while job.py imported the nonexistent
        # cosa.app.configuration_manager (ModuleNotFoundError swallowed → :85-87 dead);
        # de-armed once the cosa.app→cosa.config import fix landed.
        ClaudeCodeJob._config_defaults_loaded = False
        cfg = MagicMock()
        cfg.get.side_effect = lambda key, default=None, return_type=None: (
            77 if "max turns" in key else 999
        )
        with patch( "cosa.config.configuration_manager.ConfigurationManager", return_value=cfg ):
            ClaudeCodeJob._load_config_defaults()
        self.assertEqual( ClaudeCodeJob._default_max_turns, 77 )
        self.assertEqual( ClaudeCodeJob._default_timeout, 999 )


class TestConstruction( unittest.TestCase ):

    def test_defaults_and_uppercasing( self ):
        job = make_job( task_type="bounded" )
        self.assertEqual( job.task_type, "BOUNDED" )
        self.assertEqual( job.max_turns, 50 )
        self.assertEqual( job.timeout_seconds, 3600 )
        self.assertEqual( job.state, JobState.PENDING )

    def test_explicit_overrides( self ):
        job = make_job( task_type="INTERACTIVE", max_turns=200, timeout_seconds=120 )
        self.assertEqual( job.max_turns, 200 )
        self.assertEqual( job.timeout_seconds, 120 )

    def test_class_constants( self ):
        self.assertEqual( ClaudeCodeJob.JOB_TYPE, "claude_code" )
        self.assertEqual( ClaudeCodeJob.JOB_PREFIX, "cc" )

    def test_last_question_asked_bounded_short( self ):
        job = make_job( prompt="short", task_type="BOUNDED" )
        self.assertEqual( job.last_question_asked, "[Claude Code - Bounded] short" )

    def test_last_question_asked_interactive_truncated( self ):
        job = make_job( prompt="x" * 80, task_type="INTERACTIVE" )
        lqa = job.last_question_asked
        self.assertIn( "[Claude Code - Interactive]", lqa )
        self.assertIn( "...", lqa )


class TestDoAll( unittest.TestCase ):

    def test_success( self ):
        job = make_job( debug=True )
        job._execute = AsyncMock( return_value="done" )
        self.assertEqual( job.do_all(), "done" )
        self.assertEqual( job.state, JobState.COMPLETED )
        self.assertEqual( job.answer_conversational, "done" )

    def test_success_no_debug( self ):
        job = make_job( debug=False )
        job._execute = AsyncMock( return_value="ok" )
        job.do_all()
        self.assertEqual( job.state, JobState.COMPLETED )

    def test_exception_reraises_debug( self ):
        job = make_job( debug=True )
        job._execute = AsyncMock( side_effect=RuntimeError( "boom" ) )
        with self.assertRaises( RuntimeError ):
            job.do_all()
        self.assertEqual( job.state, JobState.FAILED )
        self.assertIn( "boom", job.error )

    def test_exception_reraises_no_debug( self ):
        job = make_job( debug=False )
        job._execute = AsyncMock( side_effect=RuntimeError( "boom" ) )
        with self.assertRaises( RuntimeError ):
            job.do_all()
        self.assertEqual( job.state, JobState.FAILED )


@patch( "cosa.agents.claude_code.cosa_interface.notify_progress", new_callable=AsyncMock )
@patch( "cosa.orchestration.claude_code.TaskType" )
@patch( "cosa.orchestration.claude_code.Task" )
@patch( "cosa.orchestration.claude_code.ClaudeCodeDispatcher" )
class TestExecuteReal( unittest.IsolatedAsyncioTestCase ):

    async def test_success_bounded( self, MockDispatcher, MockTask, MockTaskType, mock_notify ):
        MockDispatcher.return_value.dispatch = AsyncMock( return_value=make_result() )
        job = make_job( task_type="BOUNDED", debug=True )
        result = await job._execute()
        self.assertIn( "Claude Code task completed", result )
        self.assertEqual( job.cost_usd, 0.05 )
        self.assertEqual( job.artifacts[ "task_type" ], "BOUNDED" )

    async def test_success_interactive( self, MockDispatcher, MockTask, MockTaskType, mock_notify ):
        MockDispatcher.return_value.dispatch = AsyncMock( return_value=make_result() )
        job = make_job( task_type="INTERACTIVE" )
        result = await job._execute()
        self.assertIn( "Claude Code task completed", result )

    async def test_success_zero_cost_none_duration_no_output( self, MockDispatcher, MockTask, MockTaskType, mock_notify ):
        # cost_usd 0 → "$0.00"; duration_ms None → "N/A"; output_text "" → fallbacks.
        MockDispatcher.return_value.dispatch = AsyncMock(
            return_value=make_result( cost_usd=0.0, duration_ms=None, result="" )
        )
        job = make_job( task_type="BOUNDED" )
        result = await job._execute()
        self.assertIn( "$0.00", result )

    async def test_failure_raises_runtime_error( self, MockDispatcher, MockTask, MockTaskType, mock_notify ):
        MockDispatcher.return_value.dispatch = AsyncMock(
            return_value=make_result( success=False, error="exploded", exit_code=2 )
        )
        job = make_job()
        with self.assertRaises( RuntimeError ):
            await job._execute()
        self.assertEqual( job.artifacts[ "error" ], "exploded" )

    async def test_failure_no_error_message( self, MockDispatcher, MockTask, MockTaskType, mock_notify ):
        MockDispatcher.return_value.dispatch = AsyncMock(
            return_value=make_result( success=False, error=None )
        )
        job = make_job()
        with self.assertRaises( RuntimeError ):
            await job._execute()


class TestExecuteDryRunDispatch( unittest.IsolatedAsyncioTestCase ):

    async def test_routes_to_interactive( self ):
        job = make_job( task_type="INTERACTIVE", dry_run=True )
        job._execute_dry_run_interactive = AsyncMock( return_value="interactive" )
        self.assertEqual( await job._execute(), "interactive" )

    async def test_routes_to_bounded( self ):
        job = make_job( task_type="BOUNDED", dry_run=True )
        job._execute_dry_run_bounded = AsyncMock( return_value="bounded" )
        self.assertEqual( await job._execute(), "bounded" )


@patch( "cosa.agents.claude_code.cosa_interface.notify_progress", new_callable=AsyncMock )
@patch( "asyncio.sleep", new_callable=AsyncMock )
class TestDryRunBounded( unittest.IsolatedAsyncioTestCase ):

    async def test_default_phases_debug( self, mock_sleep, mock_notify ):
        job = make_job( task_type="BOUNDED", dry_run=True, debug=True )
        result = await job._execute_dry_run_bounded()
        self.assertIn( "Mock Bounded execution", result )
        self.assertEqual( job.cost_usd, 0.0 )
        self.assertTrue( job.artifacts[ "dry_run" ] )
        # default phases = all 5 labels → 5 phase notifies + 1 completion
        self.assertEqual( mock_notify.await_count, 6 )

    async def test_custom_phases_and_delay( self, mock_sleep, mock_notify ):
        job = make_job( task_type="BOUNDED", dry_run=True, dry_run_phases=2, dry_run_delay=0.0, debug=False )
        await job._execute_dry_run_bounded()
        # 2 phase notifies + 1 completion
        self.assertEqual( mock_notify.await_count, 3 )


@patch( "cosa.agents.claude_code.cosa_interface.notify_progress", new_callable=AsyncMock )
@patch( "asyncio.sleep", new_callable=AsyncMock )
class TestDryRunInteractive( unittest.IsolatedAsyncioTestCase ):

    async def test_default_phases_debug( self, mock_sleep, mock_notify ):
        # default 7 phases + debug=True exercises every `if num_phases >= N` true arm
        # and the debug asserts (conversation_turns == 5).
        job = make_job( task_type="INTERACTIVE", dry_run=True, debug=True )
        result = await job._execute_dry_run_interactive()
        self.assertIn( "conversation turns", result )
        self.assertEqual( job.artifacts[ "conversation_turns" ], 5 )

    async def test_zero_phases_no_debug( self, mock_sleep, mock_notify ):
        # num_phases=0 → every `if num_phases >= N` false arm; debug=False skips asserts.
        job = make_job( task_type="INTERACTIVE", dry_run=True, dry_run_phases=0, debug=False )
        result = await job._execute_dry_run_interactive()
        self.assertIn( "Mock Interactive session", result )
        # only the final completion notify fires (all 7 phase notifies skipped)
        self.assertEqual( mock_notify.await_count, 1 )


class TestOnMessageCallback( unittest.TestCase ):

    def test_debug_dict_message( self ):
        job = make_job( debug=True )
        job._on_message_callback( "task-1", { "type": "assistant" } )   # dict → .get path

    def test_debug_non_dict_message( self ):
        job = make_job( debug=True )
        job._on_message_callback( "task-1", SimpleNamespace() )         # non-dict → type().__name__

    def test_no_debug_noop( self ):
        job = make_job( debug=False )
        job._on_message_callback( "task-1", { "type": "x" } )           # no-op


if __name__ == "__main__":
    unittest.main()
