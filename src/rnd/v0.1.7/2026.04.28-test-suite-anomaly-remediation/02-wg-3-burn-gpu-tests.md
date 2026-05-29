# WG-3 — BURN the GPU-touching tests (6 FAILs deleted, not fixed)

## Standing rule

Per `feedback_never_grab_gpu` (and 2026-04-28 corollary) + `feedback_tests_call_server_api_not_instantiate`: tests are FORBIDDEN from touching GPU/CUDA/embedding engines. Earlier draft of this plan proposed "VRAM headroom guards" — that is itself a forbidden fix because it perpetuates a forbidden test path. The correct response is **DELETION**.

Embedding work belongs to the FastAPI server's `/api/embeddings/batch` endpoint. Tests call the endpoint, never instantiate `ProseEmbeddingEngine` / `CodeEmbeddingEngine` / `LocalEmbeddingEngine` in-process.

## Audit + deletion

### Audit command

```
grep -rln 'torch\.cuda\|mem_get_info\|EmbeddingEngine\(\|cuda:0' src/tests/
```

### Expected hits → action

| File | Action | Justification |
|------|--------|---------------|
| `src/tests/smoke/test_embedding_benchmark.py` | **DELETE** | Loads models in-process; benchmarks are operator tooling, belong in `src/scripts/`. |
| `src/tests/smoke/test_local_embedding_smoke.py` | **DELETE** | All 5 tests instantiate engines locally. Routing/metrics coverage already lives in `src/tests/unit/test_local_embedding_engine.py` with mocked engines. |
| any other match | **DELETE** or rewrite to call `/api/embeddings/batch` | Same rule. |

### Allowed exception

PEFT trainer — operator-launched, GPU-monopolizing, not part of automated suites. If `src/tests/` has a PEFT-trainer test (must be confirmed by audit), it stays. WG-4 covers PEFT separately (import-time guard).

## Optional replacement coverage

If post-audit any embedding-API regression risk is identified, add an integration test calling `POST /api/embeddings/batch` against `:7999` that asserts response shape + non-empty vectors. No GPU touch in the test itself.

```python
# src/tests/integration/test_embeddings_api.py
def test_embeddings_api_smoke( authed_client ):
    payload = { "texts": [ "hello world" ], "engine": "prose" }
    r = authed_client.post( "/api/embeddings/batch", json=payload )
    assert r.status_code == 200
    body = r.json()
    assert "vectors" in body
    assert len( body[ "vectors" ] ) == 1
    assert len( body[ "vectors" ][ 0 ] ) > 0
```

## Acceptance

- `git ls-files src/tests/` returns no file matching the audit grep (after deletes).
- The 6 prior FAILs (5 in `test_local_embedding_smoke` + 1 in `test_embedding_benchmark`) no longer exist (file removed).
- Optional replacement integration test passes against `:7999`.

## Files

- `src/tests/smoke/test_embedding_benchmark.py` — **DELETED**
- `src/tests/smoke/test_local_embedding_smoke.py` — **DELETED**
- (optional) `src/tests/integration/test_embeddings_api.py` — NEW
- audit output → 90-execution-log.md

## Status

- [ ] Audit grep
- [ ] Delete `test_embedding_benchmark.py`
- [ ] Delete `test_local_embedding_smoke.py`
- [ ] (optional) Replacement integration test
- [ ] `pytest src/tests/` passes module collection without these files
