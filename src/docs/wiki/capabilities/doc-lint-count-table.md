---
capability: doc-lint-count-table
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.doc_lint.counts.TableError@39c1d64184
  - cosa.repo.doc_lint.counts.file_count@c05630a083
  - cosa.repo.doc_lint.counts.unreadable_count@da39ca94f5
  - cosa.repo.doc_lint.counts.counted_paths@7868eede18
  - cosa.repo.doc_lint.counts.census@98b721b22d
  - cosa.repo.doc_lint.counts.rules_stamp@5569c94b98
  - cosa.repo.doc_lint.counts.rule_files@14d190e164
  - cosa.repo.doc_lint.counts.differing_rule_files@86c1913078
  - cosa.repo.doc_lint.counts.table_text@9bb5ab1530
  - cosa.repo.doc_lint.counts.parse_table@c05b9d205b
  - cosa.repo.doc_lint.counts.allowance@f392e37dc9
  - cosa.repo.doc_lint.counts.table_raises@e9385c96df
  - cosa.repo.doc_lint.counts.check_table@de0a9598dd
  - cosa.repo.doc_lint.counts.main@7157b4fc88
---
# Doc-lint count table

The table of unwaived docstring findings per file for the tracked Python files outside the swept scope. The [[doc-lint-gate]] refuses a commit that raises a count above its entry.

## Counting
- `file_count` counts the findings in one file that no waiver covers and returns a `FileCount`. A file that does not parse counts as one finding. `unreadable_count` does the same for bytes that are not UTF-8.
- `counted_paths` lists the tracked `.py` files that `is_swept` rejects, read from git. `census` counts them all and returns the counts with the number of files walked.

## The table file
- `table_text` renders one entry per line sorted by path, so two edits to different files merge without a conflict. `parse_table` reads it back and raises `TableError` when it is malformed or too deeply nested.
- A file at zero has no entry. `allowance` returns the entry of a path, or of the path it was renamed from, else zero.
- `rules_stamp` hashes the files that decide what a finding is. `rule_files` lists them from git, so a new file in the package is covered at once.
- `differing_rule_files` lists rule files whose working copy is not the staged one.

## Checking
- `table_raises` lists staged entries above the committed ones. `check_table` compares a table with a census in both directions, and needs the current stamp.
- `main` takes `--write` and `--check`. It exits 0 when the table is exact and 1 when a count differs. A run that could not read the table or measure the tree exits 2, so it never reads as clean.
