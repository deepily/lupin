---
capability: needset-smoke-run
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.smoke.in_window@3e463bf907
  - lupin_mcp.reuse_needset.smoke.parse_args@f96e6b5b34
  - lupin_mcp.reuse_needset.smoke.kind_split@9af7ff40ce
  - lupin_mcp.reuse_needset.smoke.Timed@265424ee74
  - lupin_mcp.reuse_needset.smoke.index_parts@da503efe90
  - lupin_mcp.reuse_needset.smoke.candidate_parts@307e96b916
  - lupin_mcp.reuse_needset.smoke.assemble_env@bbe8b4d00c
  - lupin_mcp.reuse_needset.smoke.live_build_env@25bbb09542
  - lupin_mcp.reuse_needset.smoke.lifted_by@33e224265f
  - lupin_mcp.reuse_needset.smoke.smoke_report@c5864ce9f2
  - lupin_mcp.reuse_needset.smoke.main@3aa90d0e32
---
# Need set: smoke run

A small live run of ten needs that measures and sets no pass bar. It takes a test-only kind split and a named commit, and marks every need smoke. The drafting it drives is on [[needset-drafting-run]].

## Time window
- `in_window` is true from 10:00 up to, not including, 13:00 Eastern time, on any day. A time with no timezone raises `ValueError`.
- A live run outside the window is refused with `OUTSIDE_WINDOW`, unless a named person lifts it. `lifted_by` returns who lifted the window, and blank text counts as nobody.
- The window is checked before anything is built or called, and only for the live env.

## Arguments
- `parse_args` reads the command line. The root, output folder, source commit, seed, vector folders and the three matched-kind counts are required.
- `kind_split` returns the split the arguments name. No default stands in for the real split.

## Building the run
- `index_parts` builds the index of a tree and everything the run reads from it. A root without the lupin layout raises `NOT_LUPIN_TREE`.
- `candidate_parts` loads the live vector set and builds the word stage and the query embedder.
- `assemble_env` puts the index, the candidate parts and the model calls into a run environment. The seed pool is the eligible symbols with a row in the vector set. A symbol newer than the vector set is left out.
- `live_build_env` builds the environment with the real drafter, second model and embeddings client.
- `Timed` times every model call and counts the ones that raise, by the model's label.

## Report
- `main` drafts ten needs and measures. It writes `needset-smoke.json` beside the plan, the drafts and the draft report, and returns the report.
- `smoke_report` gives the date, host, commit, split and seed, plus the calls of both models and the failure rate. It states in a note that it is a measurement and not a pass bar.
