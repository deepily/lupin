"""
TestFixExpediter background job for queue-based execution.

Session 1cfcdf73 (2026-04-10): Parallel to BFE's job.py. Takes a remediation
snapshot (from a failed TestSuiteJob), runs the TFE pipeline (cluster →
diagnose → propose → fix → git → rerun), and returns a conversational answer.

**Step 6 scaffolding**: `_execute()` loads the snapshot, runs the orchestrator
phase stubs, and returns a placeholder conversational answer. Full pipeline
wiring lands incrementally in steps 7-12.

Example:
    job = TestFixExpediterJob(
        remediation_snapshot_path = "test-suite/2026.04.10-at-14:53-e2e-remediation.json",
        source_test_suite_job_id  = "ts-abc12345",
        user_id                   = "user123",
        user_email                = "user@example.com",
        session_id                = "wise-penguin",
        debug                     = True,
    )
    result = job.do_all()
"""

import asyncio
import time
import traceback
from datetime import datetime
from typing import Optional

import cosa.utils.util as cu

from cosa.agents.agentic_job_base import AgenticJobBase
from cosa.agents.test_fix_expediter.state import StalledException
from cosa.rest.job_state import JobState


class TestFixExpediterJob( AgenticJobBase ):
    """
    Background job for TestFixExpediter execution.

    Runs the TFE pipeline on a remediation snapshot from a failed
    TestSuiteJob. **Step 6 scaffolding**: `_execute()` exercises the
    orchestrator phase stubs to prove end-to-end wiring. Full pipeline
    lands in steps 7-12 per the approved plan.

    Attributes:
        remediation_snapshot_path: Path to the snapshot JSON (relative to io/)
        source_test_suite_job_id:  The TestSuiteJob that produced the snapshot
        remediation_context:       Parsed TestRemediationContext (set during _execute)
        orchestrator:              TFEOrchestrator instance (set during _execute)
        cost_summary:              Execution cost summary (set after completion)
    """

    JOB_TYPE   = "test_fix_expediter"
    JOB_PREFIX = "tfe"

    def __init__(
        self,
        remediation_snapshot_path: str,
        source_test_suite_job_id: str,
        user_id: str,
        user_email: str,
        session_id: str,
        original_test_types: Optional[ list ] = None,
        original_pytest_args: Optional[ list ] = None,
        dry_run: bool = False,
        lead_model_override:   Optional[ str ] = None,
        worker_model_override: Optional[ str ] = None,
        thinking_effort:       Optional[ str ] = None,
        debug: bool = False,
        verbose: bool = False
    ) -> None:
        """
        Initialize a TestFixExpediter job.

        Requires:
            - remediation_snapshot_path is a non-empty path (relative to io/)
            - source_test_suite_job_id is a non-empty string
            - user_id, user_email, session_id are non-empty

        Ensures:
            - Job ID generated with "tfe-" prefix (via AgenticJobBase)
            - All parameters stored for execution

        Args:
            remediation_snapshot_path: Path to the remediation JSON
            source_test_suite_job_id: ID of the TestSuiteJob that produced the snapshot
            user_id: System ID of the job owner
            user_email: Email address for notification routing
            session_id: WebSocket session for notifications
            original_test_types: Suites the original job ran (for Phase 6 rerun)
            original_pytest_args: Original pytest args (for Phase 6 rerun)
            dry_run: Simulate execution without making changes
            lead_model_override:   Optional per-invocation override of the TFE
                                   lead model (e.g. "claude-sonnet-4-6" for E2E
                                   --cheap runs). Applied after config.from_config
                                   loads INI defaults. None = use INI value.
            worker_model_override: Optional per-invocation override of the TFE
                                   worker model. Same semantics as lead override.
            thinking_effort:       Optional extended-thinking effort level
                                   ("low" | "medium" | "high" | "xhigh" | "max").
                                   Forwarded to ClaudeAgentOptions.effort in the
                                   orchestrator. None = SDK default.
            debug: Enable debug output
            verbose: Enable verbose output
        """
        super().__init__(
            user_id    = user_id,
            user_email = user_email,
            session_id = session_id,
            debug      = debug,
            verbose    = verbose,
        )

        self.remediation_snapshot_path = remediation_snapshot_path
        self.source_test_suite_job_id  = source_test_suite_job_id
        self.original_test_types       = original_test_types or []
        self.original_pytest_args      = original_pytest_args or []
        self.dry_run                   = dry_run
        self.lead_model_override       = lead_model_override
        self.worker_model_override     = worker_model_override
        self.thinking_effort           = thinking_effort

        # Results (populated during execution)
        self.remediation_context = None    # TestRemediationContext
        self.orchestrator        = None    # TFEOrchestrator
        self.cost_summary        = None

    @property
    def last_question_asked( self ) -> str:
        """
        Display string for queue UI.

        Returns:
            str: Concise description of the remediation source
        """
        return f"TFE: fix failures from {self.source_test_suite_job_id}"

    def do_all( self ) -> str:
        """
        Synchronous entry point for queue consumer.

        Runs `_execute()` in an event loop, sets the `AgenticJobBase` lifecycle
        state (`self.state`), captures full Python traceback into `self.error`
        on failure, and returns a conversational answer string. Exception
        handling follows the BFE pattern (`bug_fix_expediter/job.py:107-157`)
        so dead TFE jobs carry complete forensic data for queue serialization
        + job_history persistence.

        Returns:
            str: Conversational answer for UI display
        """
        if self.debug:
            print( f"[TestFixExpediterJob] Starting do_all() for: {self.source_test_suite_job_id}" )

        self.state      = JobState.RUNNING
        self.started_at = cu.get_current_datetime_iso()

        try:
            result = asyncio.run( self._execute() )

            # Checkpoint-resume: _execute() returns "__STALLED__" when
            # a voice gate timed out and the orchestrator saved its state.
            if result == "__STALLED__":
                self.state                 = JobState.STALLED
                self.completed_at          = cu.get_current_datetime_iso()
                self.answer_conversational = (
                    f"TFE stalled at voice gate. "
                    f"{len( self.orchestrator.proposed_fixes )} proposals await your review. "
                    f"Resume when ready."
                )
                if self.debug: print( f"[TestFixExpediterJob] Stalled — checkpoint saved" )
                return self.answer_conversational

            if self._cancel_requested:
                self.state                 = JobState.CANCELLED
                self.completed_at          = cu.get_current_datetime_iso()
                self.error                 = "Cancelled by user request"
                self.answer_conversational = result or "TFE was cancelled by the user."
                if self.debug: print( f"[TestFixExpediterJob] Cancelled by user request" )
                return self.answer_conversational

            self.state                 = JobState.COMPLETED
            self.completed_at          = cu.get_current_datetime_iso()
            self.result                = result
            self.answer_conversational = result

            if self.debug:
                duration = self.get_execution_duration_seconds()
                print( f"[TestFixExpediterJob] Completed in {duration:.1f}s" )

            return result

        except Exception as e:
            tb_str = traceback.format_exc()

            self.state        = JobState.FAILED
            self.completed_at = cu.get_current_datetime_iso()
            self.error        = f"{e}\n\n{tb_str}"
            self.answer_conversational = f"TFE failed: {str( e )}"

            # Unconditional stdout (not gated behind self.debug) so dockered
            # server logs always capture the traceback regardless of the
            # job's debug flag. Production submissions run with debug=False.
            print( f"[TestFixExpediterJob] Failed: {e}" )
            print( tb_str )

            # Preserve the failure as a comprehensive final report so the user
            # has a surface to investigate what blew up. Stash the traceback in
            # artifacts so _write_final_report picks it up.
            self.artifacts[ "failure_traceback" ] = tb_str
            self.artifacts[ "failure_message" ]   = str( e )
            self._write_final_report(
                status       = "failed",
                summary_line = self.answer_conversational,
            )

            # Re-raise so the agentic-pool Future captures the exception.
            # Backlog item 5 (2026-04-29): canonical Future contract.
            raise

    async def _execute( self ) -> str:
        """
        Run the TFE pipeline.

        Sets cosa-voice routing (SENDER_ID + TARGET_USER) for BFE's delegated
        notification dispatcher, then wraps phase orchestration in a try/except
        that emits an urgent voice notification with the full traceback on
        crash before re-raising (do_all's handler captures self.error).

        **Step 6 scaffolding**: loads the snapshot, instantiates the
        orchestrator, walks the phase stubs, and returns a placeholder.
        Full pipeline wiring lands in steps 7-12.
        """
        from cosa.agents.test_fix_expediter.config import TestFixExpediterConfig
        from cosa.agents.test_fix_expediter.snapshot_loader import (
            load_from_path,
            SnapshotLoadError,
        )
        from cosa.agents.test_fix_expediter.orchestrator import TFEOrchestrator
        from cosa.agents.test_fix_expediter import voice_io
        # TFE's cosa_interface.py is a thin delegator that forwards to BFE's
        # cosa_interface module. BFE's dispatcher reads SENDER_ID and TARGET_USER
        # from its OWN module-level state, so we must set them on BFE's module
        # directly for TFE notifications to route correctly. This was the root
        # cause of tfe-d9e6b50f's "present_choices failed: Cannot resolve
        # target_user" crash at the Phase 2 voice gate.
        # See: src/rnd/v0.1.6/2026.04.11-tfe-forensics-capture-plan.md (Fix 7)
        from cosa.agents.bug_fix_expediter import cosa_interface as _bfe_ci

        _bfe_ci.TARGET_USER = self.user_email
        _bfe_ci.SENDER_ID   = _bfe_ci._get_sender_id( suffix=self.base_id )

        # Config load has its own fallback; not inside the main try/except
        # because using defaults is acceptable, not a TFE failure.
        try:
            from cosa.config.configuration_manager import ConfigurationManager
            config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
            config     = TestFixExpediterConfig.from_config( config_mgr, debug=self.debug )
        except Exception as e:
            if self.debug: print( f"[TestFixExpediterJob] from_config failed, using defaults: {e}" )
            config = TestFixExpediterConfig()

        # Per-invocation model overrides (e.g. E2E --cheap runs)
        if self.lead_model_override:
            if self.debug: print( f"[TFE] lead_model overridden: {config.lead_model} -> {self.lead_model_override}" )
            config.lead_model = self.lead_model_override
        if self.worker_model_override:
            if self.debug: print( f"[TFE] worker_model overridden: {config.worker_model} -> {self.worker_model_override}" )
            config.worker_model = self.worker_model_override
        if self.thinking_effort:
            if self.debug: print( f"[TFE] thinking_effort set: {self.thinking_effort}" )
            config.thinking_effort = self.thinking_effort

        self._start_time = time.time()

        try:
            # Load the remediation snapshot
            try:
                self.remediation_context = load_from_path(
                    snapshot_path             = self.remediation_snapshot_path,
                    source_test_suite_job_id  = self.source_test_suite_job_id,
                    user_id                   = self.user_id,
                    user_email                = self.user_email,
                    session_id                = self.session_id,
                    original_test_types       = self.original_test_types,
                    original_pytest_args      = self.original_pytest_args,
                )
            except SnapshotLoadError as e:
                raise RuntimeError( f"Failed to load remediation snapshot: {e}" )

            # Instantiate the orchestrator
            self.orchestrator = TFEOrchestrator(
                remediation_context = self.remediation_context,
                config              = config,
                user_id             = self.user_id,
                user_email          = self.user_email,
                session_id          = self.session_id,
                job_id              = self.id_hash,
                dry_run             = self.dry_run,
                debug               = self.debug,
                verbose             = self.verbose,
            )

            # Resume from checkpoint if this is a resumed job
            if hasattr( self, "_resume_checkpoint" ) and self._resume_checkpoint:
                self.orchestrator.load_checkpoint( self._resume_checkpoint )
                self.orchestrator.set_resume_phase( self._resume_checkpoint[ "phase_ordinal" ] )
                print( f"[TFE] Resuming from phase ordinal {self._resume_checkpoint[ 'phase_ordinal' ]}" )

            # Walk the phases (real implementations for P0/P1, stubs for P2-P6)
            clusters = await self.orchestrator.run_phase0_cluster()
            diagnoses = await self.orchestrator.run_phase1_diagnose()
            _propose_result = await self.orchestrator.run_phase2_propose()

            # Fix 8a: Surface the Phase 2 plan path for dead-queue card. Storing
            # it here (before Phase 3) ensures the artifact survives if a later
            # phase crashes — tfe-d9e6b50f died at the Phase 2 voice gate with a
            # complete plan on disk but no link to it in the UI.
            if self.orchestrator.last_plan_path:
                self.artifacts[ "plan_path" ] = self.orchestrator.last_plan_path

            # Phase 3 + 5: wrap in worktree_scope so isolation (when enabled)
            # spans both FixExecutor and GitStrategist (Bug 9, 2026-04-16).
            # Phase 6 runs OUTSIDE the scope — it just queues a new TestSuiteJob
            # via the REST API and doesn't touch git/file state.
            async with self.orchestrator.worktree_scope():
                fix_results = await self.orchestrator.run_phase3_fix()
                _git_result = await self.orchestrator.run_phase5_git()
            validation_run_job_id = await self.orchestrator.run_phase6_validation()

            # Populate artifacts for UI
            self.artifacts[ "remediation_snapshot_path" ] = self.remediation_snapshot_path
            self.artifacts[ "source_test_suite_job_id" ]  = self.source_test_suite_job_id
            self.artifacts[ "cluster_count" ]             = len( clusters )
            self.artifacts[ "fix_count" ]                 = len( fix_results )
            self.artifacts[ "validation_run_job_id" ]     = validation_run_job_id
            if self.orchestrator.last_plan_path:
                self.artifacts[ "plan_path" ] = self.orchestrator.last_plan_path

            # ── Completion report (Phase 11 pattern: TTS + rich abstract) ──
            n_clusters     = len( clusters )
            n_failures     = len( self.orchestrator.remediation_context.failures )
            n_proposed     = len( self.orchestrator.proposed_fixes )
            n_selected     = len( self.orchestrator.selected_fixes )
            n_fixed        = sum( 1 for r in fix_results if r.success )
            n_failed_fixes = sum( 1 for r in fix_results if not r.success )
            duration       = round( time.time() - self._start_time, 1 )
            rerun_status   = (
                f"Validation queued: {validation_run_job_id}"
                if validation_run_job_id
                else "No rerun (no successful fixes)"
            )

            # Brief TTS message — outcome-aware
            if n_fixed > 0:
                tts_msg = (
                    f"Test Fix Expediter complete. "
                    f"{n_fixed} fix{'es' if n_fixed != 1 else ''} applied "
                    f"across {n_clusters} cluster{'s' if n_clusters != 1 else ''}."
                )
            elif n_selected == 0:
                tts_msg = (
                    f"Test Fix Expediter complete. "
                    f"{n_clusters} cluster{'s' if n_clusters != 1 else ''} diagnosed, "
                    f"no fixes selected."
                )
            else:
                tts_msg = (
                    f"Test Fix Expediter complete. "
                    f"{n_selected} fix{'es' if n_selected != 1 else ''} attempted, "
                    f"{n_failed_fixes} failed."
                )

            # Rich markdown abstract (UI-only, not spoken)
            lines = [ "**TFE Activity Report**", "" ]
            lines.append( f"**Source**: `{self.source_test_suite_job_id}`" )
            lines.append( f"**Clusters**: {n_clusters} (from {n_failures} failures)" )
            lines.append(
                f"**Proposed**: {n_proposed} | **Selected**: {n_selected} | "
                f"**Fixed**: {n_fixed} | **Failed**: {n_failed_fixes}"
            )
            if self.orchestrator.last_plan_path:
                lines.append( f"**Plan**: `{self.orchestrator.last_plan_path}`" )
            lines.append( f"**Rerun**: {rerun_status}" )
            lines.append( f"**Duration**: {duration}s" )

            # Per-cluster diagnosis detail
            if self.orchestrator.diagnoses:
                lines.append( "" )
                lines.append( "**Cluster Diagnoses:**" )
                for cid, diag in self.orchestrator.diagnoses.items():
                    conf = f"{diag.confidence:.0%}" if hasattr( diag, "confidence" ) else "?"
                    lines.append(
                        f"- **{cid}**: {diag.root_cause[ :120 ]} ({conf}, {diag.error_category})"
                    )

            # Worktree artifacts — surfaces what Phase 3/5 produced so the
            # operator can actually find the worktree + commits when
            # cosa_worktree.auto_cleanup=false preserves the sandbox.
            # Delegated to TFEOrchestrator.render_worktree_artifacts_abstract
            # so the logic is unit-testable in isolation.
            lines.extend(
                self.orchestrator.render_worktree_artifacts_abstract( self.id_hash )
            )

            # Failed-fix diagnostics — last_stderr tails retained by FixExecutor's
            # auto-reject path. Capped at top-5 failures to keep the notification
            # abstract under ~8KB; remaining failures pointed to the worktree log.
            failed_pairs = [
                ( p, r ) for p, r in zip(
                    self.orchestrator.selected_fixes, self.orchestrator.fix_results
                )
                if not r.success and r.last_stderr
            ]
            if failed_pairs:
                lines.append( "" )
                lines.append( "**Failed fix diagnostics:**" )
                shown = failed_pairs[ :5 ]
                for proposed, result in shown:
                    lines.append( "" )
                    lines.append(
                        f"✗ **{proposed.title}** — {result.attempts} attempt(s)"
                    )
                    lines.append( "```" )
                    lines.append( result.last_stderr )
                    lines.append( "```" )
                if len( failed_pairs ) > 5:
                    lines.append( "" )
                    lines.append(
                        f"(+{len( failed_pairs ) - 5} more failed — see worktree logs)"
                    )

            completion_abstract = "\n".join( lines )

            try:
                await voice_io.notify(
                    tts_msg,
                    priority   = "medium",
                    abstract   = completion_abstract,
                    job_id     = self.id_hash,
                    queue_name = "run",
                )
            except Exception as notify_err:
                print( f"[TestFixExpediterJob] completion notify failed: {notify_err}" )

            # Conversational answer
            result = (
                f"TFE complete: {n_clusters} clusters, {n_proposed} proposed, "
                f"{n_selected} selected, {n_fixed} fixed. {rerun_status}. "
                f"Source: {self.source_test_suite_job_id}."
            )
            self._write_final_report( status="completed", summary_line=result )
            return result

        except StalledException as stall:
            # Checkpoint-resume: voice gate timed out, orchestrator saved state.
            # Persist checkpoint in artifacts for metadata_json serialization,
            # notify the user, and return a sentinel for do_all() to detect.
            self.artifacts[ "checkpoint" ] = stall.checkpoint
            if stall.checkpoint.get( "artifacts", {} ).get( "plan_path" ):
                self.artifacts[ "plan_path" ] = stall.checkpoint[ "artifacts" ][ "plan_path" ]

            try:
                await voice_io.notify(
                    f"TFE stalled at {stall.phase} — resume when ready",
                    priority   = "high",
                    abstract   = (
                        f"**TFE Stalled**\n\n"
                        f"**Phase**: {stall.phase}\n"
                        f"**Reason**: {stall.checkpoint[ 'stall_reason' ]}\n"
                        f"**Clusters diagnosed**: {len( self.orchestrator.clusters )}\n"
                        f"**Proposals awaiting review**: {len( self.orchestrator.proposed_fixes )}\n\n"
                        f"Resume via UI 'Resume' button or API `POST /api/jobs/{self.id_hash}/resume`"
                    ),
                    job_id     = self.id_hash,
                    queue_name = "todo",
                )
            except Exception as notify_err:
                print( f"[TestFixExpediterJob] stall notify failed: {notify_err}" )

            self._write_final_report(
                status       = "stalled",
                summary_line = f"TFE stalled at phase={stall.phase}",
            )
            return "__STALLED__"

        except Exception as e:
            # Emit urgent voice notification with full traceback in the abstract
            # field (UI-only, not spoken via TTS) so the user gets in-UI access
            # to the failure without having to grep docker logs. Re-raises so
            # do_all()'s handler captures the traceback into self.error too.
            # See: src/rnd/v0.1.6/2026.04.11-tfe-forensics-capture-plan.md (Fix 3)
            tb_str = traceback.format_exc()
            try:
                await voice_io.notify(
                    f"Test Fix Expediter error: {str( e )[ :100 ]}",
                    priority = "urgent",
                    job_id   = self.id_hash,
                    abstract = tb_str,
                )
            except Exception as notify_err:
                # Never let the notify failure mask the original exception
                print( f"[TestFixExpediterJob] voice_io.notify failed during error path: {notify_err}" )
            raise

    def _write_final_report( self, status: str, summary_line: str ):
        """
        Write a comprehensive final-report markdown file for this TFE run and
        store its path in `self.artifacts["report_path"]`.

        Called at each terminal exit of the TFE pipeline (happy path, stall).
        Never blocks the job on failure — returns None and logs a warning if
        writing fails.

        The report captures artifacts accumulated in-memory during the run:
        source_test_suite_job_id, cluster_count, fix_count, validation_run_job_id,
        plan_path, remediation_snapshot_path, and checkpoint (if stalled).
        """
        try:
            from cosa.agents.shared.report_writer import ReportWriter

            duration   = self.get_execution_duration_seconds() if hasattr( self, "get_execution_duration_seconds" ) else None
            duration_s = f"{duration:.1f}s" if duration is not None else "n/a"
            artifacts  = self.artifacts or {}
            sections   = [ ]

            sections.append( "## Summary\n" )
            sections.append( f"- **Status**: {status}" )
            sections.append( f"- **TFE job id**: `{self.id_hash}`" )
            sections.append( f"- **Source test suite**: `{self.source_test_suite_job_id}`" )
            sections.append( f"- **Duration**: {duration_s}" )
            if artifacts.get( "cluster_count" ) is not None:
                sections.append( f"- **Clusters**: {artifacts[ 'cluster_count' ]}" )
            if artifacts.get( "fix_count" ) is not None:
                sections.append( f"- **Fixes**: {artifacts[ 'fix_count' ]}" )
            if artifacts.get( "validation_run_job_id" ):
                sections.append( f"- **Validation rerun**: `{artifacts[ 'validation_run_job_id' ]}`" )
            sections.append( f"\n**Conversational answer**: {summary_line}\n" )

            # Cluster detail
            if self.orchestrator is not None and self.orchestrator.clusters:
                sections.append( "\n## Clusters\n" )
                for i, c in enumerate( self.orchestrator.clusters, 1 ):
                    count = len( c.failure_indices )
                    sections.append( f"### {i}. {c.cluster_id} — {count} failure(s)" )
                    if c.shared_error_signature:
                        sections.append( f"\n{c.shared_error_signature}\n" )

            # Proposals
            if self.orchestrator is not None and self.orchestrator.proposed_fixes:
                sections.append( "\n## Proposed fixes\n" )
                for i, p in enumerate( self.orchestrator.proposed_fixes, 1 ):
                    sections.append( f"### {i}. {p.title}" )
                    if p.description:
                        sections.append( f"\n{p.description}\n" )

            # Stall checkpoint
            ckpt = artifacts.get( "checkpoint" )
            if ckpt:
                sections.append( "\n## Stall checkpoint\n" )
                sections.append( f"- **Phase**: {ckpt.get( 'phase', 'n/a' )}" )
                sections.append( f"- **Reason**: {ckpt.get( 'stall_reason', 'n/a' )}" )

            # Failure (unhandled exception from do_all)
            if artifacts.get( "failure_traceback" ):
                sections.append( "\n## Failure\n" )
                msg = artifacts.get( "failure_message" ) or "Unhandled exception"
                sections.append( f"**Message**: {msg}\n" )
                sections.append( "**Traceback**:\n```\n" + str( artifacts[ "failure_traceback" ] )[ :4000 ] + "\n```" )

            # Appendix
            appendix = [ ]
            if artifacts.get( "plan_path" ):
                appendix.append( f"- **Plan**: `{artifacts[ 'plan_path' ]}`" )
            if artifacts.get( "remediation_snapshot_path" ):
                appendix.append( f"- **Remediation snapshot**: `{artifacts[ 'remediation_snapshot_path' ]}`" )
            if appendix:
                sections.append( "\n## Appendix\n" )
                sections.extend( appendix )

            body_md   = "\n".join( sections )
            base_slug = ( self.source_test_suite_job_id or "tfe" ).split( "::" )[ 0 ]
            slug      = f"{base_slug}-{status}"

            writer = ReportWriter( user_email=self.user_email, debug=self.debug )
            path = writer.write(
                agent   = "test_fix_expediter",
                slug    = slug,
                title   = f"Test Fix Expediter Report — {self.source_test_suite_job_id}",
                body_md = body_md,
            )
            self.artifacts[ "report_path" ] = path
            if self.debug: print( f"[TestFixExpediterJob] Final report written: {path}" )
            return path

        except Exception as e:
            print( f"[TestFixExpediterJob] Failed to write final report (non-fatal): {e}" )
            return None


