# Approach C — Phase 1 Execution Log

**Status**: NOT STARTED (skeleton only — populate as implementation proceeds)
**Paired design doc**: `01-phase-1-rlock-config-and-resource-manager.md`
**Branch**: `wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe`

---

## Progress ledger

Mark each sub-step as work lands. Format: `[ ]` pending, `[~]` in progress, `[x]` done, `[!]` blocked.

### Step 1.1 — RLock on `FifoQueue`

- [ ] Add `import threading` to `src/cosa/rest/fifo_queue.py`
- [ ] Add `self._lock = threading.RLock()` to `FifoQueue.__init__`
- [ ] Wrap `push()` body with `with self._lock:`
- [ ] Wrap `pop()` body with `with self._lock:`
- [ ] Wrap `head()` body with `with self._lock:`
- [ ] Wrap `get_by_id_hash()` body with `with self._lock:`
- [ ] Wrap `delete_by_id_hash()` body with `with self._lock:`
- [ ] Wrap `is_empty()` body with `with self._lock:`
- [ ] Wrap `size()` body with `with self._lock:`
- [ ] Wrap `has_changed()` body with `with self._lock:`
- [ ] Wrap `clear()` body with `with self._lock:`
- [ ] Wrap `get_jobs_for_user()` body with `with self._lock:`
- [ ] Wrap `get_all_jobs()` body with `with self._lock:`
- [ ] Add comment explaining RLock-vs-Lock choice (re-entrant calls)
- [ ] `py_compile` verification passes

### Step 1.2 — INI key

- [ ] Add `cj flow max concurrent agentic jobs = 1` to `src/conf/lupin-app.ini`
- [ ] Add matching entry in `src/conf/lupin-app-splainer.ini`
- [ ] Config loader reads the key without `KeyError`
- [ ] Dev environment override bumps to `= 3` (verify how dev overrides work — env var? separate INI? TBD during impl)

### Step 1.3 — `ApiResourceManager` stub

- [ ] Create `src/cosa/utils/api_resource_manager.py`
- [ ] Implement `get_instance()` classmethod with thread-safe double-check
- [ ] Implement `__init__` with `_lock` and lazy `_web_search_limiter` handle
- [ ] Implement `acquire( provider, tokens )` with lazy import of `WebSearchRateLimiter`
- [ ] Implement `record_call( provider, tokens, latency_ms )` no-op for passthrough providers
- [ ] Implement `get_status()` returning the Phase-1 payload shape
- [ ] `py_compile` verification passes
- [ ] Import chain verification: `PYTHONPATH=src python -c "from cosa.utils.api_resource_manager import ApiResourceManager; print(ApiResourceManager.get_instance())"`

### Step 1.4 — Tests

- [ ] Create `src/tests/unit/test_fifo_queue_thread_safety.py`
  - [ ] `test_concurrent_push_no_corruption`
  - [ ] `test_concurrent_push_pop_consistency`
  - [ ] `test_concurrent_read_during_write`
  - [ ] `test_delete_by_id_hash_under_concurrency`
  - [ ] `test_rlock_reentrant_pop`
- [ ] Create `src/tests/unit/test_api_resource_manager.py`
  - [ ] `test_singleton_returns_same_instance`
  - [ ] `test_singleton_thread_safe_construction`
  - [ ] `test_acquire_passthrough_provider_returns_immediately`
  - [ ] `test_acquire_web_search_delegates_to_rate_limiter`
  - [ ] `test_record_call_passthrough_is_noop`
  - [ ] `test_get_status_shape`

### Phase 1 verification

> **Executor contract**: every checkbox below is `EXECUTOR: AI`. The AI runs against `:7999`, captures output, and reports pass/fail via cosa-voice before marking `[x]`. Phase 1 has no `EXECUTOR: HUMAN` steps. See `00-working-contract.md`.

- [ ] Both new test files pass (`pytest ... -v`)
- [ ] Full unit regression passes (`pytest src/tests/unit/ -v`)
- [ ] `/smoke-test-remediation FULL` — no regressions
- [ ] `./src/scripts/run-websocket-smoke-tests.sh` — 50/50
- [ ] `./src/scripts/run-e2e-ui-tests.sh --bg -v` — 285/285 (`--bg` MANDATORY)
- [ ] `./src/tests/run-integration-tests.sh --bg -v` — 43/43 (`--bg` MANDATORY, final gate)

---

## Blockers / open questions encountered

(Fill in during implementation. Remove section if empty at phase close.)

| Date | Blocker | Resolution |
|---|---|---|
| — | — | — |

---

## Surprises / notable deviations from design doc

(Document any places where the implementation had to diverge from `2026.04.23-01-*.md`.)

| Date | What diverged | Why |
|---|---|---|
| — | — | — |

---

## Commits

| Date | Commit hash | Summary | Files |
|---|---|---|---|
| — | — | — | — |

---

## Verification results

Fill in output / key evidence as each verification step completes.

```
# py_compile
$ python -c "import py_compile; py_compile.compile( 'src/cosa/rest/fifo_queue.py', doraise=True )"
(TBD)

# import chain
$ PYTHONPATH=src python -c "from cosa.rest.fifo_queue import FifoQueue; from cosa.utils.api_resource_manager import ApiResourceManager; print('OK')"
(TBD)

# new unit tests
$ pytest src/tests/unit/test_fifo_queue_thread_safety.py src/tests/unit/test_api_resource_manager.py -v
(TBD)

# full unit regression
$ pytest src/tests/unit/ -v
(TBD — expect 915 baseline + ~11 new = ~926 passing)

# smoke
$ /smoke-test-remediation FULL
(TBD)

# WebSocket smoke
$ ./src/scripts/run-websocket-smoke-tests.sh
(TBD — expect 50/50)

# E2E UI (background)
$ ./src/scripts/run-e2e-ui-tests.sh --bg -v
$ tail -20 /tmp/e2e-ui-latest.log
(TBD — expect 285/285)

# Integration (final gate, background)
$ ./src/tests/run-integration-tests.sh --bg -v
$ tail -20 /tmp/integration-latest.log
(TBD — expect 43/43)
```

---

## Phase 1 sign-off criteria

- All checkboxes above marked `[x]`.
- No items in "Blockers" section (or all resolved).
- Verification results filled in with actual command output.
- Commit hash(es) recorded.
- Ready to hand off to Phase 2.
