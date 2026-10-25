---
capability: dm-experiment-arm-rows-and-pairs
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.dm-experiment.analyze_arms.load_rows@9df2b28d90
  - scripts.dm-experiment.analyze_arms.is_experiment_row@13925acee3
  - scripts.dm-experiment.analyze_arms.is_self_addressed@de82258ddd
  - scripts.dm-experiment.analyze_arms.eligible_rows@74d8e3e102
  - scripts.dm-experiment.analyze_arms.slot_date@6f8698850f
  - scripts.dm-experiment.analyze_arms.clock_hour@b86d88bd41
  - scripts.dm-experiment.analyze_arms.excess_words@6423b9fbde
  - scripts.dm-experiment.analyze_arms.hour_arm_excess@9dde789b85
  - scripts.dm-experiment.analyze_arms.matched_pair_diffs@c4b70d393b
  - scripts.dm-experiment.analyze_arms.randomization_test@afc8fb7bf8
---
# DM verbosity pilot: rows and matched pairs
`src/scripts/dm-experiment/analyze_arms.py` analyses the two-arm DM-verbosity pilot, arms `blind` and `rejecting`. The evidence is matched clock-hour pairs, not individual messages, because messages correlate within an hour. The reports are on [[dm-experiment-arm-reports]].
- `load_rows` reads the JSONL corpus into dicts and skips blank lines.
- `is_experiment_row` is true only for a row written under `two-arm-v1`. Legacy signal-only rows are false.
- `is_self_addressed` is true when sender and recipient are one session. A row missing either id is false, so the denominator is not shrunk by a guess.
- `eligible_rows` keeps experiment attempts that are not exempt, transient or self-addressed. The exempt arbiter poker never enters an arm.
- `slot_date` and `clock_hour` read the date and the hour out of a row's slot id.
- `excess_words` is the attempted words beyond the 60 word target, never below 0.
- `hour_arm_excess` is the mean excess of one arm in one clock hour, or None when that arm made no eligible attempt.
- `matched_pair_diffs` builds the rejecting minus blind difference for each hour in which both arms made attempts. It can be limited to first attempts.
- `randomization_test` flips the sign of each pair's difference to get an exact or sampled interval and p value.
