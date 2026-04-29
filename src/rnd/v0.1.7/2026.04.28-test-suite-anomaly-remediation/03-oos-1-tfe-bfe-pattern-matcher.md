# OOS-1 — TFE/BFE pattern-matcher upgrade (PROPOSAL — awaiting ratification)

**Status**: Plan only. No code work until ratified.
**Prewarm-evidence update**: 2026-04-28 read-only forensic pass through cluster.py + report writer + proposal prompt confirmed both bugs are tractable. Findings folded in below as "Prewarm Findings"; original speculative hypothesis section preserved for context.

---

## Prewarm Findings (2026-04-28, evidence-grounded)

### Finding A — "0 failure(s) per cluster" is a one-line report-writer typo

**File**: `src/cosa/agents/test_fix_expediter/job.py:549`

```python
# CURRENT — broken:
count = getattr( c, "failure_count", len( getattr( c, "failures", [] ) or [] ) )
```

`FailureCluster` has the attribute `failure_indices` (per `state.py:95`), NOT `failures`. So `getattr(c, "failures", [])` returns the default `[]` for every cluster → `len([])` = 0. **Every cluster reports 0 regardless of actual size.**

**The 22:35 run actually clustered correctly.** Confirmed by:
- `2026.04.27-at-22:35-EDT-all-remediation.json` recorded all 42 failures (well-formed input).
- `prompts/diagnosis.py:149,152` and `prompts/proposal.py:115,117` use the correct attribute name (`cluster.failure_indices`) → diagnosis + proposal pipeline operated on real data.
- The 23 proposals are coherent and cluster-grounded (visual baselines / docker-check / BFE phase6 / live-pipeline / CUDA / peft / sys.argv) — exactly what you'd expect from 8 well-formed clusters.

**Fix**: one-line replacement —
```python
count = len( c.failure_indices )
```
or, defensively:
```python
count = len( getattr( c, "failure_indices", [] ) or [] )
```

**Other reports unaffected.** `grep -rn 'getattr.*failures.*\[\]' src/cosa/agents/` returned exactly one hit — the typo is isolated. No BFE / Deep Research / Podcast siblings.

**Bonus finding**: the report doesn't render `cluster_id` alongside each proposal. From the 22:35 report alone, you can't tell "which cluster did proposal #X come from?" Adding the cluster_id is a small UX improvement (~3 lines in `job.py:561-565`).

### Finding B — "23 near-duplicate proposals" is by design at the prompt level

**File**: `src/cosa/agents/test_fix_expediter/prompts/proposal.py:20`

```
Your task: given a cluster's diagnosis, propose 1 to 3 alternative fixes ranked by your confidence.
```

The system prompt explicitly asks for **up to 3 alternatives per cluster**. 8 clusters × ~3 alternatives ≈ the observed 23 proposals. Within-cluster duplication (e.g., 3 variations of "skip if env vars unset") is a feature of "give me alternatives," not a bug in the matcher.

**The dedup question is therefore a prompt-design question, not a clustering question**:
- **Option α**: Prompt for "the single best fix per cluster; only propose alternatives when no fix clearly dominates (max 2 alternatives)." Aggressive — assumes the LLM can self-rank confidently.
- **Option β**: Keep 1-3 per cluster but add a post-step that fingerprints `(fix_type, files_touched_set, normalized_title_tokens)` and merges within-cluster near-duplicates. Conservative — the LLM keeps its alternative-generation freedom.
- **Option γ**: Make the per-cluster max configurable via INI: `test fix expediter max proposals per cluster = 1` (default could stay at 3 for backward-compat or shift to 1).

**Recommendation: γ + α combined**. Add an INI key `test fix expediter max proposals per cluster` (default 1, stricter than today). Update the prompt to scale based on the configured max (`propose 1 fix` vs `propose 1 to N alternatives`). Operators with higher tolerance can dial it up; the 22:35-style 23-proposal flood becomes the exception, not the default.

### Finding C — Cross-cluster proposal dedup is a separate, smaller win

After Finding B's per-cluster dedup, there's a smaller residual: when multiple clusters share the same root cause (e.g., "all live-pipeline tests need `pytest.skip` on missing creds"), you still get N copies of the same fix across clusters. This is real signal — the operator should know about the spread — but the report could group them: "Fix #1 applies to clusters C2, C5, C7."

**Approach**: post-process proposals after generation. Group by `(fix_type, normalized_files)` fingerprint. Render as a single proposal with an "applies to clusters" list.

This is a UX improvement on top of Findings A + B; not blocking.

