---
capability: preference-replay-arm-scoring
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.research.preference_replay.arm_scoring.load_frozen@fd23241614
  - cosa.research.preference_replay.arm_scoring.final_window@f7f953b1dd
  - cosa.research.preference_replay.arm_scoring.compact@5427a3681a
  - cosa.research.preference_replay.arm_scoring.expand@9134bcf0d9
  - cosa.research.preference_replay.arm_scoring.score_arm@aaa5b271d4
  - cosa.research.preference_replay.arm_scoring.main@e6edc88a44
---
# Preference replay: scoring one context arm

`arm_scoring.py` scores one context arm per ask on the final window, at the settings its retune froze. The retune reports hold grid points but no per-ask records, and a paired test needs the records. The comparison report is in [[preference-replay-context-arms]].

## What it does
- `load_frozen( report_path )` reads threshold, top k and metric out of a retune report. It raises `ValueError` unless the metric is the frozen cosine metric.
- `score_arm( asks, engine, frozen, snapshot_sha256 )` replays the asks once at those settings and keeps the final window. The always-yes baseline is replayed beside it on the same asks. The engine's three settings are restored even when the replay raises.
- `final_window( run )` cuts a run to the records after the tune window, the same cut the retune makes. Every arm is re-indexed from zero, and the not-replayable and unrebuildable counts carry over.
- `compact( run )` reduces a final-window run to the fields the report reads. Per ask that is the id, answer type, forecast, confidence, correct and always-yes correct.
- `expand( compacted )` rebuilds a replay-shaped run so the report's comparison can read it. `expand( compact( run ) )` holds the same per-ask figures as `run`.
- `main` takes `--arm`, `--vectors`, `--settings`, `--only-ids` and `--out`. It reads the cohort read-only, cuts it to the frozen ids and replays once.
- It writes the compact run with sorted keys. The file names the arm, settings, side file and ids file with their checksums, the command line, the code sha and the start time.
- `main` raises `ValueError` when an eligible ask has no vector or the report's metric is not cosine.
