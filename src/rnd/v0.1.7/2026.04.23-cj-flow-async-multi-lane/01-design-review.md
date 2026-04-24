# CJ Flow — Serial → Async + Hybrid Multi-Lane: Design Review

**Status**: Design review (no implementation yet)
**Session**: resumed from Session 237 (2026-02-19)
**Anchor doc**: `src/rnd/v0.1.5/2026.02.19-approach-c-hybrid-queue-architecture.md`
**Companion**: `src/rnd/v0.1.4/2026.02.13-claude-code-agentic-dev-team/2026.02.18-approach-d-hybrid-queue-checkin.md`

---

## Context

CJ Flow (COSA Jobs Flow: `todo → running → done/dead`) currently executes jobs **strictly serially**. One background consumer thread (`src/cosa/rest/queue_consumer.py:42-122`) pops the next eligible job and calls `running_queue._process_job( job )`, which blocks until the job's synchronous `do_all()` returns. For agentic jobs, `do_all()` bridges to async via `asyncio.run( self._execute() )` — still blocking the consumer for the full duration.

**Practical effect today**: a 10-minute DeepResearchJob blocks every subsequent 2-second MathAgent query. Session 237 already produced a full design (Approach C) and an 11-step, 3-phase roll-out in TODO.md. Approach D (Session 223) covers the related user↔job communication pattern needed once ClaudeCodeJob INTERACTIVE lives in its own lane.

The user's question is two-part:
1. **What did that design look like?** (recap Approach C)
2. **What are the implications — beyond faster throughput — of going async?**

This document answers both and flags the open design questions before we commit to implementation.

---

## 1. What the design looks like (Approach C recap)

### 1a. One picture

```mermaid
flowchart TD
    A[TodoFifoQueue] -->|condition.notify| B[Consumer / Dispatcher]
    B -->|isinstance AgenticJobBase| C[ThreadPoolExecutor<br/>max_workers = N]
    B -->|AgentBase / Snapshot| D[Fast Lane — inline]
    C -->|Worker 1| E1[DeepResearchJob]
    C -->|Worker 2| E2[PodcastJob]
    C -->|Worker N| E3[ClaudeCodeJob]
    D --> F[RunningFifoQueue]
    E1 -->|Future.add_done_callback| F
    E2 -->|Future.add_done_callback| F
    E3 -->|Future.add_done_callback| F
    F -->|success| G[DoneQueue + WS]
    F -->|failure| H[DeadQueue + WS]
```

### 1b. The core moves

| Move | Where | Why |
|------|-------|-----|
| Consumer becomes a **dispatcher**, not an executor | `running_fifo_queue.py::_process_job()` | One thread routes; many threads execute |
| Sync agents stay **inline (fast lane)** | `_process_fast_lane()` | Local GPU already serialized at inference — no win from parallelism |
| Agentic jobs **submitted to a `ThreadPoolExecutor`** | `_submit_agentic_job()` / `_execute_agentic_in_pool()` | Anthropic API is the resource; concurrency is bounded by rate limit quota |
| Completion handled in a **`Future.add_done_callback`** | `_on_agentic_complete()` | Moves job from `running → done/dead` off the pool thread back into queue state |
| `FifoQueue` gains a **`threading.RLock()`** | `src/cosa/rest/fifo_queue.py` | Guards `queue_list` / `queue_dict`; RLock (not Lock) because `pop()→is_empty()` and `delete_by_id_hash()→size()` are re-entrant |
| **`delete_by_id_hash()`**, not `pop()`, in agentic paths | `running_fifo_queue.py` | Order isn't preserved under concurrency — remove by key, not by head |

### 1c. What the design deliberately keeps

- `QueueableJob` protocol is untouched. `do_all()` stays synchronous.
- Agentic jobs' internals untouched — each one still creates its own event loop via `asyncio.run()`. Thread pool owns the parallelism; coroutines are a private implementation detail of each job.
- WebSocket event shape (`job_state_transition`) unchanged. Browser UI already keys cards by `job_id`, so multiple concurrent "running" cards just work.
- Cache lookup, I/O logging, snapshot persistence logic unchanged — only their concurrency guarantees.

### 1d. Knob

One INI key in `[Lupin: Baseline]`:

```ini
cj flow max concurrent agentic jobs = 3
```

`= 1` reproduces today's serial behaviour (ship-safe default for the first deploy). `= 3` is the design target. Upper bound is effectively Anthropic rate limits, not CPU.

### 1e. Lanes — how many?

