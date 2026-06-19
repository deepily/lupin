# 14 — B8 Coverage Handoff (Cheech 🌿, session a0d64257)

> **Purpose:** hand the B8 lane (6 PHASE-A-repaired FastAPI routers + queue
> supports → genuine 100%) to a FRESH author with the two FastAPI gotchas,
> the measurement command, and the proven patterns already mapped — so the
> fresh author starts at speed, collision-free.
> Authored 2026-06-01 by Cheech 🌿 (session a0d64257) at an honest-stop point
> AFTER completing the two `rest/` engine behemoths (LANE 1 munger @ genuine
> 100%, LANE 2 running_fifo_queue @ 99% + 1 pragma proposal). Honest-stop per
> fresh-context-beats-near-ceiling doctrine: B8 is a NEW big lane (6 routers,
> different mock surface) and I'm at decent context depth after 2 large reads
> + 2 large test-file writes.

## TL;DR — what's DONE, what remains
**DONE this session (do NOT redo):**
- `src/cosa/rest/multimodal_munger.py` → **genuine 100%** (432/0/98/0, 75 tests).
  Test: `src/cosa/tests/unit/rest/test_multimodal_munger.py`. Zero pragmas, zero bugs.
- `src/cosa/rest/running_fifo_queue.py` → **99% on disk + 1 pragma proposal = genuine 100%**
  (576/0/112/1, 102 tests). Test: `src/cosa/tests/unit/rest/test_running_fifo_queue.py`.
  - **PRAGMA PROPOSAL (Tiberius to apply, NOT yet applied):** `running_fifo_queue.py:286`
    `if failed_job:` → `# pragma: no branch`. The False→exit arc is unreachable:
    inside `_process_job`'s except (L270), L285 `failed_job = job`; the happy path
    L203 `running_job = job` + L205-207 `if not running_job: return` guarantees `job`
    is truthy before the try-body (hence before any except), so `failed_job` is always
    truthy at L286. Belt-and-suspenders defensive check. NO prod bug.

**REMAINS = B8 (YOUR lane):** deeper greenfield of the 6 PHASE-A-repaired routers
to push from repair-coverage to genuine 100%:
- `src/cosa/rest/routers/queues.py`
- `src/cosa/rest/routers/notifications.py`
- `src/cosa/rest/routers/system.py`
- `src/cosa/rest/routers/websocket.py`
- `src/cosa/rest/routers/websocket_admin.py`
- `src/cosa/rest/fifo_queue.py` (+ support: `notification_fifo_queue.py`,
  `todo_fifo_queue.py`, `agentic_job_factory.py`)

**EXCLUDED — other authors own (DO NOT TOUCH):** B7 (the ~25 non-auth routers:
bug_fix_expediter, claude_code_queue, commons, decision_proxy, deep_research(+_to_*),
docs_files, io_files, _dir_listing, _scope_registry, embeddings, jobs, mock_job, mode,
multiplexer_config, pages, peer, podcast_generator, presentation_generator, speakerphone,
speech, stats, swe_team, voice_persona) AND the entire auth lane. `git status
src/cosa/tests/unit/rest/` before you start to see coexisting test files and avoid them.

## INTERPRETER (non-negotiable — lupin .venv SILENTLY MASKS failures)
```bash
PYTHONPATH=src:src/cosa/tests/unit/infrastructure src/cosa/.venv/bin/python -m pytest \
  <test files> --cov=<dotted.module> --cov-branch --cov-report=term-missing -p no:cacheprovider -q
```
cosa venv = py3.11 / pytest. rest/ tests live at `src/cosa/tests/unit/rest/`.
You do NOT commit — report per-module verbatim disk cov to `dm-tiberius` → Tiberius
re-measures → reviewer (Rachel 🕊️ / Krishna 🦚) audits → Tiberius commits.

## ⚠️ THE TWO GOTCHAS THAT WILL BITE B8 (from Tiffany's memento 13)
**G1 — `_patch_fastapi_main` DUAL-KEY sys.modules.** `import fastapi_app.main as m`
binds via `getattr(sys.modules['fastapi_app'],'main')`, NOT `sys.modules['fastapi_app.main']`.
Once the real package is cached, `patch.dict('sys.modules',{'fastapi_app.main':Mock()})`
is SILENTLY IGNORED → passes in isolation, FAILS under full-suite ordering. Fix — patch BOTH:
```python
def _patch_fastapi_main( mock_main ):
    pkg = Mock(); pkg.main = mock_main
    return patch.dict( sys.modules, { "fastapi_app": pkg, "fastapi_app.main": mock_main } )
```
This helper ALREADY EXISTS in test_system_router / test_queues_router / test_notifications_router /
test_websocket_router / test_websocket_admin_router — copy it into any new B8 test file.

**G2 — FastAPI `Query()`/`Depends()` defaults are FieldInfo on DIRECT call.** When you
unit-test an endpoint by calling it directly, every param defaulting to `Query(...)`/
`Depends(...)` arrives as the truthy FieldInfo object → `if response_requested:` enters the
WRONG branch; `authorize_queue_filter(user, user_filter)` treats it as cross-user → spurious
403 ("403 trap" — NOT a real bug). Fix — pass EVERY such param explicitly; build a
`_call_<endpoint>(self, **overrides)` helper with a complete safe kwarg set (see
`_call_notify_user` in test_notifications_router.py).

