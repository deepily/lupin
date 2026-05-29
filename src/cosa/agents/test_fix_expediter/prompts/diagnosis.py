"""
Test-aware diagnosis prompt for TFE Phase 1.

Per-cluster diagnosis uses an Opus lead agent with read-only Claude Agent
SDK tools (Grep, Read, Bash) to analyze a `FailureCluster` and produce a
`TestDiagnosisResult` with root cause, error category, confidence, and
test symptoms.

**Critical difference from BFE's diagnosis prompts**: BFE embeds dead-job
fields (ctx.error, ctx.stack_trace, ctx.question_text) into the prompt.
TFE embeds `classname::name[param]` test IDs + per-failure tracebacks from
the cluster, and teaches the lead agent four failure-mode categories plus
pytest test-ID decoding.

Design: src/rnd/v0.1.6/2026.04.10-test-fix-expediter/04-phase1-diagnose-plan.md
        src/rnd/v0.1.6/2026.04.10-test-fix-expediter/10-prompt-design.md#2
"""

from typing import Optional


DIAGNOSIS_SYSTEM_PROMPT = """You are a senior software engineer diagnosing a clustered set of pytest failures.

You have read-only access to the codebase via Grep, Read, and Bash (for commands like `python -c "import foo"`). You CANNOT edit files or run write commands — your job is pure analysis.

Your task: for the given cluster of failing tests, identify the ONE shared root cause and return a structured diagnosis.

## Test ID decoding

Every failure has a `classname` and `name`:
  - `classname` is a dotted Python path, e.g. `src.tests.unit.test_auth.TestTokenRefresh`
  - `name` is the test function plus optional `[param]` suffix, e.g. `test_refresh_returns_new_token` or `test_visual_page[chromium-login]`

To find the test source file:
  - Split `classname` into parts; drop the class name (last component starting with uppercase) if present
  - Join the remaining parts with `/` and append `.py`
  - Example: `src.tests.unit.test_auth.TestTokenRefresh::test_refresh_returns_new_token` → `src/tests/unit/test_auth.py::TestTokenRefresh::test_refresh_returns_new_token`
  - Strip `[param]` from the function name for parametrized tests — all variants share one function body

## Workflow

1. **Open the test file(s) first**. Read the failing test functions to understand intent and assertions.
2. **Trace from test → tested code**. Follow the imports and function calls from the test into the production code being exercised.
3. **Identify the failure mode category**:
   - `code_bug` — Production code under test is wrong. Fix locus: non-test source files.
   - `test_bug` — Test itself is wrong (stale assertion, bad mock, race). Fix locus: the test file.
   - `fixture_bug` — A shared fixture is broken, affecting multiple tests. Fix locus: conftest.py or fixture module.
   - `env_bug` — Environment/config issue (missing env var, missing mount, service down). Fix locus: config / infra.
4. **Identify the root cause**. Write a concise one-paragraph explanation of WHAT is wrong and WHY it manifests in the observed failures.
5. **List affected components**. Specific source file paths (with optional line numbers) where the fix will need to land.
6. **Extract test symptoms**. The specific assertion messages, exceptions, or traceback clues from the cluster's failures.
7. **Assign confidence**. 0.0-1.0. Cap at 0.4 for `code_bug` unless you traced to a specific non-test source file.

## Failure mode recognition cues

- Assertion failure (`type: "FAILED"`, traceback ends in an `assert` line): the test's assertion rejected the actual value. Check the producer of the actual value.
- Test setup error (`type: "ERROR"` in test body setup): fixture error, mock error, or environment issue. Often multiple tests in the same cluster share the broken setup.
- Teardown error (`type: "ERROR"` from teardown hook): cleanup logic failed. Common in visual regression (snapshot comparison runs in teardown).
- Collection error (`name: "<collection error>"` or `name: "<conftest import>"`): the test file couldn't be imported at all. Read the top of the file for syntax errors or missing imports.
- Parametrize error (rare): the parameter generator itself raised.

## Iteration budget

You have up to MAX_ITERATIONS rounds to refine your diagnosis. Stop early when your confidence reaches MIN_CONFIDENCE. On iteration 2+, you will see your previous attempt and be asked to refine — focus on gaps in your previous evidence.

## Output contract

Return ONLY a JSON object with this exact schema:

```json
{
  "cluster_id": "C1",
  "root_cause": "one paragraph explaining the shared root cause",
  "error_category": "code_bug | test_bug | fixture_bug | env_bug",
  "confidence": 0.75,
  "evidence": ["file:line — what you observed"],
  "affected_components": ["src/cosa/...", "src/tests/..."],
  "is_transient": false,
  "test_symptoms": ["specific error message 1", "specific error message 2"]
}
```

Do not wrap in markdown code fences. Do not include any prose before or after the JSON.
"""


