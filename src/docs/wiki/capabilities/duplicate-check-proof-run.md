---
capability: duplicate-check-proof-run
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.duplicate_check.proof.monolith_pairs.assemble_pairs@d7d0b7293b
  - cosa.repo.duplicate_check.proof.monolith_pairs.blob_sha@c072f42015
  - cosa.repo.duplicate_check.proof.monolith_pairs.candidate_pairs@1dad7fb3f1
  - cosa.repo.duplicate_check.proof.monolith_pairs.check_pin@be440b136b
  - cosa.repo.duplicate_check.proof.proof_run.append_ledger@6f740aa743
  - cosa.repo.duplicate_check.proof.proof_run.build_pool@65de056c96
  - cosa.repo.duplicate_check.proof.proof_run.label_key@e703d37c56
  - cosa.repo.duplicate_check.proof.proof_run.next_number@664d265f16
  - cosa.repo.duplicate_check.proof.proof_run.proof_run@17f81c51df
  - cosa.repo.duplicate_check.proof.proof_run.resolve_label@c3626e8ef4
  - cosa.repo.duplicate_check.proof.proof_run.bar_without_unsure@4e2c9eac08
---
# Duplicate checker proof: the run and monolith pairs
The proof run judges a closed pool twice, compares with the human labels and the bar, and keeps the record whatever the result.
- `proof_run` runs the proof once and keeps its record. A trial run takes one reviewer's labels and writes to its own folder, never taking a proof number. It refuses a judge ledger outside `proof-trial` (`LEDGER_OUTSIDE_TRIAL`) before it judges or writes anything. The record carries `dropped_from_pool`, the count and ids of server definitions left out for a scrub token. The record and the ledger line carry `provenance` (the label fingerprints and the tree root). A complete record also carries `bar_without_unsure`, the bar again without the pairs either reviewer marked unsure, with the dropped counts; it gates nothing. `next_number` returns the number of the next record in the folder, counting from 1.
- `bar_without_unsure` works out a second bar without the pairs a reviewer marked unsure. It is reported beside the first bar and gates nothing, and it gives no bar when a denominator is left empty.
- `append_ledger` adds one line to the proof ledger without touching what is there.
- `build_pool` assembles the closed pool the proof judges. `label_key` returns the key of an unordered pair of definition ids.
- `resolve_label` settles one pair's label from the two reviewers' booleans. It needs a ruling on a disagreement, and raises `ValueError` without one.
- `candidate_pairs` collects candidate duplicate pairs in the monolith script from three sources, each tagged with its source. With a `total`, the neighbour source takes what is left of it after the structural and nominated pairs.
- `assemble_pairs` checks the tags and returns the list in a fixed order.
- `blob_sha` returns a file's git blob sha, so a pair list is pinned to one version. `check_pin` refuses a monolith that is not the pinned version.
- Planting and the bar are on [[duplicate-check-proof-plant]].
