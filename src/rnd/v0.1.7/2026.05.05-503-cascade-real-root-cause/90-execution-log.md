# 503 Cascade — Execution Log

**Plan**: `01-design.md`
**Session**: `45e6bf84` (Bug Fix Mode)
**Started**: 2026-05-05T21:30:00-04:00

---

## Phase status

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| 0 — Design + execution log | ✅ DONE | 2026-05-05T21:30:00 | 2026-05-05T21:35:00 | `01-design.md` + this file |
| 1 — `_start_proxy` WS-auth poll | ✅ DONE | 2026-05-05T21:36:00 | 2026-05-05T21:42:00 | `embedded_proxy.py` — added 4 class consts + WS-auth poll method + kill helper; py_compile + import OK |
| 2 — `pre_run_hook` abort across 7 callers | ✅ DONE | 2026-05-05T21:42:00 | 2026-05-05T21:50:00 | All 7 wrap `_start_proxy` in try/except RuntimeError → return False; py_compile all green |
| 3 — Label re-classification | ✅ DONE | 2026-05-05T21:50:00 | 2026-05-05T21:54:00 | All 3 cascade-affected files re-classify `http_error_*` as `infra_error`; pre-flight probe deferred (Phase 1+2 already prevents cascade at source) |
| 4a — `:7999` AI-discretionary verification | ✅ DONE | 2026-05-05T21:54:00 | 2026-05-05T21:57:00 | Happy + sad path both pass on `:7999` (see Phase 4a results below) |
| 4b — `:8000` scheduled cascade-elimination | ✅ DONE | 2026-05-07T15:23:40 | 2026-05-07T16:11:10 | `ts-e6bb533b` ran narrowed smoke (4 files via 55 `--ignore=` tokens) for 47:27. Zero `http_error_503` / zero `User cancelled`. Proxy stats: 90 notifications received, 19 responses sent, 0 errors. AC11 GREEN. See Phase 4b evidence below. |
| 5 — pytest fixture wiring (Session 6825e6af) | ✅ DONE | 2026-05-07T17:50:00 | 2026-05-07T18:05:00 | Module-scoped autouse fixture in `conftest.py` with class introspection. AC9 + AC10 green on `:7999`; AC11 green on `:8000` (closed by Phase 4b above). |

---

## Pre-flight evidence (recorded for the doc record)

### Empirical proof — 2026-05-05T21:25 EDT

`curl /api/debug/websocket-state` BEFORE running proxy:
```
users: ["931e9dae-..." (CC), "0cf47e2d-..." (browser)]
# interactive.job.tester (50c73ba7-...) absent
```

After `PYTHONPATH=src python -m cosa.agents.notification_proxy --profile test_suite --strategy llm_script` (no `--email`/`--password` — env-var fallback):
```
"50c73ba7-36dd-4eaf-a7e2-63256252c84f": ["auto proxy"]
```

UUID matches exactly the May-1 diagnosis log line: "User interactive.job.tester@lupin.deepily.ai (50c73ba7-...) is not connected".

**Conclusion**: when proxy runs, test user IS online; server's `is_user_connected(50c73ba7-...)` returns True; 503 path does NOT fire.

### Sweep result (Phase 2 scope)

`grep -rn "_start_proxy" src/tests --include="*.py"`:

| File | Line |
|------|------|
| `src/tests/smoke/utilities/embedded_proxy.py` | 94 (def) |
| `src/tests/smoke/utilities/interactive_smoke_test.py` | 72 |
| `src/tests/smoke/test_proxy_integration.py` | 580 |
| `src/tests/smoke/test_expeditor_mock_job_smoke.py` | 576 |
| `src/tests/smoke/test_swe_team_proxy.py` | 334 |
| `src/tests/smoke/test_presentation_live_smoke.py` | 338 |
| `src/tests/smoke/test_research_to_presentation_live_smoke.py` | 255 |
| `src/tests/smoke/test_presentation_render_only_smoke.py` | 331 |

