#!/usr/bin/env python3
"""
Shared Agent Notification Dispatcher for COSA Agents.

Encapsulates the common async wrapper + notification dispatch pattern that
was previously copy-pasted across every agent's cosa_interface.py. All
methods use asyncio.to_thread() to bridge the blocking notification API
with async agent orchestrators.

Usage:
    dispatcher = AgentNotificationDispatcher( agent_type="deep.research" )
    await dispatcher.notify_progress( "Starting research..." )
    approved  = await dispatcher.ask_confirmation( "Proceed?" )
    feedback  = await dispatcher.get_feedback( "Any preferences?" )
    selection = await dispatcher.present_choices( questions, timeout=120 )

For role-aware agents (SWE Team):
    dispatcher = AgentNotificationDispatcher(
        agent_type="swe", supports_role=True, default_priority="high"
    )
    await dispatcher.notify_progress( "Planning...", role="lead" )
"""

import asyncio
import json
import logging
from contextvars import ContextVar
from typing import Optional

from lupin_cli.notifications.notification_models import (
    NotificationRequest,
    AsyncNotificationRequest,
    NotificationResponse,
    NotificationType,
    NotificationPriority,
    ResponseType
)
from lupin_cli.notifications.notify_user_sync import notify_user_sync as _notify_user_sync
from lupin_cli.notifications.notify_user_async import notify_user_async as _notify_user_async
from cosa.utils.notification_utils import format_questions_for_tts, convert_questions_for_api
from cosa.agents.utils.sender_id import build_sender_id

logger = logging.getLogger( __name__ )


# =============================================================================
# Per-task dispatch context (concurrent-job isolation, OOS Phase 4 backlog #1)
# =============================================================================
#
# ContextVars carry per-asyncio-task / per-thread state so concurrent agentic
# jobs of the same type don't clobber each other's sender_id / target_user /
# session_name when emitting notifications. Each pool worker's `asyncio.run()`
# creates an isolated context; jobs set these vars at execution start and the
# dispatcher reads them in priority over `self.*` instance state.
#
# Without these, the legacy "module-global SENDER_ID + shared dispatcher
# instance" pattern races: two concurrent DR jobs both write
# `cosa_interface.SENDER_ID`, and the most-recently-launched job's value
# leaks onto the earlier still-running job's notifications. Symptom seen in
# 2026-04-28 RUN 2 logs: dr-de05b9d0's notifications carried dr-d5e4408a's
# sender_id.
#
# Reset semantics: callers should use `.set(value)` and store the returned
# token, then `.reset(token)` at job end to restore the prior context. In
# practice agentic jobs run in fresh asyncio.run() contexts per worker
# thread, so the reset is mostly cosmetic — but explicit cleanup is good
# practice and prevents leaks if the same thread runs multiple jobs.
ctx_sender_id    : ContextVar[ Optional[ str ] ] = ContextVar( "agent_dispatcher_sender_id",    default=None )
ctx_target_user  : ContextVar[ Optional[ str ] ] = ContextVar( "agent_dispatcher_target_user",  default=None )
ctx_session_name : ContextVar[ Optional[ str ] ] = ContextVar( "agent_dispatcher_session_name", default=None )


def _prepend_operator_routing( abstract: Optional[ str ], original_target: str ) -> str:
    """
    Prefix an abstract with an 'Operator routing:' context line so the operator
    answering a voice gate understands they're acting on behalf of a service
    account. See Bug 10 (2026-04-15).
    """
    header = f"**Operator routing**: originally owned by `{original_target}`"
    if not abstract:
        return header
    return f"{header}\n\n{abstract}"


