# 04 — TFE Phase 1: Diagnose (per cluster)

## Goal

For each `FailureCluster` produced by Phase 0, run an Opus lead agent with read-only Claude Agent SDK tools to:
1. Parse the test IDs (`classname::name[param]`) into actual source file paths
2. Read the test file to understand the intent and the assertion
3. Trace from test file to tested module(s)
4. Identify the root cause and the affected source components
5. Return a structured `TestDiagnosisResult` with confidence

## Input / output

```python
# Input per invocation
cluster : FailureCluster
ctx     : TestRemediationContext   # full snapshot for context
config  : TestFixExpediterConfig

# Output per invocation
class TestDiagnosisResult(DiagnosisResult):
    cluster_id      : str
    test_symptoms   : list[str]   # specific messages/assertions observed
    # inherits from BFE's DiagnosisResult:
    #   root_cause           : str
    #   error_category       : str   # "code_bug" | "test_bug" | "fixture_bug" | "env_bug"
    #   confidence           : float
    #   evidence             : list[str]
    #   affected_components  : list[str]
    #   is_transient         : bool
```

## LLM + tools

- **Model**: Opus (lead agent, read-only) — matches BFE Phase 1 convention.
- **SDK tools**: `Grep`, `Read`, `Bash` (for `python -c "import foo"` style import checks). NO `Edit`, NO `Write`.
- **Iteration pattern**: up to `test fix expediter max diagnosis iterations` (default 4). Stop when confidence ≥ `test fix expediter min diagnosis confidence` (default 0.65). This matches BFE's pattern.

## Critical prompt differences from BFE

BFE's diagnosis prompt embeds:
```
Error: {ctx.error}
Stack trace: {ctx.stack_trace}
Question: {ctx.question_text}
Metadata: {ctx.metadata_json}
```

TFE's diagnosis prompt embeds something very different:
```
Failure cluster: {cluster.cluster_id}
Suite: {primary_suite}
Hypothesis (from Phase 0): {cluster.hypothesis}
Shared error signature: {cluster.shared_error_signature}

Failing tests in this cluster:
  1. {classname1}::{name1}[{param1}]
     Type: {type}
     Message: {message}
     Traceback (truncated to 30 lines): {traceback_excerpt}
  2. ...
```

### Prompt teaching points (what the LLM must know)

The TFE diagnosis system prompt teaches the agent four things BFE doesn't:

1. **Test ID decoding**: `classname` is a dotted path like `src.tests.e2e_ui.test_visual_regression.TestVisualRegression` → source path `src/tests/e2e_ui/test_visual_regression.py::TestVisualRegression`. The `name` is the test function plus `[param]` suffix for parametrized tests. Strip the `[param]` suffix to get the function name.

2. **Open test file first**: Always read the failing test file before speculating. The test body reveals what the test is actually checking — assertion, fixture use, mocks, parametrization source.

3. **Trace test → tested module**: After reading the test, trace the imports and function calls into the production code. The bug is usually in the code under test, occasionally in the test itself, occasionally in a fixture, occasionally in the test environment.

4. **Recognize failure mode categories**:
   - **Assertion failure** (`type: "FAILED"`): The test's `assert` statement rejected the actual value. Read the assertion, check the producer of the actual value.
   - **Test setup error** (`type: "ERROR"` in test body): Fixture, mock, or environment issue. Often multiple tests share the broken fixture.
   - **Teardown error** (`type: "ERROR"` in teardown): Cleanup logic failed — common in visual regression (snapshot comparison runs in teardown).
   - **Collection error**: Test file couldn't be imported at all — syntax error, missing import, top-level exception.
   - **Parametrize error**: The parameter generator raised — rare but distinct.

The system prompt includes all four of these as explicit mental models, with one-line examples.

## Error category mapping

Output `error_category` is one of:

| Category | Meaning | Fix locus |
|----------|---------|-----------|
| `code_bug` | Production code under test is wrong | `src/cosa/...` or `src/fastapi_app/...` |
| `test_bug` | Test is wrong (stale assertion, race, bad mock) | `src/tests/...` |
| `fixture_bug` | Fixture is broken | `src/tests/conftest.py` or nearest conftest.py |
| `env_bug` | Environment/config issue (missing env var, mount, service) | `src/conf/...` or infra |

