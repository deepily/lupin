# 15 — B8-Tail Coverage Handoff (Mr. Radio 🦉, session 783ee1b0)

> **Purpose:** hand the B8-TAIL lane (the 2 biggest FastAPI routers —
> `routers/queues` + `routers/notifications` → genuine 100%) to a FRESH author.
> Authored 2026-06-01 by Mr. Radio 🦉 at an honest-stop point AFTER completing
> B8 clusters 1 + 2 (6 modules). Honest-stop per fresh-context-beats-near-ceiling
> doctrine: I'm at real depth after cluster-1 (5 modules) + the 1416-LoC
> todo_fifo_queue, and the 2 remaining are the largest in B8 (queues 1897 LoC,
> notifications 2326 LoC). Manager Tiberius 👑 accepted the stop.

## TL;DR — what's DONE, what remains

**DONE this session (do NOT redo) — all TEST-ONLY, zero prod edits:**

| Module | Disk cov | Tests | Notes |
|---|---|---|---|
| `cosa.rest.agentic_job_factory` | 122/0/72/0 = **100%** | 57 | new `test_agentic_job_factory.py` + existing heartbeat |
| `cosa.rest.fifo_queue` | 174/0/48/0 = **100%** | 50 | + PRAGMA-1 (applied) `delete_by_id_hash` dead else+except |
| `cosa.rest.notification_fifo_queue` | 161/0/46/0 = **100%** | 27 | new `_coverage.py` |
| `cosa.rest.routers.system` | 159/0/20/0 = **100%** | 27 | new `_coverage.py` |
| `cosa.rest.routers.websocket` | 245/0/54/0 = **100%** | 39 | + PRAGMA-2 (applied) not-a-dict dead branch |
| `cosa.rest.todo_fifo_queue` | 491/1/148/3 = **99%** | 81 | + PRAGMA-3/4/5 **PROPOSED** (awaiting Tiberius verify) |
| `cosa.rest.routers.websocket_admin` | 44/0/6/0 = **100%** | — | was already 100% pre-campaign; NOT re-touched |

Cluster-1 (first 5) → verified 100% by Tiberius, routed to reviewer Rachel.
Cluster-2 (todo_fifo_queue) → reported; 3 pragma proposals under Tiberius review.

**New test files added (all SUPPLEMENTAL — existing files left untouched):**
`test_agentic_job_factory.py`, `test_fifo_queue_coverage.py`,
`test_notification_fifo_queue_coverage.py`, `test_system_router_coverage.py`,
`test_websocket_router_coverage.py`, `test_todo_fifo_queue_coverage.py`.

**REMAINS = B8-TAIL (YOUR lane):**
- `src/cosa/rest/routers/queues.py` (519 stmts / 1897 LoC) — baseline **27%** (519/367/142/11). 19 endpoints. Existing test: `test_queues_router.py`.
- `src/cosa/rest/routers/notifications.py` (707 stmts / 2326 LoC) — baseline **26%** (707/515/184/16). 17 endpoints. Existing test: `test_notifications_router.py`.

**EXCLUDED — other authors own (DO NOT TOUCH):** all B7 routers (Rio idx6), the auth lane, multimodal_munger + running_fifo_queue (Cheech, DONE), decision_proxy/commons/speech + SDK-adjacent. `git status src/cosa/tests/unit/rest/` before starting; the `??` files (decision_proxy_router, jobs_router, peer_router, speakerphone_router, voice_persona_router) are Rio's — avoid them.

## ⚠️ KEY INTEL — queues + notifications have NO pre-existing pragmas

I grepped both files: **`grep -nE "pragma|c8 ignore" routers/queues.py routers/notifications.py` → ZERO hits.** So Tiberius's "likely carry AC12 route pragmas" assumption does NOT hold for these two. You cover them **fully via unit tests** — exactly like I did system/websocket (which also had none). The AC12 verification-bar protocol (below) only fires IF you discover an existing pragma; you won't here, so no integration-test citation is needed. NEW author-added pragmas (if you find genuinely-unreachable defensive branches) stay unreachable-only with read-the-contract-source proof, proposed to Tiberius.

