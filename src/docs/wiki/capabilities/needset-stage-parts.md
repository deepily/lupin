---
capability: needset-stage-parts
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.stage_parts.route_table@28c12f9bc9
  - lupin_mcp.reuse_needset.stage_parts.final_need_fn@f55d181246
  - lupin_mcp.reuse_needset.stage_parts.mark@c43da76f40
  - lupin_mcp.reuse_needset.stage_parts.counted@b290dae039
  - lupin_mcp.reuse_needset.stage_parts.Tally@a51b5f124a
  - lupin_mcp.reuse_needset.stage_parts.yield_row@4e34235d91
  - lupin_mcp.reuse_needset.stage_parts.build_parts@7fbdf91c8a
---
# Need set: stage parts

The live pieces of the attribution and yield stages. Each seed becomes a final need with no person in the loop, or it is counted and dropped.

## One seed
- `final_need_fn` returns the function for one seed. It finds a partner by the seed's route, has the drafter write the sentence, and has the second model check it against the partner's source.
- The need is final only when the second model agrees, with `final_source` model_agreed. A disagree or unsure answer is counted as disputed, its id is kept, and the need is never traced.
- A seed outside the search pool, with no partner, or with no sentence that passes the leak check is counted under `not_pooled`, `no_partner` or `draft_failed`.
- A seed whose same-job or check reply is unreadable twice is skipped and counted under `unreadable_reply`. Its id, code and detail go in `skipped`, and the stage goes on. Any other error, the call cap's included, still stops it.
- The second model may not be the drafter's model. That raises `CHECKER_EQUALS_DRAFTER` before the check.

## The parts
- `route_table` gives each listed seed its route, half and half within each stage and language.
- `build_parts` returns `make_need`, `prepare_fn`, `trace_fn`, the hardness `index` and the `tally`. The blocking model calls run on a worker thread, one seed at a time, under the cap's stage name.
- `yield_row` is the row the hardness step reads: seed, sentence, key symbols and language.
- `trace_fn` is `trace_all` over the run's context and trace ledger. The index and vector identity are read at build time and again at each trace, so a moved index is refused before a call.
- `Tally` counts the five reasons and keeps the disputed ids and the skipped seeds. `mark` notes where a stage began, and `counted` reports only what grew since, so each stage's `no_final_need` holds its own seeds.