Diagnosis confidence floors by category:
- `code_bug`: requires reading tested code path. If LLM can't find it, cap confidence at 0.4.
- `test_bug`: reading the test file is enough. Confidence can reach 0.9.
- `fixture_bug`: requires reading fixture source + at least 2 failing tests in cluster. Confidence can reach 0.8.
- `env_bug`: heuristic clues (env var, mount, port, service name) in the traceback. Often high confidence even without source inspection.

## Iteration loop

```python
for iteration in range(config.max_diagnosis_iterations):
    prompt = build_diagnose_prompt(cluster, ctx, previous_attempts=attempts)
    result = await api_client.call_lead_agent(prompt, tools=READ_ONLY_TOOLS)
    diagnosis = parse_diagnosis_response(result)

    if diagnosis.confidence >= config.min_diagnosis_confidence:
        return diagnosis

    attempts.append(diagnosis)
    breadcrumb(f"Cluster {cluster.cluster_id} iteration {iteration+1}: "
               f"confidence {diagnosis.confidence:.2f}, refining")

# Exhausted iterations — return best-effort with a warning
return max(attempts, key=lambda d: d.confidence)
```

## Voice / notification

- **Session topic**: `voice_io.set_session_topic(f"TFE Phase 1: Diagnose cluster {i}/{K}")` at entry per cluster
- **Breadcrumb per cluster**: `notify(f"Diagnosing cluster {i} of {K}...", priority="low")`
- **Breadcrumb per iteration**: `notify(f"Cluster {i} iteration {j}/{max}: confidence {c:.2f}", priority="low")`
- **No per-cluster gate.** One aggregate gate AFTER all K clusters complete (see below)
- **Error notification**: if a cluster's diagnosis exhausts iterations AND final confidence < 0.3, fire `notify(priority="urgent")` with the low-confidence warning — but DO NOT abort the pipeline. The low-confidence diagnosis becomes a "manual investigation" entry in the proposal stage.

## Aggregate voice gate (post-Phase-1)

After all K diagnoses complete:

```python
abstract = render_cluster_summaries(diagnoses)  # markdown: per-cluster root cause + confidence

answer = await voice_io.ask_yes_no(
    f"Diagnosis complete. {K} clusters analyzed.\n\n{summary_line}\n\nProceed to proposal phase?",
    default="yes",
    priority="high",
    abstract=abstract,
    job_id=self.job_id,
    timeout_seconds=300,
)

if answer.startswith("no"):
    self.status = "cancelled_by_user"
    return
```

Where `summary_line` is e.g. `"Cluster C1: code_bug (0.78), Cluster C2: fixture_bug (0.82), Cluster C3: env_bug (0.91)"`.

## Unit test coverage

Target: `src/tests/unit/test_tfe_diagnose.py` (part of `test_tfe_orchestrator.py` or separate)

| Test | Fixture | Mock | Assertion |
|------|---------|------|-----------|
| `test_diagnose_single_cluster_high_confidence` | 1-cluster snapshot | API client returns high-conf result first iteration | Returns in 1 iteration |
| `test_diagnose_iterates_until_confidence` | any | Mock returns low → medium → high across 3 calls | Returns on iteration 3 |
| `test_diagnose_exhausts_iterations` | any | Mock always returns low | Returns max-confidence attempt, no exception |
| `test_diagnose_fixture_bug_category` | snapshot_fixture_error | Mock returns fixture_bug | `error_category == "fixture_bug"` |
| `test_diagnose_env_bug_category` | snapshot_env | Mock returns env_bug | `error_category == "env_bug"` |
| `test_diagnose_low_confidence_notification` | any | Mock always < 0.3 | Urgent notification fired |
| `test_diagnose_voice_gate_yes` | K=3 snapshot | Mock gate returns "yes" | Phase 2 proceeds |
| `test_diagnose_voice_gate_no` | K=3 snapshot | Mock gate returns "no" | Status=cancelled_by_user, no Phase 2 |

## Future optimization (not in MVP)

- **Parallel diagnose via `asyncio.gather()` with a semaphore**. MVP is serial to keep SDK client lifecycle simple and to avoid rate-limit pile-up on Opus. Can parallelize once per-cluster diagnose is proven stable.
- **Shared context cache**: if cluster 2 has already read a file cluster 1 read, reuse. Requires SDK client pooling.
- **Adaptive iterations**: reduce `max_diagnosis_iterations` for clusters with high heuristic confidence from Phase 0.
