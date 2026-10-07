---
capability: embedding-pipeline
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.memory.embedding_provider.EmbeddingProvider@34ec7500d3
  - cosa.memory.embedding_provider.EmbeddingProvider.generate_embedding@a98f0d354b
  - cosa.memory.embedding_provider.EmbeddingProvider.declare_in_process_engine_owner@a4cbc76f67
  - cosa.memory.embedding_provider.EmbeddingProviderUnreachable@eba06d26f9
  - cosa.memory.embedding_pool.BoundedEmbeddingPool.submit@39bc28ad1f
  - cosa.memory.local_embedding_engine.ProseEmbeddingEngine@be0afcade0
  - cosa.memory.local_embedding_engine.CodeEmbeddingEngine@24592454ec
  - cosa.rest.db.repositories.vector_search.dot_topk@0e6969973e
  - cosa.rest.db.embedding_regeneration.validate_fresh_vector@f9e88a64f7
---
# Embedding pipeline

This capability turns text into vectors, caches them, and searches them in Postgres. `EmbeddingProvider.generate_embedding` is the one call callers should use.

## What it does
- `EmbeddingProvider` routes on the INI key `embedding provider`: `openai` uses `EmbeddingManager`, and `local` uses the Prose or Code engine. The caller picks `content_type` of `prose` or `code`.
- With a non-openai provider, a process that does not own the GPU engines sends the same call over HTTP. The target is `LUPIN_MODEL_SERVER_URL`, then the `model server url` key, else `/api/embeddings` on the app server.
- `ProseEmbeddingEngine` and `CodeEmbeddingEngine` are lazy singletons that load their models on first use. Only `lupin_app/main.py` calls `declare_in_process_engine_owner`.
- It skips that call when `speech to text provider` is `model-server`. Then every non-openai embedding call goes over HTTP.
- `BoundedEmbeddingPool.submit` runs background embedding work on a capped pool. It never blocks the caller.
- `EmbeddingCacheTable` and `QuestionEmbeddingsTable` store vectors through repositories. `dot_topk` finds the nearest rows by inner product.
- `embedding_regeneration` re-embeds the three vector columns in `REGEN_SPECS` through `plan`, `fill` into shadow columns, and `swap`. `ensure-columns` and `verify` are separate commands, and `swap` runs `verify` first.

## Don't
- Don't load a GPU model in a script or test. Call the provider and let it use HTTP.
- Don't treat a dot-product score as a percentage unless both vectors are unit length. Pass `metric="cosine"` to `dot_topk`.
- Don't mix vectors from two models in one table. Both emit 768 dimensions as configured, so nothing fails, and the scores are wrong.
- Don't retry a smaller batch on `EmbeddingProviderUnreachable`. It is raised after every retry is spent on a transport error or a retryable status: 429, 500, 502, 503 or 504. The service has not given a good answer, so a smaller retry fails the same way.

## Invariants
- A non-owner process never touches the GPU. When HTTP cannot complete, the call raises `RuntimeError`.
- HTTP retries cover transport failures and 429, 500, 502, 503 and 504. Any other 4xx is raised on the first attempt.
- Embedding calls are blocking. The `/api/embeddings` endpoints run them in a thread so the event loop stays free.
- When the pool's backlog is full, new work is dropped and counted. The caller is not told to wait.
- `swap` refuses unless verification passes. `validate_fresh_vector` rejects a vector that is missing, the wrong size, not finite, or outside the model's norm band.
- `dot_topk` defaults to inner product, and `cosine` is opt-in per caller.
