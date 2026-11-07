---
capability: needset-control-scoring
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.planted_purposes.stage_sources@187dea5976
  - lupin_mcp.reuse_needset.planted_purposes.write_lines@fa3a2a9983
  - lupin_mcp.reuse_needset.planted_purposes.load_lines@51f189492a
  - lupin_mcp.reuse_needset.planted_purposes.merged_store@8bf78fbc86
  - lupin_mcp.reuse_needset.planted_purposes.main@ac7a5240ed
  - lupin_mcp.reuse_needset.control_report.same_job_labels@e94e92292d
  - lupin_mcp.reuse_needset.control_report.ranks_of@036d420ae3
  - lupin_mcp.reuse_needset.control_report.pair_row@fae561963e
  - lupin_mcp.reuse_needset.control_report.figures@12494561e3
  - lupin_mcp.reuse_needset.control_report.scored@812d8bd008
  - lupin_mcp.reuse_needset.planted_purposes.lines_path@458ba28195
  - lupin_mcp.reuse_needset.planted_purposes.is_ignored@080de7aef9
  - lupin_mcp.reuse_needset.control_report.content_words@6945de07d6
  - lupin_mcp.reuse_needset.control_report.word_overlap@b4707892e5
  - lupin_mcp.reuse_needset.control_report.position@2113b62ebe
  - lupin_mcp.reuse_needset.control_report.count@8aa11d89f6
---
# Need set: the control's purpose lines and scoring

The control plants 20 rewrites and scores whether the checker finds them. A real index entry has a one-line purpose written once by a bounded job, and a bare plant has none. The planted pool is on [[needset-first-thousand]]; the command is on [[needset-first-thousand-command]].

## The plants' purpose lines
- `stage_sources` copies each rewrite's text to a gitignored file in the run folder and lists a symbols row pointing at it. The planted entry keeps the rewrite's recorded file.
- `write_lines` asks the production writer for a line per plant: same prompt, screen and version string. The lines go to the run folder's `purpose-plants/purpose.jsonl`, never the live store.
- `load_lines` reads them by pin and lists any plant with none. `merged_store` writes the live lines plus the plants' for the planted stage to read.
- `main` runs the one bounded job, the only model spend. `lines_path` names the store; `is_ignored` asks git if a path is ignored.

## The scored report
- `same_job_labels` settles each pair from the two reviewers, with the third rater on disputes. It refuses a not-same set other than the five pinned ones, and records the label files' hashes.
- `pair_row` builds one pair's row from the checker's receipt. Retrieved means in the ids sent to the judge. Accepted means retrieved and rated relevant. Given the live check's judge sweeps, the plant and original also carry `fusion` and `judge` ([[needset-judge-readings]]).
- `ranks_of` gives a plant's place in each source list and in the merged list, read to its end. `position` is the place of one id in one list.
- `figures` scores one population: retrieval, judge given retrieval and end to end, each a `count` with a Wilson interval. Undrafted pairs count as misses in the intention-to-treat figures.
- `word_overlap` measures the leakage audit over each text's `content_words`: the share a need and a purpose line share. `finalize.file_sha256` hashes the label files.
- The pass mark compares each plant with its own original, found by one search where both compete. It passes when originals found and plants missed exceed the reverse by at most two, over drafted pairs only.
- `retrieval_bare` counts plants found with no purpose line, from a second planted stage whose transport refuses every request. `scored` splits the 15 same-job pairs from the 5 others, a negative control. The originals' rate has a Wilson interval beside the attribution stage's 27 of 37; nothing stops the run.
