# Phase 5 — Smoke Test Audit (5.0d output)

**Author**: Tiberius 🌑 (session `225e5b2d`)
**Filed**: 2026-05-17
**Status**: ✅ AUDIT COMPLETE — both smoke tests carveout-compatible; no retrofit needed
**Parent design**: [`01-design.md`](01-design.md)
**Parent plan**: [`02-phase5-unit-tests-and-coverage-design.md`](02-phase5-unit-tests-and-coverage-design.md) §9
**Doc-viewer**: `/app/docs?path=lupin/src/rnd/v0.1.7/2026.05.16-model-server-carveout/91-phase5-smoke-audit.md`

---

## Files audited

| File | LOC | Status | Notes |
|---|---|---|---|
| `src/tests/smoke/test_embedding_api_smoke.py` | 110 | ✅ COMPATIBLE | HTTP path; already calls `:8000/api/embeddings/batch` via `requests`. The route internally delegates to `EmbeddingProvider`, which now HTTP-proxies to `:7998` when `LUPIN_MODEL_SERVER_URL` is set. No code change needed. |
| `src/tests/smoke/test_model_server_smoke.py` | 263 | ✅ DESIGNED FOR CARVEOUT | Top-of-file docstring explicitly cites "Phase 5.1 AC of the model-server carve-out." Tests `:7998` direct + the compute proxy path. Skip-on-unreachable for portability. Already shipped as part of Rio's Phase 5.1 close. |

No other speech / embedding / model-server smoke tests found under `src/tests/smoke/`.

---

## Findings

### `test_embedding_api_smoke.py` — no retrofit needed

The audit checklist from `02-phase5...md` §9:

1. **Does it instantiate the provider singleton?** No — calls the FastAPI route via HTTP. Provider singleton is server-side.
2. **Does it set `LUPIN_MODEL_SERVER_URL`?** No, but it doesn't need to — the env-var is set at compose-up on the server side, not in the test process.
3. **Does it require a live `:7998`?** Indirectly. The test hits `:8000` (route handler), which under the new carveout HTTP-proxies to `:7998`. If `:7998` is down, the route returns 5xx and the test fails — which is the *correct* behavior, not a regression.
4. **Does it pass from host context AND container context?** From host context: yes (default `LUPIN_TEST_BASE_URL=http://localhost:8000`). From container context: requires `LUPIN_TEST_BASE_URL` override (not commonly needed since these tests run on host).

**Net**: Same test, same assertion contract, same passing condition. The HTTP-proxy path is invisible to this smoke test by design.

### `test_model_server_smoke.py` — already shipped for this carveout

Top-of-docstring: "Phase 5.1 AC of the model-server carve-out." Tests cover:
- `GET /health` — 200 + 3 models loaded + VRAM > 0
- `POST /transcribe` — round-trip warmup MP3
- `POST /embeddings/generate` — 768-dim vector
- `POST /embeddings/batch` — N × 768 vectors
- `GET /admin/metrics` — Prometheus text format
- Auth rejection: missing / wrong-prefix / wrong-value `ck_live_*` → 401
- End-to-end via compute: `:7999/api/upload-and-transcribe-mp3` → HTTP-proxy → `:7998`

Skip-on-unreachable ensures portability across environments without `:7998` deployed yet.

**Net**: This file IS the Phase 5.1 acceptance smoke. Already green per Rio's session-end commit. No Phase 5 changes.

---

## What this audit does NOT cover

Out of scope per `02-phase5...md` §9:
- `src/tests/smoke/test_container_preflight.py` extension — scoped to Phase 6 per TODO L37-39 (model-server bind-mount + health-curl probe). Will be tackled in Phase 6, not here.
- Live smoke runs against `:8000` — those require server slot-ask per CLAUDE.md §TESTING VENUES; this audit is read-only against the source.

---

## Conclusions for Phase 5 implementation sequencing

