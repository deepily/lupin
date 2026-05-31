"""
Unit tests for cosa.agents.deep_research.job (DeepResearchJob).

NEW FILE 2026-05-31 by Extra 2 🪨 (CoSA coverage campaign, deep_research SDK/network
tier). DeepResearchJob is the AgenticJobBase subclass that bridges the sync queue
entrypoint do_all() to the async _execute() via asyncio.run(). Every collaborator
(voice_io, cosa_interface, ConfigurationManager, Gister, ResearchConfig.from_config,
CostTracker, cli.run_research / generate_abstract_for_cli / save_report_with_frontmatter,
cu.get_project_root) is boundary-mocked — ZERO API/network/voice/fs I/O, ZERO spend.
asyncio.sleep is patched out so the dry-run breadcrumbs don't actually sleep.

BUDGET-BUG (FIXED 2026-05-31): test_budget_exceeded_notifies_and_reraises was an
armed xfail-strict TRIPWIRE pinning a CONFIRMED PROD BUG at job.py:374 — the
BudgetExceededError handler read `e.current_cost` / `e.budget_limit`, but
deep_research's BudgetExceededError was a bare `Exception` raised with only a string
(cost_tracker.py:207). A real budget-exceed raised AttributeError inside the handler,
the intended voice notification never fired, and line 379's `raise` was unreachable.
Tiberius fixed it (cost_tracker.py: BudgetExceededError now carries current_cost +
budget_limit, passed at the raise site). The xfail is removed; the test now asserts
the working contract (formatted budget notification + re-raise + line 379 reachable).

Must run via run-sdk-cov.sh (job imports the SDK chain through cli).
"""

import unittest
from contextlib import contextmanager, ExitStack
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from cosa.agents.deep_research.job import DeepResearchJob
from cosa.agents.deep_research.cost_tracker import SessionSummary, BudgetExceededError
from cosa.rest.job_state import JobState
import cosa.agents.deep_research.voice_io as voice_io_mod
import cosa.agents.deep_research.cosa_interface as ci_mod


def make_job( **over ):
    defaults = dict(
        query="Compare frameworks", user_id="u1", user_email="e@x.com",
        session_id="s1", debug=False,
    )
    defaults.update( over )
    return DeepResearchJob( **defaults )


def make_summary():
    return SessionSummary(
        duration_seconds=2.5, total_cost_usd=0.1234,
        total_input_tokens=100, total_output_tokens=200,
    )


@contextmanager
def execute_env(
    cfg_values=None, gist="My Research Topic",
    run_research_result="THE REPORT", run_research_error=None,
    project_root="/proj",
):
    """Patch every _execute() collaborator. Yields a dict of the key mocks."""
    values = {
        "deep research storage backend"  : "local",
        "deep research gcs bucket"        : None,
        "deep research output directory"  : "/io/deep-research",
    }
    if cfg_values:
        values.update( cfg_values )

    cfg = MagicMock()
    cfg.get.side_effect = lambda key, default=None: values.get( key, default )

    gister = MagicMock()
    gister.get_gist.return_value = gist

    mock_config = MagicMock()

    tracker = MagicMock()
    tracker.get_summary.return_value = make_summary()

    if run_research_error is not None:
        run_research = AsyncMock( side_effect=run_research_error )
    else:
        run_research = AsyncMock( return_value=run_research_result )

    with ExitStack() as stack:
        stack.enter_context( patch( "cosa.config.configuration_manager.ConfigurationManager", return_value=cfg ) )
        stack.enter_context( patch( "cosa.memory.gister.Gister", return_value=gister ) )
        stack.enter_context( patch( "cosa.agents.deep_research.config.ResearchConfig.from_config", return_value=mock_config ) )
        stack.enter_context( patch( "cosa.agents.deep_research.cost_tracker.CostTracker", return_value=tracker ) )
        stack.enter_context( patch( "cosa.agents.deep_research.cli.run_research", run_research ) )
        stack.enter_context( patch( "cosa.agents.deep_research.cli.generate_abstract_for_cli", new=AsyncMock( return_value="ABSTRACT" ) ) )
        stack.enter_context( patch( "cosa.agents.deep_research.cli.save_report_with_frontmatter", return_value="/path/report.md" ) )
        stack.enter_context( patch( "cosa.utils.util.get_project_root", return_value=project_root ) )

        stack.enter_context( patch.object( voice_io_mod, "reconfigure" ) )
        stack.enter_context( patch.object( voice_io_mod, "notify", new=AsyncMock() ) )
        stack.enter_context( patch.object( voice_io_mod, "set_job_id" ) )
        stack.enter_context( patch.object( voice_io_mod, "clear_job_id" ) )

        stack.enter_context( patch.object( ci_mod, "_get_sender_id", return_value="dr.research@x#abc" ) )
        stack.enter_context( patch.object( ci_mod, "set_dispatch_context" ) )
        stack.enter_context( patch.object( ci_mod, "SENDER_ID", "orig" ) )
        stack.enter_context( patch.object( ci_mod, "TARGET_USER", None ) )
        stack.enter_context( patch.object( ci_mod, "SESSION_NAME", None ) )

        yield {
            "cfg": cfg, "gister": gister, "config": mock_config, "tracker": tracker,
            "run_research": run_research, "notify": voice_io_mod.notify,
        }


