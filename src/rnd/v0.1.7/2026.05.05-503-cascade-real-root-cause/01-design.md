# 503 Cascade — Real Root Cause + Fix Design

**Filed**: 2026-05-05 PM | **Session**: `45e6bf84` (Bug Fix Mode)
**Bug entry**: `bug-fix-queue.md` In Progress — "Notification 503 cascade for offline users in expediter flow"
**Supersedes diagnosis**: `src/rnd/v0.1.7/2026.05.01-postmortem-fixes-90-execution-log.md` §Phase 5

---

## TL;DR

The May-1 §Phase 5 diagnosis was **substantively wrong**. Its claim — "the auto-proxy server does NOT maintain a WS connection for the test user" — was disproved empirically today on live `:7999`. The proxy fully supports WS-as-test-user; the env-var fallback (`get_credentials` in `base_config.py:37`) already recycles `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL`/`_PASSWORD`; tests already pass those creds to `_start_proxy`. When the proxy is alive, the test user's UUID `50c73ba7-36dd-4eaf-a7e2-63256252c84f` appears in `WebSocketManager.user_sessions` and `is_user_connected()` returns True.

The 503 cascade observed on May 1 had a different root cause: **silent proxy startup failure**. `EmbeddedProxyMixin._start_proxy()` only verifies `subprocess.Popen` is alive after a 5-second blind sleep — it does NOT verify WS-auth completion. When startup fails (env vars missing, account not present in target DB, login 401, WS handshake race past 5s), the test harness prints a WARNING and **continues anyway**, running 21+ scenarios with no proxy → cascade of 503s mislabelled as "User cancelled unexpectedly."

**Fix is in the test harness, not the expediter or the server.** The expediter is behaving correctly; the server's offline-without-default 503 is the right contract. The bug is the test harness's silent tolerance of a missing proxy.

---

## Empirical proof (today, live `:7999`)

Before proxy:
```
"users": ["931e9dae-...", "0cf47e2d-..."]   # CC sender + browser user
```

`interactive.job.tester` is absent.

After `python -m cosa.agents.notification_proxy --profile test_suite --strategy llm_script` (no `--email`/`--password` — picked up env vars via `get_credentials`):
```
"50c73ba7-36dd-4eaf-a7e2-63256252c84f": ["auto proxy"]
```

UUID `50c73ba7-...` matches **exactly** the UUID quoted in the May-1 diagnosis log:
> "[NOTIFY] User interactive.job.tester@lupin.deepily.ai (50c73ba7-...) is not connected"

So when the proxy runs with proper creds, the test user IS online and the 503 path will NOT fire. The architecture is working as designed.

---

## Real root cause

`src/tests/smoke/utilities/embedded_proxy.py:152-163`:

```python
# Give the proxy time to authenticate and subscribe
print( f"  Waiting {self.PROXY_STARTUP_WAIT}s for proxy to connect..." )
time.sleep( self.PROXY_STARTUP_WAIT )

if self._proxy_process.poll() is not None:
    # Proxy exited prematurely
    ...
```

Two gaps:

1. **Blind sleep, no WS-auth check.** The 5-second `PROXY_STARTUP_WAIT` is a guess. Under load, login + WS handshake + subscribe can take longer; the test fires `/api/notify` before the proxy is registered → 503.
2. **`subprocess.Popen.poll() is None` is a weak liveness signal.** The subprocess can be alive but not WS-connected (e.g., login retry loop, subscribe pending). Or if it crashes after the 5-second wait, the test continues until the next pre-run check.

`pre_run_hook` in callers (e.g. `test_proxy_integration.py:582-584`):

```python
if not self.proxy_running:
    print( "  WARNING: Proxy failed to start. Interactive scenarios may timeout." )
```

**WARNING-only.** The hook does NOT return False. The test continues with no proxy → 21 scenarios all 503.

---

## Fix design (4 phases)

### Phase 1 — `EmbeddedProxyMixin._start_proxy` adds WS-auth verification

