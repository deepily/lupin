# 13 — Rio ⚡ → B7 Author: REMAINING non-auth routers (commons, speech, SDK set) Handoff

> **Purpose:** seed a FRESH author to finish the B7 non-auth-router lane at genuine
> 100% L/B/F, with zero rediscovery. Written 2026-06-01 by Rio ⚡ (idx6, session
> cacf3a99) at an honest-stop after 15 B7 modules (clusters 1–4, all genuine
> 100%-of-reachable). Manager = Tiberius 👑. You do NOT commit.
>
> **READ FIRST:** this file, then **`11-rest-greenfield-b5-b7-handoff.md` (Tiffany)**
> §Gotcha 1 (`_patch_fastapi_main` dual-key) + §Gotcha 2 (FieldInfo 403-trap) + the 8
> patterns, AND **`12-rio-rest-auth-c4-handoff.md`** (router-test recipes). Then skim
> any 2-3 of my 15 test files below for the proven idiom before writing.

---

## TL;DR — lane state

**DONE (mine, 15 B7 modules @ genuine 100%-of-reachable, banked-pending Clayton/Rachel):**

| cluster | modules (verbatim final cov) |
|---|---|
| C1 | multiplexer_config 11/0·0/0 · pages 59/0·0/0 · _dir_listing 44/0·24/0 · embeddings 39/0·2/0 · stats 68/0·26/0 |
| C2 | _scope_registry 93/0·54/0 · mode 56/0·4/0 · io_files 74/0·28/0 · docs_files 90/1·32/1 (PRAGMA) · mock_job 104/0·32/0 |
| C3 | jobs 24/0·4/0 · peer 201/0·40/0 · speakerphone 66/0·20/1 (PRAGMA) · voice_persona 155/0·58/1 (PRAGMA) |
| C4 | decision_proxy 158/0·24/0 |

Test files at `src/cosa/tests/unit/rest/`: `test_{multiplexer_config,pages,dir_listing,
embeddings,stats,scope_registry,mode,io_files,docs_files,mock_job,speakerphone,jobs,
peer,voice_persona,decision_proxy}_router.py` (+ `test_dir_listing.py`, `test_scope_registry.py`
have no `_router` suffix). All 15 run green together: **249 passed**, zero cross-interference.
Zero prod bugs found. Zero API spend.

**3 PRAGMA PROPOSALS pending Tiberius's ruling (NOT applied by me — propose-only):**
1. `docs_files.py:218-219` — `if not project_name:` guard. UNREACHABLE: `decoded_path =
   unquote(path).lstrip("/")` + the non-empty + contains-"/" guards above guarantee a
   non-empty pre-slash segment. Propose `# pragma: no cover  # unreachable: lstrip('/')
   guarantees non-empty project segment`.
2. `speakerphone.py:254` — `if not ok:` (solo self-write, last stmt of `async with
   _speakerphone_lock`). Branch `254->270` is the **async-with `__aexit__` trailing-if
   arc artifact** (ratified class, memento §Pragma discipline). Both ok-arms tested
   (success+500). Propose `# pragma: no branch  # async-with __aexit__ trailing-if arc`.
3. `voice_persona.py:278` — same artifact (requested-path self-write before `async with`
   exit). Branch `278->346`. Both ok-arms tested. Propose `# pragma: no branch  # async-with
   __aexit__ trailing-if arc`.

**YOUR LANE — the 3 remaining buckets:**
- **commons.py** (1321 L) — biggest. plain pytest-cov.
- **speech.py** (1312 L) — biggest. plain pytest-cov. ⚠️ likely ElevenLabs/TTS + streaming;
  boundary-mock every audio/network seam, NEVER read a real API key.
- **SDK-adjacent set → `src/cosa/tests/run-sdk-cov.sh`** (NOT plain pytest-cov): `bug_fix_expediter`
  (130), `claude_code_queue` (315), `deep_research` (340), `deep_research_to_podcast` (236),
  `deep_research_to_presentation` (242), `podcast_generator` (797), `presentation_generator`
  (284), `swe_team` (179). These import `claude_agent_sdk`/`mcp.types`/scipy → the cov tracer
  KeyErrors under plain pytest-cov; run-sdk-cov.sh pre-warms the caches (memento §interpreter).

**EXCLUDE (not yours):** auth routers (done — Mr. Radio), Tiffany's repaired routers
(system/websocket/websocket_admin/queues/notifications = B8) + DB/postgres_models/base.py
(Tiffany's), B6 watchers/engines (Tiffany's), `routers/test_suite.py` +
`test_suite_completion_watchdog.py` (Cheech / Tiffany — see 10-handoff).

## Canonical interpreter (NON-NEGOTIABLE)
```
# non-SDK (commons, speech):
PYTHONPATH=src:src/cosa/tests/unit/infrastructure src/cosa/.venv/bin/python -m pytest \
  src/cosa/tests/unit/rest/<test> --cov=cosa.rest.routers.<mod> --cov-branch \
  --cov-report=term-missing -p no:cacheprovider -q
# SDK-adjacent (deep_research/podcast/presentation/swe_team/bfe/claude_code_queue):
src/cosa/tests/run-sdk-cov.sh   # pre-warms claude_agent_sdk + scipy caches
```
cosa venv (py3.11 / pytest 9.0.2). The lupin .venv (py3.13/pytest 8.4.2) silently MASKS reds.

