#!/usr/bin/env python3
"""
Core Orchestrator for COSA SWE Team Agent.

Phase 2: Lead + Coder delegation loop with real Claude Agent SDK.
Lead decomposes tasks into TaskSpec[], delegates each to a Coder
subagent via ClaudeSDKClient, and collects DelegationResults.

Supports dry-run mode via MockAgentSDKSession (Phase 1 preserved).
"""

import asyncio
import json
import logging
import os
import queue
import threading
import time
import uuid
from typing import Optional

import cosa.utils.util as cu

from .config import SweTeamConfig
from .state import (
    OrchestratorState,
    SweTeamState,
    TaskSpec,
    DelegationResult,
    VerificationResult,
    create_initial_state,
)
from .safety_limits import SafetyGuard, SafetyLimitError
from .agent_definitions import (
    get_agent_roles,
    get_active_roles,
    get_model_for_role,
    get_sender_id,
    LEAD_SYSTEM_PROMPT,
    CODER_SYSTEM_PROMPT,
    TESTER_SYSTEM_PROMPT,
)
from .test_runner import run_pytest, TestRunResult
from .mock_clients import MockAgentSDKSession
from .hooks import build_can_use_tool, post_tool_hook, notification_hook, wrap_prompt_for_streaming
from .state_files import FeatureList, ProgressLog

# Transport budget for out-of-process HTTP calls to `:7999` (row 204911ca).
# ~30s = 1.60x the observed maximum reload window of 18.76s — a multiplier with
# explicit headroom, NOT a coverage guarantee. `:7999` runs `uvicorn --reload`
# and the reloader parent holds the listening socket across a restart, so the
# kernel ACCEPTS a request nothing is there to answer and the caller hangs
# instead of getting a fast ConnectionRefused. The prior 5s failed every reload
# it landed in (measured n=143: min 6.59s, median 6.91s, max 18.76s).
#
# 🔴 WHY THIS MODULE IS EXPOSED — an earlier pass excluded it, twice. Reached
# via `agentic_job_factory.py:135` -> `SweTeamJob` it runs in the CJ Flow
# agentic pool INSIDE `:7999`, where a reload tears the caller down alongside
# the callee and a bigger budget buys nothing. That exclusion was verified by
# asking which OTHER package imports this module — the one question that cannot
# see this package's own entry point. `swe_team/__main__.py` imports
# SweTeamOrchestrator directly and runs it under `python -m cosa.agents.swe_team`,
# in a SEPARATE OS process. Exposure is a property of the INVOCATION, not of the
# call site; any package with a `__main__.py` is dual-mode by construction and
# must be classified per entry point.
#
# Full derivation: src/rnd/v0.1.9/2026.07.19-dev-server-reload-availability.md §9(a).
#
# 🔴 DRIFT CONTROL — TWO SEARCHES, AND IT TOOK BOTH.
# `grep -rn _SERVER_TRANSPORT_TIMEOUT_SECONDS` returns every DIRECT call site.
# It does NOT return members whose budget is carried in a Pydantic FIELD rather
# than passed at the call — `AsyncNotificationRequest( timeout=… )`, consumed at
# `notify_user_async.py:197-201` as a bare `requests.post( timeout=request.timeout )`.
# Two such members were missed on the first pass for exactly this reason.
# The second search is: `grep -rn "AsyncNotificationRequest(" -A14 | grep timeout`.
# Run BOTH, or the set you get back is the set the first grep can see.
#
# TRADE: a hung server now stalls these best-effort notifications ~30s instead
# of ~5s. All three sites are already wrapped in broad excepts and are non-fatal,
# so the cost lands as latency, never as a failed run. Not free.
_SERVER_TRANSPORT_TIMEOUT_SECONDS = 30


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
except ImportError:  # pragma: no cover - optional-dep import guard; claude_agent_sdk is installed in this env, so the False fallback never runs
    SDK_AVAILABLE = False

logger = logging.getLogger( __name__ )

MAX_VERIFICATION_ITERATIONS = 3