7 caller sites + 1 definition site. All 7 callers must wrap in try/except.

---

## Phase 1 — `_start_proxy` WS-auth poll

**File**: `src/tests/smoke/utilities/embedded_proxy.py`

**Changes**:
- Added `import requests` to imports
- Added 4 class constants: `PROXY_STARTUP_WAIT = 1` (was 5; now just brief settle), `PROXY_WS_AUTH_TIMEOUT = 30`, `PROXY_WS_AUTH_POLL_INTERVAL = 0.5`, `PROXY_EXPECTED_SESSION_ID = "auto proxy"`
- Rewrote `_start_proxy` body: Popen errors now raise `RuntimeError`; premature subprocess exit raises with stdout in message; WS-auth poll added after settle
- Added `_wait_for_proxy_ws_auth(expected_email)`: polls `GET /api/debug/websocket-state` for `"auto proxy"` in `active_connections` with non-empty `session_to_user`; raises `RuntimeError` on timeout or subprocess death; rich diagnostics in error message
- Added `_kill_proxy_subprocess()`: best-effort SIGINT → SIGKILL helper used on poll-timeout cleanup
- Reader thread spawn timing unchanged (still gated by `debug` flag)
- Polling URL parameterized via `LUPIN_API_URL` env var (default `http://localhost:7999`) per `feedback_tests_parameterize_base_url`

**Verification**: `py_compile` + `import EmbeddedProxyMixin` + class-attr inspection all green.

---

## Phase 2 — `pre_run_hook` abort across 7 callers

**Pattern adopted** (uniform across all 7 sites): wrap `_start_proxy` in `try/except RuntimeError` → `print` clear ABORT message + the exception's diagnostic string → `return False`. Removed the now-dead `if not self.proxy_running: WARNING` branch (since the new `_start_proxy` raises on all failure paths).

| File | Action |
|------|--------|
| `src/tests/smoke/utilities/interactive_smoke_test.py` | Pattern A → ABORT (was: WARNING-only) |
| `src/tests/smoke/test_proxy_integration.py` | Pattern A → ABORT (was: WARNING-only) |
| `src/tests/smoke/test_expeditor_mock_job_smoke.py` | Pattern A → ABORT (was: WARNING-only) |
| `src/tests/smoke/test_swe_team_proxy.py` | Pattern A → ABORT (was: WARNING-only) |
| `src/tests/smoke/test_presentation_live_smoke.py` | Pattern B → ABORT (was already aborting on `proxy_running`; now via try/except + preserves `_remove_pid_file()`) |
| `src/tests/smoke/test_research_to_presentation_live_smoke.py` | Pattern B → ABORT |
| `src/tests/smoke/test_presentation_render_only_smoke.py` | Pattern B → ABORT |

**Verification**: `py_compile` all 7 → green.

**Insight**: Pattern A vs B split was useful — only the 4 Pattern A sites were the actual cascade triggers. The 3 Pattern B sites already aborted, but adapted to the new exception contract preserves their existing intent.

---

## Phase 3 — Label re-classification

**Files**: `test_proxy_integration.py`, `test_expeditor_mock_job_smoke.py`, `test_swe_team_proxy.py`

**Pattern adopted**: in each file's `_verify_*` method, when `data.status == "cancelled"`, FIRST check `config.notification_status`. If it starts with `"http_error_"`, return a NEW status `"infra_error"` with details `"Infra failure: notification dispatch returned <status> (proxy unreachable or /api/notify down)"`. Only after that infra check fall through to the existing pass/cancel branches.

**Label catalog before/after**:

| Cause | Old label | New label |
|-------|-----------|-----------|
| 503 from `/api/notify` (proxy unreachable / dispatch down) | `cancel: User cancelled unexpectedly` | `infra_error: Infra failure: notification dispatch returned http_error_503 (proxy unreachable or /api/notify down)` |
| 502/504/etc from `/api/notify` | `cancel: User cancelled unexpectedly` | `infra_error: Infra failure: notification dispatch returned http_error_NNN ...` |
| User actually pressed cancel in UI | `cancel: User cancelled unexpectedly` | unchanged |

