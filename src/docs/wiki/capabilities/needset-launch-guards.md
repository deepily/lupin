---
capability: needset-launch-guards
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.launch_preflight.begun_run_names@69f4ef457a
  - lupin_mcp.reuse_needset.launch_preflight.next_run_name@d42595b2d3
  - lupin_mcp.reuse_needset.launch_preflight.check_run_name@1b201f274d
  - lupin_mcp.reuse_needset.launch_preflight.preflight@bdacd7f667
  - lupin_mcp.reuse_needset.launch_preflight.source_tree_of@318b233f83
  - lupin_mcp.reuse_needset.launch_preflight.index_of@00dac8ea73
  - lupin_mcp.reuse_needset.launch_preflight.parse_args@ed2a7144ee
  - lupin_mcp.reuse_needset.launch_preflight.main@d346f641d6
  - lupin_mcp.reuse_needset.rebuild_vectors.live_purpose_store@4e7ff1cb04
  - lupin_mcp.reuse_needset.rebuild_vectors.check_prior@a7723e0b06
  - lupin_mcp.reuse_needset.rebuild_vectors.check_purpose_store@8faa2cad80
  - lupin_mcp.reuse_needset.rebuild_vectors.matrix_changes@6d62162511
  - lupin_mcp.reuse_needset.rebuild_vectors.rebuild@b6c17ec3ea
  - lupin_mcp.reuse_needset.rebuild_vectors.main@ccf7b09217
  - lupin_mcp.reuse_needset.launch_preflight.tree_is_locked@3cdf647c11
---
# Need set: the launch guards

Two script steps keep a live first-thousand launch from failing after setup. The run is in [[needset-first-thousand-command]] and the vector identity in [[needset-freeze]].

## What it does
- `launch_preflight` runs last in a `run-command.sh`, before the python launch, and only with `--live`. A plan-only run checks nothing and makes no tree.
- `check_run_name` refuses a name the spend ledger has a begin row for. A name is consumed by its first attempt, even one refused before any model call. The refusal names the next letter and prints the rule.
- `next_run_name` letters forward past every begun name. With `--advance` the preflight prints `RUN_NAME=<name>` instead of refusing.
- `source_tree_of` makes and locks the run's `needset-run-<sha>` tree, which the janitor sweeps when idle. It says whether it made the tree and whether it was locked before. `tree_is_locked` asks git for a locked line, and answers True when git cannot list.
- `preflight` builds the index from that tree and reads `freeze.identity` last. A refusal after the tree step unlocks the tree, unless it was locked before. A stale identity on a new tree names `rebuild_vectors`.
- `rebuild_vectors` replaces the hand-run rebuild script. It needs `--prior-gen`, the prior generation's folder, and refuses with `PRIOR_GEN_MISSING` before it builds when that folder lacks a matrix.
- `check_purpose_store` requires the run's `purpose-lines/purpose.jsonl` to be byte-equal to the live store, else `PURPOSE_STORE_NOT_LIVE`.
- `matrix_changes` compares `code.f32`, `concat.f32`, `prose.f32` and `ids.txt` with the prior generation. Any change not named in `--expect` exits 2 with `MATRICES_CHANGED`.

## Invariants
- Both commands exit 2 on a refusal and print the code, and neither calls a model. The rebuild embeds changed rows through the :7999 endpoint.
- The identity is read after every step that can touch the tree, because the index manifest hashes file times.

## Don't
- A refused launch still consumes its run name, so letter it forward. A purpose store older than the live one fails `check_purpose_store`.
