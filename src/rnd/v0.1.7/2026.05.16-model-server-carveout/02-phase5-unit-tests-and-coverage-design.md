# Phase 5 — Unit Tests + 100% Coverage Backfill (Design)

**Author**: Tiberius 🌑 (session `225e5b2d`)
**Filed**: 2026-05-17
**Status**: 🟡 PLAN — awaiting Rick's go/review (per @all broadcast `21bb12cd`)
**Parent**: [`01-design.md`](01-design.md) (Phases 0-3 + 3.6 + Part 2 bounce + Phase 5.1 smoke — already shipped)
**TODO entry**: `TODO.md` L29-34 ("Phase 5 — Test coverage + unit tests")
**Doc-viewer**: `/app/docs?path=lupin/src/rnd/v0.1.7/2026.05.16-model-server-carveout/02-phase5-unit-tests-and-coverage-design.md`

---

## §1 Context & scope

Rio shipped Phases 0-3 + 3.6 of the model-server carve-out in session `0025f917`. The compute-side now HTTP-proxies all Whisper + 2 embedding-model calls to `lupin-model-server:7998`. Doom-loop layers 1 + 3 are structurally dead. End-to-end smoke (9/9 green; native browser ASR working) verified the live path.

**What's missing**: unit-tier coverage on the new + modified code. Per the 2026-05-16 scope-expansion of `feedback_100pct_coverage_multiplexer`, **100% line + branch + function coverage on every Lupin-side file in this carve-out is a hard gate**. `pragma: no cover` is allowed only on genuinely-unreachable defensive branches with same-line reason comments (two such markers already exist in `speech_to_text_provider.py:255,257`).

**This doc plans**: the unit-test scaffolding + mock-fixture design + coverage-gap audit needed to satisfy the gate, plus the audit of existing smoke tests for HTTP-proxy-path compatibility. **No code is written in this plan** — test names + assertions are enumerated in prose. Implementation lands after Rick's go.

---

## §2 Files in scope

Per TODO L33, the 5 files needing 100% coverage are:

| # | File | LOC | Status |
|---|---|---|---|
| 1 | `src/cosa/memory/speech_to_text_provider.py` | 321 | NEW — full coverage from scratch |
| 2 | `src/lupin_model_server/main.py` | 420 | NEW — full coverage from scratch |
| 3 | `src/cosa/memory/embedding_provider.py` | 638 | MODIFIED — coverage gap audit on new branches |
| 4 | `src/cosa/rest/routers/speech.py` | 1312 | MODIFIED — coverage gap audit on Depends + provider wiring |
| 5 | `src/fastapi_app/main.py` lifespan switch branch | (subset of file) | MODIFIED — switch-branch coverage |

Primary new test files needed:
- `src/tests/unit/test_speech_to_text_provider.py` (NEW — main deliverable, mirrors `test_voice_persona_helpers.py` mock-based pattern per TODO L31)
- `src/tests/unit/test_lupin_model_server_main.py` (NEW)
- Coverage-gap additions to existing `src/tests/unit/test_embedding_provider.py` (if it exists; otherwise NEW)
- Coverage-gap additions to existing `src/tests/unit/test_speech_router.py` or equivalent (router-level)
- One new test in `src/tests/unit/test_main_lifespan.py` (or equivalent) for the lifespan switch branch

---

## §3 `speech_to_text_provider.py` — test plan (primary deliverable)

The module exposes 7 surfaces. Below is the test-case enumeration per surface, sized for 100% branch coverage.

### §3.1 Singleton + init (`__new__` + `__init__`)

Three branches: (a) first construction creates instance under lock; (b) subsequent constructions return same instance without re-init; (c) `__init__` early-returns when `_initialized` is already True.

Test cases:
- `test_singleton_returns_same_instance_across_calls` — assert `SpeechToTextProvider() is SpeechToTextProvider()`
- `test_init_runs_once_even_with_multiple_constructions` — patch `ConfigurationManager` to count calls; assert called exactly once across 3 constructions
- `test_init_reads_provider_from_ini_lowercased_stripped` — INI returns `"  MODEL-SERVER  "` → `self._provider == "model-server"`
- `test_init_defaults_provider_to_local_when_ini_unset` — INI raises or returns default; `self._provider == "local"`
- `test_debug_prints_init_state_when_debug_true` — capture stdout; assert one-line debug print contains `provider=` and `owner=`