### Finding D — Bonus: separate empty-`failures[]` regression in `integration-e2e-remediation.json`

**Out of OOS-1 scope; subsume into OOS-4.** Audit of recent remediation snapshots:

| File | summary says | recorded |
|------|-------------|----------|
| `2026.04.24-at-12:47-…integration-e2e-remediation.json` | 4 failed | **0 recorded** (BROKEN) |
| `2026.04.24-at-16:38-…e2e-integration-remediation.json` (note hyphen order!) | 13 failed | 13 recorded ✓ |
| `2026.04.24-at-17:45-…e2e-remediation.json` | 12 failed | 12 recorded ✓ |
| `2026.04.27-at-22:35-…all-remediation.json` | 42 failed | 42 recorded ✓ |
| `2026.04.28-at-15:32-…integration-e2e-remediation.json` | 4 failed | **0 recorded** (BROKEN) |

The `integration-e2e` test_types combo systematically writes empty `failures[]` despite reporting failures in summary. The `e2e-integration` ordering and `all` test_types both work. Consistent across 04.24 → 04.28. Likely a `test_types` ordering or single-suite-iteration bug in the remediation-snapshot writer (`src/cosa/agents/test_suite/job.py`?). **Add this finding to OOS-4's grep audit scope**.

---

## Revised approach (post-prewarm)

The original speculative plan listed 4 hypotheses. Findings A–D collapse them:

| Original hypothesis | Status |
|--------------------|--------|
| H1: snapshot loader dropping failures | **Refuted for 22:35** (snapshot has 42). Real for OOS-4's `integration-e2e` regression. |
| H2: `_validate_refined` silently dropping refined indices | Refuted — diagnosis + proposal use indices correctly. |
| H3: `_cap_enforce` consolidating into "mixed" tail | Refuted — 8 clusters were generated as expected. |
| H4: proposer hallucinates fixes from inferred problems | **Half-confirmed** — proposer asked for 3 alternatives per cluster (Finding B); proposals ARE grounded but voluminous. |
| (NEW) H5: report-writer field-name typo | **CONFIRMED** (Finding A). The "0 failure(s)" output is purely a rendering bug. |

**Revised scope**:

### Part A — Report-writer typo fix (Finding A) [TRIVIAL]

- 1-line edit in `job.py:549`: `getattr(c, "failures", [])` → `getattr(c, "failure_indices", [])`.
- Optional bonus: render `cluster_id` alongside each proposal (~3 lines in `job.py:561-565`).
- Unit test: replay the 22:35 stalled artifact through the report writer; assert per-cluster failure counts > 0.

**Effort**: XS (10 min including the test).

### Part B — Per-cluster proposal cap (Finding B) [SMALL]

- New INI key: `test fix expediter max proposals per cluster = 1` (changeable; default 1 to reduce 22:35-style floods).
- Splainer entry.
- Update `prompts/proposal.py` system prompt to scale based on `max_proposals_per_cluster` (template variable).
- Update `config.py` to read the new key.
- Pass it through to the prompt builder in the orchestrator's propose phase.
- Unit test: assert that a `max=1` config produces 1-proposal-per-cluster output.

**Effort**: S (~2 hours).

### Part C — Cross-cluster dedup grouping (Finding C) [MEDIUM]

- New file: `src/cosa/agents/test_fix_expediter/proposal_dedup.py` with the fingerprint logic.
- Hook into orchestrator after proposal generation, before the voice gate.
- Update report writer to render the "applies to clusters" group.
- Unit tests for the dedup logic.

**Effort**: M (~3-4 hours).

**Recommended order**: A → B → C. Part A is so cheap you'd do it standalone before the rest. Part B addresses the 22:35-style flood directly. Part C is a polish pass.

### Part D (out-of-scope for OOS-1, lift to OOS-4)

The `integration-e2e-remediation.json` empty-`failures[]` regression (Finding D) belongs in OOS-4's audit because it's the same family of bug — non-canonical state-transition / data-flow paths. Update OOS-4's grep targets to include `_parse_junit_xml` and the snapshot-writer's per-suite iteration logic.

## Evidence

The 22:35 EDT 2026-04-27 TFE run (`tfe-d9786eea`) generated **23 fix proposals** but the cluster-failure assignment came back empty:

```
### 1. C1 — 0 failure(s)
### 2. C2 — 0 failure(s)
...
### 8. C8 — 0 failure(s)

## Proposed fixes
### 1. ... (23 distinct titles)
```

Two distinct anomalies:

