"""
Per-cluster fix proposal prompt for TFE Phase 2.

Given a TestDiagnosisResult for one failure cluster, asks the Lead agent
(Opus, read-only SDK) to propose up to N alternative fixes (N from
TFEConfig.max_proposals_per_cluster, default 1). Each proposal is a
TFEProposedFix with title, description, fix_type, confidence, risk,
estimated effort, and concrete file changes.

Design: src/rnd/v0.1.6/2026.04.10-test-fix-expediter/05-phase2-propose-plan.md
        src/rnd/v0.1.6/2026.04.10-test-fix-expediter/10-prompt-design.md#3
        OOS-1B (2026-04-29): cap parameterized via INI key
"""

from typing import Optional


def build_proposal_system_prompt( max_proposals: int ) -> str:
    """
    Build the system prompt for a TFE proposal call.

    Requires:
        - max_proposals is a positive integer

    Ensures:
        - Returns a system-prompt string with the proposal cap interpolated
          into the task description and ranking instruction
        - Instructs the Lead to emit between 1 and `max_proposals` fixes per
          cluster, ranked by confidence

    Args:
        max_proposals: Maximum fixes the Lead may emit per cluster

    Returns:
        str: Fully-formed system prompt
    """
    return f"""You are a senior software engineer proposing fixes for a clustered set of pytest failures.

You have read-only access via Read, Grep, and Glob. You CANNOT edit files — your job is to propose fixes, not apply them. The Coder agent will apply whichever fix the user approves.

Your task: given a cluster's diagnosis, propose 1 to {max_proposals} alternative fixes ranked by your confidence.

## Allowed fix_type values

- `code_patch` — Edit production source files under test (e.g., `src/cosa/...`). Most common for `code_bug` diagnoses.
- `test_patch` — Edit the test file itself (e.g., stale assertion, broken mock, race condition). Use for `test_bug` diagnoses.
- `config_change` — Edit `lupin-app.ini`, environment, or other config. Use for `env_bug` diagnoses or missing config keys.
- `retry` — The failure looks transient (flaky network, timing). No code change needed. Use sparingly.
- `manual` — The fix is too complex or unclear to propose; defer to human. Only valid when diagnosis confidence is below 0.4.

## Constraints

1. **Minimal and targeted** — no refactors, no unrelated cleanup, no new features.
2. **Name specific files** — each fix's `changes` array must reference real files by path.
3. **Max 5 file changes per fix** — proposals touching more than 5 files suggest the diagnosis is too broad.
4. **Risk level** — one of `low`, `medium`, `high`. `high` requires rationale in the description.
5. **Estimated effort** — one of `minutes`, `hours`, `session`.
6. **Rank by confidence** — return the array with the highest-confidence fix FIRST.

## Output contract

Return ONLY a JSON array of TFEProposedFix objects. No prose, no markdown fences outside the JSON.

```json
[
  {{
    "cluster_id": "C1",
    "title": "Short commit-message title (≤60 chars)",
    "description": "1-2 paragraph explanation of what to change and why it addresses the diagnosed root cause.",
    "fix_type": "code_patch",
    "confidence": 0.85,
    "risk_level": "low",
    "estimated_effort": "minutes",
    "changes": [
      {{"file": "src/cosa/auth/tokens.py", "action": "modify", "description": "Replace `return None` on line 42 with `return new_token`"}}
    ]
  }}
]
```

Guardrails (the reviewer will reject your output if violated):
- Empty `changes` array is allowed ONLY for `fix_type: retry` or `fix_type: manual`
- `fix_type: manual` is valid ONLY when diagnosis confidence < 0.4
- Proposals editing more than 5 files are rejected as over-ambitious
"""