class SweTeamOrchestrator:
    """
    Orchestrator for the SWE Team multi-agent engineering system.

    Phase 3 implementation:
    - Lead decomposes task into TaskSpec[] via SDK
    - Coder executes each TaskSpec via SDK delegation
    - Tester verifies coder output with tests (coder-tester loop)
    - Safety guard enforced at every delegation step
    - Dry-run mode preserved from Phase 1

    Future phases will add:
    - Phase 5: Reviewer, Debugger, full CJ Flow

    Requires:
        - task_description is a non-empty string
        - config is a valid SweTeamConfig

    Ensures:
        - run() executes the task within safety limits
        - Notifications flow through cosa_interface
        - Dry-run mode simulates without API calls
        - Live mode decomposes, delegates, and verifies via SDK
    """

    def __init__(
        self,
        task_description  : str,
        config            : SweTeamConfig = None,
        session_id        : str = None,
        job_id            : str = None,
        on_state_change   = None,
        debug             : bool = False,
        verbose           : bool = False,
    ):
        self.task_description  = task_description
        self.config            = config or SweTeamConfig()
        self.session_id        = session_id or f"st-{uuid.uuid4().hex[ :8 ]}"
        self.job_id            = job_id
        self._on_state_change  = on_state_change
        self.debug             = debug
        self.verbose           = verbose

        # State
        self.state          = create_initial_state( task_description )
        self.current_state  = OrchestratorState.INITIALIZING
        self._stop_requested = False

        # User message queue (Phase: Approach D - user-initiated communication)
        self._user_messages    = queue.Queue()
        self._urgent_interrupt = threading.Event()

        # Safety
        self.guard = SafetyGuard(
            max_iterations = self.config.max_iterations_per_task,
            max_failures   = self.config.max_consecutive_failures,
            timeout_secs   = self.config.wall_clock_timeout_secs,
        )

        # Proxy notification state (Phase 7)
        self._proxy_pending_count = 0
        self._user_email          = None    # Set from job context when available

        # Decision proxy (Phase 4 + Phase 5 INI integration)
        self.proxy = None
        if self.config.trust_mode != "disabled":
            try:
                from .proxy import EngineeringStrategy
                from cosa.agents.decision_proxy.trust_tracker import TrustTracker
                from cosa.agents.decision_proxy.circuit_breaker import CircuitBreaker

                # Read INI config via factory functions (non-fatal fallback to defaults)
                proxy_cfg = {}
                swe_cfg   = {}
                try:
                    from cosa.config.configuration_manager import ConfigurationManager
                    from cosa.agents.decision_proxy.config import trust_proxy_config_from_config_mgr
                    from cosa.agents.swe_team.proxy.config import swe_proxy_config_from_config_mgr

                    cfg_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
                    proxy_cfg = trust_proxy_config_from_config_mgr( cfg_mgr )
                    swe_cfg   = swe_proxy_config_from_config_mgr( cfg_mgr )
                except Exception as e:
                    logger.warning( f"INI config read failed, using defaults: {e}" )

                # Build TrustTracker with INI values
                trust_tracker = TrustTracker(
                    rolling_window_days  = proxy_cfg.get( "rolling_window_days", 30 ),
                    decay_half_life_days = proxy_cfg.get( "decay_half_life_days", 14 ),
                    l2_threshold         = proxy_cfg.get( "l2_threshold", 50 ),
                    l3_threshold         = proxy_cfg.get( "l3_threshold", 200 ),
                    l4_threshold         = proxy_cfg.get( "l4_threshold", 500 ),
                    l5_threshold         = proxy_cfg.get( "l5_threshold", 1000 ),
                    debug                = self.debug,
                )

                # Build CircuitBreaker with INI values
                circuit_breaker = CircuitBreaker(
                    trust_tracker                 = trust_tracker,
                    error_rate_threshold          = proxy_cfg.get( "cb_error_rate_threshold", 0.15 ),
                    confidence_collapse_threshold = proxy_cfg.get( "cb_confidence_collapse_threshold", 0.3 ),
                    auto_demotion_levels          = proxy_cfg.get( "cb_auto_demotion_levels", 2 ),
                    recovery_cooldown_seconds     = proxy_cfg.get( "cb_recovery_cooldown_seconds", 3600 ),
                    on_trip_callback              = self._on_circuit_breaker_trip,
                    debug                         = self.debug,
                )

                self.proxy = EngineeringStrategy(
                    trust_tracker    = trust_tracker,
                    circuit_breaker  = circuit_breaker,
                    accepted_senders = swe_cfg.get( "accepted_senders" ),
                    trust_mode       = self.config.trust_mode,
                    debug            = self.debug,
                )
            except ImportError:
                logger.warning( "Decision proxy requested but proxy module unavailable" )

        # Metrics
        self.start_time   = None
        self.end_time     = None
        self.tokens_used  = 0

    async def _notify( self, team_io, message, role="lead", priority="medium", abstract=None, progress_group_id=None ):
        """
        Send a notification with automatic job_id/queue_name passthrough.

        Requires:
            - team_io is the cosa_interface module
            - message is a non-empty string

        Ensures:
            - Passes job_id and queue_name when orchestrator has a job_id
            - Omits job_id/queue_name in standalone CLI mode (job_id=None)
            - Passes progress_group_id for in-place DOM updates when provided
        """
        await team_io.notify_progress(
            message           = message,
            role              = role,
            priority          = priority,
            abstract          = abstract,
            job_id            = self.job_id,
            queue_name        = "run" if self.job_id else None,
            progress_group_id = progress_group_id,
        )

    async def _emit_state( self, from_state, to_state, metadata=None ):
        """
        Emit a state transition event via the on_state_change callback.

        Requires:
            - from_state and to_state are OrchestratorState values

        Ensures:
            - Calls on_state_change callback if provided
            - Never raises — logs warning on failure
        """
        if self._on_state_change:
            try:
                await self._on_state_change( from_state, to_state, metadata )
            except Exception as e:
                logger.warning( f"on_state_change callback failed: {e}" )

    async def _gated_confirmation( self, question, role, default, timeout, abstract, team_io ):
        """
        Route confirmation through decision proxy with trust feedback recording.

        Always evaluates the proxy (shadow, suggest, active modes) to build
        trust data. In active mode, may auto-approve. In suggest mode, appends
        suggestions. In shadow mode, observes only. After user answers, records
        agreement/disagreement in trust tracker.

        Requires:
            - question is a non-empty string
            - team_io is the cosa_interface module

        Ensures:
            - Returns bool (True if approved, False otherwise)
            - Proxy evaluate() called for all non-disabled modes
            - Trust feedback recorded after every user decision
            - Falls through to ask_confirmation when proxy is None

        Args:
            question: The yes/no question to ask
            role: Agent role asking the question
            default: Default answer if timeout ("yes" or "no")
            timeout: Seconds to wait for response
            abstract: Optional supplementary context
            team_io: cosa_interface module

        Returns:
            bool: True if approved, False otherwise
        """
        proxy_result = None

        # Step 1: Always evaluate if proxy exists (shadow, suggest, active all classify)
        if self.proxy:
            try:
                proxy_result = self.proxy.evaluate( question, get_sender_id( role, self.session_id ) )
            except Exception as e:
                logger.warning( f"Decision proxy evaluation failed: {e}" )

        # Step 2: Act autonomously in active mode at sufficient trust
        if proxy_result and self.proxy.trust_mode not in ( "shadow", "disabled" ):

            if proxy_result.action == "act":
                await self._notify( team_io,
                    message  = f"[Auto-approved by proxy] {question[ :80 ]}",
                    role     = role,
                    priority = "low",
                )
                self.proxy.trust_tracker.record_decision( proxy_result.category, success=True )
                return proxy_result.value == "approved"

            if proxy_result.action == "suggest" and proxy_result.value:
                suggestion_note = f"\n\n**Proxy suggestion**: {proxy_result.value} (confidence: {proxy_result.confidence:.0%})"
                abstract = ( abstract or "" ) + suggestion_note

        # Step 3: Fall through to user confirmation
        user_answer = await team_io.ask_confirmation( question, role, default, timeout, abstract )

        # Step 4: Record trust feedback (shadow observes, suggest tracks follow-through)
        if proxy_result and self.proxy:
            try:
                proxy_would_approve = ( proxy_result.value == "approved" )
                agreement           = ( proxy_would_approve == user_answer )
                self.proxy.trust_tracker.record_decision( proxy_result.category, success=agreement )
                if self.debug:
                    print( f"[Proxy Feedback] mode={self.proxy.trust_mode}, cat={proxy_result.category}, proxy={'approve' if proxy_would_approve else 'review'}, user={'yes' if user_answer else 'no'}, agree={agreement}" )

                # Persist trust state to DB (non-fatal)
                self._persist_trust_feedback( proxy_result.category, agreement )

                # Phase 7: Emit proxy summary notification for pending ratification decisions
                # "suggest" and "defer" actions produce pending ratification decisions;
                # "shadow" (not_required) and "act" (auto-approved) do NOT.
                if proxy_result.action in ( "suggest", "defer" ):
                    self._proxy_pending_count += 1
                    self._emit_proxy_summary_notification(
                        category    = proxy_result.category,
                        action      = proxy_result.action,
                        trust_level = proxy_result.trust_level,
                        confidence  = proxy_result.confidence,
                        question    = question,
                        team_io     = team_io,
                    )

            except Exception as e:
                logger.warning( f"Trust feedback recording failed: {e}" )

        return user_answer

    def _persist_trust_feedback( self, category, approved ):
        """
        Persist trust feedback to the database (non-fatal best-effort).

        In-memory TrustTracker is source of truth. DB is the persistence
        layer for cross-session trust survival.

        Requires:
            - category is a string (decision category)
            - approved is a bool (True if user agreed with proxy)

        Ensures:
            - Trust state updated in DB on success
            - Failure logged but never propagates
        """
        try:
            from cosa.rest.db.database import get_db
            from cosa.rest.db.repositories.proxy_decision_repository import TrustStateRepository

            # Use job user_email if available, fallback to session_id
            user_email = getattr( self, '_user_email', None ) or f"{self.session_id}@swe.deepily.ai"

            with get_db() as session:
                repo = TrustStateRepository( session )
                repo.update_after_ratification(
                    user_email = user_email,
                    domain     = "swe",
                    category   = category,
                    approved   = approved,
                )
        except Exception as e:
            logger.warning( f"Trust state DB persistence failed (non-fatal): {e}" )

    def _on_circuit_breaker_trip( self, category, reason ):
        """
        Callback fired when the circuit breaker trips for a category.

        Emits a high-priority alert notification (one-time, no progress group).

        Requires:
            - category is a string identifying the decision category
            - reason is a human-readable string

        Ensures:
            - Sends one alert notification with high priority
            - Non-fatal: logs warning on failure, never raises
        """
        try:
            import requests as http_requests

            base_url = f"http://localhost:{os.environ.get( 'LUPIN_PORT', '7999' )}"
            message  = f"Circuit breaker TRIPPED for {category} — trust demoted to L1"
            abstract = (
                f"**Circuit Breaker Alert**\n"
                f"- **Category**: {category}\n"
                f"- **Reason**: {reason}\n"
                f"- **Action**: Trust level demoted, proxy paused for cooldown"
            )

            # Use direct HTTP POST to notification API (synchronous callback context)
            http_requests.post( f"{base_url}/api/notify", json={
                "message"           : message,
                "notification_type" : "alert",
                "priority"          : "high",
                "abstract"          : abstract,
                "sender_id"         : f"claude.code@swe-team#{self.job_id}" if self.job_id else "claude.code@swe-team",
                "target_user"       : self._user_email,
            }, timeout=_SERVER_TRANSPORT_TIMEOUT_SECONDS )

        except Exception as e:
            logger.warning( f"Circuit breaker alert notification failed (non-fatal): {e}" )

    def _emit_proxy_summary_notification( self, category, action, trust_level, confidence, question, team_io ):
        """
        Emit a progress notification summarizing pending proxy decisions.

        Uses progress_group_id with proxy batch format (pr-{hex}-{N}) for
        in-place DOM updates. Each new decision updates the same notification
        element with an incremented count.

        Requires:
            - self._proxy_pending_count is a positive integer
            - team_io is the cosa_interface module

        Ensures:
            - Fetches current batch ID from the proxy batch-id endpoint
            - Sends progress notification with proxy summary message
            - Non-fatal: logs warning on failure, never raises
        """
        try:
            import requests as http_requests

            # Fetch current batch ID from the proxy batch-id endpoint
            base_url = f"http://localhost:{os.environ.get( 'LUPIN_PORT', '7999' )}"
            batch_resp = http_requests.get( f"{base_url}/api/proxy/batch-id", timeout=_SERVER_TRANSPORT_TIMEOUT_SECONDS )
            batch_data = batch_resp.json()
            batch_id   = batch_data.get( "batch_id", None )

            count = self._proxy_pending_count
            plural = "s" if count != 1 else ""
            message = f"🛡️ {count} proxy decision{plural} pending ratification"

            abstract = (
                f"**Latest Decision**\n"
                f"- **Category**: {category}\n"
                f"- **Action**: {action}\n"
                f"- **Trust Level**: L{trust_level}\n"
                f"- **Confidence**: {confidence:.0%}\n"
                f"- **Question**: {question[ :100 ]}"
            )

            import asyncio
            asyncio.ensure_future( self._notify(
                team_io,
                message           = message,
                role              = "lead",
                priority          = "medium",
                abstract          = abstract,
                progress_group_id = batch_id,
            ) )

            # Also broadcast WebSocket event for ratify page real-time updates
            try:
                http_requests.post( f"{base_url}/api/ws/emit", json={
                    "event" : "proxy_decision_new",
                    "data"  : {
                        "category"      : category,
                        "action"        : action,
                        "trust_level"   : trust_level,
                        "confidence"    : confidence,
                        "question"      : question[ :100 ],
                        "pending_count" : count,
                    }
                }, timeout=_SERVER_TRANSPORT_TIMEOUT_SECONDS )
            except Exception:
                pass  # WebSocket broadcast is best-effort

        except Exception as e:
            logger.warning( f"Proxy summary notification failed (non-fatal): {e}" )

    async def _check_in_with_user( self, team_io, prompt, timeout=None ):
        """
        Pause for user input at a natural break point between tasks.

        Enters WAITING_FEEDBACK state, calls get_feedback() with a short
        timeout, then classifies the response as approval (continue) or
        substantive feedback (inject into next task context).

        Requires:
            - team_io is the cosa_interface module
            - prompt is a non-empty string

        Ensures:
            - Returns None if check-ins disabled, timeout, or user approves
            - Returns feedback string if user provides substantive input
            - State transitions: current -> WAITING_FEEDBACK -> DELEGATING

        Args:
            team_io: cosa_interface module
            prompt: Text to present to user
            timeout: Override for checkin_timeout (seconds)

        Returns:
            str or None: User's substantive feedback, or None
        """
        if not self.config.enable_checkins:
            return None

        prev_state = self.current_state
        self.current_state = OrchestratorState.WAITING_FEEDBACK
        await self._emit_state( prev_state, self.current_state )

        # --- Drain queued user messages (Approach D) ---
        queued_messages = self._drain_user_messages()
        if queued_messages:
            analysis = await self._analyze_user_messages( queued_messages, team_io )

            await self._notify( team_io,
                message  = f"User sent {len( queued_messages )} message(s) during execution",
                role     = "lead",
                priority = "medium",
                abstract = analysis,
            )

            # Present analysis and ask if user approves incorporating it
            approved = await self._gated_confirmation(
                question = f"Incorporate {len( queued_messages )} queued message(s) into the next task?",
                role     = "lead",
                default  = "yes",
                timeout  = 60,
                abstract = f"**User Message Analysis**:\n{analysis}",
                team_io  = team_io,
            )

            self._urgent_interrupt.clear()

            if approved:
                # Restore to DELEGATING state
                self.current_state = OrchestratorState.DELEGATING
                await self._emit_state( OrchestratorState.WAITING_FEEDBACK, self.current_state )
                return analysis  # Treated as substantive feedback

        self._urgent_interrupt.clear()

        resolved_timeout = timeout or self.config.checkin_timeout

        feedback = await team_io.get_feedback(
            prompt  = prompt,
            role    = "lead",
            timeout = resolved_timeout,
        )

        # Restore to DELEGATING state
        self.current_state = OrchestratorState.DELEGATING
        await self._emit_state( OrchestratorState.WAITING_FEEDBACK, self.current_state )

        if feedback and not team_io.is_approval( feedback ):
            return feedback  # Substantive input

        return None  # Approval, dismissal, or timeout

    def _drain_user_messages( self ):
        """
        Drain all pending user messages from the shared queue.

        Requires:
            - self._user_messages is a threading.Queue

        Ensures:
            - Returns list of message dicts (may be empty)
            - Queue is empty after call
            - Never raises

        Returns:
            list[dict]: Accumulated user messages
        """
        messages = []
        while True:
            try:
                msg = self._user_messages.get_nowait()
                messages.append( msg )
            except queue.Empty:
                break
        return messages

    async def _analyze_user_messages( self, messages, team_io ):
        """
        Analyze accumulated user messages using the lead model via SDK.

        Builds a prompt with the accumulated messages and current task context,
        calls the lead model to produce a concise analysis, and returns the
        analysis text to be presented at check-in.

        Requires:
            - messages is a non-empty list of message dicts
            - team_io is the cosa_interface module

        Ensures:
            - Returns analysis string from lead model
            - Falls back to raw concatenation if SDK call fails

        Args:
            messages: List of user message dicts with "message" and "priority" keys
            team_io: cosa_interface module

        Returns:
            str: Analysis text summarizing user messages and suggested actions
        """
        # Build message summary
        msg_lines = []
        for i, msg in enumerate( messages, 1 ):
            priority_tag = f" [URGENT]" if msg.get( "priority" ) == "urgent" else ""
            msg_lines.append( f"  {i}. {msg[ 'message' ]}{priority_tag}" )
        messages_text = "\n".join( msg_lines )

        # Current task context
        current_task_idx = self.state.get( "current_task_index", 0 )
        task_specs = self.state.get( "task_specs", [] )
        current_task = task_specs[ current_task_idx ].title if current_task_idx < len( task_specs ) else "unknown"

        analysis_prompt = f"""The user sent {len( messages )} message(s) during SWE Team execution.

CURRENT TASK: {current_task} (task {current_task_idx + 1}/{len( task_specs )})

USER MESSAGES:
{messages_text}

Analyze these messages and provide:
1. A brief summary of what the user wants
2. Concrete actions to take (modify approach, skip task, use specific module, etc.)
3. Any messages that can be safely acknowledged without action

Keep your response concise (3-5 sentences). Output ONLY the analysis, no preamble."""

        if not SDK_AVAILABLE:
            # Fallback: just concatenate messages
            return f"User sent {len( messages )} message(s):\n{messages_text}"

        try:
            options = self._build_agent_options( "lead" )
            collected_text = []

            async for message in sdk_query( prompt=analysis_prompt, options=options ):
                if isinstance( message, AssistantMessage ):
                    for block in message.content:
                        if isinstance( block, TextBlock ):
                            collected_text.append( block.text )
                elif isinstance( message, TextBlock ):
                    collected_text.append( message.text )
                elif isinstance( message, RateLimitEvent ):
                    logger.warning( f"Rate limited: retry_after={getattr( message, 'retry_after', '?' )}s" )

            return "".join( collected_text ).strip() or f"User messages:\n{messages_text}"

        except Exception as e:
            logger.warning( f"User message analysis failed: {e}" )
            return f"User sent {len( messages )} message(s):\n{messages_text}"

    async def run( self ) -> Optional[ str ]:
        """
        Execute the SWE Team task.

        Phase 2: Decomposes task, delegates to coder, or runs dry-run.

        Requires:
            - task_description is non-empty

        Ensures:
            - Returns final summary string on success
            - Returns None on failure
            - Notifications sent at each phase boundary
            - Safety limits enforced throughout

        Returns:
            str or None: Final task summary
        """
        self.start_time = time.time()

        try:
            # Import here to avoid circular imports at module load
            from . import cosa_interface as team_io

            # Set session context for notifications
            team_io.SESSION_ID = self.session_id

            prev_state = self.current_state
            self.current_state = OrchestratorState.INITIALIZING
            await self._emit_state( prev_state, self.current_state )

            await self._notify( team_io,
                message  = f"Starting SWE Team task: {self.task_description[ :100 ]}",
                role     = "lead",
                priority = "medium",
                abstract = self.task_description,
            )

            if self.config.dry_run:
                result = await self._execute_dry_run( team_io )
            else:
                result = await self._execute_live( team_io )

            self.end_time = time.time()
            prev_state = self.current_state
            self.current_state = OrchestratorState.COMPLETED
            await self._emit_state( prev_state, self.current_state )

            elapsed = self.end_time - self.start_time

            # Build rich summary for completion notification
            summary = self.state.get( "final_summary", "" )
            files_changed = self.state.get( "files_changed", [] )
            files_list = "\n".join( f"  - `{f}`" for f in files_changed[ :20 ] ) if files_changed else "  None"

            rich_abstract = (
                f"**Task**: {self.task_description[ :100 ]}\n"
                f"**Duration**: {elapsed:.1f}s\n\n"
                f"{summary}\n\n"
                f"**Files Changed**:\n{files_list}"
            )

            await self._notify( team_io,
                message  = f"SWE Team task complete ({elapsed:.1f}s)",
                role     = "lead",
                priority = "medium",
                abstract = rich_abstract,
            )

            return result

        except SafetyLimitError as e:
            self.current_state = OrchestratorState.FAILED
            self.end_time = time.time()

            from . import cosa_interface as team_io
            await self._notify( team_io,
                message  = f"SWE Team task stopped: {e}",
                role     = "lead",
                priority = "urgent",
            )

            logger.error( f"Safety limit reached: {e}" )
            return None

        except Exception as e:
            self.current_state = OrchestratorState.FAILED
            self.end_time = time.time()

            from . import cosa_interface as team_io
            await self._notify( team_io,
                message  = f"SWE Team task failed: {str( e )[ :200 ]}",
                role     = "lead",
                priority = "urgent",
            )

            logger.exception( f"Orchestrator failed: {e}" )
            return None

    async def _execute_dry_run( self, team_io ) -> str:
        """
        Execute task in dry-run mode using mock client.

        Sends breadcrumb notifications at each phase.

        Returns:
            str: Dry-run summary
        """
        if self.debug: print( "[Orchestrator] Entering dry-run mode" )

        mock_session = MockAgentSDKSession(
            task_description = self.task_description,
            debug            = self.debug,
        )

        # Override our session_id with the mock's
        self.session_id = mock_session.session_id

        prev_state = self.current_state
        self.current_state = OrchestratorState.DELEGATING
        await self._emit_state( prev_state, self.current_state )

        async for msg in mock_session.query():
            # Send each phase as a notification
            await self._notify( team_io,
                message  = f"[{msg.agent_name}] {msg.content[ :200 ]}",
                role     = msg.agent_name,
                priority = "low",
            )

            self.guard.check_timeout()

            if self._stop_requested:
                break

        summary = mock_session.get_session_summary()
        self.state[ "final_summary" ] = f"Dry-run complete: {summary[ 'messages_sent' ]} phases simulated"

        return self.state[ "final_summary" ]

    async def _execute_live( self, team_io ) -> str:
        """
        Execute task with real Agent SDK delegation.

        Phase 3: Lead decomposes task into TaskSpec[], asks user
        confirmation, delegates each to a Coder subagent, then
        verifies with a Tester subagent in a retry loop.

        Requires:
            - SDK_AVAILABLE is True (claude-agent-sdk installed)
            - team_io is the cosa_interface module

        Ensures:
            - Returns final summary string
            - state["task_specs"] populated with decomposition
            - state["delegation_results"] populated per task
            - state["verification_results"] populated per verification
            - Safety guard checked at each delegation and verification
            - Coder-tester loop capped at MAX_VERIFICATION_ITERATIONS

        Returns:
            str: Task execution summary
        """
        if not SDK_AVAILABLE:
            self.state[ "final_summary" ] = (
                "claude-agent-sdk not installed. Cannot run live mode.\n"
                "Install with: pip install claude-agent-sdk"
            )
            return self.state[ "final_summary" ]

        if self.debug: print( "[Orchestrator] Entering live execution mode" )

        # --- Phase: DECOMPOSING ---
        prev_state = self.current_state
        self.current_state = OrchestratorState.DECOMPOSING
        await self._emit_state( prev_state, self.current_state )

        await self._notify( team_io,
            message  = "Decomposing task into subtasks...",
            role     = "lead",
            priority = "medium",
        )

        task_specs = await self._decompose_task( team_io )
        self.state[ "task_specs" ] = task_specs

        if self.debug: print( f"[Orchestrator] Decomposed into {len( task_specs )} tasks" )

        # --- Confirmation ---
        prev_state = self.current_state
        self.current_state = OrchestratorState.WAITING_CONFIRMATION
        await self._emit_state( prev_state, self.current_state )

        task_summary = "\n".join(
            f"  {i + 1}. {spec.title} → {spec.assigned_role}"
            for i, spec in enumerate( task_specs )
        )

        approved = await self._gated_confirmation(
            question = f"SWE Team decomposed the task into {len( task_specs )} subtasks. Proceed?",
            role     = "lead",
            default  = "yes",
            timeout  = 120,
            abstract = f"**Task**: {self.task_description[ :100 ]}\n\n**Subtasks**:\n{task_summary}",
            team_io  = team_io,
        )

        if not approved:
            self.state[ "final_summary" ] = "Task cancelled by user after decomposition."
            return self.state[ "final_summary" ]

        # --- Phase: DELEGATING ---
        prev_state = self.current_state
        self.current_state = OrchestratorState.DELEGATING
        await self._emit_state( prev_state, self.current_state )
        results = []

        # Initialize state files for progress tracking
        storage_dir = os.path.join( cu.get_project_root(), "io", "swe-team", self.session_id )

        # Wire on_log callback for live progress narration
        on_log = None
        if self.config.narrate_progress:
            def _narrate( msg, role ):
                asyncio.ensure_future( self._notify( team_io, msg, role=role, priority="low" ) )
            on_log = _narrate

        progress_log = ProgressLog( storage_dir=storage_dir, on_log=on_log )
        feature_list = FeatureList( storage_dir=storage_dir )

        for spec in task_specs:
            feature_list.add_task( spec )

        # Progress group IDs for in-place DOM updates
        delegation_group_id = f"pg-{uuid.uuid4().hex[ :8 ]}"

        for i, spec in enumerate( task_specs ):
            if self._stop_requested:
                break

            # --- Urgent interrupt check (Approach D) ---
            if self.config.enable_user_messages and self._urgent_interrupt.is_set():
                if self.debug: print( "[Orchestrator] Urgent interrupt — triggering immediate check-in" )
                urgent_feedback = await self._check_in_with_user(
                    team_io,
                    prompt = f"Urgent message received before task {i + 1}: {spec.title}. Reviewing...",
                )
                if urgent_feedback:
                    self.state[ "user_feedback" ] = urgent_feedback
                    progress_log.log( f"Urgent user feedback received: {urgent_feedback[ :200 ]}", role="user" )

            self.guard.check_timeout()
            self.state[ "current_task_index" ] = i

            await self._notify( team_io,
                message           = f"Delegating task {i + 1}/{len( task_specs )}: {spec.title}",
                role              = "lead",
                priority          = "low",
                progress_group_id = delegation_group_id,
            )

            progress_log.log( f"Starting task {i + 1}: {spec.title}", role="lead" )

            try:
                # Inject user feedback from previous check-in into task spec context
                if self.state.get( "user_feedback" ):
                    spec = TaskSpec(
                        title          = spec.title,
                        objective      = spec.objective + f"\n\nUSER FEEDBACK:\n{self.state[ 'user_feedback' ]}\nIncorporate this guidance.",
                        output_format  = spec.output_format,
                        tool_guidance  = spec.tool_guidance,
                        scope_boundary = spec.scope_boundary,
                        assigned_role  = spec.assigned_role,
                        priority       = spec.priority,
                        depends_on     = spec.depends_on,
                    )
                    self.state[ "user_feedback" ] = None  # Clear after use

                result = await self._delegate_task( spec, i, team_io )
                results.append( result )
                self.state[ "delegation_results" ].append( result )

                if result.status == "success" and self.config.require_test_pass:
                    # --- Coder-Tester Verification Loop ---
                    verify_group_id = f"pg-{uuid.uuid4().hex[ :8 ]}"
                    verification_iteration = 0
                    while verification_iteration < MAX_VERIFICATION_ITERATIONS:  # pragma: no branch - loop always exits via break (verify-pass / redelegate-fail / max-iteration escalation), so the condition-false exit is unreachable
                        verification_iteration += 1
                        self.state[ "total_verification_iterations" ] += 1

                        verification = await self._verify_result( spec, result, i, team_io )
                        self.state[ "verification_results" ].append( verification )

                        if verification.passed:
                            result.test_results = verification.tester_output[ :1000 ]
                            self.guard.record_success()
                            feature_list.mark_complete( i )

                            # Build test summary for abstract
                            test_abstract = None
                            if verification.test_run_result:
                                tr = verification.test_run_result
                                test_abstract = (
                                    f"**Passed**: {tr.get( 'passed_count', 0 )} | "
                                    f"**Failed**: {tr.get( 'failed_count', 0 )} | "
                                    f"**Errors**: {tr.get( 'error_count', 0 )}"
                                )

                            await self._notify( team_io,
                                message           = f"Task {i + 1} verified (iteration {verification_iteration}): {spec.title}",
                                role              = "tester",
                                priority          = "low",
                                abstract          = test_abstract,
                                progress_group_id = verify_group_id,
                            )

                            progress_log.log(
                                f"Task {i + 1} verified (iteration {verification_iteration}): {spec.title}",
                                role="tester",
                            )
                            break  # Tests pass — done

                        if verification_iteration >= MAX_VERIFICATION_ITERATIONS:
                            # Max retries exhausted — escalate to user
                            self.guard.record_failure( "verification failed after max iterations" )

                            await self._notify( team_io,
                                message           = f"Task {i + 1} failed after {MAX_VERIFICATION_ITERATIONS} verification attempts: {spec.title}",
                                role              = "lead",
                                priority          = "high",
                                progress_group_id = verify_group_id,
                            )

                            # Escalation decision
                            escalation = await team_io.request_decision(
                                question = f"Task {i + 1} tests keep failing after {MAX_VERIFICATION_ITERATIONS} attempts. How should I proceed?",
                                options  = [ {
                                    "question"    : f"Task '{spec.title}' failed verification {MAX_VERIFICATION_ITERATIONS} times. What next?",
                                    "header"      : "Escalation",
                                    "multiSelect" : False,
                                    "options"     : [
                                        { "label": "Continue to next task", "description": "Skip this task and move on" },
                                        { "label": "Skip tests for this task", "description": "Accept implementation without passing tests" },
                                        { "label": "Stop and get help", "description": "Halt execution for manual intervention" },
                                    ],
                                } ],
                                role     = "lead",
                                timeout  = 300,
                                abstract = f"**Task**: {spec.title}\n**Attempts**: {MAX_VERIFICATION_ITERATIONS}\n**Last failure**:\n{verification.tester_output[ :500 ]}",
                            )

                            # Process escalation response
                            escalation_choice = escalation.get( "answers", {} ).get( "Escalation", "Continue to next task" )

                            if escalation_choice == "Stop and get help":
                                self._stop_requested = True

                            elif escalation_choice == "Skip tests for this task":
                                # Accept implementation without tests
                                result.status = "success"
                                result.errors = [ "Tests skipped by user escalation" ]
                                self.guard.record_success()
                                feature_list.mark_complete( i )
                                progress_log.log(
                                    f"Task {i + 1} accepted without tests (user escalation): {spec.title}",
                                    role="lead",
                                )
                                break

                            # Default: "Continue to next task" — mark failed and move on
                            result = DelegationResult(
                                task_index    = i,
                                task_title    = spec.title,
                                status        = "failure",
                                output        = result.output,
                                errors        = [ "Verification failed after max iterations" ],
                                test_results  = verification.tester_output[ :1000 ],
                                confidence    = 0.0,
                            )
                            self.state[ "delegation_results" ][ -1 ] = result
                            results[ -1 ] = result   # keep the local summary list in sync with state — was left as the stale SUCCESS object, so an abandoned task was over-counted in the completed-X/N summary
                            progress_log.log(
                                f"Task {i + 1} verification exhausted: {spec.title}",
                                role="lead",
                            )
                            break

                        # Re-delegate to coder with tester feedback
                        result = await self._redelegate_with_feedback(
                            spec, i, result, verification.tester_output,
                            verification_iteration + 1, team_io,
                        )
                        self.state[ "delegation_results" ][ -1 ] = result

                        if result.status != "success":
                            self.guard.record_failure( "coder re-implementation failed" )

                            await self._notify( team_io,
                                message           = f"Task {i + 1} re-implementation failed: {spec.title}",
                                role              = "coder",
                                priority          = "medium",
                                progress_group_id = verify_group_id,
                            )

                            progress_log.log(
                                f"Task {i + 1} re-implementation failed: {spec.title}",
                                role="coder",
                            )
                            break

                elif result.status == "success":
                    # require_test_pass=False — skip verification
                    self.guard.record_success()
                    feature_list.mark_complete( i )
                    progress_log.log( f"Task {i + 1} completed (no verification): {spec.title}", role="coder" )

                else:
                    self.guard.record_failure( f"Task {i + 1} failed: {result.errors}" )
                    progress_log.log( f"Task {i + 1} failed: {spec.title}", role="coder" )

                # Track changed files
                for f in result.files_changed:
                    if f not in self.state[ "files_changed" ]:
                        self.state[ "files_changed" ].append( f )

                # --- Between-task check-in ---
                if i < len( task_specs ) - 1:
                    feedback = await self._check_in_with_user(
                        team_io,
                        prompt = f"Task {i + 1}/{len( task_specs )} done: {spec.title}. Any input before the next task?",
                    )
                    if feedback:
                        self.state[ "user_feedback" ] = feedback
                        progress_log.log( f"User feedback received: {feedback[ :200 ]}", role="user" )

            except SafetyLimitError:
                raise  # Let outer handler catch

            except Exception as e:
                logger.error( f"Delegation failed for task {i + 1}: {e}" )
                self.guard.record_failure( str( e ) )

                await self._notify( team_io,
                    message  = f"Task {i + 1} delegation error: {str( e )[ :100 ]}",
                    role     = "lead",
                    priority = "high",
                )

                results.append( DelegationResult(
                    task_index    = i,
                    task_title    = spec.title,
                    status        = "failure",
                    output        = "",
                    errors        = [ str( e ) ],
                    confidence    = 0.0,
                ) )
                progress_log.log( f"Task {i + 1} exception: {e}", role="lead" )

        # --- Post-completion check-in ---
        success_count = sum( 1 for r in results if r.status == "success" )
        feedback = await self._check_in_with_user(
            team_io,
            prompt  = f"All {len( task_specs )} tasks complete ({success_count} successful). Any final input before summary?",
            timeout = 60,
        )
        if feedback:
            progress_log.log( f"User final feedback: {feedback[ :200 ]}", role="user" )

        # --- Summary ---
        success_count        = sum( 1 for r in results if r.status == "success" )
        total_files          = len( self.state[ "files_changed" ] )
        verification_count   = len( self.state[ "verification_results" ] )
        verification_passed  = sum( 1 for v in self.state[ "verification_results" ] if v.passed )
        total_v_iterations   = self.state[ "total_verification_iterations" ]

        summary_markdown = (
            f"SWE Team completed {success_count}/{len( task_specs )} tasks.\n"
            f"Files changed: {total_files}\n"
            f"Verifications: {verification_passed}/{verification_count} passed"
            f" ({total_v_iterations} total iterations)\n"
            f"Session: {self.session_id}"
        )
        self.state[ "final_summary" ] = summary_markdown

        # Package CJ Flow-compatible artifacts
        self.state[ "artifacts" ] = {
            "abstract"      : summary_markdown,
            "report_path"   : progress_log.file_path,
            "cost_summary"  : f"${self.tokens_used * 0.000015:.4f} est.",
            "files_changed" : self.state[ "files_changed" ],
        }

        progress_log.log( summary_markdown, role="lead" )

        return summary_markdown

    async def _decompose_task( self, team_io ):
        """
        Lead agent decomposes task into TaskSpec[].

        Uses ClaudeSDKClient with lead model and read-only tools
        to produce a structured JSON decomposition.

        Requires:
            - SDK_AVAILABLE is True
            - team_io is the cosa_interface module

        Ensures:
            - Returns list[TaskSpec] with at least 1 item
            - Falls back to single TaskSpec if parse fails

        Args:
            team_io: cosa_interface module

        Returns:
            list[TaskSpec]: Decomposed task specifications
        """
        decomposition_prompt = f"""Decompose the following task into 1-5 subtasks.

TASK: {self.task_description}

OUTPUT FORMAT: Respond with a JSON array of task objects. Each object must have:
- "title": Short title (string)
- "objective": What must be accomplished (string)
- "output_format": Expected output structure (string)
- "tool_guidance": Which tools to use (string, optional)
- "scope_boundary": What NOT to touch (string, optional)
- "assigned_role": "coder" (string)
- "priority": 1-5 integer

IMPORTANT: Output ONLY the JSON array, no markdown fences, no explanation.

Example:
[
  {{
    "title": "Add health check endpoint",
    "objective": "Create GET /health that returns {{'status': 'ok'}}",
    "output_format": "Modified main.py with new endpoint",
    "tool_guidance": "Use Edit to modify existing router file",
    "scope_boundary": "Do not modify authentication code",
    "assigned_role": "coder",
    "priority": 1
  }}
]"""

        try:
            options = self._build_agent_options( "lead" )
            collected_text = []

            async for message in sdk_query( prompt=decomposition_prompt, options=options ):
                if isinstance( message, AssistantMessage ):
                    for block in message.content:
                        if isinstance( block, TextBlock ):
                            collected_text.append( block.text )
                elif isinstance( message, TextBlock ):
                    collected_text.append( message.text )
                elif isinstance( message, RateLimitEvent ):
                    logger.warning( f"Rate limited: retry_after={getattr( message, 'retry_after', '?' )}s" )

            raw_response = "".join( collected_text ).strip()

            if self.debug: print( f"[Orchestrator] Lead response: {raw_response[ :500 ]}" )

            return self._parse_task_specs( raw_response )

        except Exception as e:
            logger.warning( f"Decomposition failed, using single-task fallback: {e}" )
            return self._fallback_single_task()

    def _parse_task_specs( self, raw_response ):
        """
        Parse lead's JSON response into list[TaskSpec].

        Requires:
            - raw_response is a string (possibly with markdown fences)

        Ensures:
            - Returns list[TaskSpec] with validated entries
            - Falls back to single TaskSpec on parse failure

        Args:
            raw_response: Raw text from lead agent

        Returns:
            list[TaskSpec]: Parsed task specifications
        """
        # Strip markdown code fences if present
        text = raw_response.strip()
        if text.startswith( "```" ):
            lines = text.split( "\n" )
            # Remove first and last lines (fences)
            lines = [ l for l in lines if not l.strip().startswith( "```" ) ]
            text = "\n".join( lines ).strip()

        try:
            data = json.loads( text )

            if not isinstance( data, list ):
                data = [ data ]

            specs = []
            for item in data:
                spec = TaskSpec( **item )
                specs.append( spec )

            if not specs:
                return self._fallback_single_task()

            return specs

        except ( json.JSONDecodeError, TypeError, ValueError ) as e:
            logger.warning( f"Failed to parse task specs: {e}" )
            return self._fallback_single_task()

    def _fallback_single_task( self ):
        """
        Create a single TaskSpec fallback from the original task.

        Ensures:
            - Returns list with one TaskSpec
            - Uses original task_description as objective

        Returns:
            list[TaskSpec]: Single-item list
        """
        return [ TaskSpec(
            title          = self.task_description[ :80 ],
            objective      = self.task_description,
            output_format  = "Modified source files",
            tool_guidance  = "Use Read, Edit, and Bash as needed",
            scope_boundary = "Stay within the project directory",
            assigned_role  = "coder",
            priority       = 1,
        ) ]

    async def _delegate_task( self, task_spec, task_index, team_io ):
        """
        Delegate a single TaskSpec to a coder subagent via SDK.

        Requires:
            - task_spec is a valid TaskSpec
            - task_index is a non-negative integer
            - team_io is the cosa_interface module

        Ensures:
            - Returns DelegationResult with status, output, files_changed
            - Safety guard checked during execution
            - Notifications sent for progress

        Args:
            task_spec: The task to delegate
            task_index: Index of this task in the decomposition
            team_io: cosa_interface module

        Returns:
            DelegationResult: Execution result
        """
        delegation_prompt = f"""TASK: {task_spec.title}
OBJECTIVE: {task_spec.objective}
EXPECTED OUTPUT: {task_spec.output_format}
TOOL GUIDANCE: {task_spec.tool_guidance}
SCOPE BOUNDARY: {task_spec.scope_boundary}

Complete this task. When done, summarize what you did and list all files changed."""

        try:
            options = self._build_agent_options( "coder", team_io )
            collected_text  = []
            files_changed   = []

            # Progress group ID for in-place DOM updates of coder SDK stream messages
            coder_group_id = f"pg-{uuid.uuid4().hex[ :8 ]}"

            prev_state = self.current_state
            self.current_state = OrchestratorState.CODING
            await self._emit_state( prev_state, self.current_state, { "task_index": task_index } )

            # Bug 15 WORKAROUND: claude-agent-sdk ≥ 0.1.36 rejects str prompt when
            # can_use_tool is set on options. Upstream (unresolved as of 2026-04-17):
            # https://github.com/anthropics/claude-code/issues/18735 — remove the
            # wrap_prompt_for_streaming() call once upstream lands the fix.
            async for message in sdk_query( prompt=wrap_prompt_for_streaming( delegation_prompt ), options=options ):
                self.guard.check_timeout()

                if isinstance( message, AssistantMessage ):
                    for block in message.content:
                        if isinstance( block, TextBlock ):
                            collected_text.append( block.text )
                        elif isinstance( block, ToolUseBlock ):
                            # Track file changes from Edit/Write tool uses
                            if block.name in ( "Edit", "Write" ):
                                file_path = block.input.get( "file_path", "" )
                                if file_path and file_path not in files_changed:
                                    files_changed.append( file_path )
                                await post_tool_hook( block.name, block.input, self.guard )

                elif isinstance( message, TextBlock ):
                    collected_text.append( message.text )

                elif isinstance( message, ResultMessage ):
                    # Forward SDK notification events through notification_hook
                    await notification_hook(
                        { "message": getattr( message, "text", str( message ) ) },
                        team_io, role="coder", progress_group_id=coder_group_id,
                    )
                elif isinstance( message, RateLimitEvent ):
                    logger.warning( f"Rate limited: retry_after={getattr( message, 'retry_after', '?' )}s" )

                if self._stop_requested:
                    break

            self.guard.check_iteration()

            output = "".join( collected_text ).strip()

            return DelegationResult(
                task_index    = task_index,
                task_title    = task_spec.title,
                status        = "success",
                output        = output[ :2000 ],
                files_changed = files_changed,
                confidence    = 0.8,
            )

        except SafetyLimitError:
            raise  # Propagate to outer handler

        except Exception as e:
            logger.error( f"Delegation error for '{task_spec.title}': {e}" )
            return DelegationResult(
                task_index    = task_index,
                task_title    = task_spec.title,
                status        = "failure",
                output        = "",
                errors        = [ str( e ) ],
                confidence    = 0.0,
            )

    async def _verify_result( self, task_spec, coder_result, task_index, team_io ):
        """
        Verify coder's implementation by delegating to the tester agent.

        Builds a tester prompt with the original task spec and coder's output,
        delegates to the tester via sdk_query(), and optionally runs independent
        pytest validation on any test files created.

        Requires:
            - task_spec is a valid TaskSpec
            - coder_result is a DelegationResult with status "success"
            - task_index is a non-negative integer
            - team_io is the cosa_interface module

        Ensures:
            - Sets self.current_state to OrchestratorState.TESTING
            - Returns VerificationResult with pass/fail status
            - Tracks test files created by the tester
            - Never raises — returns failed VerificationResult on error

        Args:
            task_spec: The original task specification
            coder_result: The coder's delegation result
            task_index: Index of the task in decomposition
            team_io: cosa_interface module

        Returns:
            VerificationResult: Test verification outcome
        """
        prev_state = self.current_state
        self.current_state = OrchestratorState.TESTING
        await self._emit_state( prev_state, self.current_state, { "task_index": task_index } )

        await self._notify( team_io,
            message  = f"Verifying task {task_index + 1}: {task_spec.title}",
            role     = "tester",
            priority = "low",
        )

        verification_prompt = f"""VERIFY THE FOLLOWING IMPLEMENTATION:

ORIGINAL TASK: {task_spec.title}
OBJECTIVE: {task_spec.objective}
EXPECTED OUTPUT: {task_spec.output_format}

CODER OUTPUT SUMMARY:
{coder_result.output[ :1500 ]}

FILES CHANGED BY CODER:
{chr( 10 ).join( coder_result.files_changed ) if coder_result.files_changed else "None reported"}

YOUR INSTRUCTIONS:
1. Read the changed files to understand what was implemented
2. Write appropriate tests (unit tests preferred, in src/tests/unit/)
3. Run the tests with pytest
4. Report whether the implementation passes all tests

IMPORTANT:
- Focus on testing the ACTUAL changes made by the coder
- Follow existing test patterns in the project
- Report a clear PASS or FAIL verdict at the end of your output
- If tests FAIL, explain what failed and why"""

        try:
            options         = self._build_agent_options( "tester", team_io )
            collected_text  = []
            test_files      = []

            # Progress group ID for in-place DOM updates of tester SDK stream messages
            tester_group_id = f"pg-{uuid.uuid4().hex[ :8 ]}"

            # Bug 15 WORKAROUND: claude-agent-sdk ≥ 0.1.36 rejects str prompt when
            # can_use_tool is set on options. Upstream (unresolved as of 2026-04-17):
            # https://github.com/anthropics/claude-code/issues/18735 — remove the
            # wrap_prompt_for_streaming() call once upstream lands the fix.
            async for message in sdk_query( prompt=wrap_prompt_for_streaming( verification_prompt ), options=options ):
                self.guard.check_timeout()

                if isinstance( message, AssistantMessage ):
                    for block in message.content:
                        if isinstance( block, TextBlock ):
                            collected_text.append( block.text )
                        elif isinstance( block, ToolUseBlock ):
                            # Track test files created by the tester
                            if block.name in ( "Edit", "Write" ):
                                file_path = block.input.get( "file_path", "" )
                                if file_path and file_path not in test_files:
                                    test_files.append( file_path )
                                await post_tool_hook( block.name, block.input, self.guard )

                elif isinstance( message, TextBlock ):
                    collected_text.append( message.text )

                elif isinstance( message, ResultMessage ):
                    await notification_hook(
                        { "message": getattr( message, "text", str( message ) ) },
                        team_io, role="tester", progress_group_id=tester_group_id,
                    )
                elif isinstance( message, RateLimitEvent ):
                    logger.warning( f"Rate limited: retry_after={getattr( message, 'retry_after', '?' )}s" )

                if self._stop_requested:
                    break

            tester_output = "".join( collected_text ).strip()

            # Determine pass/fail from tester output
            output_lower = tester_output.lower()
            passed = (
                "pass" in output_lower
                and "fail" not in output_lower
            ) or "all tests pass" in output_lower

            # Optionally run independent pytest validation on test files
            test_run_dict = None
            if test_files:
                for tf in test_files:
                    if tf.endswith( ".py" ) and "test" in tf.lower():
                        run_result = await run_pytest( tf, timeout_secs=60 )
                        test_run_dict = {
                            "passed"       : run_result.passed,
                            "total_tests"  : run_result.total_tests,
                            "passed_count" : run_result.passed_count,
                            "failed_count" : run_result.failed_count,
                            "error_count"  : run_result.error_count,
                            "timed_out"    : run_result.timed_out,
                        }
                        # Independent validation overrides tester's self-report
                        if not run_result.passed:
                            passed = False
                        break  # Only validate first test file found

            status = "passed" if passed else "failed"

            return VerificationResult(
                task_index         = task_index,
                task_title         = task_spec.title,
                passed             = passed,
                tester_output      = tester_output[ :2000 ],
                test_run_result    = test_run_dict,
                test_files_created = test_files,
                status             = status,
            )

        except SafetyLimitError:
            raise  # Propagate to outer handler

        except Exception as e:
            logger.error( f"Verification error for '{task_spec.title}': {e}" )
            return VerificationResult(
                task_index    = task_index,
                task_title    = task_spec.title,
                passed        = False,
                tester_output = f"Verification error: {e}",
                status        = "failed",
            )

    async def _redelegate_with_feedback( self, task_spec, task_index, coder_result, test_feedback, iteration, team_io ):
        """
        Re-delegate a task to the coder with tester failure feedback.

        Builds an augmented prompt including the prior coder output,
        tester failure feedback, and current iteration number to help
        the coder address the specific test failures.

        Requires:
            - task_spec is a valid TaskSpec
            - task_index is a non-negative integer
            - coder_result is the previous DelegationResult
            - test_feedback is a string with tester output
            - iteration is a positive integer (current retry number)
            - team_io is the cosa_interface module

        Ensures:
            - Returns a new DelegationResult from the coder
            - Prompt includes prior output and failure feedback
            - Sets current_state to CODING

        Args:
            task_spec: The original task specification
            task_index: Index of the task in decomposition
            coder_result: Previous coder result
            test_feedback: Tester output describing failures
            iteration: Current iteration number (2, 3, etc.)
            team_io: cosa_interface module

        Returns:
            DelegationResult: New coder execution result
        """
        await self._notify( team_io,
            message  = f"Re-delegating task {task_index + 1} (iteration {iteration}): {task_spec.title}",
            role     = "lead",
            priority = "low",
        )

        redelegation_prompt = f"""FIX THE FOLLOWING IMPLEMENTATION (Iteration {iteration}/{MAX_VERIFICATION_ITERATIONS}):

ORIGINAL TASK: {task_spec.title}
OBJECTIVE: {task_spec.objective}

YOUR PRIOR OUTPUT:
{coder_result.output[ :1000 ]}

FILES YOU CHANGED:
{chr( 10 ).join( coder_result.files_changed ) if coder_result.files_changed else "None reported"}

TESTER FEEDBACK (TESTS FAILED):
{test_feedback[ :1500 ]}

INSTRUCTIONS:
1. Read the tester's failure feedback carefully
2. Fix the implementation to address the test failures
3. Do NOT modify the test files — fix your implementation code
4. Summarize what you changed and list all files modified"""

        try:
            options = self._build_agent_options( "coder", team_io )
            collected_text  = []
            files_changed   = []

            # Progress group ID for in-place DOM updates of re-delegation SDK stream messages
            redelegate_group_id = f"pg-{uuid.uuid4().hex[ :8 ]}"

            prev_state = self.current_state
            self.current_state = OrchestratorState.CODING
            await self._emit_state( prev_state, self.current_state, { "task_index": task_index, "iteration": iteration } )

            # Bug 15 WORKAROUND: claude-agent-sdk ≥ 0.1.36 rejects str prompt when
            # can_use_tool is set on options. Upstream (unresolved as of 2026-04-17):
            # https://github.com/anthropics/claude-code/issues/18735 — remove the
            # wrap_prompt_for_streaming() call once upstream lands the fix.
            async for message in sdk_query( prompt=wrap_prompt_for_streaming( redelegation_prompt ), options=options ):
                self.guard.check_timeout()

                if isinstance( message, AssistantMessage ):
                    for block in message.content:
                        if isinstance( block, TextBlock ):
                            collected_text.append( block.text )
                        elif isinstance( block, ToolUseBlock ):
                            if block.name in ( "Edit", "Write" ):
                                file_path = block.input.get( "file_path", "" )
                                if file_path and file_path not in files_changed:
                                    files_changed.append( file_path )
                                await post_tool_hook( block.name, block.input, self.guard )

                elif isinstance( message, TextBlock ):
                    collected_text.append( message.text )

                elif isinstance( message, ResultMessage ):
                    await notification_hook(
                        { "message": getattr( message, "text", str( message ) ) },
                        team_io, role="coder", progress_group_id=redelegate_group_id,
                    )
                elif isinstance( message, RateLimitEvent ):
                    logger.warning( f"Rate limited: retry_after={getattr( message, 'retry_after', '?' )}s" )

                if self._stop_requested:
                    break

            self.guard.check_iteration()

            output = "".join( collected_text ).strip()

            return DelegationResult(
                task_index    = task_index,
                task_title    = task_spec.title,
                status        = "success",
                output        = output[ :2000 ],
                files_changed = files_changed,
                confidence    = 0.6,  # Lower confidence on retries
            )

        except SafetyLimitError:
            raise

        except Exception as e:
            logger.error( f"Re-delegation error for '{task_spec.title}': {e}" )
            return DelegationResult(
                task_index    = task_index,
                task_title    = task_spec.title,
                status        = "failure",
                output        = "",
                errors        = [ str( e ) ],
                confidence    = 0.0,
            )

    def _build_agent_options( self, role_name, team_io=None ):
        """
        Build ClaudeAgentOptions for a given role.

        Requires:
            - role_name is "lead", "coder", or "tester"

        Ensures:
            - Returns ClaudeAgentOptions with correct model, tools, permissions
            - Coder and tester get can_use_tool callback for safety gating
            - Lead gets read-only tools

        Args:
            role_name: Agent role name
            team_io: cosa_interface module (required for coder/tester)

        Returns:
            ClaudeAgentOptions: Configured SDK options
        """
        roles  = get_agent_roles( self.config )
        role   = roles[ role_name ]
        model  = get_model_for_role( role, self.config )

        if role_name == "lead":
            system_prompt = LEAD_SYSTEM_PROMPT.format(
                max_failures=self.config.max_consecutive_failures
            )
        elif role_name == "tester":
            system_prompt = TESTER_SYSTEM_PROMPT
        else:
            system_prompt = CODER_SYSTEM_PROMPT

        options_kwargs = {
            "model"           : model,
            "system_prompt"   : system_prompt,
            "tools"           : role.tools,
            "cwd"             : cu.get_project_root(),
            "max_turns"       : self.config.max_iterations_per_task,
            "max_budget_usd"  : self.config.budget_usd,
        }

        # Coder and tester get permission gating and acceptEdits mode
        if role_name in ( "coder", "tester" ) and team_io is not None:
            options_kwargs[ "permission_mode" ] = "acceptEdits"
            options_kwargs[ "can_use_tool" ]    = build_can_use_tool( team_io, self.guard, role_name )
        else:
            options_kwargs[ "permission_mode" ] = "plan"

        return ClaudeAgentOptions( **options_kwargs )

    def get_state( self ) -> dict:
        """
        Get current orchestrator state for external monitoring.

        Returns:
            dict: Current state, progress, guard status, and proxy status
        """
        state = {
            "orchestrator_state" : self.current_state.value,
            "session_id"         : self.session_id,
            "task"               : self.task_description[ :100 ],
            "guard_status"       : self.guard.get_status(),
            "tokens_used"        : self.tokens_used,
            "dry_run"            : self.config.dry_run,
        }

        # Decision proxy fields (Phase 4 light-up)
        if self.proxy is not None:
            state[ "proxy_trust_mode" ]     = self.proxy.trust_mode
            state[ "proxy_trust_levels" ]   = self.proxy.trust_tracker.get_all_levels()
            state[ "proxy_trust_stats" ]    = self.proxy.trust_tracker.get_stats()
            state[ "proxy_circuit_breaker" ] = self.proxy.circuit_breaker.get_status()
        else:
            state[ "proxy_trust_mode" ]     = "disabled"
            state[ "proxy_trust_levels" ]   = {}
            state[ "proxy_trust_stats" ]    = {}
            state[ "proxy_circuit_breaker" ] = {}

        return state

    async def stop( self ) -> dict:
        """
        Request graceful stop of the orchestrator.

        Ensures:
            - Sets stop flag for next iteration check
            - Returns current state

        Returns:
            dict: Final state at time of stop
        """
        self._stop_requested = True
        self.current_state = OrchestratorState.STOPPED
        return self.get_state()

    def _calculate_progress( self ) -> int:
        """
        Calculate approximate progress percentage.

        Returns:
            int: Progress 0-100
        """
        progress_map = {
            OrchestratorState.INITIALIZING         : 5,
            OrchestratorState.DECOMPOSING          : 15,
            OrchestratorState.DELEGATING            : 30,
            OrchestratorState.CODING                : 50,
            OrchestratorState.TESTING               : 70,
            OrchestratorState.REVIEWING             : 85,
            OrchestratorState.DEBUGGING             : 75,
            OrchestratorState.WAITING_CONFIRMATION : 40,
            OrchestratorState.WAITING_DECISION     : 40,
            OrchestratorState.WAITING_FEEDBACK     : 40,
            OrchestratorState.COMPLETED             : 100,
            OrchestratorState.FAILED                : 100,
            OrchestratorState.PAUSED                : 50,
            OrchestratorState.STOPPED               : 100,
        }
        return progress_map.get( self.current_state, 0 )


