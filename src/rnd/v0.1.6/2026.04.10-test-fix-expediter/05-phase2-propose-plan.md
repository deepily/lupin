# 05 — TFE Phase 2: Propose (aggregated multi-select gate)

## Goal

Given a list of `TestDiagnosisResult` (one per cluster from Phase 1), produce a list of `ProposedFix` objects and gather the user's selection of which to apply via a single aggregate voice gate. Write a multi-section plan doc covering all clusters.

## Input / output

```python
# Input
diagnoses : list[TestDiagnosisResult]   # K entries
ctx       : TestRemediationContext

# Output
proposed_fixes : list[ProposedFix]   # K entries (one per cluster, or more if a cluster warrants multiple alternatives)
selected_fixes : list[ProposedFix]   # user-selected subset from the gate
plan_path      : str                 # path to the multi-section plan doc
```

BFE's `ProposedFix` model is extended with an optional `cluster_id: Optional[str] = None` field (backwards-compatible — BFE leaves it None). TFE populates it so the fix can be traced back to its cluster during Phase 3 and Phase 5.

## LLM + tools

- **Model**: Opus, read-only SDK tools. The propose phase doesn't need `Edit` — it's still in the "plan the fix" stage.
- **Call shape**: one call per diagnosis (K calls), OR one batched call for all K diagnoses. MVP: **one call per cluster** for prompt simplicity and to keep per-cluster proposals cleanly attributable. Future optimization: batched call with structured output.

## Prompt structure

Each proposal call receives:
- The `TestDiagnosisResult` for this cluster (including root cause, error category, affected components)
- A reference list of the original failures in this cluster (`classname::name[param]` + short message)
- The original user instruction (test_types that were run, pytest_args)
- Instruction to propose 1-3 alternative fixes, each with `title`, `description`, `fix_type`, `confidence`, `risk_level`, `estimated_effort`, `changes[]`

`fix_type` options (reused from BFE):
- `code_patch` — edit source files
- `test_patch` — edit test files (for test_bug category)
- `config_change` — edit `lupin-app.ini` / other config
- `retry` — flaky test, no edit needed
- `manual` — too complex, defer to human

Prompt themes (details in [10-prompt-design.md](10-prompt-design.md)):

```
SYSTEM: You are a senior engineer proposing fixes for a clustered set of
pytest failures. The cluster's root cause has been diagnosed. Propose 1-3
alternative fixes, ranked by your confidence in the primary recommendation.

Each fix should describe:
  - WHAT to change (specific files and lines)
  - WHY it addresses the root cause (link to the diagnosis)
  - WHAT the risk is (could this break something else?)
  - HOW to verify (which tests should be re-run — Phase 6 handles this)

Fixes should be minimal and targeted. Do not bundle unrelated changes.
Do not propose refactors. Do not propose new features.

Return JSON array of ProposedFix objects.

USER: <diagnosis summary> <cluster failures> <original run context>
```

## Plan doc structure (multi-section)

Written via `shared/PlanWriter` to `src/rnd/{YYYY.MM.DD}-tfe-{suite_abbrev}-{short_slug}.md`.

```markdown
# TFE Plan: Test Fix for {suites_abbrev} run at {timestamp}

**Source TestSuiteJob**: {test_suite_job_id}
**Clusters**: {K}
**User**: {user_email}

---

## Summary

{N} test failures grouped into {K} clusters by TFE Phase 0. Each cluster
represents a distinct root cause. Fixes are proposed per cluster; user
selects a subset via aggregate gate.

---

## Cluster C1: {hypothesis}

**Error category**: {error_category}
**Confidence**: {confidence:.0%}
**Affected components**: {affected_components_list}
**Failing tests** ({N1}):
- {classname}::{name}[{param}]
- ...

### Proposed fixes

#### Fix 1.A: {title} ({fix_type}, {risk_level} risk, {confidence:.0%} confidence)
{description}

Changes:
- `{file1}` — {summary}
- `{file2}` — {summary}

#### Fix 1.B: (alternative) {title}
...

---

## Cluster C2: ...

...

---

## Git References

(populated by Phase 5 after fix application)

- Branch: _(pending)_
- Commits: _(pending)_
- PR: _(pending)_

---

## Validation run

(populated by Phase 6 after resubmit)

- Validation TestSuiteJob ID: _(pending)_
```