Approach C as designed is **two lanes** (short inline + long pool). Session 237 consciously deferred a third lane. Today's job inventory suggests the two-lane cut is still the right first step, with one honest asymmetry worth naming:

| Lane | Members | Rationale |
|------|---------|-----------|
| **Short / Fast** (inline, 1 at a time) | `AgentBase` (Math, Calendar, Calculator, Receptionist, Todo, Weather, DateAndTime), `SolutionSnapshot` | <2s, LLM-bound, local-GPU-serialized |
| **Long / Agentic pool** (N concurrent) | `DeepResearchJob`, `PodcastGeneratorJob`, `PresentationGeneratorJob`, chained research jobs, `SweTeamJob`, `TestSuiteJob`, `TestFixExpediterJob`, `BugFixExpediterJob`, `ClaudeCodeJob BOUNDED` | minutes to hours, API-bound, rate-limit-bounded |
| **(Deferred) Interactive** | `ClaudeCodeJob INTERACTIVE`, and arguably any job holding an open WS to a human | Bidirectional streaming; indefinite human-wait time would clog an N-worker pool |

The INTERACTIVE-lane question is the main open design decision — see §3.

---

## 2. Implications, beyond "faster"

The user asked specifically what changes *other than* throughput. Organised by concern:

### 2a. Concurrency safety — the central implication

Going async means state that was *de-facto* safe because only one thread touched it is now touched by many. Approach C audited this; the residual exposure is tight:

| Shared state | Today's protection | Under pool | Action |
|--------------|-------------------|------------|--------|
| `FifoQueue.queue_list / queue_dict` | "Only the consumer thread mutates" | Pool-callback threads also mutate (when calling back into running/done/dead) | **`threading.RLock()` inside `FifoQueue`** — the one mandatory new primitive |
| `WebSocketManager.emit*_sync` | Already uses `asyncio.run_coroutine_threadsafe` against the main loop | Same, from more threads | No change needed |
| `emit_job_state_transition()` | Already thread-safe (wraps the above) | Same | No change |
| `UserJobTracker` | Already has its own `Lock` | Same | No change |
| `InputAndOutputTable.insert_io_row()` (SQLite) | Single writer | Concurrent writers via WAL mode | SQLite WAL serialises writers — fine, but worth verifying under load |
| `SnapshotManager` persistence | Internal `_save_lock` | Same | Already defensive |

**Implication**: the blast radius is much smaller than "thread everything." But *any* future code that mutates queue state outside the lock has become a concurrency bug source. This is a discipline cost that persists forever, not just during migration.

### 2b. Ordering and determinism change character

CJ Flow is FIFO today in a very strong sense: if job A was submitted before job B, B starts only after A finishes. Under Approach C:

- **Within a lane**, FIFO start-order is preserved (dispatcher pops todo in order).
- **Completion order** is not: a fast job submitted after a slow one can finish first. The UI already handles this (cards keyed by `job_id`), but downstream consumers that assumed "the latest `done` entry is my job" will be wrong.
- **Across lanes** there's no ordering at all — a 2s MathAgent submitted after a 10min DeepResearchJob finishes first. That's the point.
- **`pop()` is dangerous for agentic paths** — the head of `running_queue` is no longer "the job that just finished." This is why the design mandates `delete_by_id_hash(job.id_hash)` in every agentic path.

**Implication**: any consumer code, test, or mental model that relied on "running has size 1 and its head is the current job" has to be reviewed. The `/api/get-queue`-family endpoints and any watchdogs (`dead_queue_watchdog`, `test_suite_completion_watchdog`, `repair_attempt_tracker`) are the exposed spots.

### 2c. Failure-mode geometry changes

Serial mode has a convenient property: a crash kills at most one in-flight job. Under a pool:

- N jobs can be in-flight when the process dies → N lost runs. Shutdown hook (`shutdown_pool( wait=True, timeout=30.0 )`) is not optional — without it we'll see phantom running rows.
- `_on_agentic_complete()` is the single path that moves a finished job from running → done/dead. **If that callback raises, the job is stuck in `running_queue` forever** (no "ghost detector" exists). The callback has to be defensively written and the exception-in-callback path has to go somewhere observable.
- Agentic `do_all()` raises → in the old world the consumer's `try/except` caught it. Under the pool, exceptions travel through `Future.exception()` and must be pulled out in the callback. Forgetting this = silent job loss.
- **Partial failures**: today, one agentic job timeout just delays the queue. Under a pool, a stuck job holds a worker slot and reduces effective concurrency until its timeout fires. The pool size is *effective*, not nominal, under contention.

