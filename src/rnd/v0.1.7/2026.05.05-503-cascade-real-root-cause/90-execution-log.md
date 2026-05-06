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
| 4b — `:8000` scheduled cascade-elimination | ⏳ PENDING | | | Requires user slot confirmation |

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

(Fill on completion: scheduled_at slot, suites submitted, results table per suite, regression confirmation.)

---

## Spec drifts + execute-time deviations

(Empty at start. Append any deviation from `01-design.md` here.)