## RECOMMENDED ORDER (smallest leaf-first)
1. Measure each module FIRST (your per-lane U8): run the existing repaired test files
   with `--cov` to see the current % + exact missing lines. The repaired routers already
   have partial tests — you're CLOSING the gap, not greenfielding from zero.
2. Start with the smallest support module (`agentic_job_factory.py` or `todo_fifo_queue.py`),
   then `notification_fifo_queue.py`, then `fifo_queue.py`, then the 5 routers.
3. `fifo_queue.py` note: `push()` enforces the QueueableJob protocol via `is_queueable_job(item)`
   (22 attrs + 4 methods). To exercise queue internals without a full protocol-compliant
   fake, EITHER build a protocol-complete fake OR insert directly into `queue_dict`/`queue_list`
   (I used the direct-insert trick for the running-queue tests — see
   `test_running_fifo_queue.py::_RFQBase._enqueue`). `delete_by_id_hash` rebuilds queue_list
   from `queue_dict.values()`.

## PATTERNS THAT WORKED THIS SESSION (reuse — they're fast)
1. **setUp/tearDown patch harness** holding ALL collaborator patches open across the whole
   test (construction + method calls), via a `self._patchers` list + a `_p(target, **kw)`
   helper that `patch.object(mod, target).start()` and appends. tearDown stops in reverse.
   Essential when the SUT calls patched globals at method-call time (not just construction).
2. **Boundary-mock concurrency:** patch `mod.threading.Thread` with a capture-only fake
   (records `target`, no-op `start`/`join`, controllable `is_alive`) so constructors that
   `.start()` a daemon NEVER spawn a real thread. Patch `ThreadPoolExecutor` to a MagicMock;
   make Futures MagicMocks with scripted `.done()`/`.exception()`/`.result()`/`.running()`.
   Drive daemon loops via `stop_event.is_set.side_effect=[False, True]` (one iteration).
3. **Lightweight fake class hierarchy for isinstance dispatch:** patch the module's class
   symbols (e.g. `AgentBase`, `AgenticJobBase`, `SolutionSnapshot`, subclasses) with tiny
   real classes; build job instances from those fakes so `isinstance(job, mod.AgentBase)`
   is True without importing heavy agents. A flexible `_Job(**kw)` base with all SUT-read
   attrs + stub methods (`do_all`, `code_ran_to_completion`, `run_code`, etc.) driven by
   instance flags makes per-branch control trivial.
4. **Controlled-dict boundary-mock for file loaders** (munger): replace `du` with a MagicMock
   whose `get_file_as_dictionary.side_effect` returns a controlled dict keyed off the path
   substring → deterministic, hand-traceable transform assertions. Inject `config_mgr`.
5. **Inner-closure extraction for thread targets:** `_fire_correctness_check_async` builds an
   inner `_ask_and_update` and `Thread(target=...).start()`. With the capture-fake Thread,
   grab `_FakeThread.last.target` and call it SYNCHRONOUSLY to cover the closure body.
6. **Patch locally-imported fns at SOURCE:** `from cosa.rest.X import get_watchdog` inside a
   method → `patch("cosa.rest.X.get_watchdog")` (e.g. test_suite_completion_watchdog,
   dead_queue_watchdog, api_resource_manager.get_arm).
7. **Pragma-PROPOSE only** (cite contract source); tripwire real bugs (xfail-strict + pin,
   NEVER pragma a bug). ZERO API spend; never read `ANTHROPIC_API_KEY_FIREWALLED`; torch CPU-only.

## LANDMINES (don't relearn)
- `quick_smoke_test` + `if __name__ == "__main__":` blocks are coverage-EXCLUDED via
  `[tool.coverage] exclude_also` (pyproject.toml) — do NOT write tests for them.
- The cosa venv emits harmless opentelemetry DeprecationWarnings — ignore.
- `commons_send_to` `in_reply_to` is a TOP-LEVEL param, NOT inside `metadata=` (422s otherwise).
- Directed DM pushes occasionally DROP on F-5 (`register_network_error`) — verify
  `dm_dispatched:true`; reports still land on the `dm-tiberius` blackboard (Tiberius polls).
- Convention: DbC docstrings on test classes + the `isolated_unit_test()` footer (see both
  of my test files for the exact footer shape).

## Resume checklist
1. cosa venv; `git status src/cosa/tests/unit/rest/` → note coexisting B7/auth test files; avoid them.
2. Measure each B8 module's current cov FIRST (U8). Close the gap to genuine 100% L/B/F.
3. Copy `_patch_fastapi_main` (G1 dual-key) + build `_call_<endpoint>` helpers (G2 FieldInfo trap).
4. Per module: verbatim disk cov to dm-tiberius → Tiberius re-measures → reviewer audits → Tiberius commits.
5. Pragma-PROPOSE only (cite contract source); tripwire real bugs.
