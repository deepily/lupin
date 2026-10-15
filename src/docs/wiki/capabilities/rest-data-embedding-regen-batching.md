---
capability: rest-data-embedding-regen-batching
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.db.embedding_regeneration.plan_batches@c5b3996e2c
  - cosa.rest.db.embedding_regeneration.plan_batches_by_budget@49a49b54b6
  - cosa.rest.db.embedding_regeneration.bulk_update_shadow_sql@5f9169648a
  - cosa.rest.db.embedding_regeneration.AdaptiveBudget@537f9d2f2d
  - cosa.rest.db.embedding_regeneration.split_batch@1d5480dd2b
---
# Embedding regeneration: batching

How `fill` in [[rest-data-embedding-regeneration]] sizes the batches it sends to the embedder and how it writes the results back. A batch costs by its total text, not its row count. 256 typical texts embed fine; about eight of the longest run the shared GPU out of memory.

## What it does
- `plan_batches( ids, batch_size )` cuts a list into consecutive chunks of at most `batch_size`. `fill` uses it, at four times the batch size, only to bound each row fetch.
- `plan_batches_by_budget( items, size_of, char_budget=, max_count= )` starts a new batch when adding an item would pass `char_budget` or `max_count`. An item larger than the budget goes alone, not dropped.
- `AdaptiveBudget` holds the character budget a run is currently using. It starts at 40,000. A good batch grows it by a factor of 1.5, up to 2,000,000. A refused batch halves it, down to 5,000.
- `split_batch` cuts a refused batch into two halves. A batch of one or none returns `[]`, which the caller treats as a failure of that single row.
- `bulk_update_shadow_sql( table, pk, shadow_column )` returns one `UPDATE ... FROM ( VALUES %s )` statement. `fill` sends a whole chunk through it with one psycopg2 `execute_values` call, then commits.

## Don't
- Don't rely on the count limit alone. A few huge texts pass it and still exhaust memory.
- Don't pass table or column names from outside the specs. `bulk_update_shadow_sql` does no quoting.

## Invariants
- `plan_batches` and `plan_batches_by_budget` cover every item once, in order. Non-positive sizes raise `ValueError`; `AdaptiveBudget` also raises for `growth` of 1.0 or less, or inconsistent bounds.
- The budget only learns from whole-batch results. A dead embedding service is not counted as a failure.