def _truncate_traceback( traceback: str, max_lines: int = 30 ) -> str:
    """Keep the last N lines of a traceback (most specific frames first)."""
    if not traceback:
        return "(no traceback available)"
    lines = traceback.splitlines()
    if len( lines ) <= max_lines:
        return traceback
    return "\n".join( lines[ -max_lines: ] )


def build_diagnosis_prompt(
    cluster,
    ctx,
    iteration: int = 1,
    previous_attempts: Optional[ list ] = None,
    max_iterations: int = 4,
    min_confidence: float = 0.65,
) -> str:
    """
    Build the per-cluster diagnosis user prompt.

    Requires:
        - cluster is a FailureCluster with failure_indices into ctx.failures
        - ctx is a TestRemediationContext
        - iteration is 1-indexed (first call = 1)
        - previous_attempts is a list of prior TestDiagnosisResult JSON dicts
          (used on iteration 2+); may be None on iteration 1

    Ensures:
        - Returns a prompt string including:
          * cluster metadata (id, suites, hypothesis, signature)
          * up to N per-failure records (classname, name, type, message, truncated traceback)
          * iteration metadata + previous-attempt refinement hints if iteration > 1
          * max_iterations and min_confidence injected into instructions

    Args:
        cluster: FailureCluster to diagnose
        ctx: TestRemediationContext (for failures lookup)
        iteration: Current iteration number (1-indexed)
        previous_attempts: Prior diagnosis attempts (for refinement prompts)
        max_iterations: Config value for budget
        min_confidence: Config value for early-exit threshold

    Returns:
        str: Fully-formed user prompt
    """
    lines = []

    # Cluster header
    primary_suite = ctx.suites_run[ 0 ] if ctx.suites_run else "unknown"
    lines.append( f"Failure cluster: {cluster.cluster_id}" )
    lines.append( f"Suite: {primary_suite}" )
    lines.append( f"Shared error signature: {cluster.shared_error_signature}" )
    if cluster.hypothesis:
        lines.append( f"Heuristic hypothesis: {cluster.hypothesis}" )
    else:
        lines.append( "Heuristic hypothesis: (none — please diagnose from scratch)" )
    if cluster.affected_files_guess:
        lines.append( f"Affected files (guess): {', '.join( cluster.affected_files_guess )}" )
    lines.append( "" )

    # Failing tests in this cluster
    lines.append( f"Failing tests in this cluster ({len( cluster.failure_indices )}):" )
    lines.append( "" )

    for i, idx in enumerate( cluster.failure_indices, start=1 ):
        failure = ctx.failures[ idx ]
        lines.append( f"### {i}. {failure.get( 'classname', '<unknown>' )}::{failure.get( 'name', '<unknown>' )}" )
        lines.append( f"  Type: {failure.get( 'type', 'FAILED' )}" )
        lines.append( f"  Message: {failure.get( 'message', '(none)' )}" )
        lines.append( "  Traceback (truncated):" )
        lines.append( "  ```" )
        truncated = _truncate_traceback( failure.get( "traceback", "" ), max_lines=30 )
        for tb_line in truncated.splitlines():
            lines.append( f"  {tb_line}" )
        lines.append( "  ```" )
        lines.append( "" )

    # Iteration metadata
    lines.append( f"Iteration: {iteration} of {max_iterations}" )
    lines.append( f"Early-exit threshold: confidence >= {min_confidence}" )
    lines.append( "" )

    # Previous attempts (for iteration 2+ refinement)
    if iteration > 1 and previous_attempts:
        lines.append( "## Previous attempts" )
        lines.append( "" )
        for i, prior in enumerate( previous_attempts, start=1 ):
            lines.append( f"### Attempt {i}" )
            lines.append( f"  root_cause: {prior.get( 'root_cause', '(none)' )[ :200 ]}" )
            lines.append( f"  error_category: {prior.get( 'error_category', '(none)' )}" )
            lines.append( f"  confidence: {prior.get( 'confidence', 0.0 )}" )
            evidence = prior.get( "evidence", [] )
            if evidence:
                lines.append( f"  evidence: {evidence[ :3 ]}" )
            lines.append( "" )
        lines.append(
            "Your previous attempt(s) had confidence below the threshold. "
            "Refine the diagnosis. What additional files should you read? "
            "What evidence is missing? If the previous root_cause is wrong, "
            "replace it entirely — do not incrementally patch a bad hypothesis."
        )
        lines.append( "" )

    # Original user context
    lines.append(
        f"Original user-submitted test command: test_types={ctx.original_test_types}"
    )
    if ctx.original_pytest_args:
        lines.append( f"pytest args: {ctx.original_pytest_args}" )
    lines.append( "" )

    lines.append(
        "Analyze this cluster. Open the test file(s) first, trace to the "
        "production code (or fixture / config) under test, and return a "
        "JSON TestDiagnosisResult per the schema in the system prompt."
    )

    return "\n".join( lines )


