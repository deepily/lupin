# Approach C — Phase 1 Execution Log

**Status**: NOT STARTED (skeleton only — populate as implementation proceeds)
**Paired design doc**: `02-phase-1-rlock-config-and-resource-manager.md`
**Branch**: `wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe`

---

## Progress ledger

Mark each sub-step as work lands. Format: `[ ]` pending, `[~]` in progress, `[x]` done, `[!]` blocked.

> **Implementation steps below (Steps 1.1 – 1.4) are EXECUTOR: AI throughout** — these are code-writing checkboxes. Verification steps in the "Phase 1 verification" section later in this file carry their own per-line `EXECUTOR:` tags.

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
- [ ] EXECUTOR: AI — `python -c "import py_compile; py_compile.compile('src/cosa/rest/fifo_queue.py', doraise=True)"` — AI asserts exit code 0, reports stdout verbatim

### Step 1.2 — INI key

- [ ] Add `cj flow max concurrent agentic jobs = 1` to `src/conf/lupin-app.ini` under the existing `[Lupin: Baseline]` block
- [ ] Add matching entry in `src/conf/lupin-app-splainer.ini`
- [ ] EXECUTOR: AI — `PYTHONPATH=src python -c "from cosa.app.configuration_manager import ConfigurationManager; cm = ConfigurationManager('gib-app.ini'); print(cm.get('cj flow max concurrent agentic jobs', default=1, return_type='int'))"` — AI asserts output is `1` and exit code is 0 (no `KeyError`).
- [ ] EXECUTOR: AI — Check whether `[Lupin: Dev Overrides]` block exists in `lupin-app.ini` already (from prior dev-overlay work). If not, add the block with a comment explaining it is read only when `LUPIN_ENV=dev`. Add `cj flow max concurrent agentic jobs = 3` inside the block. Add splainer entry describing the override mechanism.
- [ ] EXECUTOR: AI — Verify the dev overlay works: `LUPIN_ENV=dev PYTHONPATH=src python -c "from cosa.app.configuration_manager import ConfigurationManager; cm = ConfigurationManager('gib-app.ini'); print(cm.get('cj flow max concurrent agentic jobs', default=1, return_type='int'))"` — AI asserts output is `3`. Then without `LUPIN_ENV=dev`, rerun and assert output is `1`. If `ConfigurationManager` does not support the `[Lupin: Dev Overrides]` pattern natively, surface via cosa-voice `ask_multiple_choice` before proceeding (don't invent overlay logic without user input).

### Step 1.3 — `ApiResourceManager` stub

- [ ] Create `src/cosa/utils/api_resource_manager.py`
- [ ] Implement module-level singleton pattern: `_arm_instance: Optional[ApiResourceManager] = None`, `init_arm() -> ApiResourceManager` (idempotent), `get_arm() -> ApiResourceManager` (raises `RuntimeError` if not initialised)
- [ ] Implement `ApiResourceManager.__init__` with lazy `self._web_search_limiter = None` (no internal RLock — no construction race under module-level singleton)
- [ ] Implement `async def acquire( self, provider: str ) -> None` (no tokens arg) with lazy import of `WebSearchRateLimiter` inside the method to avoid utils→agents cycle
- [ ] Implement sync `record_call( self, provider: str, tokens: int = 0, latency_ms: float = 0.0 ) -> None` — no-op for passthrough providers; delegates to `WebSearchRateLimiter.record_usage(tokens)` for `anthropic_web_search`
- [ ] Implement `get_status() -> dict` returning verbatim passthrough of `WebSearchRateLimiter.get_status()` under `anthropic_web_search` key (no key rename); passthrough providers return `{"provider_wait_state": "passthrough"}`
- [ ] EXECUTOR: AI — `python -c "import py_compile; py_compile.compile('src/cosa/utils/api_resource_manager.py', doraise=True)"` — AI asserts exit code 0
- [ ] EXECUTOR: AI — `PYTHONPATH=src python -c "from cosa.utils.api_resource_manager import init_arm, get_arm; arm = init_arm(); print(arm); print(get_arm() is arm)"` — AI asserts (a) `init_arm()` returns non-None, (b) `get_arm() is arm` prints `True` (same object), (c) no ImportError / AttributeError

### Step 1.3b — Wire `init_arm()` into server startup

- [ ] Add `from cosa.utils.api_resource_manager import init_arm` to `src/fastapi_app/main.py` imports
- [ ] Call `init_arm()` in the startup hook (same function / lifespan that already inits other singletons like TFE/BFE watchdogs — grep `init_watchdog` in main.py to locate the canonical startup block). No agents CALL it yet; the wiring ensures the infrastructure is alive from boot.
- [ ] EXECUTOR: AI — `python -c "import py_compile; py_compile.compile('src/fastapi_app/main.py', doraise=True)"` — AI asserts exit code 0
- [ ] EXECUTOR: AI — After edit, restart FastAPI once (user-owned), then `PYTHONPATH=src python -c "import requests; r = requests.get('http://localhost:7999/health'); assert r.status_code == 200"` — AI asserts server came up cleanly (sanity check that `init_arm()` did not crash startup)

### Step 1.4 — Tests

- [ ] Create `src/tests/unit/test_fifo_queue_thread_safety.py`
  - [ ] `test_concurrent_push_no_corruption`
  - [ ] `test_concurrent_push_pop_consistency`
  - [ ] `test_concurrent_read_during_write`
  - [ ] `test_delete_by_id_hash_under_concurrency`
  - [ ] `test_rlock_reentrant_pop`
  - [ ] `test_phase2_shaped_stress` — simulates 1 dispatcher + 4 callback threads with random mix of `push` / `delete_by_id_hash` / `size` / `get_all_jobs` for 5s; 10s watchdog thread aborts the test on deadlock. At end asserts: (1) no deadlock (watchdog did not fire); (2) `len(queue._queue_list) == len(queue._queue_dict)`; (3) `set(item.id_hash for item in queue._queue_list) == set(queue._queue_dict.keys())`. Catches RLock-placement bugs that only surface at Phase 2 concurrency.
- [ ] Create `src/tests/unit/test_api_resource_manager.py`
  - [ ] `test_get_arm_raises_before_init`
  - [ ] `test_init_arm_is_idempotent`
  - [ ] `test_get_arm_returns_singleton`
  - [ ] `test_acquire_passthrough_provider_returns_immediately`
  - [ ] `test_acquire_web_search_delegates_to_rate_limiter`
  - [ ] `test_acquire_no_tokens_arg` — regression test for signature decision
  - [ ] `test_record_call_passthrough_is_noop`
  - [ ] `test_record_call_web_search_delegates`
  - [ ] `test_get_status_shape` — verbatim-passthrough of `WebSearchRateLimiter.get_status()` keys

### Phase 1 verification

> **Executor contract**: every checkbox below is `EXECUTOR: AI`. AI captures output and reports pass/fail via cosa-voice before marking `[x]`. Phase 1 has no `EXECUTOR: HUMAN` steps. See `00-working-contract.md` and §TESTING VENUES for routing.

#### A. `:7999` AI-discretionary

- [ ] EXECUTOR: AI — Both new test files pass: `pytest src/tests/unit/test_fifo_queue_thread_safety.py src/tests/unit/test_api_resource_manager.py -v`
- [ ] EXECUTOR: AI — Full unit regression passes: `pytest src/tests/unit/ -v` (915 baseline + new tests)
- [ ] EXECUTOR: AI — `/smoke-test-remediation SELECTIVE` (non-destructive only; destructive suites routed to :8000 below) — no regressions
- [ ] EXECUTOR: AI — `./src/scripts/run-websocket-smoke-tests.sh` — 50/50

#### B. `:8000` scheduled monopolize-mode (AI submits via `/api/test-suite/submit` after user slot-check)

- [ ] EXECUTOR: AI — E2E UI via `POST /api/test-suite/submit {"test_types": "e2e_ui", "scheduled_at": "<user-confirmed>"}` (local fallback: `./src/scripts/run-e2e-ui-tests.sh --bg -v`) — 285/285
- [ ] EXECUTOR: AI — Integration (final gate) via `POST /api/test-suite/submit {"test_types": "integration", "scheduled_at": "<user-confirmed>"}` (local fallback: `./src/tests/run-integration-tests.sh --bg -v`) — 43/43

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
