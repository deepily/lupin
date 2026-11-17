---
capability: duplicate-check-drift-report
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - lupin_mcp.duplicate_check_drift.week_of_text@c70029b17f
  - lupin_mcp.duplicate_check_drift.run_documents@e84ad53d76
  - lupin_mcp.duplicate_check_drift.weekly_flags@1275908e2a
  - lupin_mcp.duplicate_check_drift.ledger_counts@17d10ededa
  - lupin_mcp.duplicate_check_drift.backlog_ledgers@065d009bfe
  - lupin_mcp.duplicate_check_drift.backlog_rate@5afd0ec98f
  - lupin_mcp.duplicate_check_drift.shift_table@14484ad1f4
  - lupin_mcp.duplicate_check_drift.against@63c1e3f57d
  - lupin_mcp.duplicate_check_drift.finding_judges@f0dd924e5f
  - lupin_mcp.duplicate_check_drift.triage_table@de0e826237
  - lupin_mcp.duplicate_check_drift.report@06e510ff97
  - lupin_mcp.duplicate_check_drift.main@04569b9cc9
  - lupin_mcp.duplicate_check_daily.pair_counts@93cea221b7
  - lupin_mcp.duplicate_check_drift.run_pairs@905acf9d60
---
# Duplicate check drift report
A weekly report on the interim judge. It shows a shift in what the model flags while it stands in for Fable. It reads files the daily check already wrote, makes no model call and writes nothing. The daily run that fills the counts is in [[duplicate-check-daily-run]]. The self-check on the same model is [[duplicate-check-self-consistency]]. The sample against a reference model is [[duplicate-check-sample-rejudge]].

## What it does
- The flag rate is the share of pair verdicts, each one definition against one candidate, that the judge flagged. The weekly counts come from the `pairs` entry of each result file.
- `pair_counts` of the daily check writes that entry. It holds a model's own verdicts and never a reused ruling.
- `run_documents` reads the result files of a folder, in name order, through `check_documents` of `reuse_behaviour`. `run_pairs` lists the files that hold a `pairs` entry for a model. A file that is not a JSON object is named in the report and left out.
- `weekly_flags` sums the model's rows and flags for each week, grouped by the Monday of the file's `started_at`. `week_of_text` reads the date as written, so a time zone never moves the week. A file with no entry for the model, such as one written before the field, adds nothing.
- The backlog rate is Fable's flag rate on the version ledgers that closed before a cut-off day (default 11 November 2026). `backlog_ledgers` lists the rotated `judge-ledger.<version>.jsonl` files whose last change is before that day, oldest version first, through `rotated_files` of `ledger_merge`, and never the live `judge-ledger.jsonl`. `ledger_counts` counts the rulings whose key names the model, and `backlog_rate` sums them.
- `shift_table` gives one row for each week the model ruled any pair. `against` compares a reference rate with the week's Wilson interval. The references are Fable's 15% on the proof and the backlog rate. It says within, or above or below the whole interval.
- `finding_judges` reads each finding's `judge_model` from the result files. `triage_table` counts each finding once, by the last verdict logged for it in `verdicts.jsonl`.
- It gives one row for each judge model: duplicate, extend, distinct, not ruled yet, real of ruled, and how many came from a saved ruling.
- A finding written before result files named their judge goes in the row `no model recorded`, and the report adds a line saying so.
- `report` joins the tables. `main` prints it and returns 0. It prints a refusal and returns 3 when the model key, the folder, a date or a file cannot be read. `--baseline-model` has no default; `--model` defaults to the `duplicate check judge model` key.

## Limits
- The model's own weekly history starts with the first run that records `pairs`. Before that its table has no rows.
- The backlog cut-off uses each ledger file's last change time, so a ledger that is touched again is counted as closed later.
- The triage table holds only findings that appear in a result file, so a verdict whose run file is gone is left out.
