---
capability: repo-tools-candidate-arms-wiring
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.symindex.candidates.arms.build_arm_stages@0924c8dc22
  - cosa.repo.symindex.candidates.arms.lists_for_arm@5925f024a7
  - cosa.repo.symindex.candidates.arms.run_arm@d9321a7371
  - cosa.repo.symindex.candidates.arms.full_ranking@3d51d6c72c
  - cosa.repo.symindex.candidates.arms.cosine_sources@63195fd498
  - cosa.repo.symindex.candidates.arms.refuse_fresh_needs@509bd894cf
  - cosa.repo.symindex.candidates.arms.select_fusion@9aef2e654b
---
# Candidate arms: wiring

`arms.py` puts five arms onto the candidate stage. It builds stages, picks each arm's lists and ranks. It measures nothing and reads no needs file; scoring is on [[repo-tools-candidate-arms-metrics]].

## The arms
- `ARMS` holds five names, defined next. `KS` is the cut-offs 32, 64, 128, 256 and 512.
- C0: BM25 alone.
- C1: BM25 plus the purpose lines.
- B1: C1 plus one concatenated vector list.
- B2: C1 plus a prose and a code vector list.
- B2w: B2 plus the wiki page list.
- `ARM_SOURCES` names the extra lists each arm fuses, and `ARM_PURPOSE` says whether it uses the purpose-line stage.

## Building and ranking
- `build_arm_stages( entries, purposes )` returns `{ "plain", "purposed" }`, two stages over the same entries with the same fusion constants.
- `lists_for_arm( arm, available )` returns only the ranked lists the arm names. It raises `ARM_UNKNOWN` for a name outside `ARMS`. It raises `ARM_LIST_MISSING` when a needed list is absent.
- `run_arm( arm, need, stages, available, K )` shortlists one need through the candidate stage and returns its `shortlist`, `ranking`, `lists` and `scores`. A K below the stage's head size raises `K_BELOW_HEAD`.
- `full_ranking( arm, need, stages, available )` returns the fused order with K set to the index size, so a twin's rank can be read. An index smaller than the head size uses the head size. An entry in no list within the fusion depth is absent.
- `cosine_sources( ids, matrices, query_vectors )` ranks the ids by cosine against each matrix named in `query_vectors`, and names the lists `vector_<name>`. The result goes into `available`.

## Guards and choices
- `refuse_fresh_needs( need_ids, needs_sha, fresh_sha, fresh_ids=() )` raises `FRESH_NEEDS_REFUSED` in three cases.
- A need id starts with `fresh-` or is in `fresh_ids`.
- The needs file hash equals the reserved file's hash.
- Either hash is missing.
- The reserved needs are kept for the confirmation phase.
- `select_fusion( recall_by_params )` picks the `( k, depth, head )` with the highest in-sample recall, ties going to the smaller k, then depth, then head. An empty mapping raises `FUSION_EMPTY`.
