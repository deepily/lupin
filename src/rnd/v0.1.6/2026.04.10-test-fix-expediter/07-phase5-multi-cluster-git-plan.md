# 07 — TFE Phase 5: Multi-Cluster Git Strategy

## Goal

After Phase 3 produces successful fixes for one or more clusters, persist them via the shared `GitStrategist` in a single coherent branch/PR. The branching strategy is: **one branch, N commits (one per cluster), one PR**.

## Why single branch / multiple commits / single PR

1. **Cohesion**: all fixes came from one test run, sharing context. Reviewing them together is faster than K separate PRs.
2. **Reviewer burden**: K separate PRs multiplied by 3-8 clusters is a review-fatigue bomb.
3. **Per-cluster commits**: each cluster's fix lives in its own commit — when you're reading `git log` or bisecting, the unit of change is the cluster, which is also the unit of root cause.
4. **One PR body** consolidates the plan doc into a single review artifact with per-cluster sections.
5. **Phase 6 validation runs once** against the combined branch state — that's what matters to the user anyway.

## Trust-to-git mapping (reused from BFE)

| Trust Level | Mode | Git Strategy | Notes |
|---|---|---|---|
| L1 (shadow) | passive | `commit_only` on current branch | Single-author safe commits, no branch/PR |
| L2 (suggest) | passive | `commit_only` on current branch | Still passive |
| L3+ (active) | active | `branch_and_pr` via `gh` | Full branch + PR via GitHub CLI |
| Proxy unavailable | — | `commit_only` | Conservative fallback |
| `gh` CLI missing | — | Degrade L3+ → `branch_only` | Branch + commit + push; PR step skipped with notification |

`test fix expediter trust mode = inherit` (default) reads the global SWE trust proxy configuration. Alternatives `fixed_l1` / `fixed_l3` force a trust level for testing.

## GitStrategist new method: `commit_and_pr_multi`

Signature:

```python
async def commit_and_pr_multi(
    self,
    clusters: list[tuple[str, str, list[str], ProposedFix]],
    # (cluster_id, cluster_title, files_for_this_cluster, fix_for_this_cluster)
    plan_path: str,
    trust_level: int,
) -> dict:
    """
    Requires:
        - clusters is non-empty
        - each tuple has valid cluster_id, title, files list, fix
        - plan_path is writable
        - trust_level is 1-5
    Ensures:
        - returns {strategy, branch_name, commit_hashes, pr_url, error}
        - strategy in {"commit_only", "branch_only", "branch_and_pr"}
        - commit_hashes is a list (one per cluster), length == len(clusters)
        - on failure: error is set, other fields may be partial
    """
```

### commit_only path (L1-L2)

On the current branch, create K sequential commits:
```
git add {files_for_c1}
git commit -m "fix(tfe): {cluster_id} {title}" -m "{body}"
git add {files_for_c2}
git commit -m "fix(tfe): {cluster_id} {title}" -m "{body}"
...
```

No branch creation, no push, no PR. Commit messages follow a convention (see below).

### branch_and_pr path (L3+)

```
git checkout -b fix/{YYYY-MM-DD}-tfe-{suite_abbrev}-{K}-clusters
# (K sequential commits as above)
git push -u origin <branch>
gh pr create --title "TFE fix: K clusters from {suites_abbrev} test run" --body "<plan_doc_summary>"
```

### branch_only path (L3+ degraded)

Same as `branch_and_pr` but without the `gh pr create` step. Emit a warning notification with the branch name so the user can PR manually.

## Branch naming

```
fix/{YYYY-MM-DD}-tfe-{suite_abbrev}-{K}-clusters
```

Examples:
- `fix/2026-04-11-tfe-e2e-3-clusters`
- `fix/2026-04-11-tfe-integration-5-clusters`
- `fix/2026-04-11-tfe-mixed-2-clusters` (when multiple suites)

Suite abbreviation helper: `_suite_abbrev(suites_run: list[str]) -> str`:
- Single suite: return the suite name
- Multiple suites: return `"mixed"`

Date uses ISO format for sortability in `git branch` listings.

## Commit message convention

**Subject**: `fix(tfe): {cluster_id} {concise title}`

Examples:
- `fix(tfe): C1 re-baseline profile visual regression`
- `fix(tfe): C2 repair Docker pytest.ini bind mount`
- `fix(tfe): C3 handle None in NotificationItem.title`

**Body**: multi-line with sections:

```
{cluster_id}: {fix.title}

Root cause (from TFE diagnosis):
{diagnosis.root_cause}

Failing tests ({N}):
  - {classname}::{name}
  - ...

Confidence: {fix.confidence:.0%}
Risk: {fix.risk_level}
Plan doc: {plan_path}

Source TestSuiteJob: {test_suite_job_id}
TFE job: {tfe_job_id}
```

