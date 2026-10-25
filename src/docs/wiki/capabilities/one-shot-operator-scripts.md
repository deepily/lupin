---
capability: one-shot-operator-scripts
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.clock_hold_plugin.pytest_collection_finish@b31b4ed2d5
  - scripts.init_test_database.main@509ada703a
  - scripts.probe_cc_bounded_billing.main@ad108a48b6
  - scripts.run-heartbeat-arbiter.main@bd651e503c
  - scripts.tfe_to_cc_phase1_smoke.main@3c4b1e848d
---
# One-shot operator scripts

Five single-entry scripts for tests and probes that an operator or a test run starts by hand. None is called from application code.

## Test-run helpers
- `pytest_collection_finish` in the clock-hold plugin sleeps after collection for `LUPIN_CLOCK_HOLD_SECONDS` (default 12.0, zero or less means no hold). It is a demonstration lever, not the shipped detector.
- `main` in the test-database initializer refuses to run unless the testing config block is active. It then creates the auth schema and runs the api-keys table script as a child process. It returns 0 on success and 1 on any error.

## Probes
- `main` in the bounded-billing probe submits ten bounded Claude Code jobs through the v2 front door, one minute apart. Five read the repo and five search the web. It prints each job's reported cost and saves the raw results under `/tmp`. The answer to compare against is the console balance, which the script cannot read.
- `main` in the phase-one smoke runs `claude -p` inside the test container against one synthetic failure cluster. It checks the diagnosis block against its output contract and appends the result to the execution log. It exits 0 on a pass and 1 otherwise.

## Arbiter runner
- `main` in the heartbeat-arbiter runner launches the arbiter consumer in dry-run mode by default. A dry run reads real fleet state and only logs the pings and posts it would send. `--live` sends them, `--once` runs a single poll, and `--quiet` must stay below `--alive`.
