# OOS-1 — TFE/BFE pattern-matcher upgrade (PROPOSAL — awaiting ratification)

**Status**: Plan only. No code work until ratified.

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
