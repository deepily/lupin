---
capability: preference-replay-arm-summary
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.research.preference_replay.arm_summary.summarize_arm@6565c46a66
  - cosa.research.preference_replay.arm_summary.per_arm_summary@4556c638a2
  - cosa.research.preference_replay.arm_summary.render_summary@2f7c6de64c
  - cosa.research.preference_replay.arm_summary_report.render_report@fc690b11cd
  - cosa.research.preference_replay.arm_summary_report.main@a09e5a0039
---
# Preference replay: the per-arm summary

One row per arm: timeliness, the late flag and the switch rate. Every arm writes a `prediction_arm_forecast` row per card ([[rest-prediction-arm-forecast]]). This joins those rows to the card's `prediction_log` row.

## What it does
- `summarize_arm( arm, rows, orphaned, no_row )` folds one arm's joined rows into a summary. `answered` counts rows with an answer time.
- Capped, not ready, timely and late partition the answered rows, in that order of precedence. Timeliness is timely over answered, and None when nothing is answered.
- Unaided, switched, exposed and `no_final` partition the answered rows by exposure class. The rules live in `cosa.agents.prediction_engine.exposure`, so every report shares one rule.
- `switch_rate` comes from `exposure.switch_rate`, and is None when none could be measured. A card revealed in time with no draft is exposed.
- `per_arm_summary( session, since )` summarizes every arm that has a row, sorted by arm name. A forecast with no card row is counted as orphaned. An answered card the arm has no row for is counted in `no_row`.
- `render_summary( summaries )` lays the summaries out as a Markdown table. A rate that is None reads n/a, and others show three places.
- `render_report( summaries, provenance )` adds a title, the provenance lines and two totals: orphaned forecasts and answered cards with no forecast row. Both should read zero on a healthy database.
- `arm_summary_report.main` reads the database only and writes the report to `--out`. Its header names the code sha, the `--since` start, the time and the command line. A bad `--since` raises `ValueError`.