---

## Reusable recipes I PROVED across all 15 (steal these verbatim)

1. **Dependency that does `import fastapi_app.main as m`** → copy `_patch_fastapi_main(mock_main)`
   (dual-key: patch BOTH `fastapi_app` pkg AND `fastapi_app.main`). One test per such dep.
   Used in: stats, mode, mock_job, speakerphone, jobs, voice_persona, decision_proxy(get_run_queue/get_config_mgr).
2. **Async endpoints** → `unittest.IsolatedAsyncioTestCase` (preferred for await-heavy modules)
   OR `asyncio.run(endpoint(...))` for simple ones. Pass EVERY `Depends`/`Query`/`Header`/`Body`
   param EXPLICITLY on the direct call (FieldInfo 403-trap — Gotcha 2). I bypassed auth by
   passing `current_user=`/`authenticated_user_id=` directly — never went through the gate.
3. **JSONResponse body assert** → `json.loads(bytes(resp.body).decode())` (see `_json()` helper
   in test_speakerphone/voice_persona/peer). Endpoints return Starlette responses, not dicts.
4. **`with get_db() as session:`** → `patch("<mod>.get_db", return_value=_db_cm(session))` where
   `_db_cm` is a MagicMock CM (`__enter__`→session). Patch the repo CLASS
   `patch("<mod>.ProxyDecisionRepository", return_value=mock_repo)`. See test_decision_proxy.
5. **aiohttp / httpx async sessions** → `_FakeResp`/`_FakeSessionCM` async-CM classes
   (`__aenter__`/`__aexit__`). For `session.post(...)` returning a CM, use
   `MagicMock(return_value=_FakeResp(...))`; for sequences (401-retry) `side_effect=[...]`;
   to raise (timeout) `side_effect=asyncio.TimeoutError`. See test_peer / test_voice_persona(sample).
6. **Awaitable Task stand-in** (for `task.cancel(); await task`) → `_FakeTask` with a generator
   `__await__`; `_RaisingTask` subclass to cover the `except (CancelledError, Exception): pass`
   arms. See test_peer.
7. **Background while-loop (poll→sleep→exit)** → patch `<mod>.asyncio.sleep` with `AsyncMock()`
   (no real sleep); drive exit via fetch `side_effect` list (drain) or `sleep` side_effect
   `asyncio.CancelledError` (cancellation arm). See test_peer `_watcher_loop`.
8. **`async def` patched as a coroutine factory passed to `create_task`** → patch the async fn
   with **`new=MagicMock(return_value="CORO")`** (force SYNC mock), NOT bare `patch(...)` — else
   `patch` auto-makes an AsyncMock and `create_task` gets an un-awaited coroutine → RuntimeWarning.
   (Bit me once in test_peer; fixed.)
9. **Module-global state** (`_proxy_batch_state`, `_peer_jwt_cache`, `_active_watchers`,
   `_watcher_state`, docs_files `_SCOPE_REGISTRY`) → snapshot in setUp, restore/clear in
   tearDown via `self.addCleanup`. Prevents cross-test leakage.
10. **`config_mgr.get(key, default, return_type, silent)`** → `MagicMock` whose `.get.side_effect
    = lambda key, default=None, **kw: default` (or a per-key dict). Patch `<mod>.MODE_METADATA`,
    `<mod>._is_secrets_path`, etc. directly when a helper's output must be controlled.
11. **Pydantic guard that duplicates an endpoint guard** (e.g. `update_trust_mode`'s
    `if mode not in VALID` mirrors the model's `pattern=`) → reach the endpoint guard via
    `Model.model_construct(mode="bogus", ...)` (bypasses validation) — covers it genuinely, no pragma.
12. **`quick_smoke_test` / `if __name__` blocks** are coverage-EXCLUDED (pyproject `exclude_also`).
    Don't test them. Footer convention: an `isolated_unit_test()` runner + `if __name__` (also excluded).

## Discipline (charter — unchanged)
Genuine 100% L/B/F per module; verbatim disk cov in every report. Boundary-mock ALL IO
(DB/JWT/crypto/aiohttp/httpx/ElevenLabs/SDK/subprocess) → ZERO real DB/net/GPU/LLM, ZERO API
spend, NEVER read `ANTHROPIC_API_KEY_FIREWALLED` or `eleven11` real key. Pragma PROPOSE-only
(manager applies). Tripwire any real prod bug (xfail-strict + pin, NEVER pragma a bug-blocked
line) + flag Tiberius. Cluster-paced reporting to dm-tiberius (he polls; ping explicitly only
for bug/ruling/cluster-complete). You do NOT commit (manager does, on Clayton/Rachel APPROVE).

## Resume checklist
1. cosa venv; `git status src/cosa/tests/unit/rest/` → my 15 test files exist; DON'T touch them.
2. Start with the SDK-adjacent SMALL leaves via run-sdk-cov.sh (bug_fix_expediter 130, swe_team
   179) to warm up on the SDK harness, OR commons/speech if you prefer non-SDK-first.
3. Per module: read live source → boundary-mock seams → 100% → verbatim disk cov → report to Tiberius.
4. Watch for more `async with`-lock trailing-if `__aexit__` artifacts (commons/speech may have
   locks) → propose `# pragma: no branch`, don't contort the test.
5. Clayton 😎 / Rachel 🕊️ audit → Tiberius commits on APPROVE.
