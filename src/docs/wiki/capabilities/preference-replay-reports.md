---
capability: preference-replay-reports
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.research.preference_replay.checkpoint_report.CheckpointMismatch@2811151b0e
  - cosa.research.preference_replay.checkpoint_report.deferral@8affdd7a51
  - cosa.research.preference_replay.checkpoint_report.label_metrics@dc0a564c68
  - cosa.research.preference_replay.checkpoint_report.main@64be14c6b1
  - cosa.research.preference_replay.checkpoint_report.refuse_post_checkpoint_report@fe85b788a9
  - cosa.research.preference_replay.checkpoint_report.render_report@0842772750
  - cosa.research.preference_replay.checkpoint_report.checkpoint_name@5da7dbc2bf
  - cosa.research.preference_replay.checkpoint_report.write_checkpoint@3e88c9ec9a
  - cosa.research.preference_replay.before_after_report.ReportMismatch@96b9138bd0
  - cosa.research.preference_replay.before_after_report.check_columns@062cea1ade
  - cosa.research.preference_replay.before_after_report.check_control@9edaad5a86
  - cosa.research.preference_replay.before_after_report.column_rows@0409838bfb
  - cosa.research.preference_replay.before_after_report.render_before_after@5d7dff1259
  - cosa.research.preference_replay.before_after_report.assemble_report@aab790a1e0
  - cosa.research.preference_replay.before_after_report.final_correct@cfec5c356a
  - cosa.research.preference_replay.before_after_report.main@2d60ab12a8
  - cosa.research.preference_replay.before_after_columns.build_column@d63656e8bc
  - cosa.research.preference_replay.before_after_columns.main@14c0fc9c52
---
# Preference replay reports

The Markdown reports of the replay, and the text each context arm embeds ([[preference-replay-core]]). Intervals and McNemar results come from the replay summaries and Brier scores from the calibration fit; nothing is hand-computed here.

## Checkpoint
- `render_report` renders the summaries, calibration, findings and cohort facts. `write_checkpoint` freezes the cohort and writes the freeze file. With `bindings` (gold sha, judge version, scorer version) it also stores them. It refuses to overwrite a file that has none. `deferral( final_window_asks )` applies the deferral rule to each interaction type.
- `refuse_post_checkpoint_report` refuses a report whose baseline arm is not on the frozen cohort. For a freeze file with bindings it also refuses any bound value that is unset or differs from the report's own, and returns 3. `main` checks baseline records against the freeze file, with an optional `--current` file holding the report's own bound values.
- `checkpoint_name( checkpoint_path )` names a freeze file's checkpoint: the second when it holds bindings, else the first.
- `label_metrics` is a scikit-learn per-label scorer that nothing calls yet.

## Before and after
- Four columns. First the committed baseline, then the same asks on regenerated vectors, then every ask on regenerated vectors. Last, every ask as neighbours, scored on column 1's final window.
- `check_columns` refuses columns that cannot support that, with `ReportMismatch`. `check_control` refuses new figures until the control run reproduces the committed final-correct count. `column_rows` flattens a column and `render_before_after` renders it. It takes optional notes, printed as bullets, and escapes a pipe in a figure name.
- `final_correct( column )` sums a column's final-window correct forecasts over its answer types.
- `assemble_report` checks the control and columns 1 to 3 against their expected counts, sets the Before column's provenance and renders. It renders nothing when a count differs.
- `before_after_report.main` builds the report from the four column files. `before_after_columns.build_column` builds one column from a replay: the tune and final windows, the calibration and the yes/no comparison with always-yes.
- `before_after_columns.main` replays the cohort at one setting and writes the column file. With `--rescore-from` it also scores the run on another column's final asks.
