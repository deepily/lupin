"""
Shared fix executor for agentic repair agents.

Extracted from cosa.agents.bug_fix_expediter.orchestrator.run_fix (Session
1cfcdf73, 2026-04-10) so BugFixExpediter and TestFixExpediter can share the
same Coder+Tester retry loop, redelegation logic, SafetyGuard wiring, and
escalation handling.

This module is a PEER of the agent packages — it does not import from any
specific agent's prompts. Agent-specific prompt builders and system prompts
are registered via `FIX_PROMPT_BUILDERS` at import time, keyed by an agent
string ("bfe", "tfe", etc.).

The caller (agent orchestrator) is responsible for:
  - State machine transitions (BFEPhase.PROPOSING → FIXING, etc.)
  - Plan doc update via PlanWriter (user_email source is agent-specific)
  - Completion notification
  - Providing the delegate_to_coder_fn and verify_fix_fn callbacks that do
    the actual SDK invocation (so test patches on orchestrator methods
    continue to work and so agent-specific options builders live in the
    agent package)
  - Constructing FixExecutor with the right config + callbacks

FixExecutor owns:
  - SafetyGuard construction
  - The main retry loop: initial coder → tester → redelegate → escalate
  - SafetyLimitError + general exception handling
  - Returning (fix_result, files_changed)
  - Populating self.last_coder_output / self.last_files_changed

See:
  - src/rnd/v0.1.6/2026.04.10-test-fix-expediter/02-fix-executor-extraction-plan.md
  - src/rnd/v0.1.6/2026.04.10-test-fix-expediter/06-phase3-fix-delegation-plan.md
"""

import logging
from typing import Callable, Optional

import cosa.utils.util as cu

# SWE Team reuse — safety
from cosa.agents.swe_team.safety_limits import SafetyGuard, SafetyLimitError

logger = logging.getLogger( __name__ )


def _tail_lines( text: Optional[ str ], max_lines: int = 12, max_chars: int = 2000 ) -> str:
    """
    Return the last `max_lines` of `text`, bounded by `max_chars`.

    Used to distill tester_output (potentially tens of KB of pytest output) into
    a triage-sized tail that fits in a notification abstract + the end-of-run
    report abstract. Preserves the FAILED line + traceback tail, which is the
    signal humans actually read.

    Requires:
        - max_lines > 0
        - max_chars > 0

    Ensures:
        - Returns "" if text is None or empty
        - Returns at most max_lines lines and max_chars characters
        - Preserves the tail of the input, not the head
    """
    if not text: return ""
    lines = text.splitlines()
    tail = "\n".join( lines[ -max_lines: ] )
    if len( tail ) > max_chars:
        tail = "…\n" + tail[ -max_chars: ]
    return tail


# ─────────────────────────────────────────────────────────────────────────
# Polymorphic prompt registry
# ─────────────────────────────────────────────────────────────────────────

FIX_PROMPT_BUILDERS: dict = {}


def register_fix_prompts(
    key: str,
    *,
    build_fix_prompt: Callable,
    build_verify_prompt: Callable,
    build_redelegate_prompt: Callable,
    coder_system_prompt: str,
    tester_system_prompt: str,
) -> None:
    """
    Register agent-specific prompt builders + system prompts under a key.

    Agent packages call this at import time (e.g., BFE's prompts/fix.py
    registers under key="bfe"; TFE's prompts/fix.py registers under "tfe").

    The `coder_system_prompt` and `tester_system_prompt` are kept in the
    registry for any agent that wants to introspect them, even though
    FixExecutor doesn't use them directly (the agent's options-builder
    does). Keeping them together simplifies auditing.

    Requires:
        - key is a non-empty string
        - all callables + strings are truthy

    Ensures:
        - FIX_PROMPT_BUILDERS[key] is populated with the full bundle
        - Overwrites silently if key already exists (supports re-import)
    """
    FIX_PROMPT_BUILDERS[ key ] = {
        "build_fix_prompt"         : build_fix_prompt,
        "build_verify_prompt"      : build_verify_prompt,
        "build_redelegate_prompt"  : build_redelegate_prompt,
        "coder_system_prompt"      : coder_system_prompt,
        "tester_system_prompt"     : tester_system_prompt,
    }


