"""
Unit tests for cosa.agents.bug_fix_expediter.job.BugFixExpediterJob.

BugFixExpediterJob is the AgenticJobBase subclass that drives the BFE pipeline.
Surface covered:
  - __init__ / last_question_asked / class constants / is_cacheable
  - do_all()              : STALLED sentinel · cancelled · completed (debug duration) · exception→FAILED+reraise
  - _execute()            : dry-run delegate · dead-job-not-found · happy full path
                            (overrides + resume-checkpoint + git-strategy + resubmit) ·
                            no-selected-fix branch · fix-fails-with-diagnostics ·
                            completion-notify-swallow · StalledException stall path
                            (+ stall-notify swallow) · generic-exception reraise
  - _resubmit_original_job: no-context · auto-fix-disabled · config-error · no-routing-command ·
                            factory-None · todo-queue-None · success · exception
  - _execute_dry_run()    : dead-job-not-found · success-with-resubmit · success-no-resubmit
  - _write_final_report() : full-artifacts render · minimal · failure section · writer-exception

Every external boundary (voice_io, cosa_interface, dead_job_packager, BFEOrchestrator,
ConfigurationManager, agentic_job_factory, queue_extensions, fastapi_app.main, ReportWriter)
is mocked — no real LLM/SDK/network/DB/git/fs writes, zero spend. quick_smoke_test +
__main__ excluded via pyproject coverage config.

Created 2026-05-31 by Mr. Radio 🦉 (CoSA coverage campaign, agents Tier-2, expediter lane).
"""

import asyncio
import sys
import types
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import cosa.agents.bug_fix_expediter.voice_io as vio_mod
import cosa.agents.bug_fix_expediter.cosa_interface as ci_mod
import cosa.agents.bug_fix_expediter.dead_job_packager as pkg_mod
import cosa.agents.bug_fix_expediter.orchestrator as orch_mod
import cosa.config.configuration_manager as cfgmgr_mod

from cosa.agents.bug_fix_expediter.job import BugFixExpediterJob
from cosa.agents.bug_fix_expediter.state import (
    DiagnosisResult, ProposedFix, FixResult,
)
from cosa.agents.test_fix_expediter.state import StalledException
from cosa.rest.job_state import JobState


def _run( coro ):
    return asyncio.run( coro )


def _job( **over ):
    kw = dict(
        dead_job_id="dr-dead::u1", user_id="u1", user_email="t@t.com",
        session_id="s1",
    )
    kw.update( over )
    return BugFixExpediterJob( **kw )


def _diag():
    return DiagnosisResult( root_cause="missing key", error_category="config", confidence=0.9 )


def _fix( **over ):
    kw = dict( title="Add key", description="d", fix_type="config_change", confidence=0.9 )
    kw.update( over )
    return ProposedFix( **kw )


class _AsyncCM:
    """Stand-in for orchestrator.worktree_scope()."""
    async def __aenter__( self ): return None
    async def __aexit__( self, *exc ): return False


def _make_orch_cls( *, diagnosis=None, proposal=None, fix_result=None,
                    git_result=None, last_files_changed=None, diag_exc=None ):
    orch = MagicMock()
    orch.run_diagnosis    = AsyncMock( side_effect=diag_exc ) if diag_exc else AsyncMock( return_value=diagnosis )
    orch.run_proposal     = AsyncMock( return_value=proposal )
    orch.run_fix          = AsyncMock( return_value=fix_result )
    orch.run_git_strategy  = AsyncMock( return_value=git_result if git_result is not None else fix_result )
    orch.worktree_scope   = MagicMock( return_value=_AsyncCM() )
    orch.last_files_changed = last_files_changed if last_files_changed is not None else []
    orch.load_checkpoint  = MagicMock()
    orch.set_resume_phase = MagicMock()
    cls = MagicMock( return_value=orch )
    cls.render_worktree_artifacts_abstract = MagicMock( return_value=[ "**Worktree**: none" ] )
    return cls, orch


