"""
Test-aware fix application prompts for TFE Phase 3.

Coder + Tester prompts tailored for the "make N failing tests pass" workflow,
registered into the shared `FIX_PROMPT_BUILDERS` registry under key `"tfe"` at
import time so `shared.fix_executor.FixExecutor` can dispatch to them.

Critical differences from BFE's prompts:
  - The tester runs `pytest -k` filtered by the cluster's failing test names,
    not a re-run of the original agentic job
  - The coder is instructed that "success" means a specific set of tests pass,
    not that the dead job restarts cleanly

Design: src/rnd/v0.1.6/2026.04.10-test-fix-expediter/06-phase3-fix-delegation-plan.md
        src/rnd/v0.1.6/2026.04.10-test-fix-expediter/10-prompt-design.md#4
"""


CODER_SYSTEM_PROMPT = """You are a senior software engineer applying a targeted fix to make a set of failing pytest tests pass.

You have full edit access via Read, Edit, and Bash tools. Apply ONLY the changes described in the proposed fix — no extra refactoring, no unrelated cleanup, no scope expansion.

## Efficiency rules (cost-conscious — follow these strictly)

1. **Commit to the Edit fast.** After Reading the files named in the proposal's "Proposed changes" section, make your Edit within 3 tool calls. Do not re-read files you've already read in this session.
2. **Read targeted, not broad.** Read only the exact file paths named in the proposal. Do NOT Grep the codebase for related code unless the diagnosis explicitly mentions other callers.
3. **One py_compile per file, not per edit.** After all edits to a file are complete, run py_compile once on that file via `python -c "import py_compile; py_compile.compile('path/to/file.py', doraise=True)"`. For single-line test-value changes (e.g. `== 9` → `== 10`) py_compile is optional.
4. **Do NOT run pytest yourself.** The Tester agent will verify after you finish. Running pytest in the Coder session is redundant and costs turns.
5. **If the proposal is unclear, STOP.** If the named files don't contain the described code, output "Proposal unclear: <reason>" in your summary and do not make speculative changes.

## Behavior rules

6. **Do not modify test files** unless the `fix_type` is `test_patch`. If fix_type is `code_patch`, the tests are correct and your code change should make them pass.
7. **Do not run destructive commands** (rm -rf, git push, git reset, etc.).
8. **Summarize at the end.** After all edits, output a short summary of what you changed and list every file you modified.

## Success criteria

The failing tests in this cluster should pass after your changes. The Tester agent will verify by running `pytest -k "<test_names>"` against the affected tests. If those specific tests pass, your fix is successful.

Do NOT aim to make the entire test suite green — only the tests in this cluster. Other failures are out of scope.
"""


TESTER_SYSTEM_PROMPT = """You are a QA engineer verifying a test-failure fix by re-running the cluster's failing tests via pytest.

You have Read and Bash access. Your job: run `pytest -k` filtered by the cluster's failing test names, interpret the output, and report PASS or FAIL.

## Rules

1. **Read the changed files first.** Understand what the Coder changed.
2. **Construct the pytest `-k` filter** from the failing test names in the cluster. The `-k` expression uses `or` between names. Example:
   `pytest -v -k "test_refresh_returns_new_token or test_refresh_updates_expiry" src/tests/unit/test_auth.py`
3. **Run pytest** with `--tb=short` and a reasonable timeout (60s default). Wait for completion.
4. **Interpret the output.** "PASS" = every cluster test passed. "FAIL" = any cluster test still failed.
5. **Do NOT run the full test suite.** Only the cluster's tests are in scope.
6. **For fixture bugs:** if the fix is to a shared fixture used by tests beyond the cluster, you MAY broaden the `-k` filter to include the related tests — but only after reading the fixture to confirm it's shared.
7. **Report the verdict at the end** with a clear PASS or FAIL line, the pytest summary counts, and any failure details if FAIL.

## Success criteria

Verdict is PASS iff the cluster's failing tests now pass. Verdict is FAIL if any cluster test still fails OR if pytest itself errors out (collection failure, timeout, crash).
"""


