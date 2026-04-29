# OOS-2 — Refactor websocket smoke runner to pytest+junit-xml (PROPOSAL — awaiting ratification)

**Status**: Plan only. No code work until ratified.
**Prewarm-evidence update**: 2026-04-28 read-only forensic pass through `src/tests/websocket_smoke/` + the bash runner. Original effort estimate (M, 1-2 days) was optimistic — the existing architecture is **fundamentally not pytest-shaped** (results-recording pattern vs pytest's raise-on-failure paradigm). Findings folded in below; revised estimate at the bottom.

---

## Prewarm Findings (2026-04-28, evidence-grounded)

### Finding A — Architecture inventory

| Component | LOC | Purpose |
|-----------|-----|---------|
| `src/scripts/run-websocket-smoke-tests.sh` | 452 | Bash runner — pre-flight, kicks off orchestrator |
| `src/tests/websocket_smoke/infrastructure/smoke_test_runner.py` | **1525** | Custom orchestrator — not pytest |
| `src/tests/websocket_smoke/infrastructure/test_utilities.py` | 856 | Auth/connection helpers, JWT lookup, etc. |
| `src/tests/websocket_smoke/core/test_connection_basic.py` | 947 | 12 test methods on a `ConnectionBasicTests` class |
| `src/tests/websocket_smoke/core/test_authentication_flow.py` | ~1080 | 13 test methods on `AuthenticationFlowTests` |
| `src/tests/websocket_smoke/core/test_session_management.py` | ~? | 12 test methods |
| `src/tests/websocket_smoke/core/test_event_system.py` | ~? | 12 test methods |
| `src/tests/websocket_smoke/config/smoke_test_config.ini` | ~50 | INI: server URL, timeouts, event lists, auth mocks |
| `src/tests/websocket_smoke/config/baselines/*.json` | small | Baseline-comparison fixtures (currently empty `results: []`) |

**Total**: ~5500 LOC of bespoke test infrastructure across 8 files. **49 test methods total** (12+13+12+12). Plus health-check + performance + load + concurrent tests added by orchestrator → matches the observed 50/50 reported in smoke runs.

### Finding B — The architecture is fundamentally NOT pytest-shaped

**Critical evidence**: test methods don't use `assert`. They use `self.results.append({"success": True/False, ...})` and **continue**.

```python
# src/tests/websocket_smoke/core/test_connection_basic.py — pattern repeated across 49 methods:
async def _test_valid_queue_connection( self ):
    try:
        # ... do test work ...
        self.results.append( { "success": True, "details": {...} } )
    except Exception as e:
        self.results.append( { "success": False, "error": str(e) } )
        # NOTE: does NOT raise — just records and returns
```

**Pytest assumes raise-on-failure.** The current architecture is "record and continue." Migrating to pytest means rewriting the result-recording layer — every `self.results.append({success: False})` becomes either `pytest.fail(...)` or a hard `assert` (raises `AssertionError`).

This is a paradigm shift, not a mechanical translation:
- **Same**: each test method's actual WebSocket-protocol logic stays (connection setup, auth handshake, event subscribe).
- **Different**: results aggregation moves from explicit `self.results` list (with custom `TestResult` dataclass) to pytest's native pass/fail/skip/error reporting via junit-xml.

### Finding C — Cross-method state via `self.results`

Each test class is a stateful object that accumulates `self.results` across methods. To pytest migration, each method must be a self-contained pytest function. State that today flows through `self.results.append` must instead be:

- **Per-test** assertions (test fails → method raises `AssertionError`).
- **Cross-test** infrastructure via session-scoped fixtures (auth token, server health probe).

`__init__` setup (`self.utils = WebSocketTestUtilities(server_url)`) → becomes a `@pytest.fixture(scope="class")` or `scope="module"`.

### Finding D — Stale `mock_token_*` auth pattern

`smoke_test_config.ini`:
```ini
mock_token_prefix = mock_token_
```

Per `feedback_mock_tokens_are_legacy.md` (pinned in MEMORY.md): **mock tokens are legacy, not canonical**. All envs are `auth mode=jwt`. The websocket smoke suite is using outdated test auth.

This is NOT a blocker for the pytest migration (the JWT login flow already exists in `LivePipelineTestBase`), but it's a co-requisite cleanup — the migration session is the right time to also modernize the auth path. Would add ~2-3 hours to the effort.

### Finding E — INI config is non-trivial

The runner reads `smoke_test_config.ini` for:
- Server URL/timeouts
- Event-name allowlists (`queue_events = auth_success,...`)
- Performance thresholds (max_connection_time, etc.)
- Concurrency limits
- Logging/debug flags

For the pytest migration, every value here needs a target — pytest fixture, parametrize input, or constants module. Not hard, but every value needs a deliberate decision.

### Finding F — Orchestrator features pytest doesn't natively replicate

The 1525-line orchestrator has logic that pytest doesn't natively offer:

- **Phased execution** (Phase 1 basic → Phase 2 comprehensive → Performance → Load) — could be pytest markers (`@pytest.mark.phase1`, etc.).
- **Server health gate** — abort all tests if server unhealthy. pytest equivalent: `@pytest.fixture(autouse=True, scope="session")` that calls `pytest.exit()` on health failure.
- **Performance metric collection** — orchestrator records timing samples; would need `pytest-benchmark` or custom hooks.
- **Baseline save/compare** — current orchestrator can save and diff against `baselines/latest_baseline.json`. pytest doesn't natively do this; would need a fixture or plugin.
- **Custom report generator** (`_generate_report`) — produces console-friendly summary by category (Core 25/25, Integration 22/22, etc.). For pytest migration, this is replaced by junit-xml + a separate "categorized summary" reporter we can keep as a thin script.

---

## Revised effort estimate

Original plan: **M (1-2 days)** — too optimistic given the paradigm shift.

Revised:

| Phase | Work | Effort |
|-------|------|--------|
| **Phase 1** | Migrate health check + basic-connection (12 methods) — establish the pattern | M (~1 day) |
| **Phase 2** | Migrate auth (13) + session (12) + events (12) — bulk mechanical rewrite | L (~1-2 days) |
| **Phase 3** | Replace orchestrator features (phased markers, server health gate, baseline save/compare) | M (~1 day) |
| **Phase 4** | Modernize auth (JWT, drop `mock_token_*`) + INI → fixtures | M (~half-day to full day) |
| **Phase 5** | Update `SUITES_SUPPORTING_JUNIT_XML` allowlist + retire/thin the bash script | XS (~1 hour) |
| **Phase 6** | End-to-end verification: `pytest --junit-xml=...`, check 50/50 pass, replay through `test_suite/job.py` parser | M (~half-day) |

**Total: 4-6 days** (revised from 1-2). This is a meaningful refactor, not a quick migration.

---

## Recommended approach (revised)

Two paths to consider given the larger effort:

### Path α — Full migration (the original plan)

Do the 4-6 day effort. End state: pytest-native suite, junit-xml emitted natively, WG-7's stdout-pattern fallback becomes inert (kept for future custom runners), 50 tests visible in pytest's native test browser.

### Path β — Adapter layer (smaller, less elegant)

Add ONE pytest test file that wraps the existing orchestrator:

```python
# src/tests/websocket_smoke/test_runner_adapter.py
import pytest
from src.tests.websocket_smoke.infrastructure.smoke_test_runner import SmokeTestRunner

@pytest.mark.asyncio
@pytest.mark.parametrize("test_name", [
    "valid_queue_connection",
    "valid_audio_connection",
    # ... 50 entries derived programmatically from runner config ...
])
async def test_websocket_smoke(test_name):
    runner = SmokeTestRunner(...)
    result = await runner.run_one(test_name)  # would need to add this method
    assert result.success, f"{test_name}: {result.error}"
```

Junit-xml is emitted natively. Each "test" is a thin wrapper. The orchestrator stays. Total work: ~half-day. Trade-off: the underlying architecture stays mismatched; future maintenance still has the result-recording pattern.

### Recommendation

**Path β as a stop-gap** unlocks the WG-7 maintenance trap immediately for ~half a day of work. **Path α as a follow-up** when the team has 4-6 days of dedicated investment to harvest. Don't skip α — the result-recording pattern is technical debt that will keep producing surprises (e.g., "test passed but recorded as failed" or vice versa).

---

## Files affected

| Path | Path α | Path β |
|------|--------|--------|
| `src/scripts/run-websocket-smoke-tests.sh` | retire / thin | keep (or thin) |
| `src/tests/websocket_smoke/core/*.py` | rewrite (4 files, 49 methods) | unchanged |
| `src/tests/websocket_smoke/infrastructure/smoke_test_runner.py` | retire | add a `run_one(test_name)` method (~50 lines) |
| `src/tests/websocket_smoke/infrastructure/test_utilities.py` | refactor for fixture use | unchanged |
| `src/tests/websocket_smoke/conftest.py` | NEW (fixtures: server URL, JWT token, session-id factory, etc.) | NEW (small — pytest-asyncio config + smoke_test_config.ini load fixture) |
| `src/tests/websocket_smoke/test_*.py` (top-level) | NEW pytest files | NEW: test_runner_adapter.py |
| `src/tests/websocket_smoke/config/smoke_test_config.ini` | retire (constants → fixtures) or keep as fixture-loaded config | unchanged |
| `src/cosa/agents/test_suite/job.py:SUITES_SUPPORTING_JUNIT_XML` | add `"websocket"` | add `"websocket"` (same change) |

---

## When to actually do this

OOS-2 is the **lowest urgency** of the four OOS items. The WG-7 fallback already works. Path α is a 4-6 day investment for elegance + future-proofing; Path β is a half-day investment for the immediate observability win. Either way, it doesn't move the needle on the 22:35 incident.

Suggest deferring until OOS-1 + OOS-4 land (those have higher leverage). When OOS-2 picks up, default to **Path β** unless the team has already-allocated time for Path α.

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