# ===========================================================================
# Construction + simple accessors
# ===========================================================================
class TestConstruction( unittest.TestCase ):

    def test_attributes_and_id_prefix( self ):
        job = _job( extra_context="extra", dry_run=True, debug=True, verbose=True,
                    lead_model_override="lm", worker_model_override="wm", thinking_effort="high" )
        self.assertTrue( job.id_hash.startswith( "bfe-" ) )
        self.assertEqual( job.dead_job_id, "dr-dead::u1" )
        self.assertEqual( job.extra_context, "extra" )
        self.assertTrue( job.dry_run )
        self.assertEqual( job.lead_model_override, "lm" )
        self.assertEqual( job.worker_model_override, "wm" )
        self.assertEqual( job.thinking_effort, "high" )
        self.assertIsNone( job.dead_job_context )
        self.assertIsNone( job.diagnosis )
        self.assertIsNone( job.cost_summary )
        self.assertEqual( job.state, JobState.PENDING )

    def test_last_question_asked_and_constants( self ):
        job = _job()
        self.assertIn( "[Bug Fix Expediter]", job.last_question_asked )
        self.assertIn( "dr-dead::u1", job.last_question_asked )
        self.assertEqual( BugFixExpediterJob.JOB_TYPE, "bug_fix_expediter" )
        self.assertEqual( BugFixExpediterJob.JOB_PREFIX, "bfe" )
        self.assertFalse( job.is_cacheable )


# ===========================================================================
# do_all() — the sync bridge
# ===========================================================================
class TestDoAll( unittest.TestCase ):

    def test_stalled_sentinel( self ):
        job = _job( debug=True )
        job._execute = AsyncMock( return_value="__STALLED__" )
        out = job.do_all()
        self.assertEqual( job.state, JobState.STALLED )
        self.assertIn( "stalled at voice gate", job.answer_conversational )
        self.assertEqual( out, job.answer_conversational )
        self.assertIsNotNone( job.completed_at )

    def test_cancelled( self ):
        job = _job( debug=True )
        job._execute = AsyncMock( return_value="partial result" )
        job._cancel_requested = True
        out = job.do_all()
        self.assertEqual( job.state, JobState.CANCELLED )
        self.assertEqual( job.error, "Cancelled by user request" )
        self.assertEqual( out, "partial result" )

    def test_cancelled_with_empty_result_uses_default_message( self ):
        job = _job()
        job._execute = AsyncMock( return_value="" )
        job._cancel_requested = True
        out = job.do_all()
        self.assertEqual( out, "Bug fix was cancelled." )

    def test_completed_with_debug_duration( self ):
        job = _job( debug=True )
        job._execute = AsyncMock( return_value="all done" )
        out = job.do_all()
        self.assertEqual( job.state, JobState.COMPLETED )
        self.assertEqual( out, "all done" )
        self.assertEqual( job.result, "all done" )
        self.assertEqual( job.answer_conversational, "all done" )

    def test_completed_debug_off_skips_duration_print( self ):
        job = _job( debug=False )
        job._execute = AsyncMock( return_value="done quietly" )
        out = job.do_all()
        self.assertEqual( job.state, JobState.COMPLETED )
        self.assertEqual( out, "done quietly" )

    def test_exception_marks_failed_and_reraises( self ):
        job = _job()
        job._execute = AsyncMock( side_effect=RuntimeError( "kaboom" ) )
        job._write_final_report = MagicMock()
        with self.assertRaises( RuntimeError ):
            job.do_all()
        self.assertEqual( job.state, JobState.FAILED )
        self.assertIn( "kaboom", job.error )
        self.assertIn( "kaboom", job.answer_conversational )
        self.assertIn( "failure_traceback", job.artifacts )
        self.assertEqual( job.artifacts[ "failure_message" ], "kaboom" )
        job._write_final_report.assert_called_once()


