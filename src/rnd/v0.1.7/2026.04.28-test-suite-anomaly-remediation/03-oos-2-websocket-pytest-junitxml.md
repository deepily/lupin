# OOS-2 — Refactor websocket smoke runner to pytest+junit-xml (PROPOSAL — awaiting ratification)

**Status**: Plan only. No code work until ratified.

## Evidence

The websocket smoke suite uses a bash-driven custom orchestrator (`src/scripts/run-websocket-smoke-tests.sh`) that emits its own `[INFO]` log format. Because the format is non-pytest and there's no junit-xml output, the test_suite parser couldn't extract per-suite metrics — leading to the 0/0/0/0 false-FAIL classification fixed in WG-7 with a stdout-pattern fallback.

WG-7's fallback is a workable patch but it's also a **maintenance trap**: every future change to the websocket runner's stdout format risks re-breaking classification. Routing the runner under pytest with `--junit-xml=...` would eliminate the fallback entirely.

## Constraints

- The runner orchestrates 50 WebSocket connection / auth / subscription / event tests across 4 categories (Core, Integration, Performance, Load).
- Tests are inherently asynchronous (coroutines vs websockets) — pure-pytest collection works but assertions must use pytest-style fixtures.
- `:7999` server must be running and authenticated; runner already handles auth-token caching.
- The bash script provides bonus value beyond pytest: pre-flight (server health probe, credential check), post-run summary table. These should stay (just outside the pytest boundary).

## Proposed approach

### Phase 1 — pytest harness shell

1. Move all per-test logic into pytest-style functions under `src/tests/websocket_smoke/` (the directory may already exist — confirm).
2. Use `pytest-asyncio` (already a dep) for async test functions.
3. Use a session-scoped fixture for auth-token + server-health-check (replaces the bash pre-flight).
4. Group tests by category via `@pytest.mark.<category>` (parametrize categories so the existing 25/22/2/1 per-category breakdown is preserved).

### Phase 2 — script-as-thin-wrapper

The shell script stays for one reason: pytest doesn't have a native "log-and-summarize-by-category" output mode. Two options:

| Option | Pros | Cons |
|--------|------|------|
| A. Replace shell script with `pytest src/tests/websocket_smoke/ --junit-xml=/tmp/websocket-junit.xml -v` directly invoked by test_suite | Cleanest. test_suite_job already has junit-xml plumbing for unit/smoke/integration suites. | Loses the categorized summary table operators see in CLI runs |
| B. Keep the shell script as a wrapper that runs pytest then post-processes junit-xml into the categorized summary | Preserves CLI ergonomics. test_suite still gets the junit-xml directly. | Two layers of indirection |

Recommendation: **option A**. The test_suite_job consumer is the load-bearing one; the human-facing categorized summary can live in a dedicated reporter script (`src/scripts/websocket-test-report.sh`) callable separately.

### Phase 3 — flip the `SUITES_SUPPORTING_JUNIT_XML` allowlist

Add `"websocket"` to `SUITES_SUPPORTING_JUNIT_XML` in `src/cosa/agents/test_suite/job.py`. This causes `--junit-xml=/tmp/websocket-junit-...xml` to get appended automatically and the existing `_parse_junit_xml` does the rest. WG-7's `_parse_non_pytest_stdout` becomes inert for websocket (still useful for any other future custom runners — keep it).

## Files likely to change

- `src/scripts/run-websocket-smoke-tests.sh` — gut to wrap pytest invocation, or delete
- `src/tests/websocket_smoke/conftest.py` — NEW or updated: session-scoped auth/health fixtures
- `src/tests/websocket_smoke/test_*.py` — NEW or refactored from existing async test code
- `src/cosa/agents/test_suite/job.py:SUITES_SUPPORTING_JUNIT_XML` — add `"websocket"`
- (new) `src/scripts/websocket-test-report.sh` — categorized summary for CLI-only use

## Acceptance criteria

- `pytest src/tests/websocket_smoke/ --junit-xml=/tmp/x.xml -v` produces 50 testcase entries in the junit-xml.
- All 4 categories (Core, Integration, Performance, Load) preserved as pytest markers.
- Replaying through `test_suite_job` produces `passed=50 failed=0 skipped=0 errors=0` with the standard parser path (no fallback hit).
- `:7999` smoke run-time stays ≤60s (currently 45s).
- WG-7's fallback path remains functional but unused for websocket.

## Estimated effort

M: 1-2 days. The migration is mostly mechanical; pytest-asyncio handles the async structure cleanly. Risk: subtle order-dependence between tests (the existing runner may rely on connection ordering). Verify with a few test runs.

## Out of scope (for OOS-2)

- Reorganizing the websocket smoke test categories (separate ticket).
- Adding new websocket smoke tests (separate ticket).
- Changing what the tests assert (the goal here is format-only).