def build_fix_prompt( selected_fix, diagnosis, fix_context ) -> str:
    """
    Build the Coder prompt for a single cluster fix.

    Requires:
        - selected_fix is a TFEProposedFix (or duck-typed equivalent) with
          .title, .description, .fix_type, .changes, .cluster_id attributes
        - diagnosis is a TestDiagnosisResult with .root_cause,
          .error_category, .affected_components
        - fix_context is a FailureCluster with .cluster_id, .failure_indices,
          .shared_error_signature, .hypothesis

    Ensures:
        - Returns a prompt string instructing the Coder to apply exactly the
          changes listed in `selected_fix.changes`
    """
    lines = []

    cluster_id = getattr( selected_fix, "cluster_id", None ) or getattr( fix_context, "cluster_id", "C?" )

    lines.append( f"Apply this fix for cluster {cluster_id}." )
    lines.append( "" )
    lines.append( f"## Fix: {selected_fix.title}" )
    lines.append( "" )
    lines.append( f"**Type**: {selected_fix.fix_type}" )
    lines.append( f"**Risk**: {getattr( selected_fix, 'risk_level', 'low' )}" )
    lines.append( f"**Confidence**: {selected_fix.confidence:.0%}" )
    lines.append( "" )
    lines.append( "## Description" )
    lines.append( "" )
    lines.append( selected_fix.description )
    lines.append( "" )

    # Diagnosis context
    lines.append( "## Diagnosis (from Phase 1)" )
    lines.append( "" )
    lines.append( f"Root cause: {diagnosis.root_cause}" )
    lines.append( f"Error category: {diagnosis.error_category}" )
    if diagnosis.affected_components:
        lines.append( f"Affected components: {diagnosis.affected_components}" )
    lines.append( "" )

    # Proposed changes
    if selected_fix.changes:
        lines.append( "## Proposed changes" )
        lines.append( "" )
        for i, change in enumerate( selected_fix.changes, start=1 ):
            file_path   = change.get( "file", "<unknown>" )
            action      = change.get( "action", "modify" )
            description = change.get( "description", "" )
            lines.append( f"{i}. **{file_path}** ({action}): {description}" )
        lines.append( "" )
    else:
        lines.append( "## Proposed changes: (none — retry or manual fix)" )
        lines.append( "" )

    lines.append(
        "Apply the changes exactly as described. Then output a summary of "
        "files modified and what you changed."
    )

    return "\n".join( lines )


def build_verification_prompt( selected_fix, coder_output, files_changed ) -> str:
    """
    Build the Tester prompt for verifying a cluster fix.

    The Tester will receive `selected_fix`, the Coder's summary, and the list
    of files the Coder modified. The prompt instructs it to construct a
    `pytest -k` filter from the cluster's failing test names (which the Coder
    baked into the description via the Phase 2 propose prompt) and run pytest
    against those specific tests.

    Requires:
        - selected_fix is a TFEProposedFix (duck-typed)
        - coder_output is the Coder's summary text
        - files_changed is a list of file paths the Coder modified

    Ensures:
        - Returns a prompt string for the Tester agent
    """
    lines = []

    cluster_id = getattr( selected_fix, "cluster_id", "C?" )

    lines.append( f"Verify the fix for cluster {cluster_id}: {selected_fix.title}" )
    lines.append( "" )

    lines.append( "## What the Coder did" )
    lines.append( "" )
    lines.append( coder_output[ :2000 ] if coder_output else "(Coder produced no summary)" )
    lines.append( "" )

    if files_changed:
        lines.append( "## Files modified" )
        lines.append( "" )
        for f in files_changed:
            lines.append( f"- `{f}`" )
        lines.append( "" )

    lines.append( "## Your task" )
    lines.append( "" )
    lines.append(
        "Run pytest targeting the failing tests in this cluster. Use `pytest -v -k` "
        "with an `or`-joined expression of the cluster's failing test names. Keep "
        "the filter as narrow as possible — do NOT run the full suite."
    )
    lines.append( "" )
    lines.append(
        "If the fix_type was `fixture_bug` and the fixture is shared across "
        "tests beyond this cluster, you may broaden the filter after reading "
        "the fixture to confirm the scope."
    )
    lines.append( "" )
    lines.append(
        "Report a clear PASS or FAIL verdict at the end of your output, with "
        "the pytest summary counts (e.g. `5 passed, 0 failed`) and details of "
        "any remaining failures."
    )

    return "\n".join( lines )


def build_redelegation_prompt(
    selected_fix,
    coder_output,
    tester_output,
    iteration: int,
) -> str:
    """
    Build the redelegation prompt when the Tester reports failure.

    Requires:
        - selected_fix is a TFEProposedFix (duck-typed)
        - coder_output is the prior Coder summary
        - tester_output is the Tester's failure report
        - iteration is 2-indexed (first redelegation = iteration 2)

    Ensures:
        - Returns a prompt string asking the Coder to refine the fix
    """
    lines = []

    cluster_id = getattr( selected_fix, "cluster_id", "C?" )

    lines.append(
        f"The previous fix attempt for cluster {cluster_id} did not pass "
        f"verification. This is iteration {iteration}."
    )
    lines.append( "" )

    lines.append( "## Your previous changes" )
    lines.append( "" )
    lines.append( coder_output[ :2000 ] if coder_output else "(no summary)" )
    lines.append( "" )

    lines.append( "## Tester feedback" )
    lines.append( "" )
    lines.append( tester_output[ :2000 ] if tester_output else "(no feedback)" )
    lines.append( "" )

    lines.append( "## Your task" )
    lines.append( "" )
    lines.append(
        "Analyze the Tester's feedback. Identify what's still wrong with the fix "
        "and apply refinements. Rules:"
    )
    lines.append( "" )
    lines.append( "1. **Do NOT modify test files** (unless fix_type is `test_patch`)." )
    lines.append( "2. **Fix only the failing tests in this cluster** — other tests are out of scope." )
    lines.append( "3. **If the diagnosis looks wrong**, report that in your summary — do NOT make increasingly desperate changes." )
    lines.append( "4. **Verify changes compile** before handing back to the Tester." )
    lines.append( "5. **Summarize what you changed** at the end." )

    return "\n".join( lines )


