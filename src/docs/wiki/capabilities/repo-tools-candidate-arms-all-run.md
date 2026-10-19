---
capability: repo-tools-candidate-arms-all-run
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.symindex.candidates.arm_run.vector_source@e9b7c2f6db
  - cosa.repo.symindex.candidates.arm_run.select_fusion_constants@1cc3121e46
  - cosa.repo.symindex.candidates.arm_run.run_all_arms@7395ce4864
  - cosa.repo.symindex.candidates.arm_run.cached_query_vectors@9d00971402
  - cosa.repo.symindex.candidates.arm_run.render_all_arms_page@5b642ed69a
---
# Candidate arms: the all-arms run

Measures all five arms on one index, one needs file and one vector set. The single-arm path is on [[repo-tools-candidate-arms-measure]].

## Inputs
- `vector_source( entry_ids, vset, query_for )` returns a callable from query text to the `vector_concat`, `vector_prose` and `vector_code` ranked lists. It ranks only entries the vector set holds, and cuts the matrices to those rows once.
- `cached_query_vectors( cache_dir, manifest_hash )` returns a read-only source of query vectors from files another process wrote. It never embeds or writes.
- A text with no file, an unreadable file, or a file made under another set raises `QUERY_VECTOR_MISSING`.

## Running
- `select_fusion_constants` tries each `( k, depth, head )` in `FUSION_GRID`. It scores the arm named by `SELECTION_ARM` at `SELECTION_K` by mean repeat-1 recall, and `arms.select_fusion` picks.
- `run_all_arms( env, snapshot_paths, needs_path, fresh_sha, manifest_path, vset, purposes, pages, query_for, redactor, code_sha )` measures each arm in turn. It uses the snapshot the cache answers best, and every arm ranks the same entries for the same redacted text.
- Fusion constants come from `select_fusion_constants`. If no measured arm fuses a vector list, nothing is embedded, the module defaults are used, and no vector choice is made.
- It returns a dict for the page builder: `meta`, `fusion`, `measured`, `t3`, `reference`, the entry counts and the cache `misses`. The page builder reads this dict and measures nothing.

## The page
- `render_all_arms_page( result, redactable )` returns the shared report plus the pooled-items recall table, the fusion selection, and the entry and empty-purpose counts.
- The recall in the recall table is the mean of each need's own fraction. The pooled table gives found items out of all reference items per arm and K.
- The replay column is the verdict replay at K=128, and the page says so. A run with no vector arm says the vector choice and fusion selection were not made.
