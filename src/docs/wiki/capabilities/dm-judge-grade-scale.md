---
capability: dm-judge-grade-scale
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.dm_quality_judge.xml_models.DmQualityJudgeResponse@7375e03b7e
  - cosa.agents.dm_quality_judge.xml_models.grade_emoji@535b726881
  - cosa.agents.dm_quality_judge.xml_models.grade_weight@66c2b1a0c1
  - cosa.agents.dm_quality_judge.xml_models.normalize_grade_label@17fb453f17
  - cosa.agents.dm_quality_judge.xml_models_v2.DmToneJudgement@a22facd36b
---
# DM judge grade scale

The judge's model answers are text labels, never numbers. These pieces turn a label into a weight and a face, and hold the response shape for the tone and directness grades. The judge itself is in [[dm-quality-judge]].

## What it does
- The scale has five labels: `terrible` (-2), `bad` (-1), `meh` (0), `good` (1) and `exemplary` (2). Each has one emoji, and the table is the single source for the face of every grade.
- `normalize_grade_label` lowercases a label and turns any run of spaces, hyphens and underscores into one underscore. The known typo `meah` becomes `meh`.
- An unknown or blank label becomes `meh`. So a parse miss reads as a considered `meh`.
- `grade_weight` and `grade_emoji` read the weight and the face through that normalizer.
- `DmQualityJudgeResponse` holds `directness`, `directness-note`, `tone` and `tone-note`. Labels default to `meh` and notes to an empty string. Serialized tags are dash-cased.
- Its four methods return the weight and the emoji of each label.
- `DmToneJudgement` is the version 2 tone shape. It holds `tone-evidence` first, then `tone`, so the model writes its evidence before its grade.

## Invariants
- A non-answer face never equals a grade face. An import-time assertion checks this.
- The four non-answer faces are withheld, too long, unavailable and unverified. Each means a different silence.