# ===========================================================================
# _execute() — the async pipeline
# ===========================================================================
class TestExecute( unittest.TestCase ):

    def setUp( self ):
        self.job = _job()
        self.es  = ExitStack()
        # Voice + interface boundary
        self.notify = AsyncMock()
        self.es.enter_context( patch.object( vio_mod, "notify", self.notify ) )
        self.es.enter_context( patch.object( vio_mod, "set_job_id", MagicMock() ) )
        self.es.enter_context( patch.object( vio_mod, "clear_job_id", MagicMock() ) )
        self.es.enter_context( patch.object( vio_mod, "reconfigure", MagicMock() ) )
        self.es.enter_context( patch.object( ci_mod, "_get_sender_id", MagicMock( return_value="sid" ) ) )
        self.es.enter_context( patch.object( ci_mod, "SENDER_ID", "sid", create=True ) )
        self.es.enter_context( patch.object( ci_mod, "TARGET_USER", None, create=True ) )
        # package_dead_job
        self.pkg = MagicMock()
        self.es.enter_context( patch.object( pkg_mod, "package_dead_job", self.pkg ) )
        # ConfigurationManager → echo defaults
        cfg_inst = MagicMock()
        cfg_inst.get.side_effect = lambda key, default=None, return_type=None: default
        self.es.enter_context( patch.object( cfgmgr_mod, "ConfigurationManager", MagicMock( return_value=cfg_inst ) ) )
        # Isolate report writing + resubmit
        self.job._write_final_report  = MagicMock( return_value="/tmp/report.md" )
        self.job._resubmit_original_job = AsyncMock( return_value=None )
        # A populated dead-job context (model with metadata_json)
        self.ctx = MagicMock()
        self.ctx.job_type = "deep_research"
        self.ctx.status   = "failed"
        self.ctx.model_dump = MagicMock( return_value={ "job_type": "deep_research" } )
        self.pkg.return_value = self.ctx

    def tearDown( self ):
        self.es.close()

    def _install_orch( self, **kw ):
        cls, orch = _make_orch_cls( **kw )
        self.es.enter_context( patch.object( orch_mod, "BFEOrchestrator", cls ) )
        return cls, orch

    def test_dry_run_delegates( self ):
        self.job.dry_run = True
        self.job._execute_dry_run = AsyncMock( return_value="DRY DONE" )
        out = _run( self.job._execute() )
        self.assertEqual( out, "DRY DONE" )
        self.pkg.assert_not_called()                # never reaches live packaging

    def test_dead_job_not_found( self ):
        self.pkg.return_value = None
        out = _run( self.job._execute() )
        self.assertEqual( out, "Dead job not found: dr-dead::u1" )
        self.job._write_final_report.assert_called_once()
        self.assertEqual(
            self.job._write_final_report.call_args.kwargs[ "status" ], "dead_job_not_found" )

    def test_happy_path_full_with_overrides_resume_git_and_resubmit( self ):
        self.job.debug                 = True
        self.job.lead_model_override   = "lead-x"
        self.job.worker_model_override = "worker-x"
        self.job.thinking_effort       = "high"
        self.job._resume_checkpoint    = { "phase_ordinal": 2 }
        self.job._resubmit_original_job = AsyncMock( return_value="bfe-new::u1" )

        applied_fix = FixResult( applied=True, success=True, details="ok" )
        git_fix     = FixResult( applied=True, success=True, details="ok",
                                 pr_url="https://gh/pr/9", git_strategy="branch_and_pr" )
        cls, orch = self._install_orch(
            diagnosis=_diag(),
            proposal=( [ _fix(), _fix( title="Alt" ) ], _fix(), "/tmp/plan.md" ),
            fix_result=applied_fix, git_result=git_fix,
            last_files_changed=[ "src/a.py" ],
        )
        out = _run( self.job._execute() )
        self.assertIn( "BFE complete: 2 proposed", out )
        self.assertIn( "fix applied", out )
        self.assertIn( "Resubmitted as bfe-new::u1", out )
        # Resume checkpoint loaded
        orch.load_checkpoint.assert_called_once_with( { "phase_ordinal": 2 } )
        orch.set_resume_phase.assert_called_once_with( 2 )
        # Git strategy ran (success + files changed)
        orch.run_git_strategy.assert_awaited_once()
        self.job._resubmit_original_job.assert_awaited_once()
        self.assertEqual( self.job.artifacts[ "resubmitted_job_id" ], "bfe-new::u1" )
        # Final report completed
        self.assertEqual(
            self.job._write_final_report.call_args.kwargs[ "status" ], "completed" )

    def test_no_selected_fix_branch( self ):
        cls, orch = self._install_orch(
            diagnosis=_diag(),
            proposal=( [ _fix() ], None, "/tmp/plan.md" ),
        )
        out = _run( self.job._execute() )
        self.assertIn( "no fix applied", out )
        orch.run_fix.assert_not_awaited()           # no selected fix → fix never runs
        self.assertEqual(
            self.job._write_final_report.call_args.kwargs[ "status" ], "completed_no_fix" )

    def test_git_strategy_skipped_when_no_files_changed( self ):
        # selected_fix present, fix SUCCESS but zero files changed →
        # the `success and last_files_changed` guard is False → no git strategy,
        # plan_path falsy so the completion abstract omits the Plan line.
        cls, orch = self._install_orch(
            diagnosis=_diag(),
            proposal=( [ _fix() ], _fix(), "" ),     # empty plan_path
            fix_result=FixResult( applied=True, success=True ),
            last_files_changed=[],                    # no files → git strategy skipped
        )
        out = _run( self.job._execute() )
        orch.run_fix.assert_awaited_once()
        orch.run_git_strategy.assert_not_awaited()
        self.assertIn( "Plan: .", out )              # plan_path empty

    def test_fix_fails_with_diagnostics_branch( self ):
        failed = FixResult( applied=True, success=False, details="nope",
                            last_stderr="AssertionError: boom", attempts=2 )
        cls, orch = self._install_orch(
            diagnosis=_diag(),
            proposal=( [ _fix() ], _fix(), "/tmp/plan.md" ),
            fix_result=failed,
            last_files_changed=[ "src/a.py" ],
        )
        out = _run( self.job._execute() )
        self.assertIn( "no fix applied", out )
        orch.run_fix.assert_awaited_once()
        orch.run_git_strategy.assert_not_awaited()  # success False → no git strategy
        self.job._resubmit_original_job.assert_not_awaited()

    def test_completion_notify_failure_is_swallowed( self ):
        def _notify_side( *a, **kw ):
            if "abstract" in kw and kw[ "abstract" ]:
                raise RuntimeError( "notify down" )
            return None
        self.notify.side_effect = _notify_side
        cls, orch = self._install_orch(
            diagnosis=_diag(),
            proposal=( [ _fix() ], _fix(), "/tmp/plan.md" ),
            fix_result=FixResult( applied=True, success=True ),
            last_files_changed=[ "src/a.py" ],
        )
        # Must NOT raise despite completion notify blowing up.
        out = _run( self.job._execute() )
        self.assertIn( "BFE complete", out )

    def test_stalled_exception_returns_sentinel( self ):
        ckpt = { "artifacts": { "plan_path": "/tmp/plan.md" }, "stall_reason": "voice_gate_timeout" }
        cls, orch = self._install_orch(
            diag_exc=StalledException( checkpoint=ckpt, phase="diagnosing" ),
        )
        out = _run( self.job._execute() )
        self.assertEqual( out, "__STALLED__" )
        self.assertEqual( self.job.artifacts[ "checkpoint" ], ckpt )
        self.assertEqual( self.job.artifacts[ "plan_path" ], "/tmp/plan.md" )
        self.assertEqual(
            self.job._write_final_report.call_args.kwargs[ "status" ], "stalled" )

    def test_stalled_notify_failure_is_swallowed( self ):
        ckpt = { "artifacts": {}, "stall_reason": "voice_gate_timeout" }
        # notify raises only for the stall (priority high + 'Stalled' abstract)
        def _notify_side( *a, **kw ):
            if kw.get( "abstract", "" ) and "Stalled" in kw[ "abstract" ]:
                raise RuntimeError( "stall notify down" )
            return None
        self.notify.side_effect = _notify_side
        cls, orch = self._install_orch(
            diag_exc=StalledException( checkpoint=ckpt, phase="diagnosing" ),
        )
        out = _run( self.job._execute() )
        self.assertEqual( out, "__STALLED__" )

    def test_generic_exception_reraises( self ):
        cls, orch = self._install_orch(
            diag_exc=ValueError( "diag exploded" ),
        )
        with self.assertRaises( ValueError ):
            _run( self.job._execute() )
        # urgent error notify fired
        self.assertTrue( any(
            "error" in str( c.args[ 0 ] ).lower()
            for c in self.notify.call_args_list if c.args ) )