**Cleanup mandate**: every test that constructs the singleton MUST reset `_instance` + `_is_in_process_owner` + `_initialized` in a fixture teardown to avoid cross-test pollution. Pattern below in §4.

### §3.2 Owner-flag class methods (`declare_in_process_owner` + `declare_remote_only`)

Two single-line methods. Three tests:
- `test_declare_in_process_owner_sets_flag` — call → `_is_in_process_owner is True`
- `test_declare_in_process_owner_is_idempotent` — call twice → still True (no exception)
- `test_declare_remote_only_resets_flag` — set True, then call → `_is_in_process_owner is False`

### §3.3 URL resolution (`_resolve_model_server_url`)

Five branches: env-set / env-empty-then-INI-set / env-empty-and-INI-empty / env-empty-and-INI-default / exception path.

Test cases:
- `test_url_returns_env_when_set_and_nonempty` — `monkeypatch.setenv("LUPIN_MODEL_SERVER_URL", "http://test:9999")` → returns `"http://test:9999"`
- `test_url_strips_env_whitespace` — env is `"  http://test:9999  "` → returns stripped
- `test_url_falls_back_to_ini_when_env_unset` — env unset; mock `ConfigurationManager.get` → returns `"http://ini-url:7998"`
- `test_url_falls_back_to_hardcoded_default_when_ini_returns_empty` — INI returns `""` → returns `"http://lupin-model-server:7998"`
- `test_url_returns_hardcoded_default_when_config_manager_raises` — patch `ConfigurationManager` to raise; assert returns `"http://lupin-model-server:7998"` and does NOT re-raise

### §3.4 API-key resolution (`_model_server_api_key`)

Two branches: `du.get_api_key` succeeds → return key string; raises → return None.

Test cases:
- `test_api_key_returns_string_when_file_present` — mock `du.get_api_key` to return `"ck_live_abc123"`; assert returns `"ck_live_abc123"`
- `test_api_key_returns_none_when_get_api_key_raises` — mock to raise `FileNotFoundError`; assert returns None and does NOT re-raise

### §3.5 Routing decision (`_should_use_local`)

Four-way matrix per the docstring contract:

| `self._provider` | `_is_in_process_owner` | Expected |
|---|---|---|
| `"local"` | True | True |
| `"local"` | False | False |
| `"model-server"` | True | False |
| `"model-server"` | False | False |

Four test cases, one per row. Parametrize via `pytest.mark.parametrize` for compactness.

### §3.6 `transcribe()` — main entry point

This is the load-bearing branch matrix. Six paths:

| Provider | Owner | `whisper_pipeline` | OOM on first try | Expected behavior |
|---|---|---|---|---|
| `"local"` | True | None | n/a | RuntimeError raised |
| `"local"` | True | callable | False | Returns `result["text"]` if dict, else `str(result)` |
| `"local"` | True | callable | True | OOM caught; `gc.collect()` + `torch.cuda.empty_cache()` called; retry returns text |
| `"local"` | True | callable that returns non-dict | False | Returns `str(result)` |
| `"local"` | False | (irrelevant) | n/a | Routes to `_transcribe_via_http` (HTTP path) |
| `"model-server"` | (irrelevant) | (irrelevant) | n/a | Routes to `_transcribe_via_http` |

Test cases:
- `test_transcribe_local_raises_when_no_pipeline_passed`
- `test_transcribe_local_returns_text_from_dict_result`
- `test_transcribe_local_returns_str_from_non_dict_result`
- `test_transcribe_local_retries_once_on_cuda_oom_and_succeeds` — pipeline mock raises `torch.cuda.OutOfMemoryError` on first call, returns dict on second; assert gc+empty_cache called between
- `test_transcribe_local_propagates_oom_when_retry_also_fails` — pipeline raises OOM twice; assert second OOM propagates (mirrors historical `_run_whisper_with_retry` contract)
- `test_transcribe_routes_to_http_when_not_owner` — set provider=local but owner=False → mock `_transcribe_via_http` to verify it's called, NOT the pipeline
- `test_transcribe_routes_to_http_when_provider_is_model_server` — set provider=model-server, owner=True → asserts HTTP path is taken
- `test_transcribe_imports_torch_and_gc_lazily` — verify imports happen inside `transcribe`, not at module import time (cold-path patterns matter for non-GPU test workers)

