# Approach C — Phase 3: Ghost-Job Watchdog + ApiResourceManager Integration + Full Regression

**Status**: DESIGN (implementation not started)
**Branch**: `wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe`
**Paired execution log**: `92-phase-3-execution-log.md`
**Depends on**: Phase 1 (`01-phase-1-rlock-config-and-resource-manager.md`) and Phase 2 (`02-phase-2-dispatcher-pool-and-pool-status.md`) landed and green
**Decisions driving this phase**: Q3 (ApiResourceManager caller migration), Q4 (watchdog sweep = suspenders to Phase 2's defensive callback belt), Q5 (ApiResourceManager state joins pool-status in Phase 3)

---

## Context

Phase 3 closes the loop. Phase 2 shipped the pool with a defensive callback (belt). Phase 3 adds the **watchdog sweep** that catches the one case the callback can't: when the callback thread itself dies before firing. Phase 3 also **migrates the first agents to call `ApiResourceManager.acquire()`** (the singleton stub landed empty in Phase 1), and **enriches the `/api/queue/pool-status` endpoint** with per-provider contention state.

Finally, Phase 3 runs the full automated regression across all four layers (the same layers Phase 1 and 2 ran, re-run together to catch integration drift), a concurrent-happy-path Protocol E2E (AI-executed), and documentation updates.

After Phase 3 lands, the v0.1.7 async-pool milestone is complete. Bumping the prod default from `= 1` to `= 3` becomes a separate deliberate action.

---

## Scope

### In scope

- **Ghost-job watchdog** — new periodic sweep that detects jobs whose pool `Future.done()` is True but whose state transition never happened.
- **`ApiResourceManager` caller migration (first wave)** — migrate `WebSearchRateLimiter` callers in `src/cosa/agents/deep_research/` to call the singleton. Other agents (podcast, presentation) stay on their `_call_with_retry()` patterns; their migration is follow-up work.
- **`/api/queue/pool-status` enrichment** — add `api_resource_manager` section to the response payload.
- **Full regression pass** across all four automated layers (unit, smoke, WebSocket, E2E, integration).
- **Protocol E2E — concurrent-happy-path** (two agentic + one math, simultaneous; AI-executed).
- **Documentation updates** — `notification-api.md`, `websocket-architecture.md`, `rest-api-reference.md`, the v0.1.5 anchor doc (mark phases complete).

### Out of scope (explicit)

- Third (interactive) lane — deferred per Q1.
- Approach D bundling — deferred per Q7.
- Migration of podcast/presentation/BFE/TFE/ClaudeCode agents to `ApiResourceManager` — follow-up work.
- Per-job-type pools — deferred per Q6.
- Admin UI visualization of pool/ARM state — optional nice-to-have; include only if trivial at review time.
- Prod default bump from `= 1` to `= 3` — explicit separate deliberate action after Phase 3 ships.

---

## Architecture additions

```mermaid
flowchart TD
    subgraph Phase3Add["Phase 3 additions"]
        WD["Ghost-Job Watchdog<br/>(periodic sweep)"]
        ARM["ApiResourceManager<br/>(Phase 1 stub) — now called by agents"]
        DR["DeepResearch _call_with_retry"]
        PSE["/api/queue/pool-status<br/>enriched"]
    end

    RQ[running_queue] -. sweeps every N sec .-> WD
    WD -->|Future.done() but still in queue| DL[dead_queue]

    DR -->|Phase 3: await acquire| ARM
    DR -->|Phase 3: record_call| ARM

    ARM -->|Phase 3: get_status| PSE
```

---

## Step 3.1 — Ghost-job watchdog

### Purpose

Phase 2's `_on_agentic_complete()` is defensively wrapped (belt). If the callback body *itself* raises and the inner dead-letter attempt also fails, the job is stuck in `running_queue` with a `Future` that's `done()`. The watchdog (suspenders) detects this and recovers.

Second failure mode it covers: callback never fires at all because the callback thread died (extremely rare, but the cost of not handling it is "job stuck forever, no observability").

### Placement options

Two implementation shapes. Pick one during impl:

**A. New thread inside `RunningFifoQueue`.**
- Pros: self-contained, lives with the thing it watches, easy start/stop in `shutdown_pool()`.
- Cons: one more long-lived thread.

**B. Tick inside an existing watchdog** (e.g. `dead_queue_watchdog` or `test_suite_completion_watchdog`).
- Pros: no new thread, reuses existing scheduling infrastructure.
- Cons: couples async-pool health to a loosely related watchdog's cadence.

**Recommendation**: Option A — `_ghost_job_sweeper_thread` owned by `RunningFifoQueue`. Clearer ownership, easier to test.

### Behavior

```python
def _ghost_job_sweep( self ):
    """
    Scan running_queue for agentic jobs whose Future is done() but are still
    in running_queue (i.e., the transition never happened). Dead-letter them.
    Runs periodically; interval configurable via INI.
    """
    with self._agentic_futures_lock:
        futures_snapshot = dict( self._agentic_futures )

    for id_hash, future in futures_snapshot.items():
        if not future.done():
            continue

        # Future done but still in our tracker → transition never happened
        job = self.get_by_id_hash( id_hash )
        if job is None:
            # Already transitioned by someone; clean up our tracker
            with self._agentic_futures_lock:
                self._agentic_futures.pop( id_hash, None )
            continue

        cause = future.exception() or RuntimeError(
            f"Ghost job {id_hash} detected — Future done but never transitioned"
        )
        try:
            self._transition_to_dead( job, cause )
        except Exception as e:
            du.print_banner(
                f"Ghost-job watchdog failed to dead-letter {id_hash}: {e}",
                error=True
            )

        with self._agentic_futures_lock:
            self._agentic_futures.pop( id_hash, None )
```

### Config key

```ini
# in lupin-app.ini
cj flow ghost job sweep interval seconds = 30
```

Splainer:

```ini
cj flow ghost job sweep interval seconds = How often the ghost-job watchdog scans the running queue for agentic jobs whose pool Future is done but whose state transition never happened (safety net for failures in _on_agentic_complete). 30s balances responsiveness with overhead; lower in dev if testing the watchdog itself.
```

### Thread lifecycle

- Started in `RunningFifoQueue.__init__` after the pool.
- Uses `threading.Event` for sleep + early-wakeup at shutdown.
- Stopped as the **first** step in `shutdown_pool()` so the sweeper isn't racing against the drain.

### Tests

| Test | What it proves |
|---|---|
| `test_ghost_job_detected_and_dead_lettered` | Manually set a Future to done, leave its job in `running_queue`, trigger sweep → job lands in `dead_queue` |
| `test_ghost_job_sweep_idempotent` | Sweep twice in a row; second run is a no-op (futures dict cleaned) |
| `test_ghost_job_sweep_ignores_live_futures` | In-flight (not done) futures untouched |
| `test_ghost_job_sweeper_stops_on_shutdown` | `shutdown_pool()` returns within timeout; sweeper thread exits |

These go into `src/tests/unit/test_agentic_pool.py` (extending the Phase 2 file).

---

## Step 3.2 — `ApiResourceManager` caller migration (first wave)

### Scope

ONLY Deep Research in Phase 3. It's the agent with the richest existing rate-limit logic (already uses `WebSearchRateLimiter`), so migration validates the singleton shape against real callers without inventing patterns.

### Changes

**`src/cosa/agents/deep_research/api_client.py`** — `_call_with_retry()`:

Before (today):
```python
# Existing pseudocode
await self._rate_limiter.wait_if_needed( tokens=estimated_tokens )
response = await self._client.messages.create( ... )
self._rate_limiter.record_call( tokens=response.usage.input_tokens )
```

After (Phase 3):
```python
from cosa.utils.api_resource_manager import ApiResourceManager

arm = ApiResourceManager.get_instance()
await arm.acquire( provider="anthropic_web_search", tokens=estimated_tokens )
response = await self._client.messages.create( ... )
arm.record_call(
    provider    = "anthropic_web_search",
    tokens      = response.usage.input_tokens,
    latency_ms  = <measured>,
)
```

### Compatibility note

The singleton's `acquire("anthropic_web_search", ...)` delegates internally to the same `WebSearchRateLimiter` that existed before. **Runtime behavior is identical** — just the call site moves.

**Agents NOT migrated in Phase 3** (stay on current patterns):
- `src/cosa/agents/podcast_generator/api_client.py::_call_with_retry()`
- `src/cosa/agents/presentation_generator/api_client.py::_call_with_retry()` (if present)
- Any `ClaudeCodeJob` / `BFE` / `TFE` code paths

Their migration is a follow-up — tracked in TODO.md as a separate post-v0.1.7 item.

### Tests

| Test | What it proves |
|---|---|
| `test_deep_research_calls_acquire_through_singleton` | Mock `ApiResourceManager.acquire()`; assert called once per request |
| `test_deep_research_records_call_after_success` | Mock `record_call()`; assert called with right provider + tokens |
| `test_deep_research_records_call_even_on_error` | Even when SDK raises, record_call fires (for provider state accuracy) |

These go into `src/tests/unit/test_api_resource_manager.py` (extending the Phase 1 file).

---

## Step 3.3 — `/api/queue/pool-status` enrichment (Q5 Phase 3 half)

Phase 2 shipped the endpoint with minimal payload. Phase 3 adds:

```json
{
    "active_agentic_jobs" : 2,
    "max_agentic_workers" : 3,
    "pending_in_pool"     : 0,
    "api_resource_manager" : {
        "anthropic_web_search" : {
            "tokens_used_in_window" : 12500,
            "window_seconds"        : 60,
            "current_wait_ms"       : 0
        },
        "anthropic" : { "provider_wait_state" : "passthrough" },
        "openai"    : { "provider_wait_state" : "passthrough" },
        "gemini"    : { "provider_wait_state" : "passthrough" }
    }
}
```

The `api_resource_manager` key is populated by calling `ApiResourceManager.get_instance().get_status()` (the Phase 1 stub already returns this shape).

---

## Step 3.4 — Full regression (all four automated layers)

This is the pre-merge gate per project rule. Run in this order, each passing before proceeding.

> **Executor contract**: every row below is `EXECUTOR: AI`. The AI runs the commands against `:7999`, captures output, and reports pass/fail. No row is `EXECUTOR: HUMAN`. See `00-working-contract.md`.

| # | Layer | Command | Gate |
|---|---|---|---|
| 1 | **py_compile** | Compile all modified `.py` files individually | No errors |
| 2 | **Unit** | `pytest src/tests/unit/ -v` | 915 baseline + Phase 1 + 2 + 3 tests; all green |
| 3 | **Smoke** | `/smoke-test-remediation FULL` | No regressions against baseline |
| 4 | **WebSocket smoke** | `./src/scripts/run-websocket-smoke-tests.sh` | 50/50 pass |
| 5 | **E2E UI** (`--bg` MANDATORY) | `./src/scripts/run-e2e-ui-tests.sh --bg -v` | 285/285 pass |
| 6 | **Integration (final gate)** (`--bg` MANDATORY) | `./src/tests/run-integration-tests.sh --bg -v` | 43/43 pass |

`--bg` is MANDATORY for E2E and integration (both exceed the 10min Bash timeout). Monitor via `tail -20 /tmp/e2e-ui-latest.log` and `tail -20 /tmp/integration-latest.log`. Wait for E2E to finish before launching integration (PID-file overlap protection is in place).

### Protocol E2E — Phase 3 mandatory concurrent-happy-path (AI-executed)

**REQUIRED** for Phase 3 sign-off (this is the behaviour-validation that automated tests can't express). Every step is executed by the AI via the API against `:7999`:

1. EXECUTOR: AI — Set `cj flow max concurrent agentic jobs = 3` (`:7999` auto-reloads).
2. EXECUTOR: AI — POST /api/push × 2 (DeepResearch dry-run) sequentially, seconds apart; capture both `job_id`s.
3. EXECUTOR: AI — While both research jobs are running, POST /api/push (MathAgent, "what is 17 * 23?"); capture `job_id`.
4. EXECUTOR: AI — Poll `/api/get-queue/running` while DRs run; assert both DR `job_id`s present simultaneously.
5. EXECUTOR: AI — Poll `/api/get-queue/done` until MathAgent completes; assert elapsed < 5s.
6. EXECUTOR: AI — GET `/api/queue/pool-status` mid-run; assert payload shape `{active_agentic_jobs: 2, max_agentic_workers: 3, pending_in_pool: 0, api_resource_manager: {...}}`.
7. EXECUTOR: AI — Continue polling until both DRs complete; assert `running_queue` size returns to 0.
8. EXECUTOR: AI — Assert no jobs stuck in `running_queue` after both finish.
9. EXECUTOR: AI — Report all observed values (timings, pool-status payload, final queue sizes) via cosa-voice `notify`.

### Post-regression checks

- Shut down server cleanly — no phantom `running` rows in the next start's queue reload.
- Bring server back up with `= 1`, submit same workload — verify serial behaviour preserved (jobs process one at a time).

---

## Step 3.5 — Documentation updates

| File | Change |
|---|---|
| `src/docs/notification-api.md` | Note that multiple jobs can transition to `running` concurrently; clients should key cards by `job_id` (already do) |
| `src/docs/websocket-architecture.md` | Note that `job_state_transition` events for concurrent jobs interleave non-deterministically |
| `src/docs/rest-api-reference.md` | Add `GET /api/queue/pool-status` row with response shape |
| `src/rnd/v0.1.5/2026.02.19-approach-c-hybrid-queue-architecture.md` | Add completion banner pointing at the v0.1.7 implementation; mark all 11 sub-steps complete |
| `src/rnd/v0.1.7/2026.04.23-cj-flow-async-multi-lane/00-design-review.md` | Add postmortem-pointer: "Implemented per `0{1,2,3}-phase-N-*.md` in the same dir" |

---

## Critical files touched

| File | Touch type | Est. LOC change |
|---|---|---|
| `src/cosa/rest/running_fifo_queue.py` | Modify | +80 (ghost sweeper thread + lifecycle hooks) |
| `src/cosa/rest/routers/queue.py` | Modify | +15 (endpoint enrichment) |
| `src/cosa/agents/deep_research/api_client.py` | Modify | ~+15 / −10 (migrate to singleton) |
| `src/cosa/utils/api_resource_manager.py` | Modify | +60 (flesh out acquire/record for anthropic_web_search) |
| `src/conf/lupin-app.ini` | Modify | +1 (sweep interval key) |
| `src/conf/lupin-app-splainer.ini` | Modify | +1 (matching splainer) |
| `src/tests/unit/test_agentic_pool.py` | Modify | +80 (ghost sweep tests) |
| `src/tests/unit/test_api_resource_manager.py` | Modify | +60 (migration tests) |
| `src/docs/*.md` | Modify | ~+40 total across 3 files |
| `src/rnd/v0.1.5/2026.02.19-approach-c-hybrid-queue-architecture.md` | Modify | +10 (completion banner) |
| `src/rnd/v0.1.7/2026.04.21-cj-flow-async-multi-lane-design-review.md` | Modify | +5 (implementation pointer) |

Total: **~280 LOC, 11 modified files, 0 new files**.

---

## Rollback

Phase 3 is less trivially reversible than 1 or 2 because it touches agent call sites:
- Revert the Phase 3 commit(s). Ghost sweeper, endpoint enrichment, and the Deep Research migration all unwind.
- Deep Research falls back to its pre-migration `_call_with_retry` pattern (identical runtime behaviour).
- `ApiResourceManager` singleton remains installed but dormant.
- No data-layer changes.

If only the sweeper is problematic: set `cj flow ghost job sweep interval seconds = 86400` (effectively off) without reverting.

---

## Open sub-questions for impl

1. **Sweeper cadence**: 30s default. Adjust based on observed Future-transition latency in dev. Should NOT be below 5s (noise) or above 300s (too slow to catch ghosts).
2. **Deep Research `_rate_limiter` field**: after migration, the existing `self._rate_limiter` reference can be removed OR kept as a private alias to `ApiResourceManager`. Lean: remove it — fewer paths to maintain, the public `ApiResourceManager.get_instance()` is the canonical handle.
3. **`record_call` timing semantics**: should it fire on response receipt (what Deep Research does today) or at request start? Phase 3 keeps current semantics (receipt-time) to avoid behaviour drift.
4. **Documentation depth**: update one anchor doc + one rest-api reference row, or write a dedicated `src/docs/cj-flow-async-pool.md` too? Lean: update existing docs only; dedicated doc can follow if v0.1.7 ships widely.

---

## Definition of done (v0.1.7 async-pool milestone)

- All three phases' design docs landed with paired execution logs fully populated.
- All four automated test layers pass (unit 915+, smoke no-regression, WS 50/50, E2E 285/285, integration 43/43).
- Protocol E2E — concurrent-happy-path observed green (AI-executed with reported values).
- `/api/queue/pool-status` returns correct payload during mixed workload.
- v0.1.5 anchor doc bannered as superseded; v0.1.7 design-review doc points at implementation docs.
- TODO.md line 340 parent task checked off (with dated completion note); follow-up items (agent migration for podcast/presentation/BFE/TFE) captured as new TODO entries.