**Pre-flight probe**: deferred. Phase 1+2 already prevents the cascade at source (proxy fails to start → suite aborts cleanly, never reaches the test scenarios). Pre-flight probe would only add value if proxy starts successfully but `/api/notify` is independently down — niche scenario; can be filed as follow-up if observed.

**Verification**: `py_compile` all 3 → green.

---

## Phase 4a — `:7999` AI-discretionary verification

Two probes run via inline Python script (PYTHONPATH=src) on live `:7999`:

### Probe 1 — HAPPY PATH (valid env-var creds)

```
Using env-var email: interactive.job.tester@lupin.deepily.ai
✅ HAPPY PATH PASS — proxy registered as user UUID 50c73ba7-36dd-4eaf-a7e2-63256252c84f in 1.63s
✅ WS-auth confirmation: 'auto proxy' in active_connections
[clean stop, no zombies]
```

**Result**: ✅ `_start_proxy` returns normally in 1.63s (vs old 5-second blind sleep). WS-auth poll succeeded on first attempt.

### Probe 2 — SAD PATH (valid email + wrong password, `PROXY_WS_AUTH_TIMEOUT=8s`)

```
✅ SAD PATH PASS — RuntimeError raised in 14.30s
Error head: Proxy WS-auth did not complete within 8s.
  Expected session ID:  'auto proxy'
  Expected user email:  interactive.job.tester@lupin.deepily.ai
  Last observed active_connections: [..., no 'auto proxy']
  Last observed user_sessions keys: [...]
✅ Error message contains expected diagnostic text
```

**Result**: ✅ `RuntimeError` raised with informative diagnostics. The proxy subprocess kept retrying login (listener has built-in reconnect with backoff) — so the failure surfaced as poll-timeout rather than premature-exit, but the cleanup + raise path worked correctly.

**Behavioral note**: poll-timeout (rather than subprocess-exit) is the dominant failure mode for bad credentials, because the listener has its own reconnect loop. The 30s default `PROXY_WS_AUTH_TIMEOUT` should give legitimate proxies more than enough time while still being a reasonable cap on bad-creds runs (~30s wasted vs old behavior of running 21 scenarios with no proxy).

### Final WS state — zombie check

```
✅ No 'auto proxy' zombie. Active: ['cc-listener-45e6bf84', 'cc-listener-532b16e1', ...]
```

**Result**: `_kill_proxy_subprocess` left no orphaned WS connections.

---

## Phase 4b — `:8000` scheduled cascade-elimination

### Submission

User authorized immediate slot on 2026-05-07. First attempt (`ts-f04eed7f`) failed at startup (exit=4) because `pytest_args = "-k 'expr1 or expr2 or expr3'"` got `.split()` on whitespace — pytest received `'expr1`, `or`, `expr2'`, etc. as positional args and crashed with `ERROR: file or directory not found: or`. Resubmitted (`ts-e6bb533b`) using 55 `--ignore=src/tests/smoke/<file>.py` tokens (each single-token, no internal whitespace) to narrow to 4 keepers: `test_proxy_integration`, `test_expeditor_mock_job_smoke`, `test_swe_team_proxy`, `test_auto_proxy_fixture`.

**Submission body**:
```json
{
  "test_types": "smoke",
  "pytest_args": "-v --ignore=src/tests/smoke/test_agentic_disambiguation_smoke.py ... (55 ignores)",
  "scheduled_at": null
}
```

`--auto-proxy --cost-cap-usd 5.00` auto-injected via INI key `test suite smoke extra pytest args` (Cluster B fix from 2026-04-30 post-mortem). Confirmed in the running pytest argv (subprocess inspection inside `lupin-rest-test`).

### Results

