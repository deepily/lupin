---
capability: fix-shared-primitives
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.agents.shared.fix_executor.FixExecutor@5dcfbbea82
  - cosa.agents.shared.fix_executor.FixExecutor.execute_fix@4a060ae1d4
  - cosa.agents.shared.fix_executor.register_fix_prompts@1eec1c5893
  - cosa.agents.shared.git_strategist.GitStrategist.resolve_trust_level@d0d72d8ff8
  - cosa.agents.shared.git_strategist.GitStrategist.commit_and_pr_single@c3b2518a8c
  - cosa.agents.shared.git_strategist.GitStrategist.commit_and_pr_multi@dde2110642
  - cosa.agents.shared.plan_writer.PlanWriter.write_plan@7642a07cc3
  - cosa.agents.shared.report_writer.ReportWriter.write@14bbc03bbd
---
# Shared fix primitives

Both [[fix-expediter-bfe]] and [[fix-expediter-tfe]] use these: a coder and tester retry loop (`FixExecutor`), a git step (`GitStrategist`), and two writers for plan and report files. The `worktree_*` modules in the same package are not covered here.

## FixExecutor
- `execute_fix` returns a result and the list of changed files. The caller keeps the state machine, the plan update and the completion notice, and passes in the coder and tester callbacks.
- Agent prompts are looked up by key. `register_fix_prompts` stores a bundle under a key, and the two agents register `bfe` and `tfe`.
- A coder that returns nothing is a failure. Otherwise the tester checks the fix up to `max_fix_attempts` times. A failed check before the last re-delegates to the coder with the tester's output; a pass ends the loop as success.
- Failing the last check auto-rejects the fix: no operator is asked, and the tail of the tester output goes into the result.
- A `SafetyGuard` is built per call: iteration limit ten times `max_fix_attempts`, failure limit `max_fix_attempts + 1`, and the wall-clock budget as its timeout.

## The runtime brake
- Every coder and tester call runs under `asyncio.wait_for` with the wall-clock budget. When it runs out, `BFETimeoutError` is raised.
- `execute_fix` re-raises that error instead of turning it into a result, so the job fails and its pool slot is freed.
- Any other error comes back as a failed result; a safety-limit error also sends an urgent notification.

## GitStrategist
- `resolve_trust_level` returns 1 when the proxy is missing or anything goes wrong; otherwise it returns the level read from the proxy's trust tracker.
- Below level 3, the commits stay on the current branch (`commit_only`). At 3 and above, `commit_and_pr_single` makes a fix branch, commits and pushes, then opens a pull request through `gh`. After any PR failure the result is `branch_only`.
- `commit_and_pr_single` makes one commit. `commit_and_pr_multi` is what TFE uses: one commit per cluster, and a pull request only at level 3 and above. Its push step needs a `push_branch` that `GitOps` lacks, so no push runs today (delete this clause when row c07aef9f-b7b9-4001-969b-7b74c2a87bab closes).
- Both return a dict with an `error` field instead of raising.

## Plan and report files
- `PlanWriter.write_plan` writes under `io/swe-team/plans/<user email>/`, named `<date>-<slug>-plan.md`.
- `ReportWriter.write` writes under `io/swe-team/reports/<user email>/`. The name has a fixed `EST` token, while the time itself is America/New_York.
