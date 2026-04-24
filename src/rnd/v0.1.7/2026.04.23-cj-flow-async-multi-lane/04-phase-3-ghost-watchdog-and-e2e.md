# Approach C — Phase 3: Ghost-Job Watchdog + ApiResourceManager Integration + Full Regression

**Status**: DESIGN (implementation not started)
**Branch**: `wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe`
**Paired execution log**: `92-phase-3-execution-log.md`
**Depends on**: Phase 1 (`02-phase-1-rlock-config-and-resource-manager.md`) and Phase 2 (`03-phase-2-dispatcher-pool-and-pool-status.md`) landed and green
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

### Placement (pre-resolved 2026-04-23 fitness review)

**Decision**: New dedicated thread inside `RunningFifoQueue` — `_ghost_job_sweeper_thread`.

**Why (not the alternative)**: the reuse-map survey showed existing watchdogs (`dead_queue_watchdog`, `test_suite_completion_watchdog`) are **event-driven / on-demand** — they have no periodic tick loop to piggyback on. Piggybacking would require inventing a new tick cadence inside them, which is not cheaper than a dedicated thread. Option A is the only feasible shape given the existing codebase; Option B was discarded.

**Benefits**:
- Self-contained; lives with the queue state it watches.
- Start/stop lifecycle is trivial (owned by `RunningFifoQueue.__init__` / `shutdown_pool`).
- Precedent exists: `RunningFifoQueue` already owns ephemeral daemon threads (`_fire_correctness_check_async` spawns one per completion — see `running_fifo_queue.py:864-923`).

### Behavior

> **Load-bearing invariant (defined in `03-phase-2-*.md` Step 2.1, relied on here)**: `_on_agentic_complete` pops from `_agentic_futures` **BEFORE** transitioning. The sweeper uses "still in `_agentic_futures` AND `Future.done()`" as the signal that a transition never happened. If the callback is later re-ordered to pop-after-transition, this sweeper starts dead-lettering jobs that were just moved to `done_queue`. Phase-3 tests include a regression test that fails on re-ordering (see `test_on_agentic_complete_pops_before_transition`).
>
> **Second safeguard — `get_by_id_hash` None-check**: the sweeper reads `dict(self._agentic_futures)` under lock to get a snapshot, then iterates WITHOUT the lock. If a completion callback fires DURING iteration and pops its id_hash + transitions to done_queue, the sweeper's stale snapshot still shows the future as "tracked and done" — the per-future check of `self.get_by_id_hash(id_hash)` returns `None` (job already moved out of running_queue), and the sweeper skips. This is not a race; it's the designed safe-flow. The pop-before-transition invariant AND the sweeper's None-check together ensure no double-transition under concurrent completion.

```python
def _ghost_job_sweep( self ):
    """
    Scan running_queue for agentic jobs whose Future is done() but are still
    in running_queue (i.e., the transition never happened). Dead-letter them.
    Runs periodically; interval configurable via INI.

    INVARIANT DEPENDENCY: relies on _on_agentic_complete popping from
    _agentic_futures BEFORE transitioning. See 03-phase-2 Step 2.1 callout.
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

Concrete `__init__` ordering — append to the Phase 2 init sequence (`03-phase-2-*.md` Step 2.1):

```python
def __init__( self, config_mgr, ... ):
    # ... Phase 2 init (pool + futures + lock) already present ...

    # Phase 3: ghost-job sweeper
    self._ghost_job_sweeper_stop_event = threading.Event()
    self._ghost_job_sweeper_thread     = threading.Thread(
        target = self._ghost_job_sweep_loop,
        daemon = True,
        name   = "GhostJobSweeper",
    )
    self._ghost_job_sweeper_thread.start()

def _ghost_job_sweep_loop( self ):
    """Main loop — daemon thread. Runs until stop_event is set."""
    interval_seconds = self._config_mgr.get(
        "cj flow ghost job sweep interval seconds", default=30, return_type="int"
    )
    while not self._ghost_job_sweeper_stop_event.is_set():
        try:
            self._ghost_job_sweep()
        except Exception as e:
            du.print_banner(
                f"Ghost-job sweeper loop caught exception (continuing): {e!r}",
                error=True
            )
        # stop_event.wait returns True if event set (early wakeup) — loop exits next iter.
        self._ghost_job_sweeper_stop_event.wait( timeout=interval_seconds )