# ─────────────────────────────────────────────────────────────────────────
# FixExecutor
# ─────────────────────────────────────────────────────────────────────────


class FixExecutor:
    """
    Shared Coder+Tester retry loop executor.

    Requires:
        - config has attributes: max_fix_attempts, wall_clock_timeout_secs,
          feedback_timeout_seconds
        - fix_context is any object (passed through to the agent's prompt
          builders — BFE passes DeadJobContext, TFE passes TestRemediation
          cluster info)
        - prompt_builder_key is registered in FIX_PROMPT_BUILDERS
        - delegate_to_coder_fn: async callable(voice_io, prompt, guard,
          cosa_interface) -> (coder_output: str, files_changed: list)
        - verify_fix_fn: async callable(voice_io, selected_fix, coder_output,
          files_changed, guard, cosa_interface) -> (passed: bool, tester_output: str)
        - voice_io_module and cosa_interface_module are the agent's modules
        - notify_fn: async callable(voice_io, message, priority, abstract=None)
        - is_cancelled_fn: sync callable() -> bool

    Ensures:
        - execute_fix returns (FixResult, files_changed_list)
        - Never raises from execute_fix — all failures surface via FixResult
        - Respects cancellation via is_cancelled_fn
        - Populates self.last_coder_output and self.last_files_changed for
          caller inspection after the call
    """

    def __init__(
        self,
        config,
        fix_context,
        job_id: str,
        prompt_builder_key: str,
        voice_io_module,
        cosa_interface_module,
        notify_fn: Callable,
        is_cancelled_fn: Callable,
        delegate_to_coder_fn: Callable,
        verify_fix_fn: Callable,
        debug: bool = False,
        verbose: bool = False,
        worktree_cwd: Optional[ str ] = None,
    ):
        self.config              = config
        self.fix_context         = fix_context
        self.job_id              = job_id
        self.prompt_builder_key  = prompt_builder_key
        self._voice_io           = voice_io_module
        self._cosa_interface     = cosa_interface_module
        self._notify             = notify_fn
        self._is_cancelled       = is_cancelled_fn
        self._delegate_to_coder  = delegate_to_coder_fn
        self._verify_fix         = verify_fix_fn
        self.debug               = debug
        self.verbose             = verbose

        # Bug 9 (2026-04-16): isolation cwd for Phase 3 SDK delegations.
        # When set, the orchestrator's _delegate_to_coder / _verify_fix
        # callbacks must use this path as cwd when constructing the SDK
        # ClaudeAgentOptions. Value is resolved by WorktreeContext at the
        # orchestrator layer. None = live working tree (pre-Bug-9 behavior).
        self.worktree_cwd = worktree_cwd

        # Populated after execute_fix
        self.last_coder_output   = ""
        self.last_files_changed: list = []

        # Resolve prompt bundle at construction for fast-fail
        if prompt_builder_key not in FIX_PROMPT_BUILDERS:
            raise KeyError(
                f"FixExecutor: prompt_builder_key '{prompt_builder_key}' not registered. "
                f"Available keys: {list( FIX_PROMPT_BUILDERS.keys() )}. "
                f"Agent prompt module must call register_fix_prompts() at import time."
            )
        self._prompts = FIX_PROMPT_BUILDERS[ prompt_builder_key ]

    # ───── public API ─────

    async def execute_fix(
        self,
        diagnosis,
        selected_fix,
    ):
        """
        Run the Coder+Tester retry loop and return the outcome.

        Requires:
            - diagnosis has fields used by the agent's build_fix_prompt
            - selected_fix is a ProposedFix with .title, .fix_type, .risk_level

        Ensures:
            - Returns tuple (FixResult, list[str]) = (result, files_changed)
            - self.last_coder_output and self.last_files_changed populated

        Args:
            diagnosis: DiagnosisResult from the diagnosis phase
            selected_fix: User-approved ProposedFix from the proposal phase

        Returns:
            tuple: (FixResult, list of files modified)
        """
        # Lazy-import FixResult from BFE state — both BFE and TFE share this type
        # (TFE extends ProposedFix with cluster_id but reuses FixResult as-is).
        from cosa.agents.bug_fix_expediter.state import FixResult

        # Create SafetyGuard for fix phase (fresh counters)
        guard = SafetyGuard(
            max_iterations = self.config.max_fix_attempts * 10,
            max_failures   = self.config.max_fix_attempts + 1,
            timeout_secs   = self.config.wall_clock_timeout_secs,
        )

        coder_output  = ""
        files_changed = []
        fix_result    = FixResult( applied=False, success=False )

        build_fix_prompt        = self._prompts[ "build_fix_prompt" ]
        build_redelegate_prompt = self._prompts[ "build_redelegate_prompt" ]

        try:
            # --- Initial coder delegation ---
            prompt = build_fix_prompt( selected_fix, diagnosis, self.fix_context )

            coder_output, files_changed = await self._delegate_to_coder(
                self._voice_io, prompt, guard, self._cosa_interface
            )

            if not coder_output:
                fix_result = FixResult(
                    applied=False, success=False,
                    details="Coder produced no output",
                )
            else:
                # --- Coder-Tester retry loop ---
                for iteration in range( 1, self.config.max_fix_attempts + 1 ):

                    if self._is_cancelled():
                        fix_result = FixResult(
                            applied=True, success=False,
                            details="Cancelled during verification",
                        )
                        break

                    if self.debug: print( f"[FixExecutor] Verification iteration {iteration}/{self.config.max_fix_attempts}" )

                    await self._notify(
                        self._voice_io,
                        f"Verifying fix (iteration {iteration}/{self.config.max_fix_attempts})...",
                        priority="low",
                    )

                    # --- Tester verification ---
                    passed, tester_output = await self._verify_fix(
                        self._voice_io, selected_fix, coder_output, files_changed,
                        guard, self._cosa_interface
                    )

                    if passed:
                        guard.record_success()
                        fix_result = FixResult(
                            applied=True, success=True,
                            details=f"Fix verified on iteration {iteration}",
                            retry_eligible=True,
                            attempts=iteration,
                        )
                        break

                    # --- Max iterations check ---
                    if iteration >= self.config.max_fix_attempts:
                        guard.record_failure( "verification failed after max iterations" )

                        # Auto-reject + fire-and-forget telemetry (no operator gate).
                        # Last tester_output is retained on FixResult so the end-of-run
                        # report can surface it without a worktree dig.
                        stderr_tail = _tail_lines( tester_output, max_lines=12, max_chars=2000 )
                        await self._notify(
                            self._voice_io,
                            f"Fix Verification Failed: '{selected_fix.title}' auto-rejected after {iteration} attempt(s)",
                            priority="low",
                            abstract=(
                                f"**Fix**: {selected_fix.title}\n"
                                f"**Attempts**: {iteration}\n"
                                f"**Disposition**: auto-rejected (no operator gate)\n"
                                f"**Last failure** (last 12 lines):\n```\n{stderr_tail}\n```"
                            ),
                        )

                        fix_result = FixResult(
                            applied=False, success=False,
                            details=f"Auto-rejected after {iteration} verification attempt(s)",
                            attempts=iteration,
                            last_stderr=stderr_tail,
                        )

                        break

                    # --- Re-delegate with feedback ---
                    await self._notify(
                        self._voice_io,
                        "Tests failed — re-delegating to coder with feedback...",
                        priority="low",
                    )

                    redelegate_prompt = build_redelegate_prompt(
                        selected_fix, coder_output, tester_output, iteration + 1
                    )
                    coder_output, new_files = await self._delegate_to_coder(
                        self._voice_io, redelegate_prompt, guard, self._cosa_interface
                    )
                    files_changed.extend( f for f in new_files if f not in files_changed )

                    if not coder_output:
                        guard.record_failure( "coder re-delegation produced no output" )
                        fix_result = FixResult(
                            applied=False, success=False,
                            details="Coder re-delegation failed",
                        )
                        break

        except SafetyLimitError as e:
            logger.warning( f"Safety limit reached: {e}" )
            await self._notify(
                self._voice_io, f"Safety limit: {e}", priority="urgent"
            )
            fix_result = FixResult(
                applied=False, success=False, details=f"Safety limit: {e}"
            )

        except Exception as e:
            logger.error( f"Fix phase error: {e}" )
            fix_result = FixResult(
                applied=False, success=False, details=str( e )
            )

        # Store for caller inspection
        self.last_coder_output  = coder_output
        self.last_files_changed = files_changed

        return ( fix_result, files_changed )