# ===========================================================================
# _resubmit_original_job()
# ===========================================================================
class TestResubmit( unittest.TestCase ):

    def setUp( self ):
        self.job = _job( debug=True )
        self.es  = ExitStack()
        self.notify = AsyncMock()
        # voice_io passed in as an arg; build a stand-in module-ish mock
        self.vio = MagicMock()
        self.vio.notify = self.notify

    def tearDown( self ):
        self.es.close()

    def _ctx( self, **over ):
        ctx = MagicMock()
        ctx.job_type        = over.get( "job_type", "deep_research" )
        ctx.user_id         = "u1"
        ctx.user_email      = "t@t.com"
        ctx.session_id      = "s1"
        ctx.routing_command = over.get( "routing_command", "agent router go to dr" )
        ctx.question_text   = "q"
        ctx.metadata_json   = over.get( "metadata_json", { "original_args": { "query": "q" } } )
        return ctx

    def _patch_cfg( self, auto_enabled=True, raise_exc=False ):
        inst = MagicMock()
        if raise_exc:
            inst.get.side_effect = RuntimeError( "cfg boom" )
        else:
            inst.get.return_value = auto_enabled
        self.es.enter_context( patch.object( cfgmgr_mod, "ConfigurationManager", MagicMock( return_value=inst ) ) )

    def test_no_dead_job_context_returns_none( self ):
        self.job.dead_job_context = None
        out = _run( self.job._resubmit_original_job( self.vio ) )
        self.assertIsNone( out )

    def test_auto_fix_disabled_returns_none( self ):
        self.job.dead_job_context = self._ctx()
        self._patch_cfg( auto_enabled=False )
        out = _run( self.job._resubmit_original_job( self.vio ) )
        self.assertIsNone( out )

    def test_config_check_exception_returns_none( self ):
        self.job.dead_job_context = self._ctx()
        self._patch_cfg( raise_exc=True )
        out = _run( self.job._resubmit_original_job( self.vio ) )
        self.assertIsNone( out )

    def test_no_routing_command_returns_none( self ):
        self.job.dead_job_context = self._ctx( routing_command=None )
        self._patch_cfg( auto_enabled=True )
        out = _run( self.job._resubmit_original_job( self.vio ) )
        self.assertIsNone( out )

    def _patch_factory_and_queue( self, *, new_job, todo_queue ):
        factory_mod = types.ModuleType( "cosa.rest.agentic_job_factory" )
        factory_mod.create_agentic_job = MagicMock( return_value=new_job )
        qext_mod = types.ModuleType( "cosa.rest.queue_extensions" )
        tracker = MagicMock()
        tracker.register_scoped_job = MagicMock( side_effect=lambda idh, uid, sid: idh )
        qext_mod.user_job_tracker = tracker
        main_mod = types.ModuleType( "fastapi_app.main" )
        main_mod.jobs_todo_queue = todo_queue
        self.es.enter_context( patch.dict( sys.modules, {
            "cosa.rest.agentic_job_factory": factory_mod,
            "cosa.rest.queue_extensions"   : qext_mod,
            "fastapi_app.main"             : main_mod,
        } ) )
        return factory_mod, tracker, main_mod

    def test_factory_returns_none( self ):
        self.job.dead_job_context = self._ctx( metadata_json={} )   # no original_args → reconstruct
        self._patch_cfg( auto_enabled=True )
        self._patch_factory_and_queue( new_job=None, todo_queue=MagicMock() )
        out = _run( self.job._resubmit_original_job( self.vio ) )
        self.assertIsNone( out )

    def test_todo_queue_unavailable( self ):
        self.job.dead_job_context = self._ctx()
        self._patch_cfg( auto_enabled=True )
        new_job = MagicMock(); new_job.id_hash = "bfe-new::u1"
        self._patch_factory_and_queue( new_job=new_job, todo_queue=None )
        out = _run( self.job._resubmit_original_job( self.vio ) )
        self.assertIsNone( out )

    def test_success_pushes_and_returns_id( self ):
        self.job.dead_job_context = self._ctx()
        self._patch_cfg( auto_enabled=True )
        new_job = MagicMock(); new_job.id_hash = "bfe-new::u1"
        todo_queue = MagicMock()
        self._patch_factory_and_queue( new_job=new_job, todo_queue=todo_queue )
        out = _run( self.job._resubmit_original_job( self.vio ) )
        self.assertEqual( out, "bfe-new::u1" )
        todo_queue.push.assert_called_once_with( new_job )

    def test_success_debug_off_skips_final_print( self ):
        self.job.debug = False                       # exercises the debug-off arc on success
        self.job.dead_job_context = self._ctx()
        self._patch_cfg( auto_enabled=True )
        new_job = MagicMock(); new_job.id_hash = "bfe-new::u1"
        todo_queue = MagicMock()
        self._patch_factory_and_queue( new_job=new_job, todo_queue=todo_queue )
        out = _run( self.job._resubmit_original_job( self.vio ) )
        self.assertEqual( out, "bfe-new::u1" )

    def test_exception_during_resubmit_returns_none( self ):
        self.job.dead_job_context = self._ctx()
        self._patch_cfg( auto_enabled=True )
        # factory raises → caught by the outer try/except → None
        factory_mod = types.ModuleType( "cosa.rest.agentic_job_factory" )
        factory_mod.create_agentic_job = MagicMock( side_effect=RuntimeError( "factory boom" ) )
        self.es.enter_context( patch.dict( sys.modules, {
            "cosa.rest.agentic_job_factory": factory_mod,
        } ) )
        out = _run( self.job._resubmit_original_job( self.vio ) )
        self.assertIsNone( out )