## INTERPRETER (non-negotiable — lupin .venv py3.13 SILENTLY MASKS failures)
```bash
PYTHONPATH=src:src/cosa/tests/unit/infrastructure src/cosa/.venv/bin/python -m pytest \
  <test files> --cov=<dotted.module> --cov-branch --cov-report=term-missing -p no:cacheprovider -q
```
cosa venv = py3.11. You do NOT commit — report verbatim per-module disk cov to
`dm-tiberius` at each cluster boundary → he re-measures → reviewer audits → he commits.

## ⚠️ THE TWO GOTCHAS (they bite EVERY B8 router)
**G1 — `_patch_fastapi_main` DUAL-KEY sys.modules.** Patch BOTH `sys.modules["fastapi_app"]` (a Mock WITH a `.main` attr) AND `sys.modules["fastapi_app.main"]`, because `import fastapi_app.main as m` binds via `getattr(sys.modules['fastapi_app'],'main')`, NOT the submodule key. Single-key patches pass in isolation but FAIL under full-suite ordering. The helper already exists copy-paste-ready in `test_system_router.py` / `test_websocket_router.py` / `test_queues_router.py` / `test_notifications_router.py`.

**G2 — FastAPI `Query()`/`Depends()`/`Header()` defaults are FieldInfo on DIRECT call.** When you unit-test an endpoint by calling it directly, every param defaulting to `Query(...)`/`Depends(...)`/`Header(None)` arrives as a truthy FieldInfo object → `if response_requested:` takes the WRONG branch; `authorize_queue_filter(...)` reads it as cross-user → spurious 403 (the "403 trap" — NOT a real bug). FIX: pass EVERY such param explicitly. Build a `_call_<endpoint>(self, **overrides)` helper with a complete safe kwarg set (see `_call_notify_user` in `test_notifications_router.py`).