## Aggregate voice gate

The key UX decision. **Default mode is `aggregate`** (config `test fix expediter voice gate mode = aggregate | per_cluster`).

### Aggregate mode UX

```python
options = []
for i, fix in enumerate(proposed_fixes):
    cluster = clusters[fix.cluster_id]
    options.append({
        "label": f"Cluster {cluster.cluster_id}: {fix.title}",
        "description": (
            f"{fix.fix_type}, {fix.confidence:.0%} confidence, "
            f"{fix.risk_level} risk, {fix.estimated_effort}. "
            f"Affects {len(fix.changes)} files."
        )
    })

result = await voice_io.ask_multiple_choice(
    questions=[{
        "question": f"Select fixes to apply ({len(proposed_fixes)} proposed across {K} clusters):",
        "header": "Fixes",
        "multiSelect": True,
        "options": options,
    }],
    priority="high",
    timeout_seconds=600,
    title="TFE Proposal",
    abstract=render_plan_doc_excerpt(plan_path),
    job_id=self.job_id,
)

selected_labels = result["answers"]["Fixes"]  # list of accepted labels
selected_fixes = [fix for fix, opt in zip(proposed_fixes, options)
                  if opt["label"] in selected_labels]
```

Total interactive gates per TFE run in aggregate mode: **2** (one after Phase 1 diagnose, one here).

### Per-cluster mode UX

```python
selected_fixes = []
for i, fix in enumerate(proposed_fixes):
    answer = await voice_io.ask_yes_no(
        f"Apply fix for cluster {fix.cluster_id}: {fix.title}?",
        default="yes", priority="high",
        abstract=render_single_fix(fix),
        job_id=self.job_id,
        timeout_seconds=300,
    )
    if answer.startswith("yes"):
        selected_fixes.append(fix)
```

Total interactive gates per TFE run in per-cluster mode: **K + 1** (K proposal gates + 1 diagnose gate). With K=5: 6 gates. With K=8: 9 gates. Decision fatigue.

### Why aggregate is the default

1. Realworld batches cluster at K=3-8.
2. Multi-select already exists in `ask_multiple_choice` with `multiSelect=True`.
3. Users want to review once, decide once, not K times.
4. The user can reject the whole batch by deselecting everything.
5. The alternative per-cluster mode is available via the config key for high-trust automated mode.

## No selection = no Phase 3

If `selected_fixes` is empty, TFE does not proceed to Phase 3. Status transitions to `cancelled_by_user_at_proposal` and the plan doc is left as a record. Validation rerun is also skipped (nothing to validate).

## Unit test coverage

Target: `src/tests/unit/test_tfe_propose.py` (or inside `test_tfe_orchestrator.py`)

| Test | Mock | Assertion |
|------|------|-----------|
| `test_propose_single_cluster` | API client returns 1 fix | `len(proposed_fixes) == 1` |
| `test_propose_multiple_alternatives_per_cluster` | API client returns 3 fixes for one cluster | All 3 captured |
| `test_propose_plan_doc_multi_section` | any | Plan doc contains `## Cluster C1:`, `## Cluster C2:`, ... sections |
| `test_aggregate_gate_select_all` | Mock returns all labels | `len(selected_fixes) == K` |
| `test_aggregate_gate_select_subset` | Mock returns [C1, C3] | Only fixes for C1 and C3 selected |
| `test_aggregate_gate_select_none` | Mock returns [] | Status=cancelled_by_user_at_proposal, no Phase 3 |
| `test_per_cluster_gate_mode` | Config override + K=2 yes/no mocks | 2 gates fired sequentially |
| `test_plan_doc_cluster_id_propagation` | K=3 | Each ProposedFix has its cluster_id set |