| Sub-step | Pre-condition | Status |
|---|---|---|
| 5.0a inventory existing `test_embedding_provider.py` | Does it exist? | **DOES NOT EXIST** — will create from scratch in Phase 5.4 (`test_embedding_provider.py` NEW under `src/tests/unit/`) |
| 5.0b identify carveout changes in `routers/speech.py` | Where are the touchpoints? | **MAPPED** — imports at L32; `get_speech_provider` Depends at L120-135; route signatures at L226-227 + L654-655; provider.transcribe() call sites at L293-299 + L701-707; legacy `_run_whisper_with_retry` retained at L40-57 with deprecated docstring |
| 5.0c read `lupin_model_server/main.py` | Refine §7 test list? | **REFINED** — extensive `pragma: no cover` annotations narrow the coverage target to non-live surfaces: `_State` class, `_load_api_key_plaintext`, `require_api_key`, `_update_vram_gauge`, `/health` route, `_select_engine`, `/embeddings/info`, `/admin/metrics`, Pydantic models. The model-loading lifespan + `/transcribe` + `/embeddings/{generate,batch}` happy paths are intentionally pragma-skipped (require live GPU). Phase 5.3 test list updated below. |
| 5.0d smoke test audit | Compatible? | **YES** — no retrofit needed (this doc) |

---

## Refined Phase 5.3 — `test_lupin_model_server_main.py` test list

Per the `pragma: no cover` annotations, the actually-coverable unit-test surface:

1. `_State.__init__` — defaults set correctly
2. `_State.is_ready` — False when `models_loaded` length != 3
3. `_State.is_ready` — False when `load_errors` non-empty
4. `_State.is_ready` — True only when 3 loaded + no errors
5. `_load_api_key_plaintext` — returns stripped key when file present + non-empty
6. `_load_api_key_plaintext` — returns None on OSError (missing file)
7. `_load_api_key_plaintext` — returns None when file content is empty after strip
8. `require_api_key` — raises 503 when `_state.api_key_hash` is None
9. `require_api_key` — raises 401 when `x_api_key` is None
10. `require_api_key` — raises 401 when `x_api_key` is empty string
11. `require_api_key` — raises 401 on regex mismatch (wrong prefix / too short)
12. `require_api_key` — raises 401 on hash mismatch (valid format, wrong value)
13. `require_api_key` — returns key string on hash match
14. `_update_vram_gauge` — sets gauge from `torch.cuda.memory_allocated()` when CUDA available
15. `_update_vram_gauge` — sets gauge to 0 when CUDA unavailable (pragma'd path — verify still callable)
16. `EmbedRequest` — accepts content_type `"code"` and `"prose"`
17. `EmbedRequest` — rejects content_type outside the pattern
18. `EmbedRequest` — rejects empty text (min_length=1)
19. `EmbedBatchRequest` — content_type pattern validation
20. `/health` endpoint — returns 503 with full body when not ready (via TestClient + mocked `_state`)
21. `/health` endpoint — returns 200 with body when `is_ready()` (via TestClient + mocked `_state`)
22. `_select_engine` — returns code_engine for "code" content_type
23. `_select_engine` — returns prose_engine for "prose"
24. `_select_engine` — raises 503 when target engine is None
25. `/embeddings/info` — returns metadata with valid X-API-Key
26. `/embeddings/info` — returns 401 without X-API-Key (via require_api_key dep)
27. `/admin/metrics` — returns Prometheus text format with valid X-API-Key
28. `/admin/metrics` — returns 401 without X-API-Key

~28 test cases covering the non-pragma'd surfaces. The pragma-skipped live paths (`/transcribe`, `/embeddings/generate`, `/embeddings/batch`) are intentionally untested at unit tier; the live smoke `test_model_server_smoke.py` covers them on the running container.

---

## Idempotency marker

AUDIT-v1 — 2026-05-17 by Tiberius 🌑. No follow-up audit needed unless new smoke tests are added during the Phase 5 implementation window.
