---
capability: needset-stage-seeds
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.stage_seeds.planted_ids@003815a1c4
  - lupin_mcp.reuse_needset.stage_seeds.interleave@435270e0af
  - lupin_mcp.reuse_needset.stage_seeds.sample_lang@79ea44451f
  - lupin_mcp.reuse_needset.stage_seeds.lists_sha@7d4dc7bc1f
  - lupin_mcp.reuse_needset.stage_seeds.draw_lists@4c8b1bfb4d
  - lupin_mcp.reuse_needset.stage_seeds.write_lists@93a5bb3cde
  - lupin_mcp.reuse_needset.stage_seeds.load_lists@b589b7d3bc
  - lupin_mcp.reuse_needset.stage_seeds.attribution_stage@873d1621cc
  - lupin_mcp.reuse_needset.stage_seeds.yield_stage@58e106fba2
---
# Need set: stage seeds

Draws the seed lists for the first 1,000 calls and builds the attribution and yield stage functions that read them. The draw makes no model call. The stages are run by the runner on [[needset-stages]].

## Drawing
- `draw_lists` draws 50 attribution seeds, 30 TypeScript and 20 Python, and 100 yield seeds, 50 of each language. Each language in the yield list has its own denominator.
- Only tracked files are used. No id of Set A's planted pairs is drawn, and the two lists share no id. A language that runs short raises `QUOTA_UNFILLABLE`.
- `sample_lang` seeds its random choice from the draw seed, the stage and the language. The order of the pool never changes the draw.
- `planted_ids` lists the proof ids of every planted pair. It adds the index id of each original, matched by file and name. The proof's ids are not the index's.
- `interleave` alternates the languages, so a run that stops part-way still holds both.

## Writing and reading
- `write_lists` writes the record to the run folder once, before any call. The same record again changes nothing, and a different one raises `PLAN_ALREADY_WRITTEN`.
- `lists_sha` hashes the record, and `load_lists` checks the format and the hash. A missing, changed or foreign file raises `MANIFEST_MISMATCH`.

## Stages
- `attribution_stage` reads the written file, makes a need for each seed in order and traces the needs. It reports the attribution summary with the seeds, needs and skipped seeds. With no need it stops the run and makes no trace.
- `yield_stage` reads the written file and runs the yield over its order. It reports the yield with the list hash and the seeds drawn per language.
