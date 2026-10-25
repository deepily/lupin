---
capability: doc-lint-harness-report
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.doc_lint.harness_report.upper_bound@4a36fef7ca
  - cosa.repo.doc_lint.harness_report.interval@b2d80868e6
  - cosa.repo.doc_lint.harness_report.final_absent@38c75f222e
  - cosa.repo.doc_lint.harness_report.unanimous@537474b388
  - cosa.repo.doc_lint.harness_report.caught@030833fe50
  - cosa.repo.doc_lint.harness_report.drop_tags@88b1f59660
  - cosa.repo.doc_lint.harness_report.run_flagged@ab4d9d224c
  - cosa.repo.doc_lint.harness_report.discarded_on@ee23d72db1
  - cosa.repo.doc_lint.harness_report.flagged@153a4ef4c7
  - cosa.repo.doc_lint.harness_report.run_flagged_pair@f0be1ee192
  - cosa.repo.doc_lint.harness_report.call_timing@7d11f3eff0
  - cosa.repo.doc_lint.harness_report.build_report@45ae09322d
---
# Doc-lint harness report

The exit-gate figures of the judge harness, built from runner results. The runner is [[doc-lint-harness-runner]]; per-judge tables from a finished ledger are in [[doc-lint-judge-comparison-report]].

## Intervals
- `upper_bound` is the one-sided 95% Clopper-Pearson upper bound on a miss rate, and `interval` the two-sided 95% interval for a proportion. Both return `None` for no trials.

## Verdicts
- `final_absent` marks a claim dropped only when every judge run says absent, so two of three is not enough. `unanimous` says whether every run gave the same verdict.
- `drop_tags` lists the dropped claims and which look like history. `flagged` says whether the judge dropped any claim of a list, which is a false alarm if the pair is unseeded.

## Catching a removal
- `caught` is true when a dropped claim has a verified quote overlapping the seed span, or a flagged run overlaps it. A list whose first reply was unreadable never catches.
- `run_flagged` and `discarded_on` test a flagged run or a discarded quote against the seed span. `run_flagged_pair` says whether a list has any run flagged for a person, apart from the judge.

## Report
- `call_timing` sums recorded model-call seconds and counts by stage. A row with no recorded time is counted as untimed.
- `build_report` gives per extractor list the misses and false alarms against their criteria, so a criterion must hold on every list. Pairs with empty new text are left out of the agreement figures and counted apart.
- Agreement is given over all claims and over claims overlapping a seed span, each with its interval.
