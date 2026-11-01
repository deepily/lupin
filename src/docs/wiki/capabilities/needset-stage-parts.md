---
capability: needset-stage-parts
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.stage_parts.route_table@28c12f9bc9
  - lupin_mcp.reuse_needset.stage_parts.final_need_fn@b72596fbc5
  - lupin_mcp.reuse_needset.stage_parts.mark@c43da76f40
  - lupin_mcp.reuse_needset.stage_parts.counted@b290dae039
  - lupin_mcp.reuse_needset.stage_parts.Tally@a51b5f124a
  - lupin_mcp.reuse_needset.stage_parts.yield_row@282d0350c1
  - lupin_mcp.reuse_needset.stage_parts.build_parts@0bdb752762
  - lupin_mcp.reuse_needset.stage_parts.RejectionLedger@5875c77214
  - lupin_mcp.reuse_needset.stage_parts.RejectionLedger.add@e3c1d53314
  - lupin_mcp.reuse_needset.stage_parts.RejectionLedger.rows@e754ceef84
---
# Need set: stage parts

The live pieces of the attribution and yield stages. Each seed becomes a final need with no person in the loop, or it is counted and dropped.

## One seed
- `final_need_fn` returns the function for one seed. By default no partner is searched for. The drafter writes the sentence from the seed alone, and the second model checks it against the seed's own source. So the seed is the need's known answer: a seed-answer need with key source `seed` and no route. With `partners` on, it first finds a partner by the seed's route, and the second model checks against the partner.
- The need is final only when the second model agrees, with `final_source` model_agreed. A disagree or unsure answer is counted as disputed, its id is kept, and the need is never traced.
- A seed outside the search pool is counted under `not_pooled`. A seed with no partner (partners on only) is counted under `no_partner`. A seed with no sentence that passes the copy and leak checks is counted under `draft_failed`.
- The `RejectionLedger` writes one flushed JSON line for each rejection. It records a rejected sentence with its failure details and a draft that ends rejected. It records a disputed need with the second model's result and note, and a skipped seed. It records a reply that could not be read, as raw text. The file is `ledger-rejections.jsonl` in the run folder.
- A seed whose same-job or check reply is unreadable twice is skipped and counted under `unreadable_reply`. Its id, code and detail go in `skipped`, and the stage goes on. Any other error, the call cap's included, still stops it.
- The second model may not be the drafter's model. That raises `CHECKER_EQUALS_DRAFTER` before the check.

## The parts
- `route_table` gives each listed seed its route, half and half within each stage and language.
- `build_parts` takes `partners` (off by default) and returns `make_need`, `prepare_fn`, `trace_fn`, the hardness `index` and the `tally`. The blocking model calls run on a worker thread, one seed at a time, under the cap's stage name.
- `yield_row` is the row the hardness step reads: seed, sentence, key symbols, language and `seed_is_answer`.
- `trace_fn` is `trace_all` over the run's context and trace ledger. The index and vector identity are read at build time and again at each trace, so a moved index is refused before a call.
- `Tally` counts the five reasons and keeps the disputed ids and the skipped seeds. `mark` notes where a stage began, and `counted` reports only what grew since, so each stage's `no_final_need` holds its own seeds.