```

- Uses `threading.Event.wait(timeout=N)` for sleep — lets `shutdown_pool()` interrupt the nap immediately without waiting up to `interval_seconds`.
- Stopped as the **first** step in `shutdown_pool()` (before the pool drain) so the sweeper isn't racing against the drain. The `shutdown_pool()` prelude becomes:
  ```python
  self._ghost_job_sweeper_stop_event.set()
  self._ghost_job_sweeper_thread.join( timeout=5.0 )  # should exit within one wait-cycle
  # ... existing pool shutdown ...
  ```
- Daemon thread — dies with the process if anything goes wrong with graceful shutdown.

### Tests

| Test | What it proves |
|---|---|
| `test_ghost_job_detected_and_dead_lettered` | Test fixture (monkeypatched) sets a Future to done, leaves its job in `running_queue`, triggers sweep → job lands in `dead_queue` |
| `test_ghost_job_sweep_idempotent` | Sweep twice in a row; second run is a no-op (futures dict cleaned) |
| `test_ghost_job_sweep_ignores_live_futures` | In-flight (not done) futures untouched |
| `test_ghost_job_sweep_get_by_id_hash_none_skips` | **Second-safeguard regression**: during sweep iteration, simulate a callback finishing between snapshot and per-future check — `get_by_id_hash(id_hash)` returns None (already transitioned). Assert sweeper skips; no double-transition; no exception |
| `test_ghost_job_sweeper_loop_survives_exception` | Force `_ghost_job_sweep` to raise `RuntimeError` once. Assert `_ghost_job_sweep_loop` catches it, logs banner, and continues on the next tick (thread does not die) |
| `test_ghost_job_sweeper_stops_on_shutdown` | `shutdown_pool()` returns within timeout; sweeper thread exits within one tick of `stop_event.set()` |
| `test_on_agentic_complete_pops_before_transition` | **Invariant regression test**: monkeypatch `_transition_to_done` to record the state of `_agentic_futures` at entry; assert `job.id_hash not in _agentic_futures` at that point. Fails if the pop is ever re-ordered to run after the transition. |

These go into `src/tests/unit/test_agentic_pool.py` (extending the Phase 2 file).

---

## Step 3.2 — `ApiResourceManager` caller migration (first wave)

### Scope

ONLY Deep Research in Phase 3, but **both callers** of `WebSearchRateLimiter`:
- `src/cosa/agents/deep_research/api_client.py::_call_with_retry()` — the primary production caller.
- `src/cosa/agents/deep_research/cli.py` — a direct caller of `rate_limiter.estimate_total_time(...)` (surfaced by the fitness-review reuse-map survey as a hidden third caller; migrating it too keeps the "two-path" invariant in `01-design-review.md` §3a honest — DR side is fully on ARM, everything else is on legacy).

Migration validates the singleton shape against real callers without inventing patterns. Podcast/presentation/BFE/TFE/ClaudeCode stay on legacy `_call_with_retry()` patterns — see `01-design-review.md` §3a for the retirement triggers.

### Changes

**`src/cosa/agents/deep_research/api_client.py`** — `_call_with_retry()`:

Before (today):
```python
# Existing pseudocode
await self._rate_limiter.wait_if_needed()  # wait_if_needed takes NO args — reactive
response = await self._client.messages.create( ... )
self._rate_limiter.record_usage( tokens=response.usage.input_tokens )
```

After (Phase 3):
```python
from cosa.utils.api_resource_manager import get_arm  # module-level accessor, not class-method

arm = get_arm()
await arm.acquire( provider="anthropic_web_search" )  # no tokens arg — passthrough to reactive limiter
response = await self._client.messages.create( ... )
arm.record_call(
    provider    = "anthropic_web_search",
    tokens      = response.usage.input_tokens,
    latency_ms  = <measured>,
)
```

**`src/cosa/agents/deep_research/cli.py`** — direct `rate_limiter.estimate_total_time(...)` calls:

Current (direct):
```python
# Wherever cli.py imports and uses the module-level rate_limiter
total_time = rate_limiter.estimate_total_time( len( subqueries ) )
```

After (via ARM):
```python
from cosa.utils.api_resource_manager import get_arm

