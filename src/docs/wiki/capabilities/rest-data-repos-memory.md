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
- `EmbeddingCacheRepository` (keyed on normalized text) and `QuestionEmbeddingRepository` (keyed on the question) each answer `has` and add one. Each returns a stored embedding or `None`. Neither uses a vector index.
- `InputAndOutputRepository.insert_io_row` adds a row. `get_knn_by_input` is a nearest-k search over the input embedding. `get_all_qnr` lists the newest agent-router rows. `get_all_io` and `get_io_stats_by_input_type` scan at most `max_rows`.
- `QueryLogRepository.log_query` appends one telemetry row. `get_recent_queries` returns newest first, and `get_cache_hit_stats` returns the verbatim, normalized and gist hit rates since a time.
- `SolutionSnapshotRepository` reads and writes by `id_hash`. `upsert_snapshot` creates or updates. Three cosine searches run over the question (90 percent), code (85) and solution (85) embeddings, and each can exclude one `id_hash`.

## Don't
- Don't call `cache_embedding` or `add_embedding` for a key that is already stored. They insert, and the repository does not check first.
- Don't trust the stats of `get_io_stats_by_input_type`. It counts only the first `max_rows` rows, not the table.
- Don't read `get_knn_by_input` scores as cosine for unnormalized vectors. It uses the default inner product.

## Invariants
- The snapshot searches pass `metric="cosine"`. Their threshold is a percentage from 0 to 100.
- `upsert_snapshot` sets only the fields it is given and flushes. `delete_snapshot` returns whether a row existed and does not flush.
- No repository here commits.
- `get_cache_hit_stats` returns all rates as 0.0 when no rows match.
