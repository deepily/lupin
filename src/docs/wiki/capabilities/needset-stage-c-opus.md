---
capability: needset-stage-c-opus
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.stage_c_opus.build_prompt@3b3b3d7b76
  - lupin_mcp.reuse_needset.stage_c_opus.judge_pair@c1eeb70c03
  - lupin_mcp.reuse_needset.stage_c_opus.judged_pairs@50caa2b49a
  - lupin_mcp.reuse_needset.stage_c_opus.main@944f86a751
  - lupin_mcp.reuse_needset.stage_c_opus.opus_ask@202a21a361
  - lupin_mcp.reuse_needset.stage_c_opus.parse_args@ccbf564482
  - lupin_mcp.reuse_needset.stage_c_opus.parse_reply@0e18bfb51e
  - lupin_mcp.reuse_needset.stage_c_opus.run_pairs@597f6f76cd
  - lupin_mcp.reuse_needset.stage_c_opus.split_pairs@fd38bef6d8
  - lupin_mcp.reuse_needset.stage_c_opus.tabulate@202fd5e0e2
---
# Needset Opus judge

Rates the labelled pairs the Jev judge never rated, by reading each side's whole source text from the answer key's packet. No side is refused. It is a different instrument from the Jev run: no drafted need, and the judge sees source, not a signature and docstring.

## Pairs and prompt
- `judged_pairs( report )` names the pairs a stage-c report already rated, twins' copies included. `split_pairs( pairs, judged )` returns `( rated, left )` in key order.
- `build_prompt( pair, repeat, rng )` puts the two sides in tags with one random suffix found in neither text. The label, the stratum and the planted status stay out. The repeat number is in the prompt, so each repeat has its own request body.
- `parse_reply( text )` reads a forward and a reverse reading, each a choice (reuse, extend, unrelated) and a fit from 0 to 1. A reply that is not that JSON, a bad choice or a fit out of range gives both readings as unanswered. A code fence is read.

## Judging
- `opus_ask( model, query_fn )` builds the one-prompt-to-text function. The model is the INI key `duplicate check judge model` unless given. It must not be called from a running event loop.
- `judge_pair( pair, repeat, ask, seed )` returns a row `stage_c_score` reads. A failed ask is an unanswered row with its error text, never a raised error.
- `run_pairs( pairs, ask, seed, workers )` judges every pair at every repeat and returns rows in pair then repeat order.
- `tabulate( rows, resamples )` returns `{ pairs, unanswered, figures }` over the forward readings. A pair with no answered repeat is left out of the figures.

## Command
- `parse_args` takes `--only` as the pairs left, the pairs rated or all. `main` without `--live` calls no model and reports `left`, `rated` and `chosen`. With `--live` it writes `--out` with the rows and the figures.
