---
capability: repo-tools-git-loc-delta-outputs
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.git_loc_delta.csv_writer.write_csv@d80368d812
  - cosa.repo.git_loc_delta.csv_writer.write_sidecar@3f94f7e914
  - cosa.repo.git_loc_delta.report_formatter.format_console@a047db31ad
  - cosa.repo.git_loc_delta.report_formatter.format_json@052bb8f0e3
  - cosa.repo.git_loc_delta.report_formatter.print_console_banner@67ff48b31f
  - cosa.repo.git_loc_delta.plotter.plot_summary@4352cdf671
---
# Daily LoC delta: console, JSON, CSV and plot output

The second half of `git_loc_delta` (see [[repo-tools-git-loc-delta-read-and-bucket]]). Each function takes the `daily`, `summary` and `by_type` dicts that `DailyAggregator` produces. None of them reads git.

## Console and JSON
- `format_console( daily, summary, since, until, branch, rev_range )` returns a string with two tables. The first is daily totals with a closing total row; the second is date by file type. An empty `daily` gives the banner and "No commits in range."
- `format_json( daily, summary, since, until, branch, rev_range, repo_path )` returns indented JSON with `since`, `until`, `branch`, `rev_range`, `repo_path`, `summary` and `days` (date ascending).
- `print_console_banner( title )` prints a banner through `cosa.utils.util.print_banner`. Nothing in the CLI calls it; it is for callers that want the banner printed directly.

## CSV
- `write_csv( by_type, path, repo, branch=None )` writes the tidy-long schema v2: columns `date`, `repo`, `branch`, `file_type`, `added`, `deleted`, `files_touched`, `commits`. It creates the parent folder, sorts by date then added (largest first), and returns the row count. An empty input gives a header-only file.
- `write_sidecar( csv_path, repo, branch, rev_range, since, until )` writes `<csv>.meta.json` with `csv_schema_version`, those fields and a UTC `generated_at`, and returns its path. Missing values are written as null.

## Plot
- `plot_summary( daily, summary, output_path, group_by="file_type", title_meta=None )` writes a two-panel PNG. The top panel has aggregate insertions, deletions and a net line; the bottom has one signed net line per group. `group_by` is `file_type` or `repo`.
- It raises `ValueError` for any other `group_by` or for fewer than two dates, and `KeyError` when a day lacks the `by_<group_by>` list. It creates the parent folder, returns the absolute path and closes the figure.