# ===========================================================================
# _execute_dry_run()
# ===========================================================================
class TestExecuteDryRun( unittest.TestCase ):

    def setUp( self ):
        self.job = _job( dry_run=True, debug=True )
        self.es  = ExitStack()
        self.vio = MagicMock()
        self.vio.notify       = AsyncMock()
        self.vio.set_job_id   = MagicMock()
        self.vio.clear_job_id = MagicMock()
        self.ci  = MagicMock()
        self.ci._get_sender_id = MagicMock( return_value="sid" )
        self.pkg = MagicMock()
        self.es.enter_context( patch.object( pkg_mod, "package_dead_job", self.pkg ) )
        # asyncio.sleep → no real delay
        self.es.enter_context( patch( "cosa.agents.bug_fix_expediter.job.asyncio.sleep", AsyncMock() ) )
        self.job._write_final_report   = MagicMock( return_value="/tmp/r.md" )
        self.job._resubmit_original_job = AsyncMock( return_value=None )

    def tearDown( self ):
        self.es.close()

    def _ctx( self, metadata_json ):
        ctx = MagicMock()
        ctx.metadata_json = metadata_json
        ctx.model_dump    = MagicMock( return_value={} )
        return ctx

    def test_dead_job_not_found( self ):
        self.pkg.return_value = None
        out = _run( self.job._execute_dry_run( self.vio, self.ci ) )
        self.assertIn( "dead job not found", out )
        self.assertEqual(
            self.job._write_final_report.call_args.kwargs[ "status" ], "dead_job_not_found_dry_run" )

    def test_success_with_resubmit( self ):
        ctx = self._ctx( { "original_args": { "force_failure_mode": "x", "query": "q" } } )
        self.pkg.return_value = ctx
        self.job._resubmit_original_job = AsyncMock( return_value="bfe-redo::u1" )
        out = _run( self.job._execute_dry_run( self.vio, self.ci ) )
        self.assertIn( "Resubmitted as bfe-redo::u1", out )
        self.assertEqual( self.job.artifacts[ "resubmitted_job_id" ], "bfe-redo::u1" )
        # force_failure_mode stripped, dry_run injected
        sent_args = ctx.metadata_json[ "original_args" ]
        self.assertNotIn( "force_failure_mode", sent_args )
        self.assertTrue( sent_args[ "dry_run" ] )

    def test_success_no_resubmit( self ):
        self.pkg.return_value = self._ctx( None )    # metadata None → `or {}`
        self.job._resubmit_original_job = AsyncMock( return_value=None )
        out = _run( self.job._execute_dry_run( self.vio, self.ci ) )
        self.assertIn( "Resubmit skipped", out )


