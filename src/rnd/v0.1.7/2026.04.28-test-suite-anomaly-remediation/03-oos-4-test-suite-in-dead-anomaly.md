# OOS-4 — Why 21:06 test_suite job ended up in `dead` not `done` (PROPOSAL — awaiting ratification)

**Status**: Plan only. No code work until ratified.
**Prewarm-evidence update**: 2026-04-28 read-only forensic pass through `running_fifo_queue.py` + `test_suite_completion_watchdog.py` + remediation-snapshot writer surfaced the canonical-vs-non-canonical dead-write split + isolated the empty-error root cause to a single missing line. Findings folded in below.

This OOS subsumes WG-8c (the empty-error field on the 8 reaped Calculator dead jobs) AND OOS-1's Finding D (integration-e2e-remediation.json empty-failures regression) since all three share the family "non-canonical state-transition / data-flow path."

---

## Prewarm Findings (2026-04-28, evidence-grounded)

### Finding A — 5 dead-queue write paths; only 1 is canonical

**File**: `src/cosa/rest/running_fifo_queue.py`

| Line | Context | Canonical? | Sets `job.error`? |
|------|---------|------------|-------------------|
| 314 | `_process_job` bare exception catch (line 270) | NO | **NO** ← bug |
| 378 | `_handle_error_case` | NO | YES (line 346: `running_job.error = notification_msg`) |
| 762 | inside `_transition_to_dead` | **YES** | YES (line 702 sets `job.error = error_msg`) |
| 1202 | `_handle_agentic_job` failed-path (line 1180-1202) | NO | depends — uses `running_job.error` for stack_trace metadata, but doesn't explicitly set |
| 1263 | `_handle_agentic_job` exception catch (line 1207) | NO | YES (line 1217: `running_job.error = str(e)`) |

**Implication**: there are FOUR sites that bypass `_transition_to_dead`. They evolved organically as the codebase grew. Three of them happen to set `job.error`; one (line 314) doesn't. Hence the 8 reaped Calculator dead jobs with empty error fields.

### Finding B — Empty-`error` root cause: ONE missing assignment at line 270 catch

**File**: `src/cosa/rest/running_fifo_queue.py:270-314`

```python
except Exception as e:
    print( f"[RUNNING] Error processing job: {e}" )
    print( f"[RUNNING] Full stack trace:" )
    traceback.print_exc()

    failed_job = self.head()
    if failed_job:
        # ... build websocket metadata with error: str(e) ...
        metadata = {
            'error'     : str( e ),         # ← in metadata
            ...
        }
        emit_job_state_transition( ... )    # ← emit OK

        # Phase 2: id_hash-based delete
        self.delete_by_id_hash( failed_job.id_hash )
        self.jobs_dead_queue.push( failed_job )    # ← push WITHOUT setting failed_job.error
```

The `error: str(e)` ONLY lives in the WebSocket metadata dict; **it never gets persisted on the `failed_job` object before the push**. Compare to the equivalent paths:

- `_handle_error_case:346`: `running_job.error = notification_msg` ✓
- `_handle_agentic_job` exception:1217: `running_job.error = str(e)` ✓

**Fix**: ONE-LINE addition before the metadata dict:

```python
failed_job.error = str( e )       # ← ADD THIS
```

Plus a defensive assertion in `dead_queue.push` would catch any future regression. Or: refactor to route through `_transition_to_dead`.

### Finding C — `test_suite_completion_watchdog` does NOT move source to dead

`grep -n 'dead\|_transition' src/cosa/rest/test_suite_completion_watchdog.py` returned **zero matches**. Confirmed: the watchdog spawns TFE as a sibling and lets the source test_suite job stay in `done`. This matches the design.

So how did the 21:06 test_suite job end up in `dead` with `status=completed`?

**Hypothesis** (needs runtime evidence to confirm): the `_handle_agentic_job` exception catch at line 1207 fired during the test_suite job's post-execution wrap-up — for example, while the watchdog tried to spawn TFE, an exception bubbled up, the test_suite job's state was already `JobState.COMPLETED`, but the exception-handling path moved the (already-completed) job to dead. The empty-`error` bug at line 314 didn't trigger here because line 1217 properly sets `.error`. But the user's API view showed `error=(none)` — so this hypothesis predicts wrong evidence.

Alternative hypothesis: the test_suite job's `do_all` returned successfully, was about to be `_transition_to_done`'d, but something in the post-completion accounting (e.g., `_evaluate_for_auto_fix` at line 1205, which may itself spawn tasks that fail) raised an exception, which was caught at the parent layer and moved the job to dead.

