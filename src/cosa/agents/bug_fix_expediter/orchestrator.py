"""
Bug Fix Expediter Orchestrator — Diagnosis + Proposal + Fix Phases.

Phase 2: Lead agent (Opus, read-only) diagnoses failure.
Phase 3: Lead agent proposes fixes and writes plan document.
Phase 4: Coder agent (Sonnet, edit-capable) applies fix, Tester validates.

Example:
    orchestrator = BFEOrchestrator( ... )
    diagnosis = await orchestrator.run_diagnosis()
    fixes, selected, plan_path = await orchestrator.run_proposal( diagnosis )
    fix_result = await orchestrator.run_fix( diagnosis, selected, plan_path )
"""

import asyncio
import json
import logging
import queue
import threading
import uuid
from contextlib import asynccontextmanager
from typing import Optional, Callable

import cosa.utils.util as cu

from cosa.agents.bug_fix_expediter.state import BFEPhase, DiagnosisResult, ProposedFix, FixResult
from cosa.agents.bug_fix_expediter.prompts.diagnosis import (
    DIAGNOSIS_SYSTEM_PROMPT,
    build_diagnosis_prompt,
)
from cosa.agents.bug_fix_expediter.prompts.proposal import (
    PROPOSAL_SYSTEM_PROMPT,
    build_proposal_prompt,
)
from cosa.agents.bug_fix_expediter.prompts.fix import (
    CODER_SYSTEM_PROMPT,
    TESTER_SYSTEM_PROMPT,
    build_fix_prompt,
    build_verification_prompt,
    build_redelegation_prompt,
)
from cosa.agents.bug_fix_expediter.plan_writer import PlanWriter
from cosa.agents.shared.git_strategist import GitStrategist
from cosa.agents.shared.fix_executor import FixExecutor

# SWE Team reuse — safety, hooks, test runner (kept for back-compat;
# FixExecutor imports these directly, but existing BFE test fixtures may
# reference the orchestrator-module-level names)
from cosa.agents.swe_team.safety_limits import SafetyGuard, SafetyLimitError
from cosa.agents.swe_team.hooks import build_can_use_tool, post_tool_hook, wrap_prompt_for_streaming
from cosa.agents.swe_team.test_runner import run_pytest
from cosa.agents.utils.voice_io import read_gate_answer

# SDK imports — graceful fallback
try:
    from claude_agent_sdk import (
        ClaudeSDKClient,
        ClaudeAgentOptions,
        AssistantMessage,
        TextBlock,
        ToolUseBlock,
        ResultMessage,
        query as sdk_query,
        RateLimitEvent,
    )
    SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - optional-dep import guard; claude-agent-sdk is installed in this env
    SDK_AVAILABLE = False

logger = logging.getLogger( __name__ )


