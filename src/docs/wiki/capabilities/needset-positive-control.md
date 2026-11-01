---
capability: needset-positive-control
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.positive_control.load_pairs@c4a0820cce
  - lupin_mcp.reuse_needset.positive_control.pool_digest@1bbb275579
  - lupin_mcp.reuse_needset.positive_control.plant@88bc6b0a26
  - lupin_mcp.reuse_needset.positive_control.lexical_find@99d6d6cd8e
  - lupin_mcp.reuse_needset.positive_control.run_control@5b01db1eea
  - lupin_mcp.reuse_needset.positive_control.snapshot@5552f6a3f4
  - lupin_mcp.reuse_needset.positive_control.check_restored@016460cbc1
  - lupin_mcp.reuse_needset.stage3.need_for@cd0a64c87b
  - lupin_mcp.reuse_needset.stage3.control_stage@f6ab58d294
---
# Need set: positive control

The one-time check that the checker finds a duplicate that is known to be there. It plants Set A's 20 synthetic pairs, asks the checker about each, removes them, and proves the pool is as it was. It makes no model call itself. Part of [[needset-smoke-run]]'s family of tools.

## The pairs
- `load_pairs` reads the proof's `planted.json` for reading only, and keeps the 20 entries of stratum `opus-work-alike` (12 TypeScript, 8 Python). The file's sha256 must be the recorded one and the count must be 20, or it raises `CONTROL_INPUT_CHANGED`.

## Planting and removing
- `plant` returns a copy of the pool with each rewrite added as an index record. The pool passed in is not changed. A rewrite whose id is already in the pool, or planted twice, raises `CONTROL_ID_COLLIDES`.
- Planting is in memory only. Nothing goes to the symindex, the vector store or the proof's evidence folder.
- `pool_digest` fingerprints a pool as the sha256 of its canonical JSON.

## Finding
- `run_control` takes a find function, `find( planted pool, pair )`, that returns the ids the checker asked about. A pair is found when its rewrite id is among them, and the report lists the missed rewrite ids.
- `snapshot` records the pool's digest and stage ids. `check_restored` compares the pool with a snapshot and raises `CONTROL_NOT_RESTORED` on any difference.
- `run_control` checks the pool against a snapshot after the run. It takes the snapshot itself unless the caller passes one taken earlier.
- `lexical_find` makes a find function from the word stage alone, so it needs no model call. A caller who wants the full checker passes its own function. That checker is `loss_trace.check_need`, read through `loss_trace.asked_ids`. A full check counts against the shared 1,000-call cap.
- Rewrites have no vector rows, so only the word half of the candidate stage can find them.
- A real rewrite has no `module` or `doc` field, so its planted record holds an empty module and doc. The word stage then finds it by id, name and signature only.

## Stage 3
- `control_stage` returns the zero-argument async function the stage runner takes for its control stage. It snapshots the pool, plants, and awaits the caller's `ask( planted pool, pair )` once per pair in file order.
- It then calls `run_control` with the answers and the earlier snapshot. A trace left by an ask is caught as well as one left by the plant.
- The report is `run_control`'s plus `by_lang` (found and total per language) and `restored`. It carries `stop` true when any pair was missed.
- `need_for` builds the need record the checker takes. The seed is the original's id, so the checker leaves the original out and can find only the rewrite.
- The module makes no call. The calls the checker makes go through the cap that the runner has installed.