arm = get_arm()
# ARM exposes estimate_total_time as a passthrough method on the WebSearchRateLimiter.
# Expose via get_arm().get_web_search_limiter().estimate_total_time(...) OR
# add a dedicated ARM helper method. Pick the simpler path at impl time.
total_time = arm.get_web_search_limiter().estimate_total_time( len( subqueries ) )
```

(If this cli.py usage is purely a CLI helper / dev utility and not a production path, leaving it on the direct `rate_limiter` import is acceptable — document that decision in the execution log.)

### Compatibility note

The singleton's `acquire("anthropic_web_search", ...)` delegates internally to the same `WebSearchRateLimiter` that existed before. **Runtime behavior is identical** — just the call site moves.

**Agents NOT migrated in Phase 3** (stay on legacy `_call_with_retry()` per 01 §3a two-path invariant):
- `src/cosa/agents/podcast_generator/api_client.py::_call_with_retry()`
- `src/cosa/agents/presentation_generator/api_client.py::_call_with_retry()` (if present)
- Any `ClaudeCodeJob` / `BFE` / `TFE` code paths

These stay on legacy patterns indefinitely until a retirement trigger from `01-design-review.md` §3a fires. This is not an "address soon" TODO — the two-path reality is permanent-until-triggered.

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
    "inflight_agentic_jobs" : 2,
    "max_agentic_workers"   : 3,
    "pending_in_pool"       : 0,
    "api_resource_manager"  : {
        "anthropic_web_search" : {
            "tokens_in_window"          : 12500,
            "tokens_per_minute_limit"   : 30000,
            "calls_in_window"           : 3,
            "window_seconds"            : 60.0,
            "time_until_oldest_expires" : 42.5,
            "would_need_delay"          : false
        },
        "anthropic" : { "provider_wait_state" : "passthrough" },
        "openai"    : { "provider_wait_state" : "passthrough" },
        "gemini"    : { "provider_wait_state" : "passthrough" }
    }
}
```