### §3.7 `_call_with_retry` — exponential backoff

Static method, 4 branches per the docstring:
1. Success on first try → return immediately
2. 5xx response + attempts remaining → sleep + retry → eventual success
3. 5xx response + no attempts left → return the 5xx response (caller decides)
4. 4xx response → return immediately (no retry per contract)
5. `Timeout` / `ConnectionError` + attempts remaining → sleep + retry → success
6. `Timeout` / `ConnectionError` + exhausted → re-raise

Test cases:
- `test_retry_returns_2xx_immediately` — fn returns 200 on first call; assert called once, returns response
- `test_retry_returns_4xx_immediately_without_retry` — fn returns 422; assert called once, returns response (NO sleep)
- `test_retry_sleeps_and_retries_on_5xx_then_succeeds` — fn returns 503 once, then 200; assert `time.sleep` called with backoff_seq[0], fn called twice
- `test_retry_returns_5xx_when_all_attempts_exhausted` — fn always returns 503; assert returns final 503 (does NOT raise)
- `test_retry_sleeps_and_retries_on_timeout_then_succeeds` — fn raises `requests.Timeout` once, then 200; assert returns response
- `test_retry_raises_timeout_when_all_attempts_exhausted` — fn always raises `Timeout`; assert raises `Timeout`
- `test_retry_raises_connection_error_when_all_attempts_exhausted` — same shape but `ConnectionError`
- `test_retry_uses_backoff_sequence_in_order` — assert `time.sleep` calls match `backoff_seq` order

**`pragma: no cover` audit**: lines 255 + 257 mark unreachable defensive paths (`if last_exc is not None: raise last_exc` and the trailing `return None`). These are valid per the same-line-reason rule. Tests do NOT need to drive them.

### §3.8 `_transcribe_via_http` — HTTP path

Six failure modes + happy path:

Test cases:
- `test_http_raises_when_api_key_missing` — patch `_model_server_api_key` to return None; assert RuntimeError mentions `notification-api-claude-code-dev`
- `test_http_raises_when_audio_file_unreadable` — patch `open()` to raise `OSError`; assert RuntimeError includes file path + error
- `test_http_raises_runtime_error_when_call_with_retry_raises_request_exception` — mock `_call_with_retry` to raise `RequestException`; assert RuntimeError with `"HTTP unreachable"`
- `test_http_raises_runtime_error_on_non_200_response` — mock response with status_code=500, text="boom"; assert RuntimeError mentions 500 + truncated text
- `test_http_raises_runtime_error_on_malformed_json` — mock `response.json()` to raise `ValueError`; assert RuntimeError mentions `"malformed response"`
- `test_http_raises_runtime_error_when_text_key_missing` — mock `response.json()` to return `{"foo": "bar"}`; assert RuntimeError on KeyError
- `test_http_happy_path_returns_transcribed_text` — full mock chain: API key present, file readable, retry returns 200 with `{"text": "hello world"}`; assert returns `"hello world"`
- `test_http_posts_to_resolved_url_with_correct_headers` — assert POST URL is `{base_url}/transcribe`, `X-API-Key` header is set, files form-field shape matches contract

---

## §4 `mock_model_server_client` fixture design

Per TODO L32, this fixture goes in `src/tests/conftest.py` and provides a `FakeSpeechToTextProvider` / `FakeEmbeddingProvider`-compatible drop-in for tests that exercise the consuming surfaces (routers, lifespan, etc.) without a live `:7998`.

### §4.1 Fixture API contract

```
@pytest.fixture
def mock_model_server_client( monkeypatch, tmp_path ):
    """
    Yields a control handle with:
        - .set_transcribe_response(text: str | Exception)
        - .set_embed_response(vec: List[float] | Exception)
        - .recorded_calls: List[dict]  # each call's url + payload + headers

    Patches:
        - SpeechToTextProvider._transcribe_via_http to call into the fake
        - EmbeddingProvider._call_remote_embedding_endpoint (or equivalent
          modified method) to call into the fake
        - du.get_api_key("notification-api-claude-code-dev") to return a
          stub key
        - LUPIN_MODEL_SERVER_URL env var to a sentinel value

    Resets SpeechToTextProvider._instance + class flags after the test.
    """
```