## PATTERNS THAT WORKED THIS SESSION (reuse — they're fast)
1. **Supplemental `_coverage.py` file per module** (existing test file untouched). Lower risk; both files run together for measurement. When reporting a cluster, **NAME the exact bundled files** (existing + your new one) so Tiberius's first re-measure matches yours — he explicitly asked for this; saves a round-trip. (Measuring your NEW file ALONE under-reports, because the existing file carries part of the coverage.)
2. **setUp patcher-list harness** holding ALL heavy-constructor patches open across the test (the `self._patchers` list + `patch.object(mod, name).start()`; tearDown stops in reverse). Essential when the constructor instantiates heavy collaborators (e.g. todo_fifo_queue's 7 deps: LlmClientFactory/Gister/GistNormalizer/Normalizer/QueryLogTable/EmbeddingManager/get_embedding_provider).
3. **Async endpoints → `unittest.IsolatedAsyncioTestCase`** with `async def test_...`. For WebSocket-style message loops, drive with an `AsyncMock` websocket whose `receive_text`/`receive_json.side_effect = [msg1, msg2, WebSocketDisconnect()]` — exception instances in a side_effect list are raised. Make `send_json.side_effect` raise to reach outer defensive handlers.
4. **Patch the function symbol at the SUT module, not the source**, when the SUT does `from X import f` at call-time → patch `cosa.rest.<sutmodule>.f`. But for functions imported INSIDE the method body (`from cosa.rest.auth import verify_token`), patch at the ORIGIN `cosa.rest.auth.verify_token`. (Pre-existing websocket tests patched `verify_firebase_token` — the WRONG symbol — so the happy auth path was never covered; the live code uses `verify_token`. Watch for this kind of stale mock target.)
5. **Pydantic request models validate** — e.g. `AsyncNotificationRequest.job_id` has a strict hash-pattern regex (`prefix-8hex` or 64-hex); fake job ids like `"j1"` get rejected and swallowed by the SUT's try/except → your assertion silently fails. Use valid hashes (`"dr-a1b2c3d4"`). Notifications router will have similar models — READ the request-model class before hand-rolling a body.
6. **Mock auto-vivification trap:** `Mock().artifacts` returns a truthy Mock, not absent → `getattr(job,"artifacts",None) or {}` keeps the Mock → downstream `.get(...)` returns a Mock that fails pydantic. Default such attrs to real values (`job.artifacts = {}`) in your job-factory helper.
7. **Unreachable-defensive pragma classes** (ratified pattern — PROPOSE to Tiberius with a read-the-contract proof, never self-apply):
   - **dead else/except past a presence-guard** (fifo_queue `delete_by_id_hash`: `if id_hash not in dict: return False` guarantees `del` succeeds → size always drops → else+except dead).
   - **branch gated dead by a preceding unconditional call** (websocket L388 not-a-dict: L363's unconditional `auth_message.get('type')` AttributeErrors any non-dict into the parse-except before the isinstance check).
   - **mirror-condition dead arm** (todo L403: rejection-reason if/elif mirrors `_is_fit`'s 3 conditions → the elif-false default is dead).
   - **always-True flag** (todo L623: every non-return path sets `needs_llm_routing=True`).
   - **always-falsy var** (todo L717: automatic-command only arrives in system mode ⇒ `clear_user_mode` returns None ⇒ `if previous_mode` True-arm dead).

## AC12 PRAGMA + VERIFICATION-BAR PROTOCOL (only if you find a PRE-EXISTING pragma)
Pre-existing AC12 route-handler `# pragma: no cover` GRANDFATHER (they implement the ratified D1 HYBRID — REST credited to the server/integration suites) — BUT only after the VERIFICATION BAR: in your cluster report, for EACH pre-existing pragma'd endpoint, NAME the integration/smoke/e2e test(s) that actually exercise it (cite the TEST, not the docstring) so Tiberius confirms covered-elsewhere, not a hole. **(N/A for queues+notifications — neither has any pragma. Documented here only for completeness.)**

## PROTOCOL RECAP
- TEST-ONLY. Prod BUG → do NOT pragma: tripwire (`@pytest.mark.xfail(strict=True)` on the correct contract + pin test on current behavior) + DM Tiberius.
- ZERO GPU/DB/net/LLM: boundary-mock get_db, providers, clients, `*Response`, websocket_mgr, `notify_user_*`, `emit_*`. NEVER read `ANTHROPIC_API_KEY_FIREWALLED`.
- `commons_send_to` `in_reply_to` is a TOP-LEVEL param, never inside `metadata=`.
- Convention: DbC docstrings on test classes + `isolated_unit_test()` footer.
- `quick_smoke_test` / `if __name__=="__main__"` blocks are coverage-EXCLUDED (`[tool.coverage] exclude_also`) — do NOT test them.

## Resume checklist
1. cosa venv; `git status src/cosa/tests/unit/rest/` → note B7/auth `??` files, avoid them.
2. Measure each router's CURRENT cov FIRST (run its existing `test_<x>_router.py` with `--cov`) to see exact missing lines — the routers already have partial tests; you're CLOSING the gap.
3. Copy `_patch_fastapi_main` (G1 dual-key) into a new `test_<x>_router_coverage.py`; build `_call_<endpoint>` helpers (G2 FieldInfo trap).
4. Cover all reachable handler logic via unit tests (no AC12 citation needed — no pre-existing pragmas). READ each Pydantic request-model class before building bodies.
5. Per module: verbatim disk cov + NAMED bundled file set to `dm-tiberius` → he re-measures → reviewer audits → he commits. Propose any new pragma with read-the-contract proof.
6. Honest-stop when context deepens; clean green line + handoff memento.
