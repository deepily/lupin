---
capability: needset-first-thousand
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.planted_pool.planted_entry@79f54086e3
  - lupin_mcp.reuse_needset.planted_pool.PlantedVectors@067b309b7a
  - lupin_mcp.reuse_needset.planted_pool.embed_rows@a9fb35daa4
  - lupin_mcp.reuse_needset.planted_pool.PlantedCandidateStage@f3fa9a9d90
  - lupin_mcp.reuse_needset.first_thousand.read_latest_labels@e66a6cadd1
  - lupin_mcp.reuse_needset.first_thousand.remainder_pairs@e6db44db98
  - lupin_mcp.reuse_needset.first_thousand.draft_control_needs@b7d264a6e8
  - lupin_mcp.reuse_needset.first_thousand.planted_check@53d07356ce
  - lupin_mcp.reuse_needset.first_thousand.control_ask@e9868056c1
  - lupin_mcp.reuse_needset.first_thousand.remainder_stage@0cf94530e9
---
# Need set: the first 1,000 calls

The pieces under the control and the remainder of Set B's first 1,000 model calls; the command is on [[needset-first-thousand-command]]. The control itself is on [[needset-positive-control]]. The attribution and yield stages and the shared cap come from the stage runner and are handed in.

## The planted pool
- `planted_entry` turns a rewrite into the index record the search and the judge read. A real rewrite has no docstring, so its doc is empty. Its pin is a hash of its text. Its language is the rewrite's own, never read from the file suffix.
- `embed_rows` embeds the planted records through our own embedding server, with the same texts, engines and roles as the vector build. A plant with a purpose line embeds it as a real entry does. These are embedding calls, not model calls.
- `PlantedVectors` stacks those rows under the live vector set in memory. The live set is not changed, and its manifest hash stays the live one.
- `PlantedCandidateStage` is the candidate stage client, answering the stage upload and the search from this process. It refuses a refresher, so nothing can rebuild or write the live vector set. It writes query vectors to the cache folder it is given, which must be a scratch folder of the run and never the live cache. `last_answer` keeps the latest search with every list whole, so a rank can be read. The control then tests both halves of the search.

## The control
- `planted_check` asks the checker about one need over a pool that holds the planted records. It adds them to the entries the judge may be asked about and swaps the stage on a copy of the context. The seed is left out as in `check_need`. When the caller gives the plants' purpose lines, each plant carries its line through the same `attach_purposes` call that gives a real entry its line. So the judge reads a plant as it reads a real entry. Before 2 November 2026 it did not, and the judge saw a plant as its id and signature alone.
- `judge-readings.json` sits beside `stage-reports.json`. For each pair and pass it holds the judge's reading of the plant and of the original. A reading has a status (judged, or not judged with the reason), a cache key, `p_overlap`, `confidence` and `choice`. Beside it are the entry's rank in each source list and what each list added to its fused score (`control_report.fusion_terms`). A `SweepTap` in `judge_readings.py` writes each reading down as the live check's sweeper returns it and changes nothing the checker sees. The file is derived from the report's rows, so the two cannot disagree. The fusion terms leave out the forced top-five head of `rank_fusion.fuse`, so an entry can sit on the shortlist with a small total.
- `draft_control_needs` writes the need sentence of each pair, one at a time, with the drafter that writes real Set B needs. Each pair drafts on a worker thread. Those calls count toward the cap, under the running stage. Each pair gets `CONTROL_TRIES` (four) tries. A pair that never passes raises `CONTROL_NEED_UNDRAFTED`, or goes to `on_undrafted` when the caller gives one.
- `control_ask` builds the ask function the control stage takes, from the drafted needs and a checker. An optional observer sees each pair's receipt, which is how the scored rows are built.

## The remainder
- `read_latest_labels` reads label files for reading only and keeps the latest label of each item.
- `remainder_pairs` puts each of the 20 pairs in a group from the two reviewers' labels. Drifted means both reviewers chose none. Unsure means either note starts with the unsure marker. A pair with both is drifted.
- On the proof's labels that gives 3 drifted, 10 unsure and 7 other. Twelve pairs carry an unsure flag, and two of them are also drifted.
- `remainder_stage` runs the run-check on them and adds `unsure_flagged`, the count over all twelve flagged pairs. Its text reads "12 of 20, with 2 also drifted". No model is contacted.