Note: the `anthropic_web_search` section is a **verbatim passthrough** of `WebSearchRateLimiter.get_status()` — no key renames. The legacy field `active_agentic_jobs` has been renamed to `inflight_agentic_jobs` to disambiguate running vs submitted (the UI's "running" label derives as `inflight - pending`).

The `api_resource_manager` key is populated by calling `ApiResourceManager.get_instance().get_status()` (the Phase 1 stub already returns this shape).

---

## Step 3.4 — Full regression (all four automated layers)

This is the pre-merge gate per project rule. Run in this order, each passing before proceeding.

> **Executor contract**: every row below is `EXECUTOR: AI`. No row is `EXECUTOR: HUMAN`. See `00-working-contract.md` and §TESTING VENUES for venue routing.

#### A. `:7999` (AI-discretionary — AI runs without asking)

| # | Layer | Command | Gate |
|---|---|---|---|
| 1 | **py_compile** | Compile each modified `.py` file: `python -c "import py_compile; py_compile.compile('<path>', doraise=True)"` | Exit 0; no stderr |
| 2 | **Unit** | `pytest src/tests/unit/ -v` | 915 baseline + Phase 1 + 2 + 3 tests; all green |
| 3 | **Non-destructive smoke** | `/smoke-test-remediation SELECTIVE` (excludes `test_proxy_integration.py` and any other `:8000`-routed suite — see sub-table B) | No regressions against baseline |
| 4 | **WebSocket smoke** | `./src/scripts/run-websocket-smoke-tests.sh` | 50/50 pass |

#### B. `:8000` (scheduled monopolize-mode — AI submits via `/api/test-suite/submit` after user slot-check)

The `--bg` forms below are **local-foreground fallback**, not the primary path from Claude Code.

| # | Layer | Submission | Gate |
|---|---|---|---|
| 5 | **Destructive smoke** (proxy integration) | `POST /api/test-suite/submit {"test_types": "smoke", "scheduled_at": "..."}` — fallback: `python src/tests/smoke/test_proxy_integration.py --group all --auto-proxy --no-confirm` | 100% pass |
| 6 | **E2E UI** | `POST /api/test-suite/submit {"test_types": "e2e_ui", "scheduled_at": "..."}` — fallback: `./src/scripts/run-e2e-ui-tests.sh --bg -v` | 285/285 pass |
| 7 | **Integration (final gate)** | `POST /api/test-suite/submit {"test_types": "integration", "scheduled_at": "..."}` — fallback: `./src/tests/run-integration-tests.sh --bg -v` | 43/43 pass |

For local-fallback monitoring only: `tail -20 /tmp/e2e-ui-latest.log` and `tail -20 /tmp/integration-latest.log`. Primary path is the scheduled submission — wait for each `:8000` slot to drain between submissions.

### Protocol E2E — Phase 3 mandatory concurrent-happy-path (AI-executed)

**REQUIRED** for Phase 3 sign-off (this is the behaviour-validation that automated tests can't express). Every step is executed by the AI via the API against `:7999`:

1. EXECUTOR: AI — Set `cj flow max concurrent agentic jobs = 3` (`:7999` auto-reloads).
2. EXECUTOR: AI — **Warmup**: POST /api/push (MathAgent, trivial query); poll `/api/get-queue/done` until returned; discard. Warms fast-lane Phi-4-GPTQ path so the measured MathAgent in step 6 isn't confounded by cold-GPU load (3–8s).
3. EXECUTOR: AI — POST /api/push × 2 (DeepResearch dry-run — uses the mechanism confirmed in `91-phase-2-execution-log.md` Step 2.0) sequentially, seconds apart; capture both `job_id`s.
4. EXECUTOR: AI — While both research jobs are running, POST /api/push (MathAgent, "what is 17 * 23?"); capture `job_id`.
5. EXECUTOR: AI — Poll `/api/get-queue/running` while DRs run; assert both DR `job_id`s present simultaneously.
6. EXECUTOR: AI — Poll `/api/get-queue/done` until MathAgent completes; assert elapsed < 5s.
7. EXECUTOR: AI — GET `/api/queue/pool-status` mid-run (with auth); assert payload shape `{inflight_agentic_jobs: 2, max_agentic_workers: 3, pending_in_pool: 0, api_resource_manager: {...}}`.
8. EXECUTOR: AI — Continue polling until both DRs complete; assert `running_queue` size returns to 0.
9. EXECUTOR: AI — Assert no jobs stuck in `running_queue` after both finish.
10. EXECUTOR: AI — Report all observed values (timings, pool-status payload, final queue sizes) via cosa-voice `notify`.

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
| `src/rnd/v0.1.7/2026.04.23-cj-flow-async-multi-lane/01-design-review.md` | Add postmortem-pointer: "Implemented per `0{2,3,4}-phase-N-*.md` in the same dir" |

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

## Pre-resolved design decisions (2026-04-23 fitness review)

1. **Sweeper cadence**: **30s default** (kept). Bounded to [5s, 300s] via splainer note; below 5s is noise, above 300s is too slow to catch ghosts in realistic workloads.
2. **Deep Research `_rate_limiter` field**: **remove** it during migration. Fewer paths to maintain; `get_arm()` is the canonical handle. If any legacy reference remains after migration, the grep-style regression test catches it.
3. **`record_call` timing semantics**: **receipt-time** (kept). Matches Deep Research's current behaviour; no drift during migration. Any future predictive / pre-flight accounting can add a separate `record_intent()` method without changing existing semantics.
4. **Documentation depth**: **update existing docs only** — `notification-api.md`, `websocket-architecture.md`, `rest-api-reference.md`. No dedicated `cj-flow-async-pool.md` in Phase 3. A dedicated doc can follow if the milestone ships widely and needs one.

---

## Definition of done (v0.1.7 async-pool milestone)

- All three phases' design docs landed with paired execution logs fully populated.
- All four automated test layers pass (unit 915+, smoke no-regression, WS 50/50, E2E 285/285, integration 43/43).
- Protocol E2E — concurrent-happy-path observed green (AI-executed with reported values).
- `/api/queue/pool-status` returns correct payload during mixed workload.
- v0.1.5 anchor doc bannered as superseded; v0.1.7 design-review doc points at implementation docs.
- TODO.md line 340 parent task checked off (with dated completion note); follow-up items (agent migration for podcast/presentation/BFE/TFE) captured as new TODO entries.
