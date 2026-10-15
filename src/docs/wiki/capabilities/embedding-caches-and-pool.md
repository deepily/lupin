---
capability: embedding-caches-and-pool
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.memory.embedding_cache_table.EmbeddingCacheTable@159fcbe284
  - cosa.memory.question_embeddings_table.QuestionEmbeddingsTable@03fe930f14
  - cosa.memory.embedding_manager.EmbeddingManager@9cda702dc4
  - cosa.memory.embedding_manager.generate_embedding@5b8776b54a
  - cosa.memory.embedding_manager.get_embedding_manager@33ae6d973f
  - cosa.memory.embedding_provider.get_embedding_provider@3f76a503e6
  - cosa.memory.embedding_provider.EmbeddingRoleUnsupported@5768fff1d0
  - cosa.memory.local_embedding_engine.get_code_engine@0cc38be9f1
  - cosa.memory.local_embedding_engine.get_prose_engine@98b07d0aab
  - cosa.memory.local_embedding_engine.device_class@b615d20fa6
  - cosa.memory.local_embedding_engine.vram_report@95ef4c4af8
  - cosa.memory.embedding_pool.BoundedEmbeddingPool@ed84ee6bf5
  - cosa.memory.embedding_pool.get_embedding_pool@5f018ae3c6
  - cosa.memory.embedding_pool.reconfigure_embedding_pool@7005235e1b
---
# Embedding caches and pool

The vector caches, the OpenAI manager, the engine accessors and the bounded pool that sit beside the [[embedding-pipeline]]. `EmbeddingProvider` stays the one call callers should use.

## What it does
- `EmbeddingCacheTable` stores a normalized text and its vector in Postgres. `has_cached_embedding`, `get_cached_embedding` and `cache_embedding` match by exact string.
- `QuestionEmbeddingsTable` does the same for a question. `get_embedding` returns the stored vector, or generates one on a miss without storing it. `add_embedding` appends a row.
- `EmbeddingManager` makes OpenAI embeddings with a cache and text normalization. `get_embedding_manager` returns its singleton, and the module-level `generate_embedding` calls it.
- `normalize_text_for_cache` extracts the gist, and may expand numbers and symbols to words, so equivalent text shares a cache key.
- `get_embedding_provider` returns the `EmbeddingProvider` singleton. `get_code_engine` and `get_prose_engine` return the two engine singletons.
- `device_class` names a device for the vector manifest. `vram_report` returns allocated, reserved and peak gigabytes for a CUDA device, and zeros without CUDA.
- `BoundedEmbeddingPool` is a fixed-size thread pool with a pending-slot budget. `get_embedding_pool` builds the process-wide pool from config on first call. `reconfigure_embedding_pool( max_workers, max_pending )` replaces the shared pool and shuts the old one down, so tuning needs no code change.
- `EmbeddingRoleUnsupported` is a `RuntimeError`, raised when a role is asked of a service that cannot honour it.

## Don't
- Don't expect `QuestionEmbeddingsTable.get_embedding` to fill the cache. A miss generates a vector and does not store it.
- Don't pass config to `get_embedding_pool` after the first call. Once the pool exists, the arguments are ignored.
- Don't call `reconfigure_embedding_pool` with `max_workers` under 1 or `max_pending` under 0. The constructor raises `ValueError`.

## Invariants
- A repository or session error in either cache table reaches the caller. A full pool makes `submit` return `False` and count the task in `dropped`.
