---
capability: rest-data-embedding-regen-run-control
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.db.embedding_regeneration.should_proceed@aeac709481
  - cosa.rest.db.embedding_regeneration.is_off_peak@5f0ceef609
  - cosa.rest.db.embedding_regeneration.checkpoint_path@ca8526172e
  - cosa.rest.db.embedding_regeneration.load_checkpoint@151d5bf412
  - cosa.rest.db.embedding_regeneration.save_checkpoint@60510dd9cb
  - cosa.rest.db.embedding_regeneration.remaining_ids@e4feab66f5
---
# Embedding regeneration: run control

These functions decide whether a `fill` pass may start and let an interrupted pass resume. They sit beside [[rest-data-embedding-regeneration]]; the batching that happens once a pass is running is in [[rest-data-embedding-regen-batching]].

## What it does
- `should_proceed( busy=, hour_edt=, force= )` returns `None` when a pass may start and a refusal sentence otherwise.
- The busy flag is the real gate. `True` refuses, and `None` (the probe could not answer) also refuses, because the check exists so nobody guesses about a server in use.
- The clock check runs only when `force` is false and an hour is given. `force` skips the clock and never the busy check.
- `is_off_peak( hour_edt, end_hour )` is true for hours from 0 up to, not including, `end_hour`. The module default `OFF_PEAK_END_HOUR` is 24, so today every hour passes. Pass a smaller `end_hour` to bring a window back.
- `checkpoint_path( label, scratch_dir )` is `regen-checkpoint-<label>.json` under the scratch directory, one file per spec.
- `load_checkpoint` returns `{"done_ids": []}` for a missing file and raises `ValueError` for a file that is not valid JSON.
- `save_checkpoint` writes a temp file and renames it over the checkpoint, so a crash leaves the old one.
- `remaining_ids` drops ids already done, compares them as strings, and keeps the original order.

## Don't
- Don't read a `None` busy answer as idle. It means unknown.
- Don't delete a corrupt checkpoint to get past the error. It would restart a run of tens of thousands of rows from zero.

## Invariants
- `fill` saves its checkpoint after every committed chunk, so a re-run redoes only what was not committed.
- A `fill` aborts, with a message, when the embedding service is unreachable. It does not split the batch or record it as a size failure.
