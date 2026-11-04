---
capability: swe-team-state-and-task-files
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.swe_team.state.DelegationResult@0cde500df0
  - cosa.agents.swe_team.state.JobSubState@03141c2a87
  - cosa.agents.swe_team.state.ReviewFinding@014804f2a3
  - cosa.agents.swe_team.state.SweTeamState@999e761a0b
  - cosa.agents.swe_team.state.TaskSpec@15daeb8bb3
  - cosa.agents.swe_team.state.VerificationResult@6fac76b34c
  - cosa.agents.swe_team.state.create_initial_state@707b5fd2b3
  - cosa.agents.swe_team.state_files.FeatureList@2c71e53055
---
# SWE team state and task files

The orchestrator passes typed records between its phases and saves the task list so a run can resume. The state machine is in [[swe-team-orchestrator]].

## What it does
- `SweTeamState` is a typed dict for one run: the task text, task specs, results, review findings, verification results, a final summary, files changed and metadata.
- `create_initial_state` returns it with every counter at 0, every list empty and every optional field `None`.
- `TaskSpec` is one unit of work: title, objective, output format, tool guidance, scope boundary, assigned role (default `coder`), priority 1 to 5 and optional dependencies.
- `DelegationResult` records a task's status (`success`, `failure` or `partial`), output, files changed, errors, test output and a confidence from 0 to 1.
- `ReviewFinding` has a severity (`critical`, `major`, `minor` or `suggestion`), a file, an optional line, a description and a suggestion.
- `VerificationResult` holds one test cycle: passed flag, tester output, an independent run result, test files, iteration count and a status of `passed`, `failed` or `skipped`. The status defaults to `failed`.
- `JobSubState` has five values: `executing`, `waiting_for_human`, `waiting_for_subtask`, `waiting_for_llm` and `paused`.
- `FeatureList` keeps the task list in `feature_list.json`. `add_task` stamps it incomplete, and `mark_complete` stamps a completion time and raises `IndexError` for a bad index.
- `get_pending` returns `( index, task )` pairs for tasks not yet complete. `load` returns an empty list for a missing or unreadable file.

## Invariants
- Without a storage directory, `FeatureList` uses a temporary directory that `cleanup` removes.
- `save` overwrites the file in place and logs an I/O error instead of raising.