### §4.2 Singleton-reset teardown helper

Both providers are class-level singletons. EVERY test that touches them needs a teardown that clears `_instance`, `_initialized`, `_is_in_process_owner` / `_is_in_process_engine_owner`. Bake this into a module-scoped autouse fixture so individual tests don't have to remember.

```
@pytest.fixture(autouse=True)
def _reset_provider_singletons():
    yield
    SpeechToTextProvider._instance              = None
    SpeechToTextProvider._is_in_process_owner   = False
    EmbeddingProvider._instance                 = None
    EmbeddingProvider._is_in_process_engine_owner = False
```

Scope: file-level in `test_speech_to_text_provider.py` and `test_embedding_provider.py`; promote to package-level conftest if more callers emerge.

### §4.3 Lifespan-flag fixture

```
@pytest.fixture
def speech_provider_in_local_mode( monkeypatch ):
    monkeypatch.setitem( <config patch> )
    SpeechToTextProvider.declare_in_process_owner()
    yield
    SpeechToTextProvider.declare_remote_only()

@pytest.fixture
def speech_provider_in_remote_mode( monkeypatch ):
    # provider = "model-server" OR _is_in_process_owner = False
    SpeechToTextProvider.declare_remote_only()
    yield
```

These let test functions clearly declare their mode-context without re-asserting class flags inline.

---

## §5 `embedding_provider.py` — coverage gap audit

Already in the codebase pre-Phase-3. The carveout added/modified these lines (per grep):

| Line(s) | Surface | Coverage status |
|---|---|---|
| 21 + 56 | `_is_in_process_engine_owner` class flag | NEEDS NEW BRANCH TESTS |
| 59 + 78 | `declare_in_process_engine_owner` class method | NEEDS NEW TESTS (mirror §3.2) |
| 177-202 | `_resolve_model_server_url` (new static method) | NEEDS NEW TESTS (mirror §3.3) |
| 238-296 | Route-resolution logic that picks model-server URL when env set | NEEDS NEW BRANCH TESTS |
| 423 + 475 | `elif self._is_in_process_engine_owner:` branches | NEEDS NEW BRANCH TESTS |

If `src/tests/unit/test_embedding_provider.py` exists: append new tests under a `class TestModelServerCarveout` marker. If not: create the file from scratch following the same pattern as `test_speech_to_text_provider.py`.

**Audit task before writing**: grep for existing `test_embedding_provider.py` and inventory what's already covered to avoid duplication. (Marked as Phase 5.0a prerequisite in §11.)

---

## §6 `routers/speech.py` — coverage gap audit

1312 lines is too large to retest end-to-end at the unit tier. **Scope of unit-tier additions**: only the SpeechToTextProvider integration points. Integration-test surface (full `/api/speech/transcribe` route through TestClient) belongs in smoke tests (§7).

Carveout-introduced changes (need confirmation via grep — Phase 5.0b prerequisite):
- `Depends`-injected `SpeechToTextProvider` instance
- Replacement of direct `whisper_pipeline(...)` calls with `provider.transcribe(...)`
- Removal of the original `_run_whisper_with_retry` (semantics moved into `provider.transcribe`)

Unit tests needed (3-5 cases):
- `test_speech_router_uses_provider_transcribe` — mock provider; assert router calls `transcribe()` with the right args
- `test_speech_router_propagates_provider_runtime_error_as_http_500` — provider raises RuntimeError; assert response is 500 with sanitized message
- `test_speech_router_preserves_kwargs_to_provider` — chunk_length_s + stride_length_s reach `transcribe(**kwargs)`

---

## §7 `lupin_model_server/main.py` — test plan

Standalone FastAPI app on `:7998`. New file, no existing tests. Surfaces to cover (will be enumerated concretely after reading the 420-line file — Phase 5.0c prerequisite):