def quick_smoke_test():
    """Quick smoke test for TFE fix prompt builders."""
    import cosa.utils.util as cu
    from cosa.agents.test_fix_expediter.state import (
        FailureCluster, TestDiagnosisResult, TFEProposedFix,
    )

    cu.print_banner( "TFE Fix Prompts Smoke Test", prepend_nl=True )

    try:
        cluster = FailureCluster(
            cluster_id="C1", failure_indices=[ 0, 1 ],
            shared_error_signature="auth bug",
        )
        diagnosis = TestDiagnosisResult(
            cluster_id="C1",
            root_cause="Token refresh returns None",
            error_category="code_bug",
            confidence=0.85,
            affected_components=[ "src/cosa/auth/tokens.py" ],
        )
        fix = TFEProposedFix(
            cluster_id="C1",
            title="Replace `return None` with new token",
            description="Change line 42 of tokens.py",
            fix_type="code_patch",
            confidence=0.9,
            risk_level="low",
            estimated_effort="minutes",
            changes=[
                { "file": "src/cosa/auth/tokens.py", "action": "modify",
                  "description": "Line 42: return new_token instead of None" }
            ],
        )

        # 1: build_fix_prompt
        fix_prompt = build_fix_prompt( fix, diagnosis, cluster )
        assert "cluster C1" in fix_prompt
        assert "Replace `return None`" in fix_prompt
        assert "code_patch" in fix_prompt
        assert "Token refresh returns None" in fix_prompt
        assert "src/cosa/auth/tokens.py" in fix_prompt
        print( "✓ build_fix_prompt" )

        # 2: build_verification_prompt
        verify_prompt = build_verification_prompt(
            fix, "Modified line 42", [ "src/cosa/auth/tokens.py" ]
        )
        assert "cluster C1" in verify_prompt
        assert "pytest" in verify_prompt
        assert "PASS or FAIL" in verify_prompt
        assert "src/cosa/auth/tokens.py" in verify_prompt
        assert "Modified line 42" in verify_prompt
        print( "✓ build_verification_prompt" )

        # 3: build_redelegation_prompt
        redelegate_prompt = build_redelegation_prompt(
            fix, "Prior coder output", "Tests still failing", iteration=2
        )
        assert "iteration 2" in redelegate_prompt
        assert "Prior coder output" in redelegate_prompt
        assert "Tests still failing" in redelegate_prompt
        print( "✓ build_redelegation_prompt" )

        # 4: System prompts
        assert len( CODER_SYSTEM_PROMPT ) > 200
        assert len( TESTER_SYSTEM_PROMPT ) > 200
        assert "pytest -k" in TESTER_SYSTEM_PROMPT
        assert "targeted fix" in CODER_SYSTEM_PROMPT
        print( "✓ System prompts contain key themes" )

        # 5: Registration check (runs at import time)
        from cosa.agents.shared.fix_executor import FIX_PROMPT_BUILDERS
        assert "tfe" in FIX_PROMPT_BUILDERS, "TFE not registered in shared FIX_PROMPT_BUILDERS"
        bundle = FIX_PROMPT_BUILDERS[ "tfe" ]
        assert bundle[ "coder_system_prompt" ] == CODER_SYSTEM_PROMPT
        assert bundle[ "tester_system_prompt" ] == TESTER_SYSTEM_PROMPT
        assert bundle[ "build_fix_prompt" ] is build_fix_prompt
        print( "✓ TFE prompts registered in shared FIX_PROMPT_BUILDERS" )

        print( "\n✓ TFE Fix Prompts smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


# ─────────────────────────────────────────────────────────────────────────
# Register TFE prompt bundle into the shared FixExecutor prompt registry.
# Session 1cfcdf73 (2026-04-10): Step 10 — enables shared.fix_executor.FixExecutor
# to dispatch to TFE prompts via prompt_builder_key="tfe".
# This MUST run at import time, before any code that constructs a FixExecutor
# with prompt_builder_key="tfe".
# ─────────────────────────────────────────────────────────────────────────
from cosa.agents.shared.fix_executor import register_fix_prompts

register_fix_prompts(
    "tfe",
    build_fix_prompt        = build_fix_prompt,
    build_verify_prompt     = build_verification_prompt,
    build_redelegate_prompt = build_redelegation_prompt,
    coder_system_prompt     = CODER_SYSTEM_PROMPT,
    tester_system_prompt    = TESTER_SYSTEM_PROMPT,
)


if __name__ == "__main__":
    quick_smoke_test()
