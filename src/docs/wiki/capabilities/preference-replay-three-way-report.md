---
capability: preference-replay-three-way-report
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.research.preference_replay.three_way_report.make_three_way_arm@a92a358ae5
  - cosa.research.preference_replay.three_way_report.build_report@f0d086e7b8
---
# Preference replay: the three-way report

Measures the three-way challenger inside a replay, against always-yes and the margin rule ([[prediction-three-way-stance]]).

## What it does
- `make_three_way_arm( half_life_days )` builds a baseline arm that forecasts with the challenger. It returns None for an ask that is not yes/no or has no vector. Otherwise it returns the stance, with a qualifier when one was chosen.
- `build_report( run, asks, operational_floor, arm )` reports the challenger and the margin rule. Each gets its stance counts and a `summarize` result against always-yes. The challenger is also summarized against the margin rule.
- The counts are genuine no, genuine neither, false alarms and asks given no forecast. The two answered denominators sit beside them.
- A false alarm is an ask answered yes that the arm forecast as no or neither.
- `display` is True only when the challenger's verdict against always-yes is `engine better`. That needs the discordant-pair floor and McNemar's p below 0.05.
- In every other case `display` is False, and the text says the challenger stays in shadow with the labelled always-yes baseline on display.
