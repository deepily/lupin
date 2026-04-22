# 03 — TFE Phase 0: Clustering

## Goal

Transform a flat list of N test failures (from the TestSuiteJob remediation snapshot) into K ≤ 8 coherent clusters, each representing one shared root cause. Clusters drive the rest of the pipeline: per-cluster diagnose, per-cluster propose, per-cluster fix application, per-cluster commit within the single branch.

## Input

`TestRemediationContext` (from `snapshot_loader.py`, see [06](06-phase3-fix-delegation-plan.md) for the model). The relevant field:

```python
failures : list[dict]  # each dict has classname, name, type, message, traceback, suite
```

Typical N: 1-50. Realworld observed: 22 failures → 3 clusters. Upper bound enforced at `test fix expediter max cluster seed failures = 50`; beyond that the watchdog defers to human.

## Output

```python
class FailureCluster(BaseModel):
    cluster_id              : str             # "C1", "C2", ... K
    failure_indices         : list[int]       # indices into TestRemediationContext.failures
    shared_error_signature  : str             # normalized summary of the common error
    hypothesis              : str             # likely root cause (one sentence)
    affected_files_guess    : list[str]       # inferred from classnames/tracebacks
    confidence              : float           # 0.0 - 1.0
```

## Approach — hybrid heuristic + LLM

### Stage 1: Heuristic seed (`cluster.py::heuristic_seed()`)

Pure Python, no LLM cost. Handles the 80% case.

```python
def heuristic_seed(failures: list[dict]) -> list[FailureCluster]:
    """
    Group failures by (normalized_classname_prefix, first_non_pytest_frame).

    Rationale:
      - Same test class + same traceback origin → same bug.
      - Parametrized tests differ only in [param], same classname.
      - Fixture errors have traceback originating in the fixture function, not the test.
      - Collection errors have traceback in pytest's collector.
    """
    seeds = defaultdict(list)
    for idx, f in enumerate(failures):
        key = _compute_seed_key(f)
        seeds[key].append(idx)

    clusters = []
    for key, indices in seeds.items():
        clusters.append(FailureCluster(
            cluster_id=f"S{len(clusters)+1}",  # provisional id
            failure_indices=indices,
            shared_error_signature=_signature_from_key(key),
            hypothesis="",  # filled by LLM refine
            affected_files_guess=_guess_files(key, failures, indices),
            confidence=0.5,  # heuristic baseline
        ))
    return clusters
```

Helper functions:
- `_compute_seed_key(failure_dict) → tuple[str, str]` — normalizes classname (strip `[param]` suffix from `name`, keep `classname`) and extracts the first traceback frame that does not belong to pytest/_pytest/conftest/unittest.
- `_signature_from_key(key) → str` — human-readable: `"{classname} at {file}:{line}"`.
- `_guess_files(key, failures, indices) → list[str]` — parse classname → test file path, parse traceback for tested-module paths.

### Stage 2: LLM refinement (`cluster.py::llm_refine()`)

Opus, read-only SDK with `Read` tool only (no Grep/Bash — clustering doesn't need source exploration). The LLM sees:
- Full remediation snapshot (JSON)
- Heuristic seed clusters (JSON)
- The `max_clusters` cap

And returns final cluster assignments with merges/splits/relabels justified in `hypothesis`.

Prompt shape (details in [10-prompt-design.md](10-prompt-design.md)):

```
SYSTEM: You are a test-failure triage analyst. Group the N pytest failures
into the smallest number of clusters where each cluster represents ONE shared
root cause. Use the heuristic seeds as a starting point — you may merge, split,
or relabel them.

A cluster is "one root cause" if fixing one thing would fix all failures in
the cluster. Parametrized tests with the same failure mode belong together.
Fixture errors that break many tests belong together (the fixture is the bug,
not the tests).

Maximum K clusters: {max_clusters}. Minimum K: 1. Return JSON matching the
FailureCluster schema for each cluster.

USER: <JSON of snapshot + heuristic seeds>
```

### Stage 3: Validation + output

- Assert `1 <= len(clusters) <= max_clusters`
- Assert every failure index appears in exactly one cluster (no duplicates, no drops)
- Assign stable `cluster_id` strings (`C1`, `C2`, ...)
- Persist clusters to `self.artifacts["clusters"]` for UI display and downstream phases

## Voice / notification

- **No voice gate** at Phase 0. Clusters are shown to the user in the Phase 2 proposal gate.
- **Breadcrumb**: `notify("Clustering N failures into K groups...", priority="low")` before LLM refinement. In dry-run mode this is the only visible signal.

## Edge cases handled

| Case | Behavior |
|------|----------|
| N=0 (snapshot has no failures) | Watchdog eligibility gate rejects upstream. Should never reach Phase 0. Assert and raise if it does. |
| N=1 (one failure) | Heuristic produces 1 cluster. LLM refinement no-op. |
| Heuristic produces K > max_clusters | LLM refinement asked to consolidate down to max_clusters, merging smallest/similar clusters first. |
| LLM returns K > max_clusters | Truncate with warning notification. |
| LLM returns duplicate indices across clusters | Re-prompt once; if still bad, fall back to heuristic seeds verbatim. |
| LLM call fails (rate limit, timeout) | Retry per api_client retry policy (8 retries, 30s initial for rate limit). If still fails, fall back to heuristic seeds. |
| Collection errors (pytest couldn't import a test file) | Form their own cluster by file path. Easy for Phase 1 diagnosis. |
| Fixture errors (same fixture breaks many tests) | Heuristic catches this via shared traceback frame in the fixture source. |

## Unit test coverage

Target: `src/tests/unit/test_tfe_cluster.py`

| Test | Fixture | Assertion |
|------|---------|-----------|
| `test_heuristic_seed_single_cluster` | `snapshot_1cluster.json` | Returns 1 cluster with all failures |
| `test_heuristic_seed_k_clusters` | `snapshot_kcluster.json` | Returns K clusters, disjoint coverage |
| `test_heuristic_seed_parametrized` | `snapshot_parametrized.json` | Parametrized test variants grouped as one cluster |
| `test_heuristic_seed_fixture_error` | `snapshot_fixture_error.json` | Fixture failures group by fixture source, not test source |
| `test_heuristic_seed_collection_error` | `snapshot_collection_error.json` | Collection errors grouped by file path |
| `test_heuristic_seed_max_cluster_cap` | Large synthetic K=20 | Heuristic returns all 20; LLM refine consolidates to ≤ 8 (mocked) |
| `test_llm_refine_mocked` | any | Mock API client returns canned 3-cluster response; assert output shape |
| `test_llm_refine_duplicates_retry` | any | Mock returns duplicate indices once, then valid; assert retry taken |
| `test_llm_refine_fallback_on_fail` | any | Mock always fails; assert fallback to heuristic seeds |
| `test_voice_breadcrumb` | any | Assert `notify` called with `priority="low"` before LLM call |

## Future extensions (not in MVP)

- **Parallel cluster processing in later phases** — Phase 0 could pre-sort clusters by confidence so Phase 1 tackles the highest-signal first.
- **Semantic similarity via embeddings** — replace heuristic `first_non_pytest_frame` with a cheap embedding distance over traceback summaries. Deferred; heuristic is sufficient for MVP.
- **Flake filtering** — rerun each cluster's failures in isolation to filter flakes before diagnosis. Deferred; flake detection is its own feature.
