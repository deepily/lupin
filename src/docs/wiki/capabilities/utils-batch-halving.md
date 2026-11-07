---
capability: utils-batch-halving
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.utils.batch_halving.split_batch@1d5480dd2b
  - cosa.utils.batch_halving.embed_in_halves@d22a91fdb0
---
# Batch halving

A batch the embedder refuses is not proof that any text in it is bad. It may only have been too big for the memory free at that moment. Halving finds the real culprit, or success, in log2(n) tries. The vector builder ([[repo-tools-candidate-vector-build]]) and the database regeneration ([[rest-data-embedding-regen-batching]]) both use it.

## What it does
- `split_batch( batch )` returns two halves in order. A batch of one or none returns `[]`, which means it cannot be split.
- `embed_in_halves( embed, batch, alone_failed, ... )` calls `embed( batch )`. On any error it splits the batch and tries each half in turn, joining the results in order.
- A refused single item goes to `alone_failed( error, batch )`. The vector builder's raises. The regeneration's returns the row with no vector.
- `before_half( depth )` runs before each half, so the vector builder can pause. `on_failure( error, batch )` runs for each refused batch. `on_success( depth )` runs for each batch that fits, depth 0 being the whole batch.
- An error class in `passthrough` is never split. The regeneration passes `EmbeddingProviderUnreachable`, because a dead server fails at every size.

## Don't
- Don't put a retry loop of your own around it. The halves already retry.
