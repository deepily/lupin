# 11 — REST Greenfield (B5/B6/B7) — Author Handoff (Tiffany 💍)

> **Purpose:** hand the remaining `src/cosa/rest/` greenfield coverage lane to a
> FRESH author with all partition intel, gotchas, and reusable patterns already
> mapped — so execution is fast and collision-free.
> Authored 2026-06-01 by Tiffany 💍 (session 65f3adf3) at an honest-stop point
> (this session authored 14 test files / ~290 tests — PHASE A repair + B3
> greenfield — and is at deep context; fresh context outperforms on the large
> NEW B5/B6/B7 lanes). Honest-stop ratified by Tiberius 👑 (option b).

## TL;DR
The `cosa/rest/` lane is the campaign long pole. PHASE A (stale-mock repair, 37→0)
and B3 (8 pure-logic modules greenfield to 100%) are DONE + green. What remains is
**B5 (non-auth DB) + B6 (watchers/daemons + queue engines) + B7 (~25 non-auth
routers)**. The auth/admin/user/token cluster is **Rio's ⚡** — do NOT touch it.

Interpreter (non-negotiable): `PYTHONPATH=src:src/cosa/tests/unit/infrastructure src/cosa/.venv/bin/python -m pytest <path> --cov=<dotted.module> --cov-branch --cov-report=term-missing -p no:cacheprovider -q`.
SDK/scipy-adjacent modules → `src/cosa/tests/run-sdk-cov.sh` instead. You do NOT
commit — report per-module verbatim disk cov to Tiberius → Clayton 😎 audits →
Tiberius commits.

## What's DONE (do not redo)
- **PHASE A repair**: test_system_router, test_websocket_admin_router, test_websocket_router,
  test_fifo_queue, test_queues_router, test_notifications_router — all green, full rest/
  dir 37 failed → 0. Routed to Clayton.
- **Systemic isolation fix**: `_patch_fastapi_main` dual-key helper added to 5 files
  (see Gotcha 1).
- **B3 greenfield (8 modules, 144 tests)**: job_state, commons_rate_limiter, queue_util,
  queue_protocol, rate_limiter, repair_attempt_tracker, voice_persona_helpers → 100%;
  queue_extensions → 97% with 2 PENDING pragma proposals (see below).
