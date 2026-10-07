---
capability: dm-rewrite-model-study
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.research.phi4_flash_lite_study.freeze_corpus.freeze@822fdfceb8
  - cosa.research.phi4_flash_lite_study.freeze_corpus.assert_snapshot_is_not_live@be6f2b6d3e
  - cosa.research.phi4_flash_lite_study.replay_harness.replay_arm@8805c410d2
  - cosa.research.phi4_flash_lite_study.replay_harness.pair_records@65736828e1
  - cosa.research.phi4_flash_lite_study.replay_harness.fabrication_rate@a4d80f3c68
  - cosa.research.phi4_flash_lite_study.arm_markers.check_arm_markers@8cf44ed831
  - cosa.research.phi4_flash_lite_study.statistics.compare_arms@2e8330db7b
---
# DM rewrite model study

A one-off package compares two models on the DM Tutor's rewrite task: Phi-4 14B on a local vLLM host and `gemini-3.1-flash-lite` on Vertex. It replays frozen DM bodies through the production tutor. Only tests import it.

## What it does
- `freeze` copies tutor-eligible rows from the live `dm_traffic.jsonl` into a checksummed snapshot and manifest. Eligible means a claim count above the trigger, default 4.
- It checksums the source before and after the read and raises if the two checksums differ. It refuses an empty set.
- `replay_arm` calls the production `_apply_dm_tutor` once per row, giving it a per-arm `rewrite_fn`. The INI and the tutor are untouched.
- The arms use spec keys `dm_tutor/phi_4` and `dm_tutor/flash_lite`. The harness builds the same `DmTutorAgent` and overrides only `model_name`.
- `check_arm_markers` runs before row 0. The Flash-Lite client must show the Vertex host, the model id, `vertexai` true and no API key. The Phi-4 arm must not be a Vertex client.
- A row where the tutor was off or did not fire aborts the run. A caller-stated `model_failed` ceiling is checked after a preflight prefix, if the run has that many rows (25 by default), and again at the end.
- `pair_records` joins the arms on `frozen_index` and snapshot sha, never `row_index`. It raises when indices, snapshots or bodies differ.
- `compare_arms` runs McNemar's exact test on the discordant cells, plus a Wilson interval.
- `report` prints counts, latency and paired cells from a finished run. `latency_ratio` compares LAN with internet deployments, not model speed. `label_sheet` writes a blind A/B sheet and a separate answer key for hand-labelling.

## Don't
- Don't repoint `llm spec key for dm tutor rewrite` to run an arm. That swaps the model for the whole fleet and writes its rows into the corpus under study.
- Don't pick the fabrication denominator. `fabrication_rate` raises until given "narrow" or "wide"; that choice belongs to the owner.
- Don't ask `compare_arms` for a verdict without a pre-stated floor. Under 6 discordant pairs, p cannot fall below 0.05.
- Don't use `--limit` to cut cost. It takes the first N rows, a time-window sample. Use `--sample-size` with a seed.
- Don't read a blocked rewrite as dishonesty. The guard measures detectability; honesty needs the hand-labelled sample.

## Invariants
- The snapshot is never the live corpus: both realpath and (device, inode) must differ.
- The docstrings of `report` and `label_sheet` name scripts under `src/scripts/` that are not tracked. Run them with `python -m cosa.research.phi4_flash_lite_study.<module>`.
- `label_sheet` pairs the arms on `row_index`, not `frozen_index`. Feed it one results file from one paired run.
- The harness writes no run header, so `report` prints "run header ABSENT" for its output.