**Implication**: we need to add ghost-job detection (e.g., `running_queue` sweep for jobs whose `Future.done()` is true but which never transitioned) before we consider this production-ready.

### 2d. Resource contention moves from CPU/thread to rate-limits/cost

The serial architecture was its own backpressure: only one job spent money at a time. Under a pool:

- **Anthropic API rate limits** become the real ceiling. Three DeepResearchJobs in parallel can hit RPM/TPM caps and cause cascading 429s that don't exist today.
- **Spend is now multiplicative**: three concurrent DeepResearch + one BFE can easily burn through several dollars per minute. The serial queue was a crude but effective cost governor.
- **GPU contention** is *not* a concern for agentic (API-bound) jobs, but the fast lane still uses local Phi-4-GPTQ. That's why sync stays inline — running 3 local-LLM jobs in parallel would thrash VRAM.
- **TTS / Gemini / Veo** (podcast, presentation) share external quota pools across concurrent jobs. Today they can't step on each other because only one runs.

**Implication**: the INI default should be `= 1` for first deploy and only be raised after we have per-provider rate-limit observability. Consider a "budget guard" that checks remaining spend before the dispatcher submits a new agentic job.

### 2e. Observability debt becomes real

Serial made debugging easy: "look at the consumer thread, it's either in the job or waiting." Under a pool:

- Log lines need thread-prefix discipline (design already specifies `AgenticPool-N` thread names).
- **`/api/queue/pool-status`** endpoint (`{active_agentic_jobs, max_agentic_workers, pending_in_pool}`) is listed as "optional Phase 3" in the original plan — in practice it's table-stakes for debugging a live deployment, so treat it as Phase 2.
- The Notifications / WebSocket UI already renders multiple `running` cards correctly (keyed by `job_id`). But there's no *admin* visualization of "here's what the pool is doing right now" — we should add a minimal admin card.
- Watchdog interactions (dead-queue watchdog, test-suite completion watchdog) need to be reviewed for pool-awareness; most are already state-machine-driven, not order-driven, so likely fine.

**Implication**: plan real observability in with the first implementation, not after-the-fact.

### 2f. Testing complexity increases step-wise

- Existing unit tests assume serial: "push three jobs, assert they finish in order." Some of those assertions stop being meaningful.
- Two brand-new test files (`test_fifo_queue_thread_safety.py`, `test_agentic_pool.py`) are mandatory — not optional. They exercise concurrency, not just correctness, which is qualitatively different (harder to make deterministic).
- E2E UI suite (285 tests) and integration suite (43 tests) probably still pass as-is if default stays at `= 1`, but we need a **concurrent-happy-path E2E** (two agentics + one math, simultaneous) as part of Phase 3 verification. That suite is ~17min and must use `--bg` per project rules.
- Per recent feedback: "Plans must include ALL automated testing layers" — we also need to schedule a smoke-test regression before declaring Phase 2 complete.

### 2g. Shutdown and resume semantics

Serial shutdown just stops the consumer thread. Pool shutdown must:

1. Stop the dispatcher from submitting new work.
2. Let in-flight agentic jobs finish (`wait=True`) up to a timeout.
3. Time out gracefully — dead-letter any job that didn't finish so it isn't "running forever" after restart.
4. Mirror this behaviour in the existing checkpoint/resume logic for BFE/TFE, which currently assumes they can resume from state serialized by a single executor.

**Implication**: shutdown is the place where bugs will hide. It needs its own test and its own runbook entry.

### 2h. UI + user expectations shift

- Notifications page starts showing multiple "running" cards concurrently. This already works technically; the UX implication is the user now sees a *busy* system instead of a *serial* one. Some users may interpret "3 things running" as "something is stuck" — small copy/UX pass probably warranted.
- Voice notifications (cosa-voice) currently announce one-at-a-time completions. Under concurrency, `notify()` calls can arrive in rapid bursts. May need a debounce or batching layer in the TTS side.
- ClaudeCodeJob INTERACTIVE running alongside other agentic jobs is fine in principle — but if it's in the same pool, it holds a worker slot indefinitely while waiting on the human, which is the argument for a separate interactive lane (§3).

### 2i. Human-in-the-loop jobs need extra thought

`BugFixExpediterJob`, `TestFixExpediterJob`, and `ClaudeCodeJob INTERACTIVE` all block on operator input. Two are already async-notification-driven (BFE/TFE stall on a notification response, not on a synchronous wait), so they fit the long lane cleanly. `ClaudeCodeJob INTERACTIVE`, however, holds bidirectional state for its whole session — if we let three of those occupy the agentic pool simultaneously with a 3-worker limit, no other agentic work runs until a human hits "end session." This is the single strongest argument for a third "interactive" lane (see §3).

