# 10 — TFE Prompt Design (Collected)

All TFE prompts live in `src/cosa/agents/test_fix_expediter/prompts/`. This doc collects their semantic design in one place for review. Actual prompt text is written during implementation and committed to the corresponding `.py` file with docstrings.

## Prompt files

| File | Phase | Used by |
|------|-------|---------|
| `prompts/cluster.py` | Phase 0 | `cluster.py::llm_refine()` |
| `prompts/diagnosis.py` | Phase 1 | `orchestrator.run_phase1_diagnose()` |
| `prompts/proposal.py` | Phase 2 | `orchestrator.run_phase2_propose()` |
| `prompts/fix.py` | Phase 3 | Registered into shared `FIX_PROMPT_BUILDERS["tfe"]` |

---

## 1. `prompts/cluster.py` — Failure clustering

### System prompt themes

- Role: "test-failure triage analyst"
- Goal: group N pytest failures into smallest K clusters, one root cause per cluster
- Constraint: `max_clusters` upper bound, 1 lower bound
- Heuristics the model should apply:
  - Parametrized tests with same failure mode → one cluster
  - Fixture errors breaking many tests → one cluster keyed on fixture source
  - Collection errors (failed imports) → one cluster per file
  - Same production-code stack frame across multiple tests → strong signal for shared root cause

### User prompt shape

```
Remediation snapshot: <JSON>

Heuristic seed clusters (starting point — you may merge, split, relabel):
<JSON of seed clusters>

Return JSON array of final clusters. Each element:
{
  "cluster_id": "C1" | "C2" | ...,
  "failure_indices": [0, 3, 7],
  "shared_error_signature": "short summary of the shared error",
  "hypothesis": "one-sentence root cause guess",
  "affected_files_guess": ["src/cosa/...", "src/tests/..."],
  "confidence": 0.0-1.0
}

Constraints:
- Every failure_index from 0 to {N-1} must appear in exactly one cluster
- No duplicates across clusters
- 1 <= len(clusters) <= {max_clusters}
- hypothesis is one sentence, specific (not "test failed")
```

### Output parsing

- JSON parse with lenient fallback (strip markdown code fences)
- Validate index coverage + disjointness
- On parse failure: retry once with a "your previous output had issue X, fix it" prompt; on second failure, fall back to heuristic seeds verbatim

---

## 2. `prompts/diagnosis.py` — Test-aware diagnosis

### System prompt themes

- Role: "senior engineer diagnosing a set of related test failures"
- Teaching points the system prompt embeds explicitly:
  1. **Test ID decoding**: `classname::name[param]` → file path + function
  2. **Open test file first**: always read the failing test file before speculating
  3. **Trace test → tested module**: after reading the test, identify what it imports/calls in production code
  4. **Four failure modes**:
     - Assertion failure (`type: FAILED`, in test body): test asserted; check the producer of the actual value
     - Test setup error (`type: ERROR` in body): fixture / mock / env issue
     - Teardown error (`type: ERROR` in teardown): cleanup logic failed — common in visual regression
     - Collection error: file couldn't be imported — syntax error, top-level exception, missing import
  5. **Error categories to assign**: `code_bug`, `test_bug`, `fixture_bug`, `env_bug`

- Output contract: JSON matching `TestDiagnosisResult` schema
- Tool access: `Grep`, `Read`, `Bash` (for `python -c "import foo"` checks). NO Edit, NO Write.
- Budget: up to `max_diagnosis_iterations` calls per cluster, stop when confidence ≥ `min_diagnosis_confidence`

### User prompt shape (iteration 1)

```
Failure cluster: {cluster.cluster_id}
Suite: {primary_suite}
Heuristic hypothesis: {cluster.hypothesis or "(none — please diagnose from scratch)"}
Shared error signature: {cluster.shared_error_signature}

Failing tests in this cluster ({N}):

1. {classname}::{name}[{param}]
   Type: {type}
   Message: {message}
   Traceback (last 30 lines):
   {traceback_excerpt}

2. ...

Original user-submitted test command: `test_types={original_test_types}`

Your task:
1. Open the test file(s) for the failing tests
2. Identify the root cause (code bug / test bug / fixture bug / env bug)
3. List the affected components (specific file paths + optional line numbers)
4. Assign confidence 0.0-1.0

Return JSON:
{
  "cluster_id": "{cluster.cluster_id}",
  "root_cause": "one paragraph explaining the shared root cause",
  "error_category": "code_bug" | "test_bug" | "fixture_bug" | "env_bug",
  "confidence": 0.0-1.0,
  "evidence": ["file:line — what you observed"],
  "affected_components": ["src/cosa/...", ...],
  "is_transient": true | false,
  "test_symptoms": ["specific error messages observed"]
}
```

### User prompt shape (iteration 2+)

Include previous attempt(s) with reasons for low confidence, ask for refinement:

```
Your previous attempt:
{previous_diagnosis_json}

Confidence was {prev_confidence}, below the threshold {min_confidence}.
Refine the diagnosis. What additional files should you read?
What evidence is missing?
```

### Guardrails

