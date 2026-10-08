---
capability: scheduled-test-suite
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.agents.test_suite.job.TestSuiteJob@ea20f71658
  - cosa.agents.test_suite.job.TestSuiteJob.do_all@e22090c710
  - cosa.agents.test_suite.job.unknown_suite_names@9f548f8b52
  - cosa.agents.test_suite.job.BetweenSuiteResetError@d5be6190f9
  - cosa.agents.test_suite.v2_client.submit_body@44eb514dad
  - cosa.agents.test_suite.v2_client.read_reply@977acafd19
  - cosa.agents.test_suite.attestation.append_attestation@ea206219ee
  - cosa.agents.test_suite.attestation.verify_chain@8888b25752
---
# Scheduled test suite

`TestSuiteJob` (`JOB_TYPE` `test_suite`) runs the project's test suites as a queue job. It starts each suite's shell script as a subprocess. The failures of a finished run are what [[fix-expediter-tfe]] repairs. Guide: `src/docs/agents/test-suite-scheduling-guide.md`.

## Submitting
- The one door is `POST /api/v2/submit` with the command `agent router go to test suite`. `submit_body` builds the request, and `read_reply` reads the answer. The old `/api/test-suite/submit` door answers 410.
- A refused submit is HTTP 200 with `status` `failed` and the cause in `error`. Only `status` `waiting` on a 2xx answer counts as accepted.
- `unknown_suite_names` lists names that are not keys of `SUITE_SCRIPTS`. `e2e_ui` is a directory, not a suite.
- `all` expands to `ALL_SUITE_COMPONENTS`: typecheck, stylelint, doclint, unit, cosa, coverage, typescript, smoke, docker_smoke, websocket, integration, e2e_a, e2e_b. Duplicates are dropped, first one wins.
- A server in a container refuses a request naming `unit` or `docker_smoke`, and `all` there leaves both out and says `unit: not run here, host tier` and the same for `docker_smoke`.
- The job always runs with `monopolize=True`, because the scripts swap the database config.

## Running
- Before the first suite, a preflight raises `RuntimeError` if a non-test agentic job is in flight on `lupin_db_test`. Off that database it does nothing.
- Suites run one after another. A failing suite does not stop the sweep; a cancel request or a failed reset does.
- Each suite has its own timeout in `SUITE_TIMEOUTS_SECONDS`. An unknown suite name is refused at submit and never runs.
- Between two suites, and never before the first or after the last, the shared test database is reset. Non-protected users are deleted and residue tables truncated. Off `lupin_db_test` the reset is a logged no-op.
- A failed reset raises `BetweenSuiteResetError`. The next suite is recorded as failed with `errors` 1, the sweep stops, and the summary still reports a failing verdict.

## Verdicts
- A run with all counts zero is `NOT EXECUTED`, not a pass. A collection error is `COLLECTION ERROR`.
- Any failed or errored test is `FAILED`, and so is a printed coverage-threshold miss on a run where tests ran. A tier that did not run, with no failures, is `NOT EXECUTED`. Only a run where every tier ran with no failures is `PASSED`.

## Attestation
- After each suite, `append_attestation` appends a record to a ledger under `io/test-suite/attestations/`. Each record carries the sha256 of the one before it.
- A suite that crashes is recorded too, with `exit_code` 1 and `errors` 1. A failure to record is printed and never fails the suite.
- `verify_chain` names the first broken index. An empty ledger returns `no_records`, never `valid`. It shows tampering; it does not prevent it.
