---
capability: dm-experiment-arm-reports
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.dm-experiment.analyze_arms.co_primary@b73dbe238d
  - scripts.dm-experiment.analyze_arms.order_effect@f1eab4365f
  - scripts.dm-experiment.analyze_arms.delivery_delay_seconds@8377560c8c
  - scripts.dm-experiment.analyze_arms.secondaries@38c60b3c45
  - scripts.dm-experiment.analyze_arms.counts_only@2933dc499a
  - scripts.dm-experiment.analyze_arms.format_report@66ef6ce181
  - scripts.dm-experiment.analyze_arms.format_counts@717b67cec7
  - scripts.dm-experiment.analyze_arms.default_corpus_path@ad3f7083f6
  - scripts.dm-experiment.analyze_arms.main@6c251836ac
---
# DM verbosity pilot: co-primaries and reports
The reporting half of `analyze_arms.py`. Rows and pairs are on [[dm-experiment-arm-rows-and-pairs]].
- `co_primary` returns the matched pairs and their randomization test for one co-primary. A covers all attempts and B covers first attempts only.
- `order_effect` compares pairs where the blind arm came first with pairs where the rejecting arm did. It tests carryover instead of assuming none.
- `delivery_delay_seconds` is the time from arm assignment to delivery for one row, or None. A negative value is returned as found, not clamped.
- `secondaries` gives per-arm share above threshold, attempts per delivered message, bunching just under it, rejection loops and token means.
- `counts_only` counts distinct slots per date and arm against the expected seven, so a gap can be fixed while it is still fixable.
- `format_report` and `format_counts` render the full analysis and the slot coverage check as plain text. Neither uses markdown.
- `default_corpus_path` is `src/tmp/dm_traffic.jsonl` under the project root.
- `main` prints the full analysis, or only the coverage check with `--counts-only`, from the default corpus or `--corpus`.
