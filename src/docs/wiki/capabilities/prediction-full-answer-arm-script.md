---
capability: prediction-full-answer-arm-script
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - scripts.full_answer_arm.add_missing_columns@49ecaa0662
  - scripts.full_answer_arm.prepare_copy@5155fba8e4
  - scripts.full_answer_arm.RefusalKeeper@fd98b4c025
  - scripts.full_answer_arm.draw_sample@6799997769
  - scripts.full_answer_arm.refused_ids@c04ca105a4
  - scripts.full_answer_arm.forecast_all@9be580eb46
  - scripts.full_answer_arm.score_rows@cffe12d57e
  - scripts.full_answer_arm.line_of@ef89234d95
  - scripts.full_answer_arm.summarize@0452bfb5f5
  - scripts.full_answer_arm.render@694856d2a1
  - scripts.full_answer_arm.pair_with@382ba07515
  - scripts.full_answer_arm.render_pair@1048d27ce9
  - scripts.full_answer_arm.progress_due@482ebe1ae6
  - scripts.full_answer_arm.main@f1934c7203
---
# The full-answer arm run

`src/scripts/full_answer_arm.py` forecasts an earlier run's cards with the context baseline and the full-answer reply ([[prediction-full-answer-reply]]), then scores them. It makes real model calls.

## What it does
- `main` needs `--archive`, `--records` and `--work-dir`. It raises if the full-answer switch reads off or the folder already holds a per-ask file. `--limit`, `--only-refused`, `--sample` with `--seed`, `--write-in` and `--model` narrow or change the run.
- `prepare_copy` copies the archive and deletes the copy's baseline rows for those cards. A copy already there is reused as it is, so a stopped run resumes. `add_missing_columns` adds the nullable columns the copy lacks and refuses anything else missing.
- `draw_sample` draws a fixed-seed sample split by response type. `refused_ids` lists the cards an earlier file left unanswered.
- `forecast_all` runs the jobs, two at a time by default. `RefusalKeeper` keeps the raw reply of every reply the parser refuses. `progress_due` allows a line each hundred cards and at the end.
- `score_rows` scores each stored forecast per field and keeps the earlier run's flag beside it.
- `line_of`, `summarize` and `render` print counts for all cards, each type and the Stop-hook cards, where a miss includes an abstention.
- `pair_with` and `render_pair`, behind `--pair-with`, compare the multiple-choice cards two runs share.

## Invariants
- The archive is only read, and every output goes in the work folder.