No "Co-Authored-By" footer — per CLAUDE.md global instructions, only add the Claude co-author line when explicitly asked.

## PR title + body

**PR title**: `TFE fix: {K} clusters from {suites_abbrev} test run`

**PR body** (via heredoc to `gh pr create --body`):

```markdown
## Summary

TestSuite job `{test_suite_job_id}` reported {N} test failures. TFE clustered
them into {K} root causes and applied targeted fixes.

## Clusters fixed

| Cluster | Title | Fix type | Confidence | Files changed |
|---------|-------|----------|------------|---------------|
| C1      | {title} | {fix_type} | {confidence:.0%} | {file_count} |
| C2      | ...   | ...      | ...        | ...           |

## Test plan

- [ ] TFE Phase 6 rerun (`test_types={original_test_types}`) passes
- [ ] Manual review of cluster fixes for correctness
- [ ] Visual inspection of snapshot diffs (if visual regression cluster)

## Source references

- Source TestSuiteJob: `{test_suite_job_id}`
- TFE job: `{tfe_job_id}`
- Plan doc: [`{plan_path}`]({plan_path})

🤖 Generated with [TestFixExpediter](../../src/rnd/v0.1.6/2026.04.10-test-fix-expediter/00-index.md)
```

## Plan doc update

After the branch + commits are created, `PlanWriter.update_git_references(plan_path, fix_result)` fills in the Git References section of the plan doc. For multi-cluster mode, this section becomes:

```markdown
## Git References

- **Branch**: `fix/2026-04-11-tfe-e2e-3-clusters`
- **Commits**:
  - C1: `a1b2c3d` — fix(tfe): C1 re-baseline profile visual regression
  - C2: `b2c3d4e` — fix(tfe): C2 repair Docker pytest.ini bind mount
  - C3: `c3d4e5f` — fix(tfe): C3 handle None in NotificationItem.title
- **PR**: https://github.com/deepily/lupin/pull/1234
```

## Safety: partial commit handling

If a fix partially succeeded (`fix_results` has both success and failure), only the **successful** clusters get committed. The failed clusters' changes (if any) must NOT be committed — they represent incomplete work.

Implementation detail: `FixExecutor` returns `files_changed` only for fixes that applied cleanly. Phase 3 aggregates only successful clusters' files into `files_changed_by_cluster`. Phase 5 only iterates over successful clusters.

## Voice / notification

- **Session topic**: `voice_io.set_session_topic("TFE Phase 5: Git commit and PR")`
- **Breadcrumb per commit**: `notify(f"Committing cluster {cluster_id}: {commit_hash[:8]}", priority="low")`
- **Success notification**: `notify(f"TFE branch created: {branch_name}, PR: {pr_url}", priority="medium")` with abstract showing the full commit list
- **Degradation notification** (gh missing): `notify(f"gh CLI missing - branch {branch_name} created but no PR. Create manually: {branch_name}", priority="high")`
- **Failure notification**: `notify(f"TFE git strategy failed: {error}", priority="urgent")` — TFE still completes with the `failed` state and users can recover manually

## Unit test coverage

Target: `src/tests/unit/test_git_strategist_shared.py` (new file)

| Test | Mock | Assertion |
|------|------|-----------|
| `test_commit_and_pr_single_still_works` | Mock GitOps | BFE path unchanged |
| `test_commit_and_pr_multi_commit_only_l1` | Mock GitOps, trust=1 | K sequential commits on current branch, no push |
| `test_commit_and_pr_multi_commit_only_l2` | Mock GitOps, trust=2 | Same as L1 |
| `test_commit_and_pr_multi_branch_and_pr_l3` | Mock GitOps + mock gh | Branch created, K commits, push, PR created |
| `test_commit_and_pr_multi_branch_only_gh_missing` | Mock GitOps, gh missing | Branch + K commits + push, no PR, warning notif |
| `test_commit_and_pr_multi_empty_clusters` | any | Raises ValueError — caller must filter |
| `test_commit_message_format` | any | Matches `fix(tfe): {id} {title}` |
| `test_branch_slug_single_suite` | ["e2e"], K=3 | `fix/YYYY-MM-DD-tfe-e2e-3-clusters` |
| `test_branch_slug_mixed_suites` | ["e2e", "integration"], K=2 | `fix/YYYY-MM-DD-tfe-mixed-2-clusters` |
| `test_plan_doc_git_references_populated` | any | Plan doc has `## Git References` section with branch + commits + PR |
| `test_partial_failure_only_successful_committed` | 2 successful 1 failed in inputs | Only 2 commits created, failed cluster's files NOT committed |
