---
capability: semdup-proof-run
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.semdup.proof.monolith_pairs.assemble_pairs@28fd736ff4
  - cosa.repo.semdup.proof.monolith_pairs.blob_sha@c072f42015
  - cosa.repo.semdup.proof.monolith_pairs.candidate_pairs@b883fb5309
  - cosa.repo.semdup.proof.monolith_pairs.check_pin@be440b136b
  - cosa.repo.semdup.proof.proof_run.append_ledger@6f740aa743
  - cosa.repo.semdup.proof.proof_run.build_pool@65de056c96
  - cosa.repo.semdup.proof.proof_run.label_key@e703d37c56
  - cosa.repo.semdup.proof.proof_run.next_number@664d265f16
  - cosa.repo.semdup.proof.proof_run.proof_run@0641ea230c
  - cosa.repo.semdup.proof.proof_run.resolve_label@c3626e8ef4
---
# Duplicate checker proof: the run and monolith pairs
The proof run judges a closed pool twice, compares with the human labels and the bar, and keeps the record whatever the result.
- `proof_run` runs the proof once and keeps its record. The record carries `dropped_from_pool`, the count and ids of server definitions left out for a scrub token. `next_number` returns the number of the next record in the folder, counting from 1.
- `append_ledger` adds one line to the proof ledger without touching what is there.
- `build_pool` assembles the closed pool the proof judges. `label_key` returns the key of an unordered pair of definition ids.
- `resolve_label` settles one pair's label from the two reviewers' booleans. It needs a ruling on a disagreement, and raises `ValueError` without one.
- `candidate_pairs` collects candidate duplicate pairs in the monolith script from three sources, each tagged with its source.
- `assemble_pairs` checks the tags and returns the list in a fixed order.
- `blob_sha` returns a file's git blob sha, so a pair list is pinned to one version. `check_pin` refuses a monolith that is not the pinned version.
- Planting and the bar are on [[semdup-proof-plant]].