# ===========================================================================
# Construction + property
# ===========================================================================
class TestConstruction( unittest.TestCase ):

    def test_init_stores_params( self ):
        job = make_job( query="X", budget=2.0, lead_model="m", audience="expert" )
        self.assertEqual( job.query, "X" )
        self.assertEqual( job.budget, 2.0 )
        self.assertEqual( job.lead_model, "m" )
        self.assertEqual( job.audience, "expert" )
        self.assertEqual( job.state, JobState.PENDING )
        self.assertIsNone( job.report_path )

    def test_class_constants( self ):
        self.assertEqual( DeepResearchJob.JOB_TYPE, "deep_research" )
        self.assertEqual( DeepResearchJob.JOB_PREFIX, "dr" )

    def test_last_question_asked( self ):
        job = make_job( query="my query" )
        self.assertEqual( job.last_question_asked, "[Deep Research] my query" )


# ===========================================================================
# do_all() — the asyncio.run bridge
# ===========================================================================
class TestDoAll( unittest.TestCase ):

    def test_success_completed( self ):
        job = make_job( debug=True )
        job._execute = AsyncMock( return_value="the answer" )
        result = job.do_all()
        self.assertEqual( result, "the answer" )
        self.assertEqual( job.state, JobState.COMPLETED )
        self.assertEqual( job.answer_conversational, "the answer" )
        self.assertIsNotNone( job.completed_at )

    def test_success_completed_no_debug( self ):
        job = make_job( debug=False )
        job._execute = AsyncMock( return_value="ans" )
        self.assertEqual( job.do_all(), "ans" )
        self.assertEqual( job.state, JobState.COMPLETED )

    def test_cancelled_path( self ):
        job = make_job( debug=True )
        job._cancel_requested = True
        job._execute = AsyncMock( return_value="partial" )
        result = job.do_all()
        self.assertEqual( job.state, JobState.CANCELLED )
        self.assertEqual( result, "partial" )
        self.assertEqual( job.error, "Cancelled by user request" )

    def test_cancelled_path_no_debug( self ):
        job = make_job( debug=False )
        job._cancel_requested = True
        job._execute = AsyncMock( return_value="partial2" )
        job.do_all()
        self.assertEqual( job.state, JobState.CANCELLED )

    def test_exception_sets_failed_and_reraises( self ):
        job = make_job( debug=True )
        job._execute = AsyncMock( side_effect=RuntimeError( "boom" ) )
        with self.assertRaises( RuntimeError ):
            job.do_all()
        self.assertEqual( job.state, JobState.FAILED )
        self.assertIn( "boom", job.error )
        self.assertEqual( job.answer_conversational, "Research failed: boom" )


# ===========================================================================
# _execute() — live research path
# ===========================================================================
class TestExecute( unittest.IsolatedAsyncioTestCase ):

    async def test_happy_path_returns_conversational_answer( self ):
        job = make_job( debug=True, lead_model="lead-x", audience="expert", audience_context="ctx" )
        with execute_env() as m:
            result = await job._execute()
        self.assertIn( "Research complete", result )
        self.assertEqual( job.report, "THE REPORT" )
        self.assertEqual( job.abstract, "ABSTRACT" )
        self.assertEqual( job.report_path, "/path/report.md" )
        self.assertEqual( job.artifacts[ "report_path" ], "/path/report.md" )
        self.assertIn( "cost_summary", job.artifacts )
        # lead_model / audience / audience_context override arms (282-287)
        self.assertEqual( m[ "config" ].lead_model, "lead-x" )
        self.assertEqual( m[ "config" ].audience, "expert" )
        self.assertEqual( m[ "config" ].audience_context, "ctx" )

    async def test_happy_path_no_overrides( self ):
        # lead_model / audience / audience_context all None → skip 282-287 true arms
        job = make_job( debug=False )
        with execute_env() as m:
            result = await job._execute()
        self.assertIn( "Research complete", result )

    async def test_run_research_returns_none_is_cancelled( self ):
        job = make_job()
        with execute_env( run_research_result=None ) as m:
            result = await job._execute()
        self.assertEqual( result, "Research was cancelled by the user." )

    async def test_empty_gist_falls_back_to_default_session_name( self ):
        # gist "   " → lowered/stripped empty → 240-241 fallback
        job = make_job()
        with execute_env( gist="   " ) as m:
            await job._execute()
        m[ "gister" ].get_gist.assert_called_once()

    async def test_output_dir_relative_prefixes_project_root( self ):
        # 231 true arm: relative path → project_root + "/" + dir
        job = make_job()
        with execute_env( cfg_values={ "deep research output directory": "io/dr" } ):
            await job._execute()  # must not raise

    async def test_output_dir_absolute_already_under_root_unchanged( self ):
        # 231 false + 233 false arm: already absolute under project_root
        job = make_job()
        with execute_env( cfg_values={ "deep research output directory": "/proj/io/dr" } ):
            await job._execute()

    async def test_generic_exception_notifies_urgent_and_reraises( self ):
        job = make_job()
        with execute_env( run_research_error=ValueError( "kaboom" ) ) as m:
            with self.assertRaises( ValueError ):
                await job._execute()
        # urgent error notification fired (381-388)
        self.assertTrue( m[ "notify" ].await_count >= 1 )

    async def test_budget_exceeded_notifies_and_reraises( self ):
        # Post-fix contract (BudgetExceededError now carries current_cost/budget_limit):
        # the handler formats the "Budget exceeded" notification from those attrs, then
        # re-raises BudgetExceededError (job.py:379 — now reachable). Was an armed
        # xfail-strict TRIPWIRE while the bug stood (handler hit AttributeError on the
        # bare-Exception error); de-armed once the cost_tracker fix landed.
        job = make_job( budget=0.01 )
        err = BudgetExceededError( "Budget limit $0.01 would be exceeded", current_cost=0.0317, budget_limit=0.01 )
        with execute_env( run_research_error=err ) as m:
            with self.assertRaises( BudgetExceededError ):
                await job._execute()
        budget_msgs = [ c for c in m[ "notify" ].call_args_list if "Budget exceeded" in str( c ) ]
        self.assertTrue( budget_msgs, "expected a 'Budget exceeded' notification" )
        # the carried attrs are formatted into the spoken message
        self.assertIn( "$0.03 spent of $0.01 limit", str( budget_msgs[ 0 ] ) )