After `subprocess.Popen` + initial wait, poll `GET /api/debug/websocket-state` (no auth required — it's a debug endpoint) on a bounded timer until either:

- Session ID `"auto proxy"` (`DEFAULT_SESSION_ID` from `notification_proxy/config.py`) appears in `active_connections` AND its `session_to_user` mapping is non-empty → success
- Timeout (default 30s, configurable via `PROXY_WS_AUTH_TIMEOUT` class attr) → SIGINT the proxy, clear `self._proxy_process`, raise `RuntimeError` with a clear message including: env-var status, login URL, expected user, observed `user_sessions` keys, and the proxy's last 30 lines of stdout.

Optional refinement (later phase if useful): also verify the registered user UUID matches the expected test user's UUID. The harness has the test user's email and password; it can do its own `POST /auth/login` and extract `sub` from the JWT. If the proxy registered under a DIFFERENT user UUID, the upcoming notifications would still 503. For Phase 1 ship, **session-presence + non-empty user-mapping is sufficient** — UUID matching is a Phase 1.5 nice-to-have.

**Behavior change**: `_start_proxy` becomes raising-on-failure. Callers must wrap in try/except.

### Phase 2 — `pre_run_hook` aborts on proxy startup failure

All 6 test files + the shared `InteractiveSmokeTest.pre_run_hook` follow this pattern:

```python
if getattr( args, "auto_proxy", False ):
    debug    = getattr( args, "proxy_debug", False )
    email    = os.environ.get( f"{self.CREDENTIAL_ENV_PREFIX}_EMAIL" )
    password = os.environ.get( f"{self.CREDENTIAL_ENV_PREFIX}_PASSWORD" )
    try:
        self._start_proxy( debug=debug, email=email, password=password )
    except RuntimeError as e:
        print( f"\n  ERROR: Proxy startup failed — aborting suite to prevent 503 cascade." )
        print( f"  {e}" )
        return False  # ABORT — do NOT run scenarios with no proxy
```

Callers to fix (sweep result):

| File | Line | Status |
|------|------|--------|
| `src/tests/smoke/utilities/interactive_smoke_test.py` | ~70 | Shared mixin pre-run hook |
| `src/tests/smoke/test_proxy_integration.py` | 580 | Override |
| `src/tests/smoke/test_expeditor_mock_job_smoke.py` | 576 | Override |
| `src/tests/smoke/test_swe_team_proxy.py` | 334 | Override |
| `src/tests/smoke/test_presentation_live_smoke.py` | 338 | Override |
| `src/tests/smoke/test_research_to_presentation_live_smoke.py` | 255 | Override |
| `src/tests/smoke/test_presentation_render_only_smoke.py` | 331 | Override |

Total: 7 sites. All must adopt try/except + abort.

### Phase 3 — Label re-classification + pre-flight probe in `live_pipeline_base.py`

This is the standalone "Smoke harness label improvement" entry already filed in `bug-fix-queue.md`. Bundling here closes two bugs in one commit.

Changes:

1. **Re-classify** `notification_status` starting with `http_error_` as a distinct failure class:
   - Current: "User cancelled unexpectedly" (misleading; 503 is not user cancellation)
   - New: "Infra failure: HTTP <code> from /api/notify" (clear, actionable)
2. **Pre-flight probe** in `pre_run_hook`: send a no-op `/api/notify` health check with a known-online sender (Claude Code listener as test target). If 503 → abort suite with "notification dispatch unavailable" instead of running 21 scenarios that will all fail.

### Phase 4 — Verification

#### Phase 4a — AI-discretionary `:7999` (no monopoly, no state mutation)

Two probes:

1. **Happy path**: with valid env vars, run `_start_proxy` → assert WS-auth poll succeeds → assert `"auto proxy"` in `active_connections` → cleanup
2. **Sad path**: temporarily unset env vars → run `_start_proxy` → assert `RuntimeError` is raised with the expected message → assert `pre_run_hook` returns False

These probes are pure observation against `:7999` — no scenarios run, no jobs submitted, no destructive state.

#### Phase 4b — User-gated `:8000` scheduled submission

Per `:8000` monopolize-mode rules: submit the 3 affected suites via `POST /api/test-suite/submit` with a user-confirmed `scheduled_at`. Use `/schedule-tests` skill, never hand-roll auth + API.

Suites to verify:
- `test_expeditor_mock_job_smoke`
- `test_proxy_integration --group all --auto-proxy`
- `test_swe_team_proxy`

Acceptance criteria:
- Zero `http_error_503` results across the 3 suites
- All previously-cancelled-as-503 scenarios now show real pass/fail
- A deliberately-broken proxy run (e.g., wrong password) aborts cleanly with a clear error and no scenarios attempt

User-coordinates the `:8000` slot; AI submits + waits + reports.

---

## Sweep check (per `feedback_sweep_for_pattern_offenders`)

Pattern: silent-tolerance of failed proxy startup.

- ✅ All 7 `_start_proxy` callers identified and listed above
- ✅ Shared `InteractiveSmokeTest.pre_run_hook` covers any future test that subclasses `InteractiveSmokeTest`
- ✅ The `_start_proxy` raise-on-failure change is the choke point — even if a future test forgets to try/except, the unhandled exception propagates and pytest fails the test loudly (no silent cascade)

No other test areas use a similar "subprocess + blind sleep + warn-on-fail" pattern — `grep -rn "PROXY_STARTUP_WAIT\|subprocess.Popen" src/tests/` returns only this mixin.

---

## Acceptance criteria

| AC | What |
|----|------|
| AC1 | `_start_proxy` raises `RuntimeError` on WS-auth poll timeout with informative message |
| AC2 | `_start_proxy` succeeds within bounded poll on a healthy proxy startup against `:7999` |
| AC3 | All 7 callers wrap `_start_proxy` in try/except and return False from `pre_run_hook` on failure |
| AC4 | `live_pipeline_base.py` reports `http_error_*` failures as "Infra failure: HTTP NNN" not "User cancelled unexpectedly" |
| AC5 | Pre-flight `/api/notify` probe in `pre_run_hook` aborts suite early on dispatch outage |
| AC6 | Phase 4a probes pass on `:7999` (happy path + sad path) |
| AC7 | Phase 4b scheduled `:8000` run shows zero `http_error_503` across 3 affected suites |
| AC8 | Bug-fix-queue.md "503 cascade" entry → Completed; "Smoke harness label improvement" entry → Completed (closed by Phase 3) |

---

## Risk + open questions

- **`PROXY_WS_AUTH_TIMEOUT = 30s` default**: too generous? too tight? Tunable via class attribute; can revisit after Phase 4a observation.
- **`/api/debug/websocket-state` is unauthenticated**: confirmed today (`curl` succeeded with no auth header). If that endpoint is locked down later, harness needs JWT. For now, free poll is fine.
- **UUID-matching (Phase 1.5)**: deferred. Session-presence is sufficient for this fix; UUID matching guards against a different failure mode (proxy auths as wrong user) that hasn't been observed.
- **CoSA edits**: none planned. All changes are in `src/tests/` (Lupin parent repo). No `src/cosa/` files touched.

---

## Files to be touched

**Lupin parent repo only** (no CoSA edits):

- `src/tests/smoke/utilities/embedded_proxy.py` — Phase 1 (add WS-auth poll)
- `src/tests/smoke/utilities/interactive_smoke_test.py` — Phase 2 (try/except + abort)
- `src/tests/smoke/test_proxy_integration.py` — Phase 2
- `src/tests/smoke/test_expeditor_mock_job_smoke.py` — Phase 2
- `src/tests/smoke/test_swe_team_proxy.py` — Phase 2
- `src/tests/smoke/test_presentation_live_smoke.py` — Phase 2
- `src/tests/smoke/test_research_to_presentation_live_smoke.py` — Phase 2
- `src/tests/smoke/test_presentation_render_only_smoke.py` — Phase 2
- `src/tests/smoke/utilities/live_pipeline_base.py` — Phase 3 (label + probe)
- `src/rnd/v0.1.7/2026.05.05-503-cascade-real-root-cause/01-design.md` — this doc
- `src/rnd/v0.1.7/2026.05.05-503-cascade-real-root-cause/90-execution-log.md` — paired tracker
- `bug-fix-queue.md` — close 503 cascade + label improvement entries
- `history.md` — Fix entry + Session Summary