**This requires runtime trace evidence** that we don't have. Phase 1 of OOS-4's investigation should add structured logging at each dead-queue write site so the next test_suite-in-dead occurrence is fully traceable.

### Finding D — `integration-e2e-remediation.json` empty-failures regression (needs runtime evidence)

**File**: `src/cosa/agents/test_suite/job.py:511-515`

```python
for suite_type, result in self.suite_results.items():
    for fd in result.get( "failure_details", [] ):
        fd_copy            = dict( fd )
        fd_copy[ "suite" ] = suite_type
        snapshot[ "failures" ].append( fd_copy )
```

The writer correctly iterates suites and pulls `failure_details`. The bug must be **upstream** — the integration suite's `result` dict has `failure_details=[]` (or missing entirely) despite `failed > 0` in the same dict.

The integration script at `src/tests/run-integration-tests.sh:219` runs:
```
"$VENV_PYTHON" -m pytest src/tests/integration/ "${REMAINING_ARGS[@]}"
```

REMAINING_ARGS includes the `--junit-xml=/tmp/integration-junit-...xml` flag injected by `test_suite/job.py:712`. So junit-xml SHOULD be written.

But: from the host, `ls /tmp/integration-junit-*.xml` returns nothing. The test_suite_job runs **inside the lupin-rest-test container**, so its `/tmp/` is the container's /tmp/, not host's. To verify, one needs:

```
docker exec lupin-rest-test ls -la /tmp/integration-junit-*.xml 2>/dev/null
```

If the file exists but `_parse_junit_xml` is dropping its content → bug is in the parser (specific to integration's junit-xml shape).
If the file doesn't exist → bug is in junit-xml NOT being written by the integration shell script (perhaps argument-forwarding breaks at some level).

**Phase 1 of OOS-4 must include this container-side inspection to localize.**

The breadth of impact (every `integration-e2e-remediation.json` since 04.24 is broken — that's 12+ runs) makes this medium severity. The 22:35 `all-remediation.json` worked because each component-suite (unit, smoke, integration, e2e) wrote its own junit-xml AND something about the `all` test_types path apparently aggregates differently, OR all of those component-suites individually populated `failure_details` even though the standalone `integration-e2e` runs don't. Confusing — needs evidence.

---

## Revised approach (post-prewarm)

### Part A — Empty-error fix (Finding B) [TRIVIAL]

- 1-line addition at `running_fifo_queue.py:294` (just before `metadata = { ... }`):
  ```python
  failed_job.error = str( e )
  ```
- Add a defensive precondition to `dead_queue.push` (or a helper) that asserts `job.error` is non-empty:
  ```python
  def _push_to_dead_with_assertion( self, job ):
      assert job.error, f"job {job.id_hash} pushed to dead with empty error"
      self.jobs_dead_queue.push( job )
  ```
  Migrate all 4 non-canonical sites to use it.
- Unit test: simulate `_process_job` raising; assert `failed_job.error` is non-empty after; assert it propagates into the dead-queue listing.

**Effort**: XS (~30 min including the test).

### Part B — Refactor 4 non-canonical paths through `_transition_to_dead` (Finding A) [SMALL]

- The 4 non-canonical sites (314, 378, 1202, 1263) reproduce significant logic that `_transition_to_dead` already does. Migrate each one to call `self._transition_to_dead( job, exc )`.
- The signatures differ — some build elaborate metadata dicts inline. Refactor to pass enough context to `_transition_to_dead` to recover the same metadata.
- Unit tests for each migrated path.

**Effort**: M (~3-4 hours). Risk-bearing because the 4 paths are subtly different.

### Part C — test_suite-in-dead trace logging (Finding C) [SMALL]

Until we have runtime evidence, we can't fix Finding C. Phase 1 of this:
- Add `logger.info("[DEAD-WRITE] from <site>", site_id=N, job_id=..., job_type=..., error=..., stack=...)` at every `dead_queue.push` call (5 sites).
- Wait for the next test_suite-in-dead occurrence.
- Read the logs to identify which site fired.
- Fix per evidence.

**Effort**: XS (logging) + uncertain wait time + S (fix per evidence).

### Part D — Integration-e2e remediation regression (Finding D) [SMALL after evidence]

Phase 0:
```
docker exec lupin-rest-test ls -la /tmp/integration-junit-*.xml
docker exec lupin-rest-test cat /tmp/integration-junit-<latest>.xml | head -40
```

Then localize per the if/then in Finding D. Likely a one-line parser fix or a shell-script arg-forwarding fix.

**Effort**: XS-S after Phase 0.

---

## Recommended order

A → C-logging → wait for evidence → B+C-fix → D (independently, anytime). Part A is the cheapest highest-value win (one-line + assertion + test) — would do it standalone before anything else.

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
