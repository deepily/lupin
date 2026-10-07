---
capability: solution-memory
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.memory.solution_snapshot.SolutionSnapshot@665a0d4e25
  - cosa.memory.snapshot_manager_interface.SolutionSnapshotManagerInterface@4420372f1f
  - cosa.memory.solution_manager_factory.SolutionSnapshotManagerFactory.create_from_config_manager@2e94505a85
  - cosa.memory.postgres_solution_manager.PostgresSolutionManager.save_snapshot@db62fbcce8
  - cosa.memory.two_tier_question_search.TwoTierQuestionSearch.lookup@2fbb24d57b
  - cosa.memory.two_tier_question_search.CacheLookup@ce53ddc2b7
  - cosa.memory.two_tier_question_search.pg_hierarchical_search@1c023a232c
  - cosa.memory.input_and_output_table.InputAndOutputTable.insert_io_row@4a230f6918
  - cosa.memory.query_log_table.QueryLogTable.log_query@b3ad025a7f
---
# Solution memory

Solution memory stores answered questions as snapshots, finds a cached snapshot for a new question, and logs every query and its input and output. Postgres with pgvector is the only backend.

## What it does
- `SolutionSnapshot` is one stored answer, its code and its seven embedding columns. `SolutionSnapshotManagerInterface` is the storage contract.
- `SolutionSnapshotManagerFactory.create_from_config_manager` builds the manager from the INI key `solution snapshots manager type`. `ManagerType` has the one value `postgres`.
- `PostgresSolutionManager` saves, fetches, deletes and searches snapshots through `SolutionSnapshotRepository`. It keeps no in-memory lookup, so every search goes to Postgres: exact synonym probes first, then pgvector.
- `TwoTierQuestionSearch.lookup` is the v2 flow's read-only lookup. Tier 1 is exact SQL, verbatim and then normalized. Tier 2 embeds the question and probes nearest-neighbour.
- `pg_hierarchical_search` is the manager's own two-tier lookup. It returns `(percent, snapshot)` pairs and deletes ghost synonyms.
- `InputAndOutputTable.insert_io_row` stores an input and output pair with embeddings. `QueryLogTable.log_query` appends one row per query.

## Don't
- Don't add a write to `TwoTierQuestionSearch.lookup`. The v2 flow relies on its reads staying free of side effects.
- Don't decide a replay from a similarity score. `CacheLookup.is_replay_hit` is true only for a tier-1 exact hit, and tier 2 never sets it.
- Don't merge the two lookups into one core. Their contracts differ: one cleans up ghosts and returns tuples, the other does neither.
- Don't import a LanceDB module here. The Postgres path must not reach it, and a unit test guards the v2 side.

## Invariants
- A synonym row pointing at a missing snapshot, a ghost, counts as a miss in `lookup`. The manager's search removes it.
- Tier 2 asks for candidates at or above 70 percent by default. The caller applies its own higher decision floor, and `best_score` is recorded even when it falls below that.
- `save_snapshot` upserts by verbatim question. An existing row for that question keeps its `id_hash`. A database or upsert failure returns `False`. An uninitialized manager or an empty question still raises.
- With async embedding on and an embedding missing, `insert_io_row` returns at once. The row is built on the shared bounded pool.
- A failed async insert drops the row. `async_failure_count` counts the losses, and nothing retries them. A row refused by a full pool is counted in the pool's `dropped` instead.
- `_orm_to_snapshot` pads or truncates a vector to the embedding dimension, and an empty one becomes zeros.