- If the LLM assigns `confidence > 0.5` without evidence field populated, reject and retry
- If `affected_components` is empty, reject and retry (every root cause must name at least one file)
- If `error_category` is `code_bug` without tracing to a non-test source file, cap confidence at 0.4

---

## 3. `prompts/proposal.py` — Per-cluster fix proposal

### System prompt themes

- Role: "senior engineer proposing a fix for a clustered set of test failures"
- Goal: propose 1-3 alternative fixes, ranked by confidence, each with concrete file changes
- Fix types allowed: `code_patch`, `test_patch`, `config_change`, `retry`, `manual`
- Constraints:
  - Minimal and targeted — no refactors, no new features
  - Each fix must name specific files + describe the change
  - Risk level one of `low`, `medium`, `high` — high requires rationale
  - Estimated effort one of `minutes`, `hours`, `session`
- Tool access: read-only (`Read`, `Grep`)

### User prompt shape

```
Cluster {cluster_id} diagnosis:
Root cause: {diagnosis.root_cause}
Error category: {diagnosis.error_category}
Confidence: {diagnosis.confidence:.0%}
Affected components: {diagnosis.affected_components}
Test symptoms: {diagnosis.test_symptoms}

Failing tests in this cluster:
  - {classname}::{name}[{param}] — {short_message}
  - ...

Propose 1-3 alternative fixes. Return JSON array of ProposedFix objects:
[
  {
    "cluster_id": "{cluster_id}",
    "title": "short title (for commit message subject)",
    "description": "1-2 paragraph explanation",
    "fix_type": "code_patch" | "test_patch" | "config_change" | "retry" | "manual",
    "confidence": 0.0-1.0,
    "risk_level": "low" | "medium" | "high",
    "estimated_effort": "minutes" | "hours" | "session",
    "changes": [
      {"file": "src/...", "description": "what to change", "line_hint": 42 or null}
    ]
  },
  ...
]

Rank the array by your confidence — best recommendation first.
```

### Guardrails

- Reject proposals with empty `changes` array unless `fix_type == "retry"` or `fix_type == "manual"`
- Reject proposals that edit more than 5 files (too ambitious — suggests the diagnosis is wrong)
- Reject `fix_type: "manual"` unless diagnosis confidence < 0.4 (otherwise the agent is being lazy)

---

## 4. `prompts/fix.py` — Fix application (coder + tester)

Three prompt builders registered into the shared `FIX_PROMPT_BUILDERS["tfe"]`:

### `build_fix_prompt(proposed_fix, fix_context, iteration)`

Coder agent (Sonnet) with Edit/Read/Grep tools. Applies the fix.

System prompt themes:
- Role: "implementation engineer applying a targeted bug fix"
- Constraint: follow the proposal exactly — no scope creep
- Must use Edit tool for file changes (not Write, not Bash `sed`)
- Must verify each edit via Read after the change

User prompt shape:
```
You are fixing cluster {cluster_id}: {fix.title}

Root cause (from diagnosis):
{fix_context.root_cause}

Proposed changes:
{fix.changes_as_markdown}

Failing tests that this fix should make pass:
{list_from_fix_context.origin_details.failure_indices_resolved}

Apply the changes. Return a summary of files modified:
{
  "files_modified": ["src/..."],
  "summary": "what you changed and why"
}
```

### `build_verification_prompt(proposed_fix, fix_context)`

Tester agent (Sonnet) with Bash + Read tools. Runs pytest to verify.

System prompt themes:
- Role: "QA engineer verifying a bug fix"
- Must run pytest with `-k` filter targeting only the cluster's failing tests
- Must NOT run the full suite (too slow, not in scope)
- Must interpret output: "pass" means the cluster tests pass, "fail" means any cluster test still fails
- Bonus: if fix_type was `fixture_bug`, also run tests that share the fixture (broader `-k`)

User prompt shape:
```
Verify the fix for cluster {cluster_id}: {fix.title}

Cluster failing tests ({N}):
{list_of_classname_name_pairs}

Run:
  pytest -v -k "{or_joined_test_names}"

Expected: all {N} tests pass.

Return JSON:
{
  "success": true | false,
  "passed": <count>,
  "failed": <count>,
  "details": "pytest output summary",
  "retry_eligible": true | false  // true if the failure looks fixable by more code changes
}
```

### `build_redelegation_prompt(proposed_fix, fix_context, prior_attempt, tester_output)`

Used when the tester reports failure and the fix executor wants to retry.

User prompt shape:
```
The previous fix attempt did not pass verification.

Your previous fix:
{prior_attempt.summary}
Files you modified:
{prior_attempt.files_modified}

Tester output:
{tester_output.details}

Analyze the tester output. Refine your approach and apply a new fix.
If the tester output suggests the diagnosis is wrong, return:
{"files_modified": [], "summary": "diagnosis appears incorrect, no changes applied",
 "retry_eligible": false}
```

---

## Prompt review cadence

- **Before coding step 8** (Phase 1 diagnose): review diagnosis prompts with user
- **Before coding step 9** (Phase 2 propose): review proposal prompts
- **Before coding step 10** (Phase 3 fix delegation): review fix/verify/redelegate prompts

Prompt changes during implementation are tracked in `92-tfe-phases-execution-log.md` with the commit that introduced them.
