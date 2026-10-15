---
capability: repo-tools-git-loc-delta-read-and-bucket
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.git_loc_delta.git_log_parser.GitLogParser@d8001ceab3
  - cosa.repo.git_loc_delta.daily_aggregator.DailyAggregator@9bbb6d0691
  - cosa.repo.git_loc_delta.date_bounds.normalize_since@045f555788
  - cosa.repo.git_loc_delta.date_bounds.normalize_until@052fc2910e
  - cosa.repo.git_loc_delta.exceptions.GitLocDeltaError@d005b45535
  - cosa.repo.git_loc_delta.exceptions.DateRangeError@c74584a6da
---
# Daily LoC delta: reading git and bucketing by day

The first half of `git_loc_delta` (see [[branch-and-directory-loc-analysis]]). `GitLogLocDeltaAnalyzer` wires these four parts together.

## `GitLogParser`
- `GitLogParser( repo_path=".", since=None, until=None, rev_range=None, all_branches=False, include_merges=False, author=None, timeout=60 )`. `iter_changes()` runs one `git log --numstat` and yields a dict per file row: `date`, `sha`, `author`, `path`, `added`, `deleted`.
- The date is the committer date, because `--since` and `--until` filter on it too. Binary rows (`-` counts) and malformed rows are skipped.
- Without `include_merges` the command carries `--no-merges`. With it, `--diff-merges=first-parent`, which git older than 2.31 rejects. `all_branches` adds `--branches`; `rev_range` is appended last.
- Any git failure, a timeout included, raises `GitCommandError`, which the package re-exports from `branch_analyzer`.

## `DailyAggregator`
- `record( change )` takes one row from the parser and puts it in a (date, file type) bucket. The file type comes from `FileTypeClassifier` under the packaged branch-analyzer config.
- `by_type()` returns `added`, `deleted`, `files_touched` and `commits` per bucket. `daily()` returns the same per date, with a `by_file_type` list sorted by `added`. `summary()` returns `total_added`, `total_deleted`, `total_files`, `total_commits`, `total_days` and `net`. `is_empty()` is true before any record.
- Commit counts are sets of SHAs. Never sum the per-bucket `commits` column: one commit touching two file types sits in both. `all_shas()` returns the set, and the coverage guard checks it against `git rev-list`.

## Date bounds
- `normalize_since( value )` turns a bare `YYYY-MM-DD` into `YYYY-MM-DD 00:00:00`. Git otherwise reads a bare date as that day at the current time, so `--since=<today>` selects nothing. Other values pass through.
- `normalize_until( value )` returns its argument unchanged, because a bare date already ends that day. Both are called at every site so the pair stays symmetric.

## Errors
- `GitLocDeltaError( message, context=None )` is the base.
- `DateRangeError( message, since, until, branch )` means a bad or empty range: `--since` after `--until`, `--branch` on the base itself, or an unknown branch. The CLI reports an empty branch range as "No commits in range." and exits 0.