def quick_smoke_test():
    """Quick smoke test for TFE diagnosis prompt builder."""
    import cosa.utils.util as cu
    from cosa.agents.test_fix_expediter.state import FailureCluster, TestRemediationContext

    cu.print_banner( "TFE Diagnosis Prompt Smoke Test", prepend_nl=True )

    try:
        ctx = TestRemediationContext(
            source_test_suite_job_id="ts-test",
            snapshot_path="p", snapshot={ "schema_version": "1.0" },
            suites_run=[ "unit" ],
            summary={ "all_passed": False },
            failures=[
                {
                    "classname": "src.tests.unit.test_auth.TestTokenRefresh",
                    "name": "test_refresh_ok",
                    "type": "FAILED",
                    "message": "assert 401 == 200",
                    "traceback": 'File "src/cosa/auth/tokens.py", line 42, in refresh\n    return None',
                },
                {
                    "classname": "src.tests.unit.test_auth.TestTokenRefresh",
                    "name": "test_refresh_expiry",
                    "type": "FAILED",
                    "message": "AttributeError: NoneType has no expiry",
                    "traceback": 'File "src/cosa/auth/tokens.py", line 42, in refresh\n    return None',
                },
            ],
            original_test_types=[ "unit" ],
            original_pytest_args=[ "-k", "auth" ],
            user_id="u", user_email="e@e.com", session_id="s",
        )
        cluster = FailureCluster(
            cluster_id="C1",
            failure_indices=[ 0, 1 ],
            shared_error_signature="src.tests.unit.test_auth.TestTokenRefresh at src/cosa/auth/tokens.py:42",
            hypothesis="",
            affected_files_guess=[ "src/tests/unit/test_auth.py", "src/cosa/auth/tokens.py" ],
            confidence=0.7,
        )

        # 1: Iteration 1 prompt
        prompt = build_diagnosis_prompt( cluster, ctx, iteration=1 )
        assert "Failure cluster: C1" in prompt
        assert "Suite: unit" in prompt
        assert "test_refresh_ok" in prompt
        assert "test_refresh_expiry" in prompt
        assert "src/cosa/auth/tokens.py" in prompt
        assert "Iteration: 1 of 4" in prompt
        assert "test_types=['unit']" in prompt
        assert "-k" in prompt
        assert "Previous attempts" not in prompt
        print( "✓ Iteration 1 prompt built" )

        # 2: Iteration 2 prompt (with previous attempt)
        prior = {
            "root_cause": "Token refresh returns None instead of a new token",
            "error_category": "code_bug",
            "confidence": 0.55,
            "evidence": [ "tokens.py:42 returns None" ],
        }
        prompt2 = build_diagnosis_prompt(
            cluster, ctx, iteration=2, previous_attempts=[ prior ]
        )
        assert "Iteration: 2 of 4" in prompt2
        assert "Previous attempts" in prompt2
        assert "Token refresh returns None" in prompt2
        assert "confidence: 0.55" in prompt2
        print( "✓ Iteration 2 prompt includes previous attempt" )

        # 3: System prompt sanity
        assert len( DIAGNOSIS_SYSTEM_PROMPT ) > 1000
        assert "classname" in DIAGNOSIS_SYSTEM_PROMPT
        assert "code_bug" in DIAGNOSIS_SYSTEM_PROMPT
        assert "fixture_bug" in DIAGNOSIS_SYSTEM_PROMPT
        assert "Output contract" in DIAGNOSIS_SYSTEM_PROMPT
        print( "✓ System prompt contains teaching points" )

        print( "\n✓ TFE Diagnosis Prompt smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
