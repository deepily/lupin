---
capability: fix-expediter-tfe
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.agents.test_fix_expediter.job.TestFixExpediterJob@402076182b
  - cosa.agents.test_fix_expediter.job.TestFixExpediterJob.do_all@14c1dab6f0
  - cosa.agents.test_fix_expediter.orchestrator.TFEOrchestrator@71b61f0581
  - cosa.agents.test_fix_expediter.orchestrator.TFEOrchestrator.run_phase2_propose@a962b5c905
  - cosa.agents.test_fix_expediter.orchestrator.TFEOrchestrator.run_phase5_git@c558da9428
  - cosa.agents.test_fix_expediter.orchestrator.TFEOrchestrator.run_phase6_validation@b7f67e93c3
  - cosa.agents.test_fix_expediter.cluster.llm_refine@a616338366
  - cosa.agents.test_fix_expediter.resume_resolver.resolve_resume_target@a22583b016
  - cosa.agents.test_fix_expediter.state.TFEPhase@020eb07553
---
# Test Fix Expediter (TFE)

TFE takes the failures from one finished test-suite run, groups them into clusters, and has agents diagnose, propose and apply fixes, then queues a rerun. `TestFixExpediterJob` (`JOB_TYPE` `test_fix_expediter`) is the queue entry and `TFEOrchestrator` runs the phases. The fix loop and the git step are shared with [[fix-expediter-bfe]] through [[fix-shared-primitives]]; the failures come from [[scheduled-test-suite]].

## The phases, in the order `do_all` runs them
- Input: `load_from_path` or `load_from_artifacts` builds a `TestRemediationContext` from a suite run's remediation snapshot.
- Clustering, `run_phase0_cluster`: `heuristic_seed` groups failures; `llm_refine` then enforces the cluster cap. No model call is wired: the orchestrator passes no `refine_fn`, so only the cap runs.
- Over the cap, the `max_clusters - 1` largest clusters are kept and the rest merge into one "mixed" cluster. Shipped `max clusters` is 8 and `max proposals per cluster` is 1.
- Diagnosis runs a Lead agent per cluster (`Read`, `Glob`, `Grep`, `Bash`, `plan` mode). Proposal, `run_phase2_propose`, uses a Lead with `Read`, `Glob`, `Grep` only.
- The fix and git steps run inside `worktree_scope`; the rerun step runs outside it.
- `TFEPhase` also has `PARTIAL` (some clusters fixed, others failed) besides completed, failed and skipped.

## The voice gate
- `aggregate` mode (shipped) asks one multi-select question over all proposals; `per_cluster` asks one yes/no per proposal. In dry-run every proposal is selected without asking.
- In `aggregate` mode a timeout, or any other gate failure, goes to `voice gate timeout policy`. `stall` (shipped) raises, so the job stalls and can be resumed from its checkpoint. `top_1` and `top_n` take the highest-confidence proposals; `none` selects nothing; `delegate` raises `NotImplementedError` today.
- In `per_cluster` mode a proposal whose question fails or times out is skipped, not applied, and the policy is not used.

## Fix, git, rerun
- `run_phase3_fix` hands each selected fix to the shared `FixExecutor` with prompt key `tfe`. With `continue on cluster failure` false, one failed cluster stops the rest; shipped value is true.
- `run_phase5_git` makes one commit per fixed cluster. At trust level 1 or 2 they go on the current branch and no pull request is opened. At 3 and above it creates a branch, commits per cluster and runs `gh pr create`. The strategist's push step needs a `push_branch` that `GitOps` does not have, so no push runs today (delete this clause when row c07aef9f-b7b9-4001-969b-7b74c2a87bab closes). If the PR step fails the branch is left. `trust mode` `inherit` (shipped) gives level 1 because TFE wires no proxy, so shipped TFE opens no PR; `fixed_l3` gives 3.
- `run_phase6_validation` queues a `TestSuiteJob` only if a fix succeeded, and does not wait for it. `rerun scope` `affected` (shipped) reruns the original suites; `full` runs all.
- The rerun carries `triggered_by_tfe`, and `test_suite_completion_watchdog` skips such jobs, so a rerun does not start another TFE.

## Resuming
- `resolve_resume_target` finds a stalled job from a `tfe-` job id, a plan path, or a fuzzy description. A checkpoint-file path is recognised but not implemented. Guide: `src/docs/agents/test-fix-expediter-guide.md`; keys are `test fix expediter *`.