Anticipated surfaces (from `01-design.md` and provider HTTP-path expectations):
- `/health` endpoint
- `/transcribe` endpoint (multipart audio upload, returns `{"text": ...}`)
- `/embeddings` endpoint (batch embed, returns vectors)
- Lifespan: model load on startup (Whisper + 2 embedding models on `cuda:0` per `feedback_lupin_models_always_gpu_0`)
- X-API-Key middleware enforcing the same `ck_live_*` key as the FastAPI HTTP paths

Test approach: TestClient-based, model loads MOCKED (no real GPU touch — `feedback_never_grab_gpu`).

Anticipated test cases (refined after source read):
- `test_health_returns_ok_when_models_loaded`
- `test_health_returns_503_when_models_unhealthy`
- `test_transcribe_requires_api_key`
- `test_transcribe_accepts_multipart_audio_and_returns_text`
- `test_transcribe_returns_500_on_pipeline_failure`
- `test_embeddings_requires_api_key`
- `test_embeddings_returns_vector_for_single_input`
- `test_embeddings_returns_vector_list_for_batch_input`
- `test_embeddings_returns_500_on_oom`
- `test_lifespan_loads_models_on_startup` (model loaders mocked)
- `test_lifespan_skips_load_when_remote_mode_flag_set` (if applicable)
- `test_x_api_key_middleware_rejects_missing_key`
- `test_x_api_key_middleware_rejects_invalid_key`

---

## §8 `fastapi_app/main.py` lifespan switch branch — test plan

The carveout added a conditional in the FastAPI lifespan that decides whether THIS process loads Whisper + embedding models in-process (sets `declare_in_process_*_owner` flags) OR skips loading entirely (compute-side runs HTTP-proxy mode).

Test surface is narrow: the switch branch itself.

Test cases:
- `test_lifespan_declares_local_owner_when_provider_local_and_models_loadable` — patch loader to succeed; assert `declare_in_process_owner` called
- `test_lifespan_declares_remote_only_when_provider_model_server` — patch INI to `model-server`; assert `declare_remote_only` called AND no model loader invoked
- `test_lifespan_handles_load_failure_gracefully` — loader raises; assert error logged, app still starts (or fails fast per design — need source read to confirm contract)

---

## §9 Existing smoke tests audit (Phase 5.0d prerequisite)

Per TODO L34, audit `src/tests/smoke/test_embedding_api_smoke.py` + any speech smoke tests for HTTP-proxy compatibility now that `LUPIN_MODEL_SERVER_URL` is injected at compose-up.

Audit checklist per file:
1. Does it instantiate the provider singleton in a way that respects the new mode flag?
2. Does it set `LUPIN_MODEL_SERVER_URL` (or rely on default)?
3. Does it require a live `:7998` to pass? If so, route to smoke tier; document the dependency.
4. Does it pass when run from `:7999` host context AND from inside a container?

Files to audit (will grep — Phase 5.0d):
- `src/tests/smoke/test_embedding_api_smoke.py` (named in TODO)
- Any `src/tests/smoke/test_speech_*.py` (search)
- `src/tests/smoke/test_container_preflight.py` (extension scoped to Phase 6 per TODO L37-39 — out of scope here but cross-referenced)

---

## §10 Coverage enforcement gate

Per `feedback_100pct_coverage_multiplexer` (scope-expanded Lupin-wide 2026-05-16):

```
pytest \
  --cov=cosa.memory.speech_to_text_provider \
  --cov=lupin_model_server.main \
  --cov-report=term-missing \
  --cov-branch \
  --cov-fail-under=100 \
  src/tests/unit/test_speech_to_text_provider.py \
  src/tests/unit/test_lupin_model_server_main.py
```

For `embedding_provider.py`, `routers/speech.py`, and `fastapi_app/main.py` — full-file 100% may not be feasible in one phase if they have legacy uncovered branches outside the carveout. **Two interpretations of the mandate** (decision needed for Rick — see §11.Q1):

- **Strict**: full 100% on every file touched, including legacy branches → adds 1-2 sessions of test backfill
- **Carveout-scoped**: 100% on new/modified surfaces only (lines named in §5, §6, §8) → matches the spirit of "every new or modified file in this carve-out"

TODO L33's wording ("every new or modified file") suggests the strict interpretation, but the embedding/router files are large enough that strict mode could spill into Phase 7+ scope.

