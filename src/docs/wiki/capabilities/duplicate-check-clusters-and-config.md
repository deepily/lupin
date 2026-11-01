---
capability: duplicate-check-clusters-and-config
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.duplicate_check.cluster.clusters@62c12e6059
  - cosa.repo.duplicate_check.cluster.join_pairs@322934e6a6
  - cosa.repo.duplicate_check.cluster.score@03fd52325c
  - cosa.repo.duplicate_check.cluster.sizes@2295c8d25f
  - cosa.repo.duplicate_check.cluster.surplus@cf21b33e57
  - cosa.repo.duplicate_check.config.build_config@38d0b4be75
  - cosa.repo.duplicate_check.config.config_sha@5878c5f4f2
  - cosa.repo.duplicate_check.config.freeze@8550134eb2
  - cosa.repo.duplicate_check.config.is_empty@b14a97293d
  - cosa.repo.duplicate_check.config.verify_frozen@9dad4819c9
  - cosa.repo.duplicate_check.frozen.frozen_path@737ab8ab6a
  - cosa.repo.duplicate_check.frozen.live_config@34e3da1146
  - cosa.repo.duplicate_check.frozen.main@4b908edc3d
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
- `frozen_path` is `src/conf/semdup-frozen-2.json` under the project root. `live_config` builds the configuration from the decided values in `frozen.py`, the judge's prompt parts and the scrub list of the tool tokens and arm labels.
- `frozen.main` freezes `live_config` once and prints the path and sha. It raises `CONFIG_ALREADY_FROZEN` when the file exists.
- Inputs come from [[duplicate-check-judge-and-pipeline]].
