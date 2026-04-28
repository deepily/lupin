# WG-8 — Run-queue orphan cleanup + consumer-stall guardrails

## Background

After the 2026-04-27 22:35 EDT run:
- 1 Calculator job stuck in `run` (`status="pending"`, `started_at=""`)
- 8 sibling Calculators reaped to `dead` with empty `error` field
- Pool empty (`inflight=0`)

The consumer thread either advanced jobs and then froze, OR the test harness pushed the trailing scenario right as the run ended.

## Three sub-WGs

### WG-8a (cleanup, manual, one-time)

Use existing endpoint `DELETE /api/queue/run/{job_id}` (admin endpoint at `src/cosa/rest/routers/queues.py:1189-1300`) to clear the orphan. Optionally also clear the 8 dead Calculator entries via `DELETE /api/queue/dead/{job_id}` for a clean slate.

Both are user-confirmed actions (mutate state on `:8000`). **Defer until user is back.**

### WG-8b (preventive — observability)

Add a consumer-thread heartbeat:
- `src/cosa/rest/queue_consumer.py` — write a timestamp at the top of each consumer-loop iteration (a single field on the consumer or queue object).
- `GET /api/queue/pool-status` (`src/cosa/rest/routers/queues.py:363-385`) — expose `last_consumer_heartbeat_at` and `seconds_since_heartbeat`.
- INI key `cj flow consumer stall threshold seconds = 120` in `lupin-app.ini`.
- Splainer entry in `lupin-app-splainer.ini`.

### WG-8c (preventive — error population audit)

Per exploration, `running_fifo_queue.py:702` does set `job.error` on `_transition_to_dead`. The 8 dead Calculator jobs have empty `error`, so either:
- they took a path that bypassed `_transition_to_dead`, OR
- a different reaper exists.

Add a unit test exercising the "reaped from run, never started" path and assert `job.error` is non-empty. If the test fails, fix the offending path.

## Acceptance

- WG-8a: orphan + 8 deads gone from `:8000` queues (deferred).
- WG-8b: `/api/queue/pool-status` shows `seconds_since_heartbeat` < threshold during normal ops.
- WG-8c: unit test passes; reaped jobs always have non-empty error.

## Files

- (cleanup) — none, API-only
- `src/cosa/rest/queue_consumer.py` (~5 lines)
- `src/cosa/rest/running_fifo_queue.py` + `routers/queues.py` (~10 lines)
- `src/conf/lupin-app.ini` + `splainer.ini` (1 INI key + splainer)
- `src/tests/unit/test_consumer_heartbeat.py` (NEW)
- `src/tests/unit/test_dead_queue_error_population.py` (NEW)

## Status

- [ ] WG-8a (DEFERRED — user-coordinated)
- [ ] WG-8b heartbeat write
- [ ] WG-8b pool-status read
- [ ] WG-8b INI key + splainer
- [ ] WG-8b unit test
- [ ] WG-8c unit test
- [ ] WG-8c follow-up if test fails
