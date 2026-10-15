---
capability: doc-lint-judge-comparison-report
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.doc_lint.judge_comparison.key_rows@b7dc257f87
  - cosa.repo.doc_lint.judge_comparison.groups_of@196219685c
  - cosa.repo.doc_lint.judge_comparison.wrong_on@4d151e9f2a
  - cosa.repo.doc_lint.judge_comparison.group_rows@c5fce5edde
  - cosa.repo.doc_lint.judge_comparison.build_comparison@2054c47ee5
  - cosa.repo.doc_lint.judge_comparison.pct@04cfbb09dd
  - cosa.repo.doc_lint.judge_comparison.axis_top@c824d64519
  - cosa.repo.doc_lint.judge_comparison.worst_list@2364261791
  - cosa.repo.doc_lint.judge_comparison.render_markdown@b8fa005fb6
  - cosa.repo.doc_lint.judge_comparison.parse_args@8d3298f888
  - cosa.repo.doc_lint.judge_comparison.main@c17670b6b5
---
# Doc-lint judge comparison report

Per-judge, per-pair-type figures from a finished ledger, as JSON and markdown. The rebuild step is in [[doc-lint-judge-comparison-ledger]].

## Grouping pairs
- `key_rows` reads the keys file into `kind`, `seeded_positive` and `injection` per id, and raises `ValueError` for a missing field or unknown kind.
- `groups_of` names the rows a pair belongs to: its kind, plus one injection row when the flag is set. `wrong_on` says whether an extractor list judged a pair wrongly. A seeded pair is a false pass, an unseeded one a false alarm.
- `group_rows` counts wrong verdicts per group on the worse list, with a rate and a 95% bound. A group that mixes seeded and unseeded pairs raises `ValueError`.

## Comparison
- `build_comparison` returns `split`, `pairs`, `config`, `judges` and `calls`. A judge whose ledger is incomplete, or holds more or fewer calls than its configuration makes, is `incomplete` and never a partial figure set.
- `render_markdown` renders the headline, by-group and calls tables and four Mermaid charts. `pct`, `axis_top` and `worst_list` format a share, a chart axis and the headline entry.

## Command line
- `parse_args` requires every model id. `main` makes no model call and writes the JSON and markdown files.
- It returns 2 for a refused model or mixed Claude Code binaries. It returns 3 for a gate split with no matching `--frozen-pairs-sha`. A Jev report from another run returns 4.
