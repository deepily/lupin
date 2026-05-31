"""
Bug Fix Expediter background job for queue-based execution.

Takes a dead job's context, diagnoses the failure, proposes fixes,
and optionally applies a fix and retries the original job.

Example:
    job = BugFixExpediterJob(
        dead_job_id = "dr-abc12345::user123",
        user_id     = "user123",
        user_email  = "user@example.com",
        session_id  = "wise-penguin",
        debug       = True
    )
    result = job.do_all()  # Runs pipeline and returns conversational answer
"""

import asyncio
import time
from datetime import datetime
from typing import Optional

import cosa.utils.util as cu
from cosa.agents.agentic_job_base import AgenticJobBase
from cosa.rest.job_state import JobState


class BugFixExpediterJob( AgenticJobBase ):
    """
    Background job for Bug Fix Expediter execution.

    Runs the three-phase forensic pipeline (diagnose -> propose -> fix)
    on a dead job's context. Phase 1 foundation: packages dead job context
    and returns a placeholder (orchestrator pipeline is Phase 2+).

    Attributes:
        dead_job_id: The id_hash of the failed/interrupted job to fix
        extra_context: Optional additional context from user
        dead_job_context: Extracted context (set during execution)
        diagnosis: Root cause analysis (set during execution, Phase 2+)
        cost_summary: Execution cost summary (set after completion)
    """

    JOB_TYPE   = "bug_fix_expediter"
    JOB_PREFIX = "bfe"

    def __init__(
        self,
        dead_job_id: str,
        user_id: str,
        user_email: str,
        session_id: str,
        extra_context: str = "",
        dry_run: bool = False,
        lead_model_override:   Optional[ str ] = None,
        worker_model_override: Optional[ str ] = None,
        thinking_effort:       Optional[ str ] = None,
        debug: bool = False,
        verbose: bool = False
    ) -> None:
        """
        Initialize a Bug Fix Expediter job.

        Requires:
            - dead_job_id is a non-empty string (id_hash from job_history)
            - user_id is a valid system ID
            - user_email is a valid email address
            - session_id is a WebSocket session ID

        Ensures:
            - Job ID generated with "bfe-" prefix
            - All parameters stored for execution

        Args:
            dead_job_id: The id_hash of the dead job to fix
            user_id: System ID of the job owner
            user_email: Email address for notification routing
            session_id: WebSocket session for notifications
            extra_context: Optional user-provided context about the failure
            dry_run: Simulate execution without making changes
            lead_model_override:   Optional per-invocation override of the BFE
                                   lead model (e.g. "claude-sonnet-4-6" for E2E
                                   --cheap runs). Applied after config.from_config
                                   loads INI defaults. None = use INI value.
            worker_model_override: Optional per-invocation override of the BFE
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
            verbose    = verbose
        )

        self.dead_job_id           = dead_job_id
        self.extra_context         = extra_context
        self.dry_run               = dry_run
        self.lead_model_override   = lead_model_override
        self.worker_model_override = worker_model_override
        self.thinking_effort       = thinking_effort

        # Results (populated after execution)
        self.dead_job_context = None    # DeadJobContext
        self.diagnosis        = None    # DiagnosisResult (Phase 2+)
        self.cost_summary     = None

    @property
    def last_question_asked( self ) -> str:
        """
        Display string for queue UI.

        Returns:
            str: Human-readable job description
        """
        return f"[Bug Fix Expediter] Fix job: {self.dead_job_id}"

    def do_all( self ) -> str:
        """
        Execute bug fix pipeline and return conversational answer.

        This is the main entry point called by RunningFifoQueue.
        Bridges to the async _execute() method via asyncio.run().

        Returns:
            str: Conversational answer summarizing results
        """
        if self.debug: print( f"[BugFixExpediterJob] Starting do_all() for dead job: {self.dead_job_id}" )

        self.state      = JobState.RUNNING
        self.started_at = cu.get_current_datetime_iso()

        try:
            result = asyncio.run( self._execute() )

            # Checkpoint-resume: _execute() returns __STALLED__ sentinel when
            # a voice gate timed out and the orchestrator saved its state.
            # (Session 9056c113 Phase E.2)
            if result == "__STALLED__":
                self.state                 = JobState.STALLED
                self.completed_at          = cu.get_current_datetime_iso()
                self.answer_conversational = "BFE stalled at voice gate. Resume when ready."
                if self.debug: print( "[BugFixExpediterJob] Stalled — checkpoint saved" )
                return self.answer_conversational

            # Check if cancellation was requested during execution
            if self._cancel_requested:
                self.state                 = JobState.CANCELLED
                self.completed_at          = cu.get_current_datetime_iso()
                self.error                 = "Cancelled by user request"
                self.answer_conversational = result or "Bug fix was cancelled."
                if self.debug: print( "[BugFixExpediterJob] Cancelled by user request" )
                return self.answer_conversational

            self.state        = JobState.COMPLETED
            self.completed_at = cu.get_current_datetime_iso()
            self.result       = result
            self.answer_conversational = result

            if self.debug:
                duration = self.get_execution_duration_seconds()
                print( f"[BugFixExpediterJob] Completed in {duration:.1f}s" )

            return result

        except Exception as e:
            import traceback
            tb_str = traceback.format_exc()

            self.state        = JobState.FAILED
            self.completed_at = cu.get_current_datetime_iso()
            self.error        = f"{e}\n\n{tb_str}"
            self.answer_conversational = f"Bug fix failed: {str( e )}"

            print( f"[BugFixExpediterJob] Failed: {e}" )
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
        Internal async bug fix execution.

        Phase 1 foundation: packages dead job context and returns placeholder.
        Orchestrator pipeline (diagnose -> propose -> fix) is Phase 2+.

        Returns:
            str: Conversational summary of results
        """
        from cosa.agents.bug_fix_expediter import voice_io, cosa_interface
        from cosa.agents.bug_fix_expediter.dead_job_packager import package_dead_job

        self._start_time = time.time()

        # Re-establish core voice_io binding (import-order race)
        voice_io.reconfigure()

        # Handle dry-run mode
        if self.dry_run:
            return await self._execute_dry_run( voice_io, cosa_interface )

        # Set sender identity
        cosa_interface.SENDER_ID   = cosa_interface._get_sender_id( suffix=self.base_id )
        cosa_interface.TARGET_USER = self.user_email

        # Set job_id for auto-injection into all downstream notify() calls
        voice_io.set_job_id( self.id_hash )

        try:
            # Phase 0: Package dead job context
            await voice_io.notify(
                f"Packaging dead job context: {self.dead_job_id}",
                priority="medium", job_id=self.id_hash, queue_name="run"
            )

            self.dead_job_context = package_dead_job( self.dead_job_id, debug=self.debug )

            if self.dead_job_context is None:
                msg = f"Dead job not found: {self.dead_job_id}"
                self._write_final_report( status="dead_job_not_found", summary_line=msg )
                await voice_io.notify( msg, priority="high", job_id=self.id_hash, queue_name="run" )
                return msg

            self.artifacts[ "dead_job_context" ] = self.dead_job_context.model_dump()

            await voice_io.notify(
                f"Dead job packaged: {self.dead_job_context.job_type} "
                f"(status={self.dead_job_context.status})",
                priority="medium", job_id=self.id_hash, queue_name="run"
            )

            # Phase 1: Diagnose (Lead agent analyzes failure)
            from cosa.agents.bug_fix_expediter.orchestrator import BFEOrchestrator
            from cosa.agents.bug_fix_expediter.config import BugFixExpediterConfig
            from cosa.config.configuration_manager import ConfigurationManager

            config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
            config     = BugFixExpediterConfig.from_config( config_mgr, debug=self.debug )

            # Per-invocation model overrides (e.g. E2E --cheap runs)
            if self.lead_model_override:
                if self.debug: print( f"[BFE] lead_model overridden: {config.lead_model} -> {self.lead_model_override}" )
                config.lead_model = self.lead_model_override
            if self.worker_model_override:
                if self.debug: print( f"[BFE] worker_model overridden: {config.worker_model} -> {self.worker_model_override}" )
                config.worker_model = self.worker_model_override
            if self.thinking_effort:
                if self.debug: print( f"[BFE] thinking_effort set: {self.thinking_effort}" )
                config.thinking_effort = self.thinking_effort

            orchestrator = BFEOrchestrator(
                dead_job_context = self.dead_job_context,
                extra_context    = self.extra_context,
                config           = config,
                session_id       = self.session_id,
                job_id           = self.id_hash,
                cancel_check     = lambda: self._cancel_requested,
                debug            = self.debug,
                verbose          = self.verbose,
            )

            # Store orchestrator ref for external cancellation (AgenticJobBase protocol)
            self._orchestrator = orchestrator

            # Resume from checkpoint if this is a resumed BFE job (Session 9056c113 Phase E.2)
            if hasattr( self, "_resume_checkpoint" ) and self._resume_checkpoint:
                orchestrator.load_checkpoint( self._resume_checkpoint )
                orchestrator.set_resume_phase( self._resume_checkpoint[ "phase_ordinal" ] )
                print( f"[BFE] Resuming from phase ordinal {self._resume_checkpoint[ 'phase_ordinal' ]}" )

            self.diagnosis = await orchestrator.run_diagnosis()
            orchestrator.diagnosis = self.diagnosis   # populate for save_checkpoint
            self.artifacts[ "diagnosis" ] = self.diagnosis.model_dump()

            # Phase 2: Propose (Lead agent generates fix proposals)
            proposed_fixes, selected_fix, plan_path = await orchestrator.run_proposal( self.diagnosis )

            # Populate orchestrator state for save_checkpoint (Phase E.2)
            orchestrator.proposed_fixes = proposed_fixes
            orchestrator.selected_fix   = selected_fix
            orchestrator.plan_path      = plan_path

            self.artifacts[ "proposed_fixes" ] = [ f.model_dump() for f in proposed_fixes ]
            self.artifacts[ "plan_path" ]      = plan_path

            if selected_fix:
                self.artifacts[ "selected_fix" ] = selected_fix.model_dump()

            # Phase 3 + 5: wrap in worktree_scope so isolation (when enabled)
            # spans both FixExecutor and GitStrategist (Bug 9, 2026-04-16).
            if selected_fix:
                async with orchestrator.worktree_scope():
                    fix_result = await orchestrator.run_fix( self.diagnosis, selected_fix, plan_path )
                    orchestrator.fix_result = fix_result
                    self.artifacts[ "fix_result" ] = fix_result.model_dump()

                    # Phase 5: Git strategy (commit / branch / PR based on trust proxy)
                    if fix_result.success and orchestrator.last_files_changed:  # pragma: no branch - false-arc unrepresentable: trailing if inside async-with; both outcomes covered (test_job: git-run + git-skipped)
                        fix_result = await orchestrator.run_git_strategy(
                            fix_result, orchestrator.last_files_changed, plan_path
                        )
                        orchestrator.fix_result = fix_result
                        self.artifacts[ "fix_result" ] = fix_result.model_dump()
            else:
                from cosa.agents.bug_fix_expediter.state import FixResult
                fix_result = FixResult( applied=False, success=False, details="No fix selected" )
                orchestrator.fix_result = fix_result

            fix_summary = f"{len( proposed_fixes )} fix(es) proposed"
            if selected_fix:
                fix_summary += f", selected: '{selected_fix.title}'"
            if fix_result.applied:
                fix_summary += f", applied: {'success' if fix_result.success else 'failed'}"

            await voice_io.notify(
                "Fix phase complete." if fix_result.applied else "No fix applied.",
                priority="medium", job_id=self.id_hash, queue_name="run"
            )

            # Phase 6: Resubmit original job if fix succeeded
            resubmit_id = None
            if fix_result.success and fix_result.applied:
                resubmit_id = await self._resubmit_original_job( voice_io )
                if resubmit_id:
                    fix_result.resubmitted_job_id = resubmit_id
                    self.artifacts[ "fix_result" ]       = fix_result.model_dump()
                    self.artifacts[ "resubmitted_job_id" ] = resubmit_id

            resubmit_msg = ""
            if resubmit_id:
                resubmit_msg = f" Resubmitted as {resubmit_id}."
            elif fix_result.success and fix_result.applied:
                resubmit_msg = " Resubmit skipped (no auto-fix config or queue unavailable)."

            # ── Completion report (Phase 11 pattern: outcome-aware TTS + rich abstract) ──
            n_proposed  = len( proposed_fixes )
            fix_applied = fix_result.success and fix_result.applied
            resubmit_ok = resubmit_id is not None
            duration    = round( time.time() - self._start_time, 1 )
            root_cause  = self.diagnosis.root_cause if self.diagnosis else ""

            # Three-variant TTS (mirrors TFE Phase A pattern)
            if fix_applied and resubmit_ok:
                tts_msg = "Bug Fix Expediter complete. Fix applied and job resubmitted."
            elif fix_applied:
                tts_msg = "Bug Fix Expediter complete. Fix applied, no resubmit."
            else:
                tts_msg = (
                    f"Bug Fix Expediter complete. "
                    f"{n_proposed} fix{'es' if n_proposed != 1 else ''} proposed, "
                    f"none applied successfully."
                )

            # Rich markdown abstract (UI-only, not spoken)
            lines = [ "**BFE Activity Report**", "" ]
            lines.append( f"**Dead job**: `{self.dead_job_id}`" )
            lines.append( f"**Root cause**: {root_cause[:150]}" )
            lines.append(
                f"**Proposed**: {n_proposed} | **Fix applied**: {'yes' if fix_applied else 'no'}"
            )
            if plan_path:
                lines.append( f"**Plan**: `{plan_path}`" )
            if resubmit_id:
                lines.append( f"**Resubmitted**: `{resubmit_id}`" )
            if getattr( fix_result, "pr_url", None ):
                lines.append( f"**PR**: {fix_result.pr_url}" )
            lines.append( f"**Duration**: {duration}s" )

            # Failed-fix diagnostics — last_stderr retained by shared FixExecutor's
            # auto-reject path. Mirrors TFE's end-of-run report parity so BFE
            # triage doesn't require digging through worktree logs.
            if not fix_applied and fix_result.last_stderr and fix_result.attempts > 0:
                lines.append( "" )
                lines.append(
                    f"**Failed fix diagnostics** ({fix_result.attempts} attempt(s)):"
                )
                lines.append( "```" )
                lines.append( fix_result.last_stderr )
                lines.append( "```" )

            # Worktree artifacts — delegated to pure static helper on the
            # orchestrator class for unit-test isolation. Called via the
            # class (not self.orchestrator) because BFE uses a local-variable
            # orchestrator, not an instance attribute.
            from cosa.agents.bug_fix_expediter.orchestrator import BFEOrchestrator
            lines.extend(
                BFEOrchestrator.render_worktree_artifacts_abstract(
                    self.id_hash, fix_result, fix_applied
                )
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
                print( f"[BugFixExpediterJob] completion notify failed: {notify_err}" )

            # Conversational answer with real stats
            result = (
                f"BFE complete: {n_proposed} proposed, "
                f"{'fix applied' if fix_applied else 'no fix applied'}. "
                f"Root cause: {root_cause[:80]}. "
                f"Plan: {plan_path}.{resubmit_msg}"
            )

            # Write comprehensive final report before returning.
            self._write_final_report(
                status       = "completed" if fix_applied else "completed_no_fix",
                summary_line = result,
            )

            return result

        except Exception as e:
            # Check for StalledException first (clean stall with checkpoint).
            # Imported here so state.py changes don't force module reload.
            from cosa.agents.bug_fix_expediter.state import StalledException
            if isinstance( e, StalledException ):
                # Persist checkpoint to artifacts for metadata_json serialization
                self.artifacts[ "checkpoint" ] = e.checkpoint
                if e.checkpoint.get( "artifacts", {} ).get( "plan_path" ):
                    self.artifacts[ "plan_path" ] = e.checkpoint[ "artifacts" ][ "plan_path" ]

                try:
                    await voice_io.notify(
                        f"BFE stalled at {e.phase} — resume when ready",
                        priority   = "high",
                        abstract   = (
                            f"**BFE Stalled**\n\n"
                            f"**Phase**: {e.phase}\n"
                            f"**Reason**: {e.checkpoint.get( 'stall_reason', 'voice_gate_timeout' )}\n"
                            f"**Dead job**: `{self.dead_job_id}`\n\n"
                            f"Resume via UI 'Resume from Checkpoint' button or "
                            f"`POST /api/jobs/{self.id_hash}/resume-from-checkpoint`"
                        ),
                        job_id     = self.id_hash,
                        queue_name = "todo",
                    )
                except Exception as notify_err:
                    print( f"[BugFixExpediterJob] stall notify failed: {notify_err}" )

                self._write_final_report(
                    status       = "stalled",
                    summary_line = f"BFE stalled at phase={e.phase}",
                )

                return "__STALLED__"

            # Original error handling
            await voice_io.notify(
                f"Bug Fix Expediter error: {str( e )[ :100 ]}",
                priority="urgent", job_id=self.id_hash, queue_name="run"
            )
            raise

        finally:
            voice_io.clear_job_id()

    async def _resubmit_original_job( self, voice_io ) -> Optional[ str ]:
        """
        Phase 6: Resubmit the original failed job after successful fix.

        Reconstructs the original job using its persisted metadata and
        pushes it to the todo queue as the original user.

        Requires:
            - self.dead_job_context is populated (Phase 0 completed)
            - Fix was successful (caller must check)

        Ensures:
            - Returns resubmitted job's id_hash on success, None on failure
            - Job is submitted as the original user (user_id, user_email, session_id)
            - Notifications sent at each stage
            - Never raises — returns None on any error

        Returns:
            str or None: Resubmitted job id_hash, or None if skipped/failed
        """
        from cosa.agents.bug_fix_expediter.state import BFEPhase

        if self.dead_job_context is None:
            if self.debug: print( "[BFE] Cannot resubmit: no dead_job_context" )
            return None

        ctx = self.dead_job_context

        # Check if auto-fix resubmission is enabled
        try:
            from cosa.config.configuration_manager import ConfigurationManager
            config_mgr   = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
            auto_enabled = config_mgr.get( "auto fix enabled", default=False, return_type="boolean" )
            if not auto_enabled:
                if self.debug: print( "[BFE] Auto-fix resubmit disabled in config" )
                return None
        except Exception as e:
            if self.debug: print( f"[BFE] Config check failed, skipping resubmit: {e}" )
            return None

        await voice_io.notify(
            f"Resubmitting original {ctx.job_type} job as {ctx.user_email}...",
            priority="medium", job_id=self.id_hash, queue_name="run"
        )

        try:
            from cosa.rest.agentic_job_factory import create_agentic_job
            from cosa.rest.queue_extensions import user_job_tracker

            # Use the original routing command to reconstruct the job
            routing_command = ctx.routing_command
            if not routing_command:
                if self.debug: print( f"[BFE] No routing_command in dead job context, cannot resubmit" )
                await voice_io.notify(
                    "Cannot resubmit: original routing command not found in job history.",
                    priority="high", job_id=self.id_hash, queue_name="run"
                )
                return None

            # Extract original args from metadata_json
            metadata  = ctx.metadata_json or {}
            args_dict = metadata.get( "original_args", {} )

            # If original_args not stored, reconstruct minimal args from question_text
            if not args_dict:
                args_dict = { "query": ctx.question_text }

            # Create the job as the original user
            new_job = create_agentic_job(
                command    = routing_command,
                args_dict  = args_dict,
                user_id    = ctx.user_id,
                user_email = ctx.user_email,
                session_id = ctx.session_id,
                debug      = self.debug,
                verbose    = self.verbose,
            )

            if new_job is None:
                await voice_io.notify(
                    f"Resubmit failed: factory returned None for command '{routing_command}'.",
                    priority="high", job_id=self.id_hash, queue_name="run"
                )
                return None

            # Register scoped ID and push to todo queue
            new_job.id_hash = user_job_tracker.register_scoped_job(
                new_job.id_hash, ctx.user_id, ctx.session_id
            )

            # Get the todo queue from the app module singleton
            import fastapi_app.main as main_module
            todo_queue = main_module.jobs_todo_queue
            if todo_queue is None:
                await voice_io.notify(
                    "Resubmit failed: todo queue not available.",
                    priority="high", job_id=self.id_hash, queue_name="run"
                )
                return None

            todo_queue.push( new_job )

            await voice_io.notify(
                f"Original job resubmitted as {new_job.id_hash}. Notifications will route to your UI.",
                priority="high", job_id=new_job.id_hash, queue_name="todo"
            )

            if self.debug:
                print( f"[BFE] Resubmitted job: {new_job.id_hash} "
                       f"(type={ctx.job_type}, user={ctx.user_email})" )

            return new_job.id_hash

        except Exception as e:
            print( f"[BFE] Resubmit failed: {e}" )
            await voice_io.notify(
                f"Resubmit failed: {str( e )[ :100 ]}",
                priority="high", job_id=self.id_hash, queue_name="run"
            )
            return None

    async def _execute_dry_run( self, voice_io, cosa_interface ) -> str:
        """
        Execute dry-run mode with breadcrumb notifications + Phase 6 resubmit.

        Simulates the three-phase pipeline (packaging → diagnosis → proposal → fix)
        without calling real agents, then exercises the Phase 6 resubmit path
        end-to-end so the full repair loop can be validated at $0 cost.

        The dry-run "fix" strips any `force_failure_mode` from the original job's
        `metadata_json.original_args` so the resubmitted job runs as a clean
        dry-run. This simulates the BFE "repairing" the mock failure condition.

        Requires:
            - self.dead_job_id references a real row in job_history

        Ensures:
            - Breadcrumb notifications fired for all phases
            - DeadJobContext packaged from real DB row
            - _resubmit_original_job() called with a mocked successful FixResult
            - artifacts["resubmitted_job_id"] populated on successful resubmit
            - $0.00 cost, no git commits, no real agent calls

        Args:
            voice_io: Voice I/O module for notifications
            cosa_interface: COSA interface module for sender ID

        Returns:
            str: Mock conversational summary including resubmitted job id
        """
        import asyncio
        from cosa.agents.bug_fix_expediter.dead_job_packager import package_dead_job
        from cosa.agents.bug_fix_expediter.state import FixResult

        cosa_interface.SENDER_ID   = cosa_interface._get_sender_id( suffix=self.base_id )
        cosa_interface.TARGET_USER = self.user_email

        # Set job_id for auto-injection into downstream notify() calls
        voice_io.set_job_id( self.id_hash )

        if self.debug: print( f"[BugFixExpediterJob] DRY RUN MODE for dead job: {self.dead_job_id}" )

        try:
            # Breadcrumb: Packaging (package REAL DeadJobContext so _resubmit_original_job works)
            await voice_io.notify( "🧪 Dry run: Packaging dead job context...", priority="low", job_id=self.id_hash, queue_name="run" )
            await asyncio.sleep( 1.0 )
            self.dead_job_context = package_dead_job( self.dead_job_id, debug=self.debug )

            if self.dead_job_context is None:
                msg = f"Dry run: dead job not found: {self.dead_job_id}"
                self._write_final_report( status="dead_job_not_found_dry_run", summary_line=msg )
                await voice_io.notify( msg, priority="high", job_id=self.id_hash, queue_name="run" )
                return msg

            self.artifacts[ "dead_job_context" ] = self.dead_job_context.model_dump()

            # Breadcrumb: Diagnosis
            await voice_io.notify( "🧪 Dry run: Diagnosing root cause...", priority="low", job_id=self.id_hash, queue_name="run" )
            await asyncio.sleep( 1.0 )

            self.artifacts[ "diagnosis" ] = {
                "root_cause"     : "Simulated root cause (dry-run mock)",
                "error_category" : "unknown",
                "confidence"     : 0.0,
            }

            # Breadcrumb: Proposal
            await voice_io.notify( "🧪 Dry run: Generating fix proposals...", priority="low", job_id=self.id_hash, queue_name="run" )
            await asyncio.sleep( 1.0 )

            # Breadcrumb: Fix application
            await voice_io.notify( "🧪 Dry run: Applying fix (simulated)...", priority="low", job_id=self.id_hash, queue_name="run" )
            await asyncio.sleep( 1.0 )

            # Simulate "fix applied" by preparing the resubmit args:
            #   1. Start from the exact args the job was originally submitted with
            #      (now reliably persisted as metadata_json.original_args)
            #   2. Strip force_failure_mode so the resubmitted job actually succeeds
            #   3. Ensure dry_run=True so the resubmitted job stays in dry-run mode
            metadata      = self.dead_job_context.metadata_json or {}
            original_args = dict( metadata.get( "original_args" ) or {} )
            original_args.pop( "force_failure_mode", None )
            original_args[ "dry_run" ] = True
            metadata[ "original_args" ] = original_args
            self.dead_job_context.metadata_json = metadata
            if self.debug: print( f"[BugFixExpediterJob] Dry-run fix: resubmit args = {original_args}" )

            # Build mocked-successful FixResult so _resubmit_original_job is reached
            fix_result = FixResult( applied=True, success=True, details="dry-run mock fix" )
            self.artifacts[ "fix_result" ] = fix_result.model_dump()

            # Phase 6: Resubmit original job (real code path, same as live _execute)
            await voice_io.notify( "🧪 Dry run: Resubmitting original job (simulated fix applied)...", priority="low", job_id=self.id_hash, queue_name="run" )
            resubmit_id = await self._resubmit_original_job( voice_io )
            if resubmit_id:
                fix_result.resubmitted_job_id = resubmit_id
                self.artifacts[ "fix_result" ]         = fix_result.model_dump()
                self.artifacts[ "resubmitted_job_id" ] = resubmit_id

            resubmit_msg = ""
            if resubmit_id:
                resubmit_msg = f" Resubmitted as {resubmit_id}."
            else:
                resubmit_msg = " Resubmit skipped (auto fix disabled or queue unavailable)."

            completion_abstract = f"""**🧪 Dry Run Complete!**

**Dead Job**: {self.dead_job_id}
**Diagnosis**: Simulated root cause (dry run)
**Fix**: Simulated success (dry run)
**Resubmit**: {resubmit_id or "skipped"}
**Stats**: $0.00 | 0 tokens | 5.0s (simulated)"""

            await voice_io.notify(
                "🧪 Dry run complete! Phase 6 loop validated.",
                priority="medium", abstract=completion_abstract,
                job_id=self.id_hash, queue_name="run"
            )

            dry_run_result = f"Dry run complete. Bug fix simulation finished.{resubmit_msg}"
            self._write_final_report( status="dry_run_completed", summary_line=dry_run_result )
            return dry_run_result

        finally:
            voice_io.clear_job_id()

    def _write_final_report( self, status: str, summary_line: str ) -> Optional[ str ]:
        """
        Write a comprehensive final-report markdown file for this BFE run and
        store its path in `self.artifacts["report_path"]`.

        Called at each terminal exit of the BFE pipeline (dry-run dead-job-not-
        found, live dead-job-not-found, stall, happy path). Never blocks the
        job on failure — returns None and logs a warning if writing fails.

        The report captures everything the agent accumulated in-memory during
        the run: dead_job_context, diagnosis, proposed_fixes, selected_fix,
        fix_result, resubmitted_job_id, and checkpoint (if stalled).

        Args:
            status:       Terminal state ("completed", "stalled", "dead_job_not_found", etc.)
            summary_line: One-line human summary (same text as answer_conversational)

        Returns:
            Optional path to the written report, or None on error.
        """
        try:
            from cosa.agents.shared.report_writer import ReportWriter

            duration    = self.get_execution_duration_seconds() if hasattr( self, "get_execution_duration_seconds" ) else None
            duration_s  = f"{duration:.1f}s" if duration is not None else "n/a"
            artifacts   = self.artifacts or {}
            sections    = [ ]

            sections.append( "## Summary\n" )
            sections.append( f"- **Status**: {status}" )
            sections.append( f"- **BFE job id**: `{self.id_hash}`" )
            sections.append( f"- **Dead job id**: `{self.dead_job_id}`" )
            sections.append( f"- **Dry run**: {self.dry_run}" )
            sections.append( f"- **Duration**: {duration_s}" )
            if artifacts.get( "resubmitted_job_id" ):
                sections.append( f"- **Resubmitted as**: `{artifacts[ 'resubmitted_job_id' ]}`" )
            sections.append( f"\n**Conversational answer**: {summary_line}\n" )

            # Dead job context
            if artifacts.get( "dead_job_context" ):
                ctx = artifacts[ "dead_job_context" ]
                sections.append( "\n## Dead job context\n" )
                sections.append( f"- **Job type**: `{ctx.get( 'job_type', 'unknown' )}`" )
                sections.append( f"- **Original question**: {ctx.get( 'question', 'n/a' )}" )
                err = ctx.get( "error" )
                if err:
                    sections.append( "\n**Error**:\n```\n" + str( err )[ :2000 ] + "\n```" )
                st = ctx.get( "stack_trace" )
                if st:
                    sections.append( "\n**Stack trace** (truncated):\n```\n" + str( st )[ :2000 ] + "\n```" )
            else:
                sections.append( "\n## Dead job context\n\n_not available — agent exited before package_dead_job succeeded_\n" )

            # Diagnosis
            diag = artifacts.get( "diagnosis" )
            if diag:
                sections.append( "\n## Diagnosis\n" )
                sections.append( f"- **Root cause**: {diag.get( 'root_cause', 'n/a' )}" )
                sections.append( f"- **Category**: {diag.get( 'error_category', 'n/a' )}" )
                conf = diag.get( "confidence" )
                if conf is not None:
                    try:    sections.append( f"- **Confidence**: {float( conf ):.0%}" )
                    except: sections.append( f"- **Confidence**: {conf}" )

            # Proposed fixes
            proposals = artifacts.get( "proposed_fixes" ) or []
            if proposals:
                sections.append( "\n## Proposed fixes\n" )
                for i, p in enumerate( proposals, 1 ):
                    sections.append( f"### {i}. {p.get( 'title', 'untitled' )}" )
                    sections.append( f"- **Type**: {p.get( 'fix_type', 'n/a' )}" )
                    sections.append( f"- **Risk**: {p.get( 'risk_level', 'n/a' )}" )
                    sections.append( f"- **Effort**: {p.get( 'estimated_effort', 'n/a' )}" )
                    desc = p.get( "description" )
                    if desc:
                        sections.append( f"\n{desc}\n" )

            # Selected fix
            sel = artifacts.get( "selected_fix" )
            if sel:
                sections.append( "\n## Selected fix\n" )
                sections.append( f"- **Title**: {sel.get( 'title', 'n/a' )}" )
                sections.append( f"- **Type**: {sel.get( 'fix_type', 'n/a' )}" )
                reason = sel.get( "selection_reason" ) or sel.get( "reason" )
                if reason:
                    sections.append( f"- **Reason**: {reason}" )

            # Fix result
            fix_result = artifacts.get( "fix_result" )
            if fix_result:
                sections.append( "\n## Fix result\n" )
                sections.append( f"- **Applied**: {fix_result.get( 'applied' )}" )
                sections.append( f"- **Success**: {fix_result.get( 'success' )}" )
                sections.append( f"- **Details**: {fix_result.get( 'details', 'n/a' )}" )

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

            # Appendix: linked artifacts
            if artifacts.get( "plan_path" ):
                sections.append( f"\n## Appendix\n\n- **Plan**: `{artifacts[ 'plan_path' ]}`" )

            body_md = "\n".join( sections )

            # Slug: prefer dead_job_id fragment + status
            base_slug = ( self.dead_job_id or "bfe" ).split( "::" )[ 0 ]
            slug      = f"{base_slug}-{status}"

            writer = ReportWriter( user_email=self.user_email, debug=self.debug )
            path = writer.write(
                agent   = "bug_fix_expediter",
                slug    = slug,
                title   = f"Bug Fix Expediter Report — {self.dead_job_id}",
                body_md = body_md,
            )
            self.artifacts[ "report_path" ] = path
            if self.debug: print( f"[BugFixExpediterJob] Final report written: {path}" )
            return path

        except Exception as e:
            print( f"[BugFixExpediterJob] Failed to write final report (non-fatal): {e}" )
            return None


def quick_smoke_test():
    """Quick smoke test for BugFixExpediterJob."""
    import cosa.utils.util as cu

    cu.print_banner( "BugFixExpediterJob Smoke Test", prepend_nl=True )

    try:
        # 1: Import
        from cosa.agents.bug_fix_expediter.job import BugFixExpediterJob
        print( "✓ Module imported successfully" )

        # 2: Instantiation
        job = BugFixExpediterJob(
            dead_job_id = "dr-test1234::user123",
            user_id     = "user123",
            user_email  = "test@test.com",
            session_id  = "session456",
            debug       = True
        )
        print( f"✓ Job created with id: {job.id_hash}" )

        # 3: ID format
        assert job.id_hash.startswith( "bfe-" ), "ID should start with bfe-"
        print( f"✓ ID format correct: {job.id_hash}" )

        # 4: last_question_asked
        lqa = job.last_question_asked
        assert "[Bug Fix Expediter]" in lqa
        assert "dr-test1234" in lqa
        print( f"✓ last_question_asked: {lqa}" )

        # 5: is_cacheable
        assert job.is_cacheable == False
        print( "✓ is_cacheable correctly returns False" )

        # 6: Attributes
        assert job.dead_job_id == "dr-test1234::user123"
        assert job.user_email == "test@test.com"
        assert job.state == JobState.PENDING
        assert job.dry_run == False
        print( "✓ All attributes set correctly" )

        # 7: Class constants
        assert BugFixExpediterJob.JOB_TYPE == "bug_fix_expediter"
        assert BugFixExpediterJob.JOB_PREFIX == "bfe"
        print( "✓ Class constants correct" )

        print( "\n⚠ Note: do_all() not tested (requires running server)" )
        print( "\n✓ BugFixExpediterJob smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