# ===========================================================================
# _execute() — dry-run path
# ===========================================================================
class TestExecuteDryRun( unittest.IsolatedAsyncioTestCase ):

    async def test_dry_run_happy_path( self ):
        job = make_job( dry_run=True, debug=True )
        with patch( "asyncio.sleep", new=AsyncMock() ), \
             patch.object( voice_io_mod, "notify", new=AsyncMock() ) as mock_notify, \
             patch.object( voice_io_mod, "reconfigure" ), \
             patch.object( voice_io_mod, "set_job_id" ), \
             patch.object( voice_io_mod, "clear_job_id" ), \
             patch.object( ci_mod, "_get_sender_id", return_value="dr#x" ), \
             patch.object( ci_mod, "set_dispatch_context" ), \
             patch.object( ci_mod, "SENDER_ID", "orig" ), \
             patch.object( ci_mod, "TARGET_USER", None ):
            result = await job._execute()
        self.assertEqual( result, "Dry run complete. Research simulation finished." )
        self.assertIn( "mock abstract", job.abstract )
        self.assertIsInstance( job.cost_summary, SessionSummary )
        self.assertEqual( job.cost_summary.total_cost_usd, 0.0 )
        # 6 breadcrumbs + completion = 7 notifications
        self.assertEqual( mock_notify.await_count, 7 )

    async def test_dry_run_no_debug( self ):
        job = make_job( dry_run=True, debug=False )
        with patch( "asyncio.sleep", new=AsyncMock() ), \
             patch.object( voice_io_mod, "notify", new=AsyncMock() ), \
             patch.object( voice_io_mod, "reconfigure" ), \
             patch.object( voice_io_mod, "set_job_id" ), \
             patch.object( voice_io_mod, "clear_job_id" ), \
             patch.object( ci_mod, "_get_sender_id", return_value="dr#x" ), \
             patch.object( ci_mod, "set_dispatch_context" ), \
             patch.object( ci_mod, "SENDER_ID", "orig" ), \
             patch.object( ci_mod, "TARGET_USER", None ):
            result = await job._execute()
        self.assertIn( "Dry run complete", result )

    async def test_dry_run_force_failure_invokes_hook( self ):
        # force_failure_mode set → _raise_forced_failure invoked (468-469 true arm).
        job = make_job( dry_run=True, force_failure_mode="code_bug" )
        job._raise_forced_failure = AsyncMock()
        with patch( "asyncio.sleep", new=AsyncMock() ), \
             patch.object( voice_io_mod, "notify", new=AsyncMock() ), \
             patch.object( voice_io_mod, "reconfigure" ), \
             patch.object( voice_io_mod, "set_job_id" ), \
             patch.object( voice_io_mod, "clear_job_id" ), \
             patch.object( ci_mod, "_get_sender_id", return_value="dr#x" ), \
             patch.object( ci_mod, "set_dispatch_context" ), \
             patch.object( ci_mod, "SENDER_ID", "orig" ), \
             patch.object( ci_mod, "TARGET_USER", None ):
            await job._execute()
        job._raise_forced_failure.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