---

## 3. Open questions worth deciding before implementation

These are the design calls that Session 237's plan either deferred or left implicit. Worth deciding together *before* touching code:

1. **Interactive lane — yes or no?** Two-lane ships faster. Three-lane (short / long / interactive) prevents ClaudeCodeJob INTERACTIVE from starving the pool. Recommendation: keep Phase 1/2 as two-lane, but plan the third lane now so we don't refactor twice.
2. **Default concurrency**: ship with `= 1` (no behavioural change, pure infra) then bump, vs. ship with `= 3` from day one. Recommendation: `= 1` default, dev env on `= 3` for testing.
3. **Cost guardrail**: add a per-user or per-session spend cap that the dispatcher checks before submitting to the pool? Or leave cost-control entirely out of CJ Flow?
4. **Ghost-job detection**: add a small watchdog that sweeps `running_queue` for jobs whose pool `Future` is done but whose transition never happened? Or rely on the callback always firing?
5. **Pool-status endpoint**: move from "Phase 3 optional" to "Phase 2 required"? (My read: yes.)
6. **Per-job-type pools** (e.g., separate pool for TestSuiteJob so a 60-min E2E run doesn't starve research)? Or single pool?
7. **Approach D coupling**: Approach D (inbound user messages buffered, drained at check-in) is the natural complement for interactive-lane jobs. Should it land in the same milestone or stay separate?

---

## 4. What staying the course would look like (if we decide to proceed)

If the answer to "what next" is *proceed with Approach C as designed*, the existing TODO.md breakdown is already valid:

- **Phase 1** — RLock in `FifoQueue`, config key, thread-safety unit tests. Self-contained and safe to ship alone.
- **Phase 2** — Dispatcher refactor in `running_fifo_queue.py`, shutdown hook in `main.py`, pool-status endpoint (recommended promoted from Phase 3), agentic-pool unit tests, smoke-test-remediation pass.
- **Phase 3** — Integration E2E test (concurrent agentic + sync), full regression, admin observability surface, docs updates (`notification-api.md`, `websocket-architecture.md`).

At that point we'd re-open the interactive-lane question as a follow-up, informed by real pool behaviour.

---

## 5. Files that would be touched (no code yet)

| File | Role |
|------|------|
| `src/cosa/rest/fifo_queue.py` | Add `threading.RLock`, wrap methods |
| `src/cosa/rest/running_fifo_queue.py` | Dispatcher refactor, pool, callbacks — the big change |
| `src/cosa/rest/queue_consumer.py` | Trivial — already delegates to `_process_job()` |
| `src/fastapi_app/main.py` | Shutdown hook |
| `src/conf/lupin-app.ini` + `lupin-app-splainer.ini` | One key + splainer |
| `src/cosa/rest/routers/queue.py` (or similar) | `/api/queue/pool-status` endpoint |
| `src/tests/unit/test_fifo_queue_thread_safety.py` (new) | Phase 1 tests |
| `src/tests/unit/test_agentic_pool.py` (new) | Phase 2 tests |
| `src/docs/notification-api.md`, `websocket-architecture.md` | Docs |
| `src/rnd/v0.1.5/2026.02.19-approach-c-hybrid-queue-architecture.md` | Update status as phases land |

---

## 6. Verification (if we later implement)

- `pytest src/tests/unit/ -v` (full unit regression, currently 915 tests baseline)
- `pytest src/tests/unit/test_fifo_queue_thread_safety.py -v`
- `pytest src/tests/unit/test_agentic_pool.py -v`
- `./src/scripts/run-websocket-smoke-tests.sh` (50 tests)
- `./src/scripts/run-e2e-ui-tests.sh --bg -v` (285 tests, ~17 min — `--bg` mandatory)
- `./src/tests/run-integration-tests.sh --bg -v` (43 tests — final gate)
- Protocol E2E (`EXECUTOR: AI` — see `00-working-contract.md`): two concurrent deep-research (dry-run) + a math query; AI asserts math returns in seconds and both research jobs finish.

---

## 7. This file's role

This is a **design-review plan**, not an implementation plan. The user asked *what the design looks like* and *what changes beyond speed*; §1 and §2 answer those directly. §3 surfaces the calls I'd want to make together before we start cutting code. If the user wants to proceed, we turn §4/§5/§6 into a concrete implementation plan (with paired execution logs per project convention) and serialize into `src/rnd/v0.1.5/` alongside the existing Approach C doc.
