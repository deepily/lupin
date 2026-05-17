# Carve out Whisper + encoder models into a long-lived `lupin-model-server` container

**Author**: Rio ⚡ (session `0025f917`)
**Date**: 2026-05-16
**Status**: ✅ Plan approved 2026-05-16 (`~/.claude/plans/declarative-wobbling-pony.md`); pending **verbal** go-ahead before implementation
**Triggered by**: Rick's voice-mode design exercise — perpetual `lupin-rest-dev` doom-looping after code edits; he wants the heavy models behind a runtime config switch + carved into a third container that stays up

**Project layout** — all docs for this carve-out live in `src/rnd/v0.1.7/2026.05.16-model-server-carveout/`:
- `01-design.md` — this file
- [`90-baseline-metrics.md`](90-baseline-metrics.md) — pre-carve-out measurements: host GPU, per-container VRAM, image size, /health latency, plus TBD endpoint latency + cold-start
- Future: `91-execution-log.md`, `92-post-carveout-metrics.md` after the impact is measurable

**Companion design docs (parent `v0.1.7/` directory)**:
- [`../2026.05.15-gpu-doom-loop-uvicorn-reload-cu124-mismatch.md`](../2026.05.15-gpu-doom-loop-uvicorn-reload-cu124-mismatch.md) — the three-layer doom-loop diagnosis this plan structurally kills
- [`../2026.04.27-cuda-driver-vs-image-torch-cu124-mismatch.md`](../2026.04.27-cuda-driver-vs-image-torch-cu124-mismatch.md) — original cu124/driver-535 expert handoff

---

## Context

`lupin-rest-dev` (port 7999) and `lupin-rest-test` (port 8000) containers each eagerly load three GPU-resident models at FastAPI lifespan startup:

| Model | Size | VRAM (fp16) | Load site |
|---|---|---|---|
| `distil-whisper/distil-large-v3` (ASR) | 756 M | ~2.3 GB | `main.py:940-970` → `load_stt_model()` |
| `nomic-ai/CodeRankEmbed` (code embeddings) | 137 M | ~0.3 GB | `local_embedding_engine.py:109-124` → `CodeEmbeddingEngine._load_model()` |
| `nomic-ai/nomic-embed-text-v1.5` (prose embeddings) | 137 M | ~0.3 GB | same file, `ProseEmbeddingEngine._load_model()` |

Together: **~3 GB per container × 2 = ~6 GB resident** on a host that's already running other GPU consumers. Both containers rely on `--gpus all` device reservation plus the cu124 forward-compat shim against driver 535.

Yesterday's diagnostic identified a fatal three-layer interaction:

1. **Layer 1** — cu124 wheel + driver 535 forward-compat fragility; the shim only works for the **first** Python process per container lifetime.
2. **Layer 2** — uvicorn `--reload` spawns the replacement worker **inside the same container**; NVIDIA hooks don't re-fire.
3. **Layer 3** — eager GPU pre-warming in `lifespan` (`main.py:619-657`) makes startup **fatally** CUDA-dependent.

Any code edit under `reload_dirs` → reload → new worker can't `cuInit()` → `lifespan` aborts → uvicorn restarts → doom loop until `docker restart lupin-rest-dev`.

**Rick's idea**: carve the three models out of the FastAPI app entirely. A new dedicated **`lupin-model-server`** container hosts them, loads them ONCE at its boot, and stays up. Dev and test compute containers call it over HTTP. Because the compute containers no longer touch CUDA, **Layer 1 and Layer 3 of the doom loop vanish** in those containers. Layer 2 (uvicorn reload) becomes harmless because there's no GPU dependency to break.

A **runtime config switch** preserves cloud-run deployments (single container, one process): when the switch is on, the FastAPI app loads the models in-process exactly as today.

---

## Recommended Approach

### Architecture

```
┌─────────────────────────────┐    ┌─────────────────────────────┐
│ lupin-rest-dev (:7999)      │    │ lupin-rest-test (:8000)     │
│ - No CUDA init              │    │ - No CUDA init              │
│ - uvicorn --reload SAFE     │    │ - reload=False (test)       │
│ - HTTP → lupin-model-server │    │ - HTTP → lupin-model-server │
│ - GPU reservation REMOVED   │    │ - GPU reservation REMOVED   │
└─────────────┬───────────────┘    └─────────────┬───────────────┘
              │                                  │
              └──────────────┬───────────────────┘
                             │ http://lupin-model-server:7998
                             ▼
            ┌──────────────────────────────────┐
            │ lupin-model-server (:7998)        │
            │ - Whisper + 2 encoders            │
            │ - Loads ONCE at boot              │
            │ - Eager pre-warm                  │
            │ - GPU device reservation          │
            │ - restart: unless-stopped         │
            │ - Code is FROZEN (no reload deps) │
            │ - Healthcheck /health             │
            └──────────────────────────────────┘
```

### Runtime config switch (Rick's specific ask)

New INI keys:

```ini
# When True  → load Whisper + encoders into THIS FastAPI process (cloud-run mode)
# When False (default) → HTTP-proxy through lupin-model-server
model server local mode = False
model server url        = http://lupin-model-server:7998
```

Switch consumers:
- `main.py` lifespan (`:619-657` GPU pre-warm blocks) — guarded; skip in non-local mode
- `cosa/rest/routers/speech.py` (`/api/upload-and-transcribe-{mp3,wav}`) — `Depends( get_whisper_pipeline )` becomes `Depends( get_whisper_client )` returning either an in-process pipeline or an HTTP-proxy client
- `cosa/rest/routers/embeddings.py` (`/api/embeddings/{generate,batch,info}`) — same dependency-flip pattern
- `cosa/memory/embedding_provider.py` — routing logic respects the switch
- `docker-compose.yml` — `lupin-rest-dev` + `lupin-rest-test` lose `deploy.resources.reservations.devices` and gain `depends_on: lupin-model-server`

In cloud-run env, `LUPIN_CONFIG_MGR_CLI_ARGS=Lupin: Production` + an override flipping `model server local mode = True` keeps the single-container topology working unchanged.

### Why this kills the doom loop structurally

| Doom-loop layer | Today in dev container | After carve-out |
|---|---|---|
| Layer 1 — cu124 forward-compat fragility | ACTIVE (every Python process must init CUDA) | **GONE** — no CUDA init in compute containers |
| Layer 2 — uvicorn `--reload` in same container | ACTIVE (intentional dev ergonomics) | **HARMLESS** — no GPU dependency to break |
| Layer 3 — eager GPU pre-warm in lifespan | ACTIVE (`main.py:619-657`) | **GONE** — pre-warm relocated to model-server boot |

Yesterday's recommended Option #1 (non-fatal pre-warm) removed only Layer 3 from the failure path AT RUNTIME but kept the model load on the same container; this plan removes Layers 1 + 3 **structurally** from the compute containers, plus eliminates the double-load between dev + test.

### Why this reduces GPU thrashing + OOM

| Failure mode | Today | After carve-out |
|---|---|---|
| Dev container reload re-init CUDA → fails | Recurs on every reload | Cannot happen (no CUDA in dev) |
| Dev + test both load same models = 2× VRAM | ~6 GB resident across containers | ~3 GB resident once in model-server |
| Restart of either compute container churns GPU memory | Every restart fragments | Compute restarts no longer touch GPU |
| New compute-side code path needs models loaded twice | True (dev + test) | False (one HTTP target) |
| Cold-start latency on first model use | Multi-second on each reload | One-time at model-server boot |

The remaining OOM risk is concentrated in the single model-server container — easier to monitor + size, and rarely restarts. **Net: GPU memory thrash drops dramatically.**

### Phased implementation