def quick_smoke_test():
    """Quick smoke test for TestFixExpediterJob."""
    cu.print_banner( "TestFixExpediterJob Smoke Test", prepend_nl=True )

    try:
        # 1: JOB_TYPE and JOB_PREFIX constants
        assert TestFixExpediterJob.JOB_TYPE == "test_fix_expediter"
        assert TestFixExpediterJob.JOB_PREFIX == "tfe"
        print( "✓ JOB_TYPE and JOB_PREFIX constants correct" )

        # 2: Instantiation
        job = TestFixExpediterJob(
            remediation_snapshot_path = "test-suite/fake-remediation.json",
            source_test_suite_job_id  = "ts-abc12345",
            user_id                   = "u1",
            user_email                = "t@t.com",
            session_id                = "s1",
            original_test_types       = [ "e2e" ],
            dry_run                   = True,
            debug                     = False,
        )
        assert job.remediation_snapshot_path == "test-suite/fake-remediation.json"
        assert job.source_test_suite_job_id == "ts-abc12345"
        assert job.dry_run == True
        assert job.remediation_context is None  # not loaded yet
        assert job.orchestrator is None
        print( "✓ Instantiation works" )

        # 3: id_hash format (from AgenticJobBase)
        assert job.id_hash.startswith( "tfe-" ), f"id_hash should start with tfe-, got {job.id_hash}"
        print( f"✓ id_hash format correct: {job.id_hash}" )

        # 4: last_question_asked property
        q = job.last_question_asked
        assert "ts-abc12345" in q
        print( f"✓ last_question_asked: {q}" )

        print( "\n✓ TestFixExpediterJob smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