- **Job**: `ts-e6bb533b::50c73ba7-...`
- **Started**: 2026-05-07T15:23:40 EDT
- **Completed**: 2026-05-07T16:11:10 EDT
- **Duration**: 47:27 (2847.86s)
- **Outcome**: 3 passed, 1 failed (smoke-results-2026-05-07-at-16:11-EDT)

| Test | Result | Duration | Notes |
|------|--------|----------|-------|
| `test_auto_proxy_fixture::test_fixture_started_proxy` | ✅ PASS | <1s | Fixture regression test — proxy registered as `auto proxy` UUID `50c73ba7-...` |
| `test_expeditor_mock_job_smoke::test_expeditor_mock_job_smoke` | ✅ PASS | 1620.93s (27 min) | All scenarios green |
| `test_swe_team_proxy::test_swe_team_proxy` | ✅ PASS | 383.92s (6.4 min) | All scenarios green |
| `test_proxy_integration::test_proxy_integration` | ❌ FAIL | ~13 min | 14/15 scenarios pass; **scenario 15 EXP_RTPRES_MISSING failed for an UNRELATED REASON** (voice-routing classifier mis-routes "research something and present it" → `deep_research` instead of `research_to_presentation`) |

### AC11 verification — zero `http_error_503`

| Source | Count |
|--------|-------|
| `/tmp/smoke-20260507-201109.log` (pytest stdout/stderr) | grep `http_error_503` / `HTTP 503` / `User cancelled` / `503 Service` → **0 hits** |
| `lupin-rest-test` container logs (last 50 min) | grep `503` → 5 false positives, ALL source-port substrings (`127.0.0.1:45030`, `:45032`, etc.); **zero actual HTTP 503 responses** |
| Proxy subprocess stats (final) | `Notifications Received: 90, Responses Sent: 19, Script Matcher Used: 17, LLM Used: 2, Skipped: 71, Errors: 0` — proxy was alive throughout |

**AC11 GREEN**. Cascade is eliminated. Both bug-queue entries close.

### Per-module fixture evidence

The pytest subprocess tree captured mid-run (PID 8385 + child 8425) showed:
```
python3 -m pytest src/tests/smoke/ -v --ignore=... --auto-proxy --cost-cap-usd 5.00 ...
└── python3 -m cosa.agents.notification_proxy --profile expeditor_smoke ... (PID 8425)
```

The `--profile expeditor_smoke` matches the `ExpeditorSmokeTest.PROXY_PROFILE` for the `test_expeditor_mock_job_smoke` module — **proof that `_auto_proxy_for_module` is correctly introspecting the test class and starting a proxy per module with the right profile**.

Each test module's setup output also confirmed proxy startup, e.g. for `test_proxy_integration`:
```
Starting notification proxy (profile=proxy_integration_test, strategy=llm_script)...
Proxy subprocess alive (pid=9174). Polling for WS-auth...
WS-auth confirmed: session 'auto proxy' → user UUID 50c73ba7-36dd-4eaf-a7e2-63256252c84f
Proxy WS-auth verified — proxy is registered with the server.
```

### Unrelated failure — filed as new Queued bug

Scenario 15 (`EXP_RTPRES_MISSING`): voice command "research something and present it" routed to `agent router go to deep research` instead of `agent router go to research to presentation`. Filed as a new Queued bug in `bug-fix-queue.md`. Pre-existing classifier issue, NOT a regression of the 503-cascade fix.

---

## Phase 5 — pytest fixture wiring (Session 6825e6af, 2026-05-07)

### Code changes

- `src/tests/smoke/conftest.py` — module-scoped autouse fixture `_auto_proxy_for_module` + `--proxy-debug` CLI option registered. Introspects test module for `EmbeddedProxyMixin` subclasses defined IN the module (filter via `obj.__module__ == module.__name__` to skip imported parents like `InteractiveSmokeTest`).
- `src/tests/smoke/test_auto_proxy_fixture.py` (NEW) — regression test that asserts the fixture starts a proxy and registers it as `"auto proxy"` in `/api/debug/websocket-state`. Marker class `AutoProxyFixtureProbe(EmbeddedProxyMixin)` drives the fixture (profile=`deep_research`).