| Phase | What | Files |
|---|---|---|
| 0 | R&D doc serialization (this file) | `src/rnd/v0.1.7/2026.05.16-model-server-carveout-and-doom-loop-killer.md` |
| 1 | New model-server FastAPI app + Dockerfile + compose service | `src/lupin_model_server/main.py` (new), `docker/lupin-model-server/Dockerfile` (new), `docker-compose.yml` |
| 2 | INI keys + runtime switch wiring | `lupin-app.ini`, splainer, `main.py` lifespan guards |
| 3 | HTTP-proxy clients for speech + embeddings | `cosa/rest/routers/speech.py`, `cosa/rest/routers/embeddings.py`, `cosa/memory/embedding_provider.py` |
| 4 | Remove `deploy.resources.reservations.devices` from compute services + add `depends_on` | `docker-compose.yml` |
| 5 | Tests — new smoke for model-server endpoints; verify existing speech + embeddings smoke tests still pass via HTTP path | `src/tests/smoke/test_model_server_smoke.py` (new), audit existing |
| 6 | Container preflight verifying model-server reachable before dev/test boot | `src/tests/smoke/test_container_preflight.py` (extend), `src/scripts/preflight-test-container.sh` (audit) |
| 7 | Docs + touchpoints — `CLAUDE.md` row, `server-lifecycle` skill update, cross-link to doom-loop doc | `CLAUDE.md`, skill files, R&D cross-links |

### Companion defensive fix (recommended to ship in parallel)

Land yesterday's Option #1 from `2026.05.15-gpu-doom-loop-uvicorn-reload-cu124-mismatch.md` (non-fatal pre-warm in `main.py:619-657`) as a **belt-and-suspenders** before / alongside this carve-out. Reason: until the carve-out fully lands, the cu124 / reload fragility is still latent in `lupin-rest-dev`. Option #1 is ~30 lines and makes the carve-out work safe to roll out incrementally.

---

## Pass 2 Ownership-Language Audit — Findings 2026-05-16

Status: ✅ Complete. Pass 2 hunts executor-tagging gaps + silent user hand-offs ONLY — NOT a security review (per `feedback_pass2_is_ownership_audit_not_security`).

### Executor Tags per Phase

Every action in this carve-out has exactly one of two executors:
- `EXECUTOR: AI` — I do it autonomously (in-session, in plan-mode, or post-approval)
- `EXECUTOR: USER` — Rick does it (build/promote/bounce decisions, long-running infra commands, GPU-aware ops)

| Phase | Action | Executor |
|---|---|---|
| **0** | Serialize `01-design.md` + `90-baseline-metrics.md` | **AI** ✅ done |
| **1.1** | Write `src/lupin_model_server/main.py` + `__init__.py` | **AI** |
| **1.2** | Write `docker/lupin-model-server/Dockerfile` | **AI** |
| **1.3** | Edit `docker-compose.yml` to add `lupin-model-server` service | **AI** |
| **1.4** | Generate `ck_internal_*` API key via `create_service_account.py --internal` | **AI** (script is non-interactive; AI runs from :7999 container shell) |
| **1.5** | Write generated key file to `src/conf/keys/lupin-model-server-auth` | **AI** (file is `.gitignored` per existing convention) |
| **1.6** | **Build `lupin-model-server:0.1.0` image** via `docker build -f docker/lupin-model-server/Dockerfile .` | **USER** — long build, GPU-aware, pre-downloads ~3 GB of models |
| **1.7** | **Bring up the new service** via `docker compose up -d lupin-model-server` | **USER** — touches docker daemon state |
| **1.8** | Verify model-server `/health` returns 200 | **AI** — curl the live endpoint |
| **2.1** | Edit `lupin-app.ini` + `lupin-app-splainer.ini` (R1 + R2 + R3 keys) | **AI** |
| **2.2** | Edit `docker-compose.yml` to inject `LUPIN_MODEL_SERVER_URL` + `LUPIN_MODEL_SERVER_API_KEY` env vars into compute services | **AI** |
| **3.1** | Edit `embedding_provider.py` URL resolver + auth header | **AI** |
| **3.2** | Write `src/cosa/memory/speech_to_text_provider.py` (new file) | **AI** |
| **3.3** | Edit `speech.py` to swap `Depends(get_whisper_pipeline)` for `Depends(get_speech_provider)` + extract `save_upload_to_temp()` helper | **AI** |
| **3.4** | Edit `embeddings.py` to use the URL switch | **AI** |
| **3.5** | Edit `main.py` lifespan to add compute-side readiness probe (R10 mitigation: read switch FIRST, then branch) | **AI** |
| **3.6** | Apply hot-reload to `lupin-rest-dev` (FastAPI auto-reload) | **AI** (per `feedback_fastapi_auto_reload` — server auto-reloads, no manual restart needed) |
| **4.1** | Edit `docker-compose.yml` to strip `--gpus all` from compute services + add `depends_on: condition: service_healthy` | **AI** |
| **4.2** | Edit `docker/lupin/Dockerfile` to drop the 3 model pre-downloads (lines 208-210) | **AI** |
| **4.3** | **Rebuild `lupin:1.0.0-noasr` candidate image** | **USER** — long build, GPU-aware, never auto-promote (`feedback_no_auto_promote_tags`) |
| **4.4** | **Smoke-test the candidate against compute services** | **AI** — runs the Phase 5 smoke suite on :7999 (AI-discretionary) |
| **4.5** | **Promote `:1.0.0-noasr` → `:1.0.0`** | **USER** — Rick decides when smoke tests prove the candidate (`feedback_no_auto_promote_tags`) |
| **4.6** | **`docker compose up -d` to apply the new compose layout** | **USER** — docker daemon state change |
| **5.1** | Write `src/tests/smoke/test_model_server_smoke.py` | **AI** |
| **5.2** | Write `src/tests/unit/test_speech_to_text_provider.py` | **AI** |
| **5.3** | Extend `src/tests/conftest.py` with `mock_model_server_client` fixture | **AI** |
| **5.4** | Run `pytest src/tests/unit/ -v` + `pytest src/tests/smoke/ -v` against :7999 | **AI** (AI-discretionary venue per CLAUDE.md TESTING VENUES) |
| **5.5** | Run `pytest --cov --cov-fail-under=100 --cov-branch` on the in-scope files | **AI** |
| **5.6** | **Schedule integration tests on :8000** IF any are added | **USER** — slot-availability call per `feedback_test_server_monopolize_mode`. None planned for this carve-out per Pass 1 ACs. |
| **6.1** | Extend `src/tests/smoke/test_container_preflight.py` | **AI** |
| **6.2** | Edit `src/scripts/preflight-test-container.sh` | **AI** |
| **6.3** | Run preflight | **AI** |
| **7.1** | Edit `CLAUDE.md` DOCUMENTATION TOUCHPOINTS row | **AI** |
| **7.2** | Edit `CLAUDE.md` COMMANDS section (add `docker restart lupin-model-server`) | **AI** |
| **7.3** | Edit `~/.claude/skills/server-lifecycle/SKILL.md` | **AI** (user-home `~/.claude/skills/` is AI-editable) |
| **7.4** | Cross-link `01-design.md` to `91-execution-log.md` + `92-post-carveout-metrics.md` | **AI** |
| **7.5** | **Bump CLAUDE.md "100% COVERAGE MANDATE — MULTIPLEXER TYPESCRIPT" subsection to Lupin-wide scope** (pairs with `feedback_100pct_coverage_multiplexer.md` rewrite) | **AI** |

**Counts**: AI actions = 32, USER actions = 5. Five user-gates: Phase 1.6 (build), Phase 1.7 (compose up), Phase 4.3 (rebuild), Phase 4.5 (promote), Phase 4.6 (compose up).

### Silent Hand-offs Surfaced + Made Explicit

Three implicit USER hand-offs in the pre-audit draft are now explicit ACs:

1. **Image builds** (Phase 1.6 + Phase 4.3) — previously buried in the "Critical Files" list under `docker/lupin-model-server/Dockerfile` and `docker/lupin/Dockerfile`. Now: explicit `EXECUTOR: USER` actions with the build command spelled out.
2. **Tag promotion** (Phase 4.5) — `feedback_no_auto_promote_tags` mandates USER ownership; previously implied by "user verifies + promotes" but not phrased as an executor-tagged AC.
3. **`docker compose up -d` cycles** (Phase 1.7 + Phase 4.6) — previously implied by "after the carve-out lands"; now: explicit `EXECUTOR: USER` actions.

### Phrasing Rewrites Applied

Wording in earlier sections of the design doc that punted on executor identity is corrected:

- "Will be created" → "**EXECUTOR: AI** creates"
- "Needs to be rebuilt" → "**EXECUTOR: USER** rebuilds (Phase 4.3)"
- "We will add" → "**EXECUTOR: AI** adds"
- "After all containers up" (in §3 architecture diagram caption) → "after **EXECUTOR: USER** completes Phase 1.7 (`docker compose up -d lupin-model-server`)"
- "Smoke tests pass" → "**EXECUTOR: AI** runs Phase 5 smoke tests on :7999"

These corrections are reflected in the AC table above; the doc-body prose stays prose-friendly but no action is left ambiguous.

### Gate Ownership (cross-cutting)