1. **Empty clusters** — `heuristic_seed` (in `src/cosa/agents/test_fix_expediter/cluster.py:225`) groups failures by `(normalized_classname, first_non_pytest_frame)`. With ~30 raw failures, we'd expect at least one cluster to have ≥1 failure. The fact that all 8 clusters report `0 failure(s)` means either:
   - The clusters are *generated* (e.g. by LLM refinement) but the **failure_indices field is being lost** somewhere in the pipeline, OR
   - `len(ctx.failures)` is 0 by the time `cluster.py` runs (e.g. the snapshot loader produced an empty failures list despite the report containing failures)

2. **Near-duplicate proposals** — fixes #6/#7/#8 (BFE phase6 smoke), #9-#17 (live-pipeline prereq gating), #21 (sys.argv smuggling — which the explore agent confirmed is a hallucination, see WG-2 history)... the proposer is generating multiple variants of the same idea instead of consolidating. The 23-proposal output is bloated.

## Hypotheses to investigate

| Hypothesis | Test |
|------------|------|
| Snapshot loader is dropping failures | Read the remediation_snapshot referenced by the 22:35 job; count `failures[]`; compare to TFE report's "0 failures per cluster" |
| `_validate_refined` is silently dropping refined clusters' indices | Add a debug log line at the cluster.py:325 fallback path |
| `_cap_enforce` is consolidating ALL failures into a "mixed" tail that's never displayed | Check `_cap_enforce`'s output structure |
| LLM-refine call is succeeding but emitting clusters with empty failure_indices and the validator rubber-stamps it | Inspect `_validate_refined` for an "indices nonempty" assertion |
| Proposer hallucinates fixes for inferred problems instead of reading clusters | Check propose.py for whether it conditions on `failure_indices` count |

## Proposed approach (two parts)

### Part A — Cluster-coverage repair

Add a hard invariant: every cluster MUST have ≥1 failure index, OR cluster generation aborts loudly. Pseudocode:

```python
def heuristic_seed( ctx ):
    clusters = ...  # existing logic
    total_indices = sum( len( c.failure_indices ) for c in clusters )
    assert total_indices == len( ctx.failures ), (
        f"cluster coverage broken: {total_indices} indices over {len( ctx.failures )} failures" )
    return clusters

def _validate_refined( refined, seed_clusters, max_clusters ):
    if any( not c.failure_indices for c in refined ):
        return False  # reject refined clusters with empty indices
    ...  # existing checks
```

Plus add forensics-tier logging: at each phase boundary, emit `[TFE cluster] phase=X clusters=N total_failures=M assigned=K` so the next regression makes the missing-index path visible immediately.

### Part B — Proposal de-duplication

Add a post-propose step that groups proposals by `(fix_type, files_touched_set, normalized_title_tokens)` and merges near-duplicates. Approach:

1. Tokenize titles: lowercase, strip stopwords, sort.
2. Compute fingerprint = `(fix_type, frozenset(files), tuple(token_set))`.
3. Group by fingerprint; for each group, keep highest-confidence proposal (or merge titles + descriptions if confidence is similar).
4. Emit a deduplication report so we can tune the heuristic later.

Target: reduce the 23 → 6-8 distinct proposals (one per actual cluster).

## Files likely to change

- `src/cosa/agents/test_fix_expediter/cluster.py` — invariants + validator strengthening
- `src/cosa/agents/test_fix_expediter/orchestrator.py` — proposal-dedup post-step
- `src/cosa/agents/test_fix_expediter/state.py` — possibly add `proposal_fingerprint` field
- new file: `src/cosa/agents/test_fix_expediter/proposal_dedup.py`
- `src/tests/unit/test_tfe_cluster.py` (existing) — tighten coverage assertions
- new file: `src/tests/unit/test_tfe_proposal_dedup.py`

## Acceptance criteria

- Replaying the 2026-04-27 22:35 snapshot through TFE produces clusters where `sum(len(c.failure_indices)) == len(ctx.failures)`.
- Replaying the 2026-04-27 22:35 snapshot produces ≤ 1.5× the cluster count in proposals (was 23 / 8 ≈ 2.9× — bloated).
- All existing TFE unit tests still pass.
- New unit test verifies cluster-coverage invariant.
- New unit test verifies dedup keeps highest-confidence proposal in each group.

## Estimated effort

S-M: 4-8 hours. The forensics-replay setup is the long pole; once the bug is identifiable, the fix itself is small.

## Out of scope (for OOS-1)

- LLM-refine wiring upgrade (separate ticket).
- Confidence-score recalibration (separate ticket).