---

## §11 Open questions / decisions for Rick

### Q1 — Coverage mandate strictness for the 3 modified files

Should the 100% gate apply file-wide (strict) or carveout-scoped-only?

Options:
- **A — Strict file-wide 100%** — pros: clean mandate, no caveat list; cons: adds 1-2 sessions of legacy backfill outside carveout intent
- **B — Carveout-scoped 100%** — pros: lands Phase 5 cleanly in one session; cons: adds a per-file caveat list to the coverage config
- **C — Strict for new files, carveout-scoped for modified files** — pros: pragmatic compromise; cons: introduces a mixed standard

**My recommendation: Option C.** New files (`speech_to_text_provider.py`, `lupin_model_server/main.py`) hit 100% file-wide. Modified files (`embedding_provider.py`, `routers/speech.py`, `fastapi_app/main.py`) hit 100% on carveout-modified surfaces, documented as a coverage-config carveout per `feedback_100pct_coverage_multiplexer`'s "same-line reason" carve-out for `pragma: no cover`.

**Becomes wrong if**: Rick prefers a clean Lupin-wide gate without per-file caveats — flip to Option A and accept the 1-2 extra sessions.

### Q2 — Test files: under `src/tests/unit/` flat or nested?

`src/tests/unit/` is currently flat. Options for the new files:
- **A — Flat**: `test_speech_to_text_provider.py`, `test_lupin_model_server_main.py` alongside existing
- **B — Nested**: `src/tests/unit/model_server/test_*.py` (new subfolder)

**My recommendation: Option A (flat).** Mirrors existing convention; 2 new files isn't enough scope to justify a subfolder. Cross-check before writing: peek at existing layout (probably already flat per the smoke/integration/unit pattern in `src/tests/`).

### Q3 — `mock_model_server_client` fixture location

- **A — In `src/tests/conftest.py` (top-level)** — global availability for all test tiers
- **B — In `src/tests/unit/conftest.py`** — unit-tier only
- **C — In a dedicated `src/tests/fixtures/model_server.py` module** — explicit import per consumer

**My recommendation: Option A (top-level conftest.py).** Matches the existing `mock_token_*` pattern. Smoke + integration tiers may also benefit from the fake later. Naming-wise, prefer `fake_model_server_client` over `mock_` to align with the "FakeSpeechToTextProvider" terminology already in the TODO entry.

### Q4 — Should we re-test `_run_whisper_with_retry` semantics from `routers/speech.py:39-60`?

The CUDA-OOM retry logic moved INTO `transcribe()` per `speech_to_text_provider.py:180-194`. The original `_run_whisper_with_retry` was removed (per design doc).

Options:
- **A — Yes, mirror the historical contract** — test that the OOM retry behavior in `transcribe()` exactly matches what `_run_whisper_with_retry` used to do
- **B — No, the new behavior is documented in the new module** — only test what the new module promises

**My recommendation: Option A.** The contract preservation is design-critical (mentioned explicitly in the `transcribe()` docstring lines 180-182). A test that pins "one retry, gc + empty_cache between, propagate second OOM" defends against future regression. Already enumerated in §3.6.

---

## §12 Acceptance criteria