# ===========================================================================
# _write_final_report()
# ===========================================================================
class TestWriteFinalReport( unittest.TestCase ):

    def setUp( self ):
        self.job = _job( debug=True )
        self.es  = ExitStack()
        self.writer = MagicMock()
        self.writer.write = MagicMock( return_value="/io/reports/bfe.md" )
        rw_mod = types.ModuleType( "cosa.agents.shared.report_writer" )
        rw_mod.ReportWriter = MagicMock( return_value=self.writer )
        self.es.enter_context( patch.dict( sys.modules, { "cosa.agents.shared.report_writer": rw_mod } ) )
        self.rw_module = rw_mod

    def tearDown( self ):
        self.es.close()

    def test_full_artifacts_render_all_sections( self ):
        self.job.artifacts = {
            "resubmitted_job_id" : "bfe-new::u1",
            "dead_job_context"   : { "job_type": "deep_research", "question": "q",
                                     "error": "boom", "stack_trace": "trace" },
            "diagnosis"          : { "root_cause": "rc", "error_category": "config", "confidence": 0.9 },
            "proposed_fixes"     : [ { "title": "T", "fix_type": "config_change",
                                       "risk_level": "low", "estimated_effort": "minimal",
                                       "description": "desc" } ],
            "selected_fix"       : { "title": "T", "fix_type": "config_change", "reason": "best" },
            "fix_result"         : { "applied": True, "success": True, "details": "ok" },
            "checkpoint"         : { "phase": "fixing", "stall_reason": "voice_gate_timeout" },
            "plan_path"          : "/tmp/plan.md",
        }
        path = self.job._write_final_report( status="completed", summary_line="done" )
        self.assertEqual( path, "/io/reports/bfe.md" )
        body = self.rw_module.ReportWriter.return_value.write.call_args.kwargs[ "body_md" ]
        for token in ( "## Summary", "## Dead job context", "## Diagnosis",
                       "## Proposed fixes", "## Selected fix", "## Fix result",
                       "## Stall checkpoint", "## Appendix", "90%" ):
            self.assertIn( token, body )

    def test_confidence_non_numeric_falls_back( self ):
        self.job.artifacts = { "diagnosis": { "root_cause": "rc", "confidence": "high" } }
        self.job._write_final_report( status="completed", summary_line="s" )
        body = self.writer.write.call_args.kwargs[ "body_md" ]
        self.assertIn( "**Confidence**: high", body )

    def test_falsy_optionals_skip_subsections( self ):
        # dead_job_context with no error / no stack_trace; diagnosis with no
        # confidence; a proposal with no description; selected_fix with no reason
        # → each guarded sub-section is skipped (the False arcs).
        self.job.artifacts = {
            "dead_job_context" : { "job_type": "deep_research", "question": "q",
                                   "error": None, "stack_trace": None },
            "diagnosis"        : { "root_cause": "rc", "error_category": "config" },  # no confidence
            "proposed_fixes"   : [ { "title": "T", "fix_type": "x" } ],               # no description
            "selected_fix"     : { "title": "T", "fix_type": "x" },                   # no reason
        }
        self.job._write_final_report( status="completed", summary_line="s" )
        body = self.writer.write.call_args.kwargs[ "body_md" ]
        self.assertIn( "## Dead job context", body )
        self.assertNotIn( "**Error**", body )           # error falsy → skipped
        self.assertNotIn( "**Stack trace**", body )     # stack_trace falsy → skipped
        self.assertNotIn( "**Confidence**", body )      # confidence None → skipped
        self.assertNotIn( "**Reason**", body )          # reason absent → skipped

    def test_minimal_artifacts_uses_placeholder( self ):
        self.job.artifacts = {}
        self.job._write_final_report( status="completed", summary_line="s" )
        body = self.writer.write.call_args.kwargs[ "body_md" ]
        self.assertIn( "_not available", body )

    def test_failure_section_rendered( self ):
        self.job.artifacts = { "failure_traceback": "Traceback...", "failure_message": "bad" }
        self.job._write_final_report( status="failed", summary_line="s" )
        body = self.writer.write.call_args.kwargs[ "body_md" ]
        self.assertIn( "## Failure", body )
        self.assertIn( "bad", body )

    def test_writer_exception_returns_none( self ):
        self.rw_module.ReportWriter.side_effect = RuntimeError( "writer down" )
        out = self.job._write_final_report( status="completed", summary_line="s" )
        self.assertIsNone( out )


if __name__ == "__main__":
    unittest.main()
