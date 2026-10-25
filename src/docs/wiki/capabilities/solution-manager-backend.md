---
capability: solution-manager-backend
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.memory.postgres_solution_manager.PostgresSolutionManager@c3a5f3f131
  - cosa.memory.solution_manager_factory.SolutionSnapshotManagerFactory@75ad062323
  - cosa.memory.solution_manager_factory.ManagerType@1894b2c710
  - cosa.memory.snapshot_manager_interface.PerformanceMetrics@dba6d0c92e
  - cosa.memory.snapshot_manager_interface.PerformanceMonitor@5b0e793b84
  - cosa.memory.two_tier_question_search.TwoTierQuestionSearch@c80afd94e5
  - cosa.memory.two_tier_question_search.pg_record_to_snapshot@a3cc6f84d9
  - cosa.memory.two_tier_question_search.snapshot_to_pg_record@49cf1d5417
  - cosa.memory.two_tier_question_search.pg_similarity_search@0574a1359f
  - cosa.memory.two_tier_question_search.update_canonical_synonyms@0c89bbc823
  - cosa.memory.input_and_output_table.InputAndOutputTable@435742516d
  - cosa.memory.query_log_table.QueryLogTable@cebc583dcf
---
# Solution manager backend

The Postgres snapshot manager, its factory and converters, and the two logging tables behind [[solution-memory]]. Read that page first for the flow.

## What it does
- `PostgresSolutionManager` implements the snapshot manager interface over `SolutionSnapshotRepository`. `initialize` builds no in-memory lookups, and `reload` is a no-op.
- `get_snapshot_by_id` returns a snapshot or `None`. `delete_snapshot` deletes by verbatim question, cascades its canonical synonyms, and returns `True` when the row was found.
- `get_snapshots_by_question`, `get_snapshots_by_code_similarity` and `get_snapshots_by_solution_similarity` return `(percent, snapshot)` pairs, highest first. The last two wrap `pg_similarity_search`.
- `get_gists` and `get_all_snapshots` return `[]` on error. `get_stats` fixes `storage_size_mb` at 0.0, and `health_check` pings the store through it and never raises.
- `SolutionSnapshotManagerFactory.create_manager` builds a manager from a `ManagerType` or its string. `get_available_types` lists them, and `ManagerType.from_string` raises `ValueError` for an unknown name.
- `snapshot_to_pg_record` and `pg_record_to_snapshot` convert between a snapshot and a database record. `update_canonical_synonyms` indexes a snapshot's questions in the synonyms table.
- `PerformanceMonitor` times an operation with `start` and `stop`. `get_metrics` returns a `PerformanceMetrics`, which `to_dict` serializes.
- `TwoTierQuestionSearch` is the read-only lookup, and `pg_hierarchical_search` is the manager's own.
- `InputAndOutputTable` also answers `get_knn_by_input`, `get_all_io`, `get_io_stats_by_input_type` and `get_all_qnr`, each bounded by `k` or `max_rows`.
- `QueryLogTable` reads back with `get_recent_queries`, newest first, and `get_cache_hit_stats` for the last N days.

## Don't
- Don't expect `reload` to refresh anything. There is no in-memory cache to refresh.
- Don't read `storage_size_mb` as a size. It is always 0.0.
- Don't treat a `[]` from `get_gists` or `get_all_snapshots` as an empty store. It is also the answer to a failure.

## Invariants
- The save, delete, search, gist, list and stats calls raise `RuntimeError` when the manager is not initialized. An empty question or a threshold outside 0 to 100 raises `ValueError`.
