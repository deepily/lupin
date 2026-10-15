---
capability: swe-team-test-run-and-dry-run
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.swe_team.test_runner.TestRunResult@82eeb97302
  - cosa.agents.swe_team.test_runner.run_pytest@3c1e616b2a
  - cosa.agents.swe_team.mock_clients.MockAgentMessage@5ecf873881
  - cosa.agents.swe_team.mock_clients.MockAgentSDKSession@5b7f9aace2
---
# SWE team test run and dry run

The orchestrator confirms the tester's work by running pytest itself, and it can rehearse a whole task without calling a model. Both are used by [[swe-team-orchestrator]].

## What it does
- `run_pytest( test_path, timeout_secs=120, max_output=4000 )` runs `python -m pytest <path> -v --tb=short --no-header` as a subprocess and returns a `TestRunResult`. It never raises.
- `TestRunResult` carries `passed`, the total, passed, failed and error counts, the output, the duration and a `timed_out` flag.
- `passed` is true only when nothing failed or errored and at least one test passed.
- The counts come from the first `N passed`, `N failed` and `N error` matches in the output. Output beyond `max_output` characters is cut and a note says how many.
- On a timeout the process is killed and the result says so. Any other exception gives a failed result with one error.
- `MockAgentSDKSession` replays six fixed messages: two from the lead, then coder, tester, reviewer and lead again.
- Each message is a `MockAgentMessage` with a role, content and agent name. Delays are scaled by `DELAY_MULTIPLIER`, which tests set to 0.
- Its summary reports 0 tokens and a cost of 0.0, with `dry_run` true. The session id looks like `st-` and eight hex digits.

## Don't
- Don't use the dry run to check real task content. The messages are fixed and ignore the task text.
