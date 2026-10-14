---
capability: fix-expediter-bfe
pin_algorithm: py3.13.x60338d/ts5.9.3
pins:
  - cosa.agents.bug_fix_expediter.job.BugFixExpediterJob@9e3e736da9
  - cosa.agents.bug_fix_expediter.job.BugFixExpediterJob.do_all@42afdb8dc9
  - cosa.agents.bug_fix_expediter.orchestrator.BFEOrchestrator@3765b984a8
  - cosa.agents.bug_fix_expediter.orchestrator.BFEOrchestrator.run_diagnosis@47e97bb180
  - cosa.agents.bug_fix_expediter.orchestrator.BFEOrchestrator.run_proposal@c395c18198
  - cosa.agents.bug_fix_expediter.orchestrator.BFEOrchestrator.run_fix@01cb024310
  - cosa.agents.bug_fix_expediter.orchestrator.BFEOrchestrator.run_git_strategy@b60c7ba7e3
  - cosa.agents.bug_fix_expediter.state.BFEPhase@12b47361c6
---
# Bug Fix Expediter (BFE)

BFE takes one dead (failed or interrupted) queue job and tries to fix the code that killed it. `BugFixExpediterJob` is the queue entry; `BFEOrchestrator` runs the phases. The fix loop and the git step are shared with [[fix-expediter-tfe]] through [[fix-shared-primitives]]. It is an `AgenticJobBase` job whose agents call the Claude Agent SDK (`sdk_query`) directly; unlike [[bounded-claude-code-jobs]] it does not use `ClaudeCodeJob`.

## What it does
- `BugFixExpediterJob.do_all` is the queue's entry point; it bridges to the async `_execute` and returns a conversational summary. Its `JOB_TYPE` is `bug_fix_expediter`.
- The phases are `BFEPhase`: packaging, diagnosing, proposing, fixing, committing, resubmitting, retrying, and `WAITING_CONFIRMATION`. Terminal phases are completed, failed and skipped.
- `run_diagnosis` has a Lead agent read the failure and return a `DiagnosisResult`. `run_proposal` returns `ProposedFix` options and writes a plan document. On a resumed run both skip the Lead agent when the checkpoint already holds their output, and the stalled gate is asked again.
- `run_fix` has a Coder apply the chosen fix and a Tester check it. The retry loop and escalation live in the shared `FixExecutor`, not here.
- `run_git_strategy` commits the changes after a successful fix.

## What each agent is given
- The Lead (diagnosis) has `Read`, `Glob`, `Grep` and `Bash`, runs in `plan` mode and has no `Edit` tool. The proposal agent is built the same way.
- The Coder and the Tester have `Read`, `Edit` and `Bash` in `acceptEdits` mode. Both carry a `can_use_tool` callback from `build_can_use_tool`, which wraps the safety guard.

## Choosing the fix
- One fix with confidence 0.8 or more is offered as a single yes/no question, default yes. Several fixes, or one under 0.8, are offered as a choice with a "Reject all" option.
- When `bug fix expediter require user confirm` is false, the highest-confidence fix is taken without asking.

## Git, by trust level
- `run_git_strategy` does nothing when the fix failed or no file changed. Levels 1 and 2 commit on the current branch only; an unreadable proxy gives level 1.
- Level 3 and above push a fix branch and open a pull request through `gh`. They do so only when `bug fix expediter push fix branch enabled` is true. The shipped INI has it false. With it false the fix is committed on its fix branch and nothing is pushed. No PR opens, the original branch is restored, and the run says so and names the key. With it true, a missing `gh` or a failed PR step leaves the branch pushed and no PR (`branch_only`).

## Worktree isolation
- With `cosa worktree enabled` true, `worktree_scope` creates a worktree under the sandbox root, named by job id. Coder, Tester and git use it; the Lead does not.
- With it off, the scope only warns about uncommitted changes. The orchestrator forgets the path on exit even if the caller raises. The directory is removed only when `cosa worktree auto cleanup` is true; the shipped INI has it false.
- Guide: `src/docs/agents/bug-fix-expediter-guide.md`; settings are the `bug fix expediter *` keys in `lupin-app.ini`.
