---
capability: dm-quality-judge
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.dm_quality_judge.get_dm_quality_judge@b060034101
  - cosa.agents.dm_quality_judge.judge.DmQualityJudge@06245fe53c
  - cosa.agents.dm_quality_judge.judge.combine_overall@fe19fdce27
  - cosa.agents.dm_quality_judge.judge.length_bucket@3bfa371a1e
  - cosa.agents.dm_quality_judge.judge.round_half_up@20a8a00706
  - cosa.agents.dm_quality_judge.judge_v2.DmQualityJudgeV2@f945264422
---
# DM quality judge

The DM quality judge grades a peer-DM body for length, directness and tone, and returns one overall grade. Length is counted in Python. Directness and tone come from a model, and only when that half is switched on. Callers get a judge from `get_dm_quality_judge`.

## What it does
- `get_dm_quality_judge` reads `dm quality judge version`. Version 2 builds `DmQualityJudgeV2`. Anything else, or an unreadable config, builds `DmQualityJudge`. Version 2 is imported only when chosen.
- Both judges expose `judge( body_text )`. It returns a dict with `length`, `directness`, `tone` and `overall`, and never raises.
- `length_bucket` puts the word count in one of five bands, weight 2 down to -2. It also returns `overage`, the count divided by the target, to one decimal. The emoji repeats once per fixed word interval.
- `DmQualityJudge` skips the model when `dm quality qualitative enabled` is false. That is the code default; the shipped INI turns it on. Directness and tone are then withheld, and the overall grade is the length grade.
- Past the qualitative word ceiling the model is skipped as well, and both dimensions are marked too long.
- Otherwise it makes up to 3 attempts, pausing 0.5 and then 1.0 seconds, with a nudge added on a retry. If all fail, both dimensions become unavailable.
- `DmQualityJudgeV2` has the same shape. Its directness comes from a checked extraction (see [[dm-judge-directness-extraction]]), and its tone from the rubric in [[dm-judge-grade-scale]].
- `round_half_up` rounds a tie upward, so 0.5 gives 1 and -0.5 gives 0. It is not Python's `round`.
- `combine_overall` averages directness and tone, weighs that equally with length, rounds half up and clamps to 2 and -2. If either weight is `None`, overall is the length weight and the note says so.

## Don't
- Don't put a threshold or a word count in anything a sender sees. The length detail names no number, so a sender cannot write up to a limit.
- Don't read a missing grade as a neutral one. A withheld, too long, unavailable or unverified dimension has weight `None`, not 0.
- Don't use `str.format` on the prompt. Braces in a DM body would break it, so the body is substituted with `replace`.
