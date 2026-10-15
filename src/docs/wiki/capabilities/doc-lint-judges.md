---
capability: doc-lint-judges
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.doc_lint.prose_judge.ProseParseError@11cdb00862
  - cosa.repo.doc_lint.prose_judge.check_judge@ca52053c65
  - cosa.repo.doc_lint.prose_judge.items_from_source@bb5a50a4bb
  - cosa.repo.doc_lint.prose_judge.changed_items@e84b5e7eb1
  - cosa.repo.doc_lint.prose_judge.parse_findings@ab396a25b3
  - cosa.repo.doc_lint.prose_judge.locate_line@8619759a3e
  - cosa.repo.doc_lint.prose_judge.judge_item@e3a7e43d87
  - cosa.repo.doc_lint.prose_judge.judge_prose@84fec037e7
  - cosa.repo.doc_lint.jev_judge.check_thresholds@ab77a19fd1
  - cosa.repo.doc_lint.jev_judge.verdict_for@afee8a0f8e
  - cosa.repo.doc_lint.jev_judge.build_state@2561f68d04
  - cosa.repo.doc_lint.jev_judge.judge_claims_jev@344f47f8ce
  - cosa.repo.doc_lint.jev_judge.JevBackend@871cc36510
  - cosa.repo.doc_lint.reader_rig.ReaderParseError@be15f19e80
  - cosa.repo.doc_lint.reader_rig.parse_answer@1194c8ef99
  - cosa.repo.doc_lint.reader_rig.parse_score@3f56c2bb36
  - cosa.repo.doc_lint.reader_rig.score_text@c7f7f51a60
  - cosa.repo.doc_lint.reader_rig.run_reader_test@7dbd3c1725
---
# Doc-lint judges

Three model-backed checks that regular expressions cannot make: a prose judge, a Jev back end for the claim judge, and a reader test. Claims come from [[doc-lint-claim-extractor]].

## Prose judge (`prose_judge`)
- `check_judge` refuses an empty id or a judge that is the writer model. `items_from_source` lists every docstring with its signature and line range, and `changed_items` keeps those that touch a changed line.
- `judge_item` asks which sentences break the four rules and keeps a finding only for a quote that really occurs. `parse_findings` raises `ProseParseError` for a bad shape or a rule outside the four.
- `locate_line` finds where a quoted sentence starts. `judge_prose` tries each item twice, and a failed one becomes a finding.

## Jev back end (`jev_judge`)
- `check_thresholds` requires `0 <= t_lo < t_hi <= 1`. `verdict_for` maps a probability: at or above `t_hi` is `present`, at or below `t_lo` is `absent`, between is `uncertain`.
- `build_state` is the new docstring plus the design document if any. `judge_claims_jev` judges every claim with Jev, escalates the uncertain and fails closed.
- `JevBackend` is the back end the runner takes in place of the Claude judge. Its `key_id` names the model, both thresholds and the escalation model, so a ledger row is never reused under other settings.

## Reader test (`reader_rig`)
- `parse_answer` and `parse_score` raise `ReaderParseError` off contract, and a score is 0 or 1. `score_text` scores one text on every question. The grader sees the question, the key and the answer, never the text.
- `run_reader_test` compares old and new on the same questions. It passes when the new total is at least the old total.
