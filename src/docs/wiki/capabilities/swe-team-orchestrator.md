---
capability: swe-team-orchestrator
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.agents.swe_team.job.SweTeamJob@82140429b7
  - cosa.agents.swe_team.job.SweTeamJob.do_all@98c373ef75
  - cosa.agents.swe_team.orchestrator.SweTeamOrchestrator@7eb9e4b72b
  - cosa.agents.swe_team.orchestrator.SweTeamOrchestrator.run@5b89c1bd41
  - cosa.agents.swe_team.safety_limits.SafetyGuard@e7424558e3
  - cosa.agents.swe_team.agent_definitions.get_active_roles@6ad024b691
  - cosa.agents.swe_team.state.OrchestratorState@9003fb52b3
  - cosa.agents.swe_team.state_files.ProgressLog@3ffb7edd2f
---
# SWE Team orchestrator

`SweTeamJob` (`JOB_TYPE` `swe_team`) runs one task through `SweTeamOrchestrator`. A Lead splits the task, a Coder does each piece, and a Tester checks it. [[fix-expediter-bfe]] and [[fix-expediter-tfe]] import its safety guard, hooks and test runner.

## The run
- `run` returns the final summary, or `None` on failure. A `SafetyLimitError` or any other exception sets the state to failed and sends an urgent notification.
- With `dry_run` set, `run` uses `MockAgentSDKSession` and makes no SDK calls. Live mode needs `claude-agent-sdk`; without it the summary says so.
- The Lead splits the task into `TaskSpec` items. If the split cannot be parsed, one task built from the whole description is used.
- Before any work, the run asks "Proceed?" (120 seconds, default yes) through `_gated_confirmation`, so an active proxy may answer. A no, from either, ends the run with "Task cancelled by user after decomposition."

## The roles
- `get_active_roles` returns the roles with `active=True`: lead, coder and tester. The architect, reviewer and debugger exist but are inactive.
- The Lead has `Read`, `Glob` and `Task` and runs in `plan` mode. Coder and tester have `Read`, `Edit` and `Bash` in `acceptEdits` mode, with a `can_use_tool` callback tied to the safety guard.

## The coder and tester loop
- Each task goes to the Coder. When it succeeds and `swe team require test pass` is true (the default), the Tester checks it, at most `MAX_VERIFICATION_ITERATIONS` (3) times. A failed check re-delegates to the Coder with the test feedback; a re-delegation that fails ends that task as failed.
- After the third failure the user chooses one of three. "Continue to next task" moves on. "Skip tests for this task" accepts the work, marked as tests skipped. "Stop and get help" halts the run.
- Failures are counted by `SafetyGuard`, which also limits iterations and wall-clock time. Its iteration, failure and time limits come from the config. The file-change limit is the `SAFETY_LIMITS` constant.

## The decision proxy
- Unless `trust_mode` is `disabled`, an `EngineeringStrategy` proxy is built on the [[decision-proxy]] trust tracker and circuit breaker. `_gated_confirmation` asks it first, then acts on its trust mode; in `shadow` the user is still asked.
- In an active mode, an `act` verdict approves or rejects without asking, with a low-priority notice. A `suggest` verdict adds its suggestion to the question's abstract.
- After a user answer, agreement with the proxy is recorded in the trust tracker.

## Progress and states
- `OrchestratorState` covers initializing, decomposing, delegating, coding, testing, reviewing, debugging, the waiting states, and the terminal and control states.
- `ProgressLog` and `FeatureList` write under `io/swe-team/<session id>/`, and `report_path` is the log file.
