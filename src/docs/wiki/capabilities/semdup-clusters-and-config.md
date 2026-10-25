---
capability: semdup-clusters-and-config
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.semdup.cluster.clusters@62c12e6059
  - cosa.repo.semdup.cluster.join_pairs@322934e6a6
  - cosa.repo.semdup.cluster.score@34b43819b0
  - cosa.repo.semdup.cluster.sizes@2295c8d25f
  - cosa.repo.semdup.cluster.surplus@cf21b33e57
  - cosa.repo.semdup.config.build_config@38d0b4be75
  - cosa.repo.semdup.config.config_sha@5878c5f4f2
  - cosa.repo.semdup.config.freeze@1550c03141
  - cosa.repo.semdup.config.is_empty@b14a97293d
  - cosa.repo.semdup.config.verify_frozen@d2018d2ceb
---
# Duplicate checker: clusters and frozen config
The score is surplus copies per 100 passing acceptance tests. The configuration that fixes every constant of a run is written once.
- `join_pairs` turns verdict rows into the pairs of definitions the judge flagged.
- `clusters` groups definitions into connected clusters by union-find.
- `surplus` counts the new definitions beyond the one a cluster needs. `sizes` counts clusters of two or more by size.
- `score` returns the surplus copies per 100 passing acceptance tests.
- `build_config` builds the dict that holds every constant of a run, and `config_sha` takes its sha over every field except its own.
- `freeze` writes the configuration once and returns its sha. `is_empty` says whether a decision field is still unset.
- `verify_frozen` checks the frozen file against its own sha and against what this run would use.
- Inputs come from [[semdup-judge-and-pipeline]].
