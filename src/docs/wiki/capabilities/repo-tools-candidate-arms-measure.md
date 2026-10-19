---
capability: repo-tools-candidate-arms-measure
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.symindex.candidates.arm_run.references@69fe1c7fee
  - cosa.repo.symindex.candidates.arm_run.lists_for@da301f7c56
  - cosa.repo.symindex.candidates.arm_run.measure_arm@705e4bf73f
  - cosa.repo.symindex.candidates.arm_run.twin_map@a92e376503
  - cosa.repo.symindex.candidates.arm_run.query_text@e6050f30ca
  - cosa.repo.symindex.candidates.arm_run.measure_twins@4d81cbe45e
  - cosa.repo.symindex.candidates.arm_run.render_partial_page@d1c0988d51
  - cosa.repo.symindex.candidates.arm_run.run_arm_report@29004293b7
  - cosa.repo.symindex.candidates.arm_run.main@3737b347e8
---
# Candidate arms: measuring and the page

The rest of `arm_run.py` measures one arm and writes its partial results page. Inputs are read by the functions on [[repo-tools-candidate-arms-run-inputs]]; the scores come from [[repo-tools-candidate-arms-metrics]].

## Recall and replay
- `references( answers, needs )` returns `( first, union )` per need. `first` is the full-sweep shortlist of repeat 1. `union` is every id any of the five repeats shortlisted.
- `measure_arm( arm, needs, stages, available, answers )` returns `t1_first`, `t1_union`, `empty` and `t2`. `available` is a mapping of ranked lists or a callable from query text to one; `lists_for` resolves either.
- `empty` lists needs whose repeat-1 reference is empty. They are left out of the repeat-1 table. They stay in the union table unless the union is also empty.
- `t2` holds a `control` replay of the answered set. Its agreement can fall below 100% when a repeat answered entries that repeat 1 did not. `K=128` and `K=512` replay the arm's shortlists.

## Known twins
- `twin_map( manifest )` maps each member of an exact or near cluster to the other members of its cluster.
- `query_text( entry )` builds a member's query from its name, signature and first docstring line.
- `measure_twins( arm, entries, twins, stages, available )` takes the same kind of `available`. It ranks each member's query with the member itself removed and takes its best twin's rank. It returns the ranks grouped by file suffix, with `None` for a member whose twins are not ranked, and the members not in the snapshot.

## The page
- `render_partial_page( meta, arm, measured, t3, absent, pending, ruling )` returns the markdown. It says every figure is in-sample and lists the arms not measured yet. A `meta` without every `META_KEYS` key raises `REPORT_META_MISSING`.
- `run_arm_report( env, snapshot_paths, needs_path, fresh_sha, manifest_path, out_path, code_sha, arm )` runs all of the above and writes the page.
- The arm defaults to the BM25-only arm. It passes no vector or wiki list, so only an arm that fuses none can run. It picks the snapshot the cache answers best, and refuses the reserved needs file.
- It returns `page_sha`, `misses` (shortlist answers missing from the cache), `snapshot`, `needs` and `members`.
- `main( argv )` is the command line: `python -m cosa.repo.symindex.candidates.arm_run` with `--data --needs --fresh-sha --manifest --out --code-sha`, all required. It prints the result as JSON and returns 0.