### py_compile + import verification

Both files green: `py_compile.compile(...)` returned cleanly. Class-introspection sanity check across all 6 affected test modules picked the right concrete subclass for each:

| Module | Picked class | PROXY_PROFILE |
|--------|--------------|---------------|
| `test_proxy_integration` | `ProxyIntegrationTest` | `proxy_integration_test` |
| `test_expeditor_mock_job_smoke` | `ExpeditorSmokeTest` | `expeditor_smoke` |
| `test_swe_team_proxy` | `SweTeamProxySmokeTest` | `swe_team` |
| `test_presentation_live_smoke` | `PresentationLiveSmokeTest` | `presentation_gates` |
| `test_research_to_presentation_live_smoke` | `ResearchToPresentationLiveSmokeTest` | `research_to_presentation_gates` |
| `test_presentation_render_only_smoke` | `PresentationRenderOnlySmokeTest` | `presentation_gates` |

(Initial draft picked `InteractiveSmokeTest` for `test_proxy_integration` because `dir(module)` lists imported names alphabetically before the local class. Filter `obj.__module__ == module.__name__` corrected this.)

### AC9 — Happy path on `:7999`

Command: `PYTHONPATH=src:$PYTHONPATH pytest src/tests/smoke/test_auto_proxy_fixture.py --auto-proxy -v -s`

Result: **1 passed in 2.19s**

Trace:
```
src/tests/smoke/test_auto_proxy_fixture.py::test_fixture_started_proxy
  Starting notification proxy (profile=deep_research, strategy=llm_script)...
  Waiting 1s for subprocess to settle...
  Proxy subprocess alive (pid=80180). Polling for WS-auth...
  WS-auth confirmed: session 'auto proxy' → user UUID 50c73ba7-36dd-4eaf-a7e2-63256252c84f
  Proxy WS-auth verified — proxy is registered with the server.
  Fixture verified: 'auto proxy' session registered as user UUID 50c73ba7-36dd-4eaf-a7e2-63256252c84f
PASSED
  Stopping notification proxy (pid=80180)...
  Proxy stopped gracefully.
```

UUID `50c73ba7-36dd-4eaf-a7e2-63256252c84f` matches `interactive.job.tester@lupin.deepily.ai` (the May-5 design doc's expected test-user UUID). Fixture cleanly torn down at module teardown.

### AC10 — Sad path on `:7999` (bad credentials)

Command: `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD=wrong-password pytest src/tests/smoke/test_auto_proxy_fixture.py --auto-proxy -v -s`

Result: **1 error in 32.33s** — `ERROR at setup of test_fixture_started_proxy`. Test body NEVER executed (cascade prevention contract honored).

Diagnostics surfaced:
```
Proxy startup failed for module test_auto_proxy_fixture (class AutoProxyFixtureProbe):
  Proxy WS-auth did not complete within 30s.
    Expected session ID:  'auto proxy'
    Expected user email:  interactive.job.tester@lupin.deepily.ai
    Last observed active_connections: [...]
    Last observed user_sessions keys: [...]
    Possible causes: Login 401 / env vars / server unreachable / proxy crashed
```

Pytest reported as `ERROR` (setup failure), not `FAILED` (assertion failure) — correct distinction. `pytrace=False` suppressed the noisy fixture call stack.

### AC11 — `:8000` cascade-elimination

Pending — this is Phase 4b (now unblocked by Phase 5).

---

## Spec drifts + execute-time deviations

(Empty at start. Append any deviation from `01-design.md` here.)

### 2026-05-07 (session 6825e6af)
- **Drift from Queued entry's "session-scoped" suggestion**: implemented as **module-scoped** instead because each test file's `PROXY_PROFILE` differs. Documented in `01-design.md` §Phase 5 "Why module scope is correct".
