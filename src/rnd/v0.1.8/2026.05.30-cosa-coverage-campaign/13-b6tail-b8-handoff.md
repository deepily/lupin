# 13 — B6-tail + B8 Coverage Handoff (Tiffany 💍, session ab4302c5)

> **Purpose:** hand the LAST two `src/cosa/rest/` engine behemoths + the B8 router
> deeper-greenfield to a FRESH author with every pattern, gotcha, and interpreter
> detail already mapped — so execution is fast and collision-free.
> Authored 2026-06-01 by Tiffany 💍 (session ab4302c5) at an honest-stop point
> (this session authored **19 test files / ~700 tests** — all of B5 + most of B6 —
> and is at deep context; fresh context outperforms on the two LARGEST files in the
> whole `rest/` tree). Honest-stop ratified by Tiberius 👑.

## TL;DR
B5 (DB) + most of B6 (watchers/daemons/engines) are DONE @ genuine 100% (see "What's
DONE"). What remains is **(1) `multimodal_munger.py` (1556 LOC), (2) `running_fifo_queue.py`
(1895 LOC) — the two biggest files in `rest/` — and (3) B8: deeper greenfield of the 6
PHASE-A-repaired routers to 100%.** B7 (~25 non-auth routers) and the auth lane are
OTHER authors' — do NOT touch them.

Interpreter (non-negotiable):
```bash
PYTHONPATH=src:src/cosa/tests/unit/infrastructure src/cosa/.venv/bin/python -m pytest <path> \
  --cov=<dotted.module> --cov-branch --cov-report=term-missing -p no:cacheprovider -q
```
cosa venv = py3.11 / pytest 9.0.2. The lupin `.venv` (3.13/pytest 8.4.2) silently MASKS
failures — never use it. rest/ tests live at `src/cosa/tests/unit/rest/`. You do NOT
commit — report per-module verbatim disk cov to Tiberius → reviewer (Rachel 🕊️ / Clayton 😎)
audits → Tiberius commits. Use `timeout 60-180` on every run (torch/heavy imports can take
seconds).

## What's DONE this session (do not redo) — all genuine 100% L/B/F
**B5 (DB) — 7 modules, 118 tests** (routed to Rachel):
`db/repositories/{base, prediction_log_repository, proxy_decision_repository, notification_repository}`,
`db/database`, `sqlite_database`, `postgres_models`.

**B6 (watchers/daemons/engines) — 11 modules** (cluster 3 committed; 4+5+6+util routed to Clayton/Rachel):
`watchdogs`, `commons_topic_watcher`, `queue_consumer`, `commons_ack_watcher`,
`commons_activity_watcher`, `commons_question_watcher`, `test_suite_completion_watchdog`,
`dead_queue_watchdog`, `job_persistence`, `util_llm_client`.

**Pragmas (manager applied — for reference):**
- `queue_consumer.py:124` `if job:` → `# pragma: no branch` (committed 5bbd16a). Falsy arc unreachable: inner loop exits only via job-found break (job truthy) or `consumer_running=False` (breaks at L121 before L124).
- `commons_activity_watcher.py:187` `elif latest_ts ...` → `# pragma: no cover`. Unreachable: store contract guarantees every entry has a non-None ts (see "Pragma class" below), so the prior `if` (L183) always fires when entries exist; empty tick early-returns at L135.

## YOUR scope (B6-tail + B8)
**EXCLUDED — other authors own:** the auth lane (auth*/jwt/password/refresh_token/email*/
user_service/admin_service/auth_audit/auth_middleware/queue_auth/user_id_generator, routers/auth,
routers/admin, the 7 auth db/repositories), AND **B7** (the ~25 NON-auth routers:
bug_fix_expediter, claude_code_queue, commons, decision_proxy, deep_research(+_to_podcast/
_to_presentation), docs_files, io_files, _dir_listing, _scope_registry, embeddings, jobs,
mock_job, mode, multiplexer_config, pages, peer, podcast_generator, presentation_generator,
speakerphone, speech, stats, swe_team, voice_persona) — a fresh author owns those.
`git status src/cosa/tests/unit/rest/` before you start to see coexisting test files.

**B6-tail (do first, ROI: do munger before running_fifo_queue):**
1. `multimodal_munger.py` (1556) — read it first; likely transform/parse logic + possibly
   LLM/transcription calls. Boundary-mock every LLM / file / network / subprocess seam.
2. `running_fifo_queue.py` (1895) — the CJ Flow execution engine. THE hard one:
   `ThreadPoolExecutor` (the "agentic pool"), `Future.add_done_callback` →
   `_on_agentic_complete`, the ghost-job sweeper DAEMON thread, `threading.RLock`,
   `isinstance`-dispatch in `_process_job`, the `_transition_to_done/_dead` primitives,
   `delete_by_id_hash` (NOT pop). See CLAUDE.md § CJ FLOW for the architecture. Boundary-mock
   the pool + futures (don't spawn real threads — use the Thread-capture pattern below).

**B8 (after B6-tail):** deeper greenfield of the 6 PHASE-A-repaired routers to push from
repair-coverage to 100%: `routers/queues`, `routers/notifications`, `routers/system`,
`routers/websocket`, `routers/websocket_admin`, and `fifo_queue` (+ `notification_fifo_queue`,
`todo_fifo_queue`, `agentic_job_factory` support). **These are FastAPI routers → BOTH of
Tiffany's original gotchas (below) bite HARD here.**

## ⚠️ GOTCHAS (will bite)
**G1 — `_patch_fastapi_main` DUAL-KEY sys.modules (B8 routers).** `import fastapi_app.main as m`
binds via `getattr(sys.modules['fastapi_app'],'main')`, NOT `sys.modules['fastapi_app.main']`.
Once the real package is cached, `patch.dict('sys.modules',{'fastapi_app.main':Mock()})` is
SILENTLY IGNORED → passes in isolation, FAILS under full-suite ordering. Fix — patch BOTH:
```python
def _patch_fastapi_main( mock_main ):
    pkg = Mock(); pkg.main = mock_main
    return patch.dict( sys.modules, { "fastapi_app": pkg, "fastapi_app.main": mock_main } )
```
The helper already exists in test_system_router / test_queues_router / test_notifications_router /
test_websocket_router / test_websocket_admin_router — copy it into new B8 test files.

**G2 — FastAPI `Query()`/`Depends()` defaults are FieldInfo on DIRECT call (B8 routers).**
When you unit-test an endpoint by calling it directly, every param defaulting to `Query(...)`/
`Depends(...)` arrives as the truthy FieldInfo object. → `if response_requested:` enters the wrong
branch; `authorize_queue_filter(user, user_filter)` treats it as cross-user → spurious 403 (the
"403 trap" — NOT a real bug). Fix — pass EVERY such param explicitly; build a
`_call_<endpoint>(self, **overrides)` helper with a complete safe kwarg set (see `_call_notify_user`
in test_notifications_router.py).

## Patterns that WORKED this session (reuse them — they're fast)
1. **Fluent self-returning query mock** (SQLAlchemy query-builder repos / `session.query` chains):
   ```python
   def _fq( rows=None, first=None, scalar=None, count=None, delete=None, update=None ):
       q = MagicMock()
       for m in ( "filter","order_by","limit","offset","group_by" ): getattr( q, m ).return_value = q
       q.all.return_value=rows or []; q.first.return_value=first; q.scalar.return_value=scalar
       q.count.return_value=count; q.delete.return_value=delete; q.update.return_value=update
       return q
   self.session.query.return_value = _fq( rows=[...] )
   ```
   Assert branch coverage via `q.filter.call_count` (how many optional filters were applied).
2. **`get_db` context-manager boundary-mock** (every persistence fn does `with get_db() as s:`):
   ```python
   def _mock_get_db( session ):
       mg = MagicMock(); mg.return_value.__enter__.return_value = session
       mg.return_value.__exit__.return_value = False; return mg
   patch.object( mod, "get_db", _mock_get_db( session_mock ) )
   ```
   For the except/fire-and-forget arc: `patch.object( mod, "get_db", side_effect=RuntimeError(...) )`.
   For multi-execute fns: `session.execute.side_effect = [ result1, result2 ]`.
3. **Thread-capture + deterministic exit** (daemon loops — CRITICAL for running_fifo_queue's
   sweeper + any consumer):
   - Patch `mod.threading.Thread`, grab the `target` from `MkThread.call_args.kwargs["target"]`,
     call it SYNCHRONOUSLY. ZERO real threads.
   - Drive loop exit with `_stop_event.wait.side_effect=[False, True]` (one iteration then stop),
     OR a `condition = MagicMock()` (so `.wait(timeout=)` is a no-op) plus a flag that a mock
     `side_effect` flips to False. Patch `mod.time.sleep` so retry-sleeps are instant.
4. **`SimpleNamespace`, NOT `Mock`, for SUT-introspected entities.** Mock auto-creates every attr
   (so `hasattr(mock, "x")` is always True) and `state.counter += 1` on a Mock attr yields a Mock
   (breaks int assertions). Use `SimpleNamespace( counter=0, ... )` with real fields when the SUT
   does `hasattr` / `+=` / attribute reads.
5. **Pragma class — unreachable defensive arcs (PROPOSE-only; manager applies):**
   - `if job:` / guard after a guaranteeing break → `# pragma: no branch`.
   - cursor-advance `elif` unreachable due to a DATA CONTRACT → `# pragma: no cover`. **MANDATE:
     READ the source that establishes the contract and cite file:line in your proposal** —
     Tiberius rightly challenged the commons_activity_watcher elif; the answer was in
     `lupin_mcp/commons_store.py` (`_HEADER_RE` makes ts mandatory; `read()`'s `e["ts"] > since`
     + sort would TypeError on None → ts always non-None). NEVER pragma a bug.
6. **Clock-seam nonzero-delta artifact.** A mocked-instant run rounds `Stopwatch.get_delta_ms()→0`
   → div-by-zero on a `tokens/second` line. Patch the `Stopwatch` class to return a nonzero delta
   (`timer.get_delta_ms.return_value=100.0`). This is a TEST ARTIFACT, not a prod bug (real work is
   never instant) — don't tripwire it.
7. **Real schema on a temp-FILE sqlite** (for DDL/init fns): you can't patch `.close` on a real
   `sqlite3.Connection` (read-only attr). Use a temp-FILE DB, let the fn commit+close, then REOPEN
   the file to inspect — genuine CREATE coverage, zero persistent state.
8. **Pure declarative ORM (postgres_models pattern):** import covers all column statements;
   only `__repr__` methods need invocation. Repr methods that SLICE a field (`token[:8]`,
   `id_hash[:20]`) need real strings passed.
9. **`patch` locally-imported fns at SOURCE.** `from cosa.rest.X import Y` inside a function →
   `patch("cosa.rest.X.Y")` (e.g. `create_agentic_job`, `get_tracker`, `get_job_by_id_hash`,
   `user_job_tracker`, `parse_sender_id`).

## Landmines hit (don't relearn these)
- **`consumer_worker` forces `todo_queue.consumer_running = True` at function entry** → you CANNOT
  pre-set it False to skip the loop; the "loop never entered" case is unreachable. Exit only by
  flipping the flag mid-iteration (via `condition.wait`/`_process_job`/`push` side_effect).
- **Coverage config:** `def quick_smoke_test` and `if __name__ == .__main__.:` are excluded via
  `[tool.coverage] exclude_also` (pyproject.toml) — do NOT write tests for smoke blocks.
- **pytest collection warning** "cannot collect test class 'TestSuiteCompletionWatchdog'… has a
  __init__" is HARMLESS (SUT class name starts with "Test") — ignore it.
- **`commons_send_to` `in_reply_to` is a TOP-LEVEL param**, not inside `metadata=` — passing it in
  metadata 422s.
- **Directed DMs occasionally DROP on F-5** (`register_network_error`) — verify `dm_dispatched:true`;
  my cluster-4 report dropped once and had to be re-posted.

## Resume checklist
1. cosa venv; `git status src/cosa/tests/unit/rest/` → note coexisting auth/B7 test files; avoid them.
2. Start with `multimodal_munger.py` (read → boundary-mock IO/LLM seams → 100% → report).
3. Then `running_fifo_queue.py` — Thread-capture the sweeper, boundary-mock the pool/futures.
4. Then B8 routers — copy `_patch_fastapi_main`, build `_call_<endpoint>` helpers (G1 + G2).
5. Per module: verbatim disk cov to Tiberius → reviewer audits → Tiberius commits. You do NOT commit.
6. Pragma-PROPOSE only (cite the contract source); tripwire real bugs (xfail-strict + pin, never
   pragma a bug). ZERO API spend; never read `ANTHROPIC_API_KEY_FIREWALLED`; torch CPU-only.
7. DbC docstrings on every test class + the `isolated_unit_test()` footer (campaign convention).