class AgentNotificationDispatcher:
    """
    Shared async notification dispatcher for COSA agents.

    Configurable via constructor for agent-specific behavior:
    - agent_type: Sender identity prefix (e.g., "deep.research")
    - default_priority: Default notification priority level
    - supports_role: Whether this agent uses role-aware sender IDs

    Attributes:
        sender_id: Current sender_id string (mutable for runtime suffixes)
        session_name: Optional session name for UI display
        session_id: Optional session ID for role-aware agents
    """

    def __init__(
        self,
        agent_type: str,
        default_priority: str = "medium",
        supports_role: bool = False,
        default_suffix: str = None
    ):
        """
        Initialize the dispatcher.

        Requires:
            - agent_type is a non-empty string

        Ensures:
            - Dispatcher ready to send notifications
            - sender_id computed from agent_type + auto-detected project

        Args:
            agent_type: Agent identifier prefix (e.g., "deep.research", "swe")
            default_priority: Default priority for blocking calls ("medium", "high")
            supports_role: If True, methods accept a `role` parameter for role-aware sender IDs
            default_suffix: Optional default suffix for sender_id (e.g., "cli")
        """
        self.agent_type       = agent_type
        self.default_priority = default_priority
        self.supports_role    = supports_role
        self.default_suffix   = default_suffix

        # Mutable state — job.py callers can modify these at runtime
        self.sender_id    = build_sender_id( agent_type, suffix=default_suffix )
        self.session_name = None
        self.session_id   = None  # For role-aware agents (SWE Team)
        self.target_user  = None  # Set by job.py callers at runtime

    def build_sender_id( self, suffix: str = None ) -> str:
        """
        Rebuild sender_id with an optional new suffix.

        Useful when job.py needs to append a job hash:
            dispatcher.sender_id = dispatcher.build_sender_id( suffix=self.id_hash )

        Args:
            suffix: Optional suffix (replaces default_suffix for this call)

        Returns:
            str: Newly constructed sender_id
        """
        return build_sender_id( self.agent_type, suffix=suffix or self.default_suffix )

    def _resolve_sender_id( self, role: str = None ) -> str:
        """
        Resolve the sender_id for a notification call.

        Priority order:
          1. Role-aware agents with a role parameter — build role-specific sender_id
          2. ContextVar `ctx_sender_id` — per-task isolation, set by job execution
          3. self.sender_id — instance default (CLI / single-job paths)

        Role-aware path is checked first because it constructs a role-suffixed
        ID that's orthogonal to the per-job sender. ContextVar takes priority
        over instance state so concurrent agentic-pool jobs don't see each
        other's sender_id leaking through the shared dispatcher instance.

        Args:
            role: Optional role name for role-aware agents

        Returns:
            str: Resolved sender_id
        """
        if self.supports_role and role:
            suffix = None
            if self.session_id:
                # Strip user-scope suffix (::user_id) — only the base hash is needed
                suffix = self.session_id.split( "::" )[ 0 ] if "::" in self.session_id else self.session_id
            return build_sender_id( f"{self.agent_type}.{role}", suffix=suffix )
        ctx_value = ctx_sender_id.get()
        if ctx_value is not None:
            return ctx_value
        return self.sender_id

    def _resolve_target_user( self ) -> Optional[ str ]:
        """
        Resolve the target_user for a notification call.

        Priority: ContextVar > self.target_user > None. ContextVar set by
        agentic jobs at execution start; self.target_user is the legacy
        instance attribute mutated by single-job CLI / non-pool callers.
        """
        ctx_value = ctx_target_user.get()
        if ctx_value is not None:
            return ctx_value
        return self.target_user

    def _resolve_session_name( self, override: Optional[ str ] = None ) -> Optional[ str ]:
        """
        Resolve session_name for a notification call.

        Priority: explicit override arg > ContextVar > self.session_name.
        Per-call override wins (callers that want a one-off session name);
        ContextVar wins over instance state for per-task isolation.
        """
        if override is not None:
            return override
        ctx_value = ctx_session_name.get()
        if ctx_value is not None:
            return ctx_value
        return self.session_name

    def _resolve_routing( self, target_user: Optional[ str ] ) -> tuple:
        """
        Resolve the effective target_user for a blocking voice call.

        When target_user is a configured service account AND an operator fallback
        is configured, swap to the operator so TTS reaches a human. See Bug 10
        (2026-04-15): service accounts have no WebSocket sessions, causing
        /api/notify to 503 on blocking calls.

        Reads two INI keys (cached on first call):
            - voice gate operator email       : str   (blank disables rerouting)
            - voice gate service accounts     : comma-separated list of emails

        Args:
            target_user: The user the caller originally intended to notify.

        Returns:
            tuple: ( effective_target, was_redirected, original_target )
                   - effective_target is the email the request should hit
                   - was_redirected is True iff a swap happened
                   - original_target is the input target_user unchanged
        """
        if not target_user:
            return ( target_user, False, target_user )

        # Lazy config load — ConfigurationManager is a global singleton so we
        # only actually parse the INI once per process.
        try:
            from cosa.config.configuration_manager import ConfigurationManager
            cfg = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
            operator = cfg.get( "voice gate operator email", default=None, return_type="string" ) or ""
            accounts_raw = cfg.get( "voice gate service accounts", default=None, return_type="string" ) or ""
        except Exception as e:
            # Never let a config read failure block notification dispatch.
            logger.warning( f"_resolve_routing config read failed: {e}" )
            return ( target_user, False, target_user )

        operator = operator.strip()
        if not operator:
            return ( target_user, False, target_user )

        service_set = { a.strip().lower() for a in accounts_raw.split( "," ) if a.strip() }
        if target_user.lower() in service_set:
            print( f"[NOTIFY] Operator routing: {target_user} (service account) → {operator}" )
            return ( operator, True, target_user )

        return ( target_user, False, target_user )

    # =========================================================================
    # Primary Interface Methods
    # =========================================================================

    async def notify_progress(
        self,
        message: str,
        priority: str = None,
        abstract: Optional[ str ] = None,
        session_name: Optional[ str ] = None,
        job_id: Optional[ str ] = None,
        queue_name: Optional[ str ] = None,
        progress_group_id: Optional[ str ] = None,
        role: str = None
    ) -> None:
        """
        Send fire-and-forget progress notification.

        Non-blocking — runs in thread pool to avoid blocking event loop.

        Args:
            message: Progress message to announce
            priority: "low", "medium", "high", or "urgent" (default: self.default_priority)
            abstract: Optional supplementary context (markdown, URLs)
            session_name: Optional human-readable session name for UI display
            job_id: Optional agentic job ID for routing to job cards
            queue_name: Optional queue where job is running
            progress_group_id: Optional progress group ID for in-place DOM updates
            role: Optional agent role (for role-aware dispatchers)
        """
        try:
            request = AsyncNotificationRequest(
                message           = message,
                notification_type = NotificationType.PROGRESS,
                priority          = NotificationPriority( priority or self.default_priority ),
                sender_id         = self._resolve_sender_id( role ),
                target_user       = self._resolve_target_user(),
                abstract          = abstract,
                session_name      = self._resolve_session_name( session_name ),
                job_id            = job_id,
                queue_name        = queue_name,
                progress_group_id = progress_group_id,
            )

            await asyncio.to_thread( _notify_user_async, request )

        except Exception as e:
            logger.warning( f"Failed to send progress notification: {e}" )

    async def ask_confirmation(
        self,
        question: str,
        default: str = "no",
        timeout: int = 60,
        abstract: Optional[ str ] = None,
        job_id: Optional[ str ] = None,
        role: str = None,
        priority: str = None
    ) -> bool:
        """
        Ask a yes/no question and return boolean result.

        Args:
            question: The yes/no question to ask
            default: Default answer if timeout ("yes" or "no")
            timeout: Seconds to wait for response
            abstract: Optional supplementary context
            job_id: Optional job ID for routing
            role: Optional agent role (for role-aware dispatchers)
            priority: "low"/"medium"/"high"/"urgent" (default: "high" for blocking calls)

        Returns:
            bool: True if user said yes, False otherwise
        """
        try:
            effective_target, was_redirected, original_target = self._resolve_routing( self._resolve_target_user() )
            if was_redirected:
                abstract = _prepend_operator_routing( abstract, original_target )
            request = NotificationRequest(
                message           = question,
                response_type     = ResponseType.YES_NO,
                notification_type = NotificationType.CUSTOM,
                priority          = NotificationPriority( priority or self.default_priority or "high" ),
                timeout_seconds   = timeout,
                response_default  = default,
                sender_id         = self._resolve_sender_id( role ),
                target_user       = effective_target,
                abstract          = abstract,
                job_id            = job_id,
            )

            response: NotificationResponse = await asyncio.to_thread( _notify_user_sync, request )

            if response.exit_code == 0 and response.response_value:
                return response.response_value.lower().strip().startswith( "yes" )

            # exit_code == 2 is the MCP server's explicit "user-unavailable timeout"
            # signal. Raise VoiceGateTimeoutError so checkpoint-resume can trigger
            # a clean stall instead of silently falling back to the default.
            # (Session 9056c113 Phase 1 — doc 16). Lazy import to avoid circular
            # dependency (TFE state imports utils).
            if response.exit_code == 2:
                from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError
                raise VoiceGateTimeoutError(
                    phase   = "confirmation",
                    message = f"ask_confirmation timeout after {timeout}s — MCP exit_code=2"
                )

            # Bug 12 (2026-04-16): any other non-0 exit code (HTTP 503 "User is
            # offline", connection errors, etc.) is a "no answer received"
            # condition for the orchestrator — NOT an explicit user decline.
            # Raise so checkpoint-resume fires instead of silently applying
            # the default. Mirrors present_choices catch-all (line ~453).
            from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError
            raise VoiceGateTimeoutError(
                phase   = "confirmation",
                message = (
                    f"ask_confirmation received no answer "
                    f"(exit_code={response.exit_code}, status={response.status}) "
                    f"after {timeout}s"
                )
            )

        except Exception as e:
            # VoiceGateTimeoutError must propagate up to the orchestrator gates;
            # don't swallow it here.
            from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError
            if isinstance( e, VoiceGateTimeoutError ):
                raise
            # Bug 13 (2026-04-16): Pydantic ValidationError fires BEFORE the MCP
            # call (e.g. abstract > 5000 chars). Pre-MCP failures also mean
            # "voice gate could not fire" — raise VoiceGateTimeoutError so the
            # orchestrator stalls with a checkpoint instead of silently
            # applying the default. Matches Bug 12 stall philosophy.
            from pydantic import ValidationError
            if isinstance( e, ( ValidationError, ConnectionError ) ):
                raise VoiceGateTimeoutError(
                    phase   = "confirmation",
                    message = f"ask_confirmation pre-MCP failure ({type( e ).__name__}): {str( e )[:200]}"
                )
            logger.warning( f"ask_confirmation failed: {e}" )
            return default == "yes"

    async def get_feedback(
        self,
        prompt: str,
        timeout: int = 300,
        job_id: Optional[ str ] = None,
        role: str = None,
        priority: str = None,
        response_default: Optional[ str ] = None
    ) -> Optional[ str ]:
        """
        Get open-ended feedback from user via voice.

        Args:
            prompt: Text to speak to the user
            timeout: Maximum seconds to wait
            job_id: Optional job ID for routing to job cards
            role: Optional agent role (for role-aware dispatchers)
            priority: "low"/"medium"/"high"/"urgent" (default: "high" for blocking calls)
            response_default: If set AND user is offline, /api/notify returns 200
                              with default rather than 503. Leave None to preserve
                              the 503-for-offline behavior (caller handles stall).

        Returns:
            str or None: User's transcribed voice response
        """
        try:
            effective_target, was_redirected, _original_target = self._resolve_routing( self._resolve_target_user() )
            request = NotificationRequest(
                message           = prompt,
                response_type     = ResponseType.OPEN_ENDED,
                notification_type = NotificationType.CUSTOM,
                priority          = NotificationPriority( priority or self.default_priority or "high" ),
                timeout_seconds   = timeout,
                response_default  = response_default,
                sender_id         = self._resolve_sender_id( role ),
                target_user       = effective_target,
                job_id            = job_id,
            )

            response: NotificationResponse = await asyncio.to_thread( _notify_user_sync, request )

            if response.exit_code == 0:
                return response.response_value

            # exit_code == 2 is the MCP server's explicit "user-unavailable
            # timeout" signal. Raise VoiceGateTimeoutError so checkpoint-resume
            # can trigger a clean stall instead of silently returning None.
            if response.exit_code == 2:
                from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError
                raise VoiceGateTimeoutError(
                    phase   = "feedback",
                    message = f"get_feedback timeout after {timeout}s — MCP exit_code=2"
                )

            # Bug 12 (2026-04-16): any other non-0 exit code (HTTP 503 "User is
            # offline", connection errors, etc.) is a "no answer received"
            # condition for the orchestrator. Raise so checkpoint-resume fires
            # instead of silently returning None. Mirrors present_choices
            # catch-all and ask_confirmation Bug 12 fix.
            from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError
            raise VoiceGateTimeoutError(
                phase   = "feedback",
                message = (
                    f"get_feedback received no answer "
                    f"(exit_code={response.exit_code}, status={response.status}) "
                    f"after {timeout}s"
                )
            )

        except Exception as e:
            # VoiceGateTimeoutError must propagate up to the orchestrator gates;
            # don't swallow it here.
            from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError
            if isinstance( e, VoiceGateTimeoutError ):
                raise
            # Bug 13 (2026-04-16): Pre-MCP ValidationError → stall, not silent default.
            from pydantic import ValidationError
            if isinstance( e, ( ValidationError, ConnectionError ) ):
                raise VoiceGateTimeoutError(
                    phase   = "feedback",
                    message = f"get_feedback pre-MCP failure ({type( e ).__name__}): {str( e )[:200]}"
                )
            logger.warning( f"get_feedback failed: {e}" )
            return None

    async def present_choices(
        self,
        questions: list,
        timeout: int = 120,
        title: Optional[ str ] = None,
        abstract: Optional[ str ] = None,
        job_id: Optional[ str ] = None,
        role: str = None,
        priority: str = None,
        response_default: Optional[ str ] = None
    ) -> dict:
        """
        Present multiple-choice questions and get user's selection.

        Args:
            questions: List of question objects with options
            timeout: Seconds to wait for response
            title: Optional title for the notification
            abstract: Optional supplementary context
            job_id: Optional job ID for routing to job cards
            role: Optional agent role (for role-aware dispatchers)
            priority: "low"/"medium"/"high"/"urgent" (default: "high" for blocking calls)
            response_default: If set AND user is offline, /api/notify returns 200
                              with this default rather than 503. Pass literal "{}"
                              (empty JSON) for the clean-stall path — dispatcher
                              interprets empty answers as timeout via Bug 7
                              normalization → VoiceGateTimeoutError.

        Returns:
            dict: {"answers": {...}} with selections keyed by header
        """
        try:
            effective_target, was_redirected, original_target = self._resolve_routing( self._resolve_target_user() )
            if was_redirected:
                abstract = _prepend_operator_routing( abstract, original_target )

            message = format_questions_for_tts( questions )

            request = NotificationRequest(
                message           = message,
                response_type     = ResponseType.MULTIPLE_CHOICE,
                notification_type = NotificationType.CUSTOM,
                priority          = NotificationPriority( priority or self.default_priority or "high" ),
                timeout_seconds   = timeout,
                response_default  = response_default,
                response_options  = convert_questions_for_api( questions ),
                sender_id         = self._resolve_sender_id( role ),
                target_user       = effective_target,
                abstract          = abstract,
                title             = title,
                job_id            = job_id,
            )

            response: NotificationResponse = await asyncio.to_thread( _notify_user_sync, request )

            if response.exit_code == 0 and response.response_value:
                try:
                    parsed = json.loads( response.response_value )
                except json.JSONDecodeError:
                    return { "answers": { "response": response.response_value } }

                # Defensive normalization (Session 2026-04-15): treat an empty
                # answers payload as a no-answer timeout, not an explicit empty
                # selection. Users never click "submit with nothing selected";
                # an empty dict means the MCP returned exit_code=0 before the
                # human interacted (observed with 3s timeout regression). This
                # keeps VoiceGateTimeoutError as the single signal for "no
                # answer" so checkpoint-resume fires reliably.
                answers = parsed.get( "answers", {} ) if isinstance( parsed, dict ) else {}
                if not answers or all( not v for v in answers.values() ):
                    from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError
                    raise VoiceGateTimeoutError(
                        phase     = "choices",
                        message   = (
                            f"present_choices returned empty answers after {timeout}s — "
                            f"treating as no-response timeout"
                        ),
                        delivered = True,   # exit_code 0 came back → the ask reached a human, who did not answer (row 38a0b373)
                    )
                return parsed

            # exit_code == 2 is the MCP server's explicit timeout signal.
            # Raise VoiceGateTimeoutError for checkpoint-resume.
            if response.exit_code == 2:
                from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError
                raise VoiceGateTimeoutError(
                    phase     = "choices",
                    message   = f"present_choices timeout after {timeout}s — MCP exit_code=2",
                    delivered = True,   # exit_code 2 is the MCP's own timeout signal → the ask reached the MCP/human (row 38a0b373)
                )

            # Catch-all (no response value at all): also treat as timeout so
            # checkpoint-resume applies instead of silently falling through
            # to an empty-selection completion.
            from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError
            raise VoiceGateTimeoutError(
                phase   = "choices",
                message = f"present_choices returned no response after {timeout}s"
            )

        except Exception as e:
            from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError
            if isinstance( e, VoiceGateTimeoutError ):
                raise
            # Bug 13 (2026-04-16): Pydantic ValidationError (e.g. abstract > 5000
            # chars on large TFE proposal lists) fires BEFORE the MCP call, so the
            # voice gate never reaches the user. Swallowing to empty-answers
            # masquerades as "user selected nothing" and the job wrongly finalizes
            # `status=completed` (observed in tfe-e4c73d5c on 2026-04-16). Treat
            # pre-MCP failures as "voice gate unreachable" and raise
            # VoiceGateTimeoutError so the orchestrator stalls with a checkpoint.
            from pydantic import ValidationError
            if isinstance( e, ( ValidationError, ConnectionError ) ):
                raise VoiceGateTimeoutError(
                    phase   = "choices",
                    message = f"present_choices pre-MCP failure ({type( e ).__name__}): {str( e )[:200]}"
                )
            logger.warning( f"present_choices failed: {e}" )
            return { "answers": {} }


