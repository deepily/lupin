---
capability: loc-rollup-and-report
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.loc-analysis.loc_rollup.git@f431efae07
  - scripts.loc-analysis.loc_rollup.counted@4755916639
  - scripts.loc-analysis.loc_rollup.commit_delta@c3453e073b
  - scripts.loc-analysis.loc_rollup.main@995d6668e0
  - scripts.loc-analysis.report.agg@2c2769bf3c
  - scripts.loc-analysis.report.table@40fec3b42b
  - scripts.loc-analysis.report.main@59085e322c
---
# Lines-of-code roll-up and report

Two small tools beside the counter. The roll-up measures added and deleted lines over time, and the report formats the counter's rows. The counter is on [[loc-count-classifier]].

## Roll-up
- The roll-up has two views. One is the release chain: the squash-merge commits on `main`, one per release. The other is authoring: monthly adds and deletes across all branches with the squash merges excluded, so feature work is counted once.
- It writes two charts and a CSV of both series under the `io/git-delta-analysis` folder.
- `git` runs a git command in the Lupin repo and returns its stdout with the trailing newline stripped.
- `counted` decides whether a path is hand-authored work. It returns false for generated, vendored or data artifacts.
- `commit_delta` computes the added and deleted lines of one commit, leaving out generated artifacts. A binary row contributes zero.
- `main` runs both views, writes the files and prints the summary tables. It returns the releases and monthly pair, so a caller can assert on the numbers. Importing the module no longer runs anything.

## Report
- `agg` totals the lines, code, comment, docstring, blank and byte counts of a list of rows, and counts the files.
- `table` prints one markdown table for a set of groups, with a total row.
- `main` renders the report for the rows JSON named by the first argument and returns the parsed rows. It prints all tracked files, the buckets, three tiers, each tier by language, tests against application code, the excluded buckets and tier A by directory.