class BFEOrchestrator:
    """
    Orchestrator for the Bug Fix Expediter diagnosis phase.

    Delegates failure analysis to a Lead agent via the Claude Agent SDK
    and produces a structured DiagnosisResult. Supports iterative refinement,
    cancellation, ad hoc user messages, and voice-gated confirmation.

    Requires:
        - dead_job_context is a valid DeadJobContext
        - config is a BugFixExpediterConfig
        - claude_agent_sdk is installed (SDK_AVAILABLE == True)

    Ensures:
        - Returns a DiagnosisResult (may be low-confidence fallback)
        - Respects cancellation and iteration limits
        - Sends progress notifications with job_id routing
    """

    def __init__(
        self,
        dead_job_context,
        extra_context: str,
        config,
        session_id: str,
        job_id: str,
        on_state_change: Optional[ Callable ] = None,
        cancel_check: Optional[ Callable ] = None,
        debug: bool = False,
        verbose: bool = False
    ):
        """
        Initialize the BFE Orchestrator.

        Args:
            dead_job_context: DeadJobContext with failure forensics
            extra_context: Optional user-provided context
            config: BugFixExpediterConfig instance
            session_id: WebSocket session for notification routing
            job_id: Job ID for CJ Flow job card routing
            on_state_change: Optional callback for phase transitions
            cancel_check: Optional callable returning True if cancelled
            debug: Enable debug output
            verbose: Enable verbose output
        """
        self.dead_job_context  = dead_job_context
        self.extra_context     = extra_context
        self.config            = config
        self.session_id        = session_id
        self.job_id            = job_id
        self.on_state_change   = on_state_change
        self.cancel_check      = cancel_check
        self.debug             = debug
        self.verbose           = verbose
        self.current_phase     = BFEPhase.PACKAGING

        # Checkpoint state (Session 9056c113 Phase E.2) — phase methods populate
        # these as a side effect so save_checkpoint() can serialize mid-pipeline.
        # Backward-compatible: existing phase methods still return tuples; these
        # attributes are additional.
        self.diagnosis         = None    # DiagnosisResult (set by run_diagnosis)
        self.proposed_fixes    = []      # list[ProposedFix] (set by run_proposal)
        self.selected_fix      = None    # ProposedFix (set by run_proposal)
        self.fix_result        = None    # FixResult (set by run_fix / run_git_strategy)
        self.plan_path         = None    # str (set by run_proposal)
        self.branch_name       = None    # str (set by run_git_strategy)
        self.commit_hashes     = []      # list[str]
        self.pr_url            = None    # str

        # Cancellation + user interrupt support (SWE Team Approach D)
        self._stop_requested   = False
        self._user_messages    = queue.Queue()
        self._urgent_interrupt = threading.Event()

        # Progress tracking
        self._diagnosis_group_id = f"pg-{uuid.uuid4().hex[ :8 ]}"

        # Phase 5: Trust proxy + last-files tracking
        self.last_files_changed: list = []
        self.proxy = None

        # Bug 9 (2026-04-16): worktree isolation state. Populated inside
        # `worktree_scope()` context manager during Phase 3+5; used by
        # `_build_coder_options`, `_build_tester_options`, and `run_git_strategy`
        # to route git / SDK operations into an isolated sandbox.
        self._worktree_cwd: Optional[ str ] = None
        try:
            from cosa.agents.swe_team.proxy.engineering_strategy import EngineeringStrategy
            self.proxy = EngineeringStrategy(
                trust_mode = self.config.trust_mode,
                debug      = self.debug,
            )
            if self.debug: print( f"[BFEOrchestrator] Trust proxy initialized (mode={self.config.trust_mode})" )
        except ImportError as e:
            if self.debug: print( f"[BFEOrchestrator] Trust proxy import failed: {e} — defaulting to L1/commit_only" )
        except Exception as e:
            if self.debug: print( f"[BFEOrchestrator] Trust proxy init failed: {e} — defaulting to L1/commit_only" )

    # =========================================================================
    # Checkpoint-resume (Session 9056c113 Phase E.2)
    # =========================================================================

    def save_checkpoint( self ) -> dict:
        """
        Serialize current BFE pipeline state to a JSON-safe dict.

        Mirrors TFE's save_checkpoint() pattern. BFE's phase methods must
        populate self.diagnosis / self.proposed_fixes / etc. as a side effect
        (see __init__ attributes) for this to capture mid-pipeline state.

        Ensures:
            - Returns dict matching CheckpointData schema
            - Pydantic models converted to dicts via .model_dump()
        """
        from cosa.agents.bug_fix_expediter.state import BFE_PHASE_ORDINALS
        from datetime import datetime

        state_snapshot = {
            "dead_job_id"      : self.dead_job_context.id_hash if self.dead_job_context else None,
            "diagnosis"        : self.diagnosis.model_dump() if self.diagnosis else None,
            "proposed_fixes"   : [ p.model_dump() for p in ( self.proposed_fixes or [] ) ],
            "selected_fix"     : self.selected_fix.model_dump() if self.selected_fix else None,
            "fix_result"       : self.fix_result.model_dump() if self.fix_result else None,
            "plan_path"        : self.plan_path,
            "branch_name"      : self.branch_name,
            "commit_hashes"    : list( self.commit_hashes or [] ),
            "pr_url"           : self.pr_url,
        }

        artifacts = {}
        if self.plan_path: artifacts[ "plan_path" ] = self.plan_path

        return {
            "phase_ordinal"  : BFE_PHASE_ORDINALS.get( self.current_phase, -1 ),
            "phase_name"     : self.current_phase.value,
            "stall_reason"   : "voice_gate_timeout",
            "stalled_at"     : datetime.now().isoformat(),
            "state_snapshot" : state_snapshot,
            "artifacts"      : artifacts,
            "resume_count"   : 0,
        }

    def load_checkpoint( self, data: dict ) -> None:
        """
        Restore BFE pipeline state from a previously saved checkpoint.

        Requires:
            - data matches CheckpointData schema (from save_checkpoint)
        """
        from cosa.agents.bug_fix_expediter.state import (
            DiagnosisResult, ProposedFix, FixResult, BFEPhase
        )

        snap = data[ "state_snapshot" ]

        self.diagnosis      = DiagnosisResult( **snap[ "diagnosis" ] ) if snap.get( "diagnosis" ) else None
        self.proposed_fixes = [ ProposedFix( **p ) for p in snap.get( "proposed_fixes", [] ) ]
        self.selected_fix   = ProposedFix( **snap[ "selected_fix" ] ) if snap.get( "selected_fix" ) else None
        self.fix_result     = FixResult( **snap[ "fix_result" ] ) if snap.get( "fix_result" ) else None
        self.plan_path      = snap.get( "plan_path" )
        self.branch_name    = snap.get( "branch_name" )
        self.commit_hashes  = snap.get( "commit_hashes", [] )
        self.pr_url         = snap.get( "pr_url" )
        self.current_phase  = BFEPhase( data[ "phase_name" ] )

    def set_resume_phase( self, phase_ordinal: int ) -> None:
        """
        Mark phases up to phase_ordinal as completed so phase methods can skip
        work that has already been done on resume.

        Requires:
            - phase_ordinal >= 0
            - load_checkpoint() has already been called
        """
        self._resume_from_ordinal = phase_ordinal

    # =========================================================================
    # Public API
    # =========================================================================

    async def run_diagnosis( self ) -> DiagnosisResult:
        """
        Run the diagnosis phase: Lead agent analyzes dead job failure.

        Requires:
            - SDK_AVAILABLE is True
            - dead_job_context is populated

        Ensures:
            - Returns DiagnosisResult (best available, even if low confidence)
            - Sends progress notifications throughout
            - Respects cancellation and max iteration limits

        Returns:
            DiagnosisResult: Structured root cause analysis
        """
        from cosa.agents.bug_fix_expediter import voice_io, cosa_interface

        if not SDK_AVAILABLE:
            logger.error( "Claude Agent SDK not available — cannot run diagnosis" )
            return self._fallback_diagnosis( "Claude Agent SDK not installed" )

        # State: PACKAGING → DIAGNOSING
        await self._emit_state( BFEPhase.PACKAGING, BFEPhase.DIAGNOSING )

        await self._notify(
            voice_io, "Starting failure diagnosis...",
            priority="medium",
            abstract=f"**Job**: {self.dead_job_context.job_type}\n"
                     f"**Error**: {( self.dead_job_context.error or 'N/A' )[ :200 ]}"
        )

        best_diagnosis = None

        for iteration in range( 1, self.config.max_diagnosis_iterations + 1 ):

            # --- Cancellation check (between iterations) ---
            if self._is_cancelled():
                logger.info( "Diagnosis cancelled by user" )
                await self._notify( voice_io, "Diagnosis cancelled.", priority="medium" )
                return best_diagnosis or self._fallback_diagnosis( "Cancelled by user" )

            # --- Drain user messages ---
            user_messages = self._drain_user_messages()
            if user_messages and self.debug:
                print( f"[BFEOrchestrator] Incorporating {len( user_messages )} user message(s) into iteration {iteration}" )

            # --- Build prompt ---
            # Only use refinement mode if we have a prior diagnosis to refine
            effective_iteration = iteration if best_diagnosis is not None else 1
            prompt = build_diagnosis_prompt(
                ctx             = self.dead_job_context,
                extra_context   = self.extra_context,
                iteration       = effective_iteration,
                prior_diagnosis = best_diagnosis,
                user_messages   = user_messages if user_messages else None,
            )

            if self.debug: print( f"[BFEOrchestrator] Diagnosis iteration {iteration}/{self.config.max_diagnosis_iterations}" )

            await self._notify(
                voice_io,
                f"Diagnosis iteration {iteration}/{self.config.max_diagnosis_iterations}",
                priority="low"
            )

            # --- SDK delegation ---
            raw_response = await self._delegate_to_lead( voice_io, prompt )

            if raw_response is None:
                logger.warning( f"SDK delegation returned None on iteration {iteration}" )
                continue

            # --- Parse result ---
            diagnosis = self._parse_diagnosis_result( raw_response )
            if self.debug:
                print( f"[BFEOrchestrator] Parsed: category={diagnosis.error_category}, "
                       f"confidence={diagnosis.confidence:.0%}, transient={diagnosis.is_transient}" )

            # Keep best diagnosis (highest confidence)
            if best_diagnosis is None or diagnosis.confidence > best_diagnosis.confidence:
                best_diagnosis = diagnosis

            # --- Confidence threshold met? ---
            if diagnosis.confidence >= self.config.min_diagnosis_confidence:
                if self.debug: print( f"[BFEOrchestrator] Confidence threshold met ({diagnosis.confidence:.0%} >= {self.config.min_diagnosis_confidence:.0%})" )
                break

            if iteration < self.config.max_diagnosis_iterations:
                await self._notify(
                    voice_io,
                    f"Confidence {diagnosis.confidence:.0%} below threshold {self.config.min_diagnosis_confidence:.0%} — refining...",
                    priority="low"
                )

        # Use best diagnosis we have
        if best_diagnosis is None:
            best_diagnosis = self._fallback_diagnosis( "All diagnosis iterations produced no result" )

        # --- Voice gate (natural break point) ---
        if not self._is_cancelled():
            from cosa.agents.bug_fix_expediter.state import (
                VoiceGateTimeoutError, VoiceGateUnreachableError, StalledException,
            )
            try:
                best_diagnosis = await self._voice_gate_diagnosis( best_diagnosis, voice_io, cosa_interface )
            except ( VoiceGateTimeoutError, VoiceGateUnreachableError ) as e:
                # No human approved — whether the ask timed out or the gate itself
                # broke. Same clean yield either way: checkpoint + stall so a human
                # can answer on resume. The message names which, because the two
                # are not the same event. (Session 9056c113 doc 16 Phase 1; row 421b9498)
                self.diagnosis = best_diagnosis   # populate for save_checkpoint
                checkpoint = self.save_checkpoint()
                why = "timeout" if isinstance( e, VoiceGateTimeoutError ) else "unreachable"
                raise StalledException(
                    checkpoint = checkpoint,
                    phase      = BFEPhase.DIAGNOSING.value,
                    message    = f"Voice gate {why} at diagnosis",
                )

        # --- Completion notification ---
        abstract = self._build_diagnosis_abstract( best_diagnosis )
        await self._notify(
            voice_io, "Diagnosis complete.",
            priority="medium", abstract=abstract
        )

        return best_diagnosis

    def queue_user_message( self, message: str, urgent: bool = False ) -> None:
        """
        Queue an ad hoc user message for incorporation into the next iteration.

        Called by job.py when users send messages during execution.
        If urgent, sets the interrupt event for immediate attention.

        Args:
            message: User message text
            urgent: If True, sets the urgent interrupt event
        """
        self._user_messages.put( message )
        if urgent:
            self._urgent_interrupt.set()

    # =========================================================================
    # SDK Delegation
    # =========================================================================

    async def _delegate_to_lead( self, voice_io, prompt: str, options=None ) -> Optional[ str ]:
        """
        Delegate analysis to the Lead agent via Claude Agent SDK.

        Requires:
            - SDK_AVAILABLE is True

        Ensures:
            - Returns raw text response from Lead agent
            - Sends progress notifications for tool usage and SDK events
            - Returns None on error

        Args:
            voice_io: Voice I/O module for notifications
            prompt: Complete prompt for the Lead agent
            options: Optional ClaudeAgentOptions override (defaults to diagnosis options)

        Returns:
            str or None: Raw agent response text
        """
        if options is None:
            options = self._build_lead_options()

        try:
            collected_text = []

            async for message in sdk_query( prompt=prompt, options=options ):
                if isinstance( message, AssistantMessage ):
                    for block in message.content:
                        if isinstance( block, TextBlock ):
                            collected_text.append( block.text )
                        elif isinstance( block, ToolUseBlock ):
                            await self._notify(
                                voice_io,
                                f"Investigating: {block.name}",
                                priority="low",
                            )
                elif isinstance( message, TextBlock ):
                    collected_text.append( message.text )
                elif isinstance( message, ResultMessage ):
                    msg_text = getattr( message, "text", str( message ) )[ :200 ]
                    await self._notify( voice_io, msg_text, priority="low" )
                elif isinstance( message, RateLimitEvent ):
                    logger.warning( f"Rate limited: retry_after={getattr( message, 'retry_after', '?' )}s" )

            raw_response = "".join( collected_text ).strip()

            if self.debug: print( f"[BFEOrchestrator] Lead response length: {len( raw_response )} chars" )

            return raw_response if raw_response else None

        except Exception as e:
            logger.error( f"SDK delegation failed: {e}" )
            if self.debug:
                import traceback
                traceback.print_exc()
            return None

    def _build_lead_options( self ):
        """
        Build ClaudeAgentOptions for the Lead (forensic analyst) agent.

        Ensures:
            - Read-only permission mode (plan)
            - Uses lead_model from config
            - Tools: Read, Glob, Grep, Bash (git only)

        Returns:
            ClaudeAgentOptions configured for forensic analysis
        """
        return ClaudeAgentOptions(
            model           = self.config.lead_model,
            system_prompt   = DIAGNOSIS_SYSTEM_PROMPT,
            tools           = [ "Read", "Glob", "Grep", "Bash" ],
            cwd             = cu.get_project_root(),
            permission_mode = "plan",
            max_turns       = self.config.max_diagnosis_iterations * 10,
            max_budget_usd  = self.config.budget_usd,
            effort          = self.config.thinking_effort,
        )

    # =========================================================================
    # JSON Parsing
    # =========================================================================

    def _parse_diagnosis_result( self, raw_response: str ) -> DiagnosisResult:
        """
        Parse a DiagnosisResult from the Lead agent's raw text response.

        Handles:
            - Clean JSON objects
            - JSON wrapped in markdown fences
            - JSON embedded in prose text
            - Parse failures (returns low-confidence fallback)

        Args:
            raw_response: Raw text from Lead agent

        Returns:
            DiagnosisResult: Parsed or fallback diagnosis
        """
        text = raw_response.strip()

        # Strip markdown code fences
        if "```json" in text:
            text = text.split( "```json" )[ -1 ]
        if "```" in text:
            text = text.split( "```" )[ 0 ]

        # Find last JSON object: search backward for } then find matching {
        json_str = self._extract_last_json_object( text )

        if json_str is None:
            logger.warning( "No JSON object found in response — returning fallback" )
            return self._fallback_diagnosis( raw_response[ :500 ] )

        try:
            data = json.loads( json_str )
            return DiagnosisResult( **data )

        except ( json.JSONDecodeError, ValueError, TypeError ) as e:
            logger.warning( f"JSON parse/validation failed: {e}" )
            return self._fallback_diagnosis( raw_response[ :500 ] )

    @staticmethod
    def _extract_last_json_object( text: str ) -> Optional[ str ]:
        """
        Extract the last JSON object from text by finding matching braces.

        Args:
            text: Text that may contain a JSON object

        Returns:
            str or None: Extracted JSON string, or None if not found
        """
        # Find last closing brace
        close_idx = text.rfind( "}" )
        if close_idx == -1:
            return None

        # Walk backward to find matching opening brace
        depth = 0
        for i in range( close_idx, -1, -1 ):
            if text[ i ] == "}":
                depth += 1
            elif text[ i ] == "{":
                depth -= 1
                if depth == 0:
                    return text[ i : close_idx + 1 ]

        return None

    @staticmethod
    def _fallback_diagnosis( reason: str ) -> DiagnosisResult:
        """
        Create a low-confidence fallback DiagnosisResult.

        The 0.1 confidence is deliberately below the default threshold (0.7)
        to trigger refinement if iterations remain.

        Args:
            reason: Description of why fallback was needed

        Returns:
            DiagnosisResult: Low-confidence fallback
        """
        return DiagnosisResult(
            root_cause          = reason,
            error_category      = "unknown",
            confidence          = 0.1,
            evidence            = [ "Failed to parse structured diagnosis" ],
            affected_components = [],
            is_transient        = False,
        )

    # =========================================================================
    # Phase 3: Proposal
    # =========================================================================

    async def run_proposal( self, diagnosis: DiagnosisResult ) -> tuple:
        """
        Run the proposal phase: Lead agent generates fix proposals.

        Requires:
            - diagnosis is a valid DiagnosisResult
            - SDK_AVAILABLE is True

        Ensures:
            - Returns ( proposed_fixes, selected_fix, plan_path )
            - Plan document written to disk
            - Voice gate for user selection if multiple fixes

        Args:
            diagnosis: DiagnosisResult from the diagnosis phase

        Returns:
            tuple: ( list[ProposedFix], Optional[ProposedFix], str )
        """
        from cosa.agents.bug_fix_expediter import voice_io, cosa_interface

        if not SDK_AVAILABLE:
            logger.error( "Claude Agent SDK not available — cannot run proposal" )
            fallback = self._fallback_proposal( "Claude Agent SDK not installed" )
            return ( fallback, None, "" )

        # Store for voice gate retry access
        self._last_diagnosis = diagnosis

        # State: DIAGNOSING → PROPOSING
        await self._emit_state( BFEPhase.DIAGNOSING, BFEPhase.PROPOSING )

        await self._notify(
            voice_io, "Generating fix proposals...",
            priority="medium",
            abstract=f"**Root Cause**: {diagnosis.root_cause[ :200 ]}\n"
                     f"**Category**: {diagnosis.error_category}"
        )

        # --- Cancellation check ---
        if self._is_cancelled():
            return ( self._fallback_proposal( "Cancelled" ), None, "" )

        # --- Drain user messages ---
        user_messages = self._drain_user_messages()
        user_feedback = "\n".join( user_messages ) if user_messages else None

        # --- Build prompt ---
        prompt = build_proposal_prompt(
            diagnosis        = diagnosis,
            dead_job_context = self.dead_job_context,
            extra_context    = self.extra_context,
            user_feedback    = user_feedback,
        )

        if self.debug: print( "[BFEOrchestrator] Delegating proposal to Lead agent" )

        # --- SDK delegation with proposal options ---
        raw_response = await self._delegate_to_lead(
            voice_io, prompt, options=self._build_proposal_options()
        )

        if raw_response is None:
            logger.warning( "SDK delegation returned None for proposal" )
            fixes = self._fallback_proposal( "Proposal generation failed" )
        else:
            fixes = self._parse_proposal_result( raw_response )

        if self.debug: print( f"[BFEOrchestrator] {len( fixes )} fix(es) proposed" )

        # --- Write plan document ---
        plan_path = ""
        try:
            writer    = PlanWriter( user_email=self.dead_job_context.user_email, debug=self.debug )
            plan_path = writer.write_plan(
                dead_job_context = self.dead_job_context,
                diagnosis        = diagnosis,
                proposed_fixes   = fixes,
            )
        except Exception as e:
            logger.warning( f"Plan document write failed: {e}" )

        # --- Voice gate (natural break point) ---
        selected_fix = None
        if not self._is_cancelled():
            from cosa.agents.bug_fix_expediter.state import (
                VoiceGateTimeoutError, VoiceGateUnreachableError, StalledException,
            )
            try:
                selected_fix = await self._voice_gate_proposal( fixes, voice_io, cosa_interface )
            except ( VoiceGateTimeoutError, VoiceGateUnreachableError ) as e:
                # Nobody approved applying a fix — the ask timed out, or the gate
                # broke. Either way: checkpoint + stall, never apply. (row 421b9498)
                # Populate orchestrator state first so save_checkpoint captures it.
                self.diagnosis      = diagnosis
                self.proposed_fixes = fixes
                self.plan_path      = plan_path
                checkpoint = self.save_checkpoint()
                why = "timeout" if isinstance( e, VoiceGateTimeoutError ) else "unreachable"
                raise StalledException(
                    checkpoint = checkpoint,
                    phase      = BFEPhase.PROPOSING.value,
                    message    = f"Voice gate {why} at proposal",
                )

            # Re-write plan with selection if user chose a fix
            if selected_fix and plan_path:
                try:
                    writer.write_plan(
                        dead_job_context = self.dead_job_context,
                        diagnosis        = diagnosis,
                        proposed_fixes   = fixes,
                        selected_fix     = selected_fix,
                    )
                except Exception as e:
                    logger.warning( f"Plan document re-write failed: {e}" )

        # --- Completion notification ---
        fix_summary = f"{len( fixes )} fix(es) proposed"
        if selected_fix:
            fix_summary += f", selected: '{selected_fix.title}'"

        await self._notify(
            voice_io, f"Proposal complete. {fix_summary}",
            priority="medium",
            abstract=self._build_proposal_abstract( fixes, selected_fix )
        )

        return ( fixes, selected_fix, plan_path )

    def _build_proposal_options( self ):
        """
        Build ClaudeAgentOptions for the proposal Lead agent.

        Ensures:
            - Read-only permission mode (plan)
            - Uses lead_model from config
            - Uses PROPOSAL_SYSTEM_PROMPT

        Returns:
            ClaudeAgentOptions configured for proposal generation
        """
        return ClaudeAgentOptions(
            model           = self.config.lead_model,
            system_prompt   = PROPOSAL_SYSTEM_PROMPT,
            tools           = [ "Read", "Glob", "Grep", "Bash" ],
            cwd             = cu.get_project_root(),
            permission_mode = "plan",
            max_turns       = 20,
            max_budget_usd  = self.config.budget_usd,
            effort          = self.config.thinking_effort,
        )

    def _parse_proposal_result( self, raw_response: str ) -> list:
        """
        Parse a list of ProposedFix from the Lead agent's raw text response.

        Handles:
            - Clean JSON arrays
            - JSON wrapped in markdown fences
            - JSON embedded in prose text
            - Parse failures (returns single fallback proposal)

        Args:
            raw_response: Raw text from Lead agent

        Returns:
            list[ProposedFix]: Parsed proposals (at least 1)
        """
        text = raw_response.strip()

        # Strip markdown code fences
        if "```json" in text:
            text = text.split( "```json" )[ -1 ]
        if "```" in text:
            text = text.split( "```" )[ 0 ]

        json_str = self._extract_last_json_array( text )

        if json_str is None:
            logger.warning( "No JSON array found in proposal response — returning fallback" )
            return self._fallback_proposal( raw_response[ :500 ] )

        try:
            data = json.loads( json_str )
            if not isinstance( data, list ):  # pragma: no cover - defensive: _extract_last_json_array always yields a JSON array → json.loads gives a list
                data = [ data ]

            fixes = []
            for item in data:
                try:
                    fixes.append( ProposedFix( **item ) )
                except ( ValueError, TypeError ) as e:
                    logger.warning( f"Skipping invalid fix proposal: {e}" )

            return fixes if fixes else self._fallback_proposal( "All proposals failed validation" )

        except ( json.JSONDecodeError, ValueError ) as e:
            logger.warning( f"JSON parse failed for proposals: {e}" )
            return self._fallback_proposal( raw_response[ :500 ] )

    @staticmethod
    def _extract_last_json_array( text: str ) -> Optional[ str ]:
        """
        Extract the last JSON array from text by finding matching brackets.

        Args:
            text: Text that may contain a JSON array

        Returns:
            str or None: Extracted JSON array string, or None if not found
        """
        close_idx = text.rfind( "]" )
        if close_idx == -1:
            return None

        depth = 0
        for i in range( close_idx, -1, -1 ):
            if text[ i ] == "]":
                depth += 1
            elif text[ i ] == "[":
                depth -= 1
                if depth == 0:
                    return text[ i : close_idx + 1 ]

        return None

    @staticmethod
    def _auto_select_fix( fixes: list ) -> Optional:
        """
        Auto-select a fix if there is exactly one with high confidence.

        Args:
            fixes: List of ProposedFix proposals

        Returns:
            ProposedFix or None: Auto-selected fix, or None if user must choose
        """
        if len( fixes ) == 1 and fixes[ 0 ].confidence >= 0.8:
            return fixes[ 0 ]
        return None

    @staticmethod
    def _fallback_proposal( reason: str ) -> list:
        """
        Create a single fallback manual-fix proposal.

        Args:
            reason: Description of why fallback was needed

        Returns:
            list[ProposedFix]: Single-element list with manual fix
        """
        return [ ProposedFix(
            title            = "Manual Investigation Required",
            description      = reason,
            fix_type         = "manual",
            confidence       = 0.1,
            risk_level       = "low",
            estimated_effort = "medium",
            changes          = [],
        ) ]

    @staticmethod
    def _build_proposal_abstract( fixes: list, selected_fix=None ) -> str:
        """
        Build a markdown abstract summarizing fix proposals.

        Args:
            fixes: List of ProposedFix proposals
            selected_fix: The selected fix (if any)

        Returns:
            str: Markdown-formatted abstract
        """
        lines = [ f"**{len( fixes )} Fix(es) Proposed**:\n" ]

        for i, fix in enumerate( fixes, 1 ):
            selected = " **[SELECTED]**" if selected_fix and fix.title == selected_fix.title else ""
            lines.append(
                f"{i}. **{fix.title}** ({fix.fix_type}, {fix.confidence:.0%} confidence, "
                f"{fix.risk_level} risk){selected}"
            )

        return "\n".join( lines )

    # =========================================================================
    # Voice Gate — Diagnosis
    # =========================================================================

    async def _voice_gate_diagnosis(
        self,
        diagnosis: DiagnosisResult,
        voice_io,
        cosa_interface
    ) -> DiagnosisResult:
        """
        Voice-gated confirmation of the diagnosis result.

        Natural break point where user can approve, reject with feedback,
        or let it auto-approve if require_user_confirm is False.

        Args:
            diagnosis: Current best DiagnosisResult
            voice_io: Voice I/O module
            cosa_interface: COSA interface for confirmation/feedback

        Returns:
            DiagnosisResult: Approved (or refined) diagnosis
        """
        if not self.config.require_user_confirm:
            if self.debug: print( "[BFEOrchestrator] Auto-approving diagnosis (require_user_confirm=False)" )
            return diagnosis

        # State: DIAGNOSING → WAITING_CONFIRMATION
        await self._emit_state( BFEPhase.DIAGNOSING, BFEPhase.WAITING_CONFIRMATION )

        abstract = self._build_diagnosis_abstract( diagnosis )

        try:
            approved = await cosa_interface.ask_confirmation(
                "Does this diagnosis look right?",
                default  = "yes",
                timeout  = self.config.feedback_timeout_seconds,
                abstract = abstract,
                job_id   = self.job_id,
            )
        except Exception as e:
            # A gate that cannot reach a human does not answer for them.
            # Timeout (asked, no answer) and unreachable (the asking broke) both
            # mean no human approved, and both checkpoint-and-stall in the caller.
            # They stay DISTINCT types so the record can say which occurred.
            # Was: fall through to `return diagnosis` — an auto-approval whose
            # return value was indistinguishable from a real one (row 421b9498).
            from cosa.agents.bug_fix_expediter.state import VoiceGateTimeoutError, VoiceGateUnreachableError
            if isinstance( e, VoiceGateTimeoutError ):
                raise
            logger.warning( f"Voice gate confirmation failed: {e} — refusing to approve for an absent human" )
            await self._emit_state( BFEPhase.WAITING_CONFIRMATION, BFEPhase.DIAGNOSING )
            raise VoiceGateUnreachableError( BFEPhase.DIAGNOSING.value, e )

        if approved:
            if self.debug: print( "[BFEOrchestrator] Diagnosis approved by user" )
            await self._emit_state( BFEPhase.WAITING_CONFIRMATION, BFEPhase.DIAGNOSING )
            return diagnosis

        # User rejected — try to get feedback for refinement
        if self.debug: print( "[BFEOrchestrator] Diagnosis rejected — requesting feedback" )

        try:
            feedback = await cosa_interface.get_feedback(
                "What should be corrected in this diagnosis?",
                timeout = self.config.feedback_timeout_seconds,
                job_id  = self.job_id,
            )
        except Exception as e:
            # The user has ALREADY REJECTED this diagnosis. Returning it here
            # converted an explicit NO into a YES because a *second* call failed
            # — the only site in this sweep that overrides a human who spoke,
            # rather than filling in for one who was absent (row 421b9498).
            #
            # get_feedback raises VoiceGateTimeoutError in its own right
            # (dispatcher: exit_code==2, 503-offline, ValidationError/ConnectionError). Let it
            # through unwrapped: a timeout relabelled "unreachable" is a handler
            # that cannot tell apart the two states this whole change exists to
            # keep distinct. (Krishna 🦚, pre-commit review.)
            from cosa.agents.bug_fix_expediter.state import VoiceGateTimeoutError, VoiceGateUnreachableError
            if isinstance( e, VoiceGateTimeoutError ):
                await self._emit_state( BFEPhase.WAITING_CONFIRMATION, BFEPhase.DIAGNOSING )
                raise
            logger.warning( f"Feedback collection failed after a REJECTION: {e} — refusing to proceed on the rejected diagnosis" )
            await self._emit_state( BFEPhase.WAITING_CONFIRMATION, BFEPhase.DIAGNOSING )
            raise VoiceGateUnreachableError( BFEPhase.DIAGNOSING.value, e )

        if not feedback:
            if self.debug: print( "[BFEOrchestrator] No feedback provided — returning diagnosis as-is" )
            await self._emit_state( BFEPhase.WAITING_CONFIRMATION, BFEPhase.DIAGNOSING )
            return diagnosis

        # Re-run one refinement iteration with user feedback
        await self._emit_state( BFEPhase.WAITING_CONFIRMATION, BFEPhase.DIAGNOSING )

        await self._notify(
            voice_io, "Refining diagnosis with your feedback...",
            priority="medium"
        )

        prompt = build_diagnosis_prompt(
            ctx             = self.dead_job_context,
            extra_context   = self.extra_context,
            iteration       = self.config.max_diagnosis_iterations + 1,
            prior_diagnosis = diagnosis,
            user_messages   = [ feedback ],
        )

        raw_response = await self._delegate_to_lead( voice_io, prompt )
        if raw_response:
            refined = self._parse_diagnosis_result( raw_response )
            if refined.confidence > diagnosis.confidence:
                return refined

        return diagnosis

    # =========================================================================
    # Voice Gate — Proposal
    # =========================================================================

    async def _voice_gate_proposal( self, fixes, voice_io, cosa_interface ):
        """
        Voice-gated selection of a fix proposal.

        Natural break point where user selects from proposals and approves.
        Auto-selects if single high-confidence fix. Supports feedback-driven
        retry on rejection.

        Future: Phase 5 will add trust proxy L1-L5 gating here.

        Args:
            fixes: List of ProposedFix proposals
            voice_io: Voice I/O module
            cosa_interface: COSA interface for choices/feedback

        Returns:
            ProposedFix or None: Selected and approved fix
        """
        if not fixes:
            return None

        if not self.config.require_user_confirm:
            # Auto-select best fix (highest confidence)
            best = sorted( fixes, key=lambda f: f.confidence, reverse=True )[ 0 ]
            if self.debug: print( f"[BFEOrchestrator] Auto-selected fix: {best.title} (require_user_confirm=False)" )
            return best

        # State: PROPOSING → WAITING_CONFIRMATION
        await self._emit_state( BFEPhase.PROPOSING, BFEPhase.WAITING_CONFIRMATION )

        # Try auto-select for single high-confidence fix
        auto = self._auto_select_fix( fixes )
        if auto:
            abstract = (
                f"**Auto-selected**: {auto.title}\n"
                f"**Type**: {auto.fix_type}\n"
                f"**Confidence**: {auto.confidence:.0%}\n"
                f"**Risk**: {auto.risk_level}\n\n"
                f"{auto.description[ :300 ]}"
            )
            try:
                approved = await cosa_interface.ask_confirmation(
                    f"Proposed fix: '{auto.title}'. Apply this fix?",
                    default  = "yes",
                    timeout  = self.config.feedback_timeout_seconds,
                    abstract = abstract,
                    job_id   = self.job_id,
                )
            except Exception as e:
                # This gate asks "Apply this fix?" — a broken gate must never
                # answer yes on a human's behalf and hand back a fix for
                # application. Both no-answer cases checkpoint-and-stall in the
                # caller; they stay distinct types so the record says which.
                # Was: fall through to `return auto` (row 421b9498).
                from cosa.agents.bug_fix_expediter.state import VoiceGateTimeoutError, VoiceGateUnreachableError
                if isinstance( e, VoiceGateTimeoutError ):
                    raise
                logger.warning( f"Voice gate failed: {e} — refusing to apply a fix nobody approved" )
                await self._emit_state( BFEPhase.WAITING_CONFIRMATION, BFEPhase.PROPOSING )
                raise VoiceGateUnreachableError( BFEPhase.PROPOSING.value, e )

            if approved:
                await self._emit_state( BFEPhase.WAITING_CONFIRMATION, BFEPhase.PROPOSING )
                return auto
        else:
            # Multiple fixes — present as choices
            options = []
            for i, fix in enumerate( fixes ):
                options.append( {
                    "label"       : fix.title,
                    "description" : f"{fix.fix_type} | {fix.confidence:.0%} confidence | {fix.risk_level} risk | {fix.estimated_effort} effort",
                } )
            options.append( { "label": "Reject all", "description": "None of these fixes are acceptable" } )

            try:
                result = await cosa_interface.present_choices(
                    questions=[ {
                        "question"    : "Which fix should be applied?",
                        "header"      : "Fix Selection",
                        "multiSelect" : False,
                        "options"     : options,
                    } ],
                    timeout  = self.config.feedback_timeout_seconds,
                    title    = "Bug Fix Proposal",
                    abstract = self._build_proposal_abstract( fixes ),
                    job_id   = self.job_id,
                )

                # An ABSENT header is not "the user picked nothing" (row 2b604cdb).
                selection = read_gate_answer(
                    result, "Fix Selection", "BFE proposal gate", unattended_default=""
                )

                # Find selected fix
                for fix in fixes:
                    if fix.title == selection:
                        await self._emit_state( BFEPhase.WAITING_CONFIRMATION, BFEPhase.PROPOSING )
                        return fix

            except Exception as e:
                # Propagate VoiceGateTimeoutError for checkpoint-resume.
                from cosa.agents.bug_fix_expediter.state import VoiceGateTimeoutError
                if isinstance( e, VoiceGateTimeoutError ):
                    raise
                logger.warning( f"Voice gate choices failed: {e}" )

        # User rejected (or timed out) — try feedback for retry
        if self.debug: print( "[BFEOrchestrator] Proposal rejected — requesting feedback" )

        try:
            feedback = await cosa_interface.get_feedback(
                "What's wrong with these proposals? Any guidance for a better fix?",
                timeout = self.config.feedback_timeout_seconds,
                job_id  = self.job_id,
            )
        except Exception as e:
            logger.warning( f"Feedback collection failed: {e}" )
            await self._emit_state( BFEPhase.WAITING_CONFIRMATION, BFEPhase.PROPOSING )
            return None

        if not feedback:
            await self._emit_state( BFEPhase.WAITING_CONFIRMATION, BFEPhase.PROPOSING )
            return None

        # Re-run proposal with user feedback
        await self._emit_state( BFEPhase.WAITING_CONFIRMATION, BFEPhase.PROPOSING )
        await self._notify( voice_io, "Revising proposals with your feedback...", priority="medium" )

        prompt = build_proposal_prompt(
            diagnosis        = self._last_diagnosis,
            dead_job_context = self.dead_job_context,
            extra_context    = self.extra_context,
            user_feedback    = feedback,
        ) if hasattr( self, "_last_diagnosis" ) else None

        if prompt:
            raw_response = await self._delegate_to_lead(
                voice_io, prompt, options=self._build_proposal_options()
            )
            if raw_response:
                revised_fixes = self._parse_proposal_result( raw_response )
                if revised_fixes and revised_fixes[ 0 ].confidence > 0.1:
                    # Auto-select best revised fix
                    best = sorted( revised_fixes, key=lambda f: f.confidence, reverse=True )[ 0 ]
                    return best

        return None

    # =========================================================================
    # Phase 4: Fix (Coder + Tester)
    # =========================================================================

    async def run_fix( self, diagnosis, selected_fix, plan_path: str ) -> FixResult:
        """
        Run the fix phase: Coder applies fix, Tester validates.

        Session 1cfcdf73 (2026-04-10): Thin shim delegating to shared FixExecutor.
        The BFE-specific concerns (state transitions, plan doc update, completion
        notification, files_changed exposure) stay in this shim; the SDK loop,
        retry logic, and escalation live in `shared/fix_executor.py`.

        Requires:
            - diagnosis is a valid DiagnosisResult
            - selected_fix is a valid ProposedFix
            - SDK_AVAILABLE is True (checked by FixExecutor)

        Ensures:
            - Returns FixResult with applied/success status
            - Plan document updated with implementation log
            - Safety limits enforced via SafetyGuard (inside FixExecutor)

        Args:
            diagnosis: DiagnosisResult from diagnosis phase
            selected_fix: User-approved ProposedFix from proposal phase
            plan_path: Path to plan document for log updates

        Returns:
            FixResult: Outcome of the fix attempt
        """
        from cosa.agents.bug_fix_expediter import voice_io, cosa_interface

        if not SDK_AVAILABLE:
            logger.error( "Claude Agent SDK not available — cannot run fix" )
            return FixResult( applied=False, success=False, details="SDK not installed" )

        # State: PROPOSING → FIXING (BFE-specific phase enum)
        await self._emit_state( BFEPhase.PROPOSING, BFEPhase.FIXING )

        await self._notify(
            voice_io, f"Applying fix: {selected_fix.title}",
            priority="medium",
            abstract=f"**Fix**: {selected_fix.title}\n**Type**: {selected_fix.fix_type}\n**Risk**: {selected_fix.risk_level}"
        )

        # Delegate the retry loop + escalation to shared FixExecutor.
        # Pass BFE's _delegate_to_coder and _verify_fix as callbacks so
        # unit test patches on those orchestrator methods continue to work.
        executor = FixExecutor(
            config                = self.config,
            fix_context           = self.dead_job_context,
            job_id                = self.job_id,
            prompt_builder_key    = "bfe",
            voice_io_module       = voice_io,
            cosa_interface_module = cosa_interface,
            notify_fn             = self._notify,
            is_cancelled_fn       = self._is_cancelled,
            delegate_to_coder_fn  = self._delegate_to_coder,
            verify_fix_fn         = self._verify_fix,
            debug                 = self.debug,
            verbose               = self.verbose,
            worktree_cwd          = self._worktree_cwd,
        )

        fix_result, files_changed = await executor.execute_fix(
            diagnosis    = diagnosis,
            selected_fix = selected_fix,
        )

        coder_output = executor.last_coder_output

        # --- Update plan document ---
        try:
            writer = PlanWriter( user_email=self.dead_job_context.user_email, debug=self.debug )
            writer.update_implementation_log( plan_path, fix_result, files_changed, coder_output )
        except Exception as e:
            logger.warning( f"Plan update failed: {e}" )

        # --- Completion notification ---
        status_msg = "Fix applied successfully!" if fix_result.success else "Fix phase complete (not successful)."
        await self._notify(
            voice_io, status_msg,
            priority="medium" if fix_result.success else "high",
            abstract=f"**Applied**: {fix_result.applied}\n**Success**: {fix_result.success}\n"
                     f"**Details**: {fix_result.details}\n**Files**: {len( files_changed )}"
        )

        # Phase 5: expose files_changed for run_git_strategy
        self.last_files_changed = files_changed

        return fix_result

    async def run_git_strategy(
        self,
        fix_result: FixResult,
        files_changed: list,
        plan_path: str,
    ) -> FixResult:
        """
        Phase 5: Run git operations post-fix (commit / branch / PR).

        Trust-to-git mapping:
            - L1-L2 (shadow/suggest): commit_only on current branch
            - L3+ (active): branch_and_pr via gh
            - Proxy unavailable: commit_only (safe default)

        Requires:
            - fix_result is a FixResult
            - files_changed is a list (may be empty)
            - plan_path is a string path

        Ensures:
            - fix_result.git_strategy / commit_hash / branch_name / pr_url populated on success
            - Plan document Git References section updated
            - State transitions: FIXING → COMMITTING → COMPLETED
            - Skipped (no-op) if fix not successful or no files changed

        Args:
            fix_result: FixResult from run_fix()
            files_changed: Files modified by coder
            plan_path: Path to plan document for git references update

        Returns:
            FixResult: Same instance with git fields populated
        """
        from cosa.agents.bug_fix_expediter import voice_io
        from cosa.agents.bug_fix_expediter.git_ops import GitOps

        # Guard: skip if fix didn't succeed or nothing to commit
        if not fix_result.success or not files_changed:
            if self.debug: print( f"[BFEOrchestrator] Skipping git strategy (success={fix_result.success}, files={len( files_changed )})" )
            return fix_result

        await self._emit_state( BFEPhase.FIXING, BFEPhase.COMMITTING )
        await self._notify( voice_io, "Committing changes to git...", priority="medium" )

        # Delegate to shared GitStrategist (Session 1cfcdf73 extraction).
        # Bug 9 (2026-04-16): route git ops through worktree when isolation
        # is active — see worktree_scope() context manager.
        git_ops       = GitOps( cwd=( self._worktree_cwd or cu.get_project_root() ), debug=self.debug )
        strategist    = GitStrategist( debug=self.debug, verbose=self.verbose )
        trust_level   = GitStrategist.resolve_trust_level( self.proxy )

        commit_message = f"[BFE] Fix: {fix_result.details[ :60 ]}" if fix_result.details else "[BFE] Fix"
        pr_title       = f"[BFE] {fix_result.details[ :60 ]}" if fix_result.details else "[BFE] Automated fix"
        pr_body        = (
            f"Automated fix from Bug Fix Expediter.\n\n"
            f"**Details**: {( fix_result.details or 'N/A' )[ :500 ]}\n\n"
            f"**Files changed**:\n" + "\n".join( f"- `{f}`" for f in files_changed[ :20 ] )
        )

        async def _notify_fn( msg, priority="low" ):
            await self._notify( voice_io, msg, priority=priority )

        git_result = await strategist.commit_and_pr_single(
            git_ops=git_ops,
            files_changed=files_changed,
            commit_message=commit_message,
            pr_title=pr_title,
            pr_body=pr_body,
            trust_level=trust_level,
            notify_fn=_notify_fn,
        )

        # Apply git result fields to FixResult
        if git_result.get( "git_strategy" ) is not None:
            fix_result.git_strategy = git_result[ "git_strategy" ]
        if git_result.get( "commit_hash" ) is not None:
            fix_result.commit_hash = git_result[ "commit_hash" ]
        if git_result.get( "branch_name" ) is not None:
            fix_result.branch_name = git_result[ "branch_name" ]
        if git_result.get( "pr_url" ) is not None:
            fix_result.pr_url = git_result[ "pr_url" ]

        return self._finalize_git_strategy( fix_result, plan_path, voice_io )

    def _finalize_git_strategy( self, fix_result: FixResult, plan_path: str, voice_io ) -> FixResult:
        """Update plan doc with git references; used by run_git_strategy as exit hook."""
        try:
            writer = PlanWriter( user_email=self.dead_job_context.user_email, debug=self.debug )
            writer.update_git_references( plan_path, fix_result )
        except Exception as e:
            logger.warning( f"Plan git references update failed: {e}" )
        return fix_result

    def _resolve_trust_level( self ) -> int:
        """
        Return trust level 1-5 from the proxy, falling back to L1 on failure.

        Session 1cfcdf73: Thin shim delegating to shared GitStrategist. Kept on
        BFEOrchestrator for backwards compatibility with existing unit tests
        that call `orch._resolve_trust_level()`.

        Ensures:
            - Always returns int between 1 and 5
            - L1 on any error (conservative default)
        """
        return GitStrategist.resolve_trust_level( self.proxy )

    @staticmethod
    def _generate_slug( text: str ) -> str:
        """
        Generate a fix/YYYY-MM-DD-{slug} branch name from text.

        Session 1cfcdf73: Thin shim delegating to shared GitStrategist. Kept on
        BFEOrchestrator for backwards compatibility with existing unit tests
        that call `BFEOrchestrator._generate_slug(...)`.

        Requires:
            - text is a string (may be empty)

        Ensures:
            - Returns string of form "fix/YYYY-MM-DD-{word1-word2-word3}"
            - At least "fix/YYYY-MM-DD-fix" if text yields no words
        """
        return GitStrategist.generate_slug( text )

    async def _delegate_to_coder( self, voice_io, prompt, guard, cosa_interface ) -> tuple:
        """
        Delegate fix application to the Coder agent via SDK.

        Args:
            voice_io: Voice I/O module
            prompt: Fix or redelegation prompt
            guard: SafetyGuard instance
            cosa_interface: COSA interface for dangerous command approval

        Returns:
            tuple: ( coder_output, files_changed )
        """
        options = self._build_coder_options( guard, cosa_interface )

        try:
            collected_text = []
            files_changed  = []

            # Bug 15 WORKAROUND: claude-agent-sdk ≥ 0.1.36 rejects str prompt when
            # can_use_tool is set on options. Upstream (unresolved as of 2026-04-17):
            # https://github.com/anthropics/claude-code/issues/18735 — remove the
            # wrap_prompt_for_streaming() call once upstream lands the fix.
            async for message in sdk_query( prompt=wrap_prompt_for_streaming( prompt ), options=options ):
                guard.check_timeout()

                if self._is_cancelled():
                    break

                if isinstance( message, AssistantMessage ):
                    for block in message.content:
                        if isinstance( block, TextBlock ):
                            collected_text.append( block.text )
                        elif isinstance( block, ToolUseBlock ):
                            # Track file changes
                            if block.name in ( "Edit", "Write" ):
                                file_path = block.input.get( "file_path", "" )
                                if file_path and file_path not in files_changed:
                                    files_changed.append( file_path )
                                await post_tool_hook( block.name, block.input, guard )
                            await self._notify(
                                voice_io,
                                f"Coder: {self._summarize_tool_use( block )}",
                                priority="low",
                            )
                elif isinstance( message, TextBlock ):
                    collected_text.append( message.text )
                elif isinstance( message, ResultMessage ):
                    msg_text = getattr( message, "text", str( message ) )[ :200 ]
                    await self._notify( voice_io, msg_text, priority="low" )
                elif isinstance( message, RateLimitEvent ):
                    logger.warning( f"Rate limited: retry_after={getattr( message, 'retry_after', '?' )}s" )

            guard.check_iteration()
            coder_output = "".join( collected_text ).strip()

            if self.debug: print( f"[BFEOrchestrator] Coder output: {len( coder_output )} chars, {len( files_changed )} files changed" )

            return ( coder_output, files_changed )

        except SafetyLimitError:
            raise
        except Exception as e:
            logger.error( f"Coder delegation failed: {e}" )
            return ( "", [] )

    async def _verify_fix( self, voice_io, selected_fix, coder_output, files_changed, guard, cosa_interface ) -> tuple:
        """
        Verify the fix via Tester agent + independent pytest.

        Args:
            voice_io: Voice I/O module
            selected_fix: The ProposedFix that was applied
            coder_output: Coder's output summary
            files_changed: Files modified by coder
            guard: SafetyGuard instance
            cosa_interface: COSA interface for tool approval

        Returns:
            tuple: ( passed, tester_output )
        """
        prompt  = build_verification_prompt( selected_fix, coder_output, files_changed )
        options = self._build_tester_options( guard, cosa_interface )

        try:
            collected_text = []
            test_files     = []

            # Bug 15 WORKAROUND: claude-agent-sdk ≥ 0.1.36 rejects str prompt when
            # can_use_tool is set on options. Upstream (unresolved as of 2026-04-17):
            # https://github.com/anthropics/claude-code/issues/18735 — remove the
            # wrap_prompt_for_streaming() call once upstream lands the fix.
            async for message in sdk_query( prompt=wrap_prompt_for_streaming( prompt ), options=options ):
                guard.check_timeout()

                if isinstance( message, AssistantMessage ):
                    for block in message.content:
                        if isinstance( block, TextBlock ):
                            collected_text.append( block.text )
                        elif isinstance( block, ToolUseBlock ):
                            if block.name in ( "Edit", "Write" ):
                                file_path = block.input.get( "file_path", "" )
                                if file_path and file_path not in test_files:
                                    test_files.append( file_path )
                                await post_tool_hook( block.name, block.input, guard )
                            await self._notify(
                                voice_io, f"Tester: {block.name}", priority="low",
                            )
                elif isinstance( message, TextBlock ):
                    collected_text.append( message.text )
                elif isinstance( message, RateLimitEvent ):
                    logger.warning( f"Rate limited: retry_after={getattr( message, 'retry_after', '?' )}s" )

            tester_output = "".join( collected_text ).strip()
            output_lower  = tester_output.lower()

            # Tester self-report
            passed = (
                "pass" in output_lower and "fail" not in output_lower
            ) or "all tests pass" in output_lower

            # Independent pytest validation — OVERRIDES tester self-report
            for tf in test_files:
                if tf.endswith( ".py" ) and "test" in tf.lower():
                    run_result = await run_pytest( tf, timeout_secs=60 )
                    if not run_result.passed:
                        passed = False
                    if self.debug:
                        print( f"[BFEOrchestrator] pytest {tf}: {'PASS' if run_result.passed else 'FAIL'} "
                               f"({run_result.passed_count}/{run_result.total_tests})" )
                    break  # Only validate first test file

            if self.debug: print( f"[BFEOrchestrator] Verification: {'PASS' if passed else 'FAIL'}" )

            return ( passed, tester_output )

        except SafetyLimitError:
            raise
        except Exception as e:
            logger.error( f"Verification failed: {e}" )
            return ( False, f"Verification error: {e}" )

    # -------------------------------------------------------------------------
    # Worktree isolation (Bug 9, 2026-04-16)
    # -------------------------------------------------------------------------

    @asynccontextmanager
    async def worktree_scope( self ):
        """
        Enter worktree isolation for Phase 3 + Phase 5 (run_fix + run_git_strategy).

        Caller pattern (from job.py):
            async with orchestrator.worktree_scope():
                fix_result = await orchestrator.run_fix( ... )
                if fix_result.success and orchestrator.last_files_changed:
                    fix_result = await orchestrator.run_git_strategy( ... )

        When `cosa worktree enabled` is true, a dedicated worktree is created
        under `<sandbox_root>/<job_id>`. `_build_coder_options`,
        `_build_tester_options`, and `run_git_strategy` automatically route
        through `self._worktree_cwd`.

        When disabled, the context is a no-op and emits a warning if the
        current working tree has uncommitted changes (safety guard).

        Ensures:
            - self._worktree_cwd is None on entry and exit (no leaked state)
            - Cleanup runs even if the caller raises
        """
        from cosa.agents.shared.worktree_context import WorktreeContext
        async with WorktreeContext( job_id=self.job_id, debug=self.debug ) as wt:
            if wt.enabled:
                self._worktree_cwd = wt.path
                if self.debug: print( f"[BFEOrchestrator] Worktree isolation active: {wt.path}" )
            else:
                self._worktree_cwd = None
                await self._warn_on_uncommitted_changes_if_any()
            try:
                yield wt
            finally:
                self._worktree_cwd = None

    async def _warn_on_uncommitted_changes_if_any( self ) -> None:
        """
        Safety guard (Bug 9): when worktree isolation is disabled AND the
        current working tree has uncommitted changes, log a visible warning.

        Does NOT block execution — the user opted into this mode by leaving
        `cosa worktree enabled=false`. Purely a heads-up.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "status", "--porcelain",
                stdout = asyncio.subprocess.PIPE,
                stderr = asyncio.subprocess.PIPE,
                cwd    = cu.get_project_root(),
            )
            stdout_bytes, _ = await asyncio.wait_for( proc.communicate(), timeout=5 )
            if stdout_bytes.strip():
                logger.warning(
                    "[BFEOrchestrator] ⚠️  Worktree isolation is DISABLED and "
                    "the current working tree has uncommitted changes. TFE/BFE "
                    "fixes will mutate this tree and may contaminate your PR. "
                    "Consider `cosa worktree enabled=true` or committing/stashing."
                )
        except Exception as e:
            if self.debug: print( f"[BFEOrchestrator] uncommitted-changes check failed: {e}" )

    def _build_coder_options( self, guard, cosa_interface ):
        """
        Build ClaudeAgentOptions for the Coder agent.

        Args:
            guard: SafetyGuard for tool gating
            cosa_interface: COSA interface for dangerous command approval

        Returns:
            ClaudeAgentOptions configured for code editing
        """
        return ClaudeAgentOptions(
            model           = self.config.worker_model,
            system_prompt   = CODER_SYSTEM_PROMPT,
            tools           = [ "Read", "Edit", "Bash" ],
            cwd             = self._worktree_cwd or cu.get_project_root(),
            permission_mode = "acceptEdits",
            can_use_tool    = build_can_use_tool( cosa_interface, guard, "code-fixer" ),
            max_turns       = self.config.max_fix_attempts * 10,
            max_budget_usd  = self.config.budget_usd,
            effort          = self.config.thinking_effort,
        )

    @staticmethod
    def render_worktree_artifacts_abstract( job_id: str, fix_result, fix_applied: bool ) -> list:
        """
        Render the 'Worktree Artifacts' section of the BFE completion abstract.

        Pure static helper so unit tests can drive it directly. Returns an
        empty list when no fix was applied AND no commit was made (nothing
        to report).

        BFE is single-fix (vs. TFE's multi-cluster), so this reads a single
        FixResult rather than parallel lists.
        """
        if not ( fix_applied or getattr( fix_result, "commit_hash", None ) ):
            return []
        lines = [ "", "**Worktree Artifacts**" ]
        worktree_path = f"{cu.get_project_root()}/.claude/worktrees/{job_id}"
        lines.append( f"**Path**: `{worktree_path}`" )
        strategy = getattr( fix_result, "git_strategy", None )
        if strategy:
            lines.append( f"**Strategy**: {strategy}" )
        branch = getattr( fix_result, "branch_name", None )
        if branch:
            lines.append( f"**Branch**: `{branch}`" )
        commit_hash = getattr( fix_result, "commit_hash", None )
        if commit_hash:
            lines.append( f"**Commit**: `{commit_hash[ :8 ]}`" )
        lines.append( "" )
        lines.append( "**Inspect**:" )
        lines.append( f"- `git -C {worktree_path} log --oneline`" )
        lines.append( f"- `git -C {worktree_path} diff --stat origin/main`" )
        return lines

    @staticmethod
    def _summarize_tool_use( block ) -> str:
        """
        Compact single-line summary of a ToolUseBlock for progress notifications.

        Replaces the old bare `Coder: {block.name}` breadcrumbs with a
        tool-specific digest that surfaces the key argument. Parity with TFE's
        `TFEOrchestrator._summarize_tool_use`. Truncated to 100 chars.

        Filed 2026-04-18 (Session be57a252).
        """
        name = block.name
        inp  = block.input or {}
        if name == "Bash":
            cmd = inp.get( "command", "" ) or ""
            first_line = cmd.splitlines()[ 0 ] if cmd else ""
            return f"Bash: {first_line[ :100 ]}" if first_line else "Bash"
        if name in ( "Read", "Edit", "Write" ):
            fp = inp.get( "file_path", "" ) or ""
            return f"{name}: {fp[ -100: ]}" if fp else name
        if name in ( "Grep", "Glob" ):
            pat = inp.get( "pattern", "" ) or ""
            return f"{name}: {pat[ :100 ]}" if pat else name
        return name

    def _build_tester_options( self, guard, cosa_interface ):
        """
        Build ClaudeAgentOptions for the Tester agent.

        Args:
            guard: SafetyGuard for tool gating
            cosa_interface: COSA interface for dangerous command approval

        Returns:
            ClaudeAgentOptions configured for test writing and execution
        """
        return ClaudeAgentOptions(
            model           = self.config.worker_model,
            system_prompt   = TESTER_SYSTEM_PROMPT,
            tools           = [ "Read", "Edit", "Bash" ],
            cwd             = self._worktree_cwd or cu.get_project_root(),
            permission_mode = "acceptEdits",
            can_use_tool    = build_can_use_tool( cosa_interface, guard, "tester" ),
            max_turns       = 10,
            max_budget_usd  = self.config.budget_usd,
            effort          = self.config.thinking_effort,
        )

    # =========================================================================
    # Notifications + State
    # =========================================================================

    async def _notify(
        self,
        voice_io,
        message: str,
        priority: str = "medium",
        abstract: Optional[ str ] = None
    ) -> None:
        """
        Send progress notification with automatic job_id and queue routing.

        Args:
            voice_io: Voice I/O module
            message: Notification message
            priority: Notification priority
            abstract: Optional supplementary context
        """
        if not self.config.narrate_progress and priority not in ( "high", "urgent" ):
            return

        try:
            await voice_io.notify(
                message,
                priority          = priority,
                abstract          = abstract,
                job_id            = self.job_id,
                queue_name        = "run",
                progress_group_id = self._diagnosis_group_id,
            )
        except Exception as e:
            logger.warning( f"Notification failed: {e}" )

    async def _emit_state(
        self,
        from_phase: BFEPhase,
        to_phase: BFEPhase,
        metadata: Optional[ dict ] = None
    ) -> None:
        """
        Emit a phase transition event.

        Args:
            from_phase: Phase transitioning from
            to_phase: Phase transitioning to
            metadata: Optional transition metadata
        """
        self.current_phase = to_phase
        if self.debug: print( f"[BFEOrchestrator] State: {from_phase.value} → {to_phase.value}" )

        if self.on_state_change:
            try:
                await self.on_state_change( from_phase, to_phase, metadata )
            except Exception as e:
                logger.warning( f"on_state_change callback failed: {e}" )

    # =========================================================================
    # Cancellation + User Messages
    # =========================================================================

    def _is_cancelled( self ) -> bool:
        """
        Check if cancellation has been requested.

        Returns:
            bool: True if stop requested or cancel_check() returns True
        """
        if self._stop_requested:
            return True
        if self.cancel_check and self.cancel_check():
            return True
        return False

    def _drain_user_messages( self ) -> list:
        """
        Drain all queued user messages and clear the urgent interrupt.

        Returns:
            list[str]: All queued messages (empty if none)
        """
        messages = []
        while not self._user_messages.empty():
            try:
                messages.append( self._user_messages.get_nowait() )
            except queue.Empty:
                break

        if messages:
            self._urgent_interrupt.clear()

        return messages

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _build_diagnosis_abstract( diagnosis: DiagnosisResult ) -> str:
        """
        Build a markdown abstract summarizing a diagnosis for notifications.

        Args:
            diagnosis: DiagnosisResult to summarize

        Returns:
            str: Markdown-formatted abstract
        """
        evidence_lines = "\n".join( f"  - {e}" for e in diagnosis.evidence ) if diagnosis.evidence else "  - None"
        components     = ", ".join( diagnosis.affected_components ) if diagnosis.affected_components else "None identified"

        return (
            f"**Root Cause**: {diagnosis.root_cause}\n"
            f"**Category**: {diagnosis.error_category}\n"
            f"**Confidence**: {diagnosis.confidence:.0%}\n"
            f"**Transient**: {'Yes' if diagnosis.is_transient else 'No'}\n"
            f"**Evidence**:\n{evidence_lines}\n"
            f"**Affected**: {components}"
        )


def quick_smoke_test():
    """Quick smoke test for BFEOrchestrator."""
    import cosa.utils.util as cu

    cu.print_banner( "BFE Orchestrator Smoke Test", prepend_nl=True )

    try:
        # 1: Import
        from cosa.agents.bug_fix_expediter.orchestrator import BFEOrchestrator
        print( "✓ Module imported successfully" )

        # 2: SDK availability check
        print( f"✓ SDK_AVAILABLE = {SDK_AVAILABLE}" )

        # 3: Instantiation
        from cosa.agents.bug_fix_expediter.state import DeadJobContext
        from cosa.agents.bug_fix_expediter.config import BugFixExpediterConfig

        ctx = DeadJobContext(
            id_hash="dr-test::u1", job_type="deep_research",
            user_id="u1", user_email="t@t.com", session_id="s1",
            status="failed", question_text="test", error="boom"
        )
        config = BugFixExpediterConfig()

        orch = BFEOrchestrator(
            dead_job_context = ctx,
            extra_context    = "test context",
            config           = config,
            session_id       = "s1",
            job_id           = "bfe-test123",
            debug            = True,
        )
        assert orch.current_phase == BFEPhase.PACKAGING
        assert orch.job_id == "bfe-test123"
        print( "✓ BFEOrchestrator instantiated" )

        # 4: Parse valid JSON
        valid_json = '{"root_cause": "Missing key", "error_category": "config", "confidence": 0.9, "evidence": ["key not found"], "affected_components": ["config.py"], "is_transient": false}'
        result = orch._parse_diagnosis_result( valid_json )
        assert result.root_cause == "Missing key"
        assert result.confidence == 0.9
        print( "✓ JSON parsing works (valid JSON)" )

        # 5: Parse markdown-wrapped JSON
        wrapped = f"Here is my analysis:\n\n```json\n{valid_json}\n```\n\nThat's my diagnosis."
        result = orch._parse_diagnosis_result( wrapped )
        assert result.root_cause == "Missing key"
        print( "✓ JSON parsing works (markdown fences)" )

        # 6: Parse failure fallback
        result = orch._parse_diagnosis_result( "No JSON here at all" )
        assert result.confidence == 0.1
        assert result.error_category == "unknown"
        print( "✓ Fallback diagnosis on parse failure" )

        # 7: Cancellation
        assert orch._is_cancelled() == False
        orch._stop_requested = True
        assert orch._is_cancelled() == True
        orch._stop_requested = False
        print( "✓ Cancellation check works" )

        # 8: User message queue
        orch.queue_user_message( "test message" )
        orch.queue_user_message( "urgent!", urgent=True )
        assert orch._urgent_interrupt.is_set()
        messages = orch._drain_user_messages()
        assert len( messages ) == 2
        assert not orch._urgent_interrupt.is_set()
        print( "✓ User message queue works" )

        # 9: Build lead options (only if SDK available)
        if SDK_AVAILABLE:
            opts = orch._build_lead_options()
            assert opts.permission_mode == "plan"
            assert opts.model == "claude-opus-4-6"
            print( "✓ Lead options built correctly" )
        else:
            print( "⚠ Skipping lead options test (SDK not available)" )

        # 10: Diagnosis abstract
        from cosa.agents.bug_fix_expediter.state import DiagnosisResult as DR
        diag = DR( root_cause="Test cause", error_category="code_bug", confidence=0.8 )
        abstract = BFEOrchestrator._build_diagnosis_abstract( diag )
        assert "Test cause" in abstract
        assert "80%" in abstract
        print( "✓ Diagnosis abstract generation works" )

        print( "\n✓ BFE Orchestrator smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
