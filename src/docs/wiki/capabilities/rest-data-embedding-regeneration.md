---
capability: rest-data-embedding-regeneration
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.db.embedding_regeneration.RegenSpec@067977b412
  - cosa.rest.db.embedding_regeneration.qualify@dc8510ea92
  - cosa.rest.db.embedding_regeneration.is_excluded@f5b6c888c4
  - cosa.rest.db.embedding_regeneration.excluded_ids_clause@2a5f1170a2
  - cosa.rest.db.embedding_regeneration.shadow_column_ddl@4925e11054
  - cosa.rest.db.embedding_regeneration.classify_norm@9a33c333d3
  - cosa.rest.db.embedding_regeneration.l2_norm@37bc13134d
  - cosa.rest.db.embedding_regeneration.summarize_verification@dbdb3b568e
---
# Embedding regeneration: scope and verification

`python -m cosa.rest.db.embedding_regeneration` re-embeds stored text with the current model, in three named steps. `plan` is read only and is the default. `fill` writes shadow columns only. `swap` is the one destructive step. `ensure-columns` and `verify` are the other two commands. Old rows hold OpenAI vectors and newer rows hold local nomic vectors. Both are 768 wide, so nothing failed loudly.
Run control is in [[rest-data-embedding-regen-run-control]] and batching in [[rest-data-embedding-regen-batching]]. The runtime embedding path is in [[embedding-pipeline]].

## What it does
- A `RegenSpec` names one target: a label, a table, its key, a text column, the live vector column, a shadow column and a content type. `REGEN_SPECS` lists three, labelled `io_input`, `io_output` and `decisions`: `input_and_output.input`, `input_and_output.output_final` and `prediction_decisions.question`. `--only=<label>` limits a run to one.
- Scope is every row that has source text, not every row that looks stale. A norm cannot say which model made a vector.
- `qualify` puts a table prefix such as `regen_probe.` in front of a table name, so a whole run can target a clone. A non-empty prefix must end in a dot or it raises `ValueError`.
- `is_excluded` and `excluded_ids_clause` keep the deliberate bad fixture row `clamp-001` out of scope, in Python for `fill` and in SQL for `verify` and `plan`.
- `shadow_column_ddl` returns one `ADD COLUMN IF NOT EXISTS ... vector(768)` statement per spec. It is safe to apply twice.
- `l2_norm` is the Euclidean norm. `classify_norm` calls a norm `normalized` at 1.01 or less, `current` from 5.0 to 60.0 and `suspect` otherwise.
- `summarize_verification` returns `ok` only when every in-scope row is filled and no vector has a bad norm or dimension.

## Don't
- Don't pick rows by norm. The band only checks fresh vectors. `validate_fresh_vector` applies it, and `fill` prints `REJECTED` for a vector outside it, skips that row and carries on. `verify` then blocks `swap`, because the row is unfilled. An unreachable embedding service aborts the run.
- Don't run `swap` before `verify` passes. `swap` repeats the check and refuses on its own.
- Don't drop `clamp-001` from the exclusion list. Counted by `verify`, it can never be filled, so the swap would stay blocked.

## Invariants
- `fill` never writes a live vector column. Only `swap` does.
- Applying anything needs `--apply`; without it `ensure-columns`, `fill` and `swap` print what they would do.
