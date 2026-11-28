---
capability: prediction-rerun-phases-script
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - scripts.rerun_phases_7_to_11.columns_of@a6abd7ddc5
  - scripts.rerun_phases_7_to_11.split_by_time@c463d499a5
  - scripts.rerun_phases_7_to_11.replay_config@6e56697238
  - scripts.rerun_phases_7_to_11.window_counts@8728352eb3
  - scripts.rerun_phases_7_to_11.control_mismatches@15d224325d
  - scripts.rerun_phases_7_to_11.with_reasons@0dda166ed5
  - scripts.rerun_phases_7_to_11.per_ask_document@abfd27e983
  - scripts.rerun_phases_7_to_11.write_json@b1aa07b69d
  - scripts.rerun_phases_7_to_11.read_switches@7eb66ac886
  - scripts.rerun_phases_7_to_11.sign_of@4ba2aa61f1
  - scripts.rerun_phases_7_to_11.reversal@ce3315d966
  - scripts.rerun_phases_7_to_11.column_run@60c3855157
  - scripts.rerun_phases_7_to_11.of_type@c11f22aff6
  - scripts.rerun_phases_7_to_11.final_records@5c88c38fa5
  - scripts.rerun_phases_7_to_11.phase7_column@85f9b7ecfa
  - scripts.rerun_phases_7_to_11.phase8_column@d128e161b2
  - scripts.rerun_phases_7_to_11.phase9_column@e021abfe9b
  - scripts.rerun_phases_7_to_11.phase11_column@b212af2bf8
  - scripts.rerun_phases_7_to_11.main@e70945db52
---
# Re-running four preference-learning comparisons from stored vectors

`src/scripts/rerun_phases_7_to_11.py` replays the preference engine with every model entry point raising ([[prediction-zero-model-proof]]). It writes files and nothing to a database.

## What it does
- `main` first replays the old 1,302 asks as a control. `window_counts` and `control_mismatches` compare it with the old record; on any difference nothing is written and it returns 2.
- `columns_of` makes three columns, `second`, `record` and `old_1302`, each replayed against only its own asks. `replay_config` sets the per-field and failure-visibility switches, records each abstention reason and restores the engine.
- `split_by_time` and `final_records` cut by position into the tune and final windows. `column_run` and `of_type` narrow a run to one column and one response type.
- `phase7_column` compares per-field multiple choice with the control. `phase8_column` compares three-way with always-yes and the margin rule on yes/no. `phase9_column` fits calibration on the tune window and scores the final one. `phase11_column` counts abstention reasons with failure visibility off and on.
- `sign_of` and `reversal` say whether a paired difference reversed sign; a zero on either side is "no sign".
- `per_ask_document`, with `with_reasons` for the engine arm, builds each arm's file, and `write_json` writes it and returns its sha256. `read_switches` records what the INI file states; the replay does not read it.
- The report lists the tenth phase as not run. `main` returns 1, after writing, if a model call was attempted or the positive control did not fire.

## Don't
- Don't reuse a `--cache` pickle across inputs or code changes. It is loaded whenever the file exists, with no check of what made it; only the control is replayed again.
