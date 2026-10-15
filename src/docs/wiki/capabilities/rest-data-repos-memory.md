---
capability: rest-data-repos-memory
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.db.repositories.embedding_cache_repository.EmbeddingCacheRepository@7701ed776c
  - cosa.rest.db.repositories.input_and_output_repository.InputAndOutputRepository@10c5fd8edf
  - cosa.rest.db.repositories.query_log_repository.QueryLogRepository@c669519d73
  - cosa.rest.db.repositories.question_embedding_repository.QuestionEmbeddingRepository@8bd9e2ca31
  - cosa.rest.db.repositories.solution_snapshot_repository.SolutionSnapshotRepository@200ac18582
---
# Memory table repositories

Five repositories sit under the question and solution memory. They are two exact-match embedding caches, the input and output log, the query telemetry log and the solution snapshots. What reads them is in [[solution-memory]] and [[embedding-pipeline]]; vector search itself is in [[db-repositories]].

## What it does
- `EmbeddingCacheRepository` is keyed on normalized text. It has `has_cached_embedding`, `get_cached_embedding` and `cache_embedding`. `QuestionEmbeddingRepository` is keyed on the question, with `has`, `get_embedding` and `add_embedding`. A get returns the embedding, or `None` when the key is missing or the row has no vector. Neither uses a vector index.
- `InputAndOutputRepository.insert_io_row` adds a row. `get_knn_by_input` is a nearest-k search over the input embedding, 10 by default. It returns `dot * 100` as the score. `get_all_qnr` lists the newest 50 rows whose input type starts `agent router go to`. `get_all_io` and `get_io_stats_by_input_type` read at most `max_rows` (1,000 by default), in no set order.
- `QueryLogRepository.log_query` appends one telemetry row. `get_recent_queries` returns newest first, and `get_cache_hit_stats` returns the verbatim, normalized and gist hit rates since a time.
- `SolutionSnapshotRepository` reads and writes by `id_hash`. `upsert_snapshot` creates or updates. Three cosine searches run over the question, code and solution embeddings, and each can exclude one `id_hash`. Their threshold defaults are 90, 85 and 85 percent and their limits 7, 20 and 20. `get_all_snapshots` loads every row with no limit.

## Don't
- Don't call `cache_embedding` or `add_embedding` for a key that is already stored. They insert without checking, so test with `has_cached_embedding` or `has` first.
- Don't call `get_all_snapshots` where a count or one lookup would do. It loads every row, and each row carries seven embeddings.
- Don't trust the stats of `get_io_stats_by_input_type`. It counts only `max_rows` rows taken in no set order, not the table.
- Don't read `get_knn_by_input` scores as cosine for unnormalized vectors. It uses the default inner product.

## Invariants
- The snapshot searches pass `metric="cosine"`. Their threshold is a percentage from 0 to 100. The limit applies first and the threshold after, so fewer than `limit` rows can come back.
- `upsert_snapshot` sets only the fields it is given and flushes. `delete_snapshot` returns whether a row existed and does not flush.
- No repository here commits.
- `get_cache_hit_stats` returns all rates as 0.0 when no rows match.
