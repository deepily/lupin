---
capability: dm-rewrite-study-report
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.research.phi4_flash_lite_study.label_sheet.build_items@2e346dc004
  - cosa.research.phi4_flash_lite_study.label_sheet.main@16eb01a450
  - cosa.research.phi4_flash_lite_study.label_sheet.render_sheet@2fc4bcf614
  - cosa.research.phi4_flash_lite_study.report.backfill_provenance@6edd22f854
  - cosa.research.phi4_flash_lite_study.report.latency_block@acbb725748
  - cosa.research.phi4_flash_lite_study.report.load_run@6c5478b51d
  - cosa.research.phi4_flash_lite_study.report.main@8deeb0e1ad
  - cosa.research.phi4_flash_lite_study.report.per_arm_table@d76f554b8d
---
# DM rewrite study: report and labelling sheet

The two read-only tools run on a finished replay file, in [[dm-rewrite-model-study]]. The file comes from [[dm-rewrite-study-replay]].

## What it does
- `load_run` splits a results file into its run header, or `None`, and the per-row records.
- `backfill_provenance` here edits the records in place. It takes `snapshot_sha256` from the header and `frozen_index` from the header's `drawn_row_indices`, only where the field is missing, and says how many it touched.
- `per_arm_table` gives rows, spec key, outcome counts and medians per arm, and no rate.
- `latency_block` covers fired rows only and reports nearest-rank percentiles, plus a Flash-Lite over Phi-4 ratio when both arms are present. It compares deployments, not model speed.
- `main` in `report` prints counts and latency, then the discordant cells. It prints rates only with `--denominator` and a p-value only with `--floor`, and it says when it withholds one.
- `build_items` draws complete row pairs by seed, shuffles the two outputs within each pair and keeps a key from item and slot to arm. A pair with identical text is kept and flagged.
- `render_sheet` writes the markdown sheet with one question per output: does the text assert anything the source does not support. It names no arm.
- `main` in `label_sheet` writes the sheet and a separate key file.

## Don't
- Don't hand the key file to the labeller before every item is answered.
- Don't feed `label_sheet` two runs. It pairs on `row_index`, not `frozen_index`.
- Don't use `report`'s backfill on a file with no header. It touches nothing, and pairing then fails.