def quick_smoke_test():
    """Quick smoke test for shared FixExecutor (construction + registry)."""
    cu.print_banner( "Shared FixExecutor Smoke Test", prepend_nl=True )

    try:
        # 1: Registry state
        initial_keys = set( FIX_PROMPT_BUILDERS.keys() )
        print( f"✓ FIX_PROMPT_BUILDERS current keys: {initial_keys}" )

        # 2: Register a synthetic key
        def _fake_fix( fix, diag, ctx ): return f"FIX: {fix.title}"
        def _fake_verify( fix, out, files ): return f"VERIFY: {fix.title}"
        def _fake_redelegate( fix, out, feedback, it ): return f"REDELEGATE: {fix.title} iter {it}"

        register_fix_prompts(
            "smoke_test_key",
            build_fix_prompt=_fake_fix,
            build_verify_prompt=_fake_verify,
            build_redelegate_prompt=_fake_redelegate,
            coder_system_prompt="Test coder prompt",
            tester_system_prompt="Test tester prompt",
        )
        assert "smoke_test_key" in FIX_PROMPT_BUILDERS
        assert FIX_PROMPT_BUILDERS[ "smoke_test_key" ][ "coder_system_prompt" ] == "Test coder prompt"
        print( "✓ register_fix_prompts works" )

        # 3: Unknown key raises at construction
        from types import SimpleNamespace

        fake_config = SimpleNamespace(
            max_fix_attempts         = 2,
            wall_clock_timeout_secs  = 60,
            feedback_timeout_seconds = 30,
        )
        fake_ctx = SimpleNamespace( user_email="test@test.com" )

        async def _noop( *args, **kwargs ): return None
        def _never_cancel(): return False

        try:
            FixExecutor(
                config=fake_config,
                fix_context=fake_ctx,
                job_id="test-job",
                prompt_builder_key="nonexistent_key",
                voice_io_module=None,
                cosa_interface_module=None,
                notify_fn=_noop,
                is_cancelled_fn=_never_cancel,
                delegate_to_coder_fn=_noop,
                verify_fix_fn=_noop,
            )
            print( "✗ Expected KeyError for unknown builder key" )
            raise AssertionError( "Should have raised" )
        except KeyError as e:
            print( f"✓ Unknown builder key raises KeyError: {str( e )[ :80 ]}" )

        # 4: Valid construction with registered key
        executor = FixExecutor(
            config=fake_config,
            fix_context=fake_ctx,
            job_id="test-job",
            prompt_builder_key="smoke_test_key",
            voice_io_module=None,
            cosa_interface_module=None,
            notify_fn=_noop,
            is_cancelled_fn=_never_cancel,
            delegate_to_coder_fn=_noop,
            verify_fix_fn=_noop,
        )
        assert executor.prompt_builder_key == "smoke_test_key"
        assert executor.last_coder_output == ""
        assert executor.last_files_changed == []
        print( "✓ FixExecutor construction with valid key works" )

        # 5: Cleanup
        del FIX_PROMPT_BUILDERS[ "smoke_test_key" ]

        print( "\n✓ Shared FixExecutor smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
