---
capability: repo-tools-symindex-labelled-run
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.symindex.labelled_set.build@f93b5b43f5
  - cosa.repo.symindex.stage2_split.twin_groups@15e2e5985c
  - cosa.repo.symindex.stage2_split.split_groups@cce13d3ee5
  - cosa.repo.symindex.stage2_split.split_record@09008aa427
  - cosa.repo.symindex.stage2_split.record_sha256@20127a90bf
  - cosa.repo.symindex.stage2_split.half_by_member@09a9aed3b6
  - cosa.repo.symindex.stage2_split.main@7be31fb4f5
---
# Labelled pairs and the fit and check split

Two steps of the verdict layer's labelled run. The split is made before any call, then answered pairs are joined to the negatives record.

## Split (`stage2_split`)
- `twin_groups( manifest )` joins the manifest's exact clusters and near pairs into connected groups of sorted member ids. A group is `exact` when any exact cluster is in it, else `near`. A record with fewer than two members raises `ValueError`.
- `split_groups( groups, seed )` halves each stratum by a shuffle seeded with a person-chosen int. The fit half takes the odd group, and the result does not depend on input order. A twin of a fit member never lands in the check half.
- `split_record( manifest, manifest_sha256, seed )` builds the record with the seed, manifest hash, counts and both halves. `record_sha256` hashes its canonical JSON. `half_by_member` maps each member id to `fit` or `check`.
- `python -m cosa.repo.symindex.stage2_split --manifest M --seed N --out F` writes the record and prints counts and the hash. An existing output file raises `FileExistsError`.

## Join (`labelled_set.build`)
- `build( negatives, answered_rows )` classes each listed pair as `twins`, `lexical` or `random`. Rows come out in the record's member order, then class.
- A pair the record lists with no answer, an unasked or malformed row, or no overlap is uncovered under its class. Held-out pairs are in no class and are counted.
- A row's label must be true exactly when the pair is a twin pair of the record. A pair listed twice, held out and classed, answered twice, or labelled against the record raises `ValueError`.
- The result holds `rows`, `uncovered`, `uncovered_counts`, `held_out`, `answered` and `ignored_rows`.
