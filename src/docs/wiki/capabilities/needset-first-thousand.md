---
capability: needset-first-thousand
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.planted_pool.planted_entry@c229017988
  - lupin_mcp.reuse_needset.planted_pool.PlantedVectors@067b309b7a
  - lupin_mcp.reuse_needset.planted_pool.embed_rows@30d6bee774
  - lupin_mcp.reuse_needset.planted_pool.PlantedCandidateStage@80e5c6ec63
  - lupin_mcp.reuse_needset.first_thousand.read_latest_labels@e66a6cadd1
  - lupin_mcp.reuse_needset.first_thousand.remainder_pairs@f953eb07d3
  - lupin_mcp.reuse_needset.first_thousand.draft_control_needs@62f1f1ebb1
  - lupin_mcp.reuse_needset.first_thousand.planted_check@f29004ed70
  - lupin_mcp.reuse_needset.first_thousand.control_ask@fa3a692e9a
  - lupin_mcp.reuse_needset.first_thousand.remainder_stage@0cf94530e9
---
# Need set: the first 1,000 calls

The pieces under the control and the remainder of Set B's first 1,000 model calls; the command is on [[needset-first-thousand-command]]. The control itself is on [[needset-positive-control]]. The attribution and yield stages and the shared cap come from the stage runner and are handed in.

## The planted pool
- `planted_entry` turns a rewrite into the index record the search and the judge read. A real rewrite has no docstring, so its doc is empty. Its pin is a hash of its text.
- `embed_rows` embeds the planted records through our own embedding server, with the same texts, engines and roles as the vector build. These are embedding calls, not model calls.
- `PlantedVectors` stacks those rows under the live vector set in memory. The live set is not changed, and its manifest hash stays the live one.
- `PlantedCandidateStage` is the candidate stage client, answering the stage upload and the search from this process. It refuses a refresher, so nothing can rebuild or write the live vector set. The control then tests both halves of the search.

## The control
- `planted_check` asks the checker about one need over a pool that holds the planted records. It adds them to the entries the judge may be asked about and swaps the stage on a copy of the context. The seed is left out as in `check_need`.
- `draft_control_needs` writes the need sentence of each pair, one at a time, with the drafter that writes real Set B needs. Those calls count toward the cap. A sentence that does not pass raises `CONTROL_NEED_UNDRAFTED`.
- `control_ask` builds the ask function the control stage takes, from the drafted needs and a checker.

## The remainder
- `read_latest_labels` reads label files for reading only and keeps the latest label of each item.
- `remainder_pairs` puts each of the 20 pairs in a group from the two reviewers' labels. Drifted means both reviewers chose none. Unsure means either note starts with the unsure marker. A pair with both is drifted.
- On the proof's labels that gives 3 drifted, 10 unsure and 7 other. Twelve pairs carry an unsure flag, and two of them are also drifted.
- `remainder_stage` runs the run-check on them and adds `unsure_flagged`, the count over all twelve flagged pairs. Its text reads "12 of 20, with 2 also drifted". No model is contacted.
