---
capability: dm-rewrite-study-replay
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.research.phi4_flash_lite_study.replay_harness.ArmBroken@b8ee1a8642
  - cosa.research.phi4_flash_lite_study.replay_harness.DenominatorUnset@15a528ee1e
  - cosa.research.phi4_flash_lite_study.replay_harness.UnmeasurableRow@43a179c27d
  - cosa.research.phi4_flash_lite_study.replay_harness.assert_arm_is_alive@9c35783288
  - cosa.research.phi4_flash_lite_study.replay_harness.assert_row_is_measurable@8bc9d8cc5d
  - cosa.research.phi4_flash_lite_study.replay_harness.backfill_provenance@f3d357621f
  - cosa.research.phi4_flash_lite_study.replay_harness.discordant_counts@c1da83bf56
  - cosa.research.phi4_flash_lite_study.replay_harness.draw_seeded_subset@d605789f2e
  - cosa.research.phi4_flash_lite_study.replay_harness.latency_ratio@d4becc89d1
  - cosa.research.phi4_flash_lite_study.replay_harness.latency_summary@44c4b7f96b
  - cosa.research.phi4_flash_lite_study.replay_harness.load_frozen_rows@3c67a53555
  - cosa.research.phi4_flash_lite_study.replay_harness.main@6aa7e7e7a3
  - cosa.research.phi4_flash_lite_study.replay_harness.make_arm_rewrite_fn@8c06a57761
  - cosa.research.phi4_flash_lite_study.replay_harness.model_failed_rate@f279cff786
  - cosa.research.phi4_flash_lite_study.replay_harness.summarize_arm@feee652539
  - cosa.research.phi4_flash_lite_study.replay_harness.verify_arm_surface@63c461c3f4
---
# DM rewrite study: replay

The functions around `replay_arm` in [[dm-rewrite-model-study]]. Freezing is in [[dm-rewrite-study-freeze]] and the tests are in [[dm-rewrite-study-checks]].

## What it does
- `load_frozen_rows` returns the rows and manifest. It refuses the live directory and a snapshot that no longer matches its manifest.
- `draw_seeded_subset` returns a copy of each drawn row with its `frozen_index`, and the sorted indices. A size at or over the population returns every row.
- `make_arm_rewrite_fn` builds the production `DmTutorAgent` per body and sets only `model_name` to the arm's spec key. A failure returns `None`. `verify_arm_surface` runs the marker check for one arm and makes no model call.
- `assert_row_is_measurable` raises `UnmeasurableRow` unless the tutor was enabled and fired. `model_failed_rate` is 0.0 for no rows, and `assert_arm_is_alive` raises `ArmBroken` above a stated ceiling.
- `summarize_arm` counts outcomes, lists any outcome it does not know under `unknown_outcomes`, and calls `fabrication_rate`. That raises `DenominatorUnset` until a denominator is passed.
- `latency_summary` splits time into answered rows and all fired rows. `latency_ratio` divides the answered medians, and above 1 the first arm is slower. Percentiles are nearest-rank.
- `discordant_counts` returns arm-named cells, and `b` means only the first arm hit the outcome. `backfill_provenance` returns copies stamped `provenance_backfilled`.
- `main` replays both arms, or one with `--arm`, and writes one JSON line per row. It always prints latency, and withholds the summaries until `--denominator` is given. It writes no run header, so [[dm-rewrite-study-report]] prints "run header ABSENT".

## Don't
- Don't omit `--max-model-failed-rate`. It has no default, so every run states its ceiling.
- Don't pass `--sample-size` and `--limit` together. The parser refuses it.
- Don't read the direction of `discordant_counts` as a winner. For `fabrication_blocked`, a higher count counts against the arm.
- Don't pair a backfilled run without the header's drawn indices. `frozen_index` then falls back to `row_index`.