def build_proposal_prompt(
    cluster,
    diagnosis,
    ctx,
    max_proposals: int = 1,
) -> str:
    """
    Build the per-cluster proposal user prompt.

    Requires:
        - cluster is a FailureCluster
        - diagnosis is a TestDiagnosisResult for the same cluster
        - ctx is a TestRemediationContext
        - max_proposals is a positive integer (cap on Lead's proposal count)

    Ensures:
        - Returns a prompt string including:
          * diagnosis summary (root_cause, error_category, confidence)
          * affected_components list from the diagnosis
          * per-failure short list (classname::name + short message)
          * original user run context
          * proposal-cap instruction interpolating max_proposals

    Args:
        cluster: FailureCluster being proposed against
        diagnosis: TestDiagnosisResult from Phase 1
        ctx: TestRemediationContext
        max_proposals: Cap on number of proposals the Lead may emit (default 1)

    Returns:
        str: Fully-formed user prompt
    """
    lines = []

    lines.append( f"Propose fixes for cluster {cluster.cluster_id}." )
    lines.append( "" )

    # Diagnosis section
    lines.append( "## Diagnosis" )
    lines.append( "" )
    lines.append( f"Root cause: {diagnosis.root_cause}" )
    lines.append( f"Error category: {diagnosis.error_category}" )
    lines.append( f"Confidence: {diagnosis.confidence:.0%}" )
    if diagnosis.evidence:
        lines.append( f"Evidence: {diagnosis.evidence}" )
    if diagnosis.affected_components:
        lines.append( f"Affected components: {diagnosis.affected_components}" )
    if diagnosis.test_symptoms:
        lines.append( f"Test symptoms: {diagnosis.test_symptoms}" )
    lines.append( "" )

    # Failing tests in this cluster (short form)
    lines.append( f"## Failing tests ({len( cluster.failure_indices )})" )
    lines.append( "" )
    for idx in cluster.failure_indices:
        failure = ctx.failures[ idx ]
        classname = failure.get( "classname", "<unknown>" )
        name      = failure.get( "name", "<unknown>" )
        message   = failure.get( "message", "" )[ :100 ]
        lines.append( f"- `{classname}::{name}` — {message}" )
    lines.append( "" )

    # Original context
    lines.append( "## Original run context" )
    lines.append( "" )
    lines.append( f"Suites run: {ctx.suites_run}" )
    lines.append( f"Test types: {ctx.original_test_types}" )
    if ctx.original_pytest_args:
        lines.append( f"pytest args: {ctx.original_pytest_args}" )
    lines.append( "" )

    # Instruction (proposal cap from TFEConfig.max_proposals_per_cluster)
    lines.append(
        f"Propose 1 to {max_proposals} alternative fix(es) for this cluster. "
        "Rank by confidence, highest first. Return a JSON array matching the "
        "schema in the system prompt. Remember: set cluster_id to \""
        + cluster.cluster_id + "\" on every proposed fix."
    )

    return "\n".join( lines )


def quick_smoke_test():
    """Quick smoke test for TFE proposal prompt builder."""
    import cosa.utils.util as cu
    from cosa.agents.test_fix_expediter.state import (
        FailureCluster, TestDiagnosisResult, TestRemediationContext,
    )

    cu.print_banner( "TFE Proposal Prompt Smoke Test", prepend_nl=True )

    try:
        ctx = TestRemediationContext(
            source_test_suite_job_id="ts-test",
            snapshot_path="p", snapshot={ "schema_version": "1.0" },
            suites_run=[ "unit" ],
            summary={ "all_passed": False },
            failures=[
                {
                    "classname": "src.tests.unit.test_auth.TestLogin",
                    "name": "test_ok",
                    "type": "FAILED",
                    "message": "assert 401 == 200",
                    "traceback": 'File "src/cosa/auth/tokens.py", line 42, in refresh',
                },
            ],
            original_test_types=[ "unit" ],
            user_id="u", user_email="e@e.com", session_id="s",
        )
        cluster = FailureCluster(
            cluster_id="C1",
            failure_indices=[ 0 ],
            shared_error_signature="auth bug",
        )
        diagnosis = TestDiagnosisResult(
            cluster_id="C1",
            root_cause="Token refresh returns None instead of a new token",
            error_category="code_bug",
            confidence=0.82,
            evidence=[ "tokens.py:42" ],
            affected_components=[ "src/cosa/auth/tokens.py" ],
            test_symptoms=[ "assert 401 == 200" ],
        )

        prompt = build_proposal_prompt( cluster, diagnosis, ctx, max_proposals=1 )
        assert "Propose fixes for cluster C1" in prompt
        assert "Token refresh returns None" in prompt
        assert "code_bug" in prompt
        assert "0.82" in prompt or "82%" in prompt
        assert "src/cosa/auth/tokens.py" in prompt
        assert "src.tests.unit.test_auth.TestLogin::test_ok" in prompt
        assert "test_types=['unit']" in prompt or "['unit']" in prompt
        assert "C1" in prompt
        assert "Propose 1 to 1 alternative" in prompt
        print( "✓ Prompt contains all required sections + cap=1 instruction" )

        # Cap parameterization sanity — same call with N=3 must reflect the cap
        prompt_3 = build_proposal_prompt( cluster, diagnosis, ctx, max_proposals=3 )
        assert "Propose 1 to 3 alternative" in prompt_3
        print( "✓ User prompt threads max_proposals correctly" )

        # System prompt sanity (now a function, not a constant)
        sys_prompt_1 = build_proposal_system_prompt( max_proposals=1 )
        sys_prompt_3 = build_proposal_system_prompt( max_proposals=3 )
        assert len( sys_prompt_1 ) > 500
        assert "code_patch" in sys_prompt_1
        assert "Output contract" in sys_prompt_1
        assert "Guardrails" in sys_prompt_1
        assert "1 to 1 alternative" in sys_prompt_1
        assert "1 to 3 alternative" in sys_prompt_3
        print( "✓ System prompt builder honors cap + retains fix_type enum + guardrails" )

        print( "\n✓ TFE Proposal Prompt smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