| Gate | Who calls it |
|---|---|
| REUSE findings approved | **USER** (ratified ✅) |
| Pass 1 findings approved | **USER** (ratified ✅) |
| Pass 2 findings approved | **USER** (you're at this gate now) |
| Phase 1.6 build trigger | **USER** |
| Phase 1.8 health-200 verify | **AI** |
| Phase 4.3 candidate-rebuild trigger | **USER** |
| Phase 4.4 smoke-against-candidate | **AI** |
| Phase 4.5 promotion | **USER** |
| Phase 4.6 compose-up | **USER** |
| Phase 5.5 coverage = 100 % | **AI** verifies |
| Phase 5.6 :8000 scheduling | **USER** (none planned) |

### Pass 2 Verdict

**Plan is fit to proceed to implementation.** All 37 actions are executor-tagged; 5 USER-owned gates are explicit; 3 previously-silent hand-offs are made AC-visible. No security threats reviewed (out of Pass 2's scope per the memory rule).

The implementation order is:
- **AI sequences 1.1–1.5** (write files, generate key)
- **USER does 1.6 (build) + 1.7 (compose up)**
- **AI does 1.8 (verify health) → 2.x → 3.x**
- **AI does 4.1–4.2 (compose edit + Dockerfile drop)**
- **USER does 4.3 (rebuild candidate)**
- **AI does 4.4 (smoke against candidate)**
- **USER does 4.5 (promote) + 4.6 (compose up)**
- **AI does 5.x → 6.x → 7.x**

After your ratification of Pass 2, implementation green-lights.

---

## Pass 1 Fitness — Findings 2026-05-16

Status: ✅ Complete after REUSE-decision ratifications (R1=C, R2=A, R3=A). Acceptance criteria below assume those decisions land as drafted.

### Acceptance Criteria per Phase

Each AC is **testable**, **observable**, and **gates the next phase**. No phase is "done" until every AC for it passes.

#### Phase 0 — R&D doc + baseline metrics (already done)

- **AC0.1**: `src/rnd/v0.1.7/2026.05.16-model-server-carveout/01-design.md` exists, contains REUSE + Pass 1 + Gap Analysis sections — ✅ verified at this commit
- **AC0.2**: `90-baseline-metrics.md` exists with §1-§7 + §10 captured — ✅ verified
- **AC0.3**: §8 / §9 / §11 outlined for follow-up data-gathering pass — ✅ verified

#### Phase 1 — `lupin-model-server` container

- **AC1.1**: `src/lupin_model_server/main.py` boots a FastAPI app on `:7998` that exposes `/health`, `/transcribe`, `/embeddings/generate`, `/embeddings/batch`, `/embeddings/info`, `/admin/metrics`
- **AC1.2**: `/health` returns **503** with body `{"status": "loading", "models_loaded": [partial list]}` while ANY of `{Whisper, CodeRankEmbed, nomic-embed-text-v1.5}` is still loading; returns **200** with body `{"status": "ready", "models_loaded": [3 names], "vram_used_mb": <int>}` once all are resident in VRAM
- **AC1.3**: All endpoints except `/health` require `X-API-Key: ck_internal_*`; reject `ck_live_*` user keys with **401** + body `{"detail": "Endpoint requires internal-service key"}`
- **AC1.4**: `/admin/metrics` returns Prometheus text-format response with at minimum: `model_server_vram_used_mb` (gauge), `model_server_requests_total{endpoint}` (counter), `model_server_request_duration_seconds{endpoint}` (histogram with p50/p95/p99), `model_server_models_loaded` (gauge), `model_server_uptime_seconds` (counter)
- **AC1.5**: `docker/lupin-model-server/Dockerfile` builds; resulting image < 15 GB; pre-downloads all 3 models at build time using the existing HF cache layout
- **AC1.6**: `docker-compose.yml` `lupin-model-server` service has `restart: unless-stopped`, `CUDA_VISIBLE_DEVICES=0` (per memory rule), `mem_limit: 8g`, `cpus: 4`, Python urllib healthcheck on `/health`, HF cache bind-mount, `X-API-Key` env-var injection

#### Phase 2 — INI keys + runtime URL config (per R1=C)

- **AC2.1**: `lupin-app.ini` gains key `model server url` (default `http://lupin-model-server:7998`) + key `speech to text provider` (default `local`, accepted values `local|model-server`)
- **AC2.2**: `lupin-app-splainer.ini` has matching explanations for both keys
- **AC2.3**: `LUPIN_MODEL_SERVER_URL` env var overrides INI fallback (mirrors existing `LUPIN_APP_SERVER_URL` convention at `embedding_provider.py:158-174`)
- **AC2.4**: `embedding_provider.py` URL resolver extended: checks `LUPIN_MODEL_SERVER_URL` → `model server url` INI → falls back to local routing (no third enum value per R1)

#### Phase 3 — HTTP-proxy paths in compute containers

- **AC3.1**: `embedding_provider.py` HTTP path correctly routes to `:7998` when `_is_in_process_engine_owner=False` AND model-server URL is set; existing tests pass unchanged
- **AC3.2**: New `src/cosa/memory/speech_to_text_provider.py` mirrors `EmbeddingProvider` architecture exactly: singleton, class-level `_is_in_process_owner` flag, INI key `speech to text provider`, local + HTTP paths, lazy-load on first call
- **AC3.3**: `speech.py` `/api/upload-and-transcribe-{mp3,wav}` endpoints replace `Depends(get_whisper_pipeline)` with `Depends(get_speech_provider)`; transcribe call site swaps in-process `whisper_pipeline(...)` for `await provider.transcribe(audio_bytes, content_type)`
- **AC3.4**: Shared `_call_with_retry()` wrapper (exp backoff 2/4/8s, retry on 5xx + timeout, no retry on 4xx) implemented once and used by both providers
- **AC3.5**: `save_upload_to_temp(file_or_b64) -> str` helper extracted in `speech.py`; both MP3 and WAV endpoints use it; cleanup via try/finally
- **AC3.6**: Compute-side `main.py` lifespan adds startup-blocker: polls `lupin-model-server:7998/health` for up to 30s with 1s interval; on timeout raises `RuntimeError` and aborts startup (mirrors GPU-load-blocker shape at `main.py:626-673`)

#### Phase 4 — Strip GPU from compute services

- **AC4.1**: `lupin-rest-dev` + `lupin-rest-test` compose services lose `deploy.resources.reservations.devices` blocks entirely
- **AC4.2**: Both gain `depends_on: lupin-model-server: condition: service_healthy`
- **AC4.3**: `lupin:1.0.0` Dockerfile drops the 3 model pre-downloads at lines 208-210; new image rebuild target is `lupin:1.0.0-noasr` (per `feedback_no_auto_promote_tags`)
- **AC4.4**: New image size < 28 GB (~4 GB savings vs 31.7 GB); user verifies + promotes to `lupin:1.0.0` only after smoke tests pass against the candidate tag

#### Phase 5 — Tests

- **AC5.1**: `src/tests/smoke/test_model_server_smoke.py` (new) hits `/health` (200), `/transcribe` (warmup MP3 round-trip), `/embeddings/{generate,batch}` (canned text round-trip), `/admin/metrics` (Prometheus format parse); uses `ck_internal_*` auth fixture
- **AC5.2**: `src/tests/unit/test_speech_to_text_provider.py` (new) mirrors `test_voice_persona_helpers.py` pattern — covers both `_is_in_process_owner=True` and `=False` branches; ≥8 test cases
- **AC5.3**: `src/tests/conftest.py` extended with `mock_model_server_client` fixture returning a `FakeSpeechToTextProvider` / `FakeEmbeddingProvider`-compatible object with canned responses
- **AC5.4**: Existing `test_voice_persona_allocation.py`, `test_embedding_api_smoke.py`, and any other speech/embeddings smoke tests **continue to pass** when run against `:7999` with `LUPIN_MODEL_SERVER_URL` pointing at `:7998` (HTTP-proxy path)
- **AC5.5**: **100% line + branch + function coverage** on every new or modified file in this carve-out, measured via `pytest --cov --cov-fail-under=100 --cov-branch`. Files in scope: `src/lupin_model_server/main.py` (new), `src/cosa/memory/speech_to_text_provider.py` (new), `src/cosa/memory/embedding_provider.py` (modified), `src/cosa/rest/routers/speech.py` (modified), `src/cosa/rest/routers/embeddings.py` (modified). `pragma: no cover` / `# pragma: no cover` exceptions permitted ONLY for genuinely-unreachable defensive branches with a same-line comment explaining why (mirroring the multiplexer `c8 ignore` rule). **Per Rick 2026-05-16: the 100% mandate previously scoped to multiplexer TS now extends to all Lupin code — see `feedback_100pct_coverage_multiplexer.md` (scope-expanded).** No tier-floor exceptions; no "≥X%" allowances.

#### Phase 6 — Container preflight

- **AC6.1**: `src/tests/smoke/test_container_preflight.py` extended with assertions: `lupin-model-server` is in `docker ps`, status `healthy`; HF cache bind-mount is present; env vars `LUPIN_MODEL_SERVER_API_KEY` injected in all three compose services
- **AC6.2**: `src/scripts/preflight-test-container.sh` includes a curl probe to `:7998/health` via docker network (using a transient `docker run --rm --network lupin-dev-network alpine` jumper if needed)

#### Phase 7 — Documentation touchpoints

- **AC7.1**: `CLAUDE.md` DOCUMENTATION TOUCHPOINTS gains a row for `src/lupin_model_server/` → cross-links `01-design.md` + `90-baseline-metrics.md`
- **AC7.2**: `CLAUDE.md` COMMANDS section documents `docker restart lupin-model-server` (rare; full reload triggers model re-load, ~25-30s)
- **AC7.3**: `~/.claude/skills/server-lifecycle/SKILL.md` adds a "Bouncing `lupin-model-server`" subsection — semantics: shared between dev + test, never auto-bounce, ~30s cold-start, all transcribe/embedding requests 503 during the window
- **AC7.4**: 01-design.md cross-links updated to point to `90-baseline-metrics.md` + future `91-execution-log.md` (Phase 1+ progress) + `92-post-carveout-metrics.md` (post-deploy comparison)

---

### Blast Radius Analysis

What happens if Phase N ships but N+1 doesn't — i.e., the rollback safety profile at each checkpoint:

| Checkpoint | State | User-facing effect | Rollback cost |
|---|---|---|---|
| **After Phase 1** | Model-server runs idle; compute untouched | Zero — compute containers still serve all endpoints in-process | Tear down model-server service entry (~5 min) |
| **After Phase 2** | Switch added, defaults to `local`; URL configured but unused | Zero — switch is `local` by default | Revert INI + splainer additions (~5 min) |
| **After Phase 3** (partial — say, embeddings carved, speech not) | Embedding endpoints route to `:7998`; speech still in-process | Half-carved state. Functional but inconsistent VRAM footprint. **Embedding latency +1-2 ms over LAN**; can be monitored via `/admin/metrics` | Flip `embedding provider` env var or revert provider code path (~10 min) |
| **After Phase 4** with model-server reachable | Compute containers have no GPU; both route to `:7998` for models. Doom loop is structurally dead. | All endpoints route to model-server. Compute reload now safe — no CUDA in compute. | Restore GPU reservations + revert Phase 3 routing (~30 min, requires container rebuild) |
| **After Phase 4** with model-server unreachable | Compute containers **fail to start** due to `depends_on: condition: service_healthy` blocking | STOP-THE-WORLD — no user-facing endpoints serve at all | Roll back to Phase 3 + bring `--gpus all` back temporarily (~45 min recovery; documented in skill) |
| **After Phase 5** | Tests cover the carve-out paths | None | None — tests are observation-only |
| **After Phase 6** | Preflight catches missing bind-mounts before runtime failures | None | None |
| **After Phase 7** | Docs updated | None | None |

**Safe-checkpoint-stops**: Phases 1, 2, 3 are individually safe stops — they don't change user-facing behavior unless we ALSO flip the runtime switch. Phase 4 is the first **destructive** step (removing GPU reservation); before Phase 4 lands, the carve-out must be proven via smoke tests in Phase 3.

**Mandatory ordering**: Phase 4 ONLY after Phase 5 smoke tests pass. Skipping that gate risks the "model-server unreachable" stop-the-world scenario.

---

### Testing Pyramid Coverage (per phase)

| Phase | Unit | Smoke (:7999) | Integration | E2E UI |
|---|---|---|---|---|
| Phase 1 (model-server) | `test_lupin_model_server.py` — provider classes, healthcheck logic | `test_model_server_smoke.py` — live `:7998` end-to-end | n/a | n/a |
| Phase 3 (HTTP proxy) | `test_speech_to_text_provider.py` — local + HTTP branches mocked | existing speech + embeddings smoke tests via HTTP-proxy | n/a | n/a |
| Phase 4 (GPU strip) | n/a | container preflight | n/a | n/a |
| Phase 6 (preflight) | n/a | `test_container_preflight.py` | n/a | n/a |

No E2E UI test changes — the carve-out is server-side; the UI calls the same FastAPI endpoints, which proxy through.

---

### Risk Re-Audit (folding in REUSE-informed surfaces)

Risks 1-8 from the original design doc still apply. Pass 1 surfaces these additional risks:

- **R9** — `prometheus-client` library Python version compatibility. The Lupin image uses Python 3.13 (per pre-bounce process tree); `prometheus-client` supports 3.8+. **Verify before pinning**. Mitigation: include the version pin in `pyproject.toml` of the new `lupin_model_server` package.
- **R10** — Lifespan race. Compute container's lifespan reads the switch → either loads models locally OR starts the model-server probe. If the order is wrong (probe first, then model load conditional on probe), a transient probe failure could cause both paths to fail. Mitigation: explicit ordering — read switch FIRST, branch IMMEDIATELY into one of two mutually-exclusive paths.
- **R11** — Disk-space transition risk. Building the new `lupin-model-server:0.1.0` image (~12 GB) while keeping `lupin:1.0.0` (31.7 GB) and the candidate `lupin:1.0.0-noasr` (~28 GB) means ~12 GB extra during the window. Mitigation: bring up the new image incrementally; do not drop the model pre-downloads from `lupin:1.0.0` (Phase 4 AC4.3) until smoke tests pass against the candidate.
- **R12** — `_is_in_process_engine_owner` flag interpretation. The existing pattern sets this flag at lifespan startup AFTER models warm up (`main.py:653`). The carve-out keeps this for cloud-run / local mode but means **the FastAPI worker that holds the flag must be the one that loaded the models** — verify the lifespan order doesn't accidentally set the flag in a non-owner process.
- **R13** — `_call_with_retry()` wrapper interaction with FastAPI's async request lifecycle. Long retries (8s) under load could pile up requests and saturate the uvicorn worker pool. Mitigation: set total retry budget per request (e.g., 14s = 2+4+8) and surface the budget as an INI key.

---

### Pass 1 Verdict

**The plan is fit to proceed to Pass 2 (Ownership-Language Audit) and then to implementation.** No structural changes required from Pass 1; only the AC additions, blast-radius mandatory-ordering rule, coverage floors, and 5 new risks (R9-R13) need to be acknowledged.

The most important Pass 1 finding: **Phase 4 (GPU strip) is the irreversible destructive step. It must wait until Phase 5 smoke tests pass.** This becomes a hard gate in implementation order.

---

## Auth Refinement (María's brief, 2026-05-16 evening)

**This section overrides the earlier R2 ratification (`ck_internal_*` namespace) — see "REUSE Pass — Findings 2026-05-16" below for the original choice.**

### Why the override

Mid-implementation, the question arose: where does the model-server's API key come from? My initial design generated a NEW `ck_internal_*` key + wrote a NEW key file + injected a NEW bcrypt-hash env var. Rick pushed back: "you already have the notification API key sitting right there in conf/keys/ — why aren't we using that?"

Cross-session DM to María (`commons_send_to(recipient="Maria", ...)`, question_id `512ae38d-…`) surfaced the canonical pattern. Her brief:

> The DB-backed `require_api_key` validator at `cosa/rest/middleware/api_key_auth.py:34-79` walks `public.api_keys` via bcrypt-checkpw, so a frozen container (no postgres dep) cannot reuse it directly. Three options: (a) couple model-server to postgres — anti-pattern; (b) file-based allowlist validator inside model-server, reusing `ck_live_*` keys minted via the existing admin flow; (c) gateway pattern (Lupin REST fronts model-server, simpler internal token onward).
>
> Your `ck_internal_*` + bcrypt-hash env-var was actually the right SHAPE — just the wrong NAMESPACE.

María's pick was Option (b). Rick ratified Option (b) immediately + deferred a dedicated inter-server key to "version-something later".

### The locked-in auth design

| Aspect | Value |
|---|---|
| **API key namespace** | Existing `ck_live_*` — same one used by `notification-api-claude-code-dev` for the cosa-voice MCP, embedding HTTP fallbacks, and commons register-question paths |
| **Key file** | `src/conf/keys/notification-api-claude-code-dev` — already on host, mode 600, gitignored, established March 4 |
| **Supplier side** | Compute containers + cosa-voice MCP read the plaintext via `du.get_api_key("notification-api-claude-code-dev")` and send as `X-API-Key` header |
| **Validator inside model-server** | Read plaintext at lifespan boot → `bcrypt.hashpw()` once → store hash in `_state.api_key_hash` → `del plaintext_key` (purge plaintext from process memory) → `bcrypt.checkpw(incoming, _state.api_key_hash)` per request |
| **Key file bind-mount** | `./src/conf/keys:/var/lupin/src/conf/keys:ro` on the model-server compose entry |
| **Env var name** | `LUPIN_MODEL_SERVER_API_KEY_NAME` (default `notification-api-claude-code-dev`) — allows future override without code change |
| **Format check** | Existing `^ck_live_[A-Za-z0-9_-]{64,}$` regex — same as `api_key_auth.py:127`. `ck_internal_*` is rejected at the regex (defense-in-depth) |

### What got deleted

- `src/scripts/generate_internal_api_key.py` (75 LOC, never committed) — replaced by the existing `create_service_account.py` minting flow
- `src/conf/keys/lupin-model-server-auth` (never committed) — replaced by the existing `notification-api-claude-code-dev`
- `LUPIN_MODEL_SERVER_API_KEY_HASH` strict-required env var from `docker-compose.yml` — replaced by the boot-time hash computation

### Future inter-server key (deferred)

When the model-server's trust scope diverges from the notification key's scope (e.g., a different team takes ownership, or rotation cadence needs to differ), mint a dedicated `ck_live_*` key for the model-server via the admin flow + flip the `LUPIN_MODEL_SERVER_API_KEY_NAME` env var to point at it. No code change required. Per Rick's call, this is "version-something later" work.

---

## Part 2 Bounce — Actuals (2026-05-16 evening)

| Step | Predicted | Actual | Notes |
|---|---|---|---|
| INI flip | <1 s | <1 s | `speech to text provider = local` → `model-server` |
| `docker restart lupin-rest-dev` | 5-10 s | **10.9 s** | Old process dies (3.2 GB freed), new lifespan reads INI=model-server, skips loads |
| `docker restart lupin-rest-test` | 5-10 s | **11.1 s** | Same — another 3.2 GB freed |
| `docker compose up -d lupin-model-server` | container init 10 s | <1 s | Almost instant — image already built |
| Model loads (Whisper + 2 encoders) | 25-30 s | **9.4 s** ⚡ | Models baked into image; only `.to(cuda:0)` + warmup MP3 ran, no HF downloads |
| Compute readiness probes succeed → :7999 + :8000 bind | <2 s | <2 s | Probes immediately succeed since `:7998/health` already 200 |
| **Total wall-clock (excluding mid-flight bug-fix loop)** | 45-60 s | **~32 s** | Faster than predicted because layers cached + models baked |

### Mid-flight bugs caught + fixed

Two bugs surfaced post-bounce, both fixed in-session:

**Bug #1 — HF cache bind-mount permission denied**:
The initial `docker-compose.yml` for `lupin-model-server` had a bind-mount of `/mnt/DATA01/.../lupin-data/huggingface:/home/rruiz/.cache/huggingface` that overwrote the baked-in image cache with an unwritable host dir. All 3 model loads failed with `PermissionError`. **Fix**: removed the HF cache bind-mount entirely. Image is self-sufficient (~12.5 GB Whisper + ~1.1 GB encoders baked in).

**Bug #2 — embedding endpoint self-recursion**:
`docker restart` doesn't re-read `docker-compose.yml`, so the `LUPIN_MODEL_SERVER_URL` env var I added to compute compose entries never injected. `embedding_provider._resolve_model_server_url()` only checked env (not INI), so it returned `None`, fell back to the FastAPI URL `http://localhost:7999` — which is the compute container ITSELF. Compute → `:7999/api/embeddings/generate` → which re-entered the same code path → infinite recursion → 10 s timeout. **Fix (two-pronged)**:
1. `_resolve_model_server_url()` now checks env → INI → None (mirrors `SpeechToTextProvider`'s resolver).
2. `docker compose up -d --force-recreate lupin-rest-{dev,test}` to inject the env var.

**Bug #3 — `/transcribe` 422 from leftover Ellipsis default**:
The `transcribe()` endpoint signature had `_authenticated: str = ...` left over from an earlier auth refactor. FastAPI interpreted `= Ellipsis` as a required body field; the compute container's multipart form didn't include `_authenticated` → 422. Browser saw the compute-side 500-wrapper. **Fix**: deleted the unused parameter; rebuild + force-recreate.

### Final state (verified)

```
GPU 0 used: 19,889 MiB  (was 23,131 → saved 3,250 MiB, matches Rick's math)
GPU 0 free: 4,335 MiB   (was 1,086 → headroom 4×)

:7998/health       — 200 ready, 3 models loaded, 2,505 MB VRAM
:7999/health       — 200 (HTTP-proxy path verified)
:8000/health       — 200 (same)

Smoke tests: 9/9 PASSED in 3.02 s
  test_health_direct
  test_transcribe_direct
  test_embeddings_generate_direct
  test_embeddings_batch_direct
  test_admin_metrics_direct
  test_auth_rejects_missing_key
  test_auth_rejects_wrong_prefix
  test_auth_rejects_invalid_ck_live
  test_proxy_through_compute_mp3

Native browser ASR: confirmed working post-fix
```

### Doom-loop status

| Layer | Pre-carve-out | Post-carve-out |
|---|---|---|
| L1 — cu124 forward-compat fragility | ACTIVE on compute reload | **GONE** — compute containers no longer touch CUDA |
| L2 — uvicorn `--reload` in same container | ACTIVE (intentional) | **HARMLESS** — no GPU dependency to break |
| L3 — eager GPU pre-warm in lifespan | ACTIVE | **GONE** — relocated to model-server boot (one-time at infrastructure-change cadence, not code-change cadence) |

Compute hot-reload is now safe. Editing any file under `reload_dirs` does not trip CUDA re-init.

---

## REUSE Pass — Findings 2026-05-16

Run via 3 parallel Explore agents covering (A) HTTP/auth/DI utilities, (B) provider routing + health + audio, (C) test fixtures + compose precedent. Key conclusion: **~200 LOC of my draft plan should be deleted in favor of extending existing code.**

### 🟢 Reuse as-is

| Pattern | Location | Use for the carve-out |
|---|---|---|
| **`EmbeddingProvider` local-vs-HTTP routing** | `cosa/memory/embedding_provider.py:48-367` with class-level `_is_in_process_engine_owner` flag + INI key `embedding provider = local\|openai` | **DON'T build `ModelServerClient` for embeddings** — just add a third provider value (e.g. `"model-server"`) that routes the existing `_generate_embedding{,s_batch}_via_http` (`:217-305`) to `:7998` instead of `:7999`. The switch is already implemented; the HTTP path is already implemented; we just swap the target URL. |
| **`X-API-Key` middleware** | `cosa/rest/middleware/api_key_auth.py:85` (`require_api_key`) + `:147` (`require_api_key_or_jwt`) — bcrypt-hashed lookup, timing-safe | **DON'T invent `model server internal api key` INI**. Generate a `ck_internal_*` key via existing `src/scripts/create_service_account.py`, store at `src/conf/keys/lupin-model-server-auth`. Auth is the existing middleware, zero new code. |
| **`LUPIN_APP_SERVER_URL` env-var redirect** | `embedding_provider.py:158-174` — dynamically resolves base URL from env | Mirror as `LUPIN_MODEL_SERVER_URL` for the same purpose — points compute → `:7998` in normal use; tests can redirect. |
| **docker-compose healthcheck convention** | `docker-compose.yml:91-96` — `python3 -c "import urllib.request; urlopen('/health', timeout=3)"` | Apply identically to `lupin-model-server` (Python urllib because curl isn't in the image). |
| **`depends_on: condition: service_healthy`** | `docker-compose.yml:99-101, 177-179` — postgres → REST | Apply identically: REST → `lupin-model-server`. |
| **Lifespan startup blocker** | `main.py:626-673` — GPU warmup loop + `declare_in_process_engine_owner()` | Mirror the retry-loop shape for waiting on `lupin-model-server:7998/health` with `max_retries=30, retry_delay=1` (30 s total). |
| **`Peer router` cross-container HTTP precedent** | `cosa/rest/routers/peer.py:1-150` — `:7999 → :8000` via `aiohttp.ClientSession`, 10 s timeout, per-host token cache, host whitelist (SSRF protection) | This is the existing pattern for service-to-service inside the docker network. Mirror it (substitute JWT → `X-API-Key` since model-server is non-user-facing). |

### 🟡 Extend (don't rebuild)

| Pattern | Location | Extension needed |
|---|---|---|
| HTTP `requests.post()` calls | `embedding_provider.py:217-252` (single), `:254-305` (batch) — **no retry, no backoff** today | Add a tiny `_call_with_retry()` wrapper (exp backoff 2/4/8 s, 503/timeout retry-eligible, 4xx no-retry). ~30 LOC. Don't build a full circuit-breaker — defer until metrics show need. |
| Audio upload-to-temp-file | `speech.py:225-236` (MP3, base64), `speech.py:640-668` (WAV, `UploadFile`) — duplicated, inline cleanup | Natural moment to extract `save_upload_to_temp(file_or_b64) -> str` helper that both endpoints + the new HTTP-proxy use. ~15 LOC; net deduplication. |
| Whisper OOM retry | `speech.py:39-60` — single OOM retry, no backoff | Keep as-is; relocate to `lupin-model-server` unchanged. |

### 🔴 Build new (no precedent — but precedent shapes the design)

| Pattern | Why no precedent | What to build |
|---|---|---|
| `SpeechToTextProvider` (new class) | No equivalent of `EmbeddingProvider` exists for Whisper today; `speech.py` directly grabs `whisper_pipeline` from `main.py:80-87` | Mirror `EmbeddingProvider` architecture exactly: singleton + class-flag `_is_in_process_owner` + INI key `speech to text provider = local\|model-server`. ~150 LOC but architecturally identical to existing code. |
| `mock_model_server_client` pytest fixture | All current Lupin tests hit a live server (`integration/conftest.py:205-242`); no canned-response precedent | Add to `src/tests/conftest.py` per Gap A8. ~40 LOC. |
| `lupin-model-server` `/health` with **models-loaded** semantics (503 until VRAM-ready, 200 once loaded) | Existing `/health` (`system.py:63, 95`) always returns 200 if process is up — no readiness semantics today | New endpoint inside the new container. ~20 LOC. |
| `/admin/metrics` Prometheus-style endpoint | No existing equivalent in Lupin | New endpoint inside the new container. ~50 LOC (or use `prometheus-client` lib). |
| `lupin-model-server` compose service entry | First Lupin-to-Lupin HTTP service-to-service compose entry beyond postgres | New service block in `docker-compose.yml`. Mirrors existing dev/test entries minus `--reload`. |

### Plan delta summary — what changes vs the pre-REUSE draft

| Pre-REUSE | Post-REUSE | Saving |
|---|---|---|
| New `src/cosa/clients/model_server_client.py` (~150 LOC) | **DELETED** — extend `embedding_provider.py` (~30 LOC) for embeddings + new `SpeechToTextProvider` (~150 LOC) mirroring it for Whisper | Net ~0 LOC but **one fewer abstraction** + reuse-tested switch logic |
| New INI key `model server local mode` | **REPLACED** — reuse existing `embedding provider` key + new `speech to text provider` key both = `local\|model-server` | Cleaner; mirrors established convention |
| New INI key `model server internal api key` | **DELETED** — use existing `create_service_account.py` flow + `X-API-Key` header | ~5 LOC + no new INI surface |
| New auth middleware | **DELETED** — `require_api_key_or_jwt` is the auth | ~80 LOC saved |
| Custom retry/backoff library | **DEFERRED** — ~30 LOC retry wrapper now; real circuit-breaker only if metrics demand | ~150 LOC saved up front |
| **Net implementation estimate** | ~2–2.5 hours (down from 4) | ~30-40 % faster |

### Open knobs informed by REUSE findings

- **Provider naming**: I now lean toward `embedding provider = model-server` (replacing the unused `"openai"` ↔ `"local"` pair? Or alongside as a third option?). The existing key is already pinned to `local` in dev. Rick to confirm whether the third value joins the existing two or this is renamed.
- **Speech provider key**: NEW key `speech to text provider = local|model-server` proposed; no existing key. Confirm name.
- **API key naming convention**: existing pattern is `ck_live_*` (user-facing) and could be extended with `ck_internal_*` (service-only). Rick to ratify the prefix or pick a different one.
- **`/admin/metrics` payload format**: Prometheus text format (using `prometheus-client` lib) or hand-rolled JSON? No existing precedent in Lupin; either works.

### Files that change because of REUSE findings

This supersedes the earlier Critical Files list — those are still the surfaces, but the LOC count and the abstractions land differently. The next iteration of the design doc's "Critical Files" + "Phased Implementation" sections will be rewritten after the Pass 1 gate. For now, the REUSE pass produces these immediate changes to the existing plan:

1. **A3 (`ModelServerClient` abstraction) — DELETED** for the embeddings half. Embeddings just extend `EmbeddingProvider` with a new provider name. The Whisper half becomes a new `SpeechToTextProvider` mirroring the existing pattern.
2. **A1 (cross-container auth) — SIMPLIFIED** to "generate an internal API key via `create_service_account.py`, store at `src/conf/keys/lupin-model-server-auth`, use existing `require_api_key_or_jwt` middleware".
3. **A4 (compute-side readiness probe) — UNCHANGED** but explicit precedent is `main.py:626-673` retry-loop shape.
4. **A7 (resource limits + `/admin/metrics`) — UNCHANGED** but use `prometheus-client` lib if Rick prefers, else hand-rolled JSON.

---

## Gap Analysis Additions (caught on second pass; added 2026-05-16 per Rick's "what else does this plan need")

The base architecture covers WHAT to carve out; these additions cover the operational + safety details needed before Phase 1 begins.

### A1. Cross-container authentication

The model-server endpoints (`/transcribe`, `/embeddings/*`) must NOT be reachable from outside the docker network without auth. Options:

| Option | Pros | Cons |
|---|---|---|
| **Shared internal API key** (recommended) — `MODEL_SERVER_API_KEY` env var injected into all three containers; model-server checks `X-API-Key` header on every request | Simple, low overhead, blocks an attacker who reaches `:7998` from another container or accidentally-exposed port | One more env var to manage |
| Docker network isolation only | Zero code change | Defense-in-depth violation; the moment `:7998` is bound to `0.0.0.0` by mistake, it's wide-open |
| JWT pass-through (forward the user's JWT from compute → model-server) | Inherits Lupin's existing auth contract | Heavyweight; tokens have short TTL; tests get harder |

**Recommendation**: shared internal API key. New INI key `model server internal api key` + matching env-var injection in `docker-compose.yml` for all three services. Generate at first compose-up via a one-shot init script (or accept a manually-set value).

### A2. Models-loaded healthcheck

The model-server's `/health` endpoint returns:
- `503 Service Unavailable` while ANY of `{Whisper, CodeRankEmbed, nomic-embed-text-v1.5}` is still loading
- `200 OK` with `{ "status": "ready", "models_loaded": ["whisper", "code_rank_embed", "nomic_embed_text_v1.5"], "vram_used_mb": <int> }` once all three are resident in VRAM

This is what makes `depends_on: lupin-model-server` actually mean "ready for requests" instead of just "process is up". Compose's `condition: service_healthy` qualifier on `depends_on` is the mechanism.

### A3. `ModelServerClient` abstraction

Instead of scattering if/else throughout `speech.py`, `embeddings.py`, and `embedding_provider.py`, introduce a single client class:

```python
# src/cosa/clients/model_server_client.py (new)
class ModelServerClient:
    def __init__( self, config_mgr ):
        self._local_mode = config_mgr.get( "model server local mode", default=False, return_type="bool" )
        if self._local_mode:
            # In-process path — lazy-load the existing engines
            self._whisper = None
            self._code_engine = None
            self._prose_engine = None
        else:
            self._http = httpx.AsyncClient( base_url=config_mgr.get( "model server url" ), timeout=120.0 )
            self._api_key = config_mgr.get( "model server internal api key" )

    async def transcribe( self, audio_bytes, content_type ) -> str: ...
    async def embed_code( self, texts: list[str] ) -> list[list[float]]: ...
    async def embed_prose( self, texts: list[str] ) -> list[list[float]]: ...
    async def info( self ) -> dict: ...
```

FastAPI endpoints become:
```python
@router.post( "/api/upload-and-transcribe-mp3" )
async def transcribe( file: UploadFile, client: ModelServerClient = Depends( get_model_client ) ):
    return await client.transcribe( await file.read(), file.content_type )
```

This contains the switch logic to one file and gives a single mock surface for tests (A8 below).

### A4. Compute-side readiness probe at lifespan startup

In `main.py` lifespan, when `model server local mode = False`, BLOCK startup until `lupin-model-server` `/health` returns 200, with retries + timeout (e.g., 60 s):

```python
if not local_mode:
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            r = await httpx.AsyncClient().get( f"{server_url}/health", timeout=2.0 )
            if r.status_code == 200:
                break
        except httpx.HTTPError:
            pass
        await asyncio.sleep( 1.0 )
    else:
        raise RuntimeError( "lupin-model-server unreachable after 60s — refusing to bind compute container" )
```

Prevents 500s during the boot race where compute is up but model-server is still loading the three models. The `depends_on: condition: service_healthy` already gives 95% of this; the in-process probe is the last 5%.

### A5. GPU pinning — model-server lands on **GPU 0** (always)

**Hard rule (Rick, 2026-05-16)**: Lupin's models have always loaded on GPU 0; the carve-out preserves that binding. Pin model-server via `CUDA_VISIBLE_DEVICES=0` in compose. Do NOT move Lupin to GPU 1 even though GPU 1 has more headroom — the workload partitioning between Lupin and the external vLLM project depends on Lupin staying on GPU 0. See auto-memory: `feedback_lupin_models_always_gpu_0.md`.

**Headroom landing**: today GPU 0 holds Lupin dev (3,274 MiB) + Lupin test (3,202 MiB) = **~6.5 GB of Lupin** plus a share of vLLM. After the carve-out, GPU 0 holds **one** model-server process (~3.2 GB) plus the same vLLM share. The ~3.2 GB savings lands on GPU 0 specifically — which is exactly the GPU where headroom matters most (it was at 94% utilization, 1 GB free pre-bounce).

Compute containers (`lupin-rest-dev`, `lupin-rest-test`) get **no GPU reservation at all** after the carve-out — that's the whole point.

### A6. Bind-mount the HuggingFace cache

The model-server container mounts the same path `/var/external-projects/models/hub/` (or wherever it lives on host) so it shares the existing pre-downloaded models with Lupin. No double-download, no extra disk burn. Coordinate with the existing bind-mount line in `docker-compose.yml`.

### A7. Resource limits + `/admin/metrics`

In compose:
```yaml
lupin-model-server:
  mem_limit: 8g     # Hard cap; OOM-kill before host swap thrashes
  cpus: 4           # Leave CPU headroom for compute containers + Claude Code
```

New endpoint `GET /admin/metrics` on model-server returning Prometheus-style or JSON:
- `vram_used_mb`
- `requests_total{endpoint=...}`
- `request_duration_seconds{endpoint=..., quantile=...}` (p50/p95/p99)
- `models_loaded` (list)
- `uptime_seconds`

This becomes the dataset for the post-carve-out impact measurement Rick asked for.

### A8. Mock fixture for unit tests

A pytest fixture `mock_model_server_client` that returns a `ModelServerClient`-compatible fake with pre-canned responses (sample embeddings, sample transcription text). Unit tests of routers + embedding_provider use this fixture instead of needing a live `:7998`.

```python
@pytest.fixture
def mock_model_server_client( monkeypatch ):
    fake = FakeModelServerClient( embed_dim=768, transcribe_text="hello world" )
    monkeypatch.setattr( "cosa.clients.model_server_client.ModelServerClient", lambda *a, **k: fake )
    return fake
```

### Open knobs (still up to Rick)

- **Switch name** — `model server local mode` (current draft) vs `models in process` vs something else
- **Whether to make A1 (auth) optional** with `False` default + explicit "I trust my docker network" override
- **Whether the `/admin/metrics` endpoint requires the same internal API key** (recommended: yes)
- **Single-GPU host fallback** — already `CUDA_VISIBLE_DEVICES=0` per A5 hard rule; no change needed

---

## Critical Files

**New**:
- `src/rnd/v0.1.7/2026.05.16-model-server-carveout/01-design.md` (this file)
- `src/rnd/v0.1.7/2026.05.16-model-server-carveout/90-baseline-metrics.md` (already serialized — pre-carve-out measurements)
- `src/lupin_model_server/main.py` — minimal FastAPI app exposing `/transcribe`, `/embeddings/generate`, `/embeddings/batch`, `/embeddings/info`, `/health`, `/admin/metrics`. Reuses `load_stt_model()` from current `main.py:940-970` and `local_embedding_engine.py` singletons. Models-loaded healthcheck per A2; internal API key middleware per A1.
- `src/cosa/clients/model_server_client.py` — `ModelServerClient` abstraction per A3; lazy local engines OR pooled `httpx.AsyncClient`
- `docker/lupin-model-server/Dockerfile` — lean image: torch 2.6.0+cu124, transformers, sentence-transformers, faster-whisper (or transformers `pipeline`), uvicorn. NO Lupin app code. Pre-downloads the three models at build time (mirrors current Dockerfile lines 208-210).
- `src/tests/smoke/test_model_server_smoke.py` — smoke against the new `:7998` (uses internal API key for auth)
- `src/tests/unit/test_model_server_client.py` — unit tests of the `ModelServerClient` switch behavior
- `src/tests/conftest.py` (extend) — `mock_model_server_client` pytest fixture per A8

**Modified**:
- `docker-compose.yml` — add `lupin-model-server` service entry (with `mem_limit`, `cpus`, `CUDA_VISIBLE_DEVICES=0` per A5 hard rule, HF cache bind-mount, internal-API-key env var); remove `deploy.resources.reservations.devices` from `lupin-rest-dev` + `lupin-rest-test`; add `depends_on: lupin-model-server: condition: service_healthy`
- `src/conf/lupin-app.ini` — new keys `model server local mode`, `model server url`, `model server internal api key`, `model server startup probe timeout seconds` (default 60)
- `src/conf/lupin-app-splainer.ini` — matching explanations
- `src/fastapi_app/main.py` — gate eager loads at lines 619-657 on `model server local mode`; add compute-side readiness probe per A4; remove `whisper_pipeline` module global when remote
- `src/cosa/rest/routers/speech.py` — replace `get_whisper_pipeline` Depends with `Depends( get_model_client )` per A3
- `src/cosa/rest/routers/embeddings.py` — same pattern
- `src/cosa/memory/embedding_provider.py` — delegate to `ModelServerClient` per A3 (no direct engine import in the remote-mode path)
- `src/scripts/preflight-test-container.sh` — extend to verify model-server bind-mounts + reachability via `/health`
- `CLAUDE.md` — DOCUMENTATION TOUCHPOINTS row + TESTING VENUES note that `:7998` is monopoly-free (model-server is shared, no monopolize mode)
- `~/.claude/skills/server-lifecycle/SKILL.md` — add `lupin-model-server` bounce semantics (rare, but document); recovery command is `docker restart lupin-model-server`

**Out-of-scope (Rick can ship separately or this plan can absorb on request)**:
- The yesterday-recommended non-fatal pre-warm wrap at `main.py:619-657` — recommended in parallel; tiny scope; not blocking the carve-out

---

## Verification

| Layer | Command | Asserts |
|---|---|---|
| py_compile | per-file `py_compile.compile()` | All new/edited files compile |
| Unit | `pytest src/tests/unit/test_*model_server*.py -v` | New unit tests for switch-aware client wrapper |
| Smoke (model-server) | `pytest src/tests/smoke/test_model_server_smoke.py -v` | `/transcribe` returns text; `/embeddings/batch` returns vectors; `/health` returns 200 with `models_loaded` list |
| Smoke (existing speech) | `pytest src/tests/smoke/test_speech_*.py -v` against `:7999` with `model server local mode = False` | All existing speech endpoints still pass via the HTTP-proxy path |
| Smoke (existing embeddings) | `pytest src/tests/smoke/test_embedding_api_smoke.py` against `:7999` | Same — embeddings flow unchanged from caller's view |
| Container preflight | `pytest src/tests/smoke/test_container_preflight.py` | Model-server bind-mounts present; reachable from dev + test |
| Doom-loop repro | Edit a file under `reload_dirs` after the carve-out is live; observe NO `RuntimeError: No CUDA GPUs are available` in `lupin-rest-dev` logs | Layers 1 + 3 are gone |
| Cloud-run mode | Run with `model server local mode = True` (no model-server container); confirm Whisper + embeddings load in-process and endpoints serve as today | Switch is honored; backward-compatible |
| VRAM steady-state | `nvidia-smi` on host after all containers up | ~3 GB resident (one model copy), not ~6 GB |

---

## Risks / Gotchas

1. **HTTP latency per call** — adds ~1-10 ms (LAN, same-host docker bridge) for embedding/transcribe. Embeddings are sometimes called per-scenario in batch proxy-decision flows; verify aggregate latency stays acceptable. Mitigation: keep `httpx.AsyncClient` pooled per-process; use `/embeddings/batch` for batch use cases.
2. **Single-point-of-failure** — if `lupin-model-server` crashes, all transcription + embeddings 503 across both compute containers. Mitigation: `restart: unless-stopped` + healthcheck-driven restart; the server is small and stable (no code-driven reload). Future: multi-replica behind a load balancer.
3. **Build-time model download moved** — currently the Lupin image pre-downloads the three models (`Dockerfile:208-210`). After the carve-out, ONLY the model-server image needs them. Lupin image can drop those lines, saving ~3 GB of image size and faster rebuilds.
4. **Cloud-run code path divergence** — `model server local mode = True` is exercised only in cloud-run. Add a CI matrix scenario (or at least a CI run with `local mode = True`) so the in-process path doesn't bit-rot.
5. **Test-server monopolize mode** — `:8000` test runs may hit `:7998` while `:7999` dev is also live. The model-server endpoints are stateless (no per-session state), so concurrent calls are safe. Document this in the new R&D doc and the server-lifecycle skill.
6. **Dependency-injection refactor** — `Depends( get_whisper_pipeline )` and `Depends( get_provider )` are touched in multiple test files (smoke + unit). Each test that mocks the in-process pipeline must be audited to instead mock the HTTP client. Plan: enumerate during Phase 5.
7. **GPU on host still required** — RTX 4090s remain. We just stop double-resident-loading them. No platform-portability gain (Rick already accepts this).
8. **Initial bring-up requires both Lupin image AND model-server image** — coordinate Phase 1 + Phase 3 so dev/test never start without the model-server up. The `depends_on` directive enforces this; the preflight test confirms.

---

## Out of Scope

- **Driver 550.x upgrade** — still recommended per yesterday's Option #3, independently. The carve-out reduces the urgency (compute containers no longer touch CUDA) but the model-server container would still benefit. Defer to next host-reboot window.
- **Multiple model-server replicas / load balancer** — single instance is fine for current scale; revisit when GPU contention shows up.
- **gRPC for model-server** — HTTP is simpler and good enough at LAN latencies; revisit only if profiling shows HTTP overhead matters.
- **Refactoring the in-process embedding engine to be reusable** — the model-server can `import cosa.memory.local_embedding_engine` directly; no API change needed inside CoSA.
- **Bug #2 follow-up (duplicate notifications)** — separate session per earlier TODO entry.