- Full rest/ dir at handoff: **342 passed / 0 failed** (incl. Rio's coexisting auth tests).

## PENDING (manager-owned, not yet applied)
- **2 pragma proposals on `queue_extensions.py`** (double-check-locking idiom, unreachable
  single-threaded): line 47 (`if cls._instance is None:` inner, __new__) and line 72
  (`if not self._initialized:` inner, __init__) → `# pragma: no branch  # double-check-lock: inner check unreachable single-threaded`.
  Until Tiberius applies these, queue_extensions sits at 97% by exactly those 2 branches.

## YOUR scope (B5/B6/B7) — partition SIGNED OFF by Tiberius
**EXCLUDED — Rio ⚡ owns (do NOT author tests for these):** auth*, jwt_service,
password_service, refresh_token_service, email_service, email_token_service,
user_service, admin_service, auth_audit, auth_middleware, auth_models,
user_id_generator, queue_auth, routers/auth, routers/admin, and the AUTH
db/repositories (api_key, auth_audit_log, email_verification, failed_login,
password_reset, refresh_token, user_repository). Rio's test files already coexist
green in `src/cosa/tests/unit/rest/` — verify with `git status` before you start so
you don't collide.

**B5 — non-auth DB (you own the DB layer):**
`postgres_models.py`, `db/database.py`, `sqlite_database.py`, and the 4 NON-auth
repos `db/repositories/{base, notification_repository, prediction_log_repository, proxy_decision_repository}`.
DB-boundary-mock heavy. (Tiberius floated a possible 3rd author for B5 if it's too big.)

**B6 — watchers/daemons + queue engines:**
`commons_ack_watcher`, `commons_activity_watcher`, `commons_question_watcher`,
`commons_topic_watcher`, `dead_queue_watchdog`, `watchdogs`,
`test_suite_completion_watchdog`, `queue_consumer`, `running_fifo_queue`,
`todo_fifo_queue` (greenfield the untested parts), `job_persistence`,
`multimodal_munger`, `util_llm_client`. Clock/poll/threading boundary-mock.

**B7 — non-auth routers (~25, the big tail):**
bug_fix_expediter, claude_code_queue, commons, decision_proxy, deep_research
(+ _to_podcast, + _to_presentation), docs_files, io_files, _dir_listing,
_scope_registry, embeddings, jobs, mock_job, mode, multiplexer_config, pages,
peer, podcast_generator, presentation_generator, speakerphone, speech, stats,
swe_team, voice_persona.

**B8 (lowest priority):** deeper greenfield of the 6 PHASE-A-repaired routers +
their support (notification_fifo_queue, fifo_queue, todo_fifo_queue,
agentic_job_factory) to push from repair-coverage (~26-48%) to 100%.

**dependencies/config.py + queue_protocol → yours** (queue side; queue_protocol already done in B3).
**Junk to skip:** `dependencies/._config.py`, `routers/._system.py` (macOS artifacts — Tiberius gitignores).

## ⚠️ GOTCHA 1 — `import fastapi_app.main as m` defeats sys.modules patching
`import a.b as c` binds `c` via `getattr(sys.modules['a'], 'b')`, NOT
`sys.modules['a.b']`. So once the REAL `fastapi_app` package is cached by an
earlier test in the suite, `patch.dict('sys.modules', {'fastapi_app.main': Mock()})`
is **silently ignored** — the test passes in isolation but FAILS under full-suite
ordering (the dependency returns the real module). This bit 8 PHASE-A tests.
**Fix — patch BOTH the package and the submodule:**
```python
def _patch_fastapi_main( mock_main ):
    pkg = Mock(); pkg.main = mock_main
    return patch.dict( sys.modules, { "fastapi_app": pkg, "fastapi_app.main": mock_main } )
```
Every router/watcher/engine that does `import fastapi_app.main as main_module`
(get_*_queue, get_websocket_manager, the endpoints, the watchdogs) needs this.
The helper is already defined in test_system_router/queues_router/notifications_router/
websocket_router/websocket_admin_router — copy it into new test files.

## ⚠️ GOTCHA 2 — FastAPI `Query()`/`Depends()` defaults are FieldInfo on direct call
When you unit-test an endpoint by CALLING IT DIRECTLY (not through FastAPI), every
parameter whose default is `Query(...)`/`Depends(...)` arrives as the **FieldInfo
object**, not the wrapped value. FieldInfo is TRUTHY, so:
- `if response_requested:` → enters the wrong branch
- `if response_options:` → `json.loads(FieldInfo)` → TypeError
- `authorize_queue_filter(user, user_filter)` where user_filter defaulted → treated
  as a cross-user request → spurious 403 (this is the "403 trap" — NOT a real bug)
**Fix — pass EVERY such parameter explicitly** in the test call. For big endpoints
build a `_call_<endpoint>(self, **overrides)` helper that supplies a complete safe
kwarg set (see `_call_notify_user` in test_notifications_router.py). This will bite
the B7 router greenfield HARD — every router endpoint has Query/Depends params.

## Reusable patterns (proven this lane)
- **get_db skip-via-raise**: when a function wraps `with get_db() as s: ...` in
  try/except (non-fatal persistence), patch `get_db` with `side_effect=Exception(...)`
  → the except swallows it → DB path skipped, ZERO DB, no need to mock the session/repo.
  (Used in notifications notify_user.) When the DB result IS asserted, mock the repo:
  `patch('<mod>.get_db')` returning a `MagicMock()` CM + `patch('<mod>.RepoClass', return_value=mock_repo)`.
- **datetime/timestamp**: live rest/ code stamps `cu.get_current_datetime_iso()` (cosa.utils.util),
  NOT `datetime.now().isoformat()`. Patch `cosa.utils.util.get_current_datetime_iso`. The old
  `patch('...routers.X.datetime')` target is DEAD in most routers (caused the PHASE-A datetime cluster).
- **session_bridge**: `find_active_voice_persona_sessions` / `get_voice_persona` are imported
  LOCALLY inside functions → patch at source `lupin_cli.claude_code.hooks.lib.session_bridge.<fn>`.
- **config_mgr**: dict-backed stand-in honoring `default` + `return_type` + `silent` kwargs
  (see `_MockConfig` in test_voice_persona_helpers.py / test_rate_limiter.py).
- **threading/time**: patch `<mod>.time.monotonic` / `time.time` with `side_effect=[...]` to drive
  windows/clocks deterministically — never real sleeps.
- **singletons**: snapshot the class `_instance` / module global in setUp, restore in tearDown,
  reset to None to exercise the fresh-construction branch. Double-check-lock inner branches are
  unreachable single-threaded → pragma-propose (don't contort the test).
- **JobState enum**: members are `COMPLETED/FAILED/...` — NOT `DONE` (cost me a red; check job_state.py).
- **DbC docstrings** on every test class + `isolated_unit_test()` smoke-runner footer (campaign convention).

## Resume checklist
1. cosa venv; `git status src/cosa/tests/unit/rest/` → confirm Rio's auth test files; avoid them.
2. Pick a bucket (B5 / B6 / B7) — recommend B6 watchers next (moderate) or B5 if a DB specialist.
3. Copy `_patch_fastapi_main` into each new test file; pass ALL Query/Depends params explicitly.
4. Per-module: read live source → boundary-mock IO seams → genuine 100% L/B/F → verbatim disk cov.
5. Report each sub-batch to Tiberius → Clayton audits → Tiberius commits. You do NOT commit.
6. Pragma-PROPOSE only (manager applies); tripwire+flag any real prod bug (xfail-strict + pin, never pragma a bug).
7. ZERO API spend; never read ANTHROPIC_API_KEY_FIREWALLED; boundary-mock every LLM/SDK/web/subprocess seam.