def quick_smoke_test():
    """Quick smoke test for AgentNotificationDispatcher."""
    import inspect
    import cosa.utils.util as cu

    cu.print_banner( "AgentNotificationDispatcher Smoke Test", prepend_nl=True )

    try:
        # Test 1: Basic instantiation
        print( "Testing basic instantiation..." )
        d = AgentNotificationDispatcher( agent_type="deep.research" )
        assert "deep.research@" in d.sender_id
        assert ".deepily.ai" in d.sender_id
        assert d.supports_role is False
        assert d.default_priority == "medium"
        print( f"  sender_id: {d.sender_id}" )

        # Test 1b: target_user defaults to None
        print( "Testing target_user default..." )
        assert d.target_user is None
        print( "  target_user is None by default" )

        # Test 1c: target_user is mutable
        print( "Testing target_user mutability..." )
        d.target_user = "test@example.com"
        assert d.target_user == "test@example.com"
        d.target_user = None
        print( "  target_user can be set and cleared" )

        # Test 2: With suffix
        print( "Testing instantiation with suffix..." )
        d = AgentNotificationDispatcher( agent_type="podcast.gen", default_suffix="cli" )
        assert d.sender_id.endswith( "#cli" )
        print( f"  sender_id: {d.sender_id}" )

        # Test 3: Role-aware
        print( "Testing role-aware dispatcher..." )
        d = AgentNotificationDispatcher( agent_type="swe", supports_role=True, default_priority="high" )
        assert d.supports_role is True
        assert d.default_priority == "high"
        resolved = d._resolve_sender_id( "lead" )
        assert "swe.lead@" in resolved
        print( f"  role='lead' -> {resolved}" )

        # Test 4: Role-aware with session_id
        print( "Testing role-aware with session_id..." )
        d.session_id = "abc123::user42"
        resolved = d._resolve_sender_id( "coder" )
        assert "swe.coder@" in resolved
        assert resolved.endswith( "#abc123" )
        assert "::" not in resolved
        print( f"  role='coder', session_id='abc123::user42' -> {resolved}" )

        # Test 5: build_sender_id helper
        print( "Testing build_sender_id helper..." )
        d = AgentNotificationDispatcher( agent_type="deep.research" )
        new_sid = d.build_sender_id( suffix="jobhash123" )
        assert new_sid.endswith( "#jobhash123" )
        print( f"  build_sender_id(suffix='jobhash123') -> {new_sid}" )

        # Test 6: Mutable sender_id
        print( "Testing mutable sender_id..." )
        d.sender_id = d.build_sender_id( suffix="custom" )
        assert d.sender_id.endswith( "#custom" )
        print( f"  Mutated sender_id: {d.sender_id}" )

        # Test 7: Async method signatures
        print( "Testing async method signatures..." )
        assert inspect.iscoroutinefunction( d.notify_progress )
        assert inspect.iscoroutinefunction( d.ask_confirmation )
        assert inspect.iscoroutinefunction( d.get_feedback )
        assert inspect.iscoroutinefunction( d.present_choices )
        print( "  All methods are async" )

        # Test 8: notify_progress signature has all expected params
        print( "Testing notify_progress signature..." )
        sig = inspect.signature( d.notify_progress )
        expected = [ "message", "priority", "abstract", "session_name", "job_id", "queue_name", "progress_group_id", "role" ]
        for param in expected:
            assert param in sig.parameters, f"Missing: {param}"
        print( "  All expected parameters present" )

        # Test 9: Standard dispatcher (no role) ignores role param
        print( "Testing standard dispatcher ignores role..." )
        d = AgentNotificationDispatcher( agent_type="deep.research" )
        d.sender_id = "deep.research@lupin.deepily.ai#test"
        resolved = d._resolve_sender_id( role="anything" )
        assert resolved == "deep.research@lupin.deepily.ai#test"
        print( "  Role ignored for non-role-aware dispatcher" )

        print( "\n  AgentNotificationDispatcher smoke test completed successfully" )

    except Exception as e:
        print( f"\n  Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