def quick_smoke_test():
    """Quick smoke test for orchestrator module."""
    import cosa.utils.util as cu

    cu.print_banner( "SWE Team Orchestrator Smoke Test", prepend_nl=True )

    try:
        # Test 1: Orchestrator creation
        print( "Testing orchestrator creation..." )
        config = SweTeamConfig( dry_run=True )
        orch = SweTeamOrchestrator(
            task_description = "Implement a health check endpoint",
            config           = config,
            debug            = False,
        )
        assert orch.task_description == "Implement a health check endpoint"
        assert orch.current_state == OrchestratorState.INITIALIZING
        assert orch.session_id.startswith( "st-" )
        print( f"✓ Orchestrator created: {orch.session_id}" )

        # Test 2: get_state
        print( "Testing get_state..." )
        state = orch.get_state()
        assert state[ "orchestrator_state" ] == "initializing"
        assert state[ "dry_run" ] is True
        assert "guard_status" in state
        print( "✓ get_state returns valid dict" )

        # Test 3: Progress calculation
        print( "Testing progress calculation..." )
        assert orch._calculate_progress() == 5  # INITIALIZING
        orch.current_state = OrchestratorState.COMPLETED
        assert orch._calculate_progress() == 100
        orch.current_state = OrchestratorState.INITIALIZING
        print( "✓ Progress calculation works" )

        # Test 4: Dry-run execution
        print( "Testing dry-run execution..." )
        result = asyncio.run( orch.run() )
        assert result is not None
        assert "Dry-run complete" in result
        assert orch.current_state == OrchestratorState.COMPLETED
        print( f"✓ Dry-run completed: {result[ :60 ]}" )

        # Test 5: Stop request
        print( "Testing stop request..." )
        orch2 = SweTeamOrchestrator(
            task_description = "Another task",
            config           = SweTeamConfig( dry_run=True ),
        )
        stop_state = asyncio.run( orch2.stop() )
        assert orch2._stop_requested is True
        assert stop_state[ "orchestrator_state" ] == "stopped"
        print( "✓ Stop request works" )

        print( "\n✓ Orchestrator smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