| # | AC | Verifiable by |
|---|----|---|
| 1 | `src/tests/unit/test_speech_to_text_provider.py` exists with ≥25 test cases covering all 7 surfaces in §3 | `pytest --collect-only` |
| 2 | `src/tests/unit/test_lupin_model_server_main.py` exists with ≥10 test cases covering all surfaces in §7 | `pytest --collect-only` |
| 3 | `mock_model_server_client` fixture added to `src/tests/conftest.py` with the API contract from §4.1 | grep + import test |
| 4 | Singleton-reset autouse fixture wired in test files per §4.2 | grep |
| 5 | `speech_to_text_provider.py` reports 100% line + branch + function coverage (modulo `pragma: no cover` at lines 255 + 257) | `pytest --cov-branch --cov-fail-under=100` |
| 6 | `lupin_model_server/main.py` reports 100% line + branch + function coverage | `pytest --cov-branch --cov-fail-under=100` |
| 7 | Coverage gap closed on `embedding_provider.py` carveout-modified surfaces per §5 (per Q1 ratification, file-wide or carveout-scoped) | coverage diff |
| 8 | Coverage gap closed on `routers/speech.py` SpeechToTextProvider integration points per §6 | coverage diff |
| 9 | Coverage gap closed on `fastapi_app/main.py` lifespan switch branch per §8 | coverage diff |
| 10 | Audit report of `src/tests/smoke/test_embedding_api_smoke.py` + any speech smoke tests per §9 — documents which still pass via HTTP-proxy path | report file in `src/rnd/v0.1.7/2026.05.16-model-server-carveout/91-phase5-smoke-audit.md` |
| 11 | All new tests pass on `:7999` discretionary tier (per CLAUDE.md §TESTING VENUES — unit + non-destructive smoke) | `pytest src/tests/unit/test_speech_to_text_provider.py src/tests/unit/test_lupin_model_server_main.py` |
| 12 | Tabular pass/fail report posted per §"Testing Ownership Mandate" before declaring Phase 5 complete | result tablein follow-up notify |

---

## §13 Cross-references

- **Parent design**: [`01-design.md`](01-design.md) — full carve-out architecture, Phase 0-3 implementation, Phase 3.6 lifespan switch, baseline metrics
- **Baseline metrics**: [`90-baseline-metrics.md`](90-baseline-metrics.md) — Phase 0 capture of pre-carveout behavior
- **TODO entry**: `TODO.md` L17-55 — full Phase 4-8 follow-up list (Phase 5 is this doc's scope; Phase 4 / 6 / 7 / 8 are out of scope here)
- **Coverage mandate**: `feedback_100pct_coverage_multiplexer` (scope-expanded Lupin-wide 2026-05-16) — the load-bearing rule
- **Testing venues**: `CLAUDE.md` §TESTING VENUES — `:7999` (AI-discretionary) for these unit tests; `:8000` not needed since all new tests are mock-based + non-destructive + fast
- **Pattern to mirror**: `src/tests/unit/test_voice_persona_helpers.py` — mock-based unit-test reference per TODO L31
- **Sibling provider**: `src/cosa/memory/embedding_provider.py` — carve-out architecture mirror; pattern source for `SpeechToTextProvider` structure

---

## §14 Sequencing within Phase 5

Once Rick gives the go:

| Step | Action | Tier | Estimated time |
|---|---|---|---|
| 5.0a | Grep + inventory existing `test_embedding_provider.py` coverage | read-only | 5 min |
| 5.0b | Grep + identify carveout changes in `routers/speech.py` | read-only | 5 min |
| 5.0c | Read `src/lupin_model_server/main.py` end-to-end + refine §7 test list | read-only | 15 min |
| 5.0d | Audit existing smoke tests per §9 + serialize report to `91-phase5-smoke-audit.md` | read-only + doc | 20 min |
| 5.1 | Implement `mock_model_server_client` fixture in `src/tests/conftest.py` | code + test | 30 min |
| 5.2 | Implement `test_speech_to_text_provider.py` (the heaviest deliverable) | code + test | 90 min |
| 5.3 | Implement `test_lupin_model_server_main.py` | code + test | 60 min |
| 5.4 | Backfill `embedding_provider.py` carveout coverage gap | code + test | 45 min |
| 5.5 | Backfill `routers/speech.py` SpeechToTextProvider integration tests | code + test | 30 min |
| 5.6 | Backfill `fastapi_app/main.py` lifespan switch-branch tests | code + test | 30 min |
| 5.7 | Run full `pytest --cov-branch --cov-fail-under=100` on the 5 files; iterate to green | verify | 30 min |
| 5.8 | Serialize completion report `92-phase5-closure.md` with tabular pass/fail | doc | 15 min |

**Total estimate**: ~6 hours of focused work. Possible to land in a single substantive session if Rick approves the plan + Q1-Q4 decisions in one batch.

---

## §15 Idempotency marker

DRAFT-v1 — written 2026-05-17 by Tiberius 🌑 in coordinator-mode planning per broadcast `21bb12cd`. Awaiting Rick's go/review (no code lands until ratified). The 4 Q-decisions in §11 are batchable; can be ratified via a single `ask_multiple_choice` once Rick is back.
