---
capability: swe-team-orchestrator
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.swe_team.job.SweTeamJob@9a70ce3429
  - cosa.agents.swe_team.job.SweTeamJob.do_all@ea4b930824
  - cosa.agents.swe_team.orchestrator.SweTeamOrchestrator@6638595dfc
  - cosa.agents.swe_team.strategy_builder.build_ini_engineering_strategy@378c620ffe
  - cosa.agents.swe_team.orchestrator.SweTeamOrchestrator.run@5b89c1bd41
  - cosa.agents.swe_team.safety_limits.SafetyGuard@e7424558e3
  - cosa.agents.swe_team.agent_definitions.get_active_roles@6ad024b691
  - cosa.agents.swe_team.state.OrchestratorState@9003fb52b3
  - cosa.agents.swe_team.state_files.ProgressLog@3ffb7edd2f
---
# SWE Team orchestrator

`SweTeamJob` (`JOB_TYPE` `swe_team`) runs one task through `SweTeamOrchestrator`. Its `do_all` calls `_run_execute`, and a failure stores `SWE Team task failed: <error>` and is raised again. A Lead splits the task, a Coder does each piece, and a Tester checks it. Its safety guard, hooks and test runner are imported by [[fix-expediter-bfe]] and [[fix-expediter-tfe]].

## The run
- `run` returns the final summary, or `None` on failure. A `SafetyLimitError` or any other exception sets the state to failed and sends an urgent notification. In the delegation, verification and re-delegation calls, a result message with `is_error` raises through `raise_error_result`. The delegation and re-delegation calls catch it and record the CLI text as the task's error, so it fails the task. The verification call records it as a failed check, so the coder is asked again like after a failed test. None of the three fails the run by itself. The analysis and decomposition calls ignore a result message and fall back. With `dry_run` set, `run` uses `MockAgentSDKSession` and makes no SDK calls. Live mode needs `claude-agent-sdk`; without it the summary says so.
- The Lead splits the task into `TaskSpec` items. If the split cannot be parsed, one task built from the whole description is used.
- Before any work, the run asks "Proceed?" (120 seconds, default yes) through `_gated_confirmation`, so an active proxy may answer. A no, from either, ends the run with "Task cancelled by user after decomposition."

## The roles
- `get_active_roles` returns the roles with `active=True`: lead, coder and tester. The architect, reviewer and debugger exist but are inactive. The Lead has `Read`, `Glob` and `Task` and runs in `plan` mode. Coder and tester have `Read`, `Edit` and `Bash` in `acceptEdits` mode, with a `can_use_tool` callback tied to the safety guard.

## The coder and tester loop
- Each task goes to the Coder. When it succeeds and `swe team require test pass` is true (the default), the Tester checks it, at most `MAX_VERIFICATION_ITERATIONS` (3) times. A failed check re-delegates to the Coder with the test feedback; a re-delegation that fails ends that task as failed.
- After the third failure the user chooses one of three. "Continue to next task" moves on. "Skip tests for this task" accepts the work, marked as tests skipped. "Stop and get help" halts the run.
- Failures are counted by `SafetyGuard`, which also limits iterations and wall-clock time. Its iteration, failure and time limits come from the config. The file-change limit is the `SAFETY_LIMITS` constant.

## The decision proxy
- Unless `trust_mode` is `disabled`, an `EngineeringStrategy` proxy is built on the [[decision-proxy]] trust tracker and circuit breaker. `_gated_confirmation` asks it first, then acts on its trust mode; in `shadow` the user is still asked.
- In an active mode, an `act` verdict approves or rejects without asking, with a low-priority notice. With `swe engineering proxy ask before act` true (shipped false), the user is asked instead. A `suggest` verdict adds its suggestion to the question's abstract.
- After a user answer, agreement with the proxy is recorded in the trust tracker. An auto-approval records no agreement, because no human answered and the proxy would be grading its own work.
- `SweTeamJob` passes its `user_email` on. The orchestrator loads that user's stored `swe` trust rows (counts, level, any breaker trip), so trust carries over between jobs. After each answer, and on a breaker trip, the counters and level are stored. Under the `blr` trust model the answer also feeds the BLR model, and its state is stored in the same write. A confirmation the proxy evaluated also writes a `proxy_decisions` row for the ratify page. That happens after an auto-approval, or after a user answer once its trust record succeeds. With no proxy or a failed evaluation, no row is written. Database failures are logged and never stop the run.
- `build_ini_engineering_strategy` builds the strategy from INI values: trust thresholds, the trust model, breaker settings, the three cap-level keys of [[swe-engineering-proxy-rules]] and the audit sample rate. BFE uses the same builder. An unknown trust model raises `InvalidTrustModelError`; any other unreadable key keeps the default.

## Progress and states
- `OrchestratorState` covers initializing, decomposing, delegating, coding, testing, reviewing, debugging, the waiting states, and the terminal and control states. `ProgressLog` and `FeatureList` write under `io/swe-team/<session id>/`, and `report_path` is the log file.
