"""
TestFixExpediter Orchestrator — Phase 0 through Phase 6.

Phase status (audited 2026-04-15 — previous "STUB" labels were stale):
    0. Cluster   — ✅ REAL: heuristic seed + cap-enforced LLM refinement
    1. Diagnose  — ✅ REAL: Opus lead agent via Claude Agent SDK
    2. Propose   — ✅ REAL: per-cluster proposal + aggregate voice gate
    3. Fix       — ✅ REAL: delegates to shared FixExecutor
    5. Git       — ✅ REAL: shared GitStrategist.commit_and_pr_multi (multi-commit, single PR)
    6. Rerun     — ✅ REAL: async TestSuiteJob resubmit with recursion guard

Design refs:
    - src/rnd/v0.1.6/2026.04.10-test-fix-expediter/03-phase0-clustering-plan.md
    - src/rnd/v0.1.6/2026.04.10-test-fix-expediter/04-phase1-diagnose-plan.md
    - src/rnd/v0.1.6/2026.04.10-test-fix-expediter/05-phase2-propose-plan.md
    - src/rnd/v0.1.6/2026.04.10-test-fix-expediter/06-phase3-fix-delegation-plan.md
    - src/rnd/v0.1.6/2026.04.10-test-fix-expediter/07-phase5-multi-cluster-git-plan.md
    - src/rnd/v0.1.6/2026.04.10-test-fix-expediter/08-phase6-rerun-validation-plan.md
    - src/rnd/v0.1.6/2026.04.10-test-fix-expediter/10-prompt-design.md
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Optional

import cosa.utils.util as cu

from cosa.agents.test_fix_expediter.config import TestFixExpediterConfig
from cosa.agents.test_fix_expediter.state import (
    TFEPhase,
    TFE_PHASE_ORDINALS,
    TestRemediationContext,
    FailureCluster,
    TestDiagnosisResult,
    TFEProposedFix,
    VoiceGateTimeoutError,
    StalledException,
)
from cosa.agents.test_fix_expediter.prompts.diagnosis import (
    DIAGNOSIS_SYSTEM_PROMPT,
    build_diagnosis_prompt,
)
from cosa.agents.test_fix_expediter.prompts.proposal import (
    build_proposal_prompt,
    build_proposal_system_prompt,
)
# Importing prompts.fix for its side-effect: registers TFE's coder/tester/
# fix/verify/redelegate builders into shared FIX_PROMPT_BUILDERS["tfe"].
from cosa.agents.test_fix_expediter.prompts import fix as _tfe_fix_prompts  # noqa: F401
from cosa.agents.test_fix_expediter.prompts.fix import (
    CODER_SYSTEM_PROMPT as TFE_CODER_SYSTEM_PROMPT,
    TESTER_SYSTEM_PROMPT as TFE_TESTER_SYSTEM_PROMPT,
)

# SWE Team safety primitives (shared with BFE)
try:
    from cosa.agents.swe_team.safety_limits import SafetyGuard, SafetyLimitError
    from cosa.agents.swe_team.hooks import build_can_use_tool, post_tool_hook, wrap_prompt_for_streaming
    from cosa.agents.swe_team.test_runner import run_pytest
    SAFETY_AVAILABLE = True
except ImportError:  # pragma: no cover - optional-dep import guard; swe_team safety primitives installed in this env
    SAFETY_AVAILABLE = False

# Claude Agent SDK imports — graceful fallback for environments without SDK
try:
    from claude_agent_sdk import (
        ClaudeAgentOptions,
        AssistantMessage,
        TextBlock,
        ToolUseBlock,
        ResultMessage,
        query as sdk_query,
        RateLimitEvent,
    )
    SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - optional-dep import guard; claude_agent_sdk installed in this env
    SDK_AVAILABLE = False

logger = logging.getLogger( __name__ )


class TFEOrchestrator:
    """
    TestFixExpediter pipeline orchestrator.

    Requires:
        - remediation_context is a valid TestRemediationContext
        - config is a TestFixExpediterConfig
        - user_id / user_email / session_id are non-empty
        - job_id has a "tfe-" prefix

    Ensures:
        - Phase methods are callable (real for P0/P1, stubs for P2-P6)
        - Never raises from public phase methods — failures surface as
          low-confidence or empty results
    """

    def __init__(
        self,
        remediation_context: TestRemediationContext,
        config: TestFixExpediterConfig,
        user_id: str,
        user_email: str,
        session_id: str,
        job_id: str,
        dry_run: bool = False,
        debug: bool = False,
        verbose: bool = False,
    ):
        self.remediation_context = remediation_context
        self.config              = config
        self.user_id             = user_id
        self.user_email          = user_email
        self.session_id          = session_id
        self.job_id              = job_id
        self.dry_run             = dry_run
        self.debug               = debug
        self.verbose             = verbose

        # Pipeline state (populated as phases run)
        self.clusters              : list[ FailureCluster ]            = []
        self.diagnoses             : dict[ str, TestDiagnosisResult ]  = {}
        self.proposed_fixes        : list[ TFEProposedFix ]            = []
        self.selected_fixes        : list[ TFEProposedFix ]            = []
        self.fix_results                                                = []
        self.files_changed_by_cluster : dict                            = {}
        self.last_plan_path        : Optional[ str ]                    = None
        self.branch_name           : Optional[ str ]                    = None
        self.commit_hashes         : list[ str ]                        = []
        self.pr_url                : Optional[ str ]                    = None
        self.validation_run_job_id : Optional[ str ]                    = None

        # Cancellation state (external integration wires this in)
        self._stop_requested = False

        # Current phase (for observability)
        self.current_phase = TFEPhase.LOADING

        # Resume state (set by set_resume_phase() after load_checkpoint()).
        # When not None, phase methods whose ordinal <= this value return
        # the rehydrated state from the checkpoint instead of re-running.
        # See: TFE_PHASE_ORDINAL (below) + load_checkpoint / set_resume_phase.
        self._resume_from_ordinal : Optional[ int ] = None

        # Bug 9 (2026-04-16): worktree isolation state. Populated inside
        # `worktree_scope()` context manager during Phase 3 + Phase 5; used
        # by `_build_tfe_coder_options`, `_build_tfe_tester_options`, and
        # Phase 5 git ops to route into an isolated sandbox.
        self._worktree_cwd : Optional[ str ] = None

        # Option A (2026-04-18): per-fix Coder turn-budget tier. Set by the
        # Phase 3 loop before each `executor.execute_fix(...)` call; read by
        # `_build_tfe_coder_options` to pick max_turns from config. Sequential
        # Phase 3 execution makes this single-writer safe.
        self._current_budget_tier : str = "medium"

    # ───────────────────────────────────────────────────────────────
    # Cancellation + notification helpers
    # ───────────────────────────────────────────────────────────────

    def _is_cancelled( self ) -> bool:
        """Check external cancellation flag."""
        return self._stop_requested

    def request_stop( self ) -> None:
        """External cancellation entry point."""
        self._stop_requested = True

    async def _notify(
        self,
        message: str,
        priority: str = "low",
        abstract: Optional[ str ] = None,
    ) -> None:
        """
        Send a voice notification via TFE's voice_io + cosa_interface.

        Errors are swallowed (notification never blocks the pipeline).
        In dry-run mode, prints a breadcrumb to stdout if debug is on.
        """
        if self.dry_run and self.debug:
            print( f"[TFE {self.current_phase.value}] {message}" )

        try:
            from cosa.agents.test_fix_expediter import cosa_interface, voice_io
            # Fix 6: `notification_type` is NOT a valid kwarg for notify_progress.
            # The dispatcher sets NotificationType.PROGRESS internally. Previously
            # passed as a kwarg → TypeError caught below → hundreds of
            # "[TFE notify error]" log lines per TFE run with no actual
            # progress notifications sent. See plan:
            # src/rnd/v0.1.6/2026.04.11-tfe-forensics-capture-plan.md
            await cosa_interface.notify_progress(
                message,
                priority=priority,
                abstract=abstract,
                job_id=self.job_id,
            )
        except Exception as e:
            # Notification must never block the pipeline
            if self.debug: print( f"[TFE notify error] {e}" )

    # ───────────────────────────────────────────────────────────────
    # Checkpoint-resume (Session 9056c113)
    # ───────────────────────────────────────────────────────────────

    def save_checkpoint( self ) -> dict:
        """
        Serialize current pipeline state to a JSON-safe dict.

        Requires:
            - Called after at least one phase has completed

        Ensures:
            - Returns dict matching CheckpointData schema
            - All Pydantic models converted to dicts via .model_dump()
        """
        from cosa.agents.test_fix_expediter.state import TFE_PHASE_ORDINALS
        from datetime import datetime

        state_snapshot = {
            "source_test_suite_job_id"  : self.remediation_context.source_test_suite_job_id,
            "remediation_snapshot_path" : self.remediation_context.snapshot_path,
            "clusters"                  : [ c.model_dump() for c in self.clusters ],
            "diagnoses"                 : { k: v.model_dump() for k, v in self.diagnoses.items() },
            "proposed_fixes"            : [ p.model_dump() for p in self.proposed_fixes ],
            "selected_fixes"            : [ s.model_dump() for s in self.selected_fixes ],
            "fix_results"               : [ r.model_dump() if hasattr( r, "model_dump" ) else r
                                            for r in self.fix_results ],
            "files_changed_by_cluster"  : dict( self.files_changed_by_cluster ),
            "last_plan_path"            : self.last_plan_path,
            "branch_name"               : self.branch_name,
            "commit_hashes"             : list( self.commit_hashes ),
            "pr_url"                    : self.pr_url,
            "validation_run_job_id"     : self.validation_run_job_id,
        }

        artifacts = {}
        if self.last_plan_path: artifacts[ "plan_path" ] = self.last_plan_path

        return {
            "phase_ordinal"  : TFE_PHASE_ORDINALS.get( self.current_phase, -1 ),
            "phase_name"     : self.current_phase.value,
            "stall_reason"   : "voice_gate_timeout",
            "stalled_at"     : datetime.now().isoformat(),
            "state_snapshot" : state_snapshot,
            "artifacts"      : artifacts,
            "resume_count"   : 0,
        }

    def load_checkpoint( self, data: dict ) -> None:
        """
        Restore pipeline state from a previously saved checkpoint.

        Requires:
            - data matches CheckpointData schema
            - self.remediation_context is already loaded (snapshot_loader ran)

        Ensures:
            - All instance attributes restored to checkpoint values
            - Pydantic models reconstructed from dicts
        """
        snap = data[ "state_snapshot" ]

        self.clusters                  = [ FailureCluster( **c ) for c in snap.get( "clusters", [] ) ]
        self.diagnoses                 = { k: TestDiagnosisResult( **v )
                                           for k, v in snap.get( "diagnoses", {} ).items() }
        self.proposed_fixes            = [ TFEProposedFix( **p ) for p in snap.get( "proposed_fixes", [] ) ]
        self.selected_fixes            = [ TFEProposedFix( **s ) for s in snap.get( "selected_fixes", [] ) ]
        self.fix_results               = snap.get( "fix_results", [] )
        self.files_changed_by_cluster  = snap.get( "files_changed_by_cluster", {} )
        self.last_plan_path            = snap.get( "last_plan_path" )
        self.branch_name               = snap.get( "branch_name" )
        self.commit_hashes             = snap.get( "commit_hashes", [] )
        self.pr_url                    = snap.get( "pr_url" )
        self.validation_run_job_id     = snap.get( "validation_run_job_id" )
        self.current_phase             = TFEPhase( data[ "phase_name" ] )

    def set_resume_phase( self, phase_ordinal: int ) -> None:
        """
        Mark phases up to phase_ordinal as already completed so phase
        methods skip work that has already been done.

        Requires:
            - phase_ordinal >= 0
            - load_checkpoint() has already been called

        Ensures:
            - self._resume_from_ordinal is set
            - Phase methods check this to skip completed work
        """
        self._resume_from_ordinal = phase_ordinal

    # ───────────────────────────────────────────────────────────────
    # Phase 0: Cluster (step 7)
    # ───────────────────────────────────────────────────────────────

    async def run_phase0_cluster( self ) -> list[ FailureCluster ]:
        """
        Group N failures into K clusters (K ≤ max_clusters).

        Heuristic seed + cap-enforced refinement (pure Python). Real LLM
        refinement callback wiring lands in a later iteration.
        """
        # Resume short-circuit: if checkpoint already carried us past this
        # phase, return the rehydrated clusters without re-running heuristic
        # + LLM refinement. See load_checkpoint / set_resume_phase.
        if self._resume_from_ordinal is not None and self._resume_from_ordinal >= TFE_PHASE_ORDINALS[ TFEPhase.CLUSTERING ]:
            if self.debug: print( f"[TFE] Phase 0 skipped via resume (ordinal={self._resume_from_ordinal})" )
            self.current_phase = TFEPhase.CLUSTERING
            return self.clusters

        from cosa.agents.test_fix_expediter.cluster import heuristic_seed, llm_refine

        self.current_phase = TFEPhase.CLUSTERING
        await self._notify(
            f"Clustering {len( self.remediation_context.failures )} failures...",
            priority="low",
        )

        seeds = heuristic_seed( self.remediation_context )
        self.clusters = await llm_refine(
            self.remediation_context, seeds, max_clusters=self.config.max_clusters
        )

        await self._notify(
            f"Phase 0 complete: {len( self.clusters )} cluster(s) identified",
            priority="low",
        )
        return self.clusters

    # ───────────────────────────────────────────────────────────────
    # Phase 1: Diagnose (step 8)
    # ───────────────────────────────────────────────────────────────

    async def run_phase1_diagnose( self ) -> dict:
        """
        Per-cluster diagnosis via Opus lead agent (read-only SDK).

        Requires:
            - self.clusters is populated (run_phase0_cluster must run first)
            - SDK_AVAILABLE is True (falls back to low-confidence otherwise)

        Ensures:
            - Returns dict[cluster_id → TestDiagnosisResult]
            - Every cluster in self.clusters has a corresponding entry
            - Failed diagnoses get low-confidence fallback (not exceptions)
        """
        # Resume short-circuit: skip re-diagnosis if checkpoint already has it.
        if self._resume_from_ordinal is not None and self._resume_from_ordinal >= TFE_PHASE_ORDINALS[ TFEPhase.DIAGNOSING ]:
            if self.debug: print( f"[TFE] Phase 1 skipped via resume (ordinal={self._resume_from_ordinal})" )
            self.current_phase = TFEPhase.DIAGNOSING
            return self.diagnoses

        self.current_phase = TFEPhase.DIAGNOSING

        if not self.clusters:
            await self._notify(
                "Phase 1 skipped: no clusters to diagnose",
                priority="low",
            )
            self.diagnoses = {}
            return self.diagnoses

        if not SDK_AVAILABLE:
            logger.error( "Claude Agent SDK not available — Phase 1 fallback" )
            self.diagnoses = {
                c.cluster_id: self._fallback_diagnosis(
                    c.cluster_id, "Claude Agent SDK not installed"
                )
                for c in self.clusters
            }
            return self.diagnoses

        k = len( self.clusters )
        await self._notify(
            f"Phase 1: diagnosing {k} cluster(s)...",
            priority="medium",
        )

        diagnoses: dict[ str, TestDiagnosisResult ] = {}

        for i, cluster in enumerate( self.clusters, start=1 ):
            if self._is_cancelled():
                await self._notify( "Phase 1 cancelled", priority="medium" )
                break

            await self._notify(
                f"Diagnosing cluster {i}/{k}: {cluster.cluster_id}",
                priority="low",
            )

            diagnosis = await self._diagnose_cluster( cluster )
            diagnoses[ cluster.cluster_id ] = diagnosis

            if self.debug:
                print(
                    f"[TFEOrchestrator] Cluster {cluster.cluster_id}: "
                    f"category={diagnosis.error_category}, "
                    f"confidence={diagnosis.confidence:.0%}"
                )

        self.diagnoses = diagnoses

        # Summary notification
        summary_parts = [
            f"{cid} ({d.error_category}, {d.confidence:.0%})"
            for cid, d in diagnoses.items()
        ]
        await self._notify(
            f"Phase 1 complete: {len( diagnoses )} cluster(s) diagnosed",
            priority="medium",
            abstract="\n".join( f"- {p}" for p in summary_parts ),
        )

        return self.diagnoses

    async def _diagnose_cluster( self, cluster: FailureCluster ) -> TestDiagnosisResult:
        """
        Run the per-cluster diagnosis iteration loop.

        Iterates up to max_diagnosis_iterations, accepting the first result
        with confidence >= min_diagnosis_confidence. Returns the highest-
        confidence attempt if the threshold is never reached.

        Never raises — returns a low-confidence fallback on any error.
        """
        best_diagnosis: Optional[ TestDiagnosisResult ] = None
        attempts: list[ dict ] = []

        max_iters = self.config.max_diagnosis_iterations
        min_conf  = self.config.min_diagnosis_confidence

        for iteration in range( 1, max_iters + 1 ):
            if self._is_cancelled():
                break

            prompt = build_diagnosis_prompt(
                cluster            = cluster,
                ctx                = self.remediation_context,
                iteration          = iteration,
                previous_attempts  = attempts if iteration > 1 else None,
                max_iterations     = max_iters,
                min_confidence     = min_conf,
            )

            raw = await self._delegate_to_lead_diagnosis( prompt )

            if raw is None:
                if self.debug: print(
                    f"[TFEOrchestrator] Cluster {cluster.cluster_id} iter {iteration}: SDK returned None"
                )
                continue

            diagnosis = self._parse_diagnosis_result( raw, cluster.cluster_id )
            attempts.append( diagnosis.model_dump() )

            if best_diagnosis is None or diagnosis.confidence > best_diagnosis.confidence:
                best_diagnosis = diagnosis

            if diagnosis.confidence >= min_conf:
                if self.debug: print(
                    f"[TFEOrchestrator] Cluster {cluster.cluster_id} iter {iteration}: "
                    f"confidence {diagnosis.confidence:.0%} ≥ {min_conf:.0%} — done"
                )
                break

        if best_diagnosis is None:
            return self._fallback_diagnosis(
                cluster.cluster_id,
                "All diagnosis iterations produced no result",
            )

        return best_diagnosis

    async def _delegate_to_lead_diagnosis( self, prompt: str ) -> Optional[ str ]:
        """
        Invoke the Lead agent via Claude Agent SDK and collect response text.

        Ensures:
            - Returns raw text response (may be empty)
            - Returns None on any SDK-level failure
            - Never raises
        """
        options = self._build_lead_diagnosis_options()

        try:
            collected = []

            async for message in sdk_query( prompt=prompt, options=options ):
                if self._is_cancelled():
                    break

                if isinstance( message, AssistantMessage ):
                    for block in message.content:
                        if isinstance( block, TextBlock ):
                            collected.append( block.text )
                        elif isinstance( block, ToolUseBlock ):
                            await self._notify(
                                f"Investigating: {block.name}",
                                priority="low",
                            )
                elif isinstance( message, TextBlock ):
                    collected.append( message.text )
                elif isinstance( message, ResultMessage ):
                    pass
                elif isinstance( message, RateLimitEvent ):
                    logger.warning(
                        f"Rate limited: retry_after={getattr( message, 'retry_after', '?' )}s"
                    )

            raw = "".join( collected ).strip()
            return raw if raw else None

        except Exception as e:
            logger.error( f"SDK delegation failed in Phase 1: {e}" )
            if self.debug:
                import traceback
                traceback.print_exc()
            return None

    def _build_lead_diagnosis_options( self ):
        """Build ClaudeAgentOptions for the TFE diagnosis Lead agent."""
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

    # ───────────────────────────────────────────────────────────────
    # JSON parsing (shared with downstream phases)
    # ───────────────────────────────────────────────────────────────

    def _parse_diagnosis_result(
        self,
        raw_response: str,
        cluster_id: str,
    ) -> TestDiagnosisResult:
        """
        Parse a TestDiagnosisResult from the Lead agent's raw text response.

        Handles clean JSON, markdown-fenced JSON, and JSON embedded in prose.
        Returns a low-confidence fallback on any parse failure.
        """
        text = raw_response.strip()

        # Strip markdown code fences if present
        if "```json" in text:
            text = text.split( "```json" )[ -1 ]
        if "```" in text:
            text = text.split( "```" )[ 0 ]

        json_str = self._extract_last_json_object( text )
        if json_str is None:
            logger.warning(
                f"[TFE] No JSON object in response for {cluster_id} — fallback"
            )
            return self._fallback_diagnosis( cluster_id, raw_response[ :500 ] )

        try:
            data = json.loads( json_str )
            # Ensure cluster_id is populated even if the LLM omitted it
            if "cluster_id" not in data or not data[ "cluster_id" ]:
                data[ "cluster_id" ] = cluster_id
            return TestDiagnosisResult( **data )
        except ( json.JSONDecodeError, ValueError, TypeError ) as e:
            logger.warning( f"[TFE] JSON parse failed for {cluster_id}: {e}" )
            return self._fallback_diagnosis( cluster_id, raw_response[ :500 ] )

    @staticmethod
    def _extract_last_json_object( text: str ) -> Optional[ str ]:
        """
        Extract the last balanced JSON object from text.

        Walks backward from the last `}` to find the matching `{`.
        Returns None if no balanced object is found.
        """
        close_idx = text.rfind( "}" )
        if close_idx == -1:
            return None

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
    def _fallback_diagnosis( cluster_id: str, reason: str ) -> TestDiagnosisResult:
        """Low-confidence fallback diagnosis used on SDK/parse failures."""
        return TestDiagnosisResult(
            cluster_id          = cluster_id,
            root_cause          = reason,
            error_category      = "unknown",
            confidence          = 0.1,
            evidence            = [ "Failed to parse structured diagnosis" ],
            affected_components = [],
            is_transient        = False,
            test_symptoms       = [],
        )

    # ───────────────────────────────────────────────────────────────
    # Phase 2-6: stubs (full implementations in steps 9-12)
    # ───────────────────────────────────────────────────────────────

    # ───────────────────────────────────────────────────────────────
    # Phase 2: Propose (step 9)
    # ───────────────────────────────────────────────────────────────

    async def run_phase2_propose( self ) -> tuple:
        """
        Per-cluster fix proposals. Aggregated voice gate selects a subset.

        Requires:
            - self.clusters is populated (Phase 0 ran)
            - self.diagnoses is populated (Phase 1 ran)
            - SDK_AVAILABLE (falls back to empty proposals otherwise)

        Ensures:
            - Returns (proposed_fixes, selected_fixes, plan_path) tuple
            - Writes a multi-section plan doc via shared PlanWriter when
              at least one valid proposal exists (not in dry_run)
            - Populates self.proposed_fixes, self.selected_fixes, self.last_plan_path
        """
        # Resume short-circuit: if the checkpoint captured proposed_fixes from
        # a previous run (stall at voice gate is the common case), skip
        # regenerating proposals and go straight to the voice gate.
        if (
            self._resume_from_ordinal is not None
            and self._resume_from_ordinal >= TFE_PHASE_ORDINALS[ TFEPhase.PROPOSING ]
            and self.proposed_fixes
        ):
            if self.debug: print( f"[TFE] Phase 2 propose-gen skipped via resume (ordinal={self._resume_from_ordinal}, {len( self.proposed_fixes )} proposals rehydrated)" )
            self.current_phase = TFEPhase.PROPOSING
            # Still run the voice gate — that's why we resumed.
            if not self._is_cancelled():
                try:
                    self.selected_fixes = await self._proposal_voice_gate( self.proposed_fixes )
                except VoiceGateTimeoutError:
                    checkpoint = self.save_checkpoint()
                    raise StalledException(
                        checkpoint = checkpoint,
                        phase      = TFEPhase.PROPOSING.value,
                        message    = (
                            f"Voice gate timeout at resumed Phase 2 — "
                            f"{len( self.proposed_fixes )} proposals await review"
                        ),
                    )
            return ( self.proposed_fixes, self.selected_fixes, self.last_plan_path )

        self.current_phase = TFEPhase.PROPOSING

        if not self.clusters or not self.diagnoses:
            await self._notify(
                "Phase 2 skipped: no clusters or diagnoses",
                priority="low",
            )
            self.proposed_fixes = []
            self.selected_fixes = []
            self.last_plan_path = None
            return ( self.proposed_fixes, self.selected_fixes, self.last_plan_path )

        if not SDK_AVAILABLE:
            logger.error( "Claude Agent SDK not available — Phase 2 skipped" )
            self.proposed_fixes = []
            self.selected_fixes = []
            self.last_plan_path = None
            return ( self.proposed_fixes, self.selected_fixes, self.last_plan_path )

        await self._notify(
            f"Phase 2: proposing fixes for {len( self.clusters )} cluster(s)...",
            priority="medium",
        )

        all_proposals: list[ TFEProposedFix ] = []

        for i, cluster in enumerate( self.clusters, start=1 ):
            if self._is_cancelled():
                await self._notify( "Phase 2 cancelled", priority="medium" )
                break

            diagnosis = self.diagnoses.get( cluster.cluster_id )
            if diagnosis is None:
                logger.warning(
                    f"[TFE] No diagnosis for cluster {cluster.cluster_id} — skipping"
                )
                continue

            await self._notify(
                f"Proposing fixes for cluster {i}/{len( self.clusters )}: {cluster.cluster_id}",
                priority="low",
            )

            cluster_proposals = await self._propose_for_cluster( cluster, diagnosis )
            all_proposals.extend( cluster_proposals )

        self.proposed_fixes = all_proposals

        # Write plan doc (skip in dry_run)
        self.last_plan_path = None
        if all_proposals and not self.dry_run:
            try:
                self.last_plan_path = self._write_multi_cluster_plan_doc( all_proposals )
            except Exception as e:
                logger.warning( f"[TFE] Plan doc write failed: {e}" )

        # Aggregate voice gate — user selects a subset
        if all_proposals and not self._is_cancelled():
            try:
                self.selected_fixes = await self._proposal_voice_gate( all_proposals )
            except VoiceGateTimeoutError:
                checkpoint = self.save_checkpoint()
                raise StalledException(
                    checkpoint = checkpoint,
                    phase      = TFEPhase.PROPOSING.value,
                    message    = (
                        f"Voice gate timeout at Phase 2 — "
                        f"{len( all_proposals )} proposals await review"
                    ),
                )
        else:
            self.selected_fixes = []

        await self._notify(
            f"Phase 2 complete: {len( all_proposals )} proposed, "
            f"{len( self.selected_fixes )} selected",
            priority="medium",
        )

        return ( self.proposed_fixes, self.selected_fixes, self.last_plan_path )

    async def _propose_for_cluster(
        self,
        cluster: FailureCluster,
        diagnosis: TestDiagnosisResult,
    ) -> list[ TFEProposedFix ]:
        """
        Run one Propose call for a single cluster. Returns 0-3 proposals.

        Never raises — returns empty list on any error.
        """
        prompt = build_proposal_prompt(
            cluster,
            diagnosis,
            self.remediation_context,
            max_proposals = self.config.max_proposals_per_cluster,
        )
        raw = await self._delegate_to_lead_proposal( prompt )

        if raw is None:
            logger.warning(
                f"[TFE] Propose delegation returned None for {cluster.cluster_id}"
            )
            return []

        proposals = self._parse_proposal_result( raw, cluster.cluster_id )
        return proposals

    async def _delegate_to_lead_proposal( self, prompt: str ) -> Optional[ str ]:
        """Invoke the Lead agent for a propose call. Mirrors _delegate_to_lead_diagnosis."""
        options = self._build_lead_proposal_options()

        try:
            collected = []

            async for message in sdk_query( prompt=prompt, options=options ):
                if self._is_cancelled():
                    break

                if isinstance( message, AssistantMessage ):
                    for block in message.content:
                        if isinstance( block, TextBlock ):
                            collected.append( block.text )
                        elif isinstance( block, ToolUseBlock ):
                            await self._notify(
                                f"Proposing: {block.name}",
                                priority="low",
                            )
                elif isinstance( message, TextBlock ):
                    collected.append( message.text )
                elif isinstance( message, ResultMessage ):
                    pass
                elif isinstance( message, RateLimitEvent ):
                    logger.warning(
                        f"Rate limited: retry_after={getattr( message, 'retry_after', '?' )}s"
                    )

            raw = "".join( collected ).strip()
            return raw if raw else None

        except Exception as e:
            logger.error( f"SDK delegation failed in Phase 2: {e}" )
            return None

    def _build_lead_proposal_options( self ):
        """Build ClaudeAgentOptions for the TFE proposal Lead agent."""
        return ClaudeAgentOptions(
            model           = self.config.lead_model,
            system_prompt   = build_proposal_system_prompt(
                max_proposals = self.config.max_proposals_per_cluster,
            ),
            tools           = [ "Read", "Glob", "Grep" ],
            cwd             = cu.get_project_root(),
            permission_mode = "plan",
            max_turns       = 20,
            max_budget_usd  = self.config.budget_usd,
            effort          = self.config.thinking_effort,
        )

    def _parse_proposal_result(
        self,
        raw_response: str,
        cluster_id: str,
    ) -> list[ TFEProposedFix ]:
        """
        Parse a JSON array of TFEProposedFix objects from the Lead response.

        Handles:
            - Clean JSON arrays
            - Arrays wrapped in markdown code fences
            - Single JSON objects (wrapped into a single-element array)
            - Arrays embedded in prose (top-level extraction, not nested)

        Returns an empty list on any parse failure (never raises).
        """
        text = raw_response.strip()
        if "```json" in text:
            text = text.split( "```json" )[ -1 ]
        if "```" in text:
            text = text.split( "```" )[ 0 ]
        text = text.strip()

        data = self._parse_proposal_json( text )
        if data is None:
            logger.warning(
                f"[TFE] Could not parse proposal response for {cluster_id}"
            )
            return []

        # If the payload is a dict, wrap into a single-element list.
        if isinstance( data, dict ):
            data = [ data ]

        if not isinstance( data, list ):
            logger.warning(
                f"[TFE] Proposal JSON is not an array or object for {cluster_id}: "
                f"{type( data ).__name__}"
            )
            return []

        proposals: list[ TFEProposedFix ] = []
        for item in data:
            if not isinstance( item, dict ):
                continue
            # Ensure cluster_id is populated
            if "cluster_id" not in item or not item[ "cluster_id" ]:
                item[ "cluster_id" ] = cluster_id
            try:
                proposals.append( TFEProposedFix( **item ) )
            except ( ValueError, TypeError ) as e:
                logger.warning(
                    f"[TFE] Dropping invalid proposal for {cluster_id}: {e}"
                )

        return proposals

    @staticmethod
    def _parse_proposal_json( text: str ):
        """
        Try to parse the text as a top-level JSON payload.

        Attempts in order:
          1. `json.loads(text)` on the whole text — works for clean JSON
          2. Walk backward from the last `]` to find a matching `[` and parse that
          3. Walk backward from the last `}` to find a matching `{` and parse that

        Returns the parsed dict/list, or None if nothing parses.
        """
        if not text:
            return None

        # Attempt 1: whole text is valid JSON
        try:
            return json.loads( text )
        except json.JSONDecodeError:
            pass

        # Attempt 2: top-level JSON array (walk backward from last `]`)
        close_idx = text.rfind( "]" )
        if close_idx != -1:
            depth = 0
            for i in range( close_idx, -1, -1 ):
                if text[ i ] == "]":
                    depth += 1
                elif text[ i ] == "[":
                    depth -= 1
                    if depth == 0:
                        candidate = text[ i : close_idx + 1 ]
                        try:
                            return json.loads( candidate )
                        except json.JSONDecodeError:
                            break

        # Attempt 3: top-level JSON object (walk backward from last `}`)
        close_idx = text.rfind( "}" )
        if close_idx != -1:
            depth = 0
            for i in range( close_idx, -1, -1 ):
                if text[ i ] == "}":
                    depth += 1
                elif text[ i ] == "{":
                    depth -= 1
                    if depth == 0:
                        candidate = text[ i : close_idx + 1 ]
                        try:
                            return json.loads( candidate )
                        except json.JSONDecodeError:
                            break

        return None

    def _write_multi_cluster_plan_doc( self, proposals: list[ TFEProposedFix ] ) -> str:
        """
        Write a multi-section plan doc via shared PlanWriter.

        The shared PlanWriter was built around BFE's single-diagnosis model,
        so we feed it a synthesized aggregate DiagnosisResult + the full
        proposals list. Each cluster's proposals show up in the Proposed
        Fixes section with cluster_id tags in the titles.
        """
        from cosa.agents.shared.plan_writer import PlanWriter
        from cosa.agents.bug_fix_expediter.state import DiagnosisResult

        writer = PlanWriter( user_email=self.remediation_context.user_email, debug=self.debug )

        # Synthesize a top-level diagnosis summary from per-cluster diagnoses
        cluster_lines = []
        all_components = []
        for cid, diag in self.diagnoses.items():
            cluster_lines.append(
                f"- **{cid}** ({diag.error_category}, {diag.confidence:.0%}): {diag.root_cause}"
            )
            for comp in diag.affected_components:
                if comp not in all_components:
                    all_components.append( comp )

        aggregate_root_cause = (
            f"{len( self.clusters )} cluster(s) from "
            f"{self.remediation_context.source_test_suite_job_id}:\n"
            + "\n".join( cluster_lines )
        )

        aggregate_diagnosis = DiagnosisResult(
            root_cause          = aggregate_root_cause,
            error_category      = "mixed" if len( set( d.error_category for d in self.diagnoses.values() ) ) > 1 else next( iter( self.diagnoses.values() ) ).error_category,
            confidence          = sum( d.confidence for d in self.diagnoses.values() ) / len( self.diagnoses ),
            evidence            = [
                f"{cid}: {', '.join( d.evidence[ :2 ] )}"
                for cid, d in self.diagnoses.items()
                if d.evidence
            ],
            affected_components = all_components,
        )

        # Synthesize a minimal dead-job-like context object for the writer
        # (PlanWriter only reads .id_hash, .job_type, .error, .stack_trace)
        from types import SimpleNamespace
        fake_ctx = SimpleNamespace(
            id_hash     = self.remediation_context.source_test_suite_job_id,
            job_type    = "test_fix_expediter",
            error       = f"{self.remediation_context.summary.get( 'total_failed', 0 )} failures + "
                          f"{self.remediation_context.summary.get( 'total_errors', 0 )} errors",
            stack_trace = None,
        )

        # Convert TFEProposedFix → something PlanWriter can render.
        # PlanWriter reads: .title, .description, .fix_type, .confidence,
        # .risk_level, .estimated_effort, .changes. TFEProposedFix has all of
        # these (plus .cluster_id). Prepend cluster_id to the title for clarity.
        render_proposals = [
            SimpleNamespace(
                title            = f"[{p.cluster_id}] {p.title}",
                description      = p.description,
                fix_type         = p.fix_type,
                confidence       = p.confidence,
                risk_level       = p.risk_level,
                estimated_effort = p.estimated_effort,
                changes          = p.changes,
            )
            for p in proposals
        ]

        return writer.write_plan(
            dead_job_context = fake_ctx,
            diagnosis        = aggregate_diagnosis,
            proposed_fixes   = render_proposals,
            selected_fix     = None,   # user selects in the voice gate below
        )

    async def _proposal_voice_gate(
        self,
        proposals: list[ TFEProposedFix ],
    ) -> list[ TFEProposedFix ]:
        """
        Present proposals to the user via an aggregated multi-select voice gate.

        In `aggregate` mode (default): one `ask_multiple_choice(multiSelect=True)`
        call. In `per_cluster` mode: K sequential `ask_yes_no` calls.

        In dry_run mode, auto-selects all proposals (no user prompt).

        Returns the subset of proposals the user approved.
        """
        if self.dry_run:
            if self.debug: print( "[TFE] dry_run: auto-selecting all proposals" )
            return list( proposals )

        if self.config.voice_gate_mode == "per_cluster":
            return await self._per_cluster_voice_gate( proposals )
        return await self._aggregate_voice_gate( proposals )

    async def _aggregate_voice_gate(
        self,
        proposals: list[ TFEProposedFix ],
    ) -> list[ TFEProposedFix ]:
        """One multi-select gate showing all proposals as a checklist."""
        from cosa.agents.test_fix_expediter import cosa_interface

        options = []
        for p in proposals:
            options.append( {
                "label": f"{p.cluster_id}: {p.title}",
                "description": (
                    f"{p.fix_type}, {p.confidence:.0%} confidence, "
                    f"{p.risk_level} risk, {p.estimated_effort}. "
                    f"Affects {len( p.changes )} file(s)."
                ),
            } )

        try:
            result = await cosa_interface.present_choices(
                questions=[ {
                    "question"    : f"Select fixes to apply ({len( proposals )} proposals):",
                    "header"      : "Fixes",
                    "multiSelect" : True,
                    "options"     : options,
                } ],
                timeout  = self.config.feedback_timeout_seconds,
                title    = "TFE Proposal",
                abstract = self._render_proposal_abstract( proposals ),
                job_id   = self.job_id,
            )
        except VoiceGateTimeoutError:
            # WG-9 (2026-04-28): branch on the configured timeout policy.
            # Default policy "stall" preserves prior behavior (raise → STALLED).
            return self._apply_voice_gate_timeout_policy( proposals )
        except Exception as e:
            logger.warning( f"[TFE] Voice gate failed: {e} — auto-selecting all" )
            return list( proposals )

        selected_labels = result.get( "answers", {} ).get( "Fixes", [] )
        if isinstance( selected_labels, str ):
            selected_labels = [ selected_labels ]

        label_to_proposal = {
            f"{p.cluster_id}: {p.title}": p for p in proposals
        }
        return [ label_to_proposal[ label ] for label in selected_labels
                 if label in label_to_proposal ]

    def _apply_voice_gate_timeout_policy(
        self,
        proposals: list[ TFEProposedFix ],
    ) -> list[ TFEProposedFix ]:
        """
        Resolve a voice-gate timeout per the configured policy.

        Policies:
            - "stall"    → re-raise VoiceGateTimeoutError (current behavior; STALLED job)
            - "top_1"    → return single highest-confidence proposal
            - "top_n"    → return top-N highest-confidence proposals (N from config)
            - "none"     → return [] (exit cleanly with no_fixes_selected)
            - "delegate" → RESERVED for UPE online-learning integration (NotImplementedError today)

        Proposals are sorted by `confidence` desc; ties keep input order.
        Unknown policy values fall back to "stall" with a warning.

        See `src/rnd/v0.1.7/2026.04.28-test-suite-anomaly-remediation/05-voice-gate-policy-evolution.md`
        for the target layered architecture (Layer 0 system default + Layer 1 per-agent override
        + UPE delegate + abstention threshold + post-hoc feedback loop).
        """
        policy = ( self.config.voice_gate_timeout_policy or "stall" ).lower()

        if policy == "stall":
            logger.info( "[TFE] voice gate timeout — policy=stall — propagating StalledException" )
            raise VoiceGateTimeoutError( "voice gate timed out and policy=stall" )

        if policy == "none":
            logger.warning( "[TFE] voice gate timeout — policy=none — selecting 0 proposals" )
            return []

        if policy == "delegate":
            return self._delegate_to_predictor( proposals )

        sorted_props = sorted(
            proposals,
            key=lambda p: ( -float( getattr( p, "confidence", 0.0 ) or 0.0 ),
                            proposals.index( p ) ),
        )

        if policy == "top_1":
            n = 1
        elif policy == "top_n":
            n = max( 1, int( self.config.voice_gate_auto_ratify_top_n ) )
        else:
            logger.warning(
                f"[TFE] unknown voice_gate_timeout_policy={policy!r}; falling back to stall" )
            raise VoiceGateTimeoutError( f"voice gate timed out; unknown policy={policy!r}" )

        selected = sorted_props[ :n ]
        logger.warning(
            f"[TFE] voice gate timeout — policy={policy} — auto-selected "
            f"{len( selected )}/{len( proposals )} proposal(s) by confidence" )
        return selected

    def _delegate_to_predictor(
        self,
        proposals: list[ TFEProposedFix ],
    ) -> list[ TFEProposedFix ]:
        """
        RESERVED HOOK — Delegate the voice-gate timeout decision to the
        Universal Prediction Engine (UPE) using its online-learned model
        of operator priors.

        Not implemented today. UPE's online-learning surface is ~2 dev
        branches out (per 2026-04-28 design discussion). When UPE lands,
        the policy `delegate` becomes a real option and the implementation
        of this method materializes per the contract sketched in
        `05-voice-gate-policy-evolution.md`:

            - Build a delegate request: agent_type, gate_type, context
              (proposals + cluster summary + diagnoses), operator_user_id,
              min_confidence threshold, request_id (for feedback tracking).
            - Call UPE; receive (answer, confidence, abstained, reasoning,
              training_signal_id).
            - If abstained or confidence < min_confidence → fall through to
              the configured `voice gate fallback policy` (default "stall").
            - Otherwise return the predicted subset of proposals AND persist
              training_signal_id alongside the applied fix so post-hoc
              operator approval/revert can flow back to UPE as a learning
              signal.

        Until that work lands, this method raises NotImplementedError so a
        misconfigured `voice gate timeout policy = delegate` fails loudly
        instead of silently falling through to `stall`.
        """
        raise NotImplementedError(
            "voice_gate_timeout_policy='delegate' is reserved for the UPE online-learning "
            "integration (~2 dev branches out). Use 'stall', 'top_1', 'top_n', or 'none' "
            "for now. See src/rnd/v0.1.7/2026.04.28-test-suite-anomaly-remediation/"
            "05-voice-gate-policy-evolution.md for the planned architecture."
        )

    async def _per_cluster_voice_gate(
        self,
        proposals: list[ TFEProposedFix ],
    ) -> list[ TFEProposedFix ]:
        """K sequential yes/no gates, one per proposal."""
        from cosa.agents.test_fix_expediter import cosa_interface

        selected = []
        for p in proposals:
            try:
                answer = await cosa_interface.ask_confirmation(
                    question=f"Apply fix for {p.cluster_id}: {p.title}?",
                    default="yes",
                    priority="high",
                    timeout=self.config.feedback_timeout_seconds,
                    abstract=self._render_single_proposal( p ),
                    job_id=self.job_id,
                )
            except Exception as e:
                logger.warning( f"[TFE] Per-cluster gate failed for {p.cluster_id}: {e}" )
                selected.append( p )   # on error, err on the side of applying
                continue

            if isinstance( answer, str ) and answer.lower().startswith( "yes" ):
                selected.append( p )

        return selected

    @staticmethod
    def _render_proposal_abstract( proposals: list[ TFEProposedFix ] ) -> str:
        """Render a markdown summary of all proposals for the voice gate abstract."""
        lines = [ f"**{len( proposals )} proposed fixes** across clusters:" ]
        lines.append( "" )
        for p in proposals:
            lines.append( f"- **{p.cluster_id}** {p.title}" )
            lines.append(
                f"  {p.fix_type} • confidence {p.confidence:.0%} • "
                f"risk {p.risk_level} • {p.estimated_effort}"
            )
            if p.description:
                truncated = p.description[ :200 ]
                lines.append( f"  {truncated}" )
        return "\n".join( lines )

    @staticmethod
    def _render_single_proposal( p: TFEProposedFix ) -> str:
        """Render a single proposal for a per-cluster yes/no gate."""
        lines = [
            f"**{p.cluster_id}: {p.title}**",
            "",
            f"**Type**: {p.fix_type}",
            f"**Confidence**: {p.confidence:.0%}",
            f"**Risk**: {p.risk_level}",
            f"**Effort**: {p.estimated_effort}",
            f"**Files**: {len( p.changes )}",
            "",
            p.description,
        ]
        return "\n".join( lines )

    # ───────────────────────────────────────────────────────────────
    # Phase 3: Fix (step 10) — delegates to shared FixExecutor
    # ───────────────────────────────────────────────────────────────

    async def run_phase3_fix( self ) -> list:
        """
        Apply the selected fixes via the shared FixExecutor.

        For each TFEProposedFix in `self.selected_fixes`:
          1. Look up the corresponding FailureCluster + TestDiagnosisResult
          2. Build a FixContext (duck-typed pass-through) from cluster + diagnosis
          3. Call `FixExecutor.execute_fix(...)` with `prompt_builder_key="tfe"`
          4. Collect the FixResult + files_changed, attribute to the cluster
          5. If `continue_on_cluster_failure == false` and a cluster fails, abort

        Requires:
            - self.selected_fixes is populated (Phase 2 ran and user selected)
            - self.clusters and self.diagnoses are populated
            - SDK_AVAILABLE (falls back to empty results otherwise)

        Ensures:
            - Returns list[FixResult], one per selected fix (in selection order)
            - Populates self.fix_results and self.files_changed_by_cluster
            - Never raises
        """
        from cosa.agents.shared.fix_executor import FixExecutor
        from types import SimpleNamespace

        self.current_phase = TFEPhase.FIXING

        if not self.selected_fixes:
            await self._notify(
                "Phase 3 skipped: no fixes selected",
                priority="low",
            )
            self.fix_results = []
            return self.fix_results

        if not SDK_AVAILABLE:
            logger.error( "Claude Agent SDK not available — Phase 3 skipped" )
            self.fix_results = []
            return self.fix_results

        # In dry_run, short-circuit to synthetic success results so Phase 5/6
        # can still walk through the happy path without real SDK calls.
        # Synthesize files from each proposal's `changes` list so Phase 5
        # has something to pretend-commit.
        if self.dry_run:
            from cosa.agents.bug_fix_expediter.state import FixResult
            self.fix_results = []
            self.files_changed_by_cluster = {}
            for proposed in self.selected_fixes:
                self.fix_results.append(
                    FixResult(
                        applied=False, success=True,
                        details="dry_run: skipped actual fix application",
                        retry_eligible=False,
                    )
                )
                # Extract file paths from the proposal's changes list so
                # Phase 5 sees non-empty file lists and walks its happy path.
                synthetic_files = []
                for change in proposed.changes:
                    if isinstance( change, dict ) and change.get( "file" ):
                        synthetic_files.append( change[ "file" ] )
                self.files_changed_by_cluster[ proposed.cluster_id ] = synthetic_files
            await self._notify(
                f"Phase 3 dry_run: {len( self.selected_fixes )} synthetic success result(s)",
                priority="low",
            )
            return self.fix_results

        n = len( self.selected_fixes )
        await self._notify(
            f"Phase 3: applying {n} fix(es) via shared FixExecutor...",
            priority="medium",
        )

        # Lookup tables for cluster + diagnosis
        cluster_by_id = { c.cluster_id: c for c in self.clusters }

        fix_results = []
        files_changed_by_cluster: dict[ str, list[ str ] ] = {}

        for i, proposed in enumerate( self.selected_fixes, start=1 ):
            if self._is_cancelled():
                await self._notify( "Phase 3 cancelled", priority="medium" )
                break

            cluster = cluster_by_id.get( proposed.cluster_id )
            diagnosis = self.diagnoses.get( proposed.cluster_id )
            if cluster is None or diagnosis is None:
                logger.warning(
                    f"[TFE] Missing cluster/diagnosis for proposal {proposed.cluster_id} — skipping"
                )
                continue

            # Option A (2026-04-18): auto-derive Coder turn budget per proposal.
            # _build_tfe_coder_options reads self._current_budget_tier to pick
            # max_turns from config. Pass cluster so derivation can fall back
            # to cluster.affected_files_guess when proposed.changes is empty
            # (2026-04-19 fix — TFE proposals routinely leave changes empty).
            self._current_budget_tier = self._derive_budget_tier( proposed, cluster=cluster )

            await self._notify(
                f"Applying fix {i}/{n} for {proposed.cluster_id}: {proposed.title} "
                f"[budget={self._current_budget_tier}]",
                priority="low",
            )

            # FixContext is a SimpleNamespace pass-through to the FixExecutor
            # prompt builders. The builders only read .cluster_id + .user_email
            # from the fix_context, so a minimal duck-typed object is enough.
            fix_context = SimpleNamespace(
                cluster_id = cluster.cluster_id,
                user_email = self.remediation_context.user_email,
                # Optional enrichment fields the prompts may read in future:
                failure_indices         = cluster.failure_indices,
                shared_error_signature  = cluster.shared_error_signature,
            )

            # Build the executor per-iteration — each fix gets a fresh
            # SafetyGuard + coder/tester client pair inside execute_fix.
            from cosa.agents.test_fix_expediter import cosa_interface, voice_io
            executor = FixExecutor(
                config                = self.config,
                fix_context           = fix_context,
                job_id                = self.job_id,
                prompt_builder_key    = "tfe",
                voice_io_module       = voice_io,
                cosa_interface_module = cosa_interface,
                notify_fn             = self._notify_for_executor,
                is_cancelled_fn       = self._is_cancelled,
                delegate_to_coder_fn  = self._delegate_to_coder,
                verify_fix_fn         = self._verify_fix,
                debug                 = self.debug,
                verbose               = self.verbose,
                worktree_cwd          = self._worktree_cwd,
            )

            try:
                fix_result, files_changed = await executor.execute_fix(
                    diagnosis    = diagnosis,
                    selected_fix = proposed,
                )
            except Exception as e:
                logger.error( f"[TFE] Phase 3 executor raised for {proposed.cluster_id}: {e}" )
                from cosa.agents.bug_fix_expediter.state import FixResult
                fix_result = FixResult(
                    applied=False, success=False,
                    details=f"Executor exception: {e}",
                )
                files_changed = []

            fix_results.append( fix_result )
            files_changed_by_cluster[ proposed.cluster_id ] = files_changed

            if not fix_result.success and not self.config.continue_on_cluster_failure:
                await self._notify(
                    f"Cluster {proposed.cluster_id} failed; aborting remaining clusters "
                    f"(continue_on_cluster_failure=False)",
                    priority="high",
                )
                break

        self.fix_results = fix_results
        self.files_changed_by_cluster = files_changed_by_cluster

        # Summary
        n_success = sum( 1 for r in fix_results if r.success )
        await self._notify(
            f"Phase 3 complete: {n_success}/{len( fix_results )} cluster(s) fixed",
            priority="medium" if n_success == len( fix_results ) else "high",
        )

        return self.fix_results

    async def _notify_for_executor(
        self,
        voice_io_module,
        message: str,
        priority: str = "low",
        abstract: Optional[ str ] = None,
    ) -> None:
        """
        Bridge TFE's `_notify(self, message, priority, abstract)` signature
        to the shared FixExecutor's `notify_fn(voice_io, message, priority, abstract)`
        signature (which mirrors BFE's `_notify(voice_io, ...)`).

        The `voice_io_module` arg is ignored here because TFE's `_notify`
        uses its own cosa_interface directly.
        """
        await self._notify( message, priority=priority, abstract=abstract )

    # ───── Phase 3 SDK helpers (Coder + Tester delegation) ─────

    async def _delegate_to_coder(
        self,
        voice_io_module,
        prompt: str,
        guard,
        cosa_interface_module,
    ) -> tuple:
        """
        Delegate fix application to the Coder agent via Claude Agent SDK.

        Mirrors BFE's _delegate_to_coder but uses TFE's CODER_SYSTEM_PROMPT.
        Tracks files modified via Edit/Write tool-use blocks.

        Returns:
            tuple: (coder_output_text, list_of_files_changed)
        """
        if not SDK_AVAILABLE or not SAFETY_AVAILABLE:
            return ( "", [] )

        options = self._build_tfe_coder_options( guard, cosa_interface_module )

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
                            if block.name in ( "Edit", "Write" ):
                                file_path = block.input.get( "file_path", "" )
                                if file_path and file_path not in files_changed:
                                    files_changed.append( file_path )
                                await post_tool_hook( block.name, block.input, guard )
                            await self._notify(
                                f"Coder: {self._summarize_tool_use( block )}",
                                priority="low",
                            )
                elif isinstance( message, TextBlock ):
                    collected_text.append( message.text )
                elif isinstance( message, ResultMessage ):
                    msg_text = getattr( message, "text", str( message ) )[ :200 ]
                    await self._notify( msg_text, priority="low" )
                elif isinstance( message, RateLimitEvent ):
                    logger.warning(
                        f"Rate limited: retry_after={getattr( message, 'retry_after', '?' )}s"
                    )

            guard.check_iteration()
            coder_output = "".join( collected_text ).strip()

            if self.debug: print(
                f"[TFEOrchestrator] Coder output: {len( coder_output )} chars, "
                f"{len( files_changed )} files changed"
            )

            return ( coder_output, files_changed )

        except SafetyLimitError:
            raise
        except Exception as e:
            logger.error( f"Coder delegation failed: {e}" )
            return ( "", [] )

    async def _verify_fix(
        self,
        voice_io_module,
        selected_fix,
        coder_output: str,
        files_changed: list,
        guard,
        cosa_interface_module,
    ) -> tuple:
        """
        Verify the fix via a Tester agent that runs pytest against the
        cluster's failing tests.

        Mirrors BFE's _verify_fix but uses TFE's TESTER_SYSTEM_PROMPT and
        the test-aware build_verification_prompt (which instructs the Tester
        to use `pytest -k` filtered by cluster test names).

        Returns:
            tuple: (passed: bool, tester_output: str)
        """
        if not SDK_AVAILABLE or not SAFETY_AVAILABLE:
            return ( False, "SDK or safety primitives not available" )

        from cosa.agents.test_fix_expediter.prompts.fix import build_verification_prompt
        prompt = build_verification_prompt( selected_fix, coder_output, files_changed )
        options = self._build_tfe_tester_options( guard, cosa_interface_module )

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
                                f"Tester: {block.name}", priority="low",
                            )
                elif isinstance( message, TextBlock ):
                    collected_text.append( message.text )
                elif isinstance( message, RateLimitEvent ):
                    logger.warning(
                        f"Rate limited: retry_after={getattr( message, 'retry_after', '?' )}s"
                    )

            tester_output = "".join( collected_text ).strip()
            output_lower  = tester_output.lower()

            # Tester self-report
            passed = (
                "pass" in output_lower and "fail" not in output_lower
            ) or "all tests pass" in output_lower

            # Independent pytest validation — OVERRIDES tester self-report when
            # the Tester touched a test file we can re-run independently.
            for tf in test_files:
                if tf.endswith( ".py" ) and "test" in tf.lower():
                    run_result = await run_pytest( tf, timeout_secs=60 )
                    if not run_result.passed:
                        passed = False
                    if self.debug: print(
                        f"[TFEOrchestrator] pytest {tf}: {'PASS' if run_result.passed else 'FAIL'} "
                        f"({run_result.passed_count}/{run_result.total_tests})"
                    )
                    break   # Only validate first test file

            if self.debug: print( f"[TFEOrchestrator] Verification: {'PASS' if passed else 'FAIL'}" )

            return ( passed, tester_output )

        except SafetyLimitError:
            raise
        except Exception as e:
            logger.error( f"Verification failed: {e}" )
            return ( False, f"Verification error: {e}" )

    # ───────────────────────────────────────────────────────────────
    # Worktree isolation (Bug 9, 2026-04-16)
    # ───────────────────────────────────────────────────────────────

    @asynccontextmanager
    async def worktree_scope( self ):
        """
        Enter worktree isolation for Phase 3 + Phase 5 (FixExecutor + GitStrategist).

        Caller pattern (from job.py):
            async with orchestrator.worktree_scope():
                await orchestrator.run_phase3_fix()
                await orchestrator.run_phase5_git()

        When `cosa worktree enabled` is true, a dedicated worktree is created
        under `<sandbox_root>/<job_id>`. `_build_tfe_coder_options`,
        `_build_tfe_tester_options`, and Phase 5 git ops automatically route
        through `self._worktree_cwd`.

        When disabled, the context is a no-op and emits a warning if the
        current working tree has uncommitted changes (safety guard).
        """
        from cosa.agents.shared.worktree_context import WorktreeContext
        async with WorktreeContext( job_id=self.job_id, debug=self.debug ) as wt:
            if wt.enabled:
                self._worktree_cwd = wt.path
                if self.debug: print( f"[TFEOrchestrator] Worktree isolation active: {wt.path}" )
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
        Non-blocking — the user opted into that mode.
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
                    "[TFEOrchestrator] ⚠️  Worktree isolation is DISABLED and "
                    "the current working tree has uncommitted changes. TFE "
                    "Phase 3/5 will mutate this tree and may contaminate your "
                    "PR. Consider `cosa worktree enabled=true` or committing/stashing."
                )
        except Exception as e:
            if self.debug: print( f"[TFEOrchestrator] uncommitted-changes check failed: {e}" )

    def render_worktree_artifacts_abstract( self, job_id: str ) -> list:
        """
        Render the 'Worktree Artifacts' section of the TFE completion abstract.

        Pure helper (no side effects) — exposed as a method so unit tests can
        stage orchestrator state directly and assert the output. Returns an
        empty list when there are no selected fixes (nothing to report).

        Fields read (all may be missing on early/partial runs):
            - self.selected_fixes : list of TFEProposedFix with cluster_id
            - self.fix_results : list of FixResult parallel to selected_fixes
            - self.files_changed_by_cluster : dict[cluster_id → list[str]]
            - self.branch_name, self.commit_hashes, self.pr_url : Phase 5 outputs
        """
        if not self.selected_fixes:
            return []
        lines = [ "", "**Worktree Artifacts**" ]
        worktree_path = f"{cu.get_project_root()}/.claude/worktrees/{job_id}"
        lines.append( f"**Path**: `{worktree_path}`" )

        results   = self.fix_results or []
        files_map = self.files_changed_by_cluster or {}
        for proposed, result in zip( self.selected_fixes, results ):
            cid    = proposed.cluster_id
            mark   = "✓" if result.success else "✗"
            nfiles = len( files_map.get( cid, [] ) )
            files_suffix = f" · files={nfiles}" if nfiles else ""
            lines.append( f"- **{cid}** {mark} {proposed.title[ :80 ]}{files_suffix}" )

        branch = getattr( self, "branch_name", None )
        hashes = getattr( self, "commit_hashes", [] ) or []
        pr_url = getattr( self, "pr_url", None )
        if branch or hashes or pr_url:
            lines.append( "" )
            if branch:
                lines.append( f"**Branch**: `{branch}`" )
            if hashes:
                lines.append( f"**Commits**: {len( hashes )}" )
                for h in hashes[ :10 ]:
                    lines.append( f"- `{h[ :8 ]}`" )
            if pr_url:
                lines.append( f"**PR**: {pr_url}" )

        lines.append( "" )
        lines.append( "**Inspect**:" )
        lines.append( f"- `git -C {worktree_path} log --oneline`" )
        lines.append( f"- `git -C {worktree_path} diff --stat origin/main`" )
        return lines

    @staticmethod
    def _summarize_tool_use( block ) -> str:
        """
        Compact single-line summary of a ToolUseBlock for progress notifications.

        Replaces the old bare `Coder: {block.name}` breadcrumbs (which produced
        long runs of identical-looking 'Coder: Bash' entries with no context)
        with a tool-specific digest that surfaces the key argument. Truncated
        to 100 chars to keep notification text tight.

        Filed 2026-04-18 (Session be57a252) after operator noted the prior
        format was "almost meaningless without more context."
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

    @staticmethod
    def _derive_budget_tier( proposed, cluster=None ) -> str:
        """
        Auto-derive Coder turn-budget tier (Option A, 2026-04-18).

        Tiers:
            - small  : single-file test_patch or config_change — trivial flips
            - large  : 4+ affected files — visual baselines, broad refactors
            - medium : everything else — single-file code_patch, 2-3 file anythings, retries

        File-count source (2026-04-19 fix after tfe-a1c6e15a post-game):
            1. `proposed.changes` list length (preferred — what the proposer explicitly enumerated)
            2. `cluster.affected_files_guess` length (fallback — TFE proposals often
               leave `changes` empty, so every proposal would otherwise fall to `medium`)
            3. 0 if neither source populated

        Defensive fallback: if no file info is discoverable, returns "medium".
        """
        n_files = len( proposed.changes ) if proposed.changes else 0
        if n_files == 0 and cluster is not None:
            n_files = len( getattr( cluster, "affected_files_guess", [] ) or [] )
        ft = proposed.fix_type
        if n_files == 1 and ft in ( "test_patch", "config_change" ):
            return "small"
        if n_files >= 4:
            return "large"
        return "medium"

    def _build_tfe_coder_options( self, guard, cosa_interface_module ):
        """Build ClaudeAgentOptions for the TFE Coder agent."""
        budget_by_tier = {
            "small"  : self.config.coder_budget_small_turns,
            "medium" : self.config.coder_budget_medium_turns,
            "large"  : self.config.coder_budget_large_turns,
        }
        max_turns = budget_by_tier.get(
            self._current_budget_tier, self.config.coder_budget_medium_turns
        )
        return ClaudeAgentOptions(
            model           = self.config.worker_model,
            system_prompt   = TFE_CODER_SYSTEM_PROMPT,
            tools           = [ "Read", "Edit", "Bash" ],
            cwd             = self._worktree_cwd or cu.get_project_root(),
            permission_mode = "acceptEdits",
            can_use_tool    = build_can_use_tool( cosa_interface_module, guard, "tfe-coder" ),
            max_turns       = max_turns,
            max_budget_usd  = self.config.budget_usd,
            effort          = self.config.thinking_effort,
        )

    def _build_tfe_tester_options( self, guard, cosa_interface_module ):
        """Build ClaudeAgentOptions for the TFE Tester agent."""
        return ClaudeAgentOptions(
            model           = self.config.worker_model,
            system_prompt   = TFE_TESTER_SYSTEM_PROMPT,
            tools           = [ "Read", "Edit", "Bash" ],
            cwd             = self._worktree_cwd or cu.get_project_root(),
            permission_mode = "acceptEdits",
            can_use_tool    = build_can_use_tool( cosa_interface_module, guard, "tfe-tester" ),
            max_turns       = 10,
            max_budget_usd  = self.config.budget_usd,
            effort          = self.config.thinking_effort,
        )

    # ───────────────────────────────────────────────────────────────
    # Phase 5: Git (step 11) — delegates to shared GitStrategist.commit_and_pr_multi
    # ───────────────────────────────────────────────────────────────

    async def run_phase5_git( self ) -> dict:
        """
        Run multi-cluster git strategy via the shared GitStrategist.

        For each successful Phase 3 fix:
          - Look up the files changed for that cluster
          - Build a commit message keyed on `fix(tfe): {cluster_id} {title}`
          - Pass the whole batch to `GitStrategist.commit_and_pr_multi()` as
            a list of (cluster_id, title, files, commit_message) tuples

        Trust-level → git strategy mapping is resolved via the shared
        `GitStrategist.resolve_trust_level(proxy)` helper. TFE doesn't have
        its own trust proxy yet (Phase 5 of the design uses `inherit` mode),
        so we pass `None` and rely on the L1 fallback for first runs. Future
        iterations can pass a SWE trust proxy.

        Dry-run mode: skips real git operations and returns a synthetic result.

        Requires:
            - self.fix_results is populated (Phase 3 ran)
            - self.files_changed_by_cluster is populated

        Ensures:
            - Returns dict: {git_strategy, branch_name, commit_hashes, pr_url, error}
            - Populates self.branch_name, self.commit_hashes, self.pr_url
            - Never raises
        """
        from cosa.agents.shared.git_strategist import GitStrategist

        self.current_phase = TFEPhase.COMMITTING

        # Guard: need successful fixes with files to commit
        successful_pairs = []
        for i, (proposed, fix_result) in enumerate(
            zip( self.selected_fixes, self.fix_results )
        ):
            if not fix_result.success:
                continue
            files = self.files_changed_by_cluster.get( proposed.cluster_id, [] )
            if not files:
                continue
            successful_pairs.append( ( proposed, fix_result, files ) )

        if not successful_pairs:
            await self._notify(
                "Phase 5 skipped: no successful fixes with file changes",
                priority="low",
            )
            return { "git_strategy": None, "branch_name": None, "commit_hashes": [], "pr_url": None, "error": None }

        if self.dry_run:
            await self._notify(
                f"Phase 5 dry_run: would commit {len( successful_pairs )} cluster(s) via shared GitStrategist",
                priority="low",
            )
            synthetic = {
                "git_strategy"  : "dry_run",
                "branch_name"   : f"fix/dry-run-{len( successful_pairs )}-clusters",
                "commit_hashes" : [ f"drycommit{i}" for i in range( len( successful_pairs ) ) ],
                "pr_url"        : None,
                "error"         : None,
            }
            self.branch_name   = synthetic[ "branch_name" ]
            self.commit_hashes = synthetic[ "commit_hashes" ]
            self.pr_url        = synthetic[ "pr_url" ]
            return synthetic

        await self._notify(
            f"Phase 5: committing {len( successful_pairs )} cluster(s) via shared GitStrategist...",
            priority="medium",
        )

        # Build the clusters list for commit_and_pr_multi
        cluster_commits = []
        for proposed, _fix_result, files in successful_pairs:
            commit_message = self._build_tfe_commit_message( proposed )
            cluster_commits.append( (
                proposed.cluster_id,
                proposed.title,
                files,
                commit_message,
            ) )

        # Build PR title + body
        suite_abbrev = self._suite_abbrev( self.remediation_context.suites_run )
        pr_title = (
            f"TFE fix: {len( successful_pairs )} cluster(s) from {suite_abbrev} test run"
        )
        pr_body  = self._build_tfe_pr_body( successful_pairs, suite_abbrev )
        branch_slug_hint = f"tfe-{suite_abbrev}-{len( successful_pairs )}-clusters"

        try:
            # GitOps import is lazy so unit tests that never reach Phase 5 in
            # non-dry-run mode don't need a git working tree.
            from cosa.agents.bug_fix_expediter.git_ops import GitOps
        except ImportError as e:
            await self._notify(
                f"Phase 5 failed: GitOps unavailable ({e})",
                priority="high",
            )
            return { "git_strategy": None, "branch_name": None, "commit_hashes": [], "pr_url": None, "error": str( e ) }

        # Bug 9 (2026-04-16): route through worktree when isolation active.
        git_ops    = GitOps( cwd=( self._worktree_cwd or cu.get_project_root() ), debug=self.debug )
        strategist = GitStrategist( debug=self.debug, verbose=self.verbose )

        # TFE doesn't wire a trust proxy yet; rely on L1 fallback unless the
        # config forces a level via trust_mode.
        trust_level = self._resolve_tfe_trust_level()

        async def _notify_fn( msg, priority="low" ):
            await self._notify( msg, priority=priority )

        git_result = await strategist.commit_and_pr_multi(
            git_ops          = git_ops,
            clusters         = cluster_commits,
            trust_level      = trust_level,
            notify_fn        = _notify_fn,
            pr_title         = pr_title,
            pr_body          = pr_body,
            branch_slug_hint = branch_slug_hint,
        )

        self.branch_name   = git_result.get( "branch_name" )
        self.commit_hashes = git_result.get( "commit_hashes", [] )
        self.pr_url        = git_result.get( "pr_url" )

        # Summary notification
        if git_result.get( "error" ):
            await self._notify(
                f"Phase 5 finished with error: {git_result[ 'error' ]}",
                priority="high",
                abstract=self._render_git_summary( git_result ),
            )
        else:
            await self._notify(
                f"Phase 5 complete: {git_result.get( 'git_strategy', 'unknown' )}",
                priority="medium",
                abstract=self._render_git_summary( git_result ),
            )

        return git_result

    @staticmethod
    def _suite_abbrev( suites_run: list ) -> str:
        """Return a short branch-slug component for the suites that ran."""
        if not suites_run:
            return "none"
        if len( suites_run ) == 1:
            return suites_run[ 0 ]
        return "mixed"

    @staticmethod
    def _build_tfe_commit_message( proposed: TFEProposedFix ) -> str:
        """Build a conventional-commit-style commit message for a TFE fix."""
        title = proposed.title[ :60 ]
        body_lines = [
            f"fix(tfe): {proposed.cluster_id} {title}",
            "",
            f"Root cause category: {getattr( proposed, 'fix_type', 'code_patch' )}",
            f"Confidence: {proposed.confidence:.0%}",
            f"Risk: {getattr( proposed, 'risk_level', 'low' )}",
        ]
        if proposed.description:
            body_lines.append( "" )
            body_lines.append( proposed.description[ :500 ] )
        return "\n".join( body_lines )

    def _build_tfe_pr_body( self, successful_pairs: list, suite_abbrev: str ) -> str:
        """Build the markdown PR body for a multi-cluster TFE fix."""
        lines = []
        lines.append( "## Summary" )
        lines.append( "" )
        lines.append(
            f"TestSuite job `{self.remediation_context.source_test_suite_job_id}` "
            f"reported failures. TFE clustered them and applied targeted fixes."
        )
        lines.append( "" )

        lines.append( f"## Clusters fixed ({len( successful_pairs )})" )
        lines.append( "" )
        lines.append( "| Cluster | Title | Fix type | Confidence | Files |" )
        lines.append( "|---------|-------|----------|------------|-------|" )
        for proposed, _fix_result, files in successful_pairs:
            lines.append(
                f"| {proposed.cluster_id} | {proposed.title[ :60 ]} "
                f"| {proposed.fix_type} | {proposed.confidence:.0%} | {len( files )} |"
            )
        lines.append( "" )

        lines.append( "## Test plan" )
        lines.append( "" )
        lines.append(
            f"- [ ] TFE Phase 6 rerun (`test_types={self.remediation_context.original_test_types}`) passes"
        )
        lines.append( "- [ ] Manual review of cluster fixes for correctness" )
        lines.append( "" )

        lines.append( "## Source references" )
        lines.append( "" )
        lines.append( f"- Source TestSuiteJob: `{self.remediation_context.source_test_suite_job_id}`" )
        lines.append( f"- TFE job: `{self.job_id}`" )
        lines.append( f"- Suite(s): {', '.join( self.remediation_context.suites_run )}" )
        lines.append( "" )
        lines.append( "🤖 Generated with [TestFixExpediter]" )

        return "\n".join( lines )

    def _resolve_tfe_trust_level( self ) -> int:
        """
        Resolve trust level for TFE Phase 5.

        Reads `self.config.trust_mode`:
          - "inherit" → L1 (conservative default — TFE doesn't wire a proxy yet)
          - "fixed_l1" → 1
          - "fixed_l3" → 3
          - "shadow"  → 1 (passive mode — compute but don't escalate)
          - anything else → 1 (safe fallback)
        """
        mode = self.config.trust_mode
        if mode == "fixed_l3":
            return 3
        if mode == "fixed_l1":
            return 1
        if mode == "shadow":
            return 1
        # "inherit" or unknown
        return 1

    @staticmethod
    def _render_git_summary( git_result: dict ) -> str:
        """Render a markdown summary of a git_result dict for voice abstracts."""
        lines = []
        strategy = git_result.get( "git_strategy" ) or "(none)"
        lines.append( f"**Strategy**: {strategy}" )
        if git_result.get( "branch_name" ):
            lines.append( f"**Branch**: `{git_result[ 'branch_name' ]}`" )
        hashes = git_result.get( "commit_hashes", [] )
        if hashes:
            lines.append( f"**Commits ({len( hashes )})**:" )
            for h in hashes[ :10 ]:
                lines.append( f"- `{h[ :8 ]}`" )
        if git_result.get( "pr_url" ):
            lines.append( f"**PR**: {git_result[ 'pr_url' ]}" )
        if git_result.get( "error" ):
            lines.append( f"**Error**: {git_result[ 'error' ]}" )
        return "\n".join( lines )

    # ───────────────────────────────────────────────────────────────
    # Phase 6: Rerun validation (step 12)
    # ───────────────────────────────────────────────────────────────

    async def run_phase6_validation( self ) -> Optional[ str ]:
        """
        Queue a validation TestSuiteJob targeting the affected suites.

        Per plan doc 08-phase6-rerun-validation-plan.md:
          - Guard: only if at least one Phase 3 fix succeeded
          - Recursion guard: set metadata["triggered_by_tfe"] = self.job_id
          - Rerun scope: `affected` (default — only original suites) or `full`
          - Does NOT wait on the validation run — it's a peer job
          - Populates self.artifacts-equivalent via `self.validation_run_job_id`

        In dry_run, emits a breadcrumb and sets validation_run_job_id to a
        synthetic placeholder.

        Requires:
            - self.fix_results is populated (Phase 3 ran)

        Ensures:
            - Returns the validation TestSuiteJob ID if queued, else None
            - Never raises
        """
        self.current_phase = TFEPhase.RESUBMITTING

        # Guard: need at least one successful fix
        successful = [ r for r in self.fix_results if r.success ]
        if not successful:
            await self._notify(
                "Phase 6 skipped: no successful fixes to validate",
                priority="low",
            )
            self.validation_run_job_id = None
            return None

        # Dry-run short-circuit
        if self.dry_run:
            self.validation_run_job_id = "dry-run-skipped"
            await self._notify(
                f"[DRY RUN] Would queue validation TestSuiteJob with "
                f"test_types={self._resolve_rerun_test_types()}",
                priority="low",
            )
            return self.validation_run_job_id

        # Determine rerun scope
        test_types = self._resolve_rerun_test_types()

        args_dict = {
            "test_types" : ",".join( test_types ),
        }
        if self.remediation_context.original_pytest_args:
            args_dict[ "pytest_args" ] = " ".join(
                self.remediation_context.original_pytest_args
            )

        # Construct the validation job via the factory
        try:
            from cosa.rest.agentic_job_factory import create_agentic_job
        except ImportError as e:
            await self._notify(
                f"Phase 6 failed: agentic_job_factory import error ({e})",
                priority="high",
            )
            self.validation_run_job_id = None
            return None

        try:
            validation_job = create_agentic_job(
                command    = "agent router go to test suite",
                args_dict  = args_dict,
                user_id    = self.remediation_context.user_id,
                user_email = self.remediation_context.user_email,
                session_id = self.remediation_context.session_id,
                debug      = self.debug,
                verbose    = self.verbose,
            )
        except Exception as e:
            logger.error( f"[TFE] Phase 6 factory error: {e}" )
            await self._notify(
                f"Phase 6 failed: could not create validation job ({e})",
                priority="high",
            )
            self.validation_run_job_id = None
            return None

        if validation_job is None:
            await self._notify(
                "Phase 6 failed: factory returned None for validation job",
                priority="high",
            )
            self.validation_run_job_id = None
            return None

        # Recursion guard — mark the validation job as TFE-triggered so the
        # TestSuiteCompletionWatchdog refuses to re-trigger TFE on its completion.
        if not hasattr( validation_job, "metadata" ) or validation_job.metadata is None:
            validation_job.metadata = {}
        validation_job.metadata[ "triggered_by_tfe" ] = self.job_id
        validation_job.metadata[ "tfe_source_test_suite_job_id" ] = (
            self.remediation_context.source_test_suite_job_id
        )
        validation_job.metadata[ "tfe_fix_count" ] = len( successful )

        # Push to the todo queue (same pattern as BFE Phase 6 _resubmit_original_job)
        try:
            import fastapi_app.main as main_module
            todo_queue = main_module.jobs_todo_queue
            if todo_queue is None:
                raise RuntimeError( "jobs_todo_queue is None — app not initialized" )
            todo_queue.push( validation_job )
        except Exception as e:
            logger.error( f"[TFE] Phase 6 queue push error: {e}" )
            await self._notify(
                f"Phase 6 failed: could not push validation job to queue ({e})",
                priority="high",
            )
            self.validation_run_job_id = None
            return None

        self.validation_run_job_id = validation_job.id_hash

        await self._notify(
            f"Phase 6: validation TestSuiteJob {validation_job.id_hash} queued "
            f"(test_types={test_types})",
            priority="medium",
            abstract=self._render_validation_abstract( validation_job, test_types, len( successful ) ),
        )

        return self.validation_run_job_id

    def _resolve_rerun_test_types( self ) -> list:
        """
        Resolve the test_types to rerun based on `rerun_scope` config.

        Returns:
            list[str]: The test suite names to rerun
        """
        scope = self.config.rerun_scope
        if scope == "full":
            return [ "all" ]
        # "affected" (default) or anything unrecognized → original suites
        return list( self.remediation_context.original_test_types )

    def _render_validation_abstract(
        self,
        validation_job,
        test_types: list,
        fix_count: int,
    ) -> str:
        """Render a markdown abstract for the validation dispatch notification."""
        lines = [ "**Validation run scheduled**", "" ]
        lines.append( f"- Job ID: `{validation_job.id_hash}`" )
        lines.append( f"- Test types: {test_types}" )
        lines.append( f"- Source TFE: `{self.job_id}`" )
        lines.append( f"- Source TestSuiteJob: `{self.remediation_context.source_test_suite_job_id}`" )
        lines.append( f"- Successful fixes applied: {fix_count}" )
        lines.append( "" )
        lines.append( "TFE does not wait on the rerun; it's queued as a peer job." )
        return "\n".join( lines )


def quick_smoke_test():
    """Quick smoke test for TFEOrchestrator Phase 0 + Phase 1 wiring."""
    from cosa.agents.test_fix_expediter.state import TestRemediationContext

    cu.print_banner( "TFE Orchestrator Smoke Test", prepend_nl=True )

    try:
        # 1: Instantiation
        ctx = TestRemediationContext(
            source_test_suite_job_id = "ts-test",
            snapshot_path            = "p",
            snapshot                 = { "schema_version": "1.0" },
            suites_run               = [ "unit" ],
            summary                  = { "all_passed": False },
            failures                 = [
                {
                    "classname": "src.tests.unit.test_auth.TestLogin",
                    "name": "test_ok", "type": "FAILED",
                    "message": "assert 401 == 200",
                    "traceback": 'File "src/cosa/auth/tokens.py", line 42, in refresh',
                }
            ],
            original_test_types      = [ "unit" ],
            user_id                  = "u1",
            user_email               = "t@t.com",
            session_id               = "s1",
        )
        config = TestFixExpediterConfig( max_diagnosis_iterations=1 )

        orch = TFEOrchestrator(
            remediation_context = ctx,
            config              = config,
            user_id             = "u1",
            user_email          = "t@t.com",
            session_id          = "s1",
            job_id              = "tfe-smoke",
            dry_run             = True,
            debug               = False,
        )
        assert orch.current_phase == TFEPhase.LOADING
        print( "✓ TFEOrchestrator instantiation" )

        # 2: Phase 0 produces real clusters
        import asyncio
        clusters = asyncio.run( orch.run_phase0_cluster() )
        assert len( clusters ) == 1
        assert clusters[ 0 ].cluster_id == "C1"
        assert orch.current_phase == TFEPhase.CLUSTERING
        print( f"✓ Phase 0 real clustering: {len( clusters )} cluster(s)" )

        # 3: Parser + fallback
        parsed = orch._parse_diagnosis_result(
            raw_response='''Here's my diagnosis:
```json
{"cluster_id": "C1", "root_cause": "Token refresh bug", "error_category": "code_bug",
 "confidence": 0.8, "evidence": ["tokens.py:42"], "affected_components": ["src/cosa/auth/tokens.py"],
 "test_symptoms": ["assert 401 == 200"]}
```
That's it.''',
            cluster_id="C1",
        )
        assert parsed.cluster_id == "C1"
        assert parsed.error_category == "code_bug"
        assert parsed.confidence == 0.8
        print( "✓ JSON parser extracts from markdown-wrapped prose" )

        # 4: Fallback on invalid JSON
        fallback = orch._parse_diagnosis_result( "no json here", "C2" )
        assert fallback.cluster_id == "C2"
        assert fallback.confidence == 0.1
        assert fallback.error_category == "unknown"
        print( "✓ Fallback on invalid JSON" )

        # 5: _fallback_diagnosis direct
        direct_fallback = TFEOrchestrator._fallback_diagnosis( "C3", "reason" )
        assert direct_fallback.cluster_id == "C3"
        assert direct_fallback.confidence == 0.1
        print( "✓ _fallback_diagnosis direct" )

        # 6: Cancel during phase
        orch.request_stop()
        assert orch._is_cancelled() is True
        print( "✓ Cancellation flag" )

        # 7: Phase 2-6 stubs still callable
        orch._stop_requested = False
        asyncio.run( orch.run_phase2_propose() )
        asyncio.run( orch.run_phase3_fix() )
        asyncio.run( orch.run_phase5_git() )
        asyncio.run( orch.run_phase6_validation() )
        assert orch.current_phase == TFEPhase.RESUBMITTING
        print( "✓ Phase 2-6 stubs callable" )

        print( "\n✓ TFE Orchestrator smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
