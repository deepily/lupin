# OOS-4 — Why 21:06 test_suite job ended up in `dead` not `done` (PROPOSAL — awaiting ratification)

**Status**: Plan only. No code work until ratified.

This OOS subsumes WG-8c (the empty-error field on the 8 reaped Calculator dead jobs) since both anomalies likely share the same dead-queue routing path.

## Evidence

### Anomaly A — `test_suite` job at 21:06 is in `dead` queue with `status=completed`

```
9. 2026-04-27T21:06:24.513003-04:00 [test_suite] [Tests] all
   status=completed   error=(none)
```

Per design (and confirmed by exploration of `src/cosa/rest/test_suite_completion_watchdog.py`), a completed `test_suite` job with failures is supposed to:
1. Stay in `done` queue with `status=completed`.
2. Spawn a TFE sibling job to handle remediation.

Evidence shows the 21:06 job is in `dead` instead. The TFE sibling `tfe-d9786eea` (the one that stalled) was successfully spawned, so the watchdog at least *fired* — but the source job was somehow moved to dead afterward.

### Anomaly B — 8 dead Calculator jobs with empty `error` field

```
1-8. CalculatorAgent ... status=pending  error=(none)
```

Per `running_fifo_queue.py:702`, `_transition_to_dead` sets `job.error = error_msg`. Empty error means either:
- A different code path moved these jobs to dead (bypassing `_transition_to_dead`)
- `_transition_to_dead` was called with `error_msg=""` or `None`

Both anomalies suggest there's a **second `run → dead` (or `done → dead`) path** that doesn't follow the canonical `_transition_to_dead` path. Finding it is the goal of OOS-4.

## Hypotheses

| # | Hypothesis | Test |
|---|------------|------|
| 1 | A reaper or watchdog (separate from `dead_queue_watchdog`) moves stalled run-queue jobs to dead without populating `error` | grep `dead_queue.push\|jobs_dead_queue.push` across `src/cosa/` |
| 2 | The `test_suite_completion_watchdog` itself moves the source job to dead **after** spawning TFE | read `test_suite_completion_watchdog.py` for any `dead_queue.push` calls |
| 3 | A consumer-loop exception path moves jobs to dead with `error=""` because the exception is swallowed before population | inspect `_transition_to_dead` callers and look for `_transition_to_dead( job, "" )` or `_transition_to_dead( job, None )` patterns |
| 4 | Manual queue manipulation via API endpoint (e.g. an admin route or migration script) | check git log for recent commits touching `dead_queue` |

## Investigation plan

### Phase 0 — Code grep audit (read-only, 30 min)

```
grep -rn 'dead_queue\.push\|jobs_dead_queue\.push\|dead_queue\.add' src/cosa/ src/fastapi_app/
grep -rn '_transition_to_dead' src/cosa/
grep -rn 'dead.*queue.*move\|to_dead' src/cosa/
```

Catalogue every site that moves a job to `dead`. Each site should:
- Set `job.error` to a non-empty descriptive string.
- Use `_transition_to_dead` (preferred) OR be marked with a comment explaining why it bypasses.

Any site that doesn't is a candidate root cause.

### Phase 1 — Replay reproduction

Submit a known-failing test_suite job (e.g. dry-run with an obviously-failing pytest target) on `:7999` and observe whether it lands in `done` or `dead`. If it lands in `dead`, we've reproduced. If `done`, the bug is conditional on something specific to the 21:06 run (timing, TFE spawn, runtime error in the watchdog itself).

### Phase 2 — Root-cause + fix

Based on Phase 0 + 1 evidence:
- If a non-canonical path is found: route it through `_transition_to_dead` with a descriptive error message.
- If `test_suite_completion_watchdog` is moving the source: confirm it's intentional, document, and either move the source-routing into the canonical path or leave a flag-controlled toggle.
- If empty-error is from `_transition_to_dead( job, "" )`: tighten with `assert error_msg, "_transition_to_dead requires non-empty error"`.

### Phase 3 — Belt-and-suspenders unit test

Add `src/tests/unit/test_dead_queue_error_population.py`:
- For each known `dead_queue.push` site, exercise the path with a controlled failure and assert `job.error` is non-empty after.
- Add a class-level `assert error` precondition in the dead-queue push wrapper (if one doesn't exist).

## Files likely to change

Unknown until Phase 0. Most likely:
- `src/cosa/rest/running_fifo_queue.py` (canonical `_transition_to_dead`)
- `src/cosa/rest/test_suite_completion_watchdog.py` (if it's the offender)
- `src/cosa/rest/dead_queue_watchdog.py` (read-only; verify it's NOT a writer)
- new file: `src/tests/unit/test_dead_queue_error_population.py`

## Acceptance criteria

- Every `dead_queue.push` (or equivalent) call site is documented with a comment: which error path triggered, what error message gets populated.
- `_transition_to_dead` enforces non-empty `error_msg` (assertion or normalization).
- New unit test exercises every known dead-queue routing path and asserts `error` is non-empty.
- Replay of a failing test_suite job lands in `done` (not `dead`) per design.

## Estimated effort

S-M: 4-6 hours. Code grep + replay are quick; fix shape depends on what's found.

## Out of scope (for OOS-4)

- Major refactoring of the queue transition machinery (separate ticket if Phase 0 reveals architectural issues).
- WG-8a (cleanup of the existing 9 dead jobs) — separate user-confirmed action.
- TFE sibling-spawn lifecycle clarification (already by-design per exploration; no work needed).
