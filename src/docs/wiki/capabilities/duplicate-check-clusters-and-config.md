---
capability: duplicate-check-clusters-and-config
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.duplicate_check.cluster.clusters@62c12e6059
  - cosa.repo.duplicate_check.cluster.join_pairs@322934e6a6
  - cosa.repo.duplicate_check.cluster.score@03fd52325c
  - cosa.repo.duplicate_check.cluster.sizes@2295c8d25f
  - cosa.repo.duplicate_check.cluster.surplus@cf21b33e57
  - cosa.repo.code_health_settings.model_id@25d79abd26
  - cosa.repo.duplicate_check.config.build_config@f2add23202
  - cosa.repo.duplicate_check.config.config_sha@5878c5f4f2
  - cosa.repo.duplicate_check.config.freeze@8550134eb2
  - cosa.repo.duplicate_check.config.is_empty@b14a97293d
  - cosa.repo.duplicate_check.config.verify_frozen@9dad4819c9
  - cosa.repo.duplicate_check.frozen.selected_model@1de18c73eb
  - cosa.repo.duplicate_check.frozen.frozen_path@00d1f36aa1
  - cosa.repo.duplicate_check.frozen.live_config@efe38fc53e
  - cosa.repo.duplicate_check.frozen.main@acae3be1fd
---
# Duplicate checker: clusters and frozen config
The score is surplus copies per 100 passing acceptance tests. The configuration that fixes every constant of a run is written once.
- `join_pairs` turns verdict rows into the pairs of definitions the judge flagged.
- `clusters` groups definitions into connected clusters by union-find.
- `surplus` counts the new definitions beyond the one a cluster needs. `sizes` counts clusters of two or more by size.
- `score` returns the surplus copies per 100 passing acceptance tests.
- `build_config` builds the dict that holds every constant of a run, and `config_sha` takes its sha over every field except its own.
- The judge's model is `model_id`, or else the INI key `duplicate check judge model`. A new model therefore reads as drift until it has its own frozen file.
- `code_health_settings.model_id( key, config=None )` reads a model key, with no default in code. A blank, absent or spaced value raises, naming the key.
- Its keys are `duplicate check judge model`, `duplicate check proof rewrite model` and `reuse need drafter model`. A manager it builds prints its banner to stderr.
- `freeze` writes the configuration once and returns its sha. `is_empty` says whether a decision field is still unset.
- `verify_frozen` checks the frozen file against its own sha and against what this run would use.
- `selected_model` returns the INI key `duplicate check judge model`, read each time through `code_health_settings.model_id`.
- `frozen_path` returns the one `semdup-frozen-*.json` file in `src/conf` whose `model_id` is the selected model: `semdup-frozen-2.json` for the Fable model, `semdup-frozen-3-opus.json` for the Opus model. With no match it returns `semdup-frozen-<model>.json`, which does not exist, so `verify_frozen` raises `FileNotFoundError` naming the model. Two matches raise `CONFIG_DRIFT`.
- `live_config` builds the configuration from the decided values in `frozen.py` and the selected model.
- It also takes the judge's prompt parts and the scrub list of the tool tokens and arm labels. The two frozen files differ in `model_id` and `config_sha` only.
- `frozen.main` freezes `live_config` once to the file named by the required `--path` and prints the path and sha. It raises `CONFIG_ALREADY_FROZEN` when the file exists.
- Inputs come from [[duplicate-check-judge-and-pipeline]].
